import SwiftUI

/// StreetEasy's visual system, transcribed from the reference recording,
/// recoloured 2026-09-09 to the app icon's teal (scripts/make_icon.py):
/// deep-teal chrome, teal links and CTAs, pale-teal selection fills,
/// hairline-bordered white cards on a light grey canvas, and a humanist
/// sans (Source Sans 3) set heavy.
enum SE {
    static let navy      = Color(hex: 0x163C47)
    static let navyDeep  = Color(hex: 0x0F2B33)
    /// Liquid Glass tint (2026-11-17, owner picked direction 1 of 5). Was
    /// 266676; 2A7889 still clears 4.5:1 on white and on F2F2F7.
    static let royal     = Color(hex: 0x2A7889)
    static let royalDark = Color(hex: 0x255F6C)
    /// The "Rent stabilized" card label — green reads as a good thing.
    static let green     = Color(hex: 0x1E8E3E)
    static let paleBlue  = Color(hex: 0xD6ECF0)
    static let paleBand  = Color(hex: 0xE6F3F5)
    static let ink       = Color(hex: 0x1A1A1A)
    static let ink2      = Color(hex: 0x4A4A4A)
    static let ink3      = Color(hex: 0x595959)   // was 6F6F6F; Apple's contrast audit failed it on white and canvas (2026-10-02)
    static let line      = Color(hex: 0xBDBDBD)
    static let lineSoft  = Color(hex: 0xE4E4E4)
    /// iOS grouped background (Liquid Glass, 2026-11-17). Was F2F2F2.
    static let canvas    = Color(hex: 0xF2F2F7)
    static let badge     = Color(hex: 0xE8E8E8)
    static let facts     = Color(hex: 0x1F2937)
    static let good      = Color(hex: 0x248A3D)
    static let warn      = Color(hex: 0xB25000)
    static let bad       = Color(hex: 0xB91C1C)
    /// The app icon's teal (scripts/make_icon.py MID/RIM), for the mark in the hero card.
    static let brand     = Color(hex: 0x3C7E8C)
    static let brandRim  = Color(hex: 0x285C69)
}

extension Color {
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
        self.background(Color.white)
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
