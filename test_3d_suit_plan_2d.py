"""Le plan de feu 2D doit rester maître de la position 3D déduite.

Scénario remonté le 27/08/2026 : 25 lyres placées en 2D et en 3D, on en
supprime 20, et les 5 restantes se déplacent en 2D sans bouger d'un pouce en
3D. Seul remède trouvé : supprimer les 5 et les repatcher.

Cause : la provenance de la position 3D (`_pos3d_src`) a TROIS états — un tuple
(déduite du plan 2D), None (posée à la main) et ABSENT (jamais affichée en 3D,
à migrer). La sauvegarde du patch écrivait `null` pour l'absent, que le
chargement relisait en None : toute fixture jamais passée par la 3D était donc
promue « placement manuel » au redémarrage, et le plan 2D ne la pilotait plus.
"""
import json

from plan_3d_webwindow import (_pos3d_from_canvas, _sync_pos3d_with_canvas,
                               _set_pos3d_auto)


class _Proj:
    def __init__(self, cx, cy):
        self.canvas_x, self.canvas_y = cx, cy
        self.group, self.name = 'face', 'lyre'


def _sauver(proj):
    """Réplique de la sérialisation de `save_dmx_patch_config`."""
    fd = {'pos_x': proj.canvas_x, 'pos_y': proj.canvas_y,
          'pos_3d_x': getattr(proj, 'pos_3d_x', None),
          'pos_3d_z': getattr(proj, 'pos_3d_z', None)}
    if hasattr(proj, '_pos3d_src'):
        fd['pos_3d_src'] = list(proj._pos3d_src) if proj._pos3d_src else None
    return json.loads(json.dumps(fd))


def _charger(fd):
    """Réplique de la relecture de `load_dmx_patch_config`."""
    p = _Proj(fd['pos_x'], fd['pos_y'])
    p3x = fd.get('pos_3d_x')
    p3z = fd.get('pos_3d_z')
    if p3x is not None:
        p.pos_3d_x = float(p3x)
    if p3z is not None:
        p.pos_3d_z = float(p3z)
    if 'pos_3d_src' in fd and not (fd.get('pos_3d_src') is None and p3x is None):
        _src = fd.get('pos_3d_src')
        p._pos3d_src = ((float(_src[0]), float(_src[1]))
                        if _src and len(_src) == 2 else None)
    return p


def _pos_3d_affichee(p):
    """Position réellement envoyée à Three.js — comme dans `_to_data`."""
    _sync_pos3d_with_canvas(p, p.canvas_x, p.canvas_y)
    dx, dz = _pos3d_from_canvas(p.canvas_x, p.canvas_y)
    x = getattr(p, 'pos_3d_x', None)
    z = getattr(p, 'pos_3d_z', None)
    return (x if x is not None else dx, z if z is not None else dz)


def test_fixture_jamais_affichee_en_3d_suit_le_plan_apres_redemarrage():
    # Patch créé sans jamais ouvrir la 3D, puis sauvé et rechargé.
    p = _charger(_sauver(_Proj(0.30, 0.40)))

    # L'utilisateur déplace la lyre sur le plan de feu 2D.
    p.canvas_x, p.canvas_y = 0.70, 0.80
    assert _pos_3d_affichee(p) == _pos3d_from_canvas(0.70, 0.80)


def test_position_reglee_a_la_main_reste_maitresse():
    p = _Proj(0.30, 0.40)
    p.pos_3d_x, p.pos_3d_z = 4.2, -1.5
    p._pos3d_src = None                      # posée dans le tableau 3D
    p = _charger(_sauver(p))

    p.canvas_x, p.canvas_y = 0.70, 0.80
    assert _pos_3d_affichee(p) == (4.2, -1.5)


def test_position_deduite_survit_a_lenregistrement():
    p = _Proj(0.30, 0.40)
    _set_pos3d_auto(p, 0.30, 0.40)
    p = _charger(_sauver(p))
    assert p._pos3d_src == (0.30, 0.40)

    p.canvas_x, p.canvas_y = 0.15, 0.55
    assert _pos_3d_affichee(p) == _pos3d_from_canvas(0.15, 0.55)


def test_ouvrir_la_3d_ne_fige_pas_le_rig():
    """`_populate_mini` recopie le plan 2D : ça doit rester une position DÉDUITE."""
    p = _Proj(0.30, 0.40)
    _set_pos3d_auto(p, 0.30, 0.40)           # ce que fait le tableau à l'ouverture
    p = _charger(_sauver(p))

    p.canvas_x, p.canvas_y = 0.62, 0.22
    assert _pos_3d_affichee(p) == _pos3d_from_canvas(0.62, 0.22)
