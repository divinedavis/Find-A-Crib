import Foundation
import Testing
@testable import FindACrib

/// Swift Testing (Apple's framework for new unit tests since Xcode 16), added
/// 2026-10-02 next to the XCTest suite rather than replacing it. Parameterized
/// tests run each case on its own, so a failure names the city or the input
/// that broke instead of stopping a loop at the first one.
///
/// Every city must answer the same questions safely: these are the invariants a
/// new city (eight since 9/24) has to keep without anyone writing a test for it.
@Suite("Every city")
struct CityInvariantTests {
    @Test("find(id) round-trips", arguments: City.all)
    func findRoundTrips(_ city: City) {
        #expect(City.find(city.id) == city)
    }

    @Test("cache file is a plain, unique filename", arguments: City.all)
    func cacheNameIsAFilename(_ city: City) {
        #expect(!city.cacheName.contains("/"))
        #expect(City.all.filter { $0.cacheName == city.cacheName }.count == 1)
    }

    /// A query restored in another city is sanitized on the way in; doing it
    /// twice must change nothing, or the saved search would drift on every open.
    @Test("sanitizing a query is idempotent", arguments: City.all)
    func sanitizeIsIdempotent(_ city: City) {
        var q = SearchQuery()
        q.maxPrice = 3500; q.minPrice = 1000; q.availableOnly = true; q.beds = [0, 2]; q.hcrOnly = true
        let once = q.sanitized(for: city)
        #expect(once.sanitized(for: city) == once)
        if !city.hasPrices { #expect(once.maxPrice == nil && once.minPrice == nil) }
    }

    /// Saved searches live on disk as JSON; one sanitized for any city must
    /// come back exactly as it went in.
    @Test("a sanitized query survives a save and load", arguments: City.all)
    func queryCodableRoundTrip(_ city: City) throws {
        var q = SearchQuery()
        q.maxPrice = 2800; q.beds = [1]
        let saved = q.sanitized(for: city)
        let back = try JSONDecoder().decode(SearchQuery.self, from: JSONEncoder().encode(saved))
        #expect(back == saved)
    }
}

@Suite("Formatting")
struct FormattingTests {
    @Test(arguments: [(850, "$850"), (1000, "$1k"), (3500, "$3.5k"), (12000, "$12k")])
    func shortMoney(_ value: Int, _ expected: String) {
        #expect(Formatters.short(value) == expected)
    }

    @Test(arguments: [("246 10TH AVE", "246 10th Ave"),
                      ("204 E 76TH ST", "204 E 76th St"),
                      ("1 W 1ST ST", "1 W 1st St")])
    func addressReadsInTitleCase(_ raw: String, _ expected: String) {
        #expect(AddressCase.pretty(raw) == expected)
    }

    @Test(arguments: [("204 E 76TH ST", "204-e-76th-st"), ("246 10TH AVE", "246-10th-ave")])
    func slugIsURLSafe(_ raw: String, _ expected: String) {
        let slug = Slug.make(raw)
        #expect(slug == expected)
        #expect(slug.allSatisfy { $0.isLowercase || $0.isNumber || $0 == "-" })
    }
}
