import SwiftUI
import UIKit

/// The Plus AI features on iPhone (owner, 2026-10-03) — the same answers as
/// findacrib.com, through AIService. Not signed in: Profile to sign in.
/// No Plus: the existing paywall, opened with the feature as its source.

struct PlusTag: View {
    var body: some View {
        Text("PLUS").font(.se(11, .black)).foregroundStyle(.white)
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(LinearGradient(colors: [Color(hex: 0x6B3DF5), Color(hex: 0x3151C8)], startPoint: .topLeading, endPoint: .bottomTrailing))
            .clipShape(Capsule())
    }
}

private struct AIButton: View {
    let title: String
    let icon: String
    let id: String
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                Image(systemName: icon).font(.system(size: 15, weight: .bold))
                Text(title).font(.se(17, .bold))
                PlusTag()
                Spacer(minLength: 0)
            }
            .foregroundStyle(SE.ink).padding(.horizontal, 14).frame(height: 48).frame(maxWidth: .infinity)
            .background(Color.white).overlay(RoundedRectangle(cornerRadius: 10).stroke(SE.line))
        }
        .buttonStyle(.plain).accessibilityIdentifier(id)
    }
}

private func errorText(_ e: Error) -> String {
    switch e as? AIError {
    case .dailyLimit: "That's a lot for one day — more tomorrow."
    case .declined: "That isn't something the records can answer."
    case .noPrice: "There isn't a current advertised rent to compare."
    default: "Not available right now — the records above are."
    }
}

/// Report card, Ask and (with an asking rent) Is this rent fair? on a NYC
/// building page.
struct AIBuildingSection: View {
    let building: Building
    var hasPrice: Bool
    @Environment(AuthService.self) private var auth
    @State private var card: ReportCard?
    @State private var cardError: String?
    @State private var loadingCard = false
    @State private var showAsk = false
    @State private var question = ""
    @State private var answer: String?
    @State private var asking = false
    @State private var rent: RentCheck?
    @State private var rentError: String?
    /// Opens the building page's own Plus sheet (a second .sheet down here
    /// never presented — the page already owns one).
    var onPlus: (String) -> Void

    var body: some View {
        // Signed out or signed in, the buttons show: tapping one without
        // Plus opens the Plus page with that feature first (owner, 2026-10-03).
        signedIn
    }

    private var signedIn: some View {
        VStack(alignment: .leading, spacing: 10) {
            AIButton(title: "Landlord report card", icon: "doc.text.magnifyingglass", id: "ai-report-card") { Task { await loadCard() } }
            if loadingCard { ProgressView().tint(SE.royal) }
            if let card { reportCard(card) }
            if let cardError { Text(cardError).font(.se(15)).foregroundStyle(SE.ink3) }

            AIButton(title: "Ask about this building", icon: "bubble.left.and.text.bubble.right", id: "ai-ask") { openAsk() }
            if showAsk {
                HStack(spacing: 8) {
                    TextField("e.g. Has it had rat problems?", text: $question)
                        .font(.se(17)).padding(10).background(Color.white)
                        .overlay(RoundedRectangle(cornerRadius: 10).stroke(SE.line))
                        .submitLabel(.send).onSubmit { Task { await send() } }
                        .accessibilityIdentifier("ai-ask-field")
                    Button { Task { await send() } } label: {
                        Text("Ask").font(.se(17, .bold)).foregroundStyle(.white).padding(.horizontal, 14).frame(height: 44).background(SE.royal).clipShape(RoundedRectangle(cornerRadius: 10))
                    }.buttonStyle(.plain).disabled(asking || question.trimmingCharacters(in: .whitespaces).count < 3)
                }
                if asking { ProgressView().tint(SE.royal) }
                if let answer {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(AIService.readable(answer)).font(.se(16)).foregroundStyle(SE.ink)
                        Text("AI answer from the city's public records.").font(.se(13)).foregroundStyle(SE.ink3)
                    }.padding(12).background(Color.white).overlay(RoundedRectangle(cornerRadius: 10).stroke(SE.lineSoft))
                        .accessibilityIdentifier("ai-ask-answer")
                }
            }

            if hasPrice {
                AIButton(title: "Is this rent fair?", icon: "dollarsign.circle", id: "ai-rent-check") { Task { await loadRent() } }
                if let rent { rentCard(rent) }
                if let rentError { Text(rentError).font(.se(15)).foregroundStyle(SE.ink3) }
            }
        }
    }

    private func gate(_ e: Error, source: String) -> Bool {
        switch e as? AIError {
        case .signIn: onPlus(source); return true
        case .plus: onPlus(source); return true
        default: return false
        }
    }

    private func loadCard() async {
        Analytics.shared.track("report_card_click", ["bbl": building.bbl, "plus": auth.hasPlus])
        guard auth.hasPlus else { onPlus("report_card"); return }
        loadingCard = true; cardError = nil; defer { loadingCard = false }
        do { card = try await AIService.reportCard(bbl: building.bbl, auth: auth) }
        catch { if !gate(error, source: "report_card") { cardError = errorText(error) } }
    }

    private func openAsk() {
        Analytics.shared.track("ask_open", ["bbl": building.bbl, "plus": auth.hasPlus])
        guard auth.hasPlus else { onPlus("ask"); return }
        showAsk = true
    }

    private func send() async {
        let q = question.trimmingCharacters(in: .whitespacesAndNewlines)
        guard q.count >= 3 else { return }
        asking = true; defer { asking = false }
        do { answer = try await AIService.ask(bbl: building.bbl, question: q, auth: auth); Analytics.shared.track("ask_result", ["bbl": building.bbl, "ok": true]) }
        catch { if !gate(error, source: "ask") { answer = errorText(error) } }
    }

    private func loadRent() async {
        Analytics.shared.track("rent_check_click", ["bbl": building.bbl, "plus": auth.hasPlus])
        guard auth.hasPlus else { onPlus("rent_check"); return }
        rentError = nil
        do { rent = try await AIService.rentCheck(bbl: building.bbl, auth: auth) }
        catch { if !gate(error, source: "rent_check") { rentError = errorText(error) } }
    }

    private func reportCard(_ c: ReportCard) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(c.headline).font(.se(17, .bold)).foregroundStyle(SE.ink)
            ForEach(c.points, id: \.self) { p in
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: p.tone == "good" ? "checkmark.circle.fill" : p.tone == "concern" ? "exclamationmark.triangle.fill" : "circle.fill")
                        .font(.system(size: p.tone == "neutral" ? 7 : 15)).foregroundStyle(p.tone == "good" ? SE.good : p.tone == "concern" ? SE.warn : SE.ink3)
                        .frame(width: 18).padding(.top, 3)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(p.text).font(.se(16)).foregroundStyle(SE.ink)
                        Text(AIRecordLabel[p.source] ?? p.source).font(.se(12, .semibold)).foregroundStyle(SE.ink3)
                    }
                }
            }
            if !c.ask_the_landlord.isEmpty {
                Text("Ask the landlord").font(.se(15, .bold)).foregroundStyle(SE.ink2).padding(.top, 4)
                ForEach(c.ask_the_landlord, id: \.self) { Text("• " + $0).font(.se(15)).foregroundStyle(SE.ink2) }
            }
            Text("Written by AI from the city's public records.").font(.se(13)).foregroundStyle(SE.ink3)
        }
        .padding(12).background(Color.white).overlay(RoundedRectangle(cornerRadius: 10).stroke(SE.lineSoft))
        .accessibilityIdentifier("ai-report-card-result")
    }

    private func rentCard(_ r: RentCheck) -> some View {
        let word = ["high": "above typical", "low": "below typical", "typical": "typical"][r.verdict ?? ""] ?? "hard to judge"
        return VStack(alignment: .leading, spacing: 6) {
            Text("\(Formatters.dollars(r.price ?? 0))/mo is \(word) for this area")
                .font(.se(17, .bold)).foregroundStyle(r.verdict == "high" ? SE.bad : r.verdict == "low" ? SE.good : SE.ink)
            if let m = r.nb_median, let n = r.comps, let pct = r.percentile {
                Text("Similar advertised rent-stabilized buildings nearby: median \(Formatters.dollars(m)) (\(n) buildings) — higher than \(pct)% of them.").font(.se(15)).foregroundStyle(SE.ink2)
            }
            if let lo = r.fmr_low, let hi = r.fmr_high {
                Text("HUD fair-market rent for this ZIP: \(lo == hi ? Formatters.dollars(lo) : Formatters.dollars(lo) + "–" + Formatters.dollars(hi)).").font(.se(15)).foregroundStyle(SE.ink2)
            }
            ForEach(r.notes ?? [], id: \.self) { Text($0).font(.se(13)).foregroundStyle(SE.ink3) }
        }
        .padding(12).background(Color.white).overlay(RoundedRectangle(cornerRadius: 10).stroke(SE.lineSoft))
    }
}

/// Help me apply, for one re-rental.
struct ApplyHelpSheet: View {
    let listing: FeaturedListing
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL
    @State private var help: ApplyHelp?
    @State private var error: String?
    @State private var needsPlus = false
    @State private var copied = false
    @State private var showPacket = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(listing.address).font(.se(22, .bold)).foregroundStyle(SE.ink)
                    if let h = help {
                        Text("How to apply").font(.se(17, .bold))
                        ForEach(Array(h.steps.enumerated()), id: \.offset) { i, s in
                            Text("\(i + 1). \(s)").font(.se(16)).foregroundStyle(SE.ink)
                        }
                        if !h.documents.isEmpty {
                            Text("Gather").font(.se(17, .bold))
                            ForEach(h.documents, id: \.self) { d in
                                Text("• \(d.item)" + (d.required_by_listing ? "  (required here)" : "")).font(.se(16)).foregroundStyle(SE.ink2)
                            }
                        }
                        if let d = h.deadline { Text("Deadline: \(d)").font(.se(16, .semibold)) }
                        // The packet: what this listing asks for vs what's on
                        // the phone, and one email with everything attached.
                        SEPrimaryButton(title: "Get my documents ready", icon: "folder.badge.plus") { showPacket = true }
                            .accessibilityIdentifier("apply-open-packet")
                            .sheet(isPresented: $showPacket) {
                                PacketView(needs: h.documents.map(\.item), listingAddress: listing.address,
                                           agentEmail: h.contact.email, emailSubject: h.email_subject, emailBody: h.email_body)
                            }
                        Text("Email to the agent").font(.se(17, .bold))
                        Text("Subject: \(h.email_subject)\n\n\(h.email_body)").font(.se(15)).foregroundStyle(SE.ink)
                            .padding(10).background(Color.white).overlay(RoundedRectangle(cornerRadius: 10).stroke(SE.lineSoft))
                            .accessibilityIdentifier("apply-email")
                        HStack(spacing: 10) {
                            SEOutlineButton(title: copied ? "Copied" : "Copy email") {
                                UIPasteboard.general.string = "Subject: \(h.email_subject)\n\n\(h.email_body)"; copied = true
                                Analytics.shared.track("apply_help_copy", ["agent": listing.agent])
                            }
                            if let e = h.contact.email,
                               let url = URL(string: "mailto:\(e)?subject=\(h.email_subject.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")&body=\(h.email_body.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "")") {
                                SEPrimaryButton(title: "Open in Mail") { openURL(url) }
                            }
                        }
                        Text("Written by AI from the agent's listing. Check their page before you send anything.").font(.se(13)).foregroundStyle(SE.ink3)
                    } else if let error {
                        Text(error).font(.se(16)).foregroundStyle(SE.ink2)
                    } else {
                        ProgressView("Reading the listing…").tint(SE.royal)
                            .frame(maxWidth: .infinity).padding(.top, 24)
                    }
                }
                // Full width: a short address used to shrink this column and
                // the sheet centered it, spinner and all (owner, 2026-10-03).
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(18)
            }
            .navigationTitle("Help me apply").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .task { await load() }
            .sheet(isPresented: $needsPlus, onDismiss: { if !auth.hasPlus { dismiss() } else { Task { await load() } } }) { PaywallView(source: "apply_help", context: listing.address) }
        }
    }

    private func load() async {
        Analytics.shared.track("apply_help_click", ["agent": listing.agent, "plus": auth.hasPlus])
        do { help = try await AIService.applyHelp(href: listing.href, auth: auth); error = nil }
        catch {
            switch error as? AIError {
            case .plus: needsPlus = true
            case .signIn: needsPlus = true
            default: self.error = errorText(error)
            }
        }
    }
}

/// "Describe what you're looking for" — plain-language search.
struct AISearchSheet: View {
    @Environment(AuthService.self) private var auth
    @Environment(AppNav.self) private var nav
    @Environment(\.dismiss) private var dismiss
    @State private var text = ""
    @State private var busy = false
    @State private var error: String?
    @State private var needsPlus = false

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 14) {
                Text("Describe the apartment you want").font(.se(22, .bold))
                Text("Neighborhood, price, bedrooms, anything — e.g. “2 bed under $2,500 near Prospect Park, no violations”.").font(.se(16)).foregroundStyle(SE.ink2)
                TextField("What are you looking for?", text: $text, axis: .vertical)
                    .font(.se(18)).lineLimit(2...4).padding(12).background(Color.white)
                    .overlay(RoundedRectangle(cornerRadius: 10).stroke(SE.line))
                    .accessibilityIdentifier("ai-search-field")
                if let error { Text(error).font(.se(15)).foregroundStyle(SE.bad) }
                SEPrimaryButton(title: busy ? "Reading…" : "Search", icon: "sparkles") { Task { await go() } }
                    .disabled(busy || text.trimmingCharacters(in: .whitespaces).count < 4)
                Spacer()
            }
            .padding(18)
            .navigationTitle("Search in plain words").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
            .sheet(isPresented: $needsPlus) { PaywallView(source: "ai_search") }
        }
    }

    private func go() async {
        let q = text.trimmingCharacters(in: .whitespacesAndNewlines)
        Analytics.shared.track("ai_search_click", ["words": q.split(separator: " ").count, "plus": auth.hasPlus])
        guard auth.hasPlus else { needsPlus = true; return }
        busy = true; error = nil; defer { busy = false }
        do {
            let r = try await AIService.search(q, auth: auth)
            Analytics.shared.track("ai_search_result", ["ok": true, "used_ai": r.used_ai ?? false, "nbs": r.filters.nbs.count])
            dismiss()
            nav.searchPath = [.results(AIService.query(from: r.filters))]
        } catch {
            switch error as? AIError {
            case .plus: needsPlus = true
            case .signIn: needsPlus = true
            default: self.error = errorText(error)
            }
        }
    }
}

/// The qualify badge on a lottery or re-rental card.
struct QualifyBadge: View {
    let verdict: Qualify.Verdict
    var body: some View {
        let (icon, ink, fill): (String, Color, Color) = switch verdict {
        case .yes: ("checkmark.circle.fill", SE.good, Color(hex: 0xE6F4EA))
        case .high, .low: ("exclamationmark.circle.fill", SE.warn, Color(hex: 0xFDF0E1))
        case .unknown: ("questionmark.circle", SE.ink3, SE.badge)
        }
        return Label(Qualify.words(verdict), systemImage: icon).font(.se(14, .bold)).foregroundStyle(ink)
            .padding(.horizontal, 10).padding(.vertical, 5).background(fill).clipShape(Capsule())
            .accessibilityIdentifier("qualify-badge")
    }
}

/// Household size + income, kept on this phone.
struct QualifySheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var household = Qualify.shared.household ?? 1
    @State private var income = Qualify.shared.income.map(String.init) ?? ""

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 16) {
                Text("What do I qualify for?").font(.se(24, .bold))
                Text("Lotteries and re-rentals have income limits by household size. Tell us yours and every listing says whether you're in range. Kept on this phone only.").font(.se(16)).foregroundStyle(SE.ink2)
                Stepper("\(household) \(household == 1 ? "person" : "people") in your household", value: $household, in: 1...8)
                    .font(.se(17)).accessibilityIdentifier("qualify-household")
                TextField("Yearly household income, $", text: $income).keyboardType(.numberPad)
                    .font(.se(18)).padding(12).background(Color.white).overlay(RoundedRectangle(cornerRadius: 10).stroke(SE.line))
                    .accessibilityIdentifier("qualify-income")
                SEPrimaryButton(title: "Show what I qualify for") { save() }
                if Qualify.shared.isSet {
                    Button("Clear") { Qualify.shared.clear(); Analytics.shared.track("qualify_clear"); dismiss() }
                        .font(.se(16, .semibold)).foregroundStyle(SE.royal)
                }
                Spacer()
            }
            .padding(18)
            // Save in the bar too, where it's always in reach above the keyboard.
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) { Button("Save") { save() }.accessibilityIdentifier("qualify-save") }
            }
        }
    }

    private func save() {
        guard let n = Int(income.filter(\.isNumber)), n >= 1000 else { return }
        Qualify.shared.set(household: household, income: n)
        Analytics.shared.track("qualify_set", ["hh": household])
        dismiss()
    }
}
