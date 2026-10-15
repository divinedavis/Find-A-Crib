import UIKit

/// Tapping anywhere outside a text field closes the keyboard, on every screen
/// (owner, 2026-10-14). One tap recognizer on each window that never cancels
/// or delays the touch, so buttons, rows and scrolling work as before; a tap
/// that lands in a text field or text view is left alone, so moving from
/// Email to Password keeps the keyboard up.
enum KeyboardDismiss {
    private final class Handler: NSObject, UIGestureRecognizerDelegate {
        @objc func tapped(_ g: UITapGestureRecognizer) { g.view?.endEditing(true) }
        func gestureRecognizer(_ g: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
            var v = touch.view
            while let cur = v {
                if cur is UITextField || cur is UITextView || cur is UISearchBar { return false }
                v = cur.superview
            }
            return true
        }
        func gestureRecognizer(_ g: UIGestureRecognizer, shouldRecognizeSimultaneouslyWith other: UIGestureRecognizer) -> Bool { true }
    }
    private static let handler = Handler()
    private static let name = "fac.keyboard-dismiss"

    /// Idempotent; called at launch and when the app comes forward, since
    /// sheets and new scenes can bring new windows.
    @MainActor static func install() {
        for scene in UIApplication.shared.connectedScenes {
            for window in (scene as? UIWindowScene)?.windows ?? [] where !(window.gestureRecognizers ?? []).contains(where: { $0.name == name }) {
                let tap = UITapGestureRecognizer(target: handler, action: #selector(Handler.tapped))
                tap.name = name
                tap.cancelsTouchesInView = false
                tap.delaysTouchesEnded = false
                tap.delegate = handler
                window.addGestureRecognizer(tap)
            }
        }
    }
}
