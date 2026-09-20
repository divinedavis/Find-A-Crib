import XCTest

final class LaunchAnimationTests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    func testLaunchRevealsInteractiveHome() {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt"]
        app.launch()
        assertHomeIsInteractive(app)
    }

    func testReducedMotionRevealsInteractiveHome() {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--reduce-launch-motion"]
        app.launch()
        assertHomeIsInteractive(app)
    }

    func testForegroundDoesNotReplayLaunchOrResetSelectedTab() {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt"]
        app.launch()
        XCTAssertTrue(app.buttons["tab-Profile"].waitForExistence(timeout: 10))
        waitForSplashToHandOver(app)
        app.buttons["tab-Profile"].tap()
        XCUIDevice.shared.press(.home)
        app.activate()
        XCTAssertFalse(app.otherElements["launch-animation"].exists)
        // activate() returns while the foreground transition is still running
        // and the first snapshot can catch the tab bar before it re-renders;
        // the app keeps Profile selected (verified 2026-09-16 by polling after
        // the same steps), so give it a moment rather than read it once.
        let profile = app.buttons["tab-Profile"]
        let selected = XCTNSPredicateExpectation(predicate: NSPredicate(format: "isSelected == true"), object: profile)
        XCTAssertEqual(XCTWaiter().wait(for: [selected], timeout: 5), .completed,
                       "Profile tab lost its selection after foregrounding: profile=\(profile.isSelected) search=\(app.buttons["tab-Search"].isSelected) state=\(app.state.rawValue)")
        app.buttons["tab-Search"].tap()
        XCTAssertTrue(app.buttons["city-field"].waitForExistence(timeout: 5))
    }

    private func waitForSplashToHandOver(_ app: XCUIApplication) {
        let splash = app.otherElements["launch-animation"]
        guard splash.exists else { return }
        let gone = XCTNSPredicateExpectation(predicate: NSPredicate(format: "exists == false"), object: splash)
        XCTAssertEqual(XCTWaiter().wait(for: [gone], timeout: 10), .completed, "the launch splash never handed over")
    }

    private func assertHomeIsInteractive(_ app: XCUIApplication) {
        let city = app.buttons["city-field"]
        XCTAssertTrue(city.waitForExistence(timeout: 10))
        // The home screen is built underneath the splash while the letters
        // play (about two seconds since 2026-09-20); "interactive" means
        // after the hand-over, so wait for it rather than read the first frame.
        waitForSplashToHandOver(app)
        XCTAssertFalse(app.otherElements["launch-animation"].exists)
        XCTAssertTrue(city.isHittable)
        XCTAssertTrue(app.buttons["tab-Profile"].isHittable)
        app.buttons["tab-Profile"].tap()
        XCTAssertTrue(app.buttons["tab-Profile"].isSelected)
        app.buttons["tab-Search"].tap()
        XCTAssertTrue(city.waitForExistence(timeout: 5))
        XCTAssertFalse(app.otherElements["launch-animation"].exists)
    }
}
