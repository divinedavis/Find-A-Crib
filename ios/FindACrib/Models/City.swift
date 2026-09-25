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
    /// What a building here IS, as one word for headlines: "rent-stabilized",
    /// "rent-controlled", "income-restricted" — the status label without its
    /// qualifier ("Likely rent-stabilized (RSO)" -> "rent-stabilized").
    var registerWord: String {
        var word = statusLabel.lowercased()
        if let paren = word.firstIndex(of: "(") { word = String(word[word.startIndex..<paren]) }
        return word.replacingOccurrences(of: "likely ", with: "").trimmingCharacters(in: .whitespaces)
    }
    /// The green badge on every card (owner, 2026-09-24: Philadelphia's cards
    /// said "Rent stabilized"). New York's wording stays New York's.
    var badgeLabel: String {
        switch id {
        case "nyc": return "Rent stabilized"
        case "la": return "Likely RSO"
        case "sf", "dc": return "Rent controlled"
        default: return isIncomeRestricted ? "Income-restricted" : statusLabel
        }
    }
    /// A city whose map is its income-restricted buildings rather than a
    /// rent-regulation register (Chicago, Miami-Dade, Atlanta, Philadelphia).
    var isIncomeRestricted: Bool { ["chi", "mia", "atl", "phl"].contains(id) }
    /// Advertised rents, vouchers, HPD violations/complaints and HCR lotteries
    /// exist only for New York; everywhere else those files 404 by design.
    var hasNYCExtras: Bool { isNYC }

    /// What the locked "Show" row says this register covers, in the city's own
    /// terms — the filter sheet shows it above the options.
    var registerNote: String {
        switch id {
        case "la": return "Parcels meeting LAHD's RSO criteria"
        case "sf": return "Units reported to the SF Rent Board"
        case "dc": return "Units registered with DC DHCD"
        case _ where isIncomeRestricted: return "Income-restricted buildings"
        default:   return "Every building on the DHCR register"
        }
    }
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

    /// The rent-regulated cities, each with its own register, then the four
    /// whose map is their income-restricted buildings (owner, 2026-09-24:
    /// "lets add the four cities - lets only add cities").
    static let all: [City] = [.nyc, .la, .sf, .dc, .chi, .mia, .atl, .phl]

    static let chi = affordable(id: "chi", name: "Chicago", short: "CHI", state: "IL", lat: 41.84, lng: -87.69, span: 0.42,
        sources: "Chicago Department of Housing (Affordable Requirements Ordinance buildings; affordable rental developments) · HUD Low-Income Housing Tax Credit database · HUD public housing (Chicago Housing Authority).")
    static let mia = affordable(id: "mia", name: "Miami-Dade", short: "MIA", state: "FL", lat: 25.70, lng: -80.30, span: 0.6,
        sources: "Florida Housing Finance Corporation rental properties and HUD/USDA assisted properties (via UF Shimberg Center) · HUD Low-Income Housing Tax Credit database · HUD public housing (Miami-Dade PHCD).")
    static let atl = affordable(id: "atl", name: "Atlanta", short: "ATL", state: "GA", lat: 33.76, lng: -84.42, span: 0.26,
        sources: "City of Atlanta Office of Housing Housing Tracker · Atlanta Beltline affordable housing developments · HUD Low-Income Housing Tax Credit database · HUD public housing (Atlanta Housing).")
    static let phl = affordable(id: "phl", name: "Philadelphia", short: "PHL", state: "PA", lat: 39.99, lng: -75.14, span: 0.26,
        sources: "Philadelphia DHCD Affordable Housing Production · HUD Low-Income Housing Tax Credit database · HUD public housing (Philadelphia Housing Authority).")

    /// A city whose map is its income-restricted buildings: none of these
    /// has a rent-stabilization register, and none runs a lottery portal —
    /// each merges its own open data with HUD's (build_affordable_cities.py).
    static func affordable(id: String, name: String, short: String, state: String,
                           lat: Double, lng: Double, span: Double, sources: String) -> City {
        City(
            id: id, name: name, short: short, state: state,
            lat: lat, lng: lng, span: span,
            dataPath: "\(id)/buildings.slim.json.gz", cacheName: "\(id)-buildings.slim.json.gz",
            regionKind: .zip, regionLabel: "ZIP",
            statusLabel: "Income-restricted", idLabel: "",
            sourceNote: "An income-restricted building: some or all of its units are for households under an income limit, at capped rents. Apply through the building's leasing office or waiting list.",
            searchPlaceholder: "Address or ZIP",
            hasPrices: false, priceLabel: "",
            recordsPath: "\(id)/buildings.hpd.json.gz", records: Records(
                heading: "Income-restricted units", agency: "the city and HUD", scope: "this building",
                violationsLabel: nil, complaintsLabel: nil, evictionsLabel: nil, petitionsLabel: nil,
                buyoutsLabel: nil, casesLabel: nil, showsOwner: false,
                noViolationsNote: nil, noViolationsLink: nil, noViolationsLinkLabel: nil,
                emptyNote: "No unit detail on file for this building.",
                note: nil),
            aboutNote: "Income-restricted housing: built or kept affordable with public money — tax credits, city programs, inclusionary zoning or public housing — so some or all of its units are for households under an income limit, at capped rents. There is no citywide lottery here; each building keeps its own waiting list, so call or apply through the leasing office.",
            sourcesNote: "Sources: " + sources)
    }

    static func find(_ id: String?) -> City { all.first { $0.id == id } ?? .nyc }
}
