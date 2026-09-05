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
    var body: some View {
        HStack(spacing: 8) {
            Button(action: onLocation) {
                HStack(spacing: 8) {
                    Image(systemName: "mappin").font(.system(size: 13, weight: .bold)).foregroundStyle(SE.royal)
                    Text(query.shortLocationLabel(boroughOf: store.boroughOfNeighborhood)).font(.se(16)).foregroundStyle(SE.ink).lineLimit(1).truncationMode(.tail).frame(minWidth: 70, alignment: .leading)
                        .accessibilityIdentifier("results-location")
                    Text(query.summary).font(.se(16)).foregroundStyle(SE.ink2).lineLimit(1).layoutPriority(1)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 10).frame(height: 40)
                .background(Color.white).clipShape(RoundedRectangle(cornerRadius: 2))
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("results-location-field")

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
        .frame(width: UIScreen.main.bounds.width - 92)
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
    @State var query: SearchQuery
    @State private var results: [Building] = []
    @State private var shown = 30
    @State private var showFilters = false
    @State private var showLocation = false
    @State private var showAlerts = false
    @State private var showSignIn = false
    @State private var showSave = false
    @State private var saveName = ""
    @State private var toast: String?

    var body: some View {
        VStack(spacing: 0) {
            NavyBarBackdrop()
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("\(results.count.formatted()) \(query.resultNoun)\(results.count == 1 ? "" : "s")")
                            .font(.se(24, .bold)).foregroundStyle(SE.ink).lineLimit(1).minimumScaleFactor(0.75)
                            .accessibilityIdentifier("results-count")
                        Spacer()
                        Menu {
                            ForEach(SortOrder.allCases, id: \.self) { s in
                                Button { query.sort = s } label: {
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

                    ForEach(results.prefix(shown)) { b in
                        BuildingCard(building: b)
                            .padding(.horizontal, 16)
                            .onAppear { if b.bbl == results[min(shown, results.count) - 1].bbl, shown < results.count { shown += 30 } }
                    }
                    Color.clear.frame(height: 150)
                }
            }
            .background(SE.canvas)
        }
        .background(SE.canvas)
        .overlay(alignment: .bottom) {
            HStack(spacing: 14) {
                FloatingPill(title: "Map", icon: "map.fill") {
                    nav.searchPath.append(.map(query))
                }
                // Available-now and Accepting-vouchers are the two views where
                // "tell me when one opens" means something; the alert is the
                // site's borough alert, so it needs an account (an email).
                if query.normalized.availableOnly || query.normalized.vouchersOnly {
                    FloatingPill(title: "Alerts", icon: "bell.badge.fill") {
                        if auth.isSignedIn { showAlerts = true } else { showSignIn = true }
                    }
                    .accessibilityIdentifier("pill-Alerts")
                }
                // Three pills do not fit "Save search" on a 390pt phone; with
                // Alerts beside it the save pill goes by its short name.
                FloatingPill(title: activity.isSearchSaved(query) ? (hasAlertsPill ? "Saved" : "Search saved") : (hasAlertsPill ? "Save" : "Save search"), icon: "bell.fill", fill: SE.navy, ink: .white) {
                    if activity.isSearchSaved(query) { toast = "Already in My Activity" }
                    else { saveName = defaultName; showSave = true }
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
        .toolbar { ToolbarItem(placement: .principal) { ResultsHeader(query: query, onLocation: { showLocation = true }, onFilter: { showFilters = true }) } }
        .sheet(isPresented: $showFilters) { FiltersSheet(query: $query) }
        .sheet(isPresented: $showLocation) { LocationPickerView(selected: $query.locations) }
        .sheet(isPresented: $showAlerts) { AlertsSheet(query: query) }
        .sheet(isPresented: $showSignIn) { EmailSignInView() }
        .onChange(of: auth.isSignedIn) { _, on in if on, showSignIn { showSignIn = false; showAlerts = true } }
        .onAppear { if CommandLine.arguments.contains("--open-alerts") { showAlerts = true } }
        .alert("Save this search", isPresented: $showSave) {
            TextField("Name", text: $saveName)
            Button("Save") { activity.saveSearch(query, name: saveName.isEmpty ? defaultName : saveName, count: results.count); toast = "Saved to My Activity" }
            Button("Cancel", role: .cancel) {}
        } message: { Text("Find it again under My Activity › Searches.") }
        .task(id: query) { run() }
        .onChange(of: store.loaded) { _, _ in run() }
        .swipeBackEnabled()
    }

    private var hasAlertsPill: Bool { query.normalized.availableOnly || query.normalized.vouchersOnly }
    private var defaultName: String { "\(query.normalized.hcrOnly ? "HCR lotteries" : (query.normalized.availableOnly ? "Available" : (query.normalized.vouchersOnly ? "Vouchers" : "Stabilized"))) · \(query.locationLabel)" }
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
    }
}
