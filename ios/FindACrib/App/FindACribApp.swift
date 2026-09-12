import SwiftUI

@main
struct FindACribApp: App {
    @State private var store = DataStore()
    @State private var activity = Activity()
    @State private var nav = AppNav()
    @State private var auth = AuthService()
    @State private var plus = PlusStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environment(store)
                .environment(activity)
                .environment(nav)
                .environment(auth)
                .environment(plus)
                .task {
                    auth.activity = activity
                    plus.auth = auth; auth.plus = plus
                    Analytics.shared.auth = auth
                    Analytics.shared.city = store.city.id
                    activity.analytics = Analytics.shared
                    Analytics.shared.track("app_open")
                    plus.start()
                    activity.remoteToggle = { [weak auth] bbl, on in auth?.remoteToggle(bbl: bbl, saved: on) }
                    await store.load()
                    LaunchArgs.apply(to: nav, store: store)
                }
                .task { await auth.listen() }
                .preferredColorScheme(.light)   // StreetEasy ships light-only; the palette is tuned for it
        }
    }
}

enum Tab: String, CaseIterable { case search = "Search", activity = "My Activity", profile = "Profile"
    var icon: String { switch self { case .search: "magnifyingglass"; case .activity: "heart"; case .profile: "person" } }
}

enum Route: Hashable {
    case results(SearchQuery)
    case map(SearchQuery)
    case building(String)
    case hpdRecords(String, HPDRecordsView.Kind)   // bbl + violations|complaints
}

@Observable @MainActor
final class AppNav {
    var tab: Tab = .search
    var hideTabBar = false
    var searchPath: [Route] = []
    var activityPath: [Route] = []
    var profilePath: [Route] = []
    /// Opened by the Profile screen; set by the --paywall launch argument.
    var showPaywall = false
}

/// `--tab activity|profile`, `--route results|map|detail[:bbl]` — used by the
/// screenshot script and UI tests to land on a screen directly.
enum LaunchArgs {
    @MainActor static func apply(to nav: AppNav, store: DataStore) {
        let a = CommandLine.arguments
        func val(_ flag: String) -> String? { a.firstIndex(of: flag).flatMap { $0 + 1 < a.count ? a[$0 + 1] : nil } }
        if let t = val("--tab") { nav.tab = t == "activity" ? .activity : (t == "profile" ? .profile : .search) }
        // `--city la|sf|dc` — land in another city, for the screenshot script
        // and the UI tests. Only NYC ships a seed in the bundle, so the others
        // have to download first; the route has to wait for that, or it
        // resolves against New York's buildings and opens the wrong one.
        if a.contains("--paywall") { nav.tab = .profile; nav.showPaywall = true }
        if let c = val("--city"), c != store.city.id {
            let target = City.find(c)
            Task { @MainActor in
                await store.switchCity(to: target, persist: false)
                route(val("--route"), nav: nav, store: store)
            }
            return
        }
        route(val("--route"), nav: nav, store: store)
    }

    @MainActor private static func route(_ r: String?, nav: AppNav, store: DataStore) {
        guard let r else { return }
        var q = SearchQuery(); q.mode = .stabilized; q.availableOnly = true; q.locations = [.borough("Bk")]
        // Brooklyn and "available only" are New York's defaults and match
        // nothing anywhere else; outside NYC start from the unfiltered city.
        if !store.city.isNYC { q = SearchQuery() }
        if r == "results" { nav.searchPath = [.results(q)] }
        else if r == "hcr" { var h = SearchQuery(); h.hcrOnly = true; nav.searchPath = [.results(h)] }
        else if r == "map" { nav.searchPath = [.results(q), .map(q)] }
        else if r == "mapall" { let a = SearchQuery(); nav.searchPath = [.results(a), .map(a)] }
        else if r.hasPrefix("hpd") {
            // hpd[:bbl] — the violations screen, for screenshots.
            let bbl = r.split(separator: ":").dropFirst().first.map(String.init)
                ?? store.buildings.first { ($0.h?.violations?.open ?? 0) > 5 }?.bbl ?? store.buildings.first?.bbl ?? ""
            nav.searchPath = [.results(q), .building(bbl), .hpdRecords(bbl, .violations)]
        }
        else if r.hasPrefix("detail") {
            // Outside NYC, prefer a building that actually carries a record —
            // a screenshot or a test of the record panel on one of the many
            // parcels with no case history proves nothing.
            let withRecord = store.city.isNYC ? nil
                : store.buildings.first { $0.h?.owner != nil || $0.h?.ev != nil || $0.h?.violations != nil }?.bbl
            let bbl = r.split(separator: ":").dropFirst().first.map(String.init)
                ?? withRecord
                ?? SearchEngine.run(q, store: store).first?.bbl ?? store.buildings.first?.bbl ?? ""
            nav.searchPath = [.results(q), .building(bbl)]
        }
    }
}
