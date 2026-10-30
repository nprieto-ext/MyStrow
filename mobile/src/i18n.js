// Langue de l'app tablette : français (texte d'origine) ou anglais.
//
// Chargé EN PREMIER sur chaque page (scripts/build-www.mjs). Le code de l'app
// reste écrit en français ; ce fichier traduit À L'AFFICHAGE : un observateur
// remplace les textes (et title / placeholder / aria-label) dès qu'ils
// apparaissent, y compris dans les fenêtres et messages créés à la volée.
// Ordre : texte exact (DICT), puis motifs (RULES, textes avec des nombres ou
// des noms), puis morceaux connus (FRAG) à l'intérieur d'un texte plus long.
// ⚠ Un texte ajouté dans l'app doit être ajouté ici, sinon il reste en français.
//
// Langue : localStorage « mystrow.lang » (fr | en), sinon celle de l'appareil
// (fr* = français, tout le reste = anglais).
(function () {
  "use strict";
  let lang = null;
  try { lang = localStorage.getItem("mystrow.lang"); } catch (e) {}
  if (lang !== "fr" && lang !== "en") lang = /^fr\b/i.test(navigator.language || "fr") ? "fr" : "en";
  window.MYSTROW_LANG = lang;
  window.MystrowI18n = {
    lang,
    set(l) { try { localStorage.setItem("mystrow.lang", l); } catch (e) {} location.reload(); },
  };
  document.documentElement.lang = lang;
  if (lang === "fr") { window.T = (s) => s; return; }

  const DICT = {
    // ── En-tête, onglets, voyants ──
    "AKAI": "AKAI", "SCÈNE": "STAGE", "MEDIA": "MEDIA", "SURFACE": "SURFACE", "LIVE ●": "LIVE ●",
    "⚙ RÉGLAGES": "⚙ SETTINGS", "Réglages": "Settings", "RÉGLAGES": "SETTINGS",
    "Réglages : projecteurs, sortie DMX, accueil": "Settings: fixtures, DMX output, home",
    "DÉMO": "DEMO", "Version démo": "Demo version", "SANS PC": "NO PC",
    "EN LIGNE": "ONLINE", "HORS LIGNE": "OFFLINE", "Hors ligne": "Offline", "CONNEXION…": "CONNECTING…",
    "État de la connexion": "Connection status", "Connectée": "Connected", "Connexion…": "Connecting…",
    "Connexion en cours…": "Connecting…", "Réessayer maintenant": "Retry now", "Tentative": "Attempt",
    "Dernière info reçue": "Last update received", "à l'instant": "just now",
    "Page": "Page", "PAGE": "PAGE", "Page précédente": "Previous page", "Page suivante": "Next page",
    "page active": "active page",
    // ── AKAI ──
    "🔴 REC": "🔴 REC", "⏺ REC": "⏺ REC", "CLEAR": "CLEAR", "VIT": "SPD", "Master": "Master",
    "Effet du bouton": "Button effect", "Fader": "Fader", "Fader MEM": "MEM fader",
    "Mémoire effacée": "Memory erased", "Mémoire remplacée": "Memory replaced", "Effacer la mémoire": "Erase memory",
    "Remplacer par ce qui joue": "Replace with what is playing", "Enregistrer la visée actuelle ici": "Save the current aim here",
    "Renommer": "Rename", "Effacer": "Erase", "Fermer": "Close", "Annuler": "Cancel", "OK": "OK",
    "Nom de la position": "Position name", "✕ Vider le pad": "✕ Clear the pad", "Pad FX": "FX pad",
    "On n'enregistre pas sur un pad FX : REC annulé": "You can't record on an FX pad: REC cancelled",
    "REC : aucune colonne MEM, appui long sur un nom de fader pour en régler une": "REC: no MEM column, long-press a fader name to set one",
    "Aucune colonne MEM : appui long sur un nom de fader pour en régler une": "No MEM column: long-press a fader name to set one",
    "à zéro : montez-le pour voir la mémoire": "at zero: raise it to see the memory",
    "Aucune lyre de cette position dans le patch": "None of this position's moving heads are in the patch",
    // ── Réglages de l'AKAI ──
    "Réglages de l'AKAI": "AKAI settings", "Dispositions toutes faites, superposition d'effets": "Ready-made layouts, effect stacking",
    "Touchez le bouton sous un fader pour choisir ce qu'il pilote.": "Tap the button under a fader to choose what it controls.",
    "DISPOSITIONS TOUTES FAITES": "READY-MADE LAYOUTS", "pour cette page": "for this page",
    "Copier la page précédente": "Copy the previous page", "Superposition d'effets": "Effect stacking",
    "Les effets s'ajoutent : un 2e effet tourne par-dessus le 1er": "Effects add up: a 2nd effect runs on top of the 1st",
    "Un seul effet à la fois : le nouveau remplace l'ancien": "One effect at a time: the new one replaces the old one",
    "COULEURS": "COLORS", "MÉMOIRES": "MEMORIES", "EFFETS": "EFFECTS", "POSITIONS": "POSITIONS", "AUTRE": "OTHER",
    "les pads donnent la couleur du groupe, le fader règle son niveau": "the pads set the group's color, the fader sets its level",
    "8 mémoires par colonne, le fader règle leur niveau": "8 memories per column, the fader sets their level",
    "8 effets par colonne, le fader règle l'amplitude": "8 effects per column, the fader sets the amplitude",
    "8 positions de lyres": "8 moving-head positions", "8 positions de lyres (pas de lyre dans le patch)": "8 moving-head positions (no moving head in the patch)",
    "Vide": "Empty", "vide": "empty", "rien": "nothing", "Vide ▾": "Empty ▾",
    // ── Réglages (⚙) ──
    "MON MATÉRIEL": "MY GEAR", "JEU": "PLAY", "Projecteurs": "Fixtures", "Sortie DMX": "DMX output", "SORTIE DMX": "DMX OUTPUT",
    "Tester la sortie": "Test the output", "Allumer canal par canal": "Light channel by channel",
    "Éditeur d'effets": "Effect editor", "Créer vos effets": "Create your effects", "Accueil": "Home",
    "Aucun projecteur": "No fixtures", "Interface USB": "USB interface", "Se connecter": "Sign in", "Se déconnecter": "Sign out",
    "DMX limité à 10 min sans compte · récupérer la config du PC": "DMX limited to 10 min without an account · get your PC config",
    "Pas de licence payante : DMX limité à 10 min": "No paid license: DMX limited to 10 min",
    "Licence active : DMX sans limite": "License active: unlimited DMX", "Licence reconnue : DMX sans limite": "License recognized: unlimited DMX",
    "Pack MyStrow": "MyStrow Pack", "Interface USB-DMX + licence · disponible sur Amazon": "USB-DMX interface + license · available on Amazon",
    "Interface USB-DMX + licence": "USB-DMX interface + license",
    "NOUVEAU · DISPONIBLE SUR AMAZON": "NEW · AVAILABLE ON AMAZON",
    "Notre propre interface, pensée pour MyStrow : on la branche, MyStrow la reconnaît tout seul, et la licence est dans la boîte.":
      "Our own interface, designed for MyStrow: plug it in, MyStrow recognizes it on its own, and the license is in the box.",
    "La licence débloque le logiciel PC/Mac et l'app tablette, sans limite de 10 minutes.": "The license unlocks the PC/Mac software and the tablet app, with no 10-minute limit.",
    "Notre propre interface, pensée pour MyStrow : on la branche, MyStrow la reconnaît tout seul, et la licence est dans la boîte. La licence débloque le logiciel PC/Mac et l'app tablette, sans limite de 10 minutes.":
      "Our own interface, designed for MyStrow: plug it in, MyStrow recognizes it on its own, and the license is in the box. The license unlocks the PC/Mac software and the tablet app, with no 10-minute limit.",
    "Licence 2 mois · 99 € ↗": "2-month license · €99 ↗", "Licence 1 an · 199 € ↗": "1-year license · €199 ↗",
    "La page s'ouvre dans Amazon (ou le navigateur).": "The page opens in Amazon (or your browser).",
    "Acheter le pack MyStrow (Amazon)": "Buy the MyStrow Pack (Amazon)",
    "Langue": "Language",
    // ── Démo / sortie DMX ──
    "DMX coupé": "DMX off", "Relancer la sortie": "Restart the output", "Régler la sortie (USB ou node)": "Set up the output (USB or node)",
    "Tester la sortie DMX": "Test the DMX output", "Sortie arrêtée": "Output stopped", "Module DMX absent": "DMX module missing",
    "Sans licence, la sortie DMX s'arrête au bout de 10 minutes.": "Without a license, the DMX output stops after 10 minutes.",
    "Connectez-vous avec un compte MyStrow sous licence pour jouer sans limite, ou relancez l'app pour 10 nouvelles minutes.":
      "Sign in with a licensed MyStrow account to play without limit, or restart the app for 10 more minutes.",
    "Connectez-vous avec un compte MyStrow sous licence pour jouer sans limite.": "Sign in with a licensed MyStrow account to play without limit.",
    // ── Achat intégré iOS « MyStrow Tablette » ──
    "Débloquez MyStrow Tablette (achat unique) ou connectez-vous avec un compte MyStrow sous licence pour jouer sans limite.":
      "Unlock MyStrow Tablet (one-time purchase) or sign in with a licensed MyStrow account to play without limit.",
    "Débloquez MyStrow Tablette (achat unique) ou connectez-vous avec un compte MyStrow sous licence pour jouer sans limite, ou relancez l'app pour 10 nouvelles minutes.":
      "Unlock MyStrow Tablet (one-time purchase) or sign in with a licensed MyStrow account to play without limit, or restart the app for 10 more minutes.",
    "Débloquer MyStrow Tablette": "Unlock MyStrow Tablet", "MyStrow Tablette": "MyStrow Tablet",
    "MyStrow Tablette débloquée ✓": "MyStrow Tablet unlocked ✓",
    "MyStrow Tablette débloquée : DMX sans limite": "MyStrow Tablet unlocked: unlimited DMX",
    "DMX limité à 10 min · débloquer ou récupérer la config du PC": "DMX limited to 10 min · unlock or get your PC config",
    "Sortie DMX sans limite de temps sur cette tablette.": "Unlimited DMX output time on this tablet.",
    "Débloquez la sortie DMX sans limite de temps sur cette tablette, par un achat unique. Aucun compte nécessaire.":
      "Unlock unlimited DMX output time on this tablet with a one-time purchase. No account needed.",
    "Achat en cours…": "Purchasing…", "Restaurer les achats": "Restore purchases",
    "Achat en attente d'autorisation : la sortie DMX sera débloquée dès qu'il sera accepté.":
      "Purchase awaiting approval: DMX output will be unlocked as soon as it is approved.",
    "Aucun achat de MyStrow Tablette trouvé pour cet identifiant Apple.": "No MyStrow Tablet purchase found for this Apple ID.",
    "Achat indisponible sur cet appareil.": "Purchase not available on this device.",
    "Achat non vérifié par l'App Store": "Purchase not verified by the App Store", "Produit introuvable": "Product not found",
    "Sur iPad, le DMX s'arrête si MyStrow reste en arrière-plan. Gardez l'app au premier plan pendant le show (Accès guidé).":
      "On iPad, DMX stops if MyStrow stays in the background. Keep the app in the foreground during the show (Guided Access).",
    // ── Mon compte ──
    "Mon compte MyStrow": "My MyStrow account", "Mon compte": "My account", "E-mail": "Email", "Mot de passe": "Password",
    "ou": "or", "Continuer avec Google": "Continue with Google", "Continuer avec Apple": "Continue with Apple",
    "Terminez la connexion dans la fenêtre qui s'est ouverte…": "Finish signing in in the window that opened…",
    "Connexion expirée : réessayez.": "Sign-in expired: try again.",
    "Connexion non terminée : réessayez.": "Sign-in not completed: try again.",
    "Impossible d'ouvrir la fenêtre de connexion.": "Could not open the sign-in window.",
    "Mot de passe oublié ? Le recevoir par e-mail": "Forgot password? Get it by email",
    "Entrez votre e-mail ci-dessus.": "Enter your email above.", "Envoi…": "Sending…",
    "Identifiants envoyés ✓ Pensez à regarder dans vos spams.": "Credentials sent ✓ Check your spam folder.",
    "Envoi impossible.": "Could not send.", "Pas de connexion Internet.": "No Internet connection.",
    "Connectez-vous avec le compte de votre licence MyStrow : la sortie DMX n'est plus coupée au bout de 10 minutes, et vous récupérez la config de votre PC (patch, mémoires, effets).":
      "Sign in with your MyStrow license account: the DMX output no longer stops after 10 minutes, and you can get your PC config (patch, memories, effects).",
    "Mot de passe oublié : depuis le logiciel MyStrow sur le PC (Mon compte) ou sur mystrow.fr.": "Forgot your password? Use the MyStrow software on your PC (My account) or mystrow.fr.",
    "Pas encore de compte ?": "No account yet?",
    "Vous avez une carte d'activation (pack MyStrow) : activez-la sur le site. Il crée votre compte et vous envoie le mot de passe par email ; revenez ensuite vous connecter ici.":
      "Got an activation card (MyStrow Pack)? Activate it on the website. It creates your account and emails you the password; then come back here to sign in.",
    "Activer ma carte sur mystrow.fr ↗": "Activate my card on mystrow.fr ↗",
    "Récupérer la config du PC": "Get my PC config", "Recherche…": "Searching…",
    "Rien n'a encore été envoyé. Sur le PC : menu Connexion › Contrôle › « Envoyer ma config vers la tablette ».":
      "Nothing has been sent yet. On the PC: menu Connection › Control › “Send my config to the tablet”.",
    "Revenir à la config d'avant l'import": "Go back to the config before the import",
    "Remplacer la config de la tablette": "Replace the tablet's config",
    "Elle remplace le patch, les pages AKAI, les mémoires et les positions de la tablette. La sortie DMX (USB ou node) ne change pas. Vos effets créés sur la tablette restent.":
      "It replaces the tablet's patch, AKAI pages, memories and positions. The DMX output (USB or node) does not change. Effects you created on the tablet are kept.",
    "Ce compte n'a pas de licence payante (essai) : la sortie DMX reste limitée à 10 minutes par lancement.": "This account has no paid license (trial): DMX output stays limited to 10 minutes per session.",
    "Licence expirée : la sortie DMX reste limitée à 10 minutes.": "License expired: DMX output stays limited to 10 minutes.",
    "Licence non vérifiée depuis plus de 7 jours : connectez la tablette à Internet.": "License not checked for more than 7 days: connect the tablet to the Internet.",
    "Adresse e-mail invalide.": "Invalid email address.", "E-mail ou mot de passe incorrect.": "Wrong email or password.",
    "Aucun compte avec cet e-mail.": "No account with this email.", "Mot de passe incorrect.": "Wrong password.",
    "Ce compte est désactivé.": "This account is disabled.", "Trop d'essais : réessayez dans quelques minutes.": "Too many attempts: try again in a few minutes.",
    "Pas de connexion Internet.": "No Internet connection.", "Pas connecté.": "Not signed in.", "Accès refusé par le compte.": "Access denied for this account.",
    "Compte indisponible dans cette version": "Account unavailable in this version",
    // ── Choix d'effet / éditeur ──
    "＋ Créer un effet": "＋ Create an effect", "Mes effets": "My effects", "Éditeur d'effets : choisir un effet à modifier": "Effect editor: choose an effect to edit",
    "Supprimer l'effet": "Delete the effect", "Effet supprimé": "Effect deleted", "Nom de l'effet": "Effect name", "Mon effet": "My effect",
    "Donnez un nom à l'effet": "Give the effect a name", "Un effet garde au moins une couche": "An effect keeps at least one layer",
    "Les boutons et pads qui le portaient n'auront plus d'effet. Les mémoires gardent leur copie.": "Buttons and pads that used it will have no effect. Memories keep their copy.",
    "‹ Retour": "‹ Back", "APERÇU": "PREVIEW", "ENREGISTRER": "SAVE", "Enregistrer": "Save", "COUCHES": "LAYERS", "COUCHE": "LAYER",
    "＋ AJOUTER UNE COUCHE": "＋ ADD A LAYER", "Dupliquer": "Duplicate", "Supprimer": "Delete", "Monter": "Move up", "Descendre": "Move down",
    "CANAL": "CHANNEL", "ce que la couche fait varier": "what the layer changes", "FORME": "SHAPE", "allure de la variation dans le temps": "how the change moves over time",
    "CIBLE": "TARGET", "projecteurs concernés par la couche": "fixtures affected by the layer", "Aucun groupe coché : tous les groupes.": "No group ticked: all groups.",
    "RÉGLAGES": "SETTINGS", "toucher une valeur = valeur par défaut": "tap a value = default value", "RÉPARTITION": "SPREAD",
    "TRAJECTOIRE": "PATH", "trajectoire des lyres": "moving-head path", "SYMÉTRIE": "SYMMETRY", "Limites": "Limits",
    "AMP": "AMP", "DÉC": "OFFS", "DÉPART": "START", "FONDU": "FADE", "MIN": "MIN", "MAX": "MAX", "TAILLE": "SIZE",
    "Couleur": "Color", "Permutation": "Permutation", "Permut": "Permut", "Intensité": "Intensity", "Strobe": "Strobe",
    "Rouge": "Red", "Vert": "Green", "Bleu": "Blue", "Mouvement": "Movement", "Pan": "Pan", "Tilt": "Tilt",
    "Sinus": "Sine", "Flash": "Flash", "Triangle": "Triangle", "Montée": "Ramp up", "Descente": "Ramp down", "Un par un": "One by one",
    "Aléatoire": "Random", "Fixe": "Fixed", "Off": "Off", "Tous": "All", "Pairs": "Even", "Impairs": "Odd", "Pair": "Even", "Impair": "Odd",
    "Groupe": "Group", "GROUPER": "GROUP", "8 Huit": "8 Figure 8", "vitesse du cycle": "cycle speed", "force de l'effet": "effect strength", "décale le départ de la couche": "shifts the layer's start",
    "adoucit la forme": "softens the shape", "Linéaire": "Linear", "Chenillard": "Chase", "Miroir (centre)": "Mirror (center)", "Miroir (bords)": "Mirror (edges)",
    "Pair / impair": "Even / odd", "projecteurs qui partent ensemble": "fixtures that start together",
    "ordre dans lequel le décalage (DÉC) parcourt les projecteurs": "order in which the offset (OFFS) goes through the fixtures",
    "1, 2, 3, 4… — chenillard classique": "1, 2, 3, 4… — classic chase", "part du centre vers les extrémités": "goes from the center to the ends",
    "1&8, puis 2&7, puis 3&6": "1&8, then 2&7, then 3&6", "une fixture sur deux, en alternance": "every other fixture, alternating",
    "ordre dispersé, mais reproductible": "scattered order, but repeatable",
    "fait varier la couleur posée sur l'AKAI": "varies the color set on the AKAI", "passe de la couleur 1 à la couleur 2": "goes from color 1 to color 2",
    "la couleur 1 suit la forme": "color 1 follows the shape", "intensité hachée": "chopped intensity", "canal rouge seul": "red channel only",
    "canal vert seul": "green channel only", "canal bleu seul": "blue channel only", "balayage gauche-droite": "left-right sweep", "balayage haut-bas": "up-down sweep",
    "Pas de lyre dans le patch : cette couche ne bougera rien.": "No moving head in the patch: this layer won't move anything.",
    "Effet d'intensité : allumez une couleur sur l'AKAI pour le voir.": "Intensity effect: light a color on the AKAI to see it.",
    "Aperçu coupé : les projecteurs jouent ce qui tournait avant.": "Preview off: the fixtures play what was running before.",
    "Quitter l'éditeur ?": "Leave the editor?", "Quitter sans enregistrer": "Leave without saving",
    "Inverser pan": "Invert pan", "Inverser tilt": "Invert tilt",
    "○ Cercle": "○ Circle", "∞ Infini": "∞ Infinity", "□ Carré": "□ Square", "↔ Balancier": "↔ Swing", "↕ Pendule": "↕ Pendulum",
    "↔ Aller-retour": "↔ Back and forth", "→ Avant": "→ Forward", "← Arrière": "← Backward", "▲ Monter": "▲ Up", "▼ Descendre": "▼ Down",
    "Bornes de pan et de tilt : la lyre ne sort jamais de cette zone": "Pan and tilt limits: the moving head never leaves this area",
    "La lyre s'allume et suit la borne que vous déplacez. Effets et visée restent ensuite dans cette zone.": "The moving head lights up and follows the limit you drag. Effects and aim then stay inside this area.",
    "Revenir à 100 %": "Back to 100%",
    // ── SCÈNE ──
    "SELECT ALL": "SELECT ALL", "NOMS": "NAMES", "DÉPLACER": "MOVE", "ALIGNER": "ALIGN", "RÉPARTIR": "SPREAD", "2 PROJOS MIN.": "2 FIXTURES MIN.",
    "Mettre les projecteurs sélectionnés à la même hauteur": "Put the selected fixtures at the same height",
    "Espacer régulièrement les projecteurs sélectionnés": "Space the selected fixtures evenly",
    "RÀZ": "RESET", "Remettre ces canaux à 0": "Reset these channels to 0",
    "Recherche du boîtier…": "Looking for the box…",
    "Aucun boîtier détecté — branchez l'interface USB-DMX ou le node.": "No box detected — plug in the USB-DMX interface or the node.",
    "Boîtier : vérifié au lancement du jeu.": "Box: checked when the show starts.",
    "Diagnostic avancé de la sortie DMX ›": "Advanced DMX output diagnostics ›", "Zoom du plan": "Plot zoom", "Zoomer": "Zoom in", "Dézoomer": "Zoom out",
    "POSITION": "POSITION", "Position": "Position", "SYM PAN": "SYM PAN", "SYM TILT": "SYM TILT", "CENTRER": "CENTER",
    "gauche ↔ droite": "left ↔ right", "haut ↕ bas": "up ↕ down", "EFFETS RAPIDES": "QUICK EFFECTS", "Arrêter": "Stop",
    "VITESSE": "SPEED", "AMPLITUDE": "AMPLITUDE", "DÉPHASAGE": "PHASE", "Cercle": "Circle", "Huit": "Figure 8",
    "Balayage pan": "Pan sweep", "Balayage tilt": "Tilt sweep", "Arc-en-ciel": "Rainbow", "Rouge → blanc": "Red → white",
    "MUTE": "MUTE", "UNMUTE": "UNMUTE", "ROUE COULEUR": "COLOR WHEEL", "GOBO": "GOBO", "Ouvert": "Open", "Autre couleur": "Other color",
    "Seulement les groupes allumés en jaune.": "Only the groups lit in yellow.", "sélectionnés": "selected",
    // ── LIVE ──
    "ÉCOUTER LA MUSIQUE": "LISTEN TO THE MUSIC", "ARRÊTER L'ÉCOUTE": "STOP LISTENING", "KICK": "KICK", "CAISSE": "SNARE", "CHARLEY": "HI-HAT",
    "BPM": "BPM", "elles tournent au rythme de la musique": "they change with the beat", "CHANGER TOUS LES": "CHANGE EVERY",
    "MOUVEMENT DES LYRES": "MOVING-HEAD MOVEMENT", "plusieurs choisis = ils s'enchaînent": "several picked = they follow each other",
    "RÉACTION": "REACTION", "NERVOSITÉ": "NERVOUSNESS", "SENSIBILITÉ": "SENSITIVITY", "STROBE": "STROBE", "AU DROP": "ON THE DROP",
    "Rapide": "Fast", "Lent": "Slow", "Aucun": "None", "Flash blanc": "White flash", "Explosion couleur": "Color burst",
    "Noir puis flash": "Blackout then flash", "Stroboscope": "Strobe", "Strobe couleur": "Color strobe", "INTENSITÉ": "INTENSITY",
    "Vague": "Wave", "Diagonale": "Diagonal", "Rebond": "Bounce", "Spirale": "Spiral", "Lissajous": "Lissajous",
    "Orange": "Orange", "Jaune": "Yellow", "Ambre": "Amber", "Rose": "Pink", "Rose chaud": "Hot pink", "Cyan": "Cyan", "Bleu nuit": "Navy blue",
    "Violet": "Purple", "Lavande": "Lavender", "Blanc": "White", "Rouge / bleu": "Red / blue", "Violet / orange": "Purple / orange",
    "Vert / jaune": "Green / yellow", "Rouge / violet": "Red / purple", "Orange / cyan": "Orange / cyan", "Bleu / vert": "Blue / green",
    "Gardez au moins une couleur": "Keep at least one color", "CALME": "CALM", "INTENSE": "INTENSE", "MONTÉE": "BUILD-UP", "COUPLET": "VERSE",
    "DROP": "DROP", "REFRAIN": "CHORUS", "SILENCE": "SILENCE", "PAUSE": "PAUSE", "INTRO": "INTRO",
    "LIVE : la lumière suit la musique (l'AKAI ne pilote plus)": "LIVE: the lights follow the music (the AKAI no longer controls them)",
    "Accès au micro refusé : autorisez-le dans les réglages de la tablette.": "Microphone access denied: allow it in the tablet's settings.",
    "Micro indisponible sur cet appareil": "Microphone unavailable on this device",
    // ── Accueil (launcher) ──
    "MyStrow — Tablette": "MyStrow — Tablet", "Piloter MyStrow sur mon PC": "Control MyStrow on my PC",
    "La tablette devient la télécommande du logiciel ouvert sur votre ordinateur, sur le même Wi-Fi.": "The tablet becomes the remote control of the software open on your computer, on the same Wi-Fi.",
    "Jouer sans PC": "Play without a PC", "Bêta": "Beta",
    "La tablette pilote elle-même vos projecteurs, par une interface USB-DMX ou un node Art-Net.": "The tablet controls your fixtures itself, through a USB-DMX interface or an Art-Net node.",
    "Connexion au PC": "Connect to the PC", "Sur le PC, dans MyStrow :": "On the PC, in MyStrow:", "Connexion › Entrée externe": "Connection › External input",
    "Entrée externe": "External input", "La tablette et le PC sur": "The tablet and the PC on", "le même Wi-Fi": "the same Wi-Fi",
    "Touchez votre PC ci-dessous, ou tapez l'adresse affichée sous le QR code.": "Tap your PC below, or type the address shown under the QR code.",
    "La première fois, tapez le": "The first time, type the", "code à 6 chiffres": "6-digit code",
    "affiché sur le PC sous le QR code.": "shown on the PC under the QR code.",
    "La tablette devient la télécommande du logiciel, sur le même Wi-Fi": "The tablet becomes the software's remote control, on the same Wi-Fi",
    "PC trouvés sur le réseau": "PCs found on the network", "Adresse du PC": "PC address", "Connecter": "Connect", "Connecter ›": "Connect ›",
    "Dernier PC utilisé": "Last PC used", "Changer de PC": "Change PC", "Code d'appairage": "Pairing code", "APPAIRER": "PAIR",
    "Appairer cette tablette": "Pair this tablet", "et saisissez le code à 6 chiffres affiché sous le QR code.": "and enter the 6-digit code shown under the QR code.",
    "Le code comporte 6 chiffres.": "The code has 6 digits.", "Code incorrect. Vérifiez le code affiché sur le PC.": "Wrong code. Check the code shown on the PC.",
    "Cette tablette n’est plus appairée. Saisissez le nouveau code affiché sur le PC.": "This tablet is no longer paired. Enter the new code shown on the PC.",
    "MyStrow trouvé, connexion…": "MyStrow found, connecting…", "Recherche de MyStrow sur": "Looking for MyStrow on",
    "La tablette contacte MyStrow sur le PC.": "The tablet is contacting MyStrow on the PC.",
    "Le dernier PC ne répond pas. Choisissez un PC ou saisissez son adresse.": "The last PC isn't answering. Pick a PC or enter its address.",
    "Ce PC ne répond plus. Réessayez dans un instant.": "This PC isn't answering. Try again in a moment.",
    "MyStrow ne répond pas à cette adresse. Vérifiez que l'Entrée externe est activée sur le PC et que la tablette est sur le même Wi-Fi.":
      "MyStrow isn't answering at this address. Check that External input is on in the PC and that the tablet is on the same Wi-Fi.",
    "MyStrow ne répond pas. Vérifiez que l’application est ouverte et que la tablette est sur le même Wi-Fi que le PC.":
      "MyStrow isn't answering. Check that the software is open and that the tablet is on the same Wi-Fi as the PC.",
    "MyStrow ne répond pas. Vérifiez que l’application est ouverte sur le PC, que la tablette est sur le même Wi-Fi et que le PC n’est pas en veille.":
      "MyStrow isn't answering. Check that the software is open on the PC, that the tablet is on the same Wi-Fi and that the PC isn't asleep.",
    "MyStrow sur ce PC est plus récent que l'app. Mettez l'app à jour depuis le store.": "MyStrow on this PC is newer than the app. Update the app from the store.",
    "MyStrow sur ce PC est trop ancien pour l'app. Mettez-le à jour, puis réessayez.": "MyStrow on this PC is too old for the app. Update it, then try again.",
    "Le Wi-Fi de la tablette est coupé. Reconnectez-la au même réseau que le PC.": "The tablet's Wi-Fi is off. Reconnect it to the same network as the PC.",
    "Reconnecter maintenant": "Reconnect now", "Relancer la connexion": "Retry the connection", "Connectée à MyStrow": "Connected to MyStrow",
    "Les pads, les faders et la playlist se mettent à jour en direct.": "Pads, faders and the playlist update live.",
    "Commencez par indiquer vos projecteurs et leurs adresses DMX.": "Start by entering your fixtures and their DMX addresses.",
    "Commencer : ajouter mes projecteurs": "Start: add my fixtures", "Mon patch": "My patch", "Jouer": "Play", "Patch": "Patch", "PATCH": "PATCH",
    "Aucun projecteur patché": "No fixtures patched", "‹ Accueil": "‹ Home", "Mon compte ›": "My account ›",
    "Plein écran": "Full screen", "Quitter le plein écran": "Exit full screen", "Plein écran non disponible dans ce navigateur.": "Full screen isn't available in this browser.",
    "Le navigateur a refusé le plein écran.": "The browser refused full screen.", "Menu du navigateur →": "Browser menu →",
    "« Ajouter à l'écran d'accueil »": "“Add to Home screen”", "Partager": "Share", "« Sur l'écran d'accueil »": "“Add to Home Screen”",
    "et ouvrez MyStrow depuis l'icône : il s'affichera en plein écran.": "and open MyStrow from the icon: it will show full screen.",
    "Touchez": "Tap", "puis": "then",
    // ── Patch ──
    "MyStrow · Patch": "MyStrow · Patch", "Mes projecteurs (patch)": "My fixtures (patch)", "＋ Ajouter": "＋ Add", "Ajouter": "Add",
    "Ajouter des projecteurs": "Add fixtures", "Rechercher un projecteur": "Search for a fixture", "Marque ou modèle : izy, cameo, par 64…": "Brand or model: izy, cameo, par 64…",
    "Aucun projecteur ne correspond. Introuvable ? Créez-le avec « ＋ Créer un projecteur ».": "No fixture matches. Can't find it? Create it with “＋ Create a fixture”.",
    "Aucun projecteur pour l'instant : touchez « ＋ Ajouter » en haut.": "No fixtures yet: tap “＋ Add” at the top.",
    "＋ Créer un projecteur": "＋ Create a fixture", "Créer un projecteur": "Create a fixture", "Modifier un projecteur": "Edit a fixture",
    "Modifier": "Edit", "Copier et modifier": "Copy and edit", "Mode DMX": "DMX mode", "Groupe (colonne de l'AKAI)": "Group (AKAI column)",
    "Groupe (colonne)": "Group (column)", "Quantité": "Quantity", "1re adresse DMX": "1st DMX address", "Écart": "Gap", "Adresse": "Address",
    "Nom": "Name", "Nom (facultatif)": "Name (optional)", "Facultatif": "Optional", "Marque": "Brand", "Modèle": "Model", "Type": "Type",
    "Ex. : Spot 60W": "E.g.: Spot 60W", "Canaux DMX, dans l'ordre de la notice": "DMX channels, in the manual's order", "＋ Ajouter un canal": "＋ Add a channel",
    "Partir d'un profil tout fait": "Start from a ready-made profile", "— Choisir —": "— Choose —", "＋ Ajouter une couleur": "＋ Add a color",
    "Pour chaque couleur de la roue : la valeur DMX où elle commence (voir la notice) et sa teinte. Sans couleur, une roue standard est utilisée.":
      "For each color on the wheel: the DMX value where it starts (see the manual) and its hue. Without colors, a standard wheel is used.",
    "Enregistrer le projecteur": "Save the fixture", "Supprimer de ma bibliothèque": "Delete from my library",
    "Supprimé de votre bibliothèque.": "Deleted from your library.", "Donnez un nom au modèle.": "Give the model a name.",
    "Ajoutez au moins un canal.": "Add at least one channel.", "Aucun canal : ajoutez-en un.": "No channels: add one.",
    "Choisissez d'abord un projecteur dans la bibliothèque.": "First choose a fixture from the library.", "Ajoutez d'abord des projecteurs.": "Add fixtures first.",
    "Plus de place dans l'univers (512 canaux).": "No more room in the universe (512 channels).",
    "⚠ Des projecteurs se chevauchent (adresses en rouge).": "⚠ Some fixtures overlap (addresses in red).",
    "« Tester » allume le projecteur en blanc : vérifiez que c'est bien lui qui s'allume.": "“Test” lights the fixture in white: check that it's the right one.",
    "Tester": "Test", "Retirer": "Remove", "Tout effacer": "Clear all", "Patch effacé.": "Patch cleared.",
    "Voulez-vous vraiment tout effacer ? Les projecteurs du patch seront supprimés.": "Do you really want to clear everything? The fixtures in the patch will be removed.", "Tout libérer": "Release all",
    "Que voulez-vous faire ?": "What do you want to do?", "Perso": "Custom", "Générique": "Generic", "Générique tablette": "Generic tablet",
    "Le projecteur est gardé sur cette tablette, dans votre bibliothèque : cherchez-le ensuite par son nom pour l'ajouter au patch.":
      "The fixture is kept on this tablet, in your library: then search for it by name to add it to the patch.",
    "Les projecteurs suivants prennent les adresses 1, 11, 21… comme dans MyStrow sur PC (plus de 10 canaux : dizaine suivante, 1, 21, 41…). Réglez vos projecteurs sur ces adresses.":
      "The following fixtures take addresses 1, 11, 21… as in MyStrow on PC (over 10 channels: next ten, 1, 21, 41…). Set your fixtures to these addresses.",
    "SORTIE": "OUTPUT", "Node Art-Net": "Art-Net node", "node Art-Net": "Art-Net node", "Filaire / node USB": "Wired / USB node", "Adresse du node": "Node address",
    "Chercher le node": "Find the node", "Chercher": "Search", "Aucun node n'a répondu.": "No node answered.", "Port": "Port",
    "Branchez l'interface USB-DMX sur la tablette : Opto ElectroConcept, ENTTEC Pro, DMXKing ou boîtier MyStrow. Son type est reconnu tout seul.":
      "Plug the USB-DMX interface into the tablet: Opto ElectroConcept, ENTTEC Pro, DMXKing or MyStrow box. Its type is recognized automatically.",
    "Branchez l'interface USB-DMX sur la tablette, ou mettez la tablette sur le même réseau que le node Art-Net.":
      "Plug the USB-DMX interface into the tablet, or put the tablet on the same network as the Art-Net node.",
    "Node Art-Net branché sur le même réseau que la tablette (box ou routeur, la tablette en Wi-Fi).": "Art-Net node on the same network as the tablet (router, tablet on Wi-Fi).",
    "Sur iPhone / iPad, la diffusion demande une autorisation Apple : donnez plutôt au node une adresse du réseau.": "On iPhone / iPad, broadcast needs an Apple permission: give the node an address on your network instead.",
    "La recherche automatique est bloquée par iPadOS (le USB NODE ne répond qu'à la diffusion). Saisissez l'adresse : 2.0.0.15 pour un node ElectroConcept, USB ou RJ45.":
      "Automatic search is blocked by iPadOS (the USB NODE only answers broadcast). Enter the address: 2.0.0.15 for an ElectroConcept node, USB or RJ45.",
    "Aucun appareil USB branché.": "No USB device plugged in.", "interface USB-DMX": "USB-DMX interface", "Tablette Android": "Android tablet",
    // Types et canaux de projecteurs
    "Lyre": "Moving head", "Barre LED": "LED bar", "Gradateur": "Dimmer", "Effet": "Effect", "Laser": "Laser", "Matrice LED": "LED matrix",
    "Machine à étincelles": "Spark machine", "Lance-flamme": "Flame thrower", "Machine à fumée": "Smoke machine", "Machine à brouillard": "Haze machine",
    "Dimmer (intensité)": "Dimmer (intensity)", "Roue de gobos": "Gobo wheel", "Rotation gobo": "Gobo rotation", "Roue de gobos 2": "Gobo wheel 2",
    "Effets / macros": "Effects / macros", "Mode / programme": "Mode / program", "Pan fin (16 bits)": "Pan fine (16-bit)", "Tilt fin (16 bits)": "Tilt fine (16-bit)",
    "Prisme": "Prism", "Rotation prisme": "Prism rotation", "Fumée (débit)": "Smoke (output)", "Ventilateur": "Fan", "Étincelles": "Sparks", "Flamme": "Flame",
    "Vitesse pan/tilt": "Pan/tilt speed", "Roue de couleurs": "Color wheel", "Shutter (obturateur)": "Shutter", "Inutilisé / autre": "Unused / other",
    "Magenta": "Magenta", "Lime": "Lime",
    // ── Test de sortie ──
    "MyStrow · Test sortie DMX": "MyStrow · DMX output test", "Démarrer": "Start", "Démarrage…": "Starting…", "Envoi arrêté": "Sending stopped",
    "Trames / s": "Frames / s", "trames / s": "frames / s", "trames envoyées": "frames sent", "trames en retard": "late frames", "erreurs d'envoi": "send errors",
    "écart moyen (ms)": "average gap (ms)", "pire écart (ms)": "worst gap (ms)", "Mesures côté tablette": "Measured on the tablet",
    "Journal vers le PC (IP, facultatif)": "Log to the PC (IP, optional)", "Contenu envoyé": "Content sent", "Plein feu": "Full on", "Noir": "Blackout",
    "La tablette envoie le DMX elle-même, sans PC : par une interface USB-DMX ou vers un node Art-Net. Sert à mesurer la régularité de l'envoi.":
      "The tablet sends DMX itself, without a PC: through a USB-DMX interface or to an Art-Net node. Used to measure how steady the output is.",
    "Module DMX absent : cette page ne marche que dans l'app.": "DMX module missing: this page only works in the app.",
    // ── Médias (mode PC) ──
    "EN COURS": "NOW PLAYING", "Morceau ajouté": "Track added", "Retirer de la playlist": "Remove from the playlist",
    "Choisir un son…": "Choose a sound…", "Vider la cartouche": "Clear the cartridge", "Cartouche vide : appui long pour choisir un son": "Empty cartridge: long-press to choose a sound",
    "fichier introuvable dans la tablette": "file not found on the tablet", "Manuel": "Manual", "Programme": "Program",
    // ── Noms des effets de la bibliothèque : ceux du logiciel PC (i18n.py, clés nm_*) ──
    "SPÉCIAL": "SPECIAL", "LYRE": "MOVING HEAD", "COULEUR": "COLOR",
    "MOUVEMENT": "MOVEMENT", "AMBIANCE": "AMBIENCE", "PERMUT": "PERMUT",
    "Spécial": "Special", "Ambiance": "Ambience", "Sur le PC, ouvrez": "On the PC, open",
    "décalage entre projecteurs (0 = tous ensemble)": "offset between fixtures (0 = all together)", "largeur du mouvement (100 = petit, 400 = toute la course)": "movement width (100 = small, 400 = full travel)", "les lyres de l'autre côté partent en miroir": "moving heads on the other side mirror the movement",
    "LYRES": "MOVING HEADS", "MÉDIA SUIVANT": "NEXT MEDIA", "Jingle entrée": "Intro jingle",
    "Sirène": "Siren", "Applaudissements": "Applause", "Roulement": "Drum roll",
    "Remise des prix — Jingle.mp3": "Awards — Jingle.mp3", "Discours d'accueil.wav": "Welcome speech.wav", "Mode démo : aucune lumière n'est pilotée. Toucher pour connecter un PC.": "Demo mode: no lights are controlled. Tap to connect a PC.",
    "FACE": "FRONT", "CONTRE": "BACK", "DCH 1": "TOP 1",
    "DCH 2": "TOP 2", "DCH 3": "TOP 3", "BARRE": "BAR",
    "ROUGE": "RED", "BLEU": "BLUE", "AMBRE": "AMBER",
    "Strobe Classique": "Classic Strobe", "Strobe Lent": "Slow Strobe", "Strobe Rapide": "Fast Strobe",
    "Strobe Alternance": "Alternating Strobe", "Flash Couleur": "Color Flash", "Flash Blanc": "White Flash",
    "Chase Blanc": "White Chase", "Chase Rapide": "Fast Chase", "Chase Retour": "Return Chase",
    "Chase Doux": "Soft Chase", "Passage Blanc": "White Sweep", "Comète": "Comet",
    "Comète Colorée": "Colored Comet", "Pulse Doux": "Soft Pulse", "Pulse Rapide": "Fast Pulse",
    "Pulse Décalé": "Offset Pulse", "Vague": "Wave", "Rainbow Rapide": "Fast Rainbow",
    "Feu": "Fire", "Bascule": "Toggle", "Strobe Couleur": "Color Strobe",
    "Escalier": "Staircase", "Miroir": "Mirror", "Miroir Comète": "Mirror Comet",
    "Alterné": "Alternate", "Va-et-vient": "Back and Forth", "Va-et-vient Comète": "Back and Forth Comet",
    "Respiration": "Breathing", "Bougie": "Candle", "Scintillement": "Twinkle",
    "Violet Pulsé": "Pulsing Purple", "Rose Flash": "Pink Flash", "Cyan Vague": "Cyan Wave",
    "Blanc Strobe": "White Strobe", "Nuit Bleue": "Blue Night", "Vert Jungle": "Jungle Green",
    "Spectre": "Spectrum", "Strobe Bleu": "Blue Strobe", "Strobe Vert": "Green Strobe",
    "Strobe Rouge": "Red Strobe", "Strobe Mémoire": "Memory Strobe", "Chase Rouge": "Red Chase",
    "Chase Vert": "Green Chase", "Chase Bleu": "Blue Chase", "Permut Rouge & Rose": "Swap Red & Pink",
    "Permut Bleu & Cyan": "Swap Blue & Cyan", "Permut Vert & Jaune": "Swap Green & Yellow", "Permut Violet & Blanc": "Swap Purple & White",
    "Permut Orange & Rouge": "Swap Orange & Red", "Permut Custom": "Custom Swap", "Permut Rose & Blanc": "Swap Pink & White",
    "Permut Rouge & Or": "Swap Red & Gold", "Permut Cyan & Blanc": "Swap Cyan & White", "Permut Feu": "Fire Swap",
    "Permut Lent": "Slow Swap", "Permut Rapide": "Fast Swap", "Lyre Cercle": "Head Circle",
    "Lyre Figure 8": "Head Figure 8", "Lyre Infini": "Head Infinity", "Lyre Balancier": "Head Swing",
    "Lyre Pendule": "Head Pendulum", "Lyre Carré": "Head Square", "Lyre Sweep": "Head Sweep",
    "Lyre Rush": "Head Rush", "Lyre Vague": "Head Wave", "Lyre Canon": "Head Canon",
    "Lyre Spiral": "Head Spiral", "Lyre Pendule Décalé": "Head Offset Pendulum", "Lyre Cercle Haché": "Head Chopped Circle",
    "Lyre Pendule Haché": "Head Chopped Pendulum", "Lyre Pendule Lent": "Head Slow Pendulum", "Lyre Cercle + Couleur": "Head Circle + Color",
    "Lyre Gobo Spin": "Head Gobo Spin", "Lyre Gobo + Cercle": "Head Gobo + Circle", "Ouvert": "Open",
    "Barre": "Bar", "Anneau": "Ring", "Logo MyStrow": "MyStrow logo",
    "Étoile 4 branches": "4-point star", "Gouttes": "Droplets", "Trois cercles": "Three circles",
    "Feuillage": "Foliage", "Trois palmes": "Three blades", "Vitrail": "Stained glass",
    "Spirale": "Spiral", "Six rayons": "Six rays", "Nuages": "Clouds",
    "Lyre Papillon": "Head Butterfly", "Lyre Éventail": "Head Fan", "Lyre Roue Couleurs": "Head Color Wheel",
    "Lyre CW + Cercle": "Head CW + Circle", "Mouvement": "Movement", "Couleur": "Color",
    "Permut": "Swap", "Lyre": "Moving head", "Mes Effets": "My Effects",
    "Personnalisés": "Custom", "Sinus": "Sine", "Montée": "Ramp up",
    "Descente": "Ramp down", "Un par un": "One by one", "Aléatoire": "Random",
    "Fixe": "Fixed", "Tous": "All", "Pair": "Even",
    "Impair": "Odd", "Ambre": "Amber", "Canal": "Channel",
    "V": "G", "Blanc": "White", "Rouge": "Red",
    "Jaune": "Yellow", "Vert": "Green", "Bleu": "Blue",
    "Violet": "Purple", "Rose": "Pink", "Barre LED": "LED bar",
    "Stroboscope": "Strobe", "Machine a fumee": "Smoke machine", "Machine a brouillard": "Haze machine",
    "Machine a etincelles": "Spark machine", "Lance-flamme": "Flame projector", "Gradateur": "Dimmer",
    "SANS SLOT": "NO SLOT", "VERT": "GREEN", "JAUNE": "YELLOW",
    "BLANC": "WHITE", "Sélec. Tout": "Select all", "Désélec.": "Deselect",
    "Stop Effets": "Stop effects", "Coupe DMX": "DMX cut", "Coupe Vidéo": "Video cut",
    "Horloge": "Clock", "Tout": "All", "Groupe A": "Group A",
    "Groupe B": "Group B", "Groupe C": "Group C", "Groupe D": "Group D",
    "Groupe E": "Group E", "Groupe F": "Group F", "Groupe G": "Group G",
    "Groupe H": "Group H", "Public": "Audience", "Lyres": "Moving heads",
    "Barres": "Bars", "Strobos": "Strobes", "Fumée": "Smoke",
    "Éteint": "Off",
  };

  // Textes construits avec des nombres, des dates ou des noms.
  const RULES = [
    [/^(\d+) min (\d+) s$/, "$1 min $2 s"],
    [/^(.+) · achat unique$/, "$1 · one-time purchase"],
    [/^Il reste (\d+) min (\d+) s avant que la sortie DMX se coupe\.\n?/, "$1 min $2 s left before the DMX output stops.\n"],
    [/^Fader (\d+) · page (\d+)$/, "Fader $1 · page $2"],
    [/^COUCHE (\d+) \/ (\d+)$/, "LAYER $1 / $2"],
    [/^REC : pas de colonne MEM sur cette page, les mémoires sont en page (\d+) \(◀ ▶\)$/, "REC: no MEM column on this page, memories are on page $1 (◀ ▶)"],
    [/^(\d+) projecteurs?$/, (m, n) => n + (n === "1" ? " fixture" : " fixtures")],
    [/^(\d+) proj\.$/, "$1 fix."], [/^(\d+) mém\.$/, "$1 mem."], [/^(\d+) pos\.$/, "$1 pos."],
    [/^(\d+) effets?$/, (m, n) => n + (n === "1" ? " effect" : " effects")],
    [/^(\d+) effets? perso$/, (m, n) => n + " custom effect" + (n === "1" ? "" : "s")],
    [/^(\d+) TEMPS$/, "$1 BEATS"], [/^(\d+) temps$/, "$1 beats"],
    [/^Effet « (.+) » enregistré$/, "Effect “$1” saved"], [/^« (.+) » enregistré dans votre bibliothèque$/, "“$1” saved to your library"],
    [/^Supprimer « (.+) » \?$/, "Delete “$1”?"], [/^✎ Modifier « (.+) »$/, "✎ Edit “$1”"], [/^Position « (.+) » enregistrée$/, "Position “$1” saved"],
    [/^Mémoire (\d+)\.(\d+)$/, "Memory $1.$2"], [/^Position (\d+)\.(\d+)(.*)$/, "Position $1.$2$3"], [/^Pad FX (\d+)\.(\d+)$/, "FX pad $1.$2"],
    [/^(\d+) projecteur\(s\) ajouté\(s\)\.$/, "$1 fixture(s) added."],
    [/^(\d+) projecteurs? patchés?$/, (m, n) => n + (n === "1" ? " fixture patched" : " fixtures patched")],
    [/^(\d+)\. (.+)$/, (m, n, t) => (DICT[t] ? n + ". " + DICT[t] : m)],
    [/^Nom de la zone du groupe (.+)$/, "Name of group $1's area"], [/^Mém\. (\d+)$/, "Mem. $1"],
  ];

  // Morceaux connus à l'intérieur d'un texte plus long (le plus long d'abord).
  const FRAG = [
    ["CANAUX AVANCÉS", "ADVANCED CHANNELS"],
    ["Interface USB connectée ✓", "USB interface connected ✓"], ["Node Art-Net connecté ✓", "Art-Net node connected ✓"],
    ["Licence active jusqu'au", "License active until"], ["Construite le", "Built on"], ["MyStrow tablette", "MyStrow tablet"],
    ["Interface USB · OK", "USB interface · OK"], ["Interface USB · coupée", "USB interface · off"], [" · coupée", " · off"],
    ["Node Art-Net", "Art-Net node"], ["interface USB-DMX", "USB-DMX interface"], ["node Art-Net", "Art-Net node"], ["Sortie DMX :", "DMX output:"], ["Sortie :", "Output:"], ["Dernière erreur :", "Last error:"],
    ["trames envoyées,", "frames sent,"], ["erreurs", "errors"], ["Nouvel essai toutes les 20 s.", "Retrying every 20 s."],
    ["Config envoyée le", "Config sent on"], ["depuis «", "from “"], ["projecteurs ·", "fixtures ·"], ["mémoires ·", "memories ·"],
    ["effets ·", "effects ·"], ["positions", "positions"], ["Connectée depuis", "Connected for"], ["Hors ligne depuis", "Offline for"],
    ["nouvel essai dans", "retrying in"], ["Reconnexion à", "Reconnecting to"], ["Connexion à", "Connecting to"],
    ["Erreur du compte (", "Account error ("], ["Erreur :", "Error:"], ["Import impossible :", "Import failed:"],
    ["Lecture impossible :", "Can't play:"], ["Recherche impossible :", "Search failed:"], ["Liste USB impossible :", "Can't list USB:"],
    ["Liste des réseaux impossible :", "Can't list networks:"], ["Réseaux de la tablette :", "Tablet networks:"], ["Vu par le noyau :", "Seen by the system:"],
    ["Node trouvé :", "Node found:"], ["Node choisi :", "Node selected:"], ["projecteur(s) du patch mis à jour.", "patch fixture(s) updated."],
    ["projecteur(s) déjà patchés restent dans le patch.", "already-patched fixture(s) stay in the patch."],
    ["projecteurs dans la bibliothèque", "fixtures in the library"], ["créé(s) sur la tablette", "created on the tablet"],
    ["fixtures MyStrow à jour du", "MyStrow fixtures updated on"], ["Les changements de «", "Changes to “"], ["» ne sont pas enregistrés.", "” are not saved."],
    ["Trop d’essais. Réessayez dans", "Too many attempts. Try again in"], ["il y a", "ago"], ["(non reconnu)", "(not recognized)"],
    ["S'il n'est pas dans la même plage d'adresses (node en 2.0.0.15 sur une box en 192.168.1.x), ", "If it isn't in the same address range (node at 2.0.0.15 on a router at 192.168.1.x), "],
    ["la tablette l'atteint quand même, en diffusion. Pour un show, préférez un routeur dédié réglé en 2.0.0.x.", "the tablet still reaches it by broadcast. For a show, use a dedicated router set to 2.0.0.x."],
    ["Symétrie : les lyres de l'autre côté partent en miroir", "Symmetry: moving heads on the other side mirror the movement"],
    ["Enregistrer le projecteur", "Save the fixture"], [" canaux)", " channels)"], ["(1 canal)", "(1 channel)"],
    ["Lyre LED ·", "LED moving head ·"], ["Shutter Vitesse", "Shutter Speed"], ["· lyre (", "· moving head ("], ["Gradateur ·", "Dimmer ·"], ["Toucher :", "Tap:"], ["PAGE", "PAGE"],
  ].sort((a, b) => b[0].length - a[0].length);

  const LETTER = /[a-zA-ZÀ-ÿ]/;
  const cache = new Map();
  function T(src) {
    if (!src || !LETTER.test(src)) return src;
    if (cache.has(src)) return cache.get(src);
    const lead = src.match(/^\s*/)[0], trail = src.match(/\s*$/)[0];
    const core = src.trim().replace(/[ \t]+/g, " ");
    let out = DICT[core];
    if (out === undefined) {
      for (const [re, rep] of RULES) { if (re.test(core)) { out = core.replace(re, rep); break; } }
    }
    if (out === undefined) {
      let s = core, hit = false;
      for (const [fr, en] of FRAG) if (s.includes(fr)) { s = s.split(fr).join(en); hit = true; }
      if (!hit && s.includes(" · ")) { const parts = s.split(" · ").map((x) => DICT[x] ?? x); if (parts.join(" · ") !== s) { s = parts.join(" · "); hit = true; } }
      // Une ligne d'un texte à plusieurs lignes peut être connue telle quelle.
      if (s.includes("\n")) { const parts = s.split("\n").map((l) => DICT[l.trim()] ?? l); if (parts.join("\n") !== s) { s = parts.join("\n"); hit = true; } }
      out = hit ? s : core;
    }
    const res = out === core ? src : lead + out + trail;
    if (cache.size < 5000) cache.set(src, res);
    return res;
  }
  window.T = T;

  const SKIP = { SCRIPT: 1, STYLE: 1, TEXTAREA: 1, NOSCRIPT: 1 };
  const ATTRS = ["title", "placeholder", "aria-label"];
  function doText(n) {
    const p = n.parentNode;
    if (!p || SKIP[p.nodeName] || p.isContentEditable) return;
    const v = n.nodeValue, t = T(v);
    if (t !== v) n.nodeValue = t;
  }
  function doEl(el) {
    if (SKIP[el.nodeName]) return;
    for (const a of ATTRS) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v) { const t = T(v); if (t !== v) el.setAttribute(a, t); }
    }
  }
  function walk(root) {
    if (root.nodeType === 3) return doText(root);
    if (root.nodeType !== 1 && root.nodeType !== 9 && root.nodeType !== 11) return;
    if (root.nodeType === 1) doEl(root);
    const it = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    let n;
    while ((n = it.nextNode())) { if (n.nodeType === 3) doText(n); else doEl(n); }
  }
  const mo = new MutationObserver((list) => {
    for (const m of list) {
      if (m.type === "characterData") doText(m.target);
      else if (m.type === "attributes") doEl(m.target);
      else m.addedNodes.forEach(walk);
    }
  });
  function start() {
    walk(document.documentElement);
    mo.observe(document.documentElement, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    // Textes écrits en CSS (voyants) : réécrits ici.
    const st = document.createElement("style");
    st.textContent = "#conn-status.ok::after{content:'ONLINE'!important}#conn-status.err::after{content:'OFFLINE'!important}" +
      "body.solo #conn-status.ok::after{content:'DMX OK'!important}body.solo #conn-status.err::after{content:'DMX OFF'!important}" +
      "#seq-list:empty::after{content:'Tap “+ ADD” to pick tracks on the tablet.'!important}";
    document.head.appendChild(st);
  }
  if (document.documentElement) start();
})();
