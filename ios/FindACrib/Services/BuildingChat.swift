import Foundation
import CryptoKit
import Observation
import Supabase

/// End-to-end encryption for building chat (owner, 2026-10-17). See
/// db/0063_building_chat.sql for what the server stores and can see.
///
/// Each phone has one Curve25519 key, made on first use and kept in the
/// Keychain on this device only (SecureStore: never synced, never restored
/// to another phone). A message is sealed with a fresh random key; that key
/// is wrapped for each member with a key derived from ECDH(sender, member)
/// through HKDF, salted per message and bound to the building. Only the
/// members at send time can open it, so a newcomer sees only new messages,
/// and a reinstall (new key) can't read what came before.
enum ChatCrypto {
    private static let store = SecureStore(service: "com.divinedavis.findacrib.chat")
    private static let account = "identity-v1"

    static func identity() -> Curve25519.KeyAgreement.PrivateKey {
        if let raw = store.data(account), let k = try? Curve25519.KeyAgreement.PrivateKey(rawRepresentation: raw) { return k }
        let k = Curve25519.KeyAgreement.PrivateKey()
        store.set(k.rawRepresentation, for: account)
        return k
    }

    static func publicKeyBase64(_ k: Curve25519.KeyAgreement.PrivateKey = identity()) -> String {
        k.publicKey.rawRepresentation.base64EncodedString()
    }

    static func wrappingKey(_ mine: Curve25519.KeyAgreement.PrivateKey, _ theirs: Curve25519.KeyAgreement.PublicKey,
                            salt: Data, bbl: String) throws -> SymmetricKey {
        try mine.sharedSecretFromKeyAgreement(with: theirs)
            .hkdfDerivedSymmetricKey(using: SHA256.self, salt: salt, sharedInfo: Data("fac-chat-v1|\(bbl)".utf8), outputByteCount: 32)
    }

    struct Sealed: Equatable { let salt: String; let ciphertext: String; let keys: [String: String] }

    /// Seals `plaintext` for every member (id -> public key), sender included.
    static func seal(_ plaintext: Data, bbl: String, from me: Curve25519.KeyAgreement.PrivateKey,
                     to members: [String: Curve25519.KeyAgreement.PublicKey]) throws -> Sealed {
        let messageKey = SymmetricKey(size: .bits256)
        let salt = Data((0..<16).map { _ in UInt8.random(in: 0...255) })
        let body = try ChaChaPoly.seal(plaintext, using: messageKey).combined
        let raw = messageKey.withUnsafeBytes { Data($0) }
        var keys: [String: String] = [:]
        for (id, pub) in members {
            let w = try wrappingKey(me, pub, salt: salt, bbl: bbl)
            keys[id] = try ChaChaPoly.seal(raw, using: w).combined.base64EncodedString()
        }
        return Sealed(salt: salt.base64EncodedString(), ciphertext: body.base64EncodedString(), keys: keys)
    }

    /// Opens a message wrapped for `myID`, sent by the holder of `senderKey`.
    static func open(_ s: Sealed, bbl: String, myID: String, mine: Curve25519.KeyAgreement.PrivateKey,
                     senderKey: Curve25519.KeyAgreement.PublicKey) throws -> Data {
        guard let wrapped = s.keys[myID].flatMap({ Data(base64Encoded: $0) }),
              let salt = Data(base64Encoded: s.salt), let body = Data(base64Encoded: s.ciphertext) else {
            throw CryptoKitError.authenticationFailure
        }
        let w = try wrappingKey(mine, senderKey, salt: salt, bbl: bbl)
        let raw = try ChaChaPoly.open(ChaChaPoly.SealedBox(combined: wrapped), using: w)
        return try ChaChaPoly.open(ChaChaPoly.SealedBox(combined: body), using: SymmetricKey(data: raw))
    }
}

/// One building's chat: members, keys, history since joining, live inserts.
@MainActor @Observable
final class BuildingChat {
    struct Message: Identifiable, Equatable {
        let id: Int
        let sender: String
        let name: String
        let text: String?          // nil: couldn't be opened on this phone
        let at: Date
        var mine: Bool
    }
    /// What travels inside the ciphertext.
    struct Payload: Codable { let t: String; let n: String }

    private struct Row: Codable {
        let id: Int
        let bbl: String
        let sender: String
        let created_at: Date
        let salt: String
        let ciphertext: String
        let keys: [String: String]
    }
    private struct NewRow: Encodable { let bbl: String; let salt: String; let ciphertext: String; let keys: [String: String] }
    private struct KeyRow: Codable { let user_id: String; let public_key: String }
    private struct MemberRow: Codable { let user_id: String }

    let bbl: String
    private(set) var messages: [Message] = []
    private(set) var joined = false
    private(set) var loading = false
    private(set) var memberCount = 0
    var error: String?
    private(set) var blocked: Set<String> = []

    private var keys: [String: Curve25519.KeyAgreement.PublicKey] = [:]
    private var channel: RealtimeChannelV2?
    private var listen: Task<Void, Never>?
    private weak var auth: AuthService?

    static let nameKey = "chat.displayName"
    static var savedName: String { UserDefaults.standard.string(forKey: nameKey) ?? "" }
    static func termsKey(_ bbl: String) -> String { "chat.terms.\(bbl)" }

    init(bbl: String) { self.bbl = bbl }

    private var me: String? { auth?.session?.user.id.uuidString.lowercased() }
    private var db: SupabaseClient? { auth?.client }
    private static let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .custom { dec in
            let s = try dec.singleValueContainer().decode(String.self)
            let f = ISO8601DateFormatter(); f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            if let t = f.date(from: s) { return t }
            f.formatOptions = [.withInternetDateTime]
            if let t = f.date(from: s) { return t }
            throw DecodingError.dataCorruptedError(in: try dec.singleValueContainer(), debugDescription: s)
        }
        return d
    }()

    /// Checks membership, then loads history and goes live if a member.
    func start(auth: AuthService) async {
        self.auth = auth
        guard let db, let me else { return }
        loading = true; defer { loading = false }
        do {
            let mine: [MemberRow] = try await db.from("chat_members").select("user_id").eq("bbl", value: bbl).eq("user_id", value: me).execute().value
            joined = !mine.isEmpty
            if joined { try await publishKey(); await refresh(); await goLive() }
        } catch { self.error = String(localized: "Couldn't reach the chat. Pull down to try again.") }
    }

    /// Joining: the terms were accepted on this phone, the key is published.
    func join() async {
        guard let db, let me else { return }
        do {
            try await publishKey()
            struct J: Encodable { let bbl: String; let user_id: String; let agreed_terms_at: Date }
            try await db.from("chat_members").upsert(J(bbl: bbl, user_id: me, agreed_terms_at: Date()), ignoreDuplicates: true).execute()
            joined = true
            Analytics.shared.track("chat_join", ["bbl": bbl])
            await refresh(); await goLive()
        } catch { self.error = String(localized: "Couldn't join the chat. Try again.") }
    }

    func leave() async {
        guard let db, let me else { return }
        try? await db.from("chat_members").delete().eq("bbl", value: bbl).eq("user_id", value: me).execute()
        await stop(); joined = false; messages = []
    }

    private func publishKey() async throws {
        guard let db, let me else { return }
        struct K: Encodable { let user_id: String; let public_key: String; let updated_at: Date }
        try await db.from("chat_keys").upsert(K(user_id: me, public_key: ChatCrypto.publicKeyBase64(), updated_at: Date())).execute()
    }

    /// Members and their keys, then the last 100 messages wrapped for me.
    func refresh() async {
        guard let db else { return }
        do {
            let members: [MemberRow] = try await db.from("chat_members").select("user_id").eq("bbl", value: bbl).execute().value
            memberCount = members.count
            let ids = members.map(\.user_id)
            if !ids.isEmpty {
                let rows: [KeyRow] = try await db.from("chat_keys").select("user_id,public_key").in("user_id", values: ids).execute().value
                keys = Dictionary(uniqueKeysWithValues: rows.compactMap { r in
                    Data(base64Encoded: r.public_key).flatMap { try? Curve25519.KeyAgreement.PublicKey(rawRepresentation: $0) }.map { (r.user_id.lowercased(), $0) }
                })
            }
            struct B: Codable { let blocked: String }
            let bl: [B] = (try? await db.from("chat_blocks").select("blocked").execute().value) ?? []
            blocked = Set(bl.map { $0.blocked.lowercased() })
            let rows: [Row] = try await db.from("chat_messages").select().eq("bbl", value: bbl)
                .order("id", ascending: false).limit(100).execute().value
            messages = rows.reversed().map(decode)
            error = nil
        } catch { self.error = String(localized: "Couldn't load messages. Pull down to try again.") }
    }

    private func decode(_ r: Row) -> Message {
        let sender = r.sender.lowercased()
        var text: String?, name = String(localized: "Neighbor")
        if let me, let pub = keys[sender],
           let data = try? ChatCrypto.open(.init(salt: r.salt, ciphertext: r.ciphertext, keys: r.keys), bbl: bbl,
                                           myID: me, mine: ChatCrypto.identity(), senderKey: pub),
           let p = try? JSONDecoder().decode(Payload.self, from: data) {
            text = p.t; name = p.n.isEmpty ? name : p.n
        }
        return Message(id: r.id, sender: sender, name: name, text: text, at: r.created_at, mine: sender == me)
    }

    private func goLive() async {
        guard let db, channel == nil else { return }
        let ch = db.channel("chat-\(bbl)")
        let inserts = ch.postgresChange(InsertAction.self, schema: "public", table: "chat_messages", filter: "bbl=eq.\(bbl)")
        channel = ch
        do { try await ch.subscribeWithError() } catch { return }
        listen = Task { [weak self] in
            for await ins in inserts {
                guard let self, let row = try? ins.decodeRecord(as: Row.self, decoder: Self.decoder) else { continue }
                // A sender we don't have a key for yet joined after our last look.
                if self.keys[row.sender.lowercased()] == nil { await self.refresh(); continue }
                if !self.messages.contains(where: { $0.id == row.id }) { self.messages.append(self.decode(row)) }
            }
        }
    }

    func stop() async {
        listen?.cancel(); listen = nil
        if let channel, let db { await db.removeChannel(channel) }
        channel = nil
    }

    /// Sends to everyone in the chat right now.
    func send(_ text: String, name: String) async -> Bool {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, t.count <= 2000, let db, me != nil else { return false }
        if ChatFilter.blocks(t) { error = String(localized: "That message breaks the chat rules and wasn't sent."); return false }
        await refresh()   // every current member's key, so a newcomer can read it
        do {
            let payload = try JSONEncoder().encode(Payload(t: t, n: String(name.prefix(40))))
            let s = try ChatCrypto.seal(payload, bbl: bbl, from: ChatCrypto.identity(), to: keys)
            try await db.from("chat_messages").insert(NewRow(bbl: bbl, salt: s.salt, ciphertext: s.ciphertext, keys: s.keys)).execute()
            Analytics.shared.track("chat_send", ["bbl": bbl, "members": keys.count])
            return true
        } catch {
            self.error = String(localized: "Couldn't send. Check your connection and try again.")
            return false
        }
    }

    /// Sends the plaintext of this one message to Find A Crib for review.
    func report(_ m: Message, reason: String) async -> Bool {
        guard let db else { return false }
        struct R: Encodable { let message_id: Int; let bbl: String; let sender: String; let plaintext: String?; let reason: String }
        do {
            try await db.from("chat_reports").insert(R(message_id: m.id, bbl: bbl, sender: m.sender, plaintext: m.text, reason: reason)).execute()
            return true
        } catch { return false }
    }

    func block(_ sender: String) async {
        guard let db else { return }
        struct B: Encodable { let blocked: String }
        try? await db.from("chat_blocks").insert(B(blocked: sender)).execute()
        blocked.insert(sender)
    }
}

/// Apple 1.2 asks for a filter on what can be posted. The server only ever
/// sees ciphertext, so the check runs on the sender's phone: slurs and
/// threats are refused before sealing. Kept short and literal on purpose.
enum ChatFilter {
    private static let words: [String] = ["nigger", "nigga", "faggot", "fag", "kike", "spic", "chink", "tranny", "retard",
                                          "kill yourself", "kys", "i will kill you", "i'll kill you"]
    static func blocks(_ text: String) -> Bool {
        let t = " " + text.lowercased().replacingOccurrences(of: "[^a-z' ]", with: " ", options: .regularExpression) + " "
        return words.contains { t.contains(" \($0) ") }
    }
}
