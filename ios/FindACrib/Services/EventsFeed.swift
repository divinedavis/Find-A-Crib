import Foundation
import Observation

/// The Events tab (owner, 2026-09-22): tenant clinics, resource fairs and other
/// housing events the City lists — HPD and the Mayor's Public Engagement Unit —
/// read from findacrib.com/events.json. build_events.py on the server pulls the
/// City's Event Calendar API twice a day, keeps housing events only and merges
/// duplicates, so the app never holds the City's API key.
///
/// The app de-duplicates again on `id` (the server's stable hash of date,
/// address and title): a stale cache and a fresh file must never show one
/// clinic twice.
@Observable @MainActor
final class EventsFeed {
    static let shared = EventsFeed()

    struct Event: Decodable, Identifiable, Equatable, Hashable {
        let id: String
        let title: String
        let start: String            // "2026-09-23T10:00:00", New York local time
        let end: String?
        let all_day: Bool?
        let online: Bool?
        let address: String?
        let borough: String?
        let hosts: [String]?
        let categories: [String]?
        let description: String?
        let url: String?

        var startDate: Date? { EventsFeed.parse(start) }
        var endDate: Date? { end.flatMap(EventsFeed.parse) }
        var dayKey: String { String(start.prefix(10)) }
    }
    private struct Payload: Decodable { let events: [Event] }

    private(set) var events: [Event] = []
    private(set) var loading = false
    private(set) var loadFailed = false
    private(set) var loaded = false

    /// `--events-demo`: three sample events (one listed twice) so the tab can
    /// be tested and reviewed before the live feed has data.
    private var demo: Bool { CommandLine.arguments.contains("--events-demo") }

    func refresh() async {
        if demo { events = Self.dedupe(Self.demoEvents(today: Date())); loaded = true; return }
        loading = true; defer { loading = false }
        var req = URLRequest(url: URL(string: "https://findacrib.com/events.json")!, timeoutInterval: 20)
        req.cachePolicy = .reloadRevalidatingCacheData
        guard let (data, resp) = try? await URLSession.shared.data(for: req) else { loadFailed = events.isEmpty; return }
        let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
        if status == 404 { events = []; loadFailed = false; loaded = true; return }   // feed not switched on yet
        guard status == 200, let p = try? JSONDecoder().decode(Payload.self, from: data) else { loadFailed = events.isEmpty; return }
        events = Self.dedupe(p.events); loadFailed = false; loaded = true
    }

    // MARK: - Pure pieces (unit-tested)

    /// Upcoming only, one row per id, soonest first.
    nonisolated static func dedupe(_ all: [Event], now: Date = Date()) -> [Event] {
        var seen = Set<String>()
        let today = dayKey(now)
        return all
            .filter { $0.dayKey >= today }
            .sorted { ($0.start, $0.title) < ($1.start, $1.title) }
            .filter { seen.insert($0.id).inserted }
    }

    nonisolated static func filter(_ all: [Event], borough: String?) -> [Event] {
        guard let borough else { return all }
        return all.filter { ($0.borough ?? "") == borough }
    }

    /// Consecutive days, each with its events, in order.
    nonisolated static func byDay(_ all: [Event]) -> [(day: String, events: [Event])] {
        var out: [(day: String, events: [Event])] = []
        for e in all {
            if out.last?.day == e.dayKey { out[out.count - 1].events.append(e) } else { out.append((e.dayKey, [e])) }
        }
        return out
    }

    nonisolated static let tz = TimeZone(identifier: "America/New_York")!

    nonisolated static func parse(_ s: String) -> Date? {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = tz
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.date(from: s)
    }

    nonisolated static func dayKey(_ d: Date) -> String {
        let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.timeZone = tz
        f.dateFormat = "yyyy-MM-dd"
        return f.string(from: d)
    }

    /// "Today", "Tomorrow", else "Wednesday, Sep 23".
    nonisolated static func dayTitle(_ key: String, now: Date = Date()) -> String {
        if key == dayKey(now) { return "Today" }
        if key == dayKey(now.addingTimeInterval(86_400)) { return "Tomorrow" }
        guard let d = parse(key + "T12:00:00") else { return key }
        let f = DateFormatter(); f.timeZone = tz; f.dateFormat = "EEEE, MMM d"
        return f.string(from: d)
    }

    /// "10:00 AM – 4:00 PM", "All day", or just the start.
    nonisolated static func timeLine(_ e: Event) -> String {
        if e.all_day == true { return "All day" }
        let f = DateFormatter(); f.timeZone = tz; f.dateFormat = "h:mm a"
        guard let s = e.startDate else { return "" }
        if let end = e.endDate, end > s, dayKey(end) == dayKey(s) { return "\(f.string(from: s)) – \(f.string(from: end))" }
        return f.string(from: s)
    }

    /// "HPD · Mayor's Public Engagement Unit" — the short names people know.
    nonisolated static func hostLine(_ e: Event) -> String? {
        let short = (e.hosts ?? []).map {
            $0.replacingOccurrences(of: "NYC Housing Preservation & Development", with: "HPD")
        }
        return short.isEmpty ? nil : short.joined(separator: " · ")
    }

    nonisolated static func demoEvents(today: Date) -> [Event] {
        let d1 = dayKey(today.addingTimeInterval(86_400)), d2 = dayKey(today.addingTimeInterval(3 * 86_400))
        let clinic = Event(id: "demo-clinic", title: "Tenant Support Clinic with the Arab American Association of NY",
                           start: "\(d1)T10:00:00", end: "\(d1)T16:00:00", all_day: false, online: false,
                           address: "6206 6th Ave, Brooklyn, NY 11220", borough: "Brooklyn",
                           hosts: ["Mayor's Public Engagement Unit", "NYC Housing Preservation & Development"],
                           categories: ["Tenant Resource Fair"],
                           description: "Housing information, rental assistance, legal information and referrals. Arabic interpretation available.",
                           url: "https://www.nyc.gov/site/mayorspeu/events/index.page")
        return [
            clinic, clinic,   // listed twice: must show once
            Event(id: "demo-district", title: "HPD In Your District: Council District 16", start: "\(d2)T17:30:00",
                  end: "\(d2)T19:30:00", all_day: false, online: false, address: "1 Fordham Plaza, Bronx, NY 10458", borough: "Bronx",
                  hosts: ["NYC Housing Preservation & Development"], categories: ["Tenant Resource Fair"],
                  description: "Ask HPD about repairs, rent-stabilized leases and affordable housing lotteries.",
                  url: "https://www.nyc.gov/site/hpd/events/index.page"),
            Event(id: "demo-owner", title: "Property Owner Clinic", start: "\(d2)T00:00:00", end: nil, all_day: true, online: true,
                  address: "100 Gold St, New York, NY 10038", borough: "Manhattan",
                  hosts: ["NYC Housing Preservation & Development"], categories: ["Property Owner Clinic"],
                  description: nil, url: "https://www.nyc.gov/site/hpd/events/index.page"),
        ]
    }
}
