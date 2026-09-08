import SwiftUI

/// "Email me the minute one opens" — the borough alerts the website offers at
/// findacrib.com/alerts/, subscribed from the app with the same filters the
/// web form has: boroughs, what to hear about, a rent cap and a household
/// income (2026-09-08). Reached from the Alerts pill on the Available-now,
/// Accepting-vouchers and Lotteries results, and from Profile. Requires an
/// account so the address is a real one the person controls; the
/// subscription itself is the site's, keyed by email, so it also shows up
/// if they later use the web form — and, signed in, the sheet loads what
/// that email already gets so it can be changed here.
struct AlertsSheet: View {
    /// The search that opened the sheet, to prefill from; nil from Profile.
    var query: SearchQuery? = nil
    @Environment(DataStore.self) private var store
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss

    @State private var boroughs: Set<String> = []
    @State private var kinds: Set<String> = []
    @State private var maxRent = ""
    @State private var income = ""
    @State private var busy = false
    @State private var done = false
    @State private var error: String?
    /// True once /api/alerts/prefs said this email already has alerts —
    /// the button then reads "Save changes", as on the web.
    @State private var editing = false
    @State private var loadingPrefs = false

    private static let kindRows: [(key: String, name: String, sub: String)] = [
        ("rerental", "Re-rentals", "A vacated affordable apartment an HPD marketing agent re-rents directly, usually first come, first served"),
        ("voucher", "Voucher listings", "A landlord newly accepting Section 8 / vouchers on AffordableHousing.com"),
        ("lottery", "Lotteries & waitlists", "Housing Connect and HCR lotteries, Mitchell-Lama waitlists"),
    ]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if done {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("You're on the list").font(.se(26, .bold)).foregroundStyle(SE.ink)
                            Text("One email the minute something opens in \(boroughPhrase)\(fitPhrase). Quiet until then — no digests. A welcome note is on its way to \(auth.email ?? "your inbox").")
                                .font(.se(17)).foregroundStyle(SE.ink2)
                            Text("Change boroughs or stop the emails any time at findacrib.com/alerts/.").font(.se(15)).foregroundStyle(SE.ink3)
                        }
                        SEPrimaryButton(title: "Done") { dismiss() }
                    } else {
                        Text(editing ? "Your alerts" : "Email me the minute one opens").font(.se(26, .bold)).foregroundStyle(SE.ink)
                        Text("Sent to \(auth.email ?? "your account email"). The feeds are checked every 10 minutes.")
                            .font(.se(16)).foregroundStyle(SE.ink2)
                        if loadingPrefs {
                            HStack(spacing: 8) { ProgressView().tint(SE.royal); Text("Loading what this email gets today…").font(.se(14)).foregroundStyle(SE.ink3) }
                        } else if editing {
                            Text("These are the alerts this address gets today. Change anything and tap Save changes.")
                                .font(.se(14)).foregroundStyle(SE.ink3).accessibilityIdentifier("alerts-editing-note")
                        }

                        Text("Boroughs").font(.se(15, .bold)).foregroundStyle(SE.ink2).textCase(.uppercase)
                        VStack(spacing: 0) {
                            ForEach(Borough.all, id: \.code) { b in
                                checkRow(b.name, nil, on: boroughs.contains(b.code)) {
                                    if boroughs.contains(b.code) { boroughs.remove(b.code) } else { boroughs.insert(b.code) }
                                }
                            }
                        }
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line))

                        Text("Tell me about").font(.se(15, .bold)).foregroundStyle(SE.ink2).textCase(.uppercase)
                        VStack(spacing: 0) {
                            ForEach(Self.kindRows, id: \.key) { k in
                                checkRow(k.name, k.sub, on: kinds.contains(k.key)) {
                                    if kinds.contains(k.key) { kinds.remove(k.key) } else { kinds.insert(k.key) }
                                }
                            }
                        }
                        .overlay(RoundedRectangle(cornerRadius: 2).stroke(SE.line))

                        Text("Only if it fits (optional)").font(.se(15, .bold)).foregroundStyle(SE.ink2).textCase(.uppercase)
                        HStack(spacing: 12) {
                            numField("Max rent, $/month", "e.g. 2000", $maxRent).accessibilityIdentifier("alerts-max-rent")
                            numField("Household income, $/year", "e.g. 65000", $income).accessibilityIdentifier("alerts-income")
                        }
                        Text("A lottery or re-rental is sent only when a unit's rent is at or under your cap and your household income falls in one of its income bands. Leave both blank to hear about everything.")
                            .font(.se(14)).foregroundStyle(SE.ink3)

                        if let error { Text(error).font(.se(15)).foregroundStyle(SE.bad) }
                        SEPrimaryButton(title: busy ? "…" : (editing ? "Save changes" : "Turn on alerts")) { Task { await subscribe() } }
                            .disabled(busy || boroughs.isEmpty || kinds.isEmpty)
                            .opacity((boroughs.isEmpty || kinds.isEmpty) ? 0.5 : 1)
                            .accessibilityIdentifier("alerts-subscribe")
                        Text(editing ? "Stop the emails any time from the link at the bottom of one, or at findacrib.com/alerts/."
                                     : "Free. This replaces any borough alert already set up for this email on findacrib.com.")
                            .font(.se(14)).foregroundStyle(SE.ink3)
                    }
                }
                .padding(16)
            }
            .background(Color.white)
            .navigationTitle("Alerts").navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
        }
        .onAppear { seed() }
        .task { await loadPrefs() }
        .accessibilityIdentifier("alerts-sheet")
    }

    private func numField(_ label: String, _ placeholder: String, _ text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label).font(.se(14, .semibold)).foregroundStyle(SE.ink2)
            SEFieldBox {
                TextField(placeholder, text: text).keyboardType(.numberPad).font(.se(18)).padding(.horizontal, 12)
            }
        }
    }

    /// Digits of a typed dollar figure, or nil when blank; -1 when it is not
    /// a number at all (the server would reject it, so say so first).
    static func dollars(_ s: String) -> Int? {
        let t = s.replacingOccurrences(of: ",", with: "").replacingOccurrences(of: "$", with: "").trimmingCharacters(in: .whitespaces)
        if t.isEmpty { return nil }
        return Int(Double(t) ?? -1)
    }

    private var fitPhrase: String {
        var fit: [String] = []
        if let r = Self.dollars(maxRent), r > 0 { fit.append("rent up to $\(r.formatted())") }
        if let i = Self.dollars(income), i > 0 { fit.append("an income band that includes $\(i.formatted())/yr") }
        return fit.isEmpty ? "" : " with " + fit.joined(separator: " and ")
    }

    private var boroughPhrase: String {
        let names = Borough.all.filter { boroughs.contains($0.code) }.map(\.name)
        if names.count == Borough.all.count { return "all five boroughs" }
        return names.count <= 1 ? (names.first ?? "your borough") : names.dropLast().joined(separator: ", ") + " and " + names.last!
    }

    /// What this email already gets, from the site, so the sheet edits the
    /// live subscription instead of blindly replacing it. Needs the session
    /// token: the API takes the email from the verified session only.
    private func loadPrefs() async {
        guard let token = auth.session?.accessToken else { return }
        loadingPrefs = true; defer { loadingPrefs = false }
        var req = URLRequest(url: URL(string: "https://findacrib.com/api/alerts/prefs")!, timeoutInterval: 15)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              (resp as? HTTPURLResponse)?.statusCode == 200,
              let j = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              (j["exists"] as? Bool) == true, (j["unsubscribed"] as? Bool) != true else { return }
        if let b = j["boroughs"] as? [String], !b.isEmpty { boroughs = Set(b) }
        if let k = j["kinds"] as? [String], !k.isEmpty { kinds = Set(k) }
        if let r = j["max_rent"] as? Int { maxRent = String(r) }
        if let i = j["income"] as? Int { income = String(i) }
        editing = true
    }

    /// Prefill from the search: its boroughs (neighborhood picks collapse to
    /// their borough) and the kind that matches the view it came from.
    private func seed() {
        guard let query else { kinds = ["lottery", "rerental"]; return }
        var b: Set<String> = []
        for l in query.locations {
            switch l {
            case .borough(let c): b.insert(c)
            case .neighborhood(let n): if let c = store.boroughOfNeighborhood[n] { b.insert(c) }
            default: break
            }
        }
        boroughs = b
        let n = query.normalized
        var k: Set<String> = []
        if n.availableOnly { k.insert("rerental") }
        if n.vouchersOnly { k.insert("voucher") }
        if n.hcrOnly { k.insert("lottery") }
        if k.isEmpty { k = ["rerental"] }
        kinds = k
    }

    private func checkRow(_ title: String, _ sub: String?, on: Bool, toggle: @escaping () -> Void) -> some View {
        Button(action: toggle) {
            HStack(alignment: .top, spacing: 12) {
                Image(systemName: on ? "checkmark.square.fill" : "square")
                    .font(.system(size: 22)).foregroundStyle(on ? SE.royal : SE.line)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title).font(.se(18, .semibold)).foregroundStyle(SE.ink)
                    if let sub { Text(sub).font(.se(14)).foregroundStyle(SE.ink2) }
                }
                Spacer(minLength: 0)
            }
            .padding(12).contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .overlay(alignment: .bottom) { Rectangle().fill(SE.line).frame(height: 1) }
    }

    private func subscribe() async {
        guard let email = auth.email else { error = "Sign in first."; return }
        let rent = Self.dollars(maxRent), inc = Self.dollars(income)
        if let rent, !(100...20000).contains(rent) { error = "Max rent should be a number of dollars per month, between 100 and 20,000."; return }
        if let inc, !(1000...2_000_000).contains(inc) { error = "Income should be a number of dollars per year, between 1,000 and 2,000,000."; return }
        busy = true; error = nil
        defer { busy = false }
        do {
            var req = URLRequest(url: URL(string: "https://findacrib.com/api/alerts/subscribe")!, timeoutInterval: 20)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.setValue("application/json", forHTTPHeaderField: "Accept")
            var payload: [String: Any] = ["email": email, "boroughs": Array(boroughs).sorted(), "kinds": Array(kinds).sorted()]
            if let rent { payload["max_rent"] = rent }
            if let inc { payload["income"] = inc }
            req.httpBody = try JSONSerialization.data(withJSONObject: payload)
            let (data, resp) = try await URLSession.shared.data(for: req)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            if code == 200, (body?["ok"] as? Bool) == true { done = true; return }
            switch body?["error"] as? String {
            case "signup_cap": error = "Sign-ups are paused for today — try again tomorrow."
            case "invalid_email": error = "Your account email doesn't look valid. Update it under Profile."
            case "no_borough": error = "Pick at least one borough."
            case "bad_rent": error = "Max rent should be a number of dollars per month, between 100 and 20,000."
            case "bad_income": error = "Income should be a number of dollars per year, between 1,000 and 2,000,000."
            default: error = code == 429 ? "Too many tries — give it an hour." : "Couldn't reach findacrib.com just now. Try again."
            }
        } catch { self.error = "Couldn't reach findacrib.com just now. Try again." }
    }
}
