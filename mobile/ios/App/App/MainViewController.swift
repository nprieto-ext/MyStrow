import UIKit
import Capacitor

/// Contrôleur principal (référencé par Main.storyboard) : enregistre les modules
/// natifs propres à l'app, qui ne viennent pas d'un paquet npm.
class MainViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(MystrowDiscoveryPlugin())
    }

    // Plein écran pendant le show : barre d'état et indicateur d'accueil discrets.
    override var prefersStatusBarHidden: Bool { true }
    override var prefersHomeIndicatorAutoHidden: Bool { true }
}
