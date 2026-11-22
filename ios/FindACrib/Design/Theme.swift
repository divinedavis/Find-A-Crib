import SwiftUI

/// StreetEasy's visual system, transcribed from the reference recording,
/// recoloured 2026-09-09 to the app icon's teal (scripts/make_icon.py):
/// deep-teal chrome, teal links and CTAs, pale-teal selection fills,
/// hairline-bordered white cards on a light grey canvas, and a humanist
/// sans (Source Sans 3) set heavy.
enum SE {
    /// `--dark` / `--light` pin the appearance, for screenshots and UI tests.
    /// Needed on iPad: XCUIDevice.shared.appearance does nothing on the iPad
    /// simulator (iPadOS 26.5, 2026-11-22: the tests set dark and the screen
    /// stayed light), so a test cannot ask the device. nil = follow the phone.
    static let forcedScheme: ColorScheme? = CommandLine.arguments.contains("--dark") ? .dark
        : (CommandLine.arguments.contains("--light") ? .light : nil)
    /// Is the app drawing dark right now? For the few places that are not a
    /// colour (which skyline to draw).
    static var isDark: Bool {
        // A pick in Profile › Appearance (or a test's --dark / --light) first;
        // with neither, whatever the phone is set to.
        if let scheme = Appearance.shared.scheme { return scheme == .dark }
        return UIScreen.main.traitCollection.userInterfaceStyle == .dark
    }

    // Every colour is a light/dark pair (dark mode, 2026-11-22). The light
    // values are the ones the app has always had; nothing changes in light.
    //
    // FILLS AND INKS ARE SEPARATE TOKENS. In light mode one teal works both
    // as a button fill under white text and as link text on a white card. No
    // single teal does both on a dark card: bright enough to read as text
    // (4.5:1 on 182023) is too bright to carry white text. So:
    //   royal / good / warn / bad          what you fill a shape with (white text sits on it)
    //   royalInk / goodInk / warnInk / badInk   text, icons and outlines
    // Same hex in light mode; in dark the fills keep their light value and the
    // inks step up. A new use picks by what it is, not by how it looks today.
    static let navy      = Color(light: 0x163C47, dark: 0x1D4E5B)
    static let navyDeep  = Color(light: 0x0F2B33, dark: 0x0B1F25)
    /// Navy as text (initials on a pale-blue avatar): navy is a fill.
    static let navyInk   = Color(light: 0x163C47, dark: 0x9FD8E3)
    /// Liquid Glass tint (2026-11-17, owner picked direction 1 of 5). Was
    /// 266676; 2A7889 still clears 4.5:1 on white and on F2F2F7, and white
    /// text clears 5:1 on it.
    static let royal     = Color(light: 0x2A7889, dark: 0x2A7889)
    static let royalInk  = Color(light: 0x2A7889, dark: 0x5FC4D8)
    static let royalDark = Color(light: 0x255F6C, dark: 0x255F6C)
    /// The "Rent stabilized" card label — green reads as a good thing.
    static let green     = Color(light: 0x1E8E3E, dark: 0x1E8E3E)
    static let paleBlue  = Color(light: 0xD6ECF0, dark: 0x1D3A42)
    static let paleBand  = Color(light: 0xE6F3F5, dark: 0x15292F)
    static let ink       = Color(light: 0x1A1A1A, dark: 0xF2F4F5)
    static let ink2      = Color(light: 0x4A4A4A, dark: 0xC6CCCF)
    static let ink3      = Color(light: 0x595959, dark: 0x9BA4A8)   // was 6F6F6F; Apple's contrast audit failed it on white and canvas (2026-10-02)
    static let line      = Color(light: 0xBDBDBD, dark: 0x465055)
    static let lineSoft  = Color(light: 0xE4E4E4, dark: 0x2A3337)
    /// iOS grouped background (Liquid Glass, 2026-11-17). Was F2F2F2.
    /// Dark: near-black with a little of the brand's teal in it.
    static let canvas    = Color(light: 0xF2F2F7, dark: 0x0B1012)
    /// What a card, a sheet row or a field is drawn on. White in light mode:
    /// use this, never Color.white, for anything text sits on.
    static let surface   = Color(light: 0xFFFFFF, dark: 0x182023)
    static let badge     = Color(light: 0xE8E8E8, dark: 0x2A3337)
    static let facts     = Color(light: 0x1F2937, dark: 0x1F2937)
    /// Kept at 1E7B34: Liquid Glass's 248A3D "nearly passed" Apple's
    /// contrast audit on its pale green chips (2026-11-17).
    static let good      = Color(light: 0x1E7B34, dark: 0x1E7B34)
    static let goodInk   = Color(light: 0x1E7B34, dark: 0x4CC273)
    static let warn      = Color(light: 0xB25000, dark: 0xB25000)
    static let warnInk   = Color(light: 0xB25000, dark: 0xF0A04B)
    static let bad       = Color(light: 0xB91C1C, dark: 0xB91C1C)
    static let badInk    = Color(light: 0xB91C1C, dark: 0xF87171)
    /// Pale chips behind goodInk / warnInk text ("Open", "First come, first served").
    static let goodWash  = Color(light: 0xDCFCE7, dark: 0x163524)
    static let warnWash  = Color(light: 0xFFF0E0, dark: 0x3A2A14)
    /// Find A Crib Plus: the promo card, its bolt, and the "First month" tag.
    static let plusWash  = Color(light: 0xF3EEFF, dark: 0x251D3D)
    static let plusInk   = Color(light: 0x5B21B6, dark: 0xB79CF5)
    static let mintWash  = Color(light: 0xDCFCE7, dark: 0x163524)
    static let mintInk   = Color(light: 0x14532D, dark: 0x86E3A8)
    /// A switch that is off.
    static let switchOff = Color(light: 0xE3E3E8, dark: 0x3A3F42)
    /// The pill behind the selected tab.
    static let tabOn     = Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(white: 1, alpha: 0.14) : UIColor(white: 1, alpha: 0.7) })
    /// The tint on clear glass (Map pill, tab bar): milky in light mode, smoky in dark.
    static let glassTint = Color(UIColor { $0.userInterfaceStyle == .dark ? UIColor(white: 0.06, alpha: 0.50) : UIColor(white: 1, alpha: 0.35) })
    /// The app icon's teal (scripts/make_icon.py MID/RIM), for the mark in the hero card.
    static let brand     = Color(hex: 0x3C7E8C)
    static let brandRim  = Color(hex: 0x285C69)
}

extension Color {
    /// A colour that follows the system appearance.
    init(light: UInt32, dark: UInt32) {
        self.init(UIColor { $0.userInterfaceStyle == .dark ? UIColor(Color(hex: dark)) : UIColor(Color(hex: light)) })
    }
    init(hex: UInt32) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: 1)
    }
}

enum SEWeight { case regular, semibold, bold, black
    var postScript: String {
        switch self {
        case .regular:  return "SourceSans3-Regular"
        case .semibold: return "SourceSans3-Semibold"
        case .bold:     return "SourceSans3-Bold"
        case .black:    return "SourceSans3-Black"
        }
    }
    var fallback: Font.Weight {
        switch self { case .regular: .regular; case .semibold: .semibold; case .bold: .bold; case .black: .black }
    }
}

extension Font {
    /// SF Pro, the system face (Liquid Glass redesign, owner 2026-11-17: was
    /// Source Sans 3). Every text style in the app goes through here, so the
    /// whole app changed face in one place. SF runs wider than Source Sans,
    /// so sizes step down a little to keep lines that fit still fitting.
    static func se(_ size: CGFloat, _ weight: SEWeight = .regular) -> Font {
        .system(size: (size * 0.94).rounded(), weight: weight.fallback)
    }
}

extension View {
    func seText(_ size: CGFloat, _ weight: SEWeight = .regular, _ color: Color = SE.ink) -> some View {
        self.font(.se(size, weight)).foregroundStyle(color)
    }
    /// Liquid Glass cards (2026-11-17): white on the grouped grey, 22 pt
    /// continuous corners, no hairline. Was StreetEasy's flat 2 pt card.
    func seCard() -> some View {
        self.background(SE.surface)
            .clipShape(RoundedRectangle(cornerRadius: 22, style: .continuous))
    }
}

struct Formatters {
    static let money: NumberFormatter = {
        let f = NumberFormatter(); f.numberStyle = .currency; f.currencyCode = "USD"; f.maximumFractionDigits = 0
        return f
    }()
    static func dollars(_ n: Int) -> String { money.string(from: NSNumber(value: n)) ?? "$\(n)" }
    /// "$1k" / "$3.5k" — the shorthand in StreetEasy's results header.
    static func short(_ n: Int) -> String {
        if n >= 1000 {
            let k = Double(n) / 1000
            return k == k.rounded() ? "$\(Int(k))k" : String(format: "$%.1fk", k)
        }
        return "$\(n)"
    }
    static let mdy: DateFormatter = { let f = DateFormatter(); f.dateFormat = "M/d/yy"; return f }()
    static let long: DateFormatter = { let f = DateFormatter(); f.dateStyle = .medium; return f }()
}
