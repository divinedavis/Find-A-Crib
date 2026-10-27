import SwiftUI
import UIKit

/// The Plus AI features on iPhone (owner, 2026-10-03) — the same answers as
/// findacrib.com, through AIService. Not signed in: Profile to sign in.
/// No Plus: the existing paywall, opened with the feature as its source.

/// "Re-rentals go first come, first served — get real-time alerts" (owner,
/// 2026-10-06). Without Plus, alerts arrive in one 8 AM digest; this opens the
/// Plus page. An optional ✕ hides it for good (`onDismiss`).
struct RealtimeUpsell: View {
    var source: String
    var onDismiss: (() -> Void)? = nil
    let open: () -> Void
    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "bolt.fill").font(.system(size: 18, weight: .bold)).foregroundStyle(Color(hex: 0x5B21B6))
            VStack(alignment: .leading, spacing: 6) {
                // Concise (owner, 2026-10-12): real-time vs once a day, and the
                // free first month, highlighted.
                HStack(spacing: 6) {
                    Text("Get alerts the minute they open, not once a day").font(.se(17, .bold)).foregroundStyle(SE.ink)
                        .fixedSize(horizontal: false, vertical: true)
                    PlusTag()
                }
                FreeMonthTag()
                Button { Analytics.shared.track("realtime_upsell_click", ["src": source]); open() } label: {
                    Text("Get real-time alerts").font(.se(16, .bold)).foregroundStyle(.white)
                        .padding(.horizontal, 14).frame(height: 40).background(Color(hex: 0x5B21B6)).clipShape(RoundedRectangle(cornerRadius: 10))
                }
                .buttonStyle(.plain).accessibilityIdentifier("realtime-upsell")
            }
            Spacer(minLength: 0)
            if let onDismiss {
                Button { Analytics.shared.track("realtime_upsell_dismiss", ["src": source]); onDismiss() } label: {
                    Image(systemName: "xmark").font(.system(size: 13, weight: .bold)).foregroundStyle(SE.ink3).frame(width: 44, height: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain).accessibilityLabel("Don't show this again").accessibilityIdentifier("realtime-upsell-dismiss")
            }
        }
        .padding(14).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color(hex: 0xF3EEFF)).clipShape(RoundedRectangle(cornerRadius: 12))
        .accessibilityElement(children: .contain)
    }
}

/// "First month free" — the Plus intro offer, highlighted (owner, 2026-10-12:
/// "highlight they will get one month free").
struct FreeMonthTag: View {
    var body: some View {
        Label("First month free", systemImage: "gift.fill")
            .font(.se(14, .bold)).foregroundStyle(Color(hex: 0x14532D))
            .padding(.horizontal, 10).padding(.vertical, 4)
            .background(Capsule().fill(Color(hex: 0xDCFCE7)))
            .accessibilityIdentifier("free-month-tag")
    }
}

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
    case .dailyLimit: String(localized: "That's a lot for one day — more tomorrow.")
    case .monthlyLimit: String(localized: "You've used this month's AI — more on the 1st.")
    case .declined: String(localized: "That isn't something the records can answer.")
    default: String(localized: "Not available right now. Try again in a little while.")
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
                SEPrimaryButton(title: busy ? String(localized: "Reading…") : String(localized: "Search"), icon: "sparkles") { Task { await go() } }
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
