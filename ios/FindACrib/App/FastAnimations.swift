import UIKit

/// UI tests only (owner, 2026-10-18: "how can we speed up our iphone and ipad
/// tests?"). With FAC_FAST_ANIMATIONS=1 in the launch environment every
/// window's layer runs 100x, so sheets, pushes and SwiftUI transitions finish
/// almost at once and XCUITest stops waiting on them. Set only by
/// FindACribUITests; the launch-animation, performance and tour tests keep
/// real timing. Never set in a shipped launch.
enum FastAnimations {
    static func installIfTesting() {
        guard ProcessInfo.processInfo.environment["FAC_FAST_ANIMATIONS"] == "1" else { return }
        NotificationCenter.default.addObserver(forName: UIWindow.didBecomeVisibleNotification, object: nil, queue: .main) { n in
            (n.object as? UIWindow)?.layer.speed = 100
        }
    }
}
