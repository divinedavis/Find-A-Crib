import SwiftUI
import UniformTypeIdentifiers

// Broker fee check + Lease review on the iPhone (owner, 2026-10-12: "we need
// broker fee check and lease review on mobile"). The same server checks the
// website uses (findacrib.com/api/ai/broker-fee, /ai/lease-review): Plus only,
// New York law. Nothing is decided on the phone — the broker fee rules live in
// broker_fee.py so a wrong "that's legal" can't come from two places.

struct BrokerFeeResult: Decodable {
    struct Finding: Decodable, Hashable { let level: String; let title: String; let why: String; let law: String? }
    let verdict: String
    let findings: [Finding]
    let next_steps: [String]
    let complaint_url: String?
}

struct LeaseReview: Decodable {
    struct Summary: Decodable { let monthly_rent: String?; let term: String?; let start_date: String?; let security_deposit: String? }
    struct Flag: Decodable, Hashable { let title: String; let quote: String; let why: String; let law: String; let severity: String }
    let summary: Summary
    let flags: [Flag]
    let ask_before_signing: [String]
}

enum LeaseUploadError: Error, Equatable { case code(String) }

extension AIService {
    static func brokerFee(_ answers: [String: Any], auth: AuthService) async throws -> BrokerFeeResult {
        try JSONDecoder().decode(BrokerFeeResult.self, from: try await post("broker-fee", auth: auth, json: answers))
    }

    /// A PDF (multipart "file") or pasted text, and stabilized yes/no/unsure.
    /// The server reads it in memory and keeps nothing.
    static func leaseReview(pdf: Data?, text: String, stabilized: String, auth: AuthService) async throws -> LeaseReview {
        guard let token = auth.session?.accessToken else { throw AIError.signIn }
        let boundary = "fac-\(UUID().uuidString)"
        var body = Data()
        func field(_ name: String, _ value: String) {
            body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"\(name)\"\r\n\r\n\(value)\r\n".utf8))
        }
        field("stabilized", stabilized)
        if let pdf {
            body.append(Data("--\(boundary)\r\nContent-Disposition: form-data; name=\"file\"; filename=\"lease.pdf\"\r\nContent-Type: application/pdf\r\n\r\n".utf8))
            body.append(pdf); body.append(Data("\r\n".utf8))
        } else {
            field("text", text)
        }
        body.append(Data("--\(boundary)--\r\n".utf8))
        var req = URLRequest(url: URL(string: "lease-review", relativeTo: base)!, timeoutInterval: 120)
        req.httpMethod = "POST"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        req.httpBody = body
        let (data, resp) = try await URLSession.shared.data(for: req)
        let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
        switch code {
        case 200:
            struct R: Decodable { let ok: Bool; let review: LeaseReview?; let error: String? }
            let r = try JSONDecoder().decode(R.self, from: data)
            guard let review = r.review else { throw AIError.declined }
            return review
        case 400:
            struct E: Decodable { let error: String? }
            throw LeaseUploadError.code((try? JSONDecoder().decode(E.self, from: data))?.error ?? "bad_pdf")
        case 401: throw AIError.signIn
        case 402: throw AIError.plus
        case 413: throw LeaseUploadError.code("too_long")
        case 429: throw AIService.limitError(data)
        default: throw AIError.unavailable
        }
    }

    nonisolated static func leaseErrorText(_ code: String) -> String {
        switch code {
        case "scanned": String(localized: "This PDF is a scan with no text in it. Paste the lease's text instead, or ask for a digital copy.")
        case "too_long": String(localized: "That lease is too long to review here (over 60 pages or 200,000 characters).")
        case "empty": String(localized: "There's no lease text in that. Pick the PDF again or paste the text.")
        default: String(localized: "That file couldn't be read as a PDF. Paste the lease's text instead.")
        }
    }
}

// MARK: - Broker fee check

/// Which Plus tools this phone has run to a result, so a card can offer one
/// they haven't tried instead of something they already have (owner,
/// 2026-10-29: "a button of some feature that i am not using").
enum ToolUsage {
    static let ids = ["broker_fee", "lease_review"]
    /// UI tests start with nothing tried (--reset-tool-usage), once per launch.
    private static let reset: Void = {
        if CommandLine.arguments.contains("--reset-tool-usage") { ids.forEach { UserDefaults.standard.removeObject(forKey: "fac.used." + $0) } }
    }()
    static func used(_ id: String) -> Bool { _ = reset; return UserDefaults.standard.bool(forKey: "fac.used." + id) }
    static func markUsed(_ id: String) { _ = reset; UserDefaults.standard.set(true, forKey: "fac.used." + id) }
}

struct BrokerFeeView: View {
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var found = "listing_agent"
    @State private var requiredBroker = false
    @State private var hiredInWriting = false
    @State private var feesDisclosed = true
    @State private var leaseBeforeFare = false
    @State private var rent = ""
    @State private var brokerFee = ""
    @State private var appFee = ""
    @State private var deposit = ""
    @State private var lateFee = ""
    @State private var listingText = ""
    @State private var result: BrokerFeeResult?
    @State private var busy = false
    @State private var error: String?
    @State private var needsPlus = false

    init() {}
    /// From a re-rental card: its rent and listing filled in.
    init(rent: Int?, listingText: String) {
        _rent = State(initialValue: rent.map(String.init) ?? "")
        _listingText = State(initialValue: listingText)
    }

    private static let foundOptions: [(String, String)] = [
        ("listing_agent", String(localized: "Through the listing's agent")), ("own_broker", String(localized: "Through a broker I hired")),
        ("landlord_direct", String(localized: "From the landlord directly")), ("unsure", String(localized: "Not sure"))]

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Find out if a broker fee, application fee or deposit breaks NYC's FARE Act or New York law — and how to get it back.")
                        .font(.se(15)).foregroundStyle(SE.ink2)
                }
                Section("How you found the apartment") {
                    Picker("Found it", selection: $found) {
                        ForEach(Self.foundOptions, id: \.0) { Text($0.1).tag($0.0) }
                    }.accessibilityIdentifier("broker-found")
                    Toggle("I was told I had to use a broker to see or rent it", isOn: $requiredBroker)
                    Toggle("I signed a paper hiring a broker", isOn: $hiredInWriting)
                    Toggle("The fees were in the listing and a written list I signed", isOn: $feesDisclosed)
                    Toggle("I signed the lease before June 11, 2025", isOn: $leaseBeforeFare)
                }
                Section("What you were asked to pay") {
                    money(String(localized: "Monthly rent"), $rent, id: "broker-rent")
                    money(String(localized: "Broker fee"), $brokerFee, id: "broker-fee-amount")
                    money(String(localized: "Application fee"), $appFee, id: "broker-app-fee")
                    money(String(localized: "Security deposit"), $deposit, id: "broker-deposit")
                    money(String(localized: "Late fee"), $lateFee, id: "broker-late-fee")
                }
                Section("The listing (optional)") {
                    TextField("Paste the listing's text", text: $listingText, axis: .vertical)
                        .lineLimit(3...8).font(.se(16))
                }
                Section {
                    Button { Task { await check() } } label: {
                        HStack { Spacer(); if busy { ProgressView() } else { Text("Check my fees").font(.se(17, .bold)) }; Spacer() }
                    }
                    .disabled(busy).accessibilityIdentifier("broker-check")
                }
                if let error { Section { Text(error).font(.se(15)).foregroundStyle(SE.bad) } }
                if let r = result { results(r) }
                Section {
                    Text("General information about New York law, not legal advice.").font(.se(13)).foregroundStyle(SE.ink3)
                }
            }
            .navigationTitle("Broker fee check").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .sheet(isPresented: $needsPlus) { PaywallView(source: "broker_fee") }
            .onAppear { Analytics.shared.track("broker_fee_view", ["src": "app"]) }
        }
    }

    private func money(_ label: String, _ value: Binding<String>, id: String) -> some View {
        HStack {
            Text(label).font(.se(16))
            Spacer()
            TextField("$0", text: value).keyboardType(.decimalPad).multilineTextAlignment(.trailing)
                .frame(maxWidth: 130).font(.se(16)).accessibilityIdentifier(id)
        }
    }

    @ViewBuilder private func results(_ r: BrokerFeeResult) -> some View {
        Section {
            Text(Self.verdictText(r.verdict)).font(.se(18, .bold))
                .foregroundStyle(r.verdict == "likely_illegal" ? SE.bad : r.verdict == "check" ? SE.warn : SE.good)
                .accessibilityIdentifier("broker-verdict")
            ForEach(r.findings, id: \.self) { f in
                VStack(alignment: .leading, spacing: 4) {
                    Text(f.title).font(.se(16, .bold)).foregroundStyle(f.level == "illegal" ? SE.bad : f.level == "warn" ? SE.warn : SE.ink)
                    Text(f.why).font(.se(15)).foregroundStyle(SE.ink2)
                    if let law = f.law { Text(law).font(.se(13)).foregroundStyle(SE.ink3) }
                }.padding(.vertical, 2)
            }
        }
        if !r.next_steps.isEmpty {
            Section("What to do") {
                ForEach(Array(r.next_steps.enumerated()), id: \.offset) { i, s in Text("\(i + 1). \(s)").font(.se(15)) }
                if let u = r.complaint_url.flatMap(URL.init(string:)) {
                    Button("File a complaint with NYC (DCWP)") { openURL(u) }.font(.se(16, .semibold))
                }
            }
        }
    }

    nonisolated static func verdictText(_ v: String) -> String {
        switch v {
        case "likely_illegal": String(localized: "Some of these charges are likely illegal")
        case "check": String(localized: "Worth checking")
        case "looks_ok": String(localized: "Nothing here looks illegal")
        default: String(localized: "Add what you were charged to check it")
        }
    }

    private func check() async {
        busy = true; error = nil; defer { busy = false }
        let answers: [String: Any] = [
            "found": found, "required_broker": requiredBroker ? "yes" : "no", "hired_in_writing": hiredInWriting ? "yes" : "no",
            "fees_disclosed": feesDisclosed ? "yes" : "no", "lease_before_fare": leaseBeforeFare ? "yes" : "no",
            "rent": rent, "broker_fee": brokerFee, "app_fee": appFee, "deposit": deposit, "late_fee": lateFee,
            "listing_text": String(listingText.prefix(4000))]
        do {
            result = try await AIService.brokerFee(answers, auth: auth)
            ToolUsage.markUsed("broker_fee")
            Analytics.shared.track("broker_fee_check", ["verdict": result?.verdict ?? "", "src": "app"])
        } catch {
            switch error as? AIError {
            case .plus, .signIn: needsPlus = true
            case .dailyLimit: self.error = String(localized: "That's a lot for one day — more tomorrow.")
            default: self.error = String(localized: "Couldn't check right now. Try again in a minute.")
            }
        }
    }
}

// MARK: - Lease review

struct LeaseReviewView: View {
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @State private var pdf: Data?
    @State private var pdfName: String?
    @State private var text = ""
    @State private var stabilized = "unsure"
    @State private var picking = false
    @State private var review: LeaseReview?
    @State private var busy = false
    @State private var error: String?
    @State private var needsPlus = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Text("Upload your lease and AI flags the clauses New York law limits or voids, quoting each one. Your lease is read once and never kept.")
                        .font(.se(15)).foregroundStyle(SE.ink2)
                }
                Section("Your lease") {
                    Button { picking = true } label: {
                        Label(pdfName ?? String(localized: "Choose a PDF"), systemImage: "doc.richtext").font(.se(16, .semibold))
                    }.accessibilityIdentifier("lease-pick")
                    if pdf != nil {
                        Button("Remove the PDF", role: .destructive) { pdf = nil; pdfName = nil }
                    } else {
                        TextField("…or paste the lease's text", text: $text, axis: .vertical)
                            .lineLimit(4...10).font(.se(15)).accessibilityIdentifier("lease-text")
                    }
                }
                Section("Is the apartment rent-stabilized?") {
                    Picker("Rent-stabilized", selection: $stabilized) {
                        Text("Yes").tag("yes"); Text("No").tag("no"); Text("Not sure").tag("unsure")
                    }.pickerStyle(.segmented).accessibilityIdentifier("lease-stabilized")
                }
                Section {
                    Button { Task { await run() } } label: {
                        HStack { Spacer(); if busy { ProgressView(String(localized: "Reading your lease…")) } else { Text("Review my lease").font(.se(17, .bold)) }; Spacer() }
                    }
                    .disabled(busy || (pdf == nil && text.trimmingCharacters(in: .whitespacesAndNewlines).count < 200))
                    .accessibilityIdentifier("lease-run")
                }
                if let error { Section { Text(error).font(.se(15)).foregroundStyle(SE.bad) } }
                if let r = review { results(r) }
                Section {
                    Text("Written by AI from your lease, checked against New York law. General information, not legal advice.")
                        .font(.se(13)).foregroundStyle(SE.ink3)
                }
            }
            .navigationTitle("Lease review").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .fileImporter(isPresented: $picking, allowedContentTypes: [.pdf]) { res in
                guard case .success(let url) = res else { return }
                let scoped = url.startAccessingSecurityScopedResource()
                defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                guard let d = try? Data(contentsOf: url) else { error = AIService.leaseErrorText("bad_pdf"); return }
                guard d.count <= 8 * 1024 * 1024 else { error = AIService.leaseErrorText("too_long"); return }
                pdf = d; pdfName = url.lastPathComponent; error = nil
            }
            .sheet(isPresented: $needsPlus) { PaywallView(source: "lease_review") }
            .onAppear { Analytics.shared.track("lease_review_view", ["src": "app"]) }
        }
    }

    @ViewBuilder private func results(_ r: LeaseReview) -> some View {
        Section("The basics") {
            row(String(localized: "Monthly rent"), r.summary.monthly_rent); row(String(localized: "Term"), r.summary.term)
            row(String(localized: "Starts"), r.summary.start_date); row(String(localized: "Security deposit"), r.summary.security_deposit)
        }
        Section(r.flags.isEmpty ? String(localized: "Nothing flagged") : String(localized: "Clauses to look at (\(r.flags.count))")) {
            if r.flags.isEmpty {
                Text("Nothing in this lease looks limited or void under New York law.").font(.se(15))
            }
            ForEach(r.flags, id: \.self) { f in
                VStack(alignment: .leading, spacing: 5) {
                    Text(f.title).font(.se(16, .bold)).foregroundStyle(f.severity == "high" ? SE.bad : f.severity == "medium" ? SE.warn : SE.ink)
                    Text("“\(f.quote)”").font(.se(14)).italic().foregroundStyle(SE.ink2)
                    Text(f.why).font(.se(15)).foregroundStyle(SE.ink)
                    Text(f.law).font(.se(13)).foregroundStyle(SE.ink3)
                }.padding(.vertical, 2)
            }
        }.accessibilityIdentifier("lease-flags")
        if !r.ask_before_signing.isEmpty {
            Section("Ask before you sign") {
                ForEach(r.ask_before_signing, id: \.self) { Text("• \($0)").font(.se(15)) }
            }
        }
    }

    private func row(_ k: String, _ v: String?) -> some View {
        HStack { Text(k).font(.se(15)).foregroundStyle(SE.ink2); Spacer(); Text(v ?? "—").font(.se(15, .semibold)) }
    }

    private func run() async {
        busy = true; error = nil; defer { busy = false }
        do {
            review = try await AIService.leaseReview(pdf: pdf, text: text, stabilized: stabilized, auth: auth)
            ToolUsage.markUsed("lease_review")
            Analytics.shared.track("lease_review_done", ["flags": review?.flags.count ?? 0, "src": "app"])
        } catch LeaseUploadError.code(let c) {
            error = AIService.leaseErrorText(c)
        } catch {
            switch error as? AIError {
            case .plus, .signIn: needsPlus = true
            case .dailyLimit: self.error = String(localized: "That's five leases today — more tomorrow.")
            case .monthlyLimit: self.error = String(localized: "You've used this month's AI — more on the 1st.")
            case .declined: self.error = String(localized: "This doesn't read like a lease. Check the file and try again.")
            default: self.error = String(localized: "Couldn't review it right now. Try again in a little while.")
            }
        }
    }
}
