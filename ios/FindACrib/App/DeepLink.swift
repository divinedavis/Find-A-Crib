import Foundation

/// Where a link, a widget, Siri or Handoff can send someone (owner,
/// 2026-10-13). One parser for every way in, so they can't disagree:
///
///   findacrib://lotteries                  the Lotteries tab (NYC)
///   findacrib://building/<bbl>             a building's page
///   findacrib://tool/<repair|rent-increase|rights|renewal>
///   findacrib://search                     the Search home
///   https://findacrib.com/#d=<bbl>         the website's building link (Handoff, shared links)
///   https://findacrib.com/#repair …        the website's tool deep links
///
/// In-App Events use findacrib://lotteries (App Store requires a deep link
/// that lands on the event's content).
enum DeepLink: Equatable {
    case lotteries
    case building(String)
    case tool(HomeTool)
    case search

    static let webBase = URL(string: "https://findacrib.com/")!

    init?(_ url: URL) {
        let parts: [String]
        if url.scheme == "findacrib" {
            // findacrib://building/123 -> host "building", path "/123"
            parts = ([url.host ?? ""] + url.pathComponents.filter { $0 != "/" }).filter { !$0.isEmpty }
        } else if url.host?.hasSuffix("findacrib.com") == true {
            let frag = url.fragment ?? ""
            if frag.hasPrefix("d=") { parts = ["building", String(frag.dropFirst(2))] }
            else if let t = Self.webTools[frag] { parts = ["tool", t] }
            else if url.path.hasPrefix("/alerts") { parts = ["lotteries"] }
            else { parts = ["search"] }
        } else { return nil }
        switch parts.first {
        case "lotteries": self = .lotteries
        case "search": self = .search
        case "building":
            let bbl = parts.dropFirst().first.map { $0.filter(\.isNumber) } ?? ""
            guard bbl.count == 10 else { return nil }
            self = .building(bbl)
        case "tool":
            guard let t = parts.dropFirst().first.flatMap(HomeTool.init(rawValue:)) else { return nil }
            self = .tool(t)
        default: return nil
        }
    }

    private static let webTools = ["repair": "repair", "rent-increase": "rent-increase", "rights": "rights", "renewal": "renewal"]

    var url: URL {
        switch self {
        case .lotteries: URL(string: "findacrib://lotteries")!
        case .search: URL(string: "findacrib://search")!
        case .building(let b): URL(string: "findacrib://building/\(b)")!
        case .tool(let t): URL(string: "findacrib://tool/\(t.rawValue)")!
        }
    }

    /// The same place on findacrib.com, for Handoff to a Mac or iPad browser.
    var webURL: URL {
        switch self {
        case .lotteries: URL(string: "https://findacrib.com/alerts/")!
        case .search: DeepLink.webBase
        case .building(let b): URL(string: "https://findacrib.com/#d=\(b)")!
        case .tool(let t): URL(string: "https://findacrib.com/#\(t.rawValue)")!
        }
    }

    @MainActor func open(nav: AppNav, store: DataStore) {
        switch self {
        case .lotteries:
            nav.tab = Tab.lotteries.available(in: store.city) ? .lotteries : .search
        case .search:
            nav.tab = .search; nav.searchPath = []
        case .building(let bbl):
            guard store.byBBL[bbl] != nil else { nav.tab = .search; return }
            nav.tab = .search; nav.searchPath = [.building(bbl)]
        case .tool(let t):
            nav.tab = .profile; nav.openTool = t
        }
    }
}

/// Handoff / Spotlight activity types (Info.plist NSUserActivityTypes).
enum ActivityType {
    static let building = "com.divinedavis.findacrib.building"
    static let lotteries = "com.divinedavis.findacrib.lotteries"
}
