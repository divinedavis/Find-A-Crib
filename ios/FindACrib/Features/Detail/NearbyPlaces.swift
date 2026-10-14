import SwiftUI
import MapKit

/// Two rows at the bottom of every building (owner, 2026-10-14): legal
/// services and cafés near it, searched live on Apple Maps. Nothing is stored:
/// Apple's terms (DPLA Schedule 6 §2.5) forbid caching Maps results beyond
/// temporary use, so each building asks again when it opens.
struct NearbyPlace: Identifiable, Hashable {
    let id: String
    let name: String
    let street: String
    let meters: Double
    let item: MKMapItem
}

enum NearbyPlaces {
    /// Apple Maps has no "lawyer" category, so legal services come from three
    /// text searches, kept only when the name reads as a legal office. A plain
    /// "legal services" search near 1 Audubon Ave returned notaries, a tax
    /// preparer and a check casher ahead of any lawyer (2026-10-14).
    static let legalQueries = ["lawyer", "tenant lawyer", "legal aid"]
    static func isLegal(_ name: String) -> Bool {
        let n = name.lowercased()
        let yes = ["law", "legal", "attorney", "esq", "counsel", "advocate"]
        let no = ["notary", "tax", "check cash", "realty", "court", "criminal justice", "insurance", "immigration consultant"]
        return yes.contains { n.contains($0) } && !no.contains { n.contains($0) }
    }

    static func legal(near c: CLLocationCoordinate2D, limit: Int = 8) async -> [NearbyPlace] {
        let region = MKCoordinateRegion(center: c, latitudinalMeters: 3000, longitudinalMeters: 3000)
        var seen = Set<String>(), out: [NearbyPlace] = []
        for q in legalQueries {
            let req = MKLocalSearch.Request()
            req.naturalLanguageQuery = q
            req.region = region
            req.resultTypes = .pointOfInterest
            guard let items = try? await MKLocalSearch(request: req).start().mapItems else { continue }
            for it in items {
                guard let p = place(it, from: c), isLegal(p.name), p.meters <= 3500, seen.insert(p.id).inserted else { continue }
                out.append(p)
            }
        }
        return Array(out.sorted { $0.meters < $1.meters }.prefix(limit))
    }

    static func cafes(near c: CLLocationCoordinate2D, limit: Int = 8) async -> [NearbyPlace] {
        let req = MKLocalPointsOfInterestRequest(center: c, radius: 800)
        req.pointOfInterestFilter = MKPointOfInterestFilter(including: [.cafe])
        guard let items = try? await MKLocalSearch(request: req).start().mapItems else { return [] }
        var seen = Set<String>()
        return Array(items.compactMap { place($0, from: c) }.filter { seen.insert($0.id).inserted }
            .sorted { $0.meters < $1.meters }.prefix(limit))
    }

    private static func place(_ it: MKMapItem, from c: CLLocationCoordinate2D) -> NearbyPlace? {
        guard let name = it.name, !name.isEmpty else { return nil }
        let pc = it.placemark.coordinate
        let m = CLLocation(latitude: c.latitude, longitude: c.longitude).distance(from: CLLocation(latitude: pc.latitude, longitude: pc.longitude))
        let street = [it.placemark.subThoroughfare, it.placemark.thoroughfare].compactMap { $0 }.joined(separator: " ")
        return NearbyPlace(id: "\(name)|\(street)", name: name, street: street, meters: m, item: it)
    }

    static func distance(_ m: Double) -> String {
        let mi = m / 1609.34
        return mi < 0.1 ? "Under 0.1 mi" : String(format: "%.1f mi", mi)
    }
}

/// One horizontal row of places with a note under it. Hidden when the search
/// comes back empty.
struct NearbyPlacesRail: View {
    let title: String
    let icon: String
    let note: String
    let places: [NearbyPlace]
    let testID: String

    var body: some View {
        if !places.isEmpty {
            VStack(alignment: .leading, spacing: 14) {
                Text(title).font(.se(30, .black)).padding(.horizontal, 16)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        ForEach(places) { p in
                            Button { p.item.openInMaps() } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    Image(systemName: icon).font(.system(size: 20, weight: .semibold)).foregroundStyle(SE.royal)
                                    Text(p.name).font(.se(17, .bold)).foregroundStyle(SE.royal).lineLimit(2).multilineTextAlignment(.leading)
                                    if !p.street.isEmpty { Text(p.street).font(.se(14)).foregroundStyle(SE.ink2).lineLimit(1) }
                                    Text(NearbyPlaces.distance(p.meters)).font(.se(14)).foregroundStyle(SE.ink3)
                                }
                                .padding(12).frame(width: 200, height: 140, alignment: .topLeading).seCard()
                            }.buttonStyle(.plain)
                        }
                    }.padding(.horizontal, 16)
                }
                Text(note).font(.se(15)).foregroundStyle(SE.ink3).padding(.horizontal, 16)
            }
            .padding(.vertical, 16).background(Color.white).padding(.bottom, 10)
            .accessibilityIdentifier(testID)
        }
    }
}
