import Foundation
import Observation
import Supabase

/// Comments on a building, shared with findacrib.com — the same
/// `building_comments` rows the website writes, so a comment left on a phone
/// shows up on the web page and the other way round (owner, 2026-09-20).
///
/// RLS does the enforcing: anyone may read, only a signed-in user may insert a
/// row carrying their own id, and a reply must point at a top-level comment on
/// the same building. The app asks for sign-in before it opens the sheet
/// anyway — the owner's rule is that comments are for people with an account —
/// but nothing here relies on that check.
@Observable @MainActor
final class CommentsStore {
    struct Comment: Identifiable, Equatable {
        let id: UUID
        let userID: UUID?
        let author: String
        let body: String
        let createdAt: Date
        let parentID: UUID?
        var likedBy: [UUID]

        var likes: Int { likedBy.count }
        func isLiked(by uid: UUID?) -> Bool { uid.map { likedBy.contains($0) } ?? false }
        func isMine(_ uid: UUID?) -> Bool { uid != nil && uid == userID }
    }

    /// What PostgREST returns for `…select(…, comment_likes(user_id))`.
    private struct Row: Decodable {
        let id: UUID
        let user_id: UUID?
        let author: String?
        let body: String?
        let created_at: String
        let parent_id: UUID?
        let comment_likes: [Liker]?
        struct Liker: Decodable { let user_id: UUID? }
    }
    private struct NewComment: Encodable {
        let bbl: String, user_id: String, author: String, body: String, parent_id: String?
    }
    private struct NewLike: Encodable { let comment_id: String, user_id: String }

    private(set) var comments: [Comment] = []
    private(set) var loading = false
    private(set) var failed = false
    private(set) var counts: [String: Int] = [:]      // bbl -> how many, for the button
    var posting = false
    var error: String?

    weak var auth: AuthService?
    private var client: SupabaseClient? { auth?.client }

    static let maxLength = 1000

    // MARK: - Reading

    func load(bbl: String) async {
        guard let client else { failed = true; return }
        loading = true; failed = false; defer { loading = false }
        do {
            let rows: [Row] = try await client.from("building_comments")
                .select("id,user_id,author,body,created_at,parent_id,comment_likes(user_id)")
                .eq("bbl", value: bbl)
                .order("created_at", ascending: true)
                .limit(500)
                .execute().value
            comments = rows.map {
                Comment(id: $0.id, userID: $0.user_id,
                        author: ($0.author?.trimmingCharacters(in: .whitespaces)).flatMap { $0.isEmpty ? nil : $0 } ?? "Member",
                        body: $0.body ?? "",
                        createdAt: Self.date($0.created_at),
                        parentID: $0.parent_id,
                        likedBy: ($0.comment_likes ?? []).compactMap(\.user_id))
            }
            counts[bbl] = comments.count
        } catch {
            failed = true
        }
    }

    /// Just the number, for the button on the building screen.
    func refreshCount(bbl: String) async {
        guard let client else { return }
        struct IDOnly: Decodable { let id: UUID }
        if let rows: [IDOnly] = try? await client.from("building_comments")
            .select("id").eq("bbl", value: bbl).limit(500).execute().value {
            counts[bbl] = rows.count
        }
    }

    func count(for bbl: String) -> Int { counts[bbl] ?? 0 }

    // MARK: - Writing

    @discardableResult
    func post(bbl: String, body: String, replyingTo parent: Comment? = nil) async -> Bool {
        guard let client, let uid = auth?.session?.user.id else { error = "Sign in to comment."; return false }
        let text = String(body.trimmingCharacters(in: .whitespacesAndNewlines).prefix(Self.maxLength))
        guard !text.isEmpty else { return false }
        posting = true; error = nil; defer { posting = false }
        do {
            try await client.from("building_comments").insert(NewComment(
                bbl: bbl, user_id: uid.uuidString, author: authorName(),
                body: text, parent_id: parent?.id.uuidString)).execute()
            Analytics.shared.track("comment_post", ["bbl": bbl, "reply": parent != nil, "len": text.count])
            await load(bbl: bbl)
            return true
        } catch {
            self.error = "Couldn't post that just now. Try again."
            return false
        }
    }

    func toggleLike(_ c: Comment, bbl: String) async {
        guard let client, let uid = auth?.session?.user.id else { return }
        let liked = c.isLiked(by: uid)
        // Optimistic: the row moves under the thumb, then the write follows.
        if let i = comments.firstIndex(where: { $0.id == c.id }) {
            if liked { comments[i].likedBy.removeAll { $0 == uid } } else { comments[i].likedBy.append(uid) }
        }
        do {
            if liked {
                try await client.from("comment_likes").delete()
                    .eq("comment_id", value: c.id.uuidString).eq("user_id", value: uid.uuidString).execute()
            } else {
                try await client.from("comment_likes")
                    .insert(NewLike(comment_id: c.id.uuidString, user_id: uid.uuidString)).execute()
            }
            Analytics.shared.track("comment_like", ["bbl": bbl, "on": !liked])
        } catch {
            await load(bbl: bbl)          // put it back the way the server has it
        }
    }

    func delete(_ c: Comment, bbl: String) async {
        guard let client, let uid = auth?.session?.user.id, c.userID == uid else { return }
        comments.removeAll { $0.id == c.id || $0.parentID == c.id }
        try? await client.from("building_comments").delete().eq("id", value: c.id.uuidString).execute()
        Analytics.shared.track("comment_delete", ["bbl": bbl])
        await load(bbl: bbl)
    }

    // MARK: - Pieces

    /// The same name the website writes: the account's name, else the part of
    /// the email before the @.
    func authorName() -> String {
        let md = auth?.session?.user.userMetadata ?? [:]
        for key in ["full_name", "name"] {
            if case .string(let s)? = md[key] {
                let t = s.trimmingCharacters(in: .whitespaces)
                if !t.isEmpty { return String(t.prefix(60)) }
            }
        }
        let email = auth?.email ?? ""
        let local = email.split(separator: "@").first.map(String.init) ?? ""
        return String((local.isEmpty ? "Member" : local).prefix(60))
    }

    nonisolated static func date(_ s: String) -> Date {
        let withFraction = ISO8601DateFormatter()
        withFraction.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let d = withFraction.date(from: s) { return d }
        let plain = ISO8601DateFormatter()
        plain.formatOptions = [.withInternetDateTime]
        return plain.date(from: s) ?? Date()
    }

    /// "just now", "4h", "3d", then the date — Instagram's shape, and the same
    /// wording the website uses.
    nonisolated static func ago(_ d: Date, now: Date = Date()) -> String {
        let s = now.timeIntervalSince(d)
        if s < 3600 { return "just now" }
        if s < 86_400 { return "\(Int(s / 3600))h" }
        if s < 30 * 86_400 { return "\(Int(s / 86_400))d" }
        let f = DateFormatter(); f.dateFormat = "MMM d"
        return f.string(from: d)
    }

    /// Top-level comments, newest last (a thread reads down), each with its replies.
    nonisolated static func threads(_ all: [Comment]) -> [(Comment, [Comment])] {
        let tops = all.filter { $0.parentID == nil }.sorted { $0.createdAt < $1.createdAt }
        return tops.map { top in
            (top, all.filter { $0.parentID == top.id }.sorted { $0.createdAt < $1.createdAt })
        }
    }
}
