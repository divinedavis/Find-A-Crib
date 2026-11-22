import SwiftUI

/// A re-rental tile in the results feed: a real income-restricted apartment
/// an HPD-approved marketing agent is advertising today, laid out like the
/// building card so it reads as part of the feed, flagged "Rerental" so it
/// never passes for a register building.
struct RerentalCard: View {
    let listing: FeaturedListing
    /// Which re-rental slot of the feed this is (0 = the 3rd tile), for the funnel.
    var slot: Int = 0
    /// The Rerental / Income-restricted / Move-in deal labels on the photo.
    /// Off on the Lotteries tab, where every card is one (owner, 2026-11-07:
    /// "remove the move in deal, rerental, and income restricted labels from
    /// the previews on the lotteries"); on in the Search feed, where the
    /// Rerental flag keeps a listing from passing for a register building.
    var photoLabels = true
    /// Set like a Housing Connect lottery card: the same type sizes, colours,
    /// photo height, edge-to-edge white card and rounded Apply button. On for
    /// the Lotteries tab's Re-rentals pane, so its cards match the NYC pane
    /// beside it (owner, 2026-11-20: "the rerental cards should have same
    /// font size, etc as nyc housing lottery cards"). The Search feed keeps
    /// the building card's layout.
    var lotteryStyle = false
    @Environment(\.openURL) private var openURL
    @Environment(AuthService.self) private var auth
    @Environment(AppNav.self) private var nav
    @State private var photo = 0
    @State private var showAlerts = false
    @State private var showSignIn = false
    @State private var sheet: CardAction?
    private var feed: LotteryFeed { LotteryFeed.shared }

    /// The one button under Share / Apply (owner, 2026-11-06): Plus gets
    /// Help me apply; free gets alerts, or real-time alerts once they have
    /// alerts. Was Broker fee check / Lease review for Plus (10/29).
    enum CardAction: String, Identifiable {
        case alerts, realtime, applyHelp = "apply_help"
        var id: String { rawValue }
        var icon: String {
            switch self {
            case .alerts: "bell.badge.fill"
            case .realtime: "bolt.fill"
            case .applyHelp: "doc.badge.plus"
            }
        }
        var title: String {
            switch self {
            case .alerts: String(localized: "Get alerts on new re-rentals")
            case .realtime: String(localized: "Get real-time alerts")
            case .applyHelp: String(localized: "Help me apply")
            }
        }
    }

    private var cardAction: CardAction {
        // subscribed is false whenever signed out (LotteryFeed.refresh).
        Self.action(covered: feed.alertsCover(rerentalIn: listing.boroughCode), plus: auth.hasPlus)
    }

    static func action(covered: Bool, plus: Bool) -> CardAction {
        if plus { return .applyHelp }
        return covered ? .realtime : .alerts
    }

    var body: some View {
        let f = listing
        VStack(alignment: .leading, spacing: 0) {
            ZStack(alignment: .topLeading) {
                // Overlay on a clear colour, like FillImage: a bare scaledToFill
                // reports a size wider than its proposal and pushed the whole
                // card past the screen edge (badge and all) on the first build.
                Color.clear
                    .overlay {
                        ZStack {
                            ImagePlaceholder()
                            let urls = f.imageURLs
                            if urls.count > 1 {
                                // Swipe through the building's photos (owner,
                                // 2026-10-04); page dots show where you are.
                                TabView(selection: $photo) {
                                    ForEach(Array(urls.enumerated()), id: \.offset) { i, url in
                                        RemoteImage(url: url).tag(i)
                                    }
                                }
                                .tabViewStyle(.page(indexDisplayMode: .always))
                                // The other photos load with the card, so a
                                // swipe finds them ready (2026-11-18).
                                .task(id: urls) { RemotePhotos.shared.prefetch(Array(urls.dropFirst())) }
                                .onChange(of: photo) { _, i in
                                    if i == 1 { Analytics.shared.track("rerental_photos_swipe", ["agent": f.agent, "photos": urls.count]) }
                                }
                            } else if let url = urls.first {
                                RemoteImage(url: url)
                            } else if let lat = f.lat, let lng = f.lng {
                                // No photo from the agent (58 of 125 on
                                // 2026-11-07): the street at the address, as
                                // the Housing Connect lottery cards show.
                                BuildingImage(building: Building(bbl: "rr-" + f.address.filter { $0.isLetter || $0.isNumber }, b: "", a: "", z: nil, lat: lat, lng: lng))
                            }
                        }
                    }
                    .frame(height: lotteryStyle ? 190 : compact ? 140 : 226).frame(maxWidth: .infinity).clipped().contentShape(Rectangle())
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(f.imageURLs.count > 1 ? String(localized: "Photo \(photo + 1) of \(f.imageURLs.count)") : String(localized: "Photo of the building"))
                    .accessibilityAdjustableAction { dir in
                        let n = f.imageURLs.count
                        guard n > 1 else { return }
                        photo = dir == .increment ? min(photo + 1, n - 1) : max(photo - 1, 0)
                    }
                    .accessibilityIdentifier("rerental-photos")
                    // The photo opens the re-rental's own page (2026-11-19).
                    .onTapGesture { open("photo") }
                    .accessibilityAction(named: Text("Open details")) { open("photo") }
                if photoLabels {
                    SEBadge(text: String(localized: "Rerental"), icon: "key.fill", fill: SE.navy, ink: .white)
                        .padding(12)
                        .accessibilityIdentifier("badge-rerental")
                    SEBadge(text: String(localized: "Income-restricted"), fill: SE.surface, ink: SE.ink)
                        .frame(maxWidth: .infinity, alignment: .topTrailing)
                        .padding(12)
                }
                if photoLabels, f.deal != nil {
                    Label("Move-in deal", systemImage: "gift.fill")
                        .font(.se(14, .bold)).foregroundStyle(.white)
                        .padding(.horizontal, 11).padding(.vertical, 6).background(SE.good)
                        .shadow(color: .black.opacity(0.3), radius: 5, y: 2)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .bottomLeading)
                        .padding(.bottom, 26)
                        .allowsHitTesting(false)
                        .accessibilityIdentifier("deal-ribbon")
                }
            }

            if lotteryStyle { lotteryInfo } else {
            // The building card's spacing (owner, 2026-10-20): one 8pt gap for
            // every row and button, the borough / address / price block 30%
            // tighter.
            VStack(alignment: .leading, spacing: compact ? 6 : BuildingCard.rowGap) {
                VStack(alignment: .leading, spacing: compact ? 3 : BuildingCard.headGap) {
                    if let kicker { Text(kicker).font(.se(compact ? 14 : 18, .semibold)).foregroundStyle(SE.ink2).lineLimit(1).minimumScaleFactor(0.85) }
                    Text(f.address).font(.se(compact ? 21 : 27, .bold)).foregroundStyle(SE.royalInk).lineLimit(3).minimumScaleFactor(0.8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .accessibilityIdentifier("card-address")
                        .contentShape(Rectangle())
                        .onTapGesture { open("address") }
                        .accessibilityAddTraits(.isButton)
                        .accessibilityHint(Text("Opens the details"))

                    // Every card in the MGNY format (owner, 2026-10-22): the
                    // labelled household income first, from the feed when the
                    // agent prints only income, else from the listing's unit
                    // table; then rent under its own label.
                    let money = f.moneyLine
                    let feedIncome = f.moneyKind == "income" || f.income1pMax != nil
                    // With a deal the two sit side by side, so the card fits one screen.
                    let pair = compact ? AnyLayout(HStackLayout(alignment: .top, spacing: 16)) : AnyLayout(VStackLayout(alignment: .leading, spacing: BuildingCard.headGap))
                    pair {
                        if !feedIncome, let income = Qualify.shared.incomeLine(for: f) {
                            moneyBlock(label: String(localized: "Household income"), text: income)
                                .accessibilityIdentifier("rerental-income")
                        }
                        if let money { moneyBlock(label: money.label, text: money.text) }
                    }
                }

                if let deal = f.deal { DealBox(listing: f, deal: deal) }

                if !bits.isEmpty { Text(bits.joined(separator: " · ")).font(.se(compact ? 14 : 18)).foregroundStyle(SE.ink2).lineLimit(1) }

                if let v = Qualify.shared.verdict(for: f) { QualifyBadge(verdict: v) }
                if let t = Qualify.shared.units[f.href] {
                    if let d = t.deadline { Text("Apply by \(d)").font(.se(15, .semibold)).foregroundStyle(SE.ink2) }
                    ForEach(t.flags ?? [], id: \.code) { fl in
                        Label("Check carefully: \(fl.why)", systemImage: "exclamationmark.triangle.fill").font(.se(14, .semibold)).foregroundStyle(SE.warnInk)
                    }
                }
                // A deal box's header names the agent already (owner, 2026-10-27).
                if f.deal == nil {
                    (Text("Listed by ").font(.se(18)) + Text(f.agent).font(.se(18, .bold)))
                        .foregroundStyle(SE.ink2)
                }

                HStack(spacing: 14) {
                    if let url = URL(string: f.href) {
                        ShareLink(item: url) {
                            HStack(spacing: 8) {
                                Image(systemName: "square.and.arrow.up").font(.system(size: 15, weight: .semibold))
                                Text("Share").font(.se(compact ? 15 : 18, .bold))
                            }
                            .foregroundStyle(SE.royalInk).frame(maxWidth: .infinity).frame(height: compact ? 40 : 50)
                            .background(SE.surface).overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line))
                        }
                        .frame(maxWidth: .infinity)
                    }
                    if let out = f.outboundURL {
                        Button { handOff(out) } label: {
                            Text(f.actionTitle).font(.se(compact ? 15 : 18, .bold)).foregroundStyle(.white).lineLimit(1).minimumScaleFactor(0.7)
                                .padding(.horizontal, 8).frame(maxWidth: .infinity).frame(height: compact ? 40 : 50).background(SE.royal)
                        }
                        .buttonStyle(.plain)
                        .frame(maxWidth: 1000)
                        .accessibilityIdentifier("rerental-apply")
                    }
                }
                .frame(maxWidth: .infinity)
                // Help me apply for Plus (owner, 2026-11-06); alerts for the
                // next re-rental in this borough, signed in first; real-time
                // alerts for someone who already gets them (10/29).
                if case let action = cardAction {
                    actionSheets(Button { run(action) } label: {
                        HStack(spacing: 8) {
                            Image(systemName: action.icon).font(.system(size: 15, weight: .bold))
                            Text(action.title).font(.se(compact ? 15 : 17, .bold)).lineLimit(1).minimumScaleFactor(0.8)
                        }.foregroundStyle(SE.royalInk).frame(maxWidth: .infinity).frame(height: compact ? 36 : 44)
                            .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line))
                    }
                    .buttonStyle(.plain).accessibilityIdentifier("rerental-\(action.id)"))
                }
            }
            .padding(compact ? 14 : 18)
            }
        }
        .background(SE.surface)
        .clipShape(RoundedRectangle(cornerRadius: lotteryStyle ? 0 : 22, style: .continuous))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("rerental-card")
        .onAppear { Analytics.shared.tileSeen(f, slot: slot) }
        .task { await Qualify.shared.loadUnits() }
    }

    /// The card under the photo, line for line a Housing Connect lottery
    /// card (LotteriesView.card): name 19 bold, where 15 semibold, rent 16,
    /// income 15 beside the qualify badge, the rounded Apply button, then
    /// the centred links.
    @ViewBuilder private var lotteryInfo: some View {
        let f = listing
        let table = Qualify.shared.units[f.href]
        VStack(alignment: .leading, spacing: 6) {
            Text(f.address).font(.se(19, .bold)).foregroundStyle(SE.ink)
                .frame(maxWidth: .infinity, alignment: .leading)
                .accessibilityIdentifier("card-address")
                .contentShape(Rectangle())
                .onTapGesture { open("address") }
                .accessibilityAddTraits(.isButton)
                .accessibilityHint(Text("Opens the details"))
            let place = [kicker, table?.deadline.map { String(localized: "Apply by \($0)") }].compactMap { $0 }
            if !place.isEmpty { Text(place.joined(separator: " · ")).font(.se(15, .semibold)).foregroundStyle(SE.ink2) }
            if let rent = lotteryRent { Text(rent).font(.se(16)).foregroundStyle(SE.ink) }
            let verdict = Qualify.shared.verdict(for: f)
            if lotteryIncome != nil || verdict != nil {
                HStack(spacing: 8) {
                    if let income = lotteryIncome {
                        Text(income).font(.se(15)).foregroundStyle(SE.ink2).lineLimit(1).minimumScaleFactor(0.8)
                            .accessibilityIdentifier("rerental-income")
                    }
                    if let verdict { QualifyBadge(verdict: verdict) }
                }
            }
            ForEach(table?.flags ?? [], id: \.code) { fl in
                Label("Check carefully: \(fl.why)", systemImage: "exclamationmark.triangle.fill").font(.se(14, .semibold)).foregroundStyle(SE.warnInk)
            }
            if let deal = f.deal { DealBox(listing: f, deal: deal).padding(.top, 2) } else {
                (Text("Listed by ").font(.se(15)) + Text(f.agent).font(.se(15, .bold))).foregroundStyle(SE.ink2)
            }
            if let out = f.outboundURL {
                // The arrow is the button's icon here, as on Apply on Housing Connect.
                SEPrimaryButton(title: f.actionTitle.replacingOccurrences(of: " ↗", with: ""), icon: "arrow.up.right") { handOff(out) }
                    .padding(.top, 6)
                    .accessibilityIdentifier("rerental-apply")
            }
            // Centred under Apply, where a lottery has Add deadline to Calendar.
            HStack(spacing: 24) {
                if let url = URL(string: f.href) {
                    ShareLink(item: url) {
                        Label("Share", systemImage: "square.and.arrow.up").font(.se(16, .semibold)).frame(minHeight: 44).contentShape(Rectangle())
                    }
                }
                if case let action = cardAction {
                    actionSheets(Button { run(action) } label: {
                        Label(action.title, systemImage: action.icon).font(.se(16, .semibold)).lineLimit(1).minimumScaleFactor(0.8)
                            .frame(minHeight: 44).contentShape(Rectangle())
                    }
                    .accessibilityIdentifier("rerental-\(action.id)"))
                }
            }
            .foregroundStyle(SE.royalInk).frame(maxWidth: .infinity).padding(.top, 4)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading)
    }

    /// "$3,661/mo · 1-bed", the lottery card's rent line.
    private var lotteryRent: String? {
        let rent = listing.moneyKind == "rent" ? listing.moneyLine?.text : nil
        let parts = [rent].compactMap { $0 } + bits
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    /// "Income $131k–$198k", in the lottery card's short thousands: the
    /// agent's own figure when the feed carries one, else the range across
    /// the listing's unit table. The re-rental's page has it to the dollar.
    private var lotteryIncome: String? {
        let f = listing
        let k = { (n: Int) in n >= 1000 ? "$\(n / 1000)k" : "$\(n)" }
        if let cap = f.income1pMax { return String(localized: "Income up to \(k(cap)) · 1 person") }
        if f.moneyKind == "income", let lo = f.moneyLow, let hi = f.moneyHigh { return String(localized: "Income \(k(lo))–\(k(hi))") }
        guard let rows = Qualify.shared.units[f.href]?.units, let r = Qualify.incomeRange(rows: rows) else { return nil }
        switch (r.low, r.high) {
        case let (lo?, hi?) where lo != hi: return String(localized: "Income \(k(lo))–\(k(hi))")
        case let (lo?, nil): return String(localized: "Income from \(k(lo))")
        case let (lo?, _): return String(localized: "Income \(k(lo))")
        case let (nil, hi?): return String(localized: "Income up to \(k(hi))")
        default: return nil
        }
    }

    /// Both rows the site writes for a hand-off: the funnel's click and the
    /// generic outbound.
    private func handOff(_ out: URL) {
        var p = Analytics.tileProps(listing, slot: slot); p["href"] = out.absoluteString
        Analytics.shared.track("featured_click", p)
        Analytics.shared.track("outbound", ["kind": "rerental", "agent": listing.agent, "href": out.absoluteString])
        openURL(out)
    }

    /// Help me apply for Plus (owner, 2026-11-06); alerts for the next
    /// re-rental in this borough, signed in first; real-time alerts for
    /// someone who already gets them (10/29).
    private func run(_ action: CardAction) {
        Analytics.shared.track("rerental_card_action", ["action": action.id, "signed_in": auth.isSignedIn])
        switch action {
        case .alerts: if auth.isSignedIn { showAlerts = true } else { showSignIn = true }
        case .realtime: sheet = .realtime
        case .applyHelp: sheet = .applyHelp
        }
    }

    /// The sheets the action button opens, on whichever layout draws it.
    private func actionSheets(_ button: some View) -> some View {
        button
            // Saved: re-read the prefs, so this card stops offering alerts.
            .sheet(isPresented: $showAlerts, onDismiss: { Task { await feed.refresh() } }) { AlertsSheet(rerentalBorough: listing.boroughCode) }
            .sheet(isPresented: $showSignIn, onDismiss: { if auth.isSignedIn { showAlerts = true } }) {
                EmailSignInView(offersSocialSignIn: true, heading: String(localized: "Sign in for re-rental alerts"), forAlerts: true)
            }
            .sheet(item: $sheet) { which in
                switch which {
                case .realtime: PaywallView(source: "realtime")
                case .applyHelp: PacketView(listing: listing)
                case .alerts: EmptyView()   // its own sheets above
                }
            }
    }

    /// Push the re-rental's own page onto the tab on screen.
    private func open(_ from: String) {
        var p = Analytics.tileProps(listing, slot: slot); p["from"] = from
        Analytics.shared.track("rerental_open", p)
        nav.push(.rerental(listing))
    }

    /// A card with a move-in deal is set smaller all over, so the card and its
    /// deal box fit on one iPhone screen (owner, 2026-10-27: "make the font
    /// smaller so it can fit on the screen of an iphone").
    private var compact: Bool { listing.deal != nil }

    /// One labelled money line, the style MGNY's income-only cards set.
    /// The label sits as far above its number as the line above sits above
    /// the label (owner, 2026-10-27: "spacing must be equal there").
    private func moneyBlock(label: String?, text: String) -> some View {
        VStack(alignment: .leading, spacing: compact ? 3 : BuildingCard.headGap) {
            if let label { Text(label).font(.se(compact ? 11 : 15, .semibold)).foregroundStyle(SE.ink3).textCase(.uppercase) }
            Text(text).font(.se(compact ? 19 : 24, .bold)).foregroundStyle(SE.ink).lineLimit(1).minimumScaleFactor(0.8)
        }
        .accessibilityElement(children: .combine)
    }

    /// A building name above the address, when it adds something ("Forten at
    /// Columbia" does; a prefix of the address doesn't), then the borough.
    private var kicker: String? {
        let f = listing
        let named = (f.title?.isEmpty == false) && !f.address.lowercased().hasPrefix(f.title!.lowercased())
        let parts = [named ? f.title : nil, f.borough].compactMap { $0 }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private var bits: [String] {
        let f = listing
        var out: [String] = []
        // Some agents print "Studio" (seen as "Studio-bed", 2026-10-27).
        if let b = f.beds { out.append(b.lowercased() == "studio" ? String(localized: "Studio") : "\(b)-bed") }
        // No unit count or ZIP (owner, 2026-10-22): the ZIP is already in
        // the address, and "1 unit" told a renter nothing.
        return out
    }
}

/// The move-in deal, in the compact box the owner picked (2026-10-27, "B2"):
/// each perk on one line, then what the lowest rent averages to over a
/// one-year lease with its free months, when the page ties them to one.
struct DealBox: View {
    let listing: FeaturedListing
    let deal: FeaturedListing.Deal

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                Text("Move-in deal").font(.se(11, .bold)).kerning(0.8).textCase(.uppercase)
                Spacer(minLength: 6)
                Text("from \(shortAgent) · as listed").font(.se(11, .semibold)).lineLimit(1).opacity(0.9)
            }
            .foregroundStyle(.white).padding(.horizontal, 10).padding(.vertical, 5).background(SE.good)
            ForEach(Array(deal.perks.enumerated()), id: \.offset) { i, p in
                if i > 0 { Divider() }
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Image(systemName: Self.icon(p.kind)).font(.system(size: 11, weight: .bold)).foregroundStyle(SE.goodInk)
                        .frame(width: 20, height: 20).background(Circle().fill(SE.goodInk.opacity(0.12)))
                        .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                    (Text(p.title).font(.se(13.5, .semibold)).foregroundStyle(SE.ink)
                     + Text(p.detail.map { " · " + $0 } ?? "").font(.se(12.5)).foregroundStyle(SE.ink3))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, 10).padding(.vertical, 5)
                .accessibilityElement(children: .combine)
            }
            if let eff = effective {
                Divider()
                HStack(alignment: .firstTextBaseline) {
                    Text(eff.label).font(.se(12)).foregroundStyle(SE.ink3).lineLimit(1).minimumScaleFactor(0.8)
                    Spacer(minLength: 6)
                    Text("≈ \(eff.amount)/mo").font(.se(17, .bold)).foregroundStyle(SE.goodInk)
                }
                .padding(.horizontal, 10).padding(.vertical, 6).background(SE.goodInk.opacity(0.06))
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("deal-effective")
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(SE.goodInk, lineWidth: 1.5))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("deal-box")
    }

    /// "MGNY" from "MGNY Consulting Corp.": the header has one short line.
    private var shortAgent: String {
        let a = listing.agent
        let cut = a.range(of: #"\s+(Consulting|Development|Management|Corp|LLC|Inc)\b"#, options: .regularExpression)
        return String(cut.map { a[..<$0.lowerBound] } ?? Substring(a)).trimmingCharacters(in: CharacterSet(charactersIn: " ,."))
    }

    static func icon(_ kind: String) -> String {
        switch kind {
        case "free": "gift.fill"
        case "deposit": "lock.fill"
        case "fees": "percent"
        default: "creditcard.fill"
        }
    }

    /// The feed's rent, else the cheapest row of the listing's unit table.
    private var effective: (label: String, amount: String)? {
        guard let free = deal.freeOn12, free > 0, free < 12 else { return nil }
        var rent: Int? = listing.moneyKind == "rent" ? listing.moneyLow : nil
        var beds: String? = listing.beds
        if rent == nil, let row = Qualify.shared.units[listing.href]?.units.filter({ $0.rent != nil }).min(by: { $0.rent! < $1.rent! }) {
            rent = row.rent; beds = row.beds.map { $0 == 0 ? "studio" : String($0) }
        }
        guard let rent else { return nil }
        let n = { (v: Int) in "$" + v.formatted() }
        let what: String = switch beds?.lowercased() {
        case "studio", "0": String(localized: "Studio")
        case let b?: "\(b)-bed"
        case nil: String(localized: "From")
        }
        let months = free == free.rounded() ? Int(free).formatted() : free.formatted()
        let label = free == 1 ? String(localized: "\(what) \(n(rent)) → with 1 month free")
            : String(localized: "\(what) \(n(rent)) → with \(months) months free")
        return (label, n(Int((Double(rent) * (12 - free) / 12).rounded())))
    }
}
