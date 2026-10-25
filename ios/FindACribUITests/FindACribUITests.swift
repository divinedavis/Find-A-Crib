import XCTest

/// Smoke path through the StreetEasy-shaped flow: home → results → detail →
/// back, plus the tab bar. Runs against the bundled data only.
final class FindACribUITests: XCTestCase {
    /// Portrait first: a simulator left in landscape by an earlier run
    /// (2026-10-13: iPhone buttons reported at x=709) fails every portrait
    /// tap in the suite.
    override func setUp() { super.setUp(); XCUIDevice.shared.orientation = .portrait }
    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash"]   // the notifications card would sit on every tap
        // Animations 100x (FastAnimations.swift). The environment survives
        // the tests' own launchArguments, so every relaunch keeps it.
        app.launchEnvironment["FAC_FAST_ANIMATIONS"] = "1"
        // No launch here (2026-10-18): 45 of these tests relaunch with their
        // own arguments first thing, so a launch in setUp was thrown away
        // each time. A test that wants the default app calls app.launch().
    }

    func testSearchToDetailAndBack() throws {
        app.launch()
        let search = app.buttons["search-button"]
        XCTAssertTrue(search.waitForExistence(timeout: 20))
        // wait for the dataset: the button label carries the live count
        let counted = NSPredicate(format: "label CONTAINS 'Search' AND NOT (label CONTAINS 'Search 0 ')")
        expectation(for: counted, evaluatedWith: search); waitForExpectations(timeout: 30)
        if !search.isHittable { app.swipeUp() }   // the form runs past the fold on smaller phones
        search.tap()

        let count = app.staticTexts["results-count"]
        XCTAssertTrue(count.waitForExistence(timeout: 15))
        XCTAssertFalse(count.label.hasPrefix("0 "))

        let addr = app.buttons["card-address"].firstMatch
        XCTAssertTrue(addr.waitForExistence(timeout: 10))
        addr.tap()
        XCTAssertTrue(app.otherElements["detail-hero"].waitForExistence(timeout: 15) || app.staticTexts["About"].waitForExistence(timeout: 15))
        app.navigationBars.buttons.element(boundBy: 0).tap()   // the system chevron is the back control
        XCTAssertTrue(count.waitForExistence(timeout: 10))

        // The results screen has no back button of its own since 2c25b69; the
        // system chevron pops it, as it does the detail.
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(search.waitForExistence(timeout: 10))
    }

    /// The one outbound button (2026-10-06; label is just the site + arrow,
    /// owner 2026-10-11): every NYC card and detail sheet
    /// opens a StreetEasy address search, every Los Angeles one Zillow's. No
    /// asking rent, listing count or "Available now" filter survives.
    func testOutboundButtonPerCity() throws {
        for (city, label) in [("nyc", "StreetEasy ↗"), ("la", "View on Zillow ↗")] {
            app.terminate()
            app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--city", city, "--route", "results"]
            app.launch()
            let addr = app.buttons["card-address"].firstMatch
            XCTAssertTrue(addr.waitForExistence(timeout: 90), "\(city): results should list buildings")
            XCTAssertFalse(app.buttons["quick-available"].exists, "\(city): Available now is gone")
            XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] 'asking rent' OR label CONTAINS[c] 'Zumper'")).firstMatch.exists,
                           "\(city): no asking rents or Zumper copy")
            let cardOut = app.descendants(matching: .any)["card-outbound"].firstMatch
            for _ in 0..<3 where !cardOut.exists { app.swipeUp() }
            XCTAssertTrue(cardOut.waitForExistence(timeout: 10), "\(city): the card carries the outbound button")
            XCTAssertEqual(cardOut.label, label)
            app.buttons["card-address"].firstMatch.tap()
            let out = app.buttons["detail-outbound"]
            XCTAssertTrue(out.waitForExistence(timeout: 20), "\(city): the detail sheet carries the outbound button")
            XCTAssertEqual(out.label, label)
            XCTAssertTrue(out.isHittable, "\(city): it sits in the bottom bar")
        }
    }

    /// App Review 4.8: a third-party login must come with an equivalent that
    /// can hide the user's email. Signed out, the profile offers Sign in with
    /// Apple first, then Google, then email. Build 14 shipped without the
    /// Apple button and was rejected for exactly this.
    func testSignInOffersAppleFirst() throws {
        app.launch()
        XCTAssertTrue(app.buttons["tab-Profile"].waitForExistence(timeout: 20))
        app.buttons["tab-Profile"].tap()
        let apple = app.buttons["sign-in-apple"], google = app.buttons["sign-in-google"], email = app.buttons["sign-in-email"]
        XCTAssertTrue(apple.waitForExistence(timeout: 10), "Sign in with Apple must be offered")
        XCTAssertTrue(google.exists && email.exists)
        XCTAssertLessThan(apple.frame.minY, google.frame.minY, "Apple sits above Google")
        XCTAssertTrue(apple.label.contains("Apple"))
    }

    func testTabsSwitch() throws {
        app.launch()
        XCTAssertTrue(app.buttons["tab-My Activity"].waitForExistence(timeout: 20))
        app.buttons["tab-My Activity"].tap()
        XCTAssertTrue(app.staticTexts["My Activity"].waitForExistence(timeout: 5))
        app.buttons["tab-Profile"].tap()
        XCTAssertTrue(app.staticTexts["Profile"].waitForExistence(timeout: 5))
        app.buttons["tab-Search"].tap()
        XCTAssertTrue(app.buttons["search-button"].waitForExistence(timeout: 5))
    }

    /// The Search button sits right under Location and the price boxes come
    /// last (owner, 2026-10-11) — pinned by position so a reshuffle of the
    /// form cannot quietly put them back.
    func testSearchButtonSitsAbovePrice() throws {
        app.launch()
        let search = app.buttons["search-button"]
        let minBox = app.buttons["price-Minimum price"]
        XCTAssertTrue(search.waitForExistence(timeout: 20))
        XCTAssertTrue(minBox.waitForExistence(timeout: 10))
        XCTAssertLessThan(search.frame.minY, minBox.frame.minY,
                          "search button must come before the price row")
    }

    /// Bedrooms sits directly under Location, above the Search button
    /// (owner, 2026-10-13).
    func testBedroomsSitsUnderLocation() throws {
        app.launch()
        let location = app.descendants(matching: .any)["location-field"].firstMatch
        let beds = app.descendants(matching: .any)["beds-row"].firstMatch
        let search = app.buttons["search-button"]
        XCTAssertTrue(location.waitForExistence(timeout: 20))
        XCTAssertTrue(beds.waitForExistence(timeout: 10))
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        XCTAssertLessThan(location.frame.minY, beds.frame.minY, "Bedrooms must come after Location")
        XCTAssertLessThan(beds.frame.minY, search.frame.minY, "Bedrooms must come before the Search button")
    }

    /// Real no-match searches (2026-10-19): filter words become filters,
    /// "rent" says what the app is, Bed-Stuy's nickname works, Yonkers points
    /// at the Westchester map.
    func testLocationPickerReadsWhatPeopleType() throws {
        app.launch()
        let field = app.descendants(matching: .any)["location-field"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 20))
        field.tap()
        let search = app.textFields["location-search"]
        XCTAssertTrue(search.waitForExistence(timeout: 10))
        search.tap(); search.typeText("rent stabilized")
        XCTAssertTrue(app.staticTexts["location-filler"].waitForExistence(timeout: 5), "\"rent stabilized\" says what the app is")
        XCTAssertTrue(app.buttons["loc-Brooklyn"].exists, "and still lists the places")
        search.clearAndType("bedford stuy")
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'loc-Bed-Stuy'")).firstMatch.waitForExistence(timeout: 5), "the nickname finds Bed-Stuy")
        search.clearAndType("yonkers")
        XCTAssertTrue(app.descendants(matching: .any)["location-westchester"].waitForExistence(timeout: 5), "Yonkers points at the Westchester map")
        search.clearAndType("2 bedroom brooklyn")
        let intent = app.buttons["location-intent"]
        XCTAssertTrue(intent.waitForExistence(timeout: 5), "\"2 bedroom\" offers the filter")
        intent.tap()
        // With the keyboard up, the first tap in the list can be spent
        // dismissing it (failed twice in the full ship run, 10/20): wait for
        // the box to change, and tap again once if it didn't.
        let placeLeft = NSPredicate(format: "value == %@", "brooklyn")
        if XCTWaiter.wait(for: [expectation(for: placeLeft, evaluatedWith: search)], timeout: 3) != .completed, intent.exists { intent.tap() }
        XCTAssertEqual(search.value as? String, "brooklyn", "and leaves the place to pick")
        XCTAssertTrue(app.buttons["loc-Brooklyn"].waitForExistence(timeout: 5))
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "location-intent"; add(shot)
        app.buttons["location-done"].tap()
    }

    func testLocationPickerFiltersResults() throws {
        app.launch()
        let field = app.descendants(matching: .any)["location-field"].firstMatch
        XCTAssertTrue(field.waitForExistence(timeout: 20))
        field.tap()
        let brooklyn = app.buttons["loc-Brooklyn"]
        XCTAssertTrue(brooklyn.waitForExistence(timeout: 10))
        // The borough count now comes from DataStore.boroughCounts (built at
        // decode) rather than a scan in body; it must still show a real number.
        let counted = NSPredicate(format: "label MATCHES %@", ".*[1-9][0-9,]* buildings.*")
        expectation(for: counted, evaluatedWith: brooklyn); waitForExpectations(timeout: 10)
        brooklyn.tap()
        // the chip row appears inside the sheet once the selection lands; a tap
        // during the sheet's presentation animation can be dropped, so retry once
        let chip = app.buttons["Remove Brooklyn"]
        if !chip.waitForExistence(timeout: 3) { brooklyn.tap() }
        XCTAssertTrue(chip.waitForExistence(timeout: 5), "selecting Brooklyn did not add a chip")
        app.buttons["location-done"].tap()
        // back on the home screen the chip (with its remove button) sits in the field
        XCTAssertTrue(app.buttons["Remove Brooklyn"].waitForExistence(timeout: 5))
    }

    /// Application packet (2026-10-03): Profile -> packet; details typed
    /// once are saved and shown; the email button waits for documents.
    func testApplicationPacketSavesDetails() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "profile"]
        app.launch()
        let open = app.buttons["profile-packet"]
        let h = app.windows.firstMatch.frame.height
        for _ in 0..<6 where !open.isHittable || open.frame.maxY > h - 140 { app.swipeUp() }
        XCTAssertTrue(open.waitForExistence(timeout: 20), "Profile should offer the application packet")
        open.tap()
        XCTAssertTrue(app.staticTexts["Everything an agent asks for, in one place"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.buttons["packet-email"].isEnabled, "nothing to email before documents are added")
        app.buttons["packet-edit-profile"].tap()
        let first = app.textFields["packet-first"]
        XCTAssertTrue(first.waitForExistence(timeout: 5))
        first.tap(); first.typeText("Testy")
        app.buttons["packet-save"].tap()
        XCTAssertTrue(app.staticTexts["Testy"].waitForExistence(timeout: 5), "the saved name shows on the packet")
        // leave the phone as it was
        app.buttons["Delete my packet"].tap()
        app.buttons["Delete everything"].tap()
    }

    /// Under Search: one fixed "Sign up for lottery alerts" link, no rotating
    /// Plus row (owner, 2026-10-14). Signed out it opens the alerts sign-in.
    func testSearchShowsLotteryAlertsLink() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash"]
        app.launch()
        let link = app.buttons["search-lottery-alerts"]
        for _ in 0..<6 where !link.isHittable { app.swipeUp() }
        XCTAssertTrue(link.waitForExistence(timeout: 30), "Search shows the lottery alerts link")
        XCTAssertTrue(link.label.contains("Sign up for lottery alerts"))
        XCTAssertFalse(app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'plus-promo-'")).firstMatch.exists, "the rotating Plus row is gone")
        XCTAssertFalse(app.staticTexts["Have AI review your lease"].exists)
        link.tap()
        XCTAssertTrue(app.staticTexts["Sign in for lottery alerts"].waitForExistence(timeout: 10), "the link opens the alerts sign-in")
        app.buttons["Cancel"].tap()
    }

    /// Scrolls the results until a re-rental card's Help me apply sits clear
    /// of the tab bar and the floating pills.
    private func scrollToHelpMeApply() -> XCUIElement {
        let help = app.buttons["rerental-apply-help"].firstMatch
        // Clear of the floating tab bar: "hittable" under it still sends the
        // tap to the bar (failed once in the build 114 ship, passed on rerun).
        // Small drags until it sits mid-screen (a full swipe could carry it
        // past the top, then the loop swiped on forever).
        // …and clear of the floating Map / Lottery Alerts pills above it
        // (2026-10-13: the tap landed on Lottery Alerts and opened alerts).
        let h = app.windows.firstMatch.frame.height
        let pills = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'pill-'"))
        let pillTop = (0..<pills.count).map { pills.element(boundBy: $0).frame.minY }.filter { $0 > h / 2 }.min() ?? (h - 140)
        let floor = min(h - 140, pillTop - 12)
        let mid = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.6))
        for _ in 0..<30 {
            if help.exists && help.isHittable && help.frame.minY > 150 && help.frame.maxY < floor { break }
            let up = !(help.exists && help.frame.minY <= 150)
            mid.press(forDuration: 0.05, thenDragTo: mid.withOffset(CGVector(dx: 0, dy: up ? -320 : 220)))
        }
        return help
    }

    /// Every re-rental card offers Help me apply.
    func testRerentalOffersHelpMeApply() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results"]
        app.launch()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 60))
        let help = scrollToHelpMeApply()
        XCTAssertTrue(help.exists, "a re-rental card should offer Help me apply")
        help.tap()
        XCTAssertTrue(app.buttons["paywall-sign-in"].waitForExistence(timeout: 10), "without Plus, Help me apply opens the Plus page")
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'WHAT YOU TAPPED'")).firstMatch.exists, "the tapped feature leads the Plus page")
        app.buttons["paywall-sign-in"].tap()
        XCTAssertTrue(app.staticTexts["Sign in for Plus"].waitForExistence(timeout: 5), "sign-in opens over the Plus page")
    }

    /// Re-rentals ride along in the results feed: the 3rd tile is one, with a
    /// "Rerental" flag and a hand-off button, and it never displaces a building
    /// (the count headline is unchanged). The default route is Brooklyn, and
    /// the bundled featured.json has Brooklyn re-rentals, so this runs offline.
    func testThirdResultTileIsARerental() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results"]
        app.launch()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 60))
        let card = app.descendants(matching: .any)["rerental-card"].firstMatch
        // A lazy stack can report the tile before it is on screen; bring it
        // into view so the checks (and the screenshot) are of the real thing.
        for _ in 0..<8 where !card.isHittable { app.swipeUp() }
        XCTAssertTrue(card.isHittable, "no re-rental tile within the first screens of results")
        // ...and fully, for the screenshot: a hittable tile can be one row peeking in at the bottom.
        let from = app.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.8))
        from.press(forDuration: 0.05, thenDragTo: from.withOffset(CGVector(dx: 0, dy: -520)), withVelocity: .slow, thenHoldForDuration: 0.3)
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "rerental-tile"; shot.lifetime = .keepAlways; add(shot)
        XCTAssertTrue(app.descendants(matching: .any)["badge-rerental"].firstMatch.exists, "the tile is not flagged Rerental")
        XCTAssertTrue(app.descendants(matching: .any)["rerental-apply"].firstMatch.exists, "the tile has no hand-off button")
        // Just "Listed by <agent>", and no "First come, first served" (owner, 2026-10-20).
        let says = { [app] (s: String) in app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] %@", s)).count }
        XCTAssertEqual(says("marketing agent"), 0, "the listed-by line should be just the agent name")
        XCTAssertEqual(says("first come"), 0, "cards should not say first come, first served")
        // No "1 unit · ZIP 11238" row: the ZIP is in the address (owner, 2026-10-22).
        XCTAssertEqual(card.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'ZIP ' OR label CONTAINS ' · ZIP '")).count, 0, "the tile repeats its ZIP")
        // Order: exactly two building cards come before it.
        let all = app.descendants(matching: .any).matching(NSPredicate(format: "identifier == 'building-card' OR identifier == 'rerental-card'")).allElementsBoundByIndex
        if let i = all.firstIndex(where: { $0.identifier == "rerental-card" }) {
            XCTAssertEqual(i, 2, "the first re-rental must be the 3rd tile, found at \(i + 1)")
        }
    }

    /// Search keeps its place (owner, 2026-10-20): scroll the results, visit
    /// My Activity, come back, and the same building is on screen, not the top.
    func testSearchTabKeepsItsScrollAfterAnotherTab() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results"]
        app.launch()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 60))
        for _ in 0..<4 { app.swipeUp() }
        let onScreen = { [app] in
            app.descendants(matching: .any).matching(identifier: "card-address").allElementsBoundByIndex
                .filter { $0.isHittable }.map(\.label)
        }
        let before = onScreen()
        XCTAssertFalse(before.isEmpty, "a building should be on screen after scrolling")
        XCTAssertFalse(app.staticTexts["results-count"].isHittable, "scrolled past the top")
        app.buttons["tab-My Activity"].tap()
        XCTAssertTrue(app.buttons["tab-Search"].waitForExistence(timeout: 10))
        app.buttons["tab-Search"].tap()
        let card = app.descendants(matching: .any).matching(identifier: "card-address").firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 10))
        XCTAssertFalse(app.staticTexts["results-count"].isHittable, "back on Search, the list should not jump to the top")
        XCTAssertFalse(Set(before).isDisjoint(with: onScreen()), "the same buildings are still on screen: \(before) vs \(onScreen())")
    }

    /// The list follows the map: pan or zoom, and the count pill reads what
    /// is in view; "List" then opens on that area — no "Search this area" tap
    /// (removed 2026-09-16 at the owner's request, from a recording of the
    /// count sitting at 47,165 through a whole zoom into Clinton Hill).
    /// Zoomed out over the whole city the map must draw cluster bubbles.
    /// Build 108 drew none (bad cell coordinates) and every other map test
    /// still passed, because they only read the count pill (owner, 2026-10-03).
    func testZoomedOutMapShowsClusterBubbles() throws {
        app.terminate()
        // mapall: the unfiltered city, ~47k buildings — the grid path, not
        // the few-pins path a Brooklyn "available" search takes.
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "mapall"]
        app.launch()
        XCTAssertTrue(app.staticTexts["map-count"].waitForExistence(timeout: 30))
        let bubble = app.descendants(matching: .any)["cluster-bubble"].firstMatch
        XCTAssertTrue(bubble.waitForExistence(timeout: 15), "no cluster bubbles on the zoomed-out map")
        XCTAssertGreaterThan(app.descendants(matching: .any).matching(identifier: "cluster-bubble").count, 3)
    }

    func testMapViewportCarriesToList() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "map"]
        app.launch()
        let list = app.buttons["pill-List"]
        XCTAssertTrue(list.waitForExistence(timeout: 30))
        let count = app.staticTexts["map-count"]
        XCTAssertTrue(count.waitForExistence(timeout: 10))
        let before = count.label
        XCTAssertFalse(before.contains("in view"), "the pill must read the whole search before the map is moved: \(before)")
        sleep(3)   // let the initial fit settle so the pan reads as the user's
        let map = app.maps.firstMatch
        XCTAssertTrue(map.waitForExistence(timeout: 10))
        map.swipeUp()
        map.pinch(withScale: 3, velocity: 2)
        let followed = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label CONTAINS 'in view'"), object: count)
        XCTAssertEqual(XCTWaiter().wait(for: [followed], timeout: 8), .completed, "count did not follow the map: \(count.label)")
        XCTAssertNotEqual(count.label, before, "zooming into a few blocks must change the count")
        list.tap()
        let field = app.buttons["results-location-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        XCTAssertTrue(field.label.contains("Map area"), "list header was: \(field.label)")
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 10))
    }

    /// Both price bounds are set on one wheel now rather than typed into two
    /// text fields. Two things this pins that a build cannot: the boxes open
    /// the picker at all (they are Buttons, and a Button whose label is a
    /// styled box is exactly the shape that collapses into an untappable
    /// element), and Done writes BOTH wheels back — the min wheel and the max
    /// wheel are separate selections and only one of them used to exist.
    func testPriceWheelSetsBothBounds() throws {
        relaunchOnIncrements()
        let minBox = app.buttons["price-Minimum price"]
        let maxBox = app.buttons["price-Maximum price"]
        XCTAssertTrue(minBox.waitForExistence(timeout: 20))

        // Clear first. The home screen restores the last query from
        // @AppStorage, so a run that inherited $1,000-$3,000 from the previous
        // one would pass this test without the sheet writing anything.
        openPriceSheet(from: minBox)
        XCTAssertEqual(app.pickerWheels.count, 2, "expected a min and a max wheel")
        spin(app.pickerWheels.element(boundBy: 0), to: "Any")
        spin(app.pickerWheels.element(boundBy: 1), to: "No max")
        app.buttons["price-done"].tap()
        XCTAssertTrue(minBox.waitForExistence(timeout: 5))
        XCTAssertTrue(minBox.label.contains("No min"), "minimum box did not clear: \(minBox.label)")

        openPriceSheet(from: maxBox)
        spin(app.pickerWheels.element(boundBy: 0), to: "$1,000")
        spin(app.pickerWheels.element(boundBy: 1), to: "$3,000")
        app.buttons["price-done"].tap()

        XCTAssertTrue(minBox.waitForExistence(timeout: 5))
        XCTAssertTrue(minBox.label.contains("$1,000"), "minimum box read: \(minBox.label)")
        XCTAssertTrue(maxBox.label.contains("$3,000"), "maximum box read: \(maxBox.label)")
    }

    /// An inverted range comes back in order. Picking $3,000 as the floor and
    /// $1,000 as the ceiling is not a search that can match anything, and the
    /// sheet is the only place both numbers are visible at once, so it is where
    /// the two get put back the right way round.
    func testPriceWheelUninvertsTheRange() throws {
        relaunchOnIncrements()
        let minBox = app.buttons["price-Minimum price"]
        let maxBox = app.buttons["price-Maximum price"]
        XCTAssertTrue(minBox.waitForExistence(timeout: 20))
        openPriceSheet(from: minBox)
        spin(app.pickerWheels.element(boundBy: 0), to: "$3,000")
        spin(app.pickerWheels.element(boundBy: 1), to: "$1,000")
        app.buttons["price-done"].tap()
        XCTAssertTrue(minBox.waitForExistence(timeout: 5))
        XCTAssertTrue(minBox.label.contains("$1,000"), "minimum box read: \(minBox.label)")
        XCTAssertTrue(maxBox.label.contains("$3,000"), "maximum box read: \(maxBox.label)")
    }

    /// The Custom tab is the escape hatch for an exact figure. Only its
    /// presence is asserted — driving the number pad from a UI test is the
    /// flaky part of this suite, and the wheel path above already proves the
    /// sheet commits.
    func testPriceCustomTabOffersTypedEntry() throws {
        app.launch()
        let minBox = app.buttons["price-Minimum price"]
        XCTAssertTrue(minBox.waitForExistence(timeout: 20))
        minBox.tap()
        let mode = app.segmentedControls["price-mode"]
        XCTAssertTrue(mode.waitForExistence(timeout: 10))
        mode.buttons["Custom"].tap()
        XCTAssertTrue(app.textFields["price-custom-low"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["price-custom-high"].exists)
        // The way back to the wheel sits under the fields, because iPad's
        // floating number pad covers the Increments tab above them.
        XCTAssertTrue(app.buttons["price-use-wheel"].exists, "there must be a way back to the wheel")
        // Driving that round trip is iPhone-only. On an iPad simulator with the
        // minimized (floating) pad up, EVERY control in this sheet reads as not
        // hittable and even a coordinate tap is swallowed — the app is fine,
        // the touch never arrives (measured 2026-09-23). The mode switch itself
        // is covered on both platforms by openPriceSheet(), which opens the
        // sheet in Custom and taps back before each wheel test.
        guard app.windows.element(boundBy: 0).frame.width < 700 else { return }
        app.buttons["price-use-wheel"].tap()
        showIncrements()
        app.buttons["price-done"].tap()
    }

    /// Violations, complaints and the bedbug/rodent inspections are behind an
    /// account (2026-09-08, same as the site): signed out — which the
    /// simulator always is — the section offers sign-in and shows no tiles,
    /// and the button opens a sheet that previews them.
    func testViolationsGatedWhenSignedOut() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "detail"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 30))
        let gate = app.buttons["hpd-sign-in"]
        for _ in 0..<12 where !gate.exists { app.swipeUp() }
        XCTAssertTrue(gate.waitForExistence(timeout: 5), "signed out, the HPD section must offer sign-in")
        XCTAssertFalse(app.buttons["open-violations"].exists, "violations tile leaked past the gate")
        XCTAssertFalse(app.buttons["bedbug-inspections"].exists, "bedbug tile leaked past the gate")
        XCTAssertFalse(app.buttons["rodent-inspections"].exists, "rodent tile leaked past the gate")
        // The gate opens its own sign-in sheet previewing the records and one
        // Plus feature, not the Profile tab (owner, 2026-10-12).
        gate.tap()
        let box = app.descendants(matching: .any)["records-promise-box"]
        XCTAssertTrue(box.waitForExistence(timeout: 10), "the gate should open the records sign-in sheet")
        XCTAssertTrue(app.staticTexts["Bedbug filings the landlord made, year by year"].exists)
        XCTAssertTrue(app.staticTexts["Rat inspections from the Health Department"].exists)
        XCTAssertTrue(app.buttons["sign-in-apple"].exists, "Apple sign-in should be on the sheet")
        XCTAssertLessThan(box.frame.minY, app.buttons["sign-in-apple"].frame.minY, "the preview sits above Apple/Google")
        XCTAssertTrue(app.buttons["records-promise-plus"].exists, "one Plus feature with a Get Plus button")
        XCTAssertTrue(app.staticTexts["Plus: real-time lottery alerts, the minute one opens"].exists, "the Plus row sells real-time alerts")
        XCTAssertTrue(app.buttons["create-account-toggle"].isHittable, "No account? Create one must stay on screen")
        // Get Plus opens the Plus page led by real-time alerts.
        app.buttons["records-promise-plus"].tap()
        XCTAssertTrue(app.buttons["paywall-close"].waitForExistence(timeout: 10), "Get Plus opens the Plus page")
        XCTAssertTrue(app.staticTexts["WHAT YOU TAPPED"].exists, "the tapped feature leads the page")
        XCTAssertTrue(app.staticTexts["Real-time alerts"].exists)
    }

    /// "Sign in to see who runs this building" (owner, 2026-10-12) opens a
    /// sheet previewing the agent and owner, with the agent's phone number as
    /// the Plus row — not the Profile tab.
    func testAgentSignInPreviewsWhoRunsTheBuilding() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "detail"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 30))
        let gate = app.buttons["agent-sign-in"]
        let h = app.windows.firstMatch.frame.height
        for _ in 0..<14 where !gate.isHittable || gate.frame.maxY > h - 140 { app.swipeUp() }
        XCTAssertTrue(gate.waitForExistence(timeout: 5), "signed out, Managing agent offers sign-in")
        gate.tap()
        let box = app.descendants(matching: .any)["agent-promise-box"]
        XCTAssertTrue(box.waitForExistence(timeout: 10), "the sign-in sheet previews who runs the building")
        XCTAssertTrue(app.staticTexts["Who owns the building, and its head officer"].exists)
        XCTAssertTrue(app.buttons["agent-promise-plus"].exists, "the phone number is the Plus row, with Get Plus")
        XCTAssertTrue(app.buttons["sign-in-apple"].exists)
        XCTAssertLessThan(box.frame.minY, app.buttons["sign-in-apple"].frame.minY, "the preview sits above Apple/Google")
    }

    /// Under "Cafés nearby", at least three housing law firms from the
    /// building's own borough (owner, 2026-10-14); both rows sit above About.
    func testDetailListsBoroughHousingLawFirmsAboveAbout() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "detail"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 30))
        let firms = app.descendants(matching: .any)["housing-law-firms"].firstMatch
        for _ in 0..<20 where !firms.exists { app.swipeUp() }
        XCTAssertTrue(firms.waitForExistence(timeout: 5), "a New York building lists housing law firms")
        let title = app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'Housing law firms for '")).firstMatch
        XCTAssertTrue(title.exists)
        XCTAssertGreaterThanOrEqual(app.buttons.matching(identifier: "law-firm-card").count, 3, "at least three firms")
        let about = app.staticTexts["About"]
        for _ in 0..<6 where !about.exists { app.swipeUp() }
        XCTAssertTrue(about.exists)
        XCTAssertLessThan(title.frame.minY, about.frame.minY, "the firms come before About")
        let cafes = app.descendants(matching: .any)["nearby-cafes"].firstMatch
        if cafes.exists { XCTAssertLessThan(cafes.frame.minY, firms.frame.minY, "cafés come first, firms right under") }
    }

    /// New York cards swap Share for the building's pests, rotating
    /// ("Bedbugs (2)" / "Rats (1)"); signed out, a tap previews the records
    /// sign-in (owner, 2026-10-13).
    func testCardPestsButtonRotatesAndPreviewsRecordsSignIn() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results", "--card-pests", "bedbugs:2,rats:1"]
        app.launch()
        let pests = app.buttons["card-pests"].firstMatch
        XCTAssertTrue(pests.waitForExistence(timeout: 60))
        var seen = Set<String>()
        let end = Date().addingTimeInterval(8)
        while Date() < end && seen.count < 2 { seen.insert(pests.label); Thread.sleep(forTimeInterval: 0.5) }
        XCTAssertEqual(seen, ["Bedbugs (2)", "Rats (1)"], "the button rotates through the kinds found")
        let h = app.windows.firstMatch.frame.height
        for _ in 0..<6 where !pests.isHittable || pests.frame.maxY > h - 140 { app.swipeUp() }
        pests.tap()
        XCTAssertTrue(app.descendants(matching: .any)["records-promise-box"].waitForExistence(timeout: 10),
                      "signed out, the pests button opens the violations sign-in sheet")
    }

    /// Outside New York there are no HPD pests, owner phones or re-rental
    /// sizes: cards keep Share and the form has no Bedrooms (2026-10-13).
    func testOtherCitiesKeepShareAndHaveNoBedrooms() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--city", "la", "--route", "results", "--card-pests", "bedbugs:2"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["card-address"].firstMatch.waitForExistence(timeout: 90))
        XCTAssertTrue(app.buttons["Share"].firstMatch.exists, "LA cards keep Share")
        XCTAssertFalse(app.buttons["card-pests"].exists, "no pests button outside New York")
        XCTAssertFalse(app.buttons["card-owner-phone"].exists, "no Owner Phone outside New York")
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--city", "la"]
        app.launch()
        XCTAssertTrue(app.buttons["search-button"].waitForExistence(timeout: 90))
        // The search screen can draw New York's form for a moment before the
        // city switches (2026-10-25: failed twice on a Mac at load ~35), so
        // wait for the row to go rather than read it at once.
        XCTAssertTrue(app.descendants(matching: .any)["beds-row"].waitForNonExistence(timeout: 10), "no Bedrooms outside New York")
    }

    /// Turn off alerts sits in Profile only while alerts are on (2026-10-13).
    func testProfileHasNoTurnOffWithoutAlerts() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "profile"]
        app.launch()
        XCTAssertTrue(app.staticTexts["Profile"].waitForExistence(timeout: 20))
        for _ in 0..<4 { app.swipeUp() }
        XCTAssertFalse(app.buttons["profile-alerts-off"].exists, "nothing to turn off without alerts")
        // Signed out, "Sign in to set up" is a link to the alerts sign-in (owner, 2026-10-15).
        let signIn = app.buttons["profile-alerts-signin"]
        for _ in 0..<4 where !signIn.isHittable { app.swipeDown() }
        XCTAssertTrue(signIn.isHittable, "Alerts offers a sign-in link")
        signIn.tap()
        add(XCTAttachment(screenshot: app.screenshot()))
        XCTAssertTrue(app.descendants(matching: .any)["alerts-promise-box"].waitForExistence(timeout: 5), "it opens the alerts sign-in")
    }

    /// Profile › Language switches the app's language in place, no trip to
    /// Settings (owner, 2026-10-17), and "iPhone setting" switches it back.
    func testProfileLanguageSwitchesInApp() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "profile"]
        app.launch()
        XCTAssertTrue(app.staticTexts["Profile"].waitForExistence(timeout: 20))
        var row = app.buttons["profile-language"]
        for _ in 0..<8 where !row.isHittable { app.swipeUp() }
        XCTAssertTrue(row.isHittable, "Profile shows a Language row")
        XCTAssertTrue(row.label.contains("English"), "it names the app's language: \(row.label)")
        row.tap()
        XCTAssertTrue(app.buttons["Español"].waitForExistence(timeout: 5), "the menu lists Spanish")
        app.buttons["Español"].tap()
        XCTAssertTrue(app.staticTexts["Perfil"].waitForExistence(timeout: 10), "the app is in Spanish without a relaunch")
        add(XCTAttachment(screenshot: app.screenshot()))
        // Kept across launches.
        app.terminate()
        app.launch()
        XCTAssertTrue(app.staticTexts["Perfil"].waitForExistence(timeout: 20), "Spanish sticks after a relaunch")
        row = app.buttons["profile-language"]
        for _ in 0..<8 where !row.isHittable { app.swipeUp() }
        row.tap()
        XCTAssertTrue(app.buttons["Ajuste del iPhone"].waitForExistence(timeout: 5))
        app.buttons["Ajuste del iPhone"].tap()
        XCTAssertTrue(app.staticTexts["Profile"].waitForExistence(timeout: 10), "back to the phone's English")
    }

    /// With the phone (or Settings › Find A Crib › Language) set to Spanish,
    /// the tabs and a building page come up in Spanish — and the page's
    /// translated counts and plurals don't crash it.
    func testAppRunsInSpanish() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "detail", "-AppleLanguages", "(es)", "-AppleLocale", "es_US"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 30))
        for _ in 0..<6 { app.swipeUp() }
        add(XCTAttachment(screenshot: app.screenshot()))
        XCTAssertTrue(app.buttons["detail-menu"].exists || app.staticTexts.count > 0, "the building page stayed up")
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "-AppleLanguages", "(es)", "-AppleLocale", "es_US"]
        app.launch()
        let search = app.buttons["tab-Search"]
        XCTAssertTrue(search.waitForExistence(timeout: 30))
        XCTAssertNotEqual(search.label, "Search", "the Search tab is translated")
        XCTAssertFalse(app.buttons["tab-Lotteries"].label == "Lotteries", "the Lotteries tab is translated")
        add(XCTAttachment(screenshot: app.screenshot()))
    }

    /// A building with no pests cited shows "Owner Phone"; signed out, a
    /// tap previews the agent sign-in (owner, 2026-10-13).
    func testCardOwnerPhoneButtonPreviewsAgentSignIn() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results", "--card-pests", "none"]
        app.launch()
        let phone = app.buttons["card-owner-phone"].firstMatch
        XCTAssertTrue(phone.waitForExistence(timeout: 60))
        XCTAssertEqual(phone.label, "Owner Phone")
        let h = app.windows.firstMatch.frame.height
        for _ in 0..<6 where !phone.isHittable || phone.frame.maxY > h - 140 { app.swipeUp() }
        phone.tap()
        XCTAssertTrue(app.descendants(matching: .any)["agent-promise-box"].waitForExistence(timeout: 10),
                      "signed out, Owner Phone opens the agent sign-in sheet")
    }

    /// A Plus member's Owner Phone tap opens the building on its Managing
    /// agent section, phone number in view (owner, 2026-10-17).
    /// `--route detail-agent` lands exactly where that tap does; the tap
    /// itself needs a real Plus session, which UI tests don't have.
    func testOwnerPhoneOpensBuildingAtManagingAgent() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "detail-agent"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 30))
        let agent = app.staticTexts["Managing agent"].firstMatch
        XCTAssertTrue(agent.waitForExistence(timeout: 10))
        let h = app.windows.firstMatch.frame.height
        let onTop = NSPredicate { _, _ in agent.isHittable && agent.frame.minY < h * 0.35 }
        wait(for: [XCTNSPredicateExpectation(predicate: onTop, object: nil)], timeout: 10)
        XCTAssertFalse(app.staticTexts["Violations & inspections"].isHittable, "the page scrolled past the sections above")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "owner-phone-agent"; shot.lifetime = .keepAlways; add(shot)
    }

    /// Google's ads live in the feed, in the re-rental slots (Ads.swift,
    /// owner 2026-09-25): no banner under the app, and the 3rd tile is an ad
    /// or — when none was loaded in time — the re-rental, never a blank.
    /// Outside New York there are no re-rentals, so the same feed slots
    /// carry Google's ads (owner, 2026-09-26) — and never a blank card.
    func testOtherCitiesGetAdsInTheRerentalSlots() throws {
        app.terminate()
        // --route results opens LA's unfiltered list (LaunchArgs), so a search
        // form left filled by an earlier test (e.g. "BK, $1k–3k") cannot
        // empty it. LA downloads first, which also gives the ad pool time.
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--ads-demo", "--city", "la", "--route", "results"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["card-address"].firstMatch.waitForExistence(timeout: 90))
        let ad = app.descendants(matching: .any)["feed-ad"].firstMatch
        for _ in 0..<5 where !ad.exists { app.swipeUp() }
        XCTAssertTrue(ad.waitForExistence(timeout: 10), "an LA search should carry an ad in the re-rental slot")
        XCTAssertFalse(app.descendants(matching: .any)["rerental-card"].firstMatch.exists, "no New York re-rentals in LA")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "la-feed-ad"; shot.lifetime = .keepAlways; add(shot)
    }

    func testFeedAdsTakeTheRerentalSlotNotTheBottom() throws {
        app.terminate()
        // --route results, not the home form: the form keeps whatever an
        // earlier test typed into it, and a leftover filter can empty the list.
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--ads-demo", "--route", "results"]
        app.launch()
        XCTAssertTrue(app.descendants(matching: .any)["card-address"].firstMatch.waitForExistence(timeout: 60))
        let ad = app.descendants(matching: .any)["feed-ad"].firstMatch
        let rerental = app.descendants(matching: .any)["rerental-card"].firstMatch
        for _ in 0..<4 where !ad.exists && !rerental.exists { app.swipeUp() }
        XCTAssertTrue(ad.waitForExistence(timeout: 10) || rerental.exists, "the re-rental slot should hold an ad or the re-rental")
        let slotCard = ad.exists ? ad : rerental
        for _ in 0..<4 where slotCard.exists && slotCard.frame.minY > app.frame.height * 0.35 { app.swipeUp(velocity: .slow) }
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "feed-slot"; shot.lifetime = .keepAlways; add(shot)
        XCTAssertFalse(app.descendants(matching: .any)["ad.slot"].exists, "the bottom banner is gone")
        XCTAssertTrue(app.buttons["Profile"].isHittable, "the tab bar stays tappable")
    }

    /// Outside New York the app must not offer New York's things: the
    /// Lotteries tab (Housing Connect + HPD re-rentals, by borough) is gone,
    /// and the map opens on THAT city — it used to fall back to New York, so
    /// LA's map opened on Manhattan (owner, 2026-09-19).
    func testOtherCitiesListTheirOwnLotteriesAndOpenTheirOwnMap() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--city", "la", "--route", "map"]
        app.launch()
        // LA downloads on first selection, so wait for ITS count to appear
        // rather than for a fixed time.
        let laCount = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS '67,5'")).firstMatch
        XCTAssertTrue(laCount.waitForExistence(timeout: 90), "the LA map never finished loading LA")
        // LA has its own openings since 2026-09-24 (Access Housing LA), so the
        // tab is back — listing LA's, never New York's.
        XCTAssertTrue(app.buttons["tab-Lotteries"].exists, "LA lists Access Housing LA's openings")
        XCTAssertFalse(app.buttons["tab-Your Crib"].exists, "Your Crib reads New York's 311 and NYPD data; it must not show in LA")
        // The count pill is the map's own: it says how many of THIS city's
        // buildings the map is showing, so 67,5xx means LA's data on LA's map.
        // (The Search screen underneath still holds its own tiles, so the whole
        // hierarchy cannot be searched for New York place names.)
        XCTAssertTrue(app.descendants(matching: .any)["map-count"].firstMatch.waitForExistence(timeout: 20),
                      "the map should show its count")
        XCTAssertTrue((app.descendants(matching: .any)["map-count"].firstMatch.label).contains("67,5"),
                      "the map is counting another city: \(app.descendants(matching: .any)["map-count"].firstMatch.label)")
        // LA's Lotteries tab: Access Housing LA's openings, no sign-up screen.
        app.buttons["tab-Lotteries"].tap()
        let opening = app.descendants(matching: .any)["opening-card"].firstMatch
        XCTAssertTrue(opening.waitForExistence(timeout: 20) || app.descendants(matching: .any)["lotteries-empty"].firstMatch.exists,
                      "LA's tab should list openings or say none are open")
        XCTAssertFalse(app.buttons["lotteries-signup"].exists, "no New York alert sign-up outside New York")
        if opening.exists {
            XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS 'Apply on Access Housing LA'")).firstMatch.exists)
            XCTAssertTrue(app.descendants(matching: .any)["lottery-photo"].firstMatch.waitForExistence(timeout: 5),
                          "LA listings show the agency's photo")
            // Filters (owner, 2026-09-24): a way-in chip narrows the list and
            // says so in the count; Clear filters brings it all back.
            let count = app.staticTexts["openings-count"]
            XCTAssertTrue(count.waitForExistence(timeout: 5))
            let lottery = app.buttons["openings-kind-lottery"]
            XCTAssertTrue(lottery.waitForExistence(timeout: 5), "LA lists lotteries and waitlists, so both chips show")
            XCTAssertTrue(app.buttons["segment-4+"].exists, "the Beds strip sits under Rent/Buy")
            XCTAssertTrue(app.buttons["openings-area"].exists, "LA's listings span neighborhoods, so the Area menu shows")
            lottery.tap()
            XCTAssertTrue(count.label.contains(" of "), "filtered, the count says how many of how many: \(count.label)")
            app.buttons["openings-clear"].tap()
            XCTAssertFalse(count.label.contains(" of "), "Clear filters shows every listing again: \(count.label)")
            let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "la-openings-filters"; shot.lifetime = .keepAlways; add(shot)
        }
    }

    /// The four income-restricted cities (owner, 2026-09-24: "lets add the
    /// four cities - lets only add cities"). Picking Chicago loads its own
    /// buildings, and a building shows its units and who to call. Miami-Dade's
    /// Lotteries tab lists the buildings leasing now.
    func testIncomeRestrictedCitiesLoadTheirBuildingsAndMiamiLeasing() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash"]
        app.launch()
        // Picking a city is remembered across launches, and the tests after
        // this one expect New York: put it back even if this test fails.
        addTeardownBlock { [app] in
            guard let app else { return }
            app.terminate()
            app.launchArguments = ["--no-launch-prompt", "--no-launch-splash"]
            app.launch()
            let field = app.buttons["city-field"]
            guard field.waitForExistence(timeout: 20) else { return }
            field.tap()
            let nyc = app.buttons["city-nyc"]
            if nyc.waitForExistence(timeout: 5) { nyc.tap() }
            _ = app.buttons["search-button"].waitForExistence(timeout: 30)
        }
        let cityField = app.buttons["city-field"]
        XCTAssertTrue(cityField.waitForExistence(timeout: 20))
        cityField.tap()
        let chi = app.buttons["city-chi"]
        XCTAssertTrue(chi.waitForExistence(timeout: 5), "Chicago is in the picker")
        XCTAssertFalse(app.buttons["city-st-nj"].exists, "no state maps (owner: cities only)")
        for id in ["city-mia", "city-atl", "city-phl"] { XCTAssertTrue(app.buttons[id].exists, "\(id) is in the picker") }
        chi.tap()
        let go = app.buttons["search-button"]
        XCTAssertTrue(go.waitForExistence(timeout: 20))
        // Chicago downloads on first selection; wait for its count, not a fixed time.
        expectation(for: NSPredicate(format: "label CONTAINS 'Search' AND NOT (label CONTAINS 'Search 0 ')"), evaluatedWith: go)
        waitForExpectations(timeout: 90)
        XCTAssertFalse(app.buttons["tab-Lotteries"].exists, "Chicago has no lottery feed, so no Lotteries tab")
        XCTAssertFalse(app.buttons["tab-Your Crib"].exists, "Your Crib is New York only")
        let bar = app.buttons["tab-Search"]
        for _ in 0..<4 where !go.isHittable || (bar.exists && go.frame.maxY > bar.frame.minY - 8) { app.swipeUp() }
        go.tap()
        let card = app.buttons["card-address"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 20), "results should list Chicago buildings")
        card.tap()
        let block = app.descendants(matching: .any)["affordable-block"].firstMatch
        for _ in 0..<5 where !block.exists { app.swipeUp() }
        XCTAssertTrue(block.waitForExistence(timeout: 10), "a Chicago building shows its income-restricted record")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "chi-building"; shot.lifetime = .keepAlways; add(shot)
        // Miami-Dade (not persisted: --city): its Lotteries tab lists lease-ups.
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--city", "mia"]
        app.launch()
        let lotteriesTab = app.buttons["tab-Lotteries"]
        XCTAssertTrue(lotteriesTab.waitForExistence(timeout: 90), "Miami-Dade lists buildings leasing now")
        lotteriesTab.tap()
        let opening = app.descendants(matching: .any)["opening-card"].firstMatch
        XCTAssertTrue(opening.waitForExistence(timeout: 20) || app.descendants(matching: .any)["lotteries-empty"].firstMatch.exists)
        if opening.exists {
            XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS 'View availability'")).firstMatch.exists,
                          "lease-ups open the building's own leasing site, not a search")
        }
        let tabShot = XCTAttachment(screenshot: app.screenshot()); tabShot.name = "mia-leasing"; tabShot.lifetime = .keepAlways; add(tabShot)
    }

    /// Each income-restricted city's results (owner, 2026-09-24, with a
    /// Philadelphia screenshot): its own landmarks over the list, its own badge,
    /// and none of New York's words — not "Rent stabilized", not HPD.
    func testNewCitiesResultsUseTheirOwnWordsAndLandmarks() throws {
        for id in ["chi", "mia", "atl", "phl"] {
            app.terminate()
            app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--city", id, "--route", "results"]
            app.launch()
            let count = app.staticTexts["results-count"]
            XCTAssertTrue(count.waitForExistence(timeout: 90), "\(id): results should open")
            // The headline is the count of buildings ("69 buildings", owner
            // 2026-10-24; a bare number from 10-17); the city's own word is
            // on each card's badge.
            expectation(for: NSPredicate(format: "label MATCHES '^[0-9][0-9,]* buildings?$'"), evaluatedWith: count)
            waitForExpectations(timeout: 60)
            XCTAssertTrue(app.buttons["card-address"].firstMatch.waitForExistence(timeout: 20), "\(id): cards should load")
            XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label == 'Income-restricted' OR label == 'Leasing now'")).firstMatch.waitForExistence(timeout: 10),
                          "\(id): cards carry the city's own badge")
            XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'HPD'")).firstMatch.exists, "\(id): no HPD wording")
            XCTAssertFalse(app.staticTexts["Rent stabilized"].exists, "\(id): no New York badge")
            let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "results-\(id)"; shot.lifetime = .keepAlways; add(shot)
        }
    }

    /// The banner is the wordmark, and it is decoration: the owner had a tap
    /// open Look Around for a day and took it back out (2026-09-20), and a
    /// re-rental photo with a borough badge for half a day on 2026-09-23. So
    /// it must not be a button and must carry no photos.
    func testHeroBannerIsDecorationOnly() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash"]
        app.launch()
        let banner = app.descendants(matching: .any)["hero-banner"].firstMatch
        XCTAssertTrue(banner.waitForExistence(timeout: 20), "the banner should be there")
        XCTAssertTrue(banner.label.contains("Find A Crib"), "the banner carries the wordmark: \(banner.label)")
        XCTAssertFalse(app.buttons["hero-banner"].exists, "the banner is not a button")
        XCTAssertFalse(app.descendants(matching: .any)["hero-rerental"].firstMatch.exists,
                       "no re-rental photo banner (owner, 2026-09-23)")
        XCTAssertFalse(app.descendants(matching: .any)["hero-tile"].firstMatch.exists, "no street photos in the banner (owner, 2026-09-22)")
        banner.tap()
        XCTAssertFalse(app.buttons["hero-lookaround-close"].waitForExistence(timeout: 4), "tapping must open nothing")
        XCTAssertTrue(app.buttons["city-field"].exists, "and leaves Search where it was")
        XCTAssertFalse(banner.label.contains("Halloween"), "an everyday banner carries no holiday: \(banner.label)")
        // On a holiday it wears the day (owner, 2026-10-25): the splash's
        // field and the day's line under the city line.
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--holiday", "halloween"]
        app.launch()
        let dressed = app.descendants(matching: .any)["hero-banner"].firstMatch
        XCTAssertTrue(dressed.waitForExistence(timeout: 20))
        XCTAssertTrue(dressed.label.contains("Halloween"), "the banner names the holiday: \(dressed.label)")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "hero-halloween"; shot.lifetime = .keepAlways; add(shot)
    }

    /// The app's Plus paywall: Plus is the AI features, real-time alerts and
    /// agent phone numbers (plus no ads) — and NO invite-a-friend route
    /// (App Review 3.1.1; referrals live on the website).
    func testPaywallAIPerksNoInvite() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--paywall"]
        app.launch()
        XCTAssertTrue(app.staticTexts["Search in plain words"].waitForExistence(timeout: 15), "the Plus paywall opens with its perks")
        // Broker fee check, Agent phone numbers and Lease review promoted
        // (owner, 2026-10-12), under the header "Your apartment hunt, with AI".
        XCTAssertTrue(app.staticTexts["Your apartment hunt, with AI"].exists, "the paywall header")
        for perk in ["Real-time alerts", "Broker fee check", "Agent phone numbers", "Lease review", "Help me apply", "No ads"] {
            XCTAssertTrue(app.staticTexts[perk].exists, "paywall perk missing: \(perk)")
        }
        // Scope to the paywall sheet: Profile (behind it) has its own "Saved
        // searches" row, which is not a paywall perk (build 104).
        let sheet = app.scrollViews.containing(.staticText, identifier: "Search in plain words").firstMatch
        XCTAssertTrue(sheet.exists, "the paywall's scroll view")
        for gone in ["Is this rent fair?", "Landlord report card", "Ask about this building", "Bedbug records", "Rodent records", "Lottery alerts", "Re-rental alerts", "Saved searches", "Landlord research", "Folders", "Your lotteries & re-rentals",
                     "Listings, rents and applications — read for you, in plain words."] {
            XCTAssertFalse(sheet.staticTexts[gone].exists, "unlisted perk on the paywall: \(gone)")
        }
        XCTAssertFalse(app.buttons["paywall-refer"].exists, "no in-app invite-a-friend button (App Review 3.1.1)")
        XCTAssertFalse(sheet.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] 'free'")).firstMatch.exists,
                       "no 'free' wording on the paywall")
    }

    /// The Lotteries tab LISTS for everyone (owner, 2026-09-30: "people should
    /// be able to see lotteries and rerentals"). Not subscribed, it shows all
    /// five boroughs with a "Turn on alerts" banner (alerts were Plus for new
    /// sign-ups), NO sheet opens by itself, and the banner opens sign-in when
    /// signed out. --lotteries-demo stands in for a subscriber to all five.
    /// Beds lives in the Filter sheet (owner, 2026-10-17: off the tab, and
    /// "Edit boroughs" renamed Filter). Picking 1 bed narrows Re-rentals —
    /// listings with no size leave with no "show them" row — and the button
    /// counts it: "Filter (1)".
    func testLotteriesFilterHoldsBeds() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "lotteries", "--lotteries-demo", "--plus-demo"]
        app.launch()
        let pane = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Re-rentals'")).firstMatch
        XCTAssertTrue(pane.waitForExistence(timeout: 30))
        pane.tap()
        XCTAssertFalse(app.buttons["segment-1"].exists, "no Beds strip on the tab")
        let filter = app.buttons["rerentals-filter"]
        XCTAssertTrue(filter.waitForExistence(timeout: 10), "the Filter button sits by the count")
        filter.tap()
        let one = app.buttons["segment-1"]
        XCTAssertTrue(one.waitForExistence(timeout: 5), "Beds is in the Filter sheet")
        // Beds is remembered between launches: start from none picked.
        for label in ["Studio", "1", "2", "3", "4+"] {
            let seg = app.buttons["segment-\(label)"]
            if seg.exists && seg.isSelected { seg.tap() }
        }
        one.tap()
        app.buttons["Close"].tap()
        XCTAssertTrue(app.buttons["Filter (1)"].waitForExistence(timeout: 5), "the button counts the filter")
        XCTAssertFalse(app.buttons["rerentals-unsized"].exists, "no show-them row")
        XCTAssertFalse(app.buttons["qualify-out-of-range"].exists, "no show-them row")
        app.buttons["rerentals-filter"].tap()
        XCTAssertTrue(app.buttons["segment-1"].waitForExistence(timeout: 5))
        app.buttons["segment-1"].tap()   // leave Beds as it was
        app.buttons["Close"].tap()
    }

    /// Broker fee check and Lease review on the iPhone (owner, 2026-10-12: "we
    /// need broker fee check and lease review on mobile"): both open from
    /// Profile with their forms; the Lease review button waits for a lease.
    func testRenterToolsOpenFromProfile() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "profile"]
        app.launch()
        let broker = app.buttons["profile-broker-fee"]
        let h = app.windows.firstMatch.frame.height
        // Clear of the floating tab bar before tapping (as the packet test does).
        for _ in 0..<6 where !broker.isHittable || broker.frame.maxY > h - 140 { app.swipeUp() }
        XCTAssertTrue(broker.waitForExistence(timeout: 20), "Profile lists Broker fee check")
        broker.tap()
        // The form is a lazy list: check what is on its first screen.
        XCTAssertTrue(app.navigationBars["Broker fee check"].waitForExistence(timeout: 10), "the broker fee form opens")
        XCTAssertTrue(app.textFields["broker-rent"].waitForExistence(timeout: 5), "with the amounts to check")
        app.buttons["Close"].tap()
        let lease = app.buttons["profile-lease-review"]
        for _ in 0..<4 where !lease.isHittable || lease.frame.maxY > h - 140 { app.swipeUp() }
        XCTAssertTrue(lease.waitForExistence(timeout: 10), "Profile lists Lease review")
        lease.tap()
        XCTAssertTrue(app.navigationBars["Lease review"].waitForExistence(timeout: 10), "the lease review form opens")
        XCTAssertTrue(app.buttons["lease-pick"].exists, "with a PDF picker")
        let run = app.buttons["lease-run"]
        for _ in 0..<3 where !run.exists { app.swipeUp() }
        XCTAssertTrue(run.exists && !run.isEnabled, "no review until there is a lease to read")
        app.buttons["Close"].tap()
    }

    /// Already have a place? (owner, 2026-10-13): Profile lists the four
    /// renter tools. Signed out, the rights cards load (they're public) and
    /// writing a repair letter asks for an account first; the rent check
    /// waits for both rents; the Renewal coach opens its form.
    func testHomeToolsOpenFromProfileSignedOut() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "profile"]
        app.launch()
        let h = app.windows.firstMatch.frame.height
        func open(_ id: String) {
            let b = app.buttons[id]
            for _ in 0..<8 where !b.isHittable || b.frame.maxY > h - 140 { app.swipeUp() }
            XCTAssertTrue(b.waitForExistence(timeout: 20), "Profile lists \(id)")
            b.tap()
        }
        open("profile-rights")
        XCTAssertTrue(app.navigationBars["Know your rights"].waitForExistence(timeout: 10), "Know your rights opens")
        let card = app.descendants(matching: .any)["rights-card-repairs"]
        for _ in 0..<3 where !card.exists { app.swipeUp() }
        XCTAssertTrue(card.waitForExistence(timeout: 20), "signed out, the rights cards load")
        app.buttons["Close"].tap()
        open("profile-repair")
        XCTAssertTrue(app.navigationBars["Get a repair made"].waitForExistence(timeout: 10), "Get a repair made opens")
        let run = app.buttons["repair-run"]
        for _ in 0..<3 where !run.isHittable { app.swipeUp() }
        run.tap()
        XCTAssertTrue(app.textFields["email-field"].waitForExistence(timeout: 10), "signed out, writing a letter asks for an account")
        app.terminate(); app.launch()
        open("profile-rent-increase")
        XCTAssertTrue(app.navigationBars["Rent increase check"].waitForExistence(timeout: 10), "the rent increase check opens")
        let check = app.buttons["rentup-run"]
        for _ in 0..<3 where !check.exists { app.swipeUp() }
        XCTAssertTrue(check.exists && !check.isEnabled, "no check until both rents are in")
        app.buttons["Close"].tap()
        open("profile-renewal")
        XCTAssertTrue(app.navigationBars["Renewal coach"].waitForExistence(timeout: 10), "the Renewal coach opens")
        app.buttons["Close"].tap()
    }

    /// Deep links (2026-10-13) — what In-App Events, the widget and Siri use:
    /// findacrib://tool/rights opens Know your rights on Profile, and
    /// findacrib://lotteries lands on the Lotteries tab, whose cards offer
    /// "Add deadline to Calendar".
    func testDeepLinksOpenToolsAndLotteries() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash"]
        app.launch()
        XCTAssertTrue(app.buttons["tab-Search"].waitForExistence(timeout: 30) || app.wait(for: .runningForeground, timeout: 5))
        app.open(URL(string: "findacrib://tool/rights")!)
        XCTAssertTrue(app.navigationBars["Know your rights"].waitForExistence(timeout: 20), "findacrib://tool/rights opens Know your rights")
        app.buttons["Close"].tap()
        app.open(URL(string: "findacrib://lotteries")!)
        let card = app.otherElements["lottery-card"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 30), "findacrib://lotteries lands on the Lotteries tab")
        let cal = app.buttons["lottery-calendar"].firstMatch
        for _ in 0..<3 where !cal.exists { app.swipeUp() }
        XCTAssertTrue(cal.exists, "a lottery card offers Add deadline to Calendar")
        // Centred under Apply (owner, 2026-10-14).
        let text = cal.staticTexts["Add deadline to Calendar"].exists ? cal.staticTexts["Add deadline to Calendar"].frame : cal.frame
        // Against its own card's full-width Apply button, not the screen: on
        // iPad the cards sit in columns (ship 133 failed comparing 213 to 417).
        let applies = app.buttons.matching(NSPredicate(format: "label CONTAINS 'Apply on Housing Connect'")).allElementsBoundByIndex
            .map(\.frame).filter { $0.maxY <= cal.frame.minY + 4 && $0.minX - 1 <= text.midX && text.midX <= $0.maxX + 1 }
        let apply = try XCTUnwrap(applies.max { $0.maxY < $1.maxY }, "Apply sits above the calendar button")
        XCTAssertEqual(text.midX, apply.midX, accuracy: 12, "the calendar button sits centred under Apply")
    }

    /// A paying member with alerts on (--plus-demo + --lotteries-demo): the
    /// Lotteries tab shows no alerts box at all (owner, 2026-10-13) — no
    /// Turn on, no upsell, no manage card. Edit boroughs stays in the header,
    /// and Turn off lives in Profile, asking first.
    func testPlusSubscriberManagesAlertsWithNoUpsell() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "lotteries", "--lotteries-demo", "--plus-demo", "--reset-rt-dismissed"]
        app.launch()
        XCTAssertTrue(app.buttons["lotteries-edit"].waitForExistence(timeout: 30), "Filter stays in the header")
        XCTAssertFalse(app.descendants(matching: .any)["lotteries-alerts-banner"].exists, "no alerts box once alerts are on")
        XCTAssertFalse(app.staticTexts["Your alerts are on"].exists)
        XCTAssertFalse(app.buttons["lotteries-signup"].exists, "no Turn on alerts for someone already subscribed")
        XCTAssertFalse(app.buttons["realtime-upsell"].exists, "nothing to sell a paying member")
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'Upgrade to Plus'")).firstMatch.exists)
        app.buttons["tab-Profile"].tap()
        let off = app.buttons["profile-alerts-off"]
        let h = app.windows.firstMatch.frame.height
        for _ in 0..<6 where !off.isHittable || off.frame.maxY > h - 140 { app.swipeUp() }
        XCTAssertTrue(off.waitForExistence(timeout: 10), "Turn off alerts lives in Profile")
        off.tap()
        let keep = app.buttons["Keep them"]
        XCTAssertTrue(keep.waitForExistence(timeout: 5), "turning off asks first")
        keep.tap()
        XCTAssertTrue(off.exists, "and Keep them leaves alerts on")
    }

    /// Real-time alerts are Plus (owner, 2026-10-06). A subscriber without Plus
    /// (--lotteries-demo) sees the real-time alerts offer instead
    /// of the alerts prompt; it opens the Plus page on real-time alerts, and
    /// its ✕ hides it for good.
    func testSubscriberSeesRealtimeUpsellAndCanDismissIt() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "lotteries", "--lotteries-demo", "--reset-rt-dismissed"]
        app.launch()
        let upsell = app.buttons["realtime-upsell"]
        XCTAssertTrue(upsell.waitForExistence(timeout: 30), "a subscriber without Plus should be offered real-time alerts")
        XCTAssertFalse(app.buttons["lotteries-signup"].exists, "not the sign-up prompt — they already get alerts")
        upsell.tap()
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'WHAT YOU TAPPED'")).firstMatch.waitForExistence(timeout: 10))
        XCTAssertTrue(app.staticTexts["Real-time alerts"].exists, "the Plus page leads with real-time alerts")
        app.buttons["paywall-close"].tap()
        app.buttons["realtime-upsell-dismiss"].tap()
        XCTAssertFalse(app.buttons["realtime-upsell"].waitForExistence(timeout: 2), "dismissed, it goes away")
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "lotteries", "--lotteries-demo"]
        app.launch()
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Re-rentals'")).firstMatch.waitForExistence(timeout: 30))
        XCTAssertFalse(app.buttons["realtime-upsell"].exists, "and it stays gone after a relaunch")
    }

    func testLotteriesTabSignupScreenThenListsForSubscribers() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash"]
        app.launch()
        let tab = app.buttons["tab-Lotteries"]
        XCTAssertTrue(tab.waitForExistence(timeout: 20), "the Lotteries tab shows for everyone")
        tab.tap()
        let signup = app.buttons["lotteries-signup"]
        XCTAssertTrue(signup.waitForExistence(timeout: 10), "not subscribed: the alerts banner sits above the list")
        XCTAssertFalse(app.buttons["Cancel"].waitForExistence(timeout: 3), "no sheet may open by itself")
        let anyCard = app.descendants(matching: .any)["lottery-card"].firstMatch
        XCTAssertTrue(anyCard.waitForExistence(timeout: 15) || app.descendants(matching: .any)["lotteries-empty"].firstMatch.exists,
                      "not subscribed: the tab still lists lotteries (or says none are open)")
        XCTAssertTrue(app.staticTexts["All five boroughs"].exists, "a non-subscriber sees all five boroughs")
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS[c] 'free'")).firstMatch.exists,
                       "nothing on the tab may call alerts free (owner, 2026-09-30)")
        signup.tap()
        let cancel = app.buttons["Cancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 10), "signed out, the button opens sign-in first")
        XCTAssertTrue(app.buttons["sign-in-apple"].exists, "sign-in for alerts must offer Apple")
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier CONTAINS 'google'")).firstMatch.exists, "…and Google")
        XCTAssertFalse(app.keyboards.firstMatch.exists, "no keyboard until they choose email")
        // The alerts box sits above Apple/Google, and adding it must not push
        // the email links off the first screen (owner, 2026-10-11).
        let promise = app.descendants(matching: .any)["alerts-promise-box"].firstMatch
        XCTAssertTrue(promise.exists, "sign-in for alerts explains what the alerts are")
        XCTAssertLessThan(promise.frame.minY, app.buttons["sign-in-apple"].frame.minY, "the box goes above Apple")
        XCTAssertTrue(app.buttons["create-account-toggle"].isHittable, "No account? Create one is on screen")
        XCTAssertTrue(app.buttons["forgot-password"].isHittable, "Forgot password? is on screen")
        XCTAssertTrue(app.staticTexts["In-app notifications and emails at 8 AM daily"].exists, "not \"push\" (owner, 2026-10-11)")
        // The Plus row's small button opens the Plus page over sign-in, and
        // closing it comes back to sign-in.
        let getPlus = app.buttons["alerts-promise-plus"]
        XCTAssertTrue(getPlus.isHittable, "Get Plus sits on the Plus row")
        getPlus.tap()
        XCTAssertTrue(app.buttons["paywall-sign-in"].waitForExistence(timeout: 10), "Get Plus opens the Plus page")
        app.buttons["paywall-close"].tap()
        XCTAssertTrue(getPlus.waitForExistence(timeout: 5), "closing Plus returns to sign-in")
        // Tapping Email brings Password into view and Sign in rides on the
        // keyboard; tapping Password keeps Sign in there (owner, 2026-10-11,
        // again 2026-10-14 with the Passwords bar making the keyboard taller).
        app.textFields["email-field"].tap()
        let keyboard = app.keyboards.firstMatch
        XCTAssertTrue(keyboard.waitForExistence(timeout: 5))
        let password = app.secureTextFields["password-field"], submit = app.buttons["email-submit"]
        // Email and Password both show, wholly above the Sign in bar: the bar
        // covered Password on the records sheet (owner, 2026-10-15).
        let email = app.textFields["email-field"]
        let above = NSPredicate { _, _ in password.isHittable && submit.isHittable && submit.frame.maxY <= keyboard.frame.minY + 1
            && password.frame.maxY <= submit.frame.minY + 1 && email.frame.minY >= 0 && email.isHittable }
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: above, object: nil)], timeout: 5), .completed,
                       "Password and Sign in sit above the keyboard")
        password.tap()
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: above, object: nil)], timeout: 5), .completed,
                       "with Password focused, Sign in still sits above the keyboard")
        XCTAssertEqual(app.buttons.matching(identifier: "email-submit").count, 1, "one Sign in button, not two")
        // A tap outside any field closes the keyboard (owner, 2026-10-14).
        app.staticTexts["or continue with email"].tap()
        XCTAssertEqual(XCTWaiter().wait(for: [XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: keyboard)], timeout: 5),
                       .completed, "tapping outside the fields closes the keyboard")
        XCTAssertTrue(submit.waitForExistence(timeout: 3), "Sign in is back in the form")
        cancel.tap()
        XCTAssertTrue(signup.waitForExistence(timeout: 5))
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--lotteries-demo"]
        app.launch()
        XCTAssertTrue(tab.waitForExistence(timeout: 20))
        XCTAssertTrue(app.buttons["tab-My Activity"].isHittable && app.buttons["tab-Profile"].isHittable
                      && app.buttons["tab-Your Crib"].isHittable, "all five tabs must fit")
        tab.tap()
        let card = app.descendants(matching: .any)["lottery-card"].firstMatch
        let empty = app.descendants(matching: .any)["lotteries-empty"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 15) || empty.exists, "the tab should list lotteries or say none are open")
        XCTAssertFalse(app.buttons["lotteries-signup"].exists, "a subscriber sees no alerts banner")
        if card.exists {
            XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS 'Apply on Housing Connect'")).firstMatch.exists)
            // A photo of the building (owner, 2026-09-25: "are we not able to get images for these?")
            XCTAssertTrue(app.descendants(matching: .any)["lottery-photo"].firstMatch.waitForExistence(timeout: 5),
                          "Housing Connect cards show the street at the address")
        }
        // Beds filter (owner, 2026-09-21; in the Filter sheet since 2026-10-17):
        // a size no open lottery has leaves the pane saying so, and clearing
        // it brings the list back.
        func setBeds(_ pick: String?) {
            app.buttons["lotteries-edit"].tap()
            let fourPlus = app.buttons["segment-4+"]
            XCTAssertTrue(fourPlus.waitForExistence(timeout: 5), "Beds sits in the Filter sheet")
            // Beds is remembered across launches (@AppStorage): a simulator that
            // last had "1" picked would make 4+ mean "1 or 4+" and hide nothing.
            for label in ["Studio", "1", "2", "3", "4+"] {
                let seg = app.buttons["segment-\(label)"]
                if seg.exists && seg.isSelected { seg.tap() }
            }
            if let pick { app.buttons["segment-\(pick)"].tap() }
            app.buttons["Close"].tap()
        }
        if card.exists {
            setBeds(nil)
            XCTAssertTrue(card.waitForExistence(timeout: 5))
            let before = app.descendants(matching: .any).matching(identifier: "lottery-card").count
            setBeds("4+")
            let shown = app.descendants(matching: .any).matching(identifier: "lottery-card").count
            XCTAssertTrue(shown < before || app.staticTexts.matching(NSPredicate(format: "label BEGINSWITH 'None with'")).firstMatch.waitForExistence(timeout: 3),
                          "4+ beds should hide lotteries without a 4-bed")
            setBeds(nil)
            XCTAssertTrue(card.waitForExistence(timeout: 5), "clearing Beds brings the lotteries back")
        }
        // The Re-rentals pane: the agents' re-rentals in the same boroughs.
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Re-rentals'")).firstMatch.tap()
        let rerental = app.descendants(matching: .any)["rerental-card"].firstMatch
        XCTAssertTrue(rerental.waitForExistence(timeout: 10) || app.descendants(matching: .any)["lotteries-empty"].firstMatch.exists,
                      "the Re-rentals pane should list re-rentals or say none are posted")
        // The NJ pane (owner, 2026-09-24): Affordable Homes New Jersey's
        // drawings, each with a way to apply; no Beds strip, as NJ lists no sizes.
        let njTab = app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'NJ'")).firstMatch
        XCTAssertTrue(njTab.isHittable, "the NJ pane must fit beside the other two")
        njTab.tap()
        let nj = app.descendants(matching: .any)["nj-lottery-card"].firstMatch
        XCTAssertTrue(nj.waitForExistence(timeout: 10) || app.descendants(matching: .any)["lotteries-empty"].firstMatch.exists,
                      "the NJ pane should list drawings or say none are open")
        if nj.exists {
            XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS 'View the listing'")).firstMatch.exists)
        }
        XCTAssertFalse(app.buttons["segment-4+"].exists, "no Beds strip on the NJ pane")
        // County filter (owner, 2026-09-25): pick the first county in the menu,
        // the count reads N of M, and Clear brings every drawing back.
        let county = app.buttons["nj-county"]
        XCTAssertTrue(county.waitForExistence(timeout: 5), "the NJ pane has a County menu")
        if nj.exists {
            county.tap()
            let firstCounty = app.buttons.matching(NSPredicate(format: "label ENDSWITH ')' AND label CONTAINS 'County ('")).firstMatch
            XCTAssertTrue(firstCounty.waitForExistence(timeout: 5), "the menu lists counties with their counts")
            firstCounty.tap()
            let njCount = app.staticTexts["nj-count"]
            XCTAssertTrue(njCount.label.contains(" of "), "filtered by county, the count says N of M: \(njCount.label)")
            let njShot = XCTAttachment(screenshot: app.screenshot()); njShot.name = "nj-county"; njShot.lifetime = .keepAlways; add(njShot)
            app.buttons["nj-clear"].tap()
            XCTAssertFalse(njCount.label.contains(" of "), "Clear shows every county again")
        }
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "lotteries-nj"; shot.lifetime = .keepAlways; add(shot)
    }

    /// Your Crib (owner, 2026-10-15; replaced Events): an address shows its
    /// 311 calls with pests first, the six-month crime line, and the Plus
    /// gates. --casa-demo opens a sample building with no network.
    func testYourCasaShowsPestsCallsAndCrime() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--casa-demo"]
        app.launch()
        let tab = app.buttons["tab-Your Crib"]
        XCTAssertTrue(tab.waitForExistence(timeout: 20), "New York should have a Your Crib tab")
        let hittable = XCTNSPredicateExpectation(predicate: NSPredicate(format: "isHittable == true"), object: tab)
        XCTAssertEqual(XCTWaiter().wait(for: [hittable], timeout: 5), .completed, "Your Crib must fit on the bar")
        tab.tap()
        XCTAssertTrue(app.descendants(matching: .any)["casa-address"].waitForExistence(timeout: 10), "the address field leads the tab")
        let pests = app.descendants(matching: .any)["casa-pests"]
        XCTAssertTrue(pests.waitForExistence(timeout: 10), "the sample building opens")
        XCTAssertTrue(pests.label.contains("2 pest calls"), "pests lead: \(pests.label)")
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "casa-call").count, 4, "every call in the past year is listed")
        let chart = app.descendants(matching: .any)["casa-crime-chart"]
        for _ in 0..<4 where !chart.exists { app.swipeUp() }
        XCTAssertTrue(chart.waitForExistence(timeout: 5), "the six-month crime line shows")
        // Not signed in: Plus history asks for an account first.
        let history = app.buttons["casa-history"]
        for _ in 0..<3 where !history.isHittable { app.swipeUp() }
        XCTAssertTrue(history.exists, "older calls are offered")
        // Signed out, the history button's sheet leads with the history.
        history.tap()
        add(XCTAttachment(screenshot: app.screenshot()))
        XCTAssertTrue(app.staticTexts["Sign in to see the full history"].waitForExistence(timeout: 5), "the history sheet names its feature")
        XCTAssertTrue(app.descendants(matching: .any)["casa-promise-box"].exists, "and lists what Plus adds")
        app.buttons["Cancel"].tap()
        XCTAssertTrue(history.waitForExistence(timeout: 5))
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "your-casa"; shot.lifetime = .keepAlways; add(shot)
        // Not signed in: "Alert me" opens the sign-in sheet with what the
        // alerts are, like the other sign-in sheets (owner, 2026-10-15).
        let alert = app.buttons["casa-alert"]
        for _ in 0..<4 where !alert.isHittable { app.swipeDown() }
        XCTAssertTrue(alert.isHittable, "Turn on alerts shows")
        alert.tap()
        XCTAssertTrue(app.descendants(matching: .any)["casa-promise-box"].waitForExistence(timeout: 5),
                      "the sign-in sheet lists what Your Crib alerts include")
        XCTAssertTrue(app.buttons["casa-promise-plus"].exists, "with a Get Plus button")
        // Crime alerts are free since 10/19; the box says so first.
        XCTAssertTrue(app.staticTexts["Free: crime alerts within half a mile of your building"].exists, "crime alerts are offered free")
        let sheet = XCTAttachment(screenshot: app.screenshot()); sheet.name = "your-crib-signin"; sheet.lifetime = .keepAlways; add(sheet)
    }

    /// Building chat (owner, 2026-10-17): a button right under the address
    /// in Your Crib opens the building's chat; signed out, it asks to sign in
    /// and says the chat is end-to-end encrypted.
    func testYourCribOpensBuildingChat() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--casa-demo", "--tab", "casa"]
        app.launch()
        let place = app.staticTexts["casa-place"]
        XCTAssertTrue(place.waitForExistence(timeout: 20))
        let chat = app.buttons["casa-chat"]
        XCTAssertTrue(chat.waitForExistence(timeout: 5), "Building chat sits under the address")
        XCTAssertLessThan(place.frame.maxY, chat.frame.minY, "below the address")
        XCTAssertLessThan(chat.frame.minY - place.frame.maxY, 80, "directly below it")
        chat.tap()
        XCTAssertTrue(app.buttons["chat-signin"].waitForExistence(timeout: 5), "signed out, the chat asks to sign in")
        XCTAssertTrue(app.staticTexts["End-to-end encrypted"].exists)
        add(XCTAttachment(screenshot: app.screenshot()))
        app.buttons["Close"].tap()
    }

    /// Building chat room in Instagram's layout (owner, 2026-10-23, from a
    /// screen recording): yours on the right, neighbors' on the left; centred
    /// time lines; a reply quote and a reaction; hold for reactions + menu;
    /// swipe right to reply; Unsend; typing bubble; details in a sheet.
    func testBuildingChatRoomLayoutAndTyping() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--casa-demo", "--chat-demo", "--tab", "casa"]
        app.launch()
        let chat = app.buttons["casa-chat"]
        XCTAssertTrue(chat.waitForExistence(timeout: 20))
        chat.tap()
        let typing = app.descendants(matching: .any)["chat-typing"]
        XCTAssertTrue(typing.waitForExistence(timeout: 5), "someone typing shows a bubble")
        XCTAssertTrue(typing.label.contains("is typing"), typing.label)
        let stamps = app.descendants(matching: .any).matching(identifier: "chat-stamp")
        XCTAssertGreaterThanOrEqual(stamps.count, 2, "Yesterday and Today get centred time lines")
        func message(_ text: String) -> XCUIElement {
            app.descendants(matching: .any).matching(identifier: "chat-message").matching(NSPredicate(format: "label CONTAINS %@", text)).firstMatch
        }
        let mine = message("Back on here"), theirs = message("Radiators are cold")
        XCTAssertTrue(mine.exists && theirs.exists)
        // Against each other, not the screen: on iPad the room is a centred
        // 720 pt column, so a neighbor's bubble starts well inside the edge.
        XCTAssertGreaterThan(mine.frame.minX, theirs.frame.minX + 80, "yours sit right of a neighbor's: \(mine.frame) vs \(theirs.frame)")
        XCTAssertTrue(app.descendants(matching: .any)["chat-quote"].exists, "a reply shows what it answers")
        XCTAssertTrue(app.buttons["chat-reactions"].exists, "a reaction sits under its bubble")
        XCTAssertFalse(app.staticTexts["You"].exists, "your messages carry no \"You\" label")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "building-chat-room"; shot.lifetime = .keepAlways; add(shot)

        // Hold a neighbor's message: reactions above, actions below.
        theirs.press(forDuration: 0.6)
        XCTAssertTrue(app.descendants(matching: .any)["chat-hold-menu"].waitForExistence(timeout: 3))
        XCTAssertTrue(app.buttons["chat-menu-reply"].exists && app.buttons["chat-menu-report"].exists)
        XCTAssertFalse(app.buttons["chat-menu-unsend"].exists, "only your own messages can be unsent")
        let held = XCTAttachment(screenshot: app.screenshot()); held.name = "building-chat-hold"; held.lifetime = .keepAlways; add(held)
        app.buttons["chat-react-😂"].tap()
        XCTAssertTrue(app.buttons["chat-reactions"].waitForExistence(timeout: 3))
        XCTAssertEqual(app.buttons.matching(identifier: "chat-reactions").count, 2, "the new reaction joins the earlier one")

        // Swipe right to reply, then send.
        let start = theirs.coordinate(withNormalizedOffset: CGVector(dx: 0.2, dy: 0.5))
        start.press(forDuration: 0.05, thenDragTo: start.withOffset(CGVector(dx: 160, dy: 0)))
        XCTAssertTrue(app.descendants(matching: .any)["chat-replying"].waitForExistence(timeout: 3), "swiping right starts a reply")
        let input = app.textFields["chat-input"].exists ? app.textFields["chat-input"] : app.textViews["chat-input"]
        input.tap(); input.typeText("Mine too")
        app.buttons["chat-send"].tap()
        let sent = message("Mine too")
        XCTAssertTrue(sent.waitForExistence(timeout: 3))
        XCTAssertFalse(app.descendants(matching: .any)["chat-replying"].exists, "the reply bar clears once sent")
        XCTAssertEqual(app.descendants(matching: .any).matching(identifier: "chat-quote").count, 2)

        // Unsend it.
        sent.press(forDuration: 0.6)
        XCTAssertTrue(app.buttons["chat-menu-unsend"].waitForExistence(timeout: 3))
        app.buttons["chat-menu-unsend"].tap()
        XCTAssertTrue(sent.waitForNonExistence(timeout: 3), "unsent messages leave the room")

        // Details stay one sheet away.
        theirs.press(forDuration: 0.6)
        XCTAssertTrue(app.buttons["chat-menu-details"].waitForExistence(timeout: 3))
        app.buttons["chat-menu-details"].tap()
        XCTAssertTrue(app.descendants(matching: .any)["chat-detail"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["chat-detail-report"].exists, "with Report")
    }

    /// No pests sits with No violations under Building condition (owner,
    /// 2026-10-24), and turning it on shows in the Filter count.
    func testFiltersOfferNoPests() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results"]
        app.launch()
        let filter = app.buttons["results-filter"]
        XCTAssertTrue(filter.waitForExistence(timeout: 60))
        filter.tap()
        let pests = app.switches["filter-no-pests"]
        for _ in 0..<6 where !(pests.exists && pests.isHittable) { app.swipeUp() }
        XCTAssertTrue(pests.waitForExistence(timeout: 5), "the filters offer No pests")
        XCTAssertEqual(pests.value as? String, "0", "off by default")
        pests.switches.firstMatch.exists ? pests.switches.firstMatch.tap() : pests.tap()
        XCTAssertEqual(pests.value as? String, "1")
    }

    /// The owner looked for it on Search's Show list, not in Filters
    /// (2026-10-25), so it is in both, and they are one setting.
    func testShowListOffersNoPests() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash"]
        app.launch()
        let row = app.buttons["check-No pests"]
        for _ in 0..<6 where !(row.exists && row.isHittable) { app.swipeUp() }
        XCTAssertTrue(row.waitForExistence(timeout: 20), "Search's Show list offers No pests")
        XCTAssertFalse(row.isSelected, "off by default")
        row.tap()
        XCTAssertTrue(row.isSelected)
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "show-no-pests"; shot.lifetime = .keepAlways; add(shot)
    }

    /// Documents saved in the app go with the email to the agent (owner,
    /// 2026-10-24): with one in the packet, the send button attaches it and
    /// says so; tapping it opens a composer, not a bare mailto link.
    func testHelpMeApplyEmailCarriesSavedDocuments() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results", "--apply-demo"]
        app.launch()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 60))
        let help = scrollToHelpMeApply()
        XCTAssertTrue(help.exists)
        help.tap()
        let send = app.buttons["apply-email-send"]
        for _ in 0..<6 where !(send.exists && send.isHittable) { app.swipeUp() }
        XCTAssertTrue(send.waitForExistence(timeout: 10))
        XCTAssertEqual(send.label, "Email with my documents", "with a saved document the button attaches it")
        XCTAssertTrue(app.staticTexts["apply-email-attached"].label.contains("Recent pay stubs"), "and names what goes with it")
        send.tap()
        // No Mail account on a simulator: the share sheet, with the files.
        XCTAssertTrue(app.otherElements["ActivityListView"].waitForExistence(timeout: 10)
                      || app.navigationBars["MFMailComposeView"].waitForExistence(timeout: 2), "sending opens a composer with the files")
    }

    /// The records screen's "N open" is the city's count now, not the weekly
    /// banked one (owner, 2026-10-24: 129 Carlton Ave said "0 open" above a
    /// list of open complaints). Live data, so it checks the contradiction
    /// itself: any Open row in the list means the count can't be 0.
    func testComplaintsOpenCountAgreesWithTheList() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "hpdc:3020440004"]
        app.launch()
        let count = app.staticTexts["hpd-open-count"]
        XCTAssertTrue(count.waitForExistence(timeout: 30), "the complaints screen shows its open count")
        let openRow = app.staticTexts["Open"].firstMatch
        if openRow.waitForExistence(timeout: 20) {
            let done = XCTNSPredicateExpectation(predicate: NSPredicate(format: "label != '0 open'"), object: count)
            XCTAssertEqual(XCTWaiter().wait(for: [done], timeout: 15), .completed, "an Open complaint is listed, but the count says \(count.label)")
        }
    }

    /// Violations & inspections leads and About is the last section (owner,
    /// 2026-09-19): violations are what people tap most on a building page.
    func testViolationsFirstAndAboutLast() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "detail"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 30))
        let violations = app.staticTexts["Violations & inspections"]
        let agent = app.staticTexts["Managing agent"]
        let about = app.staticTexts["About"]
        XCTAssertTrue(violations.waitForExistence(timeout: 5))
        var violY = violations.frame.minY
        // Scroll in steps, keeping each heading's position relative to About's
        // as both come on screen, until About appears.
        var agentAbove = false
        for _ in 0..<20 where !about.exists {
            if agent.exists { agentAbove = true }
            app.swipeUp()
        }
        if agent.exists, about.exists { agentAbove = agent.frame.minY < about.frame.minY }
        if violations.exists { violY = violations.frame.minY }
        XCTAssertTrue(about.exists, "About should be reachable at the bottom")
        XCTAssertTrue(agentAbove, "Managing agent must come before About")
        XCTAssertLessThan(violY, about.frame.minY, "Violations & inspections must sit above About")
    }

    /// The building screen's bottom bar carries Comments, not Share (Share
    /// moved into the ··· menu, owner 2026-09-20), and signed out the sheet
    /// asks people to sign up rather than showing the thread.
    func testCommentsButtonReplacesShareAndGatesOnSignUp() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "detail"]
        app.launch()
        let comments = app.buttons["detail-comments"]
        XCTAssertTrue(comments.waitForExistence(timeout: 30), "the bottom bar should offer Comments")
        XCTAssertFalse(app.buttons["Share"].exists, "Share belongs in the ··· menu now")
        comments.tap()
        XCTAssertTrue(app.buttons["comments-signup"].waitForExistence(timeout: 10), "signed out: the sheet asks for an account")
        XCTAssertFalse(app.descendants(matching: .any)["comment-row"].firstMatch.exists, "no thread without an account")
        XCTAssertFalse(app.textFields["comment-field"].exists, "and no way to type one")
        XCTAssertFalse(app.buttons["comment-report"].exists, "nothing to report without a thread")
        app.buttons["Close"].tap()
        XCTAssertTrue(comments.waitForExistence(timeout: 10))
        // Share is still reachable from the menu.
        app.buttons["detail-menu"].tap()
        XCTAssertTrue(app.buttons["Share"].waitForExistence(timeout: 5), "the menu keeps Share")
    }

    /// A building outside New York shows the record ITS city publishes, and
    /// never New York's wording.
    ///
    /// Until 2026-09-12 the detail screen was New York's for every city: an LA
    /// parcel carried "Registered with NYS Homes and Community Renewal", a
    /// "Managing agent" section with no agent to show, and HPD violation tiles
    /// wired to NYC Open Data. DC is the check here because its record blob is
    /// the smallest download of the three — the other cities ship no seed in
    /// the bundle, so this test needs the network and a patient timeout.
    func testOtherCityShowsItsOwnRecord() throws {
        for (city, heading) in [("la", "LAHD record"), ("sf", "Rent Board record"),
                                ("dc", "Owner & assessor record")] {
            app.terminate()
            app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--city", city, "--route", "detail"]
            app.launch()
            XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 90),
                          "\(city) buildings never downloaded — this test needs the network")
            XCTAssertTrue(app.staticTexts[heading].waitForExistence(timeout: 20),
                          "a \(city) building must show its own record panel")
            // New York's chrome must be gone, not merely empty.
            XCTAssertFalse(app.staticTexts["Managing agent"].exists, "NYC's agent section leaked into \(city)")
            XCTAssertFalse(app.buttons["pill-Alerts"].exists, "alerts are NY-fed; the pill must not show in \(city)")
            XCTAssertFalse(app.staticTexts["Violations & inspections"].exists, "NYC's HPD section leaked into \(city)")
            XCTAssertFalse(app.buttons["open-violations"].exists, "NYC's violations tile leaked into \(city)")
            XCTAssertFalse(app.staticTexts.containing(
                NSPredicate(format: "label CONTAINS 'Homes and Community Renewal'")).firstMatch.exists,
                "New York's register is named on a \(city) building")
            // …and the two cities that publish no violations have to say so,
            // rather than leave a gap that reads as a clean building.
            if city != "la" {
                XCTAssertTrue(app.staticTexts.containing(
                    NSPredicate(format: "label CONTAINS 'housing-code violations by street address' OR label CONTAINS 'publishes no housing-code violation'")).firstMatch.exists,
                    "\(city) must say its violations are unpublished, not show nothing")
            }
        }
    }

    /// The measurement rig for "back takes long", kept because it will be
    /// wanted again. Run with the log stream open:
    ///
    ///   xcrun simctl spawn booted log stream --predicate \
    ///     'subsystem == "com.divinedavis.findacrib" && category == "perf"'
    ///   scripts/run_tests.sh FindACribUITests/FindACribUITests/testPopFromDetailIsInstrumented
    ///
    /// It asserts nothing about timing — the simulator is not the device, and a
    /// threshold here would either be met on a Mac while the phone stutters, or
    /// fail on a busy CI box. What it guarantees is that the marks are still
    /// wired up, so the rig is not silently dead the next time it is needed.
    func testPopFromDetailIsInstrumented() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--perf", "--route", "detail"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 60))
        sleep(4)
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 30))
    }

    func testAlertsSignInOffersAppleGoogleAndEmail() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results"]
        app.launch()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 60))
        app.descendants(matching: .any)["pill-Alerts"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Sign in for lottery alerts"].waitForExistence(timeout: 10))
        let apple = app.buttons["sign-in-apple"]
        let google = app.buttons["sign-in-google"]
        XCTAssertTrue(apple.isHittable)
        XCTAssertTrue(google.isHittable)
        XCTAssertLessThan(apple.frame.minY, google.frame.minY)
        XCTAssertTrue(app.textFields["email-field"].exists)
        XCTAssertTrue(app.secureTextFields["password-field"].exists)
        XCTAssertFalse(app.keyboards.firstMatch.exists)
        app.buttons["Cancel"].tap()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 5))
        XCTAssertFalse(app.staticTexts["Sign in for lottery alerts"].exists)
        XCTAssertFalse(app.buttons["alerts-subscribe"].exists)
    }

    func testAlertsEmailValidationStillWorks() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results"]
        app.launch()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 60))
        app.descendants(matching: .any)["pill-Alerts"].firstMatch.tap()
        XCTAssertTrue(app.buttons["sign-in-google"].waitForExistence(timeout: 10))
        let submit = app.buttons["email-submit"]
        if !submit.isHittable { app.swipeUp() }
        submit.tap()
        XCTAssertTrue(app.staticTexts["Enter your email."].waitForExistence(timeout: 5))
        XCTAssertTrue(app.buttons["forgot-password"].exists)
        app.buttons["Cancel"].tap()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 5))
    }

    /// The bottom bar offers Alerts, on every search.
    ///
    /// It used to be "Save search", with Alerts appearing only on
    /// Available-now / vouchers / lottery searches. The owner swapped them on
    /// 2026-09-12: a standing email beats a bookmark you have to come back and
    /// re-read, and it means the same thing on any search.
    func testResultsOffersAlertsNotSaveSearch() throws {
        app.terminate()
        // the plain stabilized search — the one that used to show only Save search
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results"]
        app.launch()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 60))
        let alerts = app.descendants(matching: .any)["pill-Alerts"].firstMatch
        XCTAssertTrue(alerts.waitForExistence(timeout: 10), "Alerts should be offered on every search")
        XCTAssertTrue(alerts.label.contains("Lottery Alerts"), "the pill says Lottery Alerts (owner, 2026-10-12): \(alerts.label)")
        // Fits beside Map on the screen.
        XCTAssertLessThanOrEqual(alerts.frame.maxX, app.windows.firstMatch.frame.maxX)
        // Only the pill's own titles — a bare "Save" is the card heart's
        // accessibility label and has nothing to do with this bar.
        for gone in ["Save search", "Search saved"] {
            XCTAssertFalse(app.buttons[gone].exists, "the \(gone) pill is still in the bottom bar")
        }
    }

    /// Once alerts are set up the Alerts pill goes and Map sits alone in the
    /// middle (owner, 2026-10-12). --lotteries-demo stands in for a subscriber.
    func testSubscriberSeesOnlyACentredMapPill() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results", "--lotteries-demo"]
        app.launch()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 60))
        let map = app.descendants(matching: .any)["pill-Map"].firstMatch
        XCTAssertTrue(map.waitForExistence(timeout: 10))
        XCTAssertFalse(app.descendants(matching: .any)["pill-Alerts"].firstMatch.exists, "a subscriber is not offered alerts again")
        let w = app.windows.firstMatch.frame
        XCTAssertLessThan(abs(map.frame.midX - w.midX), 12, "Map is centred when it is alone")
    }

    /// The Alerts sheet carries the web form's filters: rent cap and
    /// household income beside boroughs and kinds.
    func testAlertsSheetOffersRentAndIncome() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "results", "--open-alerts"]
        app.launch()
        XCTAssertTrue(app.otherElements["alerts-sheet"].firstMatch.waitForExistence(timeout: 30) || app.descendants(matching: .any)["alerts-sheet"].firstMatch.waitForExistence(timeout: 5))
        let rent = app.descendants(matching: .any)["alerts-max-rent"].firstMatch
        let income = app.descendants(matching: .any)["alerts-income"].firstMatch
        for _ in 0..<6 where !rent.exists { app.swipeUp() }
        XCTAssertTrue(rent.waitForExistence(timeout: 5), "max-rent box missing from the alerts sheet")
        XCTAssertTrue(income.exists, "income box missing from the alerts sheet")
        XCTAssertTrue(app.descendants(matching: .any)["alerts-subscribe"].firstMatch.exists)
    }

    /// The pushed screens hide the system nav bar, which normally kills the
    /// edge swipe; this pins that swiping from the left edge still pops.
    func testEdgeSwipePopsDetail() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--route", "detail"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 30))
        // The menu exists while the push is still animating; an edge swipe
        // that lands mid-transition is swallowed, and on a loaded Mac (the
        // site's journey suite running beside this) that read as a broken
        // swipe-back 2 runs in 3 (2026-09-16). Let the screen rest first, and
        // allow one retry — a genuinely dead swipe-back fails both.
        _ = app.buttons["detail-menu"].waitForExistence(timeout: 5)
        Thread.sleep(forTimeInterval: 1.0)
        let from = app.coordinate(withNormalizedOffset: CGVector(dx: 0.01, dy: 0.55))
        let to = app.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.55))
        from.press(forDuration: 0.05, thenDragTo: to, withVelocity: .fast, thenHoldForDuration: 0.05)
        if !app.staticTexts["results-count"].waitForExistence(timeout: 8) {
            from.press(forDuration: 0.05, thenDragTo: to, withVelocity: .fast, thenHoldForDuration: 0.05)
        }
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 8), "edge swipe did not pop back to the results list")
    }

    /// `adjust(toPickerWheelValue:)` is a momentum scroll, not a seek: on an
    /// 18-rung wheel it routinely stops one or two rows short, and which row it
    /// lands on depends on where the wheel already was. Asking again from the
    /// new position converges. Failing loudly beats a test that quietly asserts
    /// against whatever row the flick happened to reach.
    /// Relaunch with the price sheet's mode reset — it is remembered across
    /// launches, and a test that inherits Custom finds no wheels.
    private func relaunchOnIncrements() {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--price-increments"]
        app.launch()
    }

    private func openPriceSheet(from box: XCUIElement) {
        box.tap()
        XCTAssertTrue(app.buttons["price-done"].waitForExistence(timeout: 10),
                      "tapping a price box did not open the picker")
        showIncrements()
    }

    /// The sheet remembers Increments vs Custom on purpose, and in Custom it
    /// raises the number pad as it appears. A tap on "Increments" that lands
    /// during that animation is swallowed and the wheels never come — which
    /// failed two price tests on iPad while passing on iPhone (2026-09-23).
    /// So: tap until the wheels are actually there.
    private func showIncrements(file: StaticString = #filePath, line: UInt = #line) {
        let wheel = app.pickerWheels.element(boundBy: 0)
        for _ in 0..<3 {
            if wheel.waitForExistence(timeout: 3) { return }
            let back = app.buttons["price-use-wheel"]
            if back.exists, back.isHittable { back.tap(); continue }
            let increments = app.segmentedControls["price-mode"].buttons["Increments"]
            if increments.exists, increments.isHittable { increments.tap() }
        }
        XCTAssertTrue(wheel.waitForExistence(timeout: 5),
                      "the Increments tab never showed its wheels", file: file, line: line)
    }

    private func spin(_ wheel: XCUIElement, to target: String, tries: Int = 5,
                      file: StaticString = #filePath, line: UInt = #line) {
        for _ in 0..<tries {
            if wheel.value as? String == target { return }
            wheel.adjust(toPickerWheelValue: target)
        }
        XCTAssertEqual(wheel.value as? String, target, "wheel would not settle on \(target)", file: file, line: line)
    }
}

/// The skyline band at the top of the results list (CitySkyline.swift). It is
/// decorative and hidden from accessibility, so what XCUITest can pin is that
/// pulling the list past its top — which reveals the night sky — leaves the
/// list working, in every city, and that the band did not push the count off
/// the screen. Set TEST_RUNNER_SKYLINE_SHOT_DIR to also save a screenshot of
/// the pulled state per city for eyeballing.
final class SkylineUITests: XCTestCase {
    /// Portrait first: a simulator left in landscape by an earlier run
    /// (2026-10-13: iPhone buttons reported at x=709) fails every portrait
    /// tap in the suite.
    override func setUp() { super.setUp(); XCUIDevice.shared.orientation = .portrait }
    func testPullingPastTheTopKeepsTheListWorkingInEveryCity() throws {
        let app = XCUIApplication()
        let shotDir = ProcessInfo.processInfo.environment["SKYLINE_SHOT_DIR"]
        for city in ["nyc", "sf", "dc", "la"] {
            app.terminate()
            app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--city", city, "--route", "results"]
            app.launch()
            let count = app.staticTexts["results-count"]
            XCTAssertTrue(count.waitForExistence(timeout: 90), "\(city) results never appeared")
            // The letter splash (2026-09-20) runs about two seconds and covers
            // the list while it does; a city that loads from the bundle has
            // its count before the splash is gone. Wait for the hand-over
            // before asking whether the count can be reached.
            let splash = app.otherElements["launch-animation"]
            if splash.exists {
                let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: splash)
                XCTAssertEqual(XCTWaiter().wait(for: [gone], timeout: 10), .completed, "\(city): the launch splash never handed over")
            }
            XCTAssertTrue(count.isHittable, "\(city): the skyline band pushed the results count out of view")
            // Drag the list down past its top and hold, the way a person peeks
            // at the sky; then let go and make sure the list snapped back.
            let start = count.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.5))
            let end = start.withOffset(CGVector(dx: 0, dy: 220))
            // The gesture blocks this thread, so the mid-pull frames — the
            // only ones that show the sky — are grabbed from another one and
            // kept in the .xcresult (xcresulttool export attachments) for
            // eyeballing; SKYLINE_SHOT_DIR also gets them as files.
            let frames = MidGestureFrames(after: [1.0, 1.8, 2.6])
            start.press(forDuration: 0.1, thenDragTo: end, withVelocity: .slow, thenHoldForDuration: 2.4)
            for (i, png) in frames.collect().enumerated() {
                let shot = XCTAttachment(uniformTypeIdentifier: "public.png", name: "skyline-pull-\(city)-\(i).png", payload: png)
                shot.lifetime = .keepAlways
                add(shot)
                if let shotDir { try? png.write(to: URL(fileURLWithPath: shotDir).appendingPathComponent("pull_\(city)_\(i).png")) }
            }
            XCTAssertTrue(count.waitForExistence(timeout: 5), "\(city): the list did not come back after the pull")
            XCTAssertTrue(count.isHittable, "\(city): results count is off screen after the pull")
            // The list still scrolls and the first card is still reachable.
            app.swipeUp()
            XCTAssertTrue(app.descendants(matching: .any)["pill-Map"].firstMatch.exists, "\(city): the results screen chrome is gone after the pull")
        }
    }
}

/// Screenshots taken on a background queue while a blocking gesture runs.
private final class MidGestureFrames {
    private let lock = NSLock()
    private var frames: [Data] = []
    private let group = DispatchGroup()
    init(after delays: [TimeInterval]) {
        for d in delays {
            group.enter()
            DispatchQueue.global().asyncAfter(deadline: .now() + d) { [self] in
                let png = XCUIScreen.main.screenshot().pngRepresentation
                lock.lock(); frames.append(png); lock.unlock()
                group.leave()
            }
        }
    }
    func collect() -> [Data] { group.wait(); lock.lock(); defer { lock.unlock() }; return frames }
}


/// The App Store rating ask (Services/ReviewPrompt.swift). A build run from
/// Xcode always gets Apple's real sheet, so `--review-now` must put it on
/// screen — it belongs to SpringBoard, not the app. TestFlight shows the
/// stand-in alert instead; that path is not reachable from a simulator.
final class ReviewPromptUITests: XCTestCase {
    /// Portrait first: a simulator left in landscape by an earlier run
    /// (2026-10-13: iPhone buttons reported at x=709) fails every portrait
    /// tap in the suite.
    override func setUp() { super.setUp(); XCUIDevice.shared.orientation = .portrait }
    func testReviewNowShowsTheSystemRatingSheet() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--review-now"]
        app.launch()
        // Apple's sheet ("Enjoying Find A Crib? Tap a star…", Not Now) is a
        // remote view hosted by StoreKitUIService — not SpringBoard, and not
        // the app. Any of its buttons proves the request reached StoreKit and
        // StoreKit chose to show it.
        let host = XCUIApplication(bundleIdentifier: "com.apple.ios.StoreKitUIService")
        let candidates = [host.buttons["Not Now"], app.buttons["Not Now"], host.buttons["Submit"]]
        var notNow: XCUIElement? = nil
        let deadline = Date().addingTimeInterval(15)
        while Date() < deadline, notNow == nil {
            notNow = candidates.first { $0.exists }
            if notNow == nil { Thread.sleep(forTimeInterval: 0.5) }
        }
        XCTAssertNotNil(notNow, "the system rating sheet never appeared after --review-now")
        if let b = notNow, b.label == "Not Now" { b.tap() }
        // The app is still usable underneath.
        XCTAssertTrue(app.buttons["city-field"].waitForExistence(timeout: 10))
    }

    /// TestFlight's look-alike (owner, 2026-09-25: the old one's button sent
    /// people to the App Store). It sits over the app with stars and Not Now,
    /// and neither leaves the app.
    func testTestFlightRatingPreviewStaysInTheApp() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--review-standin"]
        app.launch()
        let preview = app.descendants(matching: .any)["rating-preview"].firstMatch
        XCTAssertTrue(preview.waitForExistence(timeout: 15), "the preview shows over the app")
        XCTAssertTrue(app.staticTexts["Enjoying Find A Crib?"].exists)
        for i in 1...5 { XCTAssertTrue(app.buttons["rating-star-\(i)"].exists, "star \(i)") }
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "rating-preview"; shot.lifetime = .keepAlways; add(shot)
        app.buttons["rating-star-5"].tap()
        expectation(for: NSPredicate(format: "exists == false"), evaluatedWith: preview)
        waitForExpectations(timeout: 5)
        XCTAssertTrue(app.buttons["city-field"].waitForExistence(timeout: 5), "tapping a star closes it and stays in the app")
        XCTAssertEqual(app.state, .runningForeground, "never hands off to the App Store")
    }

    /// Push alerts (Services/PushService.swift). The permission dialog is only
    /// ever asked after alerts are turned on, which needs a signed-in account
    /// the anonymous UI suite does not have — so what this pins is the
    /// Profile row that reports the state, and that a launch with the
    /// notification delegate installed still reaches the home screen.
    func testProfileShowsPushAlertsState() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "profile"]
        app.launch()
        let row = app.descendants(matching: .any)["profile-push"].firstMatch
        for _ in 0..<6 where !row.exists { app.swipeUp() }
        XCTAssertTrue(row.waitForExistence(timeout: 10), "Profile has no Push alerts row")
        // The row is a container (its label is not its text); the state is a
        // static text inside it. Anonymous, never asked: "Sign in and turn on alerts".
        let state = app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'turn on alerts' OR label == 'On' OR label CONTAINS 'Settings' OR label CONTAINS 'not connected'")).firstMatch
        XCTAssertTrue(state.waitForExistence(timeout: 5), "the Push alerts row shows no state")
    }

    /// The launch-time notifications card (owner, 2026-09-18: everyone with
    /// the app is asked). Signed out on a fresh simulator it is the
    /// set-alerts-up wording; "Not now" snoozes it and the app is usable
    /// underneath. Every other test opts out of the card with
    /// --no-launch-prompt; this one resets the snooze instead.
    func testLaunchAsksToAllowNotificationsOnce() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--reset-launch-prompt"]
        app.launch()
        let card = app.alerts["Get alerts on this phone?"]
        XCTAssertTrue(card.waitForExistence(timeout: 15), "the notifications card never appeared after launch")
        XCTAssertTrue(card.staticTexts.matching(NSPredicate(format: "label CONTAINS 'pick your boroughs'")).firstMatch.exists, "signed out, the card should invite setting alerts up")
        card.buttons["Not now"].tap()
        XCTAssertFalse(card.exists)
        XCTAssertTrue(app.buttons["city-field"].waitForExistence(timeout: 10))
        // Snoozed: a plain relaunch shows nothing.
        app.terminate()
        app.launchArguments = []
        app.launch()
        XCTAssertTrue(app.buttons["city-field"].waitForExistence(timeout: 15))
        XCTAssertFalse(app.alerts["Get alerts on this phone?"].waitForExistence(timeout: 5), "Not now must snooze the card")
    }

    /// A tapped alert opens the app on every item in it (AlertPushSheet) —
    /// never straight onto one agent's website. Driven by --simulate-push,
    /// which feeds the payload through the same code path a tap does: XCUITest
    /// cannot open a notification from Notification Center.
    func testTappedAlertShowsEveryItem() throws {
        let payload = #"{"aps":{"alert":{"title":"New: 3 re-rentals","body":"x"}},"url":"https://residenewyork.com/property/a/","items":[{"k":"rerental","t":"2067 Anthony Avenue, Unit 305","s":"Bronx","u":"https://residenewyork.com/property/a/","b":"Bx"},{"k":"rerental","t":"1952 Anthony Avenue. Unit 2F","s":"","u":"https://www.taxaceny.com/projects-8","b":"Bx"},{"k":"lottery","t":"Astoria Commons","s":"Queens","u":"https://housingconnect.nyc.gov/","b":"Q"}]}"#
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--simulate-push", payload]
        app.launch()
        XCTAssertTrue(app.staticTexts["push-sheet-title"].waitForExistence(timeout: 15), "a tapped alert did not open the alert screen")
        XCTAssertEqual(app.staticTexts["push-sheet-title"].label, "New: 3 re-rentals")
        for t in ["2067 Anthony Avenue, Unit 305", "1952 Anthony Avenue. Unit 2F", "Astoria Commons"] {
            XCTAssertTrue(app.staticTexts[t].exists, "\(t) is missing from the alert screen")
        }
        XCTAssertEqual(app.buttons.matching(identifier: "push-item-open").count, 3, "every item gets its own link")
        // Without Plus (the UI runner never has it): the 8 AM wording, and the
        // real-time card as the second card (owner, 2026-10-06).
        XCTAssertTrue(app.staticTexts.matching(NSPredicate(format: "label CONTAINS '8 AM round-up'")).firstMatch.exists, "a non-Plus alert screen should say it's the 8 AM round-up")
        XCTAssertFalse(app.staticTexts.matching(NSPredicate(format: "label CONTAINS 'the minute they were posted'")).firstMatch.exists)
        let card = app.buttons["push-realtime-upsell"]
        XCTAssertTrue(card.exists, "the real-time card should be on the alert screen")
        let first = app.staticTexts["2067 Anthony Avenue, Unit 305"].frame.minY, second = app.staticTexts["1952 Anthony Avenue. Unit 2F"].frame.minY
        XCTAssertTrue(card.frame.minY > first && card.frame.minY < second, "the real-time card should sit between the first and second listing")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "push-sheet"; shot.lifetime = .keepAlways; add(shot)
        XCTAssertFalse(app.alerts["Get alerts on this phone?"].exists, "the launch card must not stack on a tapped alert")
    }

    func testProfileHasARateLink() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "profile"]
        app.launch()
        let rate = app.descendants(matching: .any)["profile-rate"].firstMatch
        for _ in 0..<6 where !rate.exists { app.swipeUp() }
        XCTAssertTrue(rate.waitForExistence(timeout: 10), "Profile has no Rate Find A Crib row")
    }
}

extension XCUIElement {
    /// Replaces a text field's contents (location search, 2026-10-19).
    func clearAndType(_ text: String) {
        tap()
        if let v = value as? String, !v.isEmpty, v != placeholderValue {
            typeText(String(repeating: XCUIKeyboardKey.delete.rawValue, count: v.count))
        }
        typeText(text)
    }
}
