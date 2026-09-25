import Foundation
import Observation

/// Affordable-housing openings outside New York (owner, 2026-09-24: "lets add
/// every state/city that has income restricted and lottery housing").
///
/// findacrib.com/openings.json is rebuilt every three hours by
/// build_openings.py from the public JSON behind SF DAHLIA and Access Housing
/// LA, plus the Miami-Dade buildings Florida Housing marks as in lease-up.
/// Nothing here needs an account: these are public lists, and the borough
/// alerts that gate New York's tab do not exist elsewhere.
@Observable @MainActor
final class OpeningsFeed {
    static let shared = OpeningsFeed()

    struct Opening: Decodable, Identifiable, Equatable {
        let id: String
        let src: String
        let state: String
        let city: String?
        let neighborhood: String?
        let name: String?
        let address: String?
        let kind: String            // lottery | waitlist | first_come | leasing
        let tenure: String          // rent | buy
        let closes: String?
        let units: Int?
        let beds: [String]?
        let rent_low: Int?
        let rent_high: Int?
        let income_min: Int?        // yearly (Boston)
        let income_min_mo: Int?     // monthly (Bloom: LA, Doorway)
        let ami: Int?
        let href: String?
    }
    private struct Payload: Decodable { let openings: [Opening] }

    private(set) var all: [Opening] = []
    private(set) var loaded = false
    private(set) var loadFailed = false
    private(set) var loading = false

    func load() async {
        loading = true; defer { loading = false }
        var req = URLRequest(url: URL(string: "https://findacrib.com/openings.json")!, timeoutInterval: 20)
        req.cachePolicy = .reloadRevalidatingCacheData
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let p = try? JSONDecoder().decode(Payload.self, from: data) else { loadFailed = all.isEmpty; return }
        all = p.openings; loaded = true; loadFailed = false
    }

    // MARK: - Pure pieces (unit-tested)

    /// Which openings belong to a place: each city takes its own agency's list.
    nonisolated static func filter(_ l: [Opening], for city: City, today: String) -> [Opening] {
        l.filter { o in
            guard o.closes.map({ $0 >= today }) ?? true else { return false }
            if let srcs = sources[city.id] { return srcs.contains(o.src) }
            return false
        }
        .sorted { ($0.closes ?? "9999", $0.name ?? "") < ($1.closes ?? "9999", $1.name ?? "") }
    }

    /// The cities with an agency feed of their own.
    nonisolated static let sources: [String: Set<String>] = [
        "la": ["Access Housing LA"],
        "sf": ["SF DAHLIA"],
        "mia": ["Florida Housing"],
    ]
    /// Places whose Lotteries tab has something to list.
    nonisolated static var places: Set<String> { Set(sources.keys) }

    nonisolated static func kindLabel(_ k: String) -> String {
        switch k { case "lottery": "Lottery"; case "waitlist": "Waitlist"; case "first_come": "First come, first served"
        case "leasing": "Leasing now"; default: k.capitalized }
    }
}

extension City {
    /// Whether this place gets a Lotteries tab: New York's own, or a feed
    /// of openings for it (OpeningsFeed.places) — LA, SF, Miami-Dade.
    var hasLotteries: Bool { isNYC || OpeningsFeed.places.contains(id) }
}
