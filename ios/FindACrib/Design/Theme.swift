import SwiftUI

/// StreetEasy's visual system, transcribed from the reference recording:
/// navy chrome, royal-blue links and CTAs, pale-blue selection fills,
/// hairline-bordered white cards on a light grey canvas, and a humanist
/// sans (Source Sans 3) set heavy.
enum SE {
    static let navy      = Color(hex: 0x0E2A6E)
    static let navyDeep  = Color(hex: 0x0A1F52)
    static let royal     = Color(hex: 0x1B46E5)
    static let royalDark = Color(hex: 0x1338C2)
    /// The "Rent stabilized" card label — green reads as a good thing.
    static let green     = Color(hex: 0x1E8E3E)
    static let paleBlue  = Color(hex: 0xD8EAFB)
    static let paleBand  = Color(hex: 0xE6F2FC)
    static let ink       = Color(hex: 0x1A1A1A)
    static let ink2      = Color(hex: 0x4A4A4A)
    static let ink3      = Color(hex: 0x6F6F6F)
    static let line      = Color(hex: 0xBDBDBD)
    static let lineSoft  = Color(hex: 0xE4E4E4)
    static let canvas    = Color(hex: 0xF2F2F2)
    static let badge     = Color(hex: 0xE8E8E8)
    static let facts     = Color(hex: 0x1F2937)
    static let good      = Color(hex: 0x1E7B34)
    static let warn      = Color(hex: 0xB45309)
    static let bad       = Color(hex: 0xB91C1C)
    /// Find A Crib's own brand blue, kept for the mark in the hero card.
    static let brand     = Color(hex: 0x006AFF)
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
    /// Source Sans 3 at a fixed size; falls back to the system face if the
    /// bundle ever ships without the font rather than rendering nothing.
    static func se(_ size: CGFloat, _ weight: SEWeight = .regular) -> Font {
        if UIFont(name: weight.postScript, size: size) != nil {
            return .custom(weight.postScript, size: size)
        }
        return .system(size: size, weight: weight.fallback)
    }
}

extension View {
    func seText(_ size: CGFloat, _ weight: SEWeight = .regular, _ color: Color = SE.ink) -> some View {
        self.font(.se(size, weight)).foregroundStyle(color)
    }
    /// StreetEasy's cards: white, 1pt hairline, 2pt corner — flat, no shadow.
    func seCard() -> some View {
        self.background(Color.white)
            .clipShape(RoundedRectangle(cornerRadius: 2))
            .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.lineSoft, lineWidth: 1))
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
