import Foundation
import MapKit

enum SearchMode: String, CaseIterable, Codable, Hashable {
    case rent = "Rent"                 // advertised now, with a real asking rent
    case stabilized = "Stabilized"     // every rent-stabilized building on file
    case vouchers = "Vouchers"         // Section 8 / voucher-friendly
    var noun: String {
        switch self { case .rent: "rentals"; case .stabilized: "buildings"; case .vouchers: "voucher listings" }
    }
}

struct MapBox: Codable, Hashable {
    var minLat: Double, maxLat: Double, minLng: Double, maxLng: Double
    init(region: MKCoordinateRegion) {
        minLat = region.center.latitude - region.span.latitudeDelta / 2
        maxLat = region.center.latitude + region.span.latitudeDelta / 2
        minLng = region.center.longitude - region.span.longitudeDelta / 2
        maxLng = region.center.longitude + region.span.longitudeDelta / 2
    }
    func contains(_ b: Building) -> Bool {
        b.lat >= minLat && b.lat <= maxLat && b.lng >= minLng && b.lng <= maxLng
    }
    var region: MKCoordinateRegion {
        .init(center: .init(latitude: (minLat + maxLat) / 2, longitude: (minLng + maxLng) / 2),
              span: .init(latitudeDelta: maxLat - minLat, longitudeDelta: maxLng - minLng))
    }
}

enum LocationScope: Codable, Hashable {
    case borough(String)        // code
    case neighborhood(String)   // exact nb name
    case zip(String)
    case mapArea(MapBox)

    var label: String {
        switch self {
        case .borough(let c): Borough.name(c)
        case .neighborhood(let n): n
        case .zip(let z): "ZIP \(z)"
        case .mapArea: "Custom map area"
        }
    }
    func matches(_ b: Building) -> Bool {
        switch self {
        case .borough(let c): b.b == c
        case .neighborhood(let n): b.nb == n
        case .zip(let z): b.z == z
        case .mapArea(let box): box.contains(b)
        }
    }
}

enum SortOrder: String, CaseIterable, Codable {
    case cheapest = "Least expensive"
    case priciest = "Most expensive"
    case fewestViolations = "Fewest violations"
    case mostUnits = "Most units"
    case newest = "Newest buildings"
}

struct SearchQuery: Codable, Hashable {
    var mode: SearchMode = .rent
    var locations: [LocationScope] = []
    var minPrice: Int? = nil
    var maxPrice: Int? = nil
    var beds: Set<Int> = []          // 0 = studio … 4 = 4+
    var unitBands: Set<Int> = []     // 0: 1–5, 1: 6–19, 2: 20–49, 3: 50+
    var noOpenViolations = false
    var voucherLiveOnly = false      // vouchers mode: only live AffordableHousing.com listings
    var sort: SortOrder = .cheapest

    /// "$1k - $3k, 1 bd" — the compressed summary in the results header.
    var summary: String {
        var parts: [String] = []
        switch (minPrice, maxPrice) {
        case let (lo?, hi?): parts.append("\(Formatters.short(lo)) - \(Formatters.short(hi))")
        case let (lo?, nil): parts.append("\(Formatters.short(lo))+")
        case let (nil, hi?): parts.append("Up to \(Formatters.short(hi))")
        default: break
        }
        if !beds.isEmpty {
            let s = beds.sorted().map { $0 == 0 ? "Studio" : ($0 == 4 ? "4+" : "\($0)") }.joined(separator: ", ")
            parts.append("\(s) bd")
        }
        if !unitBands.isEmpty { parts.append("\(unitBands.count) size\(unitBands.count == 1 ? "" : "s")") }
        if noOpenViolations { parts.append("No violations") }
        return parts.isEmpty ? "Any price" : parts.joined(separator: ", ")
    }

    var locationLabel: String {
        locations.isEmpty ? "All of NYC" : locations.map(\.label).joined(separator: ", ")
    }

    /// Filters beyond location, for the "Filter (3)" count.
    var activeFilterCount: Int {
        var n = 0
        if minPrice != nil { n += 1 }
        if maxPrice != nil { n += 1 }
        if !beds.isEmpty { n += 1 }
        if !unitBands.isEmpty { n += 1 }
        if noOpenViolations { n += 1 }
        if voucherLiveOnly { n += 1 }
        return n
    }
}

struct SavedSearch: Codable, Identifiable, Hashable {
    var id = UUID()
    var name: String
    var query: SearchQuery
    var createdAt = Date()
    var resultCount: Int
}
