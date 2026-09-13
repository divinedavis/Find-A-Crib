import XCTest

final class LaunchAnimationTests: XCTestCase {
    override func setUpWithError() throws { continueAfterFailure = false }

    func testLaunchRevealsInteractiveHome() {
        let app = XCUIApplication()
        app.launch()
        assertHomeIsInteractive(app)
    }

    func testReducedMotionRevealsInteractiveHome() {
        let app = XCUIApplication()
        app.launchArguments = ["--reduce-launch-motion"]
        app.launch()
        assertHomeIsInteractive(app)
    }

    func testForegroundDoesNotReplayLaunchOrResetSelectedTab() {
        let app = XCUIApplication()
        app.launch()
        XCTAssertTrue(app.buttons["tab-Profile"].waitForExistence(timeout: 10))
        app.buttons["tab-Profile"].tap()
        XCUIDevice.shared.press(.home)
        app.activate()
        XCTAssertFalse(app.otherElements["launch-animation"].exists)
        XCTAssertTrue(app.buttons["tab-Profile"].isSelected)
        app.buttons["tab-Search"].tap()
        XCTAssertTrue(app.buttons["city-field"].waitForExistence(timeout: 5))
    }

    private func assertHomeIsInteractive(_ app: XCUIApplication) {
        let city = app.buttons["city-field"]
        XCTAssertTrue(city.waitForExistence(timeout: 10))
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
