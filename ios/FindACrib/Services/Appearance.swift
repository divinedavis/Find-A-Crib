import Observation
import SwiftUI

/// Light, Dark, or whatever the phone is set to: Profile › Appearance (owner,
/// 2026-11-22, the day dark mode shipped: "Yes in profile"). Until someone
/// picks, the app follows the phone, as build 169 did.
///
/// One place answers "which appearance?": `scheme` is what the app's root
/// hands to preferredColorScheme, and SE.isDark asks it too, so the few things
/// that are not a colour (which skyline to draw) agree with the colours.
@Observable
final class Appearance {
    static let shared = Appearance()
    static let key = "appearance"

    enum Choice: String, CaseIterable {
        case system, light, dark
        /// The row's wording. "iPhone setting" is the Language row's phrase for
        /// the same idea, so the two rows read alike.
        var title: String {
            switch self {
            case .system: String(localized: "iPhone setting")
            case .light: String(localized: "Light", comment: "Profile › Appearance: the light look")
            case .dark: String(localized: "Dark", comment: "Profile › Appearance: the dark look")
            }
        }
    }

    private(set) var choice: Choice

    private init() {
        // UI tests share one installed app, so a pick left behind by one test
        // would colour every test after it; this launch switch forgets it.
        if CommandLine.arguments.contains("--appearance-reset") {
            UserDefaults.standard.removeObject(forKey: Self.key)
        }
        choice = Choice(rawValue: UserDefaults.standard.string(forKey: Self.key) ?? "") ?? .system
    }

    /// nil = follow the phone. --dark / --light (tests, screenshots) win over
    /// the pick, so a test's appearance never depends on what was picked.
    var scheme: ColorScheme? {
        if let forced = SE.forcedScheme { return forced }
        switch choice {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }

    func choose(_ c: Choice) {
        guard c != choice else { return }
        if c == .system { UserDefaults.standard.removeObject(forKey: Self.key) }
        else { UserDefaults.standard.set(c.rawValue, forKey: Self.key) }
        choice = c
    }
}
