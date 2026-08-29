"""
test_canaux_avances_regroupes.py — Une seule section de canaux techniques.

Le menu contextuel du plan de feu construisait DEUX paquets de canaux
techniques, separes par tout le bloc Moving Head (pad Pan/Tilt, presets, roue
de couleur, gobo, prisme) puis la grille de couleurs :

  * « CANAUX SPECIAUX » — UV, Blanc, Ambre, Orange, Effects, puis Focus,
    Gobo 2, Vitesse, Mode ;
  * « CANAUX AVANCES »  — tout le reste du profil (Zoom, Iris, Frost, CTO...).

Sur une Maverick Force S Spot, Focus/Gobo 2/Vitesse/Mode se retrouvaient donc
tout en haut et Zoom/Iris/Frost/CTO tout en bas : la meme famille de reglages
a deux endroits, avec une centaine de pixels de menu entre les deux.

Ce qui est verrouille ici :

  * les quatre canaux techniques a etat dedie sont rendus DANS la section
    « Canaux avances », en tete, et plus dans « Canaux speciaux » ;
  * « Canaux speciaux » ne garde que la couleur (UV, Blanc, Ambre, Orange,
    Effects) — et disparait quand la fixture n'en a aucun ;
  * un seul curseur par canal : deplacer les lignes ne doit pas en laisser une
    copie derriere (deux writers pour le meme canal DMX) ;
  * le curseur ecrit toujours l'ATTRIBUT dedie (`proj.focus`, `proj.mode_value`)
    et pas `channel_extras`, qui court-circuiterait le modele ;
  * la valeur affichee de ces quatre lignes est la valeur DMX BRUTE : elles
    voisinent desormais avec des canaux bruts en 0-255, ou un « 38 % » ne se
    compare a rien. Les boosts de couleur, eux, gardent leur « +38 % ».

    python test_canaux_avances_regroupes.py
"""

import os
import sys
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (QApplication, QLabel, QWidgetAction, QSlider,
                               QPushButton)

_app = QApplication.instance() or QApplication(sys.argv)

import plan_de_feu
from plan_de_feu import PlanDeFeu
from projector import Projector


# Maverick Force S Spot, mode etendu : le profil tel que MyStrow le voit apres
# import. Focus/Gobo2/Speed/Mode y cotoient Zoom/Iris/Frost/CTO — c'est cette
# fixture qui a fait remonter la coupure.
MAVERICK = [
    "Pan", "PanFine", "Tilt", "TiltFine", "Speed",
    "Dim", "Dim2", "Shutter",
    "ColorWheel", "CTO",
    "Gobo1", "Gobo1Rot", "Gobo2",
    "Prism", "PrismRot", "Frost", "Iris", "Zoom", "Focus",
    "Mode", "Reset",
]


def _make_pdf(profile, fixture_type="Moving Head"):
    proj = Projector("lyre", "Maverick", fixture_type)
    proj.dmx_profile = list(profile)
    proj.channel_labels = [f"CH{n}" for n in range(1, len(profile) + 1)]
    pdf = PlanDeFeu([proj], main_window=None, show_toolbar=False)
    return pdf, proj


def _walk(menu):
    """Le menu, a plat : ('label', titre) et ('row', etiquette, curseur, action).

    Les sections du menu sont des QWidgetAction — un QLabel pour le titre (ou
    un QPushButton « ▸ TITRE · n » quand la section se replie), un QWidget
    « etiquette + curseur + valeur » pour chaque ligne. On lit donc les widgets,
    pas les QAction — mais on rend l'action de chaque ligne : c'est ELLE qu'on
    masque au repli, et donc elle qu'il faut interroger.
    """
    out = []
    for act in menu.actions():
        if not isinstance(act, QWidgetAction):
            continue
        w = act.defaultWidget()
        if w is None:
            continue
        if isinstance(w, QLabel):
            out.append(("label", w.text()))
            continue
        if isinstance(w, QPushButton) and w.text().startswith(("▸", "▾")):
            # « ▸  CANAUX AVANCÉS  ·  9   ● 2 » → « CANAUX AVANCÉS »
            out.append(("label", w.text().lstrip("▸▾ ").split("  ·")[0].strip()))
            continue
        labels = w.findChildren(QLabel)
        slis = w.findChildren(QSlider)
        if labels and slis:
            out.append(("row", labels[0].text(), slis[0], act))
    return out


def _entete_repliable(menu, titre):
    """Le QPushButton d'en-tete de la section `titre`, ou None."""
    for act in menu.actions():
        if not isinstance(act, QWidgetAction) or act.defaultWidget() is None:
            continue
        w = act.defaultWidget()
        if isinstance(w, QPushButton) and titre in w.text():
            return w
    return None


def _section(items, titre):
    """Les lignes qui suivent le titre `titre`, jusqu'au titre suivant."""
    dedans = False
    lignes = []
    for it in items:
        if it[0] == "label":
            if dedans:
                break
            dedans = (it[1] == titre)
            continue
        if dedans and it[0] == "row":
            lignes.append(it)
    return lignes


class TestRegroupement(unittest.TestCase):

    def setUp(self):
        self.pdf, self.proj = _make_pdf(MAVERICK)
        self.pdf.selected_lamps = {("lyre", 0)}
        self.menu = None
        # On intercepte le menu au lieu de le montrer : `exec()` ouvre une
        # boucle d'evenements modale et ne rendrait jamais la main au test.
        _vrai_exec = plan_de_feu._PersistentMenu.exec

        def _capture(menu_self, *a, **k):
            self.menu = menu_self
            return None

        plan_de_feu._PersistentMenu.exec = _capture
        self.addCleanup(setattr, plan_de_feu._PersistentMenu, "exec", _vrai_exec)

    def _items(self):
        from PySide6.QtCore import QPoint
        self.pdf._show_fixture_context_menu(QPoint(0, 0), 0)
        self.assertIsNotNone(self.menu, "le menu contextuel ne s'est pas construit")
        return _walk(self.menu)

    # ── Le regroupement lui-meme ─────────────────────────────────────────
    def test_les_quatre_dedies_sont_dans_canaux_avances(self):
        items = self._items()
        avances = [r[1] for r in _section(items, "CANAUX AVANCÉS")]
        for nom in ("Focus", "Gobo 2", "Vitesse", "Mode"):
            self.assertIn(nom, avances,
                          f"« {nom} » devrait etre dans « Canaux avances »")

    def test_canaux_speciaux_ne_garde_que_la_couleur(self):
        items = self._items()
        speciaux = [r[1] for r in _section(items, "CANAUX SPÉCIAUX")]
        for nom in ("Focus", "Gobo 2", "Vitesse", "Mode"):
            self.assertNotIn(nom, speciaux,
                             f"« {nom} » est reste dans « Canaux speciaux »")

    def test_pas_de_section_speciaux_sans_canal_de_couleur(self):
        # La Maverick n'a ni UV ni W ni Ambre : la section entiere disparait,
        # au lieu de rester ouverte pour les seuls canaux techniques.
        items = self._items()
        self.assertNotIn(("label", "CANAUX SPÉCIAUX"), items)

    def test_un_seul_curseur_par_canal(self):
        # Deplacer une ligne ne doit pas en laisser une copie : deux curseurs
        # sur le meme canal, c'est l'anti-pattern des deux writers.
        items = self._items()
        for nom in ("Focus", "Gobo 2", "Vitesse", "Mode"):
            n = sum(1 for it in items if it[0] == "row" and it[1] == nom)
            self.assertEqual(n, 1, f"{n} curseurs « {nom} » dans le menu")

    def test_une_seule_famille_technique_en_bas(self):
        # Les canaux bruts du profil et les quatre dedies sont dans la MEME
        # section, les dedies en tete.
        items = self._items()
        avances = [r[1] for r in _section(items, "CANAUX AVANCÉS")]
        self.assertEqual(avances[:4], ["Focus", "Gobo 2", "Vitesse", "Mode"])
        # Les canaux bruts (Zoom, Iris, Frost, CTO...) suivent dans la meme liste
        self.assertTrue(len(avances) > 4,
                        "les canaux bruts du profil ont disparu de la section")

    # ── Ce que le curseur ecrit ──────────────────────────────────────────
    def test_le_curseur_ecrit_l_attribut_dedie(self):
        items = self._items()
        avances = _section(items, "CANAUX AVANCÉS")
        par_nom = {r[1]: r[2] for r in avances}
        for nom, attr in (("Focus", "focus"), ("Gobo 2", "gobo2"),
                          ("Vitesse", "speed"), ("Mode", "mode_value")):
            par_nom[nom].setValue(137)
            self.assertEqual(getattr(self.proj, attr), 137,
                             f"« {nom} » n'ecrit pas proj.{attr}")
        # ... et surtout PAS dans channel_extras, qui court-circuite le modele
        self.assertFalse(getattr(self.proj, "channel_extras", {}) or {},
                         "un canal a etat dedie a ete ecrit dans channel_extras")

    def test_valeur_dmx_brute_et_pas_un_pourcentage(self):
        items = self._items()
        # La valeur est le 2e QLabel de la ligne (etiquette, [valeur])
        for act in self.menu.actions():
            if not isinstance(act, QWidgetAction) or act.defaultWidget() is None:
                continue
            labels = act.defaultWidget().findChildren(QLabel)
            slis = act.defaultWidget().findChildren(QSlider)
            if len(labels) >= 2 and slis and labels[0].text() == "Mode":
                slis[0].setValue(200)
                self.assertEqual(labels[1].text(), "200",
                                 "« Mode » s'affiche encore en pourcentage")
                return
        self.fail("ligne « Mode » introuvable")

    def test_les_boosts_de_couleur_gardent_leur_plus(self):
        pdf, proj = _make_pdf(["Dim", "R", "G", "B", "W", "Ambre"], "PAR LED")
        pdf.selected_lamps = {("lyre", 0)}
        self.pdf = pdf
        from PySide6.QtCore import QPoint
        pdf._show_fixture_context_menu(QPoint(0, 0), 0)
        for act in self.menu.actions():
            if not isinstance(act, QWidgetAction) or act.defaultWidget() is None:
                continue
            labels = act.defaultWidget().findChildren(QLabel)
            slis = act.defaultWidget().findChildren(QSlider)
            if len(labels) >= 2 and slis and labels[0].text() == "Ambre":
                slis[0].setValue(128)
                self.assertTrue(labels[1].text().startswith("+"),
                                f"« Ambre » affiche {labels[1].text()!r}, "
                                "le « + » du boost a saute")
                return
        self.fail("ligne « Ambre » introuvable")

    # ── Repli de la section ──────────────────────────────────────────────
    def test_repliee_par_defaut(self):
        # 9 lignes sur une Maverick : la section fait la moitie du menu et on
        # n'y touche qu'au patch. Les lignes existent mais leur action est
        # masquee — pas le widget, sinon QMenu laisse un rectangle vide.
        items = self._items()
        avances = _section(items, "CANAUX AVANCÉS")
        self.assertTrue(avances, "la section a disparu")
        for r in avances:
            self.assertFalse(r[3].isVisible(),
                             f"« {r[1]} » est visible, la section n'est pas repliee")
        self.assertTrue(_entete_repliable(self.menu, "CANAUX AVANCÉS").text().startswith("▸"))

    def test_le_clic_sur_l_entete_deplie(self):
        items = self._items()
        avances = _section(items, "CANAUX AVANCÉS")
        _entete_repliable(self.menu, "CANAUX AVANCÉS").click()
        for r in avances:
            self.assertTrue(r[3].isVisible(), f"« {r[1]} » est reste masque")
        self.assertTrue(_entete_repliable(self.menu, "CANAUX AVANCÉS").text().startswith("▾"))

    def test_le_choix_vaut_pour_le_projecteur_suivant(self):
        # Meme memoire que le mode « Curseurs » : on ouvre une fois, ca reste
        # ouvert — sinon il faudrait redeplier a chaque clic droit.
        self._items()
        _entete_repliable(self.menu, "CANAUX AVANCÉS").click()
        self.assertIs(self.pdf._adv_expanded, True)
        items = self._items()          # deuxieme ouverture du menu
        for r in _section(items, "CANAUX AVANCÉS"):
            self.assertTrue(r[3].isVisible(),
                            "la section s'est refermee a la reouverture du menu")

    def test_un_canal_regle_ouvre_la_section(self):
        # Replier par defaut ne doit jamais escamoter un reglage actif : un
        # Zoom coince a 200 qu'on ne voit plus, c'est une soiree de recherche.
        self.proj.channel_extras = {"Zoom": 200}
        items = self._items()
        avances = _section(items, "CANAUX AVANCÉS")
        for r in avances:
            self.assertTrue(r[3].isVisible(),
                            "un canal est regle et la section est restee repliee")
        self.assertIn("●", _entete_repliable(self.menu, "CANAUX AVANCÉS").text())

    def test_un_attribut_dedie_regle_ouvre_aussi(self):
        # Meme regle pour les quatre lignes a etat dedie, qui ne passent pas
        # par channel_extras.
        self.proj.focus = 180
        items = self._items()
        for r in _section(items, "CANAUX AVANCÉS"):
            self.assertTrue(r[3].isVisible())

    def test_replier_a_la_main_prime_sur_l_ouverture_auto(self):
        self.proj.channel_extras = {"Zoom": 200}
        items = self._items()
        _entete_repliable(self.menu, "CANAUX AVANCÉS").click()   # on replie
        items = self._items()
        for r in _section(items, "CANAUX AVANCÉS"):
            self.assertFalse(r[3].isVisible(),
                             "l'ouverture auto a repris le dessus sur le choix")

    def test_le_compte_est_affiche(self):
        self._items()
        txt = _entete_repliable(self.menu, "CANAUX AVANCÉS").text()
        n = len(_section(_walk(self.menu), "CANAUX AVANCÉS"))
        self.assertIn(str(n), txt, f"l'en-tete {txt!r} n'annonce pas ses {n} lignes")

    # ── Fixtures sans canal technique ────────────────────────────────────
    def test_par_led_simple_sans_section_avancee(self):
        pdf, proj = _make_pdf(["Dim", "R", "G", "B"], "PAR LED")
        pdf.selected_lamps = {("lyre", 0)}
        from PySide6.QtCore import QPoint
        pdf._show_fixture_context_menu(QPoint(0, 0), 0)
        items = _walk(self.menu)
        self.assertNotIn(("label", "CANAUX AVANCÉS"), items)


if __name__ == "__main__":
    unittest.main(verbosity=2)
