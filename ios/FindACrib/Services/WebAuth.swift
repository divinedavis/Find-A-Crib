import AuthenticationServices
import Foundation
import UIKit

/// Runs an OAuth round trip in ASWebAuthenticationSession and returns the
/// callback URL. Kept out of the SDK's built-in flow so the URL we open can
/// start at findacrib.com (nginx bounces /auth/v1/authorize to Supabase):
/// the system consent dialog names the host of that first URL, and
/// "dbaifotzwlxjvsxjohjt.supabase.co" is not a name anyone should be asked
/// to trust.
@MainActor
final class WebAuth: NSObject, ASWebAuthenticationPresentationContextProviding {
    enum Failure: LocalizedError {
        case cancelled, noCallback
        var errorDescription: String? {
            switch self { case .cancelled: String(localized: "Sign-in was cancelled."); case .noCallback: String(localized: "Sign-in did not complete. Try again.") }
        }
    }
    private static var active: WebAuth?
    private var session: ASWebAuthenticationSession?

    static func run(url: URL, callbackScheme: String) async throws -> URL {
        let w = WebAuth(); active = w; defer { active = nil }
        return try await w.start(url: url, scheme: callbackScheme)
    }

    /// Tapping Cancel on Google's own consent page isn't the sheet's Cancel:
    /// Google answers access_denied, GoTrue passes it to the callback, and the
    /// SDK turned it into "Error in URL with unspecified error_description."
    /// — shown to a new user who then signed in with Apple 9 s later
    /// (build 139, 2026-10-19). Read it as the cancel it is.
    nonisolated static func isDeclined(_ callback: URL) -> Bool {
        guard let c = URLComponents(url: callback, resolvingAgainstBaseURL: false) else { return false }
        var items = c.queryItems ?? []
        if let f = c.fragment { items += URLComponents(string: "?" + f)?.queryItems ?? [] }
        return items.contains { $0.name == "error" && $0.value == "access_denied" }
    }

    private func start(url: URL, scheme: String) async throws -> URL {
        try await withCheckedThrowingContinuation { cont in
            let s = ASWebAuthenticationSession(url: url, callbackURLScheme: scheme) { cb, err in
                if let err {
                    if (err as? ASWebAuthenticationSessionError)?.code == .canceledLogin { cont.resume(throwing: Failure.cancelled) }
                    else { cont.resume(throwing: err) }
                } else if let cb { cont.resume(returning: cb) }
                else { cont.resume(throwing: Failure.noCallback) }
            }
            s.presentationContextProvider = self
            // Keep Safari's Google cookies: one fewer password prompt.
            s.prefersEphemeralWebBrowserSession = false
            session = s
            s.start()
        }
    }

    func presentationAnchor(for session: ASWebAuthenticationSession) -> ASPresentationAnchor {
        UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            .first { $0.activationState == .foregroundActive }?.keyWindow ?? ASPresentationAnchor()
    }
}
