import UIKit
import XCTest

/// Dark mode (owner, 2026-11-22): the app follows the phone's Light / Dark
/// setting, unless Light or Dark was picked in Profile › Appearance. Until
/// then it was pinned to light.

/// Apple's accessibility audit again, on every main screen, with the app in
/// dark mode. Contrast is the point: every colour in Theme.swift has a dark
/// half, and a text colour that is fine on a white card can fall under 4.5:1
/// on a dark one. Same screens and the same excuses as the light run, because
/// it is the same tests: this class only changes the appearance they run in.
///
/// The app is launched with --dark rather than by switching the device:
/// XCUIDevice.shared.appearance does nothing on the iPad simulator (iPadOS
/// 26.5, 2026-11-22), where the first version of this class "passed" its
/// audit on a screen that had stayed light.
final class AccessibilityAuditDarkTests: AccessibilityAuditTests {
    override var extraLaunchArguments: [String] { ["--dark"] }
}

final class DarkModeTests: XCTestCase {
    override func setUp() { super.setUp(); XCUIDevice.shared.orientation = .portrait }

    override func tearDown() {
        XCUIDevice.shared.appearance = .light
        super.tearDown()
    }

    /// How bright the screen is on average, 0 (black) to 1 (white).
    private func brightness() -> CGFloat {
        guard let cg = XCUIScreen.main.screenshot().image.cgImage else { return -1 }
        var px = [UInt8](repeating: 0, count: 4)
        guard let ctx = CGContext(data: &px, width: 1, height: 1, bitsPerComponent: 8, bytesPerRow: 4,
                                  space: CGColorSpaceCreateDeviceRGB(),
                                  bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue) else { return -1 }
        ctx.interpolationQuality = .medium
        ctx.draw(cg, in: CGRect(x: 0, y: 0, width: 1, height: 1))   // the whole screen averaged into one pixel
        return (0.2126 * CGFloat(px[0]) + 0.7152 * CGFloat(px[1]) + 0.0722 * CGFloat(px[2])) / 255
    }

    /// The Search screen is mostly background and cards, so its average says
    /// which palette is on: light canvas (F2F2F7) or dark (0B1012). Switching
    /// the phone over must switch the app while it is running, both ways.
    func testTheAppFollowsThePhonesAppearance() throws {
        // The iPad simulator ignores XCUIDevice.shared.appearance (iPadOS 26.5,
        // 2026-11-22: set to dark, the screen measured 0.93). The code path is
        // the same on both devices, and the iPhone run covers it.
        try XCTSkipIf(UIDevice.current.userInterfaceIdiom == .pad, "the iPad simulator cannot be switched to dark from a UI test")
        XCUIDevice.shared.appearance = .light
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--skyline-day"]
        app.launch()
        XCTAssertTrue(app.buttons["search-button"].waitForExistence(timeout: 30))
        sleep(1)
        let light = brightness()
        XCTAssertGreaterThan(light, 0.6, "in light mode the Search screen should be light (got \(light))")

        XCUIDevice.shared.appearance = .dark
        sleep(2)
        let dark = brightness()
        XCTAssertLessThan(dark, 0.25, "in dark mode the Search screen should be dark (got \(dark))")
        XCTAssertTrue(app.buttons["search-button"].isHittable, "Search should still be usable after the switch")

        XCUIDevice.shared.appearance = .light
        sleep(2)
        let back = brightness()
        XCTAssertGreaterThan(back, 0.6, "back in light mode the Search screen should be light again (got \(back))")
    }

    /// Two more screens, on iPhone and iPad: Profile and Your Crib are dark in
    /// dark mode, not light cards left behind on a dark canvas. Launched with
    /// --dark, which works on both devices (see AccessibilityAuditDarkTests).
    func testProfileAndYourCribAreDarkInDarkMode() throws {
        let app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--dark", "--tab", "profile"]
        app.launch()
        XCTAssertTrue(app.buttons["tab-Profile"].waitForExistence(timeout: 30))
        sleep(2)
        let profile = brightness()
        XCTAssertLessThan(profile, 0.25, "Profile should be dark in dark mode (got \(profile))")

        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--dark", "--tab", "casa", "--casa-demo"]
        app.launch()
        XCTAssertTrue(app.buttons["tab-Your Crib"].waitForExistence(timeout: 30))
        sleep(3)
        let crib = brightness()
        XCTAssertLessThan(crib, 0.25, "Your Crib should be dark in dark mode (got \(crib))")

        // And --light pins it the other way, so the flag is not just "dark".
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--light", "--tab", "profile"]
        app.launch()
        XCTAssertTrue(app.buttons["tab-Profile"].waitForExistence(timeout: 30))
        sleep(2)
        let light = brightness()
        XCTAssertGreaterThan(light, 0.6, "Profile should be light with --light (got \(light))")
    }

    /// Profile › Appearance (owner, 2026-11-22): Light, Dark, or the phone's
    /// setting, switched in place and kept across launches. Measured by how
    /// bright the screen is, like the tests above.
    func testProfileAppearancePicksLightDarkOrThePhone() throws {
        let phone = UIDevice.current.userInterfaceIdiom != .pad
        let app = XCUIApplication()
        // The tests share one installed app: a pick left behind would colour
        // every test after this one, so forget it however this test ends.
        addTeardownBlock {
            app.terminate()
            app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--appearance-reset"]
            app.launch()
            _ = app.buttons["tab-Profile"].waitForExistence(timeout: 30)
            app.terminate()
        }
        XCUIDevice.shared.appearance = .light
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--appearance-reset", "--tab", "profile"]
        app.launch()
        XCTAssertTrue(app.buttons["tab-Profile"].waitForExistence(timeout: 30))

        /// Scrolls to the row, opens its menu and taps one of the three.
        func pick(_ name: String) {
            let row = app.buttons["profile-appearance"]
            for _ in 0..<8 where !row.isHittable { app.swipeUp() }
            XCTAssertTrue(row.isHittable, "Profile shows an Appearance row")
            row.tap()
            let item = app.buttons[name]
            XCTAssertTrue(item.waitForExistence(timeout: 5), "the menu offers \(name)")
            item.tap()
            sleep(2)
        }
        let row = app.buttons["profile-appearance"]
        for _ in 0..<8 where !row.isHittable { app.swipeUp() }
        XCTAssertTrue(row.isHittable, "Profile shows an Appearance row")
        XCTAssertTrue(row.label.contains("iPhone setting"), "nothing picked yet, so it follows the phone: \(row.label)")
        if phone {
            let start = brightness()
            XCTAssertGreaterThan(start, 0.6, "a light phone and no pick: Profile is light (got \(start))")
        }

        pick("Dark")
        let dark = brightness()
        XCTAssertLessThan(dark, 0.25, "Dark turns the app dark on a light phone (got \(dark))")
        XCTAssertTrue(row.label.contains("Dark"), "the row names the pick: \(row.label)")
        add(XCTAttachment(screenshot: app.screenshot()))

        // Kept across launches (this launch does not reset it).
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--tab", "profile"]
        app.launch()
        XCTAssertTrue(app.buttons["tab-Profile"].waitForExistence(timeout: 30))
        sleep(2)
        let kept = brightness()
        XCTAssertLessThan(kept, 0.25, "Dark sticks after a relaunch (got \(kept))")

        // Light holds even when the phone goes dark. Only the iPhone simulator
        // can be switched from a test (see testTheAppFollowsThePhonesAppearance).
        pick("Light")
        if phone { XCUIDevice.shared.appearance = .dark; sleep(2) }
        let light = brightness()
        XCTAssertGreaterThan(light, 0.6, "Light keeps the app light\(phone ? " on a dark phone" : "") (got \(light))")

        // Back to the phone's setting: on the (now dark) iPhone that is dark
        // again, and it follows the phone back to light.
        pick("iPhone setting")
        XCTAssertTrue(row.label.contains("iPhone setting"), "the row says it follows the phone: \(row.label)")
        if phone {
            let followsDark = brightness()
            XCTAssertLessThan(followsDark, 0.25, "following a dark phone, the app is dark (got \(followsDark))")
            XCUIDevice.shared.appearance = .light
            sleep(2)
            let followsLight = brightness()
            XCTAssertGreaterThan(followsLight, 0.6, "and light again when the phone is (got \(followsLight))")
        }
    }
}
