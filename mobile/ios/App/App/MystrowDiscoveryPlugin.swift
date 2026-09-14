import Foundation
import Network
import Capacitor

/// Découverte des PC MyStrow sur le Wi-Fi (Bonjour « _mystrow._tcp », annoncé par
/// tablet_server.py). Équivalent iOS de MystrowDiscoveryPlugin.java : chaque PC
/// résolu est envoyé à l'écran de connexion par l'évènement « pcFound »
/// { name, host, port }. Nécessite NSLocalNetworkUsageDescription et
/// NSBonjourServices dans Info.plist (déjà présents).
@objc(MystrowDiscoveryPlugin)
public class MystrowDiscoveryPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "MystrowDiscoveryPlugin"
    public let jsName = "MystrowDiscovery"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "start", returnType: CAPPluginReturnPromise),
        CAPPluginMethod(name: "stop", returnType: CAPPluginReturnPromise)
    ]

    private var browser: NWBrowser?
    private var probes: [NWConnection] = []

    @objc func start(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            self.stopBrowser()
            let browser = NWBrowser(for: .bonjourWithTXTRecord(type: "_mystrow._tcp", domain: nil),
                                    using: NWParameters.tcp)
            browser.browseResultsChangedHandler = { [weak self] results, _ in
                results.forEach { self?.resolve($0) }
            }
            browser.start(queue: .main)
            self.browser = browser
            call.resolve()
        }
    }

    @objc func stop(_ call: CAPPluginCall) {
        DispatchQueue.main.async {
            self.stopBrowser()
            call.resolve()
        }
    }

    /// NWBrowser ne donne qu'un nom de service : une connexion éphémère le résout
    /// en adresse IPv4 + port, puis est aussitôt fermée.
    private func resolve(_ result: NWBrowser.Result) {
        var name = ""
        if case let .bonjour(txt) = result.metadata {
            name = txt["name"] ?? ""
        }
        if name.isEmpty, case let .service(serviceName, _, _, _) = result.endpoint {
            name = serviceName
        }

        let params = NWParameters.tcp
        if let ip = params.defaultProtocolStack.internetProtocol as? NWProtocolIP.Options {
            ip.version = .v4   // une adresse IPv6 ne s'utilise pas telle quelle dans l'URL du PC
        }
        let probe = NWConnection(to: result.endpoint, using: params)
        probe.stateUpdateHandler = { [weak self, weak probe] state in
            guard let self = self, let probe = probe else { return }
            switch state {
            case .ready:
                if case let .hostPort(host, port)? = probe.currentPath?.remoteEndpoint,
                   case let .ipv4(address) = host {
                    self.notifyListeners("pcFound", data: [
                        "name": name,
                        "host": "\(address)",
                        "port": Int(port.rawValue)
                    ])
                }
                probe.cancel()
            case .failed, .cancelled:
                self.probes.removeAll { $0 === probe }
            default:
                break
            }
        }
        probes.append(probe)
        probe.start(queue: .main)
    }

    private func stopBrowser() {
        browser?.cancel()
        browser = nil
        probes.forEach { $0.cancel() }
        probes.removeAll()
    }
}
