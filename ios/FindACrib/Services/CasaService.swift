import Foundation
import Observation

/// Your Casa (owner, 2026-10-15): type an address, see the 311 calls on that
/// building in the past year — pests first — and a line of reported crime
/// within half a mile. Plus adds calls older than a year and an alert for
/// each new call on one watched building (casa_alerts.py on the server).
///
/// Everything here is public NYC Open Data, read straight from Socrata like
/// HPDRecords; only the watch goes through findacrib.com/api/casa/watch.
enum Casa {
    static let geosearchURL = "https://geosearch.planninglabs.nyc/v2/autocomplete"
    static let calls311URL = "https://data.cityofnewyork.us/resource/erm2-nwe9.json"
    /// NYPD complaints: this year's file and the historic one. The NYPD
    /// publishes them quarterly, so the newest month is ~3 months back.
    static let crimeYTDURL = "https://data.cityofnewyork.us/resource/5uac-w243.json"
    static let crimeHistoricURL = "https://data.cityofnewyork.us/resource/qgea-i56i.json"
    static let watchURL = URL(string: "https://findacrib.com/api/casa/watch")!
    /// Half a mile: "the neighborhood" without naming one.
    static let radiusMeters = 800
    static let listLimit = 200

    /// One address from NYC's GeoSearch (Planning Labs), with the tax lot
    /// (BBL) every City dataset is keyed on.
    struct Place: Identifiable, Hashable, Codable {
        let label: String
        let bbl: String
        let lat: Double
        let lng: Double
        var id: String { bbl + label }
        /// "1919 MADISON AVENUE, New York, NY, USA" → "1919 Madison Avenue, New York"
        var short: String {
            let parts = label.components(separatedBy: ", ")
            let street = parts.first.map { $0.capitalized } ?? label
            return parts.count > 1 ? "\(street), \(parts[1])" : street
        }
    }

    struct Call: Decodable, Identifiable, Hashable {
        let unique_key: String?
        let created_date: String?
        let complaint_type: String?
        let descriptor: String?
        let status: String?
        let agency: String?
        var id: String { unique_key ?? (created_date ?? "") + (complaint_type ?? "") }
        var day: String { String((created_date ?? "").prefix(10)) }
        var isPest: Bool { Casa.isPest(type: complaint_type, descriptor: descriptor) }
        var isOpen: Bool { (status ?? "").lowercased() != "closed" }
        var title: String { Casa.tidy(complaint_type ?? "311 call") }
        var detail: String? { descriptor.map(Casa.tidy).flatMap { $0.isEmpty ? nil : $0 } }
    }

    /// One month of reported crime near the building.
    struct CrimeMonth: Hashable, Identifiable {
        let month: Date
        let felonies: Int
        let total: Int
        var id: Date { month }
    }

    // MARK: - Pure helpers (unit-tested)

    static let pestWords = ["PEST", "RODENT", "RAT ", "RATS", "MICE", "MOUSE", "ROACH", "BED BUG", "BEDBUG", "VERMIN"]

    /// 311 files apartment pests as UNSANITARY CONDITION → PESTS and street
    /// rats as Rodent → Rat Sighting; both count.
    static func isPest(type: String?, descriptor: String?) -> Bool {
        let t = " \(type ?? "") \(descriptor ?? "") ".uppercased()
        return pestWords.contains { t.contains($0) }
    }

    /// The City writes some types in capitals ("UNSANITARY CONDITION"), some
    /// not ("Noise - Residential"); show them all in sentence case.
    static func tidy(_ s: String) -> String {
        let t = s.trimmingCharacters(in: .whitespaces)
        guard t == t.uppercased(), t.rangeOfCharacter(from: .letters) != nil else { return t }
        return t.prefix(1) + t.dropFirst().lowercased()
    }

    struct Tally: Hashable, Identifiable {
        let title: String
        let count: Int
        var id: String { title }
    }

    /// Calls grouped by type, most first: "Pests 4 · Noise 3 · …".
    static func tally(_ calls: [Call]) -> [Tally] {
        var counts: [String: Int] = [:]
        for c in calls { counts[c.isPest ? "Pests" : c.title, default: 0] += 1 }
        return counts.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }
            .map { Tally(title: $0.key, count: $0.value) }
    }

    /// Socrata's floating timestamp, New York time.
    static func soql(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "America/New_York")
        f.dateFormat = "yyyy-MM-dd'T'HH:mm:ss"
        return f.string(from: d)
    }

    static func parseMonth(_ s: String) -> Date? {
        let f = DateFormatter()
        f.locale = Locale(identifier: "en_US_POSIX")
        f.timeZone = TimeZone(identifier: "America/New_York")
        f.dateFormat = "yyyy-MM"
        return f.date(from: String(s.prefix(7)))
    }

    /// The six newest whole months the NYPD has published, oldest first,
    /// given its newest complaint date. A month with no rows is a zero, not
    /// a gap in the line.
    static func lastSixMonths(endingWith newest: Date) -> [Date] {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "America/New_York")!
        let start = cal.date(from: cal.dateComponents([.year, .month], from: newest))!
        return (0..<6).reversed().compactMap { cal.date(byAdding: .month, value: -$0, to: start) }
    }

    static func months(_ rows: [(month: String, law: String, n: Int)], endingWith newest: Date) -> [CrimeMonth] {
        lastSixMonths(endingWith: newest).map { m in
            let key = soql(m).prefix(7)
            let here = rows.filter { $0.month.prefix(7) == key }
            return CrimeMonth(month: m, felonies: here.filter { $0.law == "FELONY" }.reduce(0) { $0 + $1.n },
                              total: here.reduce(0) { $0 + $1.n })
        }
    }

    // MARK: - Network

    static func get<T: Decodable>(_ base: String, _ query: [String: String], as: T.Type) async throws -> T {
        var c = URLComponents(string: base)!
        c.queryItems = query.map { URLQueryItem(name: $0.key, value: $0.value) }
        var req = URLRequest(url: c.url!, timeoutInterval: 30)
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        // NYC Open Data answers a stray 503 about one request in fifteen
        // (measured 2026-10-15), so a busy moment gets two more tries.
        for attempt in 0..<3 {
            if attempt > 0 { try await Task.sleep(nanoseconds: UInt64(attempt) * 700_000_000) }
            let data: Data, resp: URLResponse
            do { (data, resp) = try await URLSession.shared.data(for: req) }
            catch let e as URLError where e.code != .cancelled && attempt < 2 { continue }
            let status = (resp as? HTTPURLResponse)?.statusCode ?? 0
            if status == 200 { return try JSONDecoder().decode(T.self, from: data) }
            if !retryable(status) || attempt == 2 { break }
        }
        throw URLError(.badServerResponse)
    }

    /// Busy or briefly down: worth another try. A bad query is not.
    static func retryable(_ status: Int) -> Bool { status == 429 || (500...599).contains(status) }

    /// Address suggestions as the person types. New York City only.
    static func suggest(_ text: String) async -> [Place] {
        struct R: Decodable {
            struct F: Decodable {
                struct P: Decodable {
                    let label: String?
                    struct A: Decodable { struct Pad: Decodable { let bbl: String? }; let pad: Pad? }
                    let addendum: A?
                }
                struct G: Decodable { let coordinates: [Double] }
                let properties: P
                let geometry: G
            }
            let features: [F]
        }
        let q = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard q.count >= 3, let r = try? await get(geosearchURL, ["text": q], as: R.self) else { return [] }
        var seen = Set<String>()
        return r.features.compactMap { f in
            guard let bbl = f.properties.addendum?.pad?.bbl, bbl.count == 10, let label = f.properties.label,
                  f.geometry.coordinates.count == 2, seen.insert(bbl).inserted else { return nil }
            return Place(label: label, bbl: bbl, lat: f.geometry.coordinates[1], lng: f.geometry.coordinates[0])
        }
    }

    /// 311 calls on the lot, newest first. `before` nil = the past year;
    /// set, it is the older history (Plus).
    static func calls(bbl: String, since: Date?, before: Date?) async throws -> [Call] {
        var w = ["bbl='\(bbl)'"]
        if let since { w.append("created_date >= '\(soql(since))'") }
        if let before { w.append("created_date < '\(soql(before))'") }
        return try await get(calls311URL, [
            "$select": "unique_key,created_date,complaint_type,descriptor,status,agency",
            "$where": w.joined(separator: " AND "),
            "$order": "created_date DESC", "$limit": String(listLimit)], as: [Call].self)
    }

    /// Reported crime within half a mile, by month, for the six newest months
    /// the NYPD has published. Returns the months and the newest date.
    static func crime(lat: Double, lng: Double) async throws -> (months: [CrimeMonth], through: Date) {
        struct Max: Decodable { let newest: String? }
        let latest = try await get(crimeYTDURL, ["$select": "max(cmplnt_fr_dt) as newest"], as: [Max].self)
        guard let s = latest.first?.newest, let newest = parseMonth(s),
              let through = ISO8601DateFormatter.socrata.date(from: String(s.prefix(19))) else { throw URLError(.cannotParseResponse) }
        let window = lastSixMonths(endingWith: newest)
        struct Row: Decodable { let m: String?; let law_cat_cd: String?; let count: String? }
        func fetch(_ base: String) async throws -> [Row] {
            try await get(base, [
                "$select": "date_trunc_ym(cmplnt_fr_dt) as m, law_cat_cd, count(*) as count",
                "$where": "within_circle(lat_lon, \(lat), \(lng), \(radiusMeters)) AND cmplnt_fr_dt >= '\(soql(window[0]))'",
                "$group": "m, law_cat_cd"], as: [Row].self)
        }
        var rows = try await fetch(crimeYTDURL)
        // A window that reaches into last year needs the historic file too.
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "America/New_York")!
        if cal.component(.year, from: window[0]) < cal.component(.year, from: newest) {
            rows += (try? await fetch(crimeHistoricURL)) ?? []
        }
        let parsed = rows.compactMap { r -> (month: String, law: String, n: Int)? in
            guard let m = r.m else { return nil }
            return (month: m, law: r.law_cat_cd ?? "", n: Int(r.count ?? "") ?? 0)
        }
        return (months(parsed, endingWith: newest), through)
    }
}

extension ISO8601DateFormatter {
    /// "2026-06-30T00:00:00" — Socrata's floating timestamps carry no zone.
    static let socrata: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withFullDate, .withTime, .withColonSeparatorInTime, .withDashSeparatorInDate]
        f.timeZone = TimeZone(identifier: "America/New_York")
        return f
    }()
}

/// The one building a Plus member watches, kept on the server.
@Observable @MainActor
final class CasaWatch {
    static let shared = CasaWatch()
    struct Watch: Decodable, Hashable { let bbl: String; let address: String?; var crime_kinds: [String]? }

    /// The crime kinds a watch can pick, in chip order. casa_alerts.CRIME_KINDS
    /// and api_server.CASA_CRIME_KINDS use the same keys.
    static let crimeKinds: [(key: String, label: String)] = [
        ("shootings", "Shootings"), ("robbery", "Robbery"), ("burglary", "Burglary"),
        ("assault", "Assault"), ("theft", "Theft"), ("car_theft", "Car theft"),
        ("weapons", "Weapons"), ("drugs", "Drugs"), ("vandalism", "Vandalism"), ("harassment", "Harassment")]
    private(set) var watch: Watch?
    private(set) var busy = false
    var error: String?

    private func request(_ method: String, token: String, body: [String: Any]? = nil) async -> (Int, Data?) {
        var req = URLRequest(url: Casa.watchURL, timeoutInterval: 15)
        req.httpMethod = method
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        if let body {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        guard let (data, resp) = try? await URLSession.shared.data(for: req) else { return (0, nil) }
        return ((resp as? HTTPURLResponse)?.statusCode ?? 0, data)
    }

    private struct Reply: Decodable { let watch: Watch? }

    func load(token: String?) async {
        guard let token else { watch = nil; return }
        let (code, data) = await request("GET", token: token)
        if code == 200, let data, let r = try? JSONDecoder().decode(Reply.self, from: data) { watch = r.watch }
    }

    /// Watch `place` (or update its crime kinds). Re-posting the same building
    /// keeps its 311 alerts where they were; a new one starts fresh.
    func start(_ place: Casa.Place, crimeKinds: [String], token: String) async {
        busy = true; defer { busy = false }
        let (code, data) = await request("POST", token: token, body: [
            "bbl": place.bbl, "address": place.short, "lat": place.lat, "lng": place.lng, "crime_kinds": crimeKinds])
        if code == 200, let data, let r = try? JSONDecoder().decode(Reply.self, from: data) {
            watch = r.watch; error = nil
            Analytics.shared.track("casa_watch_on", ["bbl": place.bbl])
        } else {
            error = code == 402 ? "Alerts are part of Find A Crib Plus." : "Couldn't turn on alerts. Try again in a minute."
        }
    }

    func stop(token: String) async {
        busy = true; defer { busy = false }
        let (code, _) = await request("DELETE", token: token)
        if code == 200 { watch = nil; error = nil; Analytics.shared.track("casa_watch_off") }
        else { error = "Couldn't turn off alerts. Try again in a minute." }
    }
}
