import SwiftUI
import MapKit

struct SearchHomeView: View {
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    @Environment(AppNav.self) private var nav
    @AppStorage("lastQuery") private var lastQueryData: Data = Data()
    @State private var query = SearchQuery()
    @State private var showLocation = false
    @State private var count = 0

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HeroCollage().padding(.bottom, 14)

                SEUnderlineTabs(options: SearchMode.allCases.map { ($0, $0.title) }, selection: $query.mode)
                    .padding(.horizontal, 16)
                    .padding(.bottom, 20)

                VStack(alignment: .leading, spacing: 18) {
                    // Location
                    VStack(alignment: .leading, spacing: 10) {
                        SEFieldLabel(text: "Location")
                        // Not a Button: chips inside a Button label get flattened into
                        // one accessibility element, so their remove buttons vanish
                        // for VoiceOver and XCUITest. The box takes the tap instead.
                        SEFieldBox {
                            HStack(spacing: 10) {
                                Image(systemName: "mappin").font(.system(size: 18, weight: .bold)).foregroundStyle(SE.royal).accessibilityHidden(true)
                                if query.locations.isEmpty {
                                    Text("Neighborhood, borough or ZIP").font(.se(19)).foregroundStyle(SE.ink3)
                                    Spacer(minLength: 0)
                                } else {
                                    ScrollView(.horizontal, showsIndicators: false) {
                                        HStack(spacing: 8) {
                                            ForEach(query.locations, id: \.self) { loc in
                                                SEChip(text: loc.label) { query.locations.removeAll { $0 == loc } }
                                            }
                                        }
                                    }
                                }
                            }
                            .padding(.horizontal, 12).padding(.vertical, 6)
                        }
                        .contentShape(Rectangle())
                        .onTapGesture { showLocation = true }
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("location-field")
                        .accessibilityAddTraits(.isButton)
                        .accessibilityLabel(query.locations.isEmpty ? "Location" : "Location: \(query.locationLabel)")
                    }

                    // Price
                    HStack(spacing: 16) {
                        PriceField(label: "Minimum price", value: $query.minPrice, placeholder: "No min")
                        PriceField(label: "Maximum price", value: $query.maxPrice, placeholder: "No max")
                    }

                    // Mode-specific row
                    switch query.mode {
                    case .rent:
                        VStack(alignment: .leading, spacing: 10) {
                            SEFieldLabel(text: "Bedrooms")
                            SESegmentRow(options: [(0, "Studio"), (1, "1"), (2, "2"), (3, "3"), (4, "4+")], selection: $query.beds)
                        }
                    case .stabilized:
                        VStack(alignment: .leading, spacing: 10) {
                            SEFieldLabel(text: "Building size")
                            SESegmentRow(options: [(0, "1–5"), (1, "6–19"), (2, "20–49"), (3, "50+")], selection: $query.unitBands)
                            Text("Units in the building").font(.se(14)).foregroundStyle(SE.ink3)
                        }
                    case .vouchers:
                        VStack(alignment: .leading, spacing: 10) {
                            SEFieldLabel(text: "Voucher listings")
                            Toggle(isOn: $query.voucherLiveOnly) {
                                VStack(alignment: .leading, spacing: 2) {
                                    Text("Accepting vouchers right now").font(.se(18, .semibold))
                                    Text("Live listings on AffordableHousing.com only").font(.se(14)).foregroundStyle(SE.ink3)
                                }
                            }
                            .tint(SE.royal)
                            .padding(14)
                            .overlay(Rectangle().stroke(SE.line, lineWidth: 1))
                        }
                    }

                    SEPrimaryButton(title: "Search \(count.formatted()) \(query.mode.noun)") { runSearch() }
                        .padding(.horizontal, 34)
                        .padding(.top, 6)
                        .accessibilityIdentifier("search-button")
                        .disabled(!store.loaded)
                }
                .padding(.horizontal, 16)

                if !activity.recentSearches.isEmpty {
                    Text("Pick up where you left off:")
                        .font(.se(22, .bold)).foregroundStyle(SE.ink2)
                        .padding(.horizontal, 16).padding(.top, 34).padding(.bottom, 12)
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 12) {
                            ForEach(Array(activity.recentSearches.prefix(6).enumerated()), id: \.offset) { _, q in
                                RecentSearchCard(query: q) {
                                    query = q
                                    nav.searchPath.append(.results(q))
                                }
                            }
                        }
                        .padding(.horizontal, 16)
                    }
                }
                Color.clear.frame(height: 110)
            }
        }
        .background(Color.white)
        .scrollDismissesKeyboard(.interactively)
        .sheet(isPresented: $showLocation) {
            LocationPickerView(selected: $query.locations)
        }
        .onAppear {
            if query == SearchQuery(), let q = try? JSONDecoder().decode(SearchQuery.self, from: lastQueryData) { query = q }
            recount()
        }
        .onChange(of: query) { _, q in
            lastQueryData = (try? JSONEncoder().encode(q)) ?? Data()
            recount()
        }
        .onChange(of: store.loaded) { _, _ in recount() }
    }

    private func recount() { count = store.loaded ? SearchEngine.count(query, store: store) : 0 }

    private func runSearch() {
        activity.recordSearch(query)
        nav.searchPath.append(.results(query))
    }
}

// MARK: - Price field

struct PriceField: View {
    let label: String
    @Binding var value: Int?
    let placeholder: String
    @State private var text = ""
    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SEFieldLabel(text: label)
            SEFieldBox {
                TextField(placeholder, text: $text)
                    .font(.se(20))
                    .keyboardType(.numberPad)
                    .focused($focused)
                    .padding(.horizontal, 14)
                    .accessibilityIdentifier("price-\(label)")
            }
        }
        .onAppear { text = value.map(Formatters.dollars) ?? "" }
        .onChange(of: value) { _, v in if !focused { text = v.map(Formatters.dollars) ?? "" } }
        .onChange(of: text) { _, t in
            let digits = t.filter(\.isNumber)
            let n = Int(digits)
            if n != value { value = (n ?? 0) > 0 ? n : nil }
        }
        .onChange(of: focused) { _, f in
            if !f { text = value.map(Formatters.dollars) ?? "" }
            else if let v = value { text = String(v) }
        }
    }
}

// MARK: - Recent search card

struct RecentSearchCard: View {
    @Environment(Activity.self) private var activity
    @Environment(DataStore.self) private var store
    let query: SearchQuery
    let open: () -> Void
    @State private var snapshot: UIImage?

    var body: some View {
        Button(action: open) {
            HStack(spacing: 0) {
                ZStack {
                    if let snapshot { FillImage(image: snapshot) }
                    else { SE.canvas }
                }
                .frame(width: 104, height: 140).clipped()
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .top) {
                        Text("\(query.mode == .rent ? "Rentals" : (query.mode == .vouchers ? "Voucher homes" : "Stabilized")) in")
                            .font(.se(22, .bold)).foregroundStyle(SE.royal).lineLimit(1)
                        Spacer()
                        Image(systemName: activity.isSearchSaved(query) ? "heart.fill" : "heart")
                            .font(.system(size: 20)).foregroundStyle(SE.royal)
                    }
                    Text(query.locationLabel).font(.se(17)).foregroundStyle(SE.ink2).lineLimit(1)
                    Text(query.summary).font(.se(16)).foregroundStyle(SE.ink3).lineLimit(2)
                }
                .padding(12)
                .frame(width: 176, alignment: .leading)
            }
            .seCard()
        }
        .buttonStyle(.plain)
        .task { snapshot = await MapThumb.shared.image(for: query, store: store) }
    }
}

/// Small map thumbnails for the "pick up where you left off" rail.
actor MapThumb {
    static let shared = MapThumb()
    private var cache: [SearchQuery: UIImage] = [:]
    func image(for q: SearchQuery, store: DataStore) async -> UIImage? {
        if let c = cache[q] { return c }
        let region = await MainActor.run { MapRegion.forQuery(q, store: store) }
        let o = MKMapSnapshotter.Options()
        o.region = region; o.size = CGSize(width: 208, height: 280)
        o.pointOfInterestFilter = .excludingAll
        guard let s = try? await MKMapSnapshotter(options: o).start() else { return nil }
        cache[q] = s.image
        return s.image
    }
}

enum MapRegion {
    static let nyc = MKCoordinateRegion(center: .init(latitude: 40.72, longitude: -73.95), span: .init(latitudeDelta: 0.35, longitudeDelta: 0.35))
    @MainActor
    static func forQuery(_ q: SearchQuery, store: DataStore) -> MKCoordinateRegion {
        if case .mapArea(let box)? = q.locations.first { return box.region }
        guard !q.locations.isEmpty else { return nyc }
        var minLat = 90.0, maxLat = -90.0, minLng = 180.0, maxLng = -180.0, n = 0
        for b in store.buildings where q.locations.contains(where: { $0.matches(b) }) {
            minLat = min(minLat, b.lat); maxLat = max(maxLat, b.lat)
            minLng = min(minLng, b.lng); maxLng = max(maxLng, b.lng); n += 1
        }
        guard n > 0 else { return nyc }
        return MKCoordinateRegion(center: .init(latitude: (minLat + maxLat) / 2, longitude: (minLng + maxLng) / 2),
                                  span: .init(latitudeDelta: max(0.01, (maxLat - minLat) * 1.2), longitudeDelta: max(0.01, (maxLng - minLng) * 1.2)))
    }
    static func fit(_ bs: [Building]) -> MKCoordinateRegion {
        guard !bs.isEmpty else { return nyc }
        var minLat = 90.0, maxLat = -90.0, minLng = 180.0, maxLng = -180.0
        for b in bs { minLat = min(minLat, b.lat); maxLat = max(maxLat, b.lat); minLng = min(minLng, b.lng); maxLng = max(maxLng, b.lng) }
        return MKCoordinateRegion(center: .init(latitude: (minLat + maxLat) / 2, longitude: (minLng + maxLng) / 2),
                                  span: .init(latitudeDelta: max(0.008, (maxLat - minLat) * 1.25), longitudeDelta: max(0.008, (maxLng - minLng) * 1.25)))
    }
}

// MARK: - Hero collage

/// StreetEasy opens on a photo collage around a brand card. Ours is built from
/// Look Around imagery of real NYC blocks — no stock photos, no licensing.
struct HeroCollage: View {
    static let spots: [(String, Double, Double)] = [
        ("hero-park-slope", 40.6737, -73.9776),
        ("hero-harlem", 40.8075, -73.9455),
        ("hero-astoria", 40.7644, -73.9235),
        ("hero-fort-greene", 40.6892, -73.9740),
        ("hero-east-village", 40.7265, -73.9815),
        ("hero-bed-stuy", 40.6872, -73.9418),
        ("hero-uws", 40.7870, -73.9754),
        ("hero-bushwick", 40.6944, -73.9213),
    ]
    var body: some View {
        HStack(spacing: 6) {
            VStack(spacing: 6) { tile(0); tile(1); tile(2) }.frame(width: 64)
            VStack(spacing: 6) {
                BrandCard().frame(height: 128)
                HStack(spacing: 6) { tile(3); tile(4) }
            }
            VStack(spacing: 6) { tile(5); tile(6); tile(7) }.frame(width: 64)
        }
        .frame(height: 240)
        .padding(.horizontal, 6)
        .padding(.vertical, 6)
        .background(SE.navy.ignoresSafeArea(edges: .top))
    }
    private func tile(_ i: Int) -> some View {
        let s = Self.spots[i]
        return HeroTile(building: Building(bbl: s.0, b: "", a: "", z: nil, lat: s.1, lng: s.2))
    }
}

struct HeroTile: View {
    let building: Building
    @State private var image: UIImage?
    var body: some View {
        ZStack {
            SE.navyDeep
            if let image { FillImage(image: image) }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .clipped()
        .task { image = await ImageService.shared.image(for: building, size: CGSize(width: 300, height: 300)) }
    }
}

struct BrandCard: View {
    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(hex: 0xDCE9F5), Color(hex: 0xF3F7FB)], startPoint: .top, endPoint: .bottom)
            VStack(spacing: 6) {
                HStack(spacing: 8) {
                    BrandMark().frame(width: 24, height: 24)
                    Text("Find A Crib").font(.se(22, .bold)).foregroundStyle(SE.navy)
                }
                Text("This is where it starts").font(.se(23, .black)).foregroundStyle(SE.navy)
                    .lineLimit(1).minimumScaleFactor(0.6)
                Text("Every rent-stabilized building in NYC").font(.se(13, .semibold)).foregroundStyle(SE.ink2).lineLimit(1).minimumScaleFactor(0.7)
            }
            .padding(.horizontal, 14)
        }
        .clipShape(RoundedRectangle(cornerRadius: 3))
    }
}

/// The brand's "a" mark from brand/icon.svg, drawn in SwiftUI so it scales.
struct BrandMark: View {
    var body: some View {
        GeometryReader { g in
            let w = g.size.width
            ZStack {
                Path { p in
                    // squared-off "a": half-disc on the left, flat right edge
                    p.addRoundedRect(in: CGRect(x: 0, y: w * 0.15, width: w, height: w * 0.7), cornerRadii: RectangleCornerRadii(topLeading: w * 0.35, bottomLeading: w * 0.35, bottomTrailing: 0, topTrailing: 0))
                }
                .fill(SE.brand)
                Circle().stroke(Color.white, lineWidth: w * 0.09).frame(width: w * 0.36, height: w * 0.36).offset(x: -w * 0.13)
                Path { p in p.move(to: CGPoint(x: w * 0.5, y: w * 0.62)); p.addLine(to: CGPoint(x: w * 0.6, y: w * 0.72)) }
                    .stroke(Color.white, style: StrokeStyle(lineWidth: w * 0.09, lineCap: .round))
            }
        }
    }
}
