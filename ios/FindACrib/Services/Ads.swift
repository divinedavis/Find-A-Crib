import GoogleMobileAds
import SwiftUI
import UIKit

/// A Google (AdMob) banner at the foot of every screen (owner, 2026-09-25:
/// "google ad slots … on every view we have on the app").
///
/// One banner lives for the whole launch and sits under the tab bar, so every
/// tab and every pushed screen shows it. Moving to a new screen asks Google
/// for a fresh ad — but never sooner than `minReload` after the last one,
/// which is AdMob's own rule for apps whose users hop between screens
/// (support.google.com/admob/answer/2936217: no new request inside 60 s).
/// Faster than that and Google discards the impressions and flags the account.
///
/// Plus subscribers see no banner.
@Observable @MainActor
final class Ads: NSObject {
    static let shared = Ads()

    /// Google's published test IDs: they serve real-looking "Test mode" ads
    /// that pay nothing and can never get the account banned for invalid
    /// clicks. The app ID in Info.plist (project.yml GADApplicationIdentifier)
    /// is the matching test app until the AdMob app exists.
    static let testBannerUnit = "ca-app-pub-3940256099942544/2435281174"
    /// The real banner unit from the AdMob console. Empty until the owner has
    /// an AdMob account with Find A Crib registered in it.
    static let liveBannerUnit = ""
    /// Like Analytics.privacyLabelDeclared. The SDK collects a device ID,
    /// coarse location (IP), advertising data, product interaction and
    /// performance data (developers.google.com/admob/ios/privacy/data-disclosure)
    /// — none of which the App Privacy label published on 2026-09-16 declares.
    /// Flip only after asc_push_privacy_iris.py has published those types.
    static let privacyLabelDeclared = false

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

    /// AdMob: a user moving between screens must not trigger a new request
    /// inside 60 seconds.
    static let minReload: TimeInterval = 60

    /// Whether a screen change may ask for a new ad now.
    nonisolated static func mayReload(lastLoad: Date?, now: Date, min: TimeInterval = minReload) -> Bool {
        guard let lastLoad else { return true }
        return now.timeIntervalSince(lastLoad) >= min
    }

    let mode: Mode
    private(set) var started = false
    /// True once a banner has filled; the slot keeps no height before that,
    /// so an empty (unfilled) request never leaves a blank strip.
    private(set) var filled = false
    private(set) var bannerHeight: CGFloat = 50
    private var banner: BannerView?
    private var lastLoad: Date?
    /// The full screen key (it can carry a search), compared only.
    private var lastKey = ""
    /// What the ad events log: the tab and the kind of screen, never the
    /// search inside it (the same rule as Analytics.shape).
    private var screen = "launch"

    /// "Search|2|results(SearchQuery(…))" → "Search/results".
    nonisolated static func screenName(_ key: String) -> String {
        let parts = key.split(separator: "|", maxSplits: 2, omittingEmptySubsequences: false)
        let tab = parts.first.map(String.init) ?? ""
        let route = parts.count > 2 ? String(parts[2].prefix { $0.isLetter }) : ""
        return route.isEmpty ? tab : "\(tab)/\(route)"
    }

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
        guard mode != .off, !started else { return }
        started = true
        MobileAds.shared.start()
        // The slot is on screen (and its banner built) before the launch
        // task gets here; its first request was held back, so send it now.
        if banner != nil, lastLoad == nil { load() }
    }

    /// The one banner, created on first use and reused on every screen.
    func bannerView(width: CGFloat) -> BannerView {
        let size = currentOrientationAnchoredAdaptiveBanner(width: width)
        if let banner {
            if abs(banner.adSize.size.width - size.size.width) > 1 { banner.adSize = size; load() }
            return banner
        }
        let b = BannerView(adSize: size)
        b.adUnitID = unitID
        b.delegate = self
        b.accessibilityIdentifier = "ad.banner"
        bannerHeight = size.size.height
        banner = b
        load()
        return b
    }

    /// A new screen came up. Ask Google for a new ad if the last one has been
    /// on screen for at least a minute; otherwise the current one stays.
    func screenChanged(to key: String) {
        guard key != lastKey else { return }
        lastKey = key
        screen = Self.screenName(key)
        guard banner != nil, Self.mayReload(lastLoad: lastLoad, now: Date()) else { return }
        load()
    }

    private func load() {
        guard let banner, started else { return }
        if banner.rootViewController == nil {
            banner.rootViewController = ReviewPrompt.activeScene?.keyWindow?.rootViewController
        }
        // The first banner is built while the launch splash is still up, when
        // there is no active window yet; a request then never fills and the
        // home screen stayed blank. Try again once the window exists.
        guard banner.rootViewController != nil else {
            Task { @MainActor [weak self] in
                try? await Task.sleep(for: .seconds(1))
                self?.load()
            }
            return
        }
        lastLoad = Date()
        banner.load(Request())
    }
}

extension Ads: BannerViewDelegate {
    nonisolated func bannerViewDidReceiveAd(_ bannerView: BannerView) {
        MainActor.assumeIsolated {
            filled = true
            bannerHeight = bannerView.adSize.size.height
        }
    }

    nonisolated func bannerView(_ bannerView: BannerView, didFailToReceiveAdWithError error: Error) {
        MainActor.assumeIsolated {
            Analytics.shared.track("ad_fail", ["screen": screen, "code": (error as NSError).code])
        }
    }

    /// Google's own impression count (the ad rendered), per screen, so the
    /// dashboard can say what the slot does before AdMob's report arrives.
    nonisolated func bannerViewDidRecordImpression(_ bannerView: BannerView) {
        MainActor.assumeIsolated {
            Analytics.shared.track("ad_impression", ["screen": screen, "mode": mode == .live ? "live" : "test"])
        }
    }

    nonisolated func bannerViewDidRecordClick(_ bannerView: BannerView) {
        MainActor.assumeIsolated {
            Analytics.shared.track("ad_click", ["screen": screen, "mode": mode == .live ? "live" : "test"])
        }
    }
}

/// The strip under the tab bar. Zero height until an ad has filled, and
/// absent for Plus subscribers and builds that show no ads.
struct AdSlot: View {
    @Environment(AuthService.self) private var auth
    @Environment(PlusStore.self) private var plus
    private var ads: Ads { Ads.shared }

    var body: some View {
        if ads.mode != .off, !auth.hasPlus, !plus.entitled {
            GeometryReader { geo in
                BannerRepresentable(width: geo.size.width)
            }
            .frame(height: ads.filled ? ads.bannerHeight : 0)
            .frame(maxWidth: .infinity)
            .background(Color.white.ignoresSafeArea(edges: .bottom))
            .clipped()
            .accessibilityIdentifier("ad.slot")
        }
    }
}

private struct BannerRepresentable: UIViewRepresentable {
    let width: CGFloat
    func makeUIView(context: Context) -> UIView {
        let host = UIView()
        guard width > 0 else { return host }
        attach(to: host)
        return host
    }
    func updateUIView(_ host: UIView, context: Context) {
        guard width > 0 else { return }
        if host.subviews.isEmpty { attach(to: host) } else { _ = Ads.shared.bannerView(width: width) }
    }
    private func attach(to host: UIView) {
        let b = Ads.shared.bannerView(width: width)
        b.removeFromSuperview()
        b.translatesAutoresizingMaskIntoConstraints = false
        host.addSubview(b)
        NSLayoutConstraint.activate([
            b.centerXAnchor.constraint(equalTo: host.centerXAnchor),
            b.topAnchor.constraint(equalTo: host.topAnchor),
        ])
    }
}
