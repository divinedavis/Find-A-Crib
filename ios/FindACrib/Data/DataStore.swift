import Foundation
import Observation

/// Holds the whole dataset in memory — 47k rows decode in well under a
/// second — and refreshes it from findacrib.com's public JSON in the
/// background. The bundle ships a seed copy so first launch works offline.
@Observable @MainActor
final class DataStore {
    private(set) var buildings: [Building] = []
    private(set) var byBBL: [String: Building] = [:]
    private(set) var listings = ListingsBlob()
    private(set) var s8 = S8Blob()
    private(set) var fmr: FMRTable = [:]
    private(set) var hcr = HCRBlob()
    /// DHCR buildings that host an HCR listing, plus one synthetic Building per
    /// listing site that is not on the register — the pool "HCR" searches run over.
    private(set) var hcrBuildings: [Building] = []
    private(set) var hcrByBBL: [String: [HCRListing]] = [:]
    private(set) var loaded = false
    private(set) var loadError: String? = nil
    private(set) var refreshing = false
    private(set) var dataAsOf: Date? = nil

    /// Which city the app is showing. Persisted, so it reopens where it was.
    private(set) var city: City = City.find(UserDefaults.standard.string(forKey: "city"))
    /// Regions to offer once a city is chosen: boroughs in NYC, neighborhoods
    /// in SF and DC, ZIP areas in LA. Name, the place it sits in, and a count.
    private(set) var regions: [(name: String, sub: String, count: Int)] = []

    /// Neighborhood names with their borough + building count, for the picker.
    private(set) var neighborhoods: [(name: String, borough: String, count: Int)] = []
    /// Neighborhood name -> borough code, for collapsing a neighborhood pick to
    /// its borough in the results header.
    private(set) var boroughOfNeighborhood: [String: String] = [:]
    private(set) var zips: [String] = []

    static let host = URL(string: "https://findacrib.com/")!
    /// Advertised rents, vouchers and lotteries are New York feeds; the other
    /// cities have buildings only, so nothing else is even requested for them.
    static let nycExtras = ["listings.json", "s8.json", "fmr.json", "hcr.json"]
    nonisolated static func files(for city: City) -> [String] {
        var f = [city.dataPath]
        // The per-building record blob, where the city has one. NYC's detail is
        // fetched live from NYC Open Data per building instead, so it has none.
        if let r = city.recordsPath { f.append(r) }
        if city.hasNYCExtras { f += nycExtras }
        return f
    }
    /// Flat cache filename for a city file, whose remote path has a directory in it.
    nonisolated static func cacheName(_ remote: String, in city: City) -> String {
        if remote == city.dataPath { return city.cacheName }
        if remote == city.recordsPath { return "\(city.id)-records.json.gz" }
        return remote
    }

    nonisolated static var cacheDir: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        let d = base.appendingPathComponent("data", isDirectory: true)
        try? FileManager.default.createDirectory(at: d, withIntermediateDirectories: true)
        return d
    }

    /// Cached copy if present, else the bundled seed. `name` is the flat cache
    /// filename, which for a city file is not its remote path.
    nonisolated static func localURL(_ name: String, bundleOnly: Bool = false) -> URL? {
        let cached = cacheDir.appendingPathComponent(name)
        if !bundleOnly, FileManager.default.fileExists(atPath: cached.path) { return cached }
        let stem = (name as NSString).deletingPathExtension
        let ext = (name as NSString).pathExtension
        return Bundle.main.url(forResource: stem, withExtension: ext, subdirectory: "Data")
            ?? Bundle.main.url(forResource: stem, withExtension: ext)
    }

    struct Payload: Sendable {
        var buildings: [Building]; var listings: ListingsBlob; var s8: S8Blob; var fmr: FMRTable; var hcr: HCRBlob
    }

    /// `bundleOnly` is for the unit tests: the test host shares the app's
    /// container, so its cache holds whatever the last simulator run fetched,
    /// and a test about the shipped seed must not read that instead.
    nonisolated static func decodeLocal(_ city: City = .nyc, bundleOnly: Bool = false) throws -> Payload {
        let dec = JSONDecoder()
        guard let bURL = localURL(city.cacheName, bundleOnly: bundleOnly) else {
            // Only NYC ships a seed in the bundle; the other cities are fetched
            // on first use, so "no local copy" there means "not downloaded yet".
            throw NSError(domain: "FindACrib", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: city.isNYC ? "Building data missing from bundle"
                                                                           : "\(city.name) hasn't been downloaded yet"])
        }
        let raw = try Data(contentsOf: bURL)
        let json = city.cacheName.hasSuffix(".gz") ? try Gunzip.inflate(raw) : raw
        var buildings = try dec.decode([Building].self, from: json)
        // The boot file carries only the counts the list and filters read; the
        // rest of each record arrives in a second blob, exactly as it does on
        // the web. Merge rather than replace, so a field that is eager in one
        // and absent in the other survives. A city with no blob, or a blob that
        // has not downloaded yet, simply keeps the eager half.
        if let rp = city.recordsPath, let u = localURL(cacheName(rp, in: city), bundleOnly: bundleOnly),
           let raw = try? Data(contentsOf: u),
           let inflated = try? (rp.hasSuffix(".gz") ? Gunzip.inflate(raw) : raw),
           let full = try? dec.decode([String: Building.HPD].self, from: inflated) {
            for i in buildings.indices {
                guard let f = full[buildings[i].bbl] else { continue }
                buildings[i] = buildings[i].merging(f)
            }
        }
        func opt<T: Decodable>(_ name: String, _ empty: T) -> T {
            guard city.hasNYCExtras, let u = localURL(name, bundleOnly: bundleOnly), let d = try? Data(contentsOf: u) else { return empty }
            do { return try dec.decode(T.self, from: d) }
            catch { NSLog("FindACrib: %@ failed to decode: %@", name, String(describing: error)); return empty }
        }
        return Payload(buildings: buildings, listings: opt("listings.json", ListingsBlob()),
                       s8: opt("s8.json", S8Blob()), fmr: opt("fmr.json", [:]), hcr: opt("hcr.json", HCRBlob()))
    }

    func load() async {
        let c = city
        do {
            let p = try await Task.detached(priority: .userInitiated) { try Self.decodeLocal(c) }.value
            applyPayload(p)
        } catch {
            loadError = error.localizedDescription
        }
        await refresh()
    }

    /// Switch cities: show whatever is already on disk immediately, then fetch.
    /// A city with nothing cached (its first use) reports not-loaded until the
    /// download lands, so the UI can say it is fetching rather than say zero.
    /// `persist: false` is for the `--city` launch argument: a screenshot run or
    /// a UI test asking to start in Los Angeles must not rewrite the city the
    /// user last chose. It did until 2026-09-12, and one UI test landing in DC
    /// left every test after it in DC — which read as three unrelated failures.
    func switchCity(to c: City, persist: Bool = true) async {
        guard c != city else { return }
        city = c
        if persist { UserDefaults.standard.set(c.id, forKey: "city") }
        loadError = nil
        buildings = []; byBBL = [:]; regions = []; neighborhoods = []; zips = []
        listings = ListingsBlob(); s8 = S8Blob(); fmr = [:]; hcr = HCRBlob()
        hcrBuildings = []; hcrByBBL = [:]
        loaded = false
        await load()
    }

    func applyPayload(_ p: Payload) {
        buildings = p.buildings
        byBBL = Dictionary(p.buildings.map { ($0.bbl, $0) }, uniquingKeysWith: { a, _ in a })
        listings = p.listings; s8 = p.s8; fmr = p.fmr; hcr = p.hcr
        dataAsOf = p.listings.updatedDate
        indexHCR()
        var nbCount: [String: (String, Int)] = [:]
        var zipSet = Set<String>()
        for b in p.buildings {
            if let n = b.nb { nbCount[n, default: (b.b, 0)].1 += 1 }
            if let z = b.z, z.count == 5 { zipSet.insert(z) }
        }
        neighborhoods = nbCount.map { (name: $0.key, borough: Borough.name($0.value.0), count: $0.value.1) }
            .sorted { $0.name < $1.name }
        boroughOfNeighborhood = nbCount.mapValues { $0.0 }
        zips = zipSet.sorted()
        regions = Self.regions(for: city, buildings: p.buildings, neighborhoods: neighborhoods)
        loaded = true
    }

    /// What the picker offers once a city is chosen.
    nonisolated static func regions(for city: City, buildings: [Building],
                                    neighborhoods: [(name: String, borough: String, count: Int)])
        -> [(name: String, sub: String, count: Int)] {
        switch city.regionKind {
        case .borough:
            return Borough.all.map { b in
                (name: b.name, sub: city.short, count: buildings.lazy.filter { $0.b == b.code }.count)
            }.filter { $0.count > 0 }
        case .neighborhood:
            return neighborhoods.map { (name: $0.name, sub: city.short, count: $0.count) }
        case .zip:
            // LA's parcel source carries no neighborhood, so its areas are ZIPs.
            var byZip: [String: Int] = [:]
            for b in buildings { if let z = b.z, !z.isEmpty { byZip[z, default: 0] += 1 } }
            return byZip.map { (name: $0.key, sub: city.short, count: $0.value) }.sorted { $0.name < $1.name }
        }
    }

    /// ETag-conditional fetch of each public file into the cache; redecodes
    /// only when something actually changed. Bounded: one request per file per
    /// launch, and non-NYC cities have only the one file.
    func refresh() async {
        guard !refreshing else { return }
        refreshing = true; defer { refreshing = false }
        let c = city
        var changed = false
        for name in Self.files(for: c) {
            let cacheAs = Self.cacheName(name, in: c)
            if await Self.fetchIfChanged(name, cacheAs: cacheAs) { changed = true }
        }
        // A city fetched for the first time has no payload yet, so decode even
        // when nothing "changed" — otherwise its first launch stays empty.
        guard c == city else { return }   // the user switched away mid-fetch
        if changed || !loaded, let p = try? await Task.detached(priority: .utility, operation: { try Self.decodeLocal(c) }).value {
            guard c == city else { return }
            applyPayload(p)
            loadError = nil
        }
    }

    nonisolated private static func fetchIfChanged(_ name: String, cacheAs: String? = nil) async -> Bool {
        let cacheName = cacheAs ?? name
        let etagKey = "etag.\(cacheName)"
        var req = URLRequest(url: host.appendingPathComponent(name))
        req.timeoutInterval = 20
        // Ask for the raw bytes: the .gz file must land on disk still gzipped
        // (decodeLocal inflates it), and JSON should come back plain.
        req.setValue(name.hasSuffix(".gz") ? "identity" : "gzip", forHTTPHeaderField: "Accept-Encoding")
        if let etag = UserDefaults.standard.string(forKey: etagKey) { req.setValue(etag, forHTTPHeaderField: "If-None-Match") }
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse else { return false }
        if http.statusCode == 304 { return false }
        guard http.statusCode == 200, !data.isEmpty else { return false }
        // Validate before trusting: a truncated body must not replace a good cache.
        if name.hasSuffix(".gz") { guard (try? Gunzip.inflate(data)) != nil else { return false } }
        else { guard (try? JSONSerialization.jsonObject(with: data)) != nil else { return false } }
        let dest = cacheDir.appendingPathComponent(cacheName)
        do { try data.write(to: dest, options: .atomic) } catch { return false }
        if let etag = http.value(forHTTPHeaderField: "ETag") { UserDefaults.standard.set(etag, forKey: etagKey) }
        return true
    }

    /// Attach each listing to its DHCR building when the address matched, or
    /// mint a stand-alone Building for it so it can be a card and a pin.
    private func indexHCR() {
        var by: [String: [HCRListing]] = [:]
        var pool: [Building] = []
        var seen = Set<String>()
        for l in hcr.listings {
            for (i, site) in l.buildings.enumerated() {
                let key: String
                if let bbl = site.bbl, let b = byBBL[bbl] {
                    key = bbl
                    if !seen.contains(bbl) { pool.append(b); seen.insert(bbl) }
                } else if let lat = site.lat, let lng = site.lng {
                    key = HCRListing.syntheticBBL(l.id, i)
                    let b = Building(bbl: key, b: l.boro ?? "", a: (site.street ?? l.name ?? "HCR listing").uppercased(),
                                     z: site.zip, lat: lat, lng: lng,
                                     s: [l.kind?.uppercased() ?? "HCR AFFORDABLE HOUSING"], yr: nil, u: nil, nb: nil, h: nil)
                    byBBL[key] = b
                    pool.append(b); seen.insert(key)
                } else { continue }
                by[key, default: []].append(l)
            }
        }
        hcrByBBL = by
        hcrBuildings = pool
    }

    func hcrListings(_ b: Building) -> [HCRListing] { hcrByBBL[b.bbl] ?? [] }
    func isHCR(_ b: Building) -> Bool { hcrByBBL[b.bbl] != nil }
    /// A stand-alone HCR site, not a DHCR-register building.
    func isSyntheticHCR(_ b: Building) -> Bool { HCRListing.isSynthetic(b.bbl) }

    // MARK: derived per-building facts

    /// The asking rent, but only while the listing counts as recent (posted
    /// on Zumper within the last 5 days). Older banked prices are history,
    /// exposed separately as `lastPrice`.
    func price(_ b: Building) -> Int? { listings.isRecent(b.bbl) ? listings.prices[b.bbl] : nil }
    /// A price we once saw for the building, however old — with when.
    func lastPrice(_ b: Building) -> (Int, Date?)? { listings.prices[b.bbl].map { ($0, listings.postedDate(b.bbl)) } }
    func postedDate(_ b: Building) -> Date? { listings.postedDate(b.bbl) }
    func beds(_ b: Building) -> [Int] { listings.beds[b.bbl] ?? [] }
    func listingURL(_ b: Building) -> URL? { listings.urls[b.bbl].flatMap(URL.init) }
    /// The button that opens a listing says where it goes — "StreetEasy" or
    /// "Zumper" — not "View listing". Anything else falls back to the generic.
    func listingSite(_ b: Building) -> String {
        let host = (listingURL(b)?.host ?? "").lowercased()
        if host.hasSuffix("streeteasy.com") { return "StreetEasy" }
        if host.hasSuffix("zumper.com") { return "Zumper" }
        return "View listing"
    }
    func listingCount(_ b: Building) -> Int { listings.counts[b.bbl] ?? 0 }
    func isAdvertised(_ b: Building) -> Bool { listings.isRecent(b.bbl) }
    /// HUD estimate for the ZIP: [studio, 1BR, 2BR, 3BR]
    func estimate(_ b: Building) -> [Int]? { b.z.flatMap { fmr[$0] } }
    /// One price per building, shared by the price sort and filter: the real
    /// asking rent when advertised, else the ZIP's HUD studio–2BR midpoint.
    func priceOf(_ b: Building) -> Int? {
        if let p = listings.prices[b.bbl] { return p }
        if let f = estimate(b), f.count >= 3 { return (f[0] + f[2]) / 2 }
        // Outside New York there are no listings and no HUD table; SF reports a
        // block median and DC a registered legal rent, and that is the only
        // rent those cities have. Without this a price filter set in New York
        // rejected every building in every other city (2026-09-09).
        return b.mr
    }
    func voucherAvail(_ b: Building) -> S8Blob.Avail? { s8.avail[b.bbl] }
    func voucherBuilding(_ b: Building) -> S8Blob.Bldg? { s8.bldg[b.bbl] }
    func isVoucherFriendly(_ b: Building) -> Bool { s8.avail[b.bbl] != nil || s8.bldg[b.bbl] != nil }
}

extension DataStore {
    /// Unit tests decode the bundle and apply it directly; no refresh.
    func applyForTesting(_ p: Payload) { applyPayload(p) }
}
