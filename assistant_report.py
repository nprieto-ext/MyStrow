"""
assistant_report.py — Remontée des demandes et erreurs de l'assistant.

Seulement si l'utilisateur a dit oui (clé `share` du store ~/.mystrow_assistant.json).
Les éléments attendent dans `outbox` (gardé sur le disque) et partent par lots
vers la Cloud Function assistant_report ; sans réseau ou sans compte, ils
attendent le prochain essai. Rien d'autre du show n'est envoyé.
"""

import json
import platform
import time

from PySide6.QtCore import QObject, QThread, QTimer, Signal

_MAX_OUTBOX = 300
_BATCH = 100
_FIRST_SEND_MS = 60_000          # 1 min après le lancement
_EVERY_MS = 5 * 60_000           # puis toutes les 5 min


def queue_request(store, entry: dict):
    """`entry` = l'élément d'historique (t, ts, lang, src, did, r)."""
    if store.data.get("share") is not True:
        return
    item = {"k": "req", **{k: entry.get(k) for k in ("t", "ts", "lang", "src", "r")}}
    # Actions comprises, en JSON compact : c'est ce qui dit si la phrase a été bien lue.
    item["did"] = [json.dumps(a, ensure_ascii=False, default=str)[:300] for a in (entry.get("did") or [])]
    _push(store, item)


def queue_error(store, text: str, tb: str):
    if store.data.get("share") is not True:
        return
    _push(store, {"k": "err", "ts": int(time.time()), "t": text or "", "err": tb[-4000:]})


def _push(store, item):
    box = store.data.setdefault("outbox", [])
    box.append(item)
    del box[:-_MAX_OUTBOX]


class _Sender(QThread):
    done = Signal(int, str)          # nb envoyés (0 = échec), message

    def __init__(self, items):
        super().__init__()
        self._items = items

    def run(self):
        try:
            from license_manager import _get_fresh_token
            import firebase_client as fc
            from core import VERSION
            from i18n import get_language
            token = _get_fresh_token()
            if not token:
                self.done.emit(0, "pas de compte")
                return
            fc.send_assistant_report({
                "items": self._items,
                "app_version": VERSION,
                "app_lang": get_language(),
                "os": f"{platform.system()} {platform.release()}",
            }, token)
            self.done.emit(len(self._items), "")
        except Exception as exc:
            self.done.emit(0, str(exc))


class Reporter(QObject):
    """Envoie la file `outbox` du store par lots, en arrière-plan."""

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self._thread = None
        self._timer = QTimer(self)
        self._timer.setInterval(_EVERY_MS)
        self._timer.timeout.connect(self.flush)
        self._timer.start()
        QTimer.singleShot(_FIRST_SEND_MS, self.flush)

    def flush(self):
        if self.store.data.get("share") is not True or self._thread is not None:
            return
        items = list(self.store.data.get("outbox") or [])[:_BATCH]
        if not items:
            return
        self._thread = _Sender(items)
        self._thread.done.connect(self._on_done)
        self._thread.start()

    def _on_done(self, n, err):
        t, self._thread = self._thread, None
        if t is not None:
            t.wait(1000)
            t.deleteLater()
        if n:
            # Les éléments ajoutés pendant l'envoi sont à la fin : on retire le début.
            box = self.store.data.get("outbox") or []
            del box[:n]
            self.store.save()
            if box:
                QTimer.singleShot(2000, self.flush)
        elif err:
            print(f"[Assistant] remontée reportée : {err}")
