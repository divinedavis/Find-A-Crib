import Foundation
import Observation

/// Your Crib (owner, 2026-10-15): type an address, see the 311 calls on that
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
            // AddressCase, not .capitalized: that gave "W 42Nd Street" (2026-10-17).
            let street = parts.first.map { AddressCase.pretty($0) } ?? label
            return parts.count > 1 ? "\(street), \(parts[1])" : street
        }
    }

    struct Call: Codable, Identifiable, Hashable {
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
        var title: String { Casa.tidy(complaint_type ?? String(localized: "311 call")) }
        var detail: String? { descriptor.map(Casa.tidy).flatMap { $0.isEmpty ? nil : $0 } }
    }

    /// The last lookup of a building, kept on the phone so Your Crib opens
    /// with it on the subway or with no signal (owner, 2026-10-15: "i think
    /// it needs an internet connection"). A fresh lookup replaces it.
    struct Snapshot: Codable, Equatable {
        let bbl: String
        var calls: [Call]?
        var crime: [CrimeMonth]?
        var crimeThrough: Date?
        var savedAt: Date
    }

    /// The five most recent buildings, newest first, in Application Support
    /// (Caches can be emptied under storage pressure, right when it's needed).
    enum Saved {
        static let keep = 5
        static var url: URL {
            let dir = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            return dir.appendingPathComponent("casa-saved.json")
        }
        static func all(at url: URL = url) -> [Snapshot] {
            (try? Data(contentsOf: url)).flatMap { try? JSONDecoder().decode([Snapshot].self, from: $0) } ?? []
        }
        static func get(_ bbl: String, at url: URL = url) -> Snapshot? { all(at: url).first { $0.bbl == bbl } }
        /// Merges what loaded into the building's snapshot: a part that
        /// failed this time keeps its last good copy.
        static func put(_ s: Snapshot, at url: URL = url) {
            var list = all(at: url)
            var merged = s
            if let i = list.firstIndex(where: { $0.bbl == s.bbl }) {
                let old = list.remove(at: i)
                merged.calls = s.calls ?? old.calls
                if s.crime == nil { merged.crime = old.crime; merged.crimeThrough = old.crimeThrough }
            }
            list.insert(merged, at: 0)
            if let d = try? JSONEncoder().encode(Array(list.prefix(keep))) { try? d.write(to: url, options: .atomic) }
        }
    }

    /// One NYPD report near the building, listed under the chart (owner,
    /// 2026-11-06: the alert said "11 robberies" and Your Crib had only the
    /// chart). Same rules as casa_alerts.crime_reports on the server, so the
    /// list matches the alert. Suspect and victim fields are in the NYPD file
    /// and left out on purpose.
    struct CrimeReport: Codable, Hashable, Identifiable {
        let id: String
        let kind: String
        let detail: String
        let day: String
        let time: String
        let place: String
        let metres: Double
        let dir: String
        let attempted: Bool
        var title: String {
            var t = Casa.crimeSingular[kind] ?? kind
            if !detail.isEmpty { t += " — \(detail)" }
            if attempted { t += String(localized: " (attempted)") }
            return t
        }
        /// "Aug 14 · 8:00 PM · street · 0.4 mi S"
        var sub: String {
            var bits: [String] = []
            let f = DateFormatter(); f.locale = Locale(identifier: "en_US_POSIX"); f.dateFormat = "yyyy-MM-dd"
            if let d = f.date(from: day) { bits.append(d.formatted(.dateTime.month(.abbreviated).day())) } else { bits.append(day) }
            let h = DateFormatter(); h.locale = Locale(identifier: "en_US_POSIX"); h.dateFormat = "HH:mm"
            if let t = h.date(from: time) { bits.append(t.formatted(date: .omitted, time: .shortened)) }
            if !place.isEmpty { bits.append(place) }
            bits.append(String(format: "%.1f\u{00a0}mi\u{00a0}%@", metres / 1609.34, dir))
            return bits.joined(separator: " · ")
        }
    }

    static let shootingsURL = "https://data.cityofnewyork.us/resource/5ucz-vwe8.json"
    /// casa_alerts.CRIME_KINDS: each kind's NYPD offense names.
    static let crimeOffenses: [String: [String]] = [
        "robbery": ["ROBBERY"], "burglary": ["BURGLARY"], "assault": ["FELONY ASSAULT", "ASSAULT 3 & RELATED OFFENSES"],
        "theft": ["PETIT LARCENY", "GRAND LARCENY"], "car_theft": ["GRAND LARCENY OF MOTOR VEHICLE"], "weapons": ["DANGEROUS WEAPONS"],
        "drugs": ["DANGEROUS DRUGS"], "vandalism": ["CRIMINAL MISCHIEF & RELATED OF"], "harassment": ["HARRASSMENT 2"]]
    static let crimeSingular: [String: String] = [
        "shootings": String(localized: "Shooting"), "robbery": String(localized: "Robbery"), "burglary": String(localized: "Burglary"),
        "assault": String(localized: "Assault"), "theft": String(localized: "Theft"), "car_theft": String(localized: "Car theft"),
        "weapons": String(localized: "Weapons offense"), "drugs": String(localized: "Drug offense"),
        "vandalism": String(localized: "Vandalism report"), "harassment": String(localized: "Harassment report")]
    /// With no alert kinds picked, the list shows the serious three.
    static let defaultReportKinds = ["shootings", "robbery", "burglary"]
    private static let detailNoise: Set<String> = ["DAY", "NIGHT", "UNKNOWN TIM", "UNKNOWN TIME", "UNCL", "UNCLASSIFIE", "UNCLASSIFIED", "UNCLASSIFI"]

    /// "BURGLARY,RESIDENCE,UNKNOWN TIM" → "residence". Only robbery,
    /// burglary and theft carry a detail worth reading; assault says felony.
    static func reportDetail(kind: String, ofns: String?, pd: String?) -> String {
        if kind == "assault" { return ofns == "FELONY ASSAULT" ? "felony" : "" }
        guard ["robbery", "burglary", "theft", "car_theft"].contains(kind) else { return "" }
        return (pd ?? "").split(separator: ",", omittingEmptySubsequences: false).dropFirst().compactMap { raw -> String? in
            var x = raw.trimmingCharacters(in: .whitespaces)
            x = x.replacingOccurrences(of: #"\s+(DAY|NIGHT)$"#, with: "", options: .regularExpression)
            x = x.replacingOccurrences(of: #"^((PETIT|GRAND)\s+)?(OF\s+)?"#, with: "", options: .regularExpression)
            guard !x.isEmpty, !detailNoise.contains(x.uppercased()), Int(x) == nil else { return nil }
            return x
        }.joined(separator: ", ").lowercased()
    }

    static func metres(_ aLat: Double, _ aLng: Double, _ bLat: Double, _ bLng: Double) -> Double {
        let x = (bLng - aLng) * .pi / 180 * cos((aLat + bLat) / 2 * .pi / 180)
        return 6_371_000 * hypot(x, (bLat - aLat) * .pi / 180)
    }

    /// Compass point from the building to the report: "NE".
    static func compass(_ aLat: Double, _ aLng: Double, _ bLat: Double, _ bLng: Double) -> String {
        let x = (bLng - aLng) * cos((aLat + bLat) / 2 * .pi / 180), y = bLat - aLat
        let deg = (atan2(x, y) * 180 / .pi + 360).truncatingRemainder(dividingBy: 360)
        return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][Int((deg / 45).rounded()) % 8]
    }

    /// The list's window: one NYPD release, the three newest months.
    static func reportWindowStart(endingWith newest: Date) -> Date { lastSixMonths(endingWith: newest)[3] }

    /// Every report of `kinds` within half a mile from `from` through
    /// `through`, newest first.
    static func reports(lat: Double, lng: Double, kinds: [String], from: Date, through: Date) async throws -> [CrimeReport] {
        let end = String(soql(startOfDay(through)).prefix(10)) + "T23:59:59"
        var byOfns: [String: String] = [:]
        for k in kinds { for o in crimeOffenses[k] ?? [] { byOfns[o] = k } }
        var out: [CrimeReport] = []
        if !byOfns.isEmpty {
            struct Row: Decodable {
                let cmplnt_num: String?; let cmplnt_fr_dt: String?; let cmplnt_fr_tm: String?; let ofns_desc: String?
                let pd_desc: String?; let prem_typ_desc: String?; let crm_atpt_cptd_cd: String?; let latitude: String?; let longitude: String?
            }
            let listed = byOfns.keys.sorted().map { "'" + $0.replacingOccurrences(of: "'", with: "''") + "'" }.joined(separator: ",")
            let rows = try await get(crimeYTDURL, [
                "$select": "cmplnt_num, cmplnt_fr_dt, cmplnt_fr_tm, ofns_desc, pd_desc, prem_typ_desc, crm_atpt_cptd_cd, latitude, longitude",
                "$where": "within_circle(lat_lon, \(lat), \(lng), \(radiusMeters)) AND cmplnt_fr_dt >= '\(soql(startOfDay(from)))' AND cmplnt_fr_dt <= '\(end)' AND ofns_desc in (\(listed))",
                "$order": "cmplnt_fr_dt DESC, cmplnt_fr_tm DESC", "$limit": "2000"], as: [Row].self)
            for (i, r) in rows.enumerated() {
                guard let o = r.ofns_desc, let k = byOfns[o], let la = Double(r.latitude ?? ""), let lo = Double(r.longitude ?? "") else { continue }
                let prem = r.prem_typ_desc.flatMap { $0 == "(null)" ? nil : $0.lowercased() } ?? ""
                out.append(CrimeReport(id: r.cmplnt_num ?? "c\(i)", kind: k, detail: reportDetail(kind: k, ofns: o, pd: r.pd_desc),
                                       day: String((r.cmplnt_fr_dt ?? "").prefix(10)), time: String((r.cmplnt_fr_tm ?? "").prefix(5)),
                                       place: prem, metres: metres(lat, lng, la, lo), dir: compass(lat, lng, la, lo),
                                       attempted: r.crm_atpt_cptd_cd == "ATTEMPTED"))
            }
        }
        if kinds.contains("shootings") {
            struct Shot: Decodable { let incident_key: String?; let occur_date: String?; let occur_time: String?; let location_desc: String?; let latitude: String?; let longitude: String? }
            let dLat = Double(radiusMeters) / 111_000, dLng = Double(radiusMeters) / (111_000 * cos(lat * .pi / 180))
            let rows = try await get(shootingsURL, [
                "$select": "incident_key, occur_date, occur_time, location_desc, latitude, longitude",
                "$where": "latitude between \(lat - dLat) and \(lat + dLat) AND longitude between \(lng - dLng) and \(lng + dLng) AND occur_date >= '\(soql(startOfDay(from)))' AND occur_date <= '\(end)'",
                "$limit": "500"], as: [Shot].self)
            var seen = Set<String>()
            for (i, r) in rows.enumerated() {
                guard let la = Double(r.latitude ?? ""), let lo = Double(r.longitude ?? "") else { continue }
                let m = metres(lat, lng, la, lo)
                // One incident is one row per victim.
                guard m <= Double(radiusMeters), seen.insert(r.incident_key ?? "s\(i)").inserted else { continue }
                let loc = r.location_desc.flatMap { ["(null)", "NONE"].contains($0) ? nil : $0.lowercased() } ?? ""
                out.append(CrimeReport(id: "s" + (r.incident_key ?? "\(i)"), kind: "shootings", detail: "",
                                       day: String((r.occur_date ?? "").prefix(10)), time: String((r.occur_time ?? "").prefix(5)),
                                       place: loc, metres: m, dir: compass(lat, lng, la, lo), attempted: false))
            }
        }
        return out.sorted { ($0.day, $0.time) > ($1.day, $1.time) }
    }

    /// One month of reported crime near the building.
    struct CrimeMonth: Codable, Hashable, Identifiable {
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
        for c in calls { counts[c.isPest ? String(localized: "Pests") : c.title, default: 0] += 1 }
        return counts.sorted { $0.value != $1.value ? $0.value > $1.value : $0.key < $1.key }
            .map { Tally(title: $0.key, count: $0.value) }
    }

    static func startOfDay(_ d: Date) -> Date {
        var cal = Calendar(identifier: .gregorian)
        cal.timeZone = TimeZone(identifier: "America/New_York")!
        return cal.startOfDay(for: d)
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

    /// Why a lookup failed. Every failure used to read "Offline", including a
    /// lookup the app cancelled itself — pull to refresh redraws the list and
    /// SwiftUI cancels the refresh, so a phone on Wi-Fi said "Offline.
    /// Showing what you saw 3 seconds ago" (owner, 2026-10-17).
    enum Failure: Equatable { case cancelled, offline, server }

    static func failure(_ e: Error) -> Failure {
        if e is CancellationError { return .cancelled }
        guard let u = e as? URLError else { return .server }
        switch u.code {
        case .cancelled: return .cancelled
        case .notConnectedToInternet, .networkConnectionLost, .dataNotAllowed,
             .internationalRoamingOff, .cannotFindHost, .dnsLookupFailed: return .offline
        default: return .server
        }
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
        // Whole days: the same building asks the same question all day, so
        // Socrata answers from its cache (~0.2 s) instead of running it again
        // (3-14 s cold, measured 2026-10-15; the old to-the-second time made
        // every lookup a new query).
        var w = ["bbl='\(bbl)'"]
        if let since { w.append("created_date >= '\(soql(startOfDay(since)))'") }
        if let before { w.append("created_date < '\(soql(startOfDay(before)))'") }
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
    struct Watch: Codable, Hashable { let bbl: String; let address: String?; var crime_kinds: [String]? }

    /// The crime kinds a watch can pick, in chip order. casa_alerts.CRIME_KINDS
    /// and api_server.CASA_CRIME_KINDS use the same keys.
    static let crimeKinds: [(key: String, label: String)] = [
        ("shootings", String(localized: "Shootings")), ("robbery", String(localized: "Robbery")), ("burglary", String(localized: "Burglary")),
        ("assault", String(localized: "Assault")), ("theft", String(localized: "Theft")), ("car_theft", String(localized: "Car theft")),
        ("weapons", String(localized: "Weapons")), ("drugs", String(localized: "Drugs")), ("vandalism", String(localized: "Vandalism")), ("harassment", String(localized: "Harassment"))]
    /// The last answer is kept on the phone, so Your Crib opens already
    /// knowing alerts are on instead of flashing "Turn on alerts" until the
    /// server replies (owner, 2026-10-20).
    private(set) var watch: Watch? = CasaWatch.saved
    /// True once this launch knows whether there is a watch: from the phone's
    /// copy or the server. Until then the alerts card stays hidden.
    private(set) var known = CasaWatch.saved != nil
    private(set) var busy = false
    var error: String?

    private static let savedKey = "casa.watch"
    private static var saved: Watch? {
        UserDefaults.standard.data(forKey: savedKey).flatMap { try? JSONDecoder().decode(Watch.self, from: $0) }
    }
    private func set(_ w: Watch?) {
        watch = w; known = true
        if let w, let d = try? JSONEncoder().encode(w) { UserDefaults.standard.set(d, forKey: Self.savedKey) }
        else { UserDefaults.standard.removeObject(forKey: Self.savedKey) }
    }

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
        guard let token else { set(nil); return }
        let (code, data) = await request("GET", token: token)
        if code == 200, let data, let r = try? JSONDecoder().decode(Reply.self, from: data) { set(r.watch) }
        else { known = true }   // offline: show what we have rather than nothing
    }

    /// Watch `place` (or update its crime kinds). Re-posting the same building
    /// keeps its 311 alerts where they were; a new one starts fresh.
    func start(_ place: Casa.Place, crimeKinds: [String], token: String) async {
        busy = true; defer { busy = false }
        let (code, data) = await request("POST", token: token, body: [
            "bbl": place.bbl, "address": place.short, "lat": place.lat, "lng": place.lng, "crime_kinds": crimeKinds])
        if code == 200, let data, let r = try? JSONDecoder().decode(Reply.self, from: data) {
            set(r.watch); error = nil
            Analytics.shared.track("casa_watch_on", ["bbl": place.bbl])
        } else {
            error = code == 402 ? String(localized: "Alerts are part of Find A Crib Plus.") : String(localized: "Couldn't turn on alerts. Try again in a minute.")
        }
    }

    func stop(token: String) async {
        busy = true; defer { busy = false }
        let (code, _) = await request("DELETE", token: token)
        if code == 200 { set(nil); error = nil; Analytics.shared.track("casa_watch_off") }
        else { error = String(localized: "Couldn't turn off alerts. Try again in a minute.") }
    }
}
