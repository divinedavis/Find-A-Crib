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
    private var feed: OpeningsFeed { OpeningsFeed.shared }
    private var city: City { store.city }

    private var openings: [OpeningsFeed.Opening] {
        OpeningsFeed.filter(feed.all, for: city, today: LotteryFeed.todayKey())
            .filter { ($0.tenure == "buy") == (tenure == .buy) }
    }
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
            SEUnderlineTabs(options: [(Tenure.rent, "Rent"), (.buy, "Buy")], selection: $tenure)
                .padding(.horizontal, 16).padding(.top, 8).padding(.bottom, 10).background(Color.white)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    Text(loading && count == 0 ? "Loading…" : "\(count) open")
                        .font(.se(17, .bold)).foregroundStyle(SE.ink).padding(.horizontal, 16)
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
        .task(id: city.id) {
            await reload()
            Analytics.shared.track("openings_view", ["city": city.id, "open": count])
        }
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
            Text(feed.loadFailed ? "Couldn't load openings" : "Nothing open right now")
                .font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text(feed.loadFailed ? "Check your connection and pull down to try again."
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
            if let href = o.href, let url = URL(string: href) {
                // Lease-up buildings have no portal: the link searches for the office.
                SEPrimaryButton(title: o.kind == "leasing" ? "Find the leasing office" : "Apply on \(o.src)", icon: "arrow.up.right") {
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
