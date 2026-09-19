import Foundation
import Observation

/// The Lotteries tab (owner, 2026-09-19): the NYC Housing Connect lotteries
/// open in the boroughs an alert subscriber signed up for. The tab shows for
/// everyone; tapping it without a subscription prompts the sign-up.
///
/// Two reads, both from findacrib.com: the person's own alert prefs (session
/// token; the API keys them on the verified email) and the public
/// housing_connect.json the alert dispatcher rewrites every 10 minutes.
/// Nothing new is collected — the prefs are the ones they already gave us.
@Observable @MainActor
final class LotteryFeed {
    static let shared = LotteryFeed()

    struct Lottery: Decodable, Identifiable, Equatable {
        let id: Int
        let name: String
        let borough: String
        let neighborhood: String?
        let rent_low: Int?
        let rent_high: Int?
        let income_min: Int?
        let income_max: Int?
        let household_min: Int?
        let household_max: Int?
        let beds: [String]?
        let closes: String?
        let href: String?
    }
    private struct Payload: Decodable { let lotteries: [Lottery] }

    /// Subscribed (and not unsubscribed) — the tab shows only when true.
    private(set) var subscribed = false
    /// True once we actually know whether they are subscribed (prefs read, or
    /// signed out). A tap before that must not prompt a real subscriber.
    private(set) var checked = false
    /// Borough codes from the signup: M, Bk, Q, Bx, SI.
    private(set) var boroughs: [String] = []
    private(set) var income: Int?
    private(set) var all: [Lottery] = []
    private(set) var loadFailed = false
    private(set) var loading = false

    weak var auth: AuthService?

    /// Open lotteries in the subscriber's boroughs, soonest deadline first.
    var mine: [Lottery] { Self.filter(all, boroughs: boroughs, today: Self.todayKey()) }

    /// `--lotteries-demo` stands in for a subscriber so the tab can be tested
    /// on a simulator, which is always signed out.
    private var demo: Bool { CommandLine.arguments.contains("--lotteries-demo") }

    /// Re-read the prefs; called on launch, sign-in/out, return to the app and
    /// after the alerts sheet saves.
    func refresh() async {
        if demo {
            subscribed = true; boroughs = ["Bx", "Bk", "M", "Q", "SI"]; income = 70_000; checked = true
        } else if let token = auth?.session?.accessToken {
            let j = await Self.prefs(token: token)
            if let j {
                subscribed = PushService.isSubscribed(prefs: j)
                boroughs = (j["boroughs"] as? [String]) ?? []
                income = j["income"] as? Int
                checked = true
            }   // a failed read keeps what we had: a flaky network should not hide the tab
        } else {
            subscribed = false; boroughs = []; income = nil; checked = true
        }
        if subscribed { await loadLotteries() }
    }

    func loadLotteries() async {
        loading = true; defer { loading = false }
        var req = URLRequest(url: URL(string: "https://findacrib.com/housing_connect.json")!, timeoutInterval: 20)
        req.cachePolicy = .reloadRevalidatingCacheData
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let p = try? JSONDecoder().decode(Payload.self, from: data) else { loadFailed = all.isEmpty; return }
        all = p.lotteries; loadFailed = false
    }

    private static func prefs(token: String) async -> [String: Any]? {
        var req = URLRequest(url: URL(string: "https://findacrib.com/api/alerts/prefs")!, timeoutInterval: 15)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200 else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }

    // MARK: - Pure pieces (unit-tested)

    nonisolated static func filter(_ l: [Lottery], boroughs: [String], today: String) -> [Lottery] {
        let names = Set(boroughs.map { Borough.name($0) })
        return l.filter { names.contains($0.borough) && ($0.closes ?? "9999") >= today }
            .sorted { ($0.closes ?? "9999", $0.name) < ($1.closes ?? "9999", $1.name) }
    }

    /// True when the income they entered sits inside the lottery's band.
    /// Household size also decides eligibility, which is why the card says
    /// "fits" and never hides anything.
    nonisolated static func incomeFits(_ income: Int?, _ l: Lottery) -> Bool {
        guard let income, let lo = l.income_min, let hi = l.income_max else { return false }
        return (lo...hi).contains(income)
    }

    nonisolated static func todayKey(_ d: Date = Date()) -> String {
        var cal = Calendar(identifier: .gregorian); cal.timeZone = TimeZone(identifier: "America/New_York")!
        let c = cal.dateComponents([.year, .month, .day], from: d)
        return String(format: "%04d-%02d-%02d", c.year ?? 0, c.month ?? 0, c.day ?? 0)
    }

    /// Whole days from today to the closing date (ET), nil if unparseable.
    nonisolated static func daysLeft(_ closes: String?, today: String = todayKey()) -> Int? {
        let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "America/New_York")
        guard let c = closes, let a = f.date(from: today), let b = f.date(from: c) else { return nil }
        return Int((b.timeIntervalSince(a) / 86_400).rounded())
    }
}
