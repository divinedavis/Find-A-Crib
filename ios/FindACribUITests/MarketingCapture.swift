import XCTest

/// Raw screens for the App Store panels (scripts/capture_marketing.sh runs it;
/// skipped in every other run). Signs in with the App Review demo account so
/// the building page shows violations and the managing agent, then saves one
/// PNG per screen into $MARKETING_RAW for scripts/make_screenshots.py.
final class MarketingCapture: XCTestCase {
    private let app = XCUIApplication()
    private var dir = ""

    override func setUpWithError() throws {
        let env = ProcessInfo.processInfo.environment
        dir = env["MARKETING_RAW"] ?? ""
        try XCTSkipIf(dir.isEmpty, "set TEST_RUNNER_MARKETING_RAW to capture")
        XCUIDevice.shared.orientation = .portrait
        continueAfterFailure = true
    }

    private func launch(_ args: [String]) {
        app.terminate()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash"] + args
        app.launch()
    }

    private func shot(_ name: String, wait: Double = 4) {
        Thread.sleep(forTimeInterval: wait)
        let png = XCUIScreen.main.screenshot().pngRepresentation
        try? png.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).png"))
    }

    /// Where the head officer's name and address sit on the last shot, in
    /// pixels, for make_screenshots.py to blur: HPD lists a person as head
    /// officer on nearly every building, and the ads name no real person
    /// (owner, 2026-10-17). The officer is the last party in the agent block.
    private func redactOfficer(_ name: String) {
        let texts = app.staticTexts.allElementsBoundByIndex
        guard let i = texts.firstIndex(where: { $0.label.hasPrefix("Head officer") }) else { return }
        let img = XCUIScreen.main.screenshot().image
        let scale = img.size.width * img.scale / app.frame.width   // points -> PNG pixels
        let rects = texts[(i + 1)...].prefix(2).map { e -> [Int] in
            let f = e.frame
            return [f.minX, f.minY, f.width, f.height].map { Int(($0 * scale).rounded()) }
        }
        let json = try? JSONSerialization.data(withJSONObject: rects)
        try? json?.write(to: URL(fileURLWithPath: dir).appendingPathComponent("\(name).redact.json"))
    }

    private func signIn() {
        let env = ProcessInfo.processInfo.environment
        guard let email = env["DEMO_EMAIL"], let pw = env["DEMO_PASSWORD"] else { return }
        launch(["--tab", "profile"])
        let open = app.buttons["sign-in-email"]
        guard open.waitForExistence(timeout: 15) else { return }   // already signed in
        open.tap()
        let field = app.textFields["email-field"]
        XCTAssertTrue(field.waitForExistence(timeout: 10))
        field.tap(); field.typeText(email)
        let pass = app.secureTextFields["password-field"]
        if !pass.exists { app.buttons["email-submit"].tap() }
        XCTAssertTrue(pass.waitForExistence(timeout: 10))
        pass.tap(); pass.typeText(pw)
        app.buttons["email-submit"].tap()
        XCTAssertFalse(app.buttons["sign-in-email"].waitForExistence(timeout: 15) && app.buttons["sign-in-email"].isHittable)
    }

    func testCaptureScreens() {
        signIn()
        // 90 Atlantic Ave, Cobble Hill: its managing agent and owner are
        // companies, so only the head officer needs blurring.
        let atlantic = "3002840015"
        let only = ProcessInfo.processInfo.environment["MARKETING_ONLY"].flatMap { $0.isEmpty ? nil : Set($0.split(separator: ",").map(String.init)) }
        func want(_ n: String) -> Bool { only?.contains(n) ?? true }
        if want("home") { launch([]); shot("home", wait: 8) }
        if want("map") { launch(["--route", "map"]); shot("map", wait: 8) }
        if want("detail") { launch(["--route", "detail:\(atlantic)"]); shot("detail", wait: 8) }
        if want("agent") { launch(["--route", "detail-agent:\(atlantic)"]); shot("agent", wait: 8); redactOfficer("agent") }
        if want("violations") { launch(["--route", "hpd:\(atlantic)"]); shot("violations", wait: 8) }
        if want("results") { launch(["--route", "results"]); shot("results", wait: 8) }
        if want("lotteries") {
            launch(["--lotteries-demo", "--tab", "lotteries"])
            // The panel is the lotteries themselves, not the Plus banner over them.
            let upsell = app.buttons["realtime-upsell-dismiss"]
            if upsell.waitForExistence(timeout: 8) { upsell.tap() }
            shot("lotteries", wait: 4)
        }
        if want("casa") { launch(["--casa-demo", "--tab", "casa"]); shot("casa", wait: 8) }
        for tool in ["rights", "renewal", "rent-increase", "repair"] where want(tool) {
            launch(["--tab", "profile"])
            Thread.sleep(forTimeInterval: 3)
            app.open(URL(string: "findacrib://tool/\(tool)")!)
            shot(tool, wait: 4)
        }
        if want("packet") {
            launch(["--tab", "profile"])
            let packet = app.buttons["profile-packet"]
            for _ in 0..<8 where !packet.isHittable { app.swipeUp() }
            if packet.isHittable { packet.tap(); shot("packet") }
        }
    }
}
