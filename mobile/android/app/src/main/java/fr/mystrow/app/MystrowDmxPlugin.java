package fr.mystrow.app;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbManager;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import android.net.NetworkCapabilities;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.Process;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.hoho.android.usbserial.driver.CdcAcmSerialDriver;
import com.hoho.android.usbserial.driver.FtdiSerialDriver;
import com.hoho.android.usbserial.driver.ProbeTable;
import com.hoho.android.usbserial.driver.UsbSerialDriver;
import com.hoho.android.usbserial.driver.UsbSerialPort;
import com.hoho.android.usbserial.driver.UsbSerialProber;

import org.json.JSONException;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.InetSocketAddress;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/**
 * Sortie DMX de la tablette en mode autonome, sans PC. Deux transports :
 *   - « artnet » : ArtDMX (OpCode 0x5000) envoyé au node en UDP — y compris
 *                  le « USB NODE » ElectroConcept, qui se présente à la
 *                  tablette comme une carte réseau USB (2.0.0.x). Node hors du
 *                  réseau de la tablette (node en 2.0.0.15 sur la box, tablette
 *                  en 192.168.1.x) : envoi en diffusion, seul moyen de l'atteindre ;
 *   - « usb »    : deux familles d'interfaces, reconnues toutes seules :
 *       · passive (Open DMX : Opto ElectroConcept, FTDI, CH340…) : la
 *         tablette génère elle-même break + trame à 250 kbauds ;
 *       · « intelligente » (protocole ENTTEC Pro : ENTTEC, DMXKing, et le
 *         boîtier USB-DMX MyStrow) : le boîtier fait le break et le timing,
 *         la tablette envoie juste les 512 canaux (paquet 7E 06 … E7).
 *
 * La cadence ne dépend PAS du JavaScript : un thread natif réémet la dernière
 * trame à fréquence fixe (comme le timer DMX du PC). Le JS ne fait que modifier
 * les canaux avec setChannels() quand quelque chose change.
 *
 * Mêmes trames que artnet_dmx.py (_build_artnet_packet, boucle D2XX).
 */
@CapacitorPlugin(name = "MystrowDmx")
public class MystrowDmxPlugin extends Plugin {

    private static final String ACTION_USB_PERMISSION = "fr.mystrow.app.USB_PERMISSION";
    /** 513 octets à 250 kbauds, 11 bits chacun = 22,6 ms, + marge (cf. boucle D2XX du PC). */
    private static final long USB_FRAME_NS = 26_000_000L;

    /** Une sortie physique : reçoit une trame complète de 512 canaux par tick. */
    private interface Output {
        void send(byte[] dmx512) throws Exception;
        /** Temps pendant lequel la ligne est occupée après send() (0 = aucun). */
        long busyNs();
        void close();
        String describe();
    }

    private final Object lock = new Object();
    private final byte[] dmx = new byte[512];

    private volatile Thread sender;
    private volatile boolean running;
    private WifiManager.WifiLock wifiLock;

    // Statistiques de cadence (lues par stats()).
    private long sent, errors, lateTicks;
    private long maxIntervalNs, sumIntervalNs, intervals;
    private String lastError, outputName;

    // ── Art-Net ─────────────────────────────────────────────────────────────

    private static final class ArtNetOutput implements Output {
        private final DatagramSocket socket;
        private final DatagramPacket dp;
        private final byte[] packet = new byte[18 + 512];
        private final String name;
        private int seq;

        ArtNetOutput(Context ctx, String host, int port, int universe) throws Exception {
            InetAddress target = InetAddress.getByName(host);
            socket = new DatagramSocket();
            socket.setBroadcast(true);
            // Sans ça, Android envoie tout par le réseau « par défaut » (le Wi-Fi) :
            // vers 2.0.0.x ça part à la box et se perd, sans aucune erreur.
            Network net = networkFor(ctx, target);
            if (net != null) net.bindSocket(socket);
            // Node dans AUCUN réseau de la tablette et pas de filaire : en unicast le
            // paquet partirait à la passerelle de la box et se perdrait. En
            // diffusion il atteint le node branché sur la box (validé 24/09/2026,
            // node 2.0.0.15, tablette 192.168.1.x). Le node ne peut pas changer
            // d'adresse depuis l'app (pas d'ArtIpProg chez ElectroConcept).
            String how = "";
            if (net == null && !isBroadcast(target) && subnetNetwork(ctx, target) == null) {
                target = InetAddress.getByName("255.255.255.255");
                how = " (diffusion : node hors du réseau de la tablette)";
            }
            System.arraycopy("Art-Net\0".getBytes(), 0, packet, 0, 8);
            packet[8] = 0x00; packet[9] = 0x50;            // OpCode ArtDMX (little endian)
            packet[10] = 0x00; packet[11] = 0x0e;          // Protocole 14
            packet[14] = (byte) (universe & 0xFF);         // SubUni
            packet[15] = (byte) ((universe >> 8) & 0x7F);  // Net
            packet[16] = 0x02; packet[17] = 0x00;          // Longueur 512
            dp = new DatagramPacket(packet, packet.length, target, port);
            name = "Art-Net " + host + ":" + port + how + " via " + (net != null ? ifaceName(ctx, net) : "réseau par défaut");
        }

        @Override public void send(byte[] dmx512) throws Exception {
            seq = seq % 255 + 1;                           // 1..255 (0 = séquence désactivée)
            packet[12] = (byte) seq;
            System.arraycopy(dmx512, 0, packet, 18, 512);
            socket.send(dp);
        }
        @Override public long busyNs() { return 0; }
        @Override public void close() { socket.close(); }
        @Override public String describe() { return name; }
    }

    // ── USB-DMX passif (Open DMX) ───────────────────────────────────────────

    private static final class UsbOutput implements Output {
        private final UsbSerialPort port;
        private final byte[] frame = new byte[513];        // start code 0x00 + 512 canaux
        private final String name;

        UsbOutput(UsbSerialPort port, UsbSerialDriver driver) throws Exception {
            this.port = port;
            port.setParameters(250000, 8, UsbSerialPort.STOPBITS_2, UsbSerialPort.PARITY_NONE);
            // RTS désassertée : sur l'ENTTEC Open DMX, RTS porte le Driver Enable
            // du RS485 ; assertée = sortie muette sans aucune erreur (cf. artnet_dmx.py).
            try { port.setRTS(false); port.setDTR(false); } catch (Exception ignored) { }
            name = "USB " + describeDevice(driver.getDevice());
        }

        @Override public void send(byte[] dmx512) throws Exception {
            // BREAK puis MAB, générés par la puce. Chaque requête de contrôle USB
            // prend ~1 ms : le break dure donc ≥ 1 ms, bien au-dessus des 88 µs.
            port.setBreak(true);
            port.setBreak(false);
            System.arraycopy(dmx512, 0, frame, 1, 512);
            port.write(frame, 200);
        }
        // write() rend la main quand la puce a reçu les octets, pas quand ils
        // sont sortis sur le câble : le break suivant tronquerait la trame.
        @Override public long busyNs() { return USB_FRAME_NS; }
        @Override public void close() {
            try { port.close(); } catch (Exception ignored) { }
        }
        @Override public String describe() { return name; }
    }

    // ── USB-DMX « intelligent » (protocole ENTTEC Pro) ──────────────────────

    private static final class ProOutput implements Output {
        private final UsbSerialPort port;
        // SOM + label 6 (Output Only Send DMX) + taille 513 (LSB, MSB) + start
        // code, 512 canaux, EOM : même paquet que artnet_dmx._build_pro_packet.
        private final byte[] packet = new byte[5 + 512 + 1];
        private final String name;

        ProOutput(UsbSerialPort port, UsbSerialDriver driver) {
            this.port = port;
            packet[0] = 0x7E; packet[1] = 6; packet[2] = 0x01; packet[3] = 0x02; packet[4] = 0x00;
            packet[packet.length - 1] = (byte) 0xE7;
            name = "USB ENTTEC Pro " + describeDevice(driver.getDevice());
        }

        @Override public void send(byte[] dmx512) throws Exception {
            System.arraycopy(dmx512, 0, packet, 5, 512);
            port.write(packet, 200);
        }
        // Le boîtier gère lui-même la ligne DMX : aucune attente côté tablette.
        @Override public long busyNs() { return 0; }
        @Override public void close() {
            try { port.close(); } catch (Exception ignored) { }
        }
        @Override public String describe() { return name; }
    }

    /**
     * Détecteur d'interfaces série : celui de la bibliothèque, plus le boîtier
     * USB-DMX MyStrow (USB CDC).
     * ⚠ VID/PID PROVISOIRES : 0x1A86/0x5740 est l'identifiant CDC de WCH
     * (firmware du boîtier, usb_desc.c). À remplacer ICI par l'identifiant
     * définitif avant la série, sinon les boîtiers vendus ne seront pas vus.
     */
    private static UsbSerialProber prober() {
        ProbeTable table = UsbSerialProber.getDefaultProbeTable();
        table.addProduct(0x1A86, 0x5740, CdcAcmSerialDriver.class);
        return new UsbSerialProber(table);
    }

    /**
     * Passive (Open DMX) ou ENTTEC Pro ? Un boîtier USB CDC n'a pas de break
     * à piloter : c'est forcément un Pro. Sur une puce FTDI, les deux existent
     * (l'Opto et l'ENTTEC Pro ont le même 0403:6001) : on demande son numéro de
     * série au boîtier (label 10). Un Pro répond 7E 0A…, un passif ne répond
     * rien. Les 5 octets sortent sans break sur la ligne : ignorés par les
     * projecteurs.
     */
    private static boolean detectPro(UsbSerialPort port, UsbSerialDriver driver) {
        if (driver instanceof CdcAcmSerialDriver) return true;
        if (!(driver instanceof FtdiSerialDriver)) return false;
        try {
            port.setParameters(250000, 8, UsbSerialPort.STOPBITS_1, UsbSerialPort.PARITY_NONE);
            port.write(new byte[] {0x7E, 0x0A, 0x00, 0x00, (byte) 0xE7}, 200);
            byte[] buf = new byte[64];
            boolean som = false;
            long end = System.nanoTime() + 400_000_000L;
            while (System.nanoTime() < end) {
                int n = port.read(buf, 100);
                for (int i = 0; i < n; i++) {
                    if (som && buf[i] == 0x0A) return true;
                    som = buf[i] == 0x7E;
                }
            }
        } catch (Exception ignored) { }
        return false;
    }

    // ── Réseaux (Wi-Fi, Ethernet, node USB) ────────────────────────────────

    private static ConnectivityManager cm(Context ctx) {
        return (ConnectivityManager) ctx.getSystemService(Context.CONNECTIVITY_SERVICE);
    }

    private static boolean isBroadcast(InetAddress a) {
        return a instanceof Inet4Address && (a.getAddress()[0] & 0xFF) == 255;
    }

    /** Réseau dont une adresse IPv4 est dans le même sous-réseau que la cible, sinon null. */
    private static Network subnetNetwork(Context ctx, InetAddress target) {
        ConnectivityManager cm = cm(ctx);
        if (cm == null || !(target instanceof Inet4Address)) return null;
        byte[] t = target.getAddress();
        for (Network n : cm.getAllNetworks()) {
            LinkProperties lp = cm.getLinkProperties(n);
            if (lp == null) continue;
            for (LinkAddress la : lp.getLinkAddresses())
                if (la.getAddress() instanceof Inet4Address
                        && samePrefix(la.getAddress().getAddress(), t, la.getPrefixLength())) return n;
        }
        return null;
    }

    /** Premier réseau dont une adresse IPv4 est dans le même sous-réseau que la cible. */
    private static Network networkFor(Context ctx, InetAddress target) {
        ConnectivityManager cm = cm(ctx);
        if (cm == null || !(target instanceof Inet4Address)) return null;
        byte[] t = target.getAddress();
        boolean broadcast = (t[0] & 0xFF) == 255;
        Network wired = null;
        for (Network n : cm.getAllNetworks()) {
            LinkProperties lp = cm.getLinkProperties(n);
            if (lp == null) continue;
            for (LinkAddress la : lp.getLinkAddresses()) {
                if (!(la.getAddress() instanceof Inet4Address)) continue;
                if (!broadcast && samePrefix(la.getAddress().getAddress(), t, la.getPrefixLength())) return n;
            }
            NetworkCapabilities nc = cm.getNetworkCapabilities(n);
            if (nc != null && nc.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) wired = n;
        }
        // Broadcast, ou cible hors de tout sous-réseau : on préfère le filaire (node USB).
        return wired;
    }

    private static boolean samePrefix(byte[] a, byte[] b, int prefix) {
        for (int i = 0; i < 4; i++) {
            int bits = Math.max(0, Math.min(8, prefix - i * 8));
            int mask = bits == 0 ? 0 : (0xFF << (8 - bits)) & 0xFF;
            if ((a[i] & mask) != (b[i] & mask)) return false;
        }
        return true;
    }

    private static String ifaceName(Context ctx, Network n) {
        LinkProperties lp = cm(ctx).getLinkProperties(n);
        return lp != null && lp.getInterfaceName() != null ? lp.getInterfaceName() : "réseau " + n;
    }

    private static String transportOf(NetworkCapabilities nc) {
        if (nc == null) return "?";
        if (nc.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET)) return "ethernet";
        if (nc.hasTransport(NetworkCapabilities.TRANSPORT_WIFI)) return "wifi";
        if (nc.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR)) return "4g";
        return "autre";
    }

    /** Réseaux vus par Android : { networks: [{ iface, transport, addresses: ["2.0.0.2/24"] }] }. */
    @PluginMethod
    public void networks(PluginCall call) {
        JSArray list = new JSArray();
        ConnectivityManager cm = cm(getContext());
        if (cm != null) {
            for (Network n : cm.getAllNetworks()) {
                LinkProperties lp = cm.getLinkProperties(n);
                if (lp == null) continue;
                JSArray addrs = new JSArray();
                for (LinkAddress la : lp.getLinkAddresses())
                    if (la.getAddress() instanceof Inet4Address) addrs.put(la.getAddress().getHostAddress() + "/" + la.getPrefixLength());
                JSObject o = new JSObject();
                o.put("iface", lp.getInterfaceName());
                o.put("transport", transportOf(cm.getNetworkCapabilities(n)));
                o.put("addresses", addrs);
                list.put(o);
            }
        }
        // Vue noyau : toutes les interfaces, y compris celles qu'Android ne gère
        // pas (ex. un node USB nommé « usb0 », ignoré par le service Ethernet
        // qui ne prend que « eth* ») — c'est ce qui dit POURQUOI un node n'a pas d'IP.
        JSArray ifaces = new JSArray();
        try {
            for (java.net.NetworkInterface ni : java.util.Collections.list(java.net.NetworkInterface.getNetworkInterfaces())) {
                if (ni.isLoopback()) continue;
                JSArray addrs = new JSArray();
                for (java.net.InterfaceAddress ia : ni.getInterfaceAddresses())
                    if (ia.getAddress() instanceof Inet4Address) addrs.put(ia.getAddress().getHostAddress() + "/" + ia.getNetworkPrefixLength());
                JSObject o = new JSObject();
                o.put("name", ni.getName());
                o.put("up", ni.isUp());
                o.put("addresses", addrs);
                ifaces.put(o);
            }
        } catch (Exception ignored) { }
        JSObject r = new JSObject();
        r.put("networks", list);
        r.put("interfaces", ifaces);
        call.resolve(r);
    }

    /**
     * Cherche les nodes Art-Net (ArtPoll en broadcast sur chaque réseau IPv4).
     * { nodes: [{ ip, shortName, longName, iface }] }. Seuls les ArtPollReply
     * (0x2100) comptent : sinon la tablette se trouverait elle-même (cf. BRAD).
     */
    @PluginMethod
    public void artPoll(PluginCall call) {
        final int timeoutMs = call.getInt("timeoutMs", 1500);
        final Context ctx = getContext();
        stopSender();   // le port 6454 et le réseau doivent être libres pendant la recherche
        new Thread(() -> {
            JSArray found = new JSArray();
            List<String> seen = new ArrayList<>();
            ConnectivityManager cm = cm(ctx);
            List<Network> nets = new ArrayList<>();
            if (cm != null) for (Network n : cm.getAllNetworks()) nets.add(n);
            if (nets.isEmpty()) nets.add(null);
            byte[] poll = new byte[14];
            System.arraycopy("Art-Net\0".getBytes(), 0, poll, 0, 8);
            poll[8] = 0x00; poll[9] = 0x20;          // OpCode ArtPoll
            poll[10] = 0x00; poll[11] = 0x0e;        // Protocole 14
            for (Network n : nets) {
                try (DatagramSocket s = new DatagramSocket(null)) {
                    s.setReuseAddress(true);
                    s.setBroadcast(true);
                    s.bind(new InetSocketAddress(6454));   // les nodes répondent sur 6454
                    if (n != null) n.bindSocket(s);
                    s.send(new DatagramPacket(poll, poll.length, InetAddress.getByName("255.255.255.255"), 6454));
                    s.setSoTimeout(200);
                    long end = System.currentTimeMillis() + Math.max(500, timeoutMs / nets.size());
                    byte[] buf = new byte[600];
                    while (System.currentTimeMillis() < end) {
                        DatagramPacket p = new DatagramPacket(buf, buf.length);
                        try { s.receive(p); } catch (SocketTimeoutException e) { continue; }
                        if (p.getLength() < 108 || buf[8] != 0x00 || buf[9] != 0x21) continue;
                        String ip = (buf[10] & 0xFF) + "." + (buf[11] & 0xFF) + "." + (buf[12] & 0xFF) + "." + (buf[13] & 0xFF);
                        if (seen.contains(ip)) continue;
                        seen.add(ip);
                        JSObject o = new JSObject();
                        o.put("ip", ip);
                        o.put("shortName", new String(buf, 26, 18, StandardCharsets.US_ASCII).replace("\0", "").trim());
                        o.put("longName", new String(buf, 44, 64, StandardCharsets.US_ASCII).replace("\0", "").trim());
                        o.put("iface", n != null ? ifaceName(ctx, n) : "?");
                        found.put(o);
                    }
                } catch (Exception ignored) { }
            }
            JSObject r = new JSObject();
            r.put("nodes", found);
            call.resolve(r);
        }, "mystrow-artpoll").start();
    }

    /**
     * Vue noyau des appareils USB (/sys/bus/usb/devices) : dit si un boîtier est
     * détecté électriquement et quel pilote Linux l'a pris (rndis_host,
     * cdc_ether…), même quand Android ne le montre pas. Lecture seule ; la
     * lecture peut être refusée selon la version d'Android.
     */
    private static JSArray kernelUsb() {
        JSArray out = new JSArray();
        java.io.File[] devs = new java.io.File("/sys/bus/usb/devices").listFiles();
        if (devs == null) { out.put("lecture /sys/bus/usb refusée"); return out; }
        for (java.io.File d : devs) {
            String vid = readSys(new java.io.File(d, "idVendor"));
            if (vid == null) {
                // Interface « 1-1:1.0 » : on note le pilote qui l'a prise.
                try {
                    java.io.File drv = new java.io.File(d, "driver").getCanonicalFile();
                    if (new java.io.File(d, "driver").exists()) out.put("  " + d.getName() + " → pilote " + drv.getName());
                } catch (Exception ignored) { }
                continue;
            }
            String pid = readSys(new java.io.File(d, "idProduct"));
            String prod = readSys(new java.io.File(d, "product"));
            String maker = readSys(new java.io.File(d, "manufacturer"));
            out.put(d.getName() + " " + vid + ":" + pid + " " + (maker != null ? maker : "") + " " + (prod != null ? prod : ""));
        }
        return out;
    }

    private static String readSys(java.io.File f) {
        try (java.io.BufferedReader r = new java.io.BufferedReader(new java.io.FileReader(f))) {
            String l = r.readLine();
            return l != null ? l.trim() : null;
        } catch (Exception e) {
            return null;
        }
    }

    private static String describeDevice(UsbDevice d) {
        String product = d.getProductName() != null ? d.getProductName() : "";
        String maker = d.getManufacturerName() != null ? d.getManufacturerName() : "";
        return String.format("%04x:%04x %s %s", d.getVendorId(), d.getProductId(), maker, product).trim();
    }

    // ── API JavaScript ──────────────────────────────────────────────────────

    /** Liste les appareils USB branchés et dit lesquels sont des interfaces série reconnues. */
    @PluginMethod
    public void usbDevices(PluginCall call) {
        UsbManager usb = (UsbManager) getContext().getSystemService(Context.USB_SERVICE);
        JSArray list = new JSArray();
        if (usb != null) {
            for (UsbDevice d : usb.getDeviceList().values()) {
                UsbSerialDriver drv = prober().probeDevice(d);
                JSObject o = new JSObject();
                o.put("name", describeDevice(d));
                o.put("serial", drv != null);
                o.put("driver", drv != null ? drv.getClass().getSimpleName() : null);
                o.put("permission", usb.hasPermission(d));
                list.put(o);
            }
        }
        JSObject r = new JSObject();
        r.put("devices", list);
        r.put("kernel", kernelUsb());
        call.resolve(r);
    }

    /**
     * { transport: "artnet" | "usb", fps, host, port, universe,
     *   protocol: "auto" | "open" | "pro" (USB : type d'interface, auto par défaut) }
     * En USB, demande l'autorisation d'accès à l'interface si besoin.
     */
    @PluginMethod
    public void start(PluginCall call) {
        stopSender();
        String transport = call.getString("transport", "artnet");
        if ("usb".equals(transport)) startUsb(call);
        else startArtNet(call);
    }

    private void startArtNet(PluginCall call) {
        try {
            Output out = new ArtNetOutput(getContext(), call.getString("host", "2.0.0.15"),
                    call.getInt("port", 6454), call.getInt("universe", 0));
            acquireWifiLock();
            launch(out, fps(call, 40));
            JSObject r = new JSObject();
            r.put("output", outputName);
            call.resolve(r);
        } catch (Exception e) {
            call.reject("Adresse du node invalide : " + e.getMessage(), e);
        }
    }

    private void startUsb(PluginCall call) {
        UsbManager usb = (UsbManager) getContext().getSystemService(Context.USB_SERVICE);
        List<UsbSerialDriver> drivers = usb == null ? null : prober().findAllDrivers(usb);
        if (drivers == null || drivers.isEmpty()) {
            call.reject("Aucune interface USB-DMX reconnue n'est branchée");
            return;
        }
        UsbSerialDriver driver = drivers.get(0);
        if (usb.hasPermission(driver.getDevice())) {
            openUsb(call, usb, driver);
            return;
        }
        // Fenêtre système « Autoriser MyStrow à accéder à … ? », réponse par diffusion.
        Context ctx = getContext();
        BroadcastReceiver receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context c, Intent intent) {
                try { ctx.unregisterReceiver(this); } catch (Exception ignored) { }
                if (usb.hasPermission(driver.getDevice())) openUsb(call, usb, driver);
                else call.reject("Accès à l'interface USB refusé");
            }
        };
        ContextCompat.registerReceiver(ctx, receiver, new IntentFilter(ACTION_USB_PERMISSION),
                ContextCompat.RECEIVER_NOT_EXPORTED);
        int flags = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ? PendingIntent.FLAG_MUTABLE : 0;
        Intent intent = new Intent(ACTION_USB_PERMISSION).setPackage(ctx.getPackageName());
        usb.requestPermission(driver.getDevice(), PendingIntent.getBroadcast(ctx, 0, intent, flags));
    }

    private void openUsb(PluginCall call, UsbManager usb, UsbSerialDriver driver) {
        UsbSerialPort port = null;
        try {
            UsbDeviceConnection conn = usb.openDevice(driver.getDevice());
            if (conn == null) throw new Exception("Impossible d'ouvrir l'interface USB");
            port = driver.getPorts().get(0);
            port.open(conn);
            String proto = call.getString("protocol", "auto");
            boolean pro = "pro".equals(proto) || ("auto".equals(proto) && detectPro(port, driver));
            if (pro) launch(new ProOutput(port, driver), Math.min(fps(call, 40), 44));
            // Plafond ~36 tr/s : une trame occupe la ligne 26 ms + le break.
            else launch(new UsbOutput(port, driver), Math.min(fps(call, 30), 36));
            JSObject r = new JSObject();
            r.put("output", outputName);
            call.resolve(r);
        } catch (Exception e) {
            if (port != null) try { port.close(); } catch (Exception ignored) { }
            call.reject("Interface USB : " + e.getMessage(), e);
        }
    }

    private static int fps(PluginCall call, int def) {
        return Math.max(1, Math.min(60, call.getInt("fps", def)));
    }

    private void launch(Output out, int fps) {
        synchronized (lock) {
            sent = errors = lateTicks = maxIntervalNs = sumIntervalNs = intervals = 0;
            lastError = null;
            outputName = out.describe();
        }
        running = true;
        Thread t = new Thread(() -> runLoop(out, fps), "mystrow-dmx");
        sender = t;
        t.start();
    }

    private void runLoop(Output out, int fps) {
        Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_AUDIO);
        final long period = 1_000_000_000L / fps;
        final byte[] frame = new byte[512];
        long next = System.nanoTime();
        long prev = 0;
        try {
            while (running) {
                synchronized (lock) { System.arraycopy(dmx, 0, frame, 0, 512); }
                long now = System.nanoTime();
                try {
                    out.send(frame);
                    synchronized (lock) {
                        sent++;
                        if (prev != 0) {
                            long dt = now - prev;
                            sumIntervalNs += dt;
                            intervals++;
                            if (dt > maxIntervalNs) maxIntervalNs = dt;
                            if (dt > period * 3 / 2) lateTicks++;
                        }
                    }
                } catch (Exception e) {
                    synchronized (lock) { errors++; lastError = e.getMessage(); }
                }
                prev = now;

                // Jamais de nouvelle trame tant que la précédente occupe la ligne.
                next = Math.max(next + period, now + out.busyNs());
                long wait = next - System.nanoTime();
                if (wait < -period) next = System.nanoTime();   // gros retard : on repart, sans rafale de rattrapage
                else if (wait > 0) Thread.sleep(wait / 1_000_000L, (int) (wait % 1_000_000L));
            }
        } catch (InterruptedException ignored) {
        } finally {
            out.close();
        }
    }

    /** Écrit des canaux : { start: 1..512, values: [0..255, …] }. */
    @PluginMethod
    public void setChannels(PluginCall call) {
        int start = call.getInt("start", 1);
        JSArray values = call.getArray("values");
        if (values == null) { call.reject("values manquant"); return; }
        try {
            synchronized (lock) {
                for (int i = 0; i < values.length(); i++) {
                    int ch = start - 1 + i;
                    if (ch < 0 || ch >= 512) break;
                    dmx[ch] = (byte) Math.max(0, Math.min(255, values.getInt(i)));
                }
            }
        } catch (JSONException e) {
            call.reject("values invalide", e);
            return;
        }
        call.resolve();
    }

    @PluginMethod
    public void stats(PluginCall call) {
        JSObject r = new JSObject();
        synchronized (lock) {
            r.put("running", running);
            r.put("output", outputName);
            r.put("sent", sent);
            r.put("errors", errors);
            r.put("lateTicks", lateTicks);
            r.put("avgMs", intervals > 0 ? sumIntervalNs / intervals / 1e6 : 0);
            r.put("maxMs", maxIntervalNs / 1e6);
            r.put("lastError", lastError);
        }
        call.resolve(r);
    }

    @PluginMethod
    public void stop(PluginCall call) {
        stopSender();
        call.resolve();
    }

    private void stopSender() {
        running = false;
        Thread t = sender;
        sender = null;
        if (t != null) {
            t.interrupt();
            try { t.join(500); } catch (InterruptedException ignored) { }
        }
        releaseWifiLock();
    }

    /** Empêche le Wi-Fi de s'endormir entre deux trames (sinon trous de 100 ms et plus). */
    private void acquireWifiLock() {
        if (wifiLock != null) return;
        WifiManager wifi = (WifiManager) getContext().getApplicationContext().getSystemService(Context.WIFI_SERVICE);
        if (wifi == null) return;
        int mode = Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q
                ? WifiManager.WIFI_MODE_FULL_LOW_LATENCY
                : WifiManager.WIFI_MODE_FULL_HIGH_PERF;
        wifiLock = wifi.createWifiLock(mode, "mystrow-dmx");
        wifiLock.setReferenceCounted(false);
        wifiLock.acquire();
    }

    private void releaseWifiLock() {
        if (wifiLock != null && wifiLock.isHeld()) wifiLock.release();
        wifiLock = null;
    }

    @Override
    protected void handleOnDestroy() {
        stopSender();
    }
}
