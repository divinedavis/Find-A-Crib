import Foundation
import CoreLocation

/// One record of buildings.slim.json — the same short keys the web app boots
/// from, so the payload stays byte-identical across clients.
struct Building: Identifiable, Codable, Hashable {
    let bbl: String
    let b: String           // borough code: M, Bk, Q, Bx, SI
    let a: String           // address as DHCR types it: "246 10TH AVE"
    let z: String?          // ZIP
    let lat: Double
    let lng: Double
    let s: [String]?        // DHCR status lines
    let yr: Int?
    let u: Int?             // units
    let nb: String?         // 2020 NTA neighborhood name
    let h: HPD?

    var id: String { bbl }

    struct HPD: Codable, Hashable {
        let violations: Violations?
        let complaints: Complaints?
        let lastregistration: String?
        let op: Int?
        struct Violations: Codable, Hashable {
            let open: Int?; let total: Int?
            let a: Int?; let b: Int?; let c: Int?
            let oa: Int?; let ob: Int?; let oc: Int?
            let last_12mo: Int?
        }
        struct Complaints: Codable, Hashable {
            let open: Int?; let total: Int?; let last_12mo: Int?
        }
    }

    // ZIP arrives as a string on most rows but the pipeline has emitted
    // integers before; accept both so one odd row can't sink the decode.
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        bbl = try c.decode(String.self, forKey: .bbl)
        b = try c.decodeIfPresent(String.self, forKey: .b) ?? ""
        a = try c.decodeIfPresent(String.self, forKey: .a) ?? ""
        if let zs = try? c.decodeIfPresent(String.self, forKey: .z) { z = zs }
        else if let zi = try? c.decodeIfPresent(Int.self, forKey: .z) { z = String(zi) }
        else { z = nil }
        lat = try c.decodeIfPresent(Double.self, forKey: .lat) ?? 0
        lng = try c.decodeIfPresent(Double.self, forKey: .lng) ?? 0
        s = try c.decodeIfPresent([String].self, forKey: .s)
        yr = try c.decodeIfPresent(Int.self, forKey: .yr)
        u = try c.decodeIfPresent(Int.self, forKey: .u)
        nb = try c.decodeIfPresent(String.self, forKey: .nb)
        h = try c.decodeIfPresent(HPD.self, forKey: .h)
    }

    init(bbl: String, b: String, a: String, z: String?, lat: Double, lng: Double,
         s: [String]? = nil, yr: Int? = nil, u: Int? = nil, nb: String? = nil, h: HPD? = nil) {
        self.bbl = bbl; self.b = b; self.a = a; self.z = z; self.lat = lat; self.lng = lng
        self.s = s; self.yr = yr; self.u = u; self.nb = nb; self.h = h
    }

    var coordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lng) }
    var borough: String { Borough.name(b) }
    var boroughSlug: String { Borough.slug(b) }
    var neighborhood: String { nb ?? borough }
    /// "246 10th Ave" — the clerk's all-caps softened for a card headline.
    var address: String { AddressCase.pretty(a) }
    var openViolations: Int { h?.violations?.open ?? 0 }
    var openComplaints: Int { h?.complaints?.open ?? 0 }
    var statusLine: String { (s ?? []).map { AddressCase.pretty($0) }.joined(separator: " · ") }
    var webURL: URL {
        URL(string: "https://findacrib.com/building/\(boroughSlug)/\(Slug.make(a))-\(bbl)/")!
    }
}

enum Borough {
    static let all: [(code: String, name: String)] = [
        ("M", "Manhattan"), ("Bk", "Brooklyn"), ("Q", "Queens"), ("Bx", "Bronx"), ("SI", "Staten Island")
    ]
    static func name(_ code: String) -> String { all.first { $0.code == code }?.name ?? code }
    static func slug(_ code: String) -> String {
        switch code { case "M": "manhattan"; case "Bk": "brooklyn"; case "Q": "queens"; case "Bx": "bronx"; case "SI": "staten-island"; default: "nyc" }
    }
}

enum Slug {
    // Mirrors build_seo.py's slugify() so the app links to the exact page the
    // site already serves for each building.
    static func make(_ s: String) -> String {
        var out = ""; var dash = false
        for ch in s.lowercased() {
            if ch.isLetter || ch.isNumber, ch.isASCII { out.append(ch); dash = false }
            else if !dash { out.append("-"); dash = true }
        }
        let t = out.trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        return t.isEmpty ? "x" : t
    }
}

enum AddressCase {
    static let keepUpper: Set<String> = ["NY", "NE", "NW", "SE", "SW", "N", "S", "E", "W", "II", "III"]
    static func pretty(_ raw: String) -> String {
        raw.split(separator: " ").map { w -> String in
            let s = String(w)
            if keepUpper.contains(s) { return s }
            // ordinal suffixes: 10TH -> 10th, 1ST -> 1st
            if let first = s.first, first.isNumber { return s.lowercased() }
            return s.prefix(1).uppercased() + s.dropFirst().lowercased()
        }.joined(separator: " ")
    }
}

/// listings.json — recently advertised rentals matched to DHCR buildings.
struct ListingsBlob: Codable {
    var counts: [String: Int] = [:]
    var urls: [String: String] = [:]
    var prices: [String: Int] = [:]
    var beds: [String: [Int]] = [:]
    var updated: Double? = nil
    var updatedDate: Date? { updated.map { Date(timeIntervalSince1970: $0) } }
}

/// s8.json — voucher signals keyed by BBL.
struct S8Blob: Codable {
    struct Bldg: Codable { let f: Int?; let u: Int? }      // f: 1 HPD city-financed, 2 HUD project-based
    struct Avail: Codable { let n: Int?; let p: Int?; let url: String?; let b8: Int? }
    var bldg: [String: Bldg] = [:]
    var avail: [String: Avail] = [:]
    var updated: Double? = nil
    var avail_updated: Double? = nil
}

/// fmr.json — HUD FY2026 Small-Area Fair Market Rents by ZIP: [studio, 1BR, 2BR, 3BR]
typealias FMRTable = [String: [Int]]

/// hcr.json — HousingSearch.ny.gov lotteries and waitlists (HCR-regulated
/// affordable housing you apply to online). A listing may sit in a building
/// that is on the DHCR register (then `bbl` is set and the app attaches it
/// to that building) or stand alone (the app makes a pin of its own for it).
struct HCRBlob: Codable {
    var updated: Double? = nil
    var listings: [HCRListing] = []
    var updatedDate: Date? { updated.map { Date(timeIntervalSince1970: $0) } }
}

struct HCRListing: Codable, Hashable, Identifiable {
    struct Site: Codable, Hashable {
        let street: String?; let zip: String?; let lat: Double?; let lng: Double?; let bbl: String?
    }
    let id: String
    let name: String?
    let kind: String?          // Lottery | Waitlist | Mitchell-Lama Waitlist
    let status: String?        // Open | Closed
    let ptype: String?         // Rental | Co-op
    let boro: String?
    let min_income: Int?
    let max_income: Int?
    let due: String?
    let fee: Int?

    // Incomes/fees arrive as Int or Double depending on the record; never let
    // one 19989.0 sink the whole file.
    init(from d: Decoder) throws {
        let c = try d.container(keyedBy: CodingKeys.self)
        func int(_ k: CodingKeys) -> Int? {
            if let i = try? c.decodeIfPresent(Int.self, forKey: k) { return i }
            if let f = try? c.decodeIfPresent(Double.self, forKey: k) { return Int(f.rounded()) }
            return nil
        }
        id = try c.decode(String.self, forKey: .id)
        name = try c.decodeIfPresent(String.self, forKey: .name)
        kind = try c.decodeIfPresent(String.self, forKey: .kind)
        status = try c.decodeIfPresent(String.self, forKey: .status)
        ptype = try c.decodeIfPresent(String.self, forKey: .ptype)
        boro = try c.decodeIfPresent(String.self, forKey: .boro)
        min_income = int(.min_income); max_income = int(.max_income); fee = int(.fee)
        due = try c.decodeIfPresent(String.self, forKey: .due)
        phone = try c.decodeIfPresent(String.self, forKey: .phone)
        url = try c.decodeIfPresent(String.self, forKey: .url)
        info = try c.decodeIfPresent(String.self, forKey: .info)
        desc = try c.decodeIfPresent(String.self, forKey: .desc)
        image = try c.decodeIfPresent(String.self, forKey: .image)
        senior = try c.decodeIfPresent(Bool.self, forKey: .senior)
        accessible = try c.decodeIfPresent(Bool.self, forKey: .accessible)
        approx = try c.decodeIfPresent(Bool.self, forKey: .approx)
        buildings = (try? c.decodeIfPresent([Site].self, forKey: .buildings)) ?? []
    }
    let phone: String?
    let url: String?
    let info: String?
    let desc: String?
    let image: String?
    let senior: Bool?
    let accessible: Bool?
    let approx: Bool?
    let buildings: [Site]

    var isOpen: Bool { status == "Open" }
    var kindLabel: String {
        switch kind { case "Lottery": "HCR lottery"; case "Mitchell-Lama Waitlist": "Mitchell-Lama waitlist"; default: "HCR waitlist" }
    }
    var applyURL: URL? { url.flatMap(URL.init) }
    var incomeRange: String? {
        switch (min_income, max_income) {
        case let (lo?, hi?): "\(Formatters.dollars(lo))–\(Formatters.dollars(hi))"
        case let (lo?, nil): "from \(Formatters.dollars(lo))"
        case let (nil, hi?): "up to \(Formatters.dollars(hi))"
        default: nil
        }
    }
    /// Synthetic BBL for a site that is not on the DHCR register.
    static func syntheticBBL(_ id: String, _ i: Int) -> String { "HCR-\(id)-\(i)" }
    static func isSynthetic(_ bbl: String) -> Bool { bbl.hasPrefix("HCR-") }
}
