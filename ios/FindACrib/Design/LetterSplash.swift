import SwiftUI

/// The Netflix-style opening the owner asked for (2026-09-20, from a screen
/// recording of Netflix's): the wordmark builds letter by letter on a dark
/// field, holds for a beat, then hands over to the app.
///
/// Netflix draws one bespoke word in its own face; ours is FIND A CRIB set in
/// the app's own black weight, so the splash and the rest of the app are the
/// same typeface. Each letter fades up with a short rise and a teal glow that
/// settles to white, left to right; the word then lifts and fades as the app
/// takes over.
///
/// Not a substitute for the launch storyboard — iOS shows that instantly while
/// the process starts, and this plays on top of it once SwiftUI is up, which
/// is why the background matches LaunchNavy exactly.
struct LetterSplash: View {
    /// Fires when the last letter has settled and the hold is over.
    var onFinished: () -> Void = {}
    /// Replays forever, for looking at it (`--splash-preview`).
    var loop = false
    /// The word stays up until this says the app is ready (a signed-in
    /// session restored), for at most `readyTimeout` past the hold.
    var holdUntil: () -> Bool = { true }
    /// Reduce Motion from the caller, so a launch flag can force it in tests.
    var forceReducedMotion = false
    static let readyTimeout = 3.5

    private static let word = Array("FIND A CRIB")
    /// Gap between one letter starting and the next.
    private static let stagger = 0.075
    private static let letterDuration = 0.42
    private static let hold = 0.55

    /// The word is drawn once at a fixed size, measured, and scaled so it
    /// always spans the same share of the screen — the proportion the owner
    /// approved from the preview (an iPhone Pro Max, 2026-09-20). On the
    /// owner's own phone it then ran to the edges: `.custom(_:size:)` follows
    /// the Dynamic Type setting, so a larger text size made the letters
    /// larger. The font is fixed-size now and the fit is measured, so every
    /// iPhone and every text-size setting gets the same picture.
    private static let baseSize: CGFloat = 72
    /// Share of the screen width the finished word covers.
    private static let widthShare: CGFloat = 0.68
    @State private var wordWidth: CGFloat = 0

    @State private var shown = 0            // how many letters have started
    @State private var leaving = false
    @Environment(\.accessibilityReduceMotion) private var systemReduceMotion
    private var reduceMotion: Bool { systemReduceMotion || forceReducedMotion }

    var body: some View {
        GeometryReader { screen in
            let fit: CGFloat = wordWidth > 0 ? min(1.4, max(0.4, screen.size.width * Self.widthShare / wordWidth)) : 0.001
            ZStack {
                Color("LaunchNavy").ignoresSafeArea()
                HStack(spacing: 0) {
                    ForEach(Array(Self.word.enumerated()), id: \.offset) { i, ch in
                        letter(ch, index: i)
                    }
                }
                .background(GeometryReader { g in
                    Color.clear.onAppear { wordWidth = g.size.width }
                        .onChange(of: g.size.width) { _, w in wordWidth = w }
                })
                .scaleEffect(fit * (leaving ? 1.06 : 1))
                .opacity(leaving ? 0 : 1)
                .frame(width: screen.size.width, height: screen.size.height)
            }
        }
        .dynamicTypeSize(.large)
        .ignoresSafeArea()
        .task { await play() }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Find A Crib")
        .accessibilityIdentifier("letter-splash")
    }

    /// Fixed size: a splash must not follow the reader's text-size setting.
    private static let font: Font = UIFont(name: SEWeight.black.postScript, size: baseSize) != nil
        ? .custom(SEWeight.black.postScript, fixedSize: baseSize)
        : .system(size: baseSize, weight: .black)

    @ViewBuilder private func letter(_ ch: Character, index: Int) -> some View {
        let on = index < shown
        // A space carries no glyph; it still holds its width so the two words
        // stay apart while the line builds.
        Text(String(ch))
            .font(Self.font)
            .kerning(1)
            .foregroundStyle(on ? Color.white : Color.white.opacity(0))
            // The glow is what makes a letter look struck rather than faded
            // in: teal at full strength as it lands, gone once it settles.
            .shadow(color: SE.royal.opacity(on ? 0.35 : 0.95), radius: on ? 6 : 22)
            .offset(y: on ? 0 : 14)
            .scaleEffect(on ? 1 : 0.88, anchor: .bottom)
            .animation(.easeOut(duration: Self.letterDuration), value: on)
    }

    private func play() async {
        repeat {
            shown = 0; leaving = false
            if reduceMotion {
                // Everything at once, then the same hold: no rise, no stagger.
                shown = Self.word.count
                try? await Task.sleep(for: .seconds(Self.hold))
            } else {
                for i in 1...Self.word.count {
                    shown = i
                    try? await Task.sleep(for: .seconds(Self.stagger))
                }
                try? await Task.sleep(for: .seconds(Self.letterDuration + Self.hold))
            }
            let start = Date()
            while !holdUntil(), Date().timeIntervalSince(start) < Self.readyTimeout, !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(50))
            }
            withAnimation(.easeIn(duration: 0.35)) { leaving = true }
            try? await Task.sleep(for: .seconds(0.35))
            if !loop { onFinished(); return }
            try? await Task.sleep(for: .seconds(0.4))
        } while loop && !Task.isCancelled
    }
}

#Preview { LetterSplash(loop: true) }
