import Foundation

/// Pure filter + sort over the in-memory dataset. Kept free of UI so the
/// unit tests can pin its semantics.
@MainActor
enum SearchEngine {
    /// HCR-only searches run over the HCR pool (register buildings hosting a
    /// listing + stand-alone sites); everything else over the register.
    static func pool(_ q: SearchQuery, _ store: DataStore) -> [Building] {
        q.normalized.hcrOnly ? store.hcrBuildings : store.buildings
    }

    static func run(_ q: SearchQuery, store: DataStore) -> [Building] {
        var out: [Building] = []
        out.reserveCapacity(1024)
        for b in pool(q, store) where matches(b, q, store) { out.append(b) }
        return sort(out, q.sort, store)
    }

    static func count(_ q: SearchQuery, store: DataStore) -> Int {
        var n = 0
        for b in pool(q, store) where matches(b, q, store) { n += 1 }
        return n
    }

    /// Every building in the dataset is rent-stabilized; the Show flags narrow
    /// it (AND). Price filters use the real asking rent when the search is
    /// available-only, otherwise the building's price-or-ZIP-estimate.
    static func matches(_ b: Building, _ raw: SearchQuery, _ store: DataStore) -> Bool {
        let q = raw.normalized
        if !q.locations.isEmpty, !q.locations.contains(where: { $0.matches(b) }) { return false }
        if q.availableOnly {
            guard let p = store.price(b) else { return false }
            if let lo = q.minPrice, p < lo { return false }
            if let hi = q.maxPrice, p > hi { return false }
        } else if q.minPrice != nil || q.maxPrice != nil {
            guard let p = store.voucherAvail(b)?.p ?? store.priceOf(b) else { return false }
            if let lo = q.minPrice, p < lo { return false }
            if let hi = q.maxPrice, p > hi { return false }
        }
        // Bedrooms come from recent listings, so a bedroom filter narrows to
        // advertised buildings on its own — it no longer needs Available now
        // ticked first (2026-09-08: the control was hidden behind that box and
        // read as missing).
        if !q.beds.isEmpty {
            let bd = store.beds(b)
            if bd.isEmpty || !bd.contains(where: { n in q.beds.contains(n >= 4 ? 4 : n) }) { return false }
        }
        if q.vouchersOnly {
            if q.voucherLiveOnly { if store.voucherAvail(b) == nil { return false } }
            else if !store.isVoucherFriendly(b) { return false }
        }
        if !q.unitBands.isEmpty {
            let u = b.u ?? 0
            let band = u <= 5 ? 0 : (u <= 19 ? 1 : (u <= 49 ? 2 : 3))
            if !q.unitBands.contains(band) { return false }
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
    /// The nearest few buildings in the same neighborhood.
    ///
    /// Reads DataStore's neighborhood index rather than scanning the whole
    /// city: this used to filter all 47,165 rows and sort the matches, and the
    /// detail screen called it from `body`, so a single visit ran it seven
    /// times. Same answer, a dictionary hit and a partial selection instead.
    static func similar(to b: Building, store: DataStore, limit: Int = 8) -> [Building] {
        Perf.span("SearchEngine.similar") {
            guard let nb = b.nb, let pool = store.byNeighborhood[nb] else { return [] }
            func d2(_ x: Building) -> Double { let dl = x.lat - b.lat, dg = x.lng - b.lng; return dl * dl + dg * dg }
            // Selection beats a full sort here: the rail shows 8 of what can be
            // a few thousand, and only the ids are needed to look rows up again.
            var best: [(Double, Int)] = []
            best.reserveCapacity(limit + 1)
            for (i, x) in pool.enumerated() where x.bbl != b.bbl {
                let d = d2(x)
                if best.count < limit {
                    best.append((d, i))
                    if best.count == limit { best.sort { $0.0 < $1.0 } }
                } else if d < best[limit - 1].0 {
                    best[limit - 1] = (d, i)
                    var k = limit - 1
                    while k > 0, best[k].0 < best[k - 1].0 { best.swapAt(k, k - 1); k -= 1 }
                }
            }
            if best.count < limit { best.sort { $0.0 < $1.0 } }
            return best.map { pool[$0.1] }
        }
    }
}
