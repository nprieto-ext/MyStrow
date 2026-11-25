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

# Console Windows en cp1252 : les « → » des print de main.py la font planter
# (après l'envoi du mail, 25/11/2026).
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

here = os.path.dirname(os.path.abspath(__file__))
for line in open(os.path.join(here, ".env"), encoding="utf-8"):
    if "=" in line and not line.lstrip().startswith("#"):
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"'))
sys.path.insert(0, here)

# firebase_functions n'existe que sur les serveurs Google : on n'en a pas besoin
# ici (décorateurs des CF), une coquille suffit pour importer main.py.
try:
    import firebase_functions  # noqa: F401
except ImportError:
    import types

    class _Coquille:
        def __getattr__(self, _nom):
            return _Coquille()

        def __call__(self, *a, **k):
            if len(a) == 1 and callable(a[0]) and not k:
                return a[0]          # utilisé comme décorateur
            return _Coquille()

    ff = types.ModuleType("firebase_functions")
    for sous in ("https_fn", "scheduler_fn", "firestore_fn", "options", "params",
                 "storage_fn", "pubsub_fn", "tasks_fn", "identity_fn"):
        setattr(ff, sous, _Coquille())
        sys.modules[f"firebase_functions.{sous}"] = getattr(ff, sous)
    sys.modules["firebase_functions"] = ff

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
