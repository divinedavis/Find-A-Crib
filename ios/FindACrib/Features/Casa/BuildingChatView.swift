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
    @State private var showPlus = false
    @State private var sending = false
    @State private var reporting: BuildingChat.Message?
    @State private var reported = false
    @State private var confirmLeave = false
    @State private var detail: BuildingChat.Message?
    @State private var menu: MenuTarget?
    @State private var replyingTo: BuildingChat.Message?
    @State private var reactionsOf: BuildingChat.Message?
    @State private var timeShift: CGFloat = 0
    @State private var replyPull: [Int: CGFloat] = [:]
    @State private var atBottom = true
    @FocusState private var typing: Bool

    /// The message held down, and where its bubble sits on screen.
    struct MenuTarget: Identifiable { let message: BuildingChat.Message; let frame: CGRect; var id: Int { message.id } }

    init(bbl: String, address: String) {
        self.bbl = bbl; self.address = address
        _chat = State(initialValue: BuildingChat(bbl: bbl))
    }

    var body: some View {
        NavigationStack {
            Group {
                if BuildingChat.isDemo && chat.joined { room }
                else if !auth.isSignedIn { signedOut }
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
        .task(id: auth.isSignedIn) { if auth.isSignedIn || BuildingChat.isDemo { await chat.start(auth: auth) } }
        .onDisappear { Task { await chat.stop() } }
        .sheet(isPresented: $signIn) { EmailSignInView(offersSocialSignIn: true, purpose: .chat) }
        .sheet(isPresented: $showPlus) { PaywallView(source: "phone") }
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
        .sheet(item: $detail) { m in
            MessageDetail(message: m, onReport: { reporting = m; detail = nil },
                          onBlock: { Task { await chat.block(m.sender) }; detail = nil })
                .presentationDetents([.medium])
        }
        .sheet(item: $reactionsOf) { m in
            ReactionList(reactions: chat.reactions(on: m.id)) { r in
                Task { await chat.react(m, emoji: r.emoji, name: name) }
                reactionsOf = nil
            }
            .presentationDetents([.fraction(0.35), .medium])
        }
        .accessibilityIdentifier("chat-sheet")
        // After the identifier, so the menu's buttons keep their own.
        .overlay { if let menu { MessageMenu(target: menu, chat: chat, actions: menuActions(menu.message), close: { closeMenu() }) } }
    }

    // MARK: - Before joining

    // What joining gets, one Plus feature, then Apple, Google and email on
    // the screen itself (owner, 2026-10-27).
    private var signedOut: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                lockLine
                Text("Talk with the people in \(address)").font(.se(22, .bold)).foregroundStyle(SE.ink)
                PurposePromiseBox(purpose: .chat) { showPlus = true }
                if auth.configured { SocialSignInButtons() }
                SEOutlineButton(title: String(localized: "Sign in with email"), icon: "envelope.fill") { signIn = true }
                    .accessibilityIdentifier("chat-signin")
            }
            .padding(16)
        }
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
    //
    // Instagram's direct-message layout (owner, 2026-10-23, from a screen
    // recording), in Find A Crib's colours: yours on the right in teal,
    // neighbors' on the left in white with their initials beside the last
    // bubble of a run and their name over the first; a centred time line
    // after a gap; swipe a bubble right to reply, swipe left to see every
    // message's time; hold one for reactions and Reply / Copy / Delete for
    // you / Unsend; double-tap for a heart; ↓ jumps back to the newest.

    private var visible: [BuildingChat.Message] {
        chat.messages.filter { !chat.blocked.contains($0.sender) && !chat.hidden.contains($0.id) }
    }

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
                    LazyVStack(alignment: .leading, spacing: 0) {
                        if visible.isEmpty {
                            Text("No messages yet. Say hello to your neighbors.")
                                .font(.se(16)).foregroundStyle(SE.ink3).padding(.top, 40).frame(maxWidth: .infinity)
                                .accessibilityIdentifier("chat-empty")
                        }
                        ForEach(ChatLayout.runs(visible)) { run in
                            if let stamp = run.stamp { stampLine(stamp) }
                            runView(run, proxy: proxy)
                        }
                        if !chat.typing.isEmpty { typingBubble.id("typing") }
                        Color.clear.frame(height: 1).id("bottom")
                    }
                    .padding(.horizontal, 12).padding(.bottom, 12)
                    .frame(maxWidth: 720).frame(maxWidth: .infinity)
                }
                .refreshable { await chat.refresh() }
                .scrollDismissesKeyboard(.interactively)
                .defaultScrollAnchor(.bottom)
                .modifier(BottomTracker(atBottom: $atBottom))
                .onChange(of: chat.messages.last?.id) { _, id in
                    // New messages pull you down only if you were already at the bottom, or sent it.
                    guard id != nil, atBottom || chat.messages.last?.mine == true else { return }
                    withAnimation { proxy.scrollTo("bottom", anchor: .bottom) }
                }
                .onChange(of: chat.typing.isEmpty) { _, empty in
                    if !empty, atBottom { withAnimation { proxy.scrollTo("bottom", anchor: .bottom) } }
                }
                .onAppear { proxy.scrollTo("bottom", anchor: .bottom) }
                .overlay(alignment: .bottomTrailing) {
                    if !atBottom {
                        Button { withAnimation { proxy.scrollTo("bottom", anchor: .bottom) } } label: {
                            Image(systemName: "arrow.down").font(.system(size: 17, weight: .bold)).foregroundStyle(SE.ink)
                                .frame(width: 40, height: 40)
                                .background(Circle().fill(Color.white).shadow(color: .black.opacity(0.18), radius: 6, y: 2))
                        }
                        .buttonStyle(.plain).padding(16)
                        .transition(.scale.combined(with: .opacity))
                        .accessibilityLabel(String(localized: "Jump to the newest message"))
                        .accessibilityIdentifier("chat-jump")
                    }
                }
            }
            if let e = chat.error { Text(e).font(.se(14)).foregroundStyle(SE.bad).padding(.horizontal, 16).padding(.top, 6) }
            if let r = replyingTo { replyBar(r) }
            composer
        }
    }

    /// A centred time after a gap or a new day, Instagram's "YESTERDAY 10:20 AM".
    private func stampLine(_ text: String) -> some View {
        Text(text.uppercased())
            .font(.se(12, .semibold)).kerning(0.3).foregroundStyle(SE.ink3)
            .frame(maxWidth: .infinity).padding(.top, 18).padding(.bottom, 6)
            .accessibilityLabel(text)
            .accessibilityIdentifier("chat-stamp")
    }

    private func runView(_ run: ChatLayout.Run, proxy: ScrollViewProxy) -> some View {
        let first = run.messages[0]
        return VStack(alignment: first.mine ? .trailing : .leading, spacing: 2) {
            if !first.mine && first.reply == nil {
                Text(first.name).font(.se(12.5)).foregroundStyle(SE.ink3).lineLimit(1)
                    .padding(.leading, 48).padding(.bottom, 1)
            }
            ForEach(Array(run.messages.enumerated()), id: \.element.id) { i, m in
                row(m, first: i == 0, last: i == run.messages.count - 1, proxy: proxy).id(m.id)
            }
        }
        .padding(.top, 8)
    }

    /// One message: quote, bubble, reactions; the avatar beside a neighbor's
    /// last bubble; the time it slides out to when the room is swiped left.
    private func row(_ m: BuildingChat.Message, first: Bool, last: Bool, proxy: ScrollViewProxy) -> some View {
        let pull = replyPull[m.id] ?? 0
        let reactions = chat.reactions(on: m.id)
        return HStack(alignment: .bottom, spacing: 8) {
            if !m.mine {
                Group {
                    if last { Avatar(name: m.name) } else { Color.clear }
                }
                .frame(width: 28, height: 28)
            }
            VStack(alignment: m.mine ? .trailing : .leading, spacing: 2) {
                if let q = m.reply { quote(q, in: m, proxy: proxy) }
                bubble(m, first: first && m.reply == nil, last: last)
                    .overlay(alignment: m.mine ? .bottomTrailing : .bottomLeading) {
                        if !reactions.isEmpty { reactionPill(reactions, on: m).offset(x: m.mine ? -8 : 8, y: 16) }
                    }
                    .padding(.bottom, reactions.isEmpty ? 0 : 16)
            }
            .frame(maxWidth: .infinity, alignment: m.mine ? .trailing : .leading)
            .padding(m.mine ? .leading : .trailing, 56)
        }
        .overlay(alignment: .leading) {
            // The reply arrow that appears as the bubble is pulled right.
            Image(systemName: "arrowshape.turn.up.left.fill")
                .font(.system(size: 15)).foregroundStyle(SE.ink3)
                .padding(8).background(Circle().fill(SE.line.opacity(0.35)))
                .opacity(Double(min(pull / 56, 1))).scaleEffect(0.6 + 0.4 * min(pull / 56, 1))
                .offset(x: -40 + min(pull, 56) * 0.7)
                .accessibilityHidden(true)
        }
        .offset(x: pull + timeShift)
        .overlay(alignment: .trailing) {
            Text(m.at.formatted(date: .omitted, time: .shortened))
                .font(.se(11.5)).monospacedDigit().foregroundStyle(SE.ink3).fixedSize()
                .offset(x: 66 + timeShift)
                .opacity(Double(-timeShift / 60))
                .accessibilityIdentifier("chat-time")
        }
        .padding(.top, first ? 0 : 0)
        .contentShape(Rectangle())
        .simultaneousGesture(swipe(m))
    }

    /// Right on a bubble = reply to it; left anywhere = everyone's times.
    private func swipe(_ m: BuildingChat.Message) -> some Gesture {
        DragGesture(minimumDistance: 14)
            .onChanged { v in
                let dx = v.translation.width, dy = v.translation.height
                guard abs(dx) > abs(dy) * 1.4 else { return }
                if dx > 0, m.text != nil { replyPull[m.id] = min(dx * 0.75, 72) }
                else if dx < 0 { timeShift = max(dx * 0.8, -64) }
            }
            .onEnded { _ in
                if (replyPull[m.id] ?? 0) >= 56 {
                    UIImpactFeedbackGenerator(style: .light).impactOccurred()
                    replyingTo = m; typing = true
                }
                withAnimation(.spring(response: 0.3, dampingFraction: 0.8)) { replyPull[m.id] = nil; timeShift = 0 }
            }
    }

    private func bubble(_ m: BuildingChat.Message, first: Bool, last: Bool) -> some View {
        // Joined corners on the sender's side, as a run stacks.
        let big: CGFloat = 20, small: CGFloat = 5
        let shape = UnevenRoundedRectangle(
            topLeadingRadius: m.mine || first ? big : small, bottomLeadingRadius: m.mine || last ? big : small,
            bottomTrailingRadius: !m.mine || last ? big : small, topTrailingRadius: !m.mine || first ? big : small)
        let readable = m.text != nil
        return Text(m.text ?? String(localized: "Sent before this phone joined, so it can't be read here"))
            .font(.se(17)).italic(!readable)
            .foregroundStyle(!readable ? SE.ink3 : (m.mine ? .white : SE.ink))
            .multilineTextAlignment(.leading)
            .padding(.horizontal, 14).padding(.vertical, 9)
            .background(m.mine && readable ? SE.royal : Color.white, in: shape)
            .overlay { GeometryReader { g in
                Color.clear.contentShape(shape)
                    .onTapGesture(count: 2) { if readable { heart(m) } }
                    .onLongPressGesture(minimumDuration: 0.3) { openMenu(m, frame: g.frame(in: .global)) }
            } }
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(a11yLabel(m))
            .accessibilityAddTraits(.isButton)
            .accessibilityAction { openMenu(m, frame: .zero) }
            .accessibilityAction(named: String(localized: "Reply")) { replyingTo = m; typing = true }
            .accessibilityAction(named: String(localized: "React with a heart")) { heart(m) }
            .accessibilityIdentifier("chat-message")
    }

    private func a11yLabel(_ m: BuildingChat.Message) -> String {
        let who = m.mine ? String(localized: "You") : m.name
        let text = m.text ?? String(localized: "A message this phone can't read")
        let rs = chat.reactions(on: m.id).map(\.emoji).joined(separator: " ")
        return [who, text, m.at.formatted(date: .omitted, time: .shortened), rs].filter { !$0.isEmpty }.joined(separator: ", ")
    }

    private func heart(_ m: BuildingChat.Message) {
        UIImpactFeedbackGenerator(style: .light).impactOccurred()
        Task { await chat.react(m, emoji: "❤️", name: name) }
    }

    /// The faded bubble a reply answers, under who replied to whom; tap it to scroll there.
    private func quote(_ q: BuildingChat.Quote, in m: BuildingChat.Message, proxy: ScrollViewProxy) -> some View {
        let original = chat.messages.first { $0.id == q.id }
        let to = original?.mine == true ? String(localized: "you") : (original?.name ?? q.n)
        let caption = m.mine ? (original?.mine == true ? String(localized: "You replied to yourself") : String(localized: "You replied to \(to)"))
                             : String(localized: "Replied to \(to)")
        return VStack(alignment: m.mine ? .trailing : .leading, spacing: 3) {
            Label(caption, systemImage: "arrowshape.turn.up.left.fill")
                .font(.se(12)).foregroundStyle(SE.ink3).labelStyle(.titleAndIcon).imageScale(.small)
            Button {
                if original != nil { withAnimation { proxy.scrollTo(q.id, anchor: .center) } }
            } label: {
                Text(q.t).font(.se(15)).foregroundStyle(SE.ink2).lineLimit(2).multilineTextAlignment(.leading)
                    .padding(.horizontal, 12).padding(.vertical, 7)
                    .background(SE.line.opacity(0.35), in: RoundedRectangle(cornerRadius: 16))
            }
            .buttonStyle(.plain)
        }
        .padding(.bottom, -6)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("chat-quote")
    }

    private func reactionPill(_ rs: [BuildingChat.Reaction], on m: BuildingChat.Message) -> some View {
        var seen = Set<String>()
        let emojis = rs.map(\.emoji).filter { seen.insert($0).inserted }.prefix(3)
        return Button { reactionsOf = m } label: {
            HStack(spacing: 2) {
                Text(emojis.joined()).font(.system(size: 13))
                if rs.count > 1 { Text("\(rs.count)").font(.se(12, .semibold)).foregroundStyle(SE.ink2) }
            }
            .padding(.horizontal, 6).padding(.vertical, 3)
            .background(Capsule().fill(Color.white))
            .overlay(Capsule().stroke(SE.canvas, lineWidth: 2))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(String(localized: "Reactions: \(rs.map(\.emoji).joined(separator: " "))"))
        .accessibilityIdentifier("chat-reactions")
    }

    /// Someone is writing: their bubble shows up before their message does.
    private var typingBubble: some View {
        HStack(alignment: .bottom, spacing: 8) {
            Avatar(name: chat.typing.first ?? "").frame(width: 28, height: 28)
            VStack(alignment: .leading, spacing: 4) {
                TypingDots()
                    .padding(.horizontal, 14).padding(.vertical, 12)
                    .background(Color.white, in: RoundedRectangle(cornerRadius: 20))
                Text(ChatLayout.typingLine(chat.typing)).font(.se(12.5)).foregroundStyle(SE.ink3)
            }
            Spacer(minLength: 0)
        }
        .padding(.top, 10)
        .transition(.opacity.combined(with: .move(edge: .bottom)))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("chat-typing")
    }

    // MARK: - Hold menu

    private func openMenu(_ m: BuildingChat.Message, frame: CGRect) {
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()
        typing = false
        withAnimation(.spring(response: 0.28, dampingFraction: 0.85)) { menu = MenuTarget(message: m, frame: frame) }
    }

    private func closeMenu() { withAnimation(.easeOut(duration: 0.18)) { menu = nil } }

    private func menuActions(_ m: BuildingChat.Message) -> [MessageMenu.Action] {
        var a: [MessageMenu.Action] = []
        if m.text != nil {
            a.append(.init(title: String(localized: "Reply"), icon: "arrowshape.turn.up.left", id: "chat-menu-reply") { replyingTo = m; typing = true })
            a.append(.init(title: String(localized: "Copy"), icon: "doc.on.doc", id: "chat-menu-copy") { UIPasteboard.general.string = m.text })
        }
        a.append(.init(title: String(localized: "Details"), icon: "info.circle", id: "chat-menu-details") { detail = m })
        a.append(.init(title: String(localized: "Delete for you"), icon: "trash", id: "chat-menu-delete") { chat.hideForMe(m) })
        if m.mine {
            a.append(.init(title: String(localized: "Unsend"), icon: "arrow.uturn.backward.circle", role: .destructive, id: "chat-menu-unsend") {
                Task { await chat.unsend(m) }
            })
        } else {
            a.append(.init(title: String(localized: "Report"), icon: "flag", role: .destructive, id: "chat-menu-report") { reporting = m })
            a.append(.init(title: String(localized: "Block \(m.name)"), icon: "hand.raised", role: .destructive, id: "chat-menu-block") {
                Task { await chat.block(m.sender) }
            })
        }
        return a
    }

    // MARK: - Composer

    private func replyBar(_ r: BuildingChat.Message) -> some View {
        HStack(alignment: .center, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(r.mine ? String(localized: "Replying to yourself") : String(localized: "Replying to \(r.name)"))
                    .font(.se(13, .semibold)).foregroundStyle(SE.ink)
                Text(r.text ?? "").font(.se(13)).foregroundStyle(SE.ink3).lineLimit(1)
            }
            Spacer(minLength: 8)
            Button { withAnimation { replyingTo = nil } } label: {
                Image(systemName: "xmark").font(.system(size: 14, weight: .semibold)).foregroundStyle(SE.ink2).padding(6)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(String(localized: "Cancel reply"))
            .accessibilityIdentifier("chat-reply-cancel")
        }
        .padding(.horizontal, 16).padding(.vertical, 8)
        .background(Color.white)
        .overlay(alignment: .top) { Rectangle().fill(SE.line.opacity(0.5)).frame(height: 0.5) }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chat-replying")
    }

    private var composer: some View {
        let empty = draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        return HStack(alignment: .bottom, spacing: 8) {
            TextField(String(localized: "Message..."), text: $draft, axis: .vertical)
                .lineLimit(1...5).font(.se(17)).focused($typing)
                .padding(.leading, 16).padding(.vertical, 10)
                .onChange(of: draft) { _, d in chat.userTyped(d) }
                .accessibilityIdentifier("chat-input")
            if !empty {
                Button {
                    let text = draft, reply = replyingTo
                    sending = true
                    Task {
                        if await chat.send(text, name: name, replyTo: reply) { draft = ""; replyingTo = nil }
                        sending = false
                    }
                } label: {
                    Image(systemName: "arrow.up").font(.system(size: 16, weight: .bold)).foregroundStyle(.white)
                        .frame(width: 34, height: 34).background(Circle().fill(SE.royal))
                }
                .buttonStyle(.plain).padding(4)
                .disabled(sending)
                .transition(.scale.combined(with: .opacity))
                .accessibilityLabel("Send").accessibilityIdentifier("chat-send")
            }
        }
        .frame(minHeight: 44)
        .background(Color.white, in: RoundedRectangle(cornerRadius: 22))
        .overlay(RoundedRectangle(cornerRadius: 22).stroke(SE.line.opacity(0.6)))
        .animation(.easeOut(duration: 0.15), value: empty)
        .padding(.horizontal, 12).padding(.vertical, 8).background(SE.canvas)
    }
}

/// Whether the room is scrolled to the newest message, for the ↓ button.
/// iOS 18 reads the scroll position; on 17 the button never shows (an
/// on-appear marker at the bottom of the list fed back into the layout and
/// spun the main thread after a send).
private struct BottomTracker: ViewModifier {
    @Binding var atBottom: Bool
    func body(content: Content) -> some View {
        if #available(iOS 18, *) {
            content.onScrollGeometryChange(for: Bool.self) { g in
                g.contentOffset.y + g.containerSize.height >= g.contentSize.height - 60
            } action: { _, now in
                if atBottom != now { atBottom = now }
            }
        } else {
            content
        }
    }
}

/// A neighbor's initials in a circle, beside their last bubble.
struct Avatar: View {
    let name: String
    var body: some View {
        Text(ChatLayout.initials(name))
            .font(.se(11, .bold)).foregroundStyle(SE.royal)
            .frame(width: 28, height: 28)
            .background(Circle().fill(SE.royal.opacity(0.13)))
            .accessibilityHidden(true)
    }
}

/// Instagram's hold menu: the room blurs, the bubble lifts with a row of
/// reactions above it and the actions below.
struct MessageMenu: View {
    struct Action: Identifiable {
        let title: String
        let icon: String
        var role: ButtonRole? = nil
        let id: String
        let run: () -> Void
    }
    let target: BuildingChatView.MenuTarget
    let chat: BuildingChat
    let actions: [Action]
    let close: () -> Void
    @AppStorage(BuildingChat.nameKey) private var name = ""
    @State private var more = false

    var body: some View {
        GeometryReader { g in
            let m = target.message
            let mine = chat.reactions(on: m.id).first(where: \.mine)?.emoji
            let origin = g.frame(in: .global).origin
            let menuHeight = CGFloat(actions.count) * 46 + 16
            let bubbleH = min(max(target.frame.height, 40), 220)
            let need = 60 + bubbleH + 10 + menuHeight + (more ? 110 : 0)
            let wantTop = target.frame == .zero ? (g.size.height - need) / 2 : target.frame.minY - origin.y - 60
            let top = min(max(wantTop, g.safeAreaInsets.top + 8), max(g.safeAreaInsets.top + 8, g.size.height - need - 12))
            ZStack(alignment: .top) {
                Rectangle().fill(.ultraThinMaterial).overlay(Color.black.opacity(0.15))
                    .ignoresSafeArea()
                    .onTapGesture(perform: close)
                    .accessibilityLabel(String(localized: "Close"))
                    .accessibilityAddTraits(.isButton)
                    .accessibilityIdentifier("chat-hold-menu")
                VStack(alignment: m.mine ? .trailing : .leading, spacing: 10) {
                    emojiBar(m, current: mine)
                    Text(m.text ?? String(localized: "Sent before this phone joined, so it can't be read here"))
                        .font(.se(17)).foregroundStyle(m.mine && m.text != nil ? .white : SE.ink).lineLimit(8)
                        .padding(.horizontal, 14).padding(.vertical, 9)
                        .background(m.mine && m.text != nil ? SE.royal : Color.white, in: RoundedRectangle(cornerRadius: 20))
                        .frame(maxWidth: 300, alignment: m.mine ? .trailing : .leading)
                    VStack(alignment: .leading, spacing: 0) {
                        Text(m.at.formatted(.dateTime.weekday(.abbreviated).hour().minute()).uppercased())
                            .font(.se(12, .semibold)).foregroundStyle(SE.ink3).padding(.horizontal, 16).padding(.vertical, 8)
                        ForEach(actions) { a in
                            Button(role: a.role) { close(); a.run() } label: {
                                Label(a.title, systemImage: a.icon).font(.se(16))
                                    .foregroundStyle(a.role == .destructive ? SE.bad : SE.ink)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .padding(.horizontal, 16).frame(height: 44).contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .accessibilityIdentifier(a.id)
                        }
                    }
                    .padding(.bottom, 6)
                    .frame(width: 240)
                    .background(RoundedRectangle(cornerRadius: 16).fill(Color.white).shadow(color: .black.opacity(0.15), radius: 14, y: 4))
                }
                .padding(.horizontal, 16)
                .frame(maxWidth: .infinity, alignment: m.mine ? .trailing : .leading)
                .padding(.top, top)
            }
            .transition(.opacity)
        }
        .ignoresSafeArea(.keyboard)
    }

    private func emojiBar(_ m: BuildingChat.Message, current: String?) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 4) {
                ForEach(BuildingChat.quickReactions, id: \.self) { e in emojiButton(e, m: m, current: current) }
                Button { withAnimation(.snappy) { more.toggle() } } label: {
                    Image(systemName: more ? "minus" : "plus").font(.system(size: 17, weight: .semibold)).foregroundStyle(SE.ink2)
                        .frame(width: 38, height: 38).background(Circle().fill(SE.canvas))
                }
                .buttonStyle(.plain)
                .accessibilityLabel(String(localized: "More reactions"))
                .accessibilityIdentifier("chat-react-more")
            }
            if more {
                LazyVGrid(columns: Array(repeating: GridItem(.fixed(40), spacing: 4), count: 6), spacing: 4) {
                    ForEach(BuildingChat.moreReactions, id: \.self) { e in emojiButton(e, m: m, current: current) }
                }
            }
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
        .background(RoundedRectangle(cornerRadius: 26).fill(Color.white).shadow(color: .black.opacity(0.15), radius: 12, y: 4))
        .opacity(m.text == nil ? 0 : 1)
    }

    private func emojiButton(_ e: String, m: BuildingChat.Message, current: String?) -> some View {
        Button {
            UIImpactFeedbackGenerator(style: .light).impactOccurred()
            close()
            Task { await chat.react(m, emoji: e, name: name) }
        } label: {
            Text(e).font(.system(size: 26)).frame(width: 40, height: 40)
                .background(Circle().fill(current == e ? SE.royal.opacity(0.18) : .clear))
        }
        .buttonStyle(.plain)
        .accessibilityLabel(current == e ? String(localized: "Remove \(e)") : String(localized: "React \(e)"))
        .accessibilityIdentifier("chat-react-\(e)")
    }
}

/// Who reacted with what; your own row takes yours back.
struct ReactionList: View {
    let reactions: [BuildingChat.Reaction]
    let remove: (BuildingChat.Reaction) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("Reactions").font(.se(17, .bold)).foregroundStyle(SE.ink).padding(.horizontal, 20).padding(.vertical, 16)
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(reactions) { r in
                        HStack(spacing: 12) {
                            Avatar(name: r.name)
                            VStack(alignment: .leading, spacing: 1) {
                                Text(r.mine ? String(localized: "You") : r.name).font(.se(16, .semibold)).foregroundStyle(SE.ink)
                                if r.mine { Text("Tap to remove").font(.se(13)).foregroundStyle(SE.ink3) }
                            }
                            Spacer()
                            Text(r.emoji).font(.system(size: 24))
                        }
                        .padding(.horizontal, 20).padding(.vertical, 8)
                        .contentShape(Rectangle())
                        .onTapGesture { if r.mine { remove(r) } }
                        .accessibilityElement(children: .combine)
                        .accessibilityAddTraits(r.mine ? .isButton : [])
                    }
                }
            }
        }
        .accessibilityIdentifier("chat-reaction-list")
    }
}

/// Grouping and labels for the room, kept out of the view so they're tested.
enum ChatLayout {
    struct Run: Identifiable {
        let messages: [BuildingChat.Message]
        let stamp: String?             // the centred time line above the run, if any
        var id: Int { messages[0].id }
    }

    /// A gap this long, or a new day, gets a centred time line.
    static let stampGap: TimeInterval = 60 * 60

    /// Consecutive messages from one sender within 5 minutes stack as one run.
    static func runs(_ ms: [BuildingChat.Message], calendar: Calendar = .current, now: Date = Date()) -> [Run] {
        var out: [Run] = [], cur: [BuildingChat.Message] = [], label: String?
        var prev: BuildingChat.Message?
        func flush() { if !cur.isEmpty { out.append(Run(messages: cur, stamp: label)); cur = []; label = nil } }
        for m in ms {
            if prev == nil || !calendar.isDate(m.at, inSameDayAs: prev!.at) || m.at.timeIntervalSince(prev!.at) >= stampGap {
                flush(); label = stamp(m.at, calendar: calendar, now: now)
            }
            if let p = cur.last, p.sender != m.sender || m.at.timeIntervalSince(p.at) > 300 { flush() }
            cur.append(m); prev = m
        }
        flush()
        return out
    }

    /// Instagram's time lines: "10:20 AM" today, "Yesterday 10:20 AM",
    /// "Wed 10:07 PM" this week, "Sep 22 at 3:35 AM" before, the year if another.
    static func stamp(_ d: Date, calendar: Calendar = .current, now: Date = Date()) -> String {
        let time = d.formatted(date: .omitted, time: .shortened)
        if calendar.isDate(d, inSameDayAs: now) { return String(localized: "Today \(time)") }
        if let y = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(d, inSameDayAs: y) { return String(localized: "Yesterday \(time)") }
        if let week = calendar.date(byAdding: .day, value: -6, to: calendar.startOfDay(for: now)), d >= week {
            return "\(d.formatted(.dateTime.weekday(.abbreviated))) \(time)"
        }
        let sameYear = calendar.component(.year, from: d) == calendar.component(.year, from: now)
        let day = d.formatted(sameYear ? .dateTime.month(.abbreviated).day() : .dateTime.month(.abbreviated).day().year())
        return String(localized: "\(day) at \(time)")
    }

    static func initials(_ name: String) -> String {
        let words = name.split(whereSeparator: { !$0.isLetter && !$0.isNumber }).prefix(2)
        let s = words.compactMap(\.first).map(String.init).joined().uppercased()
        return s.isEmpty ? "•" : s
    }

    static func typingLine(_ names: [String]) -> String {
        switch names.count {
        case 0: return ""
        case 1: return String(localized: "\(names[0]) is typing…")
        case 2: return String(localized: "\(names[0]) and \(names[1]) are typing…")
        default: return String(localized: "\(names.count) neighbors are typing…")
        }
    }
}

/// Three dots that rise in turn, the usual "someone is writing" signal.
struct TypingDots: View {
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    var body: some View {
        TimelineView(.animation(minimumInterval: 1 / 30, paused: reduceMotion)) { t in
            let phase = t.date.timeIntervalSinceReferenceDate * 3
            HStack(spacing: 5) {
                ForEach(0..<3, id: \.self) { i in
                    Circle().fill(SE.ink3).frame(width: 8, height: 8)
                        .offset(y: reduceMotion ? 0 : -3 * max(0, sin(phase - Double(i) * 0.6)))
                        .opacity(reduceMotion ? 0.7 : 0.45 + 0.55 * max(0, sin(phase - Double(i) * 0.6)))
                }
            }
        }
        .frame(height: 12)
        .accessibilityLabel(String(localized: "Typing"))
    }
}

/// REVEAL: everything about one message, in a sheet or the side panel.
struct MessageDetail: View {
    let message: BuildingChat.Message
    let onReport: () -> Void
    let onBlock: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text(message.mine ? String(localized: "You") : message.name).font(.se(20, .bold)).foregroundStyle(SE.ink)
            if let t = message.text {
                Text(t).font(.se(17)).foregroundStyle(SE.ink).textSelection(.enabled)
            } else {
                Text("This phone joined after the message was sent, or it was sent to an older key. Only devices in the chat at the time can read it.")
                    .font(.se(15)).foregroundStyle(SE.ink2)
            }
            VStack(alignment: .leading, spacing: 8) {
                row(String(localized: "Sent"), message.at.formatted(date: .complete, time: .shortened))
                row(String(localized: "From"), message.fromWeb ? String(localized: "findacrib.com") : String(localized: "iPhone app"))
                row(String(localized: "Privacy"), String(localized: "End-to-end encrypted"))
            }
            if let t = message.text {
                Button { UIPasteboard.general.string = t } label: { Label(String(localized: "Copy"), systemImage: "doc.on.doc") }
                    .font(.se(16, .semibold)).foregroundStyle(SE.royal)
            }
            if !message.mine {
                HStack(spacing: 18) {
                    Button(action: onReport) { Label(String(localized: "Report"), systemImage: "flag") }
                        .accessibilityIdentifier("chat-detail-report")
                    Button(role: .destructive, action: onBlock) { Label(String(localized: "Block \(message.name)"), systemImage: "hand.raised") }
                }
                .font(.se(16, .semibold))
            }
            Spacer(minLength: 0)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("chat-detail")
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).font(.se(14, .semibold)).foregroundStyle(SE.ink3).frame(width: 70, alignment: .leading)
            Text(value).font(.se(15)).foregroundStyle(SE.ink2)
        }
    }
}
