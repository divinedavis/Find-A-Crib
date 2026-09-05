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
                        Text("Registered with NYS Homes and Community Renewal as rent stabilized (2024 building file). Rents in stabilized units rise only by the Rent Guidelines Board's annual percentage, and tenants have a right to renew.")
                            .font(.se(16)).foregroundStyle(SE.ink2).padding(.top, 12)
                        Button { openURL(URL(string: "https://findacrib.com/guide/what-is-rent-stabilization/")!) } label: {
                            Text("What rent stabilization means for you").font(.se(19, .bold)).foregroundStyle(SE.royal)
                        }.buttonStyle(.plain).padding(.top, 12)
                    }

                    section("Rent") { rentBlock }

                    section("Managing agent") { agentBlock }

                    voucherCard

                    section("Violations & complaints") { hpdBlock }

                    similarRail
                    }

                    Text("Sources: NYS HCR 2024 rent-stabilized building file · NYC HPD violations and complaints · HUD FY2026 Small-Area Fair Market Rents · Recently advertised rents via Zumper. Find A Crib is not a broker and does not list apartments.")
                        .font(.se(14)).foregroundStyle(SE.ink3).padding(16)
                    Color.clear.frame(height: 100)
                }
            }
            .background(SE.canvas)
        }
        .background(SE.canvas)
        .safeAreaInset(edge: .bottom) {
            HStack(spacing: 12) {
                ShareLink(item: b.webURL) {
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
                    SEPrimaryButton(title: "Open on findacrib.com") { openURL(b.webURL) }
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
                    ShareLink(item: b.webURL) { Label("Share", systemImage: "square.and.arrow.up") }
                    Button { openURL(b.webURL) } label: { Label("Open on findacrib.com", systemImage: "safari") }
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
        var l = ["RENT STABILIZED"]
        for s in b.s ?? [] where !s.uppercased().contains("MULTIPLE DWELLING") { l.append(s.uppercased()) }
        if let z = b.z { l.append("\(b.borough.uppercased()) · ZIP \(z)") }
        if store.voucherBuilding(b) != nil { l.append("SUBSIDIZED / VOUCHER-FRIENDLY BUILDING") }
        if let r = b.h?.lastregistration { l.append("HPD REGISTRATION \(r)") }
        return l
    }

    @ViewBuilder private var rentBlock: some View {
        if let p = store.price(b) {
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

    @ViewBuilder private var hpdBlock: some View {
        let v = b.h?.violations; let c = b.h?.complaints
        if v == nil && c == nil {
            Text("No HPD violation or complaint records on file.").font(.se(18)).foregroundStyle(SE.ink2)
        } else {
            HStack(spacing: 12) {
                stat("Open violations", v?.open ?? 0, tone: (v?.open ?? 0) == 0 ? SE.good : ((v?.oc ?? 0) > 0 ? SE.bad : SE.warn))
                stat("Open complaints", c?.open ?? 0, tone: (c?.open ?? 0) == 0 ? SE.good : SE.warn)
            }
            if let v {
                VStack(alignment: .leading, spacing: 6) {
                    nrow("Class A (non-hazardous) open", v.oa ?? 0)
                    nrow("Class B (hazardous) open", v.ob ?? 0)
                    nrow("Class C (immediately hazardous) open", v.oc ?? 0)
                    nrow("Violations issued, last 12 months", v.last_12mo ?? 0)
                    nrow("Violations on record, all time", v.total ?? 0)
                    if let c { nrow("Complaints, all time", c.total ?? 0) }
                }.padding(.top, 6)
            }
            Text("From NYC HPD's open data. Class C means the city considers the condition immediately hazardous — heat, hot water, lead, pests.")
                .font(.se(15)).foregroundStyle(SE.ink3)
        }
    }
    private func stat(_ k: String, _ n: Int, tone: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text("\(n)").font(.se(34, .bold)).foregroundStyle(tone)
            Text(k).font(.se(15, .semibold)).foregroundStyle(SE.ink2)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(14).background(SE.canvas)
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
