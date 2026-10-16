import SwiftUI
import Charts

/// The Your Crib tab (owner, 2026-10-15; replaces Events): type your address,
/// see every 311 call on your building in the past year — pests first — and
/// reported crime within half a mile, month by month. Plus: calls older than
/// a year, and an alert for each new call on one building. See Casa.
struct CasaView: View {
    @Environment(AuthService.self) private var auth
    @Environment(DataStore.self) private var store
    @Environment(AppNav.self) private var nav
    @AppStorage("casa.place") private var savedPlace: Data = Data()

    @State private var query = ""
    @State private var suggestions: [Casa.Place] = []
    @State private var place: Casa.Place?
    @State private var calls: [Casa.Call] = []
    @State private var older: [Casa.Call]?
    @State private var loading = false
    @State private var failed = false
    @State private var crime: [Casa.CrimeMonth] = []
    @State private var crimeThrough: Date?
    @State private var crimeFailed = false
    /// When the shown calls/crime came from the phone because NYC's data
    /// couldn't be reached: the time they were saved.
    @State private var offlineSince: Date?
    @State private var showPlus = false
    /// Which sign-in is open, as one value: two flags set together opened
    /// the alerts sheet from "See the full history" (2026-10-15 UI test).
    @State private var signIn: SignInFor?
    enum SignInFor: Identifiable { case alerts, history; var id: Self { self } }
    @State private var olderLoading = false
    @State private var showAllCalls = false
    @FocusState private var typing: Bool
    private var watch: CasaWatch { CasaWatch.shared }

    var body: some View {
        VStack(spacing: 0) {
            NavyHeader {
                VStack(alignment: .leading, spacing: 10) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Your Crib").font(.se(24, .bold)).foregroundStyle(.white)
                        Text("311 calls on your building, and crime nearby").font(.se(15, .semibold)).foregroundStyle(.white.opacity(0.85))
                    }
                    searchField
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.bottom, 12)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    if typing || (place == nil && !suggestions.isEmpty) {
                        suggestionList
                    } else if let place {
                        results(place)
                    } else {
                        intro
                    }
                    Color.clear.frame(height: 120)
                }
                .padding(.top, 12)
            }
            .scrollDismissesKeyboard(.immediately)
            .refreshable { if let p = place, !CommandLine.arguments.contains("--casa-demo") { await open(p) } }
            .background(SE.canvas)
        }
        .background(SE.canvas)
        .task {
            if CommandLine.arguments.contains("--casa-demo") { showDemo(); return }
            if place == nil, let p = try? JSONDecoder().decode(Casa.Place.self, from: savedPlace) { await open(p) }
            await watch.load(token: auth.session?.accessToken)
        }
        .task(id: query) {
            guard typing else { return }
            try? await Task.sleep(for: .milliseconds(250))
            guard !Task.isCancelled else { return }
            suggestions = await Casa.suggest(query)
        }
        .sheet(isPresented: $showPlus) { PaywallView(source: "casa") }
        .sheet(item: $signIn) { EmailSignInView(offersSocialSignIn: true, casaPreview: true, casaHistory: $0 == .history) }
    }

    // MARK: - Search

    private var searchField: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass").foregroundStyle(SE.ink3)
            TextField("Your address, e.g. 350 W 42nd St", text: $query)
                .font(.se(17)).foregroundStyle(SE.ink)
                .textInputAutocapitalization(.words).autocorrectionDisabled()
                .submitLabel(.search)
                .focused($typing)
                .onSubmit { if let first = suggestions.first { Task { await open(first) } } }
                .accessibilityIdentifier("casa-address")
            if !query.isEmpty {
                Button { query = ""; suggestions = [] } label: { Image(systemName: "xmark.circle.fill").foregroundStyle(SE.ink3) }
                    .accessibilityLabel("Clear address")
            }
        }
        .padding(.horizontal, 12).frame(height: 46)
        .background(Color.white).clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private var suggestionList: some View {
        VStack(alignment: .leading, spacing: 0) {
            if query.count >= 3 && suggestions.isEmpty {
                Text("Keep typing your street address in New York City.").font(.se(15)).foregroundStyle(SE.ink3).padding(16)
            }
            ForEach(suggestions) { p in
                Button { Task { await open(p) } } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "mappin.circle.fill").foregroundStyle(SE.royal)
                        Text(p.short).font(.se(17)).foregroundStyle(SE.ink).frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding(.horizontal, 16).padding(.vertical, 12).contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("casa-suggestion")
                Divider().padding(.leading, 16)
            }
        }
        .background(Color.white)
    }

    private var intro: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Does your building have pests?").font(.se(20, .bold)).foregroundStyle(SE.ink)
            Text("Type your address. You'll see every 311 call on your building in the past year — roaches, mice, rats, bed bugs, heat, noise, leaks — and reported crime within half a mile.")
                .font(.se(16)).foregroundStyle(SE.ink2)
            Text("From NYC Open Data: 311 Service Requests and NYPD complaint data.").font(.se(14)).foregroundStyle(SE.ink3)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
    }

    // MARK: - Results

    @ViewBuilder private func results(_ p: Casa.Place) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(p.short).font(.se(20, .bold)).foregroundStyle(SE.ink).accessibilityIdentifier("casa-place")
            if let b = store.byBBL[p.bbl] {
                Button { nav.casaPath.append(.building(b.bbl)) } label: {
                    Label("Rent stabilized · open the building page", systemImage: "building.2").font(.se(15, .semibold)).foregroundStyle(SE.royal)
                }
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)

        if let since = offlineSince {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "wifi.slash").foregroundStyle(SE.ink3)
                Text("Offline. Showing what you saw \(since.formatted(.relative(presentation: .named))). Pull down to refresh.")
                    .font(.se(14)).foregroundStyle(SE.ink3)
            }
            .padding(.horizontal, 16).padding(.vertical, 10).frame(maxWidth: .infinity, alignment: .leading)
            .accessibilityIdentifier("casa-offline")
        }
        if loading {
            // Only the 311 part waits; the alert and crime cards don't (owner,
            // 2026-10-15: "this screen takes too long to load").
            HStack(spacing: 10) {
                ProgressView().tint(SE.royal)
                Text("Loading 311 calls from NYC…").font(.se(15)).foregroundStyle(SE.ink3)
            }
            .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
            .accessibilityIdentifier("casa-loading")
            alertCard(p)
            crimeCard
        } else if failed {
            note("Couldn't load 311 calls", "NYC's data service didn't answer. Check your connection and try again.")
            Button { Task { await open(p) } } label: {
                Text("Try again").font(.se(16, .semibold)).foregroundStyle(.white)
                    .padding(.vertical, 12).frame(maxWidth: .infinity).background(SE.royal, in: RoundedRectangle(cornerRadius: 12))
            }
            .accessibilityIdentifier("casa-retry").padding(.horizontal, 16)
        } else {
            pestCard
            alertCard(p)
            crimeCard
            callsCard
            olderCard
        }
    }

    private var pests: [Casa.Call] { calls.filter(\.isPest) }

    private var pestCard: some View {
        let n = pests.count
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: n == 0 ? "checkmark.seal.fill" : "ant.fill")
                    .font(.system(size: 26)).foregroundStyle(n == 0 ? SE.good : SE.bad)
                VStack(alignment: .leading, spacing: 2) {
                    Text(n == 0 ? "No pest calls in the past year" : "\(n) pest call\(n == 1 ? "" : "s") in the past year")
                        .font(.se(19, .bold)).foregroundStyle(SE.ink)
                    Text("\(calls.count) 311 call\(calls.count == 1 ? "" : "s") on this building in all").font(.se(15)).foregroundStyle(SE.ink3)
                }
            }
            if n > 0 {
                ForEach(Self.pestKinds(pests)) { k in
                    Text("\(k.count) × \(k.title)").font(.se(15)).foregroundStyle(SE.ink2)
                }
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("casa-pests")
    }

    /// Pest calls by what was reported: "Pests", "Rat sighting", "Mouse sighting"…
    static func pestKinds(_ pests: [Casa.Call]) -> [Casa.Tally] {
        var counts: [String: Int] = [:]
        for c in pests { counts[c.detail ?? c.title, default: 0] += 1 }
        return counts.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }
            .map { Casa.Tally(title: $0.key, count: $0.value) }
    }

    @ViewBuilder private func alertCard(_ p: Casa.Place) -> some View {
        let watching = watch.watch?.bbl == p.bbl
        VStack(alignment: .leading, spacing: 8) {
            Text("Alerts on new 311 calls").font(.se(17, .bold)).foregroundStyle(SE.ink)
            if watching {
                Text("Each morning at 8 you'll get a notification and an email if the City published new 311 calls on this building.")
                    .font(.se(15)).foregroundStyle(SE.ink2)
                crimeChips(p)
                Button(role: .destructive) {
                    Task { if let t = auth.session?.accessToken { await watch.stop(token: t) } }
                } label: { Text("Stop alerts").font(.se(16, .semibold)) }
                    .disabled(watch.busy).accessibilityIdentifier("casa-stop")
            } else {
                Text(watch.watch.map { "Plus watches one building. Switching moves your alerts from \($0.address ?? "your other building") to here." }
                     ?? "Hear about every new 311 call on this building — pests, heat, leaks, noise. Part of Find A Crib Plus.")
                    .font(.se(15)).foregroundStyle(SE.ink2)
                SEPrimaryButton(title: watch.watch == nil ? "Alert me about new calls" : "Watch this building instead", icon: "bell.fill") {
                    guard let token = auth.session?.accessToken else { signIn = .alerts; return }
                    guard auth.hasPlus else { Analytics.shared.track("casa_plus_gate", ["what": "alerts"]); showPlus = true; return }
                    Task {
                        await watch.start(p, crimeKinds: watch.watch?.crime_kinds ?? [], token: token)
                        _ = await PushService.shared.requestAfterAlerts()
                    }
                }
                .disabled(watch.busy)
                .accessibilityIdentifier("casa-alert")
            }
            if let e = watch.error { Text(e).font(.se(14)).foregroundStyle(SE.bad) }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
    }

    /// Crime alerts (owner, 2026-10-15): pick the kinds; the server tells you
    /// when the NYPD's next quarterly release has them within half a mile.
    private func crimeChips(_ p: Casa.Place) -> some View {
        let on = Set(watch.watch?.crime_kinds ?? [])
        return VStack(alignment: .leading, spacing: 8) {
            Text("Crime alerts within half a mile").font(.se(16, .bold)).foregroundStyle(SE.ink).padding(.top, 6)
            Text("Pick what you want to hear about. The NYPD publishes every three months, so these come when each new release is out.")
                .font(.se(14)).foregroundStyle(SE.ink3)
            FlowChips(items: CasaWatch.crimeKinds.map { ($0.key, $0.label) }, selected: on) { key in
                guard let token = auth.session?.accessToken else { return }
                var next = on
                if next.contains(key) { next.remove(key) } else { next.insert(key) }
                Analytics.shared.track("casa_crime_kind", ["kind": key, "on": next.contains(key)])
                Task { await watch.start(p, crimeKinds: CasaWatch.crimeKinds.map(\.key).filter(next.contains), token: token) }
            }
            .disabled(watch.busy)
        }
    }

    private var callsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("311 calls, past 12 months").font(.se(17, .bold)).foregroundStyle(SE.ink)
            if calls.isEmpty {
                Text("No 311 calls on this building in the past year.").font(.se(15)).foregroundStyle(SE.ink3)
            } else {
                Text(Casa.tally(calls).prefix(4).map { "\($0.title) \($0.count)" }.joined(separator: " · "))
                    .font(.se(15, .semibold)).foregroundStyle(SE.ink2)
                // Ten, then the rest on a tap: a busy building has 50+ calls.
                ForEach(calls.prefix(showAllCalls ? calls.count : 10)) { callRow($0) }
                if calls.count > 10 && !showAllCalls {
                    Button("Show all \(calls.count) calls") { showAllCalls = true }
                        .font(.se(16, .semibold)).foregroundStyle(SE.royal).accessibilityIdentifier("casa-calls-more")
                }
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
    }

    private func callRow(_ c: Casa.Call) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Circle().fill(c.isPest ? SE.bad : SE.line).frame(width: 9, height: 9).padding(.top, 7)
            VStack(alignment: .leading, spacing: 2) {
                Text(c.detail.map { "\(c.title) — \($0)" } ?? c.title).font(.se(16, .semibold)).foregroundStyle(SE.ink)
                Text("\(Self.dayText(c.day)) · \(c.isOpen ? "Open" : "Closed")").font(.se(14)).foregroundStyle(SE.ink3)
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("casa-call")
    }

    private var crimeCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Reported crime within half a mile").font(.se(17, .bold)).foregroundStyle(SE.ink)
            if crimeFailed {
                Text("Couldn't load NYPD data right now.").font(.se(15)).foregroundStyle(SE.ink3)
            } else if crime.isEmpty {
                ProgressView().tint(SE.royal).frame(maxWidth: .infinity).padding(.vertical, 20)
            } else {
                Chart {
                    ForEach(crime) { m in
                        LineMark(x: .value("Month", m.month, unit: .month), y: .value("Reports", m.total))
                            .foregroundStyle(by: .value("Kind", "All crime"))
                            .symbol(by: .value("Kind", "All crime"))
                        LineMark(x: .value("Month", m.month, unit: .month), y: .value("Reports", m.felonies))
                            .foregroundStyle(by: .value("Kind", "Felonies"))
                            .symbol(by: .value("Kind", "Felonies"))
                    }
                }
                .chartForegroundStyleScale(["All crime": SE.royal, "Felonies": SE.bad])
                .chartXAxis { AxisMarks(values: .stride(by: .month)) { _ in AxisGridLine(); AxisValueLabel(format: .dateTime.month(.abbreviated)) } }
                .frame(height: 200)
                .accessibilityIdentifier("casa-crime-chart")
                if let through = crimeThrough {
                    Text("NYPD complaint reports, \(Self.monthRange(crime)). The NYPD publishes these every three months; the newest are through \(through.formatted(.dateTime.month(.wide).day().year())). Locations are rounded to the block.")
                        .font(.se(14)).foregroundStyle(SE.ink3)
                }
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
    }

    @ViewBuilder private var olderCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Older than a year").font(.se(17, .bold)).foregroundStyle(SE.ink)
            if let older {
                if older.isEmpty {
                    Text("No 311 calls on file before the past year.").font(.se(15)).foregroundStyle(SE.ink3)
                } else {
                    Text(Casa.tally(older).prefix(4).map { "\($0.title) \($0.count)" }.joined(separator: " · "))
                        .font(.se(15, .semibold)).foregroundStyle(SE.ink2)
                    ForEach(older.prefix(100)) { callRow($0) }
                    if older.count >= Casa.listLimit { Text("Showing the newest \(Casa.listLimit).").font(.se(14)).foregroundStyle(SE.ink3) }
                }
            } else if olderLoading {
                ProgressView().tint(SE.royal).frame(maxWidth: .infinity)
            } else {
                Text("Every 311 call on this building back to 2010. Part of Find A Crib Plus.").font(.se(15)).foregroundStyle(SE.ink2)
                Button {
                    guard auth.isSignedIn else { signIn = .history; return }
                    guard auth.hasPlus else { Analytics.shared.track("casa_plus_gate", ["what": "history"]); showPlus = true; return }
                    Task { await loadOlder() }
                } label: {
                    Label("See the full history", systemImage: auth.hasPlus ? "clock.arrow.circlepath" : "lock.fill").font(.se(16, .semibold)).foregroundStyle(SE.royal)
                }
                .accessibilityIdentifier("casa-history")
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
    }

    private func note(_ title: String, _ body: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.se(17, .bold)).foregroundStyle(SE.ink)
            Text(body).font(.se(15)).foregroundStyle(SE.ink3)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
    }

    // MARK: - Loading

    private var yearAgo: Date { Calendar.current.date(byAdding: .year, value: -1, to: Date())! }

    private func open(_ p: Casa.Place) async {
        typing = false
        query = ""
        suggestions = []
        place = p
        older = nil
        showAllCalls = false
        crime = []; crimeThrough = nil; crimeFailed = false; offlineSince = nil
        savedPlace = (try? JSONEncoder().encode(p)) ?? Data()
        Analytics.shared.track("casa_lookup", ["bbl": p.bbl])
        failed = false
        // What this phone saw last time shows at once; the fresh lookup
        // replaces it, and a failed one leaves it up, marked offline.
        let saved = Casa.Saved.get(p.bbl)
        if let c = saved?.calls { calls = c } else { calls = [] }
        if let m = saved?.crime, !m.isEmpty { crime = m; crimeThrough = saved?.crimeThrough }
        loading = saved?.calls == nil
        // The NYPD chart loads alongside the 311 calls and shows as soon as
        // it's in, whichever finishes first. A reply for a building the person
        // has since left is dropped.
        async let crimeDone: Void = loadCrime(p)
        do {
            let c = try await Casa.calls(bbl: p.bbl, since: yearAgo, before: nil)
            if place?.bbl == p.bbl { calls = c }
            Casa.Saved.put(Casa.Snapshot(bbl: p.bbl, calls: c, savedAt: Date()))
        } catch {
            if place?.bbl == p.bbl {
                if let s = saved, s.calls != nil { offlineSince = s.savedAt } else { failed = true; calls = [] }
            }
        }
        if place?.bbl == p.bbl { loading = false }
        await crimeDone
    }

    private func loadCrime(_ p: Casa.Place) async {
        do {
            let r = try await Casa.crime(lat: p.lat, lng: p.lng)
            Casa.Saved.put(Casa.Snapshot(bbl: p.bbl, crime: r.months, crimeThrough: r.through, savedAt: Date()))
            guard place?.bbl == p.bbl else { return }
            crime = r.months; crimeThrough = r.through
        } catch {
            // NYPD data changes once a quarter, so a saved chart stays up quietly.
            if place?.bbl == p.bbl, crime.isEmpty { crimeFailed = true }
        }
    }

    private func loadOlder() async {
        guard let p = place else { return }
        olderLoading = true; defer { olderLoading = false }
        older = (try? await Casa.calls(bbl: p.bbl, since: nil, before: yearAgo)) ?? []
        Analytics.shared.track("casa_history", ["bbl": p.bbl, "n": older?.count ?? 0])
    }

    /// `--casa-demo` (UI tests, screenshots): a sample building with no network.
    private func showDemo() {
        place = Casa.Place(label: "350 W 42ND STREET, New York, NY, USA", bbl: "1010330001", lat: 40.7585, lng: -73.9925)
        func c(_ k: String, _ t: String, _ d: String, _ s: String) -> Casa.Call {
            Casa.Call(unique_key: k, created_date: "\(d)T10:00:00.000", complaint_type: t, descriptor: nil, status: s, agency: nil)
        }
        calls = [c("1", "UNSANITARY CONDITION PESTS", "2026-10-02", "Open"), c("2", "Rodent", "2026-08-14", "Closed"),
                 c("3", "HEAT/HOT WATER", "2026-02-03", "Closed"), c("4", "Noise - Residential", "2025-12-20", "Closed")]
        let newest = Casa.parseMonth("2026-06-30")!
        crime = zip(Casa.lastSixMonths(endingWith: newest), [212, 198, 230, 241, 225, 219]).map {
            Casa.CrimeMonth(month: $0.0, felonies: $0.1 / 3, total: $0.1)
        }
        crimeThrough = ISO8601DateFormatter.socrata.date(from: "2026-06-30T00:00:00")
    }

    static func dayText(_ day: String) -> String {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"
        guard let d = f.date(from: day) else { return day }
        return d.formatted(.dateTime.month(.abbreviated).day().year())
    }

    static func monthRange(_ months: [Casa.CrimeMonth]) -> String {
        guard let a = months.first?.month, let b = months.last?.month else { return "" }
        return "\(a.formatted(.dateTime.month(.abbreviated).year())) – \(b.formatted(.dateTime.month(.abbreviated).year()))"
    }
}

/// Toggle chips that wrap onto as many lines as they need.
struct FlowChips: View {
    let items: [(key: String, label: String)]
    let selected: Set<String>
    let toggle: (String) -> Void
    var body: some View {
        ChipFlow(spacing: 8) {
            ForEach(items, id: \.key) { item in
                let on = selected.contains(item.key)
                Button { toggle(item.key) } label: {
                    HStack(spacing: 4) {
                        if on { Image(systemName: "checkmark").font(.system(size: 12, weight: .bold)) }
                        Text(item.label).font(.se(15, .semibold))
                    }
                    .padding(.horizontal, 12).frame(height: 34)
                    .foregroundStyle(on ? .white : SE.ink)
                    .background(on ? SE.royal : SE.badge)
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("casa-crime-\(item.key)")
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
    }
}

/// A left-to-right layout that wraps to the next line when a row is full.
struct ChipFlow: Layout {
    var spacing: CGFloat = 8
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, row: CGFloat = 0, widest: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > 0 && x + size.width > width { y += row + spacing; x = 0; row = 0 }
            x += size.width + spacing; row = max(row, size.height); widest = max(widest, x - spacing)
        }
        return CGSize(width: proposal.width ?? widest, height: y + row)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, row: CGFloat = 0
        for s in subviews {
            let size = s.sizeThatFits(.unspecified)
            if x > bounds.minX && x + size.width > bounds.maxX { y += row + spacing; x = bounds.minX; row = 0 }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing; row = max(row, size.height)
        }
    }
}
