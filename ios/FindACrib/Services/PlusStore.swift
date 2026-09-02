import Foundation
import Observation
import StoreKit
import Supabase

/// Find A Crib Plus as an App Store auto-renewable subscription (StoreKit 2).
///
/// The entitlement of record lives server-side: every verified transaction
/// is posted to the apple-subscription edge function, which checks Apple's
/// signature and writes the caller's row in `subscriptions` — the row
/// has_plus() reads, so a subscriber sees phone numbers here and on the
/// website alike, and a Stripe subscriber from the web is Plus here too.
@Observable @MainActor
final class PlusStore {
    static let productID = "com.divinedavis.findacrib.plus.monthly"
    static let termsURL = URL(string: "https://www.apple.com/legal/internet-services/itunes/dev/stdeula/")!
    static let privacyURL = URL(string: "https://findacrib.com/privacy/")!

    private(set) var product: Product?
    /// True while StoreKit says this device holds an active Plus entitlement.
    private(set) var entitled = false
    private(set) var busy = false
    var error: String?
    private var updates: Task<Void, Never>?
    weak var auth: AuthService?

    func start() {
        updates = Task { [weak self] in
            for await result in Transaction.updates {
                guard let self, case .verified(let tx) = result else { continue }
                await self.handle(tx, jws: result.jwsRepresentation)
                await tx.finish()
            }
        }
        Task { await load(); await refreshEntitlement() }
    }

    func load() async {
        do { product = try await Product.products(for: [Self.productID]).first }
        catch { self.error = "Couldn't load the subscription: \(error.localizedDescription)" }
    }

    var priceText: String { product?.displayPrice ?? "$4.99" }

    /// Buy. Requires a signed-in account so the entitlement can be bound to it.
    func purchase() async {
        guard let product else { await load(); guard self.product != nil else { return }; return await purchase() }
        guard auth?.isSignedIn == true else { error = "Sign in first so Plus is tied to your account."; return }
        busy = true; error = nil; defer { busy = false }
        do {
            let result = try await product.purchase()
            switch result {
            case .success(let verification):
                guard case .verified(let tx) = verification else { error = "Apple couldn't verify the purchase."; return }
                await handle(tx, jws: verification.jwsRepresentation)
                await tx.finish()
            case .userCancelled, .pending: break
            @unknown default: break
            }
        } catch { self.error = error.localizedDescription }
    }

    func restore() async {
        busy = true; error = nil; defer { busy = false }
        try? await AppStore.sync()
        await refreshEntitlement()
        if !entitled { error = "No active Find A Crib Plus subscription on this Apple ID." }
    }

    /// Current entitlement from StoreKit, pushed to the server when signed in.
    func refreshEntitlement() async {
        var found = false
        for await result in Transaction.currentEntitlements {
            guard case .verified(let tx) = result, tx.productID == Self.productID else { continue }
            found = tx.revocationDate == nil && (tx.expirationDate.map { $0 > Date() } ?? true)
            if found { await handle(tx, jws: result.jwsRepresentation) }
        }
        entitled = found
    }

    private func handle(_ tx: Transaction, jws: String) async {
        entitled = tx.revocationDate == nil && (tx.expirationDate.map { $0 > Date() } ?? true)
        await sync(jws: jws)
    }

    /// Server-side verification + row write. Silent when signed out; the
    /// entitlement is re-synced on the next sign-in (AuthService calls this).
    func sync(jws: String? = nil) async {
        guard let auth, auth.isSignedIn, let client = auth.client else { return }
        var token = jws
        if token == nil {
            for await r in Transaction.currentEntitlements {
                if case .verified(let tx) = r, tx.productID == Self.productID { token = r.jwsRepresentation }
            }
        }
        guard let token else { return }
        do {
            _ = try await client.functions.invoke("apple-subscription", options: .init(body: ["jws": token]))
            await auth.refreshPlus()
        } catch {
            // Network hiccup: the local entitlement still unlocks Plus this session.
        }
    }

    func manage() async {
        guard let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first else { return }
        try? await AppStore.showManageSubscriptions(in: scene)
    }
}
