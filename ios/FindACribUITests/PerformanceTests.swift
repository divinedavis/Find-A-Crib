import XCTest

/// Speed and memory on the paths people wait on, added 2026-10-02 with Apple's
/// XCTMetric API. Each test runs its block several times; the numbers land in
/// the .xcresult and scripts/perf_gate.py fails the ship when one goes over its
/// budget in scripts/perf_budgets.json. Simulator numbers are not phone numbers:
/// the budgets catch a regression (a 2x slower launch), not a real-world time —
/// the real-world numbers come from MetricKit (Services/Metrics.swift).
///
/// Run on the iPhone only (ship.sh): skipped in the regular suite so the iPad
/// and the per-change test runs stay as fast as they were.
final class PerformanceTests: XCTestCase {
    private let args = ["--no-launch-prompt", "--no-launch-splash"]

    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    /// Cold launch to first frame the user can touch.
    func testLaunch() throws {
        let opts = XCTMeasureOptions(); opts.iterationCount = 5
        measure(metrics: [XCTApplicationLaunchMetric(waitUntilResponsive: true)], options: opts) {
            let app = XCUIApplication(); app.launchArguments = args
            app.launch()
        }
    }

    /// Launch until the bundled buildings are decoded and the search button
    /// counts them: the wait people actually see.
    func testLaunchToSearchReady() throws {
        let app = XCUIApplication(); app.launchArguments = args
        let opts = XCTMeasureOptions(); opts.iterationCount = 5
        measure(metrics: [XCTClockMetric()], options: opts) {
            app.launch()
            let search = app.buttons["search-button"]
            XCTAssertTrue(search.waitForExistence(timeout: 30))
            let counted = NSPredicate(format: "label CONTAINS 'Search' AND NOT (label CONTAINS 'Search 0 ')")
            let ready = XCTNSPredicateExpectation(predicate: counted, object: search)
            XCTAssertEqual(XCTWaiter.wait(for: [ready], timeout: 30), .completed)
            app.terminate()
        }
    }

    /// Flinging the results list: hitches here are what "the app feels slow"
    /// means. Memory is read here too, with the list loaded and images decoding
    /// (it needs the app still running when the block ends).
    func testResultsScroll() throws {
        let app = XCUIApplication(); app.launchArguments = args
        app.launch()
        let search = app.buttons["search-button"]
        XCTAssertTrue(search.waitForExistence(timeout: 30))
        let counted = NSPredicate(format: "label CONTAINS 'Search' AND NOT (label CONTAINS 'Search 0 ')")
        expectation(for: counted, evaluatedWith: search); waitForExpectations(timeout: 30)
        if !search.isHittable { app.swipeUp() }
        search.tap()
        XCTAssertTrue(app.buttons["card-address"].firstMatch.waitForExistence(timeout: 20))
        let opts = XCTMeasureOptions(); opts.iterationCount = 5
        opts.invocationOptions = [.manuallyStop]
        measure(metrics: [XCTOSSignpostMetric.scrollDecelerationMetric, XCTMemoryMetric(application: app)], options: opts) {
            app.swipeUp(velocity: .fast)
            stopMeasuring()
            app.swipeDown(velocity: .fast)   // back to the top for the next pass
        }
    }
}
