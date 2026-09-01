import Foundation
import MapKit
import UIKit

/// Street-level photos for cards without a third-party key: Apple Look Around
/// snapshots, cached on disk by BBL, with a plain map snapshot as fallback
/// where Look Around has no coverage. Concurrency is capped so a fast scroll
/// through a list doesn't fan out hundreds of requests.
actor ImageService {
    static let shared = ImageService()
    private let mem = NSCache<NSString, UIImage>()
    private var inflight: [String: Task<UIImage?, Never>] = [:]
    private var running = 0
    private let maxConcurrent = 3
    private var waiters: [CheckedContinuation<Void, Never>] = []

    private static var dir: URL {
        let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
        let d = base.appendingPathComponent("lookaround", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    init() { mem.countLimit = 300 }

    func image(for b: Building, size: CGSize = CGSize(width: 800, height: 500)) async -> UIImage? {
        let key = b.bbl
        if let hit = mem.object(forKey: key as NSString) { return hit }
        let file = Self.dir.appendingPathComponent("\(key).jpg")
        if let d = try? Data(contentsOf: file), let img = UIImage(data: d) {
            mem.setObject(img, forKey: key as NSString); return img
        }
        if let t = inflight[key] { return await t.value }
        let task = Task<UIImage?, Never> { [weak self] in
            guard let self else { return nil }
            await self.acquire()
            defer { Task { await self.release() } }
            let img = await Self.render(b, size: size)
            if let img, let d = img.jpegData(compressionQuality: 0.8) { try? d.write(to: file, options: .atomic) }
            return img
        }
        inflight[key] = task
        let img = await task.value
        inflight[key] = nil
        if let img { mem.setObject(img, forKey: key as NSString) }
        return img
    }

    private func acquire() async {
        if running < maxConcurrent { running += 1; return }
        await withCheckedContinuation { waiters.append($0) }
        running += 1
    }
    private func release() {
        running -= 1
        if !waiters.isEmpty { waiters.removeFirst().resume() }
    }

    private static func render(_ b: Building, size: CGSize) async -> UIImage? {
        if let scene = try? await MKLookAroundSceneRequest(coordinate: b.coordinate).scene {
            let opts = MKLookAroundSnapshotter.Options()
            opts.size = size
            opts.pointOfInterestFilter = .excludingAll
            if let snap = try? await MKLookAroundSnapshotter(scene: scene, options: opts).snapshot {
                return snap.image
            }
        }
        let opts = MKMapSnapshotter.Options()
        opts.region = MKCoordinateRegion(center: b.coordinate, latitudinalMeters: 350, longitudinalMeters: 350)
        opts.size = size
        opts.pointOfInterestFilter = .excludingAll
        guard let snap = try? await MKMapSnapshotter(options: opts).start() else { return nil }
        // Drop a marker at the building so the fallback still reads as "this one".
        let r = UIGraphicsImageRenderer(size: size)
        return r.image { _ in
            snap.image.draw(at: .zero)
            let p = snap.point(for: b.coordinate)
            let pin = UIImage(systemName: "mappin.circle.fill", withConfiguration: UIImage.SymbolConfiguration(pointSize: 36, weight: .bold))?
                .withTintColor(UIColor(SE.royal), renderingMode: .alwaysOriginal)
            pin?.draw(in: CGRect(x: p.x - 18, y: p.y - 36, width: 36, height: 36))
        }
    }
}
