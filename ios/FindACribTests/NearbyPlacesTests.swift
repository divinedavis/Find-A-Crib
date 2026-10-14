import Testing
@testable import FindACrib

/// The legal-services row keeps only names that read as legal offices. These
/// are real Apple Maps results near 1 Audubon Ave (2026-10-14).
@Suite("Nearby legal services filter")
struct NearbyPlacesTests {
    @Test("keeps law offices", arguments: [
        "The Portela Law Firm, P.C.", "Law Office of Patricia M Machado", "The Legal Aid Society",
        "Hecht & Hecht Attorneys", "Robert Gardner, Esq.",
    ])
    func keeps(_ name: String) { #expect(NearbyPlaces.isLegal(name)) }

    @Test("drops what a legal search drags in", arguments: [
        "Notary Public", "William Tax Solutions", "PLS Check Cashers", "Bronx Housing Court Office",
        "Criminal Justice Agency", "Nextage C E Realty Corporation", "Starbucks Coffee Company",
    ])
    func drops(_ name: String) { #expect(!NearbyPlaces.isLegal(name)) }

    @Test func distanceReadsInMiles() {
        #expect(NearbyPlaces.distance(50) == "Under 0.1 mi")
        #expect(NearbyPlaces.distance(1609.34) == "1.0 mi")
    }
}
