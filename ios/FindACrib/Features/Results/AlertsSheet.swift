import SwiftUI

/// "Email me the minute one opens" — the borough alerts the website offers at
/// findacrib.com/alerts/, subscribed from the app. Reached from the Alerts
/// pill that appears on the results list in the Available-now and
/// Accepting-vouchers views. Requires an account so the address is a real
/// one the person controls; the subscription itself is the site's, keyed
/// by email, so it also shows up if they later use the web form.
struct AlertsSheet: View {
    let query: SearchQuery
    @Environment(DataStore.self) private var store
    @Environment(AuthService.self) private var auth
    @Environment(\.dismiss) private var dismiss

    @State private var boroughs: Set<String> = []
    @State private var kinds: Set<String> = []
    @State private var busy = false
    @State private var done = false
    @State private var error: String?

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
                            Text("One email the minute something opens in \(boroughPhrase). Quiet until then — no digests. A welcome note is on its way to \(auth.email ?? "your inbox").")
                                .font(.se(17)).foregroundStyle(SE.ink2)
                            Text("Change boroughs or stop the emails any time at findacrib.com/alerts/.").font(.se(15)).foregroundStyle(SE.ink3)
                        }
                        SEPrimaryButton(title: "Done") { dismiss() }
                    } else {
                        Text("Email me the minute one opens").font(.se(26, .bold)).foregroundStyle(SE.ink)
                        Text("Sent to \(auth.email ?? "your account email"). The feeds are checked every 10 minutes.")
                            .font(.se(16)).foregroundStyle(SE.ink2)

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

                        if let error { Text(error).font(.se(15)).foregroundStyle(SE.bad) }
                        SEPrimaryButton(title: busy ? "…" : "Turn on alerts") { Task { await subscribe() } }
                            .disabled(busy || boroughs.isEmpty || kinds.isEmpty)
                            .opacity((boroughs.isEmpty || kinds.isEmpty) ? 0.5 : 1)
                            .accessibilityIdentifier("alerts-subscribe")
                        Text("Free. This replaces any borough alert already set up for this email on findacrib.com.")
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
        .accessibilityIdentifier("alerts-sheet")
    }

    private var boroughPhrase: String {
        let names = Borough.all.filter { boroughs.contains($0.code) }.map(\.name)
        if names.count == Borough.all.count { return "all five boroughs" }
        return names.count <= 1 ? (names.first ?? "your borough") : names.dropLast().joined(separator: ", ") + " and " + names.last!
    }

    /// Prefill from the search: its boroughs (neighborhood picks collapse to
    /// their borough) and the kind that matches the view it came from.
    private func seed() {
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
        busy = true; error = nil
        defer { busy = false }
        do {
            var req = URLRequest(url: URL(string: "https://findacrib.com/api/alerts/subscribe")!, timeoutInterval: 20)
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.setValue("application/json", forHTTPHeaderField: "Accept")
            req.httpBody = try JSONSerialization.data(withJSONObject: [
                "email": email, "boroughs": Array(boroughs).sorted(), "kinds": Array(kinds).sorted(),
            ])
            let (data, resp) = try await URLSession.shared.data(for: req)
            let code = (resp as? HTTPURLResponse)?.statusCode ?? 0
            let body = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            if code == 200, (body?["ok"] as? Bool) == true { done = true; return }
            switch body?["error"] as? String {
            case "signup_cap": error = "Sign-ups are paused for today — try again tomorrow."
            case "invalid_email": error = "Your account email doesn't look valid. Update it under Profile."
            case "no_borough": error = "Pick at least one borough."
            default: error = code == 429 ? "Too many tries — give it an hour." : "Couldn't reach findacrib.com just now. Try again."
            }
        } catch { self.error = "Couldn't reach findacrib.com just now. Try again." }
    }
}
