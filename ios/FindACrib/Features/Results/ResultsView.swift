import SwiftUI

/// The filter bar StreetEasy puts over its results: a white field carrying
/// back-chevron + location + summary, and a "Filter (n)" button, on navy.
struct ResultsHeader: View {
    @Environment(\.dismiss) private var dismiss
    let query: SearchQuery
    let onFilter: () -> Void
    var body: some View {
        NavyHeader {
            HStack(spacing: 10) {
                Button { dismiss() } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "chevron.left").font(.system(size: 16, weight: .bold)).foregroundStyle(SE.royal)
                        Text(query.locationLabel).font(.se(19)).foregroundStyle(SE.ink).lineLimit(1).truncationMode(.tail).frame(minWidth: 96, alignment: .leading)
                        Text(query.summary).font(.se(19)).foregroundStyle(SE.ink2).lineLimit(1).layoutPriority(1)
                        Spacer(minLength: 0)
                    }
                    .padding(.horizontal, 12).frame(height: 52)
                    .background(Color.white).clipShape(RoundedRectangle(cornerRadius: 2))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("results-back")

                Button(action: onFilter) {
                    HStack(spacing: 6) {
                        Image(systemName: "slider.horizontal.3").font(.system(size: 15, weight: .bold))
                        Text("Filter" + (query.activeFilterCount > 0 ? " (\(query.activeFilterCount))" : ""))
                            .font(.se(18, .bold))
                    }
                    .foregroundStyle(SE.royal)
                    .padding(.horizontal, 12).frame(height: 52)
                    .background(Color.white).clipShape(RoundedRectangle(cornerRadius: 2))
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("results-filter")
            }
            .padding(.horizontal, 16).padding(.top, 8).padding(.bottom, 14)
        }
    }
}

struct ResultsView: View {
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    @Environment(AppNav.self) private var nav
    @State var query: SearchQuery
    @State private var results: [Building] = []
    @State private var shown = 30
    @State private var showFilters = false
    @State private var showSave = false
    @State private var saveName = ""
    @State private var toast: String?

    var body: some View {
        VStack(spacing: 0) {
            ResultsHeader(query: query) { showFilters = true }
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    HStack(alignment: .firstTextBaseline) {
                        Text("\(results.count.formatted()) \(query.mode == .rent ? "rental listing" : (query.mode == .vouchers ? "voucher listing" : "rent-stabilized building"))\(results.count == 1 ? "" : "s")")
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
                            Text("No \(query.mode.noun) match").font(.se(22, .bold))
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
                FloatingPill(title: activity.isSearchSaved(query) ? "Search saved" : "Save search", icon: "bell.fill", fill: SE.navy, ink: .white) {
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
        .sheet(isPresented: $showFilters) { FiltersSheet(query: $query) }
        .alert("Save this search", isPresented: $showSave) {
            TextField("Name", text: $saveName)
            Button("Save") { activity.saveSearch(query, name: saveName.isEmpty ? defaultName : saveName, count: results.count); toast = "Saved to My Activity" }
            Button("Cancel", role: .cancel) {}
        } message: { Text("Find it again under My Activity › Searches.") }
        .task(id: query) { run() }
        .onChange(of: store.loaded) { _, _ in run() }
        .navigationBarBackButtonHidden(true)
    }

    private var defaultName: String { "\(query.mode.rawValue) · \(query.locationLabel)" }
    private var emptyHint: String {
        switch query.mode {
        case .rent: "Only about 2,000 of the 47,000 rent-stabilized buildings have a recent advertised rent. Try the Stabilized tab to see every building here."
        case .stabilized: "Widen the price range or clear the building-size filter."
        case .vouchers: "Voucher listings are sparse outside upper Manhattan, the Bronx and central Brooklyn. Try clearing the price range."
        }
    }
    private func run() {
        guard store.loaded else { return }
        results = SearchEngine.run(query, store: store)
        shown = 30
    }
}
