import SwiftUI

struct MyActivityView: View {
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    @Environment(AppNav.self) private var nav
    enum Pane: Hashable { case saved, searches, recent }
    @State private var pane: Pane = .saved

    var body: some View {
        VStack(spacing: 0) {
            NavyHeader {
                Text("My Activity").font(.se(24, .bold)).foregroundStyle(.white)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.bottom, 12)
            }
            SEUnderlineTabs(options: [(Pane.saved, "Saved"), (.searches, "Searches"), (.recent, "Recent")], selection: $pane)
                .padding(.horizontal, 16).padding(.top, 8).background(Color.white)
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 16) {
                    switch pane {
                    case .saved: savedList
                    case .searches: searchesList
                    case .recent: recentList
                    }
                    Color.clear.frame(height: 120)
                }.padding(.top, 16)
            }
            .background(SE.canvas)
        }
        .background(SE.canvas)
    }

    private var savedBuildings: [Building] { activity.saved.compactMap { store.byBBL[$0] } }
    private var recentBuildings: [Building] { activity.recentlyViewed.compactMap { store.byBBL[$0] } }

    @ViewBuilder private var savedList: some View {
        if savedBuildings.isEmpty {
            empty("No saved buildings yet", "Tap the heart on any building to keep it here.", cta: "Start searching")
        } else {
            Text("\(savedBuildings.count) saved").font(.se(22, .bold)).padding(.horizontal, 16)
            ForEach(savedBuildings) { BuildingCard(building: $0).padding(.horizontal, 16) }
        }
    }

    @ViewBuilder private var searchesList: some View {
        if activity.savedSearches.isEmpty {
            empty("No saved searches", "Save a search from the results screen and it lands here.", cta: "Start searching")
        } else {
            ForEach(activity.savedSearches) { s in
                Button { nav.activityPath.append(.results(s.query)) } label: {
                    HStack(spacing: 12) {
                        Image(systemName: "bell.fill").font(.system(size: 18)).foregroundStyle(SE.royal).frame(width: 40, height: 40).background(SE.paleBlue).clipShape(Circle())
                        VStack(alignment: .leading, spacing: 3) {
                            Text(s.name).font(.se(20, .bold)).foregroundStyle(SE.royal).lineLimit(1)
                            Text(s.query.summary).font(.se(16)).foregroundStyle(SE.ink2).lineLimit(1)
                            Text("\(s.resultCount.formatted()) \(s.query.mode.noun) · saved \(Formatters.long.string(from: s.createdAt))").font(.se(14)).foregroundStyle(SE.ink3)
                        }
                        Spacer()
                        Button { activity.deleteSearch(s.id) } label: {
                            Image(systemName: "trash").font(.system(size: 17)).foregroundStyle(SE.ink3).frame(width: 40, height: 40)
                        }.buttonStyle(.plain).accessibilityLabel("Delete saved search")
                    }
                    .padding(14).seCard().padding(.horizontal, 16)
                }.buttonStyle(.plain)
            }
        }
    }

    @ViewBuilder private var recentList: some View {
        if recentBuildings.isEmpty {
            empty("Nothing viewed yet", "Buildings you open show up here.", cta: "Start searching")
        } else {
            HStack {
                Text("Recently viewed").font(.se(22, .bold))
                Spacer()
                Button("Clear") { activity.clearRecents() }.font(.se(17, .semibold)).foregroundStyle(SE.royal)
            }.padding(.horizontal, 16)
            ForEach(recentBuildings) { b in
                Button { nav.activityPath.append(.building(b.bbl)) } label: {
                    HStack(spacing: 12) {
                        BuildingImage(building: b, size: CGSize(width: 300, height: 300)).frame(width: 96, height: 96)
                        VStack(alignment: .leading, spacing: 4) {
                            Text(b.neighborhood).font(.se(15, .semibold)).foregroundStyle(SE.ink2).lineLimit(1)
                            Text(b.address).font(.se(20, .bold)).foregroundStyle(SE.royal).lineLimit(1)
                            if let p = store.price(b) { Text("\(Formatters.dollars(p)) asking rent").font(.se(16, .bold)) }
                            Text("\(b.u.map { "\($0) units" } ?? "") · \(b.openViolations) open violations").font(.se(14)).foregroundStyle(SE.ink3)
                        }
                        Spacer()
                        HeartButton(on: activity.isSaved(b.bbl)) { activity.toggleSaved(b.bbl) }
                    }
                    .padding(.trailing, 8).seCard().padding(.horizontal, 16)
                }.buttonStyle(.plain)
            }
        }
    }

    private func empty(_ title: String, _ sub: String, cta: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.se(22, .bold))
            Text(sub).font(.se(17)).foregroundStyle(SE.ink2)
            SEPrimaryButton(title: cta) { nav.tab = .search }
        }.padding(18).seCard().padding(.horizontal, 16)
    }
}
