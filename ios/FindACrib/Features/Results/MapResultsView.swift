import SwiftUI
import MapKit

struct MapResultsView: View {
    @Environment(DataStore.self) private var store
    @Environment(AppNav.self) private var nav
    @State var query: SearchQuery
    @State private var results: [Building] = []
    /// True once the background search has answered (2026-10-02).
    @State private var searched = false
    /// Set from the city on first appear; the initial value is only what the
    /// first frame draws before .task runs.
    @State private var region: MKCoordinateRegion = MapRegion.nyc
    @State private var selected: Building?
    @State private var moved = false
    @State private var showFilters = false
    @State private var showLocation = false
    @State private var initialFit = true
    @State private var calloutDrag: CGFloat = 0
    /// Computed with the results, not in `body`: as a computed property it
    /// rebuilt up to 47k entries on every frame of the callout drag.
    @State private var pricesByBBL: [String: Int] = [:]
    /// How many of `results` sit inside the viewport right now; the map
    /// reports it after each move (StreetEasy's count follows the map, and
    /// so did the owner's expectation on 2026-09-16 — no "Search this area"
    /// tap in between).
    @State private var inView: Int?

    var body: some View {
        VStack(spacing: 0) {
            NavyBarBackdrop()
            ZStack(alignment: .top) {
                BuildingMap(buildings: results, prices: pricesByBBL, region: $region, selected: $selected, initialFit: $initialFit,
                            onUserMoved: { moved = true }, onVisibleCount: { inView = $0 })
                    .ignoresSafeArea(edges: .bottom)
                // The count follows the viewport: pan or zoom and it reads what
                // is on screen, and List opens on exactly that. Until the user
                // moves the map it is the whole search.
                Text(!searched ? "Searching…"
                     : moved ? "\((inView ?? results.count).formatted()) \(query.noun) in view"
                     : "\(results.count.formatted()) \(query.noun)")
                    .font(.se(15, .bold)).foregroundStyle(SE.ink)
                    .padding(.horizontal, 12).padding(.vertical, 6).background(Color.white.opacity(0.95)).clipShape(Capsule())
                    // Tests wait for "map-count" and read its number; it only
                    // carries that id once there is a number to read.
                    .accessibilityIdentifier(searched ? "map-count" : "map-count-pending")
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
        .toolbar { ToolbarItem(placement: .principal) { ResultsHeader(query: query,
            onLocation: { Analytics.shared.track("location_open", ["src": "map"]); showLocation = true },
            onFilter: { Analytics.shared.track("filters_open", ["src": "map"]); showFilters = true },
            edit: $query) } }
        .sheet(isPresented: $showFilters) { FiltersSheet(query: $query) }
        .sheet(isPresented: $showLocation) { LocationPickerView(selected: $query.locations) }
        .task(id: query) {
            // A map area only says where to LOOK. The pins cover the whole
            // search so panning past the box keeps showing buildings, and the
            // box (or the viewport, on the way back to the list) is what gets
            // listed.
            var wide = query
            wide.locations.removeAll { if case .mapArea = $0 { return true }; return false }
            // Search and bubble prices on a background task, every core.
            let (r, prices) = await SearchEngine.runForMapAsync(wide, store: store)
            guard !Task.isCancelled else { return }
            results = r
            searched = true
            inView = nil
            pricesByBBL = prices
            // A custom map area IS the viewport the user was looking at, so
            // reopening the map lands exactly there instead of on all of NYC.
            if case .mapArea(let box)? = query.locations.first(where: { if case .mapArea = $0 { return true }; return false }) {
                region = box.region
            } else {
                region = (results.count > 0 && results.count <= 500) ? MapRegion.fit(results, city: store.city)
                    : await MapRegion.forQueryAsync(query, store: store)
            }
        }
        .swipeBackEnabled()
    }

    /// The list underneath was pushed with the query the map STARTED from.
    /// The map's Filter sheet changes this view's copy, and a moved map means
    /// the viewport, so a plain pop would show the old results. Rewrite the
    /// results route with the map's current query instead.
    private func backToList() {
        // Once the user has moved the map, the list is what the map shows.
        var q = query
        if moved { q.locations = [.mapArea(MapBox(region: region))] }
        Analytics.shared.track("map_list", ["moved": moved, "in_view": inView ?? results.count, "results": results.count])
        var path = nav.searchPath
        if !path.isEmpty { path.removeLast() }
        if case .results? = path.last { path[path.count - 1] = .results(q) } else { path.append(.results(q)) }
        nav.searchPath = path
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
                    Text("\(building.u.map { "\($0) units" } ?? "") · \(building.yr.map { (store.city.isIncomeRestricted ? "since " : "built ") + "\($0)" } ?? "")").font(.se(14)).foregroundStyle(SE.ink3)
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

/// Pins carry a stable key so a refresh can keep the ones that did not change
/// instead of removing and re-adding every pin (2026-10-02).
protocol KeyedAnnotation: MKAnnotation { var key: String { get } }

final class BuildingAnnotation: NSObject, KeyedAnnotation {
    let building: Building
    let price: Int?
    let key: String
    init(_ b: Building, price: Int?) { building = b; self.price = price; key = "b:\(b.bbl):\(price ?? -1)" }
    var coordinate: CLLocationCoordinate2D { building.coordinate }
    var title: String? { building.address }
}

/// Aggregate pin for a grid cell when there are too many buildings to draw.
final class GridAnnotation: NSObject, KeyedAnnotation {
    let coordinate: CLLocationCoordinate2D
    let count: Int
    let key: String
    init(coordinate: CLLocationCoordinate2D, count: Int, key: String) { self.coordinate = coordinate; self.count = count; self.key = key }
}

struct BuildingMap: UIViewRepresentable {
    let buildings: [Building]
    let prices: [String: Int]
    @Binding var region: MKCoordinateRegion
    @Binding var selected: Building?
    @Binding var initialFit: Bool
    var onUserMoved: () -> Void
    /// Called after each (debounced) move with the number of `buildings`
    /// inside the viewport — the exact viewport, not the padded one the pins
    /// are built from.
    var onVisibleCount: (Int) -> Void

    /// Buildings whose coordinate lies inside the region's box.
    static func countInView(_ buildings: [Building], region r: MKCoordinateRegion) -> Int {
        let minLat = r.center.latitude - r.span.latitudeDelta / 2, maxLat = r.center.latitude + r.span.latitudeDelta / 2
        let minLng = r.center.longitude - r.span.longitudeDelta / 2, maxLng = r.center.longitude + r.span.longitudeDelta / 2
        var n = 0
        for b in buildings where b.lat >= minLat && b.lat <= maxLat && b.lng >= minLng && b.lng <= maxLng { n += 1 }
        return n
    }

    /// Above this many buildings in view, cells replace pins. 47k pins froze
    /// the map and a "nearest 6,000 to the centre" sample left most of the
    /// city blank; a fixed grid is cheap at any zoom and covers everything.
    static let pinLimit = 700
    /// How far apart cluster bubbles are, in POINTS ON SCREEN — not in degrees
    /// and not as a column count.
    ///
    /// The grid used to be "9 columns across the viewport" with cells 1.2x as
    /// tall as wide. A phone's map is roughly twice as tall as it is wide, so
    /// that came out at 9 columns by ~16 rows — up to 145 cells on screen, and
    /// the bubbles (44pt across for a three-digit count) overlapped each other
    /// in a solid mat. Sizing the cell in screen points instead makes it square
    /// where it matters, gives the same spacing on any device and at any zoom,
    /// and is the number to turn if the map ever wants to be busier or calmer.
    static let cellPoints: CGFloat = 132
    /// A bubble sits at the average position of its cell's buildings, which can
    /// land right on a cell edge and touch its neighbour. Clamping that average
    /// into the middle of the cell keeps the layout organic rather than a rigid
    /// lattice, while guaranteeing bubbles stay `cellPoints * (1 - clamp)`
    /// apart — 66pt here, comfortably more than the widest bubble.
    static let centroidClamp: CGFloat = 0.5

    /// Degrees per grid cell for a viewport, from a cell measured in screen
    /// points. Square on screen, which is the only place squareness matters —
    /// a phone's map is about twice as tall as it is wide, so a grid defined in
    /// degrees gives twice as many rows as columns and the bubbles collide.
    static func cellSize(region: MKCoordinateRegion, viewSize: CGSize) -> (lng: Double, lat: Double) {
        (lng: region.span.longitudeDelta * Double(cellPoints / max(viewSize.width, 1)),
         lat: region.span.latitudeDelta * Double(cellPoints / max(viewSize.height, 1)))
    }

    /// Cluster bubbles for the buildings in view: one per map-anchored cell,
    /// at the average position of its buildings pulled toward the cell's
    /// middle. Each cell keeps its own column and row — build 108 packed them
    /// into one Int and unpacked it with a floor that is wrong for negative
    /// longitudes, which put every New York bubble at an impossible
    /// coordinate, so MapKit drew none (owner, 2026-10-03).
    nonisolated static func gridAnnotations(_ visible: [Building], cw: Double, ch: Double) -> [GridAnnotation] {
        struct Cell: Hashable { let i: Int; let j: Int }
        var cells: [Cell: (lat: Double, lng: Double, n: Int)] = [:]
        for b in visible {
            let c = Cell(i: Int((b.lng / cw).rounded(.down)), j: Int((b.lat / ch).rounded(.down)))
            var acc = cells[c] ?? (0, 0, 0)
            acc.lat += b.lat; acc.lng += b.lng; acc.n += 1
            cells[c] = acc
        }
        let clamp = Double(centroidClamp) / 2
        let zoomTag = Int((log2(1 / max(cw, 1e-9)) * 8).rounded())
        return cells.map { c, acc in
            let lng = acc.lng / Double(acc.n), lat = acc.lat / Double(acc.n)
            let cLng = (Double(c.i) + 0.5) * cw, cLat = (Double(c.j) + 0.5) * ch
            return GridAnnotation(
                coordinate: .init(latitude: min(max(lat, cLat - ch * clamp), cLat + ch * clamp),
                                  longitude: min(max(lng, cLng - cw * clamp), cLng + cw * clamp)),
                count: acc.n, key: "g:\(zoomTag):\(c.i):\(c.j):\(acc.n)")
        }
    }

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
        private var countGeneration = 0
        /// Tile index over `parent.buildings`, rebuilt off the main thread
        /// whenever the search results change (dataKey).
        private var grid: GeoGrid?
        private var gridKey = 0
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
            let all = parent.buildings
            // The tile index belongs to this result set; a new search drops it
            // and the first background pass rebuilds it.
            if gridKey != dataKey { grid = nil; gridKey = dataKey }
            let haveGrid = grid
            let key0 = dataKey
            // The in-view count is exact and cheap (one bounds check per row,
            // off the main thread), so it follows every settled move even when
            // the pins below decide the view has not moved enough to redraw.
            let report = parent.onVisibleCount
            countGeneration += 1; let cgen = countGeneration
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                let g = haveGrid ?? GeoGrid(all)
                let r = region
                let n = g.count(minLat: r.center.latitude - r.span.latitudeDelta / 2, maxLat: r.center.latitude + r.span.latitudeDelta / 2,
                                minLng: r.center.longitude - r.span.longitudeDelta / 2, maxLng: r.center.longitude + r.span.longitudeDelta / 2)
                DispatchQueue.main.async {
                    guard let self else { return }
                    if self.grid == nil, self.gridKey == key0 { self.grid = g }
                    if cgen == self.countGeneration { report(n) }
                }
            }
            // Only re-aggregate when the view moved a meaningful amount.
            let zoom = Int((log2(360 / max(region.span.longitudeDelta, 1e-6))).rounded())
            let cellLat = region.span.latitudeDelta / 3, cellLng = region.span.longitudeDelta / 3
            let key = "\(zoom):\(Int(region.center.latitude / cellLat)):\(Int(region.center.longitude / cellLng))"
            if !force && key == lastLayoutKey { return }
            lastLayoutKey = key
            let prices = parent.prices
            let limit = BuildingMap.pinLimit
            // Degrees per cell, from a cell measured in screen points. The map
            // view's own size is the only honest source for this: it differs by
            // device, and by whether the list sheet is up.
            let (rawW, rawH) = BuildingMap.cellSize(region: region, viewSize: m.bounds.size)
            // Snapped to a ladder of sizes (steps of 2^¼, ~19%): latitudeDelta
            // drifts as the map pans north/south, and an unsnapped cell height
            // would shift every cell key and defeat the pin diff below.
            func snap(_ v: Double) -> Double { pow(2, (log2(max(v, 1e-9)) * 4).rounded() / 4) }
            let cw = snap(rawW), ch = snap(rawH)
            generation += 1; let gen = generation
            // Padded viewport; the work runs off the main thread.
            let pad = 0.6
            let minLat = region.center.latitude - region.span.latitudeDelta * (0.5 + pad)
            let maxLat = region.center.latitude + region.span.latitudeDelta * (0.5 + pad)
            let minLng = region.center.longitude - region.span.longitudeDelta * (0.5 + pad)
            let maxLng = region.center.longitude + region.span.longitudeDelta * (0.5 + pad)
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                let visible = Perf.interval("map.visible") {
                    (haveGrid ?? GeoGrid(all)).visible(minLat: minLat, maxLat: maxLat, minLng: minLng, maxLng: maxLng)
                }
                var pins: [MKAnnotation] = []
                if visible.count <= limit {
                    pins = visible.map { BuildingAnnotation($0, price: prices[$0.bbl]) }
                } else {
                    // A grid over the padded viewport whose cells are square on
                    // screen, so bubbles are spaced the same in both directions
                    // and at every zoom.
                    // Cells are anchored to the map, not the viewport: a pan at
                    // the same zoom keeps the same cells, so most bubbles stay
                    // put and only the edges are added or removed.
                    pins = BuildingMap.gridAnnotations(visible, cw: cw, ch: ch)
                }
                DispatchQueue.main.async {
                    guard let self, gen == self.generation else { return }
                    Perf.interval("map.diff") {
                        // Diff instead of replace: keep pins whose key is
                        // unchanged, remove the rest, add only the new ones.
                        // The selected pin is never removed out from under
                        // the user.
                        let selBBL = self.parent.selected?.bbl
                        var current: [String: MKAnnotation] = [:]
                        for a in m.annotations { if let k = (a as? KeyedAnnotation)?.key { current[k] = a } }
                        var wanted = Set<String>(); wanted.reserveCapacity(pins.count)
                        var add: [MKAnnotation] = []
                        for p in pins {
                            guard let k = (p as? KeyedAnnotation)?.key else { continue }
                            wanted.insert(k)
                            if current[k] == nil { add.append(p) }
                        }
                        let remove = current.filter { k, a in
                            !wanted.contains(k) && (a as? BuildingAnnotation)?.building.bbl != selBBL
                        }.map(\.value)
                        if !remove.isEmpty { m.removeAnnotations(remove) }
                        if !add.isEmpty { m.addAnnotations(add) }
                    }
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
        isAccessibilityElement = true
        accessibilityIdentifier = "cluster-bubble"
        accessibilityLabel = "\(n) buildings"
        let d: CGFloat = n >= 100 ? 44 : (n >= 10 ? 38 : 32)
        bounds = CGRect(x: 0, y: 0, width: d, height: d)
        label.frame = bounds
        layer.cornerRadius = d / 2
        backgroundColor = UIColor(SE.navy)
        layer.borderColor = UIColor.white.cgColor; layer.borderWidth = 2
    }
}
