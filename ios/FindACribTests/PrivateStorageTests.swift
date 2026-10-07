import Foundation
import Testing
@testable import FindACrib

/// Where the app keeps the user's private numbers and documents (security
/// audit 2026-10-07, L10/L11): household + income live in the Keychain, not
/// UserDefaults, and the document packet never leaves the device in a backup.
@Suite("Private storage", .serialized)
@MainActor
struct PrivateStorageTests {
    /// A throwaway Keychain service + UserDefaults suite per test.
    private func fixtures() -> (SecureStore, UserDefaults, String) {
        let id = "fac.test.\(UUID().uuidString)"
        return (SecureStore(service: id), UserDefaults(suiteName: id)!, id)
    }

    @Test("SecureStore round-trips, overwrites and removes")
    func secureStoreRoundTrip() {
        let (store, _, id) = fixtures()
        defer { UserDefaults().removePersistentDomain(forName: id) }
        #expect(store.data("a") == nil)
        #expect(store.set(Data("one".utf8), for: "a"))
        #expect(store.set(Data("two".utf8), for: "a"))
        #expect(store.data("a") == Data("two".utf8))
        store.remove("a")
        #expect(store.data("a") == nil)
    }

    @Test("legacy UserDefaults values move to the Keychain and are deleted")
    func migratesFromUserDefaults() {
        let (store, defaults, id) = fixtures()
        defer { store.remove(Qualify.account); UserDefaults().removePersistentDomain(forName: id) }
        defaults.set(3, forKey: Qualify.legacyKeys.household)
        defaults.set(64000, forKey: Qualify.legacyKeys.income)

        let q = Qualify(store: store, defaults: defaults)
        #expect(q.household == 3)
        #expect(q.income == 64000)
        #expect(defaults.object(forKey: Qualify.legacyKeys.household) == nil)
        #expect(defaults.object(forKey: Qualify.legacyKeys.income) == nil)
        #expect(store.data(Qualify.account) != nil)

        // A second launch reads the Keychain copy.
        let again = Qualify(store: store, defaults: defaults)
        #expect(again.household == 3)
        #expect(again.income == 64000)
    }

    @Test("set writes only the Keychain; clear removes it")
    func setAndClear() {
        let (store, defaults, id) = fixtures()
        defer { store.remove(Qualify.account); UserDefaults().removePersistentDomain(forName: id) }
        let q = Qualify(store: store, defaults: defaults)
        #expect(!q.isSet)
        q.set(household: 2, income: 51000)
        #expect(defaults.object(forKey: Qualify.legacyKeys.income) == nil)
        #expect(Qualify(store: store, defaults: defaults).income == 51000)
        q.clear()
        #expect(store.data(Qualify.account) == nil)
        #expect(!Qualify(store: store, defaults: defaults).isSet)
    }

    @Test("a leftover Keychain item from a previous install is dropped")
    func freshInstallForgets() {
        let (store, defaults, id) = fixtures()
        defer { store.remove(Qualify.account); UserDefaults().removePersistentDomain(forName: id) }
        Qualify(store: store, defaults: defaults).set(household: 1, income: 40000)
        // Uninstall wipes UserDefaults (incl. the install marker) but not the Keychain.
        UserDefaults().removePersistentDomain(forName: id)
        let fresh = UserDefaults(suiteName: id)!
        #expect(!Qualify(store: store, defaults: fresh).isSet)
    }

    @Test("packet folder is excluded from backup with Complete protection")
    func packetFolderLockedDown() throws {
        let dir = FileManager.default.temporaryDirectory
            .appendingPathComponent("packet-test-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: dir) }
        // An existing folder (pre-fix installs) must be fixed up too.
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        Packet.prepareFolder(dir)
        let v = try dir.resourceValues(forKeys: [.isExcludedFromBackupKey])
        #expect(v.isExcludedFromBackup == true)
        let attrs = try FileManager.default.attributesOfItem(atPath: dir.path)
        // The simulator has no Data Protection; it may report nil. On device it must be complete.
        if let p = attrs[.protectionKey] as? FileProtectionType {
            #expect(p == .complete)
        }
        #expect(Packet.folder.lastPathComponent == "Packet")
    }
}
