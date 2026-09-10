"""
Génère controllers_bundle.json.gz — catalogue des profils de contrôleurs MIDI
approuvés en modération, embarqué dans l'application.

Pendant du couple `generate_bundle.py` / `_fetch_custom_fixtures_bundle()` pour
les fixtures, à une différence près : la collection Firestore
`controller_profiles` est en LECTURE PUBLIQUE (firestore.rules), donc ce script
n'a besoin d'AUCUN identifiant. Il tourne tel quel dans les jobs CI Windows et
macOS, sans secret à passer.

Sans ce catalogue, un profil approuvé n'atteint que les utilisateurs qui ouvrent
d'eux-mêmes la bibliothèque communautaire : `controller_profile.list_profiles()`
ne lit que `%APPDATA%/MyStrow/controllers`. Avec lui, le contrôleur est reconnu
au branchement, hors ligne et sans compte.

Usage :  python generate_controllers_bundle.py [chemin_de_sortie]
Sort TOUJOURS en code 0 et écrit TOUJOURS le fichier (catalogue vide en cas
d'échec réseau) : un build ne doit pas casser parce que Firestore a hoqueté, et
les lignes `--add-data` du CI exigent que le fichier existe.
"""

import gzip
import json
import sys
from pathlib import Path

OUT_FILE = Path(__file__).parent / "controllers_bundle.json.gz"

# Champs recopiés depuis le document Firestore vers le profil embarqué. Le
# mapping lui-même arrive dans `profile_json` ; le reste de la fiche (empreinte,
# version, contributeur) sert au suivi des mises à jour et au crédit.
_META_FIELDS = ("fingerprint", "version", "contributed_by")


def _native_keywords():
    """Mots-clés de détection des contrôleurs gérés nativement.

    Un profil communautaire qui vise le même appareil ne doit PAS être embarqué :
    `MIDIHandler.connect_controller` consulte les profils AVANT
    `SUPPORTED_CONTROLLERS` (midi_handler.py, « en Auto, prioritaire sur le
    natif »), donc l'embarquer remplacerait la gestion native — LED, pages,
    particularités du MkII — chez tous les utilisateurs d'un coup.

    Import protégé : rtmidi peut manquer sur un runner de build.
    """
    try:
        from midi_handler import SUPPORTED_CONTROLLERS
    except Exception as e:
        print(f"  (contrôle « déjà natif » ignoré : {e})")
        return None
    out = set()
    for ctrl in SUPPORTED_CONTROLLERS:
        out |= {str(k).strip().upper() for k in ctrl.get("keywords") or []}
    return out


def _collides_with_native(keywords, native):
    """Un mot-clé qui contient un mot-clé natif (ou l'inverse) vise le même
    appareil : « LAUNCHPAD MINI MK3 » et « MINI MK3 » désignent le même boîtier."""
    if not native:
        return ""
    for kw in {str(k).strip().upper() for k in keywords or [] if str(k).strip()}:
        for nat in native:
            if kw and nat and (kw in nat or nat in kw):
                return nat
    return ""


def _write(rows, out_path):
    data = json.dumps(rows, ensure_ascii=False).encode("utf-8")
    with gzip.open(out_path, "wb") as gz:
        gz.write(data)


def build(out_path=OUT_FILE):
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        import firebase_client as fc
        from controller_profile import validate_profile

        docs = fc.fetch_controller_profiles(None)
    except Exception as e:
        print(f"AVERTISSEMENT: lecture de controller_profiles échouée ({e}) "
              f"— catalogue vide généré.")
        _write([], out_path)
        return 0

    native = _native_keywords()
    profiles, skipped = [], 0
    for doc in docs:
        raw = doc.get("profile_json")
        if not isinstance(raw, str) or not raw.strip():
            skipped += 1
            continue
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            skipped += 1
            continue
        # Un profil invalide serait rejeté à la lecture par
        # `list_bundled_profiles`, mais silencieusement : autant le voir ici,
        # au moment où quelqu'un regarde encore la sortie du build.
        ok, reason = validate_profile(data) if isinstance(data, dict) else (False, "pas un objet")
        if not ok:
            print(f"  ignoré : {doc.get('name', '?')} — {reason}")
            skipped += 1
            continue
        clash = _collides_with_native(data.get("keywords"), native)
        if clash:
            print(f"  ignoré : {doc.get('name', '?')} — déjà supporté nativement "
                  f"(mot-clé « {clash} »)")
            skipped += 1
            continue
        # Même estampille que `install_community_profile` : sans empreinte ni
        # version, un mapping corrigé après coup ne pourrait jamais remplacer
        # celui embarqué chez ceux qui l'utilisent déjà.
        data["community"] = {
            "fingerprint": str(doc.get("fingerprint") or doc.get("_doc_id") or ""),
            "version":     int(doc.get("version") or 0),
            "bundled":     True,
        }
        if doc.get("contributed_by"):
            data["community"]["contributed_by"] = doc["contributed_by"]
        profiles.append(data)

    _write(profiles, out_path)
    size = out_path.stat().st_size
    print(f"OK {len(profiles)} profil(s) de contrôleur embarqué(s) dans "
          f"{out_path.name} ({size} octets)"
          + (f", {skipped} ignoré(s)" if skipped else ""))
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT_FILE
    sys.exit(build(target))
