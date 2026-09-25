import SwiftUI

// StreetEasy paints a row of brownstones under its results filter bar; when
// the list is pulled past its top (the scroll view's bounce) the row rides
// down with it and a navy night sky with a crescent moon shows above. Ours is
// the same idea with each city's landmarks: the band is the first row of the
// scroll content, the sky is the scroll view's background. Both are drawn with
// Canvas from the palette in Theme.swift — no image assets, so it scales and
// recolours with the app. Nothing here is interactive.

/// The landmark set for a city and the deterministic pieces the tests pin.
enum Skyline {
    enum Scene: String, CaseIterable {
        case newYork, sanFrancisco, washington, losAngeles, chicago, miami, atlanta, philadelphia, homes

        /// One scene per city; anything unknown gets New York, like `City.find`.
        static func scene(for cityID: String) -> Scene {
            switch cityID {
            case "sf": .sanFrancisco
            case "dc": .washington
            case "la": .losAngeles
            // The income-restricted cities (owner, 2026-09-24: "for the
            // other cities there should be landmarks too with the animations").
            case "chi": .chicago
            case "mia": .miami
            case "atl": .atlanta
            case "phl": .philadelphia
            default: .newYork
            }
        }

        /// The landmarks, left to right, as fractions of the band width.
        var landmarks: [Landmark] {
            switch self {
            case .newYork: [
                Landmark("Brooklyn Bridge", x: 0.17, draw: Draw.brooklynBridge),
                Landmark("One World Trade Center", x: 0.42, draw: Draw.oneWTC),
                Landmark("Empire State Building", x: 0.55, draw: Draw.empireState),
                Landmark("One Times Square", x: 0.68, draw: Draw.timesSquare),
                Landmark("Statue of Liberty", x: 0.88, draw: Draw.statueOfLiberty),
            ]
            case .sanFrancisco: [
                Landmark("Golden Gate Bridge", x: 0.2, draw: Draw.goldenGate),
                Landmark("Painted Ladies", x: 0.47, draw: Draw.paintedLadies),
                Landmark("Transamerica Pyramid", x: 0.66, draw: Draw.transamerica),
                Landmark("Coit Tower", x: 0.8, draw: Draw.coitTower),
                Landmark("Sutro Tower", x: 0.93, draw: Draw.sutroTower),
            ]
            case .washington: [
                Landmark("Lincoln Memorial", x: 0.14, draw: Draw.lincolnMemorial),
                Landmark("Washington Monument", x: 0.36, draw: Draw.washingtonMonument),
                Landmark("US Capitol", x: 0.6, draw: Draw.capitol),
                Landmark("Jefferson Memorial", x: 0.86, draw: Draw.jeffersonMemorial),
            ]
            case .chicago: [
                Landmark("Navy Pier Centennial Wheel", x: 0.13, draw: Draw.navyPierWheel),
                Landmark("Willis Tower", x: 0.34, draw: Draw.willisTower),
                Landmark("Cloud Gate", x: 0.52, draw: Draw.cloudGate),
                Landmark("875 North Michigan (Hancock)", x: 0.7, draw: Draw.hancockCenter),
                Landmark("Marina City", x: 0.89, draw: Draw.marinaCity),
            ]
            case .miami: [
                Landmark("Palm trees", x: 0.1, draw: Draw.palms),
                Landmark("Freedom Tower", x: 0.3, draw: Draw.freedomTower),
                Landmark("Art Deco hotel", x: 0.5, draw: Draw.artDecoHotel),
                Landmark("Brickell towers", x: 0.7, draw: Draw.brickellTowers),
                Landmark("Lifeguard stand", x: 0.9, draw: Draw.lifeguardStand),
            ]
            case .atlanta: [
                Landmark("SkyView Atlanta", x: 0.12, draw: Draw.skyViewWheel),
                Landmark("Georgia State Capitol", x: 0.32, draw: Draw.georgiaCapitol),
                Landmark("Bank of America Plaza", x: 0.52, draw: Draw.bankOfAmericaPlaza),
                Landmark("Westin Peachtree Plaza", x: 0.7, draw: Draw.westinPeachtree),
                Landmark("Mercedes-Benz Stadium", x: 0.89, draw: Draw.mercedesBenzStadium),
            ]
            case .philadelphia: [
                Landmark("Boathouse Row", x: 0.12, draw: Draw.boathouseRow),
                Landmark("Philadelphia Museum of Art", x: 0.32, draw: Draw.artMuseum),
                Landmark("City Hall", x: 0.5, draw: Draw.phillyCityHall),
                Landmark("Comcast Technology Center", x: 0.7, draw: Draw.comcastTower),
                Landmark("Liberty Bell", x: 0.9, draw: Draw.libertyBell),
            ]
            case .homes: [
                Landmark("Garden apartments", x: 0.16, draw: Draw.gardenApartments),
                Landmark("Row houses", x: 0.4, draw: Draw.rowHouses),
                Landmark("Mid-rise apartments", x: 0.64, draw: Draw.midrise),
                Landmark("Water tower", x: 0.88, draw: Draw.waterTower),
            ]
            case .losAngeles: [
                Landmark("Hollywood Sign", x: 0.16, draw: Draw.hollywoodSign),
                Landmark("Griffith Observatory", x: 0.4, draw: Draw.griffith),
                Landmark("US Bank Tower", x: 0.6, draw: Draw.usBankTower),
                Landmark("Capitol Records", x: 0.72, draw: Draw.capitolRecords),
                Landmark("Palm trees", x: 0.9, draw: Draw.palms),
            ]
            }
        }
    }

    struct Landmark {
        let name: String
        /// Centre, as a fraction of the band width.
        let x: CGFloat
        let draw: (inout GraphicsContext, Pen) -> Void
        init(_ name: String, x: CGFloat, draw: @escaping (inout GraphicsContext, Pen) -> Void) {
            self.name = name; self.x = x; self.draw = draw
        }
    }

    /// Height of the band under the filter bar. The landmarks are drawn in a
    /// 100-unit-tall space scaled to this, so they keep their proportions on
    /// every phone width.
    static let bandHeight: CGFloat = 64
    /// How much sky is drawn above the band; a pull rarely reveals more.
    static let skyHeight: CGFloat = 260

    // MARK: Colours — the teal family from the app icon (Theme.swift)

    static let skyTop    = SE.navyDeep
    static let skyBottom = SE.navy
    static let far       = Color(hex: 0x214F5C)
    static let near      = SE.royal
    static let lit       = SE.paleBlue
    static let ground    = Color(hex: 0x1B4653)

    // MARK: Deterministic pseudo-randomness (stars, windows, blinking)

    /// A tiny hash so the same star or window always lands in the same place
    /// and blinks on the same beat, run after run — the tests rely on that.
    static func noise(_ a: Int, _ b: Int = 0) -> Double {
        var h = UInt64(bitPattern: Int64(a)) &* 0x9E37_79B9_7F4A_7C15
        h ^= UInt64(bitPattern: Int64(b)) &+ 0x632B_E59B_D9B4_E019
        h ^= h >> 31; h &*= 0xBF58_476D_1CE4_E5B9; h ^= h >> 29
        return Double(h % 10_000) / 10_000
    }

    /// Whether window `id` is lit at time `t`. Most windows are on; each one
    /// re-rolls every ~1.6 s on its own offset, so the row flickers the way a
    /// block does at night rather than all at once.
    static func windowLit(id: Int, at t: TimeInterval) -> Bool {
        let beat = Int((t / 1.6 + noise(id, 7)).rounded(.down))
        return noise(id, beat) < 0.72
    }

    /// Star positions for a sky of the given size, spread over its top so the
    /// first pull already shows a few. `count` scales with width.
    static func stars(in size: CGSize) -> [(x: CGFloat, y: CGFloat, r: CGFloat, phase: Double)] {
        let n = max(18, Int(size.width / 14))
        return (0..<n).map { i in
            (x: CGFloat(noise(i, 1)) * size.width,
             y: 6 + CGFloat(noise(i, 2)) * (size.height - 40),
             r: 0.6 + CGFloat(noise(i, 3)) * 1.1,
             phase: noise(i, 4) * .pi * 2)
        }
    }
}

// MARK: - Pen: a landmark's local coordinate system

/// Draws polygons in a landmark's own space — x centred on the landmark,
/// y up from the ground, both in band units (band = 100 tall) — so each
/// landmark is written once at one size and lands anywhere.
struct Pen {
    let cx: CGFloat        // centre x, in points
    let ground: CGFloat    // baseline y, in points
    let u: CGFloat         // points per unit
    let time: TimeInterval
    let animated: Bool

    func p(_ x: CGFloat, _ y: CGFloat) -> CGPoint { CGPoint(x: cx + x * u, y: ground - y * u) }

    func poly(_ pts: [(CGFloat, CGFloat)]) -> Path {
        var path = Path()
        guard let f = pts.first else { return path }
        path.move(to: p(f.0, f.1))
        for q in pts.dropFirst() { path.addLine(to: p(q.0, q.1)) }
        path.closeSubpath()
        return path
    }
    func rect(x: CGFloat, y: CGFloat, w: CGFloat, h: CGFloat) -> Path {
        Path(CGRect(x: cx + (x - w / 2) * u, y: ground - (y + h) * u, width: w * u, height: h * u))
    }
    func circle(x: CGFloat, y: CGFloat, r: CGFloat) -> Path {
        Path(ellipseIn: CGRect(x: cx + (x - r) * u, y: ground - (y + r) * u, width: 2 * r * u, height: 2 * r * u))
    }
    /// A dome: the top half of an ellipse sitting on y.
    func dome(x: CGFloat, y: CGFloat, w: CGFloat, h: CGFloat) -> Path {
        var path = Path()
        path.move(to: p(x - w / 2, y))
        path.addQuadCurve(to: p(x + w / 2, y), control: p(x, y + 2 * h))
        path.closeSubpath()
        return path
    }
    /// A quadratic curve from a to b sagging (or rising) through the control point.
    func curve(_ a: (CGFloat, CGFloat), _ b: (CGFloat, CGFloat), via c: (CGFloat, CGFloat)) -> Path {
        var path = Path()
        path.move(to: p(a.0, a.1))
        path.addQuadCurve(to: p(b.0, b.1), control: p(c.0, c.1))
        return path
    }
    func line(_ a: (CGFloat, CGFloat), _ b: (CGFloat, CGFloat)) -> Path {
        var path = Path(); path.move(to: p(a.0, a.1)); path.addLine(to: p(b.0, b.1)); return path
    }

    /// A column of windows on a building face; each blinks on its own beat.
    func windows(_ ctx: inout GraphicsContext, id: Int, x: CGFloat, y: CGFloat, cols: Int, rows: Int, pitch: CGFloat = 5, size: CGFloat = 2.2) {
        for r in 0..<rows {
            for c in 0..<cols {
                let wid = id &* 131 &+ r * 17 &+ c
                let on = animated ? Skyline.windowLit(id: wid, at: time) : Skyline.noise(wid, 9) < 0.72
                guard on else { continue }
                let wx = x + (CGFloat(c) - CGFloat(cols - 1) / 2) * pitch
                ctx.fill(rect(x: wx, y: y + CGFloat(r) * pitch, w: size, h: size), with: .color(Skyline.lit.opacity(0.85)))
            }
        }
    }
}

// MARK: - The landmarks

enum Draw {
    private static var near: GraphicsContext.Shading { .color(Skyline.near) }
    private static var far: GraphicsContext.Shading { .color(Skyline.far) }
    private static var lit: GraphicsContext.Shading { .color(Skyline.lit) }

    // New York ------------------------------------------------------------

    static func brooklynBridge(_ c: inout GraphicsContext, _ k: Pen) {
        // Two granite towers with their pointed double arches, the deck, the
        // main cables sagging between and the suspenders hanging off them.
        for tx: CGFloat in [-45, 45] {
            c.fill(k.poly([(tx - 13, 0), (tx + 13, 0), (tx + 11, 62), (tx - 11, 62)]), with: near)
            for ax in [tx - 5.5, tx + 5.5] {
                var arch = Path()
                arch.move(to: k.p(ax - 3.2, 18)); arch.addLine(to: k.p(ax - 3.2, 46))
                arch.addLine(to: k.p(ax, 52)); arch.addLine(to: k.p(ax + 3.2, 46)); arch.addLine(to: k.p(ax + 3.2, 18)); arch.closeSubpath()
                c.fill(arch, with: .color(Skyline.skyBottom))
            }
        }
        c.fill(k.rect(x: 0, y: 14, w: 190, h: 3), with: near)
        for (a, b, sag) in [((-95, 30), (-45, 60), (-70, 22)), ((-45, 60), (45, 60), (0, 24)), ((45, 60), (95, 30), (70, 22))] as [((CGFloat, CGFloat), (CGFloat, CGFloat), (CGFloat, CGFloat))] {
            c.stroke(k.curve(a, b, via: sag), with: near, lineWidth: max(1, 1.2 * k.u))
        }
        var x: CGFloat = -88
        while x <= 88 {
            if abs(abs(x) - 45) > 12 {
                let y: CGFloat = abs(x) < 45 ? 42 - 24 * (1 - (x * x) / 2025) : 45 - 15 * (1 - ((abs(x) - 95) * (abs(x) - 95)) / 2500)
                c.stroke(k.line((x, 17), (x, y)), with: .color(Skyline.near.opacity(0.7)), lineWidth: max(0.5, 0.6 * k.u))
            }
            x += 8
        }
    }

    static func oneWTC(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.poly([(-9, 0), (9, 0), (7, 74), (-7, 74)]), with: near)
        c.fill(k.poly([(-4, 74), (4, 74), (1.5, 78), (-1.5, 78)]), with: near)
        c.fill(k.rect(x: 0, y: 78, w: 1.2, h: 16), with: near)
        c.fill(k.rect(x: 0, y: 6, w: 12, h: 5), with: far)
        k.windows(&c, id: 11, x: 0, y: 14, cols: 2, rows: 10, pitch: 5.5, size: 1.8)
    }

    static func empireState(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.rect(x: 0, y: 0, w: 34, h: 14), with: near)
        c.fill(k.rect(x: 0, y: 14, w: 24, h: 30), with: near)
        c.fill(k.rect(x: 0, y: 44, w: 16, h: 22), with: near)
        c.fill(k.rect(x: 0, y: 66, w: 10, h: 10), with: near)
        c.fill(k.poly([(-4, 76), (4, 76), (1.5, 84), (-1.5, 84)]), with: near)
        c.fill(k.rect(x: 0, y: 84, w: 1.2, h: 12), with: near)
        k.windows(&c, id: 12, x: 0, y: 17, cols: 3, rows: 5, pitch: 5.2, size: 2)
        k.windows(&c, id: 13, x: 0, y: 47, cols: 2, rows: 3, pitch: 5.2, size: 2)
    }

    static func timesSquare(_ c: inout GraphicsContext, _ k: Pen) {
        // One Times Square: the narrow wedge under the New Year's ball, faced
        // with billboards that flicker through their loop, and the low
        // theatre blocks either side with their marquees.
        c.fill(k.rect(x: -20, y: 0, w: 18, h: 22), with: far)
        c.fill(k.rect(x: 20, y: 0, w: 18, h: 18), with: far)
        c.fill(k.rect(x: -20, y: 9, w: 14, h: 3), with: .color(Skyline.lit.opacity(k.animated && Int(k.time * 3) % 2 == 0 ? 0.9 : 0.5)))
        c.fill(k.rect(x: 20, y: 8, w: 14, h: 3), with: .color(Skyline.lit.opacity(k.animated && Int(k.time * 3) % 2 == 1 ? 0.9 : 0.5)))
        c.fill(k.poly([(-8, 0), (8, 0), (6, 60), (-6, 60)]), with: near)
        for i in 0..<5 {
            let beat = Int((k.time + Double(i) * 0.7) / 1.1)
            let on = !k.animated || Skyline.noise(60 + i, beat) < 0.8
            c.fill(k.rect(x: 0, y: 6 + CGFloat(i) * 10, w: 9, h: 6), with: .color(Skyline.lit.opacity(on ? 0.85 : 0.2)))
        }
        c.fill(k.rect(x: 0, y: 60, w: 1.2, h: 16), with: near)
        c.fill(k.circle(x: 0, y: 77, r: 2.6), with: .color(Skyline.lit.opacity(k.animated ? 0.6 + 0.4 * sin(k.time * 4) : 1)))
    }

    static func chrysler(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.rect(x: 0, y: 0, w: 20, h: 46), with: near)
        // the crown: tiers of arches drawn as narrowing stacked slabs
        var w: CGFloat = 18, y: CGFloat = 46
        for _ in 0..<5 { c.fill(k.poly([(-w / 2, y), (w / 2, y), (w / 2 - 2, y + 5), (-w / 2 + 2, y + 5)]), with: near); w -= 3.2; y += 5 }
        c.fill(k.poly([(-1.6, y), (1.6, y), (0, y + 15)]), with: near)
        k.windows(&c, id: 14, x: 0, y: 6, cols: 3, rows: 7, pitch: 5, size: 1.9)
    }

    static func statueOfLiberty(_ c: inout GraphicsContext, _ k: Pen) {
        // star-fort base, pedestal, robed figure, crown, torch arm and tablet
        c.fill(k.poly([(-26, 0), (26, 0), (20, 8), (-20, 8)]), with: far)
        c.fill(k.poly([(-14, 8), (14, 8), (11, 30), (-11, 30)]), with: near)
        c.fill(k.rect(x: 0, y: 30, w: 24, h: 3), with: near)
        c.fill(k.poly([(-9, 33), (9, 33), (6, 62), (-6, 62)]), with: near)
        c.fill(k.rect(x: 0, y: 62, w: 8, h: 4), with: near)
        c.fill(k.circle(x: 0, y: 70, r: 4.2), with: near)
        for i in 0..<7 {
            let a = CGFloat(i) / 6 * .pi
            let bx = cos(a) * 4, by = 70 + sin(a) * 4
            c.fill(k.poly([(bx - 1, by - 0.5), (bx + 1, by - 0.5), (cos(a) * 9.5, 70 + sin(a) * 9.5)]), with: near)
        }
        c.fill(k.poly([(4, 52), (8, 50), (10.5, 80), (7.5, 80)]), with: near)      // torch arm
        c.fill(k.rect(x: 9, y: 80, w: 4, h: 3), with: near)
        c.fill(k.circle(x: 9, y: 85, r: 2.4), with: lit)                             // the flame
        c.fill(k.poly([(-14, 44), (-6, 46), (-6, 56), (-14, 54)]), with: near)      // tablet
        k.windows(&c, id: 15, x: 0, y: 12, cols: 3, rows: 2, pitch: 6, size: 2.2)
    }

    // San Francisco -------------------------------------------------------

    static func goldenGate(_ c: inout GraphicsContext, _ k: Pen) {
        for tx: CGFloat in [-48, 48] {
            for lx in [tx - 5, tx + 5] { c.fill(k.rect(x: lx, y: 0, w: 4, h: 78), with: near) }
            for y: CGFloat in [22, 40, 56, 70] { c.fill(k.rect(x: tx, y: y, w: 14, h: 3.5), with: near) }
        }
        c.fill(k.rect(x: 0, y: 20, w: 200, h: 3), with: near)
        for (a, b, sag) in [((-100, 40), (-48, 76), (-74, 24)), ((-48, 76), (48, 76), (0, 26)), ((48, 76), (100, 40), (74, 24))] as [((CGFloat, CGFloat), (CGFloat, CGFloat), (CGFloat, CGFloat))] {
            c.stroke(k.curve(a, b, via: sag), with: near, lineWidth: max(1, 1.3 * k.u))
        }
        var x: CGFloat = -92
        while x <= 92 {
            if abs(abs(x) - 48) > 9 {
                let y: CGFloat = abs(x) < 48 ? 51 - 25 * (1 - (x * x) / 2304) : 58 - 18 * (1 - ((abs(x) - 100) * (abs(x) - 100)) / 2704)
                c.stroke(k.line((x, 23), (x, y)), with: .color(Skyline.near.opacity(0.7)), lineWidth: max(0.5, 0.6 * k.u))
            }
            x += 8
        }
    }

    static func paintedLadies(_ c: inout GraphicsContext, _ k: Pen) {
        // the Alamo Square row: narrow Victorians with bay windows and gables
        for i in 0..<4 {
            let x = CGFloat(i - 2) * 18 + 9
            c.fill(k.rect(x: x, y: 0, w: 16, h: 30), with: i % 2 == 0 ? near : far)
            c.fill(k.poly([(x - 9, 30), (x + 9, 30), (x, 42)]), with: i % 2 == 0 ? near : far)
            c.fill(k.rect(x: x, y: 8, w: 7, h: 20), with: i % 2 == 0 ? far : near)   // the bay
            k.windows(&c, id: 20 + i, x: x, y: 11, cols: 1, rows: 3, pitch: 5.5, size: 2.4)
        }
    }

    static func transamerica(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.poly([(-14, 0), (14, 0), (1.5, 82), (-1.5, 82)]), with: near)
        c.fill(k.rect(x: 0, y: 82, w: 1, h: 10), with: near)
        c.fill(k.poly([(-6, 30), (-3, 30), (-3, 70), (-5, 66)]), with: far)        // the east wing
        k.windows(&c, id: 25, x: 0, y: 6, cols: 3, rows: 6, pitch: 4.6, size: 1.5)
    }

    static func coitTower(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.poly([(-22, 0), (22, 0), (14, 12), (-14, 12)]), with: far)          // Telegraph Hill
        c.fill(k.rect(x: 0, y: 12, w: 10, h: 44), with: near)
        c.fill(k.poly([(-7, 56), (7, 56), (5, 62), (-5, 62)]), with: near)
        k.windows(&c, id: 26, x: 0, y: 56, cols: 3, rows: 1, pitch: 3.2, size: 1.4)
    }

    static func sutroTower(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.poly([(-30, 0), (30, 0), (18, 16), (-18, 16)]), with: far)          // Twin Peaks
        c.fill(k.poly([(-9, 16), (9, 16), (3, 48), (-3, 48)]), with: near)
        for x: CGFloat in [-9, 0, 9] { c.fill(k.rect(x: x, y: 48, w: 1.6, h: 40), with: near) }
        c.fill(k.rect(x: 0, y: 58, w: 20, h: 1.6), with: near)
        c.fill(k.rect(x: 0, y: 72, w: 20, h: 1.6), with: near)
        c.fill(k.circle(x: 9, y: 88, r: 1.3), with: .color(Color.red.opacity(k.animated && Int(k.time * 2) % 2 == 0 ? 0.95 : 0.35)))
    }

    // Washington ----------------------------------------------------------

    static func lincolnMemorial(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.rect(x: 0, y: 0, w: 70, h: 7), with: far)
        c.fill(k.rect(x: 0, y: 7, w: 62, h: 4), with: near)
        for i in 0..<9 { c.fill(k.rect(x: CGFloat(i - 4) * 7, y: 11, w: 2.6, h: 20), with: near) }
        c.fill(k.rect(x: 0, y: 31, w: 62, h: 5), with: near)
        c.fill(k.rect(x: 0, y: 36, w: 56, h: 4), with: near)
        c.fill(k.rect(x: 0, y: 20, w: 7, h: 11), with: lit)                          // the lit chamber
    }

    static func washingtonMonument(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.poly([(-6, 0), (6, 0), (3.6, 76), (-3.6, 76)]), with: near)
        c.fill(k.poly([(-3.6, 76), (3.6, 76), (0, 88)]), with: near)
        c.fill(k.rect(x: 0, y: 0, w: 60, h: 3), with: far)
        c.fill(k.circle(x: 0, y: 87, r: 1.1), with: .color(Color.red.opacity(k.animated && Int(k.time) % 2 == 0 ? 0.95 : 0.3)))
    }

    static func capitol(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.rect(x: 0, y: 0, w: 120, h: 14), with: far)                          // the wings
        for i in 0..<12 { c.fill(k.rect(x: CGFloat(i) * 9 - 50, y: 14, w: 2, h: 8), with: far) }
        c.fill(k.rect(x: 0, y: 22, w: 120, h: 3), with: far)
        c.fill(k.rect(x: 0, y: 0, w: 46, h: 28), with: near)                          // centre block
        c.fill(k.rect(x: 0, y: 28, w: 30, h: 8), with: near)                          // the drum
        for i in 0..<7 { c.fill(k.rect(x: CGFloat(i - 3) * 4.5, y: 36, w: 1.8, h: 9), with: near) }
        c.fill(k.rect(x: 0, y: 45, w: 30, h: 3), with: near)
        c.fill(k.dome(x: 0, y: 48, w: 30, h: 16), with: near)
        c.fill(k.rect(x: 0, y: 63, w: 5, h: 5), with: near)
        c.fill(k.rect(x: 0, y: 68, w: 1.6, h: 6), with: near)                         // Freedom
        k.windows(&c, id: 30, x: 0, y: 4, cols: 5, rows: 3, pitch: 6, size: 2.2)
    }

    static func jeffersonMemorial(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.rect(x: 0, y: 0, w: 60, h: 8), with: far)
        c.fill(k.rect(x: 0, y: 8, w: 44, h: 4), with: near)
        for i in 0..<7 { c.fill(k.rect(x: CGFloat(i - 3) * 6.5, y: 12, w: 2.4, h: 16), with: near) }
        c.fill(k.rect(x: 0, y: 28, w: 44, h: 4), with: near)
        c.fill(k.dome(x: 0, y: 32, w: 40, h: 16), with: near)
        c.fill(k.rect(x: 0, y: 16, w: 6, h: 12), with: lit)
    }

    // Los Angeles ---------------------------------------------------------

    static func hollywoodSign(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.poly([(-70, 0), (70, 0), (52, 22), (20, 34), (-14, 36), (-46, 26)]), with: far)   // Mount Lee
        let text = Text("HOLLYWOOD").font(.system(size: 9.5 * k.u, weight: .heavy, design: .default)).kerning(0.3 * k.u)
            .foregroundStyle(Color.white.opacity(0.92))
        c.draw(c.resolve(text), at: k.p(-2, 40), anchor: .center)
    }

    static func griffith(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.poly([(-60, 0), (60, 0), (40, 14), (-40, 14)]), with: far)           // the hill
        c.fill(k.rect(x: 0, y: 14, w: 64, h: 12), with: near)
        c.fill(k.rect(x: 0, y: 26, w: 26, h: 8), with: near)
        c.fill(k.dome(x: 0, y: 34, w: 24, h: 10), with: near)
        c.fill(k.dome(x: -25, y: 26, w: 12, h: 5), with: near)
        c.fill(k.dome(x: 25, y: 26, w: 12, h: 5), with: near)
        k.windows(&c, id: 40, x: 0, y: 17, cols: 7, rows: 1, pitch: 7, size: 2.4)
    }

    static func usBankTower(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.rect(x: 0, y: 0, w: 22, h: 68), with: near)
        c.fill(k.poly([(-11, 68), (11, 68), (8, 74), (-8, 74)]), with: near)
        c.fill(k.rect(x: 0, y: 74, w: 14, h: 4), with: near)
        c.fill(k.rect(x: 0, y: 78, w: 1, h: 6), with: near)
        c.fill(k.rect(x: 18, y: 0, w: 14, h: 40), with: far)                           // a neighbour
        c.fill(k.rect(x: -20, y: 0, w: 12, h: 30), with: far)
        k.windows(&c, id: 41, x: 0, y: 6, cols: 3, rows: 9, pitch: 5, size: 1.9)
    }

    static func capitolRecords(_ c: inout GraphicsContext, _ k: Pen) {
        // the stack of records with the needle on top
        for i in 0..<11 {
            let y = CGFloat(i) * 4
            c.fill(k.rect(x: 0, y: y, w: i % 2 == 0 ? 22 : 18, h: 3.2), with: i % 2 == 0 ? near : far)
        }
        c.fill(k.rect(x: 0, y: 44, w: 6, h: 4), with: near)
        c.fill(k.rect(x: 0, y: 48, w: 1.2, h: 22), with: near)
        c.fill(k.circle(x: 0, y: 70, r: 1.3), with: .color(Color.red.opacity(k.animated && Int(k.time * 2) % 2 == 0 ? 0.95 : 0.3)))
    }

    // Chicago -------------------------------------------------------------

    /// A Ferris wheel whose spokes and cars turn; shared by Navy Pier and SkyView.
    private static func wheel(_ c: inout GraphicsContext, _ k: Pen, r: CGFloat, hub: CGFloat, cars: Int, speed: Double) {
        c.fill(k.poly([(-2, 0), (2, 0), (0.6, hub), (-0.6, hub)]), with: near)
        c.fill(k.poly([(-10, 0), (-8, 0), (0.4, hub), (-0.4, hub)]), with: near)
        c.fill(k.poly([(8, 0), (10, 0), (0.4, hub), (-0.4, hub)]), with: near)
        var rim = Path(); rim.addEllipse(in: CGRect(x: k.cx - r * k.u, y: k.ground - (hub + r) * k.u, width: 2 * r * k.u, height: 2 * r * k.u))
        c.stroke(rim, with: near, lineWidth: max(1, 1.4 * k.u))
        let turn = k.animated ? k.time * speed : 0
        for i in 0..<cars {
            let a = Double(i) / Double(cars) * 2 * .pi + turn
            let x = CGFloat(cos(a)) * r, y = hub + CGFloat(sin(a)) * r
            c.stroke(k.line((0, hub), (x, y)), with: .color(Skyline.near.opacity(0.7)), lineWidth: max(0.5, 0.5 * k.u))
            let lit = !k.animated || Skyline.noise(i, Int(k.time / 1.3)) < 0.8
            c.fill(k.circle(x: x, y: y - 1.8, r: 1.5), with: .color(Skyline.lit.opacity(lit ? 0.85 : 0.3)))
        }
    }

    static func navyPierWheel(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.rect(x: 0, y: 0, w: 44, h: 4), with: far)                              // the pier
        wheel(&c, k, r: 18, hub: 26, cars: 12, speed: 0.25)
    }

    static func willisTower(_ c: inout GraphicsContext, _ k: Pen) {
        // the bundled tubes stepping back, and the two white antennas
        c.fill(k.rect(x: -8, y: 0, w: 8, h: 50), with: near)
        c.fill(k.rect(x: 8, y: 0, w: 8, h: 58), with: near)
        c.fill(k.rect(x: 0, y: 0, w: 8, h: 74), with: near)
        c.fill(k.rect(x: -3, y: 74, w: 8, h: 6), with: near)
        for ax: CGFloat in [-3, 3] {
            c.fill(k.rect(x: ax, y: 80, w: 1.1, h: 14), with: near)
            c.fill(k.circle(x: ax, y: 94.5, r: 1.1), with: .color(Color.red.opacity(k.animated && Int(k.time * 1.5 + Double(ax)) % 2 == 0 ? 0.95 : 0.35)))
        }
        k.windows(&c, id: 110, x: 0, y: 6, cols: 2, rows: 12, pitch: 5, size: 1.8)
        k.windows(&c, id: 111, x: -8, y: 6, cols: 2, rows: 8, pitch: 5, size: 1.8)
    }

    static func cloudGate(_ c: inout GraphicsContext, _ k: Pen) {
        // the Bean: a mirrored bulge with a sheen that slides across it
        c.fill(k.rect(x: 0, y: 0, w: 40, h: 2), with: far)                              // the plaza
        var bean = Path()
        bean.move(to: k.p(-17, 2))
        bean.addCurve(to: k.p(17, 2), control1: k.p(-24, 22), control2: k.p(24, 22))
        bean.addQuadCurve(to: k.p(-17, 2), control: k.p(0, 7))
        c.fill(bean, with: near)
        let sx: CGFloat = k.animated ? CGFloat(sin(k.time * 0.6)) * 10 : -4
        c.fill(k.circle(x: sx, y: 12, r: 2.4), with: .color(Skyline.lit.opacity(0.55)))
    }

    static func hancockCenter(_ c: inout GraphicsContext, _ k: Pen) {
        // the tapered black tower with its X-braces and two masts
        c.fill(k.poly([(-11, 0), (11, 0), (7, 70), (-7, 70)]), with: near)
        for y: CGFloat in stride(from: 4, through: 58, by: 18) {
            let w0 = 11 - y * 4 / 70, w1 = 11 - (y + 18) * 4 / 70
            c.stroke(k.line((-w0, y), (w1, y + 18)), with: far, lineWidth: max(0.6, 0.8 * k.u))
            c.stroke(k.line((w0, y), (-w1, y + 18)), with: far, lineWidth: max(0.6, 0.8 * k.u))
        }
        for ax: CGFloat in [-3, 3] { c.fill(k.rect(x: ax, y: 70, w: 1, h: 18), with: near) }
        c.fill(k.circle(x: 3, y: 88.5, r: 1), with: .color(Color.red.opacity(k.animated && Int(k.time) % 2 == 1 ? 0.95 : 0.35)))
    }

    static func marinaCity(_ c: inout GraphicsContext, _ k: Pen) {
        // the twin corncobs: scalloped balcony rings over a parking spiral
        for x: CGFloat in [-8, 8] {
            c.fill(k.rect(x: x, y: 0, w: 12, h: 52), with: near)
            for i in 0..<10 {
                let y = 14 + CGFloat(i) * 4
                c.fill(k.dome(x: x, y: y, w: 14, h: 1.3), with: near)
                k.windows(&c, id: 120 + i * 2 + (x < 0 ? 0 : 1), x: x, y: y + 0.6, cols: 3, rows: 1, pitch: 3.5, size: 1.4)
            }
        }
    }

    // Miami ---------------------------------------------------------------

    static func freedomTower(_ c: inout GraphicsContext, _ k: Pen) {
        // Mediterranean Revival tower with a lantern cupola
        c.fill(k.rect(x: 0, y: 0, w: 34, h: 16), with: far)
        c.fill(k.rect(x: 0, y: 0, w: 14, h: 52), with: near)
        c.fill(k.rect(x: 0, y: 52, w: 10, h: 6), with: near)
        c.fill(k.dome(x: 0, y: 58, w: 10, h: 4), with: near)
        c.fill(k.rect(x: 0, y: 65, w: 1, h: 6), with: near)
        c.fill(k.rect(x: 0, y: 53, w: 6, h: 3), with: .color(Skyline.lit.opacity(k.animated ? 0.55 + 0.35 * sin(k.time * 2) : 0.8)))
        k.windows(&c, id: 130, x: 0, y: 18, cols: 2, rows: 6, pitch: 5, size: 1.8)
    }

    static func artDecoHotel(_ c: inout GraphicsContext, _ k: Pen) {
        // Ocean Drive: stepped parapet, eyebrow ledges and a neon sign
        c.fill(k.rect(x: 0, y: 0, w: 34, h: 30), with: near)
        c.fill(k.poly([(-6, 30), (6, 30), (6, 36), (3, 36), (3, 42), (-3, 42), (-3, 36), (-6, 36)]), with: near)
        for y: CGFloat in [10, 18, 26] { c.fill(k.rect(x: 0, y: y, w: 36, h: 1), with: far) }
        let neon = !k.animated || Int(k.time * 2.5) % 5 != 0                            // flickers now and then
        c.fill(k.rect(x: 0, y: 32, w: 1.6, h: 12), with: .color(Color(red: 1, green: 0.45, blue: 0.75).opacity(neon ? 0.9 : 0.25)))
        k.windows(&c, id: 140, x: 0, y: 3, cols: 5, rows: 3, pitch: 6, size: 2)
    }

    static func brickellTowers(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.rect(x: -12, y: 0, w: 12, h: 66), with: near)
        c.fill(k.poly([(-18, 66), (-6, 66), (-12, 72)]), with: near)
        c.fill(k.rect(x: 6, y: 0, w: 14, h: 80), with: near)
        c.fill(k.rect(x: 18, y: 0, w: 8, h: 44), with: far)
        c.fill(k.circle(x: 6, y: 81, r: 1.1), with: .color(Color.red.opacity(k.animated && Int(k.time * 2) % 2 == 0 ? 0.95 : 0.35)))
        k.windows(&c, id: 150, x: -12, y: 6, cols: 2, rows: 11, pitch: 5, size: 1.8)
        k.windows(&c, id: 151, x: 6, y: 6, cols: 2, rows: 14, pitch: 5, size: 1.8)
    }

    static func lifeguardStand(_ c: inout GraphicsContext, _ k: Pen) {
        // South Beach: a pastel hut on stilts with a flag that flutters
        c.fill(k.rect(x: 0, y: 0, w: 40, h: 2), with: far)                              // sand
        for x: CGFloat in [-6, 6] { c.fill(k.rect(x: x, y: 2, w: 1.4, h: 12), with: near) }
        c.fill(k.poly([(-8, 12), (8, 12), (6, 13), (-6, 13)]), with: near)
        c.fill(k.rect(x: 0, y: 13, w: 12, h: 9), with: .color(Color(red: 0.98, green: 0.62, blue: 0.55).opacity(0.85)))
        c.fill(k.poly([(-8, 22), (8, 22), (0, 28)]), with: near)
        c.fill(k.rect(x: 0, y: 28, w: 0.8, h: 8), with: near)
        let wave: CGFloat = k.animated ? CGFloat(sin(k.time * 5)) * 1.2 : 0
        c.fill(k.poly([(0.4, 36), (6, 35 + wave), (0.4, 33)]), with: .color(Color.red.opacity(0.8)))
    }

    // Atlanta -------------------------------------------------------------

    static func skyViewWheel(_ c: inout GraphicsContext, _ k: Pen) {
        wheel(&c, k, r: 16, hub: 22, cars: 10, speed: 0.3)
    }

    static func georgiaCapitol(_ c: inout GraphicsContext, _ k: Pen) {
        // the gold dome (it glints) over a columned front
        c.fill(k.rect(x: 0, y: 0, w: 40, h: 16), with: near)
        c.fill(k.poly([(-10, 16), (10, 16), (0, 22)]), with: near)
        c.fill(k.rect(x: 0, y: 22, w: 12, h: 8), with: near)
        let gold = Color(red: 0.9, green: 0.75, blue: 0.35)
        c.fill(k.dome(x: 0, y: 30, w: 12, h: 6), with: .color(gold.opacity(k.animated ? 0.6 + 0.3 * sin(k.time * 1.5) : 0.8)))
        c.fill(k.rect(x: 0, y: 42, w: 1, h: 5), with: near)
        for x: CGFloat in stride(from: -15, through: 15, by: 5) { c.fill(k.rect(x: x, y: 2, w: 1.2, h: 12), with: far) }
    }

    static func bankOfAmericaPlaza(_ c: inout GraphicsContext, _ k: Pen) {
        // the tallest in the Southeast: a shaft with a gold-lit lattice pyramid and spire
        c.fill(k.rect(x: 0, y: 0, w: 14, h: 64), with: near)
        c.fill(k.poly([(-7, 64), (7, 64), (0, 78)]), with: near)
        let gold = Color(red: 0.95, green: 0.78, blue: 0.4)
        for i in 0..<4 {
            let y = 66 + CGFloat(i) * 3, w = 5.5 - CGFloat(i) * 1.3
            let on = !k.animated || Skyline.noise(160 + i, Int(k.time / 0.9)) < 0.85
            c.fill(k.rect(x: 0, y: y, w: w * 2, h: 0.9), with: .color(gold.opacity(on ? 0.9 : 0.4)))
        }
        c.fill(k.rect(x: 0, y: 78, w: 0.9, h: 12), with: near)
        k.windows(&c, id: 161, x: 0, y: 6, cols: 2, rows: 11, pitch: 5, size: 1.8)
    }

    static func westinPeachtree(_ c: inout GraphicsContext, _ k: Pen) {
        // the glass cylinder with its revolving-restaurant crown
        c.fill(k.rect(x: 0, y: 0, w: 14, h: 62), with: near)
        c.fill(k.rect(x: 0, y: 62, w: 17, h: 5), with: near)
        c.fill(k.rect(x: 0, y: 67, w: 12, h: 2), with: near)
        // the crown's lights run round as the restaurant turns
        for i in 0..<5 {
            let lit = !k.animated || (Int(k.time * 2) + i) % 5 < 2
            c.fill(k.rect(x: CGFloat(i - 2) * 3.2, y: 63.5, w: 1.8, h: 1.8), with: .color(Skyline.lit.opacity(lit ? 0.9 : 0.3)))
        }
        for x: CGFloat in [-4.5, 0, 4.5] { c.fill(k.rect(x: x, y: 2, w: 0.6, h: 58), with: far) }
        k.windows(&c, id: 170, x: 0, y: 6, cols: 3, rows: 10, pitch: 5, size: 1.6)
    }

    static func mercedesBenzStadium(_ c: inout GraphicsContext, _ k: Pen) {
        // the pinwheel roof: angled petals over a low bowl
        c.fill(k.poly([(-26, 0), (26, 0), (22, 14), (-22, 14)]), with: near)
        for i in 0..<5 {
            let x = CGFloat(i - 2) * 9
            c.fill(k.poly([(x - 5, 14), (x + 5, 14), (x + 1, 20)]), with: i % 2 == 0 ? near : far)
        }
        c.fill(k.rect(x: 0, y: 7, w: 36, h: 2), with: .color(Skyline.lit.opacity(k.animated ? 0.5 + 0.35 * sin(k.time * 2.4) : 0.8)))
    }

    // Philadelphia ---------------------------------------------------------

    static func boathouseRow(_ c: inout GraphicsContext, _ k: Pen) {
        // the Schuylkill boathouses, outlined in lights that twinkle
        c.fill(k.rect(x: 0, y: 0, w: 46, h: 2), with: far)                              // the river bank
        for i in 0..<4 {
            let x = CGFloat(i - 2) * 11 + 5.5
            c.fill(k.rect(x: x, y: 2, w: 10, h: 10), with: near)
            c.fill(k.poly([(x - 5.5, 12), (x + 5.5, 12), (x, 18)]), with: near)
            for j in 0..<4 {
                let on = !k.animated || Skyline.noise(180 + i * 4 + j, Int(k.time / 0.8)) < 0.8
                let pts: [(CGFloat, CGFloat)] = [(x - 5, 12), (x - 2.5, 15), (x + 2.5, 15), (x + 5, 12)]
                c.fill(k.circle(x: pts[j].0, y: pts[j].1, r: 0.8), with: .color(Skyline.lit.opacity(on ? 0.95 : 0.35)))
            }
        }
    }

    static func artMuseum(_ c: inout GraphicsContext, _ k: Pen) {
        // the temple front at the top of the Rocky steps
        c.fill(k.poly([(-24, 0), (24, 0), (16, 8), (-16, 8)]), with: far)               // the steps
        c.fill(k.rect(x: 0, y: 8, w: 30, h: 14), with: near)
        c.fill(k.poly([(-17, 22), (17, 22), (0, 30)]), with: near)
        for x: CGFloat in stride(from: -12, through: 12, by: 4) { c.fill(k.rect(x: x, y: 9, w: 1.2, h: 12), with: far) }
    }

    static func phillyCityHall(_ c: inout GraphicsContext, _ k: Pen) {
        // the tower with its lit clock faces and William Penn on top
        c.fill(k.rect(x: 0, y: 0, w: 40, h: 20), with: near)
        c.fill(k.rect(x: 0, y: 20, w: 12, h: 30), with: near)
        c.fill(k.rect(x: 0, y: 50, w: 9, h: 10), with: near)
        c.fill(k.circle(x: 0, y: 44, r: 3), with: .color(Skyline.lit.opacity(k.animated ? 0.7 + 0.2 * sin(k.time * 0.8) : 0.9)))
        c.fill(k.dome(x: 0, y: 60, w: 9, h: 5), with: near)
        c.fill(k.rect(x: 0, y: 68, w: 1.6, h: 6), with: near)                           // Billy Penn
        c.fill(k.circle(x: 0, y: 75, r: 1), with: near)
        k.windows(&c, id: 190, x: 0, y: 4, cols: 6, rows: 3, pitch: 5.5, size: 1.8)
    }

    static func comcastTower(_ c: inout GraphicsContext, _ k: Pen) {
        // Comcast Technology Center: the tallest, with its open crown
        c.fill(k.poly([(-8, 0), (8, 0), (7, 84), (-7, 84)]), with: near)
        c.fill(k.rect(x: -5, y: 84, w: 2, h: 5), with: near)
        c.fill(k.rect(x: 5, y: 84, w: 2, h: 5), with: near)
        c.fill(k.rect(x: 0, y: 88, w: 12, h: 1.5), with: near)
        c.fill(k.rect(x: 18, y: 0, w: 12, h: 58), with: far)                           // Comcast Center beside it
        c.fill(k.circle(x: 0, y: 91, r: 1), with: .color(Color.red.opacity(k.animated && Int(k.time * 1.5) % 2 == 0 ? 0.95 : 0.35)))
        k.windows(&c, id: 200, x: 0, y: 6, cols: 2, rows: 15, pitch: 5, size: 1.8)
    }

    static func libertyBell(_ c: inout GraphicsContext, _ k: Pen) {
        // the Bell in its frame, swinging a little
        c.fill(k.rect(x: -10, y: 0, w: 1.6, h: 30), with: near)
        c.fill(k.rect(x: 10, y: 0, w: 1.6, h: 30), with: near)
        c.fill(k.rect(x: 0, y: 29, w: 22, h: 2.4), with: near)
        let swing: CGFloat = k.animated ? CGFloat(sin(k.time * 1.2)) * 1.6 : 0
        var bell = Path()
        bell.move(to: k.p(-2 + swing * 0.3, 28))
        bell.addQuadCurve(to: k.p(-7 + swing, 12), control: k.p(-5, 24))
        bell.addLine(to: k.p(7 + swing, 12))
        bell.addQuadCurve(to: k.p(2 + swing * 0.3, 28), control: k.p(5, 24))
        bell.closeSubpath()
        c.fill(bell, with: near)
        c.stroke(k.line((0.5 + swing * 0.6, 18), (1.5 + swing * 0.8, 13)), with: .color(Skyline.lit.opacity(0.7)), lineWidth: max(0.6, 0.6 * k.u))   // the crack
    }

    // Anywhere (state maps) ---------------------------------------------

    static func gardenApartments(_ c: inout GraphicsContext, _ k: Pen) {
        // two low walk-up blocks with pitched roofs, the tax-credit staple
        for (x, w) in [(-16, 30), (18, 26)] as [(CGFloat, CGFloat)] {
            c.fill(k.rect(x: x, y: 0, w: w, h: 22), with: x < 0 ? near : far)
            c.fill(k.poly([(x - w / 2 - 2, 22), (x + w / 2 + 2, 22), (x, 32)]), with: x < 0 ? near : far)
            k.windows(&c, id: 60 + Int(x), x: x, y: 5, cols: 4, rows: 3, pitch: 5.5, size: 2.2)
        }
    }

    static func rowHouses(_ c: inout GraphicsContext, _ k: Pen) {
        for i in 0..<5 {
            let x = CGFloat(i - 2) * 13
            let h: CGFloat = [26, 30, 28, 32, 27][i]
            c.fill(k.rect(x: x, y: 0, w: 12, h: h), with: i % 2 == 0 ? near : far)
            c.fill(k.rect(x: x, y: h, w: 13, h: 2), with: near)                        // cornice
            k.windows(&c, id: 70 + i, x: x, y: 8, cols: 2, rows: 3, pitch: 5, size: 2)
        }
    }

    static func midrise(_ c: inout GraphicsContext, _ k: Pen) {
        c.fill(k.rect(x: -4, y: 0, w: 30, h: 52), with: near)
        c.fill(k.rect(x: 18, y: 0, w: 16, h: 36), with: far)
        c.fill(k.rect(x: -4, y: 52, w: 10, h: 5), with: near)                           // stair bulkhead
        k.windows(&c, id: 80, x: -4, y: 6, cols: 4, rows: 8, pitch: 5.5, size: 2.1)
        k.windows(&c, id: 81, x: 18, y: 6, cols: 2, rows: 5, pitch: 5.5, size: 2)
    }

    static func waterTower(_ c: inout GraphicsContext, _ k: Pen) {
        for lx: CGFloat in [-7, -2.5, 2.5, 7] {
            c.fill(k.rect(x: lx, y: 0, w: 1.2, h: 40), with: near)
        }
        c.fill(k.rect(x: 0, y: 40, w: 22, h: 12), with: near)
        c.fill(k.dome(x: 0, y: 52, w: 24, h: 5), with: near)
        c.fill(k.rect(x: 0, y: 58, w: 1, h: 5), with: near)
    }

    static func palms(_ c: inout GraphicsContext, _ k: Pen) {
        for (x, h, lean) in [(-16, 42, -3), (6, 54, 2), (24, 38, 4)] as [(CGFloat, CGFloat, CGFloat)] {
            c.fill(k.poly([(x - 1.6, 0), (x + 1.6, 0), (x + lean + 1, h), (x + lean - 1, h)]), with: near)
            let top = (x + lean, h)
            // fronds: six curved blades that sway a touch when animated
            let sway: CGFloat = k.animated ? CGFloat(sin(k.time * 1.4 + Double(x))) * 1.2 : 0
            for i in 0..<6 {
                let a = CGFloat(i) / 5 * .pi + 0.2
                let tip = (top.0 + cos(a) * 13 + sway, top.1 + sin(a) * 6 - 4)
                let ctrl = (top.0 + cos(a) * 8 + sway / 2, top.1 + sin(a) * 9 + 4)
                c.stroke(k.curve(top, tip, via: ctrl), with: near, lineWidth: max(1, 1.6 * k.u))
            }
        }
    }
}

// MARK: - Views

/// The band: a low row of city blocks with the landmarks in front. Windows
/// blink on their own beats — a 2 Hz timeline, which is all a blink needs.
struct SkylineBand: View {
    let scene: Skyline.Scene
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        let animated = !reduceMotion && scenePhase == .active
        TimelineView(.periodic(from: .now, by: animated ? 0.5 : 3600)) { tl in
            Canvas(rendersAsynchronously: true) { ctx, size in
                let u = size.height / 100
                let ground = size.height
                // the far row of blocks, one every ~28 units, heights from the hash
                var x: CGFloat = -10
                var i = 0
                while x < size.width + 10 {
                    let w = 16 + CGFloat(Skyline.noise(i, 21)) * 18
                    let h = 10 + CGFloat(Skyline.noise(i, 22)) * 22
                    ctx.fill(Path(CGRect(x: x, y: ground - h * u, width: w * u, height: h * u)), with: .color(Skyline.far))
                    let pen = Pen(cx: x + w * u / 2, ground: ground, u: u, time: tl.date.timeIntervalSinceReferenceDate, animated: animated)
                    pen.windows(&ctx, id: 500 + i, x: 0, y: 3, cols: max(1, Int(w / 7)), rows: max(1, Int(h / 6)), pitch: 5.5, size: 1.8)
                    x += (w + 4 + CGFloat(Skyline.noise(i, 23)) * 10) * u
                    i += 1
                }
                for l in scene.landmarks {
                    let pen = Pen(cx: l.x * size.width, ground: ground, u: u, time: tl.date.timeIntervalSinceReferenceDate, animated: animated)
                    l.draw(&ctx, pen)
                }
                ctx.fill(Path(CGRect(x: 0, y: ground - 2, width: size.width, height: 2)), with: .color(Skyline.ground))
            }
        }
        .frame(height: Skyline.bandHeight)
        .background(LinearGradient(colors: [Skyline.skyTop, Skyline.skyBottom], startPoint: .top, endPoint: .bottom))
        .accessibilityHidden(true)
    }
}

/// The night sky behind the list: stars that twinkle, a crescent moon that
/// drifts, two slow clouds. It only shows when the list is pulled down, so
/// it only animates then (`revealed`) — at rest it is a still image.
struct NightSky: View {
    var revealed: Bool
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase

    var body: some View {
        let animated = revealed && !reduceMotion && scenePhase == .active
        TimelineView(.animation(minimumInterval: 1 / 20, paused: !animated)) { tl in
            Canvas(rendersAsynchronously: true) { ctx, size in
                let t = tl.date.timeIntervalSinceReferenceDate
                let sky = GraphicsContext.Shading.linearGradient(
                    Gradient(colors: [Skyline.skyTop, Skyline.skyBottom]),
                    startPoint: .zero, endPoint: CGPoint(x: 0, y: size.height))
                ctx.fill(Path(CGRect(origin: .zero, size: size)), with: sky)

                for s in Skyline.stars(in: size) {
                    let tw = animated ? 0.55 + 0.45 * sin(t * 1.7 + s.phase) : 0.8
                    ctx.fill(Path(ellipseIn: CGRect(x: s.x - s.r, y: s.y - s.r, width: 2 * s.r, height: 2 * s.r)),
                             with: .color(.white.opacity(tw)))
                }

                // clouds: two soft lozenges crossing right-to-left on a long loop
                for i in 0..<2 {
                    let w: CGFloat = 70 + CGFloat(i) * 30, h: CGFloat = 12
                    let loop = size.width + w
                    let period = 90.0 + Double(i) * 30            // seconds per crossing
                    let phase = CGFloat((t / period).truncatingRemainder(dividingBy: 1))
                    let start: CGFloat = i == 0 ? 0.5 : 0.8
                    let x = animated ? ((start + 1 - phase) * loop).truncatingRemainder(dividingBy: loop) - w
                                     : start * size.width
                    let y = 46 + CGFloat(i) * 58
                    var cloud = Path(roundedRect: CGRect(x: x, y: y, width: w, height: h), cornerRadius: h / 2)
                    cloud.addEllipse(in: CGRect(x: x + w * 0.3, y: y - h * 0.5, width: w * 0.36, height: h * 1.4))
                    ctx.fill(cloud, with: .color(.white.opacity(0.09)))
                }

                // the moon: a crescent, bobbing a hair
                let bob = animated ? sin(t * 0.6) * 2 : 0
                let mx = size.width * 0.2, my = 44 + bob, r: CGFloat = 12
                ctx.fill(Path(ellipseIn: CGRect(x: mx - r, y: my - r, width: 2 * r, height: 2 * r)), with: .color(.white))
                ctx.fill(Path(ellipseIn: CGRect(x: mx - r + 7, y: my - r - 3, width: 2 * r, height: 2 * r)), with: sky)
            }
        }
        .frame(height: Skyline.skyHeight)
        .accessibilityHidden(true)
    }
}

/// A results list with the band as its first row and the sky as its
/// backdrop. Owns the pull reading so the list's parent never re-renders on
/// scroll; the reading only changes state when the sky comes into or goes out
/// of view.
///
/// iOS 18 stopped re-delivering preferences while a scroll view scrolls (a
/// GeometryReader in the content still lays out every frame, but
/// `onPreferenceChange` fired once per screen, 2026-09-16), so the reading
/// comes from `onScrollGeometryChange` there and the preference is only the
/// iOS 17 path.
struct SkylineScrollView<Content: View>: View {
    let scene: Skyline.Scene
    @ViewBuilder let content: Content
    @State private var revealed = false
    @State private var restingTop: CGFloat?

    var body: some View {
        let scroll = ScrollView {
            VStack(spacing: 0) {
                SkylineBand(scene: scene)
                content.background(SE.canvas)
            }
            .background(GeometryReader { g in
                Color.clear.preference(key: PullKey.self, value: g.frame(in: .named("skyline")).minY)
            })
        }
        .coordinateSpace(.named("skyline"))
        .background(alignment: .top) { NightSky(revealed: revealed) }
        .background(SE.canvas)
        .scrollBounceBehavior(.always)

        if #available(iOS 18, *) {
            scroll.onScrollGeometryChange(for: Bool.self) { g in
                g.contentOffset.y + g.contentInsets.top < -0.5
            } action: { _, pulled in
                if pulled != revealed { revealed = pulled }
            }
        } else {
            scroll.onPreferenceChange(PullKey.self) { top in
                if restingTop == nil { restingTop = top }
                let pulled = top - (restingTop ?? 0) > 0.5
                if pulled != revealed { revealed = pulled }
            }
        }
    }
}

private struct PullKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) { value = nextValue() }
}
