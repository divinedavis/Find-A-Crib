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
        XCTAssertEqual(DataStore.files(for: .nyc).count, 6, "buildings + listings, s8, fmr, hcr, featured")
        XCTAssertTrue(DataStore.files(for: .nyc).contains("featured.json"), "the re-rental feed is a New York extra")
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
        XCTAssertEqual(Skyline.Scene.scene(for: "st-nj"), .homes, "a state map gets no one city's landmarks")
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

final class MapViewportTests: XCTestCase {
    func testCountInViewUsesTheExactViewport() {
        let mk = { (lat: Double, lng: Double) in Building(bbl: "\(lat),\(lng)", b: "", a: "", z: nil, lat: lat, lng: lng) }
        let inside = [mk(40.688, -73.97), mk(40.692, -73.96)]
        let outside = [mk(40.75, -73.97), mk(40.68, -74.10), mk(40.6849, -73.97)]   // north, west, just under the edge
        let region = MKCoordinateRegion(center: .init(latitude: 40.69, longitude: -73.965),
                                        span: .init(latitudeDelta: 0.01, longitudeDelta: 0.02))
        XCTAssertEqual(BuildingMap.countInView(inside + outside, region: region), 2)
        XCTAssertEqual(BuildingMap.countInView([], region: region), 0)
    }
}

final class RerentalFeedTests: XCTestCase {
    private func b(_ i: Int, boro: String = "Bk") -> Building { Building(bbl: "b\(i)", b: boro, a: "", z: nil, lat: 40.6, lng: -73.9) }
    private func f(_ i: Int, boro: String? = "Brooklyn") -> FeaturedListing {
        FeaturedListing(agent: "Agent \(i)", address: "\(i) Main St", borough: boro, href: "https://example.com/\(i)")
    }

    func testFirstTileIsThirdThenEvery8To15NeverAdjacent() {
        for seed: UInt64 in [1, 7, 99, 12345, .max] {
            let slots = RerentalFeed.slots(tiles: 400, seed: seed)
            XCTAssertEqual(slots.first, 2, "the first re-rental is the 3rd tile (seed \(seed))")
            for (a, z) in zip(slots, slots.dropFirst()) {
                let between = z - a - 1
                XCTAssertTrue((8...15).contains(between), "\(between) tiles between re-rentals (seed \(seed))")
            }
            XCTAssertEqual(slots, RerentalFeed.slots(tiles: 400, seed: seed), "same seed, same feed")
            XCTAssertEqual(Array(slots.prefix(3)), Array(RerentalFeed.slots(tiles: 60, seed: seed).prefix(3)), "paging further extends, never reshuffles")
        }
        XCTAssertNotEqual(RerentalFeed.slots(tiles: 400, seed: 1), RerentalFeed.slots(tiles: 400, seed: 2), "different launches differ")
    }

    func testRowsInterleaveWithoutRepeatingOrTouching() {
        let buildings = (0..<100).map { b($0) }
        let pool = (0..<3).map { f($0) }
        let rows = RerentalFeed.rows(buildings: buildings, pool: pool, seed: 42)
        XCTAssertEqual(rows.filter { if case .building = $0 { return true }; return false }.count, 100, "every building is still in the feed")
        var lastWasRerental = false, previous: FeaturedListing? = nil, rerentals = 0
        for (i, r) in rows.enumerated() {
            if case .rerental(let l, _) = r {
                rerentals += 1
                XCTAssertFalse(lastWasRerental, "two re-rentals touched at row \(i)")
                XCTAssertNotEqual(previous?.id, l.id, "the same apartment twice running at row \(i)")
                previous = l; lastWasRerental = true
            } else { lastWasRerental = false }
        }
        if case .rerental = rows[2] {} else { XCTFail("the 3rd tile is a re-rental") }
        XCTAssertGreaterThanOrEqual(rerentals, 6)
        XCTAssertEqual(Set(rows.map(\.id)).count, rows.count, "row ids are unique for ForEach")
        XCTAssertEqual(RerentalFeed.rows(buildings: buildings, pool: [], seed: 42).count, 100, "no pool, no tiles")
    }

    func testPoolFollowsTheBoroughsInTheResults() {
        let featured = [f(0, boro: "Brooklyn"), f(1, boro: "Bronx"), f(2, boro: "The Bronx"), f(3, boro: nil), f(4, boro: "Manhattan")]
        let pool = RerentalFeed.pool(featured, for: [b(0, boro: "Bk"), b(1, boro: "Bx")])
        XCTAssertEqual(pool.map(\.agent), ["Agent 0", "Agent 1", "Agent 2"], "Brooklyn and both Bronx spellings; Manhattan and the unnamed one stay out")
    }

    /// The pest filter has one job beyond finding pests: NOT counting the
    /// 73,000 "FILE ANNUAL BEDBUG REPORT" notices, which are a paperwork
    /// violation and not a bug in anyone's apartment.
    func testPestWordReadsTheNoticeText() {
        XCTAssertEqual(HPDRecords.pestWord("HMC ADM CODE: § 27-2017.4 ABATE THE INFESTATION CONSISTING OF ROACHES IN THE ENTIRE APARTMENT"), "roaches")
        XCTAssertEqual(HPDRecords.pestWord("§ 27-2018 ADM CODE ABATE THE NUISANCE CONSISTING OF VERMIN MICE IN THE ENTIRE APARTMENT"), "mice")
        XCTAssertEqual(HPDRecords.pestWord("ABATE THE NUISANCE CONSISTING OF EVIDENCE OF RATS"), "rats")
        XCTAssertEqual(HPDRecords.pestWord("ABATE THE INFESTATION CONSISTING OF BEDBUGS IN THE ENTIRE APARTMENT"), "bedbugs")
        XCTAssertEqual(HPDRecords.pestWord("ABATE THE NUISANCE CONSISTING OF VERMIN"), "vermin")
        XCTAssertEqual(HPDRecords.pestWord(nil), "vermin")
    }

    func testPestFilterDemandsAConfirmedInfestation() {
        let w = HPDRecords.pestWhere
        // Both halves: the wording an inspector uses, AND a named pest.
        XCTAssertTrue(w.contains("INFESTATION CONSISTING OF") && w.contains("NUISANCE CONSISTING OF"),
                      "without CONSISTING OF, 'FILE ANNUAL BEDBUG REPORT' counts as bedbugs")
        for pest in ["ROACH", "MICE", "RATS", "BEDBUG", "BED BUG", "VERMIN"] {
            XCTAssertTrue(w.contains("'%\(pest)%'"), "\(pest) is missing from the pest filter")
        }
        XCTAssertFalse(w.contains("FILE ANNUAL"), "the paperwork violation is not a pest")
    }

    /// The tile's numbers come from Socrata's own grouped count, so a building
    /// with more pest violations than one page holds still adds up.
    func testPestSummaryLineReadsMostFirst() {
        let s = HPDRecords.PestSummary(thisYear: 8, openThisYear: 3, total: 43,
                                       kinds: [(word: "roaches", count: 5), (word: "mice", count: 3)])
        XCTAssertEqual(s.kindLine, "5 roaches · 3 mice")
        XCTAssertFalse(s.clean)
        XCTAssertTrue(HPDRecords.PestSummary(thisYear: 0, openThisYear: 0, total: 43, kinds: []).clean,
                      "43 on record but none this year is a clean year, and the tile says so")
    }

    func testFeaturedSeedDecodesAndTagsOutboundLinks() throws {
        guard let url = Bundle(for: DataStore.self).url(forResource: "featured", withExtension: "json", subdirectory: "Data")
                ?? Bundle(for: DataStore.self).url(forResource: "featured", withExtension: "json") else {
            return XCTFail("featured.json is not in the bundle — scripts/refresh_data.sh seeds it")
        }
        let blob = try JSONDecoder().decode(FeaturedBlob.self, from: Data(contentsOf: url))
        XCTAssertGreaterThan(blob.listings.count, 5)
        XCTAssertTrue(blob.listings.contains { $0.moneyKind == "rent" && $0.moneyLine.text.hasSuffix("/mo") })
        XCTAssertTrue(blob.listings.allSatisfy { !$0.href.isEmpty && !$0.address.isEmpty })
        XCTAssertTrue(blob.listings.contains { $0.imageExterior },
                      "the sweep marks the outside-of-the-building photos (photo_kind.py) — the banner needs one")
        XCTAssertTrue(blob.listings.allSatisfy { !$0.imageExterior || $0.image != nil }, "no photo, no flag")
        let out = try XCTUnwrap(blob.listings[0].outboundURL)
        XCTAssertTrue(out.absoluteString.contains("utm_source=findacrib.com") && out.absoluteString.contains("utm_campaign=rerental_tile"))
        XCTAssertNil(FeaturedListing(agent: "", address: "", borough: nil, href: "javascript:alert(1)").outboundURL, "only http(s) hands off")
        XCTAssertEqual(FeaturedListing(agent: "", address: "", borough: nil, href: "https://x.org/u?utm_source=other").outboundURL?.absoluteString,
                       "https://x.org/u?utm_source=other", "never overwrite a campaign somebody else set")
    }
}

@MainActor
final class AnalyticsEventShapeTests: XCTestCase {
    func testLaunchSourceKeepsHostAndPathNeverTheQuery() {
        XCTAssertEqual(Analytics.source(for: URL(string: "https://findacrib.com/building/brooklyn/x-3001?token=SECRET")!), "link:findacrib.com/building/brooklyn/x-3001")
        XCTAssertEqual(Analytics.source(for: URL(string: "findacrib://auth-callback?code=abc")!), "app:auth-callback")
        XCTAssertFalse(Analytics.source(for: URL(string: "https://findacrib.com/?utm_source=qr&email=a@b.c")!).contains("email"))
    }

    func testSearchShapeCarriesNoText() {
        var q = SearchQuery(); q.locations = [.borough("Bk"), .neighborhood("Bushwick")]; q.maxPrice = 3000; q.availableOnly = true
        let p = Analytics.shape(q)
        XCTAssertEqual(p["locations"] as? Int, 2)
        XCTAssertEqual(p["priced"] as? Bool, true)
        XCTAssertEqual(p["available_only"] as? Bool, true)
        XCTAssertNil(p["q"]); XCTAssertNil(p["text"])
        XCTAssertFalse(p.values.contains { ($0 as? String)?.contains("Bushwick") == true }, "a neighborhood name is text, not shape")
    }

    func testTilePropsMatchTheSiteShape() {
        let f = FeaturedListing(agent: "MGNY", address: "1 Main St", borough: "Bronx", href: "https://x.org/1")
        let p = Analytics.tileProps(f, slot: 2)
        XCTAssertEqual(Set(p.keys), ["kind", "agent", "addr", "boro", "slot", "link"], "featProps() in index.html sends exactly these")
        XCTAssertEqual(p["kind"] as? String, "rerental")
        XCTAssertEqual(p["slot"] as? Int, 2)
        XCTAssertEqual(p["link"] as? String, "listing", "a listing with no href_kind is a unit page")
    }

    func testTrackingIsLiveAndTheLabelWasPublishedFirst() {
        // Flipped 2026-09-16, after asc_push_privacy_iris.py published
        // PRODUCT_INTERACTION + OTHER_USAGE_DATA (Analytics, linked, no
        // tracking) alongside NAME / EMAIL_ADDRESS / USER_ID /
        // PURCHASE_HISTORY. An event collecting anything outside those six
        // types needs the label published again before the build ships.
        XCTAssertTrue(Analytics.privacyLabelDeclared)
    }

    func testEveryEventIsOffWhenTheUserOptsOut() {
        let a = Analytics.shared
        let was = a.enabled
        defer { a.enabled = was }
        a.enabled = false
        // Nothing to assert on the wire from a unit test; what this pins is
        // that the switch is the thing `track` consults and that it persists,
        // so Profile → Share anonymous usage actually silences the app.
        XCTAssertFalse(a.enabled)
        a.track("search")
        XCTAssertFalse(UserDefaults.standard.bool(forKey: "analytics.enabled"))
    }
}

final class ReviewPromptTests: XCTestCase {
    private let day: TimeInterval = 86_400

    func testAsksOnceThenGoesQuietForTheVersionAndTheWindow() {
        let now = Date()
        // Never asked: ask.
        XCTAssertTrue(ReviewPrompt.shouldAsk(version: "1.2.1", lastVersion: nil, lastAsked: nil, now: now))
        // Asked on this version, whenever: never again on it.
        XCTAssertFalse(ReviewPrompt.shouldAsk(version: "1.2.1", lastVersion: "1.2.1", lastAsked: now.addingTimeInterval(-400 * day), now: now))
        // New version but asked recently: still quiet.
        XCTAssertFalse(ReviewPrompt.shouldAsk(version: "1.3.0", lastVersion: "1.2.1", lastAsked: now.addingTimeInterval(-30 * day), now: now))
        // New version and the quiet window has passed: ask again.
        XCTAssertTrue(ReviewPrompt.shouldAsk(version: "1.3.0", lastVersion: "1.2.1", lastAsked: now.addingTimeInterval(-Double(ReviewPrompt.quietDays + 1) * day), now: now))
        // The boundary itself is still quiet.
        XCTAssertFalse(ReviewPrompt.shouldAsk(version: "1.3.0", lastVersion: "1.2.1", lastAsked: now.addingTimeInterval(-Double(ReviewPrompt.quietDays) * day + 60), now: now))
    }

    func testScheduledAsks() {
        var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "America/New_York")!
        func at(_ y: Int, _ m: Int, _ d: Int, _ h: Int = 12) -> Date { cal.date(from: DateComponents(year: y, month: m, day: d, hour: h))! }
        let s = { (signedIn: Bool, signup: String?, monthly: String?, last: String?, now: Date) in
            ReviewPrompt.scheduledMoment(signedIn: signedIn, signupDay: signup, lastMonthly: monthly, lastAskDay: last, now: now, calendar: cal) }
        // Signed up today: the next open asks.
        XCTAssertEqual(s(true, "2026-09-19", nil, nil, at(2026, 9, 19)), .signup)
        // Signed up yesterday and never came back that day: no catch-up ask.
        XCTAssertNil(s(true, "2026-09-18", nil, nil, at(2026, 9, 19)))
        // The 1st: signed-in people are asked once that month.
        XCTAssertEqual(s(true, nil, nil, nil, at(2026, 10, 1)), .monthly)
        XCTAssertNil(s(true, nil, "2026-10", nil, at(2026, 10, 1)), "already asked this month")
        XCTAssertEqual(s(true, nil, "2026-10", nil, at(2026, 11, 1)), .monthly)
        XCTAssertNil(s(true, nil, nil, nil, at(2026, 10, 2)), "only on the 1st")
        // Never signed out, never twice in a day.
        XCTAssertNil(s(false, "2026-10-01", nil, nil, at(2026, 10, 1)))
        XCTAssertNil(s(true, "2026-10-01", nil, "2026-10-01", at(2026, 10, 1)))
        // Local midnight edge: 12:30am on the 1st in New York is the 1st.
        XCTAssertEqual(s(true, nil, nil, nil, at(2026, 10, 1, 0)), .monthly)
    }

    @MainActor
    func testScheduledAskIsSpentAndBlocksTheSameDay() {
        let d = UserDefaults(suiteName: "review-sched-\(UUID().uuidString)")!
        let p = ReviewPrompt(defaults: d)
        let now = Date()
        p.noteSignup(now: now)
        p.appOpened(signedIn: true, pushCardShowing: true, now: now)
        XCTAssertNotNil(d.string(forKey: "review.signupDay"), "the notifications card had this launch; the ask waits")
        p.appOpened(signedIn: true, pushCardShowing: false, now: now)
        XCTAssertNil(d.string(forKey: "review.signupDay"), "the sign-up ask is spent")
        XCTAssertEqual(d.string(forKey: "review.lastAskDay"), ReviewPrompt.dayKey(now))
    }

    func testWriteReviewLinkIsTheAppsOwnPage() {
        let u = ReviewPrompt.writeReviewURL.absoluteString
        XCTAssertTrue(u.contains("id6807549249"), "must point at Find A Crib, ASC app 6807549249")
        XCTAssertTrue(u.contains("action=write-review"))
    }

    @MainActor
    func testRecordingAMomentIsGatedThroughTheSameRule() {
        let d = UserDefaults(suiteName: "review-tests-\(UUID().uuidString)")!
        let p = ReviewPrompt(defaults: d)
        XCTAssertNil(d.string(forKey: "review.lastVersion"))
        p.record(.save)
        XCTAssertNotNil(d.string(forKey: "review.lastVersion"), "the first save asks, and the ask is recorded before the sheet")
        let firstAsk = d.object(forKey: "review.lastAsked") as? Date
        p.record(.alerts)
        XCTAssertEqual(d.object(forKey: "review.lastAsked") as? Date, firstAsk, "a second good moment on the same version does not ask again")
    }
}

final class PushServiceTests: XCTestCase {
    func testEnvironmentComesFromTheProfileNotAGuess() {
        XCTAssertEqual(PushService.environment(fromProfile: "<key>aps-environment</key>\n\t<string>development</string>"), "sandbox")
        XCTAssertEqual(PushService.environment(fromProfile: "<key>aps-environment</key><string>production</string>"), "production")
        XCTAssertNil(PushService.environment(fromProfile: "<key>get-task-allow</key><true/>"), "no aps-environment: fall back to the build configuration, never to a blanket sandbox")
        XCTAssertNil(PushService.environment(fromProfile: ""))
    }

    func testDeepLinkAndBuildingParsing() {
        XCTAssertEqual(PushService.deepLink(in: ["url": "https://afny.org/re-rentals/1"])?.host, "afny.org")
        XCTAssertNil(PushService.deepLink(in: ["aps": ["alert": "x"]]))
        XCTAssertEqual(PushService.buildingBBL(in: URL(string: "https://findacrib.com/building/brooklyn/172-union-st-3003430015/")!), "3003430015")
        XCTAssertNil(PushService.buildingBBL(in: URL(string: "https://findacrib.com/alerts/")!), "not a building page")
        XCTAssertNil(PushService.buildingBBL(in: URL(string: "https://housingconnect.nyc.gov/building/brooklyn/x-3003430015/")!), "another host never opens in-app")
        XCTAssertNil(PushService.buildingBBL(in: URL(string: "https://findacrib.com/building/brooklyn/x-300343/")!), "a bbl is ten digits")
    }
}

final class PushSubscriberPromptTests: XCTestCase {
    func testEveryoneNeverAskedIsOfferedOnce() {
        let now = Date()
        XCTAssertTrue(PushService.shouldOffer(status: .notDetermined, snoozedUntil: nil, now: now), "signed in or not: everyone with the app is asked (owner, 2026-09-18)")
        XCTAssertFalse(PushService.shouldOffer(status: .authorized, snoozedUntil: nil, now: now), "already on")
        XCTAssertFalse(PushService.shouldOffer(status: .denied, snoozedUntil: nil, now: now), "declined at the system level: only Settings can undo it, never a re-ask")
        XCTAssertFalse(PushService.shouldOffer(status: .notDetermined, snoozedUntil: now.addingTimeInterval(3 * 86_400), now: now), "snoozed")
        XCTAssertTrue(PushService.shouldOffer(status: .notDetermined, snoozedUntil: now.addingTimeInterval(-60), now: now), "snooze expired")
    }

    func testSubscriptionReadsTheSameFieldsAsTheSheet() {
        XCTAssertTrue(PushService.isSubscribed(prefs: ["exists": true, "unsubscribed": false, "kinds": ["rerental"]]))
        XCTAssertFalse(PushService.isSubscribed(prefs: ["exists": true, "unsubscribed": true]))
        XCTAssertFalse(PushService.isSubscribed(prefs: ["exists": false]))
        XCTAssertFalse(PushService.isSubscribed(prefs: [:]))
    }
}

final class PushStateLineTests: XCTestCase {
    func testOnMeansRegisteredNotMerelyAllowed() {
        XCTAssertTrue(PushService.stateLine(status: .authorized, registration: .registered).ok)
        XCTAssertFalse(PushService.stateLine(status: .authorized, registration: .none).ok, "allowed but never filed is not on")
        XCTAssertFalse(PushService.stateLine(status: .authorized, registration: .failed).ok, "builds 48–50: allowed, registration failed, still said on")
        XCTAssertTrue(PushService.stateLine(status: .authorized, registration: .failed).text.contains("update the app"))
        XCTAssertTrue(PushService.stateLine(status: .denied, registration: .registered).text.contains("Settings"), "a denial wins even with a stale token")
        XCTAssertEqual(PushService.stateLine(status: .notDetermined, registration: .none).text, "Turn on phone alerts")
    }
}

final class AlertPushTests: XCTestCase {
    func testEveryItemInThePayloadIsReachable() {
        let info: [AnyHashable: Any] = [
            "url": "https://residenewyork.com/property/a/",
            "items": [
                ["k": "rerental", "t": "2067 Anthony Avenue, Unit 305", "s": "Bronx · $2,100/mo", "u": "https://residenewyork.com/property/a/", "b": "Bx"],
                ["k": "rerental", "t": "1952 Anthony Avenue. Unit 2F", "s": "", "u": "https://www.taxaceny.com/projects-8#:~:text=1952%20Anthony", "b": "Bx"],
                ["k": "lottery", "t": "Astoria Commons", "s": "Queens · closes 10/1", "u": "", "b": "Q"],
                ["k": "rerental", "t": "", "s": "no headline is skipped", "u": "https://x.org", "b": ""],
            ]]
        let p = AlertPush.from(userInfo: info, title: "New: 3 re-rentals", body: "…")
        XCTAssertEqual(p?.items.count, 3, "all items with a headline, not just the first")
        XCTAssertEqual(p?.items[1].url?.absoluteString, "https://www.taxaceny.com/projects-8#:~:text=1952%20Anthony", "the scroll-to-unit fragment survives")
        XCTAssertNil(p?.items[2].url, "an empty link is no link, not a broken button")
        XCTAssertEqual(p?.title, "New: 3 re-rentals")
    }

    func testAnOldPayloadStillOpensTheAppNotASite() {
        let p = AlertPush.from(userInfo: ["url": "https://findacrib.com/alerts/"], title: "Find A Crib: push alerts are on", body: "This is a test.")
        XCTAssertEqual(p?.items.count, 1)
        XCTAssertEqual(p?.items.first?.text, "This is a test.")
        XCTAssertEqual(p?.items.first?.url?.host, "findacrib.com")
        XCTAssertNil(AlertPush.from(userInfo: [:], title: "", body: ""), "nothing to show: no sheet")
    }
}

final class LotteryFeedTests: XCTestCase {
    private func lot(_ id: Int, _ boro: String, _ closes: String?, income: (Int, Int)? = nil) -> LotteryFeed.Lottery {
        LotteryFeed.Lottery(id: id, name: "L\(id)", borough: boro, neighborhood: nil, rent_low: 1500, rent_high: 2000,
                            income_min: income?.0, income_max: income?.1, household_min: 1, household_max: 3,
                            beds: ["Studio", "1-bed"], closes: closes, href: "https://housingconnect.nyc.gov/PublicWeb/details/\(id)")
    }

    func testOnlyTheirBoroughsStillOpenSoonestFirst() {
        let all = [lot(1, "Bronx", "2026-10-05"), lot(2, "Brooklyn", "2026-09-22"), lot(3, "Queens", "2026-09-20"),
                   lot(4, "Bronx", "2026-09-18"), lot(5, "Bronx", "2026-09-19")]
        let got = LotteryFeed.filter(all, boroughs: ["Bx", "Bk"], today: "2026-09-19")
        XCTAssertEqual(got.map(\.id), [5, 2, 1], "Queens excluded, closed-yesterday excluded, closing-today kept, soonest first")
        XCTAssertTrue(LotteryFeed.filter(all, boroughs: [], today: "2026-09-19").isEmpty)
    }

    /// Every state is a place in the picker (owner, 2026-09-24), each its own
    /// files under states/<st>/, and none of them is taken for New York.
    func testStatesArePickableAndPointAtTheirOwnFiles() {
        XCTAssertGreaterThanOrEqual(City.states.count, 51, "50 states and DC")
        let nj = City.find("st-nj")
        XCTAssertEqual(nj.name, "New Jersey")
        XCTAssertTrue(nj.isState); XCTAssertFalse(nj.isNYC); XCTAssertFalse(nj.hasNYCExtras)
        XCTAssertEqual(nj.dataPath, "states/nj/buildings.slim.json.gz")
        XCTAssertEqual(nj.recordsPath, "states/nj/buildings.hpd.json.gz")
        XCTAssertEqual(Set(City.all.map(\.id)).count, City.all.count, "no two places share an id")
        XCTAssertEqual(Set(City.all.map(\.cacheName)).count, City.all.count, "no two places share a cache file")
        XCTAssertEqual(City.find("st-ny").name, "New York State", "not confused with the NYC register")
        XCTAssertEqual(HeroBanner.line(for: nj), "Every income-restricted building in NJ")
        let b = Building(bbl: "LIHTC-NJA1", b: "NJ", a: "1 MILL ST", z: "07416", lat: 41, lng: -74.5, nb: "Franklin")
        XCTAssertEqual(b.webURL(in: nj).host, "maps.apple.com", "no web page for state maps yet: share the place")
    }

    /// The record file's LIHTC fields decode (build_lihtc_states.py's keys).
    func testTaxCreditRecordDecodes() throws {
        let j = #"{"name":"Baxter Terrace","li":80,"units_total":90,"mix":{"1":40,"2":50},"inc":"60% of area median income","serves":["seniors"],"mgr":"Acme Llc","tel":"609-656-4205","pis":2012,"np":1}"#
        let r = try JSONDecoder().decode(BuildingRecord.self, from: Data(j.utf8))
        XCTAssertEqual(r.li, 80); XCTAssertEqual(r.mix?["2"], 50); XCTAssertEqual(r.tel, "609-656-4205"); XCTAssertEqual(r.pis, 2012)
    }

    /// NJ drawings (owner, 2026-09-24): past join-by dates drop out, the
    /// closing-today one stays, coming-soon ones sit last, and the file's
    /// shape decodes.
    func testNJDrawingsStillOpenSoonestFirst() throws {
        let json = #"""
        {"lotteries":[
         {"id":"buy-wall","town":"Wall","county":"Monmouth","tenure":"buy","closes":"2026-09-21","coming_soon":false,"href":"https://www.affordablehomesnewjersey.com/"},
         {"id":"buy-wayne","town":"Wayne","county":"Passaic","tenure":"buy","closes":null,"coming_soon":true,"href":"https://www.affordablehomesnewjersey.com/"},
         {"id":"rent-paramus","town":"Paramus","county":"Bergen","tenure":"rent","closes":"2026-11-19","coming_soon":false,"href":"https://www.affordablehomesnewjersey.com/"},
         {"id":"rent-wt","town":"Washington Township","county":null,"tenure":"rent","closes":"2026-09-24","coming_soon":false,"href":null}
        ]}
        """#
        struct P: Decodable { let lotteries: [LotteryFeed.NJLottery] }
        let all = try JSONDecoder().decode(P.self, from: Data(json.utf8)).lotteries
        let got = LotteryFeed.njFilter(all, today: "2026-09-24")
        XCTAssertEqual(got.map(\.id), ["rent-wt", "rent-paramus", "buy-wayne"], "closed Wall dropped, today kept, coming soon last")
        XCTAssertTrue(got[0].isRental); XCTAssertFalse(got[2].isRental)
    }

    func testBedFilterHidesLotteriesWithoutTheirSize() {
        XCTAssertFalse(LotteryFeed.bedsMatch(["2-bed", "3-bed"], want: [1]), "a 1-bed seeker does not see a 2/3-bed lottery")
        XCTAssertTrue(LotteryFeed.bedsMatch(["1-bed", "2-bed"], want: [1]))
        XCTAssertTrue(LotteryFeed.bedsMatch(["Studio", "1-bed"], want: [0]))
        XCTAssertTrue(LotteryFeed.bedsMatch(["2-bed", "3-bed"], want: [1, 3]), "any chosen size matches")
        XCTAssertTrue(LotteryFeed.bedsMatch(["5-bed"], want: [4]), "4+ covers five")
        XCTAssertTrue(LotteryFeed.bedsMatch(["2-bed"], want: []), "no choice = any size")
        XCTAssertTrue(LotteryFeed.bedsMatch(nil, want: [1]), "sizes not published: kept")
        XCTAssertTrue(LotteryFeed.bedsMatch(["studio"], want: [0]), "re-rental wording")
        XCTAssertFalse(LotteryFeed.bedsMatch(["1"], want: [2]))
        XCTAssertNil(LotteryFeed.bedCount("Loft"))
    }

    func testIncomeFitIsInclusiveAndNeedsBothNumbers() {
        XCTAssertTrue(LotteryFeed.incomeFits(70_000, lot(1, "Bronx", nil, income: (45_000, 70_000))))
        XCTAssertFalse(LotteryFeed.incomeFits(80_000, lot(1, "Bronx", nil, income: (45_000, 70_000))))
        XCTAssertFalse(LotteryFeed.incomeFits(nil, lot(1, "Bronx", nil, income: (45_000, 70_000))), "no income entered: no badge")
        XCTAssertFalse(LotteryFeed.incomeFits(60_000, lot(1, "Bronx", nil)), "no band published: no badge")
    }

    func testDaysLeft() {
        XCTAssertEqual(LotteryFeed.daysLeft("2026-09-22", today: "2026-09-19"), 3)
        XCTAssertEqual(LotteryFeed.daysLeft("2026-09-19", today: "2026-09-19"), 0)
        XCTAssertEqual(LotteryFeed.daysLeft("2026-11-02", today: "2026-11-01"), 1, "DST week")
        XCTAssertNil(LotteryFeed.daysLeft(nil))
    }

    func testDecodesTheLiveShape() throws {
        let json = #"{"generated":"2026-09-19","lotteries":[{"id":7569,"name":"1760 3rd Avenue Residence","borough":"Manhattan","neighborhood":"East Harlem","address":"1768 3 Avenue","zip":"10029","lat":40.7,"lng":-73.9,"rent_low":1328,"rent_high":1660,"income_min":45532,"income_max":91620,"household_min":1,"household_max":3,"beds":["Studio","1-bed"],"days_left":2,"closes":"2026-08-10","href":"https://housingconnect.nyc.gov/PublicWeb/details/7569"}]}"#
        struct P: Decodable { let lotteries: [LotteryFeed.Lottery] }
        let p = try JSONDecoder().decode(P.self, from: Data(json.utf8))
        XCTAssertEqual(p.lotteries.first?.borough, "Manhattan")
    }
}

@MainActor
final class CommentsStoreTests: XCTestCase {
    private func c(_ id: UUID = UUID(), parent: UUID? = nil, at: Date = Date(), likes: [UUID] = []) -> CommentsStore.Comment {
        CommentsStore.Comment(id: id, userID: UUID(), author: "Ada L", body: "hi", createdAt: at, parentID: parent, likedBy: likes)
    }

    func testThreadsLeadWithTheMostLikedCommentAndReply() {
        let now = Date()
        let quiet = UUID(), popular = UUID(), fresh = UUID(), topReply = UUID()
        let all = [c(quiet, at: now.addingTimeInterval(-300)),
                   c(popular, at: now.addingTimeInterval(-200), likes: [UUID(), UUID()]),
                   c(fresh, at: now.addingTimeInterval(-10)),
                   c(parent: popular, at: now.addingTimeInterval(-150)),
                   c(topReply, parent: popular, at: now.addingTimeInterval(-100), likes: [UUID()]),
                   c(parent: popular, at: now.addingTimeInterval(-50))]
        let t = CommentsStore.threads(all)
        XCTAssertEqual(t.map(\.0.id), [popular, fresh, quiet], "most liked first; a tie goes to the newest")
        XCTAssertEqual(t[0].1.count, 3, "every reply stays in the thread for View more")
        XCTAssertEqual(t[0].1.first?.id, topReply, "the reply shown first is the most liked")
        XCTAssertTrue(t[0].1[1].createdAt < t[0].1[2].createdAt, "tied replies read oldest first")
        XCTAssertTrue(t[1].1.isEmpty)
    }

    func testAgoMatchesTheWebsitesWording() {
        let now = Date()
        XCTAssertEqual(CommentsStore.ago(now.addingTimeInterval(-60), now: now), "just now")
        XCTAssertEqual(CommentsStore.ago(now.addingTimeInterval(-4 * 3600), now: now), "4h")
        XCTAssertEqual(CommentsStore.ago(now.addingTimeInterval(-3 * 86_400), now: now), "3d")
        XCTAssertFalse(CommentsStore.ago(now.addingTimeInterval(-90 * 86_400), now: now).hasSuffix("d"), "older than a month reads as a date")
    }

    func testLikeAndOwnershipAreByUserID() {
        let mine = UUID(), other = UUID()
        var x = c(likes: [other])
        XCTAssertFalse(x.isLiked(by: mine)); XCTAssertTrue(x.isLiked(by: other))
        XCTAssertFalse(x.isLiked(by: nil), "signed out, nothing reads as liked")
        x.likedBy.append(mine)
        XCTAssertTrue(x.isLiked(by: mine)); XCTAssertEqual(x.likes, 2)
        XCTAssertFalse(x.isMine(nil))
    }

    func testBlockingAndReportingHideTheRightRows() {
        let me = UUID(), troll = UUID(), other = UUID()
        let top = UUID(), trollTop = UUID(), reported = UUID()
        func c(_ id: UUID, by: UUID, parent: UUID? = nil) -> CommentsStore.Comment {
            CommentsStore.Comment(id: id, userID: by, author: "x", body: "b", createdAt: Date(), parentID: parent, likedBy: [])
        }
        let all = [c(top, by: other), c(trollTop, by: troll), c(reported, by: other),
                   c(UUID(), by: troll, parent: top),      // the troll's reply under someone else
                   c(UUID(), by: me, parent: trollTop)]    // my reply under the troll
        let left = CommentsStore.visible(all, blocked: [troll], reported: [reported])
        XCTAssertEqual(left.map(\.id), [top], "a blocked person's comments and replies go, and so does the reply under them")
        XCTAssertEqual(CommentsStore.visible(all, blocked: [], reported: []).count, all.count, "no blocks, nothing hidden")
    }

    func testTheWordFilterCatchesSlursWithoutEatingOrdinaryWords() {
        XCTAssertTrue(CommentsStore.isObjectionable("this super is a retard"))
        XCTAssertTrue(CommentsStore.isObjectionable("KYS"), "matched case-insensitively")
        XCTAssertTrue(CommentsStore.isObjectionable("kill yourself"), "phrases too")
        XCTAssertFalse(CommentsStore.isObjectionable("the radiator is classic prewar"), "'classic' contains no slur")
        XCTAssertFalse(CommentsStore.isObjectionable("Scunthorpe Ave has a nice super"))
        XCTAssertFalse(CommentsStore.isObjectionable("great building, quiet block"))
    }

    func testTimestampParsingHandlesBothShapesPostgrestSends() {
        XCTAssertEqual(Int(CommentsStore.date("2026-09-20T17:04:05.123456+00:00").timeIntervalSince1970),
                       Int(CommentsStore.date("2026-09-20T17:04:05+00:00").timeIntervalSince1970))
        XCTAssertGreaterThan(CommentsStore.date("2026-09-20T17:04:05+00:00").timeIntervalSince1970, 1_700_000_000)
    }
}


final class EventsFeedTests: XCTestCase {
    private func e(_ id: String, _ start: String, end: String? = nil, boro: String? = "Brooklyn", allDay: Bool = false,
                   hosts: [String]? = nil) -> EventsFeed.Event {
        EventsFeed.Event(id: id, title: "T\(id)", start: start, end: end, all_day: allDay, online: false, address: "1 Main St",
                         borough: boro, hosts: hosts, categories: nil, description: nil, url: "https://www.nyc.gov/x")
    }
    private let now = EventsFeed.parse("2026-09-22T09:00:00")!

    func testTheSameEventTwiceShowsOnce() {
        let all = [e("a", "2026-09-23T10:00:00"), e("a", "2026-09-23T10:00:00"), e("b", "2026-09-24T10:00:00")]
        XCTAssertEqual(EventsFeed.dedupe(all, now: now).map(\.id), ["a", "b"])
    }

    func testPastDaysGoAndTodayStays() {
        let all = [e("old", "2026-09-21T10:00:00"), e("today", "2026-09-22T08:00:00"), e("next", "2026-09-30T10:00:00")]
        XCTAssertEqual(EventsFeed.dedupe(all, now: now).map(\.id), ["today", "next"], "an event earlier today still shows")
    }

    func testSoonestFirstAndGroupedByDay() {
        let all = EventsFeed.dedupe([e("c", "2026-09-24T09:00:00"), e("a", "2026-09-23T15:00:00"), e("b", "2026-09-23T10:00:00")], now: now)
        let days = EventsFeed.byDay(all)
        XCTAssertEqual(days.map(\.day), ["2026-09-23", "2026-09-24"])
        XCTAssertEqual(days[0].events.map(\.id), ["b", "a"])
    }

    func testBoroughFilter() {
        let all = [e("bk", "2026-09-23T10:00:00"), e("bx", "2026-09-23T10:00:00", boro: "Bronx"), e("none", "2026-09-23T10:00:00", boro: nil)]
        XCTAssertEqual(EventsFeed.filter(all, borough: "Bronx").map(\.id), ["bx"])
        XCTAssertEqual(EventsFeed.filter(all, borough: nil).count, 3, "All shows every event, placed or not")
    }

    func testLabels() {
        XCTAssertEqual(EventsFeed.dayTitle("2026-09-22", now: now), "Today")
        XCTAssertEqual(EventsFeed.dayTitle("2026-09-23", now: now), "Tomorrow")
        XCTAssertEqual(EventsFeed.dayTitle("2026-09-25", now: now), "Friday, Sep 25")
        XCTAssertEqual(EventsFeed.timeLine(e("t", "2026-09-23T10:00:00", end: "2026-09-23T16:00:00")), "10:00 AM – 4:00 PM")
        XCTAssertEqual(EventsFeed.timeLine(e("t", "2026-09-23T00:00:00", allDay: true)), "All day")
        XCTAssertEqual(EventsFeed.hostLine(e("h", "2026-09-23T10:00:00", hosts: ["Mayor's Public Engagement Unit", "NYC Housing Preservation & Development"])),
                       "Mayor's Public Engagement Unit · HPD")
    }

    func testDecodesTheServerShape() throws {
        let json = #"{"generated":"2026-09-22T10:00:00Z","source":"x","fetched":3,"events":[{"id":"ab12","title":"Tenant Clinic","start":"2026-09-23T10:00:00","end":"2026-09-23T16:00:00","all_day":false,"address":"6206 6th Ave, Brooklyn, NY 11220","borough":"Brooklyn","lat":null,"lng":null,"hosts":["NYC Housing Preservation & Development"],"categories":["Tenant Resource Fair"],"description":"d","url":"https://www.nyc.gov/e","links":["https://www.nyc.gov/e"]}]}"#
        struct P: Decodable { let events: [EventsFeed.Event] }
        let p = try JSONDecoder().decode(P.self, from: Data(json.utf8))
        XCTAssertEqual(p.events.first?.borough, "Brooklyn")
        XCTAssertNotNil(p.events.first?.startDate)
    }
}
