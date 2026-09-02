import SwiftUI
import UIKit

/// Keeps UIKit's interactive swipe-to-go-back — the one you drag with a thumb
/// and can let go halfway.
///
/// Anything that tells SwiftUI the bar is gone (`.toolbar(.hidden)`,
/// `navigationBarBackButtonHidden`, even hiding the UINavigationBar from
/// UIKit) makes it switch the pop gesture off for good. So the bar stays: it
/// is made transparent, its back button loses its text, and its chevron is
/// drawn white over the navy header the screens paint behind it. The screens
/// place their own content below the bar row and carry no back arrow of
/// their own — the system chevron is the back control.
extension View {
    func swipeBackEnabled() -> some View {
        self.navigationTitle("")
            .toolbarRole(.editor)                              // chevron only, no "Back" text
            .toolbarBackground(.hidden, for: .navigationBar)   // navy header shows through
            .toolbarColorScheme(.dark, for: .navigationBar)    // white chevron
    }
}
