import SwiftUI

/// The Events tab (owner, 2026-09-22): upcoming tenant clinics, resource fairs
/// and HPD / Mayor's Public Engagement Unit housing events, soonest first,
/// grouped by day, filterable by borough. Everyone sees it — no account needed
/// to know a free clinic is on Saturday. Two columns on an iPad. See EventsFeed.
struct EventsView: View {
    @Environment(\.openURL) private var openURL
    @Environment(\.horizontalSizeClass) private var sizeClass
    @AppStorage("events.borough") private var borough = ""   // "" = all five
    private var feed: EventsFeed { EventsFeed.shared }

    private var shown: [EventsFeed.Event] { EventsFeed.filter(feed.events, borough: borough.isEmpty ? nil : borough) }
    private var columns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: 12, alignment: .top), count: sizeClass == .regular ? 2 : 1)
    }

    var body: some View {
        VStack(spacing: 0) {
            NavyHeader {
                VStack(alignment: .leading, spacing: 2) {
                    Text("Events").font(.se(24, .bold)).foregroundStyle(.white)
                    Text("Tenant clinics & housing help from the City").font(.se(15, .semibold)).foregroundStyle(.white.opacity(0.85))
                }
                .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.bottom, 12)
            }
            boroughChips
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    if feed.loading && feed.events.isEmpty {
                        ProgressView().tint(SE.royal).frame(maxWidth: .infinity).padding(.top, 40)
                    } else if feed.loadFailed {
                        message("Couldn't load events", "Check your connection and pull down to try again.")
                    } else if feed.loaded && shown.isEmpty {
                        message(borough.isEmpty ? "No events listed right now" : "Nothing in \(borough) right now",
                                borough.isEmpty
                                    ? "When HPD or the Mayor's Public Engagement Unit lists a tenant clinic or housing fair, it shows up here."
                                    : "Try All boroughs, or check back — the City adds events every week.")
                    }
                    ForEach(EventsFeed.byDay(shown), id: \.day) { group in
                        Text(EventsFeed.dayTitle(group.day)).font(.se(17, .bold)).foregroundStyle(SE.ink)
                            .padding(.horizontal, 16).padding(.top, 6)
                            .accessibilityAddTraits(.isHeader)
                        LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
                            ForEach(group.events) { card($0) }
                        }
                        .padding(.horizontal, sizeClass == .regular ? 16 : 0)
                    }
                    if !shown.isEmpty {
                        Text("Listed by NYC Housing Preservation & Development and the Mayor's Public Engagement Unit on the City's events calendar. Details and registration are on nyc.gov.")
                            .font(.se(14)).foregroundStyle(SE.ink3).padding(.horizontal, 16).padding(.top, 4)
                    }
                    Color.clear.frame(height: 120)
                }
                .padding(.top, 12)
            }
            .refreshable { await feed.refresh() }
            .background(SE.canvas)
        }
        .background(SE.canvas)
        .task {
            if !feed.loaded { await feed.refresh() }
            Analytics.shared.track("events_view", ["count": feed.events.count])
        }
    }

    private var boroughChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                chip("All", value: "")
                ForEach(["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"], id: \.self) { chip($0, value: $0) }
            }
            .padding(.horizontal, 16).padding(.vertical, 10)
        }
        .background(Color.white)
    }

    private func chip(_ title: String, value: String) -> some View {
        let on = borough == value
        return Button {
            borough = value
            Analytics.shared.track("events_borough", ["b": value.isEmpty ? "all" : value])
        } label: {
            Text(title).font(.se(15, .semibold)).lineLimit(1)
                .foregroundStyle(on ? Color.white : SE.ink)
                .padding(.horizontal, 14).padding(.vertical, 8)
                .background(on ? SE.royal : SE.badge)
                .clipShape(Capsule())
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("events-boro-\(title)")
        .accessibilityAddTraits(on ? .isSelected : [])
    }

    private func card(_ e: EventsFeed.Event) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(e.title).font(.se(19, .bold)).foregroundStyle(SE.ink).fixedSize(horizontal: false, vertical: true)
            Label(EventsFeed.timeLine(e), systemImage: "clock").font(.se(15, .semibold)).foregroundStyle(SE.ink2)
            if let a = e.address, !a.isEmpty {
                Label(a, systemImage: "mappin.and.ellipse").font(.se(15)).foregroundStyle(SE.ink2)
            }
            if let h = EventsFeed.hostLine(e) {
                Text("Hosted by \(h)").font(.se(14)).foregroundStyle(SE.ink3)
            }
            if let d = e.description, !d.isEmpty {
                Text(d).font(.se(15)).foregroundStyle(SE.ink).lineLimit(3)
            }
            HStack(spacing: 10) {
                if let a = e.address, !a.isEmpty,
                   let url = URL(string: "https://maps.apple.com/?q=" + (a.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")) {
                    SEOutlineButton(title: "Directions", icon: "arrow.triangle.turn.up.right.diamond") {
                        Analytics.shared.track("event_open", ["kind": "directions", "id": e.id])
                        openURL(url)
                    }
                }
                if let s = e.url, s.hasPrefix("https://"), let url = URL(string: s) {
                    SEPrimaryButton(title: "Details", icon: "arrow.up.right") {
                        Analytics.shared.track("event_open", ["kind": "details", "id": e.id])
                        openURL(url)
                    }
                }
            }
            .padding(.top, 6)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
        // A container, so the id stays on the card instead of being copied
        // onto every text and button inside it (26 "cards" for 3 events).
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("event-card")
    }

    private func message(_ title: String, _ body: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text(body).font(.se(16)).foregroundStyle(SE.ink2)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white)
        .accessibilityIdentifier("events-empty")
    }
}
