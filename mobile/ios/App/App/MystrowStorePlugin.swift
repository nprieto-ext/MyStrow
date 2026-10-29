import Foundation
import StoreKit
import Capacitor

/// Achat intégré « MyStrow Tablette » (non consommable, App Store Connect :
/// com.happlysas.mystrow.tablette) avec StoreKit 2. Pas de serveur : StoreKit
/// vérifie lui-même la signature des transactions, et `currentEntitlements`
/// répond hors ligne. Utilisé par account.js (iOS seulement).
///   product({id})  → { id, title, price }      prix affiché dans la devise du client
///   buy({id})      → { owned, cancelled, pending }
///   owned({id})    → { owned }
///   restore({id})  → { owned }                 « Restaurer les achats » (AppStore.sync)
/// Évènement « changed » { owned } : achat validé hors de l'app (Ask to Buy,
/// remboursement…), reçu par Transaction.updates.
@objc(MystrowStorePlugin)
public class MystrowStorePlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MystrowStorePlugin"
    public let jsName = "MystrowStore"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "product", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "buy", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "owned", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "restore", returnType: CAPPluginReturnPromise)
    ]

    private var updates: Task<Void, Never>?

    override public func load() {
        // Apple exige d'écouter les transactions dès le lancement : sinon un achat
        // terminé pendant que l'app était fermée n'est jamais « fini ».
        updates = Task.detached { [weak self] in
            for await result in Transaction.updates {
                if case .verified(let t) = result {
                    await t.finish()
                    let owned = await MystrowStorePlugin.isOwned(t.productID)
                    self?.notifyListeners("changed", data: ["id": t.productID, "owned": owned])
                }
            }
        }
    }

    deinit { updates?.cancel() }

    static func isOwned(_ id: String) async -> Bool {
        for await result in Transaction.currentEntitlements {
            if case .verified(let t) = result, t.productID == id, t.revocationDate == nil { return true }
        }
        return false
    }

    private func productId(_ call: CAPPluginCall) -> String? {
        guard let id = call.getString("id"), !id.isEmpty else { call.reject("id manquant"); return nil }
        return id
    }

    @objc func product(_ call: CAPPluginCall) {
        guard let id = productId(call) else { return }
        Task {
            do {
                guard let p = try await Product.products(for: [id]).first else { call.reject("Produit introuvable"); return }
                call.resolve(["id": p.id, "title": p.displayName, "price": p.displayPrice])
            } catch { call.reject(error.localizedDescription) }
        }
    }

    @objc func buy(_ call: CAPPluginCall) {
        guard let id = productId(call) else { return }
        Task {
            do {
                guard let p = try await Product.products(for: [id]).first else { call.reject("Produit introuvable"); return }
                switch try await p.purchase() {
                case .success(let result):
                    guard case .verified(let t) = result else { call.reject("Achat non vérifié par l'App Store"); return }
                    await t.finish()
                    call.resolve(["owned": true, "cancelled": false, "pending": false])
                case .userCancelled:
                    call.resolve(["owned": false, "cancelled": true, "pending": false])
                case .pending:   // « Demander l'autorisation d'achat » (enfant) : arrivera par Transaction.updates
                    call.resolve(["owned": false, "cancelled": false, "pending": true])
                @unknown default:
                    call.resolve(["owned": false, "cancelled": true, "pending": false])
                }
            } catch { call.reject(error.localizedDescription) }
        }
    }

    @objc func owned(_ call: CAPPluginCall) {
        guard let id = productId(call) else { return }
        Task { call.resolve(["owned": await MystrowStorePlugin.isOwned(id)]) }
    }

    @objc func restore(_ call: CAPPluginCall) {
        guard let id = productId(call) else { return }
        Task {
            do { try await AppStore.sync() } catch {
                // Annulé (connexion à l'identifiant Apple refusée) : on répond quand même.
            }
            call.resolve(["owned": await MystrowStorePlugin.isOwned(id)])
        }
    }
}
