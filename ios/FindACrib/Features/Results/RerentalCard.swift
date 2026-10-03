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
    @State private var showApply = false
    @State private var showPlus = false
    @Environment(AuthService.self) private var auth

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
                            if let url = f.imageURL {
                                RemoteImage(url: url)
                            }
                        }
                    }
                    .frame(height: 226).frame(maxWidth: .infinity).clipped()
                    .accessibilityHidden(true)   // decorative: the address below names the place
                SEBadge(text: "Rerental", icon: "key.fill", fill: SE.navy, ink: .white)
                    .padding(12)
                    .accessibilityIdentifier("badge-rerental")
                SEBadge(text: "Income-restricted", fill: .white, ink: SE.ink)
                    .frame(maxWidth: .infinity, alignment: .topTrailing)
                    .padding(12)
            }

            VStack(alignment: .leading, spacing: 10) {
                VStack(alignment: .leading, spacing: 4) {
                    if let kicker { Text(kicker).font(.se(18, .semibold)).foregroundStyle(SE.ink2).lineLimit(1).minimumScaleFactor(0.85) }
                    Text(f.address).font(.se(27, .bold)).foregroundStyle(SE.royal).lineLimit(2).minimumScaleFactor(0.8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .accessibilityIdentifier("card-address")
                }

                let money = f.moneyLine
                VStack(alignment: .leading, spacing: 2) {
                    if let label = money.label { Text(label).font(.se(15, .semibold)).foregroundStyle(SE.ink3).textCase(.uppercase) }
                    Text(money.text).font(.se(money.label == nil && f.moneyKind == "rent" ? 32 : 24, .bold)).foregroundStyle(SE.ink)
                        .lineLimit(1).minimumScaleFactor(0.8)
                }

                if !bits.isEmpty { Text(bits.joined(separator: " · ")).font(.se(18)).foregroundStyle(SE.ink2).lineLimit(1) }

                if let v = Qualify.shared.verdict(for: f) { QualifyBadge(verdict: v) }
                if let t = Qualify.shared.units[f.href] {
                    if t.first_come_first_served == true { Text("⏱ First come, first served").font(.se(15, .semibold)).foregroundStyle(SE.ink2) }
                    if let d = t.deadline { Text("Apply by \(d)").font(.se(15, .semibold)).foregroundStyle(SE.ink2) }
                    ForEach(t.flags ?? [], id: \.code) { fl in
                        Label("Check carefully: \(fl.why)", systemImage: "exclamationmark.triangle.fill").font(.se(14, .semibold)).foregroundStyle(SE.warn)
                    }
                }
                (Text("Listed by ").font(.se(18)) + Text(f.agent).font(.se(18, .bold)) + Text(f.agent.localizedCaseInsensitiveContains("Housing Development Corporation") ? " — the city's affordable-housing finance agency" : " — an HPD-approved marketing agent").font(.se(18)))
                    .foregroundStyle(SE.ink2)

                HStack(spacing: 14) {
                    if let url = URL(string: f.href) {
                        ShareLink(item: url) {
                            HStack(spacing: 8) {
                                Image(systemName: "square.and.arrow.up").font(.system(size: 15, weight: .semibold))
                                Text("Share").font(.se(18, .bold))
                            }
                            .foregroundStyle(SE.royal).frame(maxWidth: .infinity).frame(height: 50)
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
                            Text(f.actionTitle).font(.se(18, .bold)).foregroundStyle(.white).lineLimit(1).minimumScaleFactor(0.7)
                                .padding(.horizontal, 8).frame(maxWidth: .infinity).frame(height: 50).background(SE.royal)
                        }
                        .buttonStyle(.plain)
                        .frame(maxWidth: 1000)
                        .accessibilityIdentifier("rerental-apply")
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 10)
                // Plus opens the sheet; anyone else sees the Plus page first,
                // led by Help me apply, and lands in the sheet once they have it.
                Button { if auth.hasPlus { showApply = true } else { showPlus = true } } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "doc.text").font(.system(size: 15, weight: .bold))
                        Text("Help me apply").font(.se(17, .bold))
                        PlusTag()
                    }.foregroundStyle(SE.royal).frame(maxWidth: .infinity).frame(height: 44)
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line))
                }
                .buttonStyle(.plain).accessibilityIdentifier("rerental-apply-help")
                .sheet(isPresented: $showApply) { ApplyHelpSheet(listing: f) }
                .sheet(isPresented: $showPlus, onDismiss: { if auth.hasPlus { showApply = true } }) {
                    PaywallView(source: "apply_help", context: f.address)
                }
            }
            .padding(18)
        }
        .seCard()
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("rerental-card")
        .onAppear { Analytics.shared.tileSeen(f, slot: slot) }
        .task { await Qualify.shared.loadUnits() }
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
        if let b = f.beds { out.append(b == "studio" ? "Studio" : "\(b)-bed") }
        if let u = f.units { out.append("\(u) unit\(u == 1 ? "" : "s")") }
        if let z = f.zip { out.append("ZIP \(z)") }
        return out
    }
}
