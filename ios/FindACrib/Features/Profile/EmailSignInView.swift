import SwiftUI

/// Email + password sign-in for the accounts people already made on the
/// website, with sign-up and "Forgot password?" — the reset link goes to
/// findacrib.com/reset/. Same rules as the site: 8+ characters, no
/// verification step on sign-up.
struct EmailSignInView: View {
    var offersSocialSignIn = false
    /// Overrides the sign-in title (the Plus page says "Sign in for Plus").
    var heading: String? = nil
    /// Opened from an alerts button: a box above Apple/Google says what the
    /// alerts are, and stands in for the findacrib.com line, which drops to a
    /// footnote so the email links still fit on the first screen.
    var forAlerts = false
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @State private var email = ""
    @State private var password = ""
    @State private var confirm = ""
    @State private var creating = false
    @State private var notice: String?
    @State private var showPlus = false
    @FocusState private var focus: Field?
    enum Field { case email, password, confirm }

    var body: some View { content.onAppear { Analytics.shared.track("signin_view", ["for": offersSocialSignIn ? "alerts" : "profile"]) } }

    private var content: some View {
        NavigationStack {
          ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(creating ? "Create account" : (heading ?? (offersSocialSignIn ? "Sign in for alerts" : "Sign in with email"))).font(.se(26, .bold))
                    if forAlerts && !creating {
                        AlertsPromiseBox { showPlus = true }
                    } else {
                        Text(creating ? "No verification email — you're in as soon as you tap Create." : "The account you use on findacrib.com works here.")
                            .font(.se(15)).foregroundStyle(SE.ink2)
                    }

                    if offersSocialSignIn, auth.configured {
                        SocialSignInButtons { focus = nil; notice = nil }
                        HStack(spacing: 12) {
                            Rectangle().fill(SE.lineSoft).frame(height: 1)
                            Text("or continue with email").font(.se(14)).foregroundStyle(SE.ink2)
                                .fixedSize()
                            Rectangle().fill(SE.lineSoft).frame(height: 1)
                        }
                        .padding(.vertical, 4)
                    }

                    SEFieldBox {
                        TextField("Email", text: $email).font(.se(18)).textContentType(.emailAddress).keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never).autocorrectionDisabled().focused($focus, equals: .email)
                            .padding(.horizontal, 12).accessibilityIdentifier("email-field")
                    }
                    SEFieldBox {
                        SecureField(creating ? "Password (8+ characters)" : "Password", text: $password).font(.se(18))
                            .textContentType(creating ? .newPassword : .password).focused($focus, equals: .password)
                            .padding(.horizontal, 12).accessibilityIdentifier("password-field")
                    }
                    if creating {
                        SEFieldBox {
                            SecureField("Confirm password", text: $confirm).font(.se(18)).textContentType(.newPassword)
                                .focused($focus, equals: .confirm).padding(.horizontal, 12)
                        }
                    }
                    if let e = auth.error { Text(e).font(.se(14)).foregroundStyle(SE.bad) }
                    if let n = notice { Text(n).font(.se(15, .semibold)).foregroundStyle(SE.good) }

                    SEPrimaryButton(title: auth.busy ? "…" : (creating ? "Create account" : "Sign in")) { Task { await submit() } }
                        .disabled(auth.busy).accessibilityIdentifier("email-submit").id(Self.submitID)

                    // Side by side when they fit; stacked at large text sizes
                    // or narrow widths rather than truncated off the edge.
                    ViewThatFits(in: .horizontal) {
                        HStack { createToggle; Spacer(minLength: 12); forgotButton }
                        VStack(alignment: .leading, spacing: 12) { createToggle; forgotButton }
                    }
                    .buttonStyle(.plain)

                    if forAlerts && !creating {
                        Text("The account you use on findacrib.com works here.")
                            .font(.se(14)).foregroundStyle(SE.ink3)
                    }
                }
                .disabled(auth.busy)
                .padding(16)
            }
            .scrollDismissesKeyboard(.interactively)
            // Tapping Email used to leave Password under the keyboard (owner,
            // 2026-10-11). On focus, scroll so the fields and Sign in sit just
            // above it; the delay lets the keyboard finish rising first.
            .onChange(of: focus) { _, f in
                guard f != nil else { return }
                Task { @MainActor in
                    try? await Task.sleep(for: .milliseconds(350))
                    withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo(Self.submitID, anchor: .bottom) }
                }
            }
            .background(Color.white)
            .navigationTitle("").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.foregroundStyle(SE.ink2) } }
            .onAppear { auth.error = nil; focus = offersSocialSignIn ? nil : .email }
            // Signing in from the Plus sheet must not close this one under it;
            // it closes when the Plus sheet does.
            .onChange(of: auth.isSignedIn) { _, on in if on && !showPlus { dismiss() } }
            .sheet(isPresented: $showPlus, onDismiss: { if auth.isSignedIn { dismiss() } }) { PaywallView(source: "signin_alerts") }
          }
        }
    }

    private static let submitID = "email-submit-anchor"

    private var createToggle: some View {
        Button(creating ? "Have an account? Sign in" : "No account? Create one") { creating.toggle(); auth.error = nil; notice = nil }
            .font(.se(15, .semibold)).foregroundStyle(SE.royal).fixedSize()
            .accessibilityIdentifier("create-account-toggle")
    }

    @ViewBuilder private var forgotButton: some View {
        if !creating {
            Button("Forgot password?") { Task { await forgot() } }
                .font(.se(15, .semibold)).foregroundStyle(SE.royal).fixedSize()
                .accessibilityIdentifier("forgot-password")
        }
    }

    private func submit() async {
        let e = email.trimmingCharacters(in: .whitespaces)
        guard e.contains("@") else { auth.error = "Enter your email."; return }
        guard password.count >= 8 else { auth.error = "Use a password of at least 8 characters."; return }
        if creating {
            guard password == confirm else { auth.error = "Passwords do not match."; return }
            await auth.signUp(email: e, password: password)
        } else {
            await auth.signIn(email: e, password: password)
        }
    }

    private func forgot() async {
        let e = email.trimmingCharacters(in: .whitespaces)
        guard e.contains("@") else { auth.error = "Enter your email above first, then tap Forgot password."; focus = .email; return }
        notice = nil
        if await auth.sendPasswordReset(email: e) {
            notice = "Check \(e) for a link to choose a new password, then come back and sign in."
        }
    }
}

/// What signing in for alerts gets you, above the Apple/Google buttons.
/// The Plus row carries a small "Get Plus" button (owner, 2026-10-11);
/// PaywallView signs them in first if they aren't yet.
struct AlertsPromiseBox: View {
    let openPlus: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            row("building.2.fill", "New lotteries and re-rentals in the boroughs you pick")
            row("bell.badge.fill", "In-app notifications and emails at 8 AM daily")
            HStack(alignment: .center, spacing: 12) {
                row("bolt.fill", "Upgrade to Plus for instant notifications and emails")
                Button {
                    Analytics.shared.track("realtime_upsell_click", ["src": "signin_alerts"]); openPlus()
                } label: {
                    Text("Get Plus").font(.se(14, .bold)).foregroundStyle(.white).fixedSize()
                        .padding(.horizontal, 12).frame(minHeight: 32)
                        .background(Capsule().fill(Color(hex: 0x5B21B6)))
                        .frame(minHeight: 44).contentShape(Rectangle())
                }
                .buttonStyle(.plain).accessibilityIdentifier("alerts-promise-plus")
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(SE.royal.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(SE.royal.opacity(0.25)))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("alerts-promise-box")
    }

    private func row(_ icon: String, _ text: String) -> some View {
        HStack(alignment: .center, spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 13, weight: .bold)).foregroundStyle(.white)
                .frame(width: 28, height: 28)
                .background(Circle().fill(SE.royal))
                .accessibilityHidden(true)
            Text(text).font(.se(15, .semibold)).foregroundStyle(SE.ink)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct SocialSignInButtons: View {
    @Environment(AuthService.self) private var auth
    var beforeSignIn: () -> Void = {}

    var body: some View {
        VStack(spacing: 10) {
            Button {
                beforeSignIn()
                Task { await auth.signInWithApple() }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: "apple.logo").font(.system(size: 19, weight: .medium)).foregroundStyle(.white)
                    Text("Continue with Apple").font(.se(18, .semibold)).foregroundStyle(.white)
                }
                .frame(maxWidth: .infinity).frame(height: 50)
                .background(Color.black).clipShape(RoundedRectangle(cornerRadius: 6))
            }
            .buttonStyle(.plain).accessibilityIdentifier("sign-in-apple")
            Button {
                beforeSignIn()
                Task { await auth.signInWithGoogle() }
            } label: {
                HStack(spacing: 10) {
                    GoogleG().frame(width: 18, height: 18)
                    Text("Continue with Google").font(.se(18, .semibold)).foregroundStyle(SE.ink)
                }
                .frame(maxWidth: .infinity).frame(height: 50)
                .background(Color.white).overlay(RoundedRectangle(cornerRadius: 6).stroke(SE.line))
            }
            .buttonStyle(.plain).accessibilityIdentifier("sign-in-google")
        }
        .disabled(auth.busy)
    }
}
