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
                HeroCollage().padding(.bottom, 22)


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
                    PriceRangeFields(minPrice: $query.minPrice, maxPrice: $query.maxPrice)

                    // Show: multi-select. Every building here is rent-stabilized, so
                    // that box is the always-on baseline; the others narrow it.
                    VStack(alignment: .leading, spacing: 10) {
                        SEFieldLabel(text: "Show")
                        ShowChecklist(query: $query)
                    }
                    if query.availableOnly {
                        VStack(alignment: .leading, spacing: 10) {
                            SEFieldLabel(text: "Bedrooms")
                            SESegmentRow(options: [(0, "Studio"), (1, "1"), (2, "2"), (3, "3"), (4, "4+")], selection: $query.beds)
                        }
                    }

                    SEPrimaryButton(title: "Search \(count.formatted()) \(query.noun)") { runSearch() }
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
            if query == SearchQuery(), let q = try? JSONDecoder().decode(SearchQuery.self, from: lastQueryData) { query = q.normalized }
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

// MARK: - Price range

/// The rungs a price wheel snaps to.
///
/// Spaced the way rents actually cluster rather than evenly: $250 through the
/// band most of this corpus sits in, $500 above it, $1,000 at the top where a
/// tighter step would only make the wheel longer to spin. 0 is the sentinel for
/// the open end — "Any" below, "No max" above — because the model stores an
/// absent bound as nil and a wheel has to have a row for it.
enum PriceLadder {
    static let rungs: [Int] = {
        var v = [0]
        v += stride(from: 500, through: 2000, by: 250)
        v += stride(from: 2500, through: 5000, by: 500)
        v += stride(from: 6000, through: 10000, by: 1000)
        return v
    }()

    /// The ladder with a typed-in value spliced in, so a custom $1,830 does not
    /// silently snap to $1,750 the moment the wheel appears.
    static func rungs(including value: Int?) -> [Int] {
        guard let value, value > 0, !rungs.contains(value) else { return rungs }
        var v = rungs
        v.insert(value, at: v.firstIndex { $0 > value } ?? v.count)
        return v
    }

    static func label(_ v: Int, openEnd: String) -> String {
        v == 0 ? openEnd : Formatters.dollars(v)
    }
}

/// The min/max pair. Tapping either box opens one picker holding both bounds,
/// because the two numbers are only meaningful against each other — a min above
/// the max is not a filter, it is an empty result set, and only a control that
/// can see both can put them back in order.
struct PriceRangeFields: View {
    @Binding var minPrice: Int?
    @Binding var maxPrice: Int?
    @State private var editing: PriceBound?

    var body: some View {
        HStack(spacing: 16) {
            PriceField(label: "Minimum price", value: minPrice, placeholder: "No min") { editing = .low }
            PriceField(label: "Maximum price", value: maxPrice, placeholder: "No max") { editing = .high }
        }
        .sheet(item: $editing) { bound in
            PricePickerSheet(minPrice: $minPrice, maxPrice: $maxPrice, focus: bound)
        }
    }
}

enum PriceBound: String, Identifiable {
    case low, high
    var id: String { rawValue }
}

/// One box. Not a TextField any more: the number is entered on the wheel or on
/// the picker's Custom tab, so the box itself only has to show the current
/// value and take a tap. It keeps the identifier the field had when it was
/// editable in place, so existing UI tests still address the same element.
struct PriceField: View {
    let label: String
    let value: Int?
    let placeholder: String
    let open: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SEFieldLabel(text: label)
            Button(action: open) {
                SEFieldBox {
                    Text(value.map(Formatters.dollars) ?? placeholder)
                        .font(.se(20))
                        .foregroundStyle(value == nil ? SE.ink3 : SE.ink)
                        .lineLimit(1)
                        .padding(.horizontal, 14)
                }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("price-\(label)")
            .accessibilityLabel("\(label): \(value.map(Formatters.dollars) ?? placeholder)")
        }
    }
}

/// Both bounds on one sheet, docked at the bottom so the results count and the
/// rest of the form stay on screen while the wheel turns.
///
/// Two ways in, because they serve different people: the wheel is faster for
/// somebody feeling out a budget, and typing is the only sane route for an
/// exact figure. Which one you used last is remembered — a person who types
/// prices should not have to switch tabs every time.
struct PricePickerSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Binding var minPrice: Int?
    @Binding var maxPrice: Int?
    let focus: PriceBound

    @AppStorage("priceEntryMode") private var custom = false
    @State private var low = 0
    @State private var high = 0
    @State private var lowText = ""
    @State private var highText = ""
    @FocusState private var typing: PriceBound?

    // Frozen at onAppear, not derived from the bindings. Deriving them meant
    // that Done — which writes both bindings — handed the still-presented sheet
    // two new ladders, the wheels reloaded their rows mid-dismiss, and the app
    // hung there (31s to a lost XCUITest connection, no crash report, because
    // nothing crashed: the render loop simply never settled). The ladder only
    // has to accommodate the values the sheet opened with.
    @State private var lowRungs: [Int] = PriceLadder.rungs
    @State private var highRungs: [Int] = PriceLadder.rungs

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider().overlay(SE.lineSoft)
            if custom { customEntry } else { wheels }
        }
        .background(Color.white)
        .presentationDetents([.height(300)])
        .presentationDragIndicator(.hidden)
        // The map and the live result count behind the sheet are half the
        // reason to move a price at all, so they stay interactive.
        .presentationBackgroundInteraction(.enabled(upThrough: .height(300)))
        .onAppear {
            lowRungs = PriceLadder.rungs(including: minPrice)
            highRungs = PriceLadder.rungs(including: maxPrice)
            low = minPrice ?? 0
            high = maxPrice ?? 0
            lowText = minPrice.map(String.init) ?? ""
            highText = maxPrice.map(String.init) ?? ""
            if custom { typing = focus }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            Picker("Price entry", selection: $custom) {
                Text("Increments").tag(false)
                Text("Custom").tag(true)
            }
            .pickerStyle(.segmented)
            .accessibilityIdentifier("price-mode")
            .onChange(of: custom) { _, isCustom in
                // Carry the value across rather than resetting it: switching
                // tabs is a change of input method, not a change of mind.
                if isCustom {
                    lowText = low > 0 ? String(low) : ""
                    highText = high > 0 ? String(high) : ""
                    typing = focus
                } else {
                    typing = nil
                    low = Int(lowText.filter(\.isNumber)) ?? 0
                    high = Int(highText.filter(\.isNumber)) ?? 0
                }
            }
            Button("Done") { commit(); dismiss() }
                .font(.se(18, .bold))
                .foregroundStyle(SE.royal)
                .accessibilityIdentifier("price-done")
        }
        .padding(.horizontal, 16).padding(.vertical, 10)
    }

    private var wheels: some View {
        HStack(spacing: 0) {
            Picker("Minimum price", selection: $low) {
                ForEach(lowRungs, id: \.self) { Text(PriceLadder.label($0, openEnd: "Any")).tag($0) }
            }
            .pickerStyle(.wheel)
            .accessibilityIdentifier("price-wheel-min")
            Text("to").font(.se(18)).foregroundStyle(SE.ink2).accessibilityHidden(true)
            Picker("Maximum price", selection: $high) {
                ForEach(highRungs, id: \.self) { Text(PriceLadder.label($0, openEnd: "No max")).tag($0) }
            }
            .pickerStyle(.wheel)
            .accessibilityIdentifier("price-wheel-max")
        }
        .frame(maxHeight: .infinity)
    }

    private var customEntry: some View {
        HStack(spacing: 16) {
            typedField("Minimum price", text: $lowText, placeholder: "No min", bound: .low)
            typedField("Maximum price", text: $highText, placeholder: "No max", bound: .high)
        }
        .padding(16)
        .frame(maxHeight: .infinity, alignment: .top)
    }

    private func typedField(_ label: String, text: Binding<String>, placeholder: String, bound: PriceBound) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            SEFieldLabel(text: label)
            SEFieldBox {
                TextField(placeholder, text: text)
                    .font(.se(20))
                    .keyboardType(.numberPad)
                    .focused($typing, equals: bound)
                    .padding(.horizontal, 14)
                    .accessibilityIdentifier("price-custom-\(bound.rawValue)")
            }
        }
    }

    /// Nothing reaches the query until Done. A wheel fires onChange for every
    /// row it passes, and writing each one straight through would re-run the
    /// whole count for prices the person only scrolled over.
    ///
    /// An inverted range is resolved here rather than prevented on the wheel.
    /// Pushing the max up live as the min rolls past it was tried and does not
    /// work: a SwiftUI wheel whose selection is written from outside while the
    /// other wheel is being dragged accepts the first change and then stops
    /// tracking, so the ceiling lands one rung above where it started and the
    /// range is wrong in a new way. Swapping at commit is the version that is
    /// always right — $3,000 to $1,000 is a range whose ends are the same two
    /// numbers, and reading it back in order is what the person meant.
    private func commit() {
        var lo = custom ? Int(lowText.filter(\.isNumber)) ?? 0 : low
        var hi = custom ? Int(highText.filter(\.isNumber)) ?? 0 : high
        if lo > 0, hi > 0, lo > hi { swap(&lo, &hi) }
        minPrice = lo > 0 ? lo : nil
        maxPrice = hi > 0 ? hi : nil
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
                        Text("\(query.normalized.hcrOnly ? "Lotteries" : (query.normalized.availableOnly ? "Rentals" : (query.normalized.vouchersOnly ? "Voucher homes" : "Stabilized"))) in")
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
        .frame(height: 216)
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


/// The Show checklist. Rent stabilized is fixed on (it is the dataset);
/// Available now and Accepting vouchers narrow it and can be combined.
struct ShowChecklist: View {
    @Binding var query: SearchQuery
    var body: some View {
        SECheckList(rows: [
            .init(title: "Rent stabilized", subtitle: "Every building on the DHCR register", isOn: .constant(true), locked: true),
            .init(title: "Available now", subtitle: "Posted on Zumper in the last 5 days", isOn: $query.availableOnly),
            .init(title: "Accepting vouchers", subtitle: "Section 8 / voucher-friendly buildings", isOn: $query.vouchersOnly),
            .init(title: "HCR lotteries & waitlists", subtitle: "Apply online at HousingSearch.ny.gov", isOn: $query.hcrOnly),
        ])
    }
}
