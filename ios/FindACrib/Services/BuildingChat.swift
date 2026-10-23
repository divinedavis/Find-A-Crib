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
        var fromWeb = false        // sealed by a browser (findacrib.com), not a phone
        var reply: Quote? = nil    // the message this one answers
    }
    /// A neighbor's emoji on a message (owner, 2026-10-23, Instagram's
    /// long-press reactions). One per person per message; the newest wins.
    struct Reaction: Identifiable, Equatable {
        let id: Int                // its own row, so its sender can delete it
        let sender: String
        let name: String
        let emoji: String
        var mine: Bool
    }
    /// What a reply carries of the message it answers, inside the ciphertext.
    struct Quote: Codable, Equatable { let id: Int; let n: String; let t: String }
    /// What travels inside the ciphertext. A reaction is a message of its
    /// own (k = "react", to = the message, e = the emoji), so the server
    /// can't tell it from text either; its `t` reads sensibly on builds
    /// from before reactions, which show it as a line.
    struct Payload: Codable {
        let t: String
        let n: String
        var k: String? = nil
        var to: Int? = nil
        var e: String? = nil
        var r: Quote? = nil
    }
    static let quickReactions = ["❤️", "😂", "😮", "😢", "🔥", "👍"]
    static let moreReactions = ["🙏", "👏", "💯", "😍", "🎉", "😡", "🤔", "👀", "🙌", "😅", "🫶", "👎"]

    private struct Row: Codable {
        let id: Int
        let bbl: String
        let sender: String
        let created_at: Date
        let salt: String
        let ciphertext: String
        let keys: [String: String]
        var sender_device: String? = nil   // a browser's device id (db/0067); nil = the phone key
    }
    private struct NewRow: Encodable { let bbl: String; let salt: String; let ciphertext: String; let keys: [String: String] }
    private struct KeyRow: Codable { let user_id: String; let public_key: String }
    private struct MemberRow: Codable { let user_id: String }
    private struct DeviceRow: Codable { let user_id: String; let device_id: String; let public_key: String }

    let bbl: String
    private(set) var messages: [Message] = []
    /// Reactions by the message they're on.
    private(set) var reactionRows: [Reaction] = []
    private var reactionTarget: [Int: Int] = [:]   // reaction row -> message
    /// Messages this person hid with "Delete for you". Only on this phone.
    private(set) var hidden: Set<Int> = []
    private(set) var joined = false
    private(set) var loading = false
    private(set) var memberCount = 0
    var error: String?
    private(set) var blocked: Set<String> = []

    /// Who can open a message: "<uid>" = that account's phone (chat_keys),
    /// "<uid>:<device>" = one of its browsers (chat_devices, db/0067).
    private var keys: [String: Curve25519.KeyAgreement.PublicKey] = [:]
    private var channel: RealtimeChannelV2?
    private var listen: Task<Void, Never>?

    /// Typing bubbles (owner, 2026-10-19: "allow live message bubbling for
    /// when people are typing"). A private Realtime broadcast per building,
    /// members only (db/0067); it carries the account id and nothing else.
    private(set) var typing: [String] = []           // display names, oldest first
    private var typers: [String: Date] = [:]
    private var lastTypingSent = Date.distantPast
    private var typingChannel: RealtimeChannelV2?
    private var typingListen: Task<Void, Never>?
    private var typingExpiry: Task<Void, Never>?
    static let typingSendEvery: TimeInterval = 2.5
    static let typingShownFor: TimeInterval = 5
    private weak var auth: AuthService?

    static let nameKey = "chat.displayName"
    static var savedName: String { UserDefaults.standard.string(forKey: nameKey) ?? "" }
    static func termsKey(_ bbl: String) -> String { "chat.terms.\(bbl)" }

    init(bbl: String) {
        self.bbl = bbl
        hidden = Set(UserDefaults.standard.array(forKey: Self.hiddenKey(bbl)) as? [Int] ?? [])
    }
    static func hiddenKey(_ bbl: String) -> String { "chat.hidden.\(bbl)" }

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

    /// `--chat-demo` (UI tests, screenshots): a joined room with no network.
    static var isDemo: Bool { CommandLine.arguments.contains("--chat-demo") }
    func loadDemo() {
        let now = Date(), cal = Calendar.current
        let y = cal.date(byAdding: .day, value: -1, to: now)!
        func at(_ d: Date, _ h: Int, _ m: Int) -> Date { cal.date(bySettingHour: h, minute: m, second: 0, of: d)! }
        messages = [
            Message(id: 1, sender: "a", name: "Maria, 4B", text: "Is the heat out for anyone else?", at: at(y, 19, 2), mine: false),
            Message(id: 2, sender: "a", name: "Maria, 4B", text: "Radiators are cold on the 4th floor.", at: at(y, 19, 3), mine: false),
            Message(id: 3, sender: "b", name: "Devon", text: "Same in 2A. I called 311.", at: at(y, 19, 20), mine: false, fromWeb: true),
            Message(id: 4, sender: "me", name: "You", text: "Back on here this morning 👍", at: now.addingTimeInterval(-600), mine: true,
                    reply: Quote(id: 3, n: "Devon", t: "Same in 2A. I called 311.")),
            Message(id: 5, sender: "c", name: "Neighbor", text: nil, at: now.addingTimeInterval(-300), mine: false),
        ]
        reactionRows = [Reaction(id: 6, sender: "a", name: "Maria, 4B", emoji: "❤️", mine: false)]
        reactionTarget = [6: 4]
        joined = true; memberCount = 4
        typing = ["Maria, 4B"]
    }

    /// Checks membership, then loads history and goes live if a member.
    func start(auth: AuthService) async {
        if Self.isDemo { loadDemo(); return }
        self.auth = auth
        guard let db, let me else { return }
        loading = true; defer { loading = false }
        do {
            let mine: [MemberRow] = try await db.from("chat_members").select("user_id").eq("bbl", value: bbl).eq("user_id", value: me).execute().value
            joined = !mine.isEmpty
            if joined { try await publishKey(); await refresh(); await goLive(); await goLiveTyping() }
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
            await refresh(); await goLive(); await goLiveTyping()
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
                var k = Dictionary(rows.compactMap { r in
                    Self.publicKey(r.public_key).map { (r.user_id.lowercased(), $0) }
                }, uniquingKeysWith: { a, _ in a })
                let devices: [DeviceRow] = (try? await db.from("chat_devices").select("user_id,device_id,public_key")
                    .in("user_id", values: ids).execute().value) ?? []
                for d in devices { if let pub = Self.publicKey(d.public_key) { k["\(d.user_id.lowercased()):\(d.device_id)"] = pub } }
                keys = k
            }
            struct B: Codable { let blocked: String }
            let bl: [B] = (try? await db.from("chat_blocks").select("blocked").execute().value) ?? []
            blocked = Set(bl.map { $0.blocked.lowercased() })
            let rows: [Row] = try await db.from("chat_messages").select().eq("bbl", value: bbl)
                .order("id", ascending: false).limit(150).execute().value
            messages = []; reactionRows = []; reactionTarget = [:]
            for r in rows.reversed() { take(r) }
            error = nil
        } catch { self.error = String(localized: "Couldn't load messages. Pull down to try again.") }
    }

    nonisolated static func publicKey(_ b64: String) -> Curve25519.KeyAgreement.PublicKey? {
        Data(base64Encoded: b64).flatMap { try? Curve25519.KeyAgreement.PublicKey(rawRepresentation: $0) }
    }

    /// The key that sealed a row: the sender's browser if it names one, else their phone.
    nonisolated static func senderKeyID(sender: String, device: String?) -> String {
        device.map { "\(sender.lowercased()):\($0)" } ?? sender.lowercased()
    }

    /// Opens a row and files it as a message or a reaction.
    private func take(_ r: Row) {
        let sender = r.sender.lowercased()
        var p: Payload?
        if let me, let pub = keys[Self.senderKeyID(sender: sender, device: r.sender_device)],
           let data = try? ChatCrypto.open(.init(salt: r.salt, ciphertext: r.ciphertext, keys: r.keys), bbl: bbl,
                                           myID: me, mine: ChatCrypto.identity(), senderKey: pub) {
            p = try? JSONDecoder().decode(Payload.self, from: data)
        }
        let name = p.map { $0.n.isEmpty ? String(localized: "Neighbor") : String($0.n.prefix(40)) } ?? String(localized: "Neighbor")
        if let p, p.k == "react", let to = p.to, let e = p.e, Self.isReaction(e) {
            addReaction(Reaction(id: r.id, sender: sender, name: name, emoji: e, mine: sender == me), to: to)
            return
        }
        guard !messages.contains(where: { $0.id == r.id }) else { return }
        messages.append(Message(id: r.id, sender: sender, name: name, text: p?.t, at: r.created_at, mine: sender == me,
                                fromWeb: r.sender_device != nil, reply: p?.r.map { Quote(id: $0.id, n: String($0.n.prefix(40)), t: String($0.t.prefix(160))) }))
    }

    /// One emoji, nothing else: a reaction can't smuggle a sentence.
    nonisolated static func isReaction(_ e: String) -> Bool {
        e.count == 1 && e.unicodeScalars.contains { $0.properties.isEmojiPresentation || $0.properties.isEmoji && $0.value > 0xFF }
    }

    private func addReaction(_ x: Reaction, to message: Int) {
        // The newest from each person wins; an older one left behind is ignored.
        if let old = reactionRows.firstIndex(where: { $0.sender == x.sender && reactionTarget[$0.id] == message }) {
            guard reactionRows[old].id < x.id else { return }
            reactionTarget[reactionRows[old].id] = nil
            reactionRows.remove(at: old)
        }
        reactionRows.append(x); reactionTarget[x.id] = message
    }

    /// The reactions on a message, people you blocked left out.
    func reactions(on id: Int) -> [Reaction] {
        reactionRows.filter { reactionTarget[$0.id] == id && !blocked.contains($0.sender) }
    }

    /// A row is gone: an unsent message or a taken-back reaction.
    func removed(_ id: Int) {
        messages.removeAll { $0.id == id }
        if reactionTarget[id] != nil { reactionTarget[id] = nil; reactionRows.removeAll { $0.id == id } }
    }

    private func goLive() async {
        guard let db, channel == nil else { return }
        let ch = db.channel("chat-\(bbl)")
        let inserts = ch.postgresChange(InsertAction.self, schema: "public", table: "chat_messages", filter: "bbl=eq.\(bbl)")
        // Unsent messages and taken-back reactions. Realtime can't filter
        // deletes and sends only the row id, so ids we don't hold are ignored.
        let deletes = ch.postgresChange(DeleteAction.self, schema: "public", table: "chat_messages")
        channel = ch
        do { try await ch.subscribeWithError() } catch { return }
        listen = Task { [weak self] in
            await withTaskGroup(of: Void.self) { group in
                group.addTask { @MainActor [weak self] in
                    for await ins in inserts {
                        guard let self, let row = try? ins.decodeRecord(as: Row.self, decoder: Self.decoder) else { continue }
                        // A sender we don't have a key for yet joined after our last look.
                        if self.keys[Self.senderKeyID(sender: row.sender, device: row.sender_device)] == nil { await self.refresh(); continue }
                        self.take(row)
                        self.stoppedTyping(row.sender.lowercased())
                    }
                }
                group.addTask { @MainActor [weak self] in
                    for await del in deletes {
                        let v = del.oldRecord["id"]
                        guard let self, let id = v?.intValue ?? v?.doubleValue.map({ Int($0) }) else { continue }
                        self.removed(id)
                    }
                }
            }
        }
    }

    func stop() async {
        listen?.cancel(); listen = nil
        typingListen?.cancel(); typingListen = nil
        typingExpiry?.cancel(); typingExpiry = nil
        if let channel, let db { await db.removeChannel(channel) }
        if let typingChannel, let db { await db.removeChannel(typingChannel) }
        channel = nil; typingChannel = nil
        typers = [:]; typing = []
    }

    // MARK: typing bubbles

    private func goLiveTyping() async {
        guard let db, typingChannel == nil else { return }
        let ch = db.channel("chat-typing:\(bbl)") { $0.isPrivate = true }
        let events = ch.broadcastStream(event: "typing")
        typingChannel = ch
        do { try await ch.subscribeWithError() } catch { typingChannel = nil; return }
        typingListen = Task { [weak self] in
            for await e in events {
                guard let self else { return }
                let body = e["payload"]?.objectValue ?? e
                guard let who = body["u"]?.stringValue?.lowercased(), who != self.me else { continue }
                if body["stop"]?.boolValue == true { self.stoppedTyping(who) } else { self.startedTyping(who) }
            }
        }
    }

    /// The composer changed. Tells the building at most every 2.5 s.
    func userTyped(_ draft: String) {
        guard joined, let me, let typingChannel else { return }
        let empty = draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        if empty {
            guard lastTypingSent != .distantPast else { return }
            lastTypingSent = .distantPast
            Task { await typingChannel.broadcast(event: "typing", message: ["u": .string(me), "stop": .bool(true)]) }
            return
        }
        guard Date().timeIntervalSince(lastTypingSent) >= Self.typingSendEvery else { return }
        lastTypingSent = Date()
        Task { await typingChannel.broadcast(event: "typing", message: ["u": .string(me)]) }
    }

    func startedTyping(_ who: String, at now: Date = Date()) {
        guard !blocked.contains(who) else { return }
        typers[who] = now
        publishTypers(now: now)
        typingExpiry?.cancel()
        typingExpiry = Task { [weak self] in
            try? await Task.sleep(for: .seconds(Self.typingShownFor))
            self?.publishTypers(now: Date())
        }
    }

    func stoppedTyping(_ who: String) {
        guard typers.removeValue(forKey: who) != nil else { return }
        publishTypers(now: Date())
    }

    private func publishTypers(now: Date) {
        typers = typers.filter { now.timeIntervalSince($0.value) < Self.typingShownFor }
        typing = typers.sorted { $0.value < $1.value }.map { name(of: $0.key) }
    }

    /// The name a sender last used in a message we could open.
    func name(of sender: String) -> String {
        messages.last(where: { $0.sender == sender && $0.text != nil })?.name ?? String(localized: "A neighbor")
    }

    /// Sends to everyone in the chat right now, as a reply when `replyTo` is set.
    func send(_ text: String, name: String, replyTo: Message? = nil) async -> Bool {
        let t = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty, t.count <= 2000 else { return false }
        if ChatFilter.blocks(t) { error = String(localized: "That message breaks the chat rules and wasn't sent."); return false }
        let quote = replyTo.flatMap { m in m.text.map { Quote(id: m.id, n: m.mine ? String(name.prefix(40)) : m.name, t: String($0.prefix(160))) } }
        if Self.isDemo {
            messages.append(Message(id: (messages.map(\.id).max() ?? 0) + 100, sender: "me", name: name, text: t, at: Date(), mine: true, reply: quote))
            return true
        }
        guard db != nil, me != nil else { return false }
        do {
            try await seal(Payload(t: t, n: String(name.prefix(40)), r: quote))
            userTyped("")
            Analytics.shared.track("chat_send", ["bbl": bbl, "members": keys.count, "reply": quote != nil])
            return true
        } catch {
            self.error = String(localized: "Couldn't send. Check your connection and try again.")
            return false
        }
    }

    private func seal(_ p: Payload) async throws {
        guard let db else { return }
        await refresh()   // every current member's key, so a newcomer can read it
        let s = try ChatCrypto.seal(try JSONEncoder().encode(p), bbl: bbl, from: ChatCrypto.identity(), to: keys)
        try await db.from("chat_messages").insert(NewRow(bbl: bbl, salt: s.salt, ciphertext: s.ciphertext, keys: s.keys)).execute()
    }

    /// Reacts with `emoji`, replacing your earlier one; the same emoji again takes it back.
    func react(_ m: Message, emoji: String, name: String) async {
        guard Self.isReaction(emoji) else { return }
        let old = reactions(on: m.id).first(where: \.mine)
        if Self.isDemo {
            if let old { removed(old.id) }
            if old?.emoji != emoji {
                addReaction(Reaction(id: (reactionRows.map(\.id).max() ?? 1000) + 1, sender: "me", name: name, emoji: emoji, mine: true), to: m.id)
            }
            return
        }
        guard let db else { return }
        do {
            if let old {
                try await db.from("chat_messages").delete().eq("id", value: old.id).execute()
                removed(old.id)
            }
            guard old?.emoji != emoji else { return }
            try await seal(Payload(t: "Reacted \(emoji) to a message", n: String(name.prefix(40)), k: "react", to: m.id, e: emoji))
            Analytics.shared.track("chat_react", ["bbl": bbl])
        } catch { self.error = String(localized: "Couldn't send. Check your connection and try again.") }
    }

    /// Takes back one of your messages for everyone: the row is deleted on the server.
    func unsend(_ m: Message) async {
        guard m.mine else { return }
        if Self.isDemo { removed(m.id); return }
        guard let db, let me else { return }
        do {
            try await db.from("chat_messages").delete().eq("id", value: m.id).eq("sender", value: me).execute()
            removed(m.id)
            Analytics.shared.track("chat_unsend", ["bbl": bbl])
        } catch { self.error = String(localized: "Couldn't unsend. Check your connection and try again.") }
    }

    /// Hides a message on this phone only; everyone else still sees it.
    func hideForMe(_ m: Message) {
        hidden.insert(m.id)
        UserDefaults.standard.set(Array(hidden.suffix(500)), forKey: Self.hiddenKey(bbl))
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
