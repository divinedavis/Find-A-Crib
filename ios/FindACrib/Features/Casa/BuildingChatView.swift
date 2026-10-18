import SwiftUI

/// Building chat (owner, 2026-10-17): everyone signed in who opens this
/// building in Your Crib can talk, live, end-to-end encrypted. Opens from
/// the "Building chat" button under the address. See BuildingChat.
struct BuildingChatView: View {
    let bbl: String
    let address: String
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @State private var chat: BuildingChat
    @State private var draft = ""
    @AppStorage(BuildingChat.nameKey) private var name = ""
    @State private var agreed = false
    @State private var signIn = false
    @State private var sending = false
    @State private var reporting: BuildingChat.Message?
    @State private var reported = false
    @State private var confirmLeave = false
    @FocusState private var typing: Bool

    init(bbl: String, address: String) {
        self.bbl = bbl; self.address = address
        _chat = State(initialValue: BuildingChat(bbl: bbl))
    }

    var body: some View {
        NavigationStack {
            Group {
                if !auth.isSignedIn { signedOut }
                else if chat.loading && !chat.joined { ProgressView().tint(SE.royal).frame(maxWidth: .infinity, maxHeight: .infinity) }
                else if !chat.joined { joinCard }
                else { room }
            }
            .background(SE.canvas)
            .navigationTitle(String(localized: "Building chat")).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
                if chat.joined {
                    ToolbarItem(placement: .primaryAction) {
                        Menu {
                            Button(String(localized: "Leave this chat"), role: .destructive) { confirmLeave = true }
                        } label: { Image(systemName: "ellipsis.circle") }
                        .accessibilityIdentifier("chat-menu")
                    }
                }
            }
        }
        .task(id: auth.isSignedIn) { if auth.isSignedIn { await chat.start(auth: auth) } }
        .onDisappear { Task { await chat.stop() } }
        .sheet(isPresented: $signIn) { EmailSignInView(offersSocialSignIn: true) }
        .confirmationDialog(String(localized: "Report this message?"), isPresented: Binding(get: { reporting != nil }, set: { if !$0 { reporting = nil } }), titleVisibility: .visible) {
            ForEach([String(localized: "Harassment or hate"), String(localized: "Threat or violence"), String(localized: "Spam or scam"), String(localized: "Something else")], id: \.self) { reason in
                Button(reason) {
                    guard let m = reporting else { return }
                    Task { reported = await chat.report(m, reason: reason) }
                }
            }
        } message: {
            Text("This sends the message's text to Find A Crib to review. Messages are otherwise unreadable to us.")
        }
        .alert(String(localized: "Thanks — we'll review it within 24 hours."), isPresented: $reported) { Button("OK", role: .cancel) {} }
        .confirmationDialog(String(localized: "Leave the chat for \(address)?"), isPresented: $confirmLeave, titleVisibility: .visible) {
            Button(String(localized: "Leave"), role: .destructive) { Task { await chat.leave() } }
        }
        .accessibilityIdentifier("chat-sheet")
    }

    // MARK: - Before joining

    private var signedOut: some View {
        VStack(alignment: .leading, spacing: 12) {
            lockLine
            Text("Talk with the people in \(address)").font(.se(22, .bold)).foregroundStyle(SE.ink)
            Text("Sign in to join your building's chat. Messages are end-to-end encrypted: only the people in the chat can read them.")
                .font(.se(16)).foregroundStyle(SE.ink2)
            SEPrimaryButton(title: String(localized: "Sign in to chat")) { signIn = true }
                .accessibilityIdentifier("chat-signin")
            Spacer()
        }
        .padding(16)
    }

    private var joinCard: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                lockLine
                Text("Talk with the people in \(address)").font(.se(22, .bold)).foregroundStyle(SE.ink)
                Text("Messages are end-to-end encrypted: only the people in this chat can read them — not Find A Crib, not your landlord. You'll see messages sent after you join.")
                    .font(.se(16)).foregroundStyle(SE.ink2)
                VStack(alignment: .leading, spacing: 6) {
                    Text("Your name in the chat").font(.se(14, .semibold)).foregroundStyle(SE.ink2)
                    SEFieldBox {
                        TextField(String(localized: "e.g. Maria, 4B"), text: $name)
                            .font(.se(18)).padding(.horizontal, 12).textInputAutocapitalization(.words)
                            .accessibilityIdentifier("chat-name")
                    }
                }
                // Apple 1.2: terms before posting, zero tolerance stated.
                Toggle(isOn: $agreed) {
                    Text("I'll be respectful. No harassment, hate, threats, spam or sharing people's private details. Find A Crib removes anyone who breaks these rules.")
                        .font(.se(15)).foregroundStyle(SE.ink2)
                }
                .tint(SE.royal).accessibilityIdentifier("chat-terms")
                SEPrimaryButton(title: String(localized: "Join the chat"), icon: "bubble.left.and.bubble.right.fill") {
                    Task { await chat.join() }
                }
                .disabled(!agreed || name.trimmingCharacters(in: .whitespaces).isEmpty)
                .opacity(agreed && !name.trimmingCharacters(in: .whitespaces).isEmpty ? 1 : 0.5)
                .accessibilityIdentifier("chat-join")
                if let e = chat.error { Text(e).font(.se(14)).foregroundStyle(SE.bad) }
            }
            .padding(16)
        }
    }

    private var lockLine: some View {
        Label(String(localized: "End-to-end encrypted"), systemImage: "lock.fill")
            .font(.se(14, .semibold)).foregroundStyle(SE.good)
    }

    // MARK: - The room

    private var visible: [BuildingChat.Message] { chat.messages.filter { !chat.blocked.contains($0.sender) } }

    private var room: some View {
        VStack(spacing: 0) {
            HStack {
                lockLine
                Spacer()
                Text(chat.memberCount == 1 ? String(localized: "Just you so far") : String(localized: "\(chat.memberCount) neighbors"))
                    .font(.se(14)).foregroundStyle(SE.ink3)
            }
            .padding(.horizontal, 16).padding(.vertical, 8).background(Color.white)
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 10) {
                        if visible.isEmpty {
                            Text("No messages yet. Say hello to your neighbors.")
                                .font(.se(16)).foregroundStyle(SE.ink3).padding(.top, 40).frame(maxWidth: .infinity)
                                .accessibilityIdentifier("chat-empty")
                        }
                        ForEach(visible) { m in bubble(m).id(m.id) }
                    }
                    .padding(16)
                }
                .refreshable { await chat.refresh() }
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: chat.messages.last?.id) { _, id in
                    if let id { withAnimation { proxy.scrollTo(id, anchor: .bottom) } }
                }
                .onAppear { if let id = visible.last?.id { proxy.scrollTo(id, anchor: .bottom) } }
            }
            if let e = chat.error { Text(e).font(.se(14)).foregroundStyle(SE.bad).padding(.horizontal, 16).padding(.top, 6) }
            composer
        }
    }

    private func bubble(_ m: BuildingChat.Message) -> some View {
        VStack(alignment: m.mine ? .trailing : .leading, spacing: 3) {
            if !m.mine { Text(m.name).font(.se(13, .semibold)).foregroundStyle(SE.ink3) }
            Text(m.text ?? String(localized: "Can't be read on this phone"))
                .font(.se(17)).italic(m.text == nil)
                .foregroundStyle(m.mine ? .white : SE.ink)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(m.mine ? SE.royal : Color.white, in: RoundedRectangle(cornerRadius: 14))
            Text(m.at.formatted(date: .omitted, time: .shortened)).font(.se(12)).foregroundStyle(SE.ink3)
        }
        .frame(maxWidth: .infinity, alignment: m.mine ? .trailing : .leading)
        .contextMenu {
            if !m.mine {
                Button(String(localized: "Report"), systemImage: "flag") { reporting = m }
                Button(String(localized: "Block \(m.name)"), systemImage: "hand.raised") { Task { await chat.block(m.sender) } }
            }
            if let t = m.text { Button(String(localized: "Copy"), systemImage: "doc.on.doc") { UIPasteboard.general.string = t } }
        }
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("chat-message")
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField(String(localized: "Message your building"), text: $draft, axis: .vertical)
                .lineLimit(1...5).font(.se(17)).focused($typing)
                .padding(.horizontal, 12).padding(.vertical, 10)
                .background(Color.white, in: RoundedRectangle(cornerRadius: 18))
                .overlay(RoundedRectangle(cornerRadius: 18).stroke(SE.line))
                .accessibilityIdentifier("chat-input")
            Button {
                let text = draft
                sending = true
                Task {
                    if await chat.send(text, name: name) { draft = "" }
                    sending = false
                }
            } label: {
                Image(systemName: "arrow.up.circle.fill").font(.system(size: 34)).foregroundStyle(SE.royal)
            }
            .buttonStyle(.plain)
            .disabled(sending || draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .accessibilityLabel("Send").accessibilityIdentifier("chat-send")
        }
        .padding(.horizontal, 12).padding(.vertical, 10).background(SE.canvas)
    }
}
