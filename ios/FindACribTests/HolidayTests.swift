import XCTest
@testable import FindACrib

/// Holiday theming (HolidayTheme.swift): the dates come out right, the
/// shortest theme wins, and every holiday has its icon set.
final class HolidayTests: XCTestCase {
    private var cal: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = TimeZone(identifier: "America/New_York")!
        return c
    }
    private func on(_ y: Int, _ m: Int, _ d: Int) -> Date { cal.date(from: DateComponents(year: y, month: m, day: d, hour: 12))! }
    private func today(_ y: Int, _ m: Int, _ d: Int) -> String? { HolidayCalendar.current(on: on(y, m, d), calendar: cal)?.id }

    func testTheSameDaysAsMarracat() {
        XCTAssertEqual(HolidayCalendar.holidays.count, 21)
    }

    func testDates() {
        XCTAssertEqual(today(2026, 11, 26), "thanksgiving", "fourth Thursday, and it beats the gift guide around it")
        XCTAssertEqual(today(2026, 11, 27), "black-friday")
        XCTAssertEqual(today(2026, 11, 30), "cyber-monday")
        XCTAssertEqual(today(2027, 5, 31), "memorial", "last Monday in May")
        XCTAssertEqual(today(2027, 1, 18), "mlk", "third Monday in January")
        XCTAssertEqual(today(2026, 10, 25), "halloween", "Halloween's look starts six days early")
        XCTAssertEqual(today(2026, 12, 1), "gift-guide")
        XCTAssertNil(today(2026, 10, 23))
        XCTAssertNil(today(2027, 3, 10))
    }

    func testUITestsSeeTheEverydayApp() {
        // Every UI test launches with --no-launch-prompt; the unit test host doesn't.
        XCTAssertFalse(CommandLine.arguments.contains("--no-launch-prompt"))
    }

    func testEveryHolidayHasItsIcon() {
        for h in HolidayCalendar.holidays {
            XCTAssertEqual(h.icon, "AppIcon-\(h.id)")
            XCTAssertFalse(h.tab.isEmpty, h.id)
        }
        // Alternate icons only reach the app when the asset catalog compiles them in.
        let icons = Bundle.main.object(forInfoDictionaryKey: "CFBundleIcons") as? [String: Any]
        let alternates = icons?["CFBundleAlternateIcons"] as? [String: Any] ?? [:]
        for h in HolidayCalendar.holidays { XCTAssertNotNil(alternates[h.icon], "\(h.icon) missing from the app") }
    }
}
