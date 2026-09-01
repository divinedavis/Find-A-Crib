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
        .clipped()
        .task(id: building.bbl) { image = await ImageService.shared.image(for: building, size: size) }
    }
}

/// The results card, laid out like StreetEasy's listing card: photo with a
/// status badge, grey kicker, royal-blue address, price line, facts row,
/// attribution, Share + primary action.
struct BuildingCard: View {
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    @Environment(AppNav.self) private var nav
    let building: Building
    var onOpen: (() -> Void)? = nil

    private var b: Building { building }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            ZStack(alignment: .bottomTrailing) {
                BuildingImage(building: b).frame(height: 226).frame(maxWidth: .infinity)
                    .contentShape(Rectangle())
                    .onTapGesture { open() }
                if store.voucherAvail(b) != nil {
                    SEBadge(text: "Section 8", icon: "checkmark.seal.fill", fill: .white, ink: SE.ink)
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
                        .padding(12)
                        .allowsHitTesting(false)
                }
                statusBadge
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top) {
                    Text("Stabilized building in \(b.neighborhood)")
                        .font(.se(18, .semibold)).foregroundStyle(SE.ink2).lineLimit(1).minimumScaleFactor(0.85)
                    Spacer(minLength: 8)
                    HeartButton(on: activity.isSaved(b.bbl)) { activity.toggleSaved(b.bbl) }
                        .offset(x: 8, y: -6)
                }
                Button(action: open) {
                    Text(b.address).font(.se(27, .bold)).foregroundStyle(SE.royal).lineLimit(1).minimumScaleFactor(0.8)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }.buttonStyle(.plain).accessibilityIdentifier("card-address")

                priceLines

                HStack(spacing: 0) {
                    fact("bed.double", bedsText)
                    Rectangle().fill(SE.line).frame(width: 1, height: 26).padding(.horizontal, 12)
                    fact("building.2", "\(b.u.map { "\($0) unit\($0 == 1 ? "" : "s")" } ?? "– units")")
                    Rectangle().fill(SE.line).frame(width: 1, height: 26).padding(.horizontal, 12)
                    fact("calendar", b.yr.map { "Built \($0)" } ?? "Built –")
                }
                .padding(.top, 8)

                Text(attribution).font(.se(18)).foregroundStyle(b.openViolations > 0 ? SE.ink2 : SE.ink2).padding(.top, 4)

                HStack(spacing: 14) {
                    ShareLink(item: b.webURL, message: Text("\(b.address) — rent-stabilized building on Find A Crib")) {
                        HStack(spacing: 8) {
                            Image(systemName: "square.and.arrow.up").font(.system(size: 15, weight: .semibold))
                            Text("Share").font(.se(18, .bold))
                        }
                        .foregroundStyle(SE.royal).frame(maxWidth: .infinity).frame(height: 50)
                        .background(Color.white).overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line))
                    }
                    .frame(maxWidth: .infinity)
                    if let url = store.listingURL(b) {
                        Link(destination: url) {
                            Text("View listing").font(.se(18, .bold)).foregroundStyle(.white)
                                .frame(maxWidth: .infinity).frame(height: 50).background(SE.royal)
                        }.frame(maxWidth: 1000)
                    } else {
                        SEPrimaryButton(title: "Details") { open() }
                    }
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 10)
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
    private func push(_ r: Route) {
        switch nav.tab {
        case .search: nav.searchPath.append(r)
        case .activity: nav.activityPath.append(r)
        case .profile: nav.profilePath.append(r)
        }
    }

    @ViewBuilder private var statusBadge: some View {
        if store.price(b) != nil, let d = store.listings.updatedDate {
            SEBadge(text: "Listed (\(Formatters.mdy.string(from: d)))", fill: SE.badge.opacity(0.95))
        } else if let reg = b.h?.lastregistration, let d = ISO8601DateFormatter.ymd.date(from: reg) {
            SEBadge(text: "HPD registered (\(Formatters.mdy.string(from: d)))", fill: SE.badge.opacity(0.95))
        } else {
            SEBadge(text: "Rent stabilized", fill: SE.badge.opacity(0.95))
        }
    }

    @ViewBuilder private var priceLines: some View {
        if let p = store.price(b) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(Formatters.dollars(p)).font(.se(34, .bold)).foregroundStyle(SE.ink).lineLimit(1).layoutPriority(3)
                Text("asking rent").font(.se(20)).foregroundStyle(SE.ink2).lineLimit(1).layoutPriority(2)
                InfoDot().layoutPriority(2)
                Text("Advertised").font(.se(18)).foregroundStyle(SE.ink2).lineLimit(1).minimumScaleFactor(0.7)
            }
            let n = store.listingCount(b)
            if let est = store.estimate(b), est.count >= 3 {
                HStack(spacing: 6) {
                    Text("\(Formatters.dollars(est[0]))–\(Formatters.dollars(est[2]))").font(.se(18, .bold))
                    Text("typical for ZIP \(b.z ?? "")").font(.se(18)).foregroundStyle(SE.ink2)
                    InfoDot()
                }
            }
            Text("\(n) listing\(n == 1 ? "" : "s") · \(b.statusLine.isEmpty ? "Rent stabilized" : b.statusLine)")
                .font(.se(17)).foregroundStyle(SE.ink2).lineLimit(1)
        } else if let avail = store.voucherAvail(b), let p = avail.p {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("from \(Formatters.dollars(p))").font(.se(32, .bold)).foregroundStyle(SE.ink).lineLimit(1).layoutPriority(2)
                Text("voucher listing").font(.se(20)).foregroundStyle(SE.ink2).lineLimit(1)
            }
            Text("Landlord soliciting voucher tenants on AffordableHousing.com").font(.se(17)).foregroundStyle(SE.ink2)
        } else if let est = store.estimate(b), est.count >= 3 {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("\(Formatters.dollars(est[0]))–\(Formatters.dollars(est[2]))").font(.se(30, .bold)).foregroundStyle(SE.ink).lineLimit(1).layoutPriority(2)
                Text("typical rent").font(.se(20)).foregroundStyle(SE.ink2).lineLimit(1)
                InfoDot()
            }
            Text("HUD FY2026 fair market rent for ZIP \(b.z ?? ""), studio–2BR · not this building's rent")
                .font(.se(16)).foregroundStyle(SE.ink3)
        } else {
            Text("No recent listing").font(.se(22, .bold)).foregroundStyle(SE.ink2)
        }
    }

    private var bedsText: String {
        let bd = store.beds(b)
        if bd.isEmpty { return "– bed" }
        let s = bd.sorted().map { $0 == 0 ? "Studio" : "\($0)" }
        return s.count == 1 ? (bd[0] == 0 ? "Studio" : "\(bd[0]) bed") : "\(s.first!)–\(s.last!) bed"
    }

    private var attribution: String {
        let v = b.openViolations
        if v == 0 { return "No open HPD violations" }
        return "\(v) open HPD violation\(v == 1 ? "" : "s")" + ((b.h?.violations?.oc ?? 0) > 0 ? " · \(b.h!.violations!.oc!) class C" : "")
    }

    private func fact(_ icon: String, _ text: String) -> some View {
        HStack(spacing: 8) {
            Image(systemName: icon).font(.system(size: 17)).foregroundStyle(SE.ink2)
            Text(text).font(.se(20)).foregroundStyle(SE.ink).lineLimit(1).minimumScaleFactor(0.8)
        }
    }
}

extension ISO8601DateFormatter {
    static let ymd: DateFormatter = { let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.timeZone = TimeZone(identifier: "America/New_York"); return f }()
}
