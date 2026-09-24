import SwiftUI

/// The Lotteries tab outside New York (owner, 2026-09-24): the openings the
/// place's housing agencies publish — lotteries, open waitlists, first-come
/// units — soonest deadline first, each linking to the agency's own page to
/// apply. New Jersey lists CGP&H's town drawings. No sign-up: these are public
/// lists and there are no borough alerts outside New York. See OpeningsFeed.
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
    private var lotteryFeed: LotteryFeed { LotteryFeed.shared }
    private var city: City { store.city }
    private var isNJ: Bool { city.id == "st-nj" }

    private var openings: [OpeningsFeed.Opening] {
        OpeningsFeed.filter(feed.all, for: city, today: LotteryFeed.todayKey())
            .filter { ($0.tenure == "buy") == (tenure == .buy) }
    }
    private var nj: [LotteryFeed.NJLottery] { lotteryFeed.njOpen.filter { $0.isRental == (tenure == .rent) } }
    private var count: Int { isNJ ? nj.count : openings.count }
    private var loading: Bool { isNJ ? lotteryFeed.loading : feed.loading }

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
                        if isNJ { ForEach(nj) { njCard($0) } } else { ForEach(openings) { card($0) } }
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
        if isNJ { await lotteryFeed.loadLotteries() } else { await feed.load() }
    }

    private var footnote: String {
        if isNJ {
            return "From Affordable Homes New Jersey (CGP&H), checked daily. To be in a drawing, fill in CGP&H's free pre-application, then join that town's waiting list from your profile by the date shown."
        }
        let srcs = Set(OpeningsFeed.filter(feed.all, for: city, today: LotteryFeed.todayKey()).map(\.src)).sorted()
        return "From " + (srcs.isEmpty ? "the agencies' own listings" : ListFormatter.localizedString(byJoining: srcs))
            + ", updated every few hours. Income limits and household size decide eligibility — check each listing before you apply."
    }

    @ViewBuilder private var empty: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(feed.loadFailed && !isNJ ? "Couldn't load openings" : "Nothing open right now")
                .font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text(feed.loadFailed && !isNJ ? "Check your connection and pull down to try again."
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
            if let c = o.closes, let d = days {
                Text("Apply by \(Self.date(c))" + (d == 0 ? " (today)" : d == 1 ? " (tomorrow)" : " (\(d)d)"))
                    .font(.se(15, .semibold)).foregroundStyle(d <= 3 ? SE.warn : SE.ink2)
            }
            if let line = rentLine(o) { Text(line).font(.se(16)).foregroundStyle(SE.ink) }
            if let line = incomeLine(o) { Text(line).font(.se(15)).foregroundStyle(SE.ink2) }
            if let href = o.href, let url = URL(string: href) {
                SEPrimaryButton(title: "Apply on \(o.src)", icon: "arrow.up.right") {
                    Analytics.shared.track("outbound", ["kind": "opening", "src": o.src, "href": href, "from": "lotteries_tab"])
                    openURL(url)
                }
                .padding(.top, 6)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
        .accessibilityIdentifier("opening-card")
    }

    private func njCard(_ l: LotteryFeed.NJLottery) -> some View {
        let days = LotteryFeed.daysLeft(l.closes)
        return VStack(alignment: .leading, spacing: 6) {
            Text(l.town).font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text(l.county.map { "\($0) County, NJ" } ?? "New Jersey").font(.se(15, .semibold)).foregroundStyle(SE.ink2)
            Text(l.closes.map { c in "Join the waiting list by \(Self.date(c))" + (days.map { $0 == 0 ? " (today)" : $0 == 1 ? " (tomorrow)" : " (\($0)d)" } ?? "") }
                 ?? "Waiting list opening soon")
                .font(.se(16)).foregroundStyle((days ?? 99) <= 3 ? SE.warn : SE.ink)
            if let href = l.href, let url = URL(string: href) {
                SEPrimaryButton(title: "Apply on Affordable Homes NJ", icon: "arrow.up.right") {
                    Analytics.shared.track("outbound", ["kind": "nj_cgph", "href": href, "town": l.town, "from": "openings_tab"])
                    openURL(url)
                }
                .padding(.top, 6)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
        .accessibilityIdentifier("nj-lottery-card")
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
