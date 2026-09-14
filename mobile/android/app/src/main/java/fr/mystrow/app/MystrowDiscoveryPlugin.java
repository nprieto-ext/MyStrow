package fr.mystrow.app;

import android.content.Context;
import android.net.nsd.NsdManager;
import android.net.nsd.NsdServiceInfo;
import android.net.wifi.WifiManager;
import android.os.Handler;
import android.os.Looper;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/**
 * Découverte des PC MyStrow sur le Wi-Fi (Bonjour « _mystrow._tcp », annoncé par
 * tablet_server.py). Chaque PC résolu est envoyé à l'écran de connexion par
 * l'évènement « pcFound » { name, host, port }.
 */
@CapacitorPlugin(name = "MystrowDiscovery")
public class MystrowDiscoveryPlugin extends Plugin {

    private static final String SERVICE_TYPE = "_mystrow._tcp.";

    private NsdManager nsd;
    private NsdManager.DiscoveryListener discovery;
    private WifiManager.MulticastLock multicastLock;
    private final Handler main = new Handler(Looper.getMainLooper());

    @PluginMethod
    public void start(PluginCall call) {
        stopDiscovery();
        Context ctx = getContext();
        nsd = (NsdManager) ctx.getSystemService(Context.NSD_SERVICE);
        if (nsd == null) {
            call.reject("Découverte réseau indisponible sur cet appareil");
            return;
        }
        // Sans ce verrou, beaucoup de tablettes filtrent le multicast et ne
        // voient jamais les annonces Bonjour.
        WifiManager wifi = (WifiManager) ctx.getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        if (wifi != null) {
            multicastLock = wifi.createMulticastLock("mystrow-discovery");
            multicastLock.setReferenceCounted(false);
            multicastLock.acquire();
        }
        discovery = new NsdManager.DiscoveryListener() {
            @Override public void onDiscoveryStarted(String serviceType) { }
            @Override public void onDiscoveryStopped(String serviceType) { }
            @Override public void onStartDiscoveryFailed(String serviceType, int errorCode) { }
            @Override public void onStopDiscoveryFailed(String serviceType, int errorCode) { }
            @Override public void onServiceLost(NsdServiceInfo service) { }
            @Override public void onServiceFound(NsdServiceInfo service) { resolve(service, 0); }
        };
        nsd.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discovery);
        call.resolve();
    }

    @PluginMethod
    public void stop(PluginCall call) {
        stopDiscovery();
        call.resolve();
    }

    private void resolve(final NsdServiceInfo service, final int attempt) {
        if (nsd == null) return;
        nsd.resolveService(service, new NsdManager.ResolveListener() {
            @Override
            public void onResolveFailed(NsdServiceInfo info, int errorCode) {
                // Les anciens Android ne résolvent qu'un service à la fois.
                if (errorCode == NsdManager.FAILURE_ALREADY_ACTIVE && attempt < 10) {
                    main.postDelayed(() -> resolve(service, attempt + 1), 300);
                }
            }

            @Override
            public void onServiceResolved(NsdServiceInfo info) {
                InetAddress host = info.getHost();
                // Adresse IPv6 inutilisable telle quelle dans l'URL du PC.
                if (!(host instanceof Inet4Address)) return;
                String name = info.getServiceName();
                Map<String, byte[]> attrs = info.getAttributes();
                if (attrs != null && attrs.get("name") != null) {
                    name = new String(attrs.get("name"), StandardCharsets.UTF_8);
                }
                JSObject pc = new JSObject();
                pc.put("name", name);
                pc.put("host", host.getHostAddress());
                pc.put("port", info.getPort());
                notifyListeners("pcFound", pc);
            }
        });
    }

    private void stopDiscovery() {
        if (nsd != null && discovery != null) {
            try { nsd.stopServiceDiscovery(discovery); } catch (Exception ignored) { }
        }
        discovery = null;
        if (multicastLock != null && multicastLock.isHeld()) multicastLock.release();
        multicastLock = null;
    }

    @Override
    protected void handleOnDestroy() {
        stopDiscovery();
    }
}
