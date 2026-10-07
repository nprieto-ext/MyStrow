package fr.mystrow.app;

import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.hardware.usb.UsbConstants;
import android.hardware.usb.UsbDevice;
import android.hardware.usb.UsbDeviceConnection;
import android.hardware.usb.UsbEndpoint;
import android.hardware.usb.UsbInterface;
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
 *                  USB NODE branché mais qu'Android n'a pas monté en réseau
 *                  (« usb0 » ignoré, Huawei sans service Ethernet) : l'app le
 *                  pilote elle-même en USB (UsbNetOutput, CDC-NCM ou ECM) ;
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

    // ── Node Art-Net USB piloté par l'app (CDC-NCM / ECM) ───────────────────
    //
    // Le USB NODE est une carte réseau USB. iPadOS, Windows et macOS la montent
    // seuls ; Android souvent non (interface « usb0 » ignorée par le service
    // Ethernet, qui ne prend que « eth* » ; Huawei : pas de service Ethernet du
    // tout). L'API USB Host d'Android laisse en revanche l'app parler au
    // boîtier : on fabrique nous-mêmes les trames Ethernet → IPv4 → UDP →
    // ArtDMX, emballées en NTB16 (NCM) ou brutes (ECM). Lien direct
    // tablette ↔ boîtier : pas de DHCP, on prend une adresse voisine du node.

    /** Interfaces d'une carte réseau USB CDC (NCM ou ECM). */
    private static final class UsbNetIfaces {
        UsbInterface control, data;
        UsbEndpoint out, in;
        boolean ncm;
    }

    private static final int CDC_SUBCLASS_ECM = 0x06, CDC_SUBCLASS_NCM = 0x0D;

    private static UsbNetIfaces findUsbNet(UsbDevice d) {
        UsbNetIfaces r = new UsbNetIfaces();
        for (int i = 0; i < d.getInterfaceCount() && r.control == null; i++) {
            UsbInterface f = d.getInterface(i);
            if (f.getInterfaceClass() == UsbConstants.USB_CLASS_COMM
                    && (f.getInterfaceSubclass() == CDC_SUBCLASS_NCM || f.getInterfaceSubclass() == CDC_SUBCLASS_ECM)) {
                r.control = f;
                r.ncm = f.getInterfaceSubclass() == CDC_SUBCLASS_NCM;
            }
        }
        if (r.control == null) return null;
        // L'interface de données a deux réglages : 0 sans points d'accès (repos),
        // 1 avec les deux points bulk (actif). Android les liste séparément.
        for (int i = 0; i < d.getInterfaceCount(); i++) {
            UsbInterface f = d.getInterface(i);
            if (f.getInterfaceClass() != UsbConstants.USB_CLASS_CDC_DATA) continue;
            UsbEndpoint o = null, in = null;
            for (int e = 0; e < f.getEndpointCount(); e++) {
                UsbEndpoint ep = f.getEndpoint(e);
                if (ep.getType() != UsbConstants.USB_ENDPOINT_XFER_BULK) continue;
                if (ep.getDirection() == UsbConstants.USB_DIR_OUT) o = ep; else in = ep;
            }
            if (o != null && in != null) { r.data = f; r.out = o; r.in = in; return r; }
        }
        return null;
    }

    private static UsbDevice findUsbNetDevice(UsbManager usb) {
        if (usb == null) return null;
        for (UsbDevice d : usb.getDeviceList().values()) if (findUsbNet(d) != null) return d;
        return null;
    }

    private static void le16(byte[] b, int off, int v) { b[off] = (byte) v; b[off + 1] = (byte) (v >> 8); }
    private static void be16(byte[] b, int off, int v) { b[off] = (byte) (v >> 8); b[off + 1] = (byte) v; }
    private static int rd16(byte[] b, int off) { return (b[off] & 0xFF) | (b[off + 1] & 0xFF) << 8; }
    private static int rd32(byte[] b, int off) { return rd16(b, off) | rd16(b, off + 2) << 16; }

    private static final class UsbNetOutput implements Output {
        private static final byte[] BCAST = {-1, -1, -1, -1, -1, -1};
        private final UsbDeviceConnection conn;
        private final UsbNetIfaces ifs;
        // Adresse matérielle « locale » (bit 0x02) : 02 M S T R W.
        private final byte[] srcMac = {0x02, 0x4D, 0x53, 0x54, 0x52, 0x57};
        private byte[] dstMac = BCAST;
        private final byte[] srcIp, dstIp;
        private final int port;
        private final byte[] artnet = new byte[18 + 512];
        private final byte[] frame = new byte[14 + 20 + 8 + 18 + 512];
        private final byte[] block = new byte[512 + 14 + 20 + 8 + 18 + 512];
        private int seq, ntbSeq, ipId;
        // Paramètres NTB (GET_NTB_PARAMETERS), valeurs par défaut de la norme sinon.
        private int ndpAlign = 4, outDivisor = 4, outRemainder = 0, inMax = 2048;
        private final String name;

        UsbNetOutput(UsbDeviceConnection conn, UsbDevice dev, UsbNetIfaces ifs, String host, int port, int universe) throws Exception {
            this.conn = conn;
            this.ifs = ifs;
            this.port = port;
            InetAddress t = InetAddress.getByName(host);
            if (!(t instanceof Inet4Address)) throw new Exception("adresse IPv4 attendue : " + host);
            dstIp = t.getAddress();
            srcIp = dstIp.clone();
            srcIp[3] = (byte) ((dstIp[3] & 0xFF) == 2 ? 3 : 2);
            // force = true : détache le pilote du noyau (cdc_ncm) s'il les tenait.
            if (!conn.claimInterface(ifs.control, true)) throw new Exception("interface de contrôle occupée");
            if (!conn.claimInterface(ifs.data, true)) throw new Exception("interface de données occupée");
            if (!conn.setInterface(ifs.data)) throw new Exception("activation de l'interface de données refusée");
            int ctl = ifs.control.getId();
            if (ifs.ncm) {
                byte[] p = new byte[28];
                if (conn.controlTransfer(0xA1, 0x80, 0, ctl, p, p.length, 300) >= 28) {   // GET_NTB_PARAMETERS
                    inMax = Math.max(2048, Math.min(16384, rd32(p, 4)));
                    outDivisor = Math.max(1, Math.min(64, rd16(p, 20)));
                    outRemainder = rd16(p, 22) % outDivisor;
                    ndpAlign = Math.max(4, Math.min(64, rd16(p, 24)));
                }
            }
            // SET_ETHERNET_PACKET_FILTER : directed + broadcast + all multicast (pour lire la réponse ARP).
            conn.controlTransfer(0x21, 0x43, 0x0E, ctl, null, 0, 300);

            System.arraycopy("Art-Net\0".getBytes(), 0, artnet, 0, 8);
            artnet[8] = 0x00; artnet[9] = 0x50;            // OpCode ArtDMX
            artnet[10] = 0x00; artnet[11] = 0x0e;          // Protocole 14
            artnet[14] = (byte) (universe & 0xFF);
            artnet[15] = (byte) ((universe >> 8) & 0x7F);
            artnet[16] = 0x02; artnet[17] = 0x00;          // Longueur 512

            boolean arpOk = resolveMac();
            name = "USB NODE " + host + ":" + port + " (pilote MyStrow " + (ifs.ncm ? "NCM" : "ECM")
                    + (arpOk ? "" : ", sans réponse ARP : diffusion Ethernet") + ") " + describeDevice(dev);
        }

        private int ethHeader(byte[] f, byte[] dst, int type) {
            System.arraycopy(dst, 0, f, 0, 6);
            System.arraycopy(srcMac, 0, f, 6, 6);
            be16(f, 12, type);
            return 14;
        }

        /** Emballe et envoie une trame Ethernet (complétée à 60 octets, le minimum Ethernet). */
        private void transmit(byte[] f, int len) throws Exception {
            if (len < 60) { java.util.Arrays.fill(f, len, 60, (byte) 0); len = 60; }
            int total;
            if (!ifs.ncm) {
                System.arraycopy(f, 0, block, 0, len);
                total = len;
            } else {
                // NTB16 : en-tête NTH16 (12) + NDP16 (16, une entrée + fin) + datagramme aligné.
                int ndp = (12 + ndpAlign - 1) / ndpAlign * ndpAlign;
                int dg = ndp + 16;
                while (dg % outDivisor != outRemainder) dg++;
                total = dg + len;
                // Longueur multiple du paquet USB : il faudrait un paquet nul, qu'Android
                // n'envoie pas → un octet de bourrage, compté dans le bloc.
                if (total % ifs.out.getMaxPacketSize() == 0) total++;
                java.util.Arrays.fill(block, 0, dg, (byte) 0);
                block[0] = 'N'; block[1] = 'C'; block[2] = 'M'; block[3] = 'H';
                le16(block, 4, 12);
                le16(block, 6, ntbSeq++ & 0xFFFF);
                le16(block, 8, total);
                le16(block, 10, ndp);
                block[ndp] = 'N'; block[ndp + 1] = 'C'; block[ndp + 2] = 'M'; block[ndp + 3] = '0';
                le16(block, ndp + 4, 16);
                le16(block, ndp + 6, 0);
                le16(block, ndp + 8, dg);
                le16(block, ndp + 10, len);
                System.arraycopy(f, 0, block, dg, len);
                if (total > dg + len) block[dg + len] = 0;
            }
            if (conn.bulkTransfer(ifs.out, block, total, 200) < 0)
                throw new Exception("envoi USB refusé (USB NODE débranché ?)");
        }

        /** ARP : adresse matérielle du node. Sans réponse, diffusion Ethernet, que le node accepte aussi. */
        private boolean resolveMac() {
            byte[] f = new byte[60];
            int o = ethHeader(f, BCAST, 0x0806);
            be16(f, o, 1); be16(f, o + 2, 0x0800); f[o + 4] = 6; f[o + 5] = 4; be16(f, o + 6, 1);
            System.arraycopy(srcMac, 0, f, o + 8, 6);
            System.arraycopy(srcIp, 0, f, o + 14, 4);
            System.arraycopy(dstIp, 0, f, o + 24, 4);
            byte[] in = new byte[inMax];
            for (int attempt = 0; attempt < 3; attempt++) {
                try { transmit(f, 42); } catch (Exception e) { return false; }
                long end = System.currentTimeMillis() + 300;
                while (System.currentTimeMillis() < end) {
                    int n = conn.bulkTransfer(ifs.in, in, in.length, 100);
                    if (n <= 0) continue;
                    if (!ifs.ncm) { if (arpReply(in, 0, n)) return true; continue; }
                    if (n < 12 || in[0] != 'N' || in[1] != 'C' || in[2] != 'M' || in[3] != 'H') continue;
                    int ndp = rd16(in, 10);
                    if (ndp + 16 > n || in[ndp] != 'N' || in[ndp + 1] != 'C' || in[ndp + 2] != 'M') continue;
                    for (int e = ndp + 8; e + 4 <= n; e += 4) {
                        int off = rd16(in, e), len = rd16(in, e + 2);
                        if (off == 0 || len == 0) break;
                        if (off + len <= n && arpReply(in, off, len)) return true;
                    }
                }
            }
            return false;
        }

        private boolean arpReply(byte[] b, int off, int len) {
            if (len < 42 || (b[off + 12] & 0xFF) != 0x08 || b[off + 13] != 0x06) return false;
            int a = off + 14;
            if (b[a + 6] != 0 || b[a + 7] != 2) return false;                         // réponse ARP
            for (int i = 0; i < 4; i++) if (b[a + 14 + i] != dstIp[i]) return false;  // venant du node
            dstMac = java.util.Arrays.copyOfRange(b, a + 8, a + 14);
            return true;
        }

        @Override public void send(byte[] dmx512) throws Exception {
            seq = seq % 255 + 1;
            artnet[12] = (byte) seq;
            System.arraycopy(dmx512, 0, artnet, 18, 512);
            int o = ethHeader(frame, dstMac, 0x0800);
            frame[o] = 0x45; frame[o + 1] = 0;
            be16(frame, o + 2, 20 + 8 + artnet.length);
            be16(frame, o + 4, ipId++ & 0xFFFF);
            be16(frame, o + 6, 0);
            frame[o + 8] = 64; frame[o + 9] = 17;                                       // TTL, UDP
            be16(frame, o + 10, 0);
            System.arraycopy(srcIp, 0, frame, o + 12, 4);
            System.arraycopy(dstIp, 0, frame, o + 16, 4);
            int sum = 0;
            for (int i = 0; i < 20; i += 2) sum += ((frame[o + i] & 0xFF) << 8) | (frame[o + i + 1] & 0xFF);
            while ((sum >> 16) != 0) sum = (sum & 0xFFFF) + (sum >> 16);
            be16(frame, o + 10, ~sum & 0xFFFF);
            int u = o + 20;
            be16(frame, u, 6454);
            be16(frame, u + 2, port);
            be16(frame, u + 4, 8 + artnet.length);
            be16(frame, u + 6, 0);                                                      // somme UDP facultative en IPv4
            System.arraycopy(artnet, 0, frame, u + 8, artnet.length);
            transmit(frame, u + 8 + artnet.length);
        }
        @Override public long busyNs() { return 0; }
        @Override public void close() {
            try { conn.releaseInterface(ifs.data); conn.releaseInterface(ifs.control); } catch (Exception ignored) { }
            conn.close();
        }
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
                UsbNetIfaces net = findUsbNet(d);
                o.put("net", net == null ? null : (net.ncm ? "NCM" : "ECM"));
                // Interfaces (classe/sous-classe/protocole, points d'accès) : dit ce
                // qu'est un boîtier inconnu.
                StringBuilder sb = new StringBuilder();
                for (int i = 0; i < d.getInterfaceCount(); i++) {
                    UsbInterface f = d.getInterface(i);
                    sb.append(String.format("if%d.%d %02x/%02x/%02x", f.getId(), f.getAlternateSetting(),
                            f.getInterfaceClass(), f.getInterfaceSubclass(), f.getInterfaceProtocol()));
                    for (int e = 0; e < f.getEndpointCount(); e++) {
                        UsbEndpoint ep = f.getEndpoint(e);
                        sb.append(String.format(" ep%02x/t%d/%d", ep.getAddress(), ep.getType(), ep.getMaxPacketSize()));
                    }
                    sb.append("; ");
                }
                o.put("interfaces", sb.toString());
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
        // USB NODE qu'Android n'a pas monté en réseau : aucune interface Android
        // dans le sous-réseau du node, mais une carte réseau USB est branchée →
        // l'app la pilote elle-même.
        try {
            String host = call.getString("host", "2.0.0.15");
            InetAddress t = InetAddress.getByName(host);
            UsbManager usb = (UsbManager) getContext().getSystemService(Context.USB_SERVICE);
            UsbDevice dev = findUsbNetDevice(usb);
            if (dev != null && !isBroadcast(t) && subnetNetwork(getContext(), t) == null) {
                int port = call.getInt("port", 6454), universe = call.getInt("universe", 0);
                // Hors du fil principal : la recherche ARP peut prendre ~1 s.
                withUsbPermission(call, usb, dev, () -> new Thread(
                        () -> openUsbNet(call, usb, dev, host, port, universe), "mystrow-usbnet").start());
                return;
            }
        } catch (Exception ignored) { }
        try {
            Context ctx = getContext();
            String host = call.getString("host", "2.0.0.15");
            int port = call.getInt("port", 6454), universe = call.getInt("universe", 0);
            Output out = new ArtNetOutput(ctx, host, port, universe);
            acquireWifiLock();
            // Reprise : réseau changé ou revenu (socket rattachée au bon réseau).
            launch(out, fps(call, 40), () -> new ArtNetOutput(ctx, host, port, universe));
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
        withUsbPermission(call, usb, driver.getDevice(), () -> openUsb(call, usb, driver));
    }

    private void openUsbNet(PluginCall call, UsbManager usb, UsbDevice dev, String host, int port, int universe) {
        try {
            launch(newUsbNet(usb, dev, host, port, universe), fps(call, 40), () -> {
                // Reprise : le boîtier rebranché est un NOUVEL appareil pour Android.
                UsbDevice d = findUsbNetDevice(usb);
                if (d == null) throw new Exception("USB NODE débranché");
                return newUsbNet(usb, d, host, port, universe);
            });
            JSObject r = new JSObject();
            r.put("output", outputName);
            call.resolve(r);
        } catch (Exception e) {
            call.reject("USB NODE : " + e.getMessage(), e);
        }
    }

    private Output newUsbNet(UsbManager usb, UsbDevice dev, String host, int port, int universe) throws Exception {
        if (!usbAccess(usb, dev)) throw new Exception("autorisation USB demandée, touchez OK");
        UsbDeviceConnection conn = usb.openDevice(dev);
        if (conn == null) throw new Exception("impossible d'ouvrir le USB NODE");
        try {
            return new UsbNetOutput(conn, dev, findUsbNet(dev), host, port, universe);
        } catch (Exception e) {
            conn.close();
            throw e;
        }
    }

    /**
     * Accès déjà donné ? Sinon, demande-le (fenêtre système) UNE fois par
     * branchement, sans attendre : la reprise retentera chaque seconde.
     * Android oublie l'autorisation quand on débranche le boîtier.
     */
    private String permissionAskedFor;
    private boolean usbAccess(UsbManager usb, UsbDevice dev) {
        if (usb.hasPermission(dev)) return true;
        if (!dev.getDeviceName().equals(permissionAskedFor)) {
            permissionAskedFor = dev.getDeviceName();
            Context ctx = getContext();
            int flags = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ? PendingIntent.FLAG_MUTABLE : 0;
            Intent intent = new Intent(ACTION_USB_PERMISSION).setPackage(ctx.getPackageName());
            usb.requestPermission(dev, PendingIntent.getBroadcast(ctx, 0, intent, flags));
        }
        return false;
    }

    /** Lance onGranted tout de suite si l'accès est déjà donné, sinon après la fenêtre système. */
    private void withUsbPermission(PluginCall call, UsbManager usb, UsbDevice dev, Runnable onGranted) {
        if (usb.hasPermission(dev)) { onGranted.run(); return; }
        // Fenêtre système « Autoriser MyStrow à accéder à … ? », réponse par diffusion.
        Context ctx = getContext();
        BroadcastReceiver receiver = new BroadcastReceiver() {
            @Override public void onReceive(Context c, Intent intent) {
                try { ctx.unregisterReceiver(this); } catch (Exception ignored) { }
                if (usb.hasPermission(dev)) onGranted.run();
                else call.reject("Accès à l'interface USB refusé");
            }
        };
        ContextCompat.registerReceiver(ctx, receiver, new IntentFilter(ACTION_USB_PERMISSION),
                ContextCompat.RECEIVER_NOT_EXPORTED);
        int flags = Build.VERSION.SDK_INT >= Build.VERSION_CODES.S ? PendingIntent.FLAG_MUTABLE : 0;
        Intent intent = new Intent(ACTION_USB_PERMISSION).setPackage(ctx.getPackageName());
        usb.requestPermission(dev, PendingIntent.getBroadcast(ctx, 0, intent, flags));
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
            // Reprise : même type d'interface, sur le boîtier rebranché.
            Reopener reopen = () -> reopenSerial(usb, pro);
            if (pro) launch(new ProOutput(port, driver), Math.min(fps(call, 40), 44), reopen);
            // Plafond ~36 tr/s : une trame occupe la ligne 26 ms + le break.
            else launch(new UsbOutput(port, driver), Math.min(fps(call, 30), 36), reopen);
            JSObject r = new JSObject();
            r.put("output", outputName);
            call.resolve(r);
        } catch (Exception e) {
            if (port != null) try { port.close(); } catch (Exception ignored) { }
            call.reject("Interface USB : " + e.getMessage(), e);
        }
    }

    private Output reopenSerial(UsbManager usb, boolean pro) throws Exception {
        List<UsbSerialDriver> drivers = prober().findAllDrivers(usb);
        if (drivers.isEmpty()) throw new Exception("interface USB débranchée");
        UsbSerialDriver driver = drivers.get(0);
        if (!usbAccess(usb, driver.getDevice())) throw new Exception("autorisation USB demandée, touchez OK");
        UsbDeviceConnection conn = usb.openDevice(driver.getDevice());
        if (conn == null) throw new Exception("impossible d'ouvrir l'interface USB");
        UsbSerialPort port = driver.getPorts().get(0);
        try {
            port.open(conn);
            return pro ? new ProOutput(port, driver) : new UsbOutput(port, driver);
        } catch (Exception e) {
            try { port.close(); } catch (Exception ignored) { }
            throw e;
        }
    }

    private static int fps(PluginCall call, int def) {
        return Math.max(1, Math.min(60, call.getInt("fps", def)));
    }

    /** Recrée la sortie (boîtier rebranché, réseau revenu). Exception = pas encore possible. */
    private interface Reopener {
        Output open() throws Exception;
    }

    private void launch(Output out, int fps, Reopener reopen) {
        synchronized (lock) {
            sent = errors = lateTicks = maxIntervalNs = sumIntervalNs = intervals = 0;
            lastError = null;
            outputName = out.describe();
        }
        running = true;
        Thread t = new Thread(() -> runLoop(out, fps, reopen), "mystrow-dmx");
        sender = t;
        t.start();
    }

    private void runLoop(Output first, int fps, Reopener reopen) {
        Process.setThreadPriority(Process.THREAD_PRIORITY_URGENT_AUDIO);
        final long period = 1_000_000_000L / fps;
        final byte[] frame = new byte[512];
        Output out = first;
        long next = System.nanoTime();
        long prev = 0;
        int failures = 0;
        try {
            while (running) {
                // Une seconde d'échecs (boîtier débranché…) : on retente d'ouvrir la
                // sortie, une fois par seconde, sans qu'il faille refaire « Démarrer ».
                if (failures >= fps && reopen != null) {
                    failures = 0;
                    try {
                        Output fresh = reopen.open();
                        out.close();
                        out = fresh;
                        synchronized (lock) { outputName = fresh.describe(); }
                    } catch (Exception e) {
                        synchronized (lock) { lastError = "En attente du boîtier : " + e.getMessage(); }
                    }
                }
                synchronized (lock) { System.arraycopy(dmx, 0, frame, 0, 512); }
                long now = System.nanoTime();
                try {
                    out.send(frame);
                    failures = 0;
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
                    failures++;
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
