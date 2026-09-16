import XCTest
import MapKit
@testable import FindACrib

final class LaunchSequenceTests: XCTestCase {
    func testSequenceFinishesOnce() {
        var sequence = LaunchSequence()
        XCTAssertEqual(sequence.phase, .ready)
        sequence.advance(from: .ready)
        XCTAssertEqual(sequence.phase, .expanding)
        sequence.advance(from: .ready)
        XCTAssertEqual(sequence.phase, .expanding)
        sequence.advance(from: .expanding)
        XCTAssertEqual(sequence.phase, .revealing)
        sequence.advance(from: .revealing)
        XCTAssertEqual(sequence.phase, .finished)
        sequence.advance(from: .ready)
        XCTAssertEqual(sequence.phase, .finished)
    }

    func testInterruptedAnimationCannotRestartFromStaleCompletion() {
        for phase in [LaunchSequence.Phase.ready, .expanding, .revealing] {
            var sequence = LaunchSequence()
            if phase != .ready { sequence.advance(from: .ready) }
            if phase == .revealing { sequence.advance(from: .expanding) }
            sequence.finish()
            sequence.advance(from: phase)
            XCTAssertEqual(sequence.phase, .finished)
        }
    }

    func testCircleCoversEveryCornerWithoutChangingLayout() {
        for size in [CGSize(width: 320, height: 568), CGSize(width: 402, height: 874),
                     CGSize(width: 440, height: 956), CGSize(width: 956, height: 440)] {
            let diameter = LaunchSequence.coverScale(for: size) * 180
            XCTAssertGreaterThan(diameter, hypot(size.width, size.height))
        }
        XCTAssertEqual(LaunchSequence.coverScale(for: .zero), 1)
    }
}

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

    /// The picker's borough counts come from the index built at decode time,
    /// not from a scan in `body`; they must still agree with the rows.
    func testBoroughCountsMatchTheRows() {
        let s = Self.store!
        XCTAssertFalse(s.boroughCounts.isEmpty)
        for (code, n) in s.boroughCounts {
            XCTAssertEqual(n, s.buildings.lazy.filter { $0.b == code }.count, code)
        }
        for r in s.regions {
            let code = Borough.all.first { $0.name == r.name }?.code ?? ""
            XCTAssertEqual(r.count, s.boroughCounts[code], r.name)
        }
    }

    /// The price sort looks each price up once, then sorts; same order as
    /// comparing priceOf inside the comparator.
    func testPriceSortMatchesTheComparatorSort() {
        let s = Self.store!
        let xs = Array(s.buildings.prefix(3000))
        let naive = xs.sorted { (s.priceOf($0) ?? .max, $0.a) < (s.priceOf($1) ?? .max, $1.a) }
        XCTAssertEqual(SearchEngine.sort(xs, .cheapest, s).map(\.bbl), naive.map(\.bbl))
        let naiveHi = xs.sorted { (s.priceOf($0) ?? -1, $0.a) > (s.priceOf($1) ?? -1, $1.a) }
        XCTAssertEqual(SearchEngine.sort(xs, .priciest, s).map(\.bbl), naiveHi.map(\.bbl))
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
        XCTAssertEqual(q.shortLocationLabel(boroughOf: nbOf, city: "LA"), "LA", "the header names the city the search is in")
        XCTAssertEqual(q.locationLabel(city: "SF"), "All of SF")
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

final class MapClusterTests: XCTestCase {
    /// Cluster bubbles are spaced in SCREEN POINTS, not in degrees.
    ///
    /// The grid used to be "9 columns across the viewport" with cells 1.2x as
    /// tall as wide. A phone's map is about twice as tall as it is wide, so
    /// that came out at 9 by ~16 — up to 145 cells on screen, and a 44pt bubble
    /// in each of them, which is what "too many bubbles" looked like.
    func testGridCellsAreSquareOnScreenAtEveryZoom() {
        let phone = CGSize(width: 393, height: 700)
        for lngSpan in [0.6, 0.2, 0.05, 0.01] {          // city down to a few blocks
            let region = MKCoordinateRegion(center: .init(latitude: 40.72, longitude: -73.97),
                                            span: .init(latitudeDelta: lngSpan * 1.8, longitudeDelta: lngSpan))
            let (cw, ch) = BuildingMap.cellSize(region: region, viewSize: phone)
            // a cell is cellPoints across and cellPoints down, in points
            let wPts = cw / region.span.longitudeDelta * Double(phone.width)
            let hPts = ch / region.span.latitudeDelta * Double(phone.height)
            XCTAssertEqual(wPts, Double(BuildingMap.cellPoints), accuracy: 0.5, "zoom \(lngSpan)")
            XCTAssertEqual(hPts, Double(BuildingMap.cellPoints), accuracy: 0.5, "zoom \(lngSpan)")
            // …and that is few enough cells to read
            let cols = Double(phone.width) / wPts, rows = Double(phone.height) / hPts
            XCTAssertLessThanOrEqual(cols * rows, 20, "zoom \(lngSpan): \(Int(cols))x\(Int(rows)) cells on screen is a mat of bubbles")
        }
    }

    /// Two bubbles in neighbouring cells cannot touch: each sits at its cell's
    /// average position, clamped into the middle of the cell, so the closest
    /// two can be is a cell minus the clamp — which has to beat a bubble's width.
    func testNeighbouringBubblesCannotOverlap() {
        let widestBubble: CGFloat = 44          // ClusterBubbleView at 3+ digits
        let minGap = BuildingMap.cellPoints * (1 - BuildingMap.centroidClamp)
        XCTAssertGreaterThan(minGap, widestBubble,
                             "cellPoints/centroidClamp let two bubbles overlap")
    }
}

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
    /// LA offered ZIP areas until 2026-09-12, when the LA Times boundaries were
    /// joined to every parcel and it could finally offer neighborhoods.
    func testRegionsFollowTheCity() {
        let laNb = [(name: "Boyle Heights", borough: "LA", count: 2021),
                    (name: "Koreatown", borough: "LA", count: 1827)]
        let laR = DataStore.regions(for: .la, buildings: [], neighborhoods: laNb)
        XCTAssertEqual(laR.map(\.name), ["Boyle Heights", "Koreatown"])
        XCTAssertEqual(laR.first?.count, 2021)

        let nb = [(name: "Carver", borough: "DC", count: 213), (name: "Dupont Circle", borough: "DC", count: 206)]
        let dcR = DataStore.regions(for: .dc, buildings: [], neighborhoods: nb)
        XCTAssertEqual(dcR.map(\.name), ["Carver", "Dupont Circle"])

        let nyc = [Building(bbl: "1", b: "M", a: "A", z: "10001", lat: 40, lng: -73),
                   Building(bbl: "2", b: "Bk", a: "B", z: "11201", lat: 40, lng: -73)]
        let nycR = DataStore.regions(for: .nyc, buildings: nyc, neighborhoods: [])
        XCTAssertEqual(nycR.map(\.name), ["Manhattan", "Brooklyn"], "boroughs, in the app's own order, empty ones dropped")
    }

    /// The boot payload and the record blob stay SEPARATE — that is the point.
    ///
    /// Folding the record into each Building took the row from 217 to 680
    /// bytes: 22 MB of array across New York's 47,165 rows, none of which New
    /// York reads, carried again by every filter and sort. The eager counts the
    /// list and filters rank on stay on Building; everything else is looked up
    /// by id on the one screen that shows it.
    func testRecordBlobIsHeldApartFromTheRow() throws {
        let slim = """
        [{"bbl":"LA-5511008010","b":"LA","a":"106 N SWEETZER AVE","z":"90048","lat":34.07,"lng":-118.36,
          "s":["LIKELY RSO"],"yr":1937,"u":6,"nb":"Beverly Grove",
          "h":{"violations":{"open":6},"complaints":{"open":0}}}]
        """
        let full = """
        {"LA-5511008010":{"violations":{"open":6,"total":6,"last_12mo":6,
           "types":[["Smoke detectors",2],["Damp rooms",1]]},
          "complaints":{"open":0,"total":11,"last_12mo":0},
          "ev":{"total":4,"nofault":1,"last_12mo":0},
          "by":{"n":2,"med":25000},"cases":{"open":0,"total":2},
          "window":["2025-11-04","2026-07-31"]}}
        """
        let dec = JSONDecoder()
        let row = try dec.decode([Building].self, from: Data(slim.utf8))[0]
        let recs = try dec.decode([String: BuildingRecord].self, from: Data(full.utf8))
        let rec = try XCTUnwrap(recs[row.bbl])

        // the row keeps only what ranks a list
        XCTAssertEqual(row.openViolations, 6)
        XCTAssertEqual(row.h?.complaints?.open, 0)
        // …and the record carries the rest
        XCTAssertEqual(rec.violations?.total, 6)
        XCTAssertEqual(rec.complaints?.total, 11)
        XCTAssertEqual(rec.ev?.nofault, 1)
        XCTAssertEqual(rec.by?.med, 25000)
        XCTAssertEqual(rec.window, ["2025-11-04", "2026-07-31"])
        XCTAssertEqual(rec.violations?.named.map(\.0), ["Smoke detectors", "Damp rooms"],
                       "a [String, Int] pair from the wire has to survive into a usable list")

        // The row is the thing stored 47k times and copied by every scan, so
        // its size is a budget, not an implementation detail. 217 bytes was the
        // shape before the records shipped; anything near 680 means the record
        // has been folded back in.
        XCTAssertLessThan(MemoryLayout<Building.HPD?>.size, 300,
                          "Building.HPD has grown — is a record field being stored on every row?")
    }

    /// The DC record is a different shape again: no violations at all, an owner
    /// and the assessor's read of the building instead.
    func testDCRecordCarriesOwnerAndAssessor() throws {
        let full = """
        {"DC-1":{"ssl":"5507 0021","renov":1965,"rooms":16,"beds":4,"baths":4,
          "cond":"Average","units_total":4,"owner":"Minnesota Avenue SE Trustee LLC",
          "op":1,"assessed":684490,"ptype":"Multi-family (3 to 4 units)"}}
        """
        let rec = try XCTUnwrap(try JSONDecoder()
            .decode([String: BuildingRecord].self, from: Data(full.utf8))["DC-1"])
        XCTAssertEqual(rec.owner, "Minnesota Avenue SE Trustee LLC")
        XCTAssertEqual(rec.assessed, 684490)
        XCTAssertEqual(rec.cond, "Average")
        XCTAssertNil(rec.violations, "DC publishes no code violations — this must stay nil, not zero")
    }

    /// SF's extra rent detail: the block median split by bedroom, the typical
    /// size, and what the base rent includes.
    func testSFRentDetailDecodes() throws {
        let json = """
        [{"bbl":"SF-1237-X","b":"SF","a":"200 Block of DIVISADERO ST","z":"94117","lat":37.77,"lng":-122.43,
          "s":["SF RENT BOARD INVENTORY"],"yr":1900,"u":9,"nb":"Haight Ashbury",
          "mr":4625,"br":{"0":2100,"1":3200,"4":5875},"sq":1125,"ui":["water","refuse"]}]
        """
        let r = try JSONDecoder().decode([Building].self, from: Data(json.utf8))[0]
        XCTAssertEqual(r.mr, 4625)
        XCTAssertEqual(r.br?["1"], 3200)
        XCTAssertEqual(r.sq, 1125)
        XCTAssertEqual(r.ui, ["water", "refuse"])
        XCTAssertEqual(Building.bedOrder.compactMap { r.br?[$0] != nil ? Building.bedLabel($0) : nil },
                       ["Studio", "1 bed", "4+ bed"])
    }

    /// Every city says what it publishes in its own words, and never names
    /// another city's agency. This is the check that catches New York wording
    /// leaking into an LA or DC screen, which is what shipped until 2026-09-12.
    func testEachCityNamesItsOwnSources() {
        for c in City.all where !c.isNYC {
            XCTAssertFalse(c.aboutNote.contains("HPD"), "\(c.id) about note names a New York agency")
            XCTAssertFalse(c.aboutNote.contains("Rent Guidelines Board"), "\(c.id) about note is New York's")
            XCTAssertFalse(c.sourcesNote.contains("NYS HCR"), "\(c.id) sources are New York's")
            XCTAssertNotNil(c.records, "\(c.id) has a record blob but no wording for it")
            XCTAssertNotNil(c.recordsPath, "\(c.id) must fetch its record blob")
            XCTAssertTrue(DataStore.files(for: c).contains(c.recordsPath!),
                          "\(c.id) record blob is configured but never fetched")
        }
        // …and the two that publish no code violations have to say so.
        for id in ["sf", "dc"] {
            XCTAssertNotNil(City.find(id).records?.noViolationsNote,
                            "\(id) publishes no violations and must say so, not show an empty panel")
        }
        XCTAssertNotNil(City.la.records?.violationsLabel, "LA does publish violations")
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
    /// Advertised rents, vouchers and lotteries stay New York feeds. What every
    /// city now fetches is two files, not one: the boot payload and the record
    /// blob behind it, the same split the website boots from.
    func testOnlyNYCFetchesTheExtraFeeds() {
        XCTAssertEqual(DataStore.files(for: .nyc).count, 5)
        XCTAssertEqual(DataStore.files(for: .la), ["la/buildings.slim.json.gz", "la/buildings.hpd.json.gz"])
        XCTAssertEqual(DataStore.files(for: .sf), ["sf/buildings.slim.json.gz", "sf/buildings.hpd.json.gz"])
        XCTAssertEqual(DataStore.files(for: .dc), ["dc/buildings.slim.json.gz", "dc/buildings.hpd.json.gz"])
        XCTAssertFalse(City.la.hasNYCExtras)
        XCTAssertTrue(City.nyc.hasNYCExtras)
        // Two cities' record blobs must not land on the same cache file.
        let caches = City.all.compactMap { c in c.recordsPath.map { DataStore.cacheName($0, in: c) } }
        XCTAssertEqual(Set(caches).count, caches.count, "each city needs its own record cache file")
        XCTAssertFalse(caches.contains { $0.contains("/") }, "a cache filename cannot be a path")
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
        // LA read as "ZIP 90210" until the LA Times boundaries landed on every
        // parcel (2026-09-12); it now names the neighborhood like SF and DC.
        let la = Building(bbl: "LA-1", b: "LA", a: "A", z: "90210", lat: 34, lng: -118, nb: "Beverly Grove")
        XCTAssertEqual(la.place(in: .la), "Beverly Grove")
        let laNoNb = Building(bbl: "LA-2", b: "LA", a: "B", z: "90210", lat: 34, lng: -118)
        XCTAssertEqual(laNoNb.place(in: .la), "Los Angeles", "a parcel outside every polygon still has to say where it is")
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

final class SkylineTests: XCTestCase {
    func testEveryCityHasItsOwnScene() {
        XCTAssertEqual(Skyline.Scene.scene(for: "nyc"), .newYork)
        XCTAssertEqual(Skyline.Scene.scene(for: "sf"), .sanFrancisco)
        XCTAssertEqual(Skyline.Scene.scene(for: "dc"), .washington)
        XCTAssertEqual(Skyline.Scene.scene(for: "la"), .losAngeles)
        XCTAssertEqual(Skyline.Scene.scene(for: "nowhere"), .newYork, "an unknown city falls back to New York, like City.find")
        for city in City.all { XCTAssertEqual(Skyline.Scene.scene(for: city.id).rawValue.isEmpty, false) }
    }

    func testScenesShowTheLandmarksAsked() {
        let ny = Skyline.Scene.newYork.landmarks.map(\.name)
        XCTAssertTrue(ny.contains("Statue of Liberty") && ny.contains("Brooklyn Bridge") && ny.contains("One Times Square"))
        XCTAssertTrue(Skyline.Scene.sanFrancisco.landmarks.map(\.name).contains("Golden Gate Bridge"))
        XCTAssertTrue(Skyline.Scene.washington.landmarks.map(\.name).contains("Washington Monument"))
        XCTAssertTrue(Skyline.Scene.losAngeles.landmarks.map(\.name).contains("Hollywood Sign"))
        for scene in Skyline.Scene.allCases {
            let xs = scene.landmarks.map(\.x)
            XCTAssertEqual(xs, xs.sorted(), "\(scene) landmarks are laid out left to right")
            XCTAssertTrue(xs.allSatisfy { $0 > 0 && $0 < 1 }, "\(scene) landmarks sit inside the band")
        }
    }

    func testBlinkingIsDeterministicAndMostlyOn() {
        // Same window, same second → same answer, run after run.
        XCTAssertEqual(Skyline.windowLit(id: 42, at: 1000), Skyline.windowLit(id: 42, at: 1000))
        var lit = 0, changes = 0
        for id in 0..<200 {
            var last: Bool? = nil
            for step in 0..<20 {
                let on = Skyline.windowLit(id: id, at: Double(step) * 0.5)
                if on { lit += 1 }
                if let l = last, l != on { changes += 1 }
                last = on
            }
        }
        XCTAssertGreaterThan(Double(lit) / 4000, 0.6, "most windows are lit")
        XCTAssertGreaterThan(changes, 100, "windows actually blink over 10 s")
    }

    func testStarsFillTheSkyWithoutLeavingIt() {
        let size = CGSize(width: 393, height: Skyline.skyHeight)
        let stars = Skyline.stars(in: size)
        XCTAssertGreaterThanOrEqual(stars.count, 18)
        XCTAssertTrue(stars.allSatisfy { $0.x >= 0 && $0.x <= size.width && $0.y >= 0 && $0.y <= size.height })
        XCTAssertEqual(stars.map(\.x), Skyline.stars(in: size).map(\.x), "positions are stable between draws")
    }
}
