"""
amp_migration.py — Outil « Amplitudes 3.1.91 » : AMP Pan/Tilt × 4.

Pourquoi cet outil existe
-------------------------
La 3.1.91 (du 3 au 10 septembre 2026) convertissait AMP 100 en ±32768 sur les
couches Pan / Tilt / Pan-Tilt. La 3.1.92 est revenue à ±8192. Tout effet réglé
pendant cette semaine-là bouge donc 4 fois moins depuis : un AMP 70 doit
devenir 280 (le plafond de la colonne est à 400 depuis la 3.1.93).

Aucune migration automatique n'est possible : les couches ne portent ni date
ni version, et un AMP 70 réglé AVANT la 3.1.91 est déjà juste. Seul
l'utilisateur sait quels effets datent de cette semaine-là — il les coche par
NOM, et l'outil convertit ce nom partout où une copie des couches vit :

  * effets personnalisés      ~/.mystrow_custom_effects.json
  * bibliothèque d'effets     ~/.mystrow_effect_library.json
  * boutons E1-E8             ~/.mystrow_effect_assignments.json
  * pads FX, mémoires         ~/.maestro_akai_config.json  ET  chaque .tui
  * clips des REC Lumière     chaque .tui (et les exports .lrec)

⚠️ Les shows sur disque sont indispensables : ouvrir un .tui RECHARGE les pads
FX du fichier (`_apply_show_positions_fx`), et chaque clip Effet garde une
COPIE FIGÉE de ses couches. Convertir la seule config machine ne suffit pas.

Règles de conversion (voir `a_convertir`)
-----------------------------------------
  * couche Pan / Tilt / Pan-Tilt uniquement — ailleurs AMP est une intensité ;
  * AMP entre 1 et 100 : au-delà, la couche a été réglée après la 3.1.93
    (la colonne plafonnait à 100 en 3.1.91) ;
  * pas déjà marquée `amp_x4` : relancer l'outil ne multiplie jamais deux fois.

⚠️ Les couches sont REMPLACÉES par des copies, jamais modifiées sur place :
plusieurs entrepôts partagent la même liste en mémoire (une mémoire copie la
config de son bouton par `dict(...)`, un bouton peut pointer sur les couches de
BUILTIN_EFFECTS). Une modification en place convertirait deux fois (× 16) et
toucherait les effets intégrés.
"""

import json
import os
import shutil

from i18n import tr

PT_ATTRS = ("Pan", "Tilt", "Pan/Tilt")
MARQUE   = "amp_x4"
FACTEUR  = 4
PLAFOND  = 400    # LayerRow._AMP_MAX_PT
SEUIL    = 100    # plafond de la colonne AMP en 3.1.91
SUFFIXE_SAUVEGARDE = ".avant-amp-x4.bak"

# (clé de la liste de couches, clé du nom de l'effet) — configs d'effet d'un côté,
# clips de REC Lumière de l'autre.
_PORTEURS = (("layers", "name"), ("effect_layers", "effect_name"))


# ── Logique pure (sans Qt) ────────────────────────────────────────────────────

def _taille(couche):
    # Même repli que EffectLayer.from_dict.
    return couche.get("size", couche.get("amplitude", 100))


def a_convertir(couche) -> bool:
    if not isinstance(couche, dict) or couche.get("attribute") not in PT_ATTRS:
        return False
    if couche.get(MARQUE):
        return False
    t = _taille(couche)
    return isinstance(t, (int, float)) and not isinstance(t, bool) and 0 < t <= SEUIL


def _est_liste_couches(v) -> bool:
    return isinstance(v, list) and any(isinstance(c, dict) and "attribute" in c for c in v)


def porteurs(obj):
    """Tous les (dict, clé, nom d'effet) qui portent une liste de couches dans obj.

    Parcours générique d'une structure JSON : un seul code pour les boutons, les
    pads, les mémoires, la bibliothèque, les clips d'un .tui ou d'un .lrec — et
    pour les entrepôts qu'on ajoutera demain."""
    if isinstance(obj, dict):
        for cle, cle_nom in _PORTEURS:
            if _est_liste_couches(obj.get(cle)):
                yield obj, cle, str(obj.get(cle_nom) or obj.get("name") or "")
        for v in list(obj.values()):
            yield from porteurs(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from porteurs(v)


def recenser(racines, bilan=None) -> dict:
    """{nom: {"amps": set, "n": nombre d'emplacements}} des couches à convertir."""
    bilan = {} if bilan is None else bilan
    vues = set()
    for racine in racines:
        for porteur, cle, nom in porteurs(racine):
            couches = porteur[cle]
            if id(couches) in vues:
                continue
            vues.add(id(couches))
            amps = {_taille(c) for c in couches if a_convertir(c)}
            if not amps:
                continue
            entree = bilan.setdefault(nom, {"amps": set(), "n": 0})
            entree["amps"] |= amps
            entree["n"] += 1
    return bilan


def convertir(obj, noms) -> int:
    """Multiplie par 4 l'AMP des couches Pan/Tilt des effets `noms` dans obj.

    Renvoie le nombre de couches converties."""
    noms = set(noms)
    n = 0
    # list() : on remplace des valeurs pendant le parcours. Un même porteur peut
    # sortir deux fois (référencé de deux endroits) : on relit `porteur[cle]` à
    # chaque fois, la seconde trouve des couches déjà marquées.
    for porteur, cle, nom in list(porteurs(obj)):
        if nom not in noms:
            continue
        couches = porteur[cle]
        if not any(a_convertir(c) for c in couches):
            continue
        neuves = []
        for c in couches:
            if a_convertir(c):
                c = dict(c)
                c["size"] = min(PLAFOND, int(round(_taille(c) * FACTEUR)))
                c.pop("amplitude", None)
                c[MARQUE] = True
                n += 1
            neuves.append(c)
        porteur[cle] = neuves
    return n


def lire_json(chemin):
    # Le .tui est écrit par `save_show` sans encodage explicite (ASCII échappé),
    # les autres fichiers en UTF-8 : on essaie UTF-8 puis l'encodage local.
    try:
        with open(chemin, "r", encoding="utf-8") as f:
            return json.load(f)
    except UnicodeDecodeError:
        with open(chemin, "r") as f:
            return json.load(f)


def sauvegarder_original(chemin):
    """Copie le fichier à côté de lui, une seule fois : relancer l'outil ne doit
    pas écraser la copie de l'ORIGINAL par une version déjà convertie."""
    copie = chemin + SUFFIXE_SAUVEGARDE
    if os.path.exists(chemin) and not os.path.exists(copie):
        shutil.copy2(chemin, copie)


def ecrire_json(chemin, data):
    tmp = chemin + ".tmp"
    if chemin.lower().endswith(".tui"):
        # Même écriture que MainWindow.save_show : relu sans encodage explicite.
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
    else:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, chemin)


def convertir_fichier(chemin, noms) -> int:
    data = lire_json(chemin)
    n = convertir(data, noms)
    if n:
        sauvegarder_original(chemin)
        ecrire_json(chemin, data)
    return n


def chercher_shows(dossier):
    """.tui et .lrec d'un dossier et de ses sous-dossiers."""
    trouves = []
    for racine, _dirs, fichiers in os.walk(dossier):
        for nom in fichiers:
            if nom.lower().endswith((".tui", ".lrec")):
                trouves.append(os.path.join(racine, nom))
    return sorted(trouves)


def _meme_fichier(a, b) -> bool:
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == \
        os.path.normcase(os.path.abspath(b))


def sources_memoire(mw):
    """Entrepôts vivants de la fenêtre principale — convertis en mémoire puis
    réécrits par leurs propres fonctions de sauvegarde (sinon la prochaine
    sauvegarde de l'app écraserait la conversion)."""
    seq = getattr(mw, "seq", None)
    return [
        getattr(mw, "_button_effect_configs", {}),
        getattr(mw, "_effect_library_configs", {}),
        getattr(mw, "fx_pads", []),
        getattr(mw, "memories", []),
        getattr(seq, "sequences", {}) if seq is not None else {},
        getattr(mw, "active_effect_config", {}),
    ]


# ── Fenêtre ───────────────────────────────────────────────────────────────────

from PySide6.QtCore import Qt, QObject, QEvent, QTimer
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QPushButton,
                               QFileDialog, QMessageBox)


# ── Déclencheur caché : Ctrl + clic long ─────────────────────────────────────

DUREE_CLIC_LONG_MS = 1500


class _DeclencheurCache(QObject):
    """Ctrl (Cmd sur Mac) + bouton gauche TENU sur un bouton → `action`.

    Le clic normal du bouton reste intact : relâcher avant la fin du délai, ou
    appuyer sans Ctrl, laisse passer le `clicked` habituel. Quand le délai
    expire, le bouton est relevé (`setDown(False)`) AVANT d'ouvrir l'outil :
    QAbstractButton n'émet `clicked` au relâchement que s'il est encore enfoncé,
    donc les paramètres AKAI ne s'ouvrent pas derrière."""

    def __init__(self, bouton, action):
        super().__init__(bouton)
        self._bouton = bouton
        self._action = action
        self._minuteur = QTimer(self)
        self._minuteur.setSingleShot(True)
        self._minuteur.setInterval(DUREE_CLIC_LONG_MS)
        self._minuteur.timeout.connect(self._declencher)

    def eventFilter(self, obj, event):
        t = event.type()
        if t == QEvent.MouseButtonPress:
            if (event.button() == Qt.LeftButton
                    and event.modifiers() & Qt.ControlModifier):
                self._minuteur.start()
            else:
                self._minuteur.stop()
        elif t in (QEvent.MouseButtonRelease, QEvent.Leave, QEvent.Hide):
            self._minuteur.stop()
        return False

    def _declencher(self):
        self._bouton.setDown(False)
        # Hors du minuteur : la boîte est modale.
        QTimer.singleShot(0, self._action)


def armer_declencheur_cache(bouton, action):
    filtre = _DeclencheurCache(bouton, action)
    bouton.installEventFilter(filtre)
    return filtre


class AmpX4Dialog(QDialog):

    def __init__(self, main_window):
        super().__init__(main_window)
        from effect_editor import _CUSTOM_EFFECTS_FILE
        self._mw = main_window
        self._fichier_custom = str(_CUSTOM_EFFECTS_FILE)
        self._fichiers = []          # shows / REC ajoutés par l'utilisateur
        self._illisibles = []

        self.setWindowTitle(tr("ampx4_title"))
        self.resize(560, 480)
        self.setStyleSheet(
            "QDialog { background:#161616; }"
            "QLabel { color:#ddd; font-size:12px; }"
            "QListWidget { background:#111; color:#ddd; border:1px solid #333;"
            " border-radius:4px; font-size:12px; }"
            "QListWidget::item { padding:4px; }"
            "QListWidget::indicator { width:14px; height:14px; border:1px solid #777;"
            " border-radius:3px; background:#1c1c1c; }"
            "QListWidget::indicator:checked { background:#00d4ff; border-color:#00d4ff; }"
            "QPushButton { background:#222; color:#eee; border:1px solid #333;"
            " border-radius:5px; padding:6px 14px; }"
            "QPushButton:hover { border-color:#00d4ff; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        aide = QLabel(tr("ampx4_help"))
        aide.setWordWrap(True)
        lay.addWidget(aide)

        # Shows et REC à convertir
        lay.addWidget(QLabel(tr("ampx4_files_label")))
        self._liste_fichiers = QListWidget()
        self._liste_fichiers.setMaximumHeight(80)
        lay.addWidget(self._liste_fichiers)
        rang = QHBoxLayout()
        b_fichiers = QPushButton(tr("ampx4_add_files"))
        b_dossier  = QPushButton(tr("ampx4_add_folder"))
        b_fichiers.clicked.connect(self._ajouter_fichiers)
        b_dossier.clicked.connect(self._ajouter_dossier)
        rang.addWidget(b_fichiers)
        rang.addWidget(b_dossier)
        note = QLabel(tr("ampx4_open_show_note"))
        note.setStyleSheet("color:#888; font-size:11px;")
        rang.addWidget(note)
        rang.addStretch(1)
        lay.addLayout(rang)

        # Effets
        lay.addWidget(QLabel(tr("ampx4_effects_label")))
        self._liste_effets = QListWidget()
        lay.addWidget(self._liste_effets, 1)
        self._vide = QLabel(tr("ampx4_none"))
        self._vide.setWordWrap(True)
        self._vide.setStyleSheet("color:#888; font-size:11px;")
        lay.addWidget(self._vide)

        rang = QHBoxLayout()
        b_tout  = QPushButton(tr("ampx4_check_all"))
        b_aucun = QPushButton(tr("ampx4_uncheck_all"))
        b_tout.clicked.connect(lambda: self._cocher(True))
        b_aucun.clicked.connect(lambda: self._cocher(False))
        rang.addWidget(b_tout)
        rang.addWidget(b_aucun)
        rang.addStretch(1)
        b_fermer = QPushButton(tr("ampx4_close"))
        self._b_convertir = QPushButton(tr("ampx4_convert"))
        self._b_convertir.setStyleSheet("background:#0a5; color:#fff; border:none;")
        b_fermer.clicked.connect(self.reject)
        self._b_convertir.clicked.connect(self._convertir)
        rang.addWidget(b_fermer)
        rang.addWidget(self._b_convertir)
        lay.addLayout(rang)

        self._recenser()

    # ── Recensement ──────────────────────────────────────────────────────────

    def _fichiers_disque(self):
        """Fichiers à traiter sur disque. Le show ouvert en est retiré : il est
        converti en mémoire, et le réécrire sur disque serait écrasé à la
        prochaine sauvegarde (ou écraserait des modifications non enregistrées)."""
        ouvert = getattr(self._mw, "current_show_path", None)
        return [f for f in self._fichiers if not _meme_fichier(f, ouvert)]

    def _recenser(self):
        coches = {self._liste_effets.item(i).data(Qt.UserRole)
                  for i in range(self._liste_effets.count())
                  if self._liste_effets.item(i).checkState() == Qt.Checked}
        bilan = recenser(sources_memoire(self._mw))
        self._illisibles = []
        for chemin in [self._fichier_custom] + self._fichiers_disque():
            if not os.path.exists(chemin):
                continue
            try:
                recenser([lire_json(chemin)], bilan)
            except Exception:
                self._illisibles.append(chemin)

        self._liste_effets.clear()
        for nom in sorted(bilan, key=str.lower):
            entree = bilan[nom]
            amps = ", ".join(str(int(a)) if float(a).is_integer() else str(a)
                             for a in sorted(entree["amps"]))
            item = QListWidgetItem(tr("ampx4_item", name=nom or "?", amps=amps,
                                      n=entree["n"]))
            item.setData(Qt.UserRole, nom)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if nom in coches else Qt.Unchecked)
            self._liste_effets.addItem(item)
        self._vide.setVisible(not bilan)
        self._b_convertir.setEnabled(bool(bilan))

    def _ajouter(self, chemins):
        for c in chemins:
            if not any(_meme_fichier(c, f) for f in self._fichiers):
                self._fichiers.append(c)
                self._liste_fichiers.addItem(c)
        self._recenser()

    def _ajouter_fichiers(self):
        chemins, _ = QFileDialog.getOpenFileNames(
            self, tr("ampx4_add_files"), "", tr("ampx4_files_filter"))
        if chemins:
            self._ajouter(chemins)

    def _ajouter_dossier(self):
        dossier = QFileDialog.getExistingDirectory(self, tr("ampx4_add_folder"))
        if dossier:
            self._ajouter(chercher_shows(dossier))

    def _cocher(self, oui):
        for i in range(self._liste_effets.count()):
            self._liste_effets.item(i).setCheckState(Qt.Checked if oui else Qt.Unchecked)

    # ── Conversion ───────────────────────────────────────────────────────────

    def _convertir(self):
        noms = [self._liste_effets.item(i).data(Qt.UserRole)
                for i in range(self._liste_effets.count())
                if self._liste_effets.item(i).checkState() == Qt.Checked]
        if not noms:
            return
        if QMessageBox.question(
                self, tr("ampx4_title"), tr("ampx4_confirm", n=len(noms)),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return

        mw = self._mw
        home = os.path.expanduser("~")
        # Copies des fichiers de la machine AVANT que l'app ne les réécrive.
        for f in (".mystrow_effect_assignments.json", ".mystrow_effect_library.json",
                  ".maestro_akai_config.json"):
            try:
                sauvegarder_original(os.path.join(home, f))
            except Exception:
                pass

        boutons, biblio, pads_fx, memoires, sequences, actif = sources_memoire(mw)
        n_machine = convertir(boutons, noms) + convertir(biblio, noms) + convertir(actif, noms)
        # Pads FX, mémoires et clips voyagent AUSSI dans le .tui du show ouvert.
        n_show = convertir(pads_fx, noms) + convertir(memoires, noms) + \
            convertir(sequences, noms)
        n_couches = n_machine + n_show

        for sauver in ("_save_effect_assignments", "_save_effect_library",
                       "_save_akai_config_auto"):
            fn = getattr(mw, sauver, None)
            if fn:
                try:
                    fn()
                except Exception:
                    pass

        seq = getattr(mw, "seq", None)
        show_a_enregistrer = bool(
            n_show and seq is not None
            and (getattr(mw, "current_show_path", None) or getattr(seq, "sequences", None)))
        if show_a_enregistrer:
            seq.is_dirty = True

        n_fichiers, erreurs = 0, []
        for chemin in [self._fichier_custom] + self._fichiers_disque():
            if not os.path.exists(chemin):
                continue
            try:
                n = convertir_fichier(chemin, noms)
            except Exception as e:
                erreurs.append(f"{os.path.basename(chemin)} : {e}")
                continue
            n_couches += n
            if n and chemin != self._fichier_custom:
                n_fichiers += 1

        msg = tr("ampx4_done", layers=n_couches, files=n_fichiers)
        if show_a_enregistrer:
            msg += "\n\n" + tr("ampx4_save_show")
        if erreurs:
            msg += "\n\n" + tr("ampx4_errors") + "\n" + "\n".join(erreurs)
        QMessageBox.information(self, tr("ampx4_title"), msg)
        self._recenser()
