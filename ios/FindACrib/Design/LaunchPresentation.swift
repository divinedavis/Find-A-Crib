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

struct LaunchPresentation<Content: View>: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.scenePhase) private var scenePhase
    @State private var sequence = LaunchSequence()
    let content: Content
    /// The splash stays up until this is true (or 3.5 s pass) — used to hold
    /// it while a signed-in user's session is restored.
    let isReady: () -> Bool

    init(isReady: @escaping () -> Bool = { true }, @ViewBuilder content: () -> Content) {
        self.isReady = isReady
        self.content = content()
    }

    private var isFinished: Bool { sequence.phase == .finished }
    private var prefersReducedMotion: Bool {
        #if DEBUG
        reduceMotion || CommandLine.arguments.contains("--reduce-launch-motion")
        #else
        reduceMotion
        #endif
    }

    var body: some View {
        content
            .allowsHitTesting(isFinished)
            .accessibilityHidden(!isFinished)
            .overlay {
                if !isFinished {
                    GeometryReader { geometry in
                        ZStack {
                            Color("LaunchNavy")
                            Circle()
                                .fill(SE.royal)
                                .frame(width: 180, height: 180)
                                .scaleEffect(sequence.phase == .ready || prefersReducedMotion ? 1 : LaunchSequence.coverScale(for: geometry.size))
                            VStack(spacing: 14) {
                                BrandMark().frame(width: 88, height: 88)
                                Text("Find A Crib")
                                    .font(.se(28, .bold))
                                    .foregroundStyle(.white)
                            }
                        }
                        .frame(width: geometry.size.width, height: geometry.size.height)
                        .clipped()
                    }
                    .ignoresSafeArea()
                    .opacity(sequence.phase == .revealing ? 0 : 1)
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel("Find A Crib")
                    .accessibilityIdentifier("launch-animation")
                    .transition(.identity)
                }
            }
            .task(id: scenePhase) {
                guard sequence.phase == .ready, scenePhase == .active else { return }
                do { try await Task.sleep(for: .milliseconds(160)) }
                catch { return }
                let start = Date()
                while !isReady(), Date().timeIntervalSince(start) < 3.5 {
                    do { try await Task.sleep(for: .milliseconds(50)) } catch { return }
                }
                guard sequence.phase == .ready, scenePhase == .active else { return }
                if prefersReducedMotion {
                    var transaction = Transaction(animation: nil)
                    transaction.disablesAnimations = true
                    withTransaction(transaction) { sequence.advance(from: .ready) }
                    reveal()
                } else {
                    withAnimation(.timingCurve(0.4, 0, 0.2, 1, duration: 0.58), completionCriteria: .removed) {
                        sequence.advance(from: .ready)
                    } completion: {
                        reveal()
                    }
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

    private func reveal() {
        guard sequence.phase == .expanding else { return }
        withAnimation(.easeOut(duration: 0.22), completionCriteria: .removed) {
            sequence.advance(from: .expanding)
        } completion: {
            sequence.advance(from: .revealing)
        }
    }

    private func finish() {
        var transaction = Transaction(animation: nil)
        transaction.disablesAnimations = true
        withTransaction(transaction) { sequence.finish() }
    }
}
