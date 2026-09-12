import SwiftUI
import MapKit

struct BuildingDetailView: View {
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    @Environment(AppNav.self) private var nav
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @Environment(AuthService.self) private var auth
    let building: Building
    @State private var contacts: HPDContacts?
    @State private var phone: String?
    @State private var contactsLoading = false
    /// The two inspection tiles, fetched live once the person is signed in.
    @State private var bedbugSummary: HPDRecords.InspectionSummary?
    @State private var rodentSummary: HPDRecords.InspectionSummary?
    @State private var inspectionsFailed = false
    @State private var showPaywall = false
    @State private var scene: MKLookAroundScene?
    @State private var sceneChecked = false

    private var b: Building { building }

    var body: some View {
        VStack(spacing: 0) {
            NavyBarBackdrop()

            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    hero
                    if !store.isSyntheticHCR(b) { factsStrip }

                    if !store.hcrListings(b).isEmpty { section(store.hcrListings(b).count == 1 ? "Lottery / waitlist" : "Lotteries & waitlists") { hcrBlock } }

                    if store.isSyntheticHCR(b) {
                        section("About") {
                            Text("An income-restricted development with a New York State HCR regulatory agreement, listed on HousingSearch.ny.gov. It is not on the rent-stabilization register, so there is no DHCR or HPD record here — the listing above is the whole story.")
                                .font(.se(17)).foregroundStyle(SE.ink2)
                        }
                    } else {
                    section("About") {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(aboutLines, id: \.self) { Text($0).font(.se(19)).foregroundStyle(SE.ink) }
                        }
                        // Each city's register is a different thing and says so
                        // in its own words. Until 2026-09-12 every city got
                        // New York's sentence, which named a New York agency
                        // under a Los Angeles parcel.
                        Text(store.city.aboutNote)
                            .font(.se(16)).foregroundStyle(SE.ink2).padding(.top, 12)
                        if store.city.isNYC {
                            Button { openURL(URL(string: "https://findacrib.com/guide/what-is-rent-stabilization/")!) } label: {
                                Text("What rent stabilization means for you").font(.se(19, .bold)).foregroundStyle(SE.royal)
                            }.buttonStyle(.plain).padding(.top, 12)
                        }
                    }

                    if store.city.isNYC || b.mr != nil { section("Rent") { rentBlock } }

                    if store.city.isNYC { section("Managing agent") { agentBlock } }

                    if store.city.isNYC { voucherCard }

                    if store.city.isNYC {
                        section("Violations & inspections") { hpdBlock }
                    } else if let r = store.city.records {
                        section(r.heading) { cityRecordBlock(r) }
                    }

                    similarRail
                    }

                    Text(store.city.sourcesNote + " Find A Crib is not a broker and does not list apartments.")
                        .font(.se(14)).foregroundStyle(SE.ink3).padding(16)
                    Color.clear.frame(height: 100)
                }
            }
            .background(SE.canvas)
        }
        .background(SE.canvas)
        .safeAreaInset(edge: .bottom) {
            HStack(spacing: 12) {
                ShareLink(item: b.webURL(in: store.city)) {
                    Text("Share").font(.se(18, .bold)).foregroundStyle(SE.royal)
                        .frame(maxWidth: .infinity).frame(height: 50).background(Color.white)
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.royal, lineWidth: 1))
                }
                if let apply = store.hcrListings(b).first(where: { $0.isOpen })?.applyURL ?? store.hcrListings(b).first?.applyURL {
                    SEPrimaryButton(title: "Apply on HousingSearch.ny.gov") { openURL(apply) }
                } else if let url = store.listingURL(b) {
                    SEPrimaryButton(title: store.listingSite(b)) { openURL(url) }
                } else if let url = store.voucherAvail(b)?.url.flatMap(URL.init) {
                    SEPrimaryButton(title: "Voucher listing") { openURL(url) }
                } else {
                    SEPrimaryButton(title: "Open on findacrib.com") {
                        Analytics.shared.track("outbound", ["kind": "website", "bbl": b.bbl])
                        openURL(b.webURL(in: store.city))
                    }
                }
            }
            .padding(16)
            .background(Color.white.shadow(.drop(color: .black.opacity(0.08), radius: 6, y: -2)))
        }
        .swipeBackEnabled()
        .toolbar {
            ToolbarItem(placement: .principal) {
                VStack(alignment: .leading, spacing: 0) {
                    Text(b.address).font(.se(19, .bold)).foregroundStyle(.white).lineLimit(1).minimumScaleFactor(0.75)
                    Text(b.neighborhood).font(.se(13, .semibold)).foregroundStyle(.white.opacity(0.9)).lineLimit(1)
                }
                .frame(width: UIScreen.main.bounds.width - 150, alignment: .leading)
            }
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    ShareLink(item: b.webURL(in: store.city)) { Label("Share", systemImage: "square.and.arrow.up") }
                    Button { openURL(b.webURL(in: store.city)) } label: { Label("Open on findacrib.com", systemImage: "safari") }
                    Button {
                        let item = MKMapItem(placemark: MKPlacemark(coordinate: b.coordinate)); item.name = b.address
                        item.openInMaps(launchOptions: [MKLaunchOptionsDirectionsModeKey: MKLaunchOptionsDirectionsModeDefault])
                    } label: { Label("Directions", systemImage: "arrow.triangle.turn.up.right.diamond") }
                    Button { activity.toggleSaved(b.bbl) } label: {
                        Label(activity.isSaved(b.bbl) ? "Unsave" : "Save", systemImage: activity.isSaved(b.bbl) ? "heart.fill" : "heart")
                    }
                } label: {
                    Image(systemName: "ellipsis").font(.system(size: 20, weight: .bold)).foregroundStyle(.white).frame(width: 36, height: 36)
                }
                .accessibilityIdentifier("detail-menu")
            }
        }
        .sheet(isPresented: $showPaywall) { PaywallView() }
        .onAppear { nav.hideTabBar = true; activity.recordView(b.bbl) }
        .onDisappear { nav.hideTabBar = false }
        .task {
            scene = try? await MKLookAroundSceneRequest(coordinate: b.coordinate).scene
            sceneChecked = true
        }
        .task(id: "\(auth.isSignedIn)-\(auth.hasPlus)") { await loadContacts() }
        .task(id: "\(b.bbl)-\(auth.isSignedIn)") { await loadInspections() }
    }

    private func loadContacts() async {
        guard auth.isSignedIn else { contacts = nil; phone = nil; return }
        contactsLoading = true; defer { contactsLoading = false }
        contacts = await auth.contacts(for: b.bbl)
        phone = (contacts?.manager?.hasPhone ?? false) ? await auth.agentPhone(for: b.bbl) : nil
    }

    /// StreetEasy's "Listing by …" block, with the HPD-registered managing
    /// agent. The number is the Plus feature: shown only to subscribers, via
    /// get_agent_phone(); everyone else sees that one is on file.
    @ViewBuilder private var agentBlock: some View {
        if !auth.isSignedIn {
            Text("The managing agent and owner HPD has on file for this building, and — with Find A Crib Plus — the agent's phone number.")
                .font(.se(17)).foregroundStyle(SE.ink2)
            SEOutlineButton(title: "Sign in to see who runs this building", icon: "person.crop.circle") { nav.tab = .profile }
                .accessibilityIdentifier("agent-sign-in")
        } else if contactsLoading && contacts == nil {
            HStack(spacing: 10) { ProgressView().tint(SE.royal); Text("Looking up HPD registration…").font(.se(17)).foregroundStyle(SE.ink2) }
        } else if let c = contacts {
            if let m = c.manager, let name = m.name {
                party("Managing agent", name, m.type, m.address)
                if let phone {
                    Link(destination: URL(string: "tel:" + phone.filter { $0.isNumber || $0 == "+" })!) {
                        HStack(spacing: 10) {
                            Image(systemName: "phone.fill").font(.system(size: 16, weight: .bold))
                            Text(phone).font(.se(20, .bold))
                            Spacer()
                            Text("Call").font(.se(17, .bold))
                        }
                        .foregroundStyle(.white).padding(.horizontal, 16).frame(height: 50).background(SE.royal).clipShape(RoundedRectangle(cornerRadius: 2))
                    }
                    .accessibilityIdentifier("agent-phone")
                } else if m.hasPhone {
                    Button { if !auth.hasPlus { showPaywall = true } } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "lock.fill").font(.system(size: 15, weight: .bold)).foregroundStyle(SE.ink3)
                            Text(auth.hasPlus ? "Phone number temporarily unavailable" : "Phone number — unlock with Find A Crib Plus")
                                .font(.se(17, .semibold)).foregroundStyle(SE.ink2)
                            Spacer()
                            if !auth.hasPlus { Image(systemName: "chevron.right").font(.system(size: 14, weight: .bold)).foregroundStyle(SE.royal) }
                        }
                        .padding(14).frame(maxWidth: .infinity, alignment: .leading).background(SE.canvas)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityIdentifier("agent-phone-locked")
                } else {
                    Text("No phone number on file for this agent.").font(.se(16)).foregroundStyle(SE.ink3)
                }
            } else {
                Text("No managing agent in this building's HPD registration.").font(.se(17)).foregroundStyle(SE.ink2)
            }
            if let o = c.owner, let name = o.name { party("Owner", name, o.type, o.address).padding(.top, 6) }
            if let h = c.officer, let name = h.name, h.name != c.owner?.name { party("Head officer", name, h.type, h.address).padding(.top, 6) }
            Text("From the building's HPD property registration. Numbers come from public business listings and are for tenant inquiries.")
                .font(.se(14)).foregroundStyle(SE.ink3).padding(.top, 4)
        } else {
            Text("No HPD registration contacts on file for this building.").font(.se(17)).foregroundStyle(SE.ink2)
        }
    }
    private func party(_ role: String, _ name: String, _ type: String?, _ address: String?) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(role + (type.map { " · \(AddressCase.pretty($0.replacingOccurrences(of: "([a-z])([A-Z])", with: "$1 $2", options: .regularExpression)))" } ?? ""))
                .font(.se(14, .semibold)).foregroundStyle(SE.ink3)
            Text(AddressCase.pretty(name)).font(.se(20, .bold)).foregroundStyle(SE.ink)
            if let address { Text(AddressCase.pretty(address)).font(.se(16)).foregroundStyle(SE.ink2) }
        }
    }

    /// HousingSearch.ny.gov lottery / waitlist details for this site.
    @ViewBuilder private var hcrBlock: some View {
        ForEach(store.hcrListings(b)) { l in
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    SEBadge(text: l.kindLabel, icon: "doc.text.fill", fill: SE.navy, ink: .white)
                    SEBadge(text: l.isOpen ? "Open" : "Closed", fill: l.isOpen ? Color(hex: 0xDCFCE7) : SE.badge, ink: l.isOpen ? SE.good : SE.ink2)
                    if l.senior == true { SEBadge(text: "Seniors", fill: SE.badge) }
                }
                Text(l.name ?? "").font(.se(24, .bold))
                if let inc = l.incomeRange {
                    HStack(alignment: .firstTextBaseline, spacing: 8) { Text(inc).font(.se(22, .bold)); Text("household income").font(.se(17)).foregroundStyle(SE.ink2) }
                }
                VStack(alignment: .leading, spacing: 4) {
                    if let p = l.ptype { row("Type", p) }
                    if let d = l.due { row(l.kind == "Lottery" ? "Application deadline" : "Apply by", d) }
                    if let f = l.fee { row("Application fee", Formatters.dollars(f)) }
                    if let ph = l.phone { row("Phone", ph) }
                }
                if let d = l.desc { Text(d).font(.se(16)).foregroundStyle(SE.ink2).lineLimit(8) }
                if l.approx == true {
                    Text("Location shown is the development's application/mailing address; the listing does not give a building address.")
                        .font(.se(14)).foregroundStyle(SE.ink3)
                }
                if let u = l.applyURL {
                    SEPrimaryButton(title: l.isOpen ? "Apply on HousingSearch.ny.gov" : "See listing on HousingSearch.ny.gov") { openURL(u) }
                }
                Text("Source: HousingSearch.ny.gov — New York State Homes and Community Renewal. Income limits and deadlines are the listing's; confirm on the portal before applying.")
                    .font(.se(14)).foregroundStyle(SE.ink3)
            }
            .padding(.bottom, 8)
        }
    }
    private func row(_ k: String, _ v: String) -> some View {
        HStack { Text(k).font(.se(17)).foregroundStyle(SE.ink2); Spacer(); Text(v).font(.se(17, .bold)).multilineTextAlignment(.trailing) }
    }

    // MARK: pieces

    @ViewBuilder private var hero: some View {
        ZStack(alignment: .bottomTrailing) {
            if let scene {
                LookAroundPreview(initialScene: scene, allowsNavigation: true, showsRoadLabels: false, pointsOfInterest: .excludingAll)
                    .frame(height: 280)
            } else {
                BuildingImage(building: b).frame(height: 280).frame(maxWidth: .infinity)
            }
            // Save lives in the ··· menu; a heart over the photo covered the
            // Look Around imagery and the owner asked for it gone.
            if store.voucherAvail(b) != nil {
                SEBadge(text: "Section 8", icon: "checkmark.seal.fill", fill: .white).padding(12)
            }
        }
        .accessibilityIdentifier("detail-hero")
    }

    private var factsStrip: some View {
        HStack(spacing: 0) {
            factCell("Building type", b.s?.first.map { AddressCase.pretty($0) } ?? "Multiple dwelling")
            Rectangle().fill(Color.white.opacity(0.25)).frame(width: 1, height: 44)
            factCell("Year built", b.yr.map(String.init) ?? "–")
            Rectangle().fill(Color.white.opacity(0.25)).frame(width: 1, height: 44)
            factCell("Units", b.u.map { $0.formatted() } ?? "–")
        }
        .padding(.vertical, 14)
        .frame(maxWidth: .infinity)
        .background(SE.facts)
    }
    private func factCell(_ k: String, _ v: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(k).font(.se(15, .semibold)).foregroundStyle(.white.opacity(0.7))
            Text(v).font(.se(19, .semibold)).foregroundStyle(.white).lineLimit(1).minimumScaleFactor(0.7)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16)
    }

    private func section<C: View>(_ title: String, @ViewBuilder _ content: () -> C) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(title).font(.se(30, .black)).foregroundStyle(SE.ink)
            content()
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white)
        .padding(.bottom, 10)
    }

    private var aboutLines: [String] {
        // The register's own status line and the city's label are the same fact
        // in two voices — LA stacked "LIKELY RENT-STABILIZED (RSO)" on top of
        // "LIKELY RSO (PRE-1979, 2+ UNITS)", and DC did the same. Lead with the
        // source's wording, which is the more specific of the two, and fall
        // back to the city's label only when the record carries none — which is
        // New York, whose one status line is the dwelling class.
        var l = (b.s ?? []).filter { !$0.uppercased().contains("MULTIPLE DWELLING") }.map { $0.uppercased() }
        if l.isEmpty { l = [store.city.statusLabel.uppercased()] }
        if let z = b.z, !z.isEmpty {
            let place = store.city.isNYC ? b.borough : (b.nb ?? store.city.name)
            l.append("\(place.uppercased()) · ZIP \(z)")
        }
        if store.city.isNYC, store.voucherBuilding(b) != nil { l.append("SUBSIDIZED / VOUCHER-FRIENDLY BUILDING") }
        if let r = b.h?.lastregistration { l.append("HPD REGISTRATION \(r)") }
        if let t = b.h?.ptype { l.append(t.uppercased()) }
        return l
    }

    @ViewBuilder private var rentBlock: some View {
        if !store.city.isNYC {
            cityRentBlock
        } else if let p = store.price(b) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(Formatters.dollars(p)).font(.se(38, .bold))
                Text("asking rent").font(.se(20)).foregroundStyle(SE.ink2)
            }
            let n = store.listingCount(b); let bd = store.beds(b)
            Text("\(n) recent listing\(n == 1 ? "" : "s")" + (bd.isEmpty ? "" : " · " + bd.sorted().map { $0 == 0 ? "studio" : "\($0) bed" }.joined(separator: ", ")) +
                 (store.postedDate(b).map { " · posted \(Formatters.long.string(from: $0))" } ?? ""))
                .font(.se(17)).foregroundStyle(SE.ink2)
        } else if let (p, d) = store.lastPrice(b) {
            Text("Last advertised at \(Formatters.dollars(p))" + (d.map { " on \(Formatters.long.string(from: $0))" } ?? "") + " — no listing in the last 5 days.")
                .font(.se(17)).foregroundStyle(SE.ink2)
        }
        if let e = store.estimate(b), e.count >= 4 {
            VStack(alignment: .leading, spacing: 8) {
                Text("Typical rent in ZIP \(b.z ?? "")").font(.se(18, .bold)).foregroundStyle(SE.ink2).padding(.top, store.price(b) == nil ? 0 : 8)
                HStack(spacing: 0) {
                    estCell("Studio", e[0]); estCell("1 bed", e[1]); estCell("2 bed", e[2]); estCell("3 bed", e[3])
                }
                Text("HUD FY2026 Small-Area Fair Market Rents — the neighborhood's going rate, not this building's regulated rent. Stabilized rents are often well below it.")
                    .font(.se(15)).foregroundStyle(SE.ink3)
            }
        }
        if store.price(b) == nil && store.estimate(b) == nil {
            Text("No recent listing and no ZIP estimate on file.").font(.se(18)).foregroundStyle(SE.ink2)
        }
    }
    /// SF and DC publish a rent on the record itself — never an asking rent.
    /// SF's is what owners reported to the Rent Board for the block; DC's is
    /// the legal rent registered with DHCD, which is the whole point of the
    /// city being on this map at all.
    @ViewBuilder private var cityRentBlock: some View {
        if let r = b.mr {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(Formatters.dollars(r)).font(.se(38, .bold))
                Text(store.city.priceLabel.lowercased()).font(.se(20)).foregroundStyle(SE.ink2)
            }
            // Split by bedroom count where the source carries it. A blended
            // median that mixes studios with three-beds answers nobody.
            let beds = Building.bedOrder.compactMap { k in (b.br?[k]).map { (Building.bedLabel(k), $0) } }
            if !beds.isEmpty {
                HStack(spacing: 0) { ForEach(beds, id: \.0) { estCell($0.0, $0.1) } }.padding(.top, 4)
            }
            if !rentExtras.isEmpty {
                Text(rentExtras).font(.se(17)).foregroundStyle(SE.ink2)
            }
            Text(store.city.id == "sf"
                 ? "Reported to the SF Rent Board by owners on this block — not an asking rent, and not one address."
                 : "The legal rent on file with DC DHCD for this property's rent-controlled units — not an asking rent.")
                .font(.se(15)).foregroundStyle(SE.ink3)
        } else {
            Text("No rent on file for this \(store.city.records?.scope ?? "property").")
                .font(.se(18)).foregroundStyle(SE.ink2)
        }
    }

    /// The record this city keeps, in this city's words. Every block is
    /// optional: LA cites violations, SF files evictions by block, DC knows the
    /// owner and the assessor's read of the building, and none of them has what
    /// the others have.
    @ViewBuilder private func cityRecordBlock(_ r: City.Records) -> some View {
        let h = b.h
        let hasAny = h != nil && (h?.violations != nil || h?.complaints != nil || h?.ev != nil
                                  || h?.by != nil || h?.pet != nil || h?.owner != nil
                                  || (h?.cases?.total ?? 0) > 0)
        if !hasAny {
            Text(r.emptyNote).font(.se(18)).foregroundStyle(SE.ink2)
        } else {
            if r.showsOwner, let h {
                if let owner = h.owner {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("Owner of record").font(.se(15, .semibold)).foregroundStyle(SE.ink2)
                        Text(owner).font(.se(21, .bold)).foregroundStyle(SE.ink)
                    }
                }
                let spec = ownerSpec(h)
                if !spec.isEmpty { Text(spec).font(.se(17)).foregroundStyle(SE.ink2) }
                if let v = h.vacreg {
                    Text("On DC's vacant & blighted register — \(v)").font(.se(17, .bold)).foregroundStyle(SE.bad)
                }
            }
            if let label = r.violationsLabel, let v = h?.violations {
                recStat(label, [("\(v.open ?? 0)", "open", (v.open ?? 0) > 5 ? SE.bad : ((v.open ?? 0) > 0 ? SE.warn : SE.good)),
                                (v.total.map(String.init) ?? "—", "cited", SE.ink),
                                (v.last_12mo.map(String.init) ?? "—", "last 12mo", SE.ink)])
                let named = v.named
                if !named.isEmpty {
                    Text("Cited for: " + named.map { $0.1 > 1 ? "\($0.0) (\($0.1))" : $0.0 }.joined(separator: " · "))
                        .font(.se(15)).foregroundStyle(SE.ink3)
                }
                // The LA file is a rolling window, not an all-time register —
                // without the dates "6 cited" reads as a lifetime count.
                if let w = h?.window, w.count == 2 {
                    Text("Covers citations from \(w[0]) to \(w[1]) — \(r.agency)'s file is a rolling window, not an all-time register.")
                        .font(.se(15)).foregroundStyle(SE.ink3)
                }
            }
            if let label = r.complaintsLabel, let c = h?.complaints {
                recStat(label, [("\(c.open ?? 0)", "open", (c.open ?? 0) > 10 ? SE.bad : ((c.open ?? 0) > 0 ? SE.warn : SE.good)),
                                (c.total.map(String.init) ?? "—", "all time", SE.ink),
                                ((h?.insp).map(String.init) ?? "—", "inspections", SE.ink)])
            }
            if let label = r.evictionsLabel, let e = h?.ev {
                recStat(label, [("\(e.total ?? 0)", "filed", SE.ink),
                                ("\(e.nofault ?? 0)", "no-fault", (e.nofault ?? 0) > 0 ? SE.warn : SE.ink),
                                ("\(e.recent ?? e.last_12mo ?? 0)", "last 5 yrs", SE.ink)])
                let named = e.named
                if !named.isEmpty {
                    Text("Grounds cited: " + named.map { $0.1 > 1 ? "\($0.0) (\($0.1))" : $0.0 }.joined(separator: " · "))
                        .font(.se(15)).foregroundStyle(SE.ink3)
                }
                Text("A no-fault notice — Ellis Act, owner move-in, demolition — means a tenant can be made to leave without having done anything.")
                    .font(.se(15)).foregroundStyle(SE.ink3)
            }
            if let label = r.petitionsLabel, let pt = h?.pet {
                recStat(label, [("\(pt.total ?? 0)", "filed", SE.ink),
                                ("\(pt.landlord ?? 0)", "by landlord", SE.ink),
                                ("\(pt.tenant ?? 0)", "by tenant", SE.ink)])
            }
            if let label = r.buyoutsLabel, let by = h?.by, (by.n ?? 0) > 0 {
                recStat(label, [("\(by.n ?? 0)", "agreed", SE.ink),
                                (by.med.map { Formatters.dollars($0) } ?? "—", "median", SE.ink),
                                ("\(by.recent ?? 0)", "last 5 yrs", SE.ink)])
                Text("A buyout is a landlord paying a tenant to leave a rent-controlled unit. It has to be disclosed, so a run of them on one \(r.scope == "this block" ? "block" : "address") is a signal.")
                    .font(.se(15)).foregroundStyle(SE.ink3)
            }
            if let label = r.casesLabel, let cs = h?.cases, (cs.total ?? 0) > 0 {
                recStat(label, [("\(cs.open ?? 0)", "open", (cs.open ?? 0) > 0 ? SE.warn : SE.good),
                                ("\(cs.total ?? 0)", "all time", SE.ink),
                                ("", "", SE.ink)])
            }
            if let note = r.note { Text(note).font(.se(15)).foregroundStyle(SE.ink3) }
        }
        // Said even when the rest is empty: an absent panel reads as a clean
        // building, and only a sentence reads as "nobody publishes this".
        if let note = r.noViolationsNote {
            VStack(alignment: .leading, spacing: 8) {
                Text("Housing code violations").font(.se(19, .bold)).foregroundStyle(SE.ink)
                Text(note).font(.se(16)).foregroundStyle(SE.ink2)
                if let link = r.noViolationsLink, let url = URL(string: link) {
                    Button { openURL(url) } label: {
                        Text(r.noViolationsLinkLabel ?? "Look it up").font(.se(18, .bold)).foregroundStyle(SE.royal)
                    }.buttonStyle(.plain)
                }
            }.padding(.top, 6)
        }
    }

    /// "Typically 1,125 sq ft · water, refuse included in the rent" — the two
    /// things SF reports about a unit beyond its rent.
    private var rentExtras: String {
        var bits: [String] = []
        if let sq = b.sq { bits.append("typically \(sq.formatted()) sq ft") }
        if let ui = b.ui, !ui.isEmpty {
            bits.append("\(ui.map(Building.utilityLabel).joined(separator: ", ")) included in the rent")
        }
        let line = bits.joined(separator: " · ")
        return line.isEmpty ? "" : line.prefix(1).uppercased() + line.dropFirst()
    }

    private func ownerSpec(_ h: Building.HPD) -> String {
        var bits: [String] = []
        if let t = h.units_total { bits.append("\(t) unit\(t == 1 ? "" : "s") in the building") }
        if let n = h.beds { bits.append("\(n) bedroom\(n == 1 ? "" : "s")") }
        if let n = h.baths { bits.append("\(n) bathroom\(n == 1 ? "" : "s")") }
        if let n = h.rooms { bits.append("\(n) room\(n == 1 ? "" : "s")") }
        if let c = h.cond { bits.append("condition: \(c)") }
        if let y = h.renov { bits.append("brought up to date ~\(y)") }
        if let a = h.assessed { bits.append("assessed at \(Formatters.dollars(a))") }
        return bits.joined(separator: " · ")
    }

    /// Three figures across, the way the HPD tiles read — but flat, because
    /// none of these opens a screen of its own.
    private func recStat(_ title: String, _ cells: [(String, String, Color)]) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.se(19, .bold)).foregroundStyle(SE.ink)
            HStack(spacing: 0) {
                ForEach(Array(cells.enumerated()), id: \.offset) { _, c in
                    VStack(spacing: 2) {
                        Text(c.0.isEmpty ? " " : c.0).font(.se(24, .bold)).foregroundStyle(c.2)
                            .lineLimit(1).minimumScaleFactor(0.6)
                        Text(c.1.isEmpty ? " " : c.1).font(.se(14)).foregroundStyle(SE.ink3)
                    }.frame(maxWidth: .infinity).padding(.vertical, 8)
                    .overlay(Rectangle().stroke(c.1.isEmpty ? Color.clear : SE.lineSoft))
                }
            }
        }.padding(.top, 6)
    }

    private func estCell(_ k: String, _ v: Int) -> some View {
        VStack(spacing: 4) {
            Text(Formatters.dollars(v)).font(.se(19, .bold))
            Text(k).font(.se(14)).foregroundStyle(SE.ink3)
        }.frame(maxWidth: .infinity).padding(.vertical, 10).overlay(Rectangle().stroke(SE.lineSoft))
    }

    private var voucherCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let a = store.voucherAvail(b) {
                Text("Accepting Section 8 — \(a.n ?? 1) listing\((a.n ?? 1) == 1 ? "" : "s") on AffordableHousing.com" + (a.p.map { ", from \(Formatters.dollars($0))/mo" } ?? ""))
                    .font(.se(19, .semibold))
            } else {
                Text("Searching with a housing voucher, like Section 8?").font(.se(19))
            }
            Button { openURL(URL(string: "https://findacrib.com/guide/rent-stabilized-tenant-rights/")!) } label: {
                Text("See tips").font(.se(19, .bold)).foregroundStyle(SE.royal)
            }.buttonStyle(.plain)
        }
        .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Color.white).padding(.bottom, 10)
    }

    /// Signed-in only, like the website since 2026-09-08: the open
    /// violations and complaints, plus this year's bedbug filings and rodent
    /// inspections from NYC Open Data. Signed out, the section says what is
    /// behind the account and sends the person to Profile to sign in.
    @ViewBuilder private var hpdBlock: some View {
        let v = b.h?.violations; let c = b.h?.complaints
        if !auth.isSignedIn {
            Text("HPD's open violations and complaints for this building, plus this year's bedbug filings and Health Department rodent inspections. Free with an account.")
                .font(.se(17)).foregroundStyle(SE.ink2)
            SEOutlineButton(title: "Sign in to see violations & inspections", icon: "person.crop.circle") { nav.tab = .profile }
                .accessibilityIdentifier("hpd-sign-in")
        } else {
            if v == nil && c == nil {
                Text("No HPD violation or complaint records on file.").font(.se(18)).foregroundStyle(SE.ink2)
            } else {
                // Each tile opens the full list on its own screen.
                HStack(spacing: 12) {
                    NavigationLink(value: Route.hpdRecords(b.bbl, .violations)) {
                        stat("Open violations", v?.open ?? 0, tone: (v?.open ?? 0) == 0 ? SE.good : ((v?.oc ?? 0) > 0 ? SE.bad : SE.warn))
                    }.buttonStyle(.plain).accessibilityIdentifier("open-violations")
                    NavigationLink(value: Route.hpdRecords(b.bbl, .complaints)) {
                        stat("Open complaints", c?.open ?? 0, tone: (c?.open ?? 0) == 0 ? SE.good : SE.warn)
                    }.buttonStyle(.plain).accessibilityIdentifier("open-complaints")
                }
            }
            // Bedbugs and rodents: red when something was found this year,
            // green when the year is clean, grey while loading or with no
            // record on file. Same rule as the site's buttons.
            HStack(spacing: 12) {
                NavigationLink(value: Route.hpdRecords(b.bbl, .bedbugs)) {
                    inspectionTile("Bedbug inspections", bedbugSummary, found: "with bedbugs", clean: "none found this year")
                }.buttonStyle(.plain).accessibilityIdentifier("bedbug-inspections")
                NavigationLink(value: Route.hpdRecords(b.bbl, .rodents)) {
                    inspectionTile("Rodent inspections", rodentSummary, found: "failed", clean: "none failed this year")
                }.buttonStyle(.plain).accessibilityIdentifier("rodent-inspections")
            }
            Text(inspectionsFailed ? "Couldn't reach NYC Open Data for the inspections just now. Tap a tile to try again." : "Tap a tile to see each one.")
                .font(.se(14)).foregroundStyle(SE.ink3)
            // The app boots from the slim building file, which carries only
            // the open counts; the class split, 12-month and all-time figures
            // are nil there, not zero. Show a row only when it has a number —
            // six "0" rows under "20 open" were a contradiction.
            if let v {
                VStack(alignment: .leading, spacing: 6) {
                    if let n = v.oa { nrow("Class A (non-hazardous) open", n) }
                    if let n = v.ob { nrow("Class B (hazardous) open", n) }
                    if let n = v.oc { nrow("Class C (immediately hazardous) open", n) }
                    if let n = v.last_12mo { nrow("Violations issued, last 12 months", n) }
                    if let n = v.total { nrow("Violations on record, all time", n) }
                    if let n = c?.total { nrow("Complaints, all time", n) }
                }.padding(.top, 6)
            }
            Text("From NYC HPD's open data. Class C means the city considers the condition immediately hazardous — heat, hot water, lead, pests. Bedbug filings are the landlord's own annual report; rodent inspections are the Health Department's.")
                .font(.se(15)).foregroundStyle(SE.ink3)
        }
    }

    private func loadInspections() async {
        guard auth.isSignedIn else { bedbugSummary = nil; rodentSummary = nil; return }
        inspectionsFailed = false
        async let bb = HPDRecords.bedbugs(bbl: b.bbl)
        async let ro = HPDRecords.rodents(bbl: b.bbl)
        do { bedbugSummary = HPDRecords.summary(bedbugs: try await bb) } catch { inspectionsFailed = true }
        do { rodentSummary = HPDRecords.summary(rodents: try await ro) } catch { inspectionsFailed = true }
    }

    /// A tile whose headline is the year's verdict, not a bare count: "none
    /// found this year" in green, "2 with bedbugs" in red, with the number of
    /// records on file underneath.
    private func inspectionTile(_ k: String, _ s: HPDRecords.InspectionSummary?, found: String, clean: String) -> some View {
        let tone: Color = s == nil ? SE.ink3 : (s!.clean ? SE.good : SE.bad)
        let head: String = s == nil ? (inspectionsFailed ? "—" : "…") : (s!.clean ? clean : "\(s!.problemsThisYear) \(found)")
        let sub: String = s == nil ? "" : (s!.total == 0 ? "no record on file" : "\(s!.total)\(s!.total >= HPDRecords.limit ? "+" : "") on file")
        return VStack(alignment: .leading, spacing: 2) {
            Text(k).font(.se(15, .semibold)).foregroundStyle(SE.ink2)
            Text(head).font(.se(17, .bold)).foregroundStyle(tone).lineLimit(2).minimumScaleFactor(0.85)
            Text(sub.isEmpty ? " " : sub).font(.se(13)).foregroundStyle(SE.ink3)
        }.frame(maxWidth: .infinity, minHeight: 92, alignment: .topLeading).padding(14).background(SE.canvas)
        .overlay(alignment: .topTrailing) { Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)).foregroundStyle(SE.ink3).padding(12) }
        .contentShape(Rectangle())
    }
    private func stat(_ k: String, _ n: Int, tone: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(n)").font(.se(34, .bold)).foregroundStyle(tone)
            Text(k).font(.se(15, .semibold)).foregroundStyle(SE.ink2)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(14).background(SE.canvas)
        .overlay(alignment: .topTrailing) { Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)).foregroundStyle(SE.ink3).padding(12) }
        .contentShape(Rectangle())
    }
    private func nrow(_ k: String, _ n: Int) -> some View {
        HStack { Text(k).font(.se(17)).foregroundStyle(SE.ink2); Spacer(); Text("\(n)").font(.se(17, .bold)) }
    }

    @ViewBuilder private var similarRail: some View {
        let sim = SearchEngine.similar(to: b, store: store)
        if !sim.isEmpty {
            VStack(alignment: .leading, spacing: 14) {
                Text("Nearby in \(b.neighborhood)").font(.se(30, .black)).padding(.horizontal, 16)
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        ForEach(sim) { s in
                            Button { nav.searchPath.append(.building(s.bbl)); pushOther(s) } label: {
                                VStack(alignment: .leading, spacing: 6) {
                                    BuildingImage(building: s, size: CGSize(width: 600, height: 400)).frame(width: 250, height: 150)
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(s.address).font(.se(19, .bold)).foregroundStyle(SE.royal).lineLimit(1)
                                        if let p = store.price(s) { Text("\(Formatters.dollars(p)) asking rent").font(.se(16, .bold)) }
                                        else if let e = store.estimate(s), e.count >= 3 { Text("\(Formatters.dollars(e[0]))–\(Formatters.dollars(e[2])) typical").font(.se(15)).foregroundStyle(SE.ink2) }
                                        Text("\(s.u.map { "\($0) units" } ?? "") · \(s.openViolations) open violations").font(.se(14)).foregroundStyle(SE.ink3)
                                    }.padding(10)
                                }
                                .frame(width: 250).seCard()
                            }.buttonStyle(.plain)
                        }
                    }.padding(.horizontal, 16)
                }
                Text("Nearest rent-stabilized buildings in the same neighborhood.").font(.se(15)).foregroundStyle(SE.ink3).padding(.horizontal, 16)
            }
            .padding(.vertical, 16).background(Color.white).padding(.bottom, 10)
        }
    }
    /// Similar-building taps come from whichever tab's stack we're on.
    private func pushOther(_ s: Building) {
        // nav.searchPath already handled above when on the Search tab; mirror for the others.
        switch nav.tab {
        case .search: break
        case .activity: nav.searchPath.removeLast(); nav.activityPath.append(.building(s.bbl))
        case .profile: nav.searchPath.removeLast(); nav.profilePath.append(.building(s.bbl))
        }
    }
}
