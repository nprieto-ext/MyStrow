"""Pixel map : dégradé spatial sur le plan de feu 2D.

Chaque fixture prend la couleur du dégradé à SA position sur le plan,
ramenée à la boîte englobante de la sélection.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor

from pixel_map import GradientSpec, spatial_positions, sample_gradient, color_for
from plan_de_feu import PlanDeFeu
from projector import Projector

_app = QApplication.instance() or QApplication([])


# ── Calcul pur ──────────────────────────────────────────────────────────────

def test_positions_lineaires_ramenees_a_la_selection():
    # Six PAR serrés au centre parcourent quand même 0 → 1
    pts = [(0.40 + i * 0.04, 0.5) for i in range(6)]
    s = spatial_positions(pts, "linear", 0)
    assert abs(s[0]) < 1e-9 and abs(s[-1] - 1) < 1e-9
    assert s == sorted(s)
    # 180° : sens inverse
    s2 = spatial_positions(pts, "linear", 180)
    assert abs(s2[0] - 1) < 1e-9 and abs(s2[-1]) < 1e-9


def test_vertical_sur_une_ligne_horizontale_donne_une_seule_couleur():
    pts = [(0.1 * i, 0.5) for i in range(5)]
    assert spatial_positions(pts, "linear", 90) == [0.0] * 5


def test_radial():
    pts = [(0.0, 0.5), (0.5, 0.5), (1.0, 0.5)]
    assert spatial_positions(pts, "radial") == [1.0, 0.0, 1.0]
    assert spatial_positions(pts, "radial_in") == [0.0, 1.0, 0.0]


def test_positions_absentes_tolerees():
    assert len(spatial_positions([None, (None, 0.2), (0.3, 0.3)])) == 3


def test_degrade_boucle():
    st = ["#ff0000", "#0000ff"]
    assert sample_gradient(st, 0.0) == (255, 0, 0)
    assert sample_gradient(st, 0.5) == (0, 0, 255)
    assert sample_gradient(st, 1.0) == (255, 0, 0)       # boucle
    assert sample_gradient(st, -0.5) == (0, 0, 255)


def test_rouge_vers_bleu_va_bien_de_rouge_a_bleu():
    spec = GradientSpec(stops=["#ff0000", "#0000ff"], speed=0)
    assert color_for(spec, 0.0, 0.0) == (255, 0, 0)
    assert color_for(spec, 1.0, 0.0) == (0, 0, 255)


def test_defilement_continu():
    spec = GradientSpec(stops=["#ff0000", "#00ff00", "#0000ff"])
    a = color_for(spec, 0.3, 0.0)
    b = color_for(spec, 0.3, 1.0)      # un tour complet = même couleur
    assert a == b


def test_spec_aller_retour_dict():
    spec = GradientSpec(stops=["#112233"], shape="radial", angle=45,
                        repeat=2, speed=0.5, reverse=True)
    assert GradientSpec.from_dict(spec.to_dict()) == spec
    assert GradientSpec.from_dict({"shape": "zzz", "stops": ["pas une couleur"]}).shape == "linear"


# ── Moteur du plan 2D ───────────────────────────────────────────────────────

def _plan(n=5):
    projs = [Projector("face", f"PAR {i+1}", "PAR LED") for i in range(n)]
    for i, p in enumerate(projs):
        p.canvas_x, p.canvas_y = 0.1 + i * 0.2, 0.5
        p.level = 0
        p.base_color = QColor(10, 20, 30)
    return PlanDeFeu(projs), projs


def test_plan_applique_le_degrade_selon_la_position():
    pdf, projs = _plan()
    spec = GradientSpec(stops=["#ff0000", "#0000ff"], speed=0)
    pdf.start_gradient_effect(projs, spec)
    first, last = projs[0].base_color, projs[-1].base_color
    assert (first.red(), first.blue()) == (255, 0)
    assert (last.red(), last.blue()) == (0, 255)
    # Projecteurs éteints : allumés, sinon le dégradé serait invisible
    assert all(p.level > 0 for p in projs)
    assert all(getattr(p, '_manual_color', False) for p in projs)


def test_mise_a_jour_sans_saut_de_phase_puis_arret_rend_l_etat():
    pdf, projs = _plan()
    spec = GradientSpec(stops=["#ff0000", "#0000ff"], speed=1.0)
    pdf.start_gradient_effect(projs, spec)
    for p in projs:
        pdf._led_effects[id(p)]["phase"] = 1.234
    spec2 = GradientSpec(stops=["#00ff00", "#ffffff"], speed=0.5)
    pdf.update_gradient_effect(projs, spec2)
    assert all(abs(pdf._led_effects[id(p)]["phase"] - 1.234) < 0.2 for p in projs)
    # Relancer (rouvrir le panneau) ne doit pas mémoriser le dégradé comme
    # état de retour
    pdf.start_gradient_effect(projs, spec2)
    pdf.stop_gradient_effect(projs)
    assert not pdf._led_effects
    for p in projs:
        assert p.level == 0
        assert (p.base_color.red(), p.base_color.green(), p.base_color.blue()) == (10, 20, 30)


def test_master_de_matrice_exclu():
    pdf, projs = _plan(3)
    projs[0].matrix_role = 'master'
    assert projs[0] not in pdf.gradient_targets(projs)


# ── Barre d'outils : 🎯 et 🎨 selon la sélection ───────────────────────────

def test_boutons_cible_et_degrade_suivent_la_selection():
    projs = [Projector("face", f"PAR {i+1}", "PAR LED") for i in range(3)]
    projs.append(Projector("contre", "Lyre 1", "Moving Head"))
    for i, p in enumerate(projs):
        p.canvas_x, p.canvas_y = 0.1 + i * 0.2, 0.5
    pdf = PlanDeFeu(projs)

    def tick():
        sel = pdf.selected_projectors()
        pdf.refresh_target_btn(sel)
        pdf.refresh_pixmap_btn(sel)

    pdf.selected_lamps = set(); tick()
    assert pdf.btn_target.isHidden() and pdf.btn_pixmap.isHidden()

    pdf.selected_lamps = {("face", 0)}; tick()          # 1 PAR : rien
    assert pdf.btn_target.isHidden() and pdf.btn_pixmap.isHidden()

    pdf.selected_lamps = {("face", 0), ("face", 1)}; tick()   # 2 PAR : 🎨 seul
    assert pdf.btn_target.isHidden() and not pdf.btn_pixmap.isHidden()

    pdf.selected_lamps = {("contre", 0)}; tick()         # 1 lyre : 🎯 seul
    assert not pdf.btn_target.isHidden() and pdf.btn_pixmap.isHidden()

    # Cible armée sur la lyre sélectionnée, puis désélection : 🎯 reste
    # affiché tant qu'il est armé (c'est lui qui le désarme)
    pdf.btn_target.setChecked(True)
    assert pdf.selected_lamps == {("contre", 0)}
    pdf.selected_lamps = set(); tick()
    assert not pdf.btn_target.isHidden()
    pdf.btn_target.setChecked(False); tick()
    assert pdf.btn_target.isHidden()


def test_bouton_degrade_ouvre_le_panneau_et_s_allume():
    pdf, projs = _plan(4)
    pdf.selected_lamps = {("face", i) for i in range(4)}
    dlg = pdf.open_pixel_map()
    assert dlg is not None
    assert pdf.btn_pixmap.isChecked()          # dégradé en cours sur la sélection
    dlg._stop()
    pdf.refresh_pixmap_btn()
    assert not pdf.btn_pixmap.isChecked()


def test_rouge_vers_noir_eteint_le_bout_de_la_ligne():
    pdf, projs = _plan(5)
    spec = GradientSpec(stops=["#ff0000", "#000000"], speed=0)
    pdf.start_gradient_effect(projs, spec)
    assert projs[0].color.red() == 255
    last = projs[-1].color
    assert (last.red(), last.green(), last.blue()) == (0, 0, 0)
    # Le milieu est un rouge à mi-puissance, pas un rose
    mid = projs[2].color
    assert 100 < mid.red() < 160 and mid.green() == 0 and mid.blue() == 0


# ── Motifs, noir qui traîne, enregistrement et moteur du show ─────────────

from pixel_map import motif_value, selection_span


def test_noir_a_zero_rend_le_degrade_historique():
    a = GradientSpec(stops=["#ff0000", "#00ff00", "#0000ff"], gap=0.0)
    for s in (0.0, 0.2, 0.55, 0.9):
        for ph in (0.0, 0.37):
            assert color_for(a, s, ph) == sample_gradient(
                a.stops, s * (2 / 3) - ph)
    # continuité : un noir infime ne change presque rien
    b = GradientSpec(stops=["#ff0000", "#000000"], gap=0.001)
    c = GradientSpec(stops=["#ff0000", "#000000"], gap=0.0)
    for s in (0.1, 0.5, 0.9):
        ca, cb = color_for(b, s, 0.2), color_for(c, s, 0.2)
        assert abs(ca[0] - cb[0]) <= 3


def test_le_noir_traine_plus_longtemps():
    """Plus de NOIR = plus de fixtures éteintes à un instant donné."""
    def eteints(gap, motif):
        spec = GradientSpec(stops=["#ff0000", "#000000"], motif=motif, gap=gap)
        return sum(1 for i in range(100)
                   if color_for(spec, i / 100, 0.0)[0] < 10)
    for motif in ("degrade", "vague", "bloc", "chenillard", "rampe"):
        assert eteints(0.7, motif) > eteints(0.1, motif), motif


def test_motifs_forme():
    assert motif_value("bloc", 0.1) == 1.0 and motif_value("bloc", 0.7) == 0.0
    assert motif_value("chenillard", 0.1) == 1.0 and motif_value("chenillard", 0.5) == 0.0
    assert motif_value("vague", 0.5) > 0.99 and motif_value("vague", 0.0) < 0.01
    assert motif_value("rampe", 0.2) < motif_value("rampe", 0.8)   # tête devant


def test_sens_aleatoire_stable():
    pts = [(0.1 * i, 0.3) for i in range(8)]
    a = spatial_positions(pts, "random"); b = spatial_positions(pts, "random")
    assert a == b and len(set(round(x, 6) for x in a)) == 8


def _patch_lineaire(n=5):
    projs = [Projector("face", f"PAR {i+1}", "PAR LED") for i in range(n)]
    for i, p in enumerate(projs):
        p.canvas_x, p.canvas_y = 0.1 + i * 0.2, 0.5
    return projs


def test_enregistrer_cree_un_effet_de_bibliotheque(tmp_path=None):
    import tempfile, pathlib, effect_editor
    from pixel_map_panel import build_pixel_effect, save_pixel_effect
    projs = _patch_lineaire()
    pdf = PlanDeFeu(projs)
    spec = GradientSpec(stops=["#ff0000", "#000000"], motif="vague", gap=0.4,
                        shape="radial", speed=0.5)
    eff = build_pixel_effect(pdf, projs[1:4], spec, "Test")
    ld = eff["layers"][0]
    assert ld["attribute"] == "Dégradé" and ld["target_preset"] == "Selection"
    assert ld["target_selection"] == [["face", 1], ["face", 2], ["face", 3]]
    assert GradientSpec.from_dict(ld["grad"]) == spec
    # L'éditeur d'effets relit et réécrit la couche sans la perdre
    rt = effect_editor.EffectLayer.from_dict(ld).to_dict()
    assert rt["attribute"] == "Dégradé" and rt["grad"] == ld["grad"]
    # Fichier de bibliothèque : écrit dans un dossier temporaire
    d = pathlib.Path(tempfile.mkdtemp())
    old = effect_editor._CUSTOM_EFFECTS_FILE
    effect_editor._CUSTOM_EFFECTS_FILE = d / "fx.json"
    try:
        e1 = save_pixel_effect(pdf, projs, spec, "Vague")
        e2 = save_pixel_effect(pdf, projs, spec, "Vague")
        assert (e1["name"], e2["name"]) == ("Vague", "Vague 2")
        assert [e["name"] for e in effect_editor._load_custom_effects()] == ["Vague", "Vague 2"]
    finally:
        effect_editor._CUSTOM_EFFECTS_FILE = old


def test_moteur_du_show_rejoue_comme_le_plan():
    """L'effet enregistré, joué par le moteur du show (pad / REC), donne les
    mêmes couleurs que l'aperçu du plan 2D au même instant."""
    from unittest import mock
    import main_window as mw
    from pixel_map_panel import build_pixel_effect

    projs = _patch_lineaire()
    pdf = PlanDeFeu(projs)
    spec = GradientSpec(stops=["#ff0000", "#000000"], motif="degrade", gap=0.3,
                        speed=0.0)
    eff = build_pixel_effect(pdf, projs, spec, "X")

    class W:
        _update_effect_from_layers = mw.MainWindow._update_effect_from_layers
        _update_color_wheel = mw.MainWindow._update_color_wheel
        _GENERIC_WHEEL_SLOTS = mw.MainWindow._GENERIC_WHEEL_SLOTS
    w = W(); w.projectors = projs; w.effect_speed = 100; w.effect_t0 = 0.0
    w.effect_saved_colors = {}; w._effect_clock = 0.0; w._effect_clock_ts = None
    w.position_presets = []
    with mock.patch("time.monotonic", return_value=1.0):
        w._update_effect_from_layers({"layers": eff["layers"]})
    show = [(p.color.red(), p.color.green(), p.color.blue()) for p in projs]

    pdf2, projs2 = _plan(5)
    pdf2.start_gradient_effect(projs2, spec)
    plan = [(p.color.red(), p.color.green(), p.color.blue()) for p in projs2]
    assert show == plan, (show, plan)
    assert show[0] == (255, 0, 0) and show[-1] == (0, 0, 0)


# ── DIM général et placement ──────────────────────────────────────────────────────

def test_dim_general_baisse_la_sortie():
    from pixel_map import output_for
    spec = GradientSpec(stops=["#ff0000", "#000000"], speed=0, dim=0.5)
    val = output_for(spec, 0.0, 0.0)
    assert 120 <= val[0] <= 135


def test_panneau_ouvre_au_dessus_du_sequenceur():
    from PySide6.QtWidgets import QWidget
    pdf, projs = _plan(4)

    class MW:
        pass
    mw_ = MW()
    seq = QWidget(); seq.setGeometry(100, 500, 900, 400); seq.show()
    mw_.seq = seq; mw_.dmx = None
    pdf.main_window = mw_
    pdf.selected_lamps = {("face", i) for i in range(4)}
    dlg = pdf.open_pixel_map()
    from PySide6.QtWidgets import QApplication
    a = QApplication.primaryScreen().availableGeometry()
    c = seq.mapToGlobal(seq.rect().center())
    fg = dlg.frameGeometry()
    # Centré sur le séquenceur, ramené dans l'écran si besoin
    x_att = max(a.left(), min(c.x() - dlg.width() // 2, a.right() - dlg.width()))
    assert abs(dlg.x() - x_att) <= 3, (dlg.x(), x_att)
    # La fenêtre tient dans l'écran, même petit (écran de test : 800 px)
    assert fg.height() <= a.height(), (fg.height(), a.height())
    dlg._stop()


# ── Palettes multicolores et animation des vignettes ──────────────────────

def test_feu_sur_un_motif_garde_ses_couleurs():
    from pixel_map import PRESETS
    for nom in ("Feu", "Coucher", "Arc-en-ciel"):
        for motif in ("vague", "bloc", "chenillard", "rampe"):
            spec = GradientSpec(stops=PRESETS[nom], motif=motif, gap=0.3)
            cols = [color_for(spec, i / 40, 0.0) for i in range(40)]
            assert all(max(c) > 60 for c in cols), (nom, motif)   # jamais noir


def test_vignettes_accelerent_sans_sauter():
    from unittest import mock
    import pixel_map_panel as pmp
    pdf, projs = _plan(4)
    t = [100.0]
    with mock.patch.object(pmp._time, "monotonic", lambda: t[0]):
        dlg = pmp.PixelMapDialog(pdf, projs)
        dlg.spd_sli.setValue(10)
        for _ in range(300):              # 10 s d'animation lente
            t[0] += 0.033; dlg._tick()
        avant = dlg.preview_phase()
        dlg.spd_sli.setValue(100)         # on pousse la vitesse à fond
        t[0] += 0.033; dlg._tick()
        saut = dlg.preview_phase() - avant
    # Une image à 2 tours/s = 0,066 tour ; l'ancien calcul sautait de
    # (2 - 0,35) × 10 s ≈ 16 tours d'un coup.
    assert saut < 0.1, saut
    dlg._stop()


if __name__ == "__main__":
    import sys
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print("OK  ", name)
            except Exception as e:
                fails += 1; print("FAIL", name, repr(e))
    sys.exit(1 if fails else 0)
