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
        q.maxPrice = 3500; q.minPrice = 1000; q.vouchersOnly = true; q.beds = [0, 2]; q.hcrOnly = true
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

/// The one outbound button on every building (2026-10-06): StreetEasy's
/// address search in New York, Zillow's everywhere else. No listing data
/// feeds it, so the URL is a pure function of the address and the city.
@Suite("Outbound button")
struct OutboundLinkTests {
    private func building(_ a: String, boro: String, zip: String?) -> Building {
        Building(bbl: "X", b: boro, a: a, z: zip, lat: 0, lng: 0, s: nil, yr: nil, u: nil, nb: nil, h: nil)
    }

    @Test("NYC buildings open a StreetEasy address search", arguments: [
        ("246 10TH AVE", "M", "10001", "246%2010th%20Ave%2C%20Manhattan%2C%20NY%2010001"),
        ("75 DUPONT ST", "Bk", "11222", "75%20Dupont%20St%2C%20Brooklyn%2C%20NY%2011222"),
        ("1 MAIN ST", "SI", nil, "1%20Main%20St%2C%20Staten%20Island%2C%20NY"),
    ] as [(String, String, String?, String)])
    func nyc(_ c: (String, String, String?, String)) {
        let o = OutboundLink.make(building(c.0, boro: c.1, zip: c.2), in: .nyc)
        #expect(o.kind == "streeteasy")
        #expect(o.label == "View on StreetEasy ↗")
        #expect(o.url.absoluteString == "https://streeteasy.com/search?search=\(c.3)")
    }

    @Test("every other city opens a Zillow address search",
          arguments: City.all.filter { !$0.isNYC })
    func zillow(_ city: City) {
        let o = OutboundLink.make(building("100 MAIN ST", boro: city.short, zip: "00000"), in: city)
        #expect(o.kind == "zillow")
        #expect(o.label == "View on Zillow ↗")
        #expect(o.url.scheme == "https")
        #expect(o.url.host == "www.zillow.com")
        let place = city.id == "dc" ? "Washington" : city.name
        #expect(o.url.absoluteString == "https://www.zillow.com/homes/\(OutboundLink.encode("100 Main St, \(place), \(city.state)"))_rb/")
    }

    @Test("Los Angeles goes to Zillow with the city and state")
    func la() {
        let o = OutboundLink.make(building("1200 W 7TH ST", boro: "LA", zip: "90017"), in: .la)
        #expect(o.url.absoluteString == "https://www.zillow.com/homes/1200%20W%207th%20St%2C%20Los%20Angeles%2C%20CA_rb/")
    }
}
