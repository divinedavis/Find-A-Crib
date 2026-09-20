import AuthenticationServices
import CryptoKit
import Foundation
import UIKit

/// Nonce plumbing for Sign in with Apple. Apple signs SHA-256(nonce) into the
/// ID token; Supabase compares that claim to the hash of the RAW nonce we send.
/// So the request gets the hash and signInWithIdToken gets the raw value —
/// swapping them fails with a flat "invalid token".
enum AuthNonce {
    private static let alphabet = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVXYZabcdefghijklmnopqrstuvwxyz-._")
    static func random(length: Int = 32) -> String {
        var bytes = [UInt8](repeating: 0, count: length)
        let status = SecRandomCopyBytes(kSecRandomDefault, bytes.count, &bytes)
        precondition(status == errSecSuccess, "secure RNG unavailable")
        return String(bytes.map { alphabet[Int($0) % alphabet.count] })
    }
    static func sha256(_ input: String) -> String {
        SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

/// Reads a claim out of an ID token WITHOUT verifying it — verification is
/// the server's job. Used only to see whether Apple put a nonce in the token,
/// because GoTrue rejects "nonce passed but not in token" outright.
enum IDToken {
    static func stringClaim(_ name: String, from token: String) -> String? {
        let parts = token.split(separator: ".")
        guard parts.count >= 2 else { return nil }
        var s = String(parts[1]).replacingOccurrences(of: "-", with: "+").replacingOccurrences(of: "_", with: "/")
        while s.count % 4 != 0 { s += "=" }
        guard let d = Data(base64Encoded: s),
              let json = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let v = json[name] as? String, !v.isEmpty else { return nil }
        return v
    }
}

/// Runs the native Sign in with Apple sheet. ASAuthorizationController holds
/// its delegate weakly, so `active` keeps this alive while the sheet is up.
@MainActor
final class AppleSignInService: NSObject {
    struct Credential { let idToken: String; let nonce: String; let email: String? }
    enum Failure: LocalizedError {
        case cancelled, missingIdentityToken
        var errorDescription: String? {
            switch self {
            case .cancelled: "Sign in with Apple was cancelled."
            case .missingIdentityToken: "Apple did not return an identity token. Try again."
            }
        }
    }
    private var continuation: CheckedContinuation<Credential, Error>?
    private var rawNonce = ""
    private static var active: AppleSignInService?

    /// Apple answers `.unknown` (1000) when the sheet cannot be presented —
    /// which is what a half-presented anchor looks like from its side. Two
    /// users hit six or seven straight failures that way (2026-09-19/20),
    /// both from a button inside one of our own sheets, while a sign-in from
    /// the Profile screen succeeded. So: wait a beat for whatever is
    /// animating to settle, and try once more if Apple still says "unknown".
    static func authorize() async throws -> Credential {
        do {
            return try await run()
        } catch {
            guard (error as? ASAuthorizationError)?.code == .unknown else { throw error }
            Analytics.shared.track("signin_retry", ["provider": "apple"])
            try? await Task.sleep(for: .milliseconds(600))
            return try await run()
        }
    }

    private static func run() async throws -> Credential {
        // A second sheet while one is up is what Apple refuses; never leave a
        // previous attempt holding the delegate.
        active?.finish(.failure(Failure.cancelled))
        let s = AppleSignInService(); active = s; defer { if active === s { active = nil } }
        return try await s.start()
    }

    private func start() async throws -> Credential {
        rawNonce = AuthNonce.random()
        let req = ASAuthorizationAppleIDProvider().createRequest()
        req.requestedScopes = [.email]
        req.nonce = AuthNonce.sha256(rawNonce)
        let c = ASAuthorizationController(authorizationRequests: [req])
        c.delegate = self; c.presentationContextProvider = self
        // The sheet this was tapped in may still be animating; presenting into
        // a window mid-transition is the failure above.
        try? await Task.sleep(for: .milliseconds(250))
        return try await withCheckedThrowingContinuation { cont in self.continuation = cont; c.performRequests() }
    }
    private func finish(_ r: Result<Credential, Error>) { continuation?.resume(with: r); continuation = nil }
}

extension AppleSignInService: ASAuthorizationControllerDelegate {
    func authorizationController(controller: ASAuthorizationController, didCompleteWithAuthorization authorization: ASAuthorization) {
        guard let cred = authorization.credential as? ASAuthorizationAppleIDCredential,
              let data = cred.identityToken, let token = String(data: data, encoding: .utf8) else {
            finish(.failure(Failure.missingIdentityToken)); return
        }
        finish(.success(Credential(idToken: token, nonce: rawNonce, email: cred.email)))
    }
    func authorizationController(controller: ASAuthorizationController, didCompleteWithError error: Error) {
        if let e = error as? ASAuthorizationError, e.code == .canceled { finish(.failure(Failure.cancelled)) }
        else { finish(.failure(error)) }
    }
}
extension AppleSignInService: ASAuthorizationControllerPresentationContextProviding {
    /// A real window on a real scene. The old fallback built a bare
    /// `ASPresentationAnchor()` — a window belonging to no scene, which Apple
    /// cannot present into, and which is the difference between "cancelled"
    /// and six straight "unknown" errors for a user who tapped sign-in inside
    /// a sheet (2026-09-20).
    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
        let scene = scenes.first { $0.activationState == .foregroundActive } ?? scenes.first
        if let w = scene?.keyWindow ?? scene?.windows.first(where: \.isKeyWindow) ?? scene?.windows.first { return w }
        if let scene { return UIWindow(windowScene: scene) }
        return ASPresentationAnchor()
    }
}
