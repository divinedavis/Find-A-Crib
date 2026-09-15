import XCTest

/// Smoke path through the StreetEasy-shaped flow: home → results → detail →
/// back, plus the tab bar. Runs against the bundled data only.
final class FindACribUITests: XCTestCase {
    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = false
        app = XCUIApplication()
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

    /// Regression: "Search this area" then "List" must show the buildings in
    /// the map's view, not the results the map was opened from.
    func testMapSearchThisAreaCarriesToList() throws {
        app.terminate()
        app.launchArguments = ["--route", "map"]
        app.launch()
        let list = app.buttons["pill-List"]
        XCTAssertTrue(list.waitForExistence(timeout: 30))
        sleep(3)   // let the initial fit settle so the pan reads as the user's
        let map = app.maps.firstMatch
        XCTAssertTrue(map.waitForExistence(timeout: 10))
        map.swipeUp()
        map.pinch(withScale: 3, velocity: 2)
        let search = app.buttons["search-this-area"]
        XCTAssertTrue(search.waitForExistence(timeout: 5))
        search.tap()
        list.tap()
        let field = app.buttons["results-location-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        XCTAssertTrue(field.label.contains("Map area"), "list header was: \(field.label)")
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
        app.launchArguments = ["--route", "detail"]
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
            app.launchArguments = ["--city", city, "--route", "detail"]
            app.launch()
            XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 90),
                          "\(city) buildings never downloaded — this test needs the network")
            XCTAssertTrue(app.staticTexts[heading].waitForExistence(timeout: 20),
                          "a \(city) building must show its own record panel")
            // New York's chrome must be gone, not merely empty.
            XCTAssertFalse(app.staticTexts["Managing agent"].exists, "NYC's agent section leaked into \(city)")
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
        app.launchArguments = ["--perf", "--route", "detail"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 60))
        sleep(4)
        app.navigationBars.buttons.element(boundBy: 0).tap()
        XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 30))
    }

    func testAlertsSignInOffersAppleGoogleAndEmail() throws {
        app.terminate()
        app.launchArguments = ["--route", "results"]
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
        app.launchArguments = ["--route", "results"]
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
        app.launchArguments = ["--route", "results"]
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
        app.launchArguments = ["--route", "results", "--open-alerts"]
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
        app.launchArguments = ["--route", "detail"]
        app.launch()
        XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 30))
        let from = app.coordinate(withNormalizedOffset: CGVector(dx: 0.01, dy: 0.55))
        let to = app.coordinate(withNormalizedOffset: CGVector(dx: 0.95, dy: 0.55))
        from.press(forDuration: 0.05, thenDragTo: to, withVelocity: .fast, thenHoldForDuration: 0.05)
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
