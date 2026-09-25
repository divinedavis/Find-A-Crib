import Foundation

/// Everything a city's housing authority publishes about one building beyond
/// the register entry itself — `<city>/buildings.hpd.json`, keyed by building id.
///
/// Held ONCE in DataStore as a dictionary, never inline on `Building`. That is
/// the whole point of the split: `Building` is stored 47,165 times in one array
/// and copied again by every filter and sort, so a field on it costs its own
/// size 47,165 times. A record is read by exactly one screen, for exactly one
/// building at a time, so it can be as wide as the city's data is.
///
/// Every field is optional and no city fills in all of them: LA cites
/// violations and files evictions, SF's Rent Board records evictions and
/// petitions for a block, DC's assessor knows the owner and the layout. See
/// build_la_records.py / build_sf_records.py / build_dc_records.py.
struct BuildingRecord: Codable, Hashable, Sendable {
    // LA — the two NYC also has, plus what LAHD keeps that HPD does not.
    var violations: Violations?
    var complaints: Complaints?
    /// Inspections CCRIS has scheduled.
    var insp: Int?
    /// The dates LA's violation file actually covers. It is a rolling window,
    /// not an all-time register, so `violations.total` must never be shown as
    /// a lifetime count without these beside it.
    var window: [String]?
    var ev: Evictions?
    var by: Buyouts?
    var pet: Petitions?
    var cases: Cases?
    var decl: Cases?

    // DC — the assessor's roll and the owner of record on it.
    var owner: String?
    var ptype: String?
    var assessed: Int?
    var rooms: Int?
    var beds: Int?
    var baths: Int?
    var cond: String?
    var renov: Int?
    var units_total: Int?
    var vacreg: String?
    var ssl: String?
    /// Mirrors Building.HPD.op — "there is an operator worth showing".
    var op: Int?

    // Income-restricted cities — Chicago, Miami-Dade, Atlanta, Philadelphia
    // (build_affordable_cities.py): the city's own data merged with HUD's.
    var name: String?
    /// Low-income units, of `units_total`.
    var li: Int?
    /// Units by bedroom count, keyed like `Building.br`: "0" studio … "4" 4+.
    var mix: [String: Int]?
    /// The income ceiling: "60% of area median income".
    var inc: String?
    /// Who it is set aside for: families, seniors, people with disabilities…
    var serves: [String]?
    /// Units by income band: "43 at 50% AMI · 44 at 80% AMI".
    var ami: String?
    /// The manager or owner on file, its phone and website.
    var mgr: String?
    var tel: String?
    var web: String?
    /// Year placed in service (tax credit).
    var pis: Int?
    /// 1 = sponsored by a nonprofit.
    var np: Int?
    /// Every program that funds it: "Low-Income Housing Tax Credit", "ARO"…
    var prog: [String]?
    /// 1 = Florida Housing lists it as in lease-up: first tenants now.
    var leasing: Int?
    /// Public housing: vacant units at last report, and HUD's average wait.
    var vacant: Int?
    var wait_mo: Int?

    struct Violations: Codable, Hashable, Sendable {
        var open: Int?; var total: Int?; var last_12mo: Int?
        var a: Int?; var b: Int?; var c: Int?
        var oa: Int?; var ob: Int?; var oc: Int?
        /// What was actually cited, commonest first: [["Smoke detectors", 3], …].
        var types: [[Cell]]?
        var named: [(String, Int)] { Cell.pairs(types) }
    }
    struct Complaints: Codable, Hashable, Sendable {
        var open: Int?; var total: Int?; var last_12mo: Int?
    }
    struct Evictions: Codable, Hashable, Sendable {
        var total: Int?; var nofault: Int?; var last_12mo: Int?; var recent: Int?
        var reasons: [[Cell]]?
        var named: [(String, Int)] { Cell.pairs(reasons) }
    }
    struct Buyouts: Codable, Hashable, Sendable { var n: Int?; var med: Int?; var recent: Int? }
    struct Petitions: Codable, Hashable, Sendable {
        var total: Int?; var landlord: Int?; var tenant: Int?; var recent: Int?
    }
    struct Cases: Codable, Hashable, Sendable { var open: Int?; var total: Int? }

    /// The builders emit `["Smoke detectors", 3]` — a mixed array JSON can hold
    /// and Swift cannot, so each cell decodes as whichever it is.
    enum Cell: Codable, Hashable, Sendable {
        case text(String), number(Int)
        init(from d: Decoder) throws {
            let c = try d.singleValueContainer()
            if let s = try? c.decode(String.self) { self = .text(s) }
            else { self = .number((try? c.decode(Int.self)) ?? 0) }
        }
        func encode(to e: Encoder) throws {
            var c = e.singleValueContainer()
            switch self { case .text(let s): try c.encode(s); case .number(let n): try c.encode(n) }
        }
        static func pairs(_ rows: [[Cell]]?) -> [(String, Int)] {
            (rows ?? []).compactMap { r in
                guard r.count == 2, case let .text(t) = r[0], case let .number(n) = r[1] else { return nil }
                return (t, n)
            }
        }
    }
}
