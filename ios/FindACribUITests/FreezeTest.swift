import XCTest

/// The rig for "going back takes long". Keep it: this took several wrong
/// instruments to get right.
///
///   xcrun simctl spawn booted log stream --predicate \
///     'subsystem == "com.divinedavis.findacrib" && category == "perf"'
///   ROUTE=detail  scripts/run_tests.sh FindACribUITests/FreezeTest
///   ROUTE=results ANCHOR=results scripts/run_tests.sh FindACribUITests/FreezeTest
///
/// tap -> `FACMOVED` is the freeze a user actually sees. What does NOT measure
/// it, both tried and discarded:
///
///   * polling `element.exists` from the test — reads ~950ms on every build,
///     including one whose detail screen was a single Text. That is XCUITest's
///     own query cost.
///   * tap -> `onDisappear` — ~670ms for BOTH the pop that feels slow and the
///     one that feels instant. It measures SwiftUI's teardown schedule.
///
/// It asserts nothing about timing on purpose: a threshold met on a Mac is
/// missed by a phone. It exists so the marks stay wired up.
final class FreezeTest: XCTestCase {
    func testBack() throws {
        continueAfterFailure = false
        let route = ProcessInfo.processInfo.environment["ROUTE"] ?? "detail"
        let anchorIsResults = ProcessInfo.processInfo.environment["ANCHOR"] == "results"
        for run in 1...5 {
            let app = XCUIApplication()
            app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--perf", "--route", route]
            app.launch()
            if anchorIsResults {
                XCTAssertTrue(app.staticTexts["results-count"].waitForExistence(timeout: 120), "run \(run)")
            } else {
                XCTAssertTrue(app.buttons["detail-menu"].waitForExistence(timeout: 120), "run \(run)")
            }
            sleep(6)
            let back = app.navigationBars.buttons.element(boundBy: 0)
            _ = back.exists
            NSLog("FREEZE-TAP run \(run)")
            back.tap()
            sleep(3)
            app.terminate()
        }
    }
}
