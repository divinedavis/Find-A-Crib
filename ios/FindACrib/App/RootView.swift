import SwiftUI

struct RootView: View {
    @Environment(AppNav.self) private var nav
    @Environment(DataStore.self) private var store

    var body: some View {
        @Bindable var nav = nav
        ZStack(alignment: .bottom) {
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
        }
    }
}

/// The floating pill tab bar: white capsule, three items, the selected one
/// sitting in a grey disc with royal-blue icon and label.
struct PillTabBar: View {
    @Binding var selected: Tab
    var body: some View {
        HStack(spacing: 0) {
            ForEach(Tab.allCases, id: \.self) { tab in
                let on = selected == tab
                Button { selected = tab } label: {
                    VStack(spacing: 4) {
                        Image(systemName: tab.icon).font(.system(size: 22, weight: on ? .semibold : .regular))
                        Text(tab.rawValue).font(.se(14, .semibold))
                    }
                    .foregroundStyle(on ? SE.royal : SE.ink)
                    .frame(width: 104, height: 66)
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
