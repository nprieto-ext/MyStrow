import UIKit
import Capacitor

/// Contrôleur principal (référencé par Main.storyboard) : enregistre les modules
/// natifs propres à l'app, qui ne viennent pas d'un paquet npm.
class MainViewController: CAPBridgeViewController {
    override open func capacitorDidLoad() {
        bridge?.registerPluginInstance(MystrowDiscoveryPlugin())
        bridge?.registerPluginInstance(MystrowDmxPlugin())      // sortie DMX du mode sans PC (Art-Net)
    }

    // Plein écran pendant le show : barre d'état et indicateur d'accueil discrets.
    override var prefersStatusBarHidden: Bool { true }
    override var prefersHomeIndicatorAutoHidden: Bool { true }
}
