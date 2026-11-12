package fr.mystrow.app;

import com.android.billingclient.api.AcknowledgePurchaseParams;
import com.android.billingclient.api.BillingClient;
import com.android.billingclient.api.BillingClientStateListener;
import com.android.billingclient.api.BillingFlowParams;
import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.PendingPurchasesParams;
import com.android.billingclient.api.ProductDetails;
import com.android.billingclient.api.Purchase;
import com.android.billingclient.api.QueryProductDetailsParams;
import com.android.billingclient.api.QueryPurchasesParams;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Achat intégré « MyStrow Tablette » sur Google Play (produit unique non
 * consommable, Play Console : com.happlysas.mystrow.tablette). Même interface
 * JS que MystrowStorePlugin.swift (iOS), utilisée par account.js :
 *   product({id})  → { id, title, price }      prix dans la devise du client
 *   buy({id})      → { owned, cancelled, pending }
 *   owned({id})    → { owned }
 *   restore({id})  → { owned }                 Play relit les achats du compte Google
 * Évènement « changed » { id, owned } : achat en attente devenu payé, etc.
 *
 * Pas de serveur : l'état vient de queryPurchasesAsync (cache Play, lisible
 * hors ligne). Un achat non « acknowledged » sous 3 jours est remboursé
 * automatiquement par Google : on l'acquitte dès qu'il est PURCHASED.
 */
@CapacitorPlugin(name = "MystrowStore")
public class MystrowStorePlugin extends Plugin {

    private BillingClient client;
    private PluginCall pendingBuy;          // appel buy() en cours, résolu par onPurchasesUpdated
    private String pendingBuyId;

    @Override
    public void load() {
        client = BillingClient.newBuilder(getContext())
                .setListener(this::onPurchasesUpdated)
                .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().build())
                .build();
    }

    @Override
    protected void handleOnDestroy() {
        if (client != null) client.endConnection();
    }

    // ── Connexion au service Play (asynchrone, peut tomber à tout moment) ──────
    private interface Ready { void run(); }

    private void withClient(PluginCall call, Ready ready) {
        if (client.isReady()) { ready.run(); return; }
        client.startConnection(new BillingClientStateListener() {
            @Override public void onBillingSetupFinished(BillingResult r) {
                if (r.getResponseCode() == BillingClient.BillingResponseCode.OK) ready.run();
                else if (call != null) call.reject(message(r));
            }
            @Override public void onBillingServiceDisconnected() { /* reconnexion au prochain appel */ }
        });
    }

    private static String message(BillingResult r) {
        switch (r.getResponseCode()) {
            case BillingClient.BillingResponseCode.BILLING_UNAVAILABLE:
            case BillingClient.BillingResponseCode.SERVICE_UNAVAILABLE:
            case BillingClient.BillingResponseCode.SERVICE_DISCONNECTED:
                return "Google Play indisponible : vérifiez la connexion et le compte Google de la tablette.";
            case BillingClient.BillingResponseCode.ITEM_UNAVAILABLE:
                return "Produit introuvable";
            default:
                String d = r.getDebugMessage();
                return (d == null || d.isEmpty()) ? "Erreur Google Play (" + r.getResponseCode() + ")" : d;
        }
    }

    private String productId(PluginCall call) {
        String id = call.getString("id");
        if (id == null || id.isEmpty()) { call.reject("id manquant"); return null; }
        return id;
    }

    private interface DetailsCb { void done(ProductDetails pd); }

    private void details(PluginCall call, String id, DetailsCb cb) {
        QueryProductDetailsParams params = QueryProductDetailsParams.newBuilder()
                .setProductList(Collections.singletonList(QueryProductDetailsParams.Product.newBuilder()
                        .setProductId(id).setProductType(BillingClient.ProductType.INAPP).build()))
                .build();
        client.queryProductDetailsAsync(params, (r, result) -> {
            if (r.getResponseCode() != BillingClient.BillingResponseCode.OK) { call.reject(message(r)); return; }
            List<ProductDetails> list = result.getProductDetailsList();
            if (list == null || list.isEmpty()) { call.reject("Produit introuvable"); return; }
            cb.done(list.get(0));
        });
    }

    // ── État des achats ────────────────────────────────────────────────────────
    private interface OwnedCb { void done(boolean owned, boolean pending); }

    /** Relit les achats du compte Google, acquitte ceux qui ne le sont pas encore. */
    private void queryOwned(PluginCall call, String id, OwnedCb cb) {
        client.queryPurchasesAsync(
                QueryPurchasesParams.newBuilder().setProductType(BillingClient.ProductType.INAPP).build(),
                (r, purchases) -> {
                    if (r.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                        if (call != null) call.reject(message(r));
                        return;
                    }
                    boolean owned = false, pending = false;
                    for (Purchase p : purchases) {
                        if (!p.getProducts().contains(id)) continue;
                        if (p.getPurchaseState() == Purchase.PurchaseState.PURCHASED) { owned = true; acknowledge(p); }
                        else if (p.getPurchaseState() == Purchase.PurchaseState.PENDING) pending = true;
                    }
                    cb.done(owned, pending);
                });
    }

    private void acknowledge(Purchase p) {
        if (p.isAcknowledged()) return;
        client.acknowledgePurchase(
                AcknowledgePurchaseParams.newBuilder().setPurchaseToken(p.getPurchaseToken()).build(),
                r -> { /* réessayé au prochain queryOwned si ça échoue */ });
    }

    /** Résultat de launchBillingFlow, et achats « en attente » devenus payés. */
    private void onPurchasesUpdated(BillingResult r, List<Purchase> purchases) {
        PluginCall call = pendingBuy;
        String id = pendingBuyId;
        pendingBuy = null; pendingBuyId = null;
        int code = r.getResponseCode();

        boolean owned = false, pending = false;
        List<String> ids = new ArrayList<>();
        if (purchases != null) {
            for (Purchase p : purchases) {
                ids.addAll(p.getProducts());
                if (p.getPurchaseState() == Purchase.PurchaseState.PURCHASED) { acknowledge(p); if (id == null || p.getProducts().contains(id)) owned = true; }
                else if (p.getPurchaseState() == Purchase.PurchaseState.PENDING) pending = true;
            }
        }
        // Achat payé hors d'un buy() en cours (paiement en espèces validé plus tard…).
        if (call == null) {
            for (String pid : ids) {
                JSObject d = new JSObject();
                d.put("id", pid);
                d.put("owned", owned);
                notifyListeners("changed", d);
            }
            return;
        }
        if (code == BillingClient.BillingResponseCode.OK) {
            call.resolve(result(owned, false, pending && !owned));
        } else if (code == BillingClient.BillingResponseCode.USER_CANCELED) {
            call.resolve(result(false, true, false));
        } else if (code == BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED) {
            final String fid = id;
            queryOwned(call, fid, (o, p) -> call.resolve(result(o, false, p && !o)));
        } else {
            call.reject(message(r));
        }
    }

    private static JSObject result(boolean owned, boolean cancelled, boolean pending) {
        JSObject o = new JSObject();
        o.put("owned", owned);
        o.put("cancelled", cancelled);
        o.put("pending", pending);
        return o;
    }

    // ── Méthodes JS ────────────────────────────────────────────────────────────
    @PluginMethod
    public void product(PluginCall call) {
        String id = productId(call);
        if (id == null) return;
        withClient(call, () -> details(call, id, pd -> {
            JSObject o = new JSObject();
            o.put("id", pd.getProductId());
            o.put("title", pd.getName());
            ProductDetails.OneTimePurchaseOfferDetails offer = pd.getOneTimePurchaseOfferDetails();
            o.put("price", offer != null ? offer.getFormattedPrice() : "");
            call.resolve(o);
        }));
    }

    @PluginMethod
    public void buy(PluginCall call) {
        String id = productId(call);
        if (id == null) return;
        if (pendingBuy != null) { call.reject("Un achat est déjà en cours."); return; }
        withClient(call, () -> details(call, id, pd -> getActivity().runOnUiThread(() -> {
            BillingFlowParams flow = BillingFlowParams.newBuilder()
                    .setProductDetailsParamsList(Collections.singletonList(
                            BillingFlowParams.ProductDetailsParams.newBuilder().setProductDetails(pd).build()))
                    .build();
            pendingBuy = call;
            pendingBuyId = id;
            BillingResult r = client.launchBillingFlow(getActivity(), flow);
            if (r.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                pendingBuy = null; pendingBuyId = null;
                if (r.getResponseCode() == BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED)
                    queryOwned(call, id, (o, p) -> call.resolve(result(o, false, p && !o)));
                else call.reject(message(r));
            }
        })));
    }

    @PluginMethod
    public void owned(PluginCall call) {
        String id = productId(call);
        if (id == null) return;
        withClient(call, () -> queryOwned(call, id, (o, p) -> {
            JSObject r = new JSObject();
            r.put("owned", o);
            call.resolve(r);
        }));
    }

    /** « Restaurer les achats » : sur Android, Play relit simplement le compte Google. */
    @PluginMethod
    public void restore(PluginCall call) {
        owned(call);
    }
}
