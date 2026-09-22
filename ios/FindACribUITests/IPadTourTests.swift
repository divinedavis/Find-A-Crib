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
        if !search.isHittable { app.swipeUp() }
        search.tap()
        let count = app.staticTexts["results-count"]
        XCTAssertTrue(count.waitForExistence(timeout: 20), "\(tag): results should open")
        let addr = app.buttons["card-address"].firstMatch
        XCTAssertTrue(addr.waitForExistence(timeout: 15), "\(tag): results should list buildings")
        sleep(2); shot("\(tag)-2-results")
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
        for (tab, check) in [("My Activity", "tab-My Activity"), ("Profile", "tab-Profile"), ("Lotteries", "tab-Lotteries")] {
            let b = app.buttons[check]
            XCTAssertTrue(b.waitForExistence(timeout: 15), "\(tag): the \(tab) tab should show")
            XCTAssertTrue(b.isHittable, "\(tag): the \(tab) tab should be tappable")
            b.tap(); sleep(2)
            shot("\(tag)-tab-\(tab.replacingOccurrences(of: " ", with: ""))")
        }
        XCTAssertTrue(app.buttons["tab-Profile"].exists)
        app.buttons["tab-Search"].tap()
    }

    func testPortraitTour() throws {
        launch(["--lotteries-demo"])
        searchToDetail("portrait")
        tabs("portrait")
    }

    func testLandscapeTour() throws {
        launch(["--lotteries-demo"])
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
