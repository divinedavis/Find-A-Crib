import SwiftUI
import UIKit

/// Holiday theming, the same days and colours as Marracat's (owner,
/// 2026-10-23: "use the same days as marracat"). Resources/holidays.json is a
/// copy of Marracat's list (scripts/sync_holidays.py), so both apps dress up
/// on the same day in the same colours.
///
/// On a holiday the splash takes the day's background, glow and a line under
/// FIND A CRIB; the skyline under the search bar is drawn in its colours; the
/// Map pill glows in them; the selected tab fills with them; and the Home
/// Screen icon switches (on by default, Profile turns it off).
struct Holiday: Decodable, Identifiable, Equatable {
    struct DateRule: Decodable, Equatable {
        let month: Int
        let day: Int?
        /// ISO weekday, 1 = Monday ... 7 = Sunday.
        let weekday: Int?
        /// Which one in the month; -1 is the last.
        let nth: Int?
        let offset: Int?
    }

    struct Span: Decodable, Equatable {
        let from: Int
        let to: Int
    }

    let id: String
    let name: String
    let date: DateRule
    /// The days around the date the app wears it.
    let theme: Span?
    let line: String
    /// The splash background.
    let disc: String
    /// An SF Symbol beside the line, or "kinara" (drawn: seven candles).
    let mark: String?
    let icon: String
    let tab: [String]
    /// Extra splash motion: "fireworks" (New Year's).
    let effect: String?

    /// The day in `year`.
    func day(in year: Int, calendar: Calendar = .holidays) -> Date? {
        let base: Date
        if let d = date.day {
            guard let fixed = calendar.date(from: DateComponents(year: year, month: date.month, day: d)) else { return nil }
            base = fixed
        } else if let weekday = date.weekday, let nth = date.nth, nth != 0 {
            let want = weekday % 7 + 1   // Calendar's weekday is 1 = Sunday; the JSON's is ISO.
            guard let first = calendar.date(from: DateComponents(year: year, month: date.month, day: 1)),
                  let days = calendar.range(of: .day, in: .month, for: first)?.count else { return nil }
            if nth > 0 {
                let lead = (want - calendar.component(.weekday, from: first) + 7) % 7
                guard let d = calendar.date(byAdding: .day, value: lead + (nth - 1) * 7, to: first) else { return nil }
                base = d
            } else {
                guard let last = calendar.date(byAdding: .day, value: days - 1, to: first) else { return nil }
                let back = (calendar.component(.weekday, from: last) - want + 7) % 7
                guard let d = calendar.date(byAdding: .day, value: -back, to: last) else { return nil }
                base = d
            }
            guard calendar.component(.month, from: base) == date.month else { return nil }
        } else {
            return nil
        }
        return calendar.date(byAdding: .day, value: date.offset ?? 0, to: base)
    }

    /// The days it themes the app in `year`.
    func themed(in year: Int, calendar: Calendar = .holidays) -> ClosedRange<Date>? {
        guard let theme, let day = day(in: year, calendar: calendar),
              let a = calendar.date(byAdding: .day, value: theme.from, to: day),
              let b = calendar.date(byAdding: .day, value: theme.to, to: day) else { return nil }
        return a...b
    }

    var colors: [Color] { tab.map(Color.init(hexString:)) }
    var background: Color { Color(hexString: disc) }
    /// The first colour that reads on white, for type and glows (MLK Day's
    /// first colour is white).
    var accent: Color { Color(hexString: tab.first { UIColor(hexString: $0).luminance < 0.7 } ?? disc) }
    /// White or ink on the filled tab, whichever reads on its first colour.
    var onFill: Color { UIColor(hexString: tab[0]).luminance > 0.6 ? SE.ink : .white }
}

enum HolidayCalendar {
    private struct File: Decodable { let holidays: [Holiday] }

    static let holidays: [Holiday] = {
        guard let url = Bundle.main.url(forResource: "holidays", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let file = try? JSONDecoder().decode(File.self, from: data) else { return [] }
        return file.holidays
    }()

    /// The holiday on `date`, by the renter's calendar day. Overlapping themes
    /// go to the shortest, so a single day beats the season around it
    /// (Thanksgiving inside the gift guide).
    static func current(on date: Date, calendar: Calendar = .holidays) -> Holiday? {
        let day = calendar.startOfDay(for: date)
        let year = calendar.component(.year, from: day)
        var best: (Holiday, Int)?
        for h in holidays {
            for y in [year - 1, year, year + 1] {
                guard let range = h.themed(in: y, calendar: calendar), range.contains(day) else { continue }
                let length = calendar.dateComponents([.day], from: range.lowerBound, to: range.upperBound).day ?? 0
                if best == nil || length < best!.1 { best = (h, length) }
            }
        }
        return best?.0
    }

    /// What the app wears today. `--holiday <id>` dresses it for one day
    /// whatever the date (screenshots, previews, UI tests); otherwise UI test
    /// runs (they all pass `--no-launch-prompt`) see the everyday app, so a
    /// run on a holiday can't change what the tests look for.
    static var today: Holiday? {
        let args = CommandLine.arguments
        if let i = args.firstIndex(of: "--holiday"), i + 1 < args.count {
            return holidays.first { $0.id == args[i + 1] }
        }
        if args.contains("--no-launch-prompt") { return nil }
        return current(on: Date())
    }
}

extension Calendar {
    /// Gregorian in the device's time zone: a holiday starts at the renter's midnight.
    static var holidays: Calendar {
        var c = Calendar(identifier: .gregorian)
        c.timeZone = .current
        return c
    }
}

extension Color {
    /// "#RRGGBB", as holidays.json writes colours.
    init(hexString: String) { self.init(uiColor: UIColor(hexString: hexString)) }
}

extension UIColor {
    convenience init(hexString: String) {
        let v = UInt32(hexString.trimmingCharacters(in: CharacterSet(charactersIn: "#")), radix: 16) ?? 0
        self.init(red: CGFloat((v >> 16) & 0xFF) / 255, green: CGFloat((v >> 8) & 0xFF) / 255,
                  blue: CGFloat(v & 0xFF) / 255, alpha: 1)
    }

    var luminance: CGFloat {
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        getRed(&r, green: &g, blue: &b, alpha: &a)
        return 0.299 * r + 0.587 * g + 0.114 * b
    }
}

/// The Home Screen icon. On by default, as on Marracat (owner, 2026-10-23);
/// iOS shows its own "You have changed the icon" alert on each switch, which
/// no app can hide. Profile › Holiday app icons turns it off.
enum HolidayIcon {
    static let settingKey = "holidayIcons"

    static var enabled: Bool { UserDefaults.standard.object(forKey: settingKey) as? Bool ?? true }

    /// The icon today should have: the holiday's while one is on and the
    /// setting is, the everyday one (nil) otherwise.
    static var wanted: String? {
        guard enabled, let h = HolidayCalendar.today else { return nil }
        return h.icon
    }

    /// Switch to the wanted icon if it isn't already showing. Only while the
    /// app is active: iOS refuses the change from the background. UI tests
    /// never get the system's alert over what they check.
    @MainActor
    static func apply() {
        let app = UIApplication.shared
        guard app.supportsAlternateIcons, app.applicationState == .active,
              !CommandLine.arguments.contains("--no-launch-prompt") else { return }
        let want = wanted
        guard app.alternateIconName != want else { return }
        app.setAlternateIconName(want) { _ in }
    }
}

/// The holiday's line under the splash word: a rule in the day's colours,
/// then the line itself between two marks.
struct HolidayLine: View {
    let holiday: Holiday
    var size: CGFloat = 15

    var body: some View {
        VStack(spacing: size * 0.7) {
            HStack(spacing: 0) {
                ForEach(0..<16, id: \.self) { i in holiday.colors[i % holiday.colors.count] }
            }
            .frame(width: size * 12, height: size * 0.27)
            .clipShape(Capsule())
            HStack(spacing: size * 0.55) {
                mark
                Text(holiday.line)
                    .font(.custom(SEWeight.black.postScript, fixedSize: size))
                    .kerning(size * 0.2)
                    .foregroundStyle(.white)
                    .lineLimit(1)
                    .minimumScaleFactor(0.6)
                mark
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(holiday.name)
    }

    @ViewBuilder private var mark: some View {
        if holiday.mark == "kinara" {
            Kinara().frame(width: size * 1.6, height: size * 1.1)
        } else if let m = holiday.mark {
            Image(systemName: m).font(.system(size: size * 0.95, weight: .bold)).foregroundStyle(holiday.colors[0] == .white ? Color.white : holiday.accentOnDark)
        }
    }
}

extension Holiday {
    /// The mark's colour on the dark splash: the first colour bright enough
    /// to show on it, else white.
    var accentOnDark: Color { Color(hexString: tab.first { UIColor(hexString: $0).luminance > 0.25 } ?? "#FFFFFF") }
}

/// Seven candles: three red, one black, three green, as on Marracat's splash.
struct Kinara: View {
    var body: some View {
        Canvas { ctx, size in
            let colors = ["#C8102E", "#C8102E", "#C8102E", "#0A0A0A", "#007A3D", "#007A3D", "#007A3D"]
            let w = size.width / 9, gap = w / 3, tallest = size.height * 0.75
            for (i, c) in colors.enumerated() {
                let h = i == 3 ? tallest : tallest * 0.8
                let x = CGFloat(i) * (w + gap)
                ctx.fill(Path(roundedRect: CGRect(x: x, y: size.height - h, width: w, height: h), cornerRadius: w * 0.18),
                         with: .color(Color(hexString: c)))
                ctx.fill(Path(ellipseIn: CGRect(x: x + w * 0.15, y: size.height - h - w * 1.1, width: w * 0.7, height: w)),
                         with: .color(Color(hexString: "#E8B000")))
            }
        }
    }
}

/// New Year's fireworks over the splash: bursts in the day's colours.
struct Fireworks: View {
    let colors: [Color]

    var body: some View {
        TimelineView(.animation) { tl in
            Canvas { ctx, size in
                let t = tl.date.timeIntervalSinceReferenceDate
                for burst in 0..<4 {
                    let period = 1.6, phase = (t + Double(burst) * 0.4).truncatingRemainder(dividingBy: period) / period
                    let seed = Double(Int((t + Double(burst) * 0.4) / period) * 7 + burst * 13)
                    let cx = size.width * (0.15 + 0.7 * abs(sin(seed * 1.7)))
                    let cy = size.height * (0.15 + 0.3 * abs(cos(seed * 2.3)))
                    let color = colors[(burst + Int(seed)) % colors.count]
                    for i in 0..<24 {
                        let a = Double(i) / 24 * 2 * .pi
                        let r = phase * 90
                        let p = CGPoint(x: cx + cos(a) * r, y: cy + sin(a) * r + phase * phase * 30)
                        ctx.fill(Path(ellipseIn: CGRect(x: p.x - 1.5, y: p.y - 1.5, width: 3, height: 3)),
                                 with: .color(color.opacity(1 - phase)))
                    }
                }
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}
