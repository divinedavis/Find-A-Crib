import Foundation
import Observation
import UIKit
import UserNotifications

/// Borough alerts on the phone (owner, 2026-09-17: "the alerts should be
/// sent via the app notifications"). The dispatcher that emails an alert the
/// minute a lottery or re-rental opens (lottery_alerts.py) also pushes it to
/// every device registered against that account — this is the device side.
///
/// Permission is asked at exactly one moment: right after alerts are turned
/// on, when "tell me the minute one opens" has just been said out loud. Never
/// on launch (see feedback_no_unsolicited_prompts). A later launch only
/// re-registers silently if permission was already granted, because APNs
/// tokens rotate.
///
/// The token is filed against the signed-in account by findacrib-api
/// (/api/push/register), with the environment the device THINKS it is in —
/// a claim the server double-checks on the first failed send (memory:
/// apns environment claim). TestFlight and the App Store are production;
/// only an Xcode-run build is sandbox.
@Observable @MainActor
final class PushService {
    static let shared = PushService()

    weak var auth: AuthService?
    weak var nav: AppNav?
    private(set) var status: UNAuthorizationStatus = .notDetermined
    private(set) var registeredToken: String?
    /// A token that arrived while signed out; uploaded on the next sign-in.
    private var pendingToken: String?
    /// Set while the "get alerts on this phone?" card should be up (RootView
    /// shows it) — see offerAtLaunchIfNeeded. `promptForSubscriber` picks the
    /// wording: someone already signed up is told their alerts will land
    /// here; everyone else is invited to set them up.
    var launchPrompt = false
    var promptForSubscriber = false
    private let defaults = UserDefaults.standard
    /// After "Not now", leave it a week before asking again.
    nonisolated static let snoozeDays = 7

    func refreshStatus() async {
        status = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
    }

    /// At launch and on sign-in: no prompt, just keep the token current when
    /// permission already exists.
    func reregisterIfAuthorized() async {
        await refreshStatus()
        if status == .authorized || status == .provisional || status == .ephemeral {
            UIApplication.shared.registerForRemoteNotifications()
        }
        if let t = pendingToken, auth?.session != nil { pendingToken = nil; await upload(t) }
    }

    /// The one ask. Returns whether notifications are on afterwards.
    @discardableResult
    func requestAfterAlerts() async -> Bool {
        await refreshStatus()
        if status == .denied { return false }
        if status == .authorized { UIApplication.shared.registerForRemoteNotifications(); return true }
        do {
            let granted = try await UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .sound, .badge])
            Analytics.shared.track("push_permission", ["granted": granted])
            await refreshStatus()
            if granted { UIApplication.shared.registerForRemoteNotifications() }
            return granted
        } catch {
            Analytics.shared.track("push_permission", ["granted": false, "error": String(describing: type(of: error))])
            return false
        }
    }

    // MARK: - The launch-time ask

    /// Owner (2026-09-18): everyone with the app gets asked to allow
    /// notifications — alerts only reach the phone after an Allow, and most
    /// people never reopen the alerts sheet where the ask used to live. So
    /// at launch, once, while permission is undetermined, a card says what
    /// the ask is for BEFORE the system prompt (which is one-shot: a
    /// reflexive Don't Allow can only be undone in Settings). A subscriber is
    /// told their alerts will land here; anyone else is invited to set alerts
    /// up, and "Turn on" takes them there after the prompt. "Not now" snoozes
    /// a week. This is the owner's deliberate exception to "no unsolicited
    /// prompts on entry".
    func offerAtLaunchIfNeeded() async {
        // The UI test suite launches with --no-launch-prompt: an in-app alert
        // two seconds into every test would sit on top of its taps. The one
        // test that pins the card launches with --reset-launch-prompt instead,
        // so a snooze left by an earlier run cannot hide it.
        let args = CommandLine.arguments
        if args.contains("--no-launch-prompt") { return }
        if args.contains("--reset-launch-prompt") { defaults.removeObject(forKey: "push.snoozedUntil") }
        await refreshStatus()
        guard Self.shouldOffer(status: status, snoozedUntil: defaults.object(forKey: "push.snoozedUntil") as? Date) else { return }
        if let session = auth?.session {
            promptForSubscriber = await Self.hasAlertSubscription(token: session.accessToken)
        } else {
            promptForSubscriber = false
        }
        Analytics.shared.track("push_prompt", ["step": "shown", "subscriber": promptForSubscriber])
        launchPrompt = true
    }

    func acceptLaunchPrompt() {
        Analytics.shared.track("push_prompt", ["step": "turn_on", "subscriber": promptForSubscriber])
        let toAlerts = !promptForSubscriber
        Task {
            await requestAfterAlerts()
            // Permission without a subscription alerts nobody: take them to
            // set one up (Profile → Alerts; it asks for sign-in first if needed).
            if toAlerts, let nav { nav.tab = .profile; nav.showAlerts = true }
        }
    }

    func snoozeLaunchPrompt() {
        Analytics.shared.track("push_prompt", ["step": "not_now", "subscriber": promptForSubscriber])
        defaults.set(Date().addingTimeInterval(Double(Self.snoozeDays) * 86_400), forKey: "push.snoozedUntil")
    }

    nonisolated static func shouldOffer(status: UNAuthorizationStatus, snoozedUntil: Date?, now: Date = Date()) -> Bool {
        guard status == .notDetermined else { return false }
        if let snoozedUntil, snoozedUntil > now { return false }
        return true
    }

    /// Whether the account has a live alert subscription, per the same
    /// endpoint the alerts sheet prefills from.
    nonisolated static func hasAlertSubscription(token: String) async -> Bool {
        var req = URLRequest(url: URL(string: "https://findacrib.com/api/alerts/prefs")!, timeoutInterval: 15)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let j = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] else { return false }
        return Self.isSubscribed(prefs: j)
    }

    nonisolated static func isSubscribed(prefs j: [String: Any]) -> Bool {
        (j["exists"] as? Bool) == true && (j["unsubscribed"] as? Bool) != true
    }

    // MARK: - From the app delegate

    func didRegister(deviceToken: Data) {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        registeredToken = hex
        Task { await upload(hex) }
    }

    func didFailToRegister(_ error: Error) {
        Analytics.shared.track("push_register_failed", ["error": String(describing: type(of: error))])
    }

    private func upload(_ token: String) async {
        guard let session = auth?.session else { pendingToken = token; return }
        var req = URLRequest(url: URL(string: "https://findacrib.com/api/push/register")!, timeoutInterval: 15)
        req.httpMethod = "POST"
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        req.setValue("Bearer \(session.accessToken)", forHTTPHeaderField: "Authorization")
        let build = (Bundle.main.infoDictionary?["CFBundleVersion"] as? String) ?? "?"
        req.httpBody = try? JSONSerialization.data(withJSONObject: ["token": token, "env": Self.environment, "build": build])
        let code = (try? await URLSession.shared.data(for: req)).flatMap { ($0.1 as? HTTPURLResponse)?.statusCode } ?? 0
        Analytics.shared.track("push_registered", ["env": Self.environment, "status": code])
    }

    // MARK: - Pure helpers (unit-tested)

    /// "sandbox" or "production": what the embedded provisioning profile says
    /// (`aps-environment`), else what the build configuration implies. Never a
    /// blanket default to sandbox — a Release build is a distribution build.
    static var environment: String {
        if let url = Bundle.main.url(forResource: "embedded", withExtension: "mobileprovision"),
           let data = try? Data(contentsOf: url),
           let env = environment(fromProfile: String(decoding: data, as: UTF8.self)) {
            return env
        }
        #if DEBUG
        return "sandbox"
        #else
        return "production"
        #endif
    }

    nonisolated static func environment(fromProfile text: String) -> String? {
        guard let r = text.range(of: "<key>aps-environment</key>") else { return nil }
        let tail = text[r.upperBound...].prefix(120)
        if tail.contains("<string>development</string>") { return "sandbox" }
        if tail.contains("<string>production</string>") { return "production" }
        return nil
    }

    /// The link a push carries (`url` at the top level of the payload).
    nonisolated static func deepLink(in userInfo: [AnyHashable: Any]) -> URL? {
        (userInfo["url"] as? String).flatMap { URL(string: $0) }
    }

    /// A findacrib.com building page (`/building/<boro>/<slug>-<bbl>/`) opens
    /// in the app; anything else — an agent's page, Housing Connect — opens
    /// in the browser.
    nonisolated static func buildingBBL(in url: URL) -> String? {
        guard url.host?.hasSuffix("findacrib.com") == true, url.path.hasPrefix("/building/") else { return nil }
        let last = url.pathComponents.last ?? ""
        guard let dash = last.lastIndex(of: "-") else { return nil }
        let bbl = String(last[last.index(after: dash)...])
        return bbl.count == 10 && bbl.allSatisfy(\.isNumber) ? bbl : nil
    }

    func open(_ url: URL) {
        Analytics.shared.track("push_open", ["url": url.absoluteString])
        if let bbl = Self.buildingBBL(in: url), let nav {
            nav.tab = .search
            nav.searchPath.append(.building(bbl))
        } else {
            UIApplication.shared.open(url)
        }
    }
}

/// UIKit's delegate, for the two APNs callbacks SwiftUI has no modifier for,
/// and the notification-center delegate for foreground banners and taps.
final class AppDelegate: NSObject, UIApplicationDelegate {
    private let notifications = NotificationDelegate()

    func application(_ application: UIApplication,
                     didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil) -> Bool {
        UNUserNotificationCenter.current().delegate = notifications
        return true
    }

    func application(_ application: UIApplication, didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data) {
        Task { @MainActor in PushService.shared.didRegister(deviceToken: deviceToken) }
    }

    func application(_ application: UIApplication, didFailToRegisterForRemoteNotificationsWithError error: Error) {
        Task { @MainActor in PushService.shared.didFailToRegister(error) }
    }
}

final class NotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    /// An alert that arrives while the app is open still shows as a banner:
    /// the person asked to be told the minute one opens, not only when the
    /// app is closed.
    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        completionHandler([.banner, .list, .sound])
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler completionHandler: @escaping () -> Void) {
        let info = response.notification.request.content.userInfo
        if let url = PushService.deepLink(in: info) {
            Task { @MainActor in PushService.shared.open(url) }
        }
        completionHandler()
    }
}
