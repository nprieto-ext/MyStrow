"""Déclaration URSSAF mensuelle : chiffre d'affaires HT du mois, séparé en
prestations de service et achat-revente, calculé depuis les factures Axonaut.

Lancée le 1er de chaque mois par la tâche `declaration_mensuelle` (main.py) :
  1. calcule chaque mois de l'année encore absent de Firestore
     (`declarations/{AAAA-MM}`) — au premier lancement, ça rattrape janvier
     à fin du mois écoulé ;
  2. écrit le Google Sheet `DECLARATION_SHEET_ID` : un onglet « Récap »
     (une ligne par mois) et un onglet de détail par mois ;
  3. envoie le mail récapitulatif (fait par main.py).

Classement d'une ligne de facture :
  - produit fixe « Interface » (AXONAUT_PRODUCT_INTERFACE) ou libellé
    « Interface USB-DMX … » hors pack                → achat-revente ;
  - ancienne ligne unique « Pack MyStrow — … »       → coupée comme les
    nouvelles factures (69 € TTC sur le prix catalogue du pack) ;
  - tout le reste (licences, abonnements, presta)    → prestation de service.
Les avoirs (quantité négative) viennent en déduction de leur catégorie.

Montant retenu : le HT (`total_pre_tax_amount`), comme la colonne N du
tableau URSSAF tenu à la main.

Mois de rattachement : la DATE D'ENCAISSEMENT (`paid_date`), règle de la
micro-entreprise (CA encaissé) — choix de Nicolas le 02/11/2026. Les ventes
Stripe sont payées le jour même ; seules les factures payées plus tard
(Tui France…) se décalent. Une facture partiellement payée ne compte qu'une
fois soldée (Axonaut ne pose `paid_date` qu'à ce moment-là).
"""
from __future__ import annotations

from datetime import datetime, timedelta

SERVICE = "Prestation de service"
REVENTE = "Achat-revente"

# Plafonds du régime micro (année 2026). Celui des services est celui du
# tableau URSSAF tenu à la main. À mettre à jour chaque année.
PLAFOND_SERVICE = 83_600
PLAFOND_REVENTE = 203_100

MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]


def mois_label(year: int, month: int) -> str:
    return f"{MOIS_FR[month - 1]} {year}"


# ── Classement ──────────────────────────────────────────────────────────────

def classify_line(line: dict, product_interface: int, interface_ttc: float,
                  pack_prix_ttc: dict[str, float]) -> list[tuple[str, float]]:
    """[(catégorie, HT)] pour une ligne de facture Axonaut."""
    ht   = float(line.get("total_pre_tax_amount") or 0)
    name = (line.get("name") or line.get("product_name") or "").strip()

    if line.get("product_id") == product_interface:
        return [(REVENTE, ht)]
    if name.startswith("Pack MyStrow"):
        # Factures émises avant la ventilation (une seule ligne par pack).
        prix = 399.0
        for cle, plan in (("2 mois", "pack_2m"), ("1 an", "pack_1a"),
                          ("vie", "pack_vie")):
            if cle in name:
                prix = pack_prix_ttc.get(plan, prix)
                break
        part = round(ht * interface_ttc / prix, 2)
        return [(REVENTE, part), (SERVICE, round(ht - part, 2))]
    if name.startswith("Interface USB-DMX"):
        return [(REVENTE, ht)]
    return [(SERVICE, ht)]


def compute_month(invoices: list[dict], year: int, month: int,
                  product_interface: int, interface_ttc: float,
                  pack_prix_ttc: dict[str, float]) -> dict:
    """Totaux HT du mois + lignes de détail."""
    prefix = f"{year:04d}-{month:02d}"
    tot  = {SERVICE: 0.0, REVENTE: 0.0}
    # Rattachement au mois d'ENCAISSEMENT (cf. en-tête du module).
    tva  = 0.0
    rows = []
    n    = 0
    for inv in invoices:
        if not (inv.get("paid_date") or "").startswith(prefix):
            continue
        n += 1
        tva += float(inv.get("tax_amount") or 0)
        client = ((inv.get("company") or {}).get("name") or "").strip()
        for line in inv.get("invoice_lines") or []:
            for cat, ht in classify_line(line, product_interface,
                                         interface_ttc, pack_prix_ttc):
                tot[cat] += ht
                rows.append([inv.get("number") or "", (inv.get("date") or "")[:10],
                             (inv.get("paid_date") or "")[:10], client, (line.get("name") or "")[:120], cat,
                             round(ht, 2)])
    return {
        "mois":        prefix,
        "service_ht":  round(tot[SERVICE], 2),
        "revente_ht":  round(tot[REVENTE], 2),
        "total_ht":    round(tot[SERVICE] + tot[REVENTE], 2),
        "tva":         round(tva, 2),
        "nb_factures": n,
        "rows":        sorted(rows, key=lambda r: (r[2], r[0])),
    }


# ── Lecture Axonaut ─────────────────────────────────────────────────────────

def fetch_month_invoices(axonaut_get, year: int, month: int,
                         lookback_months: int = 12) -> list[dict]:
    """Factures (et avoirs) susceptibles d'avoir été PAYÉES dans le mois.

    Axonaut ne filtre pas sur un intervalle de paiement : on prend toutes les
    factures ÉMISES dans les `lookback_months` précédents jusqu'à la fin du
    mois, et `compute_month` garde celles dont `paid_date` tombe dans le mois.

    `axonaut_get(path, page)` renvoie la liste JSON. Axonaut plafonne à 500
    factures par page (vérifié le 02/11/2026) et, au-delà de la dernière page,
    renvoie de nouveau des factures déjà vues : on dédoublonne par id et on
    s'arrête dès qu'une page n'apporte rien de nouveau.
    """
    fin = datetime(year + (month == 12), month % 12 + 1, 1)
    y0, m0 = year, month - lookback_months
    while m0 < 1:
        y0, m0 = y0 - 1, m0 + 12
    apres = (datetime(y0, m0, 1) - timedelta(days=1)).strftime("%d/%m/%Y")
    avant = fin.strftime("%d/%m/%Y")
    seen: dict = {}
    for page in range(1, 41):
        data = axonaut_get(f"/invoices?date_after={apres}&date_before={avant}", page)
        if not isinstance(data, list):
            raise RuntimeError(f"Axonaut /invoices a répondu {str(data)[:200]}")
        new = [i for i in data if i.get("id") not in seen]
        for i in data:
            seen[i.get("id")] = i
        if not new or len(data) < 500:
            break
    else:
        raise RuntimeError("Axonaut /invoices : plus de 40 pages, calcul interrompu")
    return list(seen.values())


# ── Google Sheet ────────────────────────────────────────────────────────────

RECAP = "Récap"
RECAP_HEADER = ["Mois", "Prestation de service HT", "Achat-revente HT",
                "Total HT", "TVA collectée", "Nb factures", "Calculé le"]
DETAIL_HEADER = ["N° facture", "Date facture", "Payée le", "Client", "Ligne",
                 "Catégorie", "HT"]


class Sheet:
    """Accès minimal à l'API Google Sheets v4 avec le compte de service de
    la Cloud Function (le Sheet doit lui être partagé en écriture)."""

    BASE = "https://sheets.googleapis.com/v4/spreadsheets"

    def __init__(self, sheet_id: str):
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        creds, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/spreadsheets"])
        self.s  = AuthorizedSession(creds)
        self.id = sheet_id

    def _req(self, method: str, path: str, **kw):
        r = self.s.request(method, f"{self.BASE}/{self.id}{path}", timeout=30, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Sheets {method} {path} → {r.status_code} {r.text[:300]}")
        return r.json() if r.text else {}

    def tabs(self) -> dict[str, int]:
        meta = self._req("GET", "?fields=sheets.properties")
        return {s["properties"]["title"]: s["properties"]["sheetId"]
                for s in meta.get("sheets", [])}

    def ensure_tab(self, title: str) -> None:
        if title not in self.tabs():
            self._req("POST", ":batchUpdate", json={"requests": [
                {"addSheet": {"properties": {"title": title}}}]})

    def get(self, rng: str) -> list[list]:
        from urllib.parse import quote
        return self._req("GET", f"/values/{quote(rng)}").get("values", [])

    def put(self, rng: str, values: list[list]) -> None:
        from urllib.parse import quote
        self._req("PUT", f"/values/{quote(rng)}?valueInputOption=RAW",
                  json={"values": values})

    def clear(self, rng: str) -> None:
        from urllib.parse import quote
        self._req("POST", f"/values/{quote(rng)}:clear", json={})


def write_sheet(sheet: Sheet, months: list[dict]) -> None:
    """Réécrit « Récap » avec TOUS les mois fournis (Firestore) et l'onglet
    « Octobre 2026 »… de chaque mois qui porte ses lignes de détail."""
    # Le Sheet vierge a un onglet « Feuille 1 » / « Sheet1 » : on le renomme
    # en Récap plutôt que de laisser un onglet vide traîner.
    tabs = sheet.tabs()
    if RECAP not in tabs and len(tabs) == 1:
        sheet._req("POST", ":batchUpdate", json={"requests": [{
            "updateSheetProperties": {
                "properties": {"sheetId": list(tabs.values())[0], "title": RECAP},
                "fields": "title"}}]})
    sheet.ensure_tab(RECAP)

    # Le récap est RECONSTRUIT à partir des mois fournis (Firestore), jamais
    # relu depuis le Sheet : Sheets renvoie des nombres formatés à la
    # française (« 9 262,71 ») que float() ne sait pas relire.
    by_key = {m["mois"]: m for m in months}
    body = [RECAP_HEADER]
    for k in sorted(by_key):
        m = by_key[k]
        body.append([tab_title(k), m.get("service_ht", 0), m.get("revente_ht", 0),
                     m.get("total_ht", 0), m.get("tva", 0), m.get("nb_factures", 0),
                     m.get("calcule_le", "")])
    for y in sorted({k[:4] for k in by_key}):   # cumul annuel vs plafonds micro
        ys = [by_key[k] for k in sorted(by_key) if k.startswith(y)]
        body.append([f"Cumul {y}"] + [round(sum(float(m.get(f) or 0) for m in ys), 2)
                                      for f in ("service_ht", "revente_ht", "total_ht", "tva")]
                    + [sum(int(m.get("nb_factures") or 0) for m in ys), ""])
        body.append([f"Plafond {y}", PLAFOND_SERVICE, PLAFOND_REVENTE, "", "", "", ""])
    sheet.clear(f"'{RECAP}'!A1:G")
    sheet.put(f"'{RECAP}'!A1", body)

    # Anciens onglets « Détail AAAA-MM » (1er lancement du 02/11/2026) :
    # remplacés par des onglets au nom du mois.
    old = [sid for t, sid in sheet.tabs().items() if t.startswith("Détail ")]
    if old:
        sheet._req("POST", ":batchUpdate", json={"requests": [
            {"deleteSheet": {"sheetId": sid}} for sid in old]})

    for k in sorted(by_key):
        m = by_key[k]
        if "rows" not in m:
            continue
        tab = tab_title(k)
        sheet.ensure_tab(tab)
        sheet.clear(f"'{tab}'!A1:G")
        sheet.put(f"'{tab}'!A1", [DETAIL_HEADER] + m["rows"])


def tab_title(key: str) -> str:
    """« 2026-10 » → « Octobre 2026 » (nom d'onglet et libellé du récap)."""
    return f"{MOIS_FR[int(key[5:7]) - 1].capitalize()} {key[:4]}"


# ── Mail ────────────────────────────────────────────────────────────────────

def _eur(x: float) -> str:
    return f"{x:,.2f} €".replace(",", " ").replace(".", ",")


def mail_html(m: dict, cumul_service: float, cumul_revente: float,
              sheet_url: str) -> str:
    y, mo = int(m["mois"][:4]), int(m["mois"][5:])
    pct_s = cumul_service / PLAFOND_SERVICE * 100
    pct_r = cumul_revente / PLAFOND_REVENTE * 100
    alerte = ""
    if pct_s >= 80:
        alerte = (f"<p style='color:#c0392b'><b>⚠ Prestations : {pct_s:.0f} % du "
                  f"plafond annuel ({_eur(PLAFOND_SERVICE)}) atteint.</b></p>")
    return f"""
<h2>Déclaration URSSAF — {mois_label(y, mo)}</h2>
<table cellpadding="6" style="border-collapse:collapse;font-size:15px">
<tr><td>Prestations de service (HT)</td><td align="right"><b>{_eur(m['service_ht'])}</b></td></tr>
<tr><td>Achat-revente (HT)</td><td align="right"><b>{_eur(m['revente_ht'])}</b></td></tr>
<tr><td>Total HT</td><td align="right">{_eur(m['total_ht'])}</td></tr>
<tr><td>TVA collectée</td><td align="right">{_eur(m['tva'])}</td></tr>
<tr><td>Factures</td><td align="right">{m['nb_factures']}</td></tr>
</table>
<p>Cumul {y} : prestations {_eur(cumul_service)} ({pct_s:.0f} % du plafond),
achat-revente {_eur(cumul_revente)} ({pct_r:.0f} % du plafond).</p>
{alerte}
<p>Calculé depuis les factures Axonaut (ventes Amazon non comprises).
Détail ligne par ligne : <a href="{sheet_url}">tableau des déclarations</a>.</p>
"""
