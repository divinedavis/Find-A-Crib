import Foundation

/// A spatial index over a building list (2026-10-02): rows bucketed into
/// ~500 m cells, so "what is in this map window" reads only the cells the
/// window covers instead of all 47,165 rows on every pan. Zoomed far out,
/// where the window covers more cells than exist, it falls back to the plain
/// scan, which is then the cheaper of the two.
struct GeoGrid: Sendable {
    static let cellDeg = 0.005
    let buildings: [Building]
    private let cells: [Int64: [Int32]]

    init(_ buildings: [Building]) {
        self.buildings = buildings
        var c: [Int64: [Int32]] = [:]
        c.reserveCapacity(buildings.count / 8)
        for (i, b) in buildings.enumerated() { c[Self.key(b.lat, b.lng), default: []].append(Int32(i)) }
        cells = c
    }

    @inline(__always) static func cell(_ v: Double) -> Int64 { Int64((v / cellDeg).rounded(.down)) }
    @inline(__always) static func key(_ lat: Double, _ lng: Double) -> Int64 { cell(lat) &* 1_000_003 &+ cell(lng) }

    /// Calls `body` with every building inside the box.
    func forEach(minLat: Double, maxLat: Double, minLng: Double, maxLng: Double, _ body: (Building) -> Void) {
        let i0 = Self.cell(minLat), i1 = Self.cell(maxLat), j0 = Self.cell(minLng), j1 = Self.cell(maxLng)
        let span = (i1 - i0 + 1) * (j1 - j0 + 1)
        if span <= 0 || span > Int64(cells.count) {
            for b in buildings where b.lat >= minLat && b.lat <= maxLat && b.lng >= minLng && b.lng <= maxLng { body(b) }
            return
        }
        for i in i0...i1 {
            for j in j0...j1 {
                guard let rows = cells[i &* 1_000_003 &+ j] else { continue }
                for r in rows {
                    let b = buildings[Int(r)]
                    if b.lat >= minLat && b.lat <= maxLat && b.lng >= minLng && b.lng <= maxLng { body(b) }
                }
            }
        }
    }

    func visible(minLat: Double, maxLat: Double, minLng: Double, maxLng: Double) -> [Building] {
        var out: [Building] = []
        forEach(minLat: minLat, maxLat: maxLat, minLng: minLng, maxLng: maxLng) { out.append($0) }
        return out
    }

    func count(minLat: Double, maxLat: Double, minLng: Double, maxLng: Double) -> Int {
        var n = 0
        forEach(minLat: minLat, maxLat: maxLat, minLng: minLng, maxLng: maxLng) { _ in n += 1 }
        return n
    }
}

/// Bench/test entry point: the same query the map makes, over the store.
enum MapViewport {
    @MainActor
    static func visible(in store: DataStore, minLat: Double, maxLat: Double, minLng: Double, maxLng: Double) -> [Building] {
        store.geoGrid.visible(minLat: minLat, maxLat: maxLat, minLng: minLng, maxLng: maxLng)
    }
}
