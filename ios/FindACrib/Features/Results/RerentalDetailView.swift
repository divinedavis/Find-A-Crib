import SwiftUI

/// A re-rental's own page inside the app (owner, 2026-11-18: "can we allow
/// users to click on rerentals and get more info about them while on the
/// app?"; picked mock #1 "Photo page" 2026-11-19). Tapping a re-rental card's
/// photo or address opens it; the agent's site stays one tap away in the
/// floating bar.
///
/// Top to bottom: the photo set (swipe, "1 / 8" counter) fading into the
/// page, round glass back / share buttons over it; the building name and
/// address; chips (first come first served, bedrooms, how many left, apply-by
/// date); rent and the income you must earn; your verdict; who can apply
/// (household size → income band, from the listing's own table); the move-in
/// deal and how to apply when the listing says. Every number comes from
/// featured.json or featured_units.json; nothing is shown that the agent's
/// listing didn't print.
struct RerentalDetailView: View {
    let listing: FeaturedListing
    @Environment(AppNav.self) private var nav
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var photo = 0
    @State private var showPacket = false
    private var qualify: Qualify { Qualify.shared }
    private var table: Qualify.Table? { qualify.units[listing.href] }
    private var rows: [Qualify.Row] { table?.units ?? [] }

    static let heroHeight: CGFloat = 340

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                hero
                VStack(alignment: .leading, spacing: 0) {
                    heading
                    chips.padding(.top, 12)
                    tiles.padding(.top, 16)
                    if let v = qualify.verdict(for: listing), v != .unknown { verdictCard(v).padding(.top, 10) }
                    ForEach(table?.flags ?? [], id: \.code) { fl in
                        Label("Check carefully: \(fl.why)", systemImage: "exclamationmark.triangle.fill")
                            .font(.se(15, .semibold)).foregroundStyle(SE.warn).padding(.top, 10)
                    }
                    if !whoCanApply.isEmpty { whoCanApplySection.padding(.top, 22) }
                    if let deal = listing.deal { section("Move-in deal") { DealBox(listing: listing, deal: deal) }.padding(.top, 22) }
                    if let how = table?.how_to_apply, !how.isEmpty { howToApply(how).padding(.top, 22) }
                    if auth.hasPlus { helpMeApply.padding(.top, 14) }
                    Text("From \(listing.agent)'s listing. Check the details with them before you apply.")
                        .font(.se(13)).foregroundStyle(SE.ink3).padding(.top, 18)
                }
                .padding(.horizontal, 18)
                .padding(.top, -28)
                Color.clear.frame(height: 130)
            }
        }
        .ignoresSafeArea(edges: .top)
        .background(SE.canvas)
        .overlay(alignment: .top) { topButtons }
        .overlay(alignment: .bottom) { applyBar }
        .toolbar(.hidden, for: .navigationBar)
        .sheet(isPresented: $showPacket) { PacketView(listing: listing) }
        .task { await qualify.loadUnits() }
        .onAppear {
            nav.hideTabBar = true
            var p = Analytics.tileProps(listing, slot: -1); p["photos"] = listing.imageURLs.count
            Analytics.shared.track("rerental_page_view", p)
        }
        .onDisappear { nav.hideTabBar = false }
        // A container, so the page's id doesn't overwrite its buttons' ids.
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("rerental-page")
    }

    // MARK: Photo

    private var hero: some View {
        let urls = listing.imageURLs
        return Color.clear
            .overlay {
                ZStack {
                    ImagePlaceholder()
                    if urls.count > 1 {
                        TabView(selection: $photo) {
                            ForEach(Array(urls.enumerated()), id: \.offset) { i, u in RemoteImage(url: u).tag(i) }
                        }
                        .tabViewStyle(.page(indexDisplayMode: .never))
                        .task(id: urls) { RemotePhotos.shared.prefetch(urls) }
                    } else if let u = urls.first {
                        RemoteImage(url: u)
                    } else if let lat = listing.lat, let lng = listing.lng {
                        BuildingImage(building: Building(bbl: "rr-" + listing.address.filter { $0.isLetter || $0.isNumber }, b: "", a: "", z: nil, lat: lat, lng: lng))
                    }
                }
            }
            .frame(height: Self.heroHeight).frame(maxWidth: .infinity).clipped()
            // The photo fades into the page, as the mock does.
            .overlay(alignment: .bottom) {
                LinearGradient(colors: [SE.canvas.opacity(0), SE.canvas], startPoint: .top, endPoint: .bottom)
                    .frame(height: 90).allowsHitTesting(false)
            }
            .overlay(alignment: .bottomTrailing) {
                if urls.count > 1 {
                    Text("\(photo + 1) / \(urls.count)").font(.se(13, .semibold)).foregroundStyle(SE.ink)
                        .padding(.horizontal, 10).padding(.vertical, 5)
                        .lightGlass(in: Capsule())
                        .padding(.trailing, 16).padding(.bottom, 60)
                        .accessibilityHidden(true)
                }
            }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(urls.count > 1 ? String(localized: "Photo \(photo + 1) of \(urls.count)") : String(localized: "Photo of the building"))
            .accessibilityAdjustableAction { dir in
                guard urls.count > 1 else { return }
                photo = dir == .increment ? min(photo + 1, urls.count - 1) : max(photo - 1, 0)
            }
            .accessibilityIdentifier("rerental-page-photos")
    }

    private var topButtons: some View {
        HStack {
            glassButton("chevron.left", label: String(localized: "Back"), id: "rerental-page-back") { dismiss() }
            Spacer()
            if let url = URL(string: listing.href) {
                ShareLink(item: url) { glassIcon("square.and.arrow.up") }
                    .accessibilityLabel(Text("Share"))
                    .accessibilityIdentifier("rerental-page-share")
            }
        }
        .padding(.horizontal, 16)
        .padding(.top, 4)
    }

    private func glassIcon(_ name: String) -> some View {
        Image(systemName: name).font(.system(size: 17, weight: .semibold)).foregroundStyle(SE.ink)
            .frame(width: 44, height: 44).lightGlass(in: Circle()).contentShape(Circle())
    }

    private func glassButton(_ name: String, label: String, id: String, action: @escaping () -> Void) -> some View {
        Button(action: action) { glassIcon(name) }
            .buttonStyle(.plain).accessibilityLabel(Text(label)).accessibilityIdentifier(id)
    }

    // MARK: Heading, chips, tiles

    private var kicker: String? {
        let f = listing
        let named = (f.title?.isEmpty == false) && !f.address.lowercased().hasPrefix(f.title!.lowercased())
        let parts = [named ? f.title : nil, f.borough].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// "1100 Myrtle Avenue" big, the city and ZIP left to the kicker's line.
    private var street: String {
        listing.address.components(separatedBy: ",").first?.trimmingCharacters(in: .whitespaces) ?? listing.address
    }

    private var heading: some View {
        VStack(alignment: .leading, spacing: 4) {
            if let kicker { Text(kicker).font(.se(15, .semibold)).foregroundStyle(SE.ink3) }
            Text(street).font(.se(30, .bold)).foregroundStyle(SE.ink).lineLimit(3).minimumScaleFactor(0.75)
                .accessibilityAddTraits(.isHeader)
                .accessibilityIdentifier("rerental-page-address")
            if street != listing.address {
                Text(listing.address).font(.se(14)).foregroundStyle(SE.ink3).lineLimit(1).minimumScaleFactor(0.8)
            }
        }
    }

    private var bedsText: String? {
        let beds = qualify.bedrooms(listing).sorted()
        guard let lo = beds.first, let hi = beds.last else { return nil }
        let name = { (n: Int) in n == 0 ? String(localized: "Studio") : String(localized: "\(n) bed") }
        return lo == hi ? name(lo) : (lo == 0 ? String(localized: "Studio–\(hi) bed") : String(localized: "\(lo)–\(hi) bed"))
    }

    /// Apartments open. A table repeats one apartment per household size
    /// (The MC: one 1-bed listed for 1, 2 and 3 people), so rows with the
    /// same bedrooms and rent are one apartment group: its largest count.
    private var unitsLeft: Int? { Self.unitsLeft(rows) ?? listing.units }

    static func unitsLeft(_ rows: [Qualify.Row]) -> Int? {
        var groups: [String: Int] = [:]
        for r in rows {
            guard let n = r.units_available else { continue }
            let key = "\(r.beds ?? -1)|\(r.rent ?? -1)"
            groups[key] = max(groups[key] ?? 0, n)
        }
        return groups.isEmpty ? nil : groups.values.reduce(0, +)
    }

    private var chips: some View {
        RerentalChipFlow {
            if table?.first_come_first_served == true {
                chip(String(localized: "First come, first served"), icon: "bolt", tint: SE.warn, fill: Color(hex: 0xFFF0E0))
                    .accessibilityIdentifier("rerental-page-fcfs")
            }
            if let b = bedsText { chip(b, icon: "bed.double", tint: SE.ink2, fill: Color(.tertiarySystemFill)) }
            if let n = unitsLeft, n > 0 { chip(String(localized: "\(n) left"), icon: nil, tint: SE.ink2, fill: Color(.tertiarySystemFill)) }
            if let d = table?.deadline { chip(String(localized: "Apply by \(d)"), icon: "calendar", tint: SE.warn, fill: Color(hex: 0xFFF0E0)) }
        }
    }

    private func chip(_ text: String, icon: String?, tint: Color, fill: Color) -> some View {
        HStack(spacing: 5) {
            if let icon { Image(systemName: icon).font(.system(size: 12, weight: .semibold)) }
            Text(text).font(.se(14, .semibold)).lineLimit(1)
        }
        .foregroundStyle(tint).padding(.horizontal, 11).padding(.vertical, 7)
        .background(fill, in: Capsule())
    }

    /// The rent the feed carries, else the cheapest row of the unit table.
    private var rentText: String? {
        let n = { (v: Int) in "$" + v.formatted() }
        if listing.moneyKind == "rent", let lo = listing.moneyLow {
            if let hi = listing.moneyHigh, hi != lo { return "\(n(lo))–\(n(hi))" }
            return n(lo)
        }
        let rents = rows.compactMap(\.rent)
        guard let lo = rents.min(), let hi = rents.max() else { return nil }
        return lo == hi ? n(lo) : "\(n(lo))–\(n(hi))"
    }

    /// What a household must earn: "$104k+" from the lowest minimum, else
    /// "Up to $154k" from the ceiling.
    private var earnText: String? {
        let k = { (v: Int) in "$\(Int((Double(v) / 1000).rounded()))k" }
        if let r = Qualify.incomeRange(rows: rows) {
            if let lo = r.low { return k(lo) + "+" }
            if let hi = r.high { return String(localized: "Up to \(k(hi))") }
        }
        if listing.moneyKind == "income", let lo = listing.moneyLow { return k(lo) + "+" }
        if let hi = listing.income1pMax { return String(localized: "Up to \(k(hi))") }
        return nil
    }

    @ViewBuilder private var tiles: some View {
        let rent = rentText, earn = earnText
        if rent != nil || earn != nil {
            HStack(spacing: 10) {
                if let rent { tile(String(localized: "Rent"), rent, unit: String(localized: "/mo")).accessibilityIdentifier("rerental-page-rent") }
                if let earn { tile(String(localized: "You must earn"), earn, unit: String(localized: "/yr")).accessibilityIdentifier("rerental-page-earn") }
            }
        }
    }

    private func tile(_ label: String, _ value: String, unit: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(label).font(.se(13, .semibold)).foregroundStyle(SE.ink3).textCase(.uppercase).kerning(0.5)
            (Text(value).font(.se(25, .bold)).foregroundStyle(SE.ink)
             + Text(unit).font(.se(14, .semibold)).foregroundStyle(SE.ink3))
                .lineLimit(1).minimumScaleFactor(0.6)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 14).padding(.vertical, 13)
        .background(Color.white, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .accessibilityElement(children: .combine)
    }

    // MARK: Verdict

    private func verdictCard(_ v: Qualify.Verdict) -> some View {
        let good = v == .yes
        return HStack(spacing: 12) {
            Image(systemName: good ? "checkmark" : "exclamationmark")
                .font(.system(size: 16, weight: .bold)).foregroundStyle(.white)
                .frame(width: 32, height: 32).background(good ? SE.good : SE.warn, in: Circle())
            VStack(alignment: .leading, spacing: 2) {
                Text(Qualify.words(v)).font(.se(17, .bold)).foregroundStyle(good ? SE.good : SE.warn)
                if let why = verdictReason(v) { Text(why).font(.se(14)).foregroundStyle(SE.ink2) }
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 14).padding(.vertical, 13)
        .background(Color.white, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("rerental-page-verdict")
    }

    private func verdictReason(_ v: Qualify.Verdict) -> String? {
        guard let hh = qualify.household, let inc = qualify.income else { return nil }
        let n = "$" + inc.formatted()
        let who = hh == 1 ? String(localized: "1-person") : String(localized: "\(hh)-person")
        switch v {
        case .yes: return String(localized: "\(n) is inside the \(who) limit")
        case .high: return String(localized: "\(n) is above the \(who) limit")
        case .low: return String(localized: "\(n) is below the minimum")
        case .unknown: return nil
        }
    }

    // MARK: Who can apply

    struct Band: Hashable { let who: String; let income: String; let detail: String? }

    /// One line per household size the table names, with its income band;
    /// the bedrooms and rent ride along when the table mixes sizes.
    private var whoCanApply: [Band] {
        let n = { (v: Int) in "$" + v.formatted() }
        let mixed = Set(rows.compactMap(\.beds)).count > 1 || Set(rows.compactMap(\.rent)).count > 1
        var out: [Band] = []
        for r in rows.sorted(by: { ($0.beds ?? 0, $0.household_size_min ?? 0) < ($1.beds ?? 0, $1.household_size_min ?? 0) }) {
            guard r.income_min != nil || r.income_max != nil else { continue }
            let lo = r.household_size_min, hi = r.household_size_max
            let who: String = switch (lo, hi) {
            case let (l?, h?) where l == h: l == 1 ? String(localized: "1 person") : String(localized: "\(l) people")
            case let (l?, h?): String(localized: "\(l)–\(h) people")
            case let (l?, nil): String(localized: "\(l)+ people")
            case let (nil, h?): String(localized: "Up to \(h) people")
            default: String(localized: "Any household")
            }
            let income: String = switch (r.income_min, r.income_max) {
            case let (l?, h?): "\(n(l)) – \(n(h))"
            case let (l?, nil): String(localized: "from \(n(l))")
            case let (nil, h?): String(localized: "up to \(n(h))")
            default: ""
            }
            var detail: String? = nil
            if mixed {
                let bed = r.beds.map { $0 == 0 ? String(localized: "Studio") : String(localized: "\($0) bed") }
                detail = [bed, r.rent.map { "$" + $0.formatted() + String(localized: "/mo") }].compactMap { $0 }.joined(separator: " · ")
            }
            let b = Band(who: who, income: income, detail: detail)
            if !out.contains(b) { out.append(b) }
        }
        return out
    }

    private var whoCanApplySection: some View {
        section("Who can apply") {
            VStack(spacing: 0) {
                ForEach(Array(whoCanApply.enumerated()), id: \.offset) { i, b in
                    if i > 0 { Divider() }
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(b.who).font(.se(16)).foregroundStyle(SE.ink)
                            if let d = b.detail { Text(d).font(.se(13)).foregroundStyle(SE.ink3) }
                        }
                        Spacer(minLength: 8)
                        Text(b.income).font(.se(16, .semibold)).foregroundStyle(SE.ink).lineLimit(1).minimumScaleFactor(0.8)
                    }
                    .padding(.vertical, 12)
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(.horizontal, 16)
            .background(Color.white, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
            .accessibilityIdentifier("rerental-page-who")
        }
    }

    private func howToApply(_ text: String) -> some View {
        section("How to apply") {
            Text(text).font(.se(16)).foregroundStyle(SE.ink).fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
                .background(Color.white, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
                .textSelection(.enabled)
                .accessibilityIdentifier("rerental-page-how")
        }
    }

    private var helpMeApply: some View {
        Button {
            Analytics.shared.track("rerental_card_action", ["action": "apply_help", "signed_in": auth.isSignedIn, "src": "page"])
            showPacket = true
        } label: {
            Label("Help me apply", systemImage: "doc.badge.plus").font(.se(17, .bold)).foregroundStyle(SE.royal)
                .frame(maxWidth: .infinity).frame(height: 50)
                .background(Color.white, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("rerental-page-apply-help")
    }

    private func section<C: View>(_ title: LocalizedStringKey, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.se(13, .semibold)).foregroundStyle(SE.ink3).textCase(.uppercase).kerning(0.5).padding(.leading, 4)
                .accessibilityAddTraits(.isHeader)
            content()
        }
    }

    // MARK: Floating Apply bar

    private var applyTitle: String {
        switch listing.hrefKind {
        case "agent_page": String(localized: "Their listings")
        case "flyer": String(localized: "The listing")
        default: String(localized: "Apply")
        }
    }

    private var applyBar: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                if let rent = rentText {
                    (Text(rent).font(.se(19, .bold)).foregroundStyle(SE.ink)
                     + Text("/mo").font(.se(13, .semibold)).foregroundStyle(SE.ink3))
                        .lineLimit(1).minimumScaleFactor(0.7)
                }
                Text(listing.agent).font(.se(13)).foregroundStyle(SE.ink2).lineLimit(1)
            }
            Spacer(minLength: 8)
            if let out = listing.outboundURL {
                Button {
                    var p = Analytics.tileProps(listing, slot: -1); p["href"] = out.absoluteString; p["src"] = "page"
                    Analytics.shared.track("featured_click", p)
                    Analytics.shared.track("outbound", ["kind": "rerental", "agent": listing.agent, "href": out.absoluteString])
                    openURL(out)
                } label: {
                    HStack(spacing: 6) {
                        Text(applyTitle).font(.se(18, .bold))
                        Image(systemName: "arrow.up.right").font(.system(size: 14, weight: .bold))
                    }
                    .foregroundStyle(.white).padding(.horizontal, 22).frame(height: 50)
                    .background(SE.royal, in: Capsule())
                    .contentShape(Capsule())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("rerental-page-apply")
            }
        }
        .padding(.leading, 18).padding(.trailing, 8).padding(.vertical, 8)
        .lightGlass(in: RoundedRectangle(cornerRadius: 30, style: .continuous))
        .contentShape(RoundedRectangle(cornerRadius: 30, style: .continuous))
        .padding(.horizontal, 12).padding(.bottom, 6)
    }
}

/// Chips that wrap onto a second line when they don't fit one.
private struct RerentalChipFlow<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View { ChipFlowLayout(spacing: 7) { content } }
}

private struct ChipFlowLayout: Layout {
    var spacing: CGFloat
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, line: CGFloat = 0, widest: CGFloat = 0
        for s in subviews {
            let z = s.sizeThatFits(.unspecified)
            if x > 0 && x + z.width > width { y += line + spacing; x = 0; line = 0 }
            x += z.width + spacing; line = max(line, z.height); widest = max(widest, x - spacing)
        }
        return CGSize(width: min(widest, width), height: subviews.isEmpty ? 0 : y + line)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, line: CGFloat = 0
        for s in subviews {
            let z = s.sizeThatFits(.unspecified)
            if x > bounds.minX && x + z.width > bounds.maxX { y += line + spacing; x = bounds.minX; line = 0 }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(z))
            x += z.width + spacing; line = max(line, z.height)
        }
    }
}
