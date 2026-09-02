import Foundation
import Observation
import Supabase

/// HPD registration contacts for one building (public.hpd_contacts). Phone
/// numbers are NOT in here — only a has_phone flag; the number itself lives in
/// the private agent_phones table behind get_agent_phone(), which answers only
/// for Find A Crib Plus subscribers.
struct HPDContacts: Codable, Hashable {
    struct Party: Codable, Hashable {
        let name: String?; let type: String?; let address: String?
        let hasPhone: Bool
        enum CodingKeys: String, CodingKey { case name, type, address, has_phone }
        init(from d: Decoder) throws {
            let c = try d.container(keyedBy: CodingKeys.self)
            name = try c.decodeIfPresent(String.self, forKey: .name)
            type = try c.decodeIfPresent(String.self, forKey: .type)
            address = try c.decodeIfPresent(String.self, forKey: .address)
            if let b = try? c.decodeIfPresent(Bool.self, forKey: .has_phone) { hasPhone = b }
            else if let i = try? c.decodeIfPresent(Int.self, forKey: .has_phone) { hasPhone = i != 0 }
            else { hasPhone = false }
        }
        func encode(to e: Encoder) throws {
            var c = e.container(keyedBy: CodingKeys.self)
            try c.encodeIfPresent(name, forKey: .name); try c.encodeIfPresent(type, forKey: .type)
            try c.encodeIfPresent(address, forKey: .address); try c.encode(hasPhone, forKey: .has_phone)
        }
    }
    let bbl: String
    let owner: Party?
    let manager: Party?
    let officer: Party?
}

/// Supabase session + Plus status + the account-only reads (contacts, agent
/// phone) and saved-building sync. Sign-in is OAuth only — no passwords, no
/// email verification (house rule).
@Observable @MainActor
final class AuthService {
    let client: SupabaseClient?
    private(set) var session: Session?
    private(set) var hasPlus = false
    private(set) var busy = false
    var error: String?
    private var contactsCache: [String: HPDContacts] = [:]
    private var phoneCache: [String: String?] = [:]
    /// Hook so saves written locally also land in saved_buildings.
    weak var activity: Activity?
    /// App Store Plus: re-synced to the account on every sign-in.
    weak var plus: PlusStore?

    var isSignedIn: Bool { session != nil }
    var email: String? { session?.user.email }
    var configured: Bool { client != nil }

    init() {
        let info = Bundle.main.infoDictionary ?? [:]
        if let host = info["SUPABASE_HOST"] as? String, !host.isEmpty,
           let key = info["SUPABASE_ANON_KEY"] as? String, !key.isEmpty,
           let url = URL(string: "https://\(host)") {
            client = SupabaseClient(supabaseURL: url, supabaseKey: key)
            session = client?.auth.currentSession
        } else {
            client = nil   // a build without Secrets.xcconfig: the app still works, signed out
        }
    }

    /// Long-running: follows the auth stream for the life of the app.
    func listen() async {
        guard let client else { return }
        for await (event, s) in client.auth.authStateChanges {
            switch event {
            case .initialSession, .signedIn, .tokenRefreshed, .userUpdated:
                let wasSignedIn = session != nil
                session = s
                if s != nil {
                    await refreshPlus()
                    if !wasSignedIn || event == .signedIn { await syncSaves(); await plus?.sync() }
                }
            case .signedOut, .userDeleted:
                session = nil; hasPlus = false; contactsCache = [:]; phoneCache = [:]
            default: break
            }
        }
    }

    // MARK: sign-in

    func signInWithApple() async {
        await run {
            let cred = try await AppleSignInService.authorize()
            // Send the nonce only when Apple put the claim in the token.
            let claim = IDToken.stringClaim("nonce", from: cred.idToken)
            try await self.client!.auth.signInWithIdToken(credentials: .init(provider: .apple, idToken: cred.idToken, nonce: claim == nil ? nil : cred.nonce))
        }
    }

    /// Supabase's web OAuth flow (PKCE) in an ASWebAuthenticationSession,
    /// using the site's existing Google client — no separate iOS OAuth client.
    /// The authorize URL is opened at findacrib.com, which nginx bounces to
    /// GoTrue, so the consent dialog says "findacrib.com" not the project ref.
    func signInWithGoogle() async {
        await run {
            let client = self.client!
            let redirect = URL(string: "findacrib://auth-callback")!
            let url = try client.auth.getOAuthSignInURL(provider: .google, redirectTo: redirect)
            var comps = URLComponents(url: url, resolvingAgainstBaseURL: false)!
            comps.scheme = "https"; comps.host = "findacrib.com"; comps.port = nil
            let callback = try await WebAuth.run(url: comps.url!, callbackScheme: "findacrib")
            _ = try await client.auth.session(from: callback)
        }
    }

    // MARK: email + password (the website's accounts; autoconfirmed, no verification step)

    func signIn(email: String, password: String) async {
        await run { try await self.client!.auth.signIn(email: email, password: password) }
    }

    func signUp(email: String, password: String) async {
        await run {
            let r = try await self.client!.auth.signUp(email: email, password: password)
            if r.session == nil { self.error = "Account created — sign in to continue." }
        }
    }

    /// Emails a recovery link that lands on findacrib.com/reset/, where the
    /// new password is set; the app just needs the address.
    func sendPasswordReset(email: String) async -> Bool {
        var ok = false
        await run {
            try await self.client!.auth.resetPasswordForEmail(email, redirectTo: URL(string: "https://findacrib.com/reset/"))
            ok = true
        }
        return ok
    }

    func signOut() async {
        guard let client else { return }
        try? await client.auth.signOut()
        session = nil; hasPlus = false
    }

    /// App Store 5.1.1(v). delete_account() cascades every user-owned table.
    func deleteAccount() async {
        await run {
            try await self.client!.rpc("delete_account").execute()
            try? await self.client!.auth.signOut()
            self.session = nil; self.hasPlus = false
        }
    }

    private func run(_ block: @escaping () async throws -> Void) async {
        guard client != nil else { error = "Sign-in isn't configured in this build."; return }
        busy = true; error = nil; defer { busy = false }
        do { try await block() } catch {
            if (error as? AppleSignInService.Failure) == .cancelled || (error as? WebAuth.Failure) == .cancelled { return }
            let text = error.localizedDescription
            if text.localizedCaseInsensitiveContains("cancel") { return }
            self.error = text
        }
    }

    // MARK: Plus + gated reads

    func refreshPlus() async {
        guard let client, let uid = session?.user.id else { hasPlus = false; return }
        let v: Bool? = try? await client.rpc("has_plus", params: ["uid": uid.uuidString]).execute().value
        hasPlus = v ?? false
    }

    func contacts(for bbl: String) async -> HPDContacts? {
        guard let client, isSignedIn else { return nil }
        if let c = contactsCache[bbl] { return c }
        let rows: [HPDContacts]? = try? await client.from("hpd_contacts").select("bbl,owner,manager,officer").eq("bbl", value: bbl).limit(1).execute().value
        if let c = rows?.first { contactsCache[bbl] = c; return c }
        return nil
    }

    /// Plus only — the RPC returns null for everyone else.
    func agentPhone(for bbl: String) async -> String? {
        guard let client, isSignedIn, hasPlus else { return nil }
        if let cached = phoneCache[bbl] { return cached }
        let v: String? = try? await client.rpc("get_agent_phone", params: ["p_bbl": bbl]).execute().value
        phoneCache[bbl] = v
        return v
    }

    // MARK: saved buildings ↔ saved_buildings

    private struct SavedRow: Codable { let user_id: String; let bbl: String }

    /// On sign-in: push local saves up (insert-only, duplicates ignored), then
    /// pull the account's list down — same merge the website does.
    func syncSaves() async {
        guard let client, let uid = session?.user.id, let activity else { return }
        let local = activity.saved
        if !local.isEmpty {
            let rows = local.map { SavedRow(user_id: uid.uuidString, bbl: $0) }
            _ = try? await client.from("saved_buildings").upsert(rows, onConflict: "user_id,bbl", ignoreDuplicates: true).execute()
        }
        struct Row: Codable { let bbl: String }
        if let remote: [Row] = try? await client.from("saved_buildings").select("bbl").eq("user_id", value: uid.uuidString).order("created_at", ascending: false).execute().value {
            activity.mergeRemoteSaves(remote.map(\.bbl))
        }
    }

    func remoteToggle(bbl: String, saved: Bool) {
        guard let client, let uid = session?.user.id else { return }
        Task {
            if saved { _ = try? await client.from("saved_buildings").insert(SavedRow(user_id: uid.uuidString, bbl: bbl)).execute() }
            else { _ = try? await client.from("saved_buildings").delete().eq("user_id", value: uid.uuidString).eq("bbl", value: bbl).execute() }
        }
    }
}
