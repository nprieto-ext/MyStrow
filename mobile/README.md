# App MyStrow (Android, iPad)

Application des stores basée sur **Capacitor 8**. Pour l'instant, elle **pilote MyStrow
ouvert sur le PC** (mode télécommande). Le mode autonome, sans PC, viendra ensuite dans
la même application.

## Principe : une seule interface

L'interface est `tablet/index.html` à la racine du dépôt, la même page que celle servie
aux navigateurs par `tablet_server.py`. **On ne la modifie jamais dans `mobile/`.**
`npm run build` la copie dans `www/remote.html` et y ajoute uniquement l'adresse du PC
choisi (`window.MYSTROW_API_BASE`).

| Fichier | Rôle |
|---|---|
| `src/launcher.html` → `www/index.html` | Écran de connexion : dernier PC, PC trouvés (Bonjour), saisie de l'adresse, démo |
| `tablet/index.html` → `www/remote.html` | L'interface de pilotage (copiée) |
| `src/demo.js` → `www/demo.js` | **Mode démo** (`remote.html?demo=1`) : show d'exemple sans PC, pour la vitrine et la validation Apple |
| `scripts/build-www.mjs` | Construit `www/` |
| `scripts/make-icons.py` | Icônes et écrans de lancement Android/iOS depuis `logo.png` |
| `android/app/src/main/java/fr/mystrow/app/MystrowDiscoveryPlugin.java` | Découverte Bonjour `_mystrow._tcp` (Android) |
| `ios/App/App/MystrowDiscoveryPlugin.swift` + `MainViewController.swift` | Découverte Bonjour (iOS, `NWBrowser`), enregistrée par le contrôleur principal |

Le mode démo passe par deux points d'entrée de `tablet/index.html`, inactifs dans le
navigateur : `window.MYSTROW_SEND` (reçoit les actions à la place du PC) et
`_handleMsg(msg)` (applique un message, comme le flux SSE).

## Mode autonome (sans PC)

`remote.html?solo=1` : la tablette calcule elle-même le DMX et le sort par le module
natif `MystrowDmx` (USB-DMX ou Art-Net). Patch dans `src/patch.html`.

| Fichier | Rôle |
|---|---|
| `src/engine.js` | Port du moteur du PC : rendu DMX (`artnet_dmx.py`) et effets à couches, lumière et mouvement (`main_window._update_effect_from_layers`) |
| `src/effects.js` | **Généré** par `python mobile/tools/export_effects.py` depuis `effect_editor.BUILTIN_EFFECTS`. Ne pas l'éditer à la main |
| `src/standalone.js` | État du jeu : onglets COULEURS (groupes A-H) / MÉMOIRES (REC puis pad), 8 boutons d'effet (appui long = choisir), visée des lyres (pad POSITION de SCÈNE) |
| `src/library.js` | **Généré** par `python mobile/tools/export_library.py` : bibliothèque du PC (natives, OFL, Firestore `gdtf_fixtures`, QLC+), profils déjà résolus. Chargée par la seule page de patch, qui relit aussi Firestore en ligne (cache `mystrow.lib.firestore`) |
| `src/media.js` | Playlist et cartouches : fichiers copiés dans la tablette (IndexedDB), « + AJOUTER », appui long = monter / descendre / retirer |

Après toute modification de `engine.js`, `artnet_dmx.py`, du moteur d'effets ou de
`BUILTIN_EFFECTS` : `python mobile/tools/export_effects.py` puis
`python mobile/tools/test_engine_parity.py` (compare octet par octet avec le vrai code du PC),
puis `python mobile/tools/test_library_parity.py` (chaque mode de toute la bibliothèque, ~186 000
projecteurs). Avant chaque build : `python generate_custom_fixtures_bundle.py` puis
`python mobile/tools/export_library.py`.

## Côté PC (tablet_server.py)

- `GET /whoami` : `{"app": "MyStrow", "proto": 1, "name": …}`. L'app refuse un PC sans
  `proto` (MyStrow trop ancien) ou avec un `proto` plus récent que le sien (`APP_PROTO`
  dans `src/launcher.html`).
- **Appairage** : `POST /api/pair {code, name}` échange le code à 6 chiffres affiché
  dans *Entrée externe* contre un jeton permanent. Ce jeton est ensuite envoyé en
  `Authorization: Bearer` sur `/api/event` et en `?t=` sur `/stream`.
- Annonce Bonjour `_mystrow._tcp` (paquet Python `zeroconf`).

## Construire l'APK Android (Windows)

Une fois : `npm install` dans `mobile/`, Android Studio (SDK dans
`%LOCALAPPDATA%\Android\Sdk`), et un **JDK 21** dans
`%LOCALAPPDATA%\MyStrowBuild\jdk21`. Gradle 8.14 ne tourne pas sur le Java 25 fourni
avec Android Studio.

```powershell
powershell -ExecutionPolicy Bypass -File mobile\scripts\build-android.ps1
```

APK : `mobile/android/app/build/outputs/apk/debug/app-debug.apk`. Pour l'installer,
copiez-le sur la tablette, ou utilisez `adb install -r` (`adb` est dans
`%LOCALAPPDATA%\Android\Sdk\platform-tools`).

## iPad (sur le Mac)

```bash
cd mobile && npm install && npm run build && npx cap sync ios && npx cap open ios
```

Déjà en place dans `ios/App/App/Info.plist` : autorisation « réseau local », service
Bonjour `_mystrow._tcp`, HTTP autorisé sur le réseau local, barre d'état masquée.

Le module de découverte iOS (`MystrowDiscoveryPlugin.swift`) et `MainViewController.swift`
sont déjà déclarés dans `App.xcodeproj` et `Main.storyboard`, mais **ils ont été ajoutés
depuis Windows et n'ont jamais été compilés**. Au premier build Xcode, vérifier qu'ils
compilent, puis qu'un iPad trouve bien le PC. Il doit afficher la demande d'accès au
réseau local.

## Reste à faire avant les stores

- **Tester sur de vraies tablettes** : découverte, appairage, pilotage, mode démo.
- Premier build iOS sur le Mac (voir ci-dessus).
- Identifiant définitif de l'app : `fr.mystrow.app` est provisoire et ne pourra plus
  changer après la première publication.
- Signature de la version release, comptes Google Play et Apple Developer, fiches
  stores (captures possibles depuis le mode démo), page de confidentialité.
