"""
Systeme de licence Firebase pour MyStrow.
Comptes utilisateurs (email + mdp) — 2 machines max par compte.
Zero dependance Qt — appelable depuis n'importe quel contexte.
"""

import os
import sys
import json
import time
import hashlib
import subprocess
import platform
import base64
from enum import Enum
from pathlib import Path
from datetime import datetime, timezone

# === Cryptographie (chiffrement local uniquement) ===
try:
    from cryptography.fernet import Fernet
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("Module cryptography non installe. pip install cryptography")


# ============================================================
# CONSTANTES
# ============================================================

ACCOUNT_FILE    = os.path.join(os.path.expanduser("~"), ".maestro_account.dat")
TRIAL_FILE      = os.path.join(os.path.expanduser("~"), ".maestro_trial.dat")
TRIAL_DAYS      = 15
OFFLINE_GRACE_DAYS = 7  # jours sans connexion avant blocage (licence payante uniquement)

# Empreinte anti-reset essai (AppData, cachee)
if platform.system() == "Windows":
    _APPDATA = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    _FINGERPRINT_DIR  = os.path.join(_APPDATA, "MyStrow", "cache")
    _FINGERPRINT_FILE = os.path.join(_FINGERPRINT_DIR, ".sys")
else:
    _FINGERPRINT_DIR  = os.path.join(os.path.expanduser("~"), ".config", "mystrow")
    _FINGERPRINT_FILE = os.path.join(_FINGERPRINT_DIR, ".sys")

# Flags subprocess (pas de fenetre console sur Windows)
CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0


# ============================================================
# ETATS DE LICENCE
# ============================================================

class LicenseState(Enum):
    NOT_ACTIVATED = "not_activated"
    INVALID = "invalid"
    FRAUD_CLOCK = "fraud_clock"
    TRIAL_ACTIVE = "trial_active"
    TRIAL_EXPIRED = "trial_expired"
    LICENSE_ACTIVE = "license_active"
    LICENSE_EXPIRED = "license_expired"


# ============================================================
# RESULTAT DE LICENCE (immutable, cache pour toute la session)
# ============================================================

class LicenseResult:
    """Resultat de la verification de licence, cache pour toute la session."""

    __slots__ = (
        'state', 'dmx_allowed', 'watermark_required',
        'show_warning', 'days_remaining', 'message',
        'action_label', 'license_type', 'updates_until_utc',
        'machines_used', 'machines_max', 'machines_list',
    )

    def __init__(self, state, dmx_allowed=False, watermark_required=True,
                 show_warning=False, days_remaining=0, message="",
                 action_label="", license_type="", updates_until_utc=0.0,
                 machines_used=0, machines_max=2, machines_list=None):
        self.state = state
        self.dmx_allowed = dmx_allowed
        self.watermark_required = watermark_required
        self.show_warning = show_warning
        self.days_remaining = days_remaining
        self.message = message
        self.action_label = action_label
        self.license_type = license_type
        # 0.0 = pas de limite (abonnements mensuel/annuel, manuel, trial)
        # > 0  = timestamp jusqu'auquel les mises à jour sont incluses (lifetime)
        self.updates_until_utc = updates_until_utc
        self.machines_used = machines_used  # nombre de PC actuellement activés
        self.machines_max  = machines_max   # max autorisé par la licence
        self.machines_list = machines_list or []  # [{"id":..., "label":...}, ...]

    def __repr__(self):
        return f"LicenseResult(state={self.state.value}, dmx={self.dmx_allowed}, days={self.days_remaining}, machines={self.machines_used}/{self.machines_max})"


# ============================================================
# RESULTATS PRE-DEFINIS PAR ETAT
# ============================================================

def _result_not_activated():
    return LicenseResult(
        state=LicenseState.NOT_ACTIVATED,
        dmx_allowed=False,
        watermark_required=True,
        message="Connectez-vous a votre compte MyStrow",
        action_label="Connexion"
    )

def _result_invalid(reason=""):
    return LicenseResult(
        state=LicenseState.INVALID,
        dmx_allowed=False,
        watermark_required=True,
        message=f"Compte invalide{': ' + reason if reason else ''}"
    )

def _result_trial_active(days):
    warn = days <= 2
    return LicenseResult(
        state=LicenseState.TRIAL_ACTIVE,
        dmx_allowed=True,
        watermark_required=False,
        show_warning=warn,
        days_remaining=days,
        message=f"Essai - {days} jour{'s' if days > 1 else ''} restant{'s' if days > 1 else ''}",
        action_label="Mon compte" if warn else "",
        license_type="trial"
    )

def _result_trial_expired():
    return LicenseResult(
        state=LicenseState.TRIAL_EXPIRED,
        dmx_allowed=False,
        watermark_required=True,
        message="Periode d'essai expiree",
        action_label="Mon compte"
    )

def _result_license_active(days):
    warn = days <= 7
    return LicenseResult(
        state=LicenseState.LICENSE_ACTIVE,
        dmx_allowed=True,
        watermark_required=False,
        show_warning=warn,
        days_remaining=days,
        message=f"Licence expire dans {days} jour{'s' if days > 1 else ''}" if warn else "",
        action_label="Renouveler" if warn else "",
        license_type="license"
    )

def _result_license_expired():
    return LicenseResult(
        state=LicenseState.LICENSE_EXPIRED,
        dmx_allowed=False,
        watermark_required=True,
        message="Licence expiree",
        action_label="Renouveler"
    )

def _result_offline(cached_plan, cached_expiry_utc, days_offline):
    """Resultat construit depuis le cache local (mode hors-ligne)."""
    now = datetime.now(timezone.utc).timestamp()
    days_remaining = max(0, int((cached_expiry_utc - now) / 86400))

    suffix = f" (hors-ligne, {days_offline}j)"
    if cached_plan == "license":
        if now >= cached_expiry_utc:
            return _result_license_expired()
        r = _result_license_active(days_remaining)
        # Ajouter note hors-ligne sans casser la logique
        object.__setattr__ if False else None
        return LicenseResult(
            state=r.state, dmx_allowed=r.dmx_allowed,
            watermark_required=r.watermark_required,
            show_warning=r.show_warning, days_remaining=r.days_remaining,
            message=(r.message or "Licence active") + suffix,
            action_label=r.action_label, license_type=r.license_type
        )
    else:  # trial
        if now >= cached_expiry_utc:
            return _result_trial_expired()
        r = _result_trial_active(max(1, days_remaining))
        return LicenseResult(
            state=r.state, dmx_allowed=r.dmx_allowed,
            watermark_required=r.watermark_required,
            show_warning=r.show_warning, days_remaining=r.days_remaining,
            message=(r.message or "Essai actif") + suffix,
            action_label=r.action_label, license_type=r.license_type
        )


# ============================================================
# IDENTIFIANT MACHINE
# ============================================================

def _run_wmic(command):
    """Execute une commande wmic (Windows uniquement)."""
    try:
        result = subprocess.run(
            command,
            capture_output=True, text=True, timeout=5,
            creationflags=CREATE_NO_WINDOW
        )
        lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
        if len(lines) >= 2:
            return lines[1]
        return ""
    except Exception:
        return ""


_cached_machine_id: str | None = None

# Fichier cache disque du machine_id (évite de relancer PowerShell/wmic à chaque démarrage)
_MACHINE_ID_CACHE_FILE = os.path.join(_FINGERPRINT_DIR, ".mid")


_MID_CACHE_VERSION = "v2:"  # v1 = GUID+SID (instable), v2 = GUID+USERNAME (stable)


def _read_machine_id_disk_cache() -> str | None:
    try:
        if os.path.exists(_MACHINE_ID_CACHE_FILE):
            raw = open(_MACHINE_ID_CACHE_FILE, "r").read().strip()
            # Accepter uniquement le cache v2 (formule stable)
            if raw.startswith(_MID_CACHE_VERSION):
                val = raw[len(_MID_CACHE_VERSION):]
                if len(val) == 64:
                    return val
            # Cache v1 (ancien, SID-dépendant) → ignoré, recalcul forcé
    except Exception:
        pass
    return None


def _write_machine_id_disk_cache(mid: str) -> None:
    try:
        os.makedirs(_FINGERPRINT_DIR, exist_ok=True)
        open(_MACHINE_ID_CACHE_FILE, "w").write(_MID_CACHE_VERSION + mid)
    except Exception:
        pass


def get_machine_id() -> str:
    """
    Genere un identifiant unique de la machine.
    Windows : MachineGuid (registre) + USERNAME (env). Sans subprocess, 100% stable.
    Fallback : wmic si le registre echoue.
    Resultat mis en cache en memoire (session) ET sur disque (restarts).
    """
    global _cached_machine_id
    if _cached_machine_id:
        return _cached_machine_id

    # Cache disque : évite PowerShell/wmic au prochain démarrage
    cached = _read_machine_id_disk_cache()
    if cached:
        _cached_machine_id = cached
        return cached

    components = []

    if platform.system() == "Windows":
        # Source primaire : MachineGuid (registre, instantane, 100% stable)
        machine_guid = ""
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Cryptography")
            machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
            winreg.CloseKey(key)
        except Exception:
            pass

        if machine_guid:
            components.append(f"GUID:{machine_guid}")
        else:
            # Fallback wmic si le registre est inaccessible
            cpu = _run_wmic(["wmic", "cpu", "get", "ProcessorId"])
            components.append(f"CPU:{cpu}")
            bios = _run_wmic(["wmic", "bios", "get", "SerialNumber"])
            components.append(f"BIOS:{bios}")

        # USERNAME Windows — toujours disponible, pas de subprocess
        components.append(f"USER:{os.environ.get('USERNAME', os.environ.get('USER', ''))}")
    else:
        try:
            with open("/etc/machine-id", "r") as f:
                components.append(f"MID:{f.read().strip()}")
        except Exception:
            components.append(f"HOST:{platform.node()}")

    raw = "|".join(components)
    _cached_machine_id = hashlib.sha256(raw.encode()).hexdigest()
    _write_machine_id_disk_cache(_cached_machine_id)
    return _cached_machine_id


# ============================================================
# STOCKAGE LOCAL CHIFFRE (~/.maestro_account.dat)
# ============================================================

def _derive_fernet_key(machine_id: str) -> bytes:
    raw = hashlib.sha256(f"maestro-account-{machine_id}".encode()).digest()
    return base64.urlsafe_b64encode(raw)


_ACCOUNT_FILE_PLAIN = ACCOUNT_FILE + ".json"  # fallback non-chiffré


def _load_account(machine_id: str) -> dict | None:
    """Charge et dechiffre le fichier de compte local."""
    if not os.path.exists(ACCOUNT_FILE) and not os.path.exists(_ACCOUNT_FILE_PLAIN):
        return None
    if CRYPTO_AVAILABLE and os.path.exists(ACCOUNT_FILE):
        try:
            key = _derive_fernet_key(machine_id)
            f = Fernet(key)
            with open(ACCOUNT_FILE, "rb") as fp:
                encrypted = fp.read()
            decrypted = f.decrypt(encrypted)
            return json.loads(decrypted.decode())
        except Exception as e:
            print(f"Erreur lecture compte chiffré: {e}")
    # Fallback : fichier JSON non-chiffré (quand cryptography absent)
    if os.path.exists(_ACCOUNT_FILE_PLAIN):
        try:
            with open(_ACCOUNT_FILE_PLAIN, "r", encoding="utf-8") as fp:
                return json.load(fp)
        except Exception as e:
            print(f"Erreur lecture compte fallback: {e}")
    return None


def _save_account(machine_id: str, data: dict) -> bool:
    """Chiffre et sauvegarde le fichier de compte local."""
    if CRYPTO_AVAILABLE:
        try:
            key = _derive_fernet_key(machine_id)
            f = Fernet(key)
            raw = json.dumps(data).encode()
            encrypted = f.encrypt(raw)
            with open(ACCOUNT_FILE, "wb") as fp:
                fp.write(encrypted)
            return True
        except Exception as e:
            print(f"Erreur sauvegarde compte chiffré: {e}")
    # Fallback : JSON non-chiffré si cryptography non disponible
    try:
        with open(_ACCOUNT_FILE_PLAIN, "w", encoding="utf-8") as fp:
            json.dump(data, fp)
        print("⚠ Compte sauvegardé sans chiffrement (cryptography non disponible)")
        return True
    except Exception as e:
        print(f"Erreur sauvegarde compte fallback: {e}")
        return False


def _delete_account():
    """Supprime le fichier de compte local (logout)."""
    try:
        if os.path.exists(ACCOUNT_FILE):
            os.remove(ACCOUNT_FILE)
        if os.path.exists(_ACCOUNT_FILE_PLAIN):
            os.remove(_ACCOUNT_FILE_PLAIN)
        return True
    except Exception as e:
        print(f"Erreur suppression compte: {e}")
        return False


# ============================================================
# VERIFICATION INTEGRITE EXE (anti-patch, conserve)
# ============================================================

try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    _VERIFY_AVAILABLE = True
except ImportError:
    _VERIFY_AVAILABLE = False

_ED25519_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEA6tjDrKl10uRagKkkrIC0oh59c6LpowL/f71EqFfXTFA=
-----END PUBLIC KEY-----
"""

def _verify_signature(data_bytes: bytes, signature_hex: str) -> bool:
    if not _VERIFY_AVAILABLE:
        return False
    try:
        public_key = load_pem_public_key(_ED25519_PUBLIC_KEY_PEM)
        signature = bytes.fromhex(signature_hex)
        public_key.verify(signature, data_bytes)
        return True
    except Exception:
        return False


def check_exe_integrity() -> bool:
    """
    Verifie l'integrite de l'executable (uniquement en mode frozen/PyInstaller).
    Retourne True si OK ou si on n'est pas en mode frozen.
    """
    if not getattr(sys, 'frozen', False):
        return True

    exe_path = sys.executable
    sig_path = exe_path + ".sig"

    if not os.path.exists(sig_path):
        print("Fichier .sig manquant - verification ignoree")
        return True

    try:
        sha256 = hashlib.sha256()
        with open(exe_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        exe_hash = sha256.hexdigest()

        with open(sig_path, "r") as f:
            sig_data = json.load(f)

        expected_hash = sig_data.get("hash", "")
        signature = sig_data.get("signature", "")

        if not expected_hash:
            print("Hash non defini dans .sig - verification ignoree")
            return True

        if exe_hash != expected_hash:
            print("Hash exe ne correspond pas - fichier modifie")
            return False

        # Hash OK — la signature est une verification supplementaire (non bloquante)
        if signature and _VERIFY_AVAILABLE:
            if not _verify_signature(expected_hash.encode(), signature):
                print("Avertissement: verification signature Ed25519 echouee (hash OK)")

        return True

    except Exception as e:
        # En cas d'erreur inattendue (permission, JSON malforme, etc.), ne pas bloquer
        print(f"Erreur verification integrite (ignoree): {e}")
        return True


# ============================================================
# ESSAI LOCAL (sans compte, lie a la machine)
# ============================================================

def _derive_trial_key(machine_id: str) -> bytes:
    raw = hashlib.sha256(f"maestro-trial-{machine_id}".encode()).digest()
    return base64.urlsafe_b64encode(raw)


def _derive_fingerprint_key(machine_id: str) -> bytes:
    raw = hashlib.sha256(f"maestro-fp-{machine_id}".encode()).digest()
    return base64.urlsafe_b64encode(raw)


def _has_trial_fingerprint(machine_id: str) -> bool:
    """Verifie si un essai a deja ete utilise sur cette machine (empreinte cachee)."""
    if not CRYPTO_AVAILABLE or not os.path.exists(_FINGERPRINT_FILE):
        return False
    try:
        key = _derive_fingerprint_key(machine_id)
        f = Fernet(key)
        with open(_FINGERPRINT_FILE, "rb") as fp:
            data = json.loads(f.decrypt(fp.read()).decode())
        return data.get("machine_id") == machine_id and data.get("trial_used", False)
    except Exception:
        return False


def _save_trial_fingerprint(machine_id: str):
    """Sauvegarde l'empreinte irreversible indiquant qu'un essai a ete utilise."""
    try:
        os.makedirs(_FINGERPRINT_DIR, exist_ok=True)
        data = {
            "machine_id": machine_id,
            "trial_used": True,
            "created_utc": datetime.now(timezone.utc).timestamp(),
        }
        key = _derive_fingerprint_key(machine_id)
        encrypted = Fernet(key).encrypt(json.dumps(data).encode())
        with open(_FINGERPRINT_FILE, "wb") as fp:
            fp.write(encrypted)
        # Cacher le fichier sur Windows
        if platform.system() == "Windows":
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(_FINGERPRINT_FILE, 0x02)
            except Exception:
                pass
    except Exception as e:
        print(f"Erreur empreinte: {e}")


def _load_trial_data(machine_id: str) -> dict | None:
    """Charge le fichier d'essai local."""
    if not CRYPTO_AVAILABLE or not os.path.exists(TRIAL_FILE):
        return None
    try:
        key = _derive_trial_key(machine_id)
        f = Fernet(key)
        with open(TRIAL_FILE, "rb") as fp:
            data = json.loads(f.decrypt(fp.read()).decode())
        # Verifier que le machine_id correspond (protection copie de fichier)
        if data.get("machine_id") != machine_id:
            return None
        return data
    except Exception:
        return None


def _activate_local_trial(machine_id: str) -> bool:
    """Active l'essai local automatiquement (premier lancement)."""
    if not CRYPTO_AVAILABLE:
        return False
    try:
        now = datetime.now(timezone.utc).timestamp()
        data = {
            "machine_id": machine_id,
            "created_utc": now,
            "expiry_utc": now + (TRIAL_DAYS * 86400),
        }
        key = _derive_trial_key(machine_id)
        encrypted = Fernet(key).encrypt(json.dumps(data).encode())
        with open(TRIAL_FILE, "wb") as fp:
            fp.write(encrypted)
        _save_trial_fingerprint(machine_id)
        print(f"Essai local active ({TRIAL_DAYS} jours)")
        return True
    except Exception as e:
        print(f"Erreur activation essai: {e}")
        return False


def _verify_local_trial(machine_id: str) -> LicenseResult:
    """Verifie l'etat de l'essai local."""
    trial = _load_trial_data(machine_id)
    if trial is None:
        return _result_not_activated()
    now = datetime.now(timezone.utc).timestamp()
    expiry = trial.get("expiry_utc", 0)
    if now >= expiry:
        return _result_trial_expired()
    days = max(1, int((expiry - now) / 86400))
    return _result_trial_active(days)


# ============================================================
# VERIFICATION PRINCIPALE (appelee UNE FOIS au demarrage)
# ============================================================

def verify_license() -> LicenseResult:
    """
    Verifie l'etat de la licence. Appelee une seule fois au demarrage.

    Flux :
    1. Compte Firebase present → verification en ligne (priorite)
    2. Fichier essai local present → verifier l'essai
    3. Ni l'un ni l'autre + pas d'empreinte → activer l'essai automatiquement
    4. Empreinte presente + pas de compte → essai deja utilise → NOT_ACTIVATED
    """
    try:
        machine_id = get_machine_id()
    except Exception as e:
        print(f"Erreur machine ID: {e}")
        return _result_not_activated()

    # --- Etape 1 : Compte Firebase ---
    account = _load_account(machine_id)
    if account is not None:
        return _verify_firebase_account(machine_id, account)

    # --- Etape 2 : Essai local existant ---
    if _load_trial_data(machine_id) is not None:
        return _verify_local_trial(machine_id)

    # --- Etape 3 : Premier lancement → activer l'essai automatiquement ---
    if not _has_trial_fingerprint(machine_id):
        if _activate_local_trial(machine_id):
            return _verify_local_trial(machine_id)

    # --- Etape 4 : Essai deja utilise, pas de compte → connexion requise ---
    return _result_not_activated()


def _verify_firebase_account(machine_id: str, account: dict) -> LicenseResult:
    """Verification en ligne via Firebase (appel Firestore)."""
    try:
        import firebase_client as fc

        # Test de connectivité rapide (1.5s max) avant d'essayer Firebase
        if not fc.has_internet():
            print("Pas de connexion internet — mode hors-ligne immédiat")
            return _offline_fallback(account)

        token_data = fc.refresh_id_token(account["refresh_token"])
        uid = token_data["uid"]
        id_token = token_data["id_token"]

        if token_data.get("refresh_token"):
            account["refresh_token"] = token_data["refresh_token"]

        doc = fc.get_license_doc(uid, id_token)
        if doc is None:
            return _result_not_activated()

        fc.add_machine(uid, id_token, machine_id, label=platform.node()[:32])

        now = datetime.now(timezone.utc).timestamp()
        account["last_verified_utc"] = now
        account["uid"] = uid
        account["cached_plan"] = doc.get("plan", "trial")
        account["cached_expiry_utc"] = doc.get("expiry_utc", now)
        _save_account(machine_id, account)

        # Recharger le doc après add_machine pour avoir le compte exact
        doc2 = fc.get_license_doc(uid, id_token) or doc
        machines_list = doc2.get("machines", [])
        machines_used = len([m for m in machines_list if isinstance(m, dict)])
        machines_max  = int(doc2.get("max_machines", 2))

        return _build_result(
            doc.get("plan", "trial"),
            doc.get("expiry_utc", now),
            updates_until_utc=doc.get("updates_until_utc", 0.0),
            machines_used=machines_used,
            machines_max=machines_max,
            machines_list=[m for m in machines_list if isinstance(m, dict)],
        )

    except Exception as e:
        err_msg = str(e)
        print(f"Firebase injoignable ou erreur : {err_msg}")

        if "2 appareils" in err_msg or "désactivé" in err_msg or "Session expirée" in err_msg:
            return _result_invalid(err_msg)

        return _offline_fallback(account)


def _build_result(plan: str, expiry_utc: float, updates_until_utc: float = 0.0,
                  machines_used: int = 0, machines_max: int = 2,
                  machines_list: list = None) -> LicenseResult:
    """Construit un LicenseResult depuis les donnees Firestore."""
    now = datetime.now(timezone.utc).timestamp()
    days_remaining = max(0, int((expiry_utc - now) / 86400))

    if plan == "license":
        if now >= expiry_utc:
            return _result_license_expired()
        r = _result_license_active(max(1, days_remaining))
        return LicenseResult(
            state=r.state, dmx_allowed=r.dmx_allowed,
            watermark_required=r.watermark_required,
            show_warning=r.show_warning, days_remaining=r.days_remaining,
            message=r.message, action_label=r.action_label,
            license_type=r.license_type,
            updates_until_utc=updates_until_utc,
            machines_used=machines_used, machines_max=machines_max,
            machines_list=machines_list or [],
        )
    else:  # trial
        if now >= expiry_utc:
            return _result_trial_expired()
        r = _result_trial_active(max(1, days_remaining))
        return LicenseResult(
            state=r.state, dmx_allowed=r.dmx_allowed,
            watermark_required=r.watermark_required,
            show_warning=r.show_warning, days_remaining=r.days_remaining,
            message=r.message, action_label=r.action_label,
            license_type=r.license_type,
            updates_until_utc=updates_until_utc,
            machines_used=machines_used, machines_max=machines_max,
            machines_list=machines_list or [],
        )


def _offline_fallback(account: dict) -> LicenseResult:
    """Retourne un resultat depuis le cache si < 7 jours offline.
    Valable pour les comptes licence ET essai (grace period identique)."""
    cached_plan = account.get("cached_plan", "trial")

    last_verified = account.get("last_verified_utc", 0)
    now = datetime.now(timezone.utc).timestamp()
    days_offline = int((now - last_verified) / 86400)

    if days_offline > OFFLINE_GRACE_DAYS:
        print(f"Hors-ligne depuis {days_offline} jours > grace {OFFLINE_GRACE_DAYS}j")
        return _result_not_activated()

    cached_expiry = account.get("cached_expiry_utc", 0)
    print(f"Mode hors-ligne ({days_offline}j) — {cached_plan}")
    return _result_offline(cached_plan, cached_expiry, days_offline)


# ============================================================
# ACTIONS COMPTE (login, register, logout)
# ============================================================

# Résultat construit lors du dernier login réussi — utilisé par _on_activation_success
_pending_login_result: "LicenseResult | None" = None


def pop_login_result() -> "LicenseResult | None":
    """Retourne et efface le résultat du dernier login réussi."""
    global _pending_login_result
    r = _pending_login_result
    _pending_login_result = None
    return r


def login_account(email: str, password: str) -> tuple[bool, str]:
    """
    Connecte un compte Firebase et enregistre le token localement.
    Retourne (success: bool, message: str).
    """
    global _pending_login_result
    _pending_login_result = None

    try:
        machine_id = get_machine_id()
    except Exception as e:
        return False, f"Erreur identification machine: {e}"

    try:
        import firebase_client as fc

        print(f"[LOGIN] sign_in {email} ...")
        auth = fc.sign_in(email.strip(), password)
        uid = auth["uid"]
        id_token = auth["id_token"]
        refresh_token = auth["refresh_token"]
        print(f"[LOGIN] sign_in OK — uid={uid}")

        # Verifier que le document de licence existe
        doc = fc.get_license_doc(uid, id_token)
        if doc is None:
            return False, "Aucun compte licence associe a cet email."

        plan       = doc.get("plan", "trial")
        expiry_utc = doc.get("expiry_utc", 0.0)
        print(f"[LOGIN] plan={plan}  expiry_utc={expiry_utc}  doc={doc}")

        # Ajouter la machine
        fc.add_machine(uid, id_token, machine_id, label=platform.node()[:32])

        # Sauvegarder le compte local
        now = datetime.now(timezone.utc).timestamp()
        account_data = {
            "refresh_token": refresh_token,
            "uid": uid,
            "email": auth.get("email", email),
            "last_verified_utc": now,
            "cached_plan": plan,
            "cached_expiry_utc": expiry_utc,
        }
        saved = _save_account(machine_id, account_data)
        print(f"[LOGIN] _save_account → {saved}  (CRYPTO_AVAILABLE={CRYPTO_AVAILABLE})")
        print(f"[LOGIN] ACCOUNT_FILE={ACCOUNT_FILE}")
        print(f"[LOGIN] fichier existe={os.path.exists(ACCOUNT_FILE)}")
        print(f"[LOGIN] fichier plain existe={os.path.exists(_ACCOUNT_FILE_PLAIN)}")

        # Construire et stocker le LicenseResult directement depuis Firestore
        machines_list = doc.get("machines", [])
        machines_used = len([m for m in machines_list if isinstance(m, dict)])
        machines_max  = int(doc.get("max_machines", 2))
        _pending_login_result = _build_result(
            plan, expiry_utc,
            updates_until_utc=doc.get("updates_until_utc", 0.0),
            machines_used=machines_used,
            machines_max=machines_max,
            machines_list=[m for m in machines_list if isinstance(m, dict)],
        )
        print(f"[LOGIN] _pending_login_result={_pending_login_result}")

        plan_label = "licence" if plan == "license" else "essai"
        return True, f"Connecte — {auth.get('email', email)} ({plan_label})"

    except Exception as e:
        print(f"[LOGIN] ERREUR: {e}")
        return False, str(e)


def register_account(email: str, password: str) -> tuple[bool, str]:
    """
    Cree un compte Firebase et le document Firestore.
    Retourne (success: bool, message: str).
    """
    try:
        machine_id = get_machine_id()
    except Exception as e:
        return False, f"Erreur identification machine: {e}"

    try:
        import firebase_client as fc

        # Creer le compte Firebase Auth
        auth = fc.sign_up(email.strip(), password)
        uid = auth["uid"]
        id_token = auth["id_token"]
        refresh_token = auth["refresh_token"]

        # Creer le document Firestore avec plan trial
        fc.create_license_doc(uid, id_token, auth.get("email", email))

        # Ajouter la machine
        fc.add_machine(uid, id_token, machine_id, label=platform.node()[:32])

        # Sauvegarder le compte local
        now = datetime.now(timezone.utc).timestamp()
        account_data = {
            "refresh_token": refresh_token,
            "uid": uid,
            "email": auth.get("email", email),
            "last_verified_utc": now,
            "cached_plan": "trial",
            "cached_expiry_utc": now + (15 * 86400),
        }
        _save_account(machine_id, account_data)

        return True, f"Compte cree — essai gratuit 15 jours active !"

    except Exception as e:
        return False, str(e)


def deactivate_machine() -> tuple[bool, str]:
    """
    Deconnecte cette machine : retire machine_id de Firestore et supprime le compte local.
    Retourne (success: bool, message: str).
    """
    try:
        machine_id = get_machine_id()
    except Exception as e:
        return False, f"Erreur identification machine: {e}"

    account = _load_account(machine_id)
    if account is None:
        _delete_account()
        return True, "Deconnecte."

    try:
        import firebase_client as fc

        uid = account.get("uid", "")
        refresh_token = account.get("refresh_token", "")

        if uid and refresh_token:
            try:
                token_data = fc.refresh_id_token(refresh_token)
                fc.remove_machine(uid, token_data["id_token"], machine_id)
            except Exception as e:
                print(f"Impossible de retirer la machine de Firestore: {e}")
                # Continuer quand meme pour le logout local

    except ImportError:
        pass

    _delete_account()
    return True, "Machine deconnectee avec succes."


# ============================================================
# UTILITAIRES
# ============================================================

def get_current_id_token() -> str | None:
    """
    Retourne un ID token Firebase frais pour l'utilisateur connecté.
    Retourne None si aucun compte n'est enregistré localement ou en cas d'erreur.
    """
    try:
        import firebase_client as fc
        machine_id = get_machine_id()
        account    = _load_account(machine_id)
        if account is None:
            return None
        token_data = fc.refresh_id_token(account["refresh_token"])
        return token_data.get("id_token")
    except Exception as e:
        print(f"[LicenseManager] get_current_id_token erreur: {e}")
        return None


# ============================================================
# UTILITAIRES DEBUG
# ============================================================

def get_license_info() -> dict:
    """Retourne les infos du compte actuel (pour affichage debug)."""
    try:
        machine_id = get_machine_id()
        account = _load_account(machine_id)
        info = {"machine_id": machine_id[:16] + "..."}
        if account:
            info.update({
                "email": account.get("email", "?"),
                "uid": account.get("uid", "?")[:8] + "...",
                "plan": account.get("cached_plan", "?"),
                "expiry": datetime.fromtimestamp(
                    account.get("cached_expiry_utc", 0), tz=timezone.utc
                ).strftime("%Y-%m-%d UTC"),
                "last_verified": datetime.fromtimestamp(
                    account.get("last_verified_utc", 0), tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M UTC"),
            })
        else:
            info["status"] = "non_connecte"
        return info
    except Exception as e:
        return {"error": str(e)}
