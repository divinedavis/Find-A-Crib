import SwiftUI

struct RootView: View {
    @Environment(AppNav.self) private var nav
    @Environment(DataStore.self) private var store

    var body: some View {
        let _ = Perf.mark("RootView.body")
        @Bindable var nav = nav
        return ZStack(alignment: .bottom) {
            Group {
                switch nav.tab {
                case .search:
                    NavigationStack(path: $nav.searchPath) {
                        SearchHomeView().navigationDestination(for: Route.self) { RouteView(route: $0) }
                    }
                case .activity:
                    NavigationStack(path: $nav.activityPath) {
                        MyActivityView().navigationDestination(for: Route.self) { RouteView(route: $0) }
                    }
                case .lotteries:
                    NavigationStack { LotteriesView() }
                case .events:
                    NavigationStack { EventsView() }
                case .profile:
                    NavigationStack(path: $nav.profilePath) {
                        ProfileView().navigationDestination(for: Route.self) { RouteView(route: $0) }
                    }
                }
            }
            .toolbar(.hidden, for: .navigationBar)

            if !nav.hideTabBar {
                PillTabBar(selected: $nav.tab)
                    .padding(.bottom, 6)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(.easeInOut(duration: 0.2), value: nav.hideTabBar)
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
                 ? "You're signed up for borough alerts. Allow notifications and each lottery or re-rental lands here the minute it opens — not just in your email."
                 : "Be told the minute a rent-stabilized lottery or re-rental opens in your borough. Allow notifications, then pick your boroughs — ten seconds.")
        }
        // TestFlight never shows Apple's rating sheet, so a beta build shows
        // this stand-in at the same moment instead (ReviewPrompt.isBeta).
        .alert("Enjoying Find A Crib?", isPresented: Binding(get: { ReviewPrompt.shared.showBetaStandIn },
                                                              set: { ReviewPrompt.shared.showBetaStandIn = $0 })) {
            Button("Rate on the App Store") { ReviewPrompt.shared.openWriteReview() }
            Button("Not now", role: .cancel) {}
        } message: {
            Text("TestFlight build: this is where the App Store rating prompt appears in the released app. Tap through to leave a rating.")
        }
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

/// The floating pill tab bar: white capsule, three items, the selected one
/// sitting in a grey disc with royal-blue icon and label.
struct PillTabBar: View {
    @Binding var selected: Tab
    @Environment(DataStore.self) private var store
    /// Lotteries is New York's: Housing Connect and the HPD marketing agents'
    /// re-rentals, matched to boroughs. In LA, SF or DC it would list another
    /// city's openings, so it is not offered there (owner, 2026-09-19).
    private var tabs: [Tab] { Tab.allCases.filter { $0.available(in: store.city) } }
    /// Five tabs at 86 pt is 438 pt — wider than any iPhone. With the Events
    /// tab (2026-09-22) the items narrow to fit a 375 pt screen; four keep
    /// their old width.
    private var itemWidth: CGFloat { tabs.count >= 5 ? 72 : 86 }
    var body: some View {
        HStack(spacing: 0) {
            ForEach(tabs, id: \.self) { tab in
                let on = selected == tab
                Button { if selected != tab { Analytics.shared.track("tab", ["to": tab.rawValue]) }; selected = tab } label: {
                    VStack(spacing: 4) {
                        Image(systemName: tab.icon).font(.system(size: 22, weight: on ? .semibold : .regular))
                        Text(tab.rawValue).font(.se(tabs.count >= 5 ? 13 : 14, .semibold)).lineLimit(1).minimumScaleFactor(0.7)
                    }
                    .foregroundStyle(on ? SE.royal : SE.ink)
                    .frame(width: itemWidth, height: 66)
                    .background(on ? SE.badge : .clear)
                    .clipShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("tab-\(tab.rawValue)")
                .accessibilityAddTraits(on ? .isSelected : [])
            }
        }
        .padding(4)
        .background(Color.white)
        .clipShape(Capsule())
        .shadow(color: .black.opacity(0.16), radius: 10, y: 3)
    }
}
