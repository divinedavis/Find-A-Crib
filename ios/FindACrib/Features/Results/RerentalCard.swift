import SwiftUI

/// A re-rental tile in the results feed: a real income-restricted apartment
/// an HPD-approved marketing agent is advertising today, laid out like the
/// building card so it reads as part of the feed, flagged "Rerental" so it
/// never passes for a register building.
struct RerentalCard: View {
    let listing: FeaturedListing
    /// Which re-rental slot of the feed this is (0 = the 3rd tile), for the funnel.
    var slot: Int = 0
    @Environment(\.openURL) private var openURL
    @State private var photo = 0

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
                                .onChange(of: photo) { _, i in
                                    if i == 1 { Analytics.shared.track("rerental_photos_swipe", ["agent": f.agent, "photos": urls.count]) }
                                }
                            } else if let url = urls.first {
                                RemoteImage(url: url)
                            }
                        }
                    }
                    .frame(height: compact ? 140 : 226).frame(maxWidth: .infinity).clipped().contentShape(Rectangle())
                    .accessibilityElement(children: .ignore)
                    .accessibilityLabel(f.imageURLs.count > 1 ? String(localized: "Photo \(photo + 1) of \(f.imageURLs.count)") : String(localized: "Photo of the building"))
                    .accessibilityAdjustableAction { dir in
                        let n = f.imageURLs.count
                        guard n > 1 else { return }
                        photo = dir == .increment ? min(photo + 1, n - 1) : max(photo - 1, 0)
                    }
                    .accessibilityIdentifier("rerental-photos")
                SEBadge(text: String(localized: "Rerental"), icon: "key.fill", fill: SE.navy, ink: .white)
                    .padding(12)
                    .accessibilityIdentifier("badge-rerental")
                SEBadge(text: String(localized: "Income-restricted"), fill: .white, ink: SE.ink)
                    .frame(maxWidth: .infinity, alignment: .topTrailing)
                    .padding(12)
                if f.deal != nil {
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

            // The building card's spacing (owner, 2026-10-20): one 8pt gap for
            // every row and button, the borough / address / price block 30%
            // tighter.
            VStack(alignment: .leading, spacing: compact ? 6 : BuildingCard.rowGap) {
                VStack(alignment: .leading, spacing: compact ? 3 : BuildingCard.headGap) {
                    if let kicker { Text(kicker).font(.se(compact ? 14 : 18, .semibold)).foregroundStyle(SE.ink2).lineLimit(1).minimumScaleFactor(0.85) }
                    Text(f.address).font(.se(compact ? 21 : 27, .bold)).foregroundStyle(SE.royal).lineLimit(3).minimumScaleFactor(0.8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .accessibilityIdentifier("card-address")

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
                        Label("Check carefully: \(fl.why)", systemImage: "exclamationmark.triangle.fill").font(.se(14, .semibold)).foregroundStyle(SE.warn)
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
                            .foregroundStyle(SE.royal).frame(maxWidth: .infinity).frame(height: compact ? 40 : 50)
                            .background(Color.white).overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line))
                        }
                        .frame(maxWidth: .infinity)
                    }
                    if let out = f.outboundURL {
                        Button {
                            // Both rows the site writes for a hand-off: the funnel's
                            // click and the generic outbound.
                            var p = Analytics.tileProps(f, slot: slot); p["href"] = out.absoluteString
                            Analytics.shared.track("featured_click", p)
                            Analytics.shared.track("outbound", ["kind": "rerental", "agent": f.agent, "href": out.absoluteString])
                            openURL(out)
                        } label: {
                            Text(f.actionTitle).font(.se(compact ? 15 : 18, .bold)).foregroundStyle(.white).lineLimit(1).minimumScaleFactor(0.7)
                                .padding(.horizontal, 8).frame(maxWidth: .infinity).frame(height: compact ? 40 : 50).background(SE.royal)
                        }
                        .buttonStyle(.plain)
                        .frame(maxWidth: 1000)
                        .accessibilityIdentifier("rerental-apply")
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .padding(compact ? 14 : 18)
        }
        .seCard()
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("rerental-card")
        .onAppear { Analytics.shared.tileSeen(f, slot: slot) }
        .task { await Qualify.shared.loadUnits() }
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
        if let b = f.beds { out.append(b == "studio" ? String(localized: "Studio") : "\(b)-bed") }
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
                    Image(systemName: Self.icon(p.kind)).font(.system(size: 11, weight: .bold)).foregroundStyle(SE.good)
                        .frame(width: 20, height: 20).background(Circle().fill(SE.good.opacity(0.12)))
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
                    Text("≈ \(eff.amount)/mo").font(.se(17, .bold)).foregroundStyle(SE.good)
                }
                .padding(.horizontal, 10).padding(.vertical, 6).background(SE.good.opacity(0.06))
                .accessibilityElement(children: .combine)
                .accessibilityIdentifier("deal-effective")
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(RoundedRectangle(cornerRadius: 10).stroke(SE.good, lineWidth: 1.5))
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
