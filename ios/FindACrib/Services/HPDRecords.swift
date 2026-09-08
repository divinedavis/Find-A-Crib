import Foundation

/// The building's HPD record, row by row, from NYC Open Data — the same two
/// datasets the website's Violations and Complaints popups read, so the app
/// and the site never disagree about a building. Fetched on demand when the
/// records screen opens, cached per building for the session.
enum HPDRecords {
    static let violationsURL = "https://data.cityofnewyork.us/resource/wvxf-dwi5.json"
    static let complaintsURL = "https://data.cityofnewyork.us/resource/ygpa-z7cr.json"
    /// HPD's annual bedbug filings and DOHMH rodent inspections — the two
    /// "Inspections" tiles, same datasets as the site's buttons.
    static let bedbugsURL = "https://data.cityofnewyork.us/resource/wz6d-d3jb.json"
    static let rodentsURL = "https://data.cityofnewyork.us/resource/p937-wjvj.json"
    static let limit = 100

    struct Violation: Decodable, Identifiable, Hashable {
        let violationid: String?
        let `class`: String?
        let novdescription: String?
        let novissueddate: String?
        let currentstatus: String?
        let currentstatusdate: String?
        let apartment: String?
        let story: String?
        var id: String { violationid ?? (novissueddate ?? "") + (novdescription ?? "") }
        var cls: String { (`class` ?? "").uppercased() }
        var issued: String { String((novissueddate ?? "").prefix(10)) }
        var statusDate: String { String((currentstatusdate ?? "").prefix(10)) }
    }

    struct Complaint: Decodable, Identifiable, Hashable {
        let problem_id: String?
        let received_date: String?
        let major_category: String?
        let minor_category: String?
        let problem_code: String?
        let apartment: String?
        let unit_type: String?
        let type: String?
        let problem_status: String?
        let problem_status_date: String?
        let status_description: String?
        var id: String { problem_id ?? (received_date ?? "") + (problem_code ?? "") }
        var isOpen: Bool { (problem_status ?? "").uppercased() != "CLOSE" }
        var received: String { String((received_date ?? "").prefix(10)) }
        var statusDate: String { String((problem_status_date ?? "").prefix(10)) }
    }

    /// One annual landlord filing: every multiple dwelling must report its
    /// bedbug history to HPD each year. Socrata sends the numbers as strings.
    struct BedbugFiling: Decodable, Identifiable, Hashable {
        let filing_date: String?
        let of_dwelling_units: String?
        let infested_dwelling_unit_count: String?
        let re_infested_dwelling_unit: String?
        let eradicated_unit_count: String?
        let filing_period_start_date: String?
        let filling_period_end_date: String?   // sic — the dataset's own column name
        var id: String { (filing_date ?? "") + "/" + (filing_period_start_date ?? "") + "/" + (infested_dwelling_unit_count ?? "") }
        var filed: String { String((filing_date ?? "").prefix(10)) }
        var units: Int { HPDRecords.int(of_dwelling_units) }
        var infested: Int { HPDRecords.int(infested_dwelling_unit_count) }
        var reinfested: Int { HPDRecords.int(re_infested_dwelling_unit) }
        var treated: Int { HPDRecords.int(eradicated_unit_count) }
        var periodStart: String { String((filing_period_start_date ?? "").prefix(10)) }
        var periodEnd: String { String((filling_period_end_date ?? "").prefix(10)) }
        /// "A problem": the filing reported at least one infested unit.
        var hadBedbugs: Bool { infested > 0 }
        var year: Int? { Int(filed.prefix(4)) }
    }

    /// One Health Department rodent inspection.
    struct RodentInspection: Decodable, Identifiable, Hashable {
        let job_id: String?
        let inspection_date: String?
        let inspection_type: String?
        let result: String?
        var id: String { (job_id ?? "") + "/" + (inspection_date ?? "") + "/" + (inspection_type ?? "") }
        var date: String { String((inspection_date ?? "").prefix(10)) }
        /// The site's rule: rat activity, a failed inspection, or a problem
        /// condition counts against the building; "Passed" and the
        /// stoppage/monitoring visits do not.
        var failed: Bool {
            let r = (result ?? "").uppercased()
            return r.contains("RAT ACTIVITY") || r.contains("FAIL") || r.contains("PROBLEM")
        }
        var year: Int? { Int(date.prefix(4)) }
    }

    /// What the two tiles say: how many records are on file and how many of
    /// them were a problem this calendar year. `nil` = still loading.
    struct InspectionSummary: Hashable {
        let total: Int
        let problemsThisYear: Int
        var clean: Bool { problemsThisYear == 0 }
    }

    static func summary(bedbugs rows: [BedbugFiling], year: Int = currentYear) -> InspectionSummary {
        InspectionSummary(total: rows.count, problemsThisYear: rows.filter { $0.year == year && $0.hadBedbugs }.count)
    }
    static func summary(rodents rows: [RodentInspection], year: Int = currentYear) -> InspectionSummary {
        InspectionSummary(total: rows.count, problemsThisYear: rows.filter { $0.year == year && $0.failed }.count)
    }
    static var currentYear: Int { Calendar(identifier: .gregorian).component(.year, from: Date()) }
    static func int(_ s: String?) -> Int { Int(Double(s ?? "") ?? 0) }

    private static var violationCache: [String: [Violation]] = [:]
    private static var complaintCache: [String: [Complaint]] = [:]
    private static var bedbugCache: [String: [BedbugFiling]] = [:]
    private static var rodentCache: [String: [RodentInspection]] = [:]

    /// Open violations only, newest first — HPD's own Open/Close flag, not the
    /// free-text status that counts "VIOLATION DISMISSED" as open.
    static func violations(bbl: String) async throws -> [Violation] {
        if let c = violationCache[bbl] { return c }
        guard bbl.count == 10, bbl.allSatisfy(\.isNumber) else { return [] }
        var comps = URLComponents(string: violationsURL)!
        comps.queryItems = [
            .init(name: "$select", value: "violationid,class,novdescription,novissueddate,currentstatus,currentstatusdate,apartment,story"),
            .init(name: "$where", value: "bbl='\(bbl)' AND violationstatus='Open'"),
            .init(name: "$order", value: "novissueddate DESC"),
            .init(name: "$limit", value: String(limit)),
        ]
        let rows: [Violation] = try await fetch(comps.url!)
        // Most serious first, then newest — the order the site uses.
        let rank = ["C": 0, "B": 1, "A": 2]
        let sorted = rows.sorted {
            let ra = rank[$0.cls] ?? 3, rb = rank[$1.cls] ?? 3
            return ra != rb ? ra < rb : $0.issued > $1.issued
        }
        violationCache[bbl] = sorted
        return sorted
    }

    /// Every reported problem, newest first.
    static func complaints(bbl: String) async throws -> [Complaint] {
        if let c = complaintCache[bbl] { return c }
        guard bbl.count == 10, bbl.allSatisfy(\.isNumber) else { return [] }
        var comps = URLComponents(string: complaintsURL)!
        comps.queryItems = [
            .init(name: "$select", value: "problem_id,received_date,major_category,minor_category,problem_code,apartment,unit_type,type,problem_status,problem_status_date,status_description"),
            .init(name: "$where", value: "bbl='\(bbl)'"),
            .init(name: "$order", value: "received_date DESC"),
            .init(name: "$limit", value: String(limit)),
        ]
        let rows: [Complaint] = try await fetch(comps.url!)
        complaintCache[bbl] = rows
        return rows
    }

    /// Annual bedbug filings, newest first. bbl is text in this dataset.
    static func bedbugs(bbl: String) async throws -> [BedbugFiling] {
        if let c = bedbugCache[bbl] { return c }
        guard bbl.count == 10, bbl.allSatisfy(\.isNumber) else { return [] }
        var comps = URLComponents(string: bedbugsURL)!
        comps.queryItems = [
            .init(name: "$select", value: "filing_date,of_dwelling_units,infested_dwelling_unit_count,re_infested_dwelling_unit,eradicated_unit_count,filing_period_start_date,filling_period_end_date"),
            .init(name: "$where", value: "bbl='\(bbl)'"),
            .init(name: "$order", value: "filing_date DESC"),
            .init(name: "$limit", value: String(limit)),
        ]
        let rows: [BedbugFiling] = try await fetch(comps.url!)
        bedbugCache[bbl] = rows
        return rows
    }

    /// Rodent inspections, newest first. bbl is a number in this dataset, so
    /// the quotes come off — with them Socrata returns nothing, not an error.
    static func rodents(bbl: String) async throws -> [RodentInspection] {
        if let c = rodentCache[bbl] { return c }
        guard bbl.count == 10, bbl.allSatisfy(\.isNumber), let n = Int(bbl) else { return [] }
        var comps = URLComponents(string: rodentsURL)!
        comps.queryItems = [
            .init(name: "$select", value: "job_id,inspection_date,inspection_type,result"),
            .init(name: "$where", value: "bbl=\(n)"),
            .init(name: "$order", value: "inspection_date DESC"),
            .init(name: "$limit", value: String(limit)),
        ]
        let rows: [RodentInspection] = try await fetch(comps.url!)
        rodentCache[bbl] = rows
        return rows
    }

    private static func fetch<T: Decodable>(_ url: URL) async throws -> [T] {
        var req = URLRequest(url: url, timeoutInterval: 20)
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
            throw URLError(.badServerResponse)
        }
        return try JSONDecoder().decode([T].self, from: data)
    }

    // MARK: - Plain words for HPD's shorthand

    static let classWord = ["A": "Non-hazardous", "B": "Hazardous", "C": "Immediately hazardous"]

    static let statusWord: [String: String] = [
        "NOV SENT OUT": "Notice sent to the owner",
        "NOV CERTIFIED LATE": "Owner certified the fix late",
        "NOT COMPLIED WITH": "Owner did not certify a fix",
        "DEFECT LETTER ISSUED": "Owner's certification rejected",
        "FIRST NO ACCESS TO RE- INSPECT VIOLATION": "Inspector could not get in to verify",
        "SECOND NO ACCESS TO RE-INSPECT VIOLATION": "Inspector could not get in to verify (2nd try)",
        "INFO NOV SENT OUT": "Informational notice sent",
        "CIV14 MAILED": "Civil-penalty notice mailed",
    ]

    /// HPD's notice text is written for inspectors: it repeats the address,
    /// pads with empty SECTION '' '' fields, and shouts. Keep the substance.
    static func trimNotice(_ s: String?) -> (cite: String, body: String) {
        let raw = (s ?? "").replacingOccurrences(of: "\\s+", with: " ", options: .regularExpression)
            .trimmingCharacters(in: .whitespaces)
        var cite = "", body = raw
        if let m = raw.range(of: #"^(§?\s*[\d\-.,§\s]*\d)\s*(HMC|ADM\.? CODE|ADMIN\.? CODE)?\s*:?\s*"#, options: .regularExpression) {
            let head = String(raw[m]).replacingOccurrences(of: "§", with: "").replacingOccurrences(of: ":", with: "")
                .trimmingCharacters(in: .whitespaces)
            cite = head.isEmpty ? "" : "§ " + head
            body = String(raw[m.upperBound...])
        }
        body = body.replacingOccurrences(of: #",?\s*SECTION\s*'+\s*'+\.?"#, with: "", options: [.regularExpression, .caseInsensitive])
        body = body.replacingOccurrences(of: #",?\s*LOCATED AT\s+(THE\s+)?(APT|APARTMENT)\b.*$"#, with: "", options: [.regularExpression, .caseInsensitive])
        body = body.replacingOccurrences(of: #"\s{2,}"#, with: " ", options: .regularExpression)
        body = body.trimmingCharacters(in: CharacterSet(charactersIn: " ,."))
        return (cite, body)
    }

    static func floorLabel(_ story: String?) -> String {
        let s = (story ?? "").trimmingCharacters(in: .whitespaces)
        if s.isEmpty { return "" }
        if s.range(of: #"^\d+(st|nd|rd|th)$"#, options: [.regularExpression, .caseInsensitive]) != nil { return s + " floor" }
        guard let n = Int(s) else { return s }
        let t = n % 100
        let suf = (11...13).contains(t) ? "th" : ["st", "nd", "rd"][safe: n % 10 - 1] ?? "th"
        return "\(n)\(suf) floor"
    }

    /// Years since a yyyy-mm-dd date; nil when unparseable.
    static func yearsSince(_ ymd: String) -> Int? {
        guard let d = ISO8601DateFormatter.ymd.date(from: ymd) else { return nil }
        return Int(Date().timeIntervalSince(d) / (365.25 * 86400))
    }

    static func titleCase(_ s: String?) -> String {
        (s ?? "").lowercased().split(separator: " ").map { w in
            w.split(separator: "/").map { $0.prefix(1).uppercased() + $0.dropFirst() }.joined(separator: "/")
        }.joined(separator: " ")
    }
}

private extension Array {
    subscript(safe i: Int) -> Element? { indices.contains(i) ? self[i] : nil }
}
