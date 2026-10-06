import Foundation

/// Pure filter + sort over the in-memory dataset. Kept free of UI so the
/// unit tests can pin its semantics.
///
/// Searches read a SearchSnapshot (2026-10-02): an immutable copy of the
/// buildings plus their precomputed facts. That lets `runAsync`/`countAsync`
/// work on a background task and fan the scan out across every core, instead
/// of scanning all 47,165 rows on the main thread at each filter change. The
/// store-based `matches` / `sort` below stay as the reference semantics the
/// tests compare the snapshot path against.
enum SearchEngine {
    /// HCR-only searches run over the HCR pool (register buildings hosting a
    /// listing + stand-alone sites); everything else over the register.
    @MainActor
    static func pool(_ q: SearchQuery, _ store: DataStore) -> [Building] {
        q.normalized.hcrOnly ? store.hcrBuildings : store.buildings
    }

    @MainActor
    static func run(_ q: SearchQuery, store: DataStore) -> [Building] { run(q, snap: store.snapshot) }

    @MainActor
    static func count(_ q: SearchQuery, store: DataStore) -> Int { count(q, snap: store.snapshot) }

    /// Off the main actor: the scan and the sort run on a background task.
    @MainActor
    static func runAsync(_ q: SearchQuery, store: DataStore) async -> [Building] {
        let snap = store.snapshot
        return await Task.detached(priority: .userInitiated) { run(q, snap: snap) }.value
    }

    @MainActor
    static func countAsync(_ q: SearchQuery, store: DataStore) async -> Int {
        let snap = store.snapshot
        return await Task.detached(priority: .userInitiated) { count(q, snap: snap) }.value
    }

    /// The map's search: the matching buildings and, for each, the price its
    /// bubble shows (a live voucher listing's rent, where there is one).
    @MainActor
    static func runForMapAsync(_ q: SearchQuery, store: DataStore) async -> (buildings: [Building], prices: [String: Int]) {
        let snap = store.snapshot
        return await Task.detached(priority: .userInitiated) { () -> ([Building], [String: Int]) in
            let n = q.normalized
            let (pool, facts) = n.hcrOnly ? (snap.hcrPool, snap.hcrFacts) : (snap.pool, snap.facts)
            let idx = sorted(matching(n, pool, facts), n.sort, facts)
            var prices: [String: Int] = [:]
            prices.reserveCapacity(idx.count / 8)
            for i in idx {
                let f = facts[i]
                if f.voucherP >= 0 { prices[pool[i].bbl] = Int(f.voucherP) }
            }
            return (idx.map { pool[$0] }, prices)
        }.value
    }

    nonisolated static func run(_ q: SearchQuery, snap: SearchSnapshot) -> [Building] {
        Perf.interval("search.run") {
            let n = q.normalized
            let (pool, facts) = n.hcrOnly ? (snap.hcrPool, snap.hcrFacts) : (snap.pool, snap.facts)
            return sorted(matching(n, pool, facts), n.sort, facts).map { pool[$0] }
        }
    }

    nonisolated static func count(_ q: SearchQuery, snap: SearchSnapshot) -> Int {
        Perf.interval("search.count") {
            let n = q.normalized
            let (pool, facts) = n.hcrOnly ? (snap.hcrPool, snap.hcrFacts) : (snap.pool, snap.facts)
            return matching(n, pool, facts).count
        }
    }

    /// Indexes of the matching rows, in pool order. Large pools are cut into
    /// one run per core (two per core, so a slow one does not hold the rest
    /// up) and scanned at the same time.
    nonisolated static func matching(_ q: SearchQuery, _ pool: [Building], _ facts: [SearchSnapshot.Facts]) -> [Int] {
        let n = min(pool.count, facts.count)

        let chunks = n < 4096 ? 1 : min(ProcessInfo.processInfo.activeProcessorCount * 2, n / 2048)
        if chunks <= 1 {
            var out: [Int] = []
            for i in 0..<n where matches(pool[i], facts[i], q) { out.append(i) }
            return out
        }
        var parts = [[Int]](repeating: [], count: chunks)
        parts.withUnsafeMutableBufferPointer { buf in
            DispatchQueue.concurrentPerform(iterations: chunks) { c in
                let lo = n * c / chunks, hi = n * (c + 1) / chunks
                var out: [Int] = []
                out.reserveCapacity((hi - lo) / 2)
                for i in lo..<hi where matches(pool[i], facts[i], q) { out.append(i) }
                buf[c] = out
            }
        }
        return parts.flatMap { $0 }
    }

    /// The snapshot twin of `matchesNormalized`: the same rules, reading the
    /// precomputed facts instead of the store's dictionaries.
    @inline(__always)
    nonisolated static func matches(_ b: Building, _ f: SearchSnapshot.Facts, _ q: SearchQuery) -> Bool {
        if !q.locations.isEmpty, !q.locations.contains(where: { $0.matches(b) }) { return false }
        if q.minPrice != nil || q.maxPrice != nil {
            let p = f.voucherP >= 0 ? f.voucherP : f.priceOf
            guard p >= 0 else { return false }
            if let lo = q.minPrice, Int(p) < lo { return false }
            if let hi = q.maxPrice, Int(p) > hi { return false }
        }

        if q.vouchersOnly {
            if q.voucherLiveOnly { if !f.voucherLive { return false } }
            else if !f.voucherFriendly { return false }
        }
        if !q.unitBands.isEmpty {
            let u = f.units
            let band = u <= 5 ? 0 : (u <= 19 ? 1 : (u <= 49 ? 2 : 3))
            if !q.unitBands.contains(band) { return false }
        }
        if q.noOpenViolations, f.openViolations > 0 { return false }
        return true
    }

    /// Sorts row indexes on integer keys: price (or violations, units, year)
    /// then address rank — the same order as `sort` below, without comparing
    /// address strings.
    nonisolated static func sorted(_ idx: [Int], _ order: SortOrder, _ facts: [SearchSnapshot.Facts]) -> [Int] {
        switch order {
        case .cheapest:
            return idx.sorted { a, b in
                let pa = facts[a].priceOf >= 0 ? facts[a].priceOf : .max, pb = facts[b].priceOf >= 0 ? facts[b].priceOf : .max
                return pa != pb ? pa < pb : facts[a].addrRank < facts[b].addrRank
            }
        case .priciest:
            return idx.sorted { a, b in
                let pa = facts[a].priceOf, pb = facts[b].priceOf
                return pa != pb ? pa > pb : facts[a].addrRank > facts[b].addrRank
            }
        case .fewestViolations:
            return idx.sorted { a, b in
                let va = facts[a].openViolations, vb = facts[b].openViolations
                return va != vb ? va < vb : facts[a].addrRank < facts[b].addrRank
            }
        case .mostUnits:
            return idx.sorted { a, b in
                let ua = facts[a].units, ub = facts[b].units
                return ua != ub ? ua > ub : facts[a].addrRank > facts[b].addrRank
            }
        case .newest:
            return idx.sorted { a, b in
                let ya = facts[a].year, yb = facts[b].year
                return ya != yb ? ya > yb : facts[a].addrRank > facts[b].addrRank
            }
        }
    }

    /// Every building in the dataset is rent-stabilized; the Show flags narrow
    /// it (AND). Price filters read a live voucher listing's rent, else the
    /// building's ZIP estimate (or the rent its city publishes).
    @MainActor
    static func matches(_ b: Building, _ raw: SearchQuery, _ store: DataStore) -> Bool {
        matchesNormalized(b, raw.normalized, store)
    }

    /// `matches` with the query already normalized. The scans call this so
    /// the query is copied once per search, not once per building.
    @MainActor
    static func matchesNormalized(_ b: Building, _ q: SearchQuery, _ store: DataStore) -> Bool {
        if !q.locations.isEmpty, !q.locations.contains(where: { $0.matches(b) }) { return false }
        if q.minPrice != nil || q.maxPrice != nil {
            guard let p = store.voucherAvail(b)?.p ?? store.priceOf(b) else { return false }
            if let lo = q.minPrice, p < lo { return false }
            if let hi = q.maxPrice, p > hi { return false }
        }
        // No building record says what sizes its apartments are: bedrooms
        // came only from portal listings, dropped 2026-10-06. The bedroom
        // choice still narrows the re-rentals (ResultsView), never buildings.

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

    @MainActor
    static func sort(_ xs: [Building], _ order: SortOrder, _ store: DataStore) -> [Building] {
        switch order {
        // Price is looked up once per row, then sorted on: calling priceOf
        // inside the comparator was two dictionary hits per comparison, ~1.5M
        // for an all-of-New-York search.
        case .cheapest:
            return xs.map { (store.priceOf($0) ?? .max, $0) }
                .sorted { ($0.0, $0.1.a) < ($1.0, $1.1.a) }.map(\.1)
        case .priciest:
            return xs.map { (store.priceOf($0) ?? -1, $0) }
                .sorted { ($0.0, $0.1.a) > ($1.0, $1.1.a) }.map(\.1)
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
    @MainActor
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
