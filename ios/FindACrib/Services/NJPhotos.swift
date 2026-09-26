import MapKit
import SwiftUI
import UIKit

/// A street photo for a New Jersey drawing (owner, 2026-09-26: "are we able
/// to get photos of nj buildings?"). CGP&H publishes only the town and the
/// development's name, so the place is found with Apple's own search and the
/// photo is Apple's Look Around, through MapKit's snapshotter — the same
/// licensed path the building cards use (nothing stored beyond memory).
///
/// A wrong building is worse than none, so a search result only counts when
/// it is in New Jersey and in the drawing's town, or when the development's
/// name is itself a street address. No Look Around there: no photo.
@MainActor
final class NJPhotos {
    static let shared = NJPhotos()
    private var cache: [String: UIImage?] = [:]
    private var inFlight: [String: Task<UIImage?, Never>] = [:]

    func photo(for l: LotteryFeed.NJLottery, size: CGSize) async -> UIImage? {
        if let hit = cache[l.id] { return hit }
        if let t = inFlight[l.id] { return await t.value }
        let t = Task { await Self.render(l, size: size) }
        inFlight[l.id] = t
        let img = await t.value
        cache[l.id] = img
        inFlight[l.id] = nil
        return img
    }

    /// Words that name nothing in particular.
    nonisolated static let generic: Set<String> = ["the", "at", "of", "and", "apartments", "apartment", "apts",
        "townes", "towns", "villas", "village", "homes", "residences", "commons", "estates", "senior", "court",
        "place", "run", "point", "park", "gardens", "greens", "meadows", "square", "house", "manor", "street", "avenue"]

    nonisolated static func words(_ s: String) -> Set<String> {
        Set(s.lowercased().split(whereSeparator: { !$0.isLetter }).map(String.init).filter { $0.count > 2 })
    }

    /// Does a search hit look like this drawing's building? A result that
    /// only shares the TOWN's name ("Wayne St" for Wayne Villas) or a generic
    /// word ("Coral Ln" for Coral Point, 20 miles away) is not it.
    nonisolated static func accept(town: String, development: String, name: String?, locality: String?, state: String?) -> Bool {
        guard (state ?? "").uppercased() == "NJ" || (state ?? "") == "New Jersey" else { return false }
        if development.first?.isNumber == true { return true }          // "1108 McBride Avenue"
        let townWords = words(town).subtracting(["township", "borough", "city"])
        let distinctive = words(development).subtracting(townWords).subtracting(generic)
        let shared = distinctive.intersection(words(name ?? ""))
        let loc = (locality ?? "").lowercased()
        let inTown = !townWords.isEmpty && townWords.allSatisfy { loc.contains($0) }
        return shared.count >= 2 || (shared.count == 1 && inTown)
    }

    private static func render(_ l: LotteryFeed.NJLottery, size: CGSize) async -> UIImage? {
        guard let dev = l.development, !dev.isEmpty else { return nil }
        let req = MKLocalSearch.Request()
        req.naturalLanguageQuery = "\(dev), \(l.town), NJ"
        req.region = MKCoordinateRegion(center: CLLocationCoordinate2D(latitude: 40.15, longitude: -74.6),
                                        span: MKCoordinateSpan(latitudeDelta: 2.8, longitudeDelta: 2.2))
        guard let items = try? await MKLocalSearch(request: req).start().mapItems,
              let hit = items.first(where: { accept(town: l.town, development: dev, name: $0.name,
                                                     locality: $0.placemark.locality,
                                                     state: $0.placemark.administrativeArea) }),
              let scene = try? await MKLookAroundSceneRequest(coordinate: hit.placemark.coordinate).scene
        else { return nil }
        let opts = MKLookAroundSnapshotter.Options()
        opts.size = size
        opts.pointOfInterestFilter = .excludingAll
        return try? await MKLookAroundSnapshotter(scene: scene, options: opts).snapshot.image
    }
}

/// The photo at the top of an NJ card; takes no space until one is found.
struct NJPhoto: View {
    let lottery: LotteryFeed.NJLottery
    @State private var image: UIImage?

    var body: some View {
        Group {
            if let image {
                FillImage(image: image)
                    .frame(maxWidth: .infinity).frame(height: 180)
                    .overlay(alignment: .bottomLeading) {
                        Label("Apple Look Around", systemImage: "binoculars.fill")
                            .font(.se(12, .semibold)).foregroundStyle(.white)
                            .padding(.horizontal, 8).padding(.vertical, 4)
                            .background(.black.opacity(0.45)).clipShape(Capsule()).padding(8)
                    }
                    .accessibilityLabel("Street view near \(lottery.development ?? lottery.town)")
                    .accessibilityIdentifier("nj-photo")
                    .padding(.bottom, 6)
            } else {
                // Zero height, but a real view: an empty Group never runs .task.
                Color.clear.frame(height: 0)
            }
        }
        .task(id: lottery.id) {
            image = await NJPhotos.shared.photo(for: lottery, size: CGSize(width: 720, height: 360))
        }
    }
}
