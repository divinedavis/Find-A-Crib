import Foundation
import Observation

/// "What do I qualify for?" (free, owner 2026-10-03). Household size and
/// yearly income, kept ON THIS PHONE only (UserDefaults) — not sent anywhere,
/// so it adds nothing to the App Privacy label. Re-rentals are checked
/// against the unit tables the flyer reader pulls from each listing
/// (findacrib.com/featured_units.json); lotteries against their own band.
@Observable @MainActor
final class Qualify {
    static let shared = Qualify()

    private(set) var household: Int?
    private(set) var income: Int?
    private(set) var units: [String: Table] = [:]

    struct Row: Decodable {
        let beds: Int?
        let rent: Int?
        let household_size_min: Int?
        let household_size_max: Int?
        let income_min: Int?
        let income_max: Int?
    }
    struct Flag: Decodable { let code: String; let why: String }
    struct Table: Decodable {
        let units: [Row]
        let first_come_first_served: Bool?
        let deadline: String?
        let flags: [Flag]?
    }

    enum Verdict: String { case yes, high, low, unknown }

    init() {
        let d = UserDefaults.standard
        household = d.object(forKey: "qualify.household") as? Int
        income = d.object(forKey: "qualify.income") as? Int
    }

    var isSet: Bool { household != nil && income != nil }

    func set(household: Int, income: Int) {
        self.household = household; self.income = income
        UserDefaults.standard.set(household, forKey: "qualify.household")
        UserDefaults.standard.set(income, forKey: "qualify.income")
    }

    func clear() {
        household = nil; income = nil
        UserDefaults.standard.removeObject(forKey: "qualify.household")
        UserDefaults.standard.removeObject(forKey: "qualify.income")
    }

    func loadUnits() async {
        guard units.isEmpty, let url = URL(string: "https://findacrib.com/featured_units.json") else { return }
        struct File: Decodable { let listings: [String: Table] }
        if let (data, _) = try? await URLSession.shared.data(from: url),
           let f = try? JSONDecoder().decode(File.self, from: data) {
            units = f.listings
        }
    }

    nonisolated static func verdict(rows: [Row], household hh: Int, income inc: Int) -> Verdict {
        let forHh = rows.filter { (($0.household_size_min ?? 0) <= hh) && (hh <= ($0.household_size_max ?? 99)) }
        let pool = (forHh.isEmpty ? rows : forHh).filter { $0.income_min != nil || $0.income_max != nil }
        guard !pool.isEmpty else { return .unknown }
        if pool.contains(where: { (($0.income_min ?? 0) <= inc) && (inc <= ($0.income_max ?? .max)) }) { return .yes }
        if pool.allSatisfy({ $0.income_max != nil && inc > $0.income_max! }) { return .high }
        if pool.allSatisfy({ $0.income_min != nil && inc < $0.income_min! }) { return .low }
        return .unknown
    }

    func verdict(for f: FeaturedListing) -> Verdict? {
        guard let hh = household, let inc = income else { return nil }
        if let t = units[f.href], !t.units.isEmpty { return Self.verdict(rows: t.units, household: hh, income: inc) }
        if f.moneyKind == "income", f.moneyLow != nil || f.moneyHigh != nil {
            if inc < (f.moneyLow ?? 0) { return .low }
            if inc > (f.moneyHigh ?? .max) { return .high }
            return .yes
        }
        return .unknown
    }

    func verdict(incomeMin lo: Int?, incomeMax hi: Int?, householdMin hlo: Int?, householdMax hhi: Int?) -> Verdict? {
        guard let hh = household, let inc = income else { return nil }
        if let hlo, hh < hlo { return .unknown }
        if let hhi, hh > hhi { return .unknown }
        guard lo != nil || hi != nil else { return .unknown }
        if inc < (lo ?? 0) { return .low }
        if inc > (hi ?? .max) { return .high }
        return .yes
    }

    static func words(_ v: Verdict) -> String {
        switch v {
        case .yes: "You qualify"
        case .high: "Income above the limit"
        case .low: "Income below the minimum"
        case .unknown: "Check the listing's income limits"
        }
    }
}
