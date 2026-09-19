import SwiftUI

/// What a tapped alert notification carries: the headline the phone showed,
/// and every item in the alert (lottery_alerts.py `push_items`: k kind,
/// t headline, s detail, u link, b borough).
struct AlertPush: Identifiable, Equatable {
    struct Item: Identifiable, Equatable {
        let id = UUID()
        let kind: String
        let text: String
        let detail: String
        let url: URL?
        let borough: String
        static func == (a: Item, b: Item) -> Bool { a.text == b.text && a.url == b.url }
    }
    let id = UUID()
    let title: String
    let items: [Item]

    /// From a notification's payload. A payload with no `items` (build-51
    /// era sends, a test push) still becomes one item from the notification's
    /// own text and `url`, so a tap always lands on this screen rather than
    /// straight on a third-party site.
    static func from(userInfo: [AnyHashable: Any], title: String, body: String) -> AlertPush? {
        var items: [Item] = []
        if let raw = userInfo["items"] as? [[String: Any]] {
            for r in raw {
                let text = (r["t"] as? String) ?? ""
                guard !text.isEmpty else { continue }
                items.append(Item(kind: (r["k"] as? String) ?? "rerental", text: text,
                                  detail: (r["s"] as? String) ?? "",
                                  url: (r["u"] as? String).flatMap { $0.isEmpty ? nil : URL(string: $0) },
                                  borough: (r["b"] as? String) ?? ""))
            }
        }
        if items.isEmpty {
            let url = PushService.deepLink(in: userInfo)
            guard url != nil || !body.isEmpty else { return nil }
            items = [Item(kind: "alert", text: body.isEmpty ? title : body, detail: "", url: url, borough: "")]
        }
        return AlertPush(title: title.isEmpty ? "New alerts" : title, items: items)
    }

    static func == (a: AlertPush, b: AlertPush) -> Bool { a.id == b.id }
}

/// The screen a tapped alert opens: every item in the alert, each with its own
/// way through to the listing. The owner (2026-09-19) tapped a "5 new
/// re-rentals" notification and landed on a blank page — the old tap went
/// straight to the first item's agent website, and the other four were
/// unreachable. Opening here first means the phone always shows something,
/// every item is one tap away, and people come back to the app.
struct AlertPushSheet: View {
    let push: AlertPush
    @Environment(\.dismiss) private var dismiss
    @Environment(\.openURL) private var openURL

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    Text(push.title).font(.se(26, .bold)).foregroundStyle(SE.ink)
                        .accessibilityIdentifier("push-sheet-title")
                    Text(push.items.count == 1 ? "Opened the minute it was posted. Tap through to apply on the agent's site."
                                               : "\(push.items.count) opened the minute they were posted. Tap one to see it on the agent's site.")
                        .font(.se(16)).foregroundStyle(SE.ink2)
                    ForEach(push.items) { item in row(item) }
                    Text("Change which boroughs you hear about under Profile → Alerts.")
                        .font(.se(14)).foregroundStyle(SE.ink3).padding(.top, 4)
                }
                .padding(20)
            }
            .background(SE.canvas)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() } } }
        }
        .onAppear { Analytics.shared.track("push_open", ["items": push.items.count]) }
    }

    private func row(_ item: AlertPush.Item) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                SEBadge(text: Self.kindLabel(item.kind), icon: item.kind == "lottery" ? "doc.text.fill" : "key.fill",
                        fill: SE.navy, ink: .white)
                if let boro = Self.boroughName(item.borough) { Text(boro).font(.se(15, .semibold)).foregroundStyle(SE.ink2) }
            }
            Text(item.text).font(.se(20, .bold)).foregroundStyle(SE.royal).fixedSize(horizontal: false, vertical: true)
            if !item.detail.isEmpty {
                Text(item.detail).font(.se(15)).foregroundStyle(SE.ink2).fixedSize(horizontal: false, vertical: true)
            }
            if let url = item.url {
                Button {
                    Analytics.shared.track("push_item_open", ["kind": item.kind, "url": url.absoluteString])
                    if PushService.buildingBBL(in: url) != nil {
                        dismiss()
                        PushService.shared.open(url)
                    } else {
                        openURL(url)
                    }
                } label: {
                    Text(PushService.buildingBBL(in: url) != nil ? "Open the building" : "See it on their site ↗")
                        .font(.se(17, .bold)).foregroundStyle(.white)
                        .frame(maxWidth: .infinity).frame(height: 46).background(SE.royal)
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("push-item-open")
            }
        }
        .padding(16)
        .seCard()
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("push-item")
    }

    static func kindLabel(_ k: String) -> String {
        switch k { case "lottery": "Lottery"; case "voucher": "Voucher listing"; case "rerental": "Rerental"; default: "Alert" }
    }
    static func boroughName(_ code: String) -> String? {
        ["M": "Manhattan", "Bk": "Brooklyn", "Q": "Queens", "Bx": "Bronx", "SI": "Staten Island"][code]
    }
}
