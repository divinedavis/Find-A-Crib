import SwiftUI
import UserNotifications

// Renter tools for people who already have a place (owner, 2026-10-13): Get a
// repair made, Is my rent increase legal?, Know your rights, Renewal coach.
// The same server rules the website uses (renter_tools.py, /api/ai/...): the
// phone decides nothing about the law. Repairs and rent checks are free with
// an account; the rights cards are public; the Renewal coach and every "✨"
// AI draft are Plus (a 402 opens the paywall).

struct ToolFinding: Decodable, Hashable { let level: String; let title: String; let why: String; let law: String? }

struct RepairResult: Decodable {
    struct Links: Decodable { let file_311: String; let legal_help: String }
    let issue: String, label: String, rule: String, law: String, urgent: Bool, ask_by: String, letter: String
    let steps: [String]
    let links: Links
}

struct RentIncreaseResult: Decodable {
    struct Links: Decodable { let rent_history: String; let legal_help: String }
    let verdict: String
    let allowed_rent: Double?
    let increase_pct: Double?
    let findings: [ToolFinding]
    let next_steps: [String]
    let links: Links
}

struct RightsCard: Decodable, Hashable, Identifiable { let id: String; let title: String; let text: String; let law: String }
struct RightsAnswer: Decodable { struct Src: Decodable, Hashable { let id: String; let title: String; let law: String }; let answer: String; let covered: Bool; let sources: [Src] }

struct RenewalPlan: Decodable {
    struct KeyDate: Decodable, Hashable { let date: String; let label: String; let past: Bool }
    struct Reminder: Decodable, Hashable { let date: String; let title: String; let body: String }
    struct Compare: Decodable { let zip: String; let beds: Int; let fmr: Double; let current_rent: Double; let diff_pct: Double; let source: String }
    let dates: [KeyDate]
    let reminders: [Reminder]
    let compare: Compare?
    let check: RentIncreaseResult?
}

struct RenewalScript: Decodable { let talking_points: [String]; let email_subject: String; let email_body: String }

extension AIService {
    static func repair(_ a: [String: Any], auth: AuthService) async throws -> RepairResult {
        try JSONDecoder().decode(RepairResult.self, from: try await post("repair", auth: auth, json: a))
    }
    static func repairLetter(_ a: [String: Any], auth: AuthService) async throws -> String {
        struct R: Decodable { let letter: String? }
        guard let l = try JSONDecoder().decode(R.self, from: try await post("repair-letter", auth: auth, json: a)).letter else { throw AIError.declined }
        return l
    }
    static func rentIncrease(_ a: [String: Any], auth: AuthService) async throws -> RentIncreaseResult {
        try JSONDecoder().decode(RentIncreaseResult.self, from: try await post("rent-increase", auth: auth, json: a))
    }
    /// Public: no account needed to read your rights.
    nonisolated static func rights() async throws -> [RightsCard] {
        struct R: Decodable { let cards: [RightsCard] }
        let (data, _) = try await URLSession.shared.data(from: URL(string: "rights", relativeTo: URL(string: "https://findacrib.com/api/ai/")!)!)
        return try JSONDecoder().decode(R.self, from: data).cards
    }
    static func rightsAsk(_ q: String, auth: AuthService) async throws -> RightsAnswer {
        struct R: Decodable { let ok: Bool; let answer: String?; let covered: Bool?; let sources: [RightsAnswer.Src]? }
        let r = try JSONDecoder().decode(R.self, from: try await post("rights-ask", auth: auth, json: ["question": q]))
        guard let a = r.answer else { throw AIError.declined }
        return RightsAnswer(answer: a, covered: r.covered ?? false, sources: r.sources ?? [])
    }
    static func renewal(_ a: [String: Any], auth: AuthService) async throws -> RenewalPlan {
        try JSONDecoder().decode(RenewalPlan.self, from: try await post("renewal", auth: auth, json: a))
    }
    static func renewalScript(_ a: [String: Any], auth: AuthService) async throws -> RenewalScript {
        struct R: Decodable { let talking_points: [String]?; let email_subject: String?; let email_body: String? }
        let r = try JSONDecoder().decode(R.self, from: try await post("renewal-script", auth: auth, json: a))
        guard let b = r.email_body else { throw AIError.declined }
        return RenewalScript(talking_points: r.talking_points ?? [], email_subject: r.email_subject ?? "", email_body: b)
    }

    nonisolated static func toolErrorText(_ e: Error) -> String {
        switch e as? AIError {
        case .dailyLimit: "That's a lot for one day — more tomorrow."
        case .monthlyLimit: "You've used this month's AI — more on the 1st."
        case .declined: "AI couldn't write this one — try rewording it."
        default: "Couldn't reach Find A Crib just now. Try again in a minute."
        }
    }
}

/// "2026-10-14" -> "October 14, 2026"
func niceDate(_ iso: String) -> String {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX")
    guard let d = f.date(from: iso) else { return iso }
    return d.formatted(.dateTime.month(.wide).day().year())
}

private let isoDay: (Date) -> String = { d in
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX"); return f.string(from: d)
}

/// A local reminder at 9 AM on the day: nothing leaves the phone.
enum ToolReminder {
    static func schedule(id: String, date: String, title: String, body: String) async -> Bool {
        let c = UNUserNotificationCenter.current()
        let s = await c.notificationSettings()
        if s.authorizationStatus == .notDetermined {
            guard (try? await c.requestAuthorization(options: [.alert, .sound])) == true else { return false }
        } else if s.authorizationStatus == .denied { return false }
        let p = date.split(separator: "-").compactMap { Int($0) }
        guard p.count == 3 else { return false }
        let content = UNMutableNotificationContent(); content.title = title; content.body = body
        let trig = UNCalendarNotificationTrigger(dateMatching: DateComponents(year: p[0], month: p[1], day: p[2], hour: 9), repeats: false)
        do { try await c.add(UNNotificationRequest(identifier: "fac.tool.\(id)", content: content, trigger: trig)); return true } catch { return false }
    }
}

private struct FindingsList: View {
    let findings: [ToolFinding]
    var body: some View {
        ForEach(findings, id: \.self) { f in
            VStack(alignment: .leading, spacing: 4) {
                Text(f.title).font(.se(16, .bold)).foregroundStyle(f.level == "illegal" ? SE.bad : f.level == "warn" ? SE.warn : SE.ink)
                Text(f.why).font(.se(15)).foregroundStyle(SE.ink2)
                if let law = f.law { Text(law).font(.se(13)).foregroundStyle(SE.ink3) }
            }.padding(.vertical, 2)
        }
    }
}

private struct LetterSection: View {
    let title: String
    let text: String
    let id: String
    @State private var copied = false
    var body: some View {
        Section(title) {
            Text(text).font(.se(15)).textSelection(.enabled).accessibilityIdentifier(id)
            Button(copied ? "Copied ✓" : "Copy") { UIPasteboard.general.string = text; copied = true }
                .font(.se(16, .semibold)).accessibilityIdentifier(id + "-copy")
            ShareLink(item: text) { Label("Send…", systemImage: "square.and.arrow.up").font(.se(16, .semibold)) }
        }
    }
}

private let notAdvice = "General information about NYC and New York State rules, not legal advice. Free help: call 311 and ask for the Tenant Helpline."

/// Signed out, a tool's first tap opens sign-in; without Plus, the paywall.
private struct ToolGate: ViewModifier {
    @Binding var signIn: Bool
    @Binding var paywall: String?
    func body(content: Content) -> some View {
        content
            .sheet(isPresented: $signIn) { EmailSignInView() }
            .sheet(item: Binding(get: { paywall.map { PaywallSource(id: $0) } }, set: { paywall = $0?.id })) { PaywallView(source: $0.id) }
    }
    struct PaywallSource: Identifiable { let id: String }
}

// MARK: - Get a repair made

struct RepairView: View {
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var issue = "heat"
    @State private var hasSince = false
    @State private var since = Date()
    @State private var address = ""
    @State private var unit = ""
    @State private var name = ""
    @State private var details = ""
    @State private var result: RepairResult?
    @State private var aiLetter: String?
    @State private var busy = false
    @State private var error: String?
    @State private var signIn = false
    @State private var paywall: String?
    @State private var reminded = false

    static let issues: [(String, String)] = [
        ("heat", "No heat or not enough heat"), ("hot_water", "No hot water"), ("leak", "Leak, water damage or plumbing"),
        ("mold", "Mold"), ("pests", "Roaches, mice, rats or bedbugs"), ("lead", "Peeling paint with a child under 6"),
        ("window_guards", "Missing window guards (child 10 or under)"), ("gas_electric", "No gas, electricity or cooking gas"),
        ("other", "Something else broken")]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Tell us what's broken. We'll show what NYC law requires, write the letter to your landlord, and walk you through 311 if it isn't fixed.")
                        .font(.se(15)).foregroundStyle(SE.ink2)
                }
                Section("What's wrong?") {
                    Picker("Problem", selection: $issue) { ForEach(Self.issues, id: \.0) { Text($0.1).tag($0.0) } }
                        .accessibilityIdentifier("repair-issue")
                    Toggle("I know when it started", isOn: $hasSince)
                    if hasSince { DatePicker("Since", selection: $since, in: ...Date(), displayedComponents: .date) }
                }
                Section("For the letter") {
                    TextField("Building address", text: $address).textContentType(.fullStreetAddress).accessibilityIdentifier("repair-address")
                    TextField("Apartment", text: $unit)
                    TextField("Your name", text: $name).textContentType(.name)
                    TextField("Describe it (optional)", text: $details, axis: .vertical).lineLimit(2...6)
                        .accessibilityIdentifier("repair-details")
                }
                Section {
                    Button { Task { await run(ai: false) } } label: {
                        HStack { Spacer(); if busy { ProgressView() } else { Text("Write my letter").font(.se(17, .bold)) }; Spacer() }
                    }.disabled(busy).accessibilityIdentifier("repair-run")
                    Button { Task { await run(ai: true) } } label: {
                        HStack { Spacer(); Text("✨ Write it in my words").font(.se(16, .semibold)); Spacer() }
                    }.disabled(busy || details.trimmingCharacters(in: .whitespaces).count < 5).accessibilityIdentifier("repair-ai")
                }
                if let error { Section { Text(error).font(.se(15)).foregroundStyle(SE.bad) } }
                if let r = result {
                    Section(r.urgent ? "🚨 What the law requires" : "What the law requires") {
                        Text(r.rule).font(.se(15))
                        Text(r.law).font(.se(13)).foregroundStyle(SE.ink3)
                    }.accessibilityIdentifier("repair-rule")
                    LetterSection(title: aiLetter == nil ? "Your letter" : "Your letter, in your words", text: aiLetter ?? r.letter, id: "repair-letter")
                    Section("What to do next") {
                        ForEach(Array(r.steps.enumerated()), id: \.offset) { i, s in Text("\(i + 1). \(s)").font(.se(15)) }
                        if let u = URL(string: r.links.file_311) { Button("File with 311") { openURL(u) }.font(.se(16, .semibold)) }
                        if let u = URL(string: r.links.legal_help) { Button("Free legal help") { openURL(u) }.font(.se(16, .semibold)) }
                        Button(reminded ? "Reminder set for \(niceDate(r.ask_by)) ✓" : "Remind me on \(niceDate(r.ask_by))") {
                            Task { reminded = await ToolReminder.schedule(id: "repair", date: r.ask_by, title: "Check on your repair",
                                                                         body: "\(r.label) — not fixed? File a complaint with 311.") }
                        }.font(.se(16, .semibold)).accessibilityIdentifier("repair-remind")
                        AddToCalendarButton(item: CalendarItem(title: "Check on my repair: \(r.label)", day: r.ask_by,
                                                               notes: "Not fixed? File a complaint with 311."))
                    }
                }
                Section { Text(notAdvice).font(.se(13)).foregroundStyle(SE.ink3) }
            }
            .navigationTitle("Get a repair made").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .modifier(ToolGate(signIn: $signIn, paywall: $paywall))
            .onAppear { Analytics.shared.track("tool_open", ["tool": "repair", "src": "app"]) }
        }
    }

    private var answers: [String: Any] {
        ["issue": issue, "since": hasSince ? isoDay(since) : "", "address": address, "unit": unit, "name": name, "details": String(details.prefix(600))]
    }

    private func run(ai: Bool) async {
        guard auth.isSignedIn else { signIn = true; return }
        busy = true; error = nil; defer { busy = false }
        do {
            let r = try await AIService.repair(answers, auth: auth)
            result = r; aiLetter = nil
            if ai {
                guard auth.hasPlus else { paywall = "renter_ai"; return }
                // On the phone when Apple's model is here; Claude on the server otherwise.
                // The name never goes to either: the phone fills [Your name] in.
                var a = answers; a["name"] = ""
                let local = OnDeviceAI.available ? try? await OnDeviceAI.repairLetter(r, address: address, unit: unit, details: String(details.prefix(600))) : nil
                let l: String
                if let local { l = local } else { l = try await AIService.repairLetter(a, auth: auth) }
                Analytics.shared.track("ai_engine", ["tool": "repair_letter", "on_device": local != nil])
                aiLetter = name.isEmpty ? l : l.replacingOccurrences(of: "[Your name]", with: name)
            }
            Analytics.shared.track("tool_result", ["tool": ai ? "repair_letter" : "repair", "issue": issue, "src": "app"])
        } catch {
            switch error as? AIError {
            case .signIn: signIn = true
            case .plus: paywall = "renter_ai"
            default: self.error = AIService.toolErrorText(error)
            }
        }
    }
}

// MARK: - Is my rent increase legal?

struct RentIncreaseView: View {
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var stabilized = "unsure"
    @State private var current = ""
    @State private var new = ""
    @State private var start = Date()
    @State private var term = "1"
    @State private var years = ""
    @State private var notice = ""
    @State private var result: RentIncreaseResult?
    @State private var busy = false
    @State private var error: String?
    @State private var signIn = false
    @State private var paywall: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Rent-stabilized renewals follow the Rent Guidelines Board — 0% for leases starting October 1, 2026 to September 30, 2027. Most other NYC apartments are covered by Good Cause Eviction.")
                        .font(.se(15)).foregroundStyle(SE.ink2)
                }
                Section("Is it rent-stabilized?") {
                    Picker("Rent-stabilized", selection: $stabilized) {
                        Text("Yes").tag("yes"); Text("No").tag("no"); Text("Not sure").tag("unsure")
                    }.pickerStyle(.segmented).accessibilityIdentifier("rentup-stabilized")
                }
                Section("The increase") {
                    money("Rent now", $current, id: "rentup-current")
                    money("New rent", $new, id: "rentup-new")
                    DatePicker("New lease starts", selection: $start, displayedComponents: .date)
                    Picker("Lease length", selection: $term) { Text("1 year").tag("1"); Text("2 years").tag("2") }
                    number("Years you've lived there", $years)
                    number("Days' notice you got", $notice)
                }
                Section {
                    Button { Task { await run() } } label: {
                        HStack { Spacer(); if busy { ProgressView() } else { Text("Check my increase").font(.se(17, .bold)) }; Spacer() }
                    }.disabled(busy || current.isEmpty || new.isEmpty).accessibilityIdentifier("rentup-run")
                }
                if let error { Section { Text(error).font(.se(15)).foregroundStyle(SE.bad) } }
                if let r = result {
                    Section {
                        Text(Self.verdictText(r.verdict) + (r.increase_pct.map { " (\($0.formatted())%)" } ?? ""))
                            .font(.se(18, .bold))
                            .foregroundStyle(r.verdict == "likely_illegal" ? SE.bad : r.verdict == "check" ? SE.warn : SE.good)
                            .accessibilityIdentifier("rentup-verdict")
                        FindingsList(findings: r.findings)
                    }
                    Section("What you can do") {
                        ForEach(Array(r.next_steps.enumerated()), id: \.offset) { i, s in Text("\(i + 1). \(s)").font(.se(15)) }
                        if let u = URL(string: r.links.rent_history) { Button("Request your rent history") { openURL(u) }.font(.se(16, .semibold)) }
                        if let u = URL(string: r.links.legal_help) { Button("Free legal help") { openURL(u) }.font(.se(16, .semibold)) }
                    }
                }
                Section { Text(notAdvice).font(.se(13)).foregroundStyle(SE.ink3) }
            }
            .navigationTitle("Rent increase check").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .modifier(ToolGate(signIn: $signIn, paywall: $paywall))
            .onAppear { Analytics.shared.track("tool_open", ["tool": "rentup", "src": "app"]) }
        }
    }

    nonisolated static func verdictText(_ v: String) -> String {
        switch v {
        case "likely_illegal": "This increase looks too high"
        case "check": "Worth a closer look"
        case "need_rents": "Add your rent now and the new rent"
        default: "This increase looks allowed"
        }
    }

    private func money(_ label: String, _ v: Binding<String>, id: String) -> some View {
        HStack { Text(label).font(.se(16)); Spacer()
            TextField("$0", text: v).keyboardType(.decimalPad).multilineTextAlignment(.trailing).frame(maxWidth: 130).font(.se(16)).accessibilityIdentifier(id) }
    }
    private func number(_ label: String, _ v: Binding<String>) -> some View {
        HStack { Text(label).font(.se(16)); Spacer()
            TextField("—", text: v).keyboardType(.decimalPad).multilineTextAlignment(.trailing).frame(maxWidth: 90).font(.se(16)) }
    }

    private func run() async {
        guard auth.isSignedIn else { signIn = true; return }
        busy = true; error = nil; defer { busy = false }
        do {
            result = try await AIService.rentIncrease(["stabilized": stabilized, "current_rent": current, "new_rent": new, "term": term,
                                                       "lease_start": isoDay(start), "years": years, "notice_days": notice], auth: auth)
            Analytics.shared.track("tool_result", ["tool": "rent_increase", "verdict": result?.verdict ?? "", "src": "app"])
        } catch {
            if case .signIn? = error as? AIError { signIn = true } else { self.error = AIService.toolErrorText(error) }
        }
    }
}

// MARK: - Know your rights

struct RightsView: View {
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @State private var cards: [RightsCard] = []
    @State private var loadFailed = false
    @State private var question = ""
    @State private var answer: RightsAnswer?
    @State private var busy = false
    @State private var error: String?
    @State private var signIn = false
    @State private var paywall: String?

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("What your landlord can and can't do in New York City, in plain words.").font(.se(15)).foregroundStyle(SE.ink2)
                }
                Section("✨ Ask a question") {
                    TextField("Can my landlord stop my partner from moving in?", text: $question, axis: .vertical).lineLimit(2...5)
                        .accessibilityIdentifier("rights-question")
                    Button { Task { await ask() } } label: {
                        HStack { Spacer(); if busy { ProgressView() } else { Text("Ask").font(.se(17, .bold)) }; Spacer() }
                    }.disabled(busy || question.trimmingCharacters(in: .whitespaces).count < 3).accessibilityIdentifier("rights-ask")
                    if let error { Text(error).font(.se(15)).foregroundStyle(SE.bad) }
                    if let a = answer {
                        Text(a.answer).font(.se(15)).accessibilityIdentifier("rights-answer")
                        ForEach(a.sources, id: \.self) { s in Text("\(s.title) — \(s.law)").font(.se(13)).foregroundStyle(SE.ink3) }
                        Text("Written by AI using only the rights below. It can be wrong and isn't legal advice.").font(.se(12)).foregroundStyle(SE.ink3)
                    }
                }
                Section("Your rights") {
                    if cards.isEmpty {
                        if loadFailed { Text("Couldn't load your rights just now — try again.").font(.se(15)) } else { ProgressView() }
                    }
                    ForEach(cards) { c in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(c.title).font(.se(16, .bold))
                            Text(c.text).font(.se(15)).foregroundStyle(SE.ink2)
                            Text(c.law).font(.se(13)).foregroundStyle(SE.ink3)
                        }.padding(.vertical, 2).accessibilityIdentifier("rights-card-\(c.id)")
                    }
                }
                Section { Text(notAdvice).font(.se(13)).foregroundStyle(SE.ink3) }
            }
            .navigationTitle("Know your rights").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .modifier(ToolGate(signIn: $signIn, paywall: $paywall))
            .task {
                if let c = try? await AIService.rights() { cards = c } else { loadFailed = true }
            }
            .onAppear { Analytics.shared.track("tool_open", ["tool": "rights", "src": "app"]) }
        }
    }

    private func ask() async {
        guard auth.isSignedIn else { signIn = true; return }
        busy = true; error = nil; defer { busy = false }
        do {
            guard auth.hasPlus else { paywall = "renter_ai"; return }
            let q = String(question.prefix(400))
            let local = (OnDeviceAI.available && !cards.isEmpty) ? try? await OnDeviceAI.rightsAnswer(cards: cards, question: q) : nil
            if let local { answer = local } else { answer = try await AIService.rightsAsk(q, auth: auth) }
            Analytics.shared.track("ai_engine", ["tool": "rights_answer", "on_device": local != nil])
            Analytics.shared.track("tool_result", ["tool": "rights_answer", "src": "app"])
        } catch {
            switch error as? AIError {
            case .signIn: signIn = true
            case .plus: paywall = "renter_ai"
            default: self.error = AIService.toolErrorText(error)
            }
        }
    }
}

// MARK: - Renewal coach (Plus)

struct RenewalView: View {
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @State private var leaseEnd = Calendar.current.date(byAdding: .month, value: 4, to: Date()) ?? Date()
    @State private var stabilized = "unsure"
    @State private var current = ""
    @State private var offered = ""
    @State private var zip = ""
    @State private var beds = 1
    @State private var years = ""
    @State private var plan: RenewalPlan?
    @State private var script: RenewalScript?
    @State private var busy = false
    @State private var error: String?
    @State private var signIn = false
    @State private var paywall: String?
    @State private var reminded = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Your key dates, the most your rent can legally go up, how it compares with the typical rent in your ZIP, and an email to negotiate.")
                        .font(.se(15)).foregroundStyle(SE.ink2)
                }
                Section("Your lease") {
                    DatePicker("Lease ends", selection: $leaseEnd, displayedComponents: .date)
                    Picker("Rent-stabilized", selection: $stabilized) {
                        Text("Yes").tag("yes"); Text("No").tag("no"); Text("Not sure").tag("unsure")
                    }.pickerStyle(.segmented)
                    field("Rent now", $current, "$0", id: "renewal-current")
                    field("Offered rent (if any)", $offered, "$0", id: "renewal-offered")
                    field("ZIP", $zip, "11216", id: "renewal-zip", pad: .numberPad)
                    Picker("Bedrooms", selection: $beds) { Text("Studio").tag(0); Text("1").tag(1); Text("2").tag(2); Text("3+").tag(3) }
                    field("Years you've lived there", $years, "—", id: "renewal-years")
                }
                Section {
                    Button { Task { await run() } } label: {
                        HStack { Spacer(); if busy { ProgressView() } else { Text("Plan my renewal").font(.se(17, .bold)) }; Spacer() }
                    }.disabled(busy || current.isEmpty).accessibilityIdentifier("renewal-run")
                }
                if let error { Section { Text(error).font(.se(15)).foregroundStyle(SE.bad) } }
                if let p = plan {
                    Section("Your key dates") {
                        ForEach(p.dates, id: \.self) { d in
                            VStack(alignment: .leading, spacing: 2) {
                                Text(niceDate(d.date)).font(.se(16, .bold)).strikethrough(d.past)
                                Text(d.label).font(.se(14)).foregroundStyle(SE.ink2)
                            }
                        }
                        if let r = p.reminders.first {
                            Button(reminded ? "Reminder set for \(niceDate(r.date)) ✓" : "Remind me on \(niceDate(r.date))") {
                                Task { reminded = await ToolReminder.schedule(id: "renewal", date: r.date, title: r.title, body: r.body) }
                            }.font(.se(16, .semibold)).accessibilityIdentifier("renewal-remind")
                        }
                        if let end = p.dates.first(where: { $0.label == "Your lease ends" }) {
                            AddToCalendarButton(item: CalendarItem(title: "Lease ends", day: end.date,
                                                                   notes: "Open Find A Crib's Renewal coach to check the offer."),
                                                label: "Add lease end to Calendar")
                        }
                    }.accessibilityIdentifier("renewal-dates")
                    if let c = p.compare {
                        Section("How your rent compares") {
                            Text("$\(Int(c.current_rent).formatted()) is \(abs(c.diff_pct).formatted())% \(c.diff_pct >= 0 ? "above" : "below") HUD's typical rent of $\(Int(c.fmr).formatted()) for a \(c.beds == 0 ? "studio" : "\(c.beds)-bedroom") in \(c.zip).")
                                .font(.se(15))
                            Text(c.source).font(.se(13)).foregroundStyle(SE.ink3)
                        }
                    }
                    if let ch = p.check { Section("The offer") { FindingsList(findings: ch.findings) } }
                    Section {
                        Button { Task { await writeScript() } } label: {
                            HStack { Spacer(); Text("✨ Write my negotiation email").font(.se(16, .semibold)); Spacer() }
                        }.disabled(busy).accessibilityIdentifier("renewal-script")
                    }
                    if let s = script {
                        Section("Points to make") { ForEach(s.talking_points, id: \.self) { Text("• \($0)").font(.se(15)) } }
                        LetterSection(title: s.email_subject.isEmpty ? "Your email" : "Email: \(s.email_subject)", text: s.email_body, id: "renewal-email")
                    }
                }
                Section { Text(notAdvice).font(.se(13)).foregroundStyle(SE.ink3) }
            }
            .navigationTitle("Renewal coach").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .modifier(ToolGate(signIn: $signIn, paywall: $paywall))
            .onAppear { Analytics.shared.track("tool_open", ["tool": "renewal", "src": "app"]) }
        }
    }

    private func field(_ label: String, _ v: Binding<String>, _ ph: String, id: String, pad: UIKeyboardType = .decimalPad) -> some View {
        HStack { Text(label).font(.se(16)); Spacer()
            TextField(ph, text: v).keyboardType(pad).multilineTextAlignment(.trailing).frame(maxWidth: 120).font(.se(16)).accessibilityIdentifier(id) }
    }

    private var answers: [String: Any] {
        ["lease_end": isoDay(leaseEnd), "stabilized": stabilized, "current_rent": current, "offered_rent": offered,
         "zip": zip, "beds": beds, "years": years]
    }

    private func handle(_ error: Error) {
        switch error as? AIError {
        case .signIn: signIn = true
        case .plus: paywall = "renewal"
        default: self.error = AIService.toolErrorText(error)
        }
    }

    private func run() async {
        guard auth.isSignedIn else { signIn = true; return }
        busy = true; error = nil; defer { busy = false }
        do { plan = try await AIService.renewal(answers, auth: auth); script = nil
            Analytics.shared.track("tool_result", ["tool": "renewal", "src": "app"])
        } catch { handle(error) }
    }

    private func writeScript() async {
        busy = true; error = nil; defer { busy = false }
        do {
            let local = (OnDeviceAI.available && plan != nil) ? try? await OnDeviceAI.renewalScript(plan!, current: current, offered: offered, stabilized: stabilized) : nil
            if let local { script = local } else { script = try await AIService.renewalScript(answers, auth: auth) }
            Analytics.shared.track("ai_engine", ["tool": "renewal_script", "on_device": local != nil])
            Analytics.shared.track("tool_result", ["tool": "renewal_script", "src": "app"])
        } catch { handle(error) }
    }
}
