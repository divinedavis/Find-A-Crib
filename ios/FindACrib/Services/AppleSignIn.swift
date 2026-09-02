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

    static func authorize() async throws -> Credential {
        let s = AppleSignInService(); active = s; defer { active = nil }
        return try await s.start()
    }
    private func start() async throws -> Credential {
        rawNonce = AuthNonce.random()
        let req = ASAuthorizationAppleIDProvider().createRequest()
        req.requestedScopes = [.email]
        req.nonce = AuthNonce.sha256(rawNonce)
        let c = ASAuthorizationController(authorizationRequests: [req])
        c.delegate = self; c.presentationContextProvider = self
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
    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive }?.keyWindow ?? ASPresentationAnchor()
    }
}
