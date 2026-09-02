import SwiftUI

/// Edge swipe-to-go-back for screens that hide the system navigation bar.
///
/// Every pushed screen draws its own navy header, and SwiftUI switches the
/// interactive pop gesture off when the bar is hidden — re-arming the UIKit
/// recognizer from a representable proved unreliable (SwiftUI resets it), so
/// the screen owns the gesture instead: a drag that starts within 32pt of
/// the left edge and travels right pops the screen. Not tracked live like
/// UIKit's, but it always works, and it can never double-pop because there
/// is only one recognizer.
struct EdgeSwipeBack: ViewModifier {
    @Environment(\.dismiss) private var dismiss
    func body(content: Content) -> some View {
        content.simultaneousGesture(
            DragGesture(minimumDistance: 24, coordinateSpace: .global)
                .onEnded { v in
                    guard v.startLocation.x < 32, v.translation.width > 80,
                          abs(v.translation.height) < abs(v.translation.width) else { return }
                    dismiss()
                }
        )
    }
}

extension View {
    /// Attach to any pushed screen that hides the system navigation bar.
    func swipeBackEnabled() -> some View { modifier(EdgeSwipeBack()) }
}
