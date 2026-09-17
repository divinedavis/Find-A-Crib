import Foundation

/// `featured.json`: income-restricted re-rentals the HPD-approved marketing
/// agents are advertising on their own sites today (featured_rerentals.py,
/// refreshed every morning). They are not on StreetEasy or Zumper and they go
/// in days, which is why they earn a tile in the results feed.
struct FeaturedBlob: Codable, Sendable {
    var generated: String? = nil
    var listings: [FeaturedListing] = []
}

struct FeaturedListing: Codable, Hashable, Identifiable, Sendable {
    var agent: String
    var agentPage: String?
    var title: String?
    var address: String
    var borough: String?
    var zip: String?
    /// "rent" or "income" — THE MONEY IS NOT ALWAYS RENT. MGNY prints the
    /// household income you must earn; printing that as a rent would be the
    /// most misleading thing this tile could do, so the kind travels with it.
    var moneyKind: String?
    var moneyLow: Int?
    var moneyHigh: Int?
    var income1pMax: Int?
    var units: Int?
    /// "studio" or a number of bedrooms; the feed writes either.
    var beds: String?
    var href: String
    /// "listing" (a page for the apartment) or "agent_page" (the agent's
    /// board, when they publish no page per unit).
    var hrefKind: String?
    /// Site-relative, e.g. "/featured/img/abc.png".
    var image: String?

    var id: String { href + "|" + address }

    enum CodingKeys: String, CodingKey {
        case agent, title, address, borough, zip, units, beds, href, image
        case agentPage = "agent_page", moneyKind = "money_kind", moneyLow = "money_low", moneyHigh = "money_high"
        case income1pMax = "income_1p_max", hrefKind = "href_kind"
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        agent = try c.decodeIfPresent(String.self, forKey: .agent) ?? ""
        agentPage = try c.decodeIfPresent(String.self, forKey: .agentPage)
        title = try c.decodeIfPresent(String.self, forKey: .title)
        address = try c.decodeIfPresent(String.self, forKey: .address) ?? ""
        borough = try c.decodeIfPresent(String.self, forKey: .borough)
        zip = try c.decodeIfPresent(String.self, forKey: .zip)
        moneyKind = try c.decodeIfPresent(String.self, forKey: .moneyKind)
        moneyLow = try c.decodeIfPresent(Int.self, forKey: .moneyLow)
        moneyHigh = try c.decodeIfPresent(Int.self, forKey: .moneyHigh)
        income1pMax = try c.decodeIfPresent(Int.self, forKey: .income1pMax)
        units = try c.decodeIfPresent(Int.self, forKey: .units)
        if let s = try? c.decodeIfPresent(String.self, forKey: .beds) { beds = s }
        else if let n = try? c.decodeIfPresent(Int.self, forKey: .beds) { beds = String(n) }
        href = try c.decodeIfPresent(String.self, forKey: .href) ?? ""
        hrefKind = try c.decodeIfPresent(String.self, forKey: .hrefKind)
        image = try c.decodeIfPresent(String.self, forKey: .image)
    }

    init(agent: String, address: String, borough: String?, href: String, moneyKind: String? = nil, moneyLow: Int? = nil, moneyHigh: Int? = nil) {
        self.agent = agent; self.address = address; self.borough = borough; self.href = href
        self.moneyKind = moneyKind; self.moneyLow = moneyLow; self.moneyHigh = moneyHigh
    }

    /// The borough code the search uses ("Bk"), from the name the agent's
    /// page printed. Nil when the card never named one — those are left out
    /// of every feed rather than shown everywhere.
    var boroughCode: String? {
        switch borough {
        case "Manhattan": "M"
        case "Brooklyn": "Bk"
        case "Queens": "Q"
        case "Bronx", "The Bronx": "Bx"
        case "Staten Island": "SI"
        default: nil
        }
    }

    var imageURL: URL? { image.flatMap { URL(string: $0, relativeTo: DataStore.host)?.absoluteURL } }

    /// The money line, with what it IS: "$3,423–$4,376/mo", or the income
    /// ceiling when no rent is published — that answers "can I even apply?".
    var moneyLine: (label: String?, text: String) {
        let n = { (v: Int) in "$" + v.formatted() }
        if moneyKind == "rent", let lo = moneyLow {
            if let hi = moneyHigh, hi != lo { return (nil, "\(n(lo))–\(n(hi))/mo") }
            return (nil, "\(n(lo))/mo")
        }
        if let cap = income1pMax { return ("Income limit · 1 person", "up to \(n(cap))/yr") }
        if moneyKind == "income", let lo = moneyLow, let hi = moneyHigh { return ("Household income", "\(n(lo))–\(n(hi))/yr") }
        return (nil, "Income-restricted · see agent for rent")
    }

    /// The button says where the link goes: "Apply" onto a board of other
    /// people's apartments is a promise the link would not keep.
    var actionTitle: String { hrefKind == "agent_page" ? "Find it on their listings page ↗" : "Apply on their site ↗" }

    /// The hand-off, tagged so the agent can see this traffic in their own
    /// analytics (the same utm the website sets). Never on an internal link,
    /// never over a campaign somebody else set.
    var outboundURL: URL? {
        guard var comps = URLComponents(string: href), let scheme = comps.scheme, ["http", "https"].contains(scheme) else { return nil }
        if comps.host == DataStore.host.host { return comps.url }
        var q = comps.queryItems ?? []
        if q.contains(where: { $0.name == "utm_source" }) { return comps.url }
        q += [.init(name: "utm_source", value: "findacrib.com"), .init(name: "utm_medium", value: "referral"),
              .init(name: "utm_campaign", value: "rerental_tile"),
              .init(name: "utm_content", value: hrefKind == "agent_page" ? "agent_board" : "unit_listing")]
        comps.queryItems = q
        return comps.url
    }
}

/// Where the re-rental tiles go in a results feed. The owner's rule
/// (2026-09-16): the first one is the 3rd tile, then one every 8–15 tiles,
/// never two next to each other, labelled "Rerental".
enum RerentalFeed {
    /// The first re-rental is the tile at this 0-based index (the 3rd tile).
    static let firstSlot = 2
    static let minGap = 8, maxGap = 15

    /// A row of the feed: a building card or a re-rental tile.
    enum Row: Identifiable {
        case building(Building)
        case rerental(FeaturedListing, slot: Int)
        var id: String {
            switch self {
            case .building(let b): "b:\(b.bbl)"
            case .rerental(let f, let slot): "r:\(slot):\(f.id)"
            }
        }
    }

    /// 0-based positions of the re-rental tiles in a feed of `tiles` rows,
    /// from a seed. The same seed always gives the same positions, so paging
    /// the list further down extends the sequence instead of reshuffling it.
    static func slots(tiles: Int, seed: UInt64) -> [Int] {
        var rng = SplitMix(seed: seed)
        var out: [Int] = []
        var pos = firstSlot
        while pos < tiles {
            out.append(pos)
            // `gap` buildings between this tile and the next re-rental.
            let gap = minGap + Int(rng.next() % UInt64(maxGap - minGap + 1))
            pos += gap + 1
        }
        return out
    }

    /// Interleaves the re-rentals into the buildings. `pool` is walked in a
    /// seeded order so one feed shows different apartments and never the same
    /// one twice running; an empty pool leaves the feed as it was.
    static func rows(buildings: [Building], pool: [FeaturedListing], seed: UInt64) -> [Row] {
        guard !pool.isEmpty, !buildings.isEmpty else { return buildings.map { .building($0) } }
        // At least 8 buildings sit between tiles, so the feed is never longer
        // than twice the buildings; that bounds the positions to generate.
        let positions = Set(slots(tiles: buildings.count * 2 + 2, seed: seed))
        var order = pool
        var rng = SplitMix(seed: seed &+ 0x9E37_79B9)
        for i in stride(from: order.count - 1, to: 0, by: -1) { order.swapAt(i, Int(rng.next() % UInt64(i + 1))) }
        var out: [Row] = []
        out.reserveCapacity(buildings.count + buildings.count / RerentalFeed.minGap + 1)
        var bi = 0, ri = 0
        while bi < buildings.count {
            if positions.contains(out.count) {
                out.append(.rerental(order[ri % order.count], slot: ri)); ri += 1
            } else {
                out.append(.building(buildings[bi])); bi += 1
            }
        }
        return out
    }

    /// The pool for a set of results: only apartments in a borough that is
    /// actually in the results — a Bronx re-rental leading a Chelsea search is
    /// noise in the one slot where noise is least forgivable.
    static func pool(_ featured: [FeaturedListing], for buildings: [Building]) -> [FeaturedListing] {
        var codes = Set<String>()
        for b in buildings { codes.insert(b.b); if codes.count >= 5 { break } }
        return featured.filter { $0.boroughCode.map(codes.contains) ?? false }
    }

    /// One seed per launch: the feed is stable while you scroll and page, and
    /// different the next time the app opens.
    static let launchSeed: UInt64 = .random(in: 1...UInt64.max)

    struct SplitMix {
        var state: UInt64
        init(seed: UInt64) { state = seed }
        mutating func next() -> UInt64 {
            state &+= 0x9E37_79B9_7F4A_7C15
            var z = state
            z = (z ^ (z >> 30)) &* 0xBF58_476D_1CE4_E5B9
            z = (z ^ (z >> 27)) &* 0x94D0_49BB_1331_11EB
            return z ^ (z >> 31)
        }
    }
}
