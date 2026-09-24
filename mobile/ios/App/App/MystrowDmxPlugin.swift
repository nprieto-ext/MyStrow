import Foundation
import Darwin
import Capacitor

/// Sortie DMX du mode autonome (sans PC) sur iPhone / iPad : Art-Net en UDP.
/// Équivalent iOS de MystrowDmxPlugin.java, mêmes méthodes et mêmes réponses,
/// pour que standalone.js, patch.html et dmxtest.html n'aient rien à savoir de
/// la plateforme.
///
/// - Pas d'USB-DMX : iOS n'ouvre pas les interfaces série USB (Opto, ENTTEC,
///   boîtier MyStrow). `start({ transport: "usb" })` est refusé avec un message.
/// - Un node dans le réseau de l'appareil (Wi-Fi, ou carte réseau USB comme le
///   « USB NODE » ElectroConcept sur iPad) reçoit ses trames en direct : la
///   socket est liée à CETTE interface (IP_BOUND_IF), sinon iOS enverrait tout
///   par le Wi-Fi.
/// - Node hors de tout réseau de l'appareil (node en 2.0.0.15 branché sur une
///   box en 192.168.1.x) : envoi en diffusion, comme sur Android.
///   ⚠ Depuis iOS 14, la diffusion (et l'ArtPoll) exige l'autorisation Apple
///   « com.apple.developer.networking.multicast », à demander sur
///   developer.apple.com puis à ajouter aux entitlements. Sans elle, sendto()
///   échoue : l'erreur est remontée telle quelle, avec l'explication.
///
/// La cadence ne dépend pas du JavaScript : un thread natif réémet la dernière
/// trame à fréquence fixe, comme sur Android et sur le PC.
@objc(MystrowDmxPlugin)
public class MystrowDmxPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MystrowDmxPlugin"
    public let jsName = "MystrowDmx"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "setChannels", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stats", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "networks", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "artPoll", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "usbDevices", returnType: CAPPluginReturnPromise)
    ]

    private static let broadcastHint =
        "iOS refuse la diffusion sans l'autorisation « multicast » d'Apple : "
        + "donnez au node une adresse du réseau de l'appareil, ou demandez l'autorisation."

    // État partagé avec le thread d'envoi (protégé par `lock`).
    private let lock = NSLock()
    private var dmx = [UInt8](repeating: 0, count: 512)
    private var running = false
    private var generation = 0
    private var sent = 0, errors = 0, lateTicks = 0, intervals = 0
    private var maxIntervalNs: UInt64 = 0, sumIntervalNs: UInt64 = 0
    private var lastError = ""
    private var outputName = ""

    // MARK: - Réseaux

    struct Iface {
        let name: String
        let addr: UInt32      // ordre de l'hôte
        let mask: UInt32
        let up: Bool
        var prefix: Int { mask.nonzeroBitCount }
        var text: String { MystrowDmxPlugin.ipText(addr) + "/" + String(prefix) }
    }

    static func ipText(_ a: UInt32) -> String {
        return "\(a >> 24).\((a >> 16) & 255).\((a >> 8) & 255).\(a & 255)"
    }

    /// Interfaces IPv4 de l'appareil (getifaddrs), sans la boucle locale.
    static func ipv4Interfaces() -> [Iface] {
        var list: [Iface] = []
        var ifap: UnsafeMutablePointer<ifaddrs>? = nil
        guard getifaddrs(&ifap) == 0 else { return list }
        defer { freeifaddrs(ifap) }
        var cursor = ifap
        while let cur = cursor {
            let ifa = cur.pointee
            if let sa = ifa.ifa_addr, sa.pointee.sa_family == UInt8(AF_INET) {
                let addr = sa.withMemoryRebound(to: sockaddr_in.self, capacity: 1) {
                    UInt32(bigEndian: $0.pointee.sin_addr.s_addr)
                }
                var mask: UInt32 = 0
                if let nm = ifa.ifa_netmask {
                    mask = nm.withMemoryRebound(to: sockaddr_in.self, capacity: 1) {
                        UInt32(bigEndian: $0.pointee.sin_addr.s_addr)
                    }
                }
                let name = String(cString: ifa.ifa_name)
                let up = (ifa.ifa_flags & UInt32(IFF_UP)) != 0
                if name != "lo0" {
                    list.append(Iface(name: name, addr: addr, mask: mask, up: up))
                }
            }
            cursor = ifa.ifa_next
        }
        return list
    }

    static func transportOf(_ name: String) -> String {
        if name == "en0" { return "wifi" }
        if name.hasPrefix("pdp_ip") { return "4g" }
        if name.hasPrefix("en") { return "ethernet" }   // adaptateur / node USB sur iPad
        return "autre"
    }

    static func parseIPv4(_ host: String) -> UInt32? {
        var a = in_addr()
        guard inet_pton(AF_INET, host, &a) == 1 else { return nil }
        return UInt32(bigEndian: a.s_addr)
    }

    static func sockaddrFor(_ ip: UInt32, port: Int) -> sockaddr_in {
        var sa = sockaddr_in()
        sa.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        sa.sin_family = sa_family_t(AF_INET)
        sa.sin_port = in_port_t(UInt16(truncatingIfNeeded: port).bigEndian)
        sa.sin_addr = in_addr(s_addr: ip.bigEndian)
        return sa
    }

    static func bindToInterface(_ fd: Int32, _ name: String) {
        var idx = if_nametoindex(name)
        if idx != 0 {
            _ = setsockopt(fd, IPPROTO_IP, IP_BOUND_IF, &idx, socklen_t(MemoryLayout<UInt32>.size))
        }
    }

    static func errnoText() -> String {
        return String(cString: strerror(errno))
    }

    // MARK: - Sortie Art-Net

    enum DmxError: Error { case message(String) }

    final class ArtNetOutput {
        let fd: Int32
        let dest: sockaddr_in
        let broadcast: Bool
        let name: String
        var packet = [UInt8](repeating: 0, count: 18 + 512)
        var seq: UInt8 = 0

        init(host: String, port: Int, universe: Int) throws {
            guard let target = MystrowDmxPlugin.parseIPv4(host) else {
                throw DmxError.message("Adresse du node invalide : " + host)
            }
            let ifaces = MystrowDmxPlugin.ipv4Interfaces().filter { $0.up }
            var iface = ifaces.first { $0.mask != 0 && ($0.addr & $0.mask) == (target & $0.mask) }
            var ip = target
            var how = ""
            var bcast = (target >> 24) == 255
            if iface == nil && !bcast {
                // Node hors de tout réseau de l'appareil : seule la diffusion l'atteint.
                ip = 0xFFFF_FFFF
                bcast = true
                how = " (diffusion : node hors du réseau de l'appareil)"
                iface = ifaces.first { $0.name == "en0" }
            }
            let s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
            guard s >= 0 else { throw DmxError.message("Socket impossible : " + MystrowDmxPlugin.errnoText()) }
            var on: Int32 = 1
            _ = setsockopt(s, SOL_SOCKET, SO_BROADCAST, &on, socklen_t(MemoryLayout<Int32>.size))
            if let i = iface { MystrowDmxPlugin.bindToInterface(s, i.name) }
            fd = s
            dest = MystrowDmxPlugin.sockaddrFor(ip, port: port)
            broadcast = bcast
            name = "Art-Net " + host + ":" + String(port) + how + " via " + (iface?.name ?? "réseau par défaut")
            // En-tête ArtDMX : mêmes octets que artnet_dmx._build_artnet_packet.
            let id: [UInt8] = Array("Art-Net".utf8) + [0]
            packet.replaceSubrange(0..<8, with: id)
            packet[8] = 0x00; packet[9] = 0x50                       // OpCode ArtDMX
            packet[10] = 0x00; packet[11] = 0x0e                     // protocole 14
            packet[14] = UInt8(universe & 0xFF)                      // SubUni
            packet[15] = UInt8((universe >> 8) & 0x7F)               // Net
            packet[16] = 0x02; packet[17] = 0x00                     // longueur 512
        }

        func send(_ frame: [UInt8]) throws {
            seq = seq % 255 + 1                                      // 1..255 (0 = séquence désactivée)
            packet[12] = seq
            packet.replaceSubrange(18..<(18 + 512), with: frame)
            var to = dest
            let n = packet.withUnsafeBytes { buf -> Int in
                withUnsafePointer(to: &to) { p in
                    p.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                        sendto(fd, buf.baseAddress, buf.count, 0, sa, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
            }
            if n < 0 {
                let e = MystrowDmxPlugin.errnoText()
                throw DmxError.message(broadcast ? e + ". " + MystrowDmxPlugin.broadcastHint : e)
            }
        }

        func close() { Darwin.close(fd) }
    }

    // MARK: - API JavaScript

    /// { transport: "artnet" | "usb", fps, host, port, universe }
    @objc func start(_ call: CAPPluginCall) {
        stopSender()
        if (call.getString("transport") ?? "artnet") == "usb" {
            call.reject("L'USB-DMX n'est pas possible sur iPhone / iPad : utilisez un node Art-Net.")
            return
        }
        do {
            let out = try ArtNetOutput(host: call.getString("host") ?? "2.0.0.15",
                                       port: call.getInt("port") ?? 6454,
                                       universe: call.getInt("universe") ?? 0)
            // Premier envoi tout de suite : une diffusion refusée par iOS se voit ici.
            lock.lock(); let first = dmx; lock.unlock()
            do { try out.send(first) } catch DmxError.message(let m) {
                out.close()
                call.reject("Sortie Art-Net : " + m)
                return
            }
            launch(out, fps: max(1, min(60, call.getInt("fps") ?? 40)))
            call.resolve(["output": outputName])
        } catch DmxError.message(let m) {
            call.reject(m)
        } catch {
            call.reject("Sortie Art-Net : " + error.localizedDescription)
        }
    }

    private func launch(_ out: ArtNetOutput, fps: Int) {
        lock.lock()
        sent = 0; errors = 0; lateTicks = 0; intervals = 0
        maxIntervalNs = 0; sumIntervalNs = 0; lastError = ""
        outputName = out.name
        running = true
        generation += 1
        let gen = generation
        lock.unlock()
        let t = Thread { [weak self] in self?.runLoop(out, fps: fps, gen: gen) }
        t.qualityOfService = .userInteractive
        t.name = "mystrow-dmx"
        t.start()
    }

    private func stillRunning(_ gen: Int) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return running && generation == gen
    }

    private func runLoop(_ out: ArtNetOutput, fps: Int, gen: Int) {
        let period = UInt64(1_000_000_000 / fps)
        var next = DispatchTime.now().uptimeNanoseconds
        var prev: UInt64 = 0
        while stillRunning(gen) {
            lock.lock(); let frame = dmx; lock.unlock()
            let now = DispatchTime.now().uptimeNanoseconds
            do {
                try out.send(frame)
                lock.lock()
                sent += 1
                if prev != 0 {
                    let dt = now - prev
                    sumIntervalNs += dt
                    intervals += 1
                    if dt > maxIntervalNs { maxIntervalNs = dt }
                    if dt > period * 3 / 2 { lateTicks += 1 }
                }
                lock.unlock()
            } catch DmxError.message(let m) {
                lock.lock(); errors += 1; lastError = m; lock.unlock()
            } catch {
                lock.lock(); errors += 1; lastError = error.localizedDescription; lock.unlock()
            }
            prev = now
            next += period
            let after = DispatchTime.now().uptimeNanoseconds
            if after > next + period {
                next = after                     // gros retard : on repart, sans rafale de rattrapage
            } else if next > after {
                usleep(useconds_t((next - after) / 1_000))
            }
        }
        out.close()
    }

    private func stopSender() {
        lock.lock()
        running = false
        generation += 1
        lock.unlock()
    }

    /// Écrit des canaux : { start: 1..512, values: [0..255, …] }.
    @objc func setChannels(_ call: CAPPluginCall) {
        let start = call.getInt("start") ?? 1
        guard let values = call.getArray("values") else {
            call.reject("values manquant")
            return
        }
        lock.lock()
        for (i, v) in values.enumerated() {
            let ch = start - 1 + i
            if ch < 0 || ch >= 512 { break }
            let n = (v as? NSNumber)?.intValue ?? 0
            dmx[ch] = UInt8(max(0, min(255, n)))
        }
        lock.unlock()
        call.resolve()
    }

    @objc func stats(_ call: CAPPluginCall) {
        lock.lock()
        let r: [String: Any] = [
            "running": running,
            "output": outputName,
            "sent": sent,
            "errors": errors,
            "lateTicks": lateTicks,
            "avgMs": intervals > 0 ? Double(sumIntervalNs) / Double(intervals) / 1e6 : 0.0,
            "maxMs": Double(maxIntervalNs) / 1e6,
            "lastError": lastError
        ]
        lock.unlock()
        call.resolve(r)
    }

    @objc func stop(_ call: CAPPluginCall) {
        stopSender()
        call.resolve()
    }

    /// Réseaux vus par l'appareil : { networks: [{ iface, transport, addresses }], interfaces: [...] }.
    @objc func networks(_ call: CAPPluginCall) {
        let all = MystrowDmxPlugin.ipv4Interfaces()
        var networks: [[String: Any]] = []
        var interfaces: [[String: Any]] = []
        var names: [String] = []
        for i in all where !names.contains(i.name) { names.append(i.name) }
        for name in names {
            let mine = all.filter { $0.name == name }
            let addrs = mine.map { $0.text }
            let up = mine.contains { $0.up }
            interfaces.append(["name": name, "up": up, "addresses": addrs])
            if up && !addrs.isEmpty {
                networks.append(["iface": name, "transport": MystrowDmxPlugin.transportOf(name), "addresses": addrs])
            }
        }
        call.resolve(["networks": networks, "interfaces": interfaces])
    }

    /// Cherche les nodes Art-Net (ArtPoll en diffusion). Seuls les ArtPollReply
    /// (0x2100) comptent, sinon l'appareil se trouverait lui-même.
    /// { nodes: [{ ip, shortName, longName, iface }], error? }
    @objc func artPoll(_ call: CAPPluginCall) {
        let timeoutMs = call.getInt("timeoutMs") ?? 1500
        stopSender()   // le port 6454 doit être libre pendant la recherche
        DispatchQueue.global(qos: .userInitiated).async {
            var nodes: [[String: Any]] = []
            var seen: [String] = []
            var error = ""
            let s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP)
            if s < 0 {
                call.resolve(["nodes": nodes, "error": "Socket impossible : " + MystrowDmxPlugin.errnoText()])
                return
            }
            defer { Darwin.close(s) }
            var on: Int32 = 1
            _ = setsockopt(s, SOL_SOCKET, SO_REUSEADDR, &on, socklen_t(MemoryLayout<Int32>.size))
            _ = setsockopt(s, SOL_SOCKET, SO_REUSEPORT, &on, socklen_t(MemoryLayout<Int32>.size))
            _ = setsockopt(s, SOL_SOCKET, SO_BROADCAST, &on, socklen_t(MemoryLayout<Int32>.size))
            var tv = timeval(tv_sec: 0, tv_usec: 200_000)
            _ = setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, socklen_t(MemoryLayout<timeval>.size))
            var local = MystrowDmxPlugin.sockaddrFor(0, port: 6454)   // les nodes répondent sur 6454
            _ = withUnsafePointer(to: &local) { p in
                p.withMemoryRebound(to: sockaddr.self, capacity: 1) { bind(s, $0, socklen_t(MemoryLayout<sockaddr_in>.size)) }
            }
            let poll: [UInt8] = Array("Art-Net".utf8) + [0, 0x00, 0x20, 0x00, 0x0e, 0x00, 0x00]
            var to = MystrowDmxPlugin.sockaddrFor(0xFFFF_FFFF, port: 6454)
            let n = poll.withUnsafeBytes { buf -> Int in
                withUnsafePointer(to: &to) { p in
                    p.withMemoryRebound(to: sockaddr.self, capacity: 1) { sa in
                        sendto(s, buf.baseAddress, buf.count, 0, sa, socklen_t(MemoryLayout<sockaddr_in>.size))
                    }
                }
            }
            if n < 0 { error = MystrowDmxPlugin.errnoText() + ". " + MystrowDmxPlugin.broadcastHint }

            var buf = [UInt8](repeating: 0, count: 600)
            let end = DispatchTime.now().uptimeNanoseconds + UInt64(max(500, timeoutMs)) * 1_000_000
            while n >= 0 && DispatchTime.now().uptimeNanoseconds < end {
                let got = buf.withUnsafeMutableBytes { recv(s, $0.baseAddress, $0.count, 0) }
                if got < 108 || buf[8] != 0x00 || buf[9] != 0x21 { continue }
                let ip = "\(buf[10]).\(buf[11]).\(buf[12]).\(buf[13])"
                if seen.contains(ip) { continue }
                seen.append(ip)
                func text(_ from: Int, _ len: Int) -> String {
                    let bytes = buf[from..<(from + len)].prefix { $0 != 0 }
                    return (String(bytes: bytes, encoding: .ascii) ?? "").trimmingCharacters(in: .whitespaces)
                }
                nodes.append(["ip": ip, "shortName": text(26, 18), "longName": text(44, 64), "iface": "?"])
            }
            var r: [String: Any] = ["nodes": nodes]
            if !error.isEmpty { r["error"] = error }
            call.resolve(r)
        }
    }

    /// Pas d'USB-DMX sur iOS : liste vide, avec l'explication.
    @objc func usbDevices(_ call: CAPPluginCall) {
        call.resolve(["devices": [[String: Any]](), "kernel": ["L'USB-DMX n'est pas possible sur iPhone / iPad."]])
    }
}
