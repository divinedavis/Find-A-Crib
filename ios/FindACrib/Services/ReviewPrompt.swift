import Foundation
import Observation
import StoreKit
import UIKit

/// Asks for an App Store rating after something good happened — a building
/// saved, or alerts turned on (owner, 2026-09-17). Both are moments where the
/// person has just decided the app is worth keeping, which is the only kind of
/// moment Apple's guidance allows.
///
/// What the system does with the request is not ours to control: iOS shows the
/// sheet at most three times per person per 365 days and may show nothing at
/// all, and there is no callback saying which happened. So everything here is
/// about WHEN to ask, and about never nagging.
///
/// **It does not appear in TestFlight.** Apple: the request "has no effect in
/// apps distributed for beta testing using TestFlight", while a build run from
/// Xcode always shows it. A beta build therefore shows our own stand-in sheet
/// instead — clearly labelled as one — so the trigger can be tested end to end
/// on a real device. App Store builds never see the stand-in.
@Observable @MainActor
final class ReviewPrompt {
    static let shared = ReviewPrompt()

    /// What earned the ask. Recorded on the event so the two triggers can be
    /// compared later.
    enum Moment: String { case save, alerts }

    /// Never ask twice for the same version, and never inside this many days —
    /// well inside Apple's own cap, so the few asks we do get are spent on
    /// people who just did something good rather than on a re-install.
    nonisolated static let quietDays = 120

    /// Set while the beta stand-in sheet should be on screen (RootView shows
    /// it). Always false in an App Store build.
    var showBetaStandIn = false

    /// The App Store's own "write a review" page. A button may open this —
    /// Apple's restriction is on `requestReview`, not on a link.
    nonisolated static let writeReviewURL = URL(string: "https://apps.apple.com/app/id6807549249?action=write-review")!

    private let defaults: UserDefaults
    private var version: String {
        (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "?"
    }

    init(defaults: UserDefaults = .standard) { self.defaults = defaults }

    // MARK: - The decision (pure, unit-tested)

    /// Whether an ask is allowed right now.
    ///
    /// - `lastVersion` / `lastAsked`: what the last ask recorded, nil if never.
    /// - `now`: the clock, injectable for tests.
    nonisolated static func shouldAsk(version: String, lastVersion: String?, lastAsked: Date?, now: Date = Date()) -> Bool {
        if lastVersion == version { return false }               // once per version
        if let lastAsked, now.timeIntervalSince(lastAsked) < Double(quietDays) * 86_400 { return false }
        return true
    }

    // MARK: - Triggers

    /// A building was saved, or alerts were turned on. Safe to call on every
    /// save — the gate decides, and a declined ask is never retried inside the
    /// quiet window.
    func record(_ moment: Moment) {
        guard Self.shouldAsk(version: version,
                             lastVersion: defaults.string(forKey: "review.lastVersion"),
                             lastAsked: defaults.object(forKey: "review.lastAsked") as? Date) else { return }
        ask(moment, forced: false)
    }

    /// `--review-now` on the command line asks immediately, gate and all
    /// ignored. The UI test drives it, and it is how the prompt gets looked at
    /// on a simulator without saving a building first.
    func applyLaunchArguments() {
        if CommandLine.arguments.contains("--review-now") { ask(.save, forced: true) }
    }

    private func ask(_ moment: Moment, forced: Bool) {
        // Record the ask BEFORE showing it: if the sheet is what the system
        // decides to skip, we must not come back on the next save either.
        if !forced {
            defaults.set(version, forKey: "review.lastVersion")
            defaults.set(Date(), forKey: "review.lastAsked")
        }
        Analytics.shared.track("review_prompt", ["moment": moment.rawValue, "kind": Self.isBeta ? "beta_standin" : "system", "forced": forced])
        // A beat, so the sheet does not land on top of the heart still
        // animating or the alerts sheet still dismissing.
        Task { @MainActor in
            try? await Task.sleep(for: .milliseconds(700))
            guard UIApplication.shared.applicationState == .active else { return }
            if Self.isBeta {
                showBetaStandIn = true
            } else if let scene = Self.activeScene {
                AppStore.requestReview(in: scene)
            }
        }
    }

    /// TestFlight (and any sandbox-receipt build that is not a Debug build).
    /// Debug builds go down the real path because Xcode-run builds always show
    /// the system sheet, which is the only way to see the real thing.
    static var isBeta: Bool {
        #if DEBUG
        return false
        #else
        return Bundle.main.appStoreReceiptURL?.lastPathComponent == "sandboxReceipt"
        #endif
    }

    static var activeScene: UIWindowScene? {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive }
            ?? UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first
    }

    func openWriteReview() {
        Analytics.shared.track("review_link", [:])
        UIApplication.shared.open(Self.writeReviewURL)
    }
}
