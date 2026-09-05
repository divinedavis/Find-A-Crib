import XCTest
import MapKit
@testable import FindACrib

final class DataTests: XCTestCase {
    func testBundledDataDecodes() throws {
        let p = try DataStore.decodeLocal(bundleOnly: true)
        XCTAssertGreaterThan(p.buildings.count, 40_000, "bundled buildings.slim.json.gz should hold the full NYC file")
        XCTAssertGreaterThan(p.listings.prices.count, 500)
        XCTAssertFalse(p.fmr.isEmpty)
        XCTAssertFalse(p.s8.bldg.isEmpty)
        // every priced BBL should exist in the building file
        let bbls = Set(p.buildings.map(\.bbl))
        let orphan = p.listings.prices.keys.filter { !bbls.contains($0) }.count
        XCTAssertLessThan(Double(orphan) / Double(p.listings.prices.count), 0.05)
    }

    func testHCRDecodesFloatIncomesAndNulls() throws {
        let json = """
        {"updated": 1788313508.0, "count": 2, "listings": [
          {"id": "a", "name": "X", "kind": "Lottery", "status": "Open", "ptype": "Rental", "boro": "M",
           "min_income": 19989.0, "max_income": 109920, "due": "9/7/2026", "fee": null, "phone": null, "url": "https://x",
           "info": null, "desc": null, "image": null, "senior": false, "accessible": false, "approx": false,
           "buildings": [{"street": "111 East 123rd Street", "zip": "10035", "lat": 40.8, "lng": -73.9, "bbl": null}]},
          {"id": "b", "name": "Y", "kind": "Waitlist", "status": "Closed", "ptype": "Co-op", "boro": "Bx",
           "min_income": null, "max_income": 255840.5, "due": "1/1/2027", "fee": 75, "buildings": []}
        ]}
        """
        let blob = try JSONDecoder().decode(HCRBlob.self, from: Data(json.utf8))
        XCTAssertEqual(blob.listings.count, 2)
        XCTAssertEqual(blob.listings[0].min_income, 19989)
        XCTAssertEqual(blob.listings[1].max_income, 255841)
        XCTAssertEqual(blob.listings[0].incomeRange, "$19,989–$109,920")
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
            let p = try DataStore.decodeLocal(bundleOnly: true)
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

    func testRecencyRule() {
        var blob = ListingsBlob()
        blob.prices = ["a": 1000, "b": 2000]
        blob.posted = ["a": Date().timeIntervalSince1970 - 2 * 86400, "b": Date().timeIntervalSince1970 - 9 * 86400]
        XCTAssertTrue(blob.isRecent("a")); XCTAssertFalse(blob.isRecent("b")); XCTAssertFalse(blob.isRecent("zzz"))
    }

    /// The listing button names the site it opens. Every banked URL is
    /// StreetEasy's or Zumper's; a building with no URL gets the generic label.
    func testListingButtonNamesTheSite() {
        let urls = Self.store.listings.urls
        XCTAssertFalse(urls.isEmpty, "bundled listings.json has no URLs")
        for b in Self.store.buildings where urls[b.bbl] != nil {
            let site = Self.store.listingSite(b)
            let host = (Self.store.listingURL(b)?.host ?? "").lowercased()
            if host.hasSuffix("streeteasy.com") { XCTAssertEqual(site, "StreetEasy") }
            else if host.hasSuffix("zumper.com") { XCTAssertEqual(site, "Zumper") }
            else { XCTAssertEqual(site, "View listing") }
        }
        if let plain = Self.store.buildings.first(where: { urls[$0.bbl] == nil }) {
            XCTAssertEqual(Self.store.listingSite(plain), "View listing")
        }
    }

    /// The results header shows borough abbreviations only — a neighborhood
    /// pick collapses into its borough, boroughs come out in register order,
    /// nothing repeats.
    func testShortLocationLabel() {
        let nbOf = Self.store.boroughOfNeighborhood
        XCTAssertFalse(nbOf.isEmpty)
        let bk = nbOf.first { $0.value == "Bk" }!.key
        let mn = nbOf.first { $0.value == "M" }!.key
        var q = SearchQuery()
        XCTAssertEqual(q.shortLocationLabel(boroughOf: nbOf), "NYC")
        q.locations = [.neighborhood(bk), .borough("M"), .neighborhood(mn), .neighborhood(bk)]
        XCTAssertEqual(q.shortLocationLabel(boroughOf: nbOf), "MN, BK")
        q.locations = [.borough("SI"), .borough("Q"), .zip("10012")]
        XCTAssertEqual(q.shortLocationLabel(boroughOf: nbOf), "QN, SI, 10012")
        q.locations = [.mapArea(MapBox(region: .init(center: .init(latitude: 40.75, longitude: -73.95), span: .init(latitudeDelta: 0.1, longitudeDelta: 0.1))))]
        XCTAssertEqual(q.shortLocationLabel(boroughOf: nbOf), "Map area")
    }

    func testAvailableOnlyIsPriced() {
        var q = SearchQuery(); q.mode = .stabilized; q.availableOnly = true
        let r = SearchEngine.run(q, store: Self.store)
        // only buildings posted on Zumper in the last 5 days count as available
        XCTAssertEqual(r.count, Self.store.listings.prices.keys.filter { Self.store.listings.isRecent($0) }.count)
        XCTAssertTrue(r.allSatisfy { Self.store.price($0) != nil })
        // cheapest-first
        let prices = r.compactMap { Self.store.price($0) }
        XCTAssertEqual(prices, prices.sorted())
    }

    func testPriceAndBedsFilter() throws {
        try XCTSkipIf(Self.store.listings.posted.isEmpty, "seed predates posting dates; nothing is 'recent'")
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
        var q = SearchQuery(); q.vouchersOnly = true
        let all = SearchEngine.run(q, store: Self.store)
        // legacy Vouchers tab decodes to the same flag
        var legacy = SearchQuery(); legacy.mode = .vouchers
        XCTAssertEqual(SearchEngine.count(legacy, store: Self.store), all.count)
        // Show flags combine (AND): available + vouchers ⊆ each alone
        var both = q; both.availableOnly = true
        let b = SearchEngine.run(both, store: Self.store)
        XCTAssertLessThanOrEqual(b.count, all.count)
        XCTAssertTrue(b.allSatisfy { Self.store.price($0) != nil && Self.store.isVoucherFriendly($0) })
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

    func testHCRPoolAndFlag() {
        XCTAssertFalse(Self.store.hcr.listings.isEmpty, "bundled hcr.json should hold listings")
        XCTAssertFalse(Self.store.hcrBuildings.isEmpty)
        var q = SearchQuery(); q.hcrOnly = true
        let r = SearchEngine.run(q, store: Self.store)
        XCTAssertEqual(r.count, Self.store.hcrBuildings.count)
        XCTAssertTrue(r.allSatisfy { Self.store.isHCR($0) })
        // stand-alone sites resolve through byBBL so a route can open them
        if let syn = r.first(where: { Self.store.isSyntheticHCR($0) }) { XCTAssertNotNil(Self.store.byBBL[syn.bbl]) }
        // and they never leak into a plain register search
        XCTAssertFalse(SearchEngine.run(SearchQuery(), store: Self.store).contains { Self.store.isSyntheticHCR($0) })
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
