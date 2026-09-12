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

    /// Where this city's per-building record blob lives, if it has one. NYC's
    /// detail comes live from NYC Open Data instead, so it has none.
    let recordsPath: String?
    /// What this city publishes about a building beyond the register itself,
    /// and what it calls those things. Every city publishes something and no
    /// two publish the same thing, so the detail screen renders from this
    /// rather than from an HPD-shaped form with most of it blank.
    let records: Records?
    /// The sentence that belongs under every building in this city, naming the
    /// register it comes from.
    let aboutNote: String
    /// Who to credit at the foot of a building screen.
    let sourcesNote: String

    struct Records: Hashable, Codable, Sendable {
        let heading: String            // section title: "LAHD record"
        let agency: String             // "LAHD", "the SF Rent Board"
        /// Everything here describes this one property, or — SF — this block.
        let scope: String
        let violationsLabel: String?   // nil where the city publishes none
        let complaintsLabel: String?
        let evictionsLabel: String?
        let petitionsLabel: String?
        let buyoutsLabel: String?
        let casesLabel: String?
        let showsOwner: Bool
        /// Said out loud where a city publishes no code violations: an absent
        /// panel reads as a clean building, and only a sentence reads as
        /// "nobody publishes this."
        let noViolationsNote: String?
        let noViolationsLink: String?
        let noViolationsLinkLabel: String?
        let emptyNote: String
        let note: String?
    }

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
        hasPrices: true, priceLabel: "Asking rent",
        recordsPath: nil, records: nil,
        aboutNote: "Registered with NYS Homes and Community Renewal as rent stabilized (2024 building file). Rents in stabilized units rise only by the Rent Guidelines Board's annual percentage, and tenants have a right to renew.",
        sourcesNote: "Sources: NYS HCR 2024 rent-stabilized building file · NYC HPD violations, complaints and bedbug filings · NYC DOHMH rodent inspections · HUD FY2026 Small-Area Fair Market Rents · Recently advertised rents via Zumper.")

    static let la = City(
        id: "la", name: "Los Angeles", short: "LA", state: "CA",
        lat: 34.06, lng: -118.31, span: 0.55,
        dataPath: "la/buildings.slim.json.gz", cacheName: "la-buildings.slim.json.gz",
        // LA parcels carried no neighborhood at all until the LA Times
        // boundaries were joined on 2026-09-12, which is why this used to offer
        // ZIP areas — the only thing an LA record knew about where it was.
        regionKind: .neighborhood, regionLabel: "Neighborhood",
        statusLabel: "Likely rent-stabilized (RSO)", idLabel: "APN",
        sourceNote: "Meets LA's RSO criteria — 2+ units, built on or before Oct 1, 1978 (LA County assessor rolls). A few exemptions can't be derived from tax data, so verify the address on ZIMAS.",
        searchPlaceholder: "Neighborhood, address or ZIP",
        hasPrices: false, priceLabel: "",
        recordsPath: "la/buildings.hpd.json.gz", records: Records(
            heading: "LAHD record", agency: "LAHD", scope: "this property",
            violationsLabel: "Housing code violations",
            complaintsLabel: "Complaints to LAHD",
            evictionsLabel: "Eviction notices filed",
            petitionsLabel: nil,
            buyoutsLabel: "Tenant buyouts",
            casesLabel: "Enforcement cases",
            showsOwner: false,
            noViolationsNote: nil, noViolationsLink: nil, noViolationsLinkLabel: nil,
            emptyNote: "LAHD has no enforcement record for this parcel.",
            note: "From the Los Angeles Housing Department's property look-up. LA does not grade violations by hazard class the way New York does."),
        aboutNote: "Meets the City of LA's Rent Stabilization Ordinance criteria — two or more units, built on or before Oct 1, 1978. A few exemptions can't be derived from tax data, so verify the address on ZIMAS.",
        sourcesNote: "Sources: LA County Assessor parcel roll · Los Angeles Housing Department property look-up (violations, complaints, evictions, buyouts) · LA Times Mapping L.A. neighborhood boundaries.")

    static let sf = City(
        id: "sf", name: "San Francisco", short: "SF", state: "CA",
        lat: 37.7749, lng: -122.4194, span: 0.16,
        dataPath: "sf/buildings.slim.json.gz", cacheName: "sf-buildings.slim.json.gz",
        regionKind: .neighborhood, regionLabel: "Neighborhood",
        statusLabel: "Rent-controlled (reported)", idLabel: "",
        sourceNote: "Block-level data: the SF Rent Board anonymises owner reports to the block, so a pin is a block-side of rent-controlled units, not one specific building.",
        searchPlaceholder: "Neighborhood, address or block",
        hasPrices: true, priceLabel: "Median reported rent",
        recordsPath: "sf/buildings.hpd.json.gz", records: Records(
            heading: "Rent Board record", agency: "the SF Rent Board", scope: "this block",
            violationsLabel: nil,
            complaintsLabel: nil,
            evictionsLabel: "Eviction notices",
            petitionsLabel: "Rent Board petitions",
            buyoutsLabel: "Buyout agreements",
            casesLabel: nil,
            showsOwner: false,
            noViolationsNote: "San Francisco publishes housing-code violations by street address, and the Rent Board anonymises this map to the block — so there is no honest way to show them here. Look an address up directly with SF DBI.",
            noViolationsLink: "https://dbiweb02.sfgov.org/dbipts/",
            noViolationsLinkLabel: "Look up an address at SF DBI",
            emptyNote: "No Rent Board eviction, petition or buyout on file for this block.",
            note: "Filed with the SF Rent Board. Like the rent figures, these are anonymised to the block, so they cover every building on this block-side rather than one address."),
        aboutNote: "Covered by the San Francisco Rent Ordinance and reported to the Rent Board by the owner. Reports are anonymised to the block, so this pin is a block-side of rent-controlled units rather than one address.",
        sourcesNote: "Sources: SF Rent Board Housing Inventory via DataSF (owner-reported, block-anonymised) · SF Rent Board eviction notices, petitions and buyout agreements.")

    static let dc = City(
        id: "dc", name: "Washington DC", short: "DC", state: "DC",
        lat: 38.905, lng: -77.02, span: 0.18,
        dataPath: "dc/buildings.slim.json.gz", cacheName: "dc-buildings.slim.json.gz",
        regionKind: .neighborhood, regionLabel: "Neighborhood",
        statusLabel: "Rent-controlled (registered)", idLabel: "Reg. #",
        sourceNote: "Registered with DHCD under the Rental Housing Act. Coverage is per unit, so a property can hold both controlled and exempt units — the count here is the controlled ones.",
        searchPlaceholder: "Neighborhood, address or ZIP",
        hasPrices: true, priceLabel: "Median registered rent",
        recordsPath: "dc/buildings.hpd.json.gz", records: Records(
            heading: "Owner & assessor record", agency: "the DC assessor", scope: "this property",
            violationsLabel: nil,
            complaintsLabel: nil,
            evictionsLabel: nil,
            petitionsLabel: nil,
            buyoutsLabel: nil,
            casesLabel: nil,
            showsOwner: true,
            noViolationsNote: "Washington DC publishes no housing-code violation data — the Department of Buildings releases none, so no map can show it. File or check a complaint with DOB directly.",
            noViolationsLink: "https://dob.dc.gov/",
            noViolationsLinkLabel: "DC Department of Buildings",
            emptyNote: "No assessor record matched this registration.",
            note: "From the DC Office of Tax and Revenue — the owner on the tax roll and the assessor's record of the building, matched to this registration through its address."),
        aboutNote: "Registered with DC DHCD under the Rental Housing Act. Coverage is decided per unit, so a property can hold both controlled and exempt units — the count here is the controlled ones.",
        sourcesNote: "Sources: DC DHCD RentRegistry public exports · DC Office of Tax and Revenue (CAMA assessor roll, Integrated Tax System) · DCGIS address-to-lot cross reference.")

    static let all: [City] = [.nyc, .la, .sf, .dc]
    static func find(_ id: String?) -> City { all.first { $0.id == id } ?? .nyc }
}
