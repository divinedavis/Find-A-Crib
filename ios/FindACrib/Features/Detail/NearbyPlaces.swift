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
    /// Home and apartment law only (owner, 2026-10-14). Apple Maps has no
    /// lawyer category and doesn't say what a firm practices, so five housing
    /// searches are merged and a place stays only when its NAME says housing
    /// law: a legal-aid / legal-services group, or tenant/housing/eviction
    /// next to a legal word. Generic "Law Office of …" results can't be told
    /// apart and are left out. Same rule as index.html's isLegalName.
    static let legalQueries = ["tenant legal services", "tenant lawyer", "landlord tenant attorney", "housing lawyer", "eviction lawyer"]
    private static func has(_ n: String, _ pattern: String) -> Bool {
        n.range(of: pattern, options: [.regularExpression, .caseInsensitive]) != nil
    }
    static func isLegal(_ n: String) -> Bool {
        let legalWord = #"\blaw\b|legal|attorney|lawyer|esq|counsel"#
        let org = #"legal aid|legal assistance|legal services (corp|nyc|of|for)|(bronx|brooklyn|harlem|queens|manhattan|staten island|bay area|los angeles|neighborhood|community) legal services|mobilization for justice|takeroot|housing rights|tenant rights|tenants? union"#
        let no = #"criminal|injury|accident|immigra|district attorney|defender|court|commercial|notary|tax|realty|brokerage|consult|multiservice|insurance"#
        if has(n, no) || (has(n, "landlord") && !has(n, "tenant")) { return false }
        return has(n, org) || (has(n, "tenant|housing|eviction") && has(n, legalWord))
    }

    static func legal(near c: CLLocationCoordinate2D, limit: Int = 8) async -> [NearbyPlace] {
        let region = MKCoordinateRegion(center: c, latitudinalMeters: 5000, longitudinalMeters: 5000)
        var seen = Set<String>(), out: [NearbyPlace] = []
        for q in legalQueries {
            let req = MKLocalSearch.Request()
            req.naturalLanguageQuery = q
            req.region = region
            req.resultTypes = .pointOfInterest
            guard let items = try? await MKLocalSearch(request: req).start().mapItems else { continue }
            for it in items {
                guard let p = place(it, from: c), isLegal(p.name), p.meters <= 5000, seen.insert(p.id).inserted else { continue }
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
        return mi < 0.1 ? String(localized: "Under 0.1 mi") : String(format: "%.1f mi", mi)
    }
}

/// One horizontal row of places with a note under it. Hidden when the search
/// comes back empty.
struct NearbyPlacesRail: View {
    let title: String
    let icon: String
    var note: String? = nil
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
                if let note { Text(note).font(.se(15)).foregroundStyle(SE.ink3).padding(.horizontal, 16) }
            }
            .padding(.vertical, 16).background(Color.white).padding(.bottom, 10)
            .accessibilityIdentifier(testID)
        }
    }
}

/// Private firms that practise residential landlord-tenant law, by NYC
/// borough (owner, 2026-10-14: "at least 3 law firms that specialize in home
/// law in the borough that building is in"). Apple Maps can't say what a firm
/// practises, so this is a researched list in Data/housing_law_firms.json:
/// each firm's own site says it takes tenant / Housing Court cases, with the
/// page that says so kept as `source`. Re-check it a few times a year.
struct HousingLawFirm: Decodable, Identifiable, Hashable {
    let name: String
    let borough: String
    let street: String
    let phone: String?
    let website: String
    let handles: String
    /// "tenant" (tenants only) or "both" (tenants and landlords).
    let side: String
    /// Where the office is. Few firms outside Manhattan both practise this and
    /// have an office in their own borough (none in the Bronx, 2026-10-14), so
    /// a borough's list also holds firms elsewhere in NYC that say they take
    /// its Housing Court cases.
    let officeBorough: String
    let source: String
    let lat: Double?
    let lng: Double?
    var id: String { name + "|" + street }
    var sideLabel: String { side == "tenant" ? String(localized: "Represents tenants only") : String(localized: "Represents tenants and landlords") }

    private enum CodingKeys: String, CodingKey {
        case name, borough, street, phone, website, handles, side, source, lat, lng
        case officeBorough = "office_borough"
    }

    private struct File: Decodable { let firms: [HousingLawFirm] }

    static let all: [HousingLawFirm] = {
        guard let url = Bundle.main.url(forResource: "housing_law_firms", withExtension: "json", subdirectory: "Data")
                ?? Bundle.main.url(forResource: "housing_law_firms", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let file = try? JSONDecoder().decode(File.self, from: data) else { return [] }
        return file.firms
    }()

    /// The borough's firms: those with an office there first, then nearest to
    /// the building.
    static func inBorough(_ borough: String, near c: CLLocationCoordinate2D) -> [HousingLawFirm] {
        let here = CLLocation(latitude: c.latitude, longitude: c.longitude)
        func d(_ f: HousingLawFirm) -> Double {
            guard let lat = f.lat, let lng = f.lng else { return .greatestFiniteMagnitude }
            return here.distance(from: CLLocation(latitude: lat, longitude: lng))
        }
        return all.filter { $0.borough == borough }.sorted {
            ($0.officeBorough == borough ? 0 : 1, d($0)) < ($1.officeBorough == borough ? 0 : 1, d($1))
        }
    }
}

/// The firms row under "Cafés nearby": a card per firm that opens its site.
struct HousingLawFirmsRail: View {
    let borough: String
    let firms: [HousingLawFirm]
    @Environment(\.openURL) private var openURL

    var body: some View {
        if !firms.isEmpty {
            VStack(alignment: .leading, spacing: 14) {
                Text("Housing law firms for \(borough)").font(.se(30, .black)).padding(.horizontal, 16)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        ForEach(firms) { f in
                            Button {
                                Analytics.shared.track("law_firm_open", ["borough": borough])
                                if let u = URL(string: f.website) { openURL(u) }
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    Image(systemName: "building.columns").font(.system(size: 20, weight: .semibold)).foregroundStyle(SE.royal)
                                    Text(f.name).font(.se(17, .bold)).foregroundStyle(SE.royal).lineLimit(2).multilineTextAlignment(.leading)
                                    Text(f.handles).font(.se(14)).foregroundStyle(SE.ink2).lineLimit(2).multilineTextAlignment(.leading)
                                    Text(f.sideLabel).font(.se(14, .semibold)).foregroundStyle(SE.ink2).lineLimit(1)
                                    Text(f.officeBorough == borough ? f.street : String(localized: "Office in \(f.officeBorough)"))
                                        .font(.se(14)).foregroundStyle(SE.ink3).lineLimit(1)
                                }
                                .padding(12).frame(width: 230, height: 182, alignment: .topLeading).seCard()
                            }.buttonStyle(.plain).accessibilityIdentifier("law-firm-card")
                        }
                    }.padding(.horizontal, 16)
                }
                Text("Private firms whose own websites say they take tenant and Housing Court cases in \(borough)" + (firms.contains { $0.officeBorough != borough } ? String(localized: "; some have their office elsewhere in the city") : "") + String(localized: ". We don't endorse them and haven't checked their record, licence or fees, so look into anyone before you hire them. This isn't legal advice. Free help: call 311 and ask for the Tenant Helpline."))
                    .font(.se(15)).foregroundStyle(SE.ink3).padding(.horizontal, 16)
            }
            .padding(.vertical, 16).background(Color.white).padding(.bottom, 10)
            .accessibilityIdentifier("housing-law-firms")
        }
    }
}
