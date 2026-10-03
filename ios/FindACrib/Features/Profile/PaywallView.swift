import SwiftUI

/// The Plus sheet, in the StreetEasy card idiom: navy header, one price, a
/// short list of what it unlocks, Subscribe, Restore, and the disclosures
/// App Review looks for (auto-renewal terms, Terms of Use, Privacy Policy).
struct PaywallView: View {
    @Environment(PlusStore.self) private var plus
    @Environment(AuthService.self) private var auth
    @Environment(AppNav.self) private var nav
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    /// What sent them here: "phone", "alerts", "profile", … (dashboard pay conversion).
    var source = "other"

    var body: some View {
        content.onAppear {
            plus.source = source
            Analytics.shared.track("paywall_view", ["signed_in": auth.isSignedIn, "source": source])
        }
    }

    private var content: some View {
        VStack(spacing: 0) {
            NavyHeader {
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text("Find A Crib Plus").font(.se(26, .bold)).foregroundStyle(.white)
                        Text("\(plus.priceText) per month · cancel anytime").font(.se(15, .semibold)).foregroundStyle(.white.opacity(0.85))
                    }
                    Spacer()
                    Button { dismiss() } label: {
                        Image(systemName: "xmark").font(.system(size: 18, weight: .bold)).foregroundStyle(.white).frame(width: 40, height: 40)
                    }.buttonStyle(.plain).accessibilityIdentifier("paywall-close")
                }
                .padding(.horizontal, 16).padding(.top, 14).padding(.bottom, 16)
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    // The four perks (owner, 2026-10-01: alerts left Plus the same
                    // day). Landlord research, saved searches and folders stay
                    // Plus but unlisted.
                    // Plus = the AI features while everything else is free
                    // (owner, 2026-10-03); paying members also keep no ads.
                    perk("sparkles", "Search in plain words", "“2 bed under $2,500 near Prospect Park, no violations” — and the search sets every filter.")
                    perk("doc.text.magnifyingglass", "Landlord report card", "Every building's city records — violations, pests, evictions, housing court — read for you in plain words.")
                    perk("bubble.left.and.text.bubble.right", "Ask about this building", "Answers from the city's records, with the source for each fact.")
                    perk("doc.text", "Help me apply", "The steps, the documents and a ready-to-send email to the agent, for every re-rental.")
                    perk("dollarsign.circle", "Is this rent fair?", "Every advertised rent checked against the neighborhood and HUD's fair-market rent.")
                    perk("nosign", "No ads", "No ads in the app or on findacrib.com.")

                    if auth.hasPlus {
                        SEBadge(text: "You have Plus", icon: "checkmark.seal.fill", fill: SE.paleBlue, ink: SE.royal)
                    } else if !auth.isSignedIn {
                        Text("Sign in first so Plus is tied to your account.").font(.se(16)).foregroundStyle(SE.ink2)
                        SEPrimaryButton(title: "Sign in") { dismiss(); nav.tab = .profile }
                    } else {
                        SEPrimaryButton(title: plus.busy ? "…" : "Subscribe for \(plus.priceText)/month") { Task { await plus.purchase(); if auth.hasPlus { dismiss() } } }
                            .disabled(plus.busy)
                            .accessibilityIdentifier("paywall-subscribe")
                        Button { Task { await plus.restore() } } label: {
                            Text("Restore purchases").font(.se(17, .semibold)).foregroundStyle(SE.royal).frame(maxWidth: .infinity)
                        }.buttonStyle(.plain)
                    }
                    if let e = plus.error { Text(e).font(.se(14)).foregroundStyle(SE.bad) }


                    Text("Payment is charged to your Apple Account at confirmation. The subscription renews automatically each month at \(plus.priceText) unless cancelled at least 24 hours before the end of the current period. Manage or cancel in Settings › Apple Account › Subscriptions.")
                        .font(.se(13)).foregroundStyle(SE.ink3)
                    HStack(spacing: 18) {
                        Button("Terms of Use") { openURL(PlusStore.termsURL) }
                        Button("Privacy Policy") { openURL(PlusStore.privacyURL) }
                    }.font(.se(14, .semibold)).foregroundStyle(SE.royal)
                }
                .padding(16)
            }
        }
        .background(Color.white)
        .task { await plus.load() }
    }

    // No invite-a-friend button in the app (owner, 2026-10-01: "let's do
    // whatever makes Apple happy"). App Review 3.1.1 bars unlocking paid
    // features in-app by anything other than in-app purchase; the referral
    // (2 months of Plus) lives on findacrib.com, and the app honours Plus
    // however it was earned, which 3.1.3(b) allows.

    private func perk(_ icon: String, _ title: String, _ sub: String) -> some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: icon).font(.system(size: 18, weight: .bold)).foregroundStyle(SE.royal).frame(width: 40, height: 40).background(SE.paleBlue).clipShape(Circle())
            VStack(alignment: .leading, spacing: 3) {
                Text(title).font(.se(18, .bold))
                Text(sub).font(.se(15)).foregroundStyle(SE.ink2)
            }
        }
    }
}
