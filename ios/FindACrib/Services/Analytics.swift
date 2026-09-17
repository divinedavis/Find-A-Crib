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
    /// One id per launch, so a sitting's events chain together the way the
    /// site's tab-session id does (the visitor id spans the install).
    let sessionID = String(UUID().uuidString.lowercased().prefix(12))
    /// How the app was opened this time: "direct", or the link it was opened
    /// with (a findacrib.com universal link or a findacrib:// URL, host and
    /// path only). Set from onOpenURL before the first event that needs it.
    var launchSource = "direct"
    /// The install's first launch, kept so every event can say how old the
    /// install is — the app-side stand-in for the site's first-touch record.
    private let installedAt: Date
    let isFirstLaunch: Bool
    /// Re-rental tiles already counted as seen this launch (per apartment,
    /// like the site's once-per-session impression rule).
    private var seenTiles = Set<String>()
    private var sent = 0
    /// A runaway loop must not be able to write rows all afternoon; the site
    /// caps its impression rows the same way.
    private let capPerLaunch = 400

    /// ON since 2026-09-16, because the App Privacy answers now say so.
    ///
    /// `scripts/asc_push_privacy_iris.py` published NAME, EMAIL_ADDRESS,
    /// USER_ID and PURCHASE_HISTORY (App Functionality) plus
    /// PRODUCT_INTERACTION and OTHER_USAGE_DATA (Analytics) — every one
    /// linked to the account, none used for tracking. Adding an event that
    /// collects anything outside those six types means publishing the label
    /// again BEFORE the build ships.
    static let privacyLabelDeclared = true

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
        if let t = UserDefaults.standard.object(forKey: "analytics.installed") as? Date {
            installedAt = t; isFirstLaunch = false
        } else {
            installedAt = Date(); isFirstLaunch = true
            UserDefaults.standard.set(installedAt, forKey: "analytics.installed")
        }
    }

    // MARK: - Pure helpers (unit-tested)

    /// The launch source for a URL the app was opened with: host and path,
    /// never the query (a magic link or a token must not land in a log).
    nonisolated static func source(for url: URL) -> String {
        let host = url.host ?? url.scheme ?? "url"
        let path = url.path.isEmpty ? "" : url.path
        return "\(url.scheme == "findacrib" ? "app" : "link"):\(host)\(path)".prefix(120).description
    }

    /// The shape of a search, never its text: which filters were used.
    nonisolated static func shape(_ q: SearchQuery) -> [String: Any] {
        ["locations": q.locations.count, "priced": q.minPrice != nil || q.maxPrice != nil,
         "beds": q.beds.count, "available_only": q.availableOnly, "vouchers_only": q.vouchersOnly,
         "hcr_only": q.hcrOnly, "filters": q.activeFilterCount]
    }

    /// What a re-rental tile event says about the tile — the same shape the
    /// site sends (featProps in index.html), so the funnel cuts the same way.
    nonisolated static func tileProps(_ f: FeaturedListing, slot: Int) -> [String: Any] {
        ["kind": "rerental", "agent": f.agent, "addr": f.address, "boro": f.borough ?? "",
         "slot": slot, "link": f.hrefKind ?? "listing"]
    }

    /// A re-rental tile came on screen: one `tile_impression` per apartment
    /// per launch. (On the phone the list is lazy, so "served" and "seen" are
    /// the same moment; the site's `tile_served` has no separate meaning here.)
    func tileSeen(_ f: FeaturedListing, slot: Int) {
        guard !seenTiles.contains(f.id) else { return }
        seenTiles.insert(f.id)
        track("tile_impression", Self.tileProps(f, slot: slot))
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
        // The same reserved names the site uses on every row: which sitting,
        // how the app was opened this time, and how old the install is.
        p["sid"] = sessionID
        p["touch"] = ["src": launchSource]
        p["first"] = ["at": ISO8601DateFormatter().string(from: installedAt),
                      "days": Int(Date().timeIntervalSince(installedAt) / 86400)]
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
