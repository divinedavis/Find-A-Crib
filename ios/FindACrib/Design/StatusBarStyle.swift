import ObjectiveC
import SwiftUI
import UIKit

/// White status bar text while the Search banner sits behind it (owner,
/// 2026-10-29: the banner now runs up under the status bar and Dynamic
/// Island, and a black clock reads poorly on it). Everywhere else the status
/// bar is exactly what UIKit chose before.
///
/// How: the window's root view controller (SwiftUI's hosting controller)
/// gets an override of preferredStatusBarStyle and childForStatusBarStyle
/// that answers "light, from me" only while `light` is on, and otherwise
/// calls the implementation it had. Two routes were tried first and dropped:
/// - toolbarColorScheme(.dark) needs a visible navigation bar, and a
///   visible empty bar on iOS 26 drew a scroll-edge blur over the banner
///   and left the clock black anyway;
/// - app-wide style (UIViewControllerBasedStatusBarAppearance = NO) worked
///   on Search but took away UIKit's own choices, e.g. the light clock over a
///   page sheet's black backdrop (review, 2026-10-29).
@MainActor
enum StatusBarStyle {
    private static var light = false
    private static var patched = Set<ObjectIdentifier>()

    private typealias StyleIMP = @convention(c) (UIViewController, Selector) -> Int
    private typealias ChildIMP = @convention(c) (UIViewController, Selector) -> UIViewController?

    static func set(light newValue: Bool) {
        light = newValue
        guard let root = rootViewController() else { return }
        patch(type(of: root))
        root.setNeedsStatusBarAppearanceUpdate()
    }

    private static func rootViewController() -> UIViewController? {
        UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap(\.windows)
            .first(where: \.isKeyWindow)?.rootViewController
    }

    /// Adds the two overrides to the root's own class, once. class_addMethod
    /// puts them on that class only, so other view controllers (sheets,
    /// pushed screens' hosts, UIKit's own) keep theirs.
    private static func patch(_ cls: AnyClass) {
        guard patched.insert(ObjectIdentifier(cls)).inserted else { return }

        let styleSel = #selector(getter: UIViewController.preferredStatusBarStyle)
        if let m = class_getInstanceMethod(cls, styleSel) {
            let original = unsafeBitCast(method_getImplementation(m), to: StyleIMP.self)
            let block: @convention(block) (UIViewController) -> Int = { vc in
                MainActor.assumeIsolated { light } ? UIStatusBarStyle.lightContent.rawValue : original(vc, styleSel)
            }
            let imp = imp_implementationWithBlock(block)
            if !class_addMethod(cls, styleSel, imp, method_getTypeEncoding(m)) { method_setImplementation(m, imp) }
        }

        let childSel = #selector(getter: UIViewController.childForStatusBarStyle)
        if let m = class_getInstanceMethod(cls, childSel) {
            let original = unsafeBitCast(method_getImplementation(m), to: ChildIMP.self)
            let block: @convention(block) (UIViewController) -> UIViewController? = { vc in
                MainActor.assumeIsolated { light } ? nil : original(vc, childSel)
            }
            let imp = imp_implementationWithBlock(block)
            if !class_addMethod(cls, childSel, imp, method_getTypeEncoding(m)) { method_setImplementation(m, imp) }
        }
    }
}
