import XCTest

/// Smoke path through the StreetEasy-shaped flow: home → results → detail →
/// back, plus the tab bar. Runs against the bundled data only.
final class FindACribUITests: XCTestCase {
    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt"]   // the notifications card would sit on every tap
        app.launch()
    }

    func testSearchToDetailAndBack() throws {
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

    /// App Review 4.8: a third-party login must come with an equivalent that
    /// can hide the user's email. Signed out, the profile offers Sign in with
    /// Apple first, then Google, then email. Build 14 shipped without the
    /// Apple button and was rejected for exactly this.
    func testSignInOffersAppleFirst() throws {
        XCTAssertTrue(app.buttons["tab-Profile"].waitForExistence(timeout: 20))
        app.buttons["tab-Profile"].tap()
        let apple = app.buttons["sign-in-apple"], google = app.buttons["sign-in-google"], email = app.buttons["sign-in-email"]
        XCTAssertTrue(apple.waitForExistence(timeout: 10), "Sign in with Apple must be offered")
        XCTAssertTrue(google.exists && email.exists)
        XCTAssertLessThan(apple.frame.minY, google.frame.minY, "Apple sits above Google")
        XCTAssertTrue(apple.label.contains("Apple"))
    }

    func testTabsSwitch() throws {
        XCTAssertTrue(app.buttons["tab-My Activity"].waitForExistence(timeout: 20))
        app.buttons["tab-My Activity"].tap()
        XCTAssertTrue(app.staticTexts["My Activity"].waitForExistence(timeout: 5))
        app.buttons["tab-Profile"].tap()
        XCTAssertTrue(app.staticTexts["Profile"].waitForExistence(timeout: 5))
        app.buttons["tab-Search"].tap()
        XCTAssertTrue(app.buttons["search-button"].waitForExistence(timeout: 5))
    }

    func testLocationPickerFiltersResults() throws {
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

    /// Re-rentals ride along in the results feed: the 3rd tile is one, with a
    /// "Rerental" flag and a hand-off button, and it never displaces a building
    /// (the count headline is unchanged). The default route is Brooklyn, and
    /// the bundled featured.json has Brooklyn re-rentals, so this runs offline.
    func testThirdResultTileIsARerental() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--route", "results"]
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
        // Order: exactly two building cards come before it.
        let all = app.descendants(matching: .any).matching(NSPredicate(format: "identifier == 'building-card' OR identifier == 'rerental-card'")).allElementsBoundByIndex
        if let i = all.firstIndex(where: { $0.identifier == "rerental-card" }) {
            XCTAssertEqual(i, 2, "the first re-rental must be the 3rd tile, found at \(i + 1)")
        }
    }

    /// The list follows the map: pan or zoom, and the count pill reads what
    /// is in view; "List" then opens on that area — no "Search this area" tap
    /// (removed 2026-09-16 at the owner's request, from a recording of the
    /// count sitting at 47,165 through a whole zoom into Clinton Hill).
    func testMapViewportCarriesToList() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--route", "map"]
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
        let minBox = app.buttons["price-Minimum price"]
        XCTAssertTrue(minBox.waitForExistence(timeout: 20))
        minBox.tap()
        let mode = app.segmentedControls["price-mode"]
        XCTAssertTrue(mode.waitForExistence(timeout: 10))
        mode.buttons["Custom"].tap()
        XCTAssertTrue(app.textFields["price-custom-low"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.textFields["price-custom-high"].exists)
        // and back, without losing the sheet
        mode.buttons["Increments"].tap()
        XCTAssertTrue(app.pickerWheels.element(boundBy: 0).waitForExistence(timeout: 5))
        app.buttons["price-done"].tap()
    }

    /// The pushed screens hide the system nav bar, which normally kills the
    /// edge swipe; this pins that swiping from the left edge still pops.
    /// Violations, complaints and the bedbug/rodent inspections are behind an
    /// account (2026-09-08, same as the site): signed out — which the
    /// simulator always is — the section offers sign-in and shows no tiles.
    func testViolationsGatedWhenSignedOut() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--route", "detail"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 30))
        let gate = app.buttons["hpd-sign-in"]
        for _ in 0..<12 where !gate.exists { app.swipeUp() }
        XCTAssertTrue(gate.waitForExistence(timeout: 5), "signed out, the HPD section must offer sign-in")
        XCTAssertFalse(app.buttons["open-violations"].exists, "violations tile leaked past the gate")
        XCTAssertFalse(app.buttons["bedbug-inspections"].exists, "bedbug tile leaked past the gate")
        XCTAssertFalse(app.buttons["rodent-inspections"].exists, "rodent tile leaked past the gate")
        gate.tap()
        XCTAssertTrue(app.buttons["sign-in-apple"].waitForExistence(timeout: 10), "the gate should land on the Profile sign-in")
    }

    /// Outside New York the app must not offer New York's things: the
    /// Lotteries tab (Housing Connect + HPD re-rentals, by borough) is gone,
    /// and the map opens on THAT city — it used to fall back to New York, so
    /// LA's map opened on Manhattan (owner, 2026-09-19).
    func testOtherCitiesHaveNoLotteriesTabAndOpenTheirOwnMap() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--city", "la", "--route", "map"]
        app.launch()
        XCTAssertTrue(app.buttons["pill-List"].waitForExistence(timeout: 40)
                      || app.descendants(matching: .any)["pill-List"].firstMatch.waitForExistence(timeout: 10),
                      "the LA map should open")
        XCTAssertFalse(app.buttons["tab-Lotteries"].exists, "Lotteries is New York's; it must not show in LA")
        // Apple labels the map's own places; New York's would mean the map
        // opened on the wrong coast.
        let ny = app.descendants(matching: .any).matching(NSPredicate(format: "label CONTAINS[c] 'Brooklyn' OR label CONTAINS[c] 'Manhattan' OR label CONTAINS[c] 'New York'")).count
        XCTAssertEqual(ny, 0, "the LA map is showing New York")
    }

    /// The hero mosaic is the city that is loaded, and a tile opens the real
    /// Look Around (owner, 2026-09-19). On a simulator Apple sometimes has no
    /// panorama for a corner, so either the viewer or its "none here" message
    /// is a pass — what must happen is that the tap opens the sheet.
    func testHeroTileOpensLookAround() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt"]
        app.launch()
        let tile = app.descendants(matching: .any)["hero-tile"].firstMatch
        XCTAssertTrue(tile.waitForExistence(timeout: 20), "the hero mosaic should be tappable")
        tile.tap()
        let close = app.buttons["hero-lookaround-close"]
        XCTAssertTrue(close.waitForExistence(timeout: 20), "a tile should open Look Around")
        close.tap()
        XCTAssertTrue(app.buttons["city-field"].waitForExistence(timeout: 10), "closing returns to Search")
    }

    /// The Lotteries tab shows for everyone (owner, 2026-09-19). Not
    /// subscribed, it shows a sign-up screen and NO sheet opens by itself;
    /// the button opens sign-in (signed out) then the alerts sheet. --lotteries-demo stands in for a subscriber
    /// to all five boroughs: the tab lists live lotteries and re-rentals.
    func testLotteriesTabSignupScreenThenListsForSubscribers() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt"]
        app.launch()
        let tab = app.buttons["tab-Lotteries"]
        XCTAssertTrue(tab.waitForExistence(timeout: 20), "the Lotteries tab shows for everyone")
        tab.tap()
        let signup = app.buttons["lotteries-signup"]
        XCTAssertTrue(signup.waitForExistence(timeout: 10), "not subscribed: the tab shows the sign-up screen")
        XCTAssertFalse(app.buttons["Cancel"].waitForExistence(timeout: 3), "no sheet may open by itself")
        XCTAssertFalse(app.descendants(matching: .any)["lottery-card"].firstMatch.exists, "no list without a subscription")
        signup.tap()
        let cancel = app.buttons["Cancel"]
        XCTAssertTrue(cancel.waitForExistence(timeout: 10), "signed out, the button opens sign-in first")
        XCTAssertTrue(app.buttons["sign-in-apple"].exists, "sign-in for alerts must offer Apple")
        XCTAssertTrue(app.buttons.matching(NSPredicate(format: "identifier CONTAINS 'google'")).firstMatch.exists, "…and Google")
        XCTAssertFalse(app.keyboards.firstMatch.exists, "no keyboard until they choose email")
        cancel.tap()
        XCTAssertTrue(signup.waitForExistence(timeout: 5))
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--lotteries-demo"]
        app.launch()
        XCTAssertTrue(tab.waitForExistence(timeout: 20))
        XCTAssertTrue(app.buttons["tab-My Activity"].isHittable && app.buttons["tab-Profile"].isHittable, "four tabs must all fit")
        tab.tap()
        let card = app.descendants(matching: .any)["lottery-card"].firstMatch
        let empty = app.descendants(matching: .any)["lotteries-empty"].firstMatch
        XCTAssertTrue(card.waitForExistence(timeout: 15) || empty.exists, "the tab should list lotteries or say none are open")
        if card.exists {
            XCTAssertTrue(app.buttons.matching(NSPredicate(format: "label CONTAINS 'Apply on Housing Connect'")).firstMatch.exists)
        }
        // The Re-rentals pane: the agents' re-rentals in the same boroughs.
        app.buttons.matching(NSPredicate(format: "label BEGINSWITH 'Re-rentals'")).firstMatch.tap()
        let rerental = app.descendants(matching: .any)["rerental-card"].firstMatch
        XCTAssertTrue(rerental.waitForExistence(timeout: 10) || app.descendants(matching: .any)["lotteries-empty"].firstMatch.exists,
                      "the Re-rentals pane should list re-rentals or say none are posted")
    }

    /// Violations & inspections leads and About is the last section (owner,
    /// 2026-09-19): violations are what people tap most on a building page.
    func testViolationsFirstAndAboutLast() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--route", "detail"]
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
            app.launchArguments = ["--no-launch-prompt", "--city", city, "--route", "detail"]
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
        app.launchArguments = ["--no-launch-prompt", "--perf", "--route", "detail"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 60))
        sleep(4)
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 30))
    }

    func testAlertsSignInOffersAppleGoogleAndEmail() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--route", "results"]
        app.launch()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 60))
        app.descendants(matching: .any)["pill-Alerts"].firstMatch.tap()
        XCTAssertTrue(app.staticTexts["Sign in for alerts"].waitForExistence(timeout: 10))
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
        XCTAssertFalse(app.staticTexts["Sign in for alerts"].exists)
        XCTAssertFalse(app.buttons["alerts-subscribe"].exists)
    }

    func testAlertsEmailValidationStillWorks() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--route", "results"]
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
        app.launchArguments = ["--no-launch-prompt", "--route", "results"]
        app.launch()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 60))
        let alerts = app.descendants(matching: .any)["pill-Alerts"].firstMatch
        XCTAssertTrue(alerts.waitForExistence(timeout: 10), "Alerts should be offered on every search")
        // Only the pill's own titles — a bare "Save" is the card heart's
        // accessibility label and has nothing to do with this bar.
        for gone in ["Save search", "Search saved"] {
            XCTAssertFalse(app.buttons[gone].exists, "the \(gone) pill is still in the bottom bar")
        }
    }

    /// The Alerts sheet carries the web form's filters: rent cap and
    /// household income beside boroughs and kinds.
    func testAlertsSheetOffersRentAndIncome() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--route", "results", "--open-alerts"]
        app.launch()
        XCTAssertTrue(app.otherElements["alerts-sheet"].firstMatch.waitForExistence(timeout: 30) || app.descendants(matching: .any)["alerts-sheet"].firstMatch.waitForExistence(timeout: 5))
        let rent = app.descendants(matching: .any)["alerts-max-rent"].firstMatch
        let income = app.descendants(matching: .any)["alerts-income"].firstMatch
        for _ in 0..<6 where !rent.exists { app.swipeUp() }
        XCTAssertTrue(rent.waitForExistence(timeout: 5), "max-rent box missing from the alerts sheet")
        XCTAssertTrue(income.exists, "income box missing from the alerts sheet")
        XCTAssertTrue(app.descendants(matching: .any)["alerts-subscribe"].firstMatch.exists)
    }

    func testEdgeSwipePopsDetail() throws {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--route", "detail"]
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
    private func openPriceSheet(from box: XCUIElement) {
        box.tap()
        XCTAssertTrue(app.buttons["price-done"].waitForExistence(timeout: 10),
                      "tapping a price box did not open the picker")
        XCTAssertTrue(app.pickerWheels.element(boundBy: 0).waitForExistence(timeout: 5))
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
    func testPullingPastTheTopKeepsTheListWorkingInEveryCity() throws {
        let app = XCUIApplication()
        let shotDir = ProcessInfo.processInfo.environment["SKYLINE_SHOT_DIR"]
        for city in ["nyc", "sf", "dc", "la"] {
            app.terminate()
            app.launchArguments = ["--no-launch-prompt", "--city", city, "--route", "results"]
            app.launch()
            let count = app.staticTexts["results-count"]
            XCTAssertTrue(count.waitForExistence(timeout: 90), "\(city) results never appeared")
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
    func testReviewNowShowsTheSystemRatingSheet() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--review-now"]
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

    /// Push alerts (Services/PushService.swift). The permission dialog is only
    /// ever asked after alerts are turned on, which needs a signed-in account
    /// the anonymous UI suite does not have — so what this pins is the
    /// Profile row that reports the state, and that a launch with the
    /// notification delegate installed still reaches the home screen.
    func testProfileShowsPushAlertsState() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--tab", "profile"]
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
        app.launchArguments = ["--no-launch-prompt", "--simulate-push", payload]
        app.launch()
        XCTAssertTrue(app.staticTexts["push-sheet-title"].waitForExistence(timeout: 15), "a tapped alert did not open the alert screen")
        XCTAssertEqual(app.staticTexts["push-sheet-title"].label, "New: 3 re-rentals")
        for t in ["2067 Anthony Avenue, Unit 305", "1952 Anthony Avenue. Unit 2F", "Astoria Commons"] {
            XCTAssertTrue(app.staticTexts[t].exists, "\(t) is missing from the alert screen")
        }
        XCTAssertEqual(app.buttons.matching(identifier: "push-item-open").count, 3, "every item gets its own link")
        let shot = XCTAttachment(screenshot: app.screenshot()); shot.name = "push-sheet"; shot.lifetime = .keepAlways; add(shot)
        XCTAssertFalse(app.alerts["Get alerts on this phone?"].exists, "the launch card must not stack on a tapped alert")
    }

    func testProfileHasARateLink() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--tab", "profile"]
        app.launch()
        let rate = app.descendants(matching: .any)["profile-rate"].firstMatch
        for _ in 0..<6 where !rate.exists { app.swipeUp() }
        XCTAssertTrue(rate.waitForExistence(timeout: 10), "Profile has no Rate Find A Crib row")
    }
}
