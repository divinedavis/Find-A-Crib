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

    var body: some View {
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
                    perk("phone.fill", "Managing-agent phone numbers", "The number HPD has on file for the company that runs the building — 11,000+ buildings.")
                    perk("bell.fill", "Saved searches & alerts", "Save any search; get an email when a stabilized building in it is advertised.")
                    perk("building.2.fill", "Landlord research", "Everything a landlord or agent owns, with its violation record, on findacrib.com.")
                    perk("globe", "Works on the website too", "One subscription, findacrib.com and the app.")

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
