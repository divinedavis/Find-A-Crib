import SwiftUI

struct RootView: View {
    @Environment(AppNav.self) private var nav
    @Environment(DataStore.self) private var store

    var body: some View {
        let _ = Perf.mark("RootView.body")
        @Bindable var nav = nav
        return ZStack(alignment: .bottom) {
            // Search stays alive behind the other tabs, so coming back to it
            // lands where you left off: same scroll spot in the results, same
            // map (owner, 2026-10-20). The other tabs rebuild as before.
            NavigationStack(path: $nav.searchPath) {
                // Opacity per screen, not just on the stack: each pushed screen
                // is its own hosting controller, so VoiceOver (and the audit)
                // read straight through the stack's opacity and
                // .accessibilityHidden. SwiftUI drops a zero-opacity view from
                // accessibility itself; an .accessibilityHidden(false) here
                // would instead un-hide each screen's decorative views.
                SearchHomeView().opacity(nav.tab == .search ? 1 : 0)
                    .navigationDestination(for: Route.self) { RouteView(route: $0).opacity(nav.tab == .search ? 1 : 0) }
            }
            .toolbar(.hidden, for: .navigationBar)
            .opacity(nav.tab == .search ? 1 : 0)
            .allowsHitTesting(nav.tab == .search)
            .accessibilityHidden(nav.tab != .search)

            Group {
                switch nav.tab {
                case .search:
                    EmptyView()
                case .activity:
                    NavigationStack(path: $nav.activityPath) {
                        MyActivityView().navigationDestination(for: Route.self) { RouteView(route: $0) }
                    }
                case .lotteries:
                    NavigationStack { LotteriesView() }
                case .casa:
                    NavigationStack(path: $nav.casaPath) {
                        CasaView().navigationDestination(for: Route.self) { RouteView(route: $0) }
                    }
                case .profile:
                    NavigationStack(path: $nav.profilePath) {
                        ProfileView().navigationDestination(for: Route.self) { RouteView(route: $0) }
                    }
                }
            }
            .toolbar(.hidden, for: .navigationBar)

            if !nav.hideTabBar {
                ChromeTabBar(selected: $nav.tab)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: nav.hideTabBar)
        // A screen pushed or popped starts with its header and the bar showing.
        .onChange(of: nav.searchPath.count) { _, _ in nav.chromeProgress = 0; nav.tabBarCompact = false }
        // Search no longer leaves the screen when another tab opens, so its
        // building page's onDisappear doesn't run: set the bar per tab here.
        // Back on Search, a building page on top still hides it.
        .onChange(of: nav.tab) { _, t in
            nav.chromeProgress = 0
            nav.tabBarCompact = false
            if t == .search, case .building? = nav.searchPath.last { nav.hideTabBar = true } else { nav.hideTabBar = false }
        }
        // A tapped alert notification opens here, on all of its items.
        .sheet(item: Binding(get: { PushService.shared.incoming }, set: { PushService.shared.incoming = $0 })) { push in
            AlertPushSheet(push: push)
        }
        // The one launch-time ask (PushService.offerAtLaunchIfNeeded).
        .alert("Get alerts on this phone?", isPresented: Binding(get: { PushService.shared.launchPrompt },
                                                                  set: { PushService.shared.launchPrompt = $0 })) {
            Button("Turn on") { PushService.shared.acceptLaunchPrompt() }
            Button("Not now", role: .cancel) { PushService.shared.snoozeLaunchPrompt() }
        } message: {
            Text(PushService.shared.promptForSubscriber
                 ? "You're signed up for borough alerts. Allow notifications and your lotteries and re-rentals land here too — not just in your email."
                 : "Hear about new rent-stabilized lotteries and re-rentals in your borough. Allow notifications, then pick your boroughs — ten seconds.")
        }
        // TestFlight never shows Apple's rating sheet, so a beta build shows
        // a look-alike at the same moment instead, inside the app
        // (ReviewPrompt.isBeta, RatingPreview).
        .overlay {
            if ReviewPrompt.shared.showBetaStandIn {
                RatingPreview(isPresented: Binding(get: { ReviewPrompt.shared.showBetaStandIn },
                                                   set: { ReviewPrompt.shared.showBetaStandIn = $0 }))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: ReviewPrompt.shared.showBetaStandIn)
        // Type still follows the user's text-size setting, but stops at xLarge:
        // the layouts are StreetEasy's fixed compositions (segment strips,
        // three-up fact rows, price lines) and the accessibility sizes wrap
        // them into columns of single words.
        .dynamicTypeSize(...DynamicTypeSize.xLarge)
        .overlay {
            if let err = store.loadError, !store.loaded {
                VStack(spacing: 12) {
                    Text("Couldn't load building data").font(.se(20, .bold))
                    Text(err).font(.se(15)).foregroundStyle(SE.ink3).multilineTextAlignment(.center)
                }.padding(24).background(Color.white).clipShape(RoundedRectangle(cornerRadius: 8)).padding()
            }
        }
    }
}

struct RouteView: View {
    let route: Route
    @Environment(DataStore.self) private var store
    var body: some View {
        switch route {
        // .id(q): a destination keeps its identity by position in the path, so
        // rewriting `.results(old)` to `.results(new)` in place would otherwise
        // leave the old view — and its @State copy of the query — on screen.
        case .results(let q): ResultsView(query: q).id(q)
        case .map(let q): MapResultsView(query: q).id(q)
        case .building(let bbl):
            if let b = store.byBBL[bbl] { BuildingDetailView(building: b) }
            else { Text("Building not found").font(.se(18)) }
        case .hpdRecords(let bbl, let kind):
            if let b = store.byBBL[bbl] { HPDRecordsView(building: b, kind: kind) }
            else { Text("Building not found").font(.se(18)) }
        }
    }
}

/// The floating pill tab bar: a clear glass capsule (owner, 2026-10-22), the
/// selected item sitting in a frosted white disc with royal-blue icon and label.
struct PillTabBar: View {
    @Binding var selected: Tab
    @Environment(DataStore.self) private var store
    /// Lotteries is New York's: Housing Connect and the HPD marketing agents'
    /// re-rentals, matched to boroughs. In LA, SF or DC it would list another
    /// city's openings, so it is not offered there (owner, 2026-09-19).
    private var tabs: [Tab] { Tab.allCases.filter { $0.available(in: store.city) } }
    /// Five tabs at 86 pt is 438 pt — wider than any iPhone. With a fifth tab
    /// (Events 2026-09-22, Your Crib since 2026-10-15) the items narrow to fit
    /// a 375 pt screen; four keep their old width.
    private var itemWidth: CGFloat {
        if let w = TabBarSize.current.barWidth { return (w - 8) / CGFloat(tabs.count) }
        return tabs.count >= 5 ? 72 : 86
    }
    private var size: TabBarSize { .current }
    var body: some View {
        HStack(spacing: 0) {
            ForEach(tabs, id: \.self) { tab in
                let on = selected == tab
                Button { if selected != tab { Analytics.shared.track("tab", ["to": tab.rawValue]) }; selected = tab } label: {
                    VStack(spacing: 4) {
                        Image(systemName: tab.icon).font(.system(size: size.icon, weight: on ? .semibold : .regular))
                        Text(tab.title).font(.se(size.label ?? (tabs.count >= 5 ? 13 : 14), .semibold)).lineLimit(1).minimumScaleFactor(0.7)
                    }
                    .foregroundStyle(on ? (holiday?.onFill ?? SE.royal) : SE.ink)
                    .frame(width: itemWidth, height: size.itemHeight)
                    .background { if on { selectedFill } }
                    .clipShape(Capsule())
                    // The whole 72 x 66 pill is the button, selected or not.
                    // Without it an unselected tab shrank to its icon and
                    // label once its clear background went (2026-10-23), and
                    // the end tabs stopped taking taps.
                    .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("tab-\(tab.rawValue)")
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(4)
        .lightGlass(in: Capsule())
    }

    /// Frosted white every day; on a holiday the day's colours fill the
    /// selected pill (Marracat's tab bar, style B).
    private let holiday = Skyline.holiday
    @ViewBuilder private var selectedFill: some View {
        if let holiday {
            LinearGradient(colors: holiday.colors, startPoint: .topLeading, endPoint: .bottomTrailing)
        } else {
            Color.white.opacity(0.7)
        }
    }
}

/// Tab bar sizes for the minimize preview (2026-11-05). `.ours` is the
/// shipping bar (368 x 74 with five tabs); `.instagram` is Instagram's
/// measured from the owner's screen recording: 357 x 59 pt full,
/// 301 x 49 shrunk (84%, about its centre). Launch with
/// `--tabbar-size instagram` to see it.
enum TabBarSize {
    case ours, instagram
    static let current: TabBarSize =
        ProcessInfo.processInfo.arguments.contains("instagram") ? .instagram : .ours
    var barWidth: CGFloat? { self == .instagram ? 357 : nil }
    var itemHeight: CGFloat { self == .instagram ? 51 : 66 }
    var icon: CGFloat { self == .instagram ? 19 : 22 }
    var label: CGFloat? { self == .instagram ? 10.5 : nil }
    /// Instagram's shrunk bar is 84% of its full one, both ways.
    static let compactScale: CGFloat = 0.84
}

/// The tab bar. It stays on screen while a list scrolls: only the
/// screen's header slides away (owner, 2026-11-05). Scrolling down shrinks
/// it to 84%, scrolling up brings it back to full size (Instagram-style).
private struct ChromeTabBar: View {
    @Binding var selected: Tab
    @Environment(AppNav.self) private var nav

    var body: some View {
        PillTabBar(selected: $selected)
            .scaleEffect(nav.tabBarCompact ? TabBarSize.compactScale : 1)
            .padding(.bottom, 6)
    }
}
