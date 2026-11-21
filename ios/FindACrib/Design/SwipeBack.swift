import SwiftUI
import UIKit

/// Keeps UIKit's interactive swipe-to-go-back — the one you drag with a thumb
/// and can let go halfway.
///
/// Anything that tells SwiftUI the bar is gone (`.toolbar(.hidden)`,
/// `navigationBarBackButtonHidden`, even hiding the UINavigationBar from
/// UIKit) makes it switch the pop gesture off for good. So the bar stays: it
/// is made transparent, its back button loses its text, and its chevron is
/// drawn dark over the grey header the screens paint behind it (white over
/// navy until the Liquid Glass redesign, 2026-11-17). The screens
/// place their own content below the bar row and carry no back arrow of
/// their own — the system chevron is the back control.
extension View {
    func swipeBackEnabled() -> some View {
        self.navigationTitle("")
            .toolbarRole(.editor)                              // chevron only, no "Back" text
            .toolbarBackground(.hidden, for: .navigationBar)   // the grey header shows through
            // Dark chevron on the Liquid Glass grey (2026-11-17). Was a white
            // chevron over the navy header.
            .toolbarColorScheme(.light, for: .navigationBar)
    }
}

/// For a screen that cannot keep the system bar (the results list draws its
/// own collapsing header): hands UIKit's edge-swipe recognizer a delegate
/// that says yes whenever there is a screen to go back to. SwiftUI turns the
/// recognizer off when it hides the bar; this turns it back on for the stack
/// the screen sits in. The delegate lives as long as the app, because the
/// recognizer keeps only a weak reference and, left with none, would start
/// a pop on the first screen and hang the stack.
extension View {
    func edgeSwipeBackKept() -> some View {
        background(EdgeSwipeKeeper().frame(width: 0, height: 0).accessibilityHidden(true))
    }
}

private struct EdgeSwipeKeeper: UIViewControllerRepresentable {
    func makeUIViewController(context: Context) -> Probe { Probe() }
    func updateUIViewController(_ vc: Probe, context: Context) {}

    final class Probe: UIViewController {
        override func viewDidAppear(_ animated: Bool) {
            super.viewDidAppear(animated)
            guard let swipe = navigationController?.interactivePopGestureRecognizer else { return }
            swipe.delegate = EdgeSwipeDelegate.shared
            swipe.isEnabled = true
        }
    }
}

private final class EdgeSwipeDelegate: NSObject, UIGestureRecognizerDelegate {
    static let shared = EdgeSwipeDelegate()

    func gestureRecognizerShouldBegin(_ g: UIGestureRecognizer) -> Bool {
        // Each tab has its own stack and its own recognizer; the stack is
        // read off the recognizer, whose view is the stack's own.
        var next = g.view?.next
        while let r = next, !(r is UINavigationController) { next = r.next }
        guard let nav = next as? UINavigationController, nav.viewControllers.count > 1 else { return false }
        // Not while a push or pop is still running: a second one started
        // inside it leaves the stack half-moved.
        return nav.transitionCoordinator == nil
    }
}
