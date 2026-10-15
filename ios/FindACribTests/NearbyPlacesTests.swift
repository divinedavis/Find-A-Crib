import Testing
@testable import FindACrib

/// The legal row is home and apartment law only (owner, 2026-10-14). These are
/// real Apple Maps results for housing searches near three NYC buildings; the
/// same names are checked against index.html's isLegalName in tests/test_nearby_legal.py.
@Suite("Nearby housing legal help filter")
struct NearbyPlacesTests {
    @Test("keeps housing legal help", arguments: [
        "The Legal Aid Society", "Harlem Legal Services", "Bronx Legal Services", "Legal Services NYC",
        "Legal Services for New York", "Brooklyn Legal Services Corporation A", "Mobilization for Justice",
        "Tenant Rights Law Group", "Eviction Defense Attorneys", "Landlord Tenant Law Office of J. Doe",
    ])
    func keeps(_ name: String) { #expect(NearbyPlaces.isLegal(name)) }

    @Test("drops anything not clearly housing law", arguments: [
        "The Portela Law Firm, P.C.", "Law Office of Patricia M Machado", "Personal Injury Lawyer Brooklyn",
        "Peter J. Schaffer Bronx Criminal Lawyer", "Commercial Tenant Landlord Lawyer", "Jersey Landlord Lawyer",
        "Landlord & Tenant Consultation Services", "Bronx Housing Court Office", "Neighborhood Defender Service",
        "The Brooklyn District Attorney’s Office", "Tato Legal Services", "Notary Public", "William Tax Solutions",
        "2125 Tenant Association", "Real Estate", "Starbucks Coffee Company",
    ])
    func drops(_ name: String) { #expect(!NearbyPlaces.isLegal(name)) }

    @Test func distanceReadsInMiles() {
        #expect(NearbyPlaces.distance(50) == "Under 0.1 mi")
        #expect(NearbyPlaces.distance(1609.34) == "1.0 mi")
    }
}

/// The researched firm list behind "Housing law firms in <borough>" (owner,
/// 2026-10-14: at least three per borough).
@Suite("Housing law firms by borough")
struct HousingLawFirmTests {
    @Test("at least three firms in every borough", arguments: Borough.all.map(\.name))
    func threePerBorough(_ borough: String) {
        #expect(HousingLawFirm.all.filter { $0.borough == borough }.count >= 3)
    }

    @Test func everyFirmHasASiteAndASource() {
        #expect(!HousingLawFirm.all.isEmpty)
        for f in HousingLawFirm.all {
            #expect(f.website.hasPrefix("https://") || f.website.hasPrefix("http://"), "\(f.name)")
            #expect(f.source.hasPrefix("http"), "\(f.name)")
            #expect(Borough.all.contains { $0.name == f.borough }, "\(f.name): \(f.borough)")
        }
    }
}
