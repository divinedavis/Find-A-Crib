import Foundation
import Observation

/// Everything "My Activity" shows: saved buildings, saved searches, recent
/// searches and recently viewed. Persisted as JSON in Application Support.
/// Local-only for now; the web app's `saved_buildings` table is the sync
/// target once sign-in lands.
@Observable @MainActor
final class Activity {
    private(set) var saved: [String] = []              // BBLs, newest first
    private(set) var savedSearches: [SavedSearch] = []
    private(set) var recentSearches: [SearchQuery] = []
    private(set) var recentlyViewed: [String] = []     // BBLs, newest first

    private struct Disk: Codable {
        var saved: [String]; var savedSearches: [SavedSearch]; var recentSearches: [SearchQuery]; var recentlyViewed: [String]
    }
    private static var fileURL: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        try? FileManager.default.createDirectory(at: base, withIntermediateDirectories: true)
        return base.appendingPathComponent("activity.json")
    }

    init() {
        if let d = try? Data(contentsOf: Self.fileURL), let disk = try? JSONDecoder().decode(Disk.self, from: d) {
            saved = disk.saved; savedSearches = disk.savedSearches
            recentSearches = disk.recentSearches; recentlyViewed = disk.recentlyViewed
        }
    }

    private func persist() {
        let disk = Disk(saved: saved, savedSearches: savedSearches, recentSearches: recentSearches, recentlyViewed: recentlyViewed)
        if let d = try? JSONEncoder().encode(disk) { try? d.write(to: Self.fileURL, options: .atomic) }
    }

    /// Set by AuthService; mirrors each toggle into saved_buildings when signed in.
    var remoteToggle: ((String, Bool) -> Void)?

    func isSaved(_ bbl: String) -> Bool { saved.contains(bbl) }
    func toggleSaved(_ bbl: String) {
        let nowSaved: Bool
        if let i = saved.firstIndex(of: bbl) { saved.remove(at: i); nowSaved = false } else { saved.insert(bbl, at: 0); nowSaved = true }
        persist()
        remoteToggle?(bbl, nowSaved)
    }
    /// Account saves win on order; anything only known locally stays.
    func mergeRemoteSaves(_ remote: [String]) {
        var merged = remote
        for b in saved where !merged.contains(b) { merged.append(b) }
        saved = merged
        persist()
    }

    func recordSearch(_ q: SearchQuery) {
        recentSearches.removeAll { $0 == q }
        recentSearches.insert(q, at: 0)
        if recentSearches.count > 10 { recentSearches.removeLast(recentSearches.count - 10) }
        persist()
    }

    func saveSearch(_ q: SearchQuery, name: String, count: Int) {
        savedSearches.insert(SavedSearch(name: name, query: q, resultCount: count), at: 0)
        persist()
    }
    func deleteSearch(_ id: UUID) { savedSearches.removeAll { $0.id == id }; persist() }
    func isSearchSaved(_ q: SearchQuery) -> Bool { savedSearches.contains { $0.query == q } }

    func recordView(_ bbl: String) {
        recentlyViewed.removeAll { $0 == bbl }
        recentlyViewed.insert(bbl, at: 0)
        if recentlyViewed.count > 50 { recentlyViewed.removeLast(recentlyViewed.count - 50) }
        persist()
    }

    func clearRecents() { recentlyViewed = []; recentSearches = []; persist() }
}
