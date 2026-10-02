import Foundation

/// Everything a search reads, frozen into plain arrays that line up with the
/// building array (2026-10-02). Two things follow from that:
///
/// 1. A search can run OFF the main actor: the snapshot is an immutable value,
///    so a background task (and every core it fans out to) reads it safely
///    while the UI keeps drawing. SearchEngine was @MainActor and scanned all
///    47,165 rows on the main thread on every filter change.
/// 2. Each building's derived facts are worked out ONCE per data load instead
///    of once per building per search: the recent asking rent, the price the
///    sort uses, bedrooms as a bit mask, voucher flags, and the building's rank
///    in address order so sorts compare integers instead of strings (the
///    all-of-New-York cheapest sort spent most of its time in String <).
///
/// Built off the main actor alongside the decode; rebuilt when the daily feeds
/// refresh, since they are what the facts come from.
struct SearchSnapshot: Sendable {
    struct Facts: Sendable {
        /// Asking rent while the listing is recent (DataStore.price), else -1.
        var recent: Int32 = -1
        /// The sort/filter price (DataStore.priceOf), else -1.
        var priceOf: Int32 = -1
        /// Live voucher listing rent (s8.avail p), else -1.
        var voucherP: Int32 = -1
        var voucherLive = false        // s8.avail has the building
        var voucherFriendly = false    // s8.avail or s8.bldg has it
        /// Bit n set when a recent listing has n bedrooms (4 = 4+).
        var bedsMask: UInt8 = 0
        var openViolations: Int32 = 0
        var units: Int32 = 0
        var year: Int32 = 0
        /// Position in address order; equal addresses share a rank.
        var addrRank: Int32 = 0
    }

    var pool: [Building] = []
    var facts: [Facts] = []
    var hcrPool: [Building] = []
    var hcrFacts: [Facts] = []

    static let empty = SearchSnapshot()

    nonisolated static func facts(for buildings: [Building], listings: ListingsBlob, s8: S8Blob,
                                  fmr: FMRTable, now: Date = Date()) -> [Facts] {
        // Address ranks: one string sort here instead of ~700k string
        // comparisons inside every sorted search.
        let order = buildings.indices.sorted { buildings[$0].a < buildings[$1].a }
        var rank = [Int32](repeating: 0, count: buildings.count)
        var r: Int32 = 0
        for (k, i) in order.enumerated() {
            if k > 0, buildings[order[k - 1]].a != buildings[i].a { r += 1 }
            rank[i] = r
        }
        var out = [Facts](repeating: Facts(), count: buildings.count)
        for (i, b) in buildings.enumerated() {
            var f = Facts()
            if listings.isRecent(b.bbl, now: now), let p = listings.prices[b.bbl] { f.recent = Int32(clamping: p) }
            if let p = listings.prices[b.bbl] {
                f.priceOf = Int32(clamping: p)
            } else if let z = b.z, let e = fmr[z], e.count >= 3 {
                f.priceOf = Int32(clamping: (e[0] + e[2]) / 2)
            } else if let m = b.mr {
                f.priceOf = Int32(clamping: m)
            }
            if let a = s8.avail[b.bbl] {
                f.voucherLive = true
                if let p = a.p { f.voucherP = Int32(clamping: p) }
            }
            f.voucherFriendly = f.voucherLive || s8.bldg[b.bbl] != nil
            for n in listings.beds[b.bbl] ?? [] { f.bedsMask |= UInt8(1) << UInt8(min(max(n, 0), 4)) }
            f.openViolations = Int32(clamping: b.openViolations)
            f.units = Int32(clamping: b.u ?? 0)
            f.year = Int32(clamping: b.yr ?? 0)
            f.addrRank = rank[i]
            out[i] = f
        }
        return out
    }
}
