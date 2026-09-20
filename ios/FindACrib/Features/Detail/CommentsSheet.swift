import SwiftUI

/// Comments on a building, in the shape people already know from Instagram:
/// a grabber, a scrolling thread, a like heart on the right of each row, and a
/// compose bar pinned above the keyboard. Replies go one level deep.
///
/// Signed out it shows the sign-in panel instead of the thread — the owner's
/// rule is that comments are for people who signed up (2026-09-20). Apple and
/// Google come first there, with no keyboard until email is chosen.
struct CommentsSheet: View {
    let building: Building
    @Environment(\.dismiss) private var dismiss
    @Environment(AuthService.self) private var auth
    @State private var store = CommentsStore()
    @State private var draft = ""
    @State private var replyTo: CommentsStore.Comment?
    @State private var showSignIn = false
    @State private var confirmDelete: CommentsStore.Comment?
    @State private var moderate: CommentsStore.Comment?
    @FocusState private var writing: Bool

    private var uid: UUID? { auth.session?.user.id }

    var body: some View {
        NavigationStack {
            Group {
                if auth.isSignedIn { thread } else { signedOut }
            }
            .background(Color.white)
            .navigationTitle("Comments")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") { dismiss() }.foregroundStyle(SE.ink2)
                }
            }
        }
        .presentationDragIndicator(.visible)
        .sheet(isPresented: $showSignIn) { EmailSignInView(offersSocialSignIn: true) }
        .task(id: auth.isSignedIn) {
            store.auth = auth
            if auth.isSignedIn { await store.load(bbl: building.bbl) }
        }
        .alert("Delete this comment?", isPresented: Binding(get: { confirmDelete != nil },
                                                            set: { if !$0 { confirmDelete = nil } })) {
            Button("Delete", role: .destructive) {
                if let c = confirmDelete { Task { await store.delete(c, bbl: building.bbl) } }
            }
            Button("Cancel", role: .cancel) { confirmDelete = nil }
        } message: { Text("It disappears from the app and from findacrib.com.") }
        .confirmationDialog("Report this comment?", isPresented: Binding(get: { moderate != nil },
                                                                        set: { if !$0 { moderate = nil } }),
                            titleVisibility: .visible) {
            Button("Report comment", role: .destructive) {
                if let c = moderate { Task { await store.report(c, bbl: building.bbl) } }
                moderate = nil
            }
            Button("Block this person", role: .destructive) {
                if let c = moderate { Task { await store.block(c, bbl: building.bbl) } }
                moderate = nil
            }
            Button("Cancel", role: .cancel) { moderate = nil }
        } message: {
            Text("Reporting hides it for you and sends it to us to review within 24 hours. Blocking hides everything that person writes.")
        }
    }

    // MARK: - Signed out

    private var signedOut: some View {
        VStack(alignment: .leading, spacing: 14) {
            Spacer(minLength: 24)
            Image(systemName: "bubble.left.and.bubble.right").font(.system(size: 38, weight: .semibold)).foregroundStyle(SE.royal)
            Text("Comments are for members").font(.se(24, .bold)).foregroundStyle(SE.ink)
            Text("Sign up free to read what people say about \(building.address) — the cold radiators, the super, the block — and to add your own.")
                .font(.se(17)).foregroundStyle(SE.ink2)
            SEPrimaryButton(title: "Sign up to comment") { showSignIn = true }
                .accessibilityIdentifier("comments-signup")
            Text("Your account name shows on what you post.").font(.se(14)).foregroundStyle(SE.ink3)
            Spacer()
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    // MARK: - Signed in

    private var thread: some View {
        VStack(spacing: 0) {
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    if store.loading && store.comments.isEmpty {
                        ProgressView().tint(SE.royal).frame(maxWidth: .infinity).padding(.top, 40)
                    } else if store.failed {
                        message("Couldn't load comments", "Check your connection and pull to refresh.")
                    } else if store.comments.isEmpty {
                        message("No comments yet", "Be the first to say something about this building.")
                    }
                    ForEach(CommentsStore.threads(store.comments), id: \.0.id) { top, replies in
                        row(top)
                        ForEach(replies) { row($0, indented: true) }
                    }
                    Color.clear.frame(height: 12)
                }
                .padding(.horizontal, 16).padding(.top, 16)
            }
            .refreshable { await store.load(bbl: building.bbl) }
            .scrollDismissesKeyboard(.interactively)
            composer
        }
    }

    private func row(_ c: CommentsStore.Comment, indented: Bool = false) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Circle().fill(SE.paleBlue).frame(width: indented ? 26 : 34, height: indented ? 26 : 34)
                .overlay(Text(initials(c.author)).font(.se(indented ? 12 : 14, .bold)).foregroundStyle(SE.navy))
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(c.author).font(.se(15, .bold)).foregroundStyle(SE.ink)
                    Text(CommentsStore.ago(c.createdAt)).font(.se(13)).foregroundStyle(SE.ink3)
                }
                Text(c.body).font(.se(16)).foregroundStyle(SE.ink).fixedSize(horizontal: false, vertical: true)
                HStack(spacing: 16) {
                    if !indented {
                        Button("Reply") { replyTo = c; writing = true }
                            .font(.se(13, .bold)).foregroundStyle(SE.ink3).buttonStyle(.plain)
                    }
                    if c.likes > 0 {
                        Text("\(c.likes) like\(c.likes == 1 ? "" : "s")").font(.se(13)).foregroundStyle(SE.ink3)
                    }
                    if c.isMine(uid) {
                        Button("Delete") { confirmDelete = c }
                            .font(.se(13, .bold)).foregroundStyle(SE.ink3).buttonStyle(.plain)
                    } else {
                        // App Review 1.2: a way to report a comment and to
                        // block whoever wrote it, on the comment itself.
                        Button("Report") { moderate = c }
                            .font(.se(13, .bold)).foregroundStyle(SE.ink3).buttonStyle(.plain)
                            .accessibilityIdentifier("comment-report")
                    }
                }
            }
            Spacer(minLength: 6)
            Button {
                Task { await store.toggleLike(c, bbl: building.bbl) }
            } label: {
                Image(systemName: c.isLiked(by: uid) ? "heart.fill" : "heart")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(c.isLiked(by: uid) ? SE.bad : SE.ink3)
                    .padding(.top, 4)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(c.isLiked(by: uid) ? "Unlike" : "Like")
        }
        .padding(.leading, indented ? 34 : 0)
        .accessibilityIdentifier("comment-row")
    }

    private var composer: some View {
        VStack(spacing: 0) {
            Divider()
            if let replyTo {
                HStack(spacing: 6) {
                    Text("Replying to \(replyTo.author)").font(.se(13)).foregroundStyle(SE.ink3)
                    Spacer()
                    Button { self.replyTo = nil } label: { Image(systemName: "xmark").font(.system(size: 11, weight: .bold)) }
                        .foregroundStyle(SE.ink3).buttonStyle(.plain)
                }
                .padding(.horizontal, 16).padding(.top, 8)
            }
            HStack(alignment: .bottom, spacing: 10) {
                TextField(replyTo == nil ? "Add a comment…" : "Write a reply…", text: $draft, axis: .vertical)
                    .font(.se(16)).lineLimit(1...4).focused($writing)
                    .padding(.horizontal, 12).padding(.vertical, 9)
                    .overlay(RoundedRectangle(cornerRadius: 18).stroke(SE.line))
                    .accessibilityIdentifier("comment-field")
                Button {
                    let body = draft, parent = replyTo
                    Task {
                        if await store.post(bbl: building.bbl, body: body, replyingTo: parent) {
                            draft = ""; replyTo = nil; writing = false
                        }
                    }
                } label: {
                    Text(store.posting ? "…" : "Post").font(.se(16, .bold))
                        .foregroundStyle(canPost ? SE.royal : SE.ink3)
                }
                .buttonStyle(.plain).disabled(!canPost || store.posting)
                .accessibilityIdentifier("comment-post")
            }
            .padding(.horizontal, 16).padding(.vertical, 10)
            if let e = store.error {
                Text(e).font(.se(13)).foregroundStyle(SE.bad).padding(.horizontal, 16).padding(.bottom, 8)
            }
        }
        .background(Color.white)
    }

    private var canPost: Bool { !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    private func message(_ title: String, _ body: String) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.se(19, .bold)).foregroundStyle(SE.ink)
            Text(body).font(.se(16)).foregroundStyle(SE.ink2)
        }
        .padding(.top, 24)
        .accessibilityIdentifier("comments-empty")
    }

    private func initials(_ name: String) -> String {
        let parts = name.split(separator: " ").prefix(2)
        let s = parts.compactMap { $0.first }.map(String.init).joined()
        return s.isEmpty ? "?" : s.uppercased()
    }
}
