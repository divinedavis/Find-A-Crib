import XCTest

/// The iPad walk (owner, 2026-09-22: "an iPad companion with the same features
/// the iOS version has"). Every tab and the search → results → detail path, in
/// portrait and landscape, asserting each screen is reachable and usable.
/// Runs only on an iPad simulator; on an iPhone it skips.
///
/// Set TEST_RUNNER_IPAD_SHOTS=/some/dir to also write a PNG of every screen —
/// that is how the layout was reviewed, and how iPad App Store screenshots can
/// be made later.
final class IPadTourTests: XCTestCase {
    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        try XCTSkipUnless(UIDevice.current.userInterfaceIdiom == .pad, "iPad only")
        XCUIDevice.shared.orientation = .portrait
    }

    override func tearDown() {
        XCUIDevice.shared.orientation = .portrait
        super.tearDown()
    }

    private func launch(_ extra: [String] = []) {
        app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash"] + extra
        app.launch()
    }

    private func shot(_ name: String) {
        let png = XCUIScreen.main.screenshot().pngRepresentation
        let a = XCTAttachment(data: png, uniformTypeIdentifier: "public.png")
        a.name = name; a.lifetime = .keepAlways; add(a)
        if let dir = ProcessInfo.processInfo.environment["IPAD_SHOTS"], !dir.isEmpty {
            try? FileManager.default.createDirectory(atPath: dir, withIntermediateDirectories: true)
            try? png.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).png"))
        }
    }

    private func searchToDetail(_ tag: String) {
        let search = app.buttons["search-button"]
        XCTAssertTrue(search.waitForExistence(timeout: 30), "\(tag): the search form should load")
        let counted = NSPredicate(format: "label CONTAINS 'Search' AND NOT (label CONTAINS 'Search 0 ')")
        expectation(for: counted, evaluatedWith: search); waitForExpectations(timeout: 30)
        shot("\(tag)-1-search")
        // On an iPad mini the button can sit under the floating tab bar while
        // still counting as hittable; scroll until it clears the bar.
        let bar = app.buttons["tab-Search"]
        for _ in 0..<4 where !search.isHittable || (bar.exists && search.frame.maxY > bar.frame.minY - 8) { app.swipeUp() }
        search.tap()
        let count = app.staticTexts["results-count"]
        XCTAssertTrue(count.waitForExistence(timeout: 20), "\(tag): results should open")
        let addr = app.buttons["card-address"].firstMatch
        XCTAssertTrue(addr.waitForExistence(timeout: 15), "\(tag): results should list buildings")
        sleep(2); shot("\(tag)-2-results")
        // One-tap filters beside the shorter location field (owner, 2026-09-22).
        let avail = app.buttons["quick-available"]
        XCTAssertTrue(avail.waitForExistence(timeout: 5), "\(tag): the quick filters should sit in the top row")
        // The core three always; more as the bar gets wider (all six on a
        // 13-inch or sideways). Whatever shows must fit beside a readable field.
        for id in ["quick-beds", "quick-price", "results-filter"] {
            XCTAssertTrue(app.buttons[id].isHittable, "\(tag): \(id) should fit on the row")
        }
        let field = app.buttons["results-location-field"]
        XCTAssertGreaterThanOrEqual(field.frame.width, 170, "\(tag): the location field must not be squeezed out")
        let filter = app.buttons["results-filter"]
        XCTAssertLessThanOrEqual(filter.frame.maxX, app.windows.firstMatch.frame.maxX, "\(tag): Filter must stay on screen")
        XCTAssertTrue(filter.label.contains("Filter"), "\(tag): the Filter button should keep its label, got \(filter.label)")
        let before = count.label
        avail.tap()
        expectation(for: NSPredicate(format: "label != %@", before), evaluatedWith: count); waitForExpectations(timeout: 10)
        sleep(1); shot("\(tag)-2b-available-now")
        avail.tap()
        expectation(for: NSPredicate(format: "label == %@", before), evaluatedWith: count); waitForExpectations(timeout: 10)
        addr.tap()
        XCTAssertTrue(app.otherElements["detail-hero"].waitForExistence(timeout: 20) || app.staticTexts["About"].waitForExistence(timeout: 20),
                      "\(tag): a building should open")
        sleep(2); shot("\(tag)-3-detail")
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(count.waitForExistence(timeout: 10), "\(tag): back returns to the results")
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(search.waitForExistence(timeout: 10), "\(tag): back again returns to the search")
    }

    private func tabs(_ tag: String) {
        for (tab, check) in [("Events", "tab-Events"), ("My Activity", "tab-My Activity"), ("Profile", "tab-Profile"), ("Lotteries", "tab-Lotteries")] {
            let b = app.buttons[check]
            XCTAssertTrue(b.waitForExistence(timeout: 15), "\(tag): the \(tab) tab should show")
            XCTAssertTrue(b.isHittable, "\(tag): the \(tab) tab should be tappable")
            b.tap(); sleep(2)
            shot("\(tag)-tab-\(tab.replacingOccurrences(of: " ", with: ""))")
        }
        // Lotteries is the last tab tapped: its Re-rentals pane too.
        let rer = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Re-rentals'")).firstMatch
        XCTAssertTrue(rer.waitForExistence(timeout: 10), "\(tag): the Re-rentals pane should be reachable")
        rer.tap()
        XCTAssertTrue(app.descendants(matching: .any)["rerental-card"].firstMatch.waitForExistence(timeout: 10)
                      || app.descendants(matching: .any)["lotteries-empty"].firstMatch.exists, "\(tag): re-rentals should list")
        sleep(3); shot("\(tag)-tab-Rerentals")
        XCTAssertTrue(app.buttons["tab-Profile"].exists)
        app.buttons["tab-Search"].tap()
    }

    func testPortraitTour() throws {
        launch(["--lotteries-demo", "--events-demo"])
        searchToDetail("portrait")
        tabs("portrait")
    }

    func testLandscapeTour() throws {
        launch(["--lotteries-demo", "--events-demo"])
        XCUIDevice.shared.orientation = .landscapeLeft
        sleep(1)
        searchToDetail("landscape")
        tabs("landscape")
    }

    func testMapOnIPad() throws {
        launch(["--route", "map"])
        let list = app.buttons["pill-List"]
        XCTAssertTrue(list.waitForExistence(timeout: 30), "the map should open with its List pill")
        sleep(3); shot("portrait-4-map")
        XCUIDevice.shared.orientation = .landscapeLeft
        sleep(3); shot("landscape-4-map")
        XCTAssertTrue(list.isHittable, "the List pill should stay reachable in landscape")
    }
}
