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
        if a.contains("--paywall") { nav.tab = .profile; nav.showPaywall = true }
        guard let r = val("--route") else { return }
        var q = SearchQuery(); q.mode = .stabilized; q.availableOnly = true; q.locations = [.borough("Bk")]
        if r == "results" { nav.searchPath = [.results(q)] }
        else if r == "hcr" { var h = SearchQuery(); h.hcrOnly = true; nav.searchPath = [.results(h)] }
        else if r == "map" { nav.searchPath = [.results(q), .map(q)] }
        else if r == "mapall" { let a = SearchQuery(); nav.searchPath = [.results(a), .map(a)] }
        else if r.hasPrefix("detail") {
            let bbl = r.split(separator: ":").dropFirst().first.map(String.init)
                ?? SearchEngine.run(q, store: store).first?.bbl ?? store.buildings.first?.bbl ?? ""
            nav.searchPath = [.results(q), .building(bbl)]
        }
    }
}
