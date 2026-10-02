import SwiftUI
import ImageIO
import UIKit

/// The photo at the top of a lottery card (owner, 2026-09-25: "are we not
/// able to get images for these?"). The listing's own photo where the agency
/// publishes one (SF DAHLIA, Access Housing LA, Doorway); otherwise the street
/// at its address from Apple Look Around, the same picture the building cards
/// use (Housing Connect, Miami's lease-ups). No photo and no place: no header.
struct LotteryPhoto: View {
    let key: String
    var url: URL? = nil
    var lat: Double? = nil
    var lng: Double? = nil
    @State private var image: UIImage?

    var body: some View {
        if let url {
            ZStack {
                ImagePlaceholder()
                if let image { FillImage(image: image) }
            }
            .frame(height: 190).frame(maxWidth: .infinity).clipped()
            .task(id: url) { image = await RemotePhotos.shared.image(url) }
            .accessibilityElement(children: .ignore).accessibilityLabel("Photo of the building")
            .accessibilityIdentifier("lottery-photo")
        } else if let lat, let lng {
            BuildingImage(building: Building(bbl: "lot-\(key)", b: "", a: "", z: nil, lat: lat, lng: lng))
                .frame(height: 190).frame(maxWidth: .infinity).clipped()
                .accessibilityElement(children: .ignore).accessibilityLabel("Photo of the building")
            .accessibilityIdentifier("lottery-photo")
        }
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
    private let cache = NSCache<NSURL, UIImage>()
    init() { cache.countLimit = 120 }

    func image(_ url: URL, maxPixels: Int = 900) async -> UIImage? {
        if let hit = cache.object(forKey: url as NSURL) { return hit }
        var req = URLRequest(url: url, timeoutInterval: 20)
        req.cachePolicy = .returnCacheDataElseLoad
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let src = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let opts: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                     kCGImageSourceCreateThumbnailWithTransform: true,
                                     kCGImageSourceShouldCacheImmediately: true,
                                     kCGImageSourceThumbnailMaxPixelSize: maxPixels]
        guard let cg = CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary) else { return nil }
        let img = UIImage(cgImage: cg)
        cache.setObject(img, forKey: url as NSURL)
        return img
    }
}

/// A remote photo through RemotePhotos — downsampled, decoded off the main
/// thread, cached — in place of AsyncImage, which decodes the full-size file
/// at draw time and keeps no cache (2026-10-02).
struct RemoteImage: View {
    let url: URL
    @State private var image: UIImage?
    var body: some View {
        ZStack {
            if let image { FillImage(image: image) }
        }
        .task(id: url) { image = await RemotePhotos.shared.image(url) }
    }
}
