"""« 🎯 Définir le centre » d'une lyre (Patch DMX, clic droit sur le canal Pan/Tilt).

Demande client du 27/11/2026 : lyres BoomTone accrochées écrans face au public,
le centre de MyStrow les faisait regarder à 90° sur la droite. Plutôt qu'un
décalage à saisir en degrés, on CALIBRE : la vraie lyre bouge en direct, on
l'amène face au public, « C'est le centre ».

Le résultat est un décalage DMX 16 bits (`pan_offset` / `tilt_offset`) ajouté
en sortie par `artnet_dmx` (cf. `core.pantilt_offset`) : pointeur, presets,
plan 2D, 3D, effets et LIVE partent tous de ce nouveau centre sans rien savoir
de lui.

Pendant le réglage, le décalage de la lyre est mis à 0 et sa position
porte la valeur physique : ce qu'on voit sur scène est exactement la valeur du
curseur. Validation : décalage = curseur − 32768, position ramenée à 32768
(la lyre ne bouge pas). Annulation : tout est restauré.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QSlider, QPushButton, QCheckBox)

from core import pantilt_offset, pan_tilt_ranges
from i18n import tr

# Pas des flèches : 1 cran DMX grossier (256) et 1/8 de cran.
_PAS_FIN, _PAS_GROS = 32, 256


def axe_modele(proj, ch_type):
    """Axe de l'application ('pan'/'tilt') porté par le canal physique `ch_type`.

    Le décalage vit dans le repère de l'application (avant swap) ; avec
    « Inverser Pan/Tilt », le canal Pan du câblage est l'axe tilt du modèle.
    """
    axe = "pan" if ch_type.startswith("Pan") else "tilt"
    if getattr(proj, 'pan_tilt_swap', False):
        axe = "tilt" if axe == "pan" else "pan"
    return axe


def offset_degres(proj, axe):
    """Décalage actuel en degrés (arrondi), pour l'afficher."""
    pan_deg, tilt_deg = pan_tilt_ranges(proj)
    rng = pan_deg if axe == "pan" else tilt_deg
    return int(round(pantilt_offset(proj, axe) / 65535.0 * rng))


def set_offset(proj, axe, off):
    setattr(proj, f'{axe}_offset', int(max(-65535, min(65535, off))))


class CentreDialog(QDialog):
    def __init__(self, proj, ch_type, freres=(), nom="", parent=None):
        super().__init__(parent)
        self.proj   = proj
        self.axe    = axe_modele(proj, ch_type)
        self.freres = list(freres)
        self.setWindowTitle(tr("ctr_title", axe=ch_type.replace("Fine", "")))
        self.setModal(True)
        self.setStyleSheet(
            "QDialog{background:#0e0e0e;} QLabel{color:#cccccc;background:transparent;}"
            "QCheckBox{color:#cccccc;}"
            "QPushButton{background:#1a1a1a;color:#cccccc;border:1px solid #2a2a2a;"
            "border-radius:5px;padding:6px 12px;}"
            "QPushButton:hover{border-color:#00d4ff;color:#ffffff;}"
        )

        # État d'origine, restauré à l'annulation.
        self._pos0 = int(getattr(proj, self.axe, 32768))
        self._off0 = pantilt_offset(proj, self.axe)
        phys = max(0, min(65535, self._pos0 + self._off0))
        set_offset(proj, self.axe, 0)
        self._poser(phys)
        self._valide = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        t = QLabel(tr("ctr_title", axe=ch_type.replace("Fine", "")) + (f"  ·  {nom}" if nom else ""))
        t.setStyleSheet("color:#00d4ff;font-size:13px;font-weight:bold;")
        lay.addWidget(t)

        aide = QLabel(tr("ctr_hint_pan" if self.axe == "pan" else "ctr_hint_tilt"))
        aide.setWordWrap(True)
        aide.setFixedWidth(380)
        lay.addWidget(aide)

        self._val = QLabel()
        self._val.setAlignment(Qt.AlignCenter)
        self._val.setStyleSheet("color:#ffffff;font-size:20px;font-weight:bold;")
        lay.addWidget(self._val)

        row = QHBoxLayout()
        for txt, pas in (("◀◀", -_PAS_GROS), ("◀", -_PAS_FIN)):
            row.addWidget(self._fleche(txt, pas))
        self._sli = QSlider(Qt.Horizontal)
        self._sli.setRange(0, 65535)
        self._sli.setSingleStep(_PAS_FIN)
        self._sli.setPageStep(_PAS_GROS * 8)
        self._sli.setValue(phys)
        self._sli.valueChanged.connect(self._on_slide)
        row.addWidget(self._sli, 1)
        for txt, pas in (("▶", _PAS_FIN), ("▶▶", _PAS_GROS)):
            row.addWidget(self._fleche(txt, pas))
        lay.addLayout(row)

        self._chk = None
        if self.freres:
            self._chk = QCheckBox(tr("ctr_apply_same", n=len(self.freres)))
            self._chk.setChecked(True)
            lay.addWidget(self._chk)

        btns = QHBoxLayout()
        b_reset = QPushButton(tr("ctr_reset"))
        b_reset.setToolTip(tr("ctr_reset_tip"))
        b_reset.clicked.connect(self._reset)
        btns.addWidget(b_reset)
        btns.addStretch()
        b_cancel = QPushButton(tr("ctr_cancel"))
        b_cancel.clicked.connect(self.reject)
        btns.addWidget(b_cancel)
        b_ok = QPushButton(tr("ctr_ok"))
        b_ok.setDefault(True)
        b_ok.setStyleSheet("QPushButton{background:#0d2030;color:#00d4ff;"
                           "border:1px solid #00d4ff88;border-radius:5px;padding:6px 14px;"
                           "font-weight:bold;}")
        b_ok.clicked.connect(self._valider)
        btns.addWidget(b_ok)
        lay.addLayout(btns)

        self._maj_label(phys)

    # ── interne ──────────────────────────────────────────────────────────────
    def _fleche(self, txt, pas):
        b = QPushButton(txt)
        b.setFixedWidth(40)
        b.setAutoRepeat(True)
        b.clicked.connect(lambda: self._sli.setValue(self._sli.value() + pas))
        return b

    def _poser(self, v):
        setattr(self.proj, self.axe, int(v))
        # Position posée à la main : le repos automatique n'y touche plus.
        self.proj._manual_move = True

    def _maj_label(self, v):
        pan_deg, tilt_deg = pan_tilt_ranges(self.proj)
        rng = pan_deg if self.axe == "pan" else tilt_deg
        deg = int(round((v - 32768) / 65535.0 * rng))
        self._val.setText(tr("ctr_value", dmx=v >> 8, deg=f"{deg:+d}"))

    def _on_slide(self, v):
        self._poser(v)
        self._maj_label(v)

    def _cibles(self):
        if self._chk is not None and self._chk.isChecked():
            return [self.proj] + self.freres
        return [self.proj]

    def _appliquer(self, off):
        for p in self._cibles():
            set_offset(p, self.axe, off)
        # La lyre réglée garde sa position physique : centre de son repère.
        phys = self._sli.value()
        setattr(self.proj, self.axe, max(0, min(65535, phys - off)))
        self._valide = True

    def _valider(self):
        self._appliquer(self._sli.value() - 32768)
        self.accept()

    def _reset(self):
        self._appliquer(0)
        self.accept()

    def done(self, r):
        if not self._valide:
            set_offset(self.proj, self.axe, self._off0)
            setattr(self.proj, self.axe, self._pos0)
        super().done(r)

    def changed(self):
        return self._valide
