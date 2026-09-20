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

    private static let word = Array("FIND A CRIB")
    /// Gap between one letter starting and the next.
    private static let stagger = 0.075
    private static let letterDuration = 0.42
    private static let hold = 0.55

    /// Sized to the screen so the word fills it the way Netflix's does,
    /// rather than sitting small in the middle of a phone.
    private var size: CGFloat { min(72, UIScreen.main.bounds.width / 6.1) }

    @State private var shown = 0            // how many letters have started
    @State private var leaving = false
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        ZStack {
            Color("LaunchNavy").ignoresSafeArea()
            HStack(spacing: 0) {
                ForEach(Array(Self.word.enumerated()), id: \.offset) { i, ch in
                    letter(ch, index: i)
                }
            }
            .scaleEffect(leaving ? 1.06 : 1)
            .opacity(leaving ? 0 : 1)
        }
        .task { await play() }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Find A Crib")
        .accessibilityIdentifier("letter-splash")
    }

    @ViewBuilder private func letter(_ ch: Character, index: Int) -> some View {
        let on = index < shown
        // A space carries no glyph; it still holds its width so the two words
        // stay apart while the line builds.
        Text(String(ch))
            .font(.se(size, .black))
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
            withAnimation(.easeIn(duration: 0.35)) { leaving = true }
            try? await Task.sleep(for: .seconds(0.35))
            if !loop { onFinished(); return }
            try? await Task.sleep(for: .seconds(0.4))
        } while loop && !Task.isCancelled
    }
}

#Preview { LetterSplash(loop: true) }
