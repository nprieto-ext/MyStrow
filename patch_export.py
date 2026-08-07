"""
patch_export — Sorties « papier » du Patch DMX.

Deux exports construits sur les MÊMES données (build_patch_rows) :

  • export_patch_xlsx() : classeur Excel — feuille « Patch » (une ligne par
    appareil) + feuille « Adresses » (une ligne par canal DMX occupé).
  • export_patch_pdf()  : plan de feu A4 paysage (pictos aux emplacements du
    plan, avec l'adresse sous chaque appareil) + le tableau du patch.

Le .xlsx est écrit à la main (zipfile + SpreadsheetML minimal) : pas de
dépendance supplémentaire à embarquer dans les configs de build (openpyxl
aurait dû être ajouté à requirements.txt + au .spec + aux jobs CI).

Le PDF est dessiné sur fond BLANC — c'est une feuille qu'on imprime et qu'on
donne au régisseur de la salle, pas une capture de l'écran (fond noir). Les
pictos reprennent les silhouettes du canvas (cf. FixtureCanvas._draw_fixture)
pour qu'un appareil se reconnaisse d'un plan à l'autre.
"""

import datetime
import math
import zipfile

from PySide6.QtCore import QMarginsF, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QPageLayout, QPageSize, QPainter,
                           QPainterPath, QPdfWriter, QPen, QPolygon)

from core import APP_NAME, VERSION

# Couleurs de groupe — mêmes teintes que le plan de feu à l'écran.
GROUP_COLORS = {
    "face":     "#ff8844",
    "contre":   "#4488ff",
    "douche1":  "#44cc88",
    "douche2":  "#ffcc44",
    "douche3":  "#ff4488",
    "lat":      "#aa55ff",
    "lyre":     "#ff44cc",
    "barre":    "#44aaff",
    "strobe":   "#ffee44",
    "fumee":    "#88aaaa",
    "public":   "#ff6655",
    "groupe_g": "#22ddcc",
    "groupe_h": "#ff7722",
}

GROUP_LABELS = {
    "face": "A", "lat": "B", "contre": "C",
    "douche1": "D", "douche2": "E", "douche3": "F",
    "groupe_g": "G", "groupe_h": "H",
    "public": "Public", "fumee": "Fumée",
    "lyre": "Lyres", "barre": "Barres", "strobe": "Strobos",
}

# Positions par défaut quand une fixture n'a jamais été déplacée sur le plan
# (copie de plan_de_feu._DEFAULT_POSITIONS : le PDF doit montrer la même chose
# que l'écran, y compris pour un patch tout neuf).
_DEFAULT_POSITIONS = {
    "face":     lambda li, n: (0.20 + li * 0.60 / max(n - 1, 1), 0.80),
    "contre":   lambda li, n: (0.15 + li * 0.70 / max(n - 1, 1), 0.10),
    "douche1":  lambda li, n: (0.20 + li * 0.20 / max(n - 1, 1), 0.50),
    "douche2":  lambda li, n: (0.40 + li * 0.20 / max(n - 1, 1), 0.50),
    "douche3":  lambda li, n: (0.60 + li * 0.20 / max(n - 1, 1), 0.50),
    "lat":      lambda li, n: (0.07 if li == 0 else 0.93, 0.50),
    "public":   lambda li, n: (0.50, 0.90),
    "fumee":    lambda li, n: (0.10, 0.90),
    "lyre":     lambda li, n: (0.15 + li * 0.70 / max(n - 1, 1), 0.25),
    "barre":    lambda li, n: (0.15 + li * 0.70 / max(n - 1, 1), 0.35),
    "strobe":   lambda li, n: (0.15 + li * 0.70 / max(n - 1, 1), 0.45),
    "groupe_g": lambda li, n: (0.20 + li * 0.60 / max(n - 1, 1), 0.62),
    "groupe_h": lambda li, n: (0.20 + li * 0.60 / max(n - 1, 1), 0.46),
}


# ─────────────────────────────────────────────────────────────────────────────
#  Collecte des données
# ─────────────────────────────────────────────────────────────────────────────

def _norm_pos(projectors, i):
    """Position normalisée (0-1) d'une fixture, défaut de groupe si jamais posée."""
    proj = projectors[i]
    cx = getattr(proj, 'canvas_x', None)
    cy = getattr(proj, 'canvas_y', None)
    if cx is not None and cy is not None:
        return float(cx), float(cy)
    group = proj.group
    idxs = [j for j, p in enumerate(projectors) if p.group == group]
    li = idxs.index(i) if i in idxs else 0
    fn = _DEFAULT_POSITIONS.get(group, lambda li, n: (0.5, 0.5))
    return fn(li, len(idxs))


def build_patch_rows(projectors, profile_of):
    """Une entrée par APPAREIL — les pixels d'une matrice sont regroupés.

    `profile_of(i, proj)` renvoie la liste des types de canaux de la fixture i
    (["Dimmer", "Red", ...]). Une matrice/barre à pixels compte pour une seule
    ligne : sortir 128 lignes « Barre · px 37 » rendrait le tableau illisible,
    l'occupation DMX réelle reste visible via la plage adresse → fin.
    """
    rows = []
    seen_matrix = set()

    for i, proj in enumerate(projectors):
        mid = getattr(proj, 'matrix_id', None)

        if mid is not None:
            if mid in seen_matrix:
                continue
            seen_matrix.add(mid)
            members = [(j, p) for j, p in enumerate(projectors)
                       if getattr(p, 'matrix_id', None) == mid]
            pixels = [(j, p) for j, p in members
                      if getattr(p, 'matrix_role', None) != 'master']
            if not pixels:
                pixels = members
            head = pixels[0][1]
            px_profile = profile_of(pixels[0][0], head)
            # L'étendue se calcule sur TOUS les membres, master compris : une
            # matrice à canaux de tête (Dim/Strobe globaux) commence AVANT son
            # premier pixel. Partir du pixel 1 imprimerait une adresse de départ
            # fausse — celle qu'on va justement composer sur l'appareil.
            master_profile = []
            for j, p in members:
                if getattr(p, 'matrix_role', None) == 'master':
                    master_profile = profile_of(j, p)
            profile = (list(master_profile) + ["⟨px⟩"] + list(px_profile)
                       if master_profile else list(px_profile))
            addr = min(p.start_address for _j, p in members)
            end = max(p.start_address + max(len(profile_of(j, p)), 1) - 1
                      for j, p in members)
            rmat = getattr(head, 'matrix_rows', 0) or 0
            cmat = getattr(head, 'matrix_cols', 0) or 0
            note = (f"Matrice {rmat}×{cmat} — {len(pixels)} px × "
                    f"{max(len(px_profile), 1)} ch") if (rmat or cmat) \
                else f"{len(pixels)} pixels × {max(len(px_profile), 1)} ch"
            x, y = _norm_pos(projectors, pixels[0][0])
            rows.append({
                'name': (head.name or "Matrice").split(" · ")[0],
                'ftype': getattr(head, 'fixture_type', 'Barre LED'),
                'group': head.group,
                'universe': int(getattr(head, 'universe', 0) or 0),
                'address': addr,
                'end': end,
                'nch': end - addr + 1,
                'profile': profile,
                'note': note,
                'x': x, 'y': y,
                'members': [j for j, _p in pixels],
                'is_matrix': True,
                'height': getattr(head, 'fixture_height', None),
            })
            continue

        profile = profile_of(i, proj)
        addr = int(proj.start_address)
        x, y = _norm_pos(projectors, i)
        rows.append({
            'name': proj.name or proj.group,
            'ftype': getattr(proj, 'fixture_type', 'PAR LED'),
            'group': proj.group,
            'universe': int(getattr(proj, 'universe', 0) or 0),
            'address': addr,
            'end': addr + max(len(profile), 1) - 1,
            'nch': max(len(profile), 1),
            'profile': profile,
            'note': "",
            'x': x, 'y': y,
            'members': [i],
            'is_matrix': False,
            'height': getattr(proj, 'fixture_height', None),
        })

    for n, row in enumerate(rows, 1):
        row['index'] = n
    return rows


def build_channel_rows(projectors, profile_of):
    """Une ligne par canal DMX occupé : (univers, canal, nom fixture, fonction).

    Ici les pixels sont détaillés — c'est justement la feuille qu'on lit pour
    savoir qui occupe le canal 137.
    """
    out = []
    for i, proj in enumerate(projectors):
        profile = profile_of(i, proj)
        if not profile:
            continue
        uni = int(getattr(proj, 'universe', 0) or 0)
        name = proj.name or proj.group
        for k, ch_type in enumerate(profile):
            addr = int(proj.start_address) + k
            if addr > 512:
                break
            out.append((uni, addr, name, ch_type))
    out.sort(key=lambda r: (r[0], r[1]))
    return out


def find_conflicts(channel_rows):
    """{(univers, canal): [noms]} des canaux revendiqués par 2 appareils.

    Un chevauchement d'adresses est LA panne qu'on cherche en imprimant un
    patch : deux appareils qui bougent ensemble sans raison. Autant le signaler
    noir sur blanc plutôt que de laisser le régisseur comparer 300 lignes.
    """
    used = {}
    for uni, addr, name, _ch in channel_rows:
        used.setdefault((uni, addr), []).append(name)
    return {k: v for k, v in used.items() if len(set(v)) > 1}


def _group_label(group):
    return GROUP_LABELS.get(group, group.capitalize())


def _group_color(group):
    return GROUP_COLORS.get(group, "#777777")


# ─────────────────────────────────────────────────────────────────────────────
#  Export XLSX (écriture directe du format OOXML)
# ─────────────────────────────────────────────────────────────────────────────

_SHEET1_COLS = [
    ("N°", 6), ("Nom", 26), ("Type", 18), ("Groupe", 11), ("Univers", 9),
    ("Adresse", 10), ("Fin", 8), ("Canaux", 9), ("Profil DMX", 52),
    ("Remarque", 22), ("X %", 7), ("Y %", 7),
]

_SHEET2_COLS = [
    ("Univers", 9), ("Canal", 8), ("Repère", 12), ("Appareil", 30),
    ("Fonction", 22),
]


def _xml_escape(s):
    s = "" if s is None else str(s)
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Les caractères de contrôle font rejeter le fichier par Excel.
    return "".join(c for c in s if c >= " " or c in "\t\n")


def _col_letter(n):
    """1 → A, 27 → AA."""
    out = ""
    while n > 0:
        n, rem = divmod(n - 1, 26)
        out = chr(65 + rem) + out
    return out


def _cell(col, row, value, style=0):
    ref = f"{_col_letter(col)}{row}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return f'<c r="{ref}" s="{style}"><v>{value}</v></c>'
    txt = _xml_escape(value)
    if not txt:
        return f'<c r="{ref}" s="{style}"/>'
    return (f'<c r="{ref}" s="{style}" t="inlineStr"><is>'
            f'<t xml:space="preserve">{txt}</t></is></c>')


def _sheet_xml(cols, rows_cells, n_rows):
    cols_xml = "".join(
        f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
        for i, (_h, w) in enumerate(cols, 1)
    )
    last = _col_letter(len(cols))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last}{max(n_rows, 1)}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        '<sheetFormatPr defaultRowHeight="15"/>'
        f'<cols>{cols_xml}</cols>'
        f'<sheetData>{rows_cells}</sheetData>'
        f'<autoFilter ref="A1:{last}{max(n_rows, 1)}"/>'
        '</worksheet>'
    )


def _styles_xml(group_hexes):
    """Feuille de styles : en-tête sombre, texte, nombres, pastilles de groupe.

    Les fills 0 (none) et 1 (gray125) sont imposés par le format — Excel refuse
    le classeur si on les remplace.
    """
    fills = ['<fill><patternFill patternType="none"/></fill>',
             '<fill><patternFill patternType="gray125"/></fill>',
             '<fill><patternFill patternType="solid"><fgColor rgb="FF1F2937"/>'
             '<bgColor indexed="64"/></patternFill></fill>']
    for hx in group_hexes:
        fills.append('<fill><patternFill patternType="solid">'
                     f'<fgColor rgb="FF{hx}"/><bgColor indexed="64"/>'
                     '</patternFill></fill>')

    border_thin = ('<border><left/><right/><top/>'
                   '<bottom style="thin"><color rgb="FFDDDDDD"/></bottom>'
                   '<diagonal/></border>')
    # Styles fixes : 0 général · 1 en-tête · 2 texte · 3 nombre · 4 adresse
    # (gras) · 5 monospace (profil) ; puis une pastille par groupe.
    xfs = [
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>',
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1"'
        ' applyFill="1" applyAlignment="1"><alignment horizontal="center"'
        ' vertical="center" wrapText="1"/></xf>',
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"'
        ' applyAlignment="1"><alignment vertical="center"/></xf>',
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1"'
        ' applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>',
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1"'
        ' applyBorder="1" applyAlignment="1"><alignment horizontal="center"'
        ' vertical="center"/></xf>',
        '<xf numFmtId="0" fontId="3" fillId="0" borderId="1" xfId="0" applyFont="1"'
        ' applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>',
    ]
    for k in range(len(group_hexes)):
        xfs.append(
            f'<xf numFmtId="0" fontId="2" fillId="{3 + k}" borderId="1" xfId="0"'
            ' applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1">'
            '<alignment horizontal="center" vertical="center"/></xf>')

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="4">'
        '<font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font>'
        '<font><sz val="10"/><name val="Consolas"/></font>'
        '</fonts>'
        f'<fills count="{len(fills)}">{"".join(fills)}</fills>'
        f'<borders count="2"><border><left/><right/><top/><bottom/><diagonal/></border>'
        f'{border_thin}</borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        '</styleSheet>'
    )


def export_patch_xlsx(path, projectors, profile_of, show_name=""):
    """Écrit le classeur Excel du patch. Retourne (n_appareils, n_canaux)."""
    rows = build_patch_rows(projectors, profile_of)
    ch_rows = build_channel_rows(projectors, profile_of)

    # Une pastille de couleur par groupe présent dans le patch
    groups = []
    for r in rows:
        if r['group'] not in groups:
            groups.append(r['group'])
    group_hexes = [_group_color(g).lstrip("#").upper() for g in groups]
    group_style = {g: 6 + k for k, g in enumerate(groups)}

    # ── Feuille 1 : Patch ────────────────────────────────────────────────
    cells = ["<row r=\"1\" ht=\"28\" customHeight=\"1\">" + "".join(
        _cell(c, 1, h, 1) for c, (h, _w) in enumerate(_SHEET1_COLS, 1)) + "</row>"]
    for n, r in enumerate(rows, 2):
        vals = [
            (r['index'], 3),
            (r['name'], 2),
            (r['ftype'], 2),
            (_group_label(r['group']), group_style.get(r['group'], 3)),
            (r['universe'] + 1, 3),
            (r['address'], 4),
            (r['end'], 3),
            (r['nch'], 3),
            (" · ".join(r['profile']), 5),
            (r['note'], 2),
            (round(r['x'] * 100, 1), 3),
            (round(r['y'] * 100, 1), 3),
        ]
        cells.append(f'<row r="{n}">' + "".join(
            _cell(c, n, v, s) for c, (v, s) in enumerate(vals, 1)) + "</row>")
    sheet1 = _sheet_xml(_SHEET1_COLS, "".join(cells), len(rows) + 1)

    # ── Feuille 2 : Adresses ─────────────────────────────────────────────
    cells2 = ["<row r=\"1\" ht=\"28\" customHeight=\"1\">" + "".join(
        _cell(c, 1, h, 1) for c, (h, _w) in enumerate(_SHEET2_COLS, 1)) + "</row>"]
    for n, (uni, addr, name, ch_type) in enumerate(ch_rows, 2):
        vals = [
            (uni + 1, 3),
            (addr, 4),
            (f"{uni + 1}.{addr:03d}", 3),
            (name, 2),
            (ch_type, 2),
        ]
        cells2.append(f'<row r="{n}">' + "".join(
            _cell(c, n, v, s) for c, (v, s) in enumerate(vals, 1)) + "</row>")
    sheet2 = _sheet_xml(_SHEET2_COLS, "".join(cells2), len(ch_rows) + 1)

    title = f"{APP_NAME} — Patch DMX" + (f" — {show_name}" if show_name else "")
    now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '</Types>')
        z.writestr("_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '</Relationships>')
        z.writestr("docProps/core.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
            ' xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"'
            ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_xml_escape(title)}</dc:title>'
            f'<dc:creator>{APP_NAME} {VERSION}</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            '</cp:coreProperties>')
        z.writestr("xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
            ' xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets>'
            '<sheet name="Patch" sheetId="1" r:id="rId1"/>'
            '<sheet name="Adresses" sheetId="2" r:id="rId2"/>'
            '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>')
        z.writestr("xl/styles.xml", _styles_xml(group_hexes))
        z.writestr("xl/worksheets/sheet1.xml", sheet1)
        z.writestr("xl/worksheets/sheet2.xml", sheet2)

    return len(rows), len(ch_rows)


# ─────────────────────────────────────────────────────────────────────────────
#  Export PDF
# ─────────────────────────────────────────────────────────────────────────────

_INK = QColor("#1a1a1a")
_INK_SOFT = QColor("#6b6b6b")
_RULE = QColor("#d8d8d8")


def _pt(painter, size, bold=False):
    f = QFont("Segoe UI", size)
    f.setBold(bold)
    painter.setFont(f)
    return f


def _draw_picto(painter, cx, cy, r, ftype, color):
    """Silhouette de l'appareil, version encre sur papier.

    Mêmes formes que le plan à l'écran (FixtureCanvas._draw_fixture) mais sans
    halo ni dégradé : à l'impression, un aplat clair cerné de la couleur du
    groupe reste lisible en noir et blanc comme en couleur.
    """
    fill = QColor(color)
    fill.setAlpha(70)
    line = QPen(QColor(color).darker(135), max(1.0, r * 0.09))
    painter.setPen(line)
    painter.setBrush(fill)

    if ftype == "Moving Head":
        lr = r * 1.35
        yoke_top_hw = lr * 0.88
        yoke_bot_hw = lr * 0.54
        bar_t = max(2.0, lr * 0.26)
        arm_t = max(2.0, lr * 0.26)
        arm_bot_y = cy + lr * 0.08
        head_r = lr * 0.46
        # Barre d'accroche
        painter.drawRoundedRect(QRectF(cx - yoke_top_hw, cy - lr,
                                       yoke_top_hw * 2, bar_t),
                                bar_t / 2, bar_t / 2)
        # Bras (trapèzes)
        for sgn in (-1, 1):
            painter.drawPolygon(QPolygon([
                QPoint(int(cx + sgn * yoke_top_hw), int(cy - lr + bar_t)),
                QPoint(int(cx + sgn * (yoke_top_hw - arm_t)), int(cy - lr + bar_t)),
                QPoint(int(cx + sgn * (yoke_bot_hw - arm_t * 0.8)), int(arm_bot_y)),
                QPoint(int(cx + sgn * yoke_bot_hw), int(arm_bot_y)),
            ]))
        # Tête + lentille
        painter.drawEllipse(QPointF(cx, arm_bot_y), head_r, head_r)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, arm_bot_y), head_r * 0.55, head_r * 0.55)

    elif ftype == "Barre LED":
        hw, hh = r * 1.30, max(2.5, r * 0.40)
        painter.drawRoundedRect(QRectF(cx - hw, cy - hh, hw * 2, hh * 2),
                                hh * 0.5, hh * 0.5)
        painter.setPen(QPen(QColor(color).darker(135), max(1.0, r * 0.06)))
        for seg in range(1, 4):
            sx = cx - hw + seg * (hw * 2 / 4)
            painter.drawLine(QPointF(sx, cy - hh + 1), QPointF(sx, cy + hh - 1))

    elif ftype == "Stroboscope":
        hw, hh = r * 1.18, r * 0.66
        painter.drawRoundedRect(QRectF(cx - hw, cy - hh, hw * 2, hh * 2),
                                r * 0.16, r * 0.16)
        cell_r = max(1.0, min(hw / 4, hh / 2) * 0.42)
        painter.setBrush(QColor(color).darker(120))
        painter.setPen(Qt.NoPen)
        for row in range(2):
            for col in range(4):
                painter.drawEllipse(
                    QPointF(cx - hw + hw / 4 + col * (hw / 2),
                            cy - hh + hh / 2 + row * hh),
                    cell_r, cell_r)

    elif ftype == "Machine a fumee":
        hw, hh = r * 0.95, r * 0.50
        painter.drawEllipse(QRectF(cx - hw, cy - hh, hw * 2, hh * 2))
        painter.setBrush(QColor(color).lighter(120))
        painter.setPen(Qt.NoPen)
        for ox, oy, sr in ((-0.55, -0.85, 0.36), (0.0, -1.05, 0.42),
                           (0.55, -0.85, 0.36)):
            painter.drawEllipse(QPointF(cx + ox * r, cy + oy * r), sr * r, sr * r)

    elif ftype == "Gradateur":
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setPen(QPen(QColor(color).darker(160), 1))
        f = painter.font()
        f.setBold(True)
        f.setPixelSize(max(6, int(r * 1.1)))
        painter.setFont(f)
        painter.drawText(QRectF(cx - r, cy - r, r * 2, r * 2), Qt.AlignCenter, "T")

    else:  # PAR LED / défaut
        painter.drawEllipse(QPointF(cx, cy), r, r)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), r * 0.52, r * 0.52)

    painter.setBrush(Qt.NoBrush)


def _draw_matrix_picto(painter, x0, y0, x1, y1, color):
    """Barre/matrice à pixels : un cadre + une trame de cellules."""
    fill = QColor(color)
    fill.setAlpha(55)
    painter.setPen(QPen(QColor(color).darker(135), 2, Qt.DashLine))
    painter.setBrush(fill)
    painter.drawRoundedRect(QRectF(x0, y0, x1 - x0, y1 - y0), 6, 6)
    painter.setBrush(Qt.NoBrush)


def _header(painter, W, title, subtitle):
    _pt(painter, 15, True)
    painter.setPen(_INK)
    painter.drawText(QRectF(0, 0, W, 60), Qt.AlignLeft | Qt.AlignVCenter, title)
    _pt(painter, 8)
    painter.setPen(_INK_SOFT)
    painter.drawText(QRectF(0, 0, W, 60), Qt.AlignRight | Qt.AlignVCenter, subtitle)
    painter.setPen(QPen(_INK, 2))
    painter.drawLine(QPointF(0, 62), QPointF(W, 62))


def _footer(painter, W, H, page, total):
    _pt(painter, 7)
    painter.setPen(_INK_SOFT)
    painter.drawText(QRectF(0, H - 34, W, 30), Qt.AlignLeft | Qt.AlignVCenter,
                     f"{APP_NAME} {VERSION}")
    painter.drawText(QRectF(0, H - 34, W, 30), Qt.AlignRight | Qt.AlignVCenter,
                     f"Page {page}/{total}")


def _draw_plan(painter, W, H, rows, projectors, multi_universe):
    """Page « plan de feu » : scène, pictos aux emplacements, adresses."""
    top = 96
    legend_h = 150
    sx, sy = 0.0, float(top)
    sw = float(W)
    sh = float(H - top - legend_h - 40)

    # Plateau
    stage = QPainterPath()
    stage.addRoundedRect(QRectF(sx, sy, sw, sh), 14, 14)
    painter.fillPath(stage, QColor("#fbfbfc"))
    painter.setPen(QPen(_RULE, 2))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(stage)

    # Grille de repérage (quarts de plateau)
    painter.setPen(QPen(QColor("#eeeeee"), 1, Qt.DashLine))
    for c in range(1, 4):
        x = sx + c * sw / 4
        painter.drawLine(QPointF(x, sy + 12), QPointF(x, sy + sh - 12))
    for r_ in range(1, 4):
        y = sy + r_ * sh / 4
        painter.drawLine(QPointF(sx + 12, y), QPointF(sx + sw - 12, y))

    # Repères scène : le haut du plan est le lointain, le bas la face/public
    _pt(painter, 8, True)
    painter.setPen(QColor("#b0b0b0"))
    _fh = painter.fontMetrics().height()
    painter.drawText(QRectF(sx, sy + 12, sw, _fh),
                     Qt.AlignHCenter | Qt.AlignVCenter, "LOINTAIN  ·  CONTRE")
    painter.drawText(QRectF(sx, sy + sh - 14 - _fh, sw, _fh),
                     Qt.AlignHCenter | Qt.AlignVCenter, "FACE  ·  PUBLIC")

    # Échelle des pictos : lisible sans se chevaucher quand le rig est dense
    r = min(sw, sh) * 0.020
    r = max(11.0, min(30.0, r))

    # Passe 1 : les pictos (les étiquettes viennent après, sinon un picto
    # dessiné plus tard recouvre le nom du voisin déjà écrit).
    anchors = []
    for row in rows:
        color = _group_color(row['group'])
        cx = sx + row['x'] * sw
        cy = sy + row['y'] * sh

        if row['is_matrix'] and len(row['members']) > 1:
            pts = [_norm_pos(projectors, j) for j in row['members']]
            xs = [sx + p[0] * sw for p in pts]
            ys = [sy + p[1] * sh for p in pts]
            pad = r * 0.7
            _draw_matrix_picto(painter, min(xs) - pad, min(ys) - pad,
                               max(xs) + pad, max(ys) + pad, color)
            cx = (min(xs) + max(xs)) / 2
            cy = max(ys) + pad
        else:
            _draw_picto(painter, cx, cy, r, row['ftype'], color)
        anchors.append((row, cx, cy))

    # Passe 2 : nom + adresse sous chaque appareil. Les rectangles font une
    # hauteur de ligne PLEINE (fontMetrics) — trop juste, le jambage des « y »
    # et des « p » se fait raboter (« Lyre » devenait « Lvre »).
    # Sur une passerelle chargée, deux appareils voisins écriraient l'un sur
    # l'autre : l'étiquette descend alors d'un cran tant qu'elle en croise une
    # autre. Un plan illisible ne sert à rien en salle.
    _pt(painter, 7)
    lh = painter.fontMetrics().height()
    placed = []
    for row, cx, cy in sorted(anchors, key=lambda a: (a[2], a[1])):
        addr = (f"{row['universe'] + 1}.{row['address']:03d}"
                if multi_universe else f"{row['address']:03d}")
        name = row['name'][:18]
        _pt(painter, 7)
        wl = painter.fontMetrics().horizontalAdvance(name)
        _pt(painter, 7, True)
        wl = max(wl, painter.fontMetrics().horizontalAdvance(addr)) + 10

        box = QRectF(cx - wl / 2, cy + r * 1.15, wl, lh * 2)
        for _try in range(6):
            if not any(box.intersects(p) for p in placed):
                break
            box.translate(0, lh * 2)
        # Empilé trop bas, on sortirait du plateau : on remonte au-dessus du
        # picto plutôt que d'écrire par-dessus le bord (ou hors page).
        if box.bottom() > sy + sh - 6:
            box = QRectF(cx - wl / 2, cy - r * 1.15 - lh * 2, wl, lh * 2)
            for _try in range(6):
                if not any(box.intersects(p) for p in placed):
                    break
                box.translate(0, -lh * 2)
        placed.append(QRectF(box))

        _pt(painter, 7)
        painter.setPen(_INK)
        painter.drawText(QRectF(box.x(), box.y(), wl, lh),
                         Qt.AlignHCenter | Qt.AlignVCenter, name)
        # Adresse — l'information qu'on vient chercher sur un plan
        _pt(painter, 7, True)
        painter.setPen(QColor(_group_color(row['group'])).darker(175))
        painter.drawText(QRectF(box.x(), box.y() + lh, wl, lh),
                         Qt.AlignHCenter | Qt.AlignVCenter, addr)

    # ── Légende des groupes ──────────────────────────────────────────────
    ly = sy + sh + 26
    painter.setPen(QPen(_RULE, 1))
    painter.drawLine(QPointF(0, ly - 12), QPointF(W, ly - 12))

    counts = {}
    for row in rows:
        counts[row['group']] = counts.get(row['group'], 0) + 1

    _pt(painter, 8)
    lh = painter.fontMetrics().height()
    chip = lh * 0.72
    x = 0.0
    for group, n in counts.items():
        label = f"{_group_label(group)} — {n}"
        w = painter.fontMetrics().horizontalAdvance(label) + chip + 46
        if x + w > W:
            x = 0.0
            ly += lh + 10
        painter.setPen(QPen(QColor(_group_color(group)).darker(130), 1))
        c = QColor(_group_color(group))
        c.setAlpha(90)
        painter.setBrush(c)
        painter.drawRoundedRect(QRectF(x, ly + (lh - chip) / 2, chip, chip), 4, 4)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(_INK)
        painter.drawText(QRectF(x + chip + 10, ly, w, lh),
                         Qt.AlignLeft | Qt.AlignVCenter, label)
        x += w

    _pt(painter, 7)
    painter.setPen(_INK_SOFT)
    painter.drawText(
        QRectF(0, ly + lh + 12, W, painter.fontMetrics().height()),
        Qt.AlignLeft | Qt.AlignVCenter,
        "Adresse indiquée sous chaque appareil"
        + (" au format univers.adresse" if multi_universe else "")
        + "  ·  vue de dessus, public en bas de page")


_TABLE_COLS = [
    ("N°", 0.035, Qt.AlignHCenter),
    ("Nom", 0.185, Qt.AlignLeft),
    ("Type", 0.125, Qt.AlignLeft),
    ("Groupe", 0.075, Qt.AlignHCenter),
    ("Univ.", 0.050, Qt.AlignHCenter),
    ("Adresse", 0.070, Qt.AlignHCenter),
    ("Fin", 0.050, Qt.AlignHCenter),
    ("Can.", 0.050, Qt.AlignHCenter),
    ("Profil DMX", 0.360, Qt.AlignLeft),
]


_ROW_H = 44.0      # hauteur d'une ligne de tableau
_TABLE_Y0 = 116.0  # première ligne (sous l'en-tête de page)
_BOTTOM = 60.0     # réserve pour le pied de page


def _rows_per_page(H):
    """Lignes de données par page — DOIT suivre la boucle de _draw_table_page.

    Les deux calculs ont divergé une fois : le total affiché en pied de page
    annonçait une page de moins qu'il n'en sortait.
    """
    usable = H - _BOTTOM - _TABLE_Y0 - _ROW_H
    return max(1, int(usable // _ROW_H))


def _draw_table_page(painter, W, H, rows, y0):
    """Dessine autant de lignes que la page en accepte. Retourne le reste."""
    row_h = _ROW_H
    y = y0

    # En-tête de colonnes
    painter.setBrush(QColor("#1f2937"))
    painter.setPen(Qt.NoPen)
    painter.drawRect(QRectF(0, y, W, row_h))
    _pt(painter, 8, True)
    painter.setPen(QColor("#ffffff"))
    x = 0.0
    for title, frac, align in _TABLE_COLS:
        w = W * frac
        painter.drawText(QRectF(x + 8, y, w - 16, row_h),
                         align | Qt.AlignVCenter, title)
        x += w
    y += row_h

    painter.setBrush(Qt.NoBrush)
    bottom = H - _BOTTOM
    idx = 0
    for row in rows:
        if y + row_h > bottom:
            break
        if idx % 2 == 1:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#f6f7f9"))
            painter.drawRect(QRectF(0, y, W, row_h))
            painter.setBrush(Qt.NoBrush)

        values = [
            str(row['index']),
            row['name'],
            row['ftype'],
            _group_label(row['group']),
            str(row['universe'] + 1),
            f"{row['address']:03d}",
            f"{row['end']:03d}",
            str(row['nch']),
            " · ".join(row['profile']) + (f"   [{row['note']}]" if row['note'] else ""),
        ]
        x = 0.0
        for k, ((_t, frac, align), val) in enumerate(zip(_TABLE_COLS, values)):
            w = W * frac
            if k == 3:   # pastille de groupe
                c = QColor(_group_color(row['group']))
                c.setAlpha(80)
                painter.setPen(Qt.NoPen)
                painter.setBrush(c)
                painter.drawRoundedRect(QRectF(x + 10, y + 7, w - 20, row_h - 14), 5, 5)
                painter.setBrush(Qt.NoBrush)
            _pt(painter, 8, bold=(k == 5))
            painter.setPen(_INK if k != 8 else _INK_SOFT)
            fm = painter.fontMetrics()
            txt = fm.elidedText(val, Qt.ElideRight, int(w - 16))
            painter.drawText(QRectF(x + 8, y, w - 16, row_h),
                             align | Qt.AlignVCenter, txt)
            x += w

        painter.setPen(QPen(_RULE, 1))
        painter.drawLine(QPointF(0, y + row_h), QPointF(W, y + row_h))
        y += row_h
        idx += 1

    return list(rows[idx:])


def export_patch_pdf(path, projectors, profile_of, show_name=""):
    """Écrit le PDF : page 1 = plan de feu, pages suivantes = tableau du patch."""
    rows = build_patch_rows(projectors, profile_of)
    ch_rows = build_channel_rows(projectors, profile_of)
    conflicts = find_conflicts(ch_rows)
    universes = sorted({r['universe'] for r in rows})
    multi_universe = len(universes) > 1

    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QPageSize.A4))
    writer.setPageOrientation(QPageLayout.Landscape)
    writer.setPageMargins(QMarginsF(12, 10, 12, 10), QPageLayout.Millimeter)
    writer.setResolution(300)
    writer.setTitle(f"{APP_NAME} — Patch DMX" + (f" — {show_name}" if show_name else ""))
    writer.setCreator(f"{APP_NAME} {VERSION}")

    painter = QPainter(writer)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)

    W = float(painter.viewport().width())
    H = float(painter.viewport().height())

    date = datetime.datetime.now().strftime("%d/%m/%Y")
    uni_txt = ("Univers " + ", ".join(str(u + 1) for u in universes)) if universes else "—"
    subtitle = f"{len(rows)} appareils  ·  {len(ch_rows)} canaux  ·  {uni_txt}  ·  {date}"
    title = "PLAN DE FEU" + (f" — {show_name}" if show_name else "")

    # Pagination : 1 (plan) + pages de tableau + 1 si des adresses se marchent
    # dessus (page de conflits).
    per_page = _rows_per_page(H)
    n_table_pages = max(1, math.ceil(len(rows) / per_page))
    total_pages = 1 + n_table_pages + (1 if conflicts else 0)

    # ── Page 1 : le plan ─────────────────────────────────────────────────
    _header(painter, W, title, subtitle)
    _draw_plan(painter, W, H, rows, projectors, multi_universe)
    _footer(painter, W, H, 1, total_pages)

    # ── Pages suivantes : le tableau ─────────────────────────────────────
    rest = rows
    page = 2
    while rest:
        writer.newPage()
        _header(painter, W, "PATCH DMX" + (f" — {show_name}" if show_name else ""),
                subtitle)
        rest = _draw_table_page(painter, W, H, rest, _TABLE_Y0)
        _footer(painter, W, H, page, total_pages)
        page += 1

    # ── Alerte chevauchements ────────────────────────────────────────────
    if conflicts:
        writer.newPage()
        _header(painter, W, "CONFLITS D'ADRESSES", subtitle)
        _pt(painter, 9, True)
        lh = painter.fontMetrics().height()
        y = 130.0
        painter.setPen(QColor("#b03030"))
        painter.drawText(QRectF(0, y, W, lh), Qt.AlignLeft | Qt.AlignVCenter,
                         f"{len(conflicts)} canal(aux) revendiqué(s) par plusieurs appareils")
        y += lh * 1.4
        _pt(painter, 8)
        lh = painter.fontMetrics().height()
        painter.setPen(_INK_SOFT)
        painter.drawText(QRectF(0, y, W, lh), Qt.AlignLeft | Qt.AlignVCenter,
                         "Deux appareils sur le même canal bougent ensemble sans raison. "
                         "Édition ▸ ⚡ Auto-adressage réattribue tout le patch proprement.")
        y += lh * 2.0
        painter.setPen(_INK)
        step = lh * 1.25
        for (uni, addr), names in sorted(conflicts.items()):
            if y + step > H - 80:
                painter.drawText(QRectF(0, y, W, lh), Qt.AlignLeft | Qt.AlignVCenter, "   …")
                break
            painter.drawText(
                QRectF(0, y, W, lh), Qt.AlignLeft | Qt.AlignVCenter,
                f"   {uni + 1}.{addr:03d}   →   " + "  /  ".join(sorted(set(names))))
            y += step
        _footer(painter, W, H, page, total_pages)

    painter.end()
    return len(rows), len(conflicts)
