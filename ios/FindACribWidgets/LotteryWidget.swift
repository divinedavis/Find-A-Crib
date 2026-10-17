import AppIntents
import SwiftUI
import WidgetKit

// Home and Lock Screen widget (owner, 2026-10-13: "lets do widgets"): the NYC
// housing lotteries closing soonest, for the borough the person picks when
// they edit the widget. It reads the same public feed the Lotteries tab and
// Siri do (Shared/LotterySnapshot.swift) — no account, nothing shared with
// the app — and a tap opens the Lotteries tab (findacrib://lotteries).

struct LotteryWidgetConfig: WidgetConfigurationIntent {
    static let title: LocalizedStringResource = "Lotteries closing soon"
    static let description = IntentDescription("NYC housing lotteries with the nearest deadlines.")
    @Parameter(title: "Borough", default: .any) var borough: BoroughChoice
}

struct LotteryEntry: TimelineEntry {
    let date: Date
    let items: [LotterySnapshot.Item]
    let borough: BoroughChoice
    let failed: Bool
}

struct LotteryProvider: AppIntentTimelineProvider {
    func placeholder(in context: Context) -> LotteryEntry {
        LotteryEntry(date: .now, items: [
            .init(name: "1718 Crotona Park East", borough: "Bronx", closes: LotterySnapshot.todayKey(.now.addingTimeInterval(3 * 86400)), href: nil),
            .init(name: "624 Metropolitan Avenue", borough: "Brooklyn", closes: LotterySnapshot.todayKey(.now.addingTimeInterval(6 * 86400)), href: nil),
            .init(name: "1349 Commonwealth Avenue", borough: "Bronx", closes: LotterySnapshot.todayKey(.now.addingTimeInterval(9 * 86400)), href: nil)],
            borough: .any, failed: false)
    }

    func snapshot(for configuration: LotteryWidgetConfig, in context: Context) async -> LotteryEntry {
        context.isPreview ? placeholder(in: context) : await entry(configuration)
    }

    func timeline(for configuration: LotteryWidgetConfig, in context: Context) async -> Timeline<LotteryEntry> {
        let e = await entry(configuration)
        // The feed refreshes a few times a day; check every 3 hours, and right after midnight NY time so "today" is right.
        let next = min(Date().addingTimeInterval(3 * 3600), Calendar.current.startOfDay(for: Date().addingTimeInterval(86400)).addingTimeInterval(300))
        return Timeline(entries: [e], policy: .after(next))
    }

    private func entry(_ c: LotteryWidgetConfig) async -> LotteryEntry {
        do {
            let items = try await LotterySnapshot.open(borough: c.borough.feedName, limit: 4)
            return LotteryEntry(date: .now, items: items, borough: c.borough, failed: false)
        } catch {
            return LotteryEntry(date: .now, items: [], borough: c.borough, failed: true)
        }
    }
}

private let teal = Color(red: 40 / 255, green: 92 / 255, blue: 105 / 255)
private let warn = Color(red: 0.78, green: 0.36, blue: 0.05)

private func daysLeft(_ closes: String?) -> Int? {
    let f = DateFormatter(); f.dateFormat = "yyyy-MM-dd"; f.locale = Locale(identifier: "en_US_POSIX")
    f.timeZone = TimeZone(identifier: "America/New_York")
    guard let c = closes, let a = f.date(from: LotterySnapshot.todayKey()), let b = f.date(from: c) else { return nil }
    return Calendar.current.dateComponents([.day], from: a, to: b).day
}

private func whenText(_ closes: String?) -> String {
    guard let d = daysLeft(closes) else { return String(localized: "Open") }
    return d == 0 ? String(localized: "Closes today") : d == 1 ? String(localized: "Closes tomorrow") : String(localized: "Closes in \(d) days")
}

struct LotteryWidgetView: View {
    @Environment(\.widgetFamily) private var family
    let entry: LotteryEntry

    var body: some View {
        switch family {
        case .accessoryInline:
            Text(entry.items.first.map { "🏠 \($0.name) · \(whenText($0.closes))" } ?? String(localized: "🏠 No open lotteries"))
        case .accessoryRectangular:
            VStack(alignment: .leading, spacing: 1) {
                Text("Lotteries").font(.headline).widgetAccentable()
                if let f = entry.items.first {
                    Text(f.name).font(.caption).lineLimit(1)
                    Text(whenText(f.closes)).font(.caption2)
                } else { Text(entry.failed ? String(localized: "Can't load right now") : String(localized: "None open right now")).font(.caption) }
            }
        case .accessoryCircular:
            VStack(spacing: 0) {
                Text("\(entry.items.count)").font(.title2.bold())
                Text("open").font(.caption2)
            }
        default:
            homeScreen
        }
    }

    private var homeScreen: some View {
        let shown = Array(entry.items.prefix(family == .systemSmall ? 2 : family == .systemMedium ? 3 : 4))
        return VStack(alignment: .leading, spacing: family == .systemSmall ? 6 : 8) {
            HStack(spacing: 6) {
                Image(systemName: "ticket.fill").foregroundStyle(teal)
                Text(entry.borough == .any ? String(localized: "NYC lotteries") : String(localized: "Lotteries · \(entry.borough.feedName ?? "")"))
                    .font(.system(size: 13, weight: .bold)).foregroundStyle(teal).lineLimit(1)
            }
            if shown.isEmpty {
                Text(entry.failed ? String(localized: "Can't load lotteries right now.") : String(localized: "No lotteries open right now. Alerts tell you when one opens."))
                    .font(.system(size: 13)).foregroundStyle(.secondary)
                Spacer(minLength: 0)
            } else {
                ForEach(Array(shown.enumerated()), id: \.offset) { _, l in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(l.name).font(.system(size: family == .systemSmall ? 13 : 14, weight: .semibold)).lineLimit(family == .systemSmall ? 2 : 1)
                        Text("\(l.borough) · \(whenText(l.closes))").font(.system(size: 11, weight: .medium))
                            .foregroundStyle((daysLeft(l.closes) ?? 99) <= 3 ? warn : .secondary).lineLimit(1)
                    }
                }
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
}

struct LotteryWidget: Widget {
    var body: some WidgetConfiguration {
        AppIntentConfiguration(kind: "LotteriesClosingSoon", intent: LotteryWidgetConfig.self, provider: LotteryProvider()) { entry in
            LotteryWidgetView(entry: entry)
                .containerBackground(.background, for: .widget)
                .widgetURL(URL(string: "findacrib://lotteries"))
        }
        .configurationDisplayName("Lotteries closing soon")
        .description("NYC housing lotteries with the nearest deadlines.")
        .supportedFamilies([.systemSmall, .systemMedium, .systemLarge, .accessoryRectangular, .accessoryInline, .accessoryCircular])
    }
}

@main
struct FindACribWidgetBundle: WidgetBundle {
    var body: some Widget { LotteryWidget() }
}
