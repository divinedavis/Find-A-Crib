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
    /// Opened from a building's "Sign in to see violations & inspections"
    /// (owner, 2026-10-12): the same box, listing this building's records and
    /// one Plus feature, instead of sending them to Profile.
    var records: RecordsPreview? = nil
    /// Opened from a building's "Sign in to see who runs this building"
    /// (owner, 2026-10-12): what an account shows, and the Plus phone row.
    var agentPreview = false
    /// Opened from Your Crib's "Alert me about new calls" (owner, 2026-10-15:
    /// "a sheet showing them the features they'll get, like our other sheets").
    var casaPreview = false
    /// Opened from "See the full history" instead: the same box, history first
    /// (owner, 2026-10-15: show what they get for that feature).
    var casaHistory = false
    private var promo: Bool { forAlerts || records != nil || agentPreview || casaPreview }
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

    var body: some View {
        content.onAppear { Analytics.shared.track("signin_view", ["for": casaPreview ? (casaHistory ? "casa_history" : "casa") : agentPreview ? "agent" : records != nil ? "records" : (offersSocialSignIn ? "alerts" : "profile")]) }
            .modifier(TallSheetOnIPad())
    }

    private var content: some View {
        NavigationStack {
          ScrollViewReader { proxy in
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(creating ? String(localized: "Create account") : (heading ?? (casaPreview ? (casaHistory ? String(localized: "Sign in to see the full history") : String(localized: "Sign in to watch your building")) : agentPreview ? String(localized: "Sign in to see who runs this building") : records != nil ? String(localized: "Sign in to see this building's records") : (offersSocialSignIn ? String(localized: "Sign in for lottery alerts") : String(localized: "Sign in with email"))))).font(.se(26, .bold))
                    // While typing, the promise box steps aside so Email and
                    // Password both sit above the keyboard and its Sign in bar
                    // (owner, 2026-10-15: "i can't see the password field when
                    // i click on the email field"). It's back when the keyboard
                    // goes.
                    if focus != nil && promo && !creating {
                        EmptyView()
                    } else if casaPreview && !creating {
                        CasaPromiseBox(history: casaHistory) { showPlus = true }
                    } else if agentPreview && !creating {
                        AgentPromiseBox { showPlus = true }
                    } else if let r = records, !creating {
                        RecordsPromiseBox(preview: r) { showPlus = true }
                    } else if forAlerts && !creating {
                        AlertsPromiseBox { showPlus = true }
                    } else {
                        Text(creating ? String(localized: "No verification email — you're in as soon as you tap Create.") : String(localized: "The account you use on findacrib.com works here."))
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
                            .submitLabel(.next).onSubmit { focus = .password }
                    }
                    SEFieldBox {
                        SecureField(creating ? String(localized: "Password (8+ characters)") : String(localized: "Password"), text: $password).font(.se(18))
                            .textContentType(creating ? .newPassword : .password).focused($focus, equals: .password)
                            .padding(.horizontal, 12).accessibilityIdentifier("password-field")
                            .submitLabel(creating ? .next : .go).onSubmit { if creating { focus = .confirm } else { Task { await submit() } } }
                    }
                    .id(Field.password)
                    if creating {
                        SEFieldBox {
                            SecureField("Confirm password", text: $confirm).font(.se(18)).textContentType(.newPassword)
                                .focused($focus, equals: .confirm).padding(.horizontal, 12)
                                .submitLabel(.go).onSubmit { Task { await submit() } }
                        }
                        .id(Field.confirm)
                    }
                    if let e = auth.error { Text(e).font(.se(14)).foregroundStyle(SE.bad) }
                    if let n = notice { Text(n).font(.se(15, .semibold)).foregroundStyle(SE.good) }

                    // While a field is focused, Sign in rides on the keyboard
                    // (the bar below) instead of sitting here under it.
                    if focus == nil { submitButton }

                    // Side by side when they fit; stacked at large text sizes
                    // or narrow widths rather than truncated off the edge.
                    ViewThatFits(in: .horizontal) {
                        HStack { createToggle; Spacer(minLength: 12); forgotButton }
                        VStack(alignment: .leading, spacing: 12) { createToggle; forgotButton }
                    }
                    .buttonStyle(.plain)

                    if promo && !creating {
                        Text("The account you use on findacrib.com works here.")
                            .font(.se(14)).foregroundStyle(SE.ink3)
                    }
                }
                .disabled(auth.busy)
                .padding(16)
            }
            .scrollDismissesKeyboard(.interactively)
            // Sign in stays in sight whenever Email or Password is focused
            // (owner, 2026-10-14): it moves into a bar on top of the keyboard.
            // The 10/11 fix scrolled Sign in to the bottom of the scroll view,
            // but in a sheet the keyboard lifted the sheet instead and the
            // button still landed under the keys.
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if focus != nil {
                    submitButton.padding(.horizontal, 16).padding(.vertical, 10)
                        .background(Color.white.shadow(.drop(color: .black.opacity(0.08), radius: 6, y: -2)))
                }
            }
            // And the field after the focused one comes into view: tapping
            // Email showed Password under the keyboard. The delay lets the
            // keyboard and the bar settle first.
            .onChange(of: focus) { _, f in
                guard let f else { return }
                let next: Field = f == .email ? .password : (creating ? .confirm : .password)
                Task { @MainActor in
                    // Twice: the sheet itself moves as the keyboard rises, so
                    // the first scroll can land short.
                    for wait in [350, 400] {
                        try? await Task.sleep(for: .milliseconds(wait))
                        withAnimation(.easeOut(duration: 0.25)) { proxy.scrollTo(next, anchor: .bottom) }
                    }
                }
            }
            .background(Color.white)
            .navigationTitle("").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.foregroundStyle(SE.ink2) } }
            .onAppear { auth.error = nil; focus = offersSocialSignIn ? nil : .email }
            // Signing in from the Plus sheet must not close this one under it;
            // it closes when the Plus sheet does.
            .onChange(of: auth.isSignedIn) { _, on in if on && !showPlus { dismiss() } }
            .sheet(isPresented: $showPlus, onDismiss: { if auth.isSignedIn { dismiss() } }) { PaywallView(source: casaPreview ? "casa" : agentPreview ? "phone" : records != nil ? "realtime" : "signin_alerts") }
          }
        }
    }

    private var submitButton: some View {
        SEPrimaryButton(title: auth.busy ? "…" : (creating ? String(localized: "Create account") : String(localized: "Sign in"))) { Task { await submit() } }
            .disabled(auth.busy).accessibilityIdentifier("email-submit")
    }

    private var createToggle: some View {
        Button(creating ? String(localized: "Have an account? Sign in") : String(localized: "No account? Create one")) { creating.toggle(); auth.error = nil; notice = nil }
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
        guard e.contains("@") else { auth.error = String(localized: "Enter your email."); return }
        guard password.count >= 8 else { auth.error = String(localized: "Use a password of at least 8 characters."); return }
        if creating {
            guard password == confirm else { auth.error = String(localized: "Passwords do not match."); return }
            await auth.signUp(email: e, password: password)
        } else {
            await auth.signIn(email: e, password: password)
        }
    }

    private func forgot() async {
        let e = email.trimmingCharacters(in: .whitespaces)
        guard e.contains("@") else { auth.error = String(localized: "Enter your email above first, then tap Forgot password."); focus = .email; return }
        notice = nil
        if await auth.sendPasswordReset(email: e) {
            notice = String(localized: "Check \(e) for a link to choose a new password, then come back and sign in.")
        }
    }
}

/// iPad shows a sheet as a fixed-height form, and the alerts box pushed
/// "No account? Create one" and "Forgot password?" below its bottom edge
/// (2026-10-11). The page size is tall enough; iPhone sheets are unaffected.
private struct TallSheetOnIPad: ViewModifier {
    func body(content: Content) -> some View {
        if #available(iOS 18.0, *) { content.presentationSizing(.page) } else { content }
    }
}

/// What signing in for alerts gets you, above the Apple/Google buttons.
/// The Plus row carries a small "Get Plus" button (owner, 2026-10-11);
/// PaywallView signs them in first if they aren't yet.
struct AlertsPromiseBox: View {
    let openPlus: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            row("building.2.fill", String(localized: "New lotteries and re-rentals in the boroughs you pick"))
            row("bell.badge.fill", String(localized: "In-app notifications and emails at 8 AM daily"))
            HStack(alignment: .center, spacing: 12) {
                row("bolt.fill", String(localized: "Upgrade to Plus for instant notifications and emails"))
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

/// What a building's sign-in unlocks, from the counts the app already has.
struct RecordsPreview: Equatable {
    var openViolations: Int?
    var openComplaints: Int?
}

/// Same look as AlertsPromiseBox: the building's records behind the account
/// (with this building's counts when we have them), then one Plus feature
/// with a small Get Plus button.
struct RecordsPromiseBox: View {
    let preview: RecordsPreview
    let openPlus: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            PromiseRow(icon: "exclamationmark.triangle.fill", text: violationsLine)
            PromiseRow(icon: "ladybug.fill", text: String(localized: "Bedbug filings the landlord made, year by year"))
            PromiseRow(icon: "pawprint.fill", text: String(localized: "Rat inspections from the Health Department"))
            HStack(alignment: .center, spacing: 12) {
                PromiseRow(icon: "bolt.fill", text: String(localized: "Plus: real-time lottery alerts, the minute one opens"))
                Button {
                    Analytics.shared.track("records_upsell_click", ["src": "signin_records"]); openPlus()
                } label: {
                    Text("Get Plus").font(.se(14, .bold)).foregroundStyle(.white).fixedSize()
                        .padding(.horizontal, 12).frame(minHeight: 32)
                        .background(Capsule().fill(Color(hex: 0x5B21B6)))
                        .frame(minHeight: 44).contentShape(Rectangle())
                }
                .buttonStyle(.plain).accessibilityIdentifier("records-promise-plus")
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(SE.royal.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(SE.royal.opacity(0.25)))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("records-promise-box")
    }

    private var violationsLine: String {
        let v = preview.openViolations, c = preview.openComplaints
        if v == nil && c == nil { return String(localized: "HPD violations and complaints for this building") }
        let violations = String(localized: "\(v ?? 0) open HPD violations"), complaints = String(localized: "\(c ?? 0) open complaints")
        return String(localized: "\(violations) and \(complaints) here — see each one")
    }
}

/// What signing in shows about who runs a building, and the one Plus part.
struct AgentPromiseBox: View {
    let openPlus: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            PromiseRow(icon: "person.text.rectangle.fill", text: String(localized: "The managing agent HPD has on file, and their office address"))
            PromiseRow(icon: "building.2.fill", text: String(localized: "Who owns the building, and its head officer"))
            HStack(alignment: .center, spacing: 12) {
                PromiseRow(icon: "phone.fill", text: String(localized: "Plus: the agent's phone number — call who actually runs it"))
                Button {
                    Analytics.shared.track("phone_upsell_click", ["src": "signin_agent"]); openPlus()
                } label: {
                    Text("Get Plus").font(.se(14, .bold)).foregroundStyle(.white).fixedSize()
                        .padding(.horizontal, 12).frame(minHeight: 32)
                        .background(Capsule().fill(Color(hex: 0x5B21B6)))
                        .frame(minHeight: 44).contentShape(Rectangle())
                }
                .buttonStyle(.plain).accessibilityIdentifier("agent-promise-plus")
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(SE.royal.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(SE.royal.opacity(0.25)))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("agent-promise-box")
    }
}

/// What Your Crib's alerts are, before the account. Crime alerts are free
/// (2026-10-19) and lead; the rest is Plus, so the Get Plus button sits on
/// the last row like the other boxes.
struct CasaPromiseBox: View {
    /// From "See the full history": that feature leads, alerts follow.
    var history = false
    let openPlus: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if history {
                PromiseRow(icon: "clock.arrow.circlepath", text: String(localized: "Every 311 call on your building back to 2010, not just the past year"))
                PromiseRow(icon: "ant.fill", text: String(localized: "See whether roaches, mice or rats are a pattern, or a one-off"))
            } else {
                PromiseRow(icon: "exclamationmark.shield.fill", text: String(localized: "Free: crime alerts within half a mile of your building"))
                PromiseRow(icon: "bell.badge.fill", text: String(localized: "A notification and an email for every new 311 call on your building"))
                PromiseRow(icon: "ant.fill", text: String(localized: "Pests first: roaches, mice and rats called in on your building"))
            }
            HStack(alignment: .center, spacing: 12) {
                PromiseRow(icon: history ? "bell.badge.fill" : "clock.arrow.circlepath",
                           text: history ? String(localized: "A notification and an email for every new 311 call. All part of Plus")
                                         : String(localized: "Every 311 call back to 2010. Part of Plus"))
                Button {
                    Analytics.shared.track("casa_upsell_click", ["src": "signin_casa"]); openPlus()
                } label: {
                    Text("Get Plus").font(.se(14, .bold)).foregroundStyle(.white).fixedSize()
                        .padding(.horizontal, 12).frame(minHeight: 32)
                        .background(Capsule().fill(Color(hex: 0x5B21B6)))
                        .frame(minHeight: 44).contentShape(Rectangle())
                }
                .buttonStyle(.plain).accessibilityIdentifier("casa-promise-plus")
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(RoundedRectangle(cornerRadius: 12).fill(SE.royal.opacity(0.08)))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(SE.royal.opacity(0.25)))
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("casa-promise-box")
    }
}

/// One icon + line row, shared by the sign-in promise boxes.
struct PromiseRow: View {
    let icon: String
    let text: String
    var body: some View {
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
