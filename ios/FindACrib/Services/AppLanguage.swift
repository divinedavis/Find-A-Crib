import Foundation
import Observation
import ObjectiveC

/// The app's own language switch (owner 2026-10-17). Profile › Language used
/// to open Settings for iOS's per-app language, but iOS reopens Settings
/// wherever it was last left, so people often didn't land on Find A Crib ›
/// Language at all. Now the row picks the language here:
///  - `AppleLanguages` in the app's defaults makes the choice stick across
///    launches, exactly as the Settings page would;
///  - Bundle.main is swapped for a subclass that reads from the chosen .lproj,
///    and RootView is rebuilt with `revision`, so it switches without a relaunch.
/// nil ("iPhone setting") follows the phone's languages again.
@Observable
final class AppLanguage {
    static let shared = AppLanguage()
    /// Languages the catalog ships (knownRegions in the project).
    static let supported = ["en", "es", "zh-Hans", "zh-Hant", "ko"]
    private static let key = "appLanguage"

    private(set) var chosen: String? = UserDefaults.standard.string(forKey: key)
    /// Bumped on every switch; RootView's id, so every screen re-reads its text.
    private(set) var revision = 0

    /// The language the app is showing now.
    var current: String {
        chosen ?? Bundle.preferredLocalizations(from: Self.supported, forPreferences: Locale.preferredLanguages).first ?? "en"
    }
    var locale: Locale { Locale(identifier: current) }

    func choose(_ code: String?) {
        guard code != chosen else { return }
        let d = UserDefaults.standard
        if let code, Self.supported.contains(code) {
            d.set(code, forKey: Self.key)
            d.set([code], forKey: "AppleLanguages")
        } else {
            d.removeObject(forKey: Self.key)
            d.removeObject(forKey: "AppleLanguages")
        }
        chosen = d.string(forKey: Self.key)
        Self.install()
        revision += 1
    }

    /// A language's name in that language ("Español", "繁體中文").
    static func name(_ code: String) -> String {
        let l = Locale(identifier: code)
        return l.localizedString(forIdentifier: code)?.capitalized(with: l) ?? code
    }

    /// Points Bundle.main's string lookups at the chosen language; call at launch.
    static func install() {
        // Always an explicit .lproj: after "iPhone setting" mid-session, Bundle.main
        // would still answer in whatever language the app launched in.
        LanguageBundle.lproj = Bundle.main.path(forResource: shared.current, ofType: "lproj").flatMap(Bundle.init(path:))
        if object_getClass(Bundle.main) != LanguageBundle.self { object_setClass(Bundle.main, LanguageBundle.self) }
    }
}

/// Bundle.main's class once AppLanguage.install() has run.
private final class LanguageBundle: Bundle, @unchecked Sendable {
    nonisolated(unsafe) static var lproj: Bundle?
    override func localizedString(forKey key: String, value: String?, table tableName: String?) -> String {
        if let b = Self.lproj { return b.localizedString(forKey: key, value: value, table: tableName) }
        return super.localizedString(forKey: key, value: value, table: tableName)
    }
}
