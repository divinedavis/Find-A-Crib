import SwiftUI
import AuthenticationServices

struct ProfileView: View {
    @Environment(DataStore.self) private var store
    @Environment(Activity.self) private var activity
    @Environment(AuthService.self) private var auth
    @Environment(AppNav.self) private var nav
    @Environment(\.openURL) private var openURL
    @State private var confirmDelete = false
    @State private var showPaywall = false
    /// Which email sign-in is open. One value, so the sheet can't open with
    /// a stale mode: two flags set together opened the plain sheet first,
    /// which focused Email (2026-10-15, caught by the Profile UI test).
    @State private var emailSheet: EmailSheet?
    enum EmailSheet: Identifiable { case plain, alerts; var id: Self { self } }
    /// The sign-in sheet was opened to set up alerts (not by "Continue with
    /// email"): show Apple/Google first and don't raise the keyboard.
    @State private var showAlerts = false
    @State private var confirmTurnOff = false
    @State private var turnOffFailed = false
    @State private var showPacket = false
    @State private var showBrokerFee = false
    @State private var showLeaseReview = false
    @State private var homeTool: HomeTool?
    @Environment(PlusStore.self) private var plus
    @AppStorage("hereTo") private var hereTo = "Rent"
    @AppStorage(HolidayIcon.settingKey) private var holidayIcons = true
    @AppStorage("homeBorough") private var homeBorough = "Brooklyn"
    @State private var refreshing = false
    @State private var shareUsage = Analytics.shared.enabled

    var body: some View {
        VStack(spacing: 0) {
            NavyHeader {
                Text("Profile").font(.se(24, .bold)).foregroundStyle(.white)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16).padding(.bottom, 12)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text("Every rent-stabilized building in New York City, in your pocket.")
                        .font(.se(17)).foregroundStyle(SE.ink).frame(maxWidth: .infinity).padding(14).background(SE.paleBand)

                    // identity
                    VStack(alignment: .leading, spacing: 14) {
                        HStack(alignment: .top, spacing: 16) {
                            ZStack {
                                Circle().fill(SE.badge).frame(width: 74, height: 74)
                                Image(systemName: "person.fill").font(.system(size: 34)).foregroundStyle(SE.ink3).accessibilityHidden(true)
                            }
                            VStack(alignment: .leading, spacing: 4) {
                                if auth.isSignedIn {
                                    Text(auth.email?.components(separatedBy: "@").first?.capitalized ?? String(localized: "Signed in")).font(.se(30, .bold)).lineLimit(1).minimumScaleFactor(0.7)
                                    Text(auth.email ?? "").font(.se(16)).foregroundStyle(SE.ink2).lineLimit(1)
                                    if auth.hasPlus {
                                        SEBadge(text: String(localized: "Find A Crib Plus"), icon: "star.fill", fill: SE.paleBlue, ink: SE.royal)
                                    }
                                } else {
                                    Text("Guest").font(.se(30, .bold))
                                    Text("Sign in to sync your saves and see managing agents.").font(.se(16)).foregroundStyle(SE.ink2)
                                }
                            }
                        }
                        if auth.isSignedIn {
                            HStack(spacing: 14) {
                                Button { Task { await auth.signOut() } } label: {
                                    Text("Sign out").font(.se(18, .bold)).foregroundStyle(SE.royal)
                                }.buttonStyle(.plain).accessibilityIdentifier("sign-out")
                                Spacer()
                                Button(role: .destructive) { confirmDelete = true } label: {
                                    Text("Delete account").font(.se(16, .semibold)).foregroundStyle(SE.bad)
                                }.buttonStyle(.plain).accessibilityIdentifier("delete-account")
                            }
                            if auth.hasPlus {
                                Button { Task { await plus.manage() } } label: {
                                    Text("Manage subscription").font(.se(17, .semibold)).foregroundStyle(SE.royal)
                                }.buttonStyle(.plain)
                            } else {   // Plus = the AI features (2026-10-03)
                                SEPrimaryButton(title: String(localized: "Get Find A Crib Plus · \(plus.priceText)/mo"), icon: "star.fill", fill: SE.navy) { showPaywall = true }
                                    .accessibilityIdentifier("get-plus")
                                Text("Real-time alerts (re-rentals go first come, first served), plain-language search, Help me apply, Is this rent fair?, no ads." + (plus.trial.map { String(localized: " Your first \($0) is on us.") } ?? ""))
                                    .font(.se(15)).foregroundStyle(SE.ink3)
                            }
                        } else if auth.configured {
                            VStack(spacing: 10) {
                                SocialSignInButtons()
                                Button { emailSheet = .plain } label: {
                                    HStack(spacing: 10) {
                                        Image(systemName: "envelope.fill").font(.system(size: 16, weight: .bold)).foregroundStyle(SE.royal)
                                        Text("Continue with email").font(.se(18, .semibold)).foregroundStyle(SE.ink)
                                    }
                                    .frame(maxWidth: .infinity).frame(height: 50)
                                    .background(Color.white).overlay(RoundedRectangle(cornerRadius: 6).stroke(SE.line))
                                }
                                .buttonStyle(.plain).accessibilityIdentifier("sign-in-email").disabled(auth.busy)
                                if auth.busy { ProgressView().tint(SE.royal) }
                                if let e = auth.error { Text(e).font(.se(14)).foregroundStyle(SE.bad) }
                            }
                            Text("Your saves on this phone merge into the account.")
                                .font(.se(14)).foregroundStyle(SE.ink3)
                        }
                    }.padding(16)
                    .sheet(isPresented: $showPaywall) { PaywallView(source: "profile") }
                    .sheet(item: $emailSheet) { EmailSignInView(offersSocialSignIn: $0 == .alerts, forAlerts: $0 == .alerts) }
                    .sheet(isPresented: $showAlerts) { AlertsSheet() }
                    .alert(String(localized: "Turn off alerts?"), isPresented: $confirmTurnOff) {
                        Button("Turn off alerts", role: .destructive) {
                            Task { turnOffFailed = !(await LotteryFeed.shared.turnOff()) }
                        }
                        Button("Keep them", role: .cancel) {}
                    } message: {
                        Text("You'll stop getting notifications and emails about new lotteries and re-rentals.")
                    }
                    .sheet(isPresented: $showPacket) { PacketView() }
                    .sheet(isPresented: $showBrokerFee) { BrokerFeeView() }
                    .sheet(isPresented: $showLeaseReview) { LeaseReviewView() }
                    .sheet(item: $homeTool) { t in
                        switch t {
                        case .repair: RepairView()
                        case .rentIncrease: RentIncreaseView()
                        case .rights: RightsView()
                        case .renewal: RenewalView()
                        }
                    }
                    .onChange(of: nav.showPaywall) { _, on in if on { showPaywall = true; nav.showPaywall = false } }
                    .onChange(of: nav.openTool) { _, t in if let t { homeTool = t; nav.openTool = nil } }
                    .onChange(of: nav.openBrokerFee) { _, on in if on { showBrokerFee = true; nav.openBrokerFee = false } }
                    // The notifications card sends people here to set alerts up.
                    // Signed out, the sign-in sheet comes first and the alerts
                    // sheet follows once there is an account.
                    .onChange(of: nav.showAlerts) { _, on in
                        if on { if auth.isSignedIn { showAlerts = true; nav.showAlerts = false } else { emailSheet = .alerts } }
                    }
                    .onChange(of: auth.isSignedIn) { _, on in
                        if on, nav.showAlerts { showAlerts = true; nav.showAlerts = false }
                    }
                    .onAppear {
                        if nav.showPaywall { showPaywall = true; nav.showPaywall = false }
                        if let t = nav.openTool { homeTool = t; nav.openTool = nil }
                        if nav.openBrokerFee { showBrokerFee = true; nav.openBrokerFee = false }
                        if nav.showAlerts { if auth.isSignedIn { showAlerts = true; nav.showAlerts = false } else { emailSheet = .alerts } }
                    }
                    .alert(String(localized: "Delete your account?"), isPresented: $confirmDelete) {
                        Button("Delete", role: .destructive) { Task { await auth.deleteAccount() } }
                        Button("Cancel", role: .cancel) {}
                    } message: { Text("Removes your account and its saved buildings on findacrib.com. This can't be undone.") }

                    Divider()
                    settingRow(String(localized: "I'm here to")) {
                        Picker("", selection: $hereTo) { ForEach(["Rent", "Research a building", "Organize tenants"], id: \.self) { Text($0) } }
                            .pickerStyle(.menu).tint(SE.ink).font(.se(18))
                    }
                    settingRow(String(localized: "Home borough")) {
                        Picker("", selection: $homeBorough) { ForEach(Borough.all.map(\.name), id: \.self) { Text($0) } }
                            .pickerStyle(.menu).tint(SE.royal).font(.se(18))
                    }
                    settingRow(String(localized: "Saved buildings")) { Text("\(activity.saved.count)" + (auth.isSignedIn ? String(localized: " · synced") : "")).font(.se(18, .bold)) }
                    settingRow(String(localized: "Saved searches")) { Text("\(activity.savedSearches.count)").font(.se(18, .bold)) }
                    // The site's borough alerts — lotteries, re-rentals and
                    // voucher listings by borough, rent cap and income — set
                    // up or changed from here, not only from a results list.
                    settingRow(String(localized: "Alerts")) {
                        if auth.isSignedIn {
                            Button { showAlerts = true } label: {
                                HStack(spacing: 4) { Text("Set up or change").font(.se(18, .semibold)); Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)) }
                                    .foregroundStyle(SE.royal)
                            }.buttonStyle(.plain).accessibilityIdentifier("profile-alerts")
                        } else {
                            // A link like its neighbours, not grey text (owner, 2026-10-15:
                            // "alerts sign in to set up is grey"): opens the alerts sign-in.
                            Button { emailSheet = .alerts } label: {
                                HStack(spacing: 4) { Text("Sign in to set up").font(.se(18, .semibold)); Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)) }
                                    .foregroundStyle(SE.royal)
                            }.buttonStyle(.plain).accessibilityIdentifier("profile-alerts-signin")
                        }
                    }
                    // Turn off moved here from the Lotteries card, which is gone
                    // once alerts are on (owner, 2026-10-13).
                    if LotteryFeed.shared.subscribed {   // only ever true signed in (or --lotteries-demo)
                        // Flexible text with layout priority: a fixed-size
                        // "Turn off" at 18 pt was reported as clipped text by the
                        // accessibility audit on iPhone and iPad.
                        settingRow(String(localized: "Alerts are on")) {
                            Button { confirmTurnOff = true } label: {
                                HStack(spacing: 4) { Text(turnOffFailed ? String(localized: "Try again") : String(localized: "Turn off alerts")).font(.se(17, .semibold)).layoutPriority(1); Image(systemName: "bell.slash").font(.system(size: 13, weight: .bold)) }
                                    .foregroundStyle(turnOffFailed ? SE.bad : SE.royal)
                            }.buttonStyle(.plain).accessibilityIdentifier("profile-alerts-off")
                        }
                    }
                    // Renter tools (owner, 2026-10-12): the website's Broker fee
                    // check and Lease review, here too. Plus; the sheets ask.
                    settingRow(String(localized: "Broker fee check")) {
                        Button { showBrokerFee = true } label: {
                            HStack(spacing: 4) { Text("Check a fee").font(.se(18, .semibold)); Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)) }
                                .foregroundStyle(SE.royal)
                        }.buttonStyle(.plain).accessibilityIdentifier("profile-broker-fee")
                    }
                    settingRow(String(localized: "Lease review")) {
                        Button { showLeaseReview = true } label: {
                            HStack(spacing: 4) { Text("Review a lease").font(.se(18, .semibold)); Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)) }
                                .foregroundStyle(SE.royal)
                        }.buttonStyle(.plain).accessibilityIdentifier("profile-lease-review")
                    }
                    // Already have a place? (owner, 2026-10-13): repairs and rent
                    // checks are free with an account, rights are public, the
                    // Renewal coach and the ✨ drafts are Plus — the sheets ask.
                    Text("Already have a place?").font(.se(13, .bold)).foregroundStyle(SE.ink3).textCase(.uppercase)
                        .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 16).padding(.top, 8)
                    ForEach(HomeTool.allCases) { t in
                        settingRow(t.title) {
                            Button { homeTool = t } label: {
                                HStack(spacing: 4) { Text(t.action).font(.se(18, .semibold)).layoutPriority(1); Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)) }
                                    .foregroundStyle(SE.royal)
                            }.buttonStyle(.plain).accessibilityIdentifier("profile-\(t.rawValue)")
                        }
                    }
                    // Application packet (2026-10-03): on this phone, open to all.
                    settingRow(String(localized: "Application packet")) {
                        Button { showPacket = true } label: {
                            HStack(spacing: 4) { Text(Packet.shared.docs.isEmpty ? String(localized: "Set up") : String(localized: "\(Packet.shared.docs.count) documents")).font(.se(18, .semibold)); Image(systemName: "chevron.right").font(.system(size: 13, weight: .bold)) }
                                .foregroundStyle(SE.royal)
                        }.buttonStyle(.plain).accessibilityIdentifier("profile-packet")
                    }
                    // Where alerts land besides email. Denied in Settings can only be
                    // undone in Settings, so that is where the row sends people.
                    settingRow(String(localized: "Push alerts")) {
                        switch PushService.shared.status {
                        case .authorized, .provisional, .ephemeral:
                            let ok = PushService.stateLine(status: PushService.shared.status, registration: PushService.shared.registration).ok
                            Text(ok ? String(localized: "On") : String(localized: "Allowed · not connected")).font(.se(18, .bold)).foregroundStyle(ok ? SE.good : SE.warn)
                        case .denied:
                            Button { UIApplication.shared.open(URL(string: UIApplication.openSettingsURLString)!) } label: {
                                HStack(spacing: 4) { Text("Off · turn on in Settings").font(.se(16, .semibold)); Image(systemName: "arrow.up.right").font(.system(size: 12, weight: .bold)) }
                                    .foregroundStyle(SE.royal)
                            }.buttonStyle(.plain)
                        default:
                            Text(auth.isSignedIn ? String(localized: "Asked when you turn on alerts") : String(localized: "Sign in and turn on alerts")).font(.se(16)).foregroundStyle(SE.ink3)
                        }
                    }
                    .accessibilityIdentifier("profile-push")
                    .task { await PushService.shared.refreshStatus() }
                    // A link to the App Store's own review page. Apple's rule is
                    // that the in-app rating SHEET may not hang off a button; a
                    // link to the store page is fine, and is the only way to rate
                    // on demand once the sheet has had its three asks a year.
                    // Picked here, not in Settings: openSettingsURLString reopens
                    // Settings wherever it was left, so it often missed Find A
                    // Crib › Language (owner, 2026-10-17). See AppLanguage.
                    settingRow(String(localized: "Language")) {
                        Menu {
                            Picker(String(localized: "Language"), selection: Binding(get: { AppLanguage.shared.chosen ?? "" }, set: { AppLanguage.shared.choose($0.isEmpty ? nil : $0) })) {
                                Text("iPhone setting").tag("")
                                ForEach(AppLanguage.supported, id: \.self) { Text(AppLanguage.name($0)).tag($0) }
                            }
                        } label: {
                            HStack(spacing: 4) { Text(AppLanguage.name(AppLanguage.shared.current)).font(.se(18, .semibold)); Image(systemName: "chevron.up.chevron.down").font(.system(size: 13, weight: .bold)) }
                                .foregroundStyle(SE.royal)
                        }.accessibilityIdentifier("profile-language")
                    }
                    settingRow(String(localized: "Rate Find A Crib")) {
                        Button { ReviewPrompt.shared.openWriteReview() } label: {
                            HStack(spacing: 4) { Text("On the App Store").font(.se(18, .semibold)); Image(systemName: "arrow.up.right").font(.system(size: 13, weight: .bold)) }
                                .foregroundStyle(SE.royal)
                        }.buttonStyle(.plain).accessibilityIdentifier("profile-rate")
                    }

                    // data
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Data").font(.se(22, .bold))
                        dataRow(String(localized: "Rent-stabilized buildings"), store.buildings.count.formatted())
                        dataRow(String(localized: "Voucher-friendly buildings"), (store.s8.bldg.count + store.s8.avail.count).formatted())
                        dataRow(String(localized: "HCR lotteries & waitlists"), store.hcr.listings.count.formatted())
                        dataRow(String(localized: "Data as of"), store.dataAsOf.map(Formatters.long.string) ?? "–")
                        Button {
                            refreshing = true
                            Task { await store.refresh(); refreshing = false }
                        } label: {
                            HStack(spacing: 8) {
                                if refreshing { ProgressView().tint(SE.royal) }
                                Text(refreshing ? String(localized: "Checking findacrib.com…") : String(localized: "Refresh data")).font(.se(18, .bold)).foregroundStyle(SE.royal)
                            }
                        }.buttonStyle(.plain).disabled(refreshing)
                    }
                    .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(SE.canvas)

                    // Privacy: one switch, in the menu where settings belong —
                    // never a prompt on the way in.
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Privacy").font(.se(22, .bold))
                        Toggle(isOn: $shareUsage) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text("Share anonymous usage").font(.se(18)).foregroundStyle(SE.ink)
                                Text("Which screens get used, so the app can be improved. Never what you type, never sold, no advertising.")
                                    .font(.se(14)).foregroundStyle(SE.ink3)
                            }
                        }
                        .tint(SE.royal)
                        .accessibilityIdentifier("profile-share-usage")
                        .onChange(of: shareUsage) { _, on in
                            if !on { Analytics.shared.track("usage_optout") }
                            Analytics.shared.enabled = on
                            if on { Analytics.shared.track("usage_optin") }
                        }
                    }
                    .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(SE.canvas)

                    // The Home Screen icon in the day's colours on holidays,
                    // on by default as on Marracat (owner, 2026-10-23).
                    VStack(alignment: .leading, spacing: 8) {
                        Text("App icon").font(.se(22, .bold))
                        Toggle(isOn: $holidayIcons) {
                            VStack(alignment: .leading, spacing: 3) {
                                Text("Holiday app icons").font(.se(18)).foregroundStyle(SE.ink)
                                Text("The icon on your Home Screen wears each holiday's colours, then goes back. iOS tells you each time it changes.")
                                    .font(.se(14)).foregroundStyle(SE.ink3)
                            }
                        }
                        .tint(SE.royal)
                        .accessibilityIdentifier("profile-holiday-icons")
                        .onChange(of: holidayIcons) { _, _ in HolidayIcon.apply() }
                    }
                    .padding(16).frame(maxWidth: .infinity, alignment: .leading).background(SE.canvas)

                    VStack(alignment: .leading, spacing: 0) {
                        Text("About").font(.se(22, .bold)).padding(.horizontal, 16).padding(.top, 16).padding(.bottom, 6)
                        linkRow("findacrib.com", "https://findacrib.com/")
                        linkRow(String(localized: "What is rent stabilization?"), "https://findacrib.com/guide/what-is-rent-stabilization/")
                        linkRow(String(localized: "Is my apartment rent stabilized?"), "https://findacrib.com/guide/is-my-apartment-rent-stabilized/")
                        linkRow(String(localized: "Tenant rights"), "https://findacrib.com/guide/rent-stabilized-tenant-rights/")
                        linkRow(String(localized: "Deed theft: warning signs and how to report it"), "https://findacrib.com/guide/deed-theft-nyc/")
                        linkRow(String(localized: "Developer API"), "https://findacrib.com/developers")
                    }
                    Text("Find A Crib \(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "") (\(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "")) · Not a broker. Building data from NYS HCR and NYC HPD open data.")
                        .font(.se(13)).foregroundStyle(SE.ink3).padding(16)
                    Color.clear.frame(height: 100)
                }
                .readableColumn()
            }
            .background(Color.white)
        }
        .background(Color.white)
    }

    private func settingRow<C: View>(_ k: String, @ViewBuilder _ v: () -> C) -> some View {
        VStack(spacing: 0) {
            HStack { Text(k).font(.se(19, .semibold)).foregroundStyle(SE.ink2); Spacer(); v() }
                .padding(.horizontal, 16).frame(height: 54)
            Divider().padding(.leading, 16)
        }
    }
    private func dataRow(_ k: String, _ v: String) -> some View {
        HStack { Text(k).font(.se(17)).foregroundStyle(SE.ink2); Spacer(); Text(v).font(.se(17, .bold)) }
    }
    private func linkRow(_ t: String, _ url: String) -> some View {
        Button { openURL(URL(string: url)!) } label: {
            HStack { Text(t).font(.se(18)).foregroundStyle(SE.ink); Spacer(); Image(systemName: "arrow.up.right").font(.system(size: 13, weight: .bold)).foregroundStyle(SE.ink3) }
                .padding(.horizontal, 16).frame(height: 50)
        }.buttonStyle(.plain)
    }
}


/// Google's four-colour "G", drawn so the button needs no image asset.
struct GoogleG: View {
    var body: some View {
        ZStack {
            Circle().trim(from: 0.05, to: 0.30).stroke(Color(hex: 0xEA4335), lineWidth: 4).rotationEffect(.degrees(180))
            Circle().trim(from: 0.30, to: 0.55).stroke(Color(hex: 0xFBBC05), lineWidth: 4).rotationEffect(.degrees(180))
            Circle().trim(from: 0.55, to: 0.80).stroke(Color(hex: 0x34A853), lineWidth: 4).rotationEffect(.degrees(180))
            Circle().trim(from: 0.80, to: 1.0).stroke(Color(hex: 0x4285F4), lineWidth: 4).rotationEffect(.degrees(180))
            Rectangle().fill(Color(hex: 0x4285F4)).frame(width: 9, height: 4).offset(x: 4.5)
        }
        .padding(2)
    }
}

/// Profile's "Already have a place?" rows (HomeTools.swift).
enum HomeTool: String, CaseIterable, Identifiable {
    case repair, rentIncrease = "rent-increase", rights, renewal
    var id: String { rawValue }
    var title: String {
        switch self { case .repair: String(localized: "Repairs"); case .rentIncrease: String(localized: "Rent increase"); case .rights: String(localized: "Your rights"); case .renewal: String(localized: "Renewal coach") }
    }
    var action: String {
        switch self { case .repair: String(localized: "Get one made"); case .rentIncrease: String(localized: "Is it legal?"); case .rights: String(localized: "Know them"); case .renewal: String(localized: "Plan it") }
    }
}
