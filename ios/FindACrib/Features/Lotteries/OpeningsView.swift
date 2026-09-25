import SwiftUI

/// The Lotteries tab outside New York (owner, 2026-09-24): the openings the
/// place's housing agencies publish — lotteries, open waitlists, first-come
/// units — soonest deadline first, each linking to the agency's own page to
/// apply. No sign-up: these are public lists and there are no borough alerts
/// outside New York. See OpeningsFeed.
struct OpeningsView: View {
    @Environment(\.openURL) private var openURL
    @Environment(DataStore.self) private var store
    @Environment(\.horizontalSizeClass) private var sizeClass
    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 12, alignment: .top), count: sizeClass == .regular ? 2 : 1)
    }
    enum Tenure: Hashable { case rent, buy }
    @State private var tenure: Tenure = .rent
    // Filters (owner, 2026-09-24: "for each city you should allow people to
    // do filtering"). Only what the feeds actually carry: every listing has
    // sizes and a way in, LA has 69 neighborhoods, and rent is published on
    // too few (9 of LA's 258) for a rent filter to do anything but hide.
    /// Bedrooms, shared with New York's tab: "0,1" = studio or 1-bed.
    @AppStorage("lotteries.beds") private var bedsRaw = ""
    private var beds: Set<Int> { Set(bedsRaw.split(separator: ",").compactMap { Int($0) }) }
    private var bedsBinding: Binding<Set<Int>> {
        Binding(get: { beds }, set: { new in
            bedsRaw = new.sorted().map(String.init).joined(separator: ",")
            Analytics.shared.track("openings_filter", ["city": city.id, "beds": bedsRaw.isEmpty ? "any" : bedsRaw])
        })
    }
    /// Ways in: lottery, waitlist, first_come, leasing. Empty = any.
    @State private var kinds: Set<String> = []
    @State private var area: String? = nil
    @State private var unitsNow = false
    private var feed: OpeningsFeed { OpeningsFeed.shared }
    private var city: City { store.city }

    /// This city's open listings for Rent or Buy, before the filters below.
    private var pool: [OpeningsFeed.Opening] {
        OpeningsFeed.filter(feed.all, for: city, today: LotteryFeed.todayKey())
            .filter { ($0.tenure == "buy") == (tenure == .buy) }
    }
    private var openings: [OpeningsFeed.Opening] {
        OpeningsFeed.narrow(pool, beds: activeBeds, kinds: kinds, area: area, unitsNow: unitsNow)
    }
    /// Beds only where listings publish sizes: Miami's lease-ups publish none,
    /// and a remembered "1-bed" there read "20 of 20 open" (owner, 2026-09-24).
    private var showsBeds: Bool { pool.contains { !($0.beds ?? []).isEmpty } }
    private var activeBeds: Set<Int> { showsBeds ? beds : [] }
    /// Neighborhoods (or cities) present, most listings first.
    private var areas: [(String, Int)] { OpeningsFeed.areas(pool) }
    private var kindOptions: [String] {
        ["lottery", "waitlist", "first_come", "leasing"].filter { k in pool.contains { $0.kind == k } }
    }
    private var filtering: Bool { !activeBeds.isEmpty || !kinds.isEmpty || area != nil || unitsNow }
    private var count: Int { openings.count }
    private var loading: Bool { feed.loading }

    var body: some View {
        VStack(spacing: 0) {
            NavyHeader {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Lotteries").font(.se(24, .bold)).foregroundStyle(.white)
                    Text(city.name).font(.se(15, .semibold)).foregroundStyle(.white.opacity(0.85))
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.bottom, 12)
            }
            VStack(alignment: .leading, spacing: 10) {
                SEUnderlineTabs(options: [(Tenure.rent, "Rent"), (.buy, "Buy")], selection: $tenure)
                filterBar
            }
            .padding(.horizontal, 16).padding(.top, 8).padding(.bottom, 10).background(Color.white)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Text(loading && pool.isEmpty ? "Loading…" : filtering ? "\(count) of \(pool.count) open" : "\(count) open")
                            .font(.se(17, .bold)).foregroundStyle(SE.ink)
                            .accessibilityIdentifier("openings-count")
                        Spacer()
                        if filtering {
                            Button("Clear filters") { bedsRaw = ""; kinds = []; area = nil; unitsNow = false }
                                .font(.se(16, .bold)).foregroundStyle(SE.royal)
                                .accessibilityIdentifier("openings-clear")
                        }
                    }
                    .padding(.horizontal, 16)
                    if count == 0 && !loading {
                        empty
                    }
                    LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
                        ForEach(openings) { card($0) }
                    }
                    .padding(.horizontal, sizeClass == .regular ? 16 : 0)
                    Text(footnote).font(.se(14)).foregroundStyle(SE.ink3).padding(.horizontal, 16).padding(.top, 4)
                    Color.clear.frame(height: 120)
                }
                .padding(.top, 16)
            }
            .refreshable { await reload() }
            .background(SE.canvas)
        }
        .background(SE.canvas)
        .onChange(of: city.id) { _, _ in kinds = []; area = nil; unitsNow = false }
        .onChange(of: tenure) { _, _ in area = nil }
        .task(id: city.id) {
            await reload()
            Analytics.shared.track("openings_view", ["city": city.id, "open": count])
        }
    }

    /// Beds strip, then a scrolling row of chips: how you get in, units open
    /// now, and the area menu.
    private var filterBar: some View {
        VStack(alignment: .leading, spacing: 10) {
            if showsBeds {
                HStack(spacing: 10) {
                    Text("Beds").font(.se(15, .bold)).foregroundStyle(SE.ink2)
                    SESegmentRow(options: [(0, "Studio"), (1, "1"), (2, "2"), (3, "3"), (4, "4+")], selection: bedsBinding)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    // Area first: it is the one people reach for, and last it
                    // sat off the edge of a phone.
                    if areas.count > 1 {
                        Menu {
                            Button("Any area") { area = nil }
                            ForEach(areas, id: \.0) { a in
                                Button("\(a.0) (\(a.1))") {
                                    area = a.0
                                    Analytics.shared.track("openings_filter", ["city": city.id, "area": a.0])
                                }
                            }
                        } label: {
                            chipLabel(area ?? "Area", on: area != nil, chevron: true)
                        }
                        .accessibilityIdentifier("openings-area")
                    }
                    if kindOptions.count > 1 {
                        ForEach(kindOptions, id: \.self) { k in
                            chip(k == "first_come" ? "First come" : OpeningsFeed.kindLabel(k), on: kinds.contains(k), id: "openings-kind-\(k)") {
                                if kinds.contains(k) { kinds.remove(k) } else { kinds.insert(k) }
                                Analytics.shared.track("openings_filter", ["city": city.id, "kind": k])
                            }
                        }
                    }
                    if pool.contains(where: { ($0.units ?? 0) > 0 }) && pool.contains(where: { ($0.units ?? 0) == 0 }) {
                        chip("Units open now", on: unitsNow, id: "openings-units-now") {
                            unitsNow.toggle()
                            Analytics.shared.track("openings_filter", ["city": city.id, "units_now": unitsNow])
                        }
                    }
                }
            }
        }
    }

    private func chip(_ title: String, on: Bool, id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { chipLabel(title, on: on, chevron: false) }
            .buttonStyle(.plain)
            .accessibilityIdentifier(id)
            .accessibilityAddTraits(on ? .isSelected : [])
    }

    private func chipLabel(_ title: String, on: Bool, chevron: Bool) -> some View {
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

    private func reload() async {
        await feed.load()
    }

    private var footnote: String {
        let srcs = Set(OpeningsFeed.filter(feed.all, for: city, today: LotteryFeed.todayKey()).map(\.src)).sorted()
        if city.id == "mia" {
            return "Buildings Florida Housing lists as in lease-up — taking their first tenants now. Miami-Dade has no lottery portal: contact each building's leasing office to apply. Income limits and household size decide eligibility."
        }
        return "From " + (srcs.isEmpty ? "the agencies' own listings" : ListFormatter.localizedString(byJoining: srcs))
            + ", updated every few hours. Income limits and household size decide eligibility — check each listing before you apply."
    }

    @ViewBuilder private var empty: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(feed.loadFailed ? "Couldn't load openings" : filtering && !pool.isEmpty ? "None match these filters" : "Nothing open right now")
                .font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text(feed.loadFailed ? "Check your connection and pull down to try again."
                 : filtering && !pool.isEmpty ? "\(pool.count) open in \(city.name), none with these filters. Tap Clear filters to see them all."
                 : "No \(tenure == .rent ? "rentals" : "homes for sale") are taking applications in \(city.name) today. Pull down to check again.")
                .font(.se(16)).foregroundStyle(SE.ink2)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
        .accessibilityIdentifier("lotteries-empty")
    }

    private func card(_ o: OpeningsFeed.Opening) -> some View {
        let days = LotteryFeed.daysLeft(o.closes)
        return VStack(alignment: .leading, spacing: 6) {
            Text(o.name ?? o.address ?? "Listing").font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text([o.neighborhood ?? o.city, OpeningsFeed.kindLabel(o.kind)].compactMap { $0 }.joined(separator: " · "))
                .font(.se(15, .semibold)).foregroundStyle(SE.ink2)
            // Lease-ups have no listing page, so the address is how to find them.
            if o.kind == "leasing", let addr = o.address { Text(addr).font(.se(15)).foregroundStyle(SE.ink2) }
            if let c = o.closes, let d = days {
                Text("Apply by \(Self.date(c))" + (d == 0 ? " (today)" : d == 1 ? " (tomorrow)" : " (\(d)d)"))
                    .font(.se(15, .semibold)).foregroundStyle(d <= 3 ? SE.warn : SE.ink2)
            }
            if let line = rentLine(o) { Text(line).font(.se(16)).foregroundStyle(SE.ink) }
            if let line = incomeLine(o) { Text(line).font(.se(15)).foregroundStyle(SE.ink2) }
            if let note = o.note { Text(note).font(.se(15, .semibold)).foregroundStyle(SE.ink2) }
            if let ph = o.phone, let url = URL(string: "tel:\(ph.filter(\.isNumber))") {
                Button {
                    Analytics.shared.track("outbound", ["kind": "opening_phone", "src": o.src, "from": "lotteries_tab"])
                    openURL(url)
                } label: {
                    Label(ph, systemImage: "phone.fill").font(.se(17, .bold)).foregroundStyle(SE.royal)
                }.buttonStyle(.plain)
            }
            if let href = o.href, let url = URL(string: href) {
                // Lease-ups link to the building's own leasing site (a search
                // only if none was found).
                SEPrimaryButton(title: o.kind != "leasing" ? "Apply on \(o.src)"
                                : href.contains("google.com/search") ? "Find the leasing office" : "View availability",
                                icon: "arrow.up.right") {
                    Analytics.shared.track("outbound", ["kind": "opening", "src": o.src, "href": href, "from": "lotteries_tab"])
                    openURL(url)
                }
                .padding(.top, 6)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
        .accessibilityIdentifier("opening-card")
    }

    private func rentLine(_ o: OpeningsFeed.Opening) -> String? {
        var parts: [String] = []
        if let lo = o.rent_low, let hi = o.rent_high {
            parts.append(lo == hi ? "$\(lo.formatted())/mo" : "$\(lo.formatted())–$\(hi.formatted())/mo")
        }
        if let b = o.beds, !b.isEmpty { parts.append(b.count == 1 ? b[0] : "\(b.first!)–\(b.last!)") }
        if let u = o.units, u > 0 { parts.append("\(u) unit\(u == 1 ? "" : "s")") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func incomeLine(_ o: OpeningsFeed.Opening) -> String? {
        var parts: [String] = []
        if let a = o.ami { parts.append("Up to \(a)% of area median income") }
        if let m = o.income_min_mo, m > 0 { parts.append("min. income $\(m.formatted())/mo") }
        else if let y = o.income_min, y > 0 { parts.append("min. income $\(y.formatted())/yr") }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private static func date(_ c: String) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "America/New_York")
        let out = DateFormatter(); out.dateFormat = "EEE MMM d"; out.timeZone = f.timeZone
        return f.date(from: c).map { out.string(from: $0) } ?? c
    }
}
