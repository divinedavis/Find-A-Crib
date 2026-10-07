import Foundation
import Security

/// Small Keychain wrapper for values that must not sit in UserDefaults
/// (a plain plist that rides along in unencrypted backups). Items are
/// `AfterFirstUnlockThisDeviceOnly`: readable after the first unlock, never
/// synced to iCloud Keychain and never restored onto another device.
struct SecureStore: Sendable {
    let service: String

    init(service: String) { self.service = service }

    private func base(_ account: String) -> [String: Any] {
        [kSecClass as String: kSecClassGenericPassword,
         kSecAttrService as String: service,
         kSecAttrAccount as String: account]
    }

    func data(_ account: String) -> Data? {
        var q = base(account)
        q[kSecReturnData as String] = true
        q[kSecMatchLimit as String] = kSecMatchLimitOne
        var out: CFTypeRef?
        guard SecItemCopyMatching(q as CFDictionary, &out) == errSecSuccess else { return nil }
        return out as? Data
    }

    @discardableResult
    func set(_ data: Data, for account: String) -> Bool {
        let attrs: [String: Any] = [kSecValueData as String: data,
                                    kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly]
        let status = SecItemUpdate(base(account) as CFDictionary, attrs as CFDictionary)
        if status == errSecItemNotFound {
            var add = base(account)
            add.merge(attrs) { $1 }
            return SecItemAdd(add as CFDictionary, nil) == errSecSuccess
        }
        return status == errSecSuccess
    }

    func remove(_ account: String) {
        SecItemDelete(base(account) as CFDictionary)
    }
}
