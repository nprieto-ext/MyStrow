"""
fixture_share — Partage communautaire des fixtures importées (MyStrow).

Quand un utilisateur importe une fixture (XML QLC+/GrandMA, .mft…), il peut la
proposer à la bibliothèque commune. Trois garde-fous juridiques encadrent ce
partage, en plus d'une modération humaine :

  1. Déclaration de provenance  — l'utilisateur choisit la source du fichier et
     coche une attestation ("j'ai le droit de partager ce profil").
  2. Filtrage par licence        — les sources non redistribuables (fichier
     constructeur, GDTF Share, origine inconnue) ne peuvent PAS être partagées :
     import local uniquement.
  3. Quota anti-dump             — au plus DAILY_SHARE_QUOTA fixtures partagées
     par compte et par jour, ce qui écarte le scénario d'extraction
     substantielle d'une base tierce (directive 96/9/CE).

Rien n'est publié directement : la soumission atterrit dans la collection
Firestore `fixture_submissions` avec le statut "pending". Un administrateur
valide ou refuse depuis l'admin panel, et seule l'approbation écrit dans
`gdtf_fixtures`.

Le serveur (Cloud Function `fixture_submit`) refait TOUTES ces vérifications :
les contrôles de ce module sont là pour le confort d'usage, pas pour la sécurité.
"""

import hashlib
import json
import time
from datetime import date
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QCheckBox, QListWidget, QListWidgetItem, QMessageBox, QWidget,
)
from PySide6.QtCore import Qt, QObject, QThread, Signal

from i18n import tr

# Fichier d'état local (quota + fixtures déjà proposées)
SHARE_STATE_FILE = Path.home() / ".mystrow_fixture_share.json"

# Quota anti-dump : nombre maximum de fixtures proposées par jour et par compte.
# Volontairement bas : une contribution normale porte sur 1 à 3 appareils.
DAILY_SHARE_QUOTA = 20

# Clause CGV encadrant les contributions (garanties de l'utilisateur, licence
# concédée, sources exclues, retrait). L'ancre #contributions existe dans les
# cinq versions de la page ; le français seul a un slug différent.
_TERMS_URLS = {
    "fr": "https://mystrow.fr/cgv#contributions",
    "en": "https://mystrow.fr/en/terms#contributions",
    "es": "https://mystrow.fr/es/terms#contributions",
    "de": "https://mystrow.fr/de/terms#contributions",
    "pt": "https://mystrow.fr/pt/terms#contributions",
}


def contrib_terms_url() -> str:
    """URL de la clause de contribution dans la langue courante de l'interface."""
    from i18n import get_language
    return _TERMS_URLS.get(get_language(), _TERMS_URLS["fr"])


# ──────────────────────────────────────────────────────────────────────────────
# Politique de licence par provenance
# ──────────────────────────────────────────────────────────────────────────────

class SourcePolicy:
    """Règle de partage attachée à une provenance déclarée."""

    __slots__ = ("key", "label_key", "shareable", "license", "attribution", "note_key")

    def __init__(self, key, label_key, shareable, license_id, attribution, note_key):
        self.key         = key
        self.label_key   = label_key
        self.shareable   = shareable
        self.license     = license_id
        self.attribution = attribution
        self.note_key    = note_key

    @property
    def label(self) -> str:
        return tr(self.label_key)

    @property
    def note(self) -> str:
        return tr(self.note_key)


# L'ordre définit l'ordre d'affichage dans la combo.
SOURCE_POLICIES = [
    SourcePolicy(
        "perso", "fs_src_perso", True, "MyStrow-Community",
        "", "fs_note_perso",
    ),
    SourcePolicy(
        "ofl", "fs_src_ofl", True, "CC0-1.0",
        "Open Fixture Library — CC0 1.0", "fs_note_ofl",
    ),
    SourcePolicy(
        "qlcplus", "fs_src_qlcplus", True, "Apache-2.0",
        "QLC+ Fixture Library — Apache 2.0", "fs_note_qlcplus",
    ),
    SourcePolicy(
        "gdtf_share", "fs_src_gdtf", False, "",
        "", "fs_note_gdtf",
    ),
    SourcePolicy(
        "manufacturer", "fs_src_manufacturer", False, "",
        "", "fs_note_manufacturer",
    ),
    SourcePolicy(
        "unknown", "fs_src_unknown", False, "",
        "", "fs_note_unknown",
    ),
]

POLICY_BY_KEY = {p.key: p for p in SOURCE_POLICIES}

# Provenance proposée par défaut selon le champ "source" produit par les parsers.
# Tout ce qui n'est pas identifié avec certitude retombe sur "unknown", qui n'est
# pas partageable : le défaut prudent est de NE PAS diffuser.
_PARSER_SOURCE_DEFAULT = {
    "ofl":     "ofl",
    "qlcplus": "qlcplus",
    "user":    "perso",
    "custom":  "perso",
    "generic": "perso",
    "mystrow": "perso",
    "ma2":     "unknown",
    "ma3":     "unknown",
}


def default_source_for(fixture: dict) -> str:
    """
    Provenance pré-sélectionnée dans le dialogue pour une fixture importée.

    `origin_source` est prioritaire : certains flux d'import écrasent `source`
    avec "user" pour marquer la fixture comme locale, ce qui ferait passer un
    fichier constructeur pour une création personnelle.
    """
    fixture = fixture or {}
    raw = str(fixture.get("origin_source") or fixture.get("source") or "").lower()
    return _PARSER_SOURCE_DEFAULT.get(raw, "unknown")


def is_shareable(source_key: str) -> bool:
    policy = POLICY_BY_KEY.get(source_key)
    return bool(policy and policy.shareable)


# ──────────────────────────────────────────────────────────────────────────────
# État local : quota journalier et déduplication
# ──────────────────────────────────────────────────────────────────────────────

def _today() -> str:
    return date.today().isoformat()


def load_share_state() -> dict:
    """
    {"day": "YYYY-MM-DD", "count": int, "sent": {fingerprint: timestamp}}
    Le compteur est remis à zéro dès que le jour change.
    """
    state = {"day": _today(), "count": 0, "sent": {}}
    try:
        if SHARE_STATE_FILE.exists():
            loaded = json.loads(SHARE_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                state.update({k: loaded[k] for k in ("day", "count", "sent") if k in loaded})
    except Exception:
        pass
    if state.get("day") != _today():
        state["day"]   = _today()
        state["count"] = 0
    if not isinstance(state.get("sent"), dict):
        state["sent"] = {}
    try:
        state["count"] = int(state.get("count") or 0)
    except (TypeError, ValueError):
        state["count"] = 0
    return state


def save_share_state(state: dict) -> None:
    try:
        SHARE_STATE_FILE.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def remaining_quota() -> int:
    """Nombre de fixtures encore partageables aujourd'hui (indicatif : le serveur tranche)."""
    return max(0, DAILY_SHARE_QUOTA - load_share_state()["count"])


def _record_submission(fingerprints: list, used: int = None,
                       quota_left: int = None) -> None:
    """
    Mémorise les fixtures proposées et met à jour le compteur local.

    `quota_left` vient du serveur, seul détenteur du vrai compteur : il rend
    les doublons écartés, que le client ne sait pas distinguer. On s'aligne
    dessus quand il est fourni.
    """
    state = load_share_state()
    now   = int(time.time())
    for fp in fingerprints:
        state["sent"][fp] = now
    if quota_left is not None:
        state["count"] = max(0, DAILY_SHARE_QUOTA - int(quota_left))
    else:
        state["count"] += len(fingerprints) if used is None else int(used)
    save_share_state(state)


def fixture_fingerprint(fixture: dict) -> str:
    """
    Empreinte déterministe d'une fixture (fabricant + nom + structure des canaux).
    Sert d'ID de document Firestore : deux utilisateurs qui proposent le même
    profil retombent sur le même document, ce qui évite les doublons dans la
    file de modération. Doit rester identique à la version Cloud Function.
    """
    mfr  = str(fixture.get("manufacturer", "")).strip().lower()
    name = str(fixture.get("name", "")).strip().lower()
    profile = fixture.get("profile") or []
    if not profile:
        modes = fixture.get("modes") or []
        if modes and isinstance(modes[0], dict):
            profile = modes[0].get("profile") or []
    chans = "|".join(str(c) for c in profile)
    key = f"{mfr}::{name}::{chans}".encode("utf-8", "replace")
    return hashlib.sha1(key).hexdigest()[:32]


# ──────────────────────────────────────────────────────────────────────────────
# Normalisation du payload
# ──────────────────────────────────────────────────────────────────────────────

# Champs conservés lors de la soumission. Tout le reste (chemin du fichier
# d'origine, XML brut, drapeaux d'UI…) est écarté : on ne transmet que la
# description factuelle du patch DMX, jamais le fichier source.
_PAYLOAD_FIELDS = (
    "name", "manufacturer", "fixture_type", "group",
    "color_wheel_slots", "gobo_wheel_slots", "channel_defaults",
    "physical", "matrix",
    # Noms de canaux du constructeur. Ils manquaient : la fixture partie d'ici
    # avec « Light strip strobe », « Colour Macro »… arrivait chez l'autre
    # utilisateur en colonne de « UNUSED » anonymes. Non seulement il ne
    # comprenait pas ce que fait le canal, mais il ne pouvait même pas le typer
    # à la main — c'est la seule information qui reste quand le type manque.
    "channel_labels", "labels",
)


def build_submission_payload(fixture: dict) -> dict:
    """Réduit une fixture locale à la description normalisée envoyée au serveur."""
    out = {k: fixture[k] for k in _PAYLOAD_FIELDS if fixture.get(k)}
    out["name"]         = str(fixture.get("name", "")).strip()
    out["manufacturer"] = str(fixture.get("manufacturer", "")).strip()
    out["fixture_type"] = fixture.get("fixture_type", "PAR LED")

    def _labels(src, profile):
        """Libellés d'un mode, seulement s'ils correspondent au profil.

        Une liste de longueur différente décalerait tous les noms d'un canal :
        mieux vaut aucun nom qu'un nom faux.
        """
        lb = src.get("labels") or src.get("channel_labels") or []
        return list(lb) if isinstance(lb, list) and len(lb) == len(profile) else []

    modes = fixture.get("modes")
    if isinstance(modes, list) and modes:
        clean_modes = []
        for m in modes:
            if not isinstance(m, dict) or not m.get("profile"):
                continue
            profile = list(m.get("profile") or [])
            lb = _labels(m, profile) or _labels(fixture, profile)
            clean_modes.append({
                "name":         m.get("name", "Mode 1"),
                "channelCount": len(profile),
                "profile":      profile,
                **({"labels": lb} if lb else {}),
            })
        if clean_modes:
            out["modes"] = clean_modes
    if "modes" not in out:
        profile = list(fixture.get("profile") or [])
        lb = _labels(fixture, profile)
        out["modes"] = [{
            "name":         "Mode 1",
            "channelCount": len(profile),
            "profile":      profile,
            **({"labels": lb} if lb else {}),
        }]
    # Ne pas laisser remonter une liste racine qui ne colle pas au premier mode :
    # `_PAYLOAD_FIELDS` la recopie telle quelle, sans rien vérifier.
    _p0 = out["modes"][0]["profile"]
    for _cle in ("channel_labels", "labels"):
        if _cle in out and len(out[_cle] or []) != len(_p0):
            del out[_cle]
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Envoi (thread)
# ──────────────────────────────────────────────────────────────────────────────

class _SubmitWorker(QObject):
    done  = Signal(dict)
    error = Signal(str)

    def __init__(self, fixtures: list, source_key: str):
        super().__init__()
        self._fixtures = fixtures
        self._source   = source_key

    def run(self):
        try:
            from license_manager import _get_fresh_token
            import firebase_client as fc

            token = _get_fresh_token()
            if not token:
                self.error.emit(tr("fs_err_not_signed_in"))
                return
            policy = POLICY_BY_KEY.get(self._source)
            if policy is None or not policy.shareable:
                self.error.emit(tr("fs_err_source_blocked"))
                return

            items = []
            for fx in self._fixtures:
                items.append({
                    "fingerprint": fixture_fingerprint(fx),
                    "fixture":     build_submission_payload(fx),
                })
            result = fc.submit_fixture_contribution(
                items, self._source, policy.license, policy.attribution, token)
            self.done.emit(result or {})
        except Exception as e:
            self.error.emit(str(e))


# ──────────────────────────────────────────────────────────────────────────────
# Dialogue de partage
# ──────────────────────────────────────────────────────────────────────────────

_SS = """
QDialog { background: #141414; color: #e0e0e0; }
QLabel { color: #bbb; font-size: 12px; }
QListWidget {
    background: #1e1e1e; color: #e0e0e0;
    border: 1px solid #333; border-radius: 6px; font-size: 12px;
}
QListWidget::item { padding: 4px 8px; }
QComboBox {
    background: #1e1e1e; color: #fff; border: 1px solid #444;
    border-radius: 6px; padding: 6px 10px; font-size: 12px;
}
QComboBox QAbstractItemView {
    background: #1e1e1e; color: #e0e0e0; selection-background-color: #00d4ff;
    selection-color: #000;
}
QCheckBox { color: #ccc; font-size: 12px; }
QPushButton {
    background: #2a2a2a; color: #ccc; border: 1px solid #4a4a4a;
    border-radius: 6px; padding: 7px 16px; font-size: 12px;
}
QPushButton:hover { border-color: #00d4ff; color: #fff; }
QPushButton:disabled { color: #555; border-color: #2e2e2e; }
"""


class FixtureShareDialog(QDialog):
    """
    Propose de verser les fixtures fraîchement importées à la bibliothèque
    commune. Le bouton de partage ne s'active que si la provenance déclarée est
    redistribuable, que l'attestation est cochée et que le quota le permet.
    """

    def __init__(self, fixtures: list, parent=None):
        super().__init__(parent)
        self._fixtures = [f for f in fixtures if isinstance(f, dict) and f.get("name")]
        self._thread   = None
        self._worker   = None

        self.setWindowTitle(tr("fs_title"))
        self.setStyleSheet(_SS)
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        title = QLabel(tr("fs_headline"))
        title.setStyleSheet("color:#fff; font-size:15px; font-weight:bold;")
        root.addWidget(title)

        intro = QLabel(tr("fs_intro"))
        intro.setWordWrap(True)
        root.addWidget(intro)

        # ── Liste des fixtures à proposer ─────────────────────────────────────
        self._list = QListWidget()
        self._list.setMaximumHeight(140)
        for fx in self._fixtures:
            label = fx.get("name", "")
            mfr   = fx.get("manufacturer", "")
            if mfr:
                label = f"{mfr} — {label}"
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, fx)
            self._list.addItem(item)
        self._list.itemChanged.connect(lambda *_: self._refresh_state())
        root.addWidget(self._list)

        # ── Provenance déclarée ───────────────────────────────────────────────
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(tr("fs_source_label"))
        lbl.setStyleSheet("color:#fff; font-size:12px; font-weight:bold;")
        row.addWidget(lbl)
        self._combo = QComboBox()
        for policy in SOURCE_POLICIES:
            self._combo.addItem(policy.label, policy.key)
        default_key = default_source_for(self._fixtures[0]) if self._fixtures else "unknown"
        idx = self._combo.findData(default_key)
        self._combo.setCurrentIndex(idx if idx >= 0 else self._combo.count() - 1)
        self._combo.currentIndexChanged.connect(lambda *_: self._refresh_state())
        row.addWidget(self._combo, 1)
        root.addLayout(row)

        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setStyleSheet(
            "font-size:11px; border-radius:5px; padding:7px 10px;")
        root.addWidget(self._note)

        # ── Attestation ───────────────────────────────────────────────────────
        self._attest = QCheckBox(tr("fs_attestation"))
        self._attest.setStyleSheet("QCheckBox { font-size:12px; }")
        self._attest.stateChanged.connect(lambda *_: self._refresh_state())
        root.addWidget(self._attest)

        # La clause doit être lisible au moment où l'utilisateur atteste, pas
        # seulement enfouie dans les CGV acceptées à l'achat.
        terms = QLabel(
            f'<a href="{contrib_terms_url()}" style="color:#00d4ff; text-decoration:none;">'
            f'{tr("fs_terms_link")} →</a>'
        )
        terms.setOpenExternalLinks(True)
        terms.setStyleSheet("font-size:11px;")
        root.addWidget(terms)

        self._quota_lbl = QLabel("")
        self._quota_lbl.setStyleSheet("color:#777; font-size:11px;")
        root.addWidget(self._quota_lbl)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#44aaee; font-size:11px;")
        root.addWidget(self._status)

        # ── Boutons ───────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._btn_skip = QPushButton(tr("fs_keep_local"))
        self._btn_skip.clicked.connect(self.reject)
        btn_row.addWidget(self._btn_skip)
        self._btn_send = QPushButton(tr("fs_submit"))
        self._btn_send.setStyleSheet(
            "QPushButton { background:#1a3a2a; color:#44cc88;"
            " border:1px solid #44cc8844; font-weight:bold; }"
            "QPushButton:hover:enabled { border-color:#44cc88; color:#66ee99; }"
            "QPushButton:disabled { background:#1e1e1e; color:#555;"
            " border-color:#2e2e2e; }"
        )
        self._btn_send.clicked.connect(self._submit)
        btn_row.addWidget(self._btn_send)
        root.addLayout(btn_row)

        self._refresh_state()

    # ── État de l'UI ──────────────────────────────────────────────────────────

    def _checked_fixtures(self) -> list:
        out = []
        for i in range(self._list.count()):
            item = self._list.item(i)
            if item.checkState() == Qt.Checked:
                out.append(item.data(Qt.UserRole))
        return out

    def _refresh_state(self):
        policy = POLICY_BY_KEY.get(self._combo.currentData())
        n      = len(self._checked_fixtures())
        left   = remaining_quota()

        if policy is None:
            self._note.setText("")
        else:
            self._note.setText(policy.note)
            if policy.shareable:
                self._note.setStyleSheet(
                    "font-size:11px; border-radius:5px; padding:7px 10px;"
                    " color:#88cc99; background:#161f16; border:1px solid #2a3a2a;")
            else:
                self._note.setStyleSheet(
                    "font-size:11px; border-radius:5px; padding:7px 10px;"
                    " color:#eebb66; background:#241d12; border:1px solid #4a3a1a;")

        self._quota_lbl.setText(tr("fs_quota", left=left, total=DAILY_SHARE_QUOTA))

        blocked = policy is None or not policy.shareable
        self._attest.setEnabled(not blocked)
        over_quota = n > left
        if blocked:
            self._btn_send.setText(tr("fs_submit_blocked"))
        elif over_quota:
            self._btn_send.setText(tr("fs_submit_over_quota"))
        else:
            self._btn_send.setText(tr("fs_submit"))
        self._btn_send.setEnabled(
            not blocked and n > 0 and not over_quota and self._attest.isChecked())

    # ── Envoi ─────────────────────────────────────────────────────────────────

    def _submit(self):
        fixtures = self._checked_fixtures()
        if not fixtures:
            return
        source_key = self._combo.currentData()

        self._btn_send.setEnabled(False)
        self._btn_send.setText(tr("fs_sending"))
        self._status.setStyleSheet("color:#44aaee; font-size:11px;")
        self._status.setText(tr("fs_sending"))

        thread = QThread(self)
        worker = _SubmitWorker(fixtures, source_key)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_done)
        worker.error.connect(self._on_error)
        # Références fortes : sans elles le GC Python détruit le thread en vol.
        self._thread = thread
        self._worker = worker
        thread.start()

    def _stop_thread(self):
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(3000)
        self._thread = None
        self._worker = None

    def _on_done(self, result: dict):
        self._stop_thread()
        submitted = int(result.get("submitted", 0) or 0)
        skipped   = int(result.get("skipped", 0) or 0)
        # On mémorise TOUTES les fixtures envoyées, y compris celles écartées
        # comme doublons : elles sont déjà dans la file ou publiées, donc les
        # reproposer au prochain import ne servirait qu'à agacer l'utilisateur.
        quota_left = result.get("quota_left")
        _record_submission(
            [fixture_fingerprint(fx) for fx in self._checked_fixtures()],
            used=submitted,
            quota_left=None if quota_left is None else int(quota_left),
        )

        if submitted == 0:
            QMessageBox.information(self, tr("fs_title"), tr("fs_result_none"))
        else:
            msg = tr("fs_result_ok", n=submitted)
            if skipped:
                msg += "\n\n" + tr("fs_result_skipped", n=skipped)
            QMessageBox.information(self, tr("fs_title"), msg)
        self.accept()

    def _on_error(self, msg: str):
        self._stop_thread()
        self._status.setStyleSheet("color:#ee6666; font-size:11px;")
        self._status.setText(msg)
        self._refresh_state()

    def reject(self):
        self._stop_thread()
        super().reject()


# ──────────────────────────────────────────────────────────────────────────────
# Point d'entrée appelé depuis les flux d'import
# ──────────────────────────────────────────────────────────────────────────────

def offer_share(parent, fixtures: list) -> None:
    """
    Propose le partage des fixtures qui viennent d'être importées.
    Ne fait rien (silencieusement) si l'utilisateur n'est pas connecté, si la
    liste est vide ou si toutes ces fixtures ont déjà été proposées : l'import
    local ne doit jamais échouer à cause du partage.
    """
    try:
        candidates = [f for f in (fixtures or []) if isinstance(f, dict) and f.get("name")]
        if not candidates:
            return

        # Ne pas reproposer une fixture déjà envoyée depuis cette machine.
        already = set(load_share_state().get("sent", {}))
        candidates = [f for f in candidates if fixture_fingerprint(f) not in already]
        if not candidates:
            return

        # Sans compte connecté, il n'y a personne à qui attribuer la contribution.
        from license_manager import get_machine_id, _load_account
        if not _load_account(get_machine_id()):
            return

        FixtureShareDialog(candidates, parent).exec()
    except Exception as e:
        print(f"[fixture_share] proposition de partage ignorée : {e}")
