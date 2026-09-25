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
actor RemotePhotos {
    static let shared = RemotePhotos()
    private let cache = NSCache<NSURL, UIImage>()

    func image(_ url: URL) async -> UIImage? {
        if let hit = cache.object(forKey: url as NSURL) { return hit }
        var req = URLRequest(url: url, timeoutInterval: 20)
        req.cachePolicy = .returnCacheDataElseLoad
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let src = CGImageSourceCreateWithData(data as CFData, nil) else { return nil }
        let opts: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true,
                                     kCGImageSourceCreateThumbnailWithTransform: true,
                                     kCGImageSourceShouldCacheImmediately: true,
                                     kCGImageSourceThumbnailMaxPixelSize: 900]
        guard let cg = CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary) else { return nil }
        let img = UIImage(cgImage: cg)
        cache.setObject(img, forKey: url as NSURL)
        return img
    }
}
