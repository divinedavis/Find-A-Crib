import AppIntents
import Foundation

// Shared by the app (Siri, SiriIntents.swift) and the widget extension
// (FindACribWidgets): the public Housing Connect feed and the borough choice.

enum BoroughChoice: String, AppEnum {
    case any, bronx = "Bx", brooklyn = "Bk", manhattan = "M", queens = "Q", statenIsland = "SI"
    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Borough"
    static let caseDisplayRepresentations: [BoroughChoice: DisplayRepresentation] = [
        .any: "All boroughs", .bronx: "the Bronx", .brooklyn: "Brooklyn", .manhattan: "Manhattan",
        .queens: "Queens", .statenIsland: "Staten Island"]
    var feedName: String? {
        switch self { case .any: nil; case .bronx: "Bronx"; case .brooklyn: "Brooklyn"; case .manhattan: "Manhattan"
        case .queens: "Queens"; case .statenIsland: "Staten Island" }
    }
}

/// The public Housing Connect feed, read the same way by Siri and the widget.
enum LotterySnapshot {
    struct Item: Decodable { let name: String; let borough: String; let closes: String?; let href: String? }
    private struct Payload: Decodable { let lotteries: [Item] }

    static func open(borough: String? = nil, limit: Int = 5) async throws -> [Item] {
        var req = URLRequest(url: URL(string: "https://findacrib.com/housing_connect.json")!, timeoutInterval: 15)
        req.cachePolicy = .reloadRevalidatingCacheData
        let (data, _) = try await URLSession.shared.data(for: req)
        let today = todayKey()
        return try JSONDecoder().decode(Payload.self, from: data).lotteries
            .filter { ($0.closes ?? "") >= today && (borough == nil || $0.borough == borough) }
            .sorted { ($0.closes ?? "9999") < ($1.closes ?? "9999") }
            .prefix(limit).map { $0 }
    }

    static func todayKey(_ d: Date = Date()) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "America/New_York")
        f.locale = Locale(identifier: "en_US_POSIX"); return f.string(from: d)
    }

    static func spoken(_ closes: String?) -> String {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "America/New_York")
        guard let c = closes, let d = f.date(from: c) else { return "soon" }
        let out = DateFormatter(); out.setLocalizedDateFormatFromTemplate("EEEEMMMMd"); out.timeZone = f.timeZone
        return out.string(from: d)
    }
}

