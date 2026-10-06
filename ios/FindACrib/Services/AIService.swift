import Foundation

/// The Plus AI features (owner, 2026-10-03), the same endpoints the website
/// calls: plain-language search and Help me apply. Each request carries the
/// Supabase session; the server checks Plus and the $20/month cap, so a
/// 402 here means "show the paywall", never "feature broken".
enum AIError: Error, Equatable {
    case signIn, plus, dailyLimit, unavailable, declined
}

struct AISearchResult: Decodable {
    struct Filters: Decodable {
        var boroughs: [String] = []
        var nbs: [String] = []
        var pmin: Int?
        var pmax: Int?
        var beds: [Int] = []
        var s8: String?
        var viol: String?
    }
    let filters: Filters
    let explain: [String]
    let used_ai: Bool?
}

struct ApplyHelp: Decodable {
    struct Doc: Decodable, Hashable { let item: String; let required_by_listing: Bool }
    struct Contact: Decodable { let email: String?; let phone: String?; let link: String? }
    let steps: [String]
    let documents: [Doc]
    let deadline: String?
    let contact: Contact
    let email_subject: String
    let email_body: String
}

@MainActor
enum AIService {
    static let base = URL(string: "https://findacrib.com/api/ai/")!

    private static func request(_ path: String, auth: AuthService, body: [String: Any]? = nil) async throws -> Data {
        guard let token = auth.session?.accessToken else { throw AIError.signIn }
        var req = URLRequest(url: URL(string: path, relativeTo: base)!, timeoutInterval: 60)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        if let body {
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(withJSONObject: body)
        }
        let (data, resp) = try await URLSession.shared.data(for: req)
        switch (resp as? HTTPURLResponse)?.statusCode ?? 0 {
        case 200: return data
        case 401: throw AIError.signIn
        case 402: throw AIError.plus
        case 429: throw AIError.dailyLimit
        default: throw AIError.unavailable
        }
    }

    static func search(_ q: String, auth: AuthService) async throws -> AISearchResult {
        try JSONDecoder().decode(AISearchResult.self, from: try await request("search", auth: auth, body: ["q": q]))
    }

    static func applyHelp(href: String, auth: AuthService) async throws -> ApplyHelp {
        struct R: Decodable { let help: ApplyHelp }
        return try JSONDecoder().decode(R.self, from: try await request("apply-help", auth: auth, body: ["href": href])).help
    }

    /// The AI search's filters as the app's own query. Prices snap to whole
    /// dollars as given; neighborhoods and boroughs become location scopes.
    static func query(from f: AISearchResult.Filters) -> SearchQuery {
        var q = SearchQuery()
        q.locations = f.nbs.map { .neighborhood($0) } + (f.nbs.isEmpty ? f.boroughs.map { .borough($0) } : [])
        q.minPrice = f.pmin
        q.maxPrice = f.pmax
        q.beds = Set(f.beds.map { min($0, 4) })
        q.vouchersOnly = f.s8 != nil
        q.noOpenViolations = f.viol == "none"
        return q
    }
}
