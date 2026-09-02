import Foundation

/// Pure filter + sort over the in-memory dataset. Kept free of UI so the
/// unit tests can pin its semantics.
@MainActor
enum SearchEngine {
    static func run(_ q: SearchQuery, store: DataStore) -> [Building] {
        var out: [Building] = []
        out.reserveCapacity(1024)
        for b in store.buildings where matches(b, q, store) { out.append(b) }
        return sort(out, q.sort, store)
    }

    static func count(_ q: SearchQuery, store: DataStore) -> Int {
        var n = 0
        for b in store.buildings where matches(b, q, store) { n += 1 }
        return n
    }

    static func matches(_ b: Building, _ raw: SearchQuery, _ store: DataStore) -> Bool {
        let q = raw.normalized
        if !q.locations.isEmpty, !q.locations.contains(where: { $0.matches(b) }) { return false }
        switch q.mode {
        case .rent, .stabilized where q.availableOnly:
            guard let p = store.price(b) else { return false }
            if let lo = q.minPrice, p < lo { return false }
            if let hi = q.maxPrice, p > hi { return false }
            if !q.beds.isEmpty {
                let bd = store.beds(b)
                let hit = bd.contains { n in q.beds.contains(n >= 4 ? 4 : n) }
                if !hit { return false }
            }
        case .stabilized:
            if q.minPrice != nil || q.maxPrice != nil {
                guard let p = store.priceOf(b) else { return false }
                if let lo = q.minPrice, p < lo { return false }
                if let hi = q.maxPrice, p > hi { return false }
            }
            if !q.unitBands.isEmpty {
                let u = b.u ?? 0
                let band = u <= 5 ? 0 : (u <= 19 ? 1 : (u <= 49 ? 2 : 3))
                if !q.unitBands.contains(band) { return false }
            }
        case .vouchers:
            if q.voucherLiveOnly { if store.voucherAvail(b) == nil { return false } }
            else if !store.isVoucherFriendly(b) { return false }
            if q.minPrice != nil || q.maxPrice != nil {
                guard let p = store.voucherAvail(b)?.p ?? store.priceOf(b) else { return false }
                if let lo = q.minPrice, p < lo { return false }
                if let hi = q.maxPrice, p > hi { return false }
            }
        }
        if q.noOpenViolations, b.openViolations > 0 { return false }
        return true
    }

    static func sort(_ xs: [Building], _ order: SortOrder, _ store: DataStore) -> [Building] {
        switch order {
        case .cheapest:
            return xs.sorted { (store.priceOf($0) ?? .max, $0.a) < (store.priceOf($1) ?? .max, $1.a) }
        case .priciest:
            return xs.sorted { (store.priceOf($0) ?? -1, $0.a) > (store.priceOf($1) ?? -1, $1.a) }
        case .fewestViolations:
            return xs.sorted { ($0.openViolations, $0.a) < ($1.openViolations, $1.a) }
        case .mostUnits:
            return xs.sorted { ($0.u ?? 0, $0.a) > ($1.u ?? 0, $1.a) }
        case .newest:
            return xs.sorted { ($0.yr ?? 0, $0.a) > ($1.yr ?? 0, $1.a) }
        }
    }

    /// Nearest buildings to `b` in the same neighborhood — the "Similar
    /// homes" rail on the detail page.
    static func similar(to b: Building, store: DataStore, limit: Int = 8) -> [Building] {
        let pool = store.buildings.filter { $0.nb == b.nb && $0.bbl != b.bbl }
        func d2(_ x: Building) -> Double { let dl = x.lat - b.lat, dg = x.lng - b.lng; return dl * dl + dg * dg }
        return Array(pool.sorted { d2($0) < d2($1) }.prefix(limit))
    }
}
