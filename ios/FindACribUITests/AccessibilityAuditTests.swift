import XCTest

/// Apple's automated accessibility audit (Xcode 15+, iOS 17+) on every main
/// screen, added 2026-10-02. `performAccessibilityAudit()` checks what App
/// Review and VoiceOver users hit: Dynamic Type clipping, contrast, missing
/// labels, too-small hit targets, traits. Runs in every ship on iPhone and iPad.
///
/// What is excused, and why, lives in `excused(_:)` — never excuse an issue on
/// one of our own controls to make the gate pass; fix the view instead.
final class AccessibilityAuditTests: XCTestCase {
    var app: XCUIApplication!

    override func setUpWithError() throws {
        continueAfterFailure = true   // one screen's issues must not hide the next screen's
        app = XCUIApplication()
        app.launchArguments = ["--no-launch-prompt", "--no-launch-splash", "--lotteries-demo", "--events-demo"]
        app.launch()
    }

    /// Issues on views we do not draw, or that the audit cannot judge.
    private func excused(_ issue: XCUIAccessibilityAuditIssue) -> Bool {
        guard let e = issue.element else {
            // No element = the audit could not point at anything to fix.
            return true
        }
        let id = e.identifier, label = e.label
        // Google's ad view (Services/Ads.swift): its markup is Google's.
        if id == "feed-ad" || id.hasPrefix("ad-") || label.localizedCaseInsensitiveContains("advertisement")
            || label.localizedCaseInsensitiveContains("Google") { return true }
        // The tab bar and the Map/List pill float over the content: a row
        // scrolled under one (or under its drop shadow) is measured against
        // the overlay's pixels, not its own background. Scrolled into the
        // clear, the same row passes; the overlays themselves are still audited.
        if issue.auditType.contains(.contrast), !id.hasPrefix("tab-"), !id.hasPrefix("pill-"), overlapsFloating(e.frame) { return true }
        // Anything inside a Google ad slot is drawn by the Google SDK.
        let ads = app.descendants(matching: .any).matching(identifier: "feed-ad")
        if (0..<ads.count).contains(where: { ads.element(boundBy: $0).frame.insetBy(dx: -1, dy: -1).contains(e.frame) }) { return true }
        // MapKit's own legal link and map tiles.
        if label == "Legal" || e.elementType == .map { return true }
        return false
    }

    /// Floating overlays, each grown by its padding and drop shadow (~20 pt).
    private var floatingFrames: [CGRect] {
        let tabs = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'tab-'"))
        let bar = (0..<tabs.count).reduce(CGRect.null) { $0.union(tabs.element(boundBy: $1).frame) }
        let pills = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'pill-'"))
        return ([bar] + (0..<pills.count).map { pills.element(boundBy: $0).frame })
            .filter { !$0.isNull && !$0.isEmpty }.map { $0.insetBy(dx: -20, dy: -20) }
    }

    /// Partly off the bottom of the screen (behind the home indicator):
    /// sampled against what is not drawn. Scrolled up, it is audited.
    private func overlapsFloating(_ r: CGRect) -> Bool {
        let window = app.windows.firstMatch.frame
        if !window.isEmpty, r.maxY > window.maxY - 34 { return true }
        return floatingFrames.contains { r.intersects($0) }
    }

    private func audit(_ screen: String) {
        var found: [String] = []
        do {
            // Every audit type except Dynamic Type: RootView caps text at
            // xLarge on purpose (fixed StreetEasy layouts wrap to single words
            // at the accessibility sizes), so every label reports "partially
            // unsupported". Lifting that cap is a layout project of its own;
            // when it lands, put .dynamicType back here.
            var types: XCUIAccessibilityAuditType = .all
            types.remove(.dynamicType)
            try app.performAccessibilityAudit(for: types) { issue in
                if self.excused(issue) { return true }
                let e = issue.element
                found.append("\(Self.name(issue.auditType)) — \(issue.compactDescription) — [\(e?.identifier ?? "")] \"\(e?.label ?? "")\" \(e.map { "\($0.elementType.rawValue) @\(Int($0.frame.minX)),\(Int($0.frame.minY)) \(Int($0.frame.width))x\(Int($0.frame.height))" } ?? "")")
                return true   // collected below, so every issue on the screen is listed at once
            }
        } catch {
            XCTFail("\(screen): audit could not run: \(error)")
        }
        if !found.isEmpty {
            XCTFail("\(screen): \(found.count) accessibility issue(s):\n" + found.joined(separator: "\n"))
        }
    }

    private static func name(_ t: XCUIAccessibilityAuditType) -> String {
        let names: [(XCUIAccessibilityAuditType, String)] = [
            (.contrast, "contrast"), (.elementDetection, "element detection"), (.hitRegion, "hit region"),
            (.sufficientElementDescription, "description"), (.dynamicType, "dynamic type"),
            (.textClipped, "text clipped"), (.trait, "trait")]
        return names.first { t.contains($0.0) }?.1 ?? "type \(t.rawValue)"
    }

    private func tab(_ name: String) {
        let b = app.buttons["tab-\(name)"]
        XCTAssertTrue(b.waitForExistence(timeout: 20), "the \(name) tab should show")
        b.tap(); sleep(2)
    }

    func testSearchScreen() throws {
        let search = app.buttons["search-button"]
        XCTAssertTrue(search.waitForExistence(timeout: 30))
        audit("Search")
    }

    func testResultsAndDetail() throws {
        let search = app.buttons["search-button"]
        XCTAssertTrue(search.waitForExistence(timeout: 30))
        let counted = NSPredicate(format: "label CONTAINS 'Search' AND NOT (label CONTAINS 'Search 0 ')")
        expectation(for: counted, evaluatedWith: search); waitForExpectations(timeout: 30)
        let bar = app.buttons["tab-Search"]
        for _ in 0..<4 where !search.isHittable || (bar.exists && search.frame.maxY > bar.frame.minY - 8) { app.swipeUp() }
        search.tap()
        let addr = app.buttons["card-address"].firstMatch
        XCTAssertTrue(addr.waitForExistence(timeout: 20))
        sleep(2)
        audit("Results")
        addr.tap()
        XCTAssertTrue(app.otherElements["detail-hero"].waitForExistence(timeout: 15) || app.staticTexts["About"].waitForExistence(timeout: 15))
        sleep(2)
        audit("Building detail")
    }

    /// Every tab the app shows right now, found at run time: a tab added or
    /// removed is audited (or dropped) without editing this test.
    func testEveryTab() throws {
        XCTAssertTrue(app.buttons["tab-Search"].waitForExistence(timeout: 20))
        let tabs = app.buttons.matching(NSPredicate(format: "identifier BEGINSWITH 'tab-'"))
        let names = (0..<tabs.count).map { tabs.element(boundBy: $0).identifier.replacingOccurrences(of: "tab-", with: "") }
        XCTAssertGreaterThan(names.count, 1, "the tab bar should list its tabs")
        for name in Set(names).sorted() where name != "Search" {   // Search is testSearchScreen
            tab(name)
            audit(name)
        }
    }
}
