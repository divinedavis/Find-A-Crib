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
    @State private var showLocation = false
    @State private var initialFit = true
    @State private var calloutDrag: CGFloat = 0

    var body: some View {
        VStack(spacing: 0) {
            NavyBarBackdrop()
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
        .toolbar { ToolbarItem(placement: .principal) { ResultsHeader(query: query, onLocation: { showLocation = true }, onFilter: { showFilters = true }) } }
        .sheet(isPresented: $showFilters) { FiltersSheet(query: $query) }
        .sheet(isPresented: $showLocation) { LocationPickerView(selected: $query.locations) }
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
        .swipeBackEnabled()
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

/// Aggregate pin for a grid cell when there are too many buildings to draw.
final class GridAnnotation: NSObject, MKAnnotation {
    let coordinate: CLLocationCoordinate2D
    let count: Int
    init(coordinate: CLLocationCoordinate2D, count: Int) { self.coordinate = coordinate; self.count = count }
}

struct BuildingMap: UIViewRepresentable {
    let buildings: [Building]
    let prices: [String: Int]
    @Binding var region: MKCoordinateRegion
    @Binding var selected: Building?
    @Binding var initialFit: Bool
    var onUserMoved: () -> Void

    /// Above this many buildings in view, cells replace pins. 47k pins froze
    /// the map and a "nearest 6,000 to the centre" sample left most of the
    /// city blank; a fixed grid is cheap at any zoom and covers everything.
    static let pinLimit = 700
    static let gridCols = 9

    func makeUIView(context: Context) -> MKMapView {
        let m = MKMapView()
        m.delegate = context.coordinator
        m.pointOfInterestFilter = .excludingAll
        m.showsUserLocation = true
        m.register(PriceBubbleView.self, forAnnotationViewWithReuseIdentifier: "bubble")
        m.register(ClusterBubbleView.self, forAnnotationViewWithReuseIdentifier: MKMapViewDefaultClusterAnnotationViewReuseIdentifier)
        m.register(ClusterBubbleView.self, forAnnotationViewWithReuseIdentifier: "grid")
        m.setRegion(region, animated: false)
        return m
    }

    func updateUIView(_ m: MKMapView, context: Context) {
        let c = context.coordinator
        c.parent = self
        if !Self.same(region, c.reported) && !Self.same(region, c.applied) {
            m.setRegion(region, animated: c.applied != nil)
            c.applied = region
        }
        let dataKey = buildings.count &* 31 &+ (buildings.first?.bbl.hashValue ?? 0) &+ (buildings.last?.bbl.hashValue ?? 0)
        if c.dataKey != dataKey { c.dataKey = dataKey; c.schedule(m, force: true) }
        if selected == nil, let s = m.selectedAnnotations.first { m.deselectAnnotation(s, animated: false) }
    }

    static func same(_ a: MKCoordinateRegion, _ b: MKCoordinateRegion?) -> Bool {
        guard let b else { return false }
        let e = 1e-6
        return abs(a.center.latitude - b.center.latitude) < e && abs(a.center.longitude - b.center.longitude) < e
            && abs(a.span.latitudeDelta - b.span.latitudeDelta) < e && abs(a.span.longitudeDelta - b.span.longitudeDelta) < e
    }

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    final class Coordinator: NSObject, MKMapViewDelegate {
        var parent: BuildingMap
        var dataKey = 0
        var applied: MKCoordinateRegion?
        var reported: MKCoordinateRegion?
        var settled = false
        var arming = false
        private var work: DispatchWorkItem?
        private var lastLayoutKey = ""
        private var generation = 0
        init(_ p: BuildingMap) { parent = p }

        /// Debounced: pinch/pan fire regionDidChange continuously; rebuilding
        /// annotations on each event is what froze the map.
        func schedule(_ m: MKMapView, force: Bool = false) {
            work?.cancel()
            let item = DispatchWorkItem { [weak self, weak m] in
                guard let self, let m else { return }
                self.rebuild(m, force: force)
            }
            work = item
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.12, execute: item)
        }

        private func rebuild(_ m: MKMapView, force: Bool) {
            let region = m.region
            // Only re-aggregate when the view moved a meaningful amount.
            let zoom = Int((log2(360 / max(region.span.longitudeDelta, 1e-6))).rounded())
            let cellLat = region.span.latitudeDelta / 3, cellLng = region.span.longitudeDelta / 3
            let key = "\(zoom):\(Int(region.center.latitude / cellLat)):\(Int(region.center.longitude / cellLng))"
            if !force && key == lastLayoutKey { return }
            lastLayoutKey = key
            let all = parent.buildings, prices = parent.prices
            let cols = BuildingMap.gridCols, limit = BuildingMap.pinLimit
            generation += 1; let gen = generation
            // Padded viewport; the work runs off the main thread.
            let pad = 0.6
            let minLat = region.center.latitude - region.span.latitudeDelta * (0.5 + pad)
            let maxLat = region.center.latitude + region.span.latitudeDelta * (0.5 + pad)
            let minLng = region.center.longitude - region.span.longitudeDelta * (0.5 + pad)
            let maxLng = region.center.longitude + region.span.longitudeDelta * (0.5 + pad)
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                var visible: [Building] = []
                visible.reserveCapacity(2048)
                for b in all where b.lat >= minLat && b.lat <= maxLat && b.lng >= minLng && b.lng <= maxLng { visible.append(b) }
                var pins: [MKAnnotation] = []
                if visible.count <= limit {
                    pins = visible.map { BuildingAnnotation($0, price: prices[$0.bbl]) }
                } else {
                    // grid over the padded viewport, ~cols across the screen
                    let cw = region.span.longitudeDelta / Double(cols)
                    let ch = cw * 1.2
                    var cells: [Int: (lat: Double, lng: Double, n: Int)] = [:]
                    for b in visible {
                        let ci = Int((b.lng - minLng) / cw), cj = Int((b.lat - minLat) / ch)
                        let k = cj * 10_000 + ci
                        var cell = cells[k] ?? (0, 0, 0)
                        cell.lat += b.lat; cell.lng += b.lng; cell.n += 1
                        cells[k] = cell
                    }
                    pins = cells.values.map { GridAnnotation(coordinate: .init(latitude: $0.lat / Double($0.n), longitude: $0.lng / Double($0.n)), count: $0.n) }
                }
                DispatchQueue.main.async {
                    guard let self, gen == self.generation else { return }
                    let keep = self.parent.selected.map { sel in m.annotations.first { ($0 as? BuildingAnnotation)?.building.bbl == sel.bbl } }
                    m.removeAnnotations(m.annotations.filter { $0 is BuildingAnnotation || $0 is GridAnnotation })
                    m.addAnnotations(pins)
                    if let k = keep, let sel = k { m.addAnnotation(sel); m.selectAnnotation(sel, animated: false) }
                }
            }
        }

        func mapView(_ mapView: MKMapView, viewFor annotation: MKAnnotation) -> MKAnnotationView? {
            if annotation is MKUserLocation { return nil }
            if annotation is MKClusterAnnotation {
                return mapView.dequeueReusableAnnotationView(withIdentifier: MKMapViewDefaultClusterAnnotationViewReuseIdentifier, for: annotation)
            }
            if annotation is GridAnnotation {
                let v = mapView.dequeueReusableAnnotationView(withIdentifier: "grid", for: annotation)
                v.clusteringIdentifier = nil
                return v
            }
            let v = mapView.dequeueReusableAnnotationView(withIdentifier: "bubble", for: annotation)
            v.clusteringIdentifier = "b"
            return v
        }
        func mapView(_ mapView: MKMapView, didSelect view: MKAnnotationView) {
            if let a = view.annotation as? BuildingAnnotation { parent.selected = a.building }
            else if let c = view.annotation as? MKClusterAnnotation ?? (view.annotation as MKAnnotation?) , view.annotation is MKClusterAnnotation || view.annotation is GridAnnotation {
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
            schedule(mapView)
            if settled { parent.onUserMoved() }
            else if !arming { arming = true; DispatchQueue.main.asyncAfter(deadline: .now() + 1.2) { [weak self] in self?.settled = true } }
        }
    }
}

/// White capsule with the asking rent, royal border; a royal pin with a
/// building glyph when the building has no advertised price. Navy when
/// selected.
///
/// The unpriced pin used to be a 12pt dot — on a street map at block zoom it
/// read as a speck and took a precise tap to hit. It is now a 28pt disc with
/// a white ring, a drop shadow so it lifts off the map, and a glyph so it is
/// unmistakably a building; the touch target is padded to 44pt either way.
final class PriceBubbleView: MKAnnotationView {
    private let label = UILabel()
    private let glyph = UIImageView(image: UIImage(systemName: "building.2.fill",
        withConfiguration: UIImage.SymbolConfiguration(pointSize: 12, weight: .bold)))
    static let dotSize: CGFloat = 28
    override init(annotation: MKAnnotation?, reuseIdentifier: String?) {
        super.init(annotation: annotation, reuseIdentifier: reuseIdentifier)
        collisionMode = .rectangle
        label.font = UIFont(name: "SourceSans3-Bold", size: 13) ?? .boldSystemFont(ofSize: 13)
        label.textAlignment = .center
        addSubview(label)
        glyph.tintColor = .white
        glyph.contentMode = .center
        addSubview(glyph)
        layer.shadowColor = UIColor.black.cgColor
        layer.shadowOpacity = 0.28
        layer.shadowRadius = 3
        layer.shadowOffset = CGSize(width: 0, height: 1.5)
        displayPriority = .defaultHigh
    }
    /// Apple's 44pt minimum: a 28pt pin (or a 26pt-tall capsule) alone is
    /// under it, so accept touches in a padded rect around the view.
    override func point(inside point: CGPoint, with event: UIEvent?) -> Bool {
        let dx = max(0, (44 - bounds.width) / 2), dy = max(0, (44 - bounds.height) / 2)
        return bounds.insetBy(dx: -dx, dy: -dy).contains(point)
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
            glyph.isHidden = true
            layer.cornerRadius = 13
            layer.borderWidth = 1.5
            displayPriority = .required
        } else {
            label.text = nil
            let d = Self.dotSize
            bounds = CGRect(x: 0, y: 0, width: d, height: d)
            glyph.isHidden = false
            glyph.frame = bounds
            layer.cornerRadius = d / 2
            layer.borderWidth = 2.5
            displayPriority = .defaultHigh
        }
        let royal = UIColor(SE.royal), navy = UIColor(SE.navy)
        backgroundColor = isSelected ? navy : (a.price != nil ? .white : royal)
        layer.borderColor = isSelected ? navy.cgColor : (a.price != nil ? royal.cgColor : UIColor.white.cgColor)
        label.textColor = isSelected ? .white : royal
        // An explicit shadow path keeps Core Animation from rasterising each
        // pin's alpha mask every frame — hundreds of pins pan at 60fps.
        layer.shadowPath = UIBezierPath(roundedRect: bounds, cornerRadius: layer.cornerRadius).cgPath
        // A selected pin grows a touch so the tap visibly landed.
        transform = (isSelected && a.price == nil) ? CGAffineTransform(scaleX: 1.2, y: 1.2) : .identity
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
        let n: Int
        if let c = annotation as? MKClusterAnnotation { n = c.memberAnnotations.count }
        else if let g = annotation as? GridAnnotation { n = g.count }
        else { return }
        label.text = n >= 1000 ? "\(n / 1000)k" : "\(n)"
        let d: CGFloat = n >= 100 ? 44 : (n >= 10 ? 38 : 32)
        bounds = CGRect(x: 0, y: 0, width: d, height: d)
        label.frame = bounds
        layer.cornerRadius = d / 2
        backgroundColor = UIColor(SE.navy)
        layer.borderColor = UIColor.white.cgColor; layer.borderWidth = 2
    }
}
