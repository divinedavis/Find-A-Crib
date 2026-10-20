import SwiftUI

/// Street-level image with a loading placeholder; the ImageService caps
/// concurrency so a fast scroll doesn't fan out.
struct BuildingImage: View {
    let building: Building
    var size = CGSize(width: 800, height: 500)
    @State private var image: UIImage?
    var body: some View {
        ZStack {
            ImagePlaceholder()
            if let image { FillImage(image: image) }
        }
        .clipped().contentShape(Rectangle())
        .task(id: building.bbl) { image = await ImageService.shared.image(for: building, size: size) }
    }
}

/// The results card, laid out like StreetEasy's listing card: photo with a
/// status badge, grey kicker, royal-blue address, price line, facts row,
/// attribution, Share (or pests / owner phone in New York) + primary action.
struct BuildingCard: View {
    /// The one vertical gap between rows of the card body.
    static let rowGap: CGFloat = 8
    /// Neighborhood, address and price sit 30% closer than the other rows
    /// (owner, 2026-10-20).
    static let headGap: CGFloat = rowGap * 0.7
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    @Environment(AppNav.self) private var nav
    let building: Building
    var onOpen: (() -> Void)? = nil

    private var b: Building { building }

    var body: some View {
        let _ = Perf.mark("BuildingCard.body \(b.bbl)")
        VStack(alignment: .leading, spacing: 0) {
            ZStack(alignment: .bottomTrailing) {
                BuildingImage(building: b).frame(height: 226).frame(maxWidth: .infinity)
                    .accessibilityHidden(true)   // the photo repeats the address read just below it
                    .contentShape(Rectangle())
                    .onTapGesture { open() }
                if let l = store.hcrListings(b).first {
                    SEBadge(text: l.isOpen ? String(localized: "\(l.kindLabel) · open") : l.kindLabel, icon: "doc.text.fill", fill: SE.navy, ink: .white)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                        .padding(12)
                        .allowsHitTesting(false)
                }
                if store.voucherAvail(b) != nil {
                    SEBadge(text: String(localized: "Section 8"), icon: "checkmark.seal.fill", fill: .white, ink: SE.ink)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                        .padding(12)
                        .allowsHitTesting(false)
                }
                statusBadge
            }

            // One vertical gap everywhere in the card body, labels and buttons
            // alike: 8pt (owner, 2026-10-20: same spacing for both, 20% less
            // than the old 10pt). No row adds its own padding on top of it.
            VStack(alignment: .leading, spacing: Self.rowGap) {
                // Neighborhood sits right on top of the address: the heart's
                // 44pt frame was pushing the two apart by a full line.
                VStack(alignment: .leading, spacing: Self.headGap) {
                    HStack(alignment: .center) {
                        // Outside New York the borough code is the city's own
                        // ("PHL"): say where in the city instead.
                        Text(store.city.isNYC ? (b.neighborhood.isEmpty ? b.borough : b.neighborhood) : b.place(in: store.city))
                            .font(.se(18, .semibold)).foregroundStyle(SE.ink2).lineLimit(1).minimumScaleFactor(0.85)
                        Spacer(minLength: 8)
                        HeartButton(on: activity.isSaved(b.bbl)) { activity.toggleSaved(b.bbl) }
                            .offset(x: 8).frame(height: 28)
                    }
                    Button(action: open) {
                        // two lines, like the re-rental card: HCR addresses carry the
                        // neighborhood and ZIP and clipped in an iPad column
                        Text(b.address).font(.se(27, .bold)).foregroundStyle(SE.royal).lineLimit(2).minimumScaleFactor(0.8)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }.buttonStyle(.plain).accessibilityIdentifier("card-address")

                    priceLines
                }

                if !store.isSyntheticHCR(b) {
                // Three facts on one row on a 390pt phone: at 20pt "Built 1908"
                // truncated to "Built 1…". 16pt text, tighter dividers, and a
                // lower scale floor keep all three whole.
                // Spread across the card: beds flush left, year flush right,
                // dividers centred in the gaps, so the row uses the whole width.
                HStack(spacing: 0) {
                    // Bedrooms only where the city's record publishes a mix;
                    // elsewhere the slot would read "– bed" on every card.
                    if store.city.isIncomeRestricted {
                        fact("bed.double", bedsText)
                        Spacer(minLength: 6)
                        Rectangle().fill(SE.line).frame(width: 1, height: 22)
                        Spacer(minLength: 6)
                    }
                    fact("building.2", b.u.map { String(localized: "\($0) units") } ?? String(localized: "– units"))
                    Spacer(minLength: 6)
                    Rectangle().fill(SE.line).frame(width: 1, height: 22)
                    Spacer(minLength: 6)
                    fact("calendar", store.city.isIncomeRestricted ? (b.yr.map { String(localized: "Since \(String($0))") } ?? String(localized: "Since –")) : (b.yr.map { String(localized: "Built \(String($0))") } ?? String(localized: "Built –")))
                }
                }

                Text(store.isSyntheticHCR(b) ? String(localized: "Listed on HousingSearch.ny.gov") : attribution).font(.se(18)).foregroundStyle(SE.ink2)

                HStack(spacing: 14) {
                    // New York's register cards lead with the building's pests
                    // ("Bedbugs (2)", rotating through what HPD found) or, when
                    // there are none, the owner's phone (owner, 2026-10-13).
                    // Both open a sign-in preview for signed-out people.
                    // Everywhere else, and for HousingSearch sites, Share stays.
                    if store.city.isNYC && !store.isSyntheticHCR(b) {
                        CardRecordsButton(building: b, onOpen: push)
                    } else {
                        ShareLink(item: b.webURL(in: store.city)) {
                            HStack(spacing: 8) {
                                Image(systemName: "square.and.arrow.up").font(.system(size: 15, weight: .semibold))
                                Text("Share").font(.se(18, .bold))
                            }
                            .foregroundStyle(SE.royal).frame(maxWidth: .infinity).frame(height: 50)
                            .background(Color.white).overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line))
                        }
                        .frame(maxWidth: .infinity)
                    }
                    if let apply = store.hcrListings(b).first(where: { $0.isOpen })?.applyURL ?? store.hcrListings(b).first?.applyURL {
                        Link(destination: apply) {
                            Text("Apply").font(.se(18, .bold)).foregroundStyle(.white)
                                .frame(maxWidth: .infinity).frame(height: 50).background(SE.royal)
                        }.frame(maxWidth: 1000)
                    } else {
                        // The one outbound button (2026-10-06): StreetEasy in
                        // New York, Zillow elsewhere — an address search, never
                        // a listing we carry.
                        let out = store.outbound(b)
                        Link(destination: out.url) {
                            Text(out.label).font(.se(18, .bold)).foregroundStyle(.white).lineLimit(1).minimumScaleFactor(0.7)
                                .frame(maxWidth: .infinity).frame(height: 50).background(SE.royal)
                        }
                        .frame(maxWidth: 1000)
                        .simultaneousGesture(TapGesture().onEnded {
                            Analytics.shared.track("outbound", ["kind": out.kind, "bbl": b.bbl, "href": out.url.absoluteString, "via": "card"])
                        })
                        .accessibilityIdentifier("card-outbound")
                    }
                }
                .frame(maxWidth: .infinity)
            }
            .padding(18)
        }
        .seCard()
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("building-card")
    }

    private func open() {
        if let onOpen { onOpen() } else { push(.building(b.bbl)) }
    }
    fileprivate func push(_ r: Route) {
        switch nav.tab {
        case .search, .lotteries: nav.searchPath.append(r)
        case .casa: nav.casaPath.append(r)
        case .activity: nav.activityPath.append(r)
        case .profile: nav.profilePath.append(r)
        }
    }

    /// Every building on the register gets the green "Rent stabilized" label.
    /// HCR sites are not on the register and keep their own.
    @ViewBuilder private var statusBadge: some View {
        if store.isSyntheticHCR(b) {
            SEBadge(text: String(localized: "HousingSearch.ny.gov"), fill: SE.badge.opacity(0.95))
        } else {
            HStack(spacing: 6) {
                SEBadge(text: store.record(b)?.leasing == 1 ? String(localized: "Leasing now") : store.city.badgeLabel,
                        icon: "checkmark.circle.fill", fill: SE.good, ink: .white)   // SE.green read 4.1:1 under white text
                    .accessibilityIdentifier("badge-stabilized")
            }
        }
    }

    @ViewBuilder private var priceLines: some View {
        if let l = store.hcrListings(b).first {
            VStack(alignment: .leading, spacing: 4) {
                Text(l.name ?? String(localized: "HCR listing")).font(.se(22, .bold)).foregroundStyle(SE.ink).lineLimit(1)
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    if let inc = l.incomeRange { Text(inc).font(.se(20, .bold)); Text("household income").font(.se(17)).foregroundStyle(SE.ink2) }
                }
                Text([l.ptype, l.due.map { String(localized: "apply by \($0)") }, l.approx == true ? String(localized: "location approximate") : nil].compactMap { $0 }.joined(separator: " · "))
                    .font(.se(16)).foregroundStyle(SE.ink3)
            }
        } else if let avail = store.voucherAvail(b), let p = avail.p {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("from \(Formatters.dollars(p))").font(.se(32, .bold)).foregroundStyle(SE.ink).lineLimit(1).layoutPriority(2)
                Text("voucher listing").font(.se(20)).foregroundStyle(SE.ink2).lineLimit(1)
            }
            Text("Landlord soliciting voucher tenants on AffordableHousing.com").font(.se(17)).foregroundStyle(SE.ink2)
        } else if let est = store.estimate(b), est.count >= 3 {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("\(Formatters.dollars(est[0]))–\(Formatters.dollars(est[2]))").font(.se(28, .bold)).foregroundStyle(SE.ink).lineLimit(1).minimumScaleFactor(0.8).layoutPriority(2)
                Text("estimation").font(.se(16)).foregroundStyle(SE.ink2).lineLimit(1).fixedSize().layoutPriority(3)
                InfoDot(title: String(localized: "Estimation"), text: estimateNote).layoutPriority(3)
            }
        } else if store.city.isIncomeRestricted {
            // No rents here: lead with the development and its restricted units.
            let r = store.record(b)
            Text(r?.name ?? String(localized: "Income-restricted building")).font(.se(22, .bold)).foregroundStyle(SE.ink).lineLimit(2)
        } else {
            Text(b.statusLine.isEmpty ? store.city.statusLabel : b.statusLine).font(.se(20, .bold)).foregroundStyle(SE.ink2).lineLimit(2)
        }
    }

    private var bedsText: String {
        // Only the income-restricted cities publish a building's bedroom mix.
        let bd = store.city.isIncomeRestricted
            ? (store.record(b)?.mix ?? [:]).keys.compactMap { Int($0) }.sorted()
            : []
        if bd.isEmpty
 { return String(localized: "– bed") }
        let s = bd.sorted().map { $0 == 0 ? String(localized: "Studio") : "\($0)" }
        return s.count == 1 ? (bd[0] == 0 ? String(localized: "Studio") : String(localized: "\(bd[0]) bed")) : String(localized: "\(s.first!)–\(s.last!) bed")
    }

    private var estimateNote: String {
        String(localized: "HUD FY2026 Small-Area Fair Market Rent for ZIP \(b.z ?? ""), studio to 2-bedroom. A neighborhood-level estimate of what apartments go for — not this building's rent.")
    }

    private var attribution: String {
        if !store.city.isNYC { return cityAttribution }
        let v = b.openViolations
        if v == 0 { return String(localized: "No open HPD violations") }
        return String(localized: "\(v) open HPD violations") + ((b.h?.violations?.oc ?? 0) > 0 ? String(localized: " · \(b.h!.violations!.oc!) class C") : "")
    }

    /// The line under the facts outside New York — never HPD's, which is
    /// New York's agency. LA's LAHD file has violations; the income-restricted
    /// cities say how much of the building is restricted and who funds it.
    private var cityAttribution: String {
        let r = store.record(b)
        if store.city.isIncomeRestricted {
            var bits: [String] = []
            if let li = r?.li { bits.append(String(localized: "\(li) income-restricted units")) }
            if let p = r?.prog?.first { bits.append(p) }
            return bits.isEmpty ? String(localized: "Income-restricted building") : bits.joined(separator: " · ")
        }
        if let rec = store.city.records, rec.violationsLabel != nil, let v = r?.violations {
            let open = v.open ?? 0
            return open == 0 ? String(localized: "No open \(rec.agency) violations") : String(localized: "\(open) open \(rec.agency) violations")
        }
        return store.city.registerNote
    }

    private func fact(_ icon: String, _ text: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: icon).font(.system(size: 17)).foregroundStyle(SE.ink2)
            Text(text).font(.se(19)).foregroundStyle(SE.ink).lineLimit(1).minimumScaleFactor(0.7)
        }
    }
}

/// The card's left button in New York. Shows the pest kinds HPD cited at
/// the building this year, one at a time ("Bedbugs (2)", then "Rats (1)"),
/// or "Owner Phone" when the year is clean. Signed out, a tap opens the
/// matching sign-in preview; signed in, it opens the pest records, or the
/// building scrolled to its Managing agent section (where the phone is)
/// for Plus, or the Plus sheet for the phone.
struct CardRecordsButton: View {
    @Environment(AuthService.self) private var auth
    @Environment(AppNav.self) private var nav
    let building: Building
    let onOpen: (Route) -> Void
    @State private var kinds: [(word: String, count: Int)]? = nil
    @State private var showRecordsSignIn = false
    @State private var showAgentSignIn = false
    @State private var showPaywall = false

    var body: some View {
        Group {
            if let kinds {
                if kinds.isEmpty {
                    button(id: "card-owner-phone", icon: "phone.fill", text: String(localized: "Owner Phone")) { tapPhone() }
                } else {
                    // Rotates every 2.5 s through the kinds found.
                    TimelineView(.periodic(from: .now, by: 2.5)) { ctx in
                        let k = kinds[Int(ctx.date.timeIntervalSinceReferenceDate / 2.5) % kinds.count]
                        button(id: "card-pests", icon: "ladybug.fill", text: "\(k.word.prefix(1).uppercased() + k.word.dropFirst()) (\(k.count))") { tapPests() }
                    }
                }
            } else {
                frame { ProgressView().tint(SE.royal) }.accessibilityIdentifier("card-records-loading")
            }
        }
        .frame(maxWidth: .infinity)
        .task(id: building.bbl) {
            if let stub = Self.stub { kinds = stub; return }
            do { kinds = try await HPDRecords.pests(bbl: building.bbl).kinds }
            catch { kinds = [] }
        }
        .sheet(isPresented: $showRecordsSignIn) {
            EmailSignInView(offersSocialSignIn: true,
                            records: RecordsPreview(openViolations: building.h?.violations?.open, openComplaints: building.h?.complaints?.open))
        }
        .sheet(isPresented: $showAgentSignIn) { EmailSignInView(offersSocialSignIn: true, agentPreview: true) }
        .sheet(isPresented: $showPaywall) { PaywallView(source: "phone") }
    }

    private func tapPests() {
        Analytics.shared.track("card_pests_click", ["bbl": building.bbl, "signed_in": auth.isSignedIn])
        if auth.isSignedIn { onOpen(.hpdRecords(building.bbl, .pests)) } else { showRecordsSignIn = true }
    }

    private func tapPhone() {
        Analytics.shared.track("card_phone_click", ["bbl": building.bbl, "signed_in": auth.isSignedIn, "plus": auth.hasPlus])
        if !auth.isSignedIn { showAgentSignIn = true }
        else if !auth.hasPlus { showPaywall = true }
        else { nav.scrollToAgent = building.bbl; onOpen(.building(building.bbl)) }
    }

    private func button(id: String, icon: String, text: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            frame {
                HStack(spacing: 8) {
                    Image(systemName: icon).font(.system(size: 15, weight: .semibold))
                    Text(text).font(.se(18, .bold)).lineLimit(1).minimumScaleFactor(0.7)
                }
            }
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier(id)
    }

    private func frame<C: View>(@ViewBuilder _ c: () -> C) -> some View {
        c().foregroundStyle(SE.royal).frame(maxWidth: .infinity).frame(height: 50)
            .background(Color.white).overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line))
            .contentShape(Rectangle())
    }

    /// UI tests: `--card-pests bedbugs:2,rats:1` or `--card-pests none`
    /// stands in for NYC Open Data so the card is deterministic offline.
    static let stub: [(word: String, count: Int)]? = {
        let a = CommandLine.arguments
        guard let i = a.firstIndex(of: "--card-pests"), i + 1 < a.count else { return nil }
        if a[i + 1] == "none" { return [] }
        return a[i + 1].split(separator: ",").compactMap { pair in
            let p = pair.split(separator: ":")
            guard p.count == 2, let n = Int(p[1]) else { return nil }
            return (word: String(p[0]), count: n)
        }
    }()
}

extension ISO8601DateFormatter {
    static let ymd: DateFormatter = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "America/New_York"); return f }()
}
