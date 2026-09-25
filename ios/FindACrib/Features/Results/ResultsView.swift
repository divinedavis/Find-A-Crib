import SwiftUI

/// The filter bar StreetEasy puts over its results: a white field carrying
/// back-chevron + location + summary, and a "Filter (n)" button, on navy.
/// The filter bar, StreetEasy style, but living IN the navigation bar row so
/// it sits beside the system back chevron: a white field with location and
/// summary, and a Filter button. Used as the `.principal` toolbar item; the
/// navy behind it is the thin `NavyHeader` the screen keeps at the top.
struct ResultsHeader: View {
    @Environment(DataStore.self) private var store
    let query: SearchQuery
    /// Tapping the location field opens the borough / neighborhood picker in
    /// a sheet. It used to pop back to the previous screen, which read as a
    /// broken button — the system chevron beside it is the back control.
    let onLocation: () -> Void
    let onFilter: () -> Void
    /// iPad (owner, 2026-09-22): the field was the whole width of the bar, so
    /// the row carries one-tap filters beside a shorter field instead. They
    /// edit the same query the Filter sheet does. nil = no quick filters.
    var edit: Binding<SearchQuery>? = nil
    @Environment(\.horizontalSizeClass) private var sizeClass
    private var quick: Bool { sizeClass == .regular && edit != nil }

    var body: some View {
        HStack(spacing: 8) {
            Button(action: onLocation) {
                HStack(spacing: 8) {
                    Image(systemName: "mappin").font(.system(size: 13, weight: .bold)).foregroundStyle(SE.royal)
                    // Two lines inside the 40pt pill: the place, then the filter
                    // summary ("Up to $3k, 2 bd") small underneath. Side by side
                    // the summary was cut to "Up to…" on a phone (2026-09-08).
                    VStack(alignment: .leading, spacing: 1) {
                        Text(query.shortLocationLabel(boroughOf: store.boroughOfNeighborhood, city: store.city.short)).font(.se(15)).foregroundStyle(SE.ink).lineLimit(1).truncationMode(.tail)
                            .accessibilityIdentifier("results-location")
                        Text(query.summary).font(.se(12)).foregroundStyle(SE.ink2).lineLimit(1).minimumScaleFactor(0.8)
                    }
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 10).frame(height: 40)
                .background(Color.white).clipShape(RoundedRectangle(cornerRadius: 2))
            }
            .buttonStyle(.plain)
            .frame(minWidth: quick ? 180 : nil, maxWidth: quick ? 340 : .infinity)
            .accessibilityIdentifier("results-location-field")

            if quick, let edit { quickFilters(edit); Spacer(minLength: 0) }

            Button(action: onFilter) {
                HStack(spacing: 5) {
                    Image(systemName: "slider.horizontal.3").font(.system(size: 13, weight: .bold))
                    Text("Filter" + (query.activeFilterCount > 0 ? " (\(query.activeFilterCount))" : "")).font(.se(16, .bold))
                }
                .foregroundStyle(SE.royal)
                .padding(.horizontal, 10).frame(height: 40)
                .background(Color.white).clipShape(RoundedRectangle(cornerRadius: 2))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("results-filter")
        }
        // Toolbar items size to their content; give the row the bar's free width
        // (screen minus the chevron and margins) so the field can stretch.
        .frame(width: barWidth)
    }

    @ViewBuilder private func quickFilters(_ q: Binding<SearchQuery>) -> some View {
        let v = q.wrappedValue
        Menu {
            ForEach([(0, "Studio"), (1, "1 bed"), (2, "2 beds"), (3, "3 beds"), (4, "4+ beds")], id: \.0) { n, label in
                Button {
                    if q.wrappedValue.beds.contains(n) { q.wrappedValue.beds.remove(n) } else { q.wrappedValue.beds.insert(n) }
                    Analytics.shared.track("quick_filter", ["f": "beds", "beds": q.wrappedValue.beds.sorted().map(String.init).joined(separator: ",")])
                } label: {
                    if v.beds.contains(n) { Label(label, systemImage: "checkmark") } else { Text(label) }
                }
            }
            if !v.beds.isEmpty {
                Divider()
                Button("Any size") { q.wrappedValue.beds = [] }
            }
        } label: {
            chipLabel(bedsLabel(v.beds), on: !v.beds.isEmpty, chevron: true)
        }
        .accessibilityIdentifier("quick-beds")
        Button(action: onFilter) { chipLabel(priceLabel(v), on: v.minPrice != nil || v.maxPrice != nil, chevron: true) }
            .buttonStyle(.plain).accessibilityIdentifier("quick-price")
        toggle("Available now", q, \.availableOnly, "available")
        // How many more fit depends on the bar: an iPad mini upright has room
        // for three, an 11-inch for four, a 13-inch or any iPad sideways for
        // all six. The rest stay one tap away in the Filter sheet.
        if barWidth >= 740 { toggle("Vouchers", q, \.vouchersOnly, "vouchers") }
        if barWidth >= 920 {
            toggle("Lotteries", q, \.hcrOnly, "lotteries")
            toggle("No violations", q, \.noOpenViolations, "no_violations")
        }
    }

    private var barWidth: CGFloat { UIScreen.main.bounds.width - 92 }

    private func toggle(_ title: String, _ q: Binding<SearchQuery>, _ key: WritableKeyPath<SearchQuery, Bool>, _ name: String) -> some View {
        let on = q.wrappedValue[keyPath: key]
        return Button {
            q.wrappedValue[keyPath: key].toggle()
            Analytics.shared.track("quick_filter", ["f": name, "on": !on])
        } label: { chipLabel(title, on: on, chevron: false) }
        .buttonStyle(.plain)
        .accessibilityIdentifier("quick-\(name)")
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    private func chipLabel(_ text: String, on: Bool, chevron: Bool) -> some View {
        HStack(spacing: 4) {
            Text(text).font(.se(15, .semibold)).lineLimit(1)
            if chevron { Image(systemName: "chevron.down").font(.system(size: 10, weight: .bold)) }
        }
        .foregroundStyle(on ? Color.white : SE.royal)
        .padding(.horizontal, 12).frame(height: 40)
        .background(on ? SE.royal : Color.white)
        .overlay(RoundedRectangle(cornerRadius: 2).stroke(on ? Color.white.opacity(0.8) : .clear, lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 2))
        .fixedSize()
    }

    private func bedsLabel(_ beds: Set<Int>) -> String {
        guard !beds.isEmpty else { return "Beds" }
        return beds.sorted().map { $0 == 0 ? "Studio" : $0 == 4 ? "4+" : "\($0)" }.joined(separator: ", ") + (beds == [0] ? "" : " bd")
    }

    private func priceLabel(_ v: SearchQuery) -> String {
        let k = { (n: Int) in n >= 1000 ? "$\(n / 1000)k" : "$\(n)" }
        switch (v.minPrice, v.maxPrice) {
        case let (lo?, hi?): return "\(k(lo))–\(k(hi))"
        case let (lo?, nil): return "\(k(lo))+"
        case let (nil, hi?): return "Up to \(k(hi))"
        default: return "Price"
        }
    }
}

/// Navy strip behind the (transparent) navigation bar. Its content is empty;
/// the background's ignoresSafeArea is what paints the bar row navy.
struct NavyBarBackdrop: View {
    var body: some View { NavyHeader { Color.clear.frame(height: 6) } }
}

struct ResultsView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    @Environment(AppNav.self) private var nav
    @Environment(AuthService.self) private var auth
    @Environment(\.horizontalSizeClass) private var sizeClass
    /// iPad: two columns of cards instead of one card the width of the screen.
    private var wide: Bool { sizeClass == .regular }
    @State var query: SearchQuery
    @State private var results: [Building] = []
    @State private var shown = 30
    @State private var showFilters = false
    @State private var showLocation = false
    @State private var showAlerts = false
    @State private var showSignIn = false
    @State private var toast: String?

    var body: some View {
        let _ = Perf.mark("ResultsView.body shown=\(shown) results=\(results.count)")
        VStack(spacing: 0) {
            NavyBarBackdrop()
            // The city's skyline rides at the top of the list; pull past the
            // top and the night sky shows above it (CitySkyline.swift).
            SkylineScrollView(scene: Skyline.Scene.scene(for: store.city.id)) {
                LazyVStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(query.resultHeadline(count: results.count, city: store.city))
                            .font(.se(24, .bold)).foregroundStyle(SE.ink).lineLimit(1).minimumScaleFactor(0.75)
                            .accessibilityIdentifier("results-count")
                        Spacer()
                        Menu {
                            ForEach(SortOrder.allCases, id: \.self) { s in
                                Button { Analytics.shared.track("sort", ["to": s.rawValue]); query.sort = s } label: {
                                    if s == query.sort { Label(s.rawValue, systemImage: "checkmark") } else { Text(s.rawValue) }
                                }
                            }
                        } label: {
                            HStack(spacing: 6) {
                                Text(query.sort.rawValue).font(.se(18, .semibold)).lineLimit(1)
                                Image(systemName: "chevron.down").font(.system(size: 13, weight: .bold))
                            }.foregroundStyle(SE.ink2)
                        }
                        .accessibilityIdentifier("sort-menu")
                    }
                    .padding(.horizontal, 16).padding(.top, 14)

                    if results.isEmpty && store.loaded {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("No \(query.noun) match").font(.se(22, .bold))
                            Text(emptyHint).font(.se(17)).foregroundStyle(SE.ink2)
                            SEOutlineButton(title: "Adjust filters") { showFilters = true }
                        }
                        .padding(18).seCard().padding(.horizontal, 16)
                    }

                    // Re-rentals from the HPD marketing agents ride along in
                    // the feed: the 3rd tile, then one every 8–15 (RerentalFeed).
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 16, alignment: .top), count: wide ? 2 : 1),
                              alignment: .leading, spacing: 16) {
                        ForEach(RerentalFeed.rows(buildings: Array(results.prefix(shown)), pool: rerentalPool, seed: RerentalFeed.launchSeed)) { row in
                            switch row {
                            case .building(let b):
                                BuildingCard(building: b)
                                    .onAppear { if b.bbl == results[min(shown, results.count) - 1].bbl, shown < results.count { shown += 30 } }
                            case .rerental(let f, let slot):
                                RerentalCard(listing: f, slot: slot)
                            }
                        }
                    }
                    .padding(.horizontal, 16)
                    Color.clear.frame(height: 150)
                }
            }
        }
        .background(SE.canvas)
        .overlay(alignment: .bottom) {
            HStack(spacing: 14) {
                FloatingPill(title: "Map", icon: "map.fill") {
                    Analytics.shared.track("map_open", Analytics.shape(query))
                    nav.searchPath.append(.map(query))
                }
                // Alerts took this slot from "Save search" (owner, 2026-09-12).
                // It used to appear only on Available-now / vouchers / lottery
                // searches, where "tell me when one opens" obviously means
                // something — but it means the same thing on any search, and a
                // standing email beats a bookmark the visitor has to come back
                // and re-read. It needs an account, because it needs an email.
                // New York only (2026-09-19): every alert we can send comes
                // from a NY feed — Housing Connect, HousingSearch.ny.gov, the
                // HPD marketing agents, and a voucher scrape keyed to NY
                // counties — and the sign-up form asks for boroughs. In LA, SF
                // or DC the button could only promise something nothing feeds.
                if store.city.isNYC {
                    FloatingPill(title: "Alerts", icon: "bell.badge.fill", fill: SE.navy, ink: .white) {
                        Analytics.shared.track("alerts_open", ["signed_in": auth.isSignedIn, "src": "results"])
                        if auth.isSignedIn { showAlerts = true } else { showSignIn = true }
                    }
                    .accessibilityIdentifier("pill-Alerts")
                }
            }
            .padding(.bottom, 92)
        }
        .overlay(alignment: .top) {
            if let toast {
                Text(toast).font(.se(16, .semibold)).foregroundStyle(.white).padding(.horizontal, 16).padding(.vertical, 10)
                    .background(SE.ink.opacity(0.9)).clipShape(Capsule()).padding(.top, 120)
                    .task { try? await Task.sleep(for: .seconds(2)); self.toast = nil }
            }
        }
        .toolbar { ToolbarItem(placement: .principal) { ResultsHeader(query: query,
            onLocation: { Analytics.shared.track("location_open", ["src": "results"]); showLocation = true },
            onFilter: { Analytics.shared.track("filters_open", ["src": "results"]); showFilters = true },
            edit: $query) } }
        .sheet(isPresented: $showFilters) { FiltersSheet(query: $query) }
        .sheet(isPresented: $showLocation) { LocationPickerView(selected: $query.locations) }
        .sheet(isPresented: $showAlerts) { AlertsSheet(query: query) }
        .sheet(isPresented: $showSignIn, onDismiss: {
            if auth.isSignedIn { showAlerts = true }
        }) { EmailSignInView(offersSocialSignIn: true) }
        .perfFirstMovement("results")
        .onAppear { if CommandLine.arguments.contains("--open-alerts") { showAlerts = true } }
        .task(id: query) { run() }
        .onChange(of: store.loaded) { _, _ in run() }
        .swipeBackEnabled()
    }

    /// The re-rentals that belong in this feed: New York only, and only in
    /// a borough the results are in. Recomputed with the results, not per row.
    @State private var rerentalPool: [FeaturedListing] = []

    private var emptyHint: String {
        let n = query.normalized
        if n.hcrOnly { return "HousingSearch.ny.gov lists about 50 open lotteries and waitlists in the city at a time. Clear the other Show boxes and the price range to see them all." }
        if n.availableOnly { return "Only about 2,000 of the 47,000 rent-stabilized buildings have a recent advertised rent. Untick Available now to see every building here." }
        if n.vouchersOnly { return "Voucher-friendly buildings are sparse outside upper Manhattan, the Bronx and central Brooklyn. Try clearing the price range." }
        return "Widen the price range or clear a filter."

    }
    private func run() {
        guard store.loaded else { return }
        results = SearchEngine.run(query, store: store)
        shown = 30
        rerentalPool = store.city.isNYC ? RerentalFeed.pool(store.featured.listings, for: results) : []
        // The list itself: how many matched, how the search was shaped, and
        // whether re-rentals were in the mix — the denominator for the funnel.
        var p = Analytics.shape(query); p["results"] = results.count; p["rerental_pool"] = rerentalPool.count
        Analytics.shared.track("results_view", p)
    }
}
