import GoogleMobileAds
import StoreKit
import SwiftUI
import UIKit

/// Google (AdMob) ads in the results feed, in the re-rental tiles' slots
/// (owner, 2026-09-25: "have the mobile ads replace the rerental tiles … on
/// the feed instead of the banner at the bottom" — the same trade the website
/// made with its lead tile).
///
/// Each ad is a 300×250 medium rectangle, the standard in-feed size, served
/// by the existing banner unit. A slot never waits on the network: the app
/// keeps `poolSize` ads loaded ahead of time, and a slot that scrolls in when
/// none is ready shows its re-rental instead. A slot keeps whatever it was
/// given first, so nothing swaps under the reader's thumb.
///
/// Plus subscribers see no ads. Real ads run on the US App Store only:
/// anywhere in the EEA, UK or Switzerland Google requires a certified consent
/// screen first, and the app is about American cities anyway.
@Observable @MainActor
final class Ads: NSObject {
    static let shared = Ads()

    /// Google's published test unit: real-looking "Test mode" ads that pay
    /// nothing and can never get the account banned for invalid clicks. It
    /// works under the real app ID, which is why TestFlight and the simulator
    /// keep using it — the owner is the TestFlight audience, and a tap on a
    /// live ad from their own phone is exactly what Google bans accounts for.
    static let testBannerUnit = "ca-app-pub-3940256099942544/2435281174"
    /// "Every screen banner" in the AdMob console (app
    /// ca-app-pub-8077227518694725~3025780207, set in project.yml), created
    /// 2026-09-25. A banner unit serves any banner size, the medium rectangle
    /// included. Its 60-second auto-refresh applies to a rectangle while it is
    /// on screen, which is within AdMob's 30–120 s range.
    static let liveBannerUnit = "ca-app-pub-8077227518694725/7882431778"
    /// Like Analytics.privacyLabelDeclared. ON since 2026-09-25: the App
    /// Privacy label now declares what the SDK collects — device ID, coarse
    /// location, advertising data, product interaction, crash and performance
    /// data (developers.google.com/admob/ios/privacy/data-disclosure) — as
    /// linked, NOT used for tracking (scripts/asc_push_privacy_iris.py). Search
    /// history (the page + words Ads.context sends) was added to it the same
    /// night, before the build that sends them.
    static let privacyLabelDeclared = true

    enum Mode: Equatable { case off, test, live }

    /// Which ads this build shows. App Store builds stay dark until the real
    /// unit AND the privacy label exist; TestFlight shows Google's test ads so
    /// the placement can be looked at on a phone; a Debug build (simulator,
    /// UI tests) shows nothing unless launched with `--ads-demo`.
    nonisolated static func mode(debug: Bool, beta: Bool, demo: Bool, liveUnit: String, labelDeclared: Bool) -> Mode {
        if debug { return demo ? .test : .off }
        if beta { return .test }
        return !liveUnit.isEmpty && labelDeclared ? .live : .off
    }

    /// Every request asks for NON-PERSONALIZED ads. The App Privacy label says
    /// nothing is used to track, and the app never shows Apple's tracking
    /// (ATT) prompt; personalized ads would be targeting on other companies'
    /// data, which is tracking in Apple's sense and needs both. Flip this
    /// only together with an ATT prompt and a relabel.
    static let nonPersonalized = true

    /// What the ads should be about. Non-personalized ads can only be as
    /// relevant as the context Google is told, and an app gives it almost
    /// none on its own (owner, 2026-09-25: ads "tailored towards people
    /// looking for apartments"). So each request names the findacrib.com page
    /// that shows the same search, which Google reads as it would any page it
    /// places an ad on, plus the search's words. Nothing here is about the
    /// person — the privacy label and npa=1 are unaffected.
    struct Context: Equatable {
        var contentURL: String
        var keywords: [String]
    }

    static let home = Context(contentURL: "https://findacrib.com/",
                              keywords: ["apartments for rent", "rent stabilized apartments",
                                         "New York City apartments", "renters insurance", "movers"])

    /// The page and words for a search: NYC boroughs and ZIPs have their own
    /// pages (/borough/<slug>/, /zip/<zip>/); LA, SF and DC have a city page;
    /// everything else falls back to the home page.
    nonisolated static func context(for q: SearchQuery, city: City) -> Context {
        var words = ["apartments for rent", "renters insurance", "movers"]
        var url = "https://findacrib.com/"
        if city.isNYC {
            words += ["rent stabilized apartments", "New York City apartments"]
            switch q.locations.first {
            case .borough(let code)?:
                url = "https://findacrib.com/borough/\(Borough.slug(code))/"
                words.append("\(Borough.name(code)) apartments")
            case .zip(let z)?:
                url = "https://findacrib.com/zip/\(z)/"
                words.append("apartments \(z)")
            case .neighborhood(let nb)?:
                words.append("\(nb) apartments")
            default:
                break   // a map area or nothing picked: the home page
            }
            if q.vouchersOnly { words.append("housing voucher apartments") }
            if q.hcrOnly { words.append("affordable housing lottery") }
        } else {
            if ["la", "sf", "dc"].contains(city.id) { url = "https://findacrib.com/\(city.id)/" }
            words.append("\(city.name) apartments")
            words.append(city.isIncomeRestricted ? "affordable housing" : "rent controlled apartments")
        }
        return Context(contentURL: url, keywords: words)
    }

    /// The context the next ad requests carry; set by the results screen.
    @ObservationIgnored private(set) var context = home

    static func request(_ ctx: Context = home) -> Request {
        let r = Request()
        r.contentURL = ctx.contentURL
        r.keywords = ctx.keywords
        if nonPersonalized {
            let extras = Extras()
            extras.additionalParameters = ["npa": "1"]
            r.register(extras)
        }
        return r
    }

    /// Live ads only on the US storefront (StoreKit's alpha-3 code).
    nonisolated static func servesLive(countryCode: String?) -> Bool { countryCode == "USA" }

    /// Ads kept loaded ahead of the feed. Two covers the first two re-rental
    /// slots (the 3rd tile and one 8–15 further) without asking Google for
    /// ads nobody scrolls to, which drags the unit's match rate down.
    static let poolSize = 2

    /// What a feed slot shows, decided once: an ad if one was ready when the
    /// slot first appeared, the re-rental otherwise.
    enum Fill: Equatable { case ad(Int), rerental }

    /// Pure: the decision for a slot, given what it already has and whether
    /// an ad is ready now. A decided slot never changes.
    nonisolated static func decide(existing: Fill?, readyAds: Int, showsAds: Bool) -> Bool {
        existing == nil && showsAds && readyAds > 0
    }

    let mode: Mode
    /// Whether ads run at all: test builds at once, a live build only after
    /// StoreKit confirms the US storefront.
    private(set) var active = false
    private(set) var started = false

    // The pool and the slot decisions are read while SwiftUI draws the feed;
    // observing them would redraw the feed from inside its own body.
    /// Loaded, not yet shown.
    @ObservationIgnored private var ready: [BannerView] = []
    /// Requests out. Held strongly: a BannerView nobody holds is freed before
    /// its ad arrives, and its address — the old ObjectIdentifier key — was
    /// reused by the next one, so the pool never filled and topUp() spun.
    @ObservationIgnored private var loading: [BannerView] = []
    /// Slot key → what it shows. Kept per results screen (`reset`).
    @ObservationIgnored private var fills: [String: Fill] = [:]
    /// Ads handed to a slot, by id, so a slot scrolled away and back shows
    /// the same ad.
    @ObservationIgnored private var shown: [Int: BannerView] = [:]
    @ObservationIgnored private var nextID = 0

    override private init() {
        #if DEBUG
        let debug = true
        #else
        let debug = false
        #endif
        mode = Self.mode(debug: debug, beta: ReviewPrompt.isBeta,
                         demo: CommandLine.arguments.contains("--ads-demo"),
                         liveUnit: Self.liveBannerUnit, labelDeclared: Self.privacyLabelDeclared)
        super.init()
    }

    var unitID: String { mode == .live ? Self.liveBannerUnit : Self.testBannerUnit }

    /// Starts the SDK — only when this build shows ads, so an App Store build
    /// that is still dark never runs Google's code or sends it anything.
    func start() {
        switch mode {
        case .off: return
        case .test: begin()
        case .live:
            Task { @MainActor in
                guard Self.servesLive(countryCode: await Storefront.current?.countryCode) else { return }
                begin()
            }
        }
    }

    private func begin() {
        guard !started else { return }
        started = true
        active = true
        MobileAds.shared.start()
        topUp()
    }

    /// Keep `poolSize` ads loaded or loading.
    private func topUp() {
        guard started else { return }
        guard let root = ReviewPrompt.activeScene?.keyWindow?.rootViewController else {
            // Launch splash: no window yet. Try again in a second.
            Task { @MainActor [weak self] in
                try? await Task.sleep(for: .seconds(1))
                self?.topUp()
            }
            return
        }
        while ready.count + loading.count < Self.poolSize {
            let b = BannerView(adSize: AdSizeMediumRectangle)
            b.adUnitID = unitID
            b.rootViewController = root
            b.delegate = self
            b.accessibilityIdentifier = "feed-ad-banner"
            loading.append(b)
            b.load(Self.request(context))
        }
    }

    @ObservationIgnored private var feedKey: AnyHashable?

    /// A new search: slots start undecided again. The same search coming back
    /// into view (back from a building) keeps its slots and their ads.
    func beginFeed(_ key: AnyHashable, context ctx: Context? = nil) {
        guard key != feedKey else { return }
        feedKey = key
        // Ads loaded from here on are about this search. The ones already in
        // the pool keep the context they were requested with.
        if let ctx { context = ctx }
        fills = [:]
        shown = [:]
    }

    /// What the feed slot `key` shows. The first call decides; later calls
    /// (the slot scrolled back into view) return the same answer.
    func fill(for key: String, showsAds: Bool) -> Fill {
        if let f = fills[key] { return f }
        guard Self.decide(existing: nil, readyAds: ready.count, showsAds: showsAds && active) else {
            fills[key] = .rerental
            return .rerental
        }
        let b = ready.removeFirst()
        nextID += 1
        shown[nextID] = b
        fills[key] = .ad(nextID)
        topUp()
        return .ad(nextID)
    }

    func banner(_ id: Int) -> BannerView? { shown[id] }

    private var modeName: String { mode == .live ? "live" : "test" }
}

extension Ads: BannerViewDelegate {
    nonisolated func bannerViewDidReceiveAd(_ bannerView: BannerView) {
        MainActor.assumeIsolated {
            // Auto-refresh of an ad already in a slot lands here too.
            guard let i = loading.firstIndex(where: { $0 === bannerView }) else { return }
            ready.append(loading.remove(at: i))
        }
    }

    nonisolated func bannerView(_ bannerView: BannerView, didFailToReceiveAdWithError error: Error) {
        MainActor.assumeIsolated {
            guard let i = loading.firstIndex(where: { $0 === bannerView }) else { return }
            loading.remove(at: i)
            Analytics.shared.track("ad_fail", ["screen": "results/feed", "code": (error as NSError).code])
            // No fill (a new account, no demand): back off rather than retry
            // in a loop. The slots show re-rentals meanwhile.
            Task { @MainActor [weak self] in
                try? await Task.sleep(for: .seconds(60))
                self?.topUp()
            }
        }
    }

    /// Google's own impression count (the ad rendered), so the dashboard can
    /// say what the slots do before AdMob's report arrives.
    nonisolated func bannerViewDidRecordImpression(_ bannerView: BannerView) {
        MainActor.assumeIsolated {
            Analytics.shared.track("ad_impression", ["screen": "results/feed", "mode": modeName])
        }
    }

    nonisolated func bannerViewDidRecordClick(_ bannerView: BannerView) {
        MainActor.assumeIsolated {
            Analytics.shared.track("ad_click", ["screen": "results/feed", "mode": modeName])
        }
    }
}

/// A feed slot: Google's ad when one was ready, the re-rental otherwise.
struct FeedAdSlot: View {
    let listing: FeaturedListing
    let slot: Int
    /// Stable per results screen: the slot index plus the apartment it holds.
    let key: String
    @Environment(AuthService.self) private var auth
    @Environment(PlusStore.self) private var plus

    var body: some View {
        let showsAds = !auth.hasPlus && !plus.entitled
        switch Ads.shared.fill(for: key, showsAds: showsAds) {
        case .ad(let id):
            if let b = Ads.shared.banner(id) { FeedAdCard(banner: b) } else { RerentalCard(listing: listing, slot: slot) }
        case .rerental:
            RerentalCard(listing: listing, slot: slot)
        }
    }
}

/// The ad in a card the size of the feed's other cards, flagged Sponsored.
private struct FeedAdCard: View {
    let banner: BannerView
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Sponsored").font(.se(13, .semibold)).foregroundStyle(SE.ink3)
            BannerHost(banner: banner)
                .frame(width: 300, height: 250)
                .frame(maxWidth: .infinity)
        }
        .padding(14)
        .background(Color.white)
        .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line, lineWidth: 1))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("feed-ad")
    }
}

private struct BannerHost: UIViewRepresentable {
    let banner: BannerView
    func makeUIView(context: Context) -> UIView {
        let host = UIView()
        attach(to: host)
        return host
    }
    func updateUIView(_ host: UIView, context: Context) {
        if banner.superview !== host { attach(to: host) }
    }
    private func attach(to host: UIView) {
        banner.removeFromSuperview()
        banner.translatesAutoresizingMaskIntoConstraints = false
        host.addSubview(banner)
        NSLayoutConstraint.activate([
            banner.centerXAnchor.constraint(equalTo: host.centerXAnchor),
            banner.centerYAnchor.constraint(equalTo: host.centerYAnchor),
        ])
    }
}
