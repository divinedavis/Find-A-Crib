import XCTest
@testable import FindACrib

final class DataTests: XCTestCase {
    func testBundledDataDecodes() throws {
        let p = try DataStore.decodeLocal()
        XCTAssertGreaterThan(p.buildings.count, 40_000, "bundled buildings.slim.json.gz should hold the full NYC file")
        XCTAssertGreaterThan(p.listings.prices.count, 500)
        XCTAssertFalse(p.fmr.isEmpty)
        XCTAssertFalse(p.s8.bldg.isEmpty)
        // every priced BBL should exist in the building file
        let bbls = Set(p.buildings.map(\.bbl))
        let orphan = p.listings.prices.keys.filter { !bbls.contains($0) }.count
        XCTAssertLessThan(Double(orphan) / Double(p.listings.prices.count), 0.05)
    }

    func testGunzipRejectsGarbage() {
        XCTAssertThrowsError(try Gunzip.inflate(Data([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])))
    }

    func testAddressCaseAndSlug() {
        XCTAssertEqual(AddressCase.pretty("246 10TH AVE"), "246 10th Ave")
        XCTAssertEqual(AddressCase.pretty("204 E 76TH ST"), "204 E 76th St")
        XCTAssertEqual(Slug.make("204 E 76TH ST"), "204-e-76th-st")
        let b = Building(bbl: "1014300144", b: "M", a: "204 E 76TH ST", z: "10021", lat: 40.77, lng: -73.95)
        XCTAssertEqual(b.webURL.absoluteString, "https://findacrib.com/building/manhattan/204-e-76th-st-1014300144/")
    }

    func testShortMoney() {
        XCTAssertEqual(Formatters.short(1000), "$1k")
        XCTAssertEqual(Formatters.short(3500), "$3.5k")
        XCTAssertEqual(Formatters.short(850), "$850")
    }

    func testQuerySummary() {
        var q = SearchQuery(); q.minPrice = 1000; q.maxPrice = 3000; q.beds = [1]
        XCTAssertEqual(q.summary, "$1k - $3k, 1 bd")
        XCTAssertEqual(q.activeFilterCount, 3)
        q.availableOnly = true
        XCTAssertEqual(q.summary, "Available, $1k - $3k, 1 bd")
        XCTAssertEqual(SearchQuery().summary, "Any price")
    }
}

@MainActor
final class SearchEngineTests: XCTestCase {
    static var store: DataStore!

    override func setUp() async throws {
        if Self.store == nil {
            let s = DataStore()
            // Decode the bundle only; no network in tests.
            let p = try DataStore.decodeLocal()
            s.applyForTesting(p)
            Self.store = s
        }
    }

    func testLegacyRentDecodesToAvailableOnly() {
        var q = SearchQuery(); q.mode = .rent
        let n = q.normalized
        XCTAssertEqual(n.mode, .stabilized); XCTAssertTrue(n.availableOnly)
        XCTAssertEqual(SearchEngine.count(q, store: Self.store), SearchEngine.count(n, store: Self.store))
    }

    func testAvailableOnlyIsPriced() {
        var q = SearchQuery(); q.mode = .stabilized; q.availableOnly = true
        let r = SearchEngine.run(q, store: Self.store)
        XCTAssertEqual(r.count, Self.store.listings.prices.count)
        XCTAssertTrue(r.allSatisfy { Self.store.price($0) != nil })
        // cheapest-first
        let prices = r.compactMap { Self.store.price($0) }
        XCTAssertEqual(prices, prices.sorted())
    }

    func testPriceAndBedsFilter() {
        var q = SearchQuery(); q.mode = .stabilized; q.availableOnly = true; q.minPrice = 1000; q.maxPrice = 3000; q.beds = [1]
        let r = SearchEngine.run(q, store: Self.store)
        XCTAssertFalse(r.isEmpty)
        for b in r {
            let p = Self.store.price(b)!
            XCTAssert(p >= 1000 && p <= 3000)
            XCTAssert(Self.store.beds(b).contains(1))
        }
    }

    func testBoroughScope() {
        var q = SearchQuery(); q.mode = .stabilized; q.locations = [.borough("Bk")]
        let r = SearchEngine.run(q, store: Self.store)
        XCTAssertGreaterThan(r.count, 5_000)
        XCTAssertTrue(r.allSatisfy { $0.b == "Bk" })
    }

    func testNoViolationsFilter() {
        var q = SearchQuery(); q.mode = .stabilized; q.noOpenViolations = true
        let r = SearchEngine.run(q, store: Self.store)
        XCTAssertTrue(r.allSatisfy { $0.openViolations == 0 })
        XCTAssertLessThan(r.count, Self.store.buildings.count)
    }

    func testVoucherMode() {
        var q = SearchQuery(); q.mode = .vouchers
        let all = SearchEngine.run(q, store: Self.store)
        q.voucherLiveOnly = true
        let live = SearchEngine.run(q, store: Self.store)
        XCTAssertGreaterThan(all.count, live.count)
        XCTAssertTrue(live.allSatisfy { Self.store.voucherAvail($0) != nil })
    }

    func testMapArea() {
        var q = SearchQuery(); q.mode = .stabilized
        q.locations = [.mapArea(MapBox(region: .init(center: .init(latitude: 40.68, longitude: -73.975), latitudinalMeters: 800, longitudinalMeters: 800)))]
        let r = SearchEngine.run(q, store: Self.store)
        XCTAssertFalse(r.isEmpty)
        XCTAssertTrue(r.allSatisfy { abs($0.lat - 40.68) < 0.01 })
    }

    func testSimilarStaysInNeighborhood() {
        let b = Self.store.buildings.first { $0.nb != nil }!
        let sim = SearchEngine.similar(to: b, store: Self.store)
        XCTAssertTrue(sim.allSatisfy { $0.nb == b.nb && $0.bbl != b.bbl })
    }
}

@MainActor
final class ActivityTests: XCTestCase {
    func testSaveToggleAndSearchRoundTrip() {
        let a = Activity()
        let before = a.saved
        a.toggleSaved("test-bbl")
        XCTAssertTrue(a.isSaved("test-bbl"))
        a.toggleSaved("test-bbl")
        XCTAssertFalse(a.isSaved("test-bbl"))
        XCTAssertEqual(a.saved, before)
        var q = SearchQuery(); q.minPrice = 1200
        a.saveSearch(q, name: "t", count: 3)
        XCTAssertTrue(a.isSearchSaved(q))
        a.deleteSearch(a.savedSearches.first { $0.name == "t" }!.id)
        XCTAssertFalse(a.isSearchSaved(q))
    }
}
