import Foundation
import MapKit

/// A city Find A Crib covers. The web app carries the same table in its CITIES
/// config; this mirrors it so the two clients agree on names, wording and which
/// public file holds the buildings.
///
/// Each city's register is a different thing, and the app says which: NYC is the
/// DHCR rent-stabilization register, LA is parcels meeting the RSO criteria, SF
/// is owner reports anonymised to the block, DC is units registered with DHCD.
/// Only NYC has the extra feeds (advertised rents, vouchers, HPD records,
/// lotteries), so `hasNYCExtras` gates every one of those surfaces rather than
/// each view guessing.
struct City: Identifiable, Hashable, Codable, Sendable {
    /// How a city divides up, and therefore what the picker offers once the
    /// city is chosen: boroughs in New York, named neighborhoods in SF and DC,
    /// and ZIP areas in LA, whose parcel source carries no neighborhood at all.
    enum RegionKind: String, Codable, Sendable { case borough, neighborhood, zip }

    let id: String
    let name: String          // "Los Angeles" — the full name, for headings
    let short: String         // "LA" — for the compact picker button
    let state: String
    let lat: Double
    let lng: Double
    let span: Double          // degrees of latitude the opening map covers
    /// Path under findacrib.com holding this city's buildings.
    let dataPath: String
    /// Flat filename for the on-disk cache (a path would need subdirectories).
    let cacheName: String
    let regionKind: RegionKind
    /// Singular label for one region: "Borough", "Neighborhood", "Area".
    let regionLabel: String
    /// What the register says a building IS, in the city's own words.
    let statusLabel: String
    /// The identifier the source uses, shown on the detail screen.
    let idLabel: String
    /// The caveat that belongs with every result from this source.
    let sourceNote: String
    let searchPlaceholder: String
    /// Whether ANY building in this city carries a rent. New York has
    /// advertised rents and HUD estimates; SF and DC publish a reported or
    /// registered rent on some rows; LA's assessor roll has no rent at all, so
    /// a price filter there can only ever return nothing.
    let hasPrices: Bool
    /// What a rent on a card means here — never an asking rent outside NYC.
    let priceLabel: String

    var isNYC: Bool { id == "nyc" }
    /// Advertised rents, vouchers, HPD violations/complaints and HCR lotteries
    /// exist only for New York; everywhere else those files 404 by design.
    var hasNYCExtras: Bool { isNYC }
    var region: MKCoordinateRegion {
        .init(center: .init(latitude: lat, longitude: lng),
              span: .init(latitudeDelta: span, longitudeDelta: span))
    }

    static let nyc = City(
        id: "nyc", name: "New York City", short: "NYC", state: "NY",
        lat: 40.72, lng: -73.97, span: 0.42,
        dataPath: "buildings.slim.json.gz", cacheName: "buildings.slim.json.gz",
        regionKind: .borough, regionLabel: "Borough",
        statusLabel: "Rent-stabilized", idLabel: "BBL",
        sourceNote: "Registered with NYS Homes and Community Renewal under rent stabilization.",
        searchPlaceholder: "Neighborhood, borough or ZIP",
        hasPrices: true, priceLabel: "Asking rent")

    static let la = City(
        id: "la", name: "Los Angeles", short: "LA", state: "CA",
        lat: 34.06, lng: -118.31, span: 0.55,
        dataPath: "la/buildings.min.json.gz", cacheName: "la-buildings.min.json.gz",
        regionKind: .zip, regionLabel: "Area",
        statusLabel: "Likely rent-stabilized (RSO)", idLabel: "APN",
        sourceNote: "Meets LA's RSO criteria — 2+ units, built on or before Oct 1, 1978 (LA County assessor rolls). A few exemptions can't be derived from tax data, so verify the address on ZIMAS.",
        searchPlaceholder: "Address, ZIP or APN",
        hasPrices: false, priceLabel: "")

    static let sf = City(
        id: "sf", name: "San Francisco", short: "SF", state: "CA",
        lat: 37.7749, lng: -122.4194, span: 0.16,
        dataPath: "sf/buildings.min.json.gz", cacheName: "sf-buildings.min.json.gz",
        regionKind: .neighborhood, regionLabel: "Neighborhood",
        statusLabel: "Rent-controlled (reported)", idLabel: "",
        sourceNote: "Block-level data: the SF Rent Board anonymises owner reports to the block, so a pin is a block-side of rent-controlled units, not one specific building.",
        searchPlaceholder: "Neighborhood, address or block",
        hasPrices: true, priceLabel: "Median reported rent")

    static let dc = City(
        id: "dc", name: "Washington DC", short: "DC", state: "DC",
        lat: 38.905, lng: -77.02, span: 0.18,
        dataPath: "dc/buildings.min.json.gz", cacheName: "dc-buildings.min.json.gz",
        regionKind: .neighborhood, regionLabel: "Neighborhood",
        statusLabel: "Rent-controlled (registered)", idLabel: "Reg. #",
        sourceNote: "Registered with DHCD under the Rental Housing Act. Coverage is per unit, so a property can hold both controlled and exempt units — the count here is the controlled ones.",
        searchPlaceholder: "Neighborhood, address or ZIP",
        hasPrices: true, priceLabel: "Median registered rent")

    static let all: [City] = [.nyc, .la, .sf, .dc]
    static func find(_ id: String?) -> City { all.first { $0.id == id } ?? .nyc }
}
