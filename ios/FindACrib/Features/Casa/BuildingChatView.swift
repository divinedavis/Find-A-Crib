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
    @State private var detail: BuildingChat.Message?
    @State private var detailIsSheet = true
    @FocusState private var typing: Bool

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
    //
    // Laid out by six rules (owner, 2026-10-19, from a responsive-table
    // video): RANK who > what > when; STACK a sender's run under one header
    // (name left, time right, text below); SLOT the time always in the same
    // trailing place; LABEL what's ambiguous (day dividers, "You", why a
    // message can't be read) and nothing that isn't; REVEAL details by
    // tapping — a sheet, or a side panel when there's room, never a page;
    // BREAKPOINT on the room's own width (≥ 700 pt shows the panel).

    private var visible: [BuildingChat.Message] { chat.messages.filter { !chat.blocked.contains($0.sender) } }

    private var room: some View {
        GeometryReader { geo in
            let wide = geo.size.width >= 700
            HStack(spacing: 0) {
                roomColumn(wide: wide)
                if wide {
                    Divider()
                    detailPanel.frame(width: 300).background(Color.white)
                }
            }
        }
        .sheet(item: Binding(get: { detailIsSheet ? detail : nil }, set: { detail = $0 })) { m in
            MessageDetail(message: m, onReport: { reporting = m; detail = nil },
                          onBlock: { Task { await chat.block(m.sender) }; detail = nil })
                .presentationDetents([.medium])
        }
    }

    private func roomColumn(wide: Bool) -> some View {
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
                        ForEach(Array(ChatLayout.runs(visible).enumerated()), id: \.element.id) { _, run in
                            if let day = run.dayLabel { dayDivider(day) }
                            runView(run, wide: wide)
                        }
                        if !chat.typing.isEmpty { typingBubble.id("typing") }
                    }
                    .padding(.horizontal, 16).padding(.bottom, 12)
                    .frame(maxWidth: 720).frame(maxWidth: .infinity)
                }
                .refreshable { await chat.refresh() }
                .scrollDismissesKeyboard(.interactively)
                .onChange(of: chat.messages.last?.id) { _, id in
                    if let id { withAnimation { proxy.scrollTo(id, anchor: .bottom) } }
                }
                .onChange(of: chat.typing.isEmpty) { _, empty in
                    if !empty { withAnimation { proxy.scrollTo("typing", anchor: .bottom) } }
                }
                .onAppear { if let id = visible.last?.id { proxy.scrollTo(id, anchor: .bottom) } }
            }
            if let e = chat.error { Text(e).font(.se(14)).foregroundStyle(SE.bad).padding(.horizontal, 16).padding(.top, 6) }
            composer
        }
        .onAppear { detailIsSheet = !wide }
        .onChange(of: wide) { _, w in detailIsSheet = !w }
    }

    /// LABEL: dates get a divider; times don't need one.
    private func dayDivider(_ text: String) -> some View {
        HStack(spacing: 10) {
            Rectangle().fill(SE.line).frame(height: 1)
            Text(text).font(.se(13, .semibold)).foregroundStyle(SE.ink3).fixedSize()
            Rectangle().fill(SE.line).frame(height: 1)
        }
        .padding(.top, 18).padding(.bottom, 4)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("chat-day")
    }

    /// RANK + STACK + SLOT: one header per run — initials, name, then the
    /// time in the trailing slot — and the run's messages below it.
    private func runView(_ run: ChatLayout.Run, wide: Bool) -> some View {
        let first = run.messages[0]
        return VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(ChatLayout.initials(first.mine ? String(localized: "You") : first.name))
                    .font(.se(12, .bold)).foregroundStyle(first.mine ? .white : SE.royal)
                    .frame(width: 26, height: 26)
                    .background(Circle().fill(first.mine ? SE.royal : SE.royal.opacity(0.12)))
                    .alignmentGuide(.firstTextBaseline) { $0[VerticalAlignment.center] + 4 }
                    .accessibilityHidden(true)
                Text(first.mine ? String(localized: "You") : first.name)
                    .font(.se(15, .semibold)).foregroundStyle(SE.ink).lineLimit(1)
                Spacer(minLength: 8)
                Text(first.at.formatted(date: .omitted, time: .shortened))
                    .font(.se(13)).monospacedDigit().foregroundStyle(SE.ink3)
                    .accessibilityIdentifier("chat-time")
            }
            ForEach(run.messages) { m in bubble(m, wide: wide).id(m.id) }
        }
        .padding(.top, 12)
    }

    private func bubble(_ m: BuildingChat.Message, wide: Bool) -> some View {
        Button {
            detail = m
        } label: {
            Text(m.text ?? String(localized: "Sent before this phone joined, so it can't be read here"))
                .font(.se(17)).italic(m.text == nil)
                .foregroundStyle(m.text == nil ? SE.ink3 : (m.mine ? .white : SE.ink))
                .multilineTextAlignment(.leading)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .background(m.mine && m.text != nil ? SE.royal : Color.white, in: RoundedRectangle(cornerRadius: 14))
                .overlay(RoundedRectangle(cornerRadius: 14).stroke(detail?.id == m.id && wide ? SE.royal : .clear, lineWidth: 2))
        }
        .buttonStyle(.plain)
        .padding(.leading, 34)
        .frame(maxWidth: .infinity, alignment: .leading)
        .contextMenu {
            if !m.mine {
                Button(String(localized: "Report"), systemImage: "flag") { reporting = m }
                Button(String(localized: "Block \(m.name)"), systemImage: "hand.raised") { Task { await chat.block(m.sender) } }
            }
            if let t = m.text { Button(String(localized: "Copy"), systemImage: "doc.on.doc") { UIPasteboard.general.string = t } }
        }
        .accessibilityElement(children: .combine)
        .accessibilityHint(String(localized: "Shows details"))
        .accessibilityIdentifier("chat-message")
    }

    /// Someone is writing: their bubble shows up before their message does.
    private var typingBubble: some View {
        VStack(alignment: .leading, spacing: 4) {
            TypingDots()
                .padding(.horizontal, 14).padding(.vertical, 12)
                .background(Color.white, in: RoundedRectangle(cornerRadius: 14))
            Text(ChatLayout.typingLine(chat.typing)).font(.se(13)).foregroundStyle(SE.ink3)
        }
        .padding(.leading, 34).padding(.top, 10)
        .transition(.opacity.combined(with: .move(edge: .bottom)))
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("chat-typing")
    }

    /// REVEAL, wide layout: the selected message's details beside the room.
    @ViewBuilder private var detailPanel: some View {
        if let m = detail {
            MessageDetail(message: m, onReport: { reporting = m }, onBlock: { Task { await chat.block(m.sender) }; detail = nil })
        } else {
            Text("Tap a message to see when it was sent, or to report it.")
                .font(.se(15)).foregroundStyle(SE.ink3).padding(20)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
    }

    private var composer: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField(String(localized: "Message your building"), text: $draft, axis: .vertical)
                .lineLimit(1...5).font(.se(17)).focused($typing)
                .padding(.horizontal, 12).padding(.vertical, 10)
                .background(Color.white, in: RoundedRectangle(cornerRadius: 18))
                .overlay(RoundedRectangle(cornerRadius: 18).stroke(SE.line))
                .onChange(of: draft) { _, d in chat.userTyped(d) }
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

/// Grouping and labels for the room, kept out of the view so they're tested.
enum ChatLayout {
    struct Run: Identifiable {
        let messages: [BuildingChat.Message]
        let dayLabel: String?          // set on the first run of each day
        var id: Int { messages[0].id }
    }

    /// STACK: consecutive messages from one sender within 5 minutes share a header.
    static func runs(_ ms: [BuildingChat.Message], calendar: Calendar = .current, now: Date = Date()) -> [Run] {
        var out: [Run] = [], cur: [BuildingChat.Message] = [], label: String?
        var lastDay: Date?
        func flush() { if !cur.isEmpty { out.append(Run(messages: cur, dayLabel: label)); cur = []; label = nil } }
        for m in ms {
            let day = calendar.startOfDay(for: m.at)
            if day != lastDay { flush(); label = dayLabel(m.at, calendar: calendar, now: now); lastDay = day }
            if let prev = cur.last, prev.sender != m.sender || m.at.timeIntervalSince(prev.at) > 300 { flush() }
            cur.append(m)
        }
        flush()
        return out
    }

    static func dayLabel(_ d: Date, calendar: Calendar = .current, now: Date = Date()) -> String {
        if calendar.isDate(d, inSameDayAs: now) { return String(localized: "Today") }
        if let y = calendar.date(byAdding: .day, value: -1, to: now), calendar.isDate(d, inSameDayAs: y) { return String(localized: "Yesterday") }
        let sameYear = calendar.component(.year, from: d) == calendar.component(.year, from: now)
        return d.formatted(sameYear ? .dateTime.weekday(.abbreviated).month(.abbreviated).day() : .dateTime.month(.abbreviated).day().year())
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
        .accessibilityIdentifier("chat-detail")
    }

    private func row(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(label).font(.se(14, .semibold)).foregroundStyle(SE.ink3).frame(width: 70, alignment: .leading)
            Text(value).font(.se(15)).foregroundStyle(SE.ink2)
        }
    }
}
