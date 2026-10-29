import SwiftUI
import UIKit

/// The status bar's text colour, set by the app (Info.plist
/// UIViewControllerBasedStatusBarAppearance = NO). Dark everywhere, light
/// while the Search banner sits behind it (owner, 2026-10-29: the banner now
/// runs up under the status bar and Dynamic Island, and black time and
/// battery read poorly on it).
///
/// The setter is the pre-iOS 9 application-level one. It is deprecated but
/// still the only public switch that works when the screen's navigation bar
/// is hidden: toolbarColorScheme needs a visible bar, and a visible empty
/// bar on iOS 26 draws its own scroll-edge blur over the banner.
enum StatusBarStyle {
    @MainActor static func set(light: Bool) {
        let style: UIStatusBarStyle = light ? .lightContent : .darkContent
        guard UIApplication.shared.statusBarStyle != style else { return }
        UIApplication.shared.setStatusBarStyle(style, animated: true)
    }
}
