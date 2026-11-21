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
        /// The system's own delegate for the content recognizer, put back
        /// when this screen leaves so the screens that keep their bar swipe
        /// the way the system has it.
        private weak var systemContentDelegate: UIGestureRecognizerDelegate?

        override func viewDidAppear(_ animated: Bool) {
            super.viewDidAppear(animated)
            guard let nav = navigationController, let swipe = nav.interactivePopGestureRecognizer else { return }
            swipe.delegate = EdgeSwipeDelegate.shared
            swipe.isEnabled = true
            // iOS 26 has a second recognizer, for a swipe that starts in the
            // content. On iPad it is the one that pops: the edge recognizer
            // never asks to begin there (2026-11-21, iPad Pro 11, iOS 26.5),
            // so without this the swipe stayed dead on iPad.
            if #available(iOS 26.0, *), let content = nav.interactiveContentPopGestureRecognizer {
                if !(content.delegate is EdgeSwipeDelegate) { systemContentDelegate = content.delegate }
                content.delegate = EdgeSwipeDelegate.shared
                content.isEnabled = true
            }
        }

        override func viewWillDisappear(_ animated: Bool) {
            super.viewWillDisappear(animated)
            if #available(iOS 26.0, *), let content = navigationController?.interactiveContentPopGestureRecognizer,
               content.delegate is EdgeSwipeDelegate, let system = systemContentDelegate {
                content.delegate = system
            }
        }
    }
}

private final class EdgeSwipeDelegate: NSObject, UIGestureRecognizerDelegate {
    static let shared = EdgeSwipeDelegate()
    /// How far in from the leading edge a swipe may start. The system lets
    /// its content swipe start anywhere, but it also settles that against
    /// the sideways scrollers on the screen (the filter row, a card's
    /// photos); this delegate replaces that judgement, so it keeps to the
    /// strip beside the edge where nothing scrolls sideways.
    /// Measured from where the recognizer reports the swipe, which is
    /// about 30 pt after the finger first touched (its own run-up).
    private static let strip: CGFloat = 80
    /// The recognizer last allowed to begin, and when: the two recognizers
    /// can both ask about one touch, and two pops at once hang the stack.
    private weak var granted: UIGestureRecognizer?
    private var grantedAt: TimeInterval = 0

    func gestureRecognizerShouldBegin(_ g: UIGestureRecognizer) -> Bool {
        // Each tab has its own stack and its own recognizer; the stack is
        // read off the recognizer, whose view is the stack's own.
        var next = g.view?.next
        while let r = next, !(r is UINavigationController) { next = r.next }
        guard let nav = next as? UINavigationController, nav.viewControllers.count > 1 else { return false }
        // Not while a push or pop is still running: a second one started
        // inside it leaves the stack half-moved.
        guard nav.transitionCoordinator == nil else { return false }
        let now = ProcessInfo.processInfo.systemUptime
        if let granted, granted !== g, now - grantedAt < 0.6 { return false }
        if g !== nav.interactivePopGestureRecognizer {
            guard let view = g.view, let pan = g as? UIPanGestureRecognizer else { return false }
            let rtl = view.effectiveUserInterfaceLayoutDirection == .rightToLeft
            let startX = pan.location(in: view).x - pan.translation(in: view).x
            let fromEdge = rtl ? view.bounds.width - startX : startX
            let v = pan.velocity(in: view)
            let along = rtl ? -v.x : v.x
            guard fromEdge <= Self.strip, along > abs(v.y) else { return false }
            // A card's photos reach into the strip: a sideways scroller
            // under the finger keeps the swipe.
            var under: UIView? = view.hitTest(CGPoint(x: startX, y: pan.location(in: view).y), with: nil)
            while let u = under, u !== view {
                if let scroller = u as? UIScrollView, scroller.isScrollEnabled, scroller.contentSize.width > scroller.bounds.width + 1 { return false }
                under = u.superview
            }
        }
        granted = g
        grantedAt = now
        return true
    }
}
