import SwiftUI

@main
struct FindACribApp: App {
    /// UIKit delegate for the APNs registration callbacks (PushService.swift).
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @State private var store = DataStore()
    @State private var activity = Activity()
    @State private var nav = AppNav()
    @State private var auth = AuthService()
    @State private var plus = PlusStore()
    @Environment(\.scenePhase) private var scenePhase
    @State private var wasBackgrounded = false

    /// Opens a deep link now, or once the buildings have loaded.
    private func route(_ link: DeepLink) {
        Analytics.shared.track("deep_link", ["to": "\(link)"])
        if store.buildings.isEmpty { nav.pending = link } else { link.open(nav: nav, store: store) }
    }

    var body: some Scene {
        WindowGroup {
            // --splash-preview: the letter splash on a loop, nothing else, so
            // it can be looked at and recorded before it replaces anything.
            if CommandLine.arguments.contains("--splash-preview") {
                LetterSplash(loop: true)
            } else {
            // The splash holds until a signed-in user's session is confirmed,
            // so no screen ever renders as signed out first.
            LaunchPresentation(isReady: { [auth] in auth.restored }) { RootView() }
                .environment(store)
                .environment(activity)
                .environment(nav)
                .environment(auth)
                .environment(plus)
                .task {
                    await auth.restore()
                    auth.activity = activity
                    plus.auth = auth; auth.plus = plus
                    Analytics.shared.auth = auth
                    Analytics.shared.city = store.city.id
                    activity.analytics = Analytics.shared
                    Analytics.shared.track("app_open", ["first": Analytics.shared.isFirstLaunch])
                    plus.start()
                    Ads.shared.start()
                    Metrics.shared.start()
                    KeyboardDismiss.install()
                    activity.remoteToggle = { [weak auth] bbl, on in auth?.remoteToggle(bbl: bbl, saved: on) }
                    await store.load()
                    Perf.startWatchdog()
                    LaunchArgs.apply(to: nav, store: store)
                    AppNav.current = nav
                    if let l = AppNav.launchLink { AppNav.launchLink = nil; nav.pending = nav.pending ?? l }
                    if let p = nav.pending { nav.pending = nil; p.open(nav: nav, store: store) }
                    ReviewPrompt.shared.applyLaunchArguments()
                    PushService.shared.applyLaunchArguments()
                    // Keep the push token current when permission already
                    // exists (tokens rotate); never asks.
                    PushService.shared.auth = auth; PushService.shared.nav = nav
                    LotteryFeed.shared.auth = auth
                    await LotteryFeed.shared.refresh()
                    if CommandLine.arguments.contains("--tab"), CommandLine.arguments.contains("lotteries"), store.city.isNYC { nav.tab = .lotteries }
                    await PushService.shared.reregisterIfAuthorized()
                    // The one notifications card, after the launch settles.
                    try? await Task.sleep(for: .seconds(2))
                    await PushService.shared.offerAtLaunchIfNeeded()
                    ReviewPrompt.shared.appOpened(signedIn: auth.isSignedIn, pushCardShowing: PushService.shared.launchPrompt)
                }
                // Back from the background counts as an open for the scheduled
                // rating ask; .inactive alone (a sign-in sheet, Control Center) does not.
                .onChange(of: scenePhase) { _, phase in
                    if phase == .background { wasBackgrounded = true }
                    if phase == .active { KeyboardDismiss.install() }
                    if phase == .active, wasBackgrounded {
                        wasBackgrounded = false
                        Task { await LotteryFeed.shared.refresh() }
                        ReviewPrompt.shared.appOpened(signedIn: auth.isSignedIn, pushCardShowing: PushService.shared.launchPrompt)
                    }
                }
                .task { await auth.listen() }
                // A token that arrived signed out is filed once there is an account.
                // Switching to a city without the Lotteries tab must not leave
                // the app parked on it.
                .onChange(of: store.city.id) { _, _ in
                    if !nav.tab.available(in: store.city) { nav.tab = .search }
                }
                .onChange(of: auth.isSignedIn) { _, on in
                    if on { Task { await PushService.shared.reregisterIfAuthorized() } }
                    Task { await LotteryFeed.shared.refresh() }
                }
                .onOpenURL { url in
                    Analytics.shared.launchSource = Analytics.source(for: url)
                    Analytics.shared.track("open_url", ["src": Analytics.shared.launchSource])
                    // Auth callbacks share the scheme; only known paths route.
                    if let link = DeepLink(url) { route(link) }
                }
                // Handoff from findacrib.com or another device, and Spotlight.
                .onContinueUserActivity(ActivityType.building) { a in
                    if let u = a.webpageURL, let link = DeepLink(u) { route(link) }
                }
                .onContinueUserActivity(ActivityType.lotteries) { _ in route(.lotteries) }
                .onContinueUserActivity(NSUserActivityTypeBrowsingWeb) { a in
                    if let u = a.webpageURL, let link = DeepLink(u) { route(link) }
                }
                .preferredColorScheme(.light)   // StreetEasy ships light-only; the palette is tuned for it
            }
        }
    }
}

enum Tab: String, CaseIterable { case search = "Search", lotteries = "Lotteries", casa = "Your Crib", activity = "My Activity", profile = "Profile"
    /// The raw value is the analytics and accessibility id; this is the label.
    var title: String {
        switch self {
        case .search: String(localized: "Search")
        case .lotteries: String(localized: "Lotteries")
        case .casa: String(localized: "Your Crib")
        case .activity: String(localized: "My Activity")
        case .profile: String(localized: "Profile")
        }
    }
    var icon: String { switch self { case .search: "magnifyingglass"; case .lotteries: "ticket"; case .casa: "house"; case .activity: "heart"; case .profile: "person" } }
    /// Lotteries began as New York's feeds (Housing Connect, the HPD marketing
    /// agents); Your Crib reads New York's 311 and NYPD data. Elsewhere they
    /// would be empty, so those cities do not get the tabs.
    var nycOnly: Bool { self == .lotteries || self == .casa }
    /// Lotteries also shows where a place has openings of its own — LA, SF,
    /// California, New Jersey (OpeningsFeed, owner 2026-09-24). Your Crib
    /// (owner, 2026-10-15) replaced the Events tab and is New York only.
    func available(in city: City) -> Bool {
        switch self {
        case .lotteries: city.hasLotteries
        case .casa: city.isNYC
        default: true
        }
    }
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
    var casaPath: [Route] = []
    /// Opened by the Profile screen; set by the --paywall launch argument.
    var showPaywall = false
    /// Opened by the Profile screen (after sign-in if needed); set by the
    /// notifications card for someone who has no alerts yet.
    var showAlerts = false
    /// A renter tool to open on Profile (deep link, Siri, widget).
    var openTool: HomeTool?
    /// The live navigator, for App Intents (Siri) that open the app.
    static weak var current: AppNav?
    /// A link that arrived before the buildings loaded: opened after.
    var pending: DeepLink?
    /// The building whose page should open on its Managing agent section:
    /// the card's Owner Phone button (owner, 2026-10-17). Cleared once used.
    var scrollToAgent: String?
    /// Set by a Siri intent that launched the app before AppNav existed.
    static var launchLink: DeepLink?
}

/// `--tab activity|profile`, `--route results|map|detail[:bbl]|detail-agent[:bbl]` — used by the
/// screenshot script and UI tests to land on a screen directly.
enum LaunchArgs {
    @MainActor static func apply(to nav: AppNav, store: DataStore) {
        let a = CommandLine.arguments
        func val(_ flag: String) -> String? { a.firstIndex(of: flag).flatMap { $0 + 1 < a.count ? a[$0 + 1] : nil } }
        if let t = val("--tab") { nav.tab = t == "activity" ? .activity : (t == "profile" ? .profile : (t == "casa" ? .casa : .search)) }
        // `--city la|sf|dc` — land in another city, for the screenshot script
        // and the UI tests. Only NYC ships a seed in the bundle, so the others
        // have to download first; the route has to wait for that, or it
        // resolves against New York's buildings and opens the wrong one.
        if a.contains("--paywall") { nav.tab = .profile; nav.showPaywall = true }
        // The price sheet remembers Increments vs Custom across launches, on
        // purpose. A UI test of the wheels inherited whatever the test before
        // it left (iPad, 2026-09-23: it opened on Custom and found no wheels),
        // so a test can ask for a known starting mode.
        if a.contains("--price-increments") { UserDefaults.standard.set(false, forKey: "priceEntryMode") }
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
        var q = SearchQuery(); q.mode = .stabilized; q.locations = [.borough("Bk")]
        // Brooklyn is New York's default and matches
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
            var withRecord: String? = nil
            if !store.city.isNYC {
                withRecord = store.buildings.first { b in
                    guard let rec = store.records[b.bbl] else { return false }
                    return rec.owner != nil || rec.ev != nil || rec.violations != nil
                }?.bbl
            }
            let asked: String? = r.split(separator: ":").dropFirst().first.map(String.init)
            let fallback: String = SearchEngine.run(q, store: store).first?.bbl
                ?? store.buildings.first?.bbl ?? ""
            let bbl: String = asked ?? withRecord ?? fallback
            nav.searchPath = [.results(q), .building(bbl)]
            // detail-agent[:bbl] — as if Owner Phone was tapped.
            if r.hasPrefix("detail-agent") { nav.scrollToAgent = bbl }
        }
    }
}
