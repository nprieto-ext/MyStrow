"""
assistant_model.py — Téléchargement et mises à jour du modèle de l'assistant.

Le modèle (~400 Mo) n'est pas dans l'installeur : l'onglet Assistant propose
de le télécharger, puis signale les nouvelles versions. Il est publié comme
release d'un dépôt GitHub dédié (pas celui de l'app : une release « modèle »
y deviendrait la « dernière release » lue par updater.py). Chaque release porte
le fichier GGUF et un manifest.json :

    {"version": 4, "file": "mystrow-assistant-v4-q4_k_m.gguf", "size": 390750000,
     "sha256": "…", "schema": 1, "min_app": "3.2.9"}

Le fichier téléchargé est vérifié (taille + SHA-256) avant de remplacer
l'ancien : une coupure en cours de route laisse le modèle en place intact.
"""

import hashlib
import json
import os
import time
import urllib.request

from PySide6.QtCore import QThread, Signal

import assistant_llm

MODEL_REPO = "nprieto-ext/mystrow-assistant"        # ⚠ dépôt à créer (public) avant la release
MANIFEST_URL = f"https://github.com/{MODEL_REPO}/releases/latest/download/manifest.json"
SCHEMA = 1                     # format des commandes compris par cette version de MyStrow
INFO_FILE = assistant_llm.MODEL_DIR / "model.json"
CHECK_EVERY_S = 24 * 3600


def engine_available() -> bool:
    """Le moteur (llama_cpp) est-il présent ? Sans lui, pas de proposition de téléchargement."""
    import importlib.util
    return importlib.util.find_spec("llama_cpp") is not None


def installed() -> dict:
    """{"version": n, "sha256": …} du modèle en place ; version 0 pour un modèle
    copié à la main (sans model.json) ; {} s'il n'y en a pas."""
    if not assistant_llm.model_path().exists():
        return {}
    try:
        return json.loads(INFO_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 0}


def _state() -> dict:
    try:
        return json.loads((assistant_llm.MODEL_DIR / "check.json").read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(d: dict):
    try:
        assistant_llm.MODEL_DIR.mkdir(parents=True, exist_ok=True)
        (assistant_llm.MODEL_DIR / "check.json").write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


def check_due() -> bool:
    return time.time() - _state().get("last_check", 0) > CHECK_EVERY_S


def dismissed_version() -> int:
    return int(_state().get("dismissed", 0))


def dismiss(version: int):
    d = _state()
    d["dismissed"] = int(version)
    _save_state(d)


def _open(url, timeout=10):
    from core import make_ssl_context
    req = urllib.request.Request(url, headers={"User-Agent": "MyStrow"})
    return urllib.request.urlopen(req, timeout=timeout, context=make_ssl_context())


def _version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except ValueError:
        return (0,)


def fetch_manifest() -> dict:
    """Manifest de la dernière release, validé ; lève ValueError s'il est
    incohérent ou prévu pour une version de MyStrow plus récente."""
    from core import VERSION
    with _open(MANIFEST_URL) as resp:
        m = json.loads(resp.read(65536).decode("utf-8"))
    ok = (isinstance(m.get("version"), int) and isinstance(m.get("size"), int) and m["size"] > 1_000_000
          and isinstance(m.get("sha256"), str) and len(m["sha256"]) == 64
          and isinstance(m.get("file"), str) and m["file"].endswith(".gguf") and "/" not in m["file"])
    if not ok:
        raise ValueError("manifest invalide")
    if int(m.get("schema", 1)) > SCHEMA or _version_tuple(m.get("min_app", "0")) > _version_tuple(VERSION):
        raise ValueError("nécessite une version plus récente de MyStrow")
    m["url"] = f"https://github.com/{MODEL_REPO}/releases/download/v{m['version']}/{m['file']}"
    return m


def update_available(manifest: dict) -> bool:
    cur = installed()
    return not cur or manifest["version"] > int(cur.get("version", 0))


def install(part_path, manifest: dict):
    """Remplace le modèle par le fichier vérifié. À appeler dans le thread Qt,
    quand aucune demande n'est en cours : le modèle chargé est libéré d'abord."""
    assistant_llm.unload()
    os.replace(part_path, assistant_llm.model_path())
    INFO_FILE.write_text(json.dumps({"version": manifest["version"], "sha256": manifest["sha256"],
                                     "installed": int(time.time())}), encoding="utf-8")


class ManifestCheck(QThread):
    """Vérifie s'il existe une version plus récente (au plus une fois par jour)."""

    found = Signal(dict)

    def run(self):
        try:
            m = fetch_manifest()
        except Exception as exc:
            print(f"[Assistant] vérification du modèle impossible : {exc}")
            return
        d = _state()
        d["last_check"] = int(time.time())
        _save_state(d)
        if update_available(m):
            self.found.emit(m)


class ModelDownload(QThread):
    """Télécharge et vérifie le modèle dans un fichier .part, sans toucher à l'ancien."""

    progress = Signal(int, int)          # octets reçus, total
    done = Signal(dict, str)             # manifest, chemin du .part vérifié
    failed = Signal(str)

    def __init__(self, manifest: dict = None, parent=None):
        super().__init__(parent)
        self._manifest = manifest
        self._cancel = False

    def cancel(self):
        self._cancel = True

    def run(self):
        part = assistant_llm.MODEL_DIR / "download.part"
        try:
            m = self._manifest or fetch_manifest()
            assistant_llm.MODEL_DIR.mkdir(parents=True, exist_ok=True)
            h, got = hashlib.sha256(), 0
            with _open(m["url"], timeout=30) as resp, open(part, "wb") as f:
                while True:
                    if self._cancel:
                        raise InterruptedError("annulé")
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    h.update(chunk)
                    got += len(chunk)
                    self.progress.emit(got, m["size"])
            if got != m["size"] or h.hexdigest() != m["sha256"].lower():
                raise ValueError("fichier corrompu (vérification échouée)")
            self.done.emit(m, str(part))
        except Exception as exc:
            try:
                part.unlink()
            except Exception:
                pass
            self.failed.emit(str(exc))
