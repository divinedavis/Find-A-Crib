import Foundation
import Observation

/// What people do in the app, written to the same `public.events` table the
/// website writes to — same event names, so one dashboard and one coverage
/// report cover both clients. Every row carries `platform: "ios"` (the web
/// sends "web"), which is the only way to tell them apart.
///
/// Deliberately small: no SDK, no device graph, no advertising identifier.
/// One row per action, fire and forget, dropped silently when it fails. It
/// records what was done, never what was typed — a search sends the shape of
/// the query (which city, how many filters), never the text.
///
/// Off is a real setting: Profile → "Share anonymous usage". Nothing is sent
/// while it is off, and nothing is queued to send later.
///
/// NOTE FOR THE NEXT RELEASE: this is new data collection. App Store Connect's
/// App Privacy questionnaire must declare Product Interaction / Usage Data
/// (linked to identity when signed in, NOT used for tracking) before a build
/// containing it is submitted. That page is browser-only — there is no API.
@Observable @MainActor
final class Analytics {
    static let shared = Analytics()

    /// Set at launch so an event can be attributed to the signed-in account
    /// and pass the events table's row check (user_id is null, or your own).
    weak var auth: AuthService?
    var city: String = "nyc"

    private let session = URLSession(configuration: .ephemeral)
    private let host: String
    private let anonKey: String
    /// Stable per install, like the site's fac_vid cookie. Not tied to a person
    /// until they sign in, and thrown away when the app is deleted.
    private let visitorID: String
    private var sent = 0
    /// A runaway loop must not be able to write rows all afternoon; the site
    /// caps its impression rows the same way.
    private let capPerLaunch = 400

    /// OFF UNTIL THE APP PRIVACY LABEL SAYS SO.
    ///
    /// Sending usage data while App Store Connect's App Privacy answers say the
    /// app collects only name and email is a false declaration, and that page
    /// is browser-only — there is no API to change it from here. So the code
    /// ships dark: every call below is a no-op until Product Interaction /
    /// Usage Data is declared (linked to identity when signed in, NOT used for
    /// tracking) and this is flipped to true in the same commit that says so.
    static let privacyLabelDeclared = false

    var enabled: Bool {
        get { UserDefaults.standard.object(forKey: "analytics.enabled") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "analytics.enabled") }
    }

    private init() {
        let info = Bundle.main.infoDictionary ?? [:]
        host = (info["SUPABASE_HOST"] as? String) ?? ""
        anonKey = (info["SUPABASE_ANON_KEY"] as? String) ?? ""
        if let v = UserDefaults.standard.string(forKey: "analytics.vid") {
            visitorID = v
        } else {
            visitorID = UUID().uuidString
            UserDefaults.standard.set(visitorID, forKey: "analytics.vid")
        }
    }

    private var build: String {
        (Bundle.main.infoDictionary?["CFBundleVersion"] as? String) ?? "?"
    }

    /// Record one thing a person did. Never throws, never blocks, never retries.
    func track(_ event: String, _ props: [String: Any] = [:], path: String? = nil) {
        guard Self.privacyLabelDeclared, enabled, !host.isEmpty, !anonKey.isEmpty, sent < capPerLaunch else { return }
        sent += 1
        var p = props
        p["platform"] = "ios"
        p["build"] = build
        p["city"] = props["city"] as? String ?? city
        let uid = auth?.session?.user.id.uuidString
        let token = auth?.session?.accessToken
        var row: [String: Any] = ["visitor_id": visitorID, "event": event,
                                  "props": p, "path": path ?? "/app"]
        if let uid { row["user_id"] = uid }
        guard let url = URL(string: "https://\(host)/rest/v1/events"),
              let body = try? JSONSerialization.data(withJSONObject: row) else { return }
        var req = URLRequest(url: url, timeoutInterval: 10)
        req.httpMethod = "POST"
        req.httpBody = body
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue(anonKey, forHTTPHeaderField: "apikey")
        // Signed in, the row is attributed to the account, which the table's
        // row check requires; signed out it is the anon key and user_id is null.
        req.setValue("Bearer \(token ?? anonKey)", forHTTPHeaderField: "Authorization")
        req.setValue("return=minimal", forHTTPHeaderField: "Prefer")
        let s = session
        Task.detached(priority: .background) { _ = try? await s.data(for: req) }
    }
}
