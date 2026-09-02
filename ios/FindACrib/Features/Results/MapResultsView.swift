import SwiftUI
import MapKit

struct MapResultsView: View {
    @Environment(DataStore.self) private var store
    @Environment(AppNav.self) private var nav
    @State var query: SearchQuery
    @State private var results: [Building] = []
    @State private var region: MKCoordinateRegion = MapRegion.nyc
    @State private var selected: Building?
    @State private var moved = false
    @State private var showFilters = false
    @State private var initialFit = true
    @State private var calloutDrag: CGFloat = 0

    var body: some View {
        VStack(spacing: 0) {
            ResultsHeader(query: query) { showFilters = true }
            ZStack(alignment: .top) {
                BuildingMap(buildings: results, prices: pricesByBBL, region: $region, selected: $selected, initialFit: $initialFit,
                            onUserMoved: { moved = true })
                    .ignoresSafeArea(edges: .bottom)
                VStack(spacing: 10) {
                    Text("\(results.count.formatted()) \(query.noun)")
                        .font(.se(15, .bold)).foregroundStyle(SE.ink)
                        .padding(.horizontal, 12).padding(.vertical, 6).background(Color.white.opacity(0.95)).clipShape(Capsule())
                    if moved {
                        Button {
                            query.locations = [.mapArea(MapBox(region: region))]
                            moved = false
                        } label: {
                            HStack(spacing: 8) {
                                Image(systemName: "arrow.clockwise").font(.system(size: 14, weight: .bold))
                                Text("Search this area").font(.se(17, .bold))
                            }
                            .foregroundStyle(.white).padding(.horizontal, 18).frame(height: 44).background(SE.royal).clipShape(Capsule())
                            .shadow(color: .black.opacity(0.2), radius: 6, y: 2)
                        }
                        .buttonStyle(.plain)
                        .accessibilityIdentifier("search-this-area")
                    }
                }
                .padding(.top, 12)
            }
        }
        .overlay(alignment: .bottom) {
            VStack(spacing: 12) {
                if let sel = selected {
                    MapCalloutCard(building: sel) { nav.searchPath.append(.building(sel.bbl)) }
                        .padding(.horizontal, 16)
                        .offset(y: max(0, calloutDrag))
                        .opacity(1 - Double(max(0, calloutDrag)) / 220)
                        .gesture(
                            DragGesture(minimumDistance: 8)
                                .onChanged { v in if v.translation.height > 0 { calloutDrag = v.translation.height } }
                                .onEnded { v in
                                    if v.translation.height > 60 || v.predictedEndTranslation.height > 140 {
                                        withAnimation(.easeIn(duration: 0.18)) { calloutDrag = 260 }
                                        // deselect after the slide so the pin unhighlights with it
                                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.18) { selected = nil; calloutDrag = 0 }
                                    } else {
                                        withAnimation(.spring(duration: 0.3)) { calloutDrag = 0 }
                                    }
                                }
                        )
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                        .accessibilityAction(named: "Dismiss") { selected = nil }
                }
                FloatingPill(title: "List", icon: "list.bullet") { backToList() }
            }
            .padding(.bottom, 92)
            .animation(.easeInOut(duration: 0.2), value: selected?.bbl)
        }
        .sheet(isPresented: $showFilters) { FiltersSheet(query: $query) }
        .task(id: query) {
            results = SearchEngine.run(query, store: store)
            // A custom map area IS the viewport the user was looking at, so
            // reopening the map lands exactly there instead of on all of NYC.
            if case .mapArea(let box)? = query.locations.first(where: { if case .mapArea = $0 { return true }; return false }) {
                region = box.region
            } else {
                region = (results.count > 0 && results.count <= 500) ? MapRegion.fit(results) : MapRegion.forQuery(query, store: store)
            }
        }
        .navigationBarBackButtonHidden(true)
    }

    /// The list underneath was pushed with the query the map STARTED from.
    /// "Search this area" and the map's Filter sheet change this view's copy,
    /// so a plain pop would show the old results. Rewrite the results route
    /// with the map's current query instead.
    private func backToList() {
        var path = nav.searchPath
        if !path.isEmpty { path.removeLast() }
        if case .results? = path.last { path[path.count - 1] = .results(query) } else { path.append(.results(query)) }
        nav.searchPath = path
    }

    private var pricesByBBL: [String: Int] {
        var d: [String: Int] = [:]
        for b in results { if let p = store.price(b) ?? store.voucherAvail(b)?.p { d[b.bbl] = p } }
        return d
    }
}

struct MapCalloutCard: View {
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    let building: Building
    let open: () -> Void
    var body: some View {
        Button(action: open) {
            HStack(spacing: 12) {
                BuildingImage(building: building, size: CGSize(width: 300, height: 300)).frame(width: 110, height: 110)
                VStack(alignment: .leading, spacing: 4) {
                    Text(building.neighborhood).font(.se(15, .semibold)).foregroundStyle(SE.ink2).lineLimit(1)
                    Text(building.address).font(.se(20, .bold)).foregroundStyle(SE.royal).lineLimit(1)
                    if let p = store.price(building) {
                        Text("\(Formatters.dollars(p)) asking rent").font(.se(17, .bold))
                    } else if let e = store.estimate(building), e.count >= 3 {
                        Text("\(Formatters.dollars(e[0]))–\(Formatters.dollars(e[2])) typical").font(.se(15)).foregroundStyle(SE.ink2)
                    }
                    Text("\(building.u.map { "\($0) units" } ?? "") · \(building.yr.map { "built \($0)" } ?? "")").font(.se(14)).foregroundStyle(SE.ink3)
                }
                Spacer()
                HeartButton(on: activity.isSaved(building.bbl)) { activity.toggleSaved(building.bbl) }
            }
            .padding(.trailing, 8)
            .background(Color.white)
            .clipShape(RoundedRectangle(cornerRadius: 4))
            .shadow(color: .black.opacity(0.18), radius: 10, y: 3)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("map-callout")
    }
}

// MARK: - MKMapView wrapper with clustering and price bubbles

final class BuildingAnnotation: NSObject, MKAnnotation {
    let building: Building
    let price: Int?
    init(_ b: Building, price: Int?) { building = b; self.price = price }
    var coordinate: CLLocationCoordinate2D { building.coordinate }
    var title: String? { building.address }
}

struct BuildingMap: UIViewRepresentable {
    let buildings: [Building]
    let prices: [String: Int]
    @Binding var region: MKCoordinateRegion
    @Binding var selected: Building?
    @Binding var initialFit: Bool
    var onUserMoved: () -> Void

    static let cap = 6000

    func makeUIView(context: Context) -> MKMapView {
        let m = MKMapView()
        m.delegate = context.coordinator
        m.pointOfInterestFilter = .excludingAll
        m.showsUserLocation = true
        m.register(PriceBubbleView.self, forAnnotationViewWithReuseIdentifier: "bubble")
        m.register(ClusterBubbleView.self, forAnnotationViewWithReuseIdentifier: MKMapViewDefaultClusterAnnotationViewReuseIdentifier)
        m.setRegion(region, animated: false)
        return m
    }

    func updateUIView(_ m: MKMapView, context: Context) {
        let c = context.coordinator
        // Push a region the VIEW chose (a fit, a saved map area) down to the
        // map, but not one the map itself just reported back — that echo is
        // what a naive `setRegion` on every update turns into a pan-fight.
        // Before this, only the very first update ever reached the map, so
        // fits computed after the results loaded were silently dropped.
        if !Self.same(region, c.reported) && !Self.same(region, c.applied) {
            m.setRegion(region, animated: c.applied != nil)
            c.applied = region
        }
        let key = buildings.map(\.bbl).hashValue ^ prices.count ^ (buildings.count > Self.cap ? Int(m.region.center.latitude * 100) ^ Int(m.region.center.longitude * 100) : 0)
        if c.lastKey != key {
            c.lastKey = key
            m.removeAnnotations(m.annotations.filter { $0 is BuildingAnnotation })
            let subset = buildings.count > Self.cap ? Array(nearest(to: m.region.center, from: buildings, n: Self.cap)) : buildings
            m.addAnnotations(subset.map { BuildingAnnotation($0, price: prices[$0.bbl]) })
        }
        if selected == nil, let s = m.selectedAnnotations.first { m.deselectAnnotation(s, animated: false) }
    }

    static func same(_ a: MKCoordinateRegion, _ b: MKCoordinateRegion?) -> Bool {
        guard let b else { return false }
        let e = 1e-6
        return abs(a.center.latitude - b.center.latitude) < e && abs(a.center.longitude - b.center.longitude) < e
            && abs(a.span.latitudeDelta - b.span.latitudeDelta) < e && abs(a.span.longitudeDelta - b.span.longitudeDelta) < e
    }

    private func nearest(to c: CLLocationCoordinate2D, from bs: [Building], n: Int) -> ArraySlice<Building> {
        bs.sorted { ($0.lat - c.latitude) * ($0.lat - c.latitude) + ($0.lng - c.longitude) * ($0.lng - c.longitude) <
                    ($1.lat - c.latitude) * ($1.lat - c.latitude) + ($1.lng - c.longitude) * ($1.lng - c.longitude) }.prefix(n)
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, MKMapViewDelegate {
        var parent: BuildingMap
        var lastKey = 0
        var applied: MKCoordinateRegion?    // last region this wrapper pushed to the map
        var reported: MKCoordinateRegion?   // last region the map reported back
        var settled = false
        var arming = false
        init(_ p: BuildingMap) { parent = p }

        func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
            if annotation is MKUserLocation { return nil }
            if annotation is MKClusterAnnotation {
                return mapView.dequeueReusableAnnotationView(withIdentifier: MKMapViewDefaultClusterAnnotationViewReuseIdentifier, for: annotation)
            }
            let v = mapView.dequeueReusableAnnotationView(withIdentifier: "bubble", for: annotation)
            v.clusteringIdentifier = "b"
            return v
        }
        func mapView(_ mapView: MKMapView, didSelect view: MKAnnotationView) {
            if let a = view.annotation as? BuildingAnnotation { parent.selected = a.building }
            else if let c = view.annotation as? MKClusterAnnotation {
                mapView.deselectAnnotation(c, animated: false)
                let r = MKCoordinateRegion(center: c.coordinate, span: .init(latitudeDelta: mapView.region.span.latitudeDelta / 3, longitudeDelta: mapView.region.span.longitudeDelta / 3))
                mapView.setRegion(r, animated: true)
            }
        }
        func mapView(_ mapView: MKMapView, didDeselect view: MKAnnotationView) {
            if view.annotation is BuildingAnnotation { parent.selected = nil }
        }
        func mapView(_ mapView: MKMapView, regionDidChangeAnimated animated: Bool) {
            reported = mapView.region
            parent.region = mapView.region
            // Ignore the programmatic fits during the first second; anything
            // after is the user panning.
            if settled { parent.onUserMoved() }
            else if !arming { arming = true; DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in self?.settled = true } }
        }
    }
}

/// White capsule with the asking rent, royal border; a small royal dot when
/// the building has no advertised price. Navy when selected.
final class PriceBubbleView: MKAnnotationView {
    private let label = UILabel()
    override init(annotation: MKAnnotation?, reuseIdentifier: String?) {
        super.init(annotation: annotation, reuseIdentifier: reuseIdentifier)
        collisionMode = .rectangle
        label.font = UIFont(name: "SourceSans3-Bold", size: 13) ?? .boldSystemFont(ofSize: 13)
        label.textAlignment = .center
        addSubview(label)
        displayPriority = .defaultHigh
    }
    required init?(coder: NSCoder) { fatalError() }
    override var annotation: MKAnnotation? { didSet { render() } }
    override func prepareForDisplay() { super.prepareForDisplay(); render() }
    override var isSelected: Bool { didSet { render() } }

    private func render() {
        guard let a = annotation as? BuildingAnnotation else { return }
        if let p = a.price {
            label.text = Formatters.short(p)
            label.sizeToFit()
            let w = label.bounds.width + 16
            bounds = CGRect(x: 0, y: 0, width: w, height: 26)
            label.frame = bounds
            layer.cornerRadius = 13
            layer.borderWidth = 1.5
            displayPriority = .required
        } else {
            label.text = nil
            bounds = CGRect(x: 0, y: 0, width: 12, height: 12)
            layer.cornerRadius = 6
            layer.borderWidth = 2
            displayPriority = .defaultLow
        }
        let royal = UIColor(SE.royal), navy = UIColor(SE.navy)
        backgroundColor = isSelected ? navy : (a.price != nil ? .white : royal)
        layer.borderColor = isSelected ? navy.cgColor : (a.price != nil ? royal.cgColor : UIColor.white.cgColor)
        label.textColor = isSelected ? .white : royal
        centerOffset = .zero
    }
}

final class ClusterBubbleView: MKAnnotationView {
    private let label = UILabel()
    override init(annotation: MKAnnotation?, reuseIdentifier: String?) {
        super.init(annotation: annotation, reuseIdentifier: reuseIdentifier)
        collisionMode = .circle
        label.font = UIFont(name: "SourceSans3-Bold", size: 14) ?? .boldSystemFont(ofSize: 14)
        label.textColor = .white; label.textAlignment = .center
        addSubview(label)
        displayPriority = .defaultHigh
    }
    required init?(coder: NSCoder) { fatalError() }
    override var annotation: MKAnnotation? { didSet { render() } }
    override func prepareForDisplay() { super.prepareForDisplay(); render() }
    private func render() {
        guard let c = annotation as? MKClusterAnnotation else { return }
        let n = c.memberAnnotations.count
        label.text = n >= 1000 ? "\(n / 1000)k" : "\(n)"
        let d: CGFloat = n >= 100 ? 44 : (n >= 10 ? 38 : 32)
        bounds = CGRect(x: 0, y: 0, width: d, height: d)
        label.frame = bounds
        layer.cornerRadius = d / 2
        backgroundColor = UIColor(SE.navy)
        layer.borderColor = UIColor.white.cgColor; layer.borderWidth = 2
    }
}
