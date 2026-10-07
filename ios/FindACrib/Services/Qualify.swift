import Foundation
import Observation

/// "What do I qualify for?" (free, owner 2026-10-03). Household size and
/// yearly income, kept ON THIS PHONE only (Keychain, this-device-only since
/// 2026-10-07; was UserDefaults, migrated on first launch) — not sent anywhere,
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

    /// Keychain account holding `{"household":N,"income":N}`.
    nonisolated static let account = "qualify"
    /// Pre-2026-10-07 UserDefaults keys, read once to migrate and then deleted.
    nonisolated static let legacyKeys = (household: "qualify.household", income: "qualify.income")

    nonisolated static let installMarker = "qualify.keychainInstalled"

    private struct Stored: Codable { var household: Int; var income: Int }

    private let store: SecureStore

    init(store: SecureStore = SecureStore(service: "com.findacrib.qualify"),
         defaults: UserDefaults = .standard) {
        self.store = store
        // Keychain items outlive an uninstall; UserDefaults does not. With no
        // install marker this is a fresh install, so a leftover item from a
        // previous install is dropped (keeps the old "delete app = forget it").
        if !defaults.bool(forKey: Self.installMarker) {
            if defaults.object(forKey: Self.legacyKeys.household) == nil { store.remove(Self.account) }
            defaults.set(true, forKey: Self.installMarker)
        }
        if let d = store.data(Self.account), let s = try? JSONDecoder().decode(Stored.self, from: d) {
            household = s.household; income = s.income
        } else if let hh = defaults.object(forKey: Self.legacyKeys.household) as? Int,
                  let inc = defaults.object(forKey: Self.legacyKeys.income) as? Int {
            household = hh; income = inc
            // Keep the plaintext copy if the Keychain write failed, so a
            // locked-keychain launch retries next time instead of losing it.
            guard persist() else { return }
        }
        // Drop the plaintext copies (also a half-set pair).
        defaults.removeObject(forKey: Self.legacyKeys.household)
        defaults.removeObject(forKey: Self.legacyKeys.income)
    }

    var isSet: Bool { household != nil && income != nil }

    func set(household: Int, income: Int) {
        self.household = household; self.income = income
        persist()
    }

    func clear() {
        household = nil; income = nil
        store.remove(Self.account)
    }

    @discardableResult
    private func persist() -> Bool {
        guard let household, let income,
              let d = try? JSONEncoder().encode(Stored(household: household, income: income)) else { return false }
        return store.set(d, for: Self.account)
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

    /// Bedroom sizes a re-rental offers: the feed's own, plus every row of
    /// its flyer / listing table (featured_units.json). Empty = not stated.
    func bedrooms(_ f: FeaturedListing) -> Set<Int> { Self.bedrooms(f, rows: units[f.href]?.units ?? []) }

    nonisolated static func bedrooms(_ f: FeaturedListing, rows: [Row]) -> Set<Int> {
        var out = Set<Int>()
        if let b = f.beds, let n = LotteryFeed.bedCount(b) { out.insert(min(n, 4)) }
        for r in rows { if let n = r.beds { out.insert(min(n, 4)) } }
        return out
    }

    /// Out of range for the household/income on file: above the limit or
    /// below the minimum. Those leave the lists (owner, 2026-10-04: "if my
    /// income is above the limit … i shouldnt see the listing").
    func outOfRange(_ f: FeaturedListing) -> Bool {
        guard let v = verdict(for: f) else { return false }
        return v == .high || v == .low
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
