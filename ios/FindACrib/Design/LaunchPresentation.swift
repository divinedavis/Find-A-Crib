import SwiftUI

struct LaunchSequence {
    enum Phase { case ready, expanding, revealing, finished }
    private(set) var phase: Phase = .ready

    mutating func advance(from expected: Phase) {
        guard phase == expected else { return }
        switch phase {
        case .ready: phase = .expanding
        case .expanding: phase = .revealing
        case .revealing: phase = .finished
        case .finished: break
        }
    }

    mutating func finish() { phase = .finished }

    static func coverScale(for size: CGSize) -> CGFloat {
        max(1, (hypot(size.width, size.height) + 4) / 180)
    }
}

/// Wraps the app in the launch splash: FIND A CRIB building letter by letter
/// (LetterSplash, owner's choice 2026-09-20 over the teal circle that used to
/// expand here), held until a signed-in user's session is restored, then
/// lifted away. Content underneath cannot be tapped and is hidden from
/// VoiceOver until then. Backgrounding mid-splash, or Reduce Motion turning
/// on, ends it at once.
struct LaunchPresentation<Content: View>: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    /// UI tests pass --no-launch-splash: the splash takes about two seconds
    /// and blocks touches while it plays, and a test that taps the first
    /// thing it sees was tapping the splash (2026-09-20). The three tests
    /// that ARE about the splash (LaunchAnimationTests) do not pass it.
    @State private var finished: Bool = {
        #if DEBUG
        CommandLine.arguments.contains("--no-launch-splash")
        #else
        false
        #endif
    }()
    let content: Content
    /// The splash stays up until this is true (or 3.5 s pass) — used to hold
    /// it while a signed-in user's session is restored.
    let isReady: () -> Bool

    init(isReady: @escaping () -> Bool = { true }, @ViewBuilder content: () -> Content) {
        self.isReady = isReady
        self.content = content()
    }

    private var prefersReducedMotion: Bool {
        #if DEBUG
        reduceMotion || CommandLine.arguments.contains("--reduce-launch-motion")
        #else
        reduceMotion
        #endif
    }

    var body: some View {
        content
            .allowsHitTesting(finished)
            .accessibilityHidden(!finished)
            .overlay {
                if !finished {
                    LetterSplash(onFinished: { finish() }, holdUntil: isReady, forceReducedMotion: prefersReducedMotion)
                        .ignoresSafeArea()
                        .accessibilityElement(children: .ignore)
                        .accessibilityLabel("Find A Crib")
                        .accessibilityIdentifier("launch-animation")
                        .transition(.identity)
                }
            }
            .onChange(of: scenePhase) { _, phase in
                if phase == .background { finish() }
            }
            .onChange(of: reduceMotion) { _, reduced in
                if reduced { finish() }
            }
            .onDisappear { finish() }
    }

    private func finish() {
        var transaction = Transaction(animation: nil)
        transaction.disablesAnimations = true
        withTransaction(transaction) { finished = true }
    }
}
