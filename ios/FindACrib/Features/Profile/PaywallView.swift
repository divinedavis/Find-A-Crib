import SwiftUI

/// The Plus page (owner, 2026-10-03: "this is our opportunity to show users
/// what they get with plus"). Every AI button lands here when the person
/// doesn't have Plus — signed out too, instead of a bare "sign in under
/// Profile". The feature they tapped leads, then the rest; one button at
/// the bottom does the next step: sign in / create an account (in place,
/// the page stays open), then subscribe. Keeps the disclosures App Review
/// looks for (auto-renewal terms, Terms of Use, Privacy Policy).
struct PaywallView: View {
    @Environment(PlusStore.self) private var plus
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    /// What sent them here: "apply_help", "report_card", "ai_search", "profile", …
    var source = "other"
    /// Optional line under the lead feature ("for 1420 Stebbins Ave").
    var context: String? = nil
    @State private var showSignIn = false

    struct Perk: Identifiable {
        let id: String, icon: String, title: String, sub: String, example: String?
    }

    static let perks: [Perk] = [
        Perk(id: "apply_help", icon: "doc.text", title: "Help me apply",
             sub: "The agent's steps, the documents to gather and a ready-to-send email — for every re-rental.",
             example: "“1. Download the application… 2. Gather pay stubs… Email: Hi, I'm interested in unit 4B…”"),
        Perk(id: "ai_search", icon: "sparkles", title: "Search in plain words",
             sub: "Type what you want and the search sets every filter.",
             example: "“2 bed under $2,500 near Prospect Park, no violations”"),
        Perk(id: "rent_check", icon: "dollarsign.circle", title: "Is this rent fair?",
             sub: "Every advertised rent checked against the neighborhood and HUD's fair-market rent.",
             example: nil),
        Perk(id: "noads", icon: "nosign", title: "No ads", sub: "No ads in the app or on findacrib.com.", example: nil),
    ]

    private var ordered: [Perk] {
        guard let lead = Self.perks.first(where: { $0.id == source }) else { return Self.perks }
        return [lead] + Self.perks.filter { $0.id != source }
    }
    private var leads: Bool { Self.perks.contains { $0.id == source } }

    static let gradient = LinearGradient(colors: [Color(hex: 0x163C47), Color(hex: 0x266676), Color(hex: 0x3151C8)],
                                         startPoint: .topLeading, endPoint: .bottomTrailing)

    var body: some View {
        VStack(spacing: 0) {
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    hero
                    VStack(alignment: .leading, spacing: 14) {
                        ForEach(Array(ordered.enumerated()), id: \.element.id) { i, p in
                            perkCard(p, lead: i == 0 && leads)
                        }
                        disclosures
                    }
                    .padding(16)
                }
            }
            cta
        }
        .background(SE.canvas.ignoresSafeArea())
        .overlay(alignment: .topTrailing) {
            Button { dismiss() } label: {
                Image(systemName: "xmark").font(.system(size: 16, weight: .bold)).foregroundStyle(.white)
                    .frame(width: 36, height: 36).background(.white.opacity(0.18)).clipShape(Circle())
            }
            .buttonStyle(.plain).padding(14).accessibilityIdentifier("paywall-close").accessibilityLabel("Close")
        }
        .sheet(isPresented: $showSignIn) { EmailSignInView(offersSocialSignIn: true, heading: "Sign in for Plus") }
        .onChange(of: auth.isSignedIn) { _, on in
            if on { Analytics.shared.track("paywall_signed_in", ["source": source]) }
        }
        .onAppear {
            plus.source = source
            Analytics.shared.track("paywall_view", ["signed_in": auth.isSignedIn, "source": source])
        }
        .task { await plus.load() }
    }

    private var hero: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Image(systemName: "sparkles").font(.system(size: 20, weight: .bold))
                Text("FIND A CRIB PLUS").font(.se(14, .black)).tracking(1.2)
            }
            .foregroundStyle(.white.opacity(0.9))
            Text("Your apartment hunt, with an AI that reads the fine print")
                .font(.se(30, .black)).foregroundStyle(.white).fixedSize(horizontal: false, vertical: true)
            Text("Listings, rents and applications — read for you, in plain words.")
                .font(.se(17)).foregroundStyle(.white.opacity(0.88))
            // Apple 3.1.2: the billed amount stays the most prominent price;
            // the trial line is smaller, under it.
            Text("\(plus.priceText) / month · cancel anytime")
                .font(.se(15, .bold)).foregroundStyle(SE.navy)
                .padding(.horizontal, 12).padding(.vertical, 6).background(.white).clipShape(Capsule())
                .padding(.top, 4)
            if let t = plus.trial {
                Text("Your first \(t) is on us — then \(plus.priceText)/month.")
                    .font(.se(14, .semibold)).foregroundStyle(.white.opacity(0.9))
                    .accessibilityIdentifier("paywall-trial")
            }
        }
        .padding(.horizontal, 20).padding(.top, 56).padding(.bottom, 26)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Self.gradient)
    }

    private func perkCard(_ p: Perk, lead: Bool) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            if lead {
                Text(context.map { "WHAT YOU TAPPED · \($0.uppercased())" } ?? "WHAT YOU TAPPED")
                    .font(.se(12, .black)).tracking(0.8).foregroundStyle(SE.royal).lineLimit(1)
            }
            HStack(alignment: .top, spacing: 14) {
                Image(systemName: p.icon).font(.system(size: 18, weight: .bold)).foregroundStyle(.white)
                    .frame(width: 42, height: 42).background(Self.gradient).clipShape(RoundedRectangle(cornerRadius: 12))
                VStack(alignment: .leading, spacing: 4) {
                    Text(p.title).font(.se(19, .bold)).foregroundStyle(SE.ink)
                    Text(p.sub).font(.se(15)).foregroundStyle(SE.ink2).fixedSize(horizontal: false, vertical: true)
                }
            }
            if let ex = p.example, lead || p.id == "apply_help" {
                Text(ex).font(.se(14).italic()).foregroundStyle(SE.ink2)
                    .padding(10).frame(maxWidth: .infinity, alignment: .leading)
                    .background(SE.canvas).clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white)
        .clipShape(RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(lead ? SE.royal : SE.lineSoft, lineWidth: lead ? 2 : 1))
    }

    /// One button that does the next step.
    private var cta: some View {
        VStack(spacing: 8) {
            if auth.hasPlus {
                SEBadge(text: "You have Plus", icon: "checkmark.seal.fill", fill: SE.paleBlue, ink: SE.royal)
                SEPrimaryButton(title: "Done") { dismiss() }
            } else if !auth.isSignedIn {
                SEPrimaryButton(title: "Sign in or create an account", icon: "person.crop.circle") {
                    Analytics.shared.track("paywall_signin_click", ["source": source])
                    showSignIn = true
                }
                .accessibilityIdentifier("paywall-sign-in")
                Text("Step 1 of 2 — then choose Plus. Your account works on findacrib.com too.")
                    .font(.se(13)).foregroundStyle(SE.ink3).multilineTextAlignment(.center)
            } else {
                SEPrimaryButton(title: plus.busy ? "…" : (plus.trial.map { "Start your \($0) — then \(plus.priceText)/mo" } ?? "Get Plus — \(plus.priceText)/month"), icon: "sparkles") {
                    Task { await plus.purchase(); if auth.hasPlus { dismiss() } }
                }
                .disabled(plus.busy)
                .accessibilityIdentifier("paywall-subscribe")
                Button { Task { await plus.restore() } } label: {
                    Text("Restore purchases").font(.se(15, .semibold)).foregroundStyle(SE.royal)
                }.buttonStyle(.plain)
            }
            if let e = plus.error { Text(e).font(.se(14)).foregroundStyle(SE.bad) }
        }
        .padding(.horizontal, 16).padding(.top, 12).padding(.bottom, 8)
        .background(Color.white.shadow(color: .black.opacity(0.08), radius: 8, y: -2).ignoresSafeArea(edges: .bottom))
    }

    private var disclosures: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text((plus.trial.map { "The first \($0) costs nothing; \(plus.priceText) is charged to your Apple Account when it ends unless you cancel at least 24 hours before. " } ?? "Payment is charged to your Apple Account at confirmation. ")
                 + "The subscription renews automatically each month at \(plus.priceText) unless cancelled at least 24 hours before the end of the current period. Manage or cancel in Settings › Apple Account › Subscriptions.")
                .font(.se(13)).foregroundStyle(SE.ink3)
            HStack(spacing: 18) {
                Button("Terms of Use") { openURL(PlusStore.termsURL) }
                Button("Privacy Policy") { openURL(PlusStore.privacyURL) }
            }.font(.se(14, .semibold)).foregroundStyle(SE.royal)
        }
        .padding(.top, 6)
    }

    // No invite-a-friend button in the app (owner, 2026-10-01: "let's do
    // whatever makes Apple happy"). App Review 3.1.1 bars unlocking paid
    // features in-app by anything other than in-app purchase; the referral
    // (2 months of Plus) lives on findacrib.com, and the app honours Plus
    // however it was earned, which 3.1.3(b) allows.
}
