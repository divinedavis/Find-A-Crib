import SwiftUI

/// Email + password sign-in for the accounts people already made on the
/// website, with sign-up and "Forgot password?" — the reset link goes to
/// findacrib.com/reset/. Same rules as the site: 8+ characters, no
/// verification step on sign-up.
struct EmailSignInView: View {
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @State private var email = ""
    @State private var password = ""
    @State private var confirm = ""
    @State private var creating = false
    @State private var notice: String?
    @FocusState private var focus: Field?
    enum Field { case email, password, confirm }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(creating ? "Create account" : "Sign in with email").font(.se(26, .bold))
                    Text(creating ? "No verification email — you're in as soon as you tap Create." : "The account you use on findacrib.com works here.")
                        .font(.se(15)).foregroundStyle(SE.ink2)

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
                .padding(16)
            }
            .background(Color.white)
            .navigationTitle("").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.foregroundStyle(SE.ink2) } }
            .onAppear { auth.error = nil; focus = .email }
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
