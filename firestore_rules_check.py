"""
Garde-fou release : règles Firestore en ligne == firestore.rules local,
puis test RÉEL d'activation d'un poste (add_machine) contre la production.

Pourquoi : la 3.2.15 a commencé à écrire adds_window_utc / adds_count à
l'activation, mais les règles en ligne n'avaient pas été redéployées. Elles
refusaient ces champs → AUCUN nouveau client ne pouvait activer son PC
(13/11/2026, de 13 h 56 à 20 h 40 UTC). Le build, lui, passait sans broncher.

Usage :
    python firestore_rules_check.py          # synchro + test
    python firestore_rules_check.py --test   # test seul

Utilise service_account.json (lecture des règles en ligne, création/suppression
du compte de test) et la commande `firebase` pour déployer.
"""
import json
import os
import subprocess
import sys
import time
import uuid

import requests
from google.auth.transport.requests import Request
from google.oauth2 import service_account

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = "mystrow-907be"
RULES_FILE = os.path.join(HERE, "firestore.rules")
SA_FILE = os.path.join(HERE, "service_account.json")
FS = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/(default)/documents"
IDT = f"https://identitytoolkit.googleapis.com/v1/projects/{PROJECT}"


def _admin_headers() -> dict:
    c = service_account.Credentials.from_service_account_file(
        SA_FILE, scopes=["https://www.googleapis.com/auth/cloud-platform"])
    c.refresh(Request())
    return {"Authorization": "Bearer " + c.token}


def deployed_rules_source(h: dict) -> str:
    rel = requests.get(
        f"https://firebaserules.googleapis.com/v1/projects/{PROJECT}/releases/cloud.firestore",
        headers=h, timeout=30)
    rel.raise_for_status()
    rs = requests.get(f"https://firebaserules.googleapis.com/v1/{rel.json()['rulesetName']}",
                      headers=h, timeout=30)
    rs.raise_for_status()
    return rs.json()["source"]["files"][0]["content"]


def _norm(s: str) -> str:
    return "\n".join(l.rstrip() for l in s.replace("\r\n", "\n").strip().split("\n"))


def ensure_rules_deployed() -> None:
    """Déploie firestore.rules si la version en ligne diffère. Lève en cas d'échec."""
    h = _admin_headers()
    local = open(RULES_FILE, encoding="utf-8").read()
    if _norm(deployed_rules_source(h)) == _norm(local):
        print("[RULES] Règles Firestore en ligne = firestore.rules local ✓")
        return
    print("[RULES] Règles en ligne DIFFÉRENTES du local → déploiement…")
    r = subprocess.run(
        f"firebase deploy --only firestore:rules --project {PROJECT}",
        shell=True, cwd=HERE)
    if r.returncode != 0:
        raise RuntimeError("firebase deploy --only firestore:rules a échoué")
    # La propagation peut prendre quelques secondes
    for _ in range(10):
        if _norm(deployed_rules_source(h)) == _norm(local):
            print("[RULES] Déployées ✓")
            time.sleep(5)
            return
        time.sleep(3)
    raise RuntimeError("Règles déployées mais toujours différentes en ligne")


def smoke_test_activation() -> None:
    """Crée un compte jetable avec une licence, l'active sur 2 « machines » avec
    le VRAI code client (firebase_client.add_machine, jeton utilisateur, donc
    soumis aux règles), vérifie le document, puis supprime tout."""
    sys.path.insert(0, HERE)
    import firebase_client as fc

    h = _admin_headers()
    email = f"release-smoke-{uuid.uuid4().hex[:10]}@mystrow.invalid"
    password = uuid.uuid4().hex
    uid = None
    try:
        r = requests.post(f"{IDT}/accounts", headers=h, timeout=30,
                          json={"email": email, "password": password})
        r.raise_for_status()
        uid = r.json()["localId"]
        now = time.time()
        doc = {"fields": {
            "plan": {"stringValue": "license"},
            "plan_type": {"stringValue": "monthly"},
            "email": {"stringValue": email},
            "expiry_utc": {"doubleValue": now + 3600},
            "created_utc": {"doubleValue": now},
            "machines": {"arrayValue": {}},
        }}
        requests.patch(f"{FS}/licenses/{uid}", headers=h, json=doc, timeout=30).raise_for_status()

        auth = fc.sign_in(email, password)
        fc.add_machine(uid, auth["id_token"], "SMOKE-MACHINE-1", label="smoke")
        fc.add_machine(uid, auth["id_token"], "SMOKE-MACHINE-1", label="smoke")  # déjà là
        fc.add_machine(uid, auth["id_token"], "SMOKE-MACHINE-2", label="smoke")
        got = fc.get_license_doc(uid, auth["id_token"]) or {}
        ids = [m.get("id") for m in got.get("machines", []) if isinstance(m, dict)]
        if ids != ["SMOKE-MACHINE-1", "SMOKE-MACHINE-2"]:
            raise RuntimeError(f"machines inattendues après activation : {ids}")
        print("[RULES] Test d'activation réel (add_machine) ✓")
    finally:
        if uid:
            requests.delete(f"{FS}/licenses/{uid}", headers=h, timeout=30)
            requests.post(f"{IDT}/accounts:delete", headers=h, json={"localId": uid}, timeout=30)


def check(deploy: bool = True) -> None:
    if deploy:
        ensure_rules_deployed()
    smoke_test_activation()


if __name__ == "__main__":
    try:
        check(deploy="--test" not in sys.argv)
    except Exception as e:
        print(f"[RULES] ÉCHEC : {e}")
        sys.exit(1)
