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
                    // The six perks (owner, 2026-10-01). Phone numbers, landlord
                    // research, saved searches and folders stay Plus but unlisted.
                    perk("bell.fill", "Lottery alerts", "The minute a Housing Connect or HCR lottery opens in your boroughs — a notification and an email.")
                    perk("figure.run", "Re-rental alerts", "When an HPD marketing agent re-rents an apartment in your boroughs — often first come, first served.")
                    perk("bed.double.fill", "Bedbug records", "Every bedbug filing a landlord made for the building, year by year.")
                    perk("hare.fill", "Rodent records", "The Health Department's rat inspections, building by building.")
                    perk("ticket.fill", "Your lotteries & re-rentals", "Every open one in your alert boroughs, soonest deadline first.")
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

                    // The referral route on every $4.99 prompt (owner, 2026-10-01).
                    if !auth.hasPlus { inviteRow }

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

    @State private var inviteURL: URL?
    @State private var inviteBusy = false
    @State private var inviteError: String?

    /// "Invite a friend — you both get 2 months of Plus": fetch the account's
    /// link, then the share sheet. Signed out, it says to sign in first.
    @ViewBuilder private var inviteRow: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let inviteURL {
                ShareLink(item: inviteURL, message: Text("Join me on Find A Crib — we both get 2 months of Plus, on the house.")) {
                    Label("Share your invite link", systemImage: "square.and.arrow.up")
                        .font(.se(17, .bold)).foregroundStyle(SE.royal)
                        .frame(maxWidth: .infinity).padding(.vertical, 14)
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.royal, lineWidth: 1.5))
                }
                .accessibilityIdentifier("paywall-refer-share")
                Text(inviteURL.absoluteString).font(.se(13)).foregroundStyle(SE.ink3).textSelection(.enabled)
            } else {
                Button {
                    guard auth.isSignedIn else { inviteError = "Sign in first, then invite a friend."; return }
                    inviteBusy = true; inviteError = nil
                    Task {
                        let url = await auth.referralLink()
                        inviteBusy = false
                        if let url { inviteURL = url; Analytics.shared.track("referral_open", ["via": "app_paywall", "source": source]) }
                        else { inviteError = "Couldn't make your link right now. Try again shortly." }
                    }
                } label: {
                    Text(inviteBusy ? "…" : "🎁 Or invite a friend — you both get 2 months of Plus")
                        .font(.se(17, .bold)).foregroundStyle(SE.royal).multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity).padding(.vertical, 14)
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.royal, lineWidth: 1.5))
                }
                .buttonStyle(.plain).disabled(inviteBusy)
                .accessibilityIdentifier("paywall-refer")
            }
            if let inviteError { Text(inviteError).font(.se(14)).foregroundStyle(SE.bad) }
            Text("Your friend gets 2 months when they create their account from your link, and so do you. Invite more friends and the months stack.")
                .font(.se(13)).foregroundStyle(SE.ink3)
        }
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
