import AppIntents
import Foundation

// Siri and Shortcuts (owner, 2026-10-13: "lets integrate siri"). App
// Shortcuts need no setup: once the app is installed, "Hey Siri, lotteries
// closing soon in Find A Crib" works. The answer intent reads the same public
// feed the Lotteries tab does and speaks without opening the app; the others
// open the app where the deep link points (DeepLink.swift).

struct LotteriesClosingSoonIntent: AppIntent {
    static let title: LocalizedStringResource = "Lotteries closing soon"
    static let description = IntentDescription("Hear which NYC housing lotteries close next.")
    @Parameter(title: "Borough", default: .any) var borough: BoroughChoice

    func perform() async throws -> some IntentResult & ProvidesDialog {
        let items = (try? await LotterySnapshot.open(borough: borough.feedName, limit: 3)) ?? []
        guard !items.isEmpty else {
            return .result(dialog: "There are no open housing lotteries right now. Open Find A Crib to turn on alerts.")
        }
        let lines = items.map { "\($0.name), closing \(LotterySnapshot.spoken($0.closes))" }
        return .result(dialog: "\(items.count == 1 ? "One lottery" : "\(items.count) lotteries") closing soonest: \(lines.joined(separator: "; ")).")
    }
}

struct OpenLotteriesIntent: AppIntent {
    static let title: LocalizedStringResource = "Show housing lotteries"
    static let description = IntentDescription("Open the Lotteries tab in Find A Crib.")
    static let openAppWhenRun = true
    @MainActor func perform() async throws -> some IntentResult {
        if let nav = AppNav.current { nav.tab = .lotteries } else { AppNav.launchLink = .lotteries }
        return .result()
    }
}

enum ToolChoice: String, AppEnum {
    case repair, rentIncrease = "rent-increase", rights, renewal
    static let typeDisplayRepresentation: TypeDisplayRepresentation = "Renter tool"
    static let caseDisplayRepresentations: [ToolChoice: DisplayRepresentation] = [
        .repair: "Get a repair made", .rentIncrease: "Rent increase check", .rights: "Know your rights", .renewal: "Renewal coach"]
}

struct OpenRenterToolIntent: AppIntent {
    static let title: LocalizedStringResource = "Open a renter tool"
    static let description = IntentDescription("Get a repair made, check a rent increase, read your rights, or plan a renewal.")
    static let openAppWhenRun = true
    @Parameter(title: "Tool") var tool: ToolChoice
    @MainActor func perform() async throws -> some IntentResult {
        let t = HomeTool(rawValue: tool.rawValue) ?? .rights
        if let nav = AppNav.current { nav.tab = .profile; nav.openTool = t } else { AppNav.launchLink = .tool(t) }
        return .result()
    }
}

struct FindACribShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        AppShortcut(intent: LotteriesClosingSoonIntent(), phrases: [
            "Which lotteries are closing in \(.applicationName)",
            "Lotteries closing soon in \(.applicationName)",
            "Any housing lotteries in \(.applicationName)",
            "Lotteries closing in \(\.$borough) in \(.applicationName)"],
            shortTitle: "Lotteries closing soon", systemImageName: "ticket")
        AppShortcut(intent: OpenLotteriesIntent(), phrases: [
            "Show lotteries in \(.applicationName)", "Open lotteries in \(.applicationName)"],
            shortTitle: "Show lotteries", systemImageName: "list.bullet.rectangle")
        AppShortcut(intent: OpenRenterToolIntent(), phrases: [
            "Open \(\.$tool) in \(.applicationName)", "\(\.$tool) with \(.applicationName)"],
            shortTitle: "Renter tools", systemImageName: "wrench.and.screwdriver")
    }
}
