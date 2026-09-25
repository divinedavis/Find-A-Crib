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

    /// A New Jersey drawing (owner, 2026-09-24): a town's affordable rentals or
    /// sales, from the list Affordable Homes New Jersey (CGP&H) publishes. The
    /// source names only the town and the date to join its waiting list by —
    /// units, rents and income limits show only inside a CGP&H profile.
    /// scrape_nj_lotteries.py writes the file once a day.
    struct NJLottery: Decodable, Identifiable, Equatable {
        let id: String
        let town: String
        let county: String?
        let tenure: String      // "rent" or "buy"
        let closes: String?     // nil while "COMING SOON"
        let coming_soon: Bool?
        /// The development behind the drawing ("The Overlook at Van
        /// Emburgh"), from nj/cgph_links.json; nil for a town not curated yet.
        let development: String?
        /// That listing on CGP&H (?lid=), or its rental/ownership listings page.
        let href: String?
        var isRental: Bool { tenure == "rent" }
    }
    private struct NJPayload: Decodable { let lotteries: [NJLottery] }

    /// Subscribed (and not unsubscribed) — the tab shows only when true.
    private(set) var subscribed = false
    /// True once we actually know whether they are subscribed (prefs read, or
    /// signed out). A tap before that must not prompt a real subscriber.
    private(set) var checked = false
    /// Borough codes from the signup: M, Bk, Q, Bx, SI.
    private(set) var boroughs: [String] = []
    private(set) var income: Int?
    private(set) var all: [Lottery] = []
    /// Every NJ drawing in the file; `njOpen` drops the ones already closed.
    private(set) var nj: [NJLottery] = []
    var njOpen: [NJLottery] { Self.njFilter(nj, today: Self.todayKey()) }
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
        // Before the launch restore, the stored token may be expired: an
        // answer now would be a wrong "not subscribed". Wait for it.
        if !demo, let auth, !auth.restored { return }
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
        // Both files at once; NJ's result lands whatever Housing Connect does.
        async let jersey = Self.loadNJ()
        var req = URLRequest(url: URL(string: "https://findacrib.com/housing_connect.json")!, timeoutInterval: 20)
        req.cachePolicy = .reloadRevalidatingCacheData
        let got = try? await URLSession.shared.data(for: req)
        if let j = await jersey { nj = j }
        guard let (data, resp) = got,
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let p = try? JSONDecoder().decode(Payload.self, from: data) else { loadFailed = all.isEmpty; return }
        all = p.lotteries; loadFailed = false
    }

    /// NJ drawings; nil on any failure so a dropped connection keeps what we had.
    private static func loadNJ() async -> [NJLottery]? {
        var req = URLRequest(url: URL(string: "https://findacrib.com/nj_lotteries.json")!, timeoutInterval: 20)
        req.cachePolicy = .reloadRevalidatingCacheData
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let p = try? JSONDecoder().decode(NJPayload.self, from: data) else { return nil }
        return p.lotteries
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

    /// NJ drawings still open: a join-by date today or later, or "coming
    /// soon". Soonest first; coming-soon ones last, as they have no date.
    nonisolated static func njFilter(_ l: [NJLottery], today: String) -> [NJLottery] {
        l.filter { $0.closes.map { $0 >= today } ?? ($0.coming_soon ?? false) }
            .sorted { ($0.closes ?? "9999", $0.town) < ($1.closes ?? "9999", $1.town) }
    }

    /// Bedroom count from the feeds' wording: "Studio"/"studio" -> 0,
    /// "1-bed" or "1" -> 1. Nil when it cannot tell.
    nonisolated static func bedCount(_ s: String) -> Int? {
        let t = s.trimmingCharacters(in: .whitespaces).lowercased()
        if t.hasPrefix("studio") || t == "0" { return 0 }
        let digits = t.prefix { $0.isNumber }
        return digits.isEmpty ? nil : Int(digits)
    }

    /// The bedroom filter on the Lotteries tab (owner, 2026-09-21): someone
    /// who needs a 1-bed does not see a lottery that only has 2- and 3-beds.
    /// `want` holds 0 (studio) … 4, where 4 means four or more; empty means
    /// any. A listing that publishes no sizes is kept — hiding it would say
    /// "none for you" when the truth is "not stated" (41 of 43 re-rentals
    /// on 2026-09-22 carry no bedroom count).
    nonisolated static func bedsMatch(_ beds: [String]?, want: Set<Int>) -> Bool {
        guard !want.isEmpty else { return true }
        let counts = (beds ?? []).compactMap(bedCount)
        guard !counts.isEmpty else { return true }
        return counts.contains { want.contains(min($0, 4)) }
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
