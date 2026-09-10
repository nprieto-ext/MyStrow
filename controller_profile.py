"""
Gestion des profils de contrôleurs MIDI personnalisés.
Format JSON — stockés dans %APPDATA%/MyStrow/controllers/ (Windows) ou ~/.mystrow/controllers/.

Deux sources, jamais mélangées en écriture :

  * le dossier utilisateur — mappings faits maison ou installés depuis la
    bibliothèque communautaire, seuls modifiables (`save_profile`, `rename_`,
    `delete_profile`) ;
  * `controllers_bundle.json.gz`, embarqué dans l'exe — les profils approuvés
    en modération, figés à la date de la release. C'est lui qui fait qu'un
    contrôleur validé est reconnu AU BRANCHEMENT, sans compte ni réseau, au
    lieu d'attendre que l'utilisateur trouve la bibliothèque communautaire.

`list_profiles()` ne rend QUE le premier lot : tout le code de gestion s'appuie
sur `entry["file"]` pour renommer ou supprimer, et un profil embarqué n'a pas de
fichier inscriptible. La détection, elle, passe par `all_profiles()`.
"""
import gzip
import json
import os
import sys
from pathlib import Path

# Catalogue embarqué, produit au moment de la release par
# generate_controllers_bundle.py (collection Firestore `controller_profiles`).
_BUNDLE_NAME = "controllers_bundle.json.gz"
_bundled_cache = None


def get_profiles_dir() -> Path:
    # Utilise AppData/Roaming sur Windows, ~/.mystrow ailleurs
    # Évite d'écrire dans le dossier d'installation (Program Files = accès refusé)
    appdata = os.environ.get("APPDATA")
    if appdata:
        d = Path(appdata) / "MyStrow" / "controllers"
    else:
        d = Path.home() / ".mystrow" / "controllers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_profiles() -> list:
    """Retourne tous les profils utilisateur (dossier controllers/)."""
    result = []
    for f in sorted(get_profiles_dir().glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            result.append({"file": str(f), "data": data})
        except Exception:
            pass
    return result


def _bundle_path() -> Path:
    """Emplacement du catalogue embarqué (`sys._MEIPASS` une fois gelé)."""
    base = getattr(sys, "_MEIPASS", None)
    return (Path(base) if base else Path(__file__).parent) / _BUNDLE_NAME


def list_bundled_profiles() -> list:
    """Profils livrés AVEC l'application — lecture seule, `file` à None.

    Un catalogue absent n'est pas une erreur : c'est l'état d'un build fait
    avant la première approbation, et d'une exécution depuis les sources.
    """
    global _bundled_cache
    if _bundled_cache is not None:
        return _bundled_cache
    out = []
    path = _bundle_path()
    try:
        if path.exists():
            with gzip.open(path, "rb") as gz:
                rows = json.loads(gz.read().decode("utf-8"))
            if isinstance(rows, list):
                for data in rows:
                    ok, _ = validate_profile(data)
                    if ok:
                        out.append({"file": None, "data": data, "bundled": True})
    except (OSError, ValueError) as e:
        print(f"[controleurs] catalogue embarque illisible : {e}")
    _bundled_cache = out
    return out


def _profile_keywords(data: dict) -> set:
    return {str(k).strip().upper() for k in (data.get("keywords") or []) if str(k).strip()}


def all_profiles() -> list:
    """Profils utilisateur, PUIS profils embarqués qu'aucun d'eux ne masque.

    Le local passe toujours devant. Un profil livré avec l'app qui partage un
    mot-clé avec un mapping fait maison détournerait la détection sans rien
    afficher, et l'utilisateur croirait son propre travail écrasé — c'est le cas
    que `conflicting_local_profiles` fait remonter à l'installation, tranché ici
    en silence puisqu'il n'y a personne à prévenir au branchement.
    """
    user = list_profiles()
    taken_kw, taken_fp = set(), set()
    for entry in user:
        taken_kw |= _profile_keywords(entry["data"])
        fp = (entry["data"].get("community") or {}).get("fingerprint")
        if fp:
            taken_fp.add(fp)
    out = list(user)
    for entry in list_bundled_profiles():
        data = entry["data"]
        fp = (data.get("community") or {}).get("fingerprint")
        if fp and fp in taken_fp:
            continue          # déjà installé (et peut-être plus récent) côté utilisateur
        if _profile_keywords(data) & taken_kw:
            continue          # le mapping de l'utilisateur vise le même appareil
        out.append(entry)
    return out


def load_profile(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_profile(data: dict, path: str = None) -> str:
    if not path:
        safe = "".join(
            c if c.isalnum() or c == "_" else "_"
            for c in data.get("name", "custom").lower()
        ).strip("_")
        path = str(get_profiles_dir() / f"{safe}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _safe_stem(name: str) -> str:
    return "".join(c if c.isalnum() or c == "_" else "_" for c in name.lower()).strip("_") or "custom"


def validate_profile(data) -> tuple[bool, str]:
    """(ok, raison) — un profil importé vient d'un tiers, on ne lui fait pas confiance.

    Un JSON malformé accepté ici ne casserait pas l'import mais la connexion du
    contrôleur, bien plus tard et sans rapport visible avec le fichier fautif.
    """
    if not isinstance(data, dict):
        return False, "le fichier ne contient pas un profil (objet JSON attendu)"
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        return False, "champ « name » absent ou vide"
    keywords = data.get("keywords", [])
    if not isinstance(keywords, list) or not all(isinstance(k, str) for k in keywords):
        return False, "champ « keywords » invalide (liste de textes attendue)"
    if not keywords:
        return False, "aucun mot-clé de détection : le contrôleur ne serait jamais reconnu"
    for section, field in (("pad_map", "note"), ("mute_map", "note"),
                           ("effect_map", "note"), ("fader_map", "cc")):
        entries = data.get(section, {})
        if not isinstance(entries, dict):
            return False, f"section « {section} » invalide"
        for key, entry in entries.items():
            if not isinstance(entry, dict) or not isinstance(entry.get(field), int):
                return False, f"section « {section} », entrée « {key} » : « {field} » manquant"
            channel = entry.get("channel", 0)
            if not isinstance(channel, int) or not 0 <= channel <= 15:
                return False, f"section « {section} », entrée « {key} » : canal hors 0-15"
    if not any(data.get(s) for s in ("pad_map", "mute_map", "effect_map", "fader_map")):
        return False, "profil vide : aucun pad, fader ni bouton mappé"
    return True, ""


def profile_path_for_name(name: str) -> str | None:
    """Chemin du profil portant ce nom, s'il existe déjà."""
    for entry in list_profiles():
        if entry["data"].get("name") == name:
            return entry["file"]
    return None


def unique_profile_path(name: str) -> str:
    """Chemin libre pour ce nom — n'écrase jamais un profil existant."""
    stem = _safe_stem(name)
    directory = get_profiles_dir()
    candidate = directory / f"{stem}.json"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{index}.json"
        index += 1
    return str(candidate)


def import_profile(src_path: str, overwrite: bool = False) -> tuple[dict, str]:
    """Copie un profil externe dans le dossier utilisateur. Lève ValueError si invalide."""
    with open(src_path, encoding="utf-8") as f:
        data = json.load(f)
    ok, reason = validate_profile(data)
    if not ok:
        raise ValueError(reason)
    existing = profile_path_for_name(data["name"])
    if existing and overwrite:
        dest = existing
    else:
        dest = unique_profile_path(data["name"])
    return data, save_profile(data, dest)


def export_profile(data: dict, dest_path: str) -> str:
    """Écrit un profil vers un emplacement choisi par l'utilisateur."""
    with open(dest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return dest_path


def delete_profile(path: str) -> bool:
    try:
        os.remove(path)
        return True
    except OSError:
        return False


def rename_profile(path: str, new_name: str) -> dict:
    """Renomme un profil (le champ « name »). Le fichier, lui, ne bouge pas :
    son chemin sert de clé stable, et le renommer casserait un profil ouvert."""
    data = load_profile(path)
    data["name"] = new_name
    data["id"] = _safe_stem(new_name)
    save_profile(data, path)
    return data


def find_community_profile(fingerprint: str) -> str | None:
    """Chemin du profil installé depuis la bibliothèque commune sous cette empreinte."""
    if not fingerprint:
        return None
    for entry in list_profiles():
        meta = entry["data"].get("community") or {}
        if meta.get("fingerprint") == fingerprint:
            return entry["file"]
    return None


def _bundled_community_version(fingerprint: str) -> int:
    """Version de ce modèle dans le catalogue embarqué, 0 s'il n'y est pas."""
    if not fingerprint:
        return 0
    for entry in list_bundled_profiles():
        meta = entry["data"].get("community") or {}
        if meta.get("fingerprint") == fingerprint:
            return int(meta.get("version", 0) or 0)
    return 0


def installed_community_version(fingerprint: str) -> int:
    """Version communautaire déjà disponible localement, 0 si absente.

    Le catalogue embarqué compte : sans lui, la bibliothèque communautaire
    proposerait « Installer » pour un profil que l'application sait déjà lire.
    """
    path = find_community_profile(fingerprint)
    if not path:
        return _bundled_community_version(fingerprint)
    try:
        meta = load_profile(path).get("community") or {}
        return int(meta.get("version", 0) or 0)
    except Exception:
        return 0


def conflicting_local_profiles(keywords: list, fingerprint: str = "") -> list:
    """Noms des profils déjà installés qui répondraient aux mêmes mots-clés.

    `find_profile_for_port` rend le PREMIER profil dont un mot-clé apparaît dans
    le nom du port, dans l'ordre alphabétique des fichiers. Installer un profil
    communautaire qui partage un mot-clé avec un mapping fait maison peut donc
    détourner la détection sans rien afficher — et l'utilisateur croit que son
    propre mapping a été écrasé.
    """
    wanted = {str(k).strip().upper() for k in (keywords or []) if str(k).strip()}
    if not wanted:
        return []
    out = []
    for entry in list_profiles():
        data = entry["data"]
        meta = data.get("community") or {}
        if fingerprint and meta.get("fingerprint") == fingerprint:
            continue   # c'est la version déjà installée du même profil
        mine = {str(k).strip().upper() for k in (data.get("keywords") or [])}
        if wanted & mine:
            out.append(data.get("name", Path(entry["file"]).stem))
    return out


def install_community_profile(data: dict, fingerprint: str, version: int) -> tuple[str, bool]:
    """Installe (ou met à jour) un profil venu de la bibliothèque commune.

    Retourne (chemin, mise_a_jour). L'empreinte et la version sont estampillées
    dans le fichier : sans elles, un mapping corrigé après coup ne pourrait
    jamais redescendre chez ceux qui l'ont déjà installé — ils resteraient sur
    la version fautive sans moyen de le savoir.

    Une réinstallation écrase le fichier d'origine plutôt que d'en créer un
    second : deux profils portant les mêmes mots-clés se disputeraient la
    détection, et lequel gagne dépendrait de l'ordre alphabétique des fichiers.
    """
    ok, reason = validate_profile(data)
    if not ok:
        raise ValueError(reason)
    data = dict(data)
    data["community"] = {"fingerprint": fingerprint, "version": int(version or 0)}

    existing = find_community_profile(fingerprint)
    if existing:
        return save_profile(data, existing), True
    # Pas encore installé sous cette empreinte, mais un profil local peut déjà
    # porter ce nom : ne jamais écraser le travail de l'utilisateur.
    return save_profile(data, unique_profile_path(data["name"])), False


def find_profile_for_port(port_name: str) -> dict | None:
    """Cherche un profil dont les keywords matchent le nom du port MIDI.

    Balaie `all_profiles()` : un contrôleur approuvé en modération et embarqué
    dans la release est donc reconnu au branchement exactement comme un profil
    que l'utilisateur aurait mappé lui-même.
    """
    upper = port_name.upper()
    for entry in all_profiles():
        data = entry["data"]
        for kw in data.get("keywords", []):
            if kw.upper() in upper:
                return data
    return None


def build_reverse_maps(profile: dict) -> dict:
    """
    Construit des tables de lookup inversées pour dispatch O(1).
    Retourne un dict avec _rev_pad, _rev_mute, _rev_fader, _rev_effect, _rev_led.
    """
    rev_pad    = {}   # (channel, note) -> (row, col)
    rev_mute   = {}   # (channel, note) -> fader_idx
    rev_effect = {}   # (channel, note) -> effect_idx
    rev_fader  = {}   # (channel, cc)   -> fader_idx
    rev_led    = {}   # (row, col)       -> {'channel': c, 'note': n}

    for key, entry in profile.get("pad_map", {}).items():
        try:
            row, col = map(int, key.split(","))
            k = (entry.get("channel", 0), entry["note"])
            rev_pad[k]  = (row, col)
            rev_led[(row, col)] = {"channel": entry.get("channel", 0), "note": entry["note"]}
        except Exception:
            pass

    for idx_str, entry in profile.get("mute_map", {}).items():
        k = (entry.get("channel", 0), entry["note"])
        rev_mute[k] = int(idx_str)

    for idx_str, entry in profile.get("effect_map", {}).items():
        k = (entry.get("channel", 0), entry["note"])
        rev_effect[k] = int(idx_str)

    for idx_str, entry in profile.get("fader_map", {}).items():
        k = (entry.get("channel", 0), entry["cc"])
        rev_fader[k] = int(idx_str)

    # Remap velocities AKAI standard → velocités du contrôleur personnalisé
    _AKAI_TO_COLOR = {
        0: "Éteint", 3: "Rouge", 5: "Blanc", 9: "Orange", 13: "Jaune",
        21: "Vert", 25: "Vert", 37: "Cyan", 45: "Bleu", 49: "Magenta", 53: "Violet",
    }
    led_colors = profile.get("led_colors", {})
    vel_remap = {}
    for akai_vel, color_name in _AKAI_TO_COLOR.items():
        if color_name in led_colors:
            vel_remap[akai_vel] = led_colors[color_name]

    return {
        "rev_pad":    rev_pad,
        "rev_mute":   rev_mute,
        "rev_effect": rev_effect,
        "rev_fader":  rev_fader,
        "rev_led":    rev_led,
        "vel_remap":  vel_remap,
    }
