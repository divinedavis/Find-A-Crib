import SwiftUI

/// The Lotteries tab: for an alert subscriber, Housing Connect lotteries open in the
/// boroughs they get alerts for, soonest deadline first, and (owner, same
/// day) the HPD marketing agents' re-rentals in those boroughs. Everyone
/// else sees a sign-up screen; only its button opens the sign-up sheet.
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
    @State private var showAlerts = false
    @State private var showSignIn = false
    enum Pane: Hashable { case lotteries, rerentals, newJersey }
    @State private var pane: Pane = .lotteries
    /// Bedrooms they need, kept across launches: "0,1" = studio or 1-bed.
    /// Empty = any size.
    @AppStorage("lotteries.beds") private var bedsRaw = ""
    private var beds: Set<Int> { Set(bedsRaw.split(separator: ",").compactMap { Int($0) }) }
    private var bedsBinding: Binding<Set<Int>> {
        Binding(get: { beds }, set: { new in
            bedsRaw = new.sorted().map(String.init).joined(separator: ",")
            Analytics.shared.track("lotteries_beds", ["beds": bedsRaw.isEmpty ? "any" : bedsRaw])
        })
    }
    private var lotteries: [LotteryFeed.Lottery] { feed.mine.filter { LotteryFeed.bedsMatch($0.beds, want: beds) } }
    private var feed: LotteryFeed { LotteryFeed.shared }

    var body: some View {
        // Outside New York: the place's own openings, no sign-up (2026-09-24).
        if !store.city.isNYC { OpeningsView() } else { nycBody }
    }

    private var nycBody: some View {
        Group {
            // Never show the sign-up until we KNOW they are not subscribed.
            if feed.subscribed { list } else if feed.checked { signup } else { checking }
        }
        .sheet(isPresented: $showAlerts, onDismiss: { Task { await feed.refresh() } }) { AlertsSheet() }
        // Signed out: sign in first, then straight on to the alerts sheet —
        // unless the account they signed into already has alerts.
        .sheet(isPresented: $showSignIn, onDismiss: {
            guard auth.isSignedIn else { return }
            Task { await feed.refresh(); if !feed.subscribed { showAlerts = true } }
        // Apple and Google first, no keyboard until they pick email (owner, 2026-09-19).
        }) { EmailSignInView(offersSocialSignIn: true) }
        // No sheet opens by itself (owner, 2026-09-19): the tab shows the
        // sign-up screen, and only its button opens the sign-up.
    }

    private func promptSignup() {
        Analytics.shared.track("lotteries_signup_prompt", ["signed_in": auth.isSignedIn])
        if auth.isSignedIn { showAlerts = true } else { showSignIn = true }
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

    private var signup: some View {
        VStack(spacing: 0) {
            NavyHeader {
                Text("Lotteries").font(.se(24, .bold)).foregroundStyle(.white)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.bottom, 12)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Image(systemName: "ticket").font(.system(size: 40, weight: .semibold)).foregroundStyle(SE.royal)
                    Text("Lotteries & re-rentals for your boroughs").font(.se(24, .bold)).foregroundStyle(SE.ink)
                    Text("Sign up for free alerts and this tab lists every NYC Housing Connect lottery and income-restricted re-rental open in the boroughs you pick. We'll also tell you the minute a new one opens.")
                        .font(.se(17)).foregroundStyle(SE.ink2)
                    SEPrimaryButton(title: "Sign up for alerts") { promptSignup() }
                        .accessibilityIdentifier("lotteries-signup")
                        .padding(.top, 6)
                    Text("Free. Unsubscribe any time.").font(.se(14)).foregroundStyle(SE.ink3)
                }
                .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
                .padding(.top, 16)
            }
            .background(SE.canvas)
        }
        .background(SE.canvas)
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
                SEUnderlineTabs(options: [(Pane.lotteries, "NYC (\(lotteries.count))"), (.rerentals, "Re-rentals (\(rerentals.count))"),
                                          (.newJersey, "NJ (\(feed.njOpen.count))")], selection: $pane)
                    .padding(.bottom, pane == .newJersey ? 10 : 0)
                // NJ's source publishes no bedroom sizes, so no Beds strip there.
                if pane != .newJersey {
                HStack(spacing: 10) {
                    Text("Beds").font(.se(15, .bold)).foregroundStyle(SE.ink2)
                    // fixedSize: the strip's divider lines are flexible and
                    // would otherwise stretch it to fill the header.
                    SESegmentRow(options: [(0, "Studio"), (1, "1"), (2, "2"), (3, "3"), (4, "4+")], selection: bedsBinding)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.bottom, 10)
                }
            }
            .padding(.horizontal, 16).padding(.top, 8).background(Color.white)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if pane == .newJersey { njList } else if pane == .rerentals { rerentalList } else {
                    HStack {
                        Text(countLine).font(.se(17, .bold)).foregroundStyle(SE.ink)
                        Spacer()
                        Button("Edit boroughs") { showAlerts = true }
                            .font(.se(16, .bold)).foregroundStyle(SE.royal)
                            .accessibilityIdentifier("lotteries-edit")
                    }
                    .padding(.horizontal, 16)
                    if feed.loadFailed {
                        message("Couldn't load lotteries", "Check your connection and pull down to try again.")
                    } else if feed.mine.isEmpty && !feed.loading {
                        message("Nothing open right now",
                                "No Housing Connect lotteries are open in \(boroughNames) right now. We'll alert you the minute one opens.")
                    } else if lotteries.isEmpty && !feed.loading {
                        message("None with \(bedsWords)",
                                "\(feed.mine.count) open in \(boroughNames), none with \(bedsWords). Change Beds above to see them.")
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
    private var rerentals: [FeaturedListing] {
        let codes = Set(feed.boroughs)
        return store.featured.listings.filter {
            ($0.boroughCode.map(codes.contains) ?? false)
                && LotteryFeed.bedsMatch($0.beds.map { [$0] }, want: beds)
        }
    }

    /// "a 1-bed", "a studio or 1-bed", "3+ beds" — for the empty message.
    private var bedsWords: String {
        let names = beds.sorted().map { $0 == 0 ? "studio" : $0 == 4 ? "4+ bed" : "\($0)-bed" }
        return names.isEmpty ? "any size" : "a " + ListFormatter.localizedString(byJoining: names).replacingOccurrences(of: " and ", with: " or ")
    }

    @ViewBuilder private var rerentalList: some View {
        HStack {
            Text("\(rerentals.count) available").font(.se(17, .bold)).foregroundStyle(SE.ink)
            Spacer()
            Button("Edit boroughs") { showAlerts = true }.font(.se(16, .bold)).foregroundStyle(SE.royal)
        }
        .padding(.horizontal, 16)
        if rerentals.isEmpty && !beds.isEmpty {
            message("None with \(bedsWords)", "No re-rental in \(boroughNames) lists \(bedsWords) today. Change Beds above to see them.")
        } else if rerentals.isEmpty {
            message("No re-rentals right now",
                    "No HPD marketing agent is advertising a re-rental in \(boroughNames) today. We'll alert you when one is posted.")
        }
        // slot -1 marks this tab in the re-rental funnel, apart from the
        // search feed's slots 0, 1, 2…
        LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
            ForEach(rerentals) { RerentalCard(listing: $0, slot: -1) }
        }
        .padding(.horizontal, 16)
        Text("Income-restricted apartments that HPD-approved marketing agents are re-renting, from their own websites. Apply through the agent."
             + (beds.isEmpty ? "" : " Most agents don't list bedrooms, so those stay in the list whatever Beds is set to."))
            .font(.se(14)).foregroundStyle(SE.ink3).padding(.horizontal, 16).padding(.top, 4)
    }

    // MARK: - New Jersey

    private var njRentals: [LotteryFeed.NJLottery] { feed.njOpen.filter(\.isRental) }
    private var njSales: [LotteryFeed.NJLottery] { feed.njOpen.filter { !$0.isRental } }

    @ViewBuilder private var njList: some View {
        Text(feed.loading && feed.nj.isEmpty ? "Loading…" : "\(feed.njOpen.count) open in New Jersey")
            .font(.se(17, .bold)).foregroundStyle(SE.ink).padding(.horizontal, 16)
        if feed.njOpen.isEmpty && !feed.loading {
            message("No New Jersey drawings right now",
                    "Affordable Homes New Jersey isn't listing an open drawing today. Pull down to check again.")
        }
        if !njRentals.isEmpty {
            njSection("Rentals", njRentals)
        }
        if !njSales.isEmpty {
            njSection("Homes for sale", njSales)
        }
        Text("From Affordable Homes New Jersey (CGP&H), checked daily. To be in a drawing, fill in CGP&H's free pre-application, then join that town's waiting list from your CGP&H profile by the date shown. Units, rents and income limits are shown in your profile.")
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
            Text(l.development ?? l.town).font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text([l.development == nil ? nil : l.town, l.county.map { "\($0) County, NJ" } ?? "New Jersey", l.isRental ? "Rental" : "For sale"]
                    .compactMap { $0 }.joined(separator: " · "))
                .font(.se(15, .semibold)).foregroundStyle(SE.ink2)
            Text(njWhen(l, days)).font(.se(16)).foregroundStyle((days ?? 99) <= 3 ? SE.warn : SE.ink)
            if let href = l.href, let url = URL(string: href) {
                // Opens the listing itself on CGP&H (owner, 2026-09-24: the home
                // page "is a generic website - i dont see the actual listing").
                SEPrimaryButton(title: "View the listing", icon: "arrow.up.right") {
                    Analytics.shared.track("outbound", ["kind": "nj_cgph", "href": href, "town": l.town, "from": "lotteries_tab"])
                    openURL(url)
                }
                .padding(.top, 6)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
        .accessibilityIdentifier("nj-lottery-card")
    }

    private func njWhen(_ l: LotteryFeed.NJLottery, _ days: Int?) -> String {
        guard let c = l.closes, let d = days else { return "Waiting list opening soon" }
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "America/New_York")
        let out = DateFormatter(); out.dateFormat = "EEE MMM d"; out.timeZone = f.timeZone
        let when = f.date(from: c).map { out.string(from: $0) } ?? c
        return "Join the waiting list by \(when)" + (d == 0 ? " (today)" : d == 1 ? " (tomorrow)" : " (\(d)d)")
    }

    private var boroughNames: String {
        let n = feed.boroughs.map { Borough.name($0) }
        if n.count == Borough.all.count { return "all five boroughs" }
        return ListFormatter.localizedString(byJoining: n)
    }
    private var boroughLine: String { feed.boroughs.count == Borough.all.count ? "All five boroughs" : feed.boroughs.map { Borough.name($0) }.joined(separator: " · ") }
    private var countLine: String {
        if feed.loading && feed.all.isEmpty { return "Loading…" }
        return beds.isEmpty ? "\(feed.mine.count) open" : "\(lotteries.count) of \(feed.mine.count) open"
    }

    private func card(_ l: LotteryFeed.Lottery) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(l.name).font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text(whereWhen(l)).font(.se(15, .semibold)).foregroundStyle(urgent(l) ? SE.warn : SE.ink2)
            if let rent = rent(l) { Text(rent).font(.se(16)).foregroundStyle(SE.ink) }
            if let lo = l.income_min, let hi = l.income_max {
                HStack(spacing: 8) {
                    Text("Income \(k(lo))–\(k(hi))").font(.se(15)).foregroundStyle(SE.ink2)
                    if LotteryFeed.incomeFits(feed.income, l) {
                        Label("Your income fits", systemImage: "checkmark.circle.fill")
                            .font(.se(14, .bold)).foregroundStyle(SE.good)
                    }
                }
            }
            if let href = l.href, let url = URL(string: href) {
                SEPrimaryButton(title: "Apply on Housing Connect", icon: "arrow.up.right") {
                    Analytics.shared.track("outbound", ["kind": "housing_connect", "href": href, "from": "lotteries_tab"])
                    openURL(url)
                }
                .padding(.top, 6)
            }
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
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
            let out = DateFormatter(); out.dateFormat = "EEE MMM d"; out.timeZone = f.timeZone
            let when = f.date(from: c).map { out.string(from: $0) } ?? c
            s += " · Closes \(when)" + (d == 0 ? " (today)" : d == 1 ? " (tomorrow)" : " (\(d)d)")
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
