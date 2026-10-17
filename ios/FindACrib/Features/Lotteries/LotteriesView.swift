import SwiftUI

/// The Lotteries tab: Housing Connect lotteries, soonest deadline first, and
/// the HPD marketing agents' re-rentals — for EVERYONE (owner, 2026-09-30;
/// it used to be a sign-up wall). A subscriber sees their alert boroughs,
/// everyone else all five, with a banner to turn on alerts (an account, no
/// Plus — alerts left Plus on 2026-10-01).
/// The NJ pane (owner, 2026-09-24) lists the New Jersey towns holding
/// affordable-housing drawings, from Affordable Homes New Jersey (CGP&H).
/// See LotteryFeed.
struct LotteriesView: View {
    @Environment(\.openURL) private var openURL
    @Environment(DataStore.self) private var store
    @Environment(AuthService.self) private var auth
    @Environment(\.horizontalSizeClass) private var sizeClass
    /// iPad (owner, 2026-09-22): two columns of lottery and re-rental cards.
    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 12, alignment: .top), count: sizeClass == .regular ? 2 : 1)
    }
    /// One sheet, three uses. Separate .sheet modifiers stacked on one view
    /// left only the last (sign-in) working: Edit boroughs and Filter did
    /// nothing when tapped (found 2026-10-17 by the Filter UI test).
    enum Sheet: Identifiable { case alerts, beds, signIn; var id: Self { self } }
    @State private var sheet: Sheet?
    /// The sheet that just closed, for what happens after (onDismiss gets no argument).
    @State private var lastSheet: Sheet?
    /// The real-time-alerts offer, hidden for good once dismissed (2026-10-06).
    @AppStorage("fac.rtDismissed") private var rtDismissed = false
    init() {
        // UI tests start from a clean slate for the real-time offer.
        if CommandLine.arguments.contains("--reset-rt-dismissed") { UserDefaults.standard.removeObject(forKey: "fac.rtDismissed") }
    }
    @State private var showRealtimePlus = false
    enum Pane: Hashable { case lotteries, rerentals, newJersey }
    @State private var pane: Pane = .lotteries
    /// Bedrooms they need, kept across launches: "0,1" = studio or 1-bed.
    /// Empty = any size.
    @AppStorage("lotteries.beds") private var bedsRaw = ""
    private var beds: Set<Int> { Set(bedsRaw.split(separator: ",").compactMap { Int($0) }) }
    private var bedLotteries: [LotteryFeed.Lottery] { feed.mine.filter { LotteryFeed.bedsMatch($0.beds, want: beds) } }
    private func lotteryOut(_ l: LotteryFeed.Lottery) -> Bool {
        guard let v = Qualify.shared.verdict(incomeMin: l.income_min, incomeMax: l.income_max,
                                             householdMin: l.household_min, householdMax: l.household_max) else { return false }
        return v == .high || v == .low
    }
    /// Outside the income range on file: left out, with no "show them" row
    /// since 2026-10-17 (owner); the count line still says "5 of 8 open".
    private var lotteries: [LotteryFeed.Lottery] { bedLotteries.filter { !lotteryOut($0) } }
    private var feed: LotteryFeed { LotteryFeed.shared }

    var body: some View {
        // Outside New York: the place's own openings, no sign-up (2026-09-24).
        if !store.city.isNYC { OpeningsView() } else {
            nycBody.userActivity(ActivityType.lotteries) { a in
                a.title = String(localized: "NYC housing lotteries")
                a.webpageURL = DeepLink.lotteries.webURL
                a.isEligibleForHandoff = true
            }
        }
    }

    private var nycBody: some View {
        Group {
            // Wait for the subscription answer so a subscriber never sees all
            // five boroughs flash before their own.
            if feed.checked { list } else { checking }
        }
        .task { await Qualify.shared.loadUnits() }
        .sheet(item: $sheet, onDismiss: {
            switch lastSheet {
            case .alerts: Task { await feed.refresh() }
            // Signed out: sign in first, then straight on to the alerts sheet —
            // unless the account they signed into already has alerts.
            case .signIn:
                guard auth.isSignedIn else { return }
                Task { await feed.refresh(); if !feed.subscribed { sheet = .alerts } }
            default: break
            }
        }) { which in
            switch which {
            case .alerts: AlertsSheet(showsBeds: true).onAppear { lastSheet = .alerts }
            case .beds: LotteryBedsSheet().presentationDetents([.height(260)]).onAppear { lastSheet = .beds }
            // Apple and Google first, no keyboard until they pick email (owner, 2026-09-19).
            case .signIn: EmailSignInView(offersSocialSignIn: true, forAlerts: true).onAppear { lastSheet = .signIn }
            }
        }
        // No sheet opens by itself (owner, 2026-09-19): the tab shows the
        // sign-up screen, and only its button opens the sign-up.
    }

    private func promptSignup() {
        Analytics.shared.track("lotteries_signup_prompt", ["signed_in": auth.isSignedIn])
        sheet = auth.isSignedIn ? .alerts : .signIn
    }

    private var checking: some View {
        VStack(spacing: 0) {
            NavyHeader {
                Text("Lotteries").font(.se(24, .bold)).foregroundStyle(.white)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.bottom, 12)
            }
            ProgressView().tint(SE.royal).frame(maxWidth: .infinity, maxHeight: .infinity)
                .accessibilityIdentifier("lotteries-checking")
        }
        .background(SE.canvas)
        .task {
            // Retried until the answer is in (the session restore finishing
            // after this tab opened, or a dropped connection), backing off
            // 1, 2, 4… 30 s: /api/alerts/prefs allows 60 reads an hour.
            var wait = 1.0
            while !feed.checked, !Task.isCancelled {
                await feed.refresh()
                if feed.checked { break }
                try? await Task.sleep(for: .seconds(wait))
                wait = min(wait * 2, 30)
            }
        }
    }

    /// Not subscribed: a banner above the list instead of a wall; it only has
    /// to say what alerts are. (The "what you qualify for" row is gone, owner
    /// 2026-10-08: income + household are set under Edit boroughs.)
    @ViewBuilder private var alertsBanner: some View {
        if feed.statusUnknown {
            // Couldn't tell (429, offline): no box beats a wrong one.
            EmptyView()
        } else if feed.subscribed && auth.hasPlus {
            // A paying member with alerts on: nothing here (owner, 2026-10-13).
            // Edit boroughs is in the header; Turn off lives in Profile.
            EmptyView()
        } else if feed.subscribed && !auth.hasPlus && !rtDismissed {
            // Subscribed without Plus: alerts come at 8 AM — offer real-time.
            RealtimeUpsell(source: "lotteries", onDismiss: { rtDismissed = true }) { showRealtimePlus = true }
                .padding(.horizontal, 16)
                .sheet(isPresented: $showRealtimePlus) { PaywallView(source: "realtime") }
        } else if !feed.subscribed {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 10) {
                    Image(systemName: "bell.fill").font(.system(size: 18, weight: .bold)).foregroundStyle(SE.royal)
                    Text("Get alerts when a new one opens").font(.se(18, .bold)).foregroundStyle(SE.ink)
                }
                Text(auth.hasPlus
                     ? String(localized: "New lotteries and re-rentals in your boroughs, by in-app notification and email the minute they open.")
                     : String(localized: "New lotteries and re-rentals in your boroughs, by in-app notifications and emails at 8 AM daily. Upgrade to Plus for instant notifications and emails."))
                    .font(.se(15)).foregroundStyle(SE.ink2)
                SEPrimaryButton(title: String(localized: "Turn on alerts"), icon: "bell.fill", fill: SE.navy) { promptSignup() }
                    .accessibilityIdentifier("lotteries-signup")
            }
            .padding(14).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
            .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line))
            .padding(.horizontal, 16)
            .accessibilityElement(children: .contain).accessibilityIdentifier("lotteries-alerts-banner")
        }
    }

    /// Filter (owner, 2026-10-17: Beds moved off the tab, "Edit boroughs"
    /// renamed): a subscriber gets the alerts sheet with Beds on top, everyone
    /// else just Beds, no sign-in needed to narrow the list.
    private var filterButton: some View {
        Button(beds.isEmpty ? String(localized: "Filter") : String(localized: "Filter (\(beds.count))")) {
            Analytics.shared.track("lotteries_filter", ["subscribed": feed.subscribed])
            sheet = feed.subscribed ? .alerts : .beds
        }
        .font(.se(16, .bold)).foregroundStyle(SE.royal)
        .buttonStyle(.plain)
    }

    private var list: some View {
        VStack(spacing: 0) {
            NavyHeader {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Lotteries").font(.se(24, .bold)).foregroundStyle(.white)
                    Text(boroughLine).font(.se(15, .semibold)).foregroundStyle(.white.opacity(0.85))
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.bottom, 12)
            }
            VStack(alignment: .leading, spacing: 10) {
                // Three panes: "Lotteries (n)" no longer fits beside the other
                // two on a 375 pt phone, and the header already says Lotteries.
                SEUnderlineTabs(options: [(Pane.lotteries, String(localized: "NYC (\(lotteries.count))")), (.rerentals, String(localized: "Re-rentals (\(rerentals.count))")),
                                          (.newJersey, String(localized: "NJ (\(feed.njOpen.count))"))], selection: $pane)
                    .padding(.bottom, 10)
            }
            .padding(.horizontal, 16).padding(.top, 8).background(Color.white)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if pane != .newJersey { alertsBanner }
                    if pane == .newJersey { njList } else if pane == .rerentals { rerentalList } else {
                    HStack {
                        Text(countLine).font(.se(17, .bold)).foregroundStyle(SE.ink)
                        Spacer()
                        filterButton.accessibilityIdentifier("lotteries-edit")
                    }
                    .padding(.horizontal, 16)
                    if feed.loadFailed {
                        message(String(localized: "Couldn't load lotteries"), String(localized: "Check your connection and pull down to try again."))
                    } else if feed.mine.isEmpty && !feed.loading {
                        message(String(localized: "Nothing open right now"),
                                String(localized: "No Housing Connect lotteries are open in \(boroughNames) right now.") + (feed.subscribed ? String(localized: " We'll alert you when one opens.") : ""))
                    } else if lotteries.isEmpty && !bedLotteries.isEmpty && !feed.loading {
                        message(String(localized: "None in your income range"),
                                (beds.isEmpty ? String(localized: "\(bedLotteries.count) open, all outside the income range you entered. Change it under Filter.")
                                              : String(localized: "\(bedLotteries.count) open with \(bedsWords), all outside the income range you entered. Change it under Filter.")))
                    } else if lotteries.isEmpty && !feed.loading {
                        message(String(localized: "None with \(bedsWords)"),
                                String(localized: "\(feed.mine.count) open in \(boroughNames), none with \(bedsWords). Change Beds above to see them."))
                    }
                    LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
                        ForEach(lotteries) { card($0) }
                    }
                    .padding(.horizontal, sizeClass == .regular ? 16 : 0)
                    Text("From NYC Housing Connect, updated every 10 minutes. Eligibility also depends on household size — check each listing.")
                        .font(.se(14)).foregroundStyle(SE.ink3).padding(.horizontal, 16).padding(.top, 4)
                    }
                    Color.clear.frame(height: 120)
                }
                .padding(.top, 16)
            }
            .refreshable { await feed.refresh() }
            .background(SE.canvas)
        }
        .background(SE.canvas)
        .task { Analytics.shared.track("lotteries_view", ["open": feed.mine.count]) }
    }

    /// Re-rentals in their boroughs, from the same featured.json the search
    /// feed's tiles use (refreshed with the rest of the app's data).
    private var inBoroughs: [FeaturedListing] {
        let codes = Set(feed.viewBoroughs)
        return store.featured.listings.filter { $0.boroughCode.map(codes.contains) ?? false }
    }

    /// Sizes come from the feed and from each listing's own unit table (the
    /// flyer reader). With Beds set, a listing shows only if one of its
    /// sizes matches; one that states no size waits behind a button.
    private var bedRerentals: [FeaturedListing] {
        guard !beds.isEmpty else { return inBoroughs }
        return inBoroughs.filter {
            let have = Qualify.shared.bedrooms($0)
            // One that states no size is left out (owner, 2026-10-04: 1 bed
            // means only 1-beds); its "show them" row went 2026-10-17.
            return !have.isEmpty && !have.isDisjoint(with: beds)
        }
    }
    private var rerentals: [FeaturedListing] {
        bedRerentals.filter { !Qualify.shared.outOfRange($0) }
    }

    /// "a 1-bed", "a studio or 1-bed", "3+ beds" — for the empty message.
    private var bedsWords: String {
        let names = beds.sorted().map { $0 == 0 ? String(localized: "studio") : $0 == 4 ? String(localized: "4+ bed") : "\($0)-bed" }
        return names.isEmpty ? String(localized: "any size") : "a " + ListFormatter.localizedString(byJoining: names).replacingOccurrences(of: " and ", with: " or ")
    }

    @ViewBuilder private var rerentalList: some View {
        HStack {
            Text("\(rerentals.count) available").font(.se(17, .bold)).foregroundStyle(SE.ink)
            Spacer()
            filterButton.accessibilityIdentifier("rerentals-filter")
        }
        .padding(.horizontal, 16)
        if rerentals.isEmpty && !bedRerentals.isEmpty {
            message(String(localized: "None in your income range"), String(localized: "\(bedRerentals.count) re-rentals here, all outside the income range you entered. Change it under Filter."))
        } else if rerentals.isEmpty && !beds.isEmpty {
            message(String(localized: "None with \(bedsWords)"), String(localized: "No re-rental in \(boroughNames) lists \(bedsWords) today. Change Beds above to see them."))
        } else if rerentals.isEmpty {
            message(String(localized: "No re-rentals right now"),
                    String(localized: "No HPD marketing agent is advertising a re-rental in \(boroughNames) today.") + (feed.subscribed ? String(localized: " We'll alert you when one is posted.") : ""))
        }
        // slot -1 marks this tab in the re-rental funnel, apart from the
        // search feed's slots 0, 1, 2…
        LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
            ForEach(rerentals) { RerentalCard(listing: $0, slot: -1) }
        }
        .padding(.horizontal, 16)
        Text("Income-restricted apartments that HPD-approved marketing agents are re-renting, from their own websites. Apply through the agent. Bedroom sizes come from each listing's own unit table.")
            .font(.se(14)).foregroundStyle(SE.ink3).padding(.horizontal, 16).padding(.top, 4)
    }

    // MARK: - New Jersey

    /// County and Rentals/For sale filters (owner, 2026-09-25: "allow
    /// filtering for nj counties"). The county is remembered across launches;
    /// "" = every county.
    @AppStorage("nj.county") private var njCounty = ""
    @State private var njTenure: String? = nil
    private var njShown: [LotteryFeed.NJLottery] {
        LotteryFeed.njNarrow(feed.njOpen, county: njCounty.isEmpty ? nil : njCounty, tenure: njTenure)
    }
    private var njFiltering: Bool { !njCounty.isEmpty || njTenure != nil }
    private var njRentals: [LotteryFeed.NJLottery] { njShown.filter(\.isRental) }
    private var njSales: [LotteryFeed.NJLottery] { njShown.filter { !$0.isRental } }

    private var njFilterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                Menu {
                    Button("All counties") { njCounty = "" }
                    ForEach(LotteryFeed.njCounties(feed.njOpen), id: \.0) { c in
                        Button("\(c.0) County (\(c.1))") {
                            njCounty = c.0
                            Analytics.shared.track("nj_filter", ["county": c.0])
                        }
                    }
                } label: {
                    njChip(njCounty.isEmpty ? String(localized: "County") : String(localized: "\(njCounty) County"), on: !njCounty.isEmpty, chevron: true)
                }
                .accessibilityIdentifier("nj-county")
                ForEach([("rent", String(localized: "Rentals")), ("buy", String(localized: "For sale"))], id: \.0) { t in
                    Button {
                        njTenure = njTenure == t.0 ? nil : t.0
                        Analytics.shared.track("nj_filter", ["tenure": njTenure ?? "any"])
                    } label: { njChip(t.1, on: njTenure == t.0, chevron: false) }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("nj-tenure-\(t.0)")
                        .accessibilityAddTraits(njTenure == t.0 ? .isSelected : [])
                }
            }
        }
    }

    private func njChip(_ title: String, on: Bool, chevron: Bool) -> some View {
        HStack(spacing: 5) {
            Text(title).font(.se(15, .semibold)).lineLimit(1)
            if chevron { Image(systemName: "chevron.down").font(.system(size: 11, weight: .bold)) }
        }
        .foregroundStyle(on ? .white : SE.ink)
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(on ? SE.royal : Color.white)
        .overlay(Capsule().stroke(on ? SE.royal : SE.lineSoft, lineWidth: 1))
        .clipShape(Capsule())
    }

    @ViewBuilder private var njList: some View {
        njFilterBar.padding(.horizontal, 16)
        HStack {
            Text(feed.loading && feed.nj.isEmpty ? String(localized: "Loading…")
                 : njFiltering ? String(localized: "\(njShown.count) of \(feed.njOpen.count) open in New Jersey") : String(localized: "\(feed.njOpen.count) open in New Jersey"))
                .font(.se(17, .bold)).foregroundStyle(SE.ink)
                .accessibilityIdentifier("nj-count")
            Spacer()
            if njFiltering {
                Button("Clear") { njCounty = ""; njTenure = nil }
                    .font(.se(16, .bold)).foregroundStyle(SE.royal)
                    .accessibilityIdentifier("nj-clear")
            }
        }
        .padding(.horizontal, 16)
        if feed.njOpen.isEmpty && !feed.loading {
            message(String(localized: "No New Jersey drawings right now"),
                    String(localized: "Affordable Homes New Jersey isn't listing an open drawing today. Pull down to check again."))
        } else if njShown.isEmpty && !feed.loading {
            message(njCounty.isEmpty ? String(localized: "None in this selection") : String(localized: "None in \(njCounty) County"),
                    String(localized: "\(feed.njOpen.count) drawings are open elsewhere in New Jersey. Pick another county or tap Clear."))
        }
        if !njRentals.isEmpty {
            njSection(String(localized: "Rentals"), njRentals)
        }
        if !njSales.isEmpty {
            njSection(String(localized: "Homes for sale"), njSales)
        }
        Text("From Affordable Homes New Jersey (CGP&H), checked daily. To be in a drawing, fill in CGP&H's pre-application, then join that town's waiting list from your CGP&H profile by the date shown. Units, rents and income limits are shown in your profile.")
            .font(.se(14)).foregroundStyle(SE.ink3).padding(.horizontal, 16).padding(.top, 4)
    }

    @ViewBuilder private func njSection(_ title: String, _ items: [LotteryFeed.NJLottery]) -> some View {
        Text(title).font(.se(15, .bold)).foregroundStyle(SE.ink2).textCase(.uppercase)
            .padding(.horizontal, 16).padding(.top, 4)
        LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
            ForEach(items) { njCard($0) }
        }
        .padding(.horizontal, sizeClass == .regular ? 16 : 0)
    }

    private func njCard(_ l: LotteryFeed.NJLottery) -> some View {
        let days = LotteryFeed.daysLeft(l.closes)
        return VStack(alignment: .leading, spacing: 6) {
            NJPhoto(lottery: l)
            Text(l.development ?? l.town).font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text([l.development == nil ? nil : l.town, l.county.map { String(localized: "\($0) County, NJ") } ?? String(localized: "New Jersey"), l.isRental ? String(localized: "Rental") : "For sale"]
                    .compactMap { $0 }.joined(separator: " · "))
                .font(.se(15, .semibold)).foregroundStyle(SE.ink2)
            Text(njWhen(l, days)).font(.se(16)).foregroundStyle((days ?? 99) <= 3 ? SE.warn : SE.ink)
            if let href = l.href, let url = URL(string: href) {
                // Opens the listing itself on CGP&H (owner, 2026-09-24: the home
                // page "is a generic website - i dont see the actual listing").
                SEPrimaryButton(title: String(localized: "View the listing"), icon: "arrow.up.right") {
                    Analytics.shared.track("outbound", ["kind": "nj_cgph", "href": href, "town": l.town, "from": "lotteries_tab"])
                    openURL(url)
                }
                .padding(.top, 6)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
        // A container, so the card's id is not stamped onto the photo and
        // buttons inside it (the Events cards had the same problem).
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("nj-lottery-card")
    }

    private func njWhen(_ l: LotteryFeed.NJLottery, _ days: Int?) -> String {
        guard let c = l.closes, let d = days else { return String(localized: "Waiting list opening soon") }
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "America/New_York")
        let out = DateFormatter(); out.setLocalizedDateFormatFromTemplate("EEEMMMd"); out.timeZone = f.timeZone
        let when = f.date(from: c).map { out.string(from: $0) } ?? c
        return String(localized: "Join the waiting list by \(when)") + (d == 0 ? String(localized: " (today)") : d == 1 ? String(localized: " (tomorrow)") : " (\(d)d)")
    }

    private var boroughNames: String {
        let n = feed.viewBoroughs.map { Borough.name($0) }
        if n.count == Borough.all.count { return String(localized: "all five boroughs") }
        return ListFormatter.localizedString(byJoining: n)
    }
    private var boroughLine: String { feed.viewBoroughs.count == Borough.all.count ? String(localized: "All five boroughs") : feed.viewBoroughs.map { Borough.name($0) }.joined(separator: " · ") }
    private var countLine: String {
        if feed.loading && feed.all.isEmpty { return String(localized: "Loading…") }
        return lotteries.count == feed.mine.count ? String(localized: "\(feed.mine.count) open") : String(localized: "\(lotteries.count) of \(feed.mine.count) open")
    }

    private func card(_ l: LotteryFeed.Lottery) -> some View {
        VStack(alignment: .leading, spacing: 0) {
        LotteryPhoto(key: "hc-\(l.id)", lat: l.lat, lng: l.lng)
        VStack(alignment: .leading, spacing: 6) {
            Text(l.name).font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text(whereWhen(l)).font(.se(15, .semibold)).foregroundStyle(urgent(l) ? SE.warn : SE.ink2)
            if let rent = rent(l) { Text(rent).font(.se(16)).foregroundStyle(SE.ink) }
            if let lo = l.income_min, let hi = l.income_max {
                HStack(spacing: 8) {
                    Text("Income \(k(lo))–\(k(hi))").font(.se(15)).foregroundStyle(SE.ink2)
                    if let v = Qualify.shared.verdict(incomeMin: l.income_min, incomeMax: l.income_max,
                                                      householdMin: l.household_min, householdMax: l.household_max) {
                        QualifyBadge(verdict: v)
                    } else if LotteryFeed.incomeFits(feed.income, l) {
                        Label("Your income fits", systemImage: "checkmark.circle.fill")
                            .font(.se(14, .bold)).foregroundStyle(SE.good)
                    }
                }
            }
            if let href = l.href, let url = URL(string: href) {
                SEPrimaryButton(title: String(localized: "Apply on Housing Connect"), icon: "arrow.up.right") {
                    Analytics.shared.track("outbound", ["kind": "housing_connect", "href": href, "from": "lotteries_tab"])
                    openURL(url)
                }
                .padding(.top, 6)
            }
            if let c = l.closes {
                AddToCalendarButton(item: CalendarItem(title: String(localized: "Lottery deadline: \(l.name)"), day: c,
                                                       notes: String(localized: "Apply on Housing Connect before the deadline."), url: l.href.flatMap(URL.init(string:))),
                                    label: String(localized: "Add deadline to Calendar"))
                    // Centred under Apply (owner, 2026-10-14).
                    .foregroundStyle(SE.royal).frame(maxWidth: .infinity).padding(.top, 4).accessibilityIdentifier("lottery-calendar")
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Color.white)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("lottery-card")
    }

    private func message(_ title: String, _ body: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text(body).font(.se(16)).foregroundStyle(SE.ink2)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
        .accessibilityIdentifier("lotteries-empty")
    }

    private func urgent(_ l: LotteryFeed.Lottery) -> Bool { (LotteryFeed.daysLeft(l.closes) ?? 99) <= 3 }

    private func whereWhen(_ l: LotteryFeed.Lottery) -> String {
        var s = [l.neighborhood, l.borough].compactMap { $0 }.joined(separator: ", ")
        if let c = l.closes, let d = LotteryFeed.daysLeft(c) {
            let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "America/New_York")
            let out = DateFormatter(); out.setLocalizedDateFormatFromTemplate("EEEMMMd"); out.timeZone = f.timeZone
            let when = f.date(from: c).map { out.string(from: $0) } ?? c
            s += String(localized: " · Closes \(when)") + (d == 0 ? String(localized: " (today)") : d == 1 ? String(localized: " (tomorrow)") : " (\(d)d)")
        }
        return s
    }

    private func rent(_ l: LotteryFeed.Lottery) -> String? {
        let money = { (n: Int) in "$" + n.formatted() }
        var parts: [String] = []
        if let lo = l.rent_low, let hi = l.rent_high { parts.append(lo == hi ? "\(money(lo))/mo" : "\(money(lo))–\(money(hi))/mo") }
        if let b = l.beds, !b.isEmpty { parts.append(b.count == 1 ? b[0] : "\(b.first!)–\(b.last!)") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func k(_ n: Int) -> String { n >= 1000 ? "$\(n / 1000)k" : "$\(n)" }
}


/// Bedrooms wanted in the Lotteries tab, kept across launches ("0,1" =
/// studio or 1-bed; empty = any size). Lives in the Filter sheet since
/// 2026-10-17 (owner: off the tab, into "Edit boroughs", renamed Filter).
struct LotteryBedsPicker: View {
    @AppStorage("lotteries.beds") private var bedsRaw = ""
    private var binding: Binding<Set<Int>> {
        Binding(get: { Set(bedsRaw.split(separator: ",").compactMap { Int($0) }) }, set: { new in
            bedsRaw = new.sorted().map(String.init).joined(separator: ",")
            Analytics.shared.track("lotteries_beds", ["beds": bedsRaw.isEmpty ? "any" : bedsRaw])
        })
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Beds").font(.se(15, .bold)).foregroundStyle(SE.ink2).textCase(.uppercase)
            // fixedSize: the strip's divider lines are flexible and would
            // otherwise stretch it to fill the sheet.
            SESegmentRow(options: [(0, String(localized: "Studio")), (1, "1"), (2, "2"), (3, "3"), (4, "4+")], selection: binding)
                .fixedSize(horizontal: false, vertical: true)
            Text("Lotteries and re-rentals with any of these sizes. Leave all off for every size.")
                .font(.se(14)).foregroundStyle(SE.ink3)
        }
    }
}

/// Filter for someone without alerts: just Beds, no account needed.
struct LotteryBedsSheet: View {
    @Environment(\.dismiss) private var dismiss
    var body: some View {
        NavigationStack {
            LotteryBedsPicker().padding(16).frame(maxHeight: .infinity, alignment: .top)
                .navigationTitle("Filter").navigationBarTitleDisplayMode(.inline)
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } }
        }
        .accessibilityIdentifier("lotteries-filter-sheet")
    }
}
