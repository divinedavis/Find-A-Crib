import SwiftUI

/// Email + password sign-in for the accounts people already made on the
/// website, with sign-up and "Forgot password?" — the reset link goes to
/// findacrib.com/reset/. Same rules as the site: 8+ characters, no
/// verification step on sign-up.
struct EmailSignInView: View {
    var offersSocialSignIn = false
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @State private var email = ""
    @State private var password = ""
    @State private var confirm = ""
    @State private var creating = false
    @State private var notice: String?
    @FocusState private var focus: Field?
    enum Field { case email, password, confirm }

    var body: some View { content.onAppear { Analytics.shared.track("signin_view", ["for": offersSocialSignIn ? "alerts" : "profile"]) } }

    private var content: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(creating ? "Create account" : (offersSocialSignIn ? "Sign in for alerts" : "Sign in with email")).font(.se(26, .bold))
                    Text(creating ? "No verification email — you're in as soon as you tap Create." : "The account you use on findacrib.com works here.")
                        .font(.se(15)).foregroundStyle(SE.ink2)

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
                        .disabled(auth.busy).accessibilityIdentifier("email-submit")

                    HStack {
                        Button(creating ? "Have an account? Sign in" : "No account? Create one") { creating.toggle(); auth.error = nil; notice = nil }
                            .font(.se(15, .semibold)).foregroundStyle(SE.royal)
                        Spacer()
                        if !creating {
                            Button("Forgot password?") { Task { await forgot() } }
                                .font(.se(15, .semibold)).foregroundStyle(SE.royal).accessibilityIdentifier("forgot-password")
                        }
                    }
                    .buttonStyle(.plain)
                }
                .disabled(auth.busy)
                .padding(16)
            }
            .scrollDismissesKeyboard(.interactively)
            .background(Color.white)
            .navigationTitle("").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.foregroundStyle(SE.ink2) } }
            .onAppear { auth.error = nil; focus = offersSocialSignIn ? nil : .email }
            .onChange(of: auth.isSignedIn) { _, on in if on { dismiss() } }
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
