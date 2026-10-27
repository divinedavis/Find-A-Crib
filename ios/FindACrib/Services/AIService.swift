import Foundation

/// The Plus AI features (owner, 2026-10-03), the same endpoints the website
/// calls: plain-language search. Each request carries the
/// Supabase session; the server checks Plus and the $20/month cap, so a
/// 402 here means "show the paywall", never "feature broken".
enum AIError: Error, Equatable {
    case signIn, plus, dailyLimit, monthlyLimit, unavailable, declined
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
        // 429 is a daily cap or this member's $1 a month (2026-10-12).
        case 429: throw Self.limitError(data)
        default: throw AIError.unavailable
        }
    }

    nonisolated static func limitError(_ data: Data) -> AIError {
        let code = ((try? JSONSerialization.jsonObject(with: data)) as? [String: Any])?["error"] as? String
        return code == "monthly_limit" ? .monthlyLimit : .dailyLimit
    }

    /// A JSON POST for the renter tools (RenterTools.swift).
    static func post(_ path: String, auth: AuthService, json: [String: Any]) async throws -> Data {
        try await request(path, auth: auth, body: json)
    }

    static func search(_ q: String, auth: AuthService) async throws -> AISearchResult {
        try JSONDecoder().decode(AISearchResult.self, from: try await request("search", auth: auth, body: ["q": q]))
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
