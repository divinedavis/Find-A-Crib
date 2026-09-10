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
        XCTAssertEqual(b.webURL(in: .nyc).absoluteString, "https://findacrib.com/building/manhattan/204-e-76th-st-1014300144/")
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

    /// A bedroom count without Available now: every hit must carry that
    /// bedroom in its recent listings — the filter narrows to advertised
    /// buildings by itself.
    func testBedsFilterWithoutAvailableOnly() {
        var q = SearchQuery(); q.mode = .stabilized; q.beds = [2]
        let r = SearchEngine.run(q, store: Self.store)
        XCTAssertFalse(r.isEmpty)
        XCTAssertTrue(r.allSatisfy { Self.store.beds($0).contains(2) })
        var all = SearchQuery(); all.mode = .stabilized
        XCTAssertLessThan(r.count, SearchEngine.run(all, store: Self.store).count)
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

    /// The two inspection tiles: red when a filing this year reported
    /// bedbugs or an inspection this year failed, green when the year is
    /// clean — regardless of what happened in earlier years.
    func testInspectionSummariesFollowTheSiteRule() throws {
        let y = HPDRecords.currentYear
        let dec = JSONDecoder()
        let bb = try dec.decode([HPDRecords.BedbugFiling].self, from: Data("""
        [{"filing_date":"\(y)-08-13T00:00:00.000","of_dwelling_units":"210","infested_dwelling_unit_count":"1","eradicated_unit_count":"1","re_infested_dwelling_unit":"0"},
         {"filing_date":"\(y - 1)-08-01T00:00:00.000","of_dwelling_units":"210","infested_dwelling_unit_count":"4"},
         {"filing_date":"\(y)-01-02T00:00:00.000","of_dwelling_units":"210","infested_dwelling_unit_count":"0"}]
        """.utf8))
        let bs = HPDRecords.summary(bedbugs: bb)
        XCTAssertEqual(bs.total, 3)
        XCTAssertEqual(bs.problemsThisYear, 1)
        XCTAssertFalse(bs.clean)
        XCTAssertEqual(bb[0].units, 210); XCTAssertEqual(bb[0].infested, 1); XCTAssertEqual(bb[0].treated, 1)
        XCTAssertTrue(HPDRecords.summary(bedbugs: [bb[1], bb[2]]).clean, "last year's bedbugs do not make this year red")

        let ro = try dec.decode([HPDRecords.RodentInspection].self, from: Data("""
        [{"job_id":"a","inspection_date":"\(y)-03-01T10:00:00.000","inspection_type":"Initial","result":"Passed"},
         {"job_id":"b","inspection_date":"\(y)-04-01T10:00:00.000","inspection_type":"Compliance","result":"Rat Activity"},
         {"job_id":"c","inspection_date":"\(y - 2)-04-01T10:00:00.000","inspection_type":"Initial","result":"Failed for Other R"}]
        """.utf8))
        let rs = HPDRecords.summary(rodents: ro)
        XCTAssertEqual(rs.total, 3)
        XCTAssertEqual(rs.problemsThisYear, 1)
        XCTAssertTrue(ro[2].failed); XCTAssertFalse(ro[0].failed)
        XCTAssertTrue(HPDRecords.summary(rodents: [ro[0], ro[2]]).clean)
    }

    /// The alert sheet's rent/income boxes accept what people type ("$2,000")
    /// and reject nonsense before it reaches the API.
    func testAlertDollarParsing() {
        XCTAssertNil(AlertsSheet.dollars(""))
        XCTAssertNil(AlertsSheet.dollars("  "))
        XCTAssertEqual(AlertsSheet.dollars("$2,000"), 2000)
        XCTAssertEqual(AlertsSheet.dollars("65000"), 65000)
        XCTAssertEqual(AlertsSheet.dollars("abc"), -1)
    }
}

// MARK: - Cities (LA, SF, DC alongside NYC)

final class CityTests: XCTestCase {
    /// The three non-NYC cities publish a slimmer record: no HPD block, and
    /// LA carries no neighborhood at all while SF and DC do. One odd field
    /// must not sink the decode of a 67k-row file.
    func testOtherCityRecordsDecode() throws {
        let json = """
        [{"bbl":"LA-2010004040","b":"LA","a":"9035 TOPANGA CANYON BLVD","z":"91304","lat":34.23,"lng":-118.60,
          "s":["LIKELY RSO (PRE-1979, 2+ UNITS)"],"yr":1978,"u":59,"nb":null},
         {"bbl":"SF--1000BLOCKOFREVER","b":"SF","a":"1000 Block of REVERE AVE","z":"","lat":37.72,"lng":-122.37,
          "s":["SF RENT BOARD INVENTORY"],"yr":null,"u":1,"nb":"Bayview Hunters Point","mr":2450},
         {"bbl":"DC-185084_1","b":"DC","a":"1314 HOLBROOK ST NE","z":"20002","lat":38.90,"lng":-76.98,
          "s":["DC RENT CONTROL (REGISTERED)"],"yr":null,"u":4,"nb":"Carver","mr":2800}]
        """
        let rows = try JSONDecoder().decode([Building].self, from: Data(json.utf8))
        XCTAssertEqual(rows.count, 3)
        XCTAssertNil(rows[0].nb)                 // LA: no neighborhood in the source
        XCTAssertNil(rows[0].mr)
        XCTAssertEqual(rows[1].mr, 2450)         // SF: block median
        XCTAssertEqual(rows[2].nb, "Carver")     // DC: real neighborhood
        XCTAssertEqual(rows[2].mr, 2800)
        XCTAssertEqual(rows[0].openViolations, 0, "no HPD block must read as zero, not crash")
    }

    /// Each city divides differently, and the picker offers whatever it has.
    func testRegionsFollowTheCity() {
        let la = [Building(bbl: "LA-1", b: "LA", a: "A", z: "90001", lat: 34, lng: -118),
                  Building(bbl: "LA-2", b: "LA", a: "B", z: "90001", lat: 34, lng: -118),
                  Building(bbl: "LA-3", b: "LA", a: "C", z: "90210", lat: 34, lng: -118)]
        let laR = DataStore.regions(for: .la, buildings: la, neighborhoods: [])
        XCTAssertEqual(laR.map(\.name), ["90001", "90210"])
        XCTAssertEqual(laR.first?.count, 2)

        let nb = [(name: "Carver", borough: "DC", count: 213), (name: "Dupont Circle", borough: "DC", count: 206)]
        let dcR = DataStore.regions(for: .dc, buildings: [], neighborhoods: nb)
        XCTAssertEqual(dcR.map(\.name), ["Carver", "Dupont Circle"])

        let nyc = [Building(bbl: "1", b: "M", a: "A", z: "10001", lat: 40, lng: -73),
                   Building(bbl: "2", b: "Bk", a: "B", z: "11201", lat: 40, lng: -73)]
        let nycR = DataStore.regions(for: .nyc, buildings: nyc, neighborhoods: [])
        XCTAssertEqual(nycR.map(\.name), ["Manhattan", "Brooklyn"], "boroughs, in the app's own order, empty ones dropped")
    }

    /// Only New York has a page per building; the rest deep-link into the city map.
    func testWebURLPerCity() {
        let nyc = Building(bbl: "1007220003", b: "M", a: "246 10TH AVE", z: "10001", lat: 40.7, lng: -74.0)
        XCTAssertEqual(nyc.webURL(in: .nyc).absoluteString,
                       "https://findacrib.com/building/manhattan/246-10th-ave-1007220003/")
        let dc = Building(bbl: "DC-185084_1", b: "DC", a: "1314 HOLBROOK ST NE", z: "20002", lat: 38.9, lng: -77.0)
        XCTAssertTrue(dc.webURL(in: .dc).absoluteString.hasPrefix("https://findacrib.com/dc/#d="))
    }

    /// The New York feeds are New York's; nothing else should ask for them.
    func testOnlyNYCFetchesTheExtraFeeds() {
        XCTAssertEqual(DataStore.files(for: .nyc).count, 5)
        XCTAssertEqual(DataStore.files(for: .la), ["la/buildings.min.json.gz"])
        XCTAssertEqual(DataStore.files(for: .sf), ["sf/buildings.min.json.gz"])
        XCTAssertFalse(City.la.hasNYCExtras)
        XCTAssertTrue(City.nyc.hasNYCExtras)
    }

    /// Cities cache to distinct filenames, or one would overwrite another.
    func testCacheNamesAreDistinct() {
        let names = City.all.map(\.cacheName)
        XCTAssertEqual(Set(names).count, names.count, "each city needs its own cache file")
        XCTAssertEqual(City.nyc.cacheName, "buildings.slim.json.gz", "NYC keeps its name so the shipped seed still loads")
        XCTAssertFalse(City.la.cacheName.contains("/"), "a cache filename cannot be a path")
    }

    func testFindFallsBackToNYC() {
        XCTAssertEqual(City.find("dc"), .dc)
        XCTAssertEqual(City.find(nil), .nyc)
        XCTAssertEqual(City.find("atlantis"), .nyc)
    }

    func testPlaceReadsInTheCitysOwnTerms() {
        let la = Building(bbl: "LA-1", b: "LA", a: "A", z: "90210", lat: 34, lng: -118)
        XCTAssertEqual(la.place(in: .la), "ZIP 90210")
        let sf = Building(bbl: "SF-1", b: "SF", a: "A", z: "", lat: 37, lng: -122, nb: "Mission")
        XCTAssertEqual(sf.place(in: .sf), "Mission")
        let nyc = Building(bbl: "1", b: "M", a: "A", z: "10001", lat: 40, lng: -73, nb: "Chelsea")
        XCTAssertEqual(nyc.place(in: .nyc), "Chelsea")
    }
}

// MARK: - A search carried from one city to another

@MainActor
final class CitySearchTests: XCTestCase {
    /// The bug this pins (2026-09-09): the app opened Los Angeles with the
    /// $3,500 maximum still set from a New York search. Price comes from
    /// listings and the HUD table, both New York feeds, so every LA building
    /// had no price, the filter rejected all 67,511 of them and the button
    /// read "Search 0 buildings".
    func testPriceFilterDoesNotEmptyACityWithNoRents() {
        let store = DataStore()
        let la = [Building(bbl: "LA-1", b: "LA", a: "A", z: "90001", lat: 34, lng: -118, u: 4),
                  Building(bbl: "LA-2", b: "LA", a: "B", z: "90002", lat: 34, lng: -118, u: 9)]
        store.applyForTesting(.init(buildings: la, listings: ListingsBlob(), s8: S8Blob(), fmr: [:], hcr: HCRBlob()))
        var q = SearchQuery()
        XCTAssertEqual(SearchEngine.count(q, store: store), 2, "no filter: every building")
        q.maxPrice = 3500
        XCTAssertEqual(SearchEngine.count(q, store: store), 0,
                       "a price filter still excludes buildings with no rent on file — which is exactly why LA must not offer one")
        XCTAssertFalse(City.la.hasPrices, "so LA hides the price fields")
        XCTAssertTrue(City.nyc.hasPrices)
        XCTAssertTrue(City.sf.hasPrices)
        XCTAssertTrue(City.dc.hasPrices)
    }

    /// SF and DC do publish a rent — the block median and the registered legal
    /// rent — so a price filter there has to use it.
    func testRegisteredRentFeedsThePriceFilter() {
        let store = DataStore()
        let dc = [Building(bbl: "DC-1", b: "DC", a: "A", z: "20002", lat: 38.9, lng: -77, u: 4, mr: 2800),
                  Building(bbl: "DC-2", b: "DC", a: "B", z: "20011", lat: 38.9, lng: -77, u: 6, mr: 4200),
                  Building(bbl: "DC-3", b: "DC", a: "C", z: "20009", lat: 38.9, lng: -77, u: 2)]
        store.applyForTesting(.init(buildings: dc, listings: ListingsBlob(), s8: S8Blob(), fmr: [:], hcr: HCRBlob()))
        XCTAssertEqual(store.priceOf(dc[0]), 2800, "the registered rent is the price DC has")
        XCTAssertNil(store.priceOf(dc[2]), "no rent on file stays unknown")
        var q = SearchQuery()
        q.maxPrice = 3500
        XCTAssertEqual(SearchEngine.count(q, store: store), 1, "only the $2,800 building is under the cap")
    }

    /// A query restored from disk in a different city must not filter it empty.
    func testSanitizeDropsWhatACityCannotAnswer() {
        var q = SearchQuery()
        q.maxPrice = 3500; q.minPrice = 1000; q.availableOnly = true; q.beds = [1, 2]; q.hcrOnly = true
        let inLA = q.sanitized(for: .la)
        XCTAssertNil(inLA.maxPrice); XCTAssertNil(inLA.minPrice)
        XCTAssertFalse(inLA.availableOnly); XCTAssertFalse(inLA.hcrOnly); XCTAssertTrue(inLA.beds.isEmpty)
        let inDC = q.sanitized(for: .dc)
        XCTAssertEqual(inDC.maxPrice, 3500, "DC has registered rents, so a price still means something")
        XCTAssertFalse(inDC.availableOnly, "but advertised-now is a New York feed")
        let inNYC = q.sanitized(for: .nyc)
        XCTAssertEqual(inNYC.maxPrice, 3500); XCTAssertTrue(inNYC.availableOnly)
    }
}

// MARK: - Analytics

@MainActor
final class AnalyticsTests: XCTestCase {
    /// The app must not send usage data while App Store Connect's App Privacy
    /// answers still say it collects only name and email. Flipping this on is
    /// a deliberate act that belongs in the same commit as the label change —
    /// this test is here so it cannot happen by accident.
    func testAnalyticsIsDarkUntilThePrivacyLabelIsDeclared() {
        XCTAssertFalse(Analytics.privacyLabelDeclared,
                       "declare Product Interaction / Usage Data in App Store Connect, then flip this and update this test in the same commit")
    }

    /// Whatever the gate says, the setting is real and defaults to on.
    func testShareUsageDefaultsOnAndPersists() {
        let a = Analytics.shared
        let original = a.enabled
        a.enabled = false
        XCTAssertFalse(a.enabled)
        XCTAssertEqual(UserDefaults.standard.bool(forKey: "analytics.enabled"), false)
        a.enabled = true
        XCTAssertTrue(a.enabled)
        a.enabled = original
    }
}
