"""Transfère une commande pack (MCF en échec) chez Fanny, qui l'expédie.

    python tools_envoyer_chez_fanny.py MS-xxxxxxxx

Même effet que le repli automatique du webhook : mail à Fanny (adresse +
bouton « J'ai expédié »), commande `a_expedier` + `expediteur: fanny`, donc
visible dans MyStrowFan ; le client recevra le mail de suivi quand Fanny
saisira le numéro. À lancer APRÈS le déploiement de stripe_webhook,
boitier_expedie, boitier_expeditions et admin_boitier_suivi.
"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.join(here, ".env"), encoding="utf-8"):
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))
sys.path.insert(0, here)
import main  # noqa: E402

if len(sys.argv) != 2:
    sys.exit(__doc__)
order_id = sys.argv[1].strip()
ref = main._get_db().collection("boitier_commandes").document(order_id)
cmd = ref.get().to_dict()
if not cmd:
    sys.exit(f"{order_id} introuvable")
if cmd.get("status") not in ("mcf_error", "paid"):
    sys.exit(f"Statut {cmd.get('status')!r} : rien à faire (déjà expédiée ou transmise ?)")
plan = cmd.get("plan") or ""
if plan not in main._STOCK_FANNY_PLAN:
    sys.exit(f"Plan {plan!r} non pris en charge")
main._expedition_fanny(ref, order_id, order_id.replace("MS-", "")[:8], cmd.get("email", ""),
                       cmd.get("address") or {}, int(cmd.get("quantity") or 1),
                       cmd.get("amount_ttc"), plan=plan,
                       motif="stock Amazon épuisé (transfert manuel)")
print(f"OK : {order_id} ({plan}) transmis à Fanny")
