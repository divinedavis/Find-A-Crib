import SwiftUI
import ImageIO
import UIKit

/// The photo at the top of a lottery card (owner, 2026-09-25: "are we not
/// able to get images for these?"). The listing's own photo where the agency
/// publishes one (SF DAHLIA, Access Housing LA, Doorway, NYC Housing Connect
/// since 2026-11-17); otherwise the street at its address from Apple Look
/// Around, the same picture the building cards use (Miami's lease-ups). No
/// photo and no place: no header.
struct LotteryPhoto: View {
    let key: String
    var url: URL? = nil
    var lat: Double? = nil
    var lng: Double? = nil
    /// The lottery's whole photo set, lead first (Housing Connect, 2026-11-18:
    /// "doesn't housing connect have multiple photos for these?"). Two or
    /// more swipe like a re-rental card's, with page dots.
    var urls: [URL] = []
    @State private var image: UIImage?
    /// The agency photo would not load: show the street instead of a blank.
    @State private var failed = false
    @State private var page = 0

    var body: some View {
        if urls.count > 1 {
            TabView(selection: $page) {
                ForEach(Array(urls.enumerated()), id: \.offset) { i, u in
                    LotteryPhotoPage(url: u).tag(i)
                }
            }
            .tabViewStyle(.page(indexDisplayMode: .always))
            .background(ImagePlaceholder())
            .task(id: urls) { RemotePhotos.shared.prefetch(Array(urls.dropFirst())) }
            .frame(height: 190).frame(maxWidth: .infinity).clipped().contentShape(Rectangle())
            .onChange(of: page) { _, i in
                if i == 1 { Analytics.shared.track("lottery_photos_swipe", ["key": key, "photos": urls.count]) }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(String(localized: "Photo \(page + 1) of \(urls.count)"))
            .accessibilityAdjustableAction { dir in
                page = dir == .increment ? min(page + 1, urls.count - 1) : max(page - 1, 0)
            }
            .accessibilityIdentifier("lottery-photo")
        } else if let url, !(failed && lat != nil && lng != nil) {
            ZStack {
                ImagePlaceholder()
                if let image { FillImage(image: image) }
            }
            .frame(height: 190).frame(maxWidth: .infinity).clipped().contentShape(Rectangle())
            .task(id: url) {
                image = await RemotePhotos.shared.image(url)
                failed = image == nil
            }
            .accessibilityElement(children: .ignore).accessibilityLabel("Photo of the building")
            .accessibilityIdentifier("lottery-photo")
        } else if let lat, let lng {
            BuildingImage(building: Building(bbl: "lot-\(key)", b: "", a: "", z: nil, lat: lat, lng: lng))
                .frame(height: 190).frame(maxWidth: .infinity).clipped().contentShape(Rectangle())
                .accessibilityElement(children: .ignore).accessibilityLabel("Photo of the building")
            .accessibilityIdentifier("lottery-photo")
        }
    }
}

/// One page of a lottery's photo set, loaded when it is first shown.
private struct LotteryPhotoPage: View {
    let url: URL
    @State private var image: UIImage?
    var body: some View {
        ZStack {
            ImagePlaceholder()
            if let shown = image ?? RemotePhotos.shared.cached(url) { FillImage(image: shown) }
        }
        .task(id: url) { image = await RemotePhotos.shared.image(url) }
    }
}

/// Listing photos from the agencies' buckets, shrunk on the way in: some are
/// 4 MB originals, and a card needs ~900 px. Decoded off the main thread and
/// kept in memory for the session.
///
/// Not an actor any more (2026-10-02): an actor runs one call at a time, so a
/// screen of cards decoded its photos one after another on a single core.
/// NSCache is thread-safe, and each call owns its own data, so the fetches
/// and the ImageIO decodes now run side by side across the cores.
final class RemotePhotos: @unchecked Sendable {
    static let shared = RemotePhotos()
    /// Decoded photos, priced by their bytes: ~60 MB, room for every card's
    /// gallery in a session (215 re-rental photos on 2026-11-18). A count
    /// limit of 120 evicted photos the list scrolled back to, and they loaded
    /// again from the network (owner, 2026-11-18: "some of the images don't
    /// load until late").
    private let cache: NSCache<NSURL, UIImage> = {
        let c = NSCache<NSURL, UIImage>()
        c.totalCostLimit = 60 * 1024 * 1024
        return c
    }()
    /// Its own disk cache: the shared session's (10 MB) could not hold a
    /// day's photos, so every launch fetched them again.
    private let session: URLSession = {
        let cfg = URLSessionConfiguration.default
        cfg.urlCache = URLCache(memoryCapacity: 16 * 1024 * 1024, diskCapacity: 300 * 1024 * 1024,
                                directory: FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first?.appendingPathComponent("remote-photos"))
        cfg.requestCachePolicy = .returnCacheDataElseLoad
        cfg.httpMaximumConnectionsPerHost = 6
        return URLSession(configuration: cfg)
    }()
    /// One fetch per photo: a card on screen and a prefetch asking for the
    /// same photo share the download.
    private let lock = NSLock()
    private var inFlight: [URL: Task<UIImage?, Never>] = [:]

    func cached(_ url: URL) -> UIImage? { cache.object(forKey: url as NSURL) }

    func image(_ url: URL, maxPixels: Int = 900) async -> UIImage? {
        if let hit = cached(url) { return hit }
        let session = session
        let t: Task<UIImage?, Never> = lock.withLock {
            if let t = inFlight[url] { return t }
            let t = Task<UIImage?, Never>(priority: .userInitiated) {
                await Self.load(url, maxPixels: maxPixels, session: session)
            }
            inFlight[url] = t
            return t
        }
        let img = await t.value
        lock.withLock { _ = inFlight.removeValue(forKey: url) }
        if let img { cache.setObject(img, forKey: url as NSURL, cost: img.cost) }
        return img
    }

    /// Start loading a card's other photos as soon as the card is built, so
    /// swiping to them finds them ready instead of blank.
    func prefetch(_ urls: [URL]) {
        for u in urls where cached(u) == nil {
            Task(priority: .utility) { _ = await self.image(u) }
        }
    }

    private static func load(_ url: URL, maxPixels: Int, session: URLSession) async -> UIImage? {
        let req = URLRequest(url: url, cachePolicy: .returnCacheDataElseLoad, timeoutInterval: 20)
        guard let (data, resp) = try? await session.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let src = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let opts: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                     kCGImageSourceCreateThumbnailWithTransform: true,
                                     kCGImageSourceShouldCacheImmediately: true,
                                     kCGImageSourceThumbnailMaxPixelSize: maxPixels]
        guard let cg = CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary) else { return nil }
        return UIImage(cgImage: cg)
    }
}

private extension UIImage {
    /// Decoded size in bytes, the NSCache cost.
    var cost: Int { cgImage.map { $0.bytesPerRow * $0.height } ?? 1 }
}

/// A remote photo through RemotePhotos — downsampled, decoded off the main
/// thread, cached — in place of AsyncImage, which decodes the full-size file
/// at draw time and keeps no cache (2026-10-02).
struct RemoteImage: View {
    let url: URL
    @State private var image: UIImage?
    var body: some View {
        ZStack {
            // A prefetched photo shows on the first frame, not after a task hop.
            if let shown = image ?? RemotePhotos.shared.cached(url) { FillImage(image: shown) }
        }
        .task(id: url) { image = await RemotePhotos.shared.image(url) }
    }
}
