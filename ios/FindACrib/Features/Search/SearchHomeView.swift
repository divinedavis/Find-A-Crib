import SwiftUI
import MapKit

struct SearchHomeView: View {
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    @Environment(AppNav.self) private var nav
    @AppStorage("lastQuery") private var lastQueryData: Data = Data()
    @State private var query = SearchQuery()
    @State private var showLocation = false
    @State private var showCity = false
    @State private var count = 0

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HeroCollage().padding(.bottom, 22)


                VStack(alignment: .leading, spacing: 18) {
                    // City first: it decides what the Location field can offer.
                    VStack(alignment: .leading, spacing: 10) {
                        SEFieldLabel(text: "City")
                        SEFieldBox {
                            HStack(spacing: 10) {
                                Image(systemName: "building.2").font(.system(size: 18, weight: .bold)).foregroundStyle(SE.royal).accessibilityHidden(true)
                                VStack(alignment: .leading, spacing: 1) {
                                    Text(store.city.name).font(.se(19)).foregroundStyle(SE.ink)
                                    Text(store.loaded ? "\(store.buildings.count.formatted()) \(store.city.statusLabel.lowercased()) buildings"
                                                      : "Loading \(store.city.name)…")
                                        .font(.se(13)).foregroundStyle(SE.ink3)
                                }
                                Spacer(minLength: 0)
                                Image(systemName: "chevron.down").font(.system(size: 13, weight: .bold)).foregroundStyle(SE.ink3)
                            }
                            .padding(.horizontal, 12).padding(.vertical, 6)
                        }
                        .contentShape(Rectangle())
                        .onTapGesture { showCity = true }
                        .accessibilityElement(children: .combine)
                        .accessibilityIdentifier("city-field")
                        .accessibilityAddTraits(.isButton)
                        .accessibilityLabel("City: \(store.city.name)")
                    }

                    // Location
                    VStack(alignment: .leading, spacing: 10) {
                        SEFieldLabel(text: store.city.isNYC ? "Location" : store.city.regionLabel)
                        // Not a Button: chips inside a Button label get flattened into
                        // one accessibility element, so their remove buttons vanish
                        // for VoiceOver and XCUITest. The box takes the tap instead.
                        SEFieldBox {
                            HStack(spacing: 10) {
                                Image(systemName: "mappin").font(.system(size: 18, weight: .bold)).foregroundStyle(SE.royal).accessibilityHidden(true)
                                if query.locations.isEmpty {
                                    Text(store.city.searchPlaceholder).font(.se(19)).foregroundStyle(SE.ink3)
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
                        .accessibilityLabel(query.locations.isEmpty ? "Location" : "Location: \(query.locationLabel(city: store.city.short))")
                    }

                    // Price. Los Angeles publishes no rent at all — its source is
                    // an assessor roll — so the fields are not offered there
                    // rather than offered and filtering everything away.
                    if store.city.hasPrices {
                        VStack(alignment: .leading, spacing: 8) {
                            PriceRangeFields(minPrice: $query.minPrice, maxPrice: $query.maxPrice)
                            if !store.city.isNYC {
                                Text("\(store.city.priceLabel) — what the register has on file, not an asking rent. Buildings with no rent on file are not shown when you set a price.")
                                    .font(.se(14)).foregroundStyle(SE.ink3)
                            }
                        }
                    }

                    // Show and Bedrooms both read New York feeds — advertised
                    // rents, vouchers and lotteries. The other cities publish a
                    // register and nothing else, so offering those filters there
                    // would be offering a way to get zero results.
                    if store.city.hasNYCExtras {
                        // Show: multi-select. Every building here is rent-stabilized, so
                        // that box is the always-on baseline; the others narrow it.
                        VStack(alignment: .leading, spacing: 10) {
                            SEFieldLabel(text: "Show")
                            ShowChecklist(query: $query)
                        }
                        VStack(alignment: .leading, spacing: 10) {
                            SEFieldLabel(text: "Bedrooms")
                            SESegmentRow(options: [(0, "Studio"), (1, "1"), (2, "2"), (3, "3"), (4, "4+")], selection: $query.beds)
                                .accessibilityIdentifier("beds-row")
                            Text("From recent listings — picking a size narrows to buildings with an advertised apartment.")
                                .font(.se(14)).foregroundStyle(SE.ink3)
                        }
                    } else {
                        Text(store.city.sourceNote).font(.se(14)).foregroundStyle(SE.ink3)
                    }

                    SEPrimaryButton(title: "Search \(count.formatted()) \(query.noun)") { runSearch() }
                        .padding(.horizontal, 34)
                        .padding(.top, 6)
                        .accessibilityIdentifier("search-button")
                        .disabled(!store.loaded)
                }
                .readableColumn()
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
        .sheet(isPresented: $showCity) {
            CityPickerView { c in
                // A scope from the old city cannot match anything in the new
                // one, and the New York-only flags have no data behind them
                // elsewhere, so both are cleared rather than silently emptying
                // the results.
                query.locations = []
                // $3,500 in New York is not $3,500 in Los Angeles, and outside
                // New York a carried-over price matched nothing at all — the
                // rent feeds are New York's. Start each city clean.
                query.minPrice = nil; query.maxPrice = nil
                query = query.sanitized(for: c)
                Analytics.shared.track("city_switch", ["from": store.city.id, "to": c.id, "city": c.id])
                Analytics.shared.city = c.id
                Task { await store.switchCity(to: c) }
            }
        }
        .onAppear {
            // The saved query may predate the city the app reopens in, so drop
            // anything that city cannot answer before it is counted.
            if query == SearchQuery(), let q = try? JSONDecoder().decode(SearchQuery.self, from: lastQueryData) {
                query = q.normalized.sanitized(for: store.city)
            }
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
                    Text(query.locationLabel(city: store.city.short)).font(.se(17)).foregroundStyle(SE.ink2).lineLimit(1)
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

    /// Where a city opens. Every fallback below goes through this: the map used
    /// to fall back to New York, so LA — where a plain search has no location
    /// and more than 500 results — opened on Manhattan (owner, 2026-09-19).
    static func of(_ city: City) -> MKCoordinateRegion {
        MKCoordinateRegion(center: .init(latitude: city.lat, longitude: city.lng),
                           span: .init(latitudeDelta: city.span, longitudeDelta: city.span))
    }

    @MainActor
    static func forQuery(_ q: SearchQuery, store: DataStore) -> MKCoordinateRegion {
        if case .mapArea(let box)? = q.locations.first { return box.region }
        guard !q.locations.isEmpty else { return of(store.city) }
        var minLat = 90.0, maxLat = -90.0, minLng = 180.0, maxLng = -180.0, n = 0
        for b in store.buildings where q.locations.contains(where: { $0.matches(b) }) {
            minLat = min(minLat, b.lat); maxLat = max(maxLat, b.lat)
            minLng = min(minLng, b.lng); maxLng = max(maxLng, b.lng); n += 1
        }
        guard n > 0 else { return of(store.city) }
        return MKCoordinateRegion(center: .init(latitude: (minLat + maxLat) / 2, longitude: (minLng + maxLng) / 2),
                                  span: .init(latitudeDelta: max(0.01, (maxLat - minLat) * 1.2), longitudeDelta: max(0.01, (maxLng - minLng) * 1.2)))
    }
    static func fit(_ bs: [Building], city: City) -> MKCoordinateRegion {
        guard !bs.isEmpty else { return of(city) }
        var minLat = 90.0, maxLat = -90.0, minLng = 180.0, maxLng = -180.0
        for b in bs { minLat = min(minLat, b.lat); maxLat = max(maxLat, b.lat); minLng = min(minLng, b.lng); maxLng = max(maxLng, b.lng) }
        return MKCoordinateRegion(center: .init(latitude: (minLat + maxLat) / 2, longitude: (minLng + maxLng) / 2),
                                  span: .init(latitudeDelta: max(0.008, (maxLat - minLat) * 1.25), longitudeDelta: max(0.008, (maxLng - minLng) * 1.25)))
    }
}

// MARK: - Hero collage

/// StreetEasy opens on a photo collage around a brand card. Ours is built from
/// Look Around imagery of real NYC blocks — no stock photos, no licensing.
/// The mosaic at the top of Search: eight Apple Look Around snapshots of the
/// city that is loaded, re-drawn from a curated pool every time the screen
/// appears (owner, 2026-09-19). Pictures only — tapping one opened the movable
/// Look Around for a day and the owner took it back out (2026-09-20).
///
/// Curated corners rather than random buildings from the register: coverage is
/// what makes this look good, and a random parcel is as likely to be an alley
/// wall as a street. Each spot's id is stable, so ImageService caches its
/// snapshot on disk and a second launch paints instantly.
struct HeroCollage: View {
    @Environment(DataStore.self) private var store
    @State private var picks: [HeroSpot] = []

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
        .task(id: store.city.id) { picks = HeroSpot.pick(for: store.city) }
    }

    @ViewBuilder private func tile(_ i: Int) -> some View {
        if i < picks.count {
            HeroTile(building: picks[i].building)
                .accessibilityLabel(picks[i].name)
                .accessibilityIdentifier("hero-tile")
        } else {
            SE.navyDeep.frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}

/// One corner of a city: a stable id (the snapshot cache key), what to call it,
/// and where it is.
struct HeroSpot: Identifiable, Hashable {
    let id: String
    let name: String
    let lat: Double
    let lng: Double

    var building: Building { Building(bbl: id, b: "", a: name, z: nil, lat: lat, lng: lng) }
    var coordinate: CLLocationCoordinate2D { CLLocationCoordinate2D(latitude: lat, longitude: lng) }

    /// Eight of the city's corners, in a fresh order every time.
    static func pick(for city: City, count: Int = 8) -> [HeroSpot] {
        let pool = all[city.id] ?? all["nyc"]!
        return Array(pool.shuffled().prefix(count))
    }

    /// Street corners with Look Around coverage, one list per city. A spot that
    /// has no panorama falls back to a map snapshot (ImageService), so a gap
    /// costs a plain tile and never a blank one.
    static let all: [String: [HeroSpot]] = [
        "nyc": [
            HeroSpot(id: "hero-park-slope",   name: "Park Slope, Brooklyn",      lat: 40.6737, lng: -73.9776),
            HeroSpot(id: "hero-harlem",       name: "Harlem, Manhattan",         lat: 40.8075, lng: -73.9455),
            HeroSpot(id: "hero-astoria",      name: "Astoria, Queens",           lat: 40.7644, lng: -73.9235),
            HeroSpot(id: "hero-fort-greene",  name: "Fort Greene, Brooklyn",     lat: 40.6892, lng: -73.9740),
            HeroSpot(id: "hero-east-village", name: "East Village, Manhattan",   lat: 40.7265, lng: -73.9815),
            HeroSpot(id: "hero-bed-stuy",     name: "Bed-Stuy, Brooklyn",        lat: 40.6872, lng: -73.9418),
            HeroSpot(id: "hero-uws",          name: "Upper West Side",           lat: 40.7870, lng: -73.9754),
            HeroSpot(id: "hero-bushwick",     name: "Bushwick, Brooklyn",        lat: 40.6944, lng: -73.9213),
            HeroSpot(id: "hero-williamsburg", name: "Williamsburg, Brooklyn",    lat: 40.7170, lng: -73.9570),
            HeroSpot(id: "hero-les",          name: "Lower East Side",           lat: 40.7185, lng: -73.9885),
            HeroSpot(id: "hero-wash-heights", name: "Washington Heights",        lat: 40.8500, lng: -73.9380),
            HeroSpot(id: "hero-sunset-park",  name: "Sunset Park, Brooklyn",     lat: 40.6450, lng: -74.0100),
            HeroSpot(id: "hero-jackson-hts",  name: "Jackson Heights, Queens",   lat: 40.7480, lng: -73.8830),
            HeroSpot(id: "hero-crown-hts",    name: "Crown Heights, Brooklyn",   lat: 40.6710, lng: -73.9570),
            HeroSpot(id: "hero-greenpoint",   name: "Greenpoint, Brooklyn",      lat: 40.7280, lng: -73.9520),
            HeroSpot(id: "hero-mott-haven",   name: "Mott Haven, the Bronx",     lat: 40.8160, lng: -73.9200),
        ],
        "la": [
            HeroSpot(id: "hero-la-hollywood",   name: "Hollywood Blvd",          lat: 34.1016, lng: -118.3387),
            HeroSpot(id: "hero-la-venice",      name: "Venice Beach",            lat: 33.9871, lng: -118.4723),
            HeroSpot(id: "hero-la-koreatown",   name: "Koreatown",               lat: 34.0619, lng: -118.3090),
            HeroSpot(id: "hero-la-echo-park",   name: "Echo Park",               lat: 34.0782, lng: -118.2606),
            HeroSpot(id: "hero-la-silver-lake", name: "Silver Lake",             lat: 34.0906, lng: -118.2760),
            HeroSpot(id: "hero-la-dtla",        name: "Downtown LA",             lat: 34.0448, lng: -118.2540),
            HeroSpot(id: "hero-la-weho",        name: "West Hollywood",          lat: 34.0900, lng: -118.3856),
            HeroSpot(id: "hero-la-highland-pk", name: "Highland Park",           lat: 34.1135, lng: -118.1919),
            HeroSpot(id: "hero-la-los-feliz",   name: "Los Feliz",               lat: 34.1053, lng: -118.2915),
            HeroSpot(id: "hero-la-mid-city",    name: "Mid-City",                lat: 34.0619, lng: -118.3440),
        ],
        "sf": [
            HeroSpot(id: "hero-sf-mission",   name: "The Mission",               lat: 37.7616, lng: -122.4216),
            HeroSpot(id: "hero-sf-haight",    name: "Haight-Ashbury",            lat: 37.7699, lng: -122.4469),
            HeroSpot(id: "hero-sf-north-bch", name: "North Beach",               lat: 37.7999, lng: -122.4079),
            HeroSpot(id: "hero-sf-castro",    name: "The Castro",                lat: 37.7626, lng: -122.4350),
            HeroSpot(id: "hero-sf-sunset",    name: "Inner Sunset",              lat: 37.7635, lng: -122.4665),
            HeroSpot(id: "hero-sf-nob-hill",  name: "Nob Hill",                  lat: 37.7918, lng: -122.4103),
            HeroSpot(id: "hero-sf-hayes",     name: "Hayes Valley",              lat: 37.7763, lng: -122.4241),
            HeroSpot(id: "hero-sf-chinatown", name: "Chinatown",                 lat: 37.7950, lng: -122.4064),
            HeroSpot(id: "hero-sf-richmond",  name: "Inner Richmond",            lat: 37.7828, lng: -122.4640),
            HeroSpot(id: "hero-sf-dogpatch",  name: "Dogpatch",                  lat: 37.7600, lng: -122.3885),
        ],
        "dc": [
            HeroSpot(id: "hero-dc-columbia",  name: "Columbia Heights",          lat: 38.9294, lng: -77.0323),
            HeroSpot(id: "hero-dc-adams-mor", name: "Adams Morgan",              lat: 38.9215, lng: -77.0422),
            HeroSpot(id: "hero-dc-u-street",  name: "U Street",                  lat: 38.9169, lng: -77.0290),
            HeroSpot(id: "hero-dc-georgetown",name: "Georgetown",                lat: 38.9050, lng: -77.0630),
            HeroSpot(id: "hero-dc-cap-hill",  name: "Capitol Hill",              lat: 38.8815, lng: -76.9960),
            HeroSpot(id: "hero-dc-shaw",      name: "Shaw",                      lat: 38.9145, lng: -77.0219),
            HeroSpot(id: "hero-dc-dupont",    name: "Dupont Circle",             lat: 38.9105, lng: -77.0435),
            HeroSpot(id: "hero-dc-petworth",  name: "Petworth",                  lat: 38.9420, lng: -77.0237),
            HeroSpot(id: "hero-dc-h-street",  name: "H Street NE",               lat: 38.9000, lng: -76.9945),
            HeroSpot(id: "hero-dc-mt-plsnt",  name: "Mount Pleasant",            lat: 38.9300, lng: -77.0380),
        ],
    ]
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
        .task(id: building.bbl) { image = await ImageService.shared.image(for: building, size: CGSize(width: 300, height: 300)) }
    }
}

struct BrandCard: View {
    @Environment(DataStore.self) private var store

    /// "Every rent-stabilized building in NYC" — the register's own word for
    /// what a building IS, without the qualifier the card has no room for
    /// ("Likely rent-stabilized (RSO)" -> "rent-stabilized").
    static func line(for city: City) -> String {
        var word = city.statusLabel.lowercased()
        if let paren = word.firstIndex(of: "(") { word = String(word[word.startIndex..<paren]) }
        word = word.replacingOccurrences(of: "likely ", with: "").trimmingCharacters(in: .whitespaces)
        return "Every \(word) building in \(city.short)"
    }
    var body: some View {
        ZStack {
            LinearGradient(colors: [Color(hex: 0xDDEEF1), Color(hex: 0xF2F8F9)], startPoint: .top, endPoint: .bottom)
            VStack(spacing: 6) {
                HStack(spacing: 8) {
                    BrandMark().frame(width: 24, height: 24)
                    Text("Find A Crib").font(.se(22, .bold)).foregroundStyle(SE.navy)
                }
                Text("This is where it starts").font(.se(23, .black)).foregroundStyle(SE.navy)
                    .lineLimit(1).minimumScaleFactor(0.6)
                Text(Self.line(for: store.city)).font(.se(13, .semibold))
            }
            .padding(.horizontal, 14)
        }
        .clipShape(RoundedRectangle(cornerRadius: 3))
    }
}

/// The app icon's mark — three homes on the teal field — drawn in SwiftUI so it
/// scales. Same geometry as scripts/make_icon.py (1024 grid), flat here.
struct BrandMark: View {
    var body: some View {
        GeometryReader { g in
            let u = g.size.width / 1024
            let homes: [[CGPoint]] = [
                [CGPoint(x: 228, y: 566), CGPoint(x: 330, y: 440), CGPoint(x: 432, y: 566), CGPoint(x: 432, y: 760), CGPoint(x: 228, y: 760)],
                [CGPoint(x: 592, y: 546), CGPoint(x: 700, y: 412), CGPoint(x: 808, y: 546), CGPoint(x: 808, y: 760), CGPoint(x: 592, y: 760)],
                [CGPoint(x: 388, y: 470), CGPoint(x: 512, y: 316), CGPoint(x: 636, y: 470), CGPoint(x: 636, y: 760), CGPoint(x: 388, y: 760)],
            ]
            ZStack {
                RoundedRectangle(cornerRadius: 229 * u, style: .continuous)
                    .fill(RadialGradient(colors: [SE.brand, SE.brandRim], center: UnitPoint(x: 0.5, y: 0.44), startRadius: 0, endRadius: 800 * u))
                Path { p in
                    for h in homes {
                        p.move(to: CGPoint(x: h[0].x * u, y: h[0].y * u))
                        for pt in h.dropFirst() { p.addLine(to: CGPoint(x: pt.x * u, y: pt.y * u)) }
                        p.closeSubpath()
                    }
                }
                .fill(Color.white)
                // the door, cut back to the field
                Path { p in
                    p.addRoundedRect(in: CGRect(x: 480 * u, y: 632 * u, width: 64 * u, height: 128 * u), cornerRadii: RectangleCornerRadii(topLeading: 32 * u, bottomLeading: 0, bottomTrailing: 0, topTrailing: 32 * u))
                }
                .fill(SE.brand)
            }
        }
    }
}


/// The Show checklist. Rent stabilized is fixed on (it is the dataset);
/// Available now and Accepting vouchers narrow it and can be combined.
struct ShowChecklist: View {
    @Binding var query: SearchQuery
    @Environment(DataStore.self) private var store
    var body: some View {
        // Every row below the first is fed by a New York source — Zumper's
        // postings, the AffordableHousing.com voucher scrape and
        // HousingSearch.ny.gov — and SearchQuery.sanitized already switches
        // them off in another city. Offering a filter that can only ever
        // return nothing is worse than not offering it (owner, 2026-09-19).
        var rows: [SECheckList.Row] = [
            .init(title: store.city.statusLabel, subtitle: store.city.registerNote, isOn: .constant(true), locked: true)
        ]
        if store.city.hasNYCExtras {
            rows += [
                .init(title: "Available now", subtitle: "Posted on Zumper in the last 5 days", isOn: $query.availableOnly),
                .init(title: "Accepting vouchers", subtitle: "Section 8 / voucher-friendly buildings", isOn: $query.vouchersOnly),
                .init(title: "HCR lotteries & waitlists", subtitle: "Apply online at HousingSearch.ny.gov", isOn: $query.hcrOnly),
            ]
        }
        return SECheckList(rows: rows)
    }
}
