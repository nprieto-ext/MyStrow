"""
REC lumière : créer le show avec l'IA de son choix (ChatGPT, Gemini, Claude…).

Même principe que la création de fixture (fixture_ai_prompt.py) : MyStrow
n'appelle AUCUNE IA. Il fournit un prompt, l'utilisateur le colle dans son
assistant, puis recolle ici la réponse.

La difficulté, c'est la musique : toutes les IA ne l'écoutent pas (Claude ne
prend pas d'audio, ChatGPT l'analyse à peu près). MyStrow analyse donc le
morceau LUI-MÊME — tempo, grille des mesures, sections, énergie, impacts,
silences — et met le résultat dans le prompt. L'IA n'a plus besoin d'entendre
le morceau : elle écrit le show sur une grille de temps déjà juste.

La réponse n'est jamais propre (texte autour, pistes ou effets inventés, blocs
qui débordent ou se chevauchent) : `parse_ai_response` ramène tout à des blocs
valides, calés sur les temps, et dit ce qu'il a corrigé.
"""
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unicodedata

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QPlainTextEdit, QFrame, QApplication, QMessageBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QColor

from i18n import tr, get_language


# ═════════════════════════════════════════════════════════════════════════════
#  1. Analyse du morceau
# ═════════════════════════════════════════════════════════════════════════════

_SR = 11025        # assez pour le tempo et l'énergie, 4× moins lourd que 44,1 kHz
_HOP = 256         # ≈ 23 ms par trame
_NFFT = 1024


class AnalysisCancelled(Exception):
    pass


def _decode_pcm(path, cancel_check=None):
    """Audio STÉRÉO 11 kHz en float32 (N, 2) via ffmpeg, ou None. La stéréo
    sert à la détection de voix (une voix lead est mixée au centre) ; un
    fichier mono ressort avec deux canaux identiques.

    Sortie dans un fichier temporaire (jamais un PIPE non drainé : cf. le
    « bloqué à 0 % » de l'extraction de forme d'onde)."""
    import numpy as np
    try:
        from light_timeline import _ffmpeg_exe
        exe = _ffmpeg_exe()
    except Exception:
        return None
    fd, raw = tempfile.mkstemp(suffix=".raw")
    os.close(fd)
    try:
        cmd = [exe, "-nostdin", "-loglevel", "error", "-nostats", "-i", path,
               "-vn", "-ac", "2", "-ar", str(_SR), "-f", "s16le",
               "-acodec", "pcm_s16le", "-y", raw]
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = subprocess.CREATE_NO_WINDOW
        proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, **kw)
        t0 = time.time()
        while proc.poll() is None:
            if cancel_check and cancel_check():
                proc.kill()
                proc.wait()
                raise AnalysisCancelled()
            QApplication.processEvents()
            time.sleep(0.05)
            if time.time() - t0 > 180:
                proc.kill()
                proc.wait()
                return None
        if proc.returncode != 0 or os.path.getsize(raw) < 4 * _SR:
            return None
        x = np.fromfile(raw, dtype="<i2").astype(np.float32) / 32768.0
        return x[: len(x) // 2 * 2].reshape(-1, 2)
    except AnalysisCancelled:
        raise
    except Exception as e:
        print(f"[REC IA] décodage audio impossible : {e}")
        return None
    finally:
        try:
            os.remove(raw)
        except OSError:
            pass


_VOX_LO, _VOX_HI = 250, 3500          # bande de la voix (fondamentale + formants)


def _median_filter(X, k, axis):
    """Filtre médian 1-D le long d'un axe d'une matrice 2-D, par blocs (numpy
    seul : scipy n'est pas embarqué dans l'exe)."""
    import numpy as np
    from numpy.lib.stride_tricks import sliding_window_view
    pad = k // 2
    widths = [(0, 0), (0, 0)]
    widths[axis] = (pad, pad)
    Xp = np.pad(X, widths, mode="edge")
    out = np.empty_like(X)
    n = X.shape[0]
    for s in range(0, n, 512):
        e = min(n, s + 512)
        blk = Xp[s:e + (2 * pad if axis == 0 else 0)]
        out[s:e] = np.median(sliding_window_view(blk, k, axis=axis), axis=-1)
    return out


_N_MEL, _N_MFCC = 40, 20
_MEL_CACHE = {}


def _mel_dct():
    """Banc de 40 filtres mel (60 Hz – 5 kHz) et matrice DCT-II → 20 MFCC."""
    import numpy as np
    if "fb" not in _MEL_CACHE:
        def hz2mel(f):
            return 2595.0 * np.log10(1.0 + f / 700.0)

        def mel2hz(m):
            return 700.0 * (10 ** (m / 2595.0) - 1.0)
        freqs = np.fft.rfftfreq(_NFFT, 1.0 / _SR)
        pts = mel2hz(np.linspace(hz2mel(60.0), hz2mel(5000.0), _N_MEL + 2))
        fb = np.zeros((len(freqs), _N_MEL), np.float32)
        for i in range(_N_MEL):
            a, c, b = pts[i], pts[i + 1], pts[i + 2]
            up = (freqs - a) / (c - a)
            down = (b - freqs) / (b - c)
            fb[:, i] = np.maximum(0, np.minimum(up, down))
        n = np.arange(_N_MEL)
        dct = np.cos(np.pi / _N_MEL * (n[:, None] + 0.5) * np.arange(_N_MFCC)[None, :])
        _MEL_CACHE["fb"], _MEL_CACHE["dct"] = fb, dct.astype(np.float32)
    return _MEL_CACHE["fb"], _MEL_CACHE["dct"]


def _features_from_pcm(x2, cancel_check=None):
    """Descripteurs trame par trame (≈ 23 ms) depuis le signal stéréo (N, 2).

    Sur le canal MILIEU (L+R)/2 : flux spectral (attaques), RMS, basses
    (grosse caisse), 16 bandes de timbre, centroïde (brillance).
    Pour la VOIX : magnitude 250-3500 Hz du milieu, et énergie du CÔTÉ
    (L−R)/2 dans la même bande. Une voix lead est mixée au centre : elle
    vit dans le milieu et disparaît du côté (le principe du « karaoké »)."""
    import numpy as np
    x = x2.mean(axis=1)
    side = (x2[:, 0] - x2[:, 1]) * 0.5
    n_frames = 1 + max(0, len(x) - _NFFT) // _HOP
    win = np.hanning(_NFFT).astype(np.float32)
    low_bins = max(2, int(150 * _NFFT / _SR))
    v0, v1 = int(_VOX_LO * _NFFT / _SR), int(_VOX_HI * _NFFT / _SR)
    freqs = np.fft.rfftfreq(_NFFT, 1.0 / _SR).astype(np.float32)
    onset = np.zeros(n_frames, np.float32)
    rms = np.zeros(n_frames, np.float32)
    low = np.zeros(n_frames, np.float32)
    centroid = np.zeros(n_frames, np.float32)
    e_tot = np.zeros(n_frames, np.float32)
    e_side = np.zeros(n_frames, np.float32)
    vox = np.zeros((n_frames, v1 - v0), np.float32)
    mfcc = np.zeros((n_frames, _N_MFCC), np.float32)
    flat = np.zeros(n_frames, np.float32)
    fb, dct = _mel_dct()
    # 16 bandes log (≈ 40 Hz → 5 kHz) : le TIMBRE, qui distingue un couplet
    # d'un refrain même quand le mastering les rend aussi forts l'un que l'autre.
    edges = np.unique(np.geomspace(4, _NFFT // 2, 17).astype(int))
    bands = np.zeros((n_frames, len(edges) - 1), np.float32)
    prev = None
    step = 2048
    for s in range(0, n_frames, step):
        if cancel_check and cancel_check():
            raise AnalysisCancelled()
        e = min(n_frames, s + step)
        idx = (np.arange(_NFFT)[None, :] + _HOP * np.arange(s, e)[:, None])
        fr = x[idx]
        rms[s:e] = np.sqrt(np.mean(fr * fr, axis=1))
        mag = np.abs(np.fft.rfft(fr * win, axis=1))
        lm = np.log1p(100.0 * mag)
        low[s:e] = mag[:, 1:low_bins].sum(axis=1)
        cs = np.cumsum(lm, axis=1)
        bands[s:e] = (cs[:, edges[1:] - 1] - cs[:, edges[:-1] - 1]) / (edges[1:] - edges[:-1])
        d = np.diff(lm, axis=0, prepend=(lm[:1] if prev is None else prev[None, :]))
        onset[s:e] = np.maximum(d, 0).sum(axis=1)
        prev = lm[-1]
        p2 = mag * mag
        e_tot[s:e] = p2.sum(axis=1)
        centroid[s:e] = (mag * freqs).sum(axis=1) / (mag.sum(axis=1) + 1e-9)
        vox[s:e] = mag[:, v0:v1]
        smag = np.abs(np.fft.rfft(side[idx] * win, axis=1))
        e_side[s:e] = (smag[:, v0:v1] ** 2).sum(axis=1)
        mfcc[s:e] = np.log(p2 @ fb + 1e-8) @ dct
        vb = mag[:, v0:v1] + 1e-9
        flat[s:e] = np.exp(np.log(vb).mean(axis=1)) / vb.mean(axis=1)
        QApplication.processEvents()
    return {"onset": onset, "rms": rms, "low": low, "bands": bands,
            "fps": _SR / _HOP, "centroid": centroid, "e_tot": e_tot,
            "e_side": e_side, "vox": vox, "mono": x, "mfcc": mfcc, "flat": flat}


def _features_from_waveform(waveform, duration_s):
    """Repli sans ffmpeg : la forme d'onde de l'éditeur (≈ 5000 points).
    Ni voix ni tonalité : il n'y a pas assez d'information."""
    import numpy as np
    w = np.asarray(waveform, np.float32)
    fps = len(w) / max(0.1, duration_s)
    onset = np.maximum(np.diff(w, prepend=w[:1]), 0)
    return {"onset": onset, "rms": w, "low": None, "bands": None, "fps": fps}


def _vocal_frames(F, cancel_check=None):
    """Indice de voix trame par trame, sous forme de 4 descripteurs bruts
    (centre, harmonique, part dans le mix, mouvement) — combinés par mesure
    dans `_vocal_bars`.

    1. HPSS (Fitzgerald 2010) sur la bande 250-3500 Hz du milieu : médiane le
       long du temps = ce qui TIENT (voix, nappes), médiane le long des
       fréquences = ce qui FRAPPE (batterie). Masque doux → partie harmonique.
    2. centre    : harmonique du milieu / (harmonique + côté). Voix ≈ centre.
    3. harm      : part harmonique de la bande (une voix n'est pas un charley).
    4. part      : poids de cette bande harmonique dans tout le spectre.
    5. mouvement : une voix bouge sans arrêt (syllabes, vibrato, glissés) ;
       une nappe de synthé reste immobile."""
    import numpy as np
    V = F["vox"]
    H = _median_filter(V, 17, axis=0)        # ≈ 0,4 s
    if cancel_check and cancel_check():
        raise AnalysisCancelled()
    QApplication.processEvents()
    P = _median_filter(V, 17, axis=1)        # ≈ 180 Hz
    QApplication.processEvents()
    mask = H * H / (H * H + P * P + 1e-12)
    Vh = mask * V
    eh = (Vh * Vh).sum(axis=1)
    ev = (V * V).sum(axis=1)
    lh = np.log1p(100.0 * Vh)
    mv = np.abs(np.diff(lh, axis=0, prepend=lh[:1])).mean(axis=1)
    stereo = float(F["e_side"].sum() / (ev.sum() + 1e-9)) > 1e-4
    return {
        "center": eh / (eh + F["e_side"] + 1e-9) if stereo else None,
        "harm": eh / (ev + 1e-9),
        "share": eh / (F["e_tot"] + 1e-9),
        "move": mv,
    }


def _estimate_period(onset, fps):
    """Période du temps (en trames) par autocorrélation de l'enveloppe
    d'attaques, pondérée autour de 120 BPM."""
    import numpy as np
    o = onset - onset.mean()
    n = len(o)
    f = np.fft.rfft(o, 2 * n)
    ac = np.fft.irfft(f * np.conj(f))[:n]
    if ac[0] <= 0:
        return fps * 0.5
    ac /= ac[0]
    best, best_lag = -1e9, fps * 0.5
    lo, hi = int(fps * 60 / 200), int(fps * 60 / 60) + 1
    for lag in range(max(2, lo), min(n - 1, hi)):
        bpm = 60 * fps / lag
        w = np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.9) ** 2)
        # Harmonique : un vrai temps se répète aussi à 2× la période.
        sc = (ac[lag] + 0.5 * ac[min(n - 1, 2 * lag)]) * w
        if sc > best:
            best, best_lag = sc, lag
    lag = best_lag
    if 1 < lag < n - 2:   # interpolation parabolique : résolution < 1 trame
        a, b, c = ac[lag - 1], ac[lag], ac[lag + 1]
        den = a - 2 * b + c
        if den != 0:
            lag = lag + 0.5 * (a - c) / den
    period = float(lag)
    bpm = 60 * fps / period
    if bpm < 78:
        period /= 2
    elif bpm > 175:
        period *= 2
    return period


def _track_beats(onset, period, tightness=80.0):
    """Suivi de temps par programmation dynamique (Ellis 2007) : suit les
    petites dérives de tempo d'un groupe live, au lieu d'une grille rigide."""
    import numpy as np
    n = len(onset)
    o = onset / (onset.std() or 1.0)
    score = o.astype(np.float64).copy()
    back = -np.ones(n, np.int64)
    lo_off, hi_off = int(round(2 * period)), max(1, int(round(period / 2)))
    for t in range(hi_off, n):
        lo = max(0, t - lo_off)
        hi = t - hi_off
        if hi <= lo:
            continue
        prev = np.arange(lo, hi)
        cost = -tightness * np.log((t - prev) / period) ** 2
        cand = score[prev] + cost
        i = int(np.argmax(cand))
        score[t] = o[t] + cand[i]
        back[t] = prev[i]
    tail = max(1, int(period))
    t = n - tail + int(np.argmax(score[n - tail:]))
    beats = []
    while t >= 0:
        beats.append(t)
        t = back[t]
    return np.array(beats[::-1], np.float64)


def _norm01(v, lo_pct=5, hi_pct=95):
    import numpy as np
    lo, hi = np.percentile(v, lo_pct), np.percentile(v, hi_pct)
    return np.clip((v - lo) / ((hi - lo) or 1.0), 0, 1)


def analyze(media_path, duration_ms, waveform=None, cancel_check=None):
    """Analyse complète. Retourne un dict sérialisable :
    bpm, beat_s, beats (s), bars [{n, t, e}], sections, hits, silences."""
    import numpy as np
    duration_s = max(1.0, duration_ms / 1000.0)
    x = _decode_pcm(media_path, cancel_check) if media_path else None
    if x is not None and len(x) > _SR * 2:
        FT = _features_from_pcm(x, cancel_check)
        duration_s = len(x) / _SR
        source = "audio"
    elif waveform and len(waveform) > 100:
        FT = _features_from_waveform(waveform, duration_s)
        source = "waveform"
    else:
        return None
    onset, rms, low, bands, fps = FT["onset"], FT["rms"], FT["low"], FT["bands"], FT["fps"]

    # Enveloppe d'attaques débarrassée de sa moyenne locale (≈ 0,5 s).
    k = max(3, int(fps * 0.5)) | 1
    loc = np.convolve(onset, np.ones(k) / k, mode="same")
    onset_n = np.maximum(onset - loc, 0)

    period = _estimate_period(onset_n, fps)
    # Netteté de la pulsation : autocorrélation des attaques à la période du
    # temps. Haute = beat régulier et marqué (musique qui fait danser).
    _o = onset_n - onset_n.mean()
    _f = np.fft.rfft(_o, 2 * len(_o))
    _ac = np.fft.irfft(_f * np.conj(_f))[:len(_o)]
    pulse = float(_ac[min(len(_ac) - 1, int(round(period)))] / (_ac[0] or 1.0))
    beats_f = _track_beats(onset_n, period)
    if len(beats_f) < 8:
        beats_f = np.arange(0, len(onset), period)
    beats_s = beats_f / fps
    beat_len = float(np.median(np.diff(beats_s))) if len(beats_s) > 1 else 0.5
    bpm = 60.0 / beat_len

    # Premier temps de la mesure : la phase (sur 4) où la basse frappe le plus.
    acc = low if low is not None else onset_n
    bi = np.clip(beats_f.astype(int), 0, len(acc) - 1)
    phase = int(np.argmax([acc[bi[p::4]].mean() if len(bi[p::4]) else 0
                           for p in range(4)]))
    bar_starts = list(beats_s[phase::4])
    if phase > 0 and beats_s[0] > 0.05:
        bar_starts.insert(0, max(0.0, beats_s[phase] - 4 * beat_len))
    bar_ends = bar_starts[1:] + [duration_s]

    # Énergie par mesure (dB normalisés 0-1) + part des basses.
    db = 20 * np.log10(np.maximum(rms, 1e-5))
    e_frames = _norm01(db)
    bars, feats = [], []
    for i, (a, b) in enumerate(zip(bar_starts, bar_ends)):
        fa, fb = int(a * fps), max(int(a * fps) + 1, int(b * fps))
        e = float(e_frames[fa:fb].mean()) if fb > fa else 0.0
        ln = float(low[fa:fb].mean()) if low is not None and fb > fa else 0.0
        on = float(onset_n[fa:fb].mean()) if fb > fa else 0.0
        bd = list(bands[fa:fb].mean(axis=0)) if bands is not None and fb > fa else []
        bars.append({"n": i + 1, "t": round(float(a), 2), "e": e})
        feats.append([2.0 * e, ln, on] + bd)
    if not bars:
        return None
    nb = len(bars)
    F = np.array(feats, np.float64)
    F = (F - F.mean(axis=0)) / (F.std(axis=0) + 1e-9)
    F[:, 0] *= 3.0    # l'énergie pèse plus que chaque bande prise seule
    Fn = F / (np.linalg.norm(F, axis=1, keepdims=True) + 1e-9)
    S = Fn @ Fn.T     # matrice d'auto-similarité (cosinus) mesure × mesure

    # Nouveauté (noyau en damier de 2×4 mesures, Foote 2000) : forte là où les
    # 4 mesures d'avant se ressemblent entre elles mais pas à celles d'après.
    K = 4
    ker = np.ones((2 * K, 2 * K))
    ker[:K, K:] = ker[K:, :K] = -1
    g = np.exp(-0.5 * ((np.arange(2 * K) - K + 0.5) / K) ** 2)
    ker *= np.outer(g, g)
    nov = np.zeros(nb)
    for b in range(K, nb - K + 1):
        nov[b] = float((S[b - K:b + K, b - K:b + K] * ker).sum())
    target = max(3, min(14, int(round(duration_s / 22.0))))
    cand = sorted([b for b in range(K, nb - K + 1)
                   if nov[b] > 0 and nov[b] >= nov[max(0, b - 1)]
                   and nov[b] >= nov[min(nb - 1, b + 1)]], key=lambda b: -nov[b])
    bounds = []
    for b in cand:
        # Recaler sur le début de phrase (multiple de 4) s'il est presque aussi net.
        b4 = int(round(b / 4) * 4)
        if b4 != b and K <= b4 <= nb - K and nov[b4] >= 0.75 * nov[b]:
            b = b4
        if all(abs(b - o) >= 8 for o in bounds) and b >= 4 and nb - b >= 4:
            bounds.append(b)
        if len(bounds) >= target - 1:
            break
    if not bounds and nb > 24:
        bounds = list(range(16, nb - 8, 16))
    edges = [0] + sorted(bounds) + [nb]

    sections = []
    for i in range(len(edges) - 1):
        a, b = edges[i], edges[i + 1]
        es = [bars[j]["e"] for j in range(a, b)]
        sections.append({
            "bar_from": a + 1, "bar_to": b,
            "start": bars[a]["t"],
            "end": round(bars[b]["t"] if b < nb else duration_s, 2),
            "energy": float(np.mean(es)),
            "rise": float(np.mean(es[-4:]) - np.mean(es[:4])) if len(es) >= 8 else 0.0,
            "_vec": Fn[a:b].mean(axis=0),
        })
    _label_sections(sections)
    # Passage qui REVIENT (refrain…) : l'IA doit lui redonner le même look.
    for i, s in enumerate(sections):
        best, bj = 0.0, None
        for j in range(i):
            v1, v2 = s["_vec"], sections[j]["_vec"]
            c = float(v1 @ v2 / ((np.linalg.norm(v1) * np.linalg.norm(v2)) or 1))
            if c > best:
                best, bj = c, j
        if bj is not None and best >= 0.85 and (s["bar_to"] - s["bar_from"]) >= 6:
            s["like"] = bj + 1
    for s in sections:
        s.pop("_vec", None)

    # Impacts : attaques très au-dessus du reste, espacées d'au moins 2 mesures.
    hits = []
    if len(onset_n):
        thr_h = np.percentile(onset_n, 99.6)
        order = np.argsort(-onset_n)
        for f in order[:400]:
            if onset_n[f] < thr_h:
                break
            t = f / fps
            if 1.0 < t < duration_s - 1 and all(abs(t - h) > 8 * beat_len for h in hits):
                hits.append(t)
            if len(hits) >= 16:
                break
    hits = sorted(round(float(h), 2) for h in hits)

    # Silences / arrêts nets (≥ 0,4 s) au milieu du morceau : blackouts.
    silences = []
    quiet = e_frames < 0.08
    f, n = 0, len(quiet)
    while f < n:
        if quiet[f]:
            g = f
            while g < n and quiet[g]:
                g += 1
            a, b = f / fps, g / fps
            if b - a >= 0.4 and a > 2 and b < duration_s - 2:
                silences.append([round(a, 2), round(b, 2)])
            f = g
        else:
            f += 1
    silences = silences[:12]

    # ── Voix et ambiance (uniquement depuis le vrai fichier audio) ──────────
    vocals, vocal_conf, mood = [], None, None
    if source == "audio":
        try:
            vf = _vocal_frames(FT, cancel_check)
            vocals, vocal_conf = _vocal_bars(FT, vf, bars, bar_ends, fps, e_frames)
            for b in bars:
                b["v"] = any(a <= b["t"] < z for a, z in vocals)
        except AnalysisCancelled:
            raise
        except Exception as e:
            print(f"[REC IA] détection de voix : {e}")
        try:
            mood = _mood(FT, bpm, e_frames, fps, pulse)
        except Exception as e:
            print(f"[REC IA] ambiance : {e}")
        for s in sections:
            dur = max(0.01, s["end"] - s["start"])
            cov = sum(max(0.0, min(z, s["end"]) - max(a, s["start"])) for a, z in vocals)
            s["vocal"] = round(cov / dur, 2)

    for b in bars:
        b["e"] = int(round(b["e"] * 9))
    return {
        "vocals": [[round(float(a), 2), round(float(z), 2)] for a, z in vocals],
        "vocal_conf": vocal_conf,
        "mood": mood,
        "source": source,
        "duration": round(duration_s, 2),
        "bpm": round(bpm, 1),
        "beat_s": round(beat_len, 4),
        "beats": [round(float(t), 3) for t in beats_s],
        "bars": bars,
        "sections": sections,
        "hits": hits,
        "silences": silences,
    }


_DEBUG = {}   # scores intermédiaires, lus par les tests de calibrage


def _otsu(v):
    """Seuil qui sépare au mieux deux populations (méthode d'Otsu)."""
    import numpy as np
    s = np.sort(v)
    best, thr = -1.0, float(s[len(s) // 2])
    for i in range(1, len(s)):
        w0, w1 = i / len(s), 1 - i / len(s)
        d = s[:i].mean() - s[i:].mean()
        var = w0 * w1 * d * d
        if var > best:
            best, thr = var, float((s[i - 1] + s[i]) / 2)
    return thr


# Modèle de détection de voix : régression logistique entraînée hors ligne
# sur 46 titres d'une bibliothèque de DJ (6 500 mesures), étiquetés mesure par
# mesure d'après les mots horodatés de Whisper. Validation « un titre mis de
# côté » : ≈ 72 % de mesures justes (58 % en répondant « instrumental »
# partout). Indice utile, pas une vérité : le prompt le présente comme tel.
# Seuls ces coefficients sont livrés, le calcul reste du numpy pur.
_VOX_MODEL = {
    "mean":
        [117.47634, 19.47439, 5.62688, 5.19837, 1.23144, 2.02647, 0.91128, 1.7364, 0.76353,
         0.90942, 0.01251, 0.98641, 0.38108, 0.81638, 0.40667, 0.08055, -0.25222, 0.28485,
         0.37342, 0.01782, 39.88743, 12.6834, 10.08263, 8.16589, 6.99993, 6.19868, 5.55782,
         5.29816, 4.88835, 4.81637, 4.75295, 4.73075, 4.72538, 4.58314, 4.5538, 4.51506,
         4.44025, 4.33667, 4.22683, 4.2035, 19.63212, 5.47611, 4.36907, 3.56415, 3.21602,
         2.94119, 2.76248, 2.60955, 2.48991, 2.4378, 2.38884, 2.36167, 2.34238, 2.29813,
         2.27167, 2.20724, 2.16019, 2.1063, 2.07694, 2.0253, 0.61496, 0.46919, 0.2094,
         0.53936, 0.56614, 7.11686],
    "scale":
        [47.51248, 17.56767, 11.25701, 8.50873, 7.16019, 5.57647, 4.94113, 4.11627, 3.65599,
         3.86639, 3.46061, 3.70958, 3.91692, 3.46239, 3.26676, 3.47581, 3.24695, 3.0193,
         2.66696, 2.67531, 20.01167, 5.91071, 4.11629, 3.20322, 2.68035, 2.31097, 1.88523,
         1.77165, 1.55397, 1.56143, 1.53004, 1.60378, 1.60071, 1.59127, 1.65049, 1.61888,
         1.66062, 1.60157, 1.60167, 1.64144, 11.6513, 2.47824, 1.61821, 1.12468, 0.99747,
         0.88847, 0.80206, 0.71105, 0.61646, 0.59654, 0.57486, 0.5828, 0.5833, 0.57093,
         0.58896, 0.55553, 0.54052, 0.52707, 0.52202, 0.51313, 0.18518, 0.15584, 0.15662,
         0.09127, 0.13717, 1.1101],
    "w":
        [0.46655, 0.34819, 0.12756, 0.15051, -0.25901, -0.12632, -0.14719, 0.3168, -0.06056,
         0.03206, 0.01092, 0.03444, -0.26015, 0.2926, -0.13159, 0.3303, -0.27113, 0.17692,
         -0.14928, 0.22959, 0.63354, -0.45175, 0.21471, 0.38265, 0.25386, 0.30354, -0.09604,
         0.08679, 0.14374, 0.08981, -0.04729, -0.07577, -0.17611, -0.09948, 0.1117, 0.06658,
         0.03322, 0.07068, 0.07959, 0.12256, -1.44897, 0.08295, -0.21522, -0.03618,
         -0.18178, 0.2099, -0.02866, -0.0229, 0.0993, -0.03892, -0.00759, -0.1094, 0.04104,
         0.02195, -0.12702, 0.00197, -0.02618, 0.08445, 0.09222, -0.04684, 0.5079, -0.81946,
         0.08897, 0.50215, -0.45811, -0.22561],
    "b": -0.20573,
}


def _bar_vocal_features(FT, vf, bars, bar_ends, fps, e_frames):
    """Vecteur de descripteurs par mesure (moyennes et écarts des MFCC, leur
    mouvement, centre stéréo, part harmonique, planéité, brillance), puis
    normalisé PAR MORCEAU : ce qui compte, c'est l'écart d'une mesure au reste
    du titre, pas le mastering."""
    import numpy as np
    M = FT["mfcc"]
    dM = np.abs(np.diff(M, axis=0, prepend=M[:1]))
    keys = ("center", "harm", "share", "move")
    rows, loud = [], []
    for b, z in zip(bars, bar_ends):
        fa = int(b["t"] * fps)
        fb = max(fa + 1, int(z * fps))
        ok = e_frames[fa:fb] > 0.15
        sl = np.arange(fa, min(fb, len(M)))[ok[: max(0, min(fb, len(M)) - fa)]]
        if len(sl) < 3:
            rows.append(None)
            loud.append(False)
            continue
        r = list(M[sl].mean(axis=0)) + list(M[sl].std(axis=0)) + list(dM[sl].mean(axis=0))
        for k in keys:
            v = vf.get(k)
            r.append(float(v[sl].mean()) if v is not None else 0.0)
        r.append(float(FT["flat"][sl].mean()))
        r.append(float(np.log(FT["centroid"][sl].mean() + 1)))
        rows.append(r)
        loud.append(len(sl) > 0.3 * (fb - fa))
    d = len(next(r for r in rows if r is not None)) if any(r is not None for r in rows) else 0
    X = np.array([r if r is not None else [0.0] * d for r in rows], np.float64)
    loud = np.array(loud)
    _DEBUG["vraw"] = X.copy()
    if loud.sum() >= 4:
        mu, sd = X[loud].mean(axis=0), X[loud].std(axis=0) + 1e-9
        X = (X - mu) / sd
    return X, loud


def _vocal_bars(FT, vf, bars, bar_ends, fps, e_frames):
    """Passages chantés, à la mesure près : [(début, fin)] en secondes, et
    une confiance « high / medium / low »."""
    import numpy as np
    X, loud = _bar_vocal_features(FT, vf, bars, bar_ends, fps, e_frames)
    if loud.sum() < 4:
        return [], None
    if _VOX_MODEL:
        raw = _DEBUG["vraw"]   # le modèle a appris sur les valeurs BRUTES
        Xm = (raw - np.array(_VOX_MODEL["mean"])) / np.array(_VOX_MODEL["scale"])
        p = 1.0 / (1.0 + np.exp(-(Xm @ np.array(_VOX_MODEL["w"]) + _VOX_MODEL["b"])))
    else:   # heuristique : centre + harmonique + mouvement
        z = X[:, 60] + X[:, 61] + 0.5 * X[:, 62] + X[:, 63]
        p = 1.0 / (1.0 + np.exp(-z))
    p = np.where(loud, p, 0.0)
    # Lissage sur 3 mesures : une voix ne s'allume pas une mesure sur deux.
    ps = p.copy()
    for i in range(1, len(p) - 1):
        ps[i] = np.median(p[i - 1:i + 2])
    lab = ps >= 0.5
    _DEBUG["vprob"], _DEBUG["vfeat"] = ps, X
    conf_v = float(np.mean(np.abs(ps[loud] - 0.5)) * 2)
    _DEBUG["vsep"] = conf_v
    segs, i = [], 0
    while i < len(lab):
        if lab[i]:
            j = i
            while j < len(lab) and lab[j]:
                j += 1
            segs.append((bars[i]["t"], bar_ends[j - 1]))
            i = j
        else:
            i += 1
    conf = "high" if conf_v >= 0.6 else ("medium" if conf_v >= 0.35 else "low")
    return segs, conf


_KEYS = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]
_KK_MAJOR = [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88]
_KK_MINOR = [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17]


def _mood(F, bpm, e_frames, fps, pulse=0.0):
    """Tonalité (majeur = plutôt lumineux/joyeux, mineur = plutôt sombre),
    brillance du son, et une étiquette d'ambiance en deux axes :
    valence (sombre ↔ joyeux) × énergie (calme ↔ intense)."""
    import numpy as np
    x = F["mono"]
    N, H = 4096, 2048
    nfr = 1 + max(0, len(x) - N) // H
    win = np.hanning(N).astype(np.float32)
    freqs = np.fft.rfftfreq(N, 1.0 / _SR)
    # Énergie MOYENNE par note (et non somme des cases) : une note aiguë couvre
    # bien plus de cases FFT qu'une grave, et le bruit de fond de l'octave
    # haute faisait sortir presque tout en « la mineur ».
    sel = (freqs >= 80) & (freqs <= 1700)
    midi = np.round(12 * np.log2(freqs[sel] / 440.0) + 69).astype(int)
    notes = np.unique(midi)
    onehot = (midi[:, None] == notes[None, :]).astype(np.float32)
    onehot /= onehot.sum(axis=0, keepdims=True)
    fold = (notes[:, None] % 12 == np.arange(12)[None, :]).astype(np.float32)
    chroma = np.zeros(12)
    for s in range(0, nfr, 512):
        e = min(nfr, s + 512)
        idx = np.arange(N)[None, :] + H * np.arange(s, e)[:, None]
        p2 = np.abs(np.fft.rfft(x[idx] * win, axis=1))[:, sel] ** 2
        c = np.sqrt(p2 @ onehot) @ fold
        c /= c.sum(axis=1, keepdims=True) + 1e-9   # chaque trame pèse pareil
        chroma += c.sum(axis=0)
    chroma /= chroma.sum() or 1

    def corr(p, k):
        return float(np.corrcoef(chroma, np.roll(p, k))[0, 1])
    maj = max((corr(_KK_MAJOR, k), k) for k in range(12))
    mnr = max((corr(_KK_MINOR, k), k) for k in range(12))
    if maj[0] >= mnr[0]:
        mode, key, conf = "major", _KEYS[maj[1]], maj[0] - mnr[0]
    else:
        mode, key, conf = "minor", _KEYS[mnr[1]], mnr[0] - maj[0]

    loud = e_frames > 0.3
    cen = float(np.median(F["centroid"][loud])) if loud.any() else float(np.median(F["centroid"]))
    _DEBUG["mood_raw"] = {"maj": maj, "min": mnr, "centroid": cen, "pulse": pulse,
                          "bpm": bpm, "mode_conf": conf}

    # Seuils étalonnés sur une bibliothèque réelle (≈ 50 titres, percentiles
    # 33 / 66) : cf. _MOOD_CAL. Le mode ne compte que s'il est net — la
    # tonalité d'un mix complet se trompe vite (basse, percussions accordées).
    c = _MOOD_CAL
    v_mode = 0.0
    if conf >= c["mode_conf_min"]:
        v_mode = (1 if mode == "major" else -1) * min(1.0, conf / (2 * c["mode_conf_min"]))
    v_bright = max(-1.0, min(1.0, (cen - c["cen_mid"]) / c["cen_span"]))
    valence = 0.6 * v_mode + 0.4 * v_bright
    a_bpm = max(-1.0, min(1.0, (bpm - c["bpm_mid"]) / c["bpm_span"]))
    a_pulse = max(-1.0, min(1.0, (pulse - c["pulse_mid"]) / c["pulse_span"]))
    arousal = 0.5 * a_bpm + 0.5 * a_pulse
    if valence >= 0.2:
        words = (["joyful", "festive", "euphoric"] if arousal >= 0
                 else ["warm", "tender", "relaxed"])
    elif valence <= -0.2:
        words = (["intense", "dark", "driving"] if arousal >= 0
                 else ["melancholic", "dark", "mysterious"])
    else:
        words = (["energetic", "groovy", "danceable"] if arousal >= 0
                 else ["calm", "soft", "contemplative"])
    bright = "bright" if v_bright > 0.33 else ("dark / warm" if v_bright < -0.33 else "balanced")
    return {"key": f"{key} {mode}" + ("" if conf >= c["mode_conf_min"] else " (uncertain)"),
            "mode_conf": round(conf, 3), "brightness": bright, "centroid": round(cen),
            "pulse": round(pulse, 3), "valence": round(valence, 2),
            "arousal": round(arousal, 2), "words": words}


# Étalonnage de l'ambiance (cf. _mood), mesuré sur 120 titres d'une
# bibliothèque de DJ (pop, dance, afro, années 80) : brillance et pulsation
# centrées sur la médiane, mode retenu seulement au-dessus du 33ᵉ percentile
# de netteté. Le mode n'est juste qu'environ 2 fois sur 3 sur un mix complet :
# c'est un indice pour l'IA, pas une vérité.
_MOOD_CAL = {"mode_conf_min": 0.09, "cen_mid": 1476.0, "cen_span": 200.0,
             "bpm_mid": 112.0, "bpm_span": 18.0, "pulse_mid": 0.56, "pulse_span": 0.2}


def _label_sections(sections):
    """Rôle probable de chaque section, d'après son énergie et celle des
    voisines. Une estimation, présentée comme telle à l'IA."""
    if not sections:
        return
    # Énergie RELATIVE au morceau : un titre masterisé fort est « fort »
    # partout en absolu, c'est l'écart entre ses parties qui compte.
    # Intro et outro (souvent quasi muettes) exclues de l'échelle, sinon elles
    # l'écrasent et tout le corps du morceau ressort « peak ».
    es = [s["energy"] for s in sections]
    body = es[1:-1] if len(es) >= 5 else es
    lo_e, hi_e = min(body), max(body)
    span = (hi_e - lo_e) or 1.0
    rel = [min(1.0, max(0.0, (e - lo_e) / span)) if hi_e - lo_e > 0.06 else 0.5
           for e in es]
    for i, s in enumerate(sections):
        e = rel[i]
        prev = rel[i - 1] if i else None
        nxt = rel[i + 1] if i + 1 < len(sections) else None
        lvl = "high" if e >= 0.66 else ("medium" if e >= 0.33 else "low")
        s["level"] = lvl
        if i == 0 and lvl != "high":
            role = "intro"
        elif i == len(sections) - 1 and prev is not None and e < prev - 0.05:
            role = "outro"
        elif lvl == "high" and prev is not None and e - prev >= 0.35:
            role = "DROP / climax"
        elif lvl == "high":
            role = "chorus / peak"
        elif s["rise"] >= 0.15 and nxt is not None and nxt > e:
            role = "build-up"
        elif lvl == "low" and prev is not None and nxt is not None and prev > e and nxt > e:
            role = "breakdown"
        elif lvl == "low":
            role = "calm part"
        else:
            role = "verse"
        s["role"] = role


# ═════════════════════════════════════════════════════════════════════════════
#  2. Prompt
# ═════════════════════════════════════════════════════════════════════════════

_LANG_NAMES = {"fr": "French", "en": "English", "es": "Spanish", "de": "German",
               "pt": "Portuguese", "ja": "Japanese", "it": "Italian"}


def _mmss(t):
    t = max(0.0, float(t))
    return f"{int(t // 60)}:{t % 60:05.2f}"


def build_prompt(analysis, context, mood="", media_name="") -> str:
    """`context` (cf. LightTimelineEditor._ai_prompt_context) :
      groups    : [{key, label, fixtures, colour, moving}]
      effects   : [{name, type}]
      positions : [noms] ou []  (piste Position absente → None)
    """
    a = analysis
    dur = a["duration"]
    L = []
    L.append("You are a professional lighting designer. Write a complete light show "
             "for the song below, for the lighting software MyStrow. "
             "Reply ONLY with one JSON block (format at the end).")
    L.append("")
    L.append("SONG")
    if media_name:
        L.append(f"- File: {media_name}")
    L.append(f"- Duration: {_mmss(dur)} ({dur:.2f} s)")
    L.append(f"- Tempo: about {a['bpm']:.0f} BPM. One beat = {a['beat_s']:.3f} s, "
             f"one bar (4 beats) = {4 * a['beat_s']:.3f} s. "
             "(Detected automatically from the audio.)")
    m = a.get("mood")
    if m:
        L.append(f"- Musical mood (rough estimate from the audio — trust your own "
                 f"knowledge of the song first): {', '.join(m['words'])}. "
                 f"Key {m['key']}, {m['brightness']} sound. Use it to choose the palette "
                 "(e.g. dark/melancholic → deep blues, purples, slow fades; joyful/festive "
                 "→ warm, saturated, lively colours; intense → strong contrasts, reds, whites).")
    if media_name:
        L.append("- If you know this song (from its file name), use what you know of its "
                 "lyrics and atmosphere, but keep the times given here.")
    mood = (mood or "").strip()
    if mood:
        L.append(f'- What the user wants (top priority): "{mood}"')
    else:
        L.append("- No mood given: choose what fits the energy and the style of the song.")
    L.append("- If the audio file is attached and you can listen to it, use it to "
             "refine the mood, but keep the times given here: they come from the "
             "real file.")
    L.append("")

    L.append("STRUCTURE (detected automatically, roles are estimates)")
    has_v = bool(a.get("vocal_conf"))
    L.append("| # | from | to | bars | energy 0-9 |" + (" vocals |" if has_v else "") + " likely role |")
    L.append("|---|---|---|---|---|" + ("---|" if has_v else "") + "---|")
    if a["bars"] and a["bars"][0]["t"] > 0.5:
        L.append(f"| 0 | 0.00 s | {a['bars'][0]['t']:.2f} s | — | — |" + (" — |" if has_v else "")
                 + " before the first bar |")
    for i, s in enumerate(a["sections"], 1):
        role = s["role"]
        if s.get("like"):
            role += f" — sounds like section {s['like']}: give it the same look"
        vc = ""
        if has_v:
            v = s.get("vocal", 0)
            vc = " " + ("sung" if v >= 0.6 else ("partly sung" if v >= 0.2 else "instrumental")) + " |"
        L.append(f"| {i} | {s['start']:.2f} s ({_mmss(s['start'])}) | {s['end']:.2f} s "
                 f"| {s['bar_from']}-{s['bar_to']} | {round(s['energy'] * 9)} |{vc} {role} |")
    L.append("")

    L.append("BAR GRID — bar number @ bar start time in seconds : energy 0-9"
             + (" (+ « v » = vocals in this bar)" if has_v else ""))
    L.append("(Beat times inside a bar = bar start + 1, 2 or 3 × "
             f"{a['beat_s']:.3f} s.)")
    row = []
    for b in a["bars"]:
        row.append(f"{b['n']}@{b['t']:.2f}:{b['e']}" + ("v" if b.get("v") else ""))
        if len(row) == 8:
            L.append("  ".join(row))
            row = []
    if row:
        L.append("  ".join(row))
    L.append("")

    if a["hits"]:
        L.append("STRONG HITS (big accents — good for a flash, a strobe burst or a "
                 "colour change): " + ", ".join(f"{h:.2f}" for h in a["hits"]))
    if a["silences"]:
        L.append("SILENCES / STOPS (good for a blackout): " + ", ".join(
            f"{s:.2f}-{e:.2f}" for s, e in a["silences"]))
    if has_v:
        # Le détecteur a ≈ 72 % de mesures justes : jamais « fiable ».
        conf = {"high": "fairly reliable estimate", "medium": "approximate estimate",
                "low": "uncertain estimate"}.get(a["vocal_conf"], "uncertain estimate")
        if a.get("vocals"):
            L.append(f"VOCALS (detected from the audio, {conf}): " + ", ".join(
                f"{s:.2f}-{e:.2f}" for s, e in a["vocals"]))
        else:
            L.append(f"VOCALS: none detected ({conf}) — probably an instrumental.")
    if a["hits"] or a["silences"] or has_v:
        L.append("")

    L.append("LIGHTING RIG — the tracks you can write on")
    L.append("Colour tracks: one block lights every fixture of the group in that colour.")
    for g in context["groups"]:
        notes = []
        if not g.get("colour"):
            notes.append("white/dimmer only: colour is ignored, only intensity counts")
        if g.get("moving"):
            notes.append("moving heads")
        if g.get("front"):
            notes.append("FRONT light: lights the singer / performer")
        extra = f" ({'; '.join(notes)})" if notes else ""
        L.append(f'- "{g["key"]}" = {g["label"]}: {g["fixtures"]}{extra}')
    if context.get("effects"):
        L.append('Effect track "FX": runs a built-in effect on the groups you choose, '
                 "over the colour tracks. Available effects (exact names, type in brackets):")
        L.append(", ".join(f'{e["name"]} [{e["type"]}]' for e in context["effects"]))
    if context.get("positions") is not None:
        if context["positions"]:
            L.append('Position track "POS" (moving heads aim): presets = ' + ", ".join(
                f'"{p}"' for p in context["positions"]))
        else:
            L.append('Position track "POS": no position preset saved yet — do not use it.')
    L.append("")

    keys = [g["key"] for g in context["groups"]]
    k1 = keys[0] if keys else "A"
    k2 = keys[1] if len(keys) > 1 else k1
    eff_ex = context["effects"][0]["name"] if context.get("effects") else "Strobe Rapide"
    L.append("ANSWER FORMAT")
    L.append("```json")
    L.append("{")
    L.append('  "title": "short name of the show",')
    L.append('  "clips": [')
    L.append(f'    {{"track": "{k1}", "start": 0.00, "end": 15.00, "color": "#1030ff", '
             '"intensity": 60, "fade_in": 2.0},')
    L.append(f'    {{"track": "{k2}", "start": 15.00, "end": 30.00, "color": "#ff0000", '
             '"color2": "#ffaa00", "intensity": 90},')
    L.append(f'    {{"track": "FX", "start": 60.00, "end": 63.75, "effect": "{eff_ex}", '
             f'"groups": ["{k1}", "{k2}"], "speed": 80}}' +
             ("," if context.get("positions") else ""))
    if context.get("positions"):
        L.append(f'    {{"track": "POS", "start": 30.00, "end": 45.00, '
                 f'"position": "{context["positions"][0]}"}}')
    L.append("  ]")
    L.append("}")
    L.append("```")
    L.append("")
    L.append("RULES")
    L.append("1. Times in seconds with 2 decimals. Start and end every block on a bar "
             "or beat time of the BAR GRID: the light must hit with the music.")
    L.append("2. A track plays one block at a time. Avoid overlaps; if a short block "
             "(e.g. a 1-bar strobe on FX) sits inside a longer one, the short one "
             "interrupts it and the long one resumes after. No block on a colour "
             "track = that group is dark (use it for contrast and blackouts).")
    L.append('3. Colour blocks: "color" = #rrggbb, saturated. Optional "color2" = '
             "two-colour block (fixtures of the group alternate the two colours). "
             '"intensity" 0-100. Optional "fade_in" / "fade_out" in seconds.')
    L.append("4. Follow the energy. Calm parts: few groups, lower intensity, long "
             "blocks, slow fades. Build-ups: add groups bar after bar, raise "
             "intensity, chases/pulses. Drops and peaks: all groups, full intensity, "
             "contrasting colours, short strobe bursts (1 to 4 bars) on the strongest "
             "hits. Change colours on section changes and on hits, not randomly; keep "
             "a coherent palette per section, and contrast between sections.")
    if has_v:
        L.append("4b. Vocals: while someone sings, the performer must be visible — keep "
                 "the FRONT group lit, in a flattering colour (warm white, amber, soft "
                 "tints), and keep effects light. When the voice stops (instrumental "
                 "parts, breaks between verses), that is the moment for effects, chases, "
                 "strobes and big colour changes. A voice coming back after an "
                 "instrumental part is a good place for a change of look.")
    L.append(f"5. Cover the whole song from 0 to {dur:.2f} s. Typical block length: "
             "1 to 2 bars in energetic parts, 4 to 8 bars in calm parts.")
    L.append('6. "FX": only effect names from the list. "groups" = keys of the colour '
             'tracks ([] = all). "speed" 1-100. Effects run OVER the colour tracks and '
             "hide them: use them as highlights (build-ups, drops, hits), on at most "
             "about a third of the song, and leave whole sections with colours only. "
             "Effects whose name starts with « Lyre » move moving heads: target the "
             "moving-head groups only.")
    if context.get("positions"):
        L.append('7. "POS": only preset names from the list; change position on '
                 "section changes.")
    L.append("Never ask a question, never write anything outside the JSON block. "
             f'The "title" may be written in {_LANG_NAMES.get(get_language(), "English")}.')
    return "\n".join(L)


# ═════════════════════════════════════════════════════════════════════════════
#  3. Lecture de la réponse
# ═════════════════════════════════════════════════════════════════════════════

def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _relax_json(s: str) -> str:
    s = (s.replace("“", '"').replace("”", '"').replace("‘", "'").replace("’", "'"))
    s = re.sub(r"(?m)^\s*//.*$", "", s)
    s = re.sub(r",\s*([\]}])", r"\1", s)
    return s


def _extract(text: str):
    text = (text or "").strip()
    if not text:
        raise ValueError(tr("rai_err_empty"))
    cands = [m.group(1) for m in re.finditer(r"```(?:json|JSON)?\s*(.*?)```", text, re.S)]
    i, j = text.find("{"), text.rfind("}")
    if i >= 0 and j > i:
        cands.append(text[i:j + 1])
    i, j = text.find("["), text.rfind("]")
    if i >= 0 and j > i:
        cands.append(text[i:j + 1])
    cands.append(text)
    for c in cands:
        for v in (c, _relax_json(c)):
            try:
                obj = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(obj, dict):
                for k in ("clips", "blocks", "blocs", "show", "timeline"):
                    if isinstance(obj.get(k), list):
                        return obj.get("title", ""), obj[k]
            if isinstance(obj, list) and obj and isinstance(obj[0], dict):
                return "", obj
    raise ValueError(tr("rai_err_no_json"))


def _time(v):
    """Secondes depuis 12.5, "12.5", "1:02.5", "12.5s"."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().lower().rstrip("s").strip()
    if ":" in s:
        parts = s.split(":")
        try:
            t = 0.0
            for p in parts:
                t = t * 60 + float(p)
            return t
        except ValueError:
            return None
    try:
        return float(s)
    except ValueError:
        return None


_FX_ALIASES = {"fx", "effet", "effets", "effect", "effects", "efecto", "effekt", "effetto"}
_POS_ALIASES = {"pos", "position", "positions", "posicion", "posicao", "posizione"}


_COLOR_WORDS = {
    "rouge": "#ff0000", "bleu": "#0000ff", "vert": "#00ff00", "jaune": "#ffcc00",
    "orange": "#ff8800", "violet": "#8800ff", "rose": "#ff3399", "blanc": "#ffffff",
    "noir": "#000000", "ambre": "#ffaa00", "amber": "#ffaa00", "cyan": "#00ffff",
    "magenta": "#ff00ff", "turquoise": "#00ffcc", "uv": "#6600ff", "pink": "#ff3399",
    "purple": "#8800ff", "warmwhite": "#ffd8a0", "blancchaud": "#ffd8a0",
}


def _color(v):
    if not v:
        return None
    w = _COLOR_WORDS.get(_norm(v))
    if w:
        return w
    c = QColor(str(v).strip())
    if not c.isValid():
        c = QColor("#" + str(v).strip().lstrip("#"))
    return c.name() if c.isValid() else None


def _fuzzy(name, choices):
    """Nom exact du catalogue pour un nom approximatif de l'IA, ou None."""
    if not name:
        return None
    by_norm = {}
    for c in choices:
        by_norm.setdefault(_norm(c), c)
    n = _norm(name)
    if n in by_norm:
        return by_norm[n]
    m = difflib.get_close_matches(n, list(by_norm), n=1, cutoff=0.75)
    return by_norm[m[0]] if m else None


def parse_ai_response(text, context, analysis):
    """Retourne (title, clips, report).

    clips  : dicts au format `_clip_to_dict` (track, start, duration en ms…).
    report : {"ok", "fixed", "dropped": [raisons]} pour le résumé."""
    title, items = _extract(text)
    dur_ms = int(round(analysis["duration"] * 1000))
    beats = analysis.get("beats") or []
    group_keys = {}
    for g in context["groups"]:
        for alias in [g["key"]] + list(g.get("aliases", [])):
            group_keys.setdefault(_norm(alias), g["key"])
    eff_names = [e["name"] for e in context.get("effects", [])]
    eff_by_name = {e["name"]: e for e in context.get("effects", [])}
    positions = context.get("positions") or []
    report = {"fixed": 0, "dropped": []}

    def snap(t):
        """Cale sur le temps le plus proche (≤ 150 ms) — l'IA arrondit."""
        if not beats:
            return t
        import bisect
        i = bisect.bisect_left(beats, t)
        best = t
        for j in (i - 1, i):
            if 0 <= j < len(beats) and abs(beats[j] - t) <= 0.15 and abs(beats[j] - t) < abs(best - t) + 1e-9:
                best = beats[j]
        return best

    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        it = {str(k).lower(): v for k, v in it.items()}
        raw_track = it.get("track") or it.get("piste") or it.get("group") or ""
        n = _norm(raw_track)
        if n in _FX_ALIASES:
            kind, track = "fx", "Effet"
        elif n in _POS_ALIASES:
            kind, track = "pos", "Position"
        elif n in group_keys:
            kind, track = "color", group_keys[n]
        else:
            report["dropped"].append(tr("rai_drop_track", t=raw_track))
            continue
        if kind == "pos" and context.get("positions") is None:
            report["dropped"].append(tr("rai_drop_track", t=raw_track))
            continue

        start = _time(it.get("start", it.get("debut")))
        end = _time(it.get("end", it.get("fin")))
        if end is None and _time(it.get("duration")) is not None and start is not None:
            end = start + _time(it.get("duration"))
        if start is None or end is None:
            report["dropped"].append(tr("rai_drop_time"))
            continue
        s2, e2 = snap(start), snap(end)
        s_ms, e_ms = int(round(s2 * 1000)), int(round(e2 * 1000))
        if s_ms < 0 or e_ms > dur_ms:
            report["fixed"] += 1
        s_ms, e_ms = max(0, s_ms), min(dur_ms, e_ms)
        if e_ms - s_ms < 100:
            report["dropped"].append(tr("rai_drop_time"))
            continue

        d = {"track": track, "start": s_ms, "duration": e_ms - s_ms,
             "color": "#ffffff", "intensity": 100}
        if kind == "color":
            col = _color(it.get("color") or it.get("colour") or it.get("couleur"))
            if col is None:
                report["fixed"] += 1
                col = "#ffffff"
            d["color"] = col
            c2 = _color(it.get("color2") or it.get("colour2"))
            if c2 and c2 != col:
                d["color2"] = c2
            try:
                inten = float(it.get("intensity", it.get("intensite", 100)))
            except (TypeError, ValueError):
                inten = 100
            if 100 < inten <= 255:
                inten = inten * 100 / 255
            if not 0 <= inten <= 100:
                report["fixed"] += 1
            d["intensity"] = int(max(0, min(100, round(inten))))
            half = d["duration"] // 2
            for key in ("fade_in", "fade_out"):
                v = _time(it.get(key))
                if v and v > 0:
                    ms = int(round(v * 1000))
                    if ms > half:
                        ms = half
                        report["fixed"] += 1
                    d[key] = ms
        elif kind == "fx":
            name = _fuzzy(it.get("effect") or it.get("effet") or it.get("name"), eff_names)
            if not name:
                report["dropped"].append(tr("rai_drop_effect",
                                            e=it.get("effect") or it.get("name") or "?"))
                continue
            eff = eff_by_name[name]
            d["color"] = "#1a0a2e"
            d["effect"] = None
            d["effect_name"] = name
            d["effect_type"] = eff.get("type", "")
            d["effect_layers"] = [dict(l) for l in eff.get("layers", [])]
            grps = it.get("groups") or it.get("groupes") or []
            if isinstance(grps, str):
                grps = re.split(r"[,\s;/]+", grps)
            letters = []
            for g in grps:
                k = group_keys.get(_norm(g))
                if k and len(k) == 1 and k not in letters:
                    letters.append(k)
            d["effect_target_groups"] = letters
            try:
                d["effect_speed"] = int(max(1, min(100, float(it.get("speed", 50)))))
            except (TypeError, ValueError):
                d["effect_speed"] = 50
        else:
            name = _fuzzy(it.get("position") or it.get("preset") or it.get("name"), positions)
            if not name:
                report["dropped"].append(tr("rai_drop_position",
                                            p=it.get("position") or "?"))
                continue
            d["color"] = "#2255ee"
            d["position_preset_idx"] = positions.index(name)
            d["position_preset_name"] = name
        out.append(d)

    # Chevauchements : le bloc le plus COURT passe devant, le long est découpé
    # autour et REPREND après. Les IA posent volontiers un strobe d'une mesure
    # au milieu d'un chase de 16 mesures : couper le chase au début du strobe
    # (l'ancienne règle) laissait ensuite la piste vide jusqu'à la section
    # suivante.
    import copy as _copy
    by_track = {}
    for d in out:
        by_track.setdefault(d["track"], []).append(d)
    final = []
    for track, lst in by_track.items():
        kept = []
        for d in sorted(lst, key=lambda d: -d["duration"]):
            a, b = d["start"], d["start"] + d["duration"]
            nxt = []
            for p in kept:
                pa, pb = p["start"], p["start"] + p["duration"]
                if pb <= a or pa >= b:
                    nxt.append(p)
                    continue
                report["fixed"] += 1
                if pa < a:   # morceau avant
                    head = _copy.deepcopy(p)
                    head["duration"] = a - pa
                    head.pop("fade_out", None)
                    if head["duration"] >= 100:
                        nxt.append(head)
                if pb > b:   # morceau après : l'effet long reprend
                    tail = _copy.deepcopy(p)
                    tail["start"], tail["duration"] = b, pb - b
                    tail.pop("fade_in", None)
                    if tail["duration"] >= 100:
                        nxt.append(tail)
            nxt.append(d)
            kept = nxt
        final.extend(sorted(kept, key=lambda d: d["start"]))
    if not final:
        raise ValueError(tr("rai_err_no_clips"))
    report["ok"] = len(final)
    return (str(title or "").strip(), final, report)


# ═════════════════════════════════════════════════════════════════════════════
#  4. Dialogue
# ═════════════════════════════════════════════════════════════════════════════

class RecAIDialog(QDialog):
    """Étape 1 : ambiance + copier le prompt (l'analyse se fait à ce moment).
    Étape 2 : coller la réponse → blocs validés, rendus par `result_clips()`."""

    def __init__(self, editor):
        super().__init__(editor)
        from admin_pack_editor import _STYLE_EDITOR, ACCENT, TEXT_DIM
        self._ed = editor
        self._accent, self._dim = ACCENT, TEXT_DIM
        self._clips = None
        self._cancel = False
        self.setWindowTitle(tr("rai_title"))
        self.setMinimumSize(660, 640)
        self.setStyleSheet(_STYLE_EDITOR)
        self._build_ui()

    def _step_title(self, text):
        lbl = QLabel(text)
        lbl.setFont(QFont("Segoe UI", 12, QFont.Bold))
        lbl.setStyleSheet(f"color:{self._accent};")
        return lbl

    def _hint(self, text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.RichText)
        lbl.setStyleSheet(f"color:{self._dim}; font-size:11px;")
        return lbl

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        lay.addWidget(self._hint(tr("rai_intro")))

        # ── Étape 1 ──
        lay.addWidget(self._step_title(tr("rai_step1")))
        lay.addWidget(self._hint(tr("rai_mood_label")))
        self._mood = QPlainTextEdit()
        self._mood.setPlaceholderText(tr("rai_mood_placeholder"))
        self._mood.setFixedHeight(56)
        self._mood.setPlainText(getattr(self._ed, "_rec_ai_mood", "") or "")
        lay.addWidget(self._mood)

        row = QHBoxLayout()
        self._btn_copy = QPushButton(tr("rai_copy"))
        self._btn_copy.setFixedHeight(36)
        self._btn_copy.setStyleSheet(
            f"QPushButton {{ background:{self._accent}; color:#000; border:none;"
            f" border-radius:4px; font-weight:bold; font-size:12px; padding:0 20px; }}"
            f"QPushButton:hover {{ background:#33e0ff; }}"
            f"QPushButton:disabled {{ background:#335; color:#889; }}")
        self._btn_copy.clicked.connect(self._copy_prompt)
        row.addWidget(self._btn_copy)
        self._info = QLabel("")
        self._info.setWordWrap(True)
        self._info.setStyleSheet(f"color:{self._dim}; font-size:11px;")
        row.addWidget(self._info, 1)
        lay.addLayout(row)
        lay.addWidget(self._hint(tr("rai_step1_hint")))

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("background:#2a2a2a; max-height:1px; margin:6px 0;")
        lay.addWidget(sep)

        # ── Étape 2 ──
        lay.addWidget(self._step_title(tr("rai_step2")))
        self._paste = QTextEdit()
        self._paste.setAcceptRichText(False)
        self._paste.setFont(QFont("Consolas", 10))
        self._paste.setPlaceholderText(tr("rai_paste_placeholder"))
        self._paste.textChanged.connect(lambda: self._status.setText(""))
        lay.addWidget(self._paste, 1)
        lay.addWidget(self._hint(tr("rai_replace_hint")))

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("color:#ff6666; font-size:11px;")
        lay.addWidget(self._status)

        bot = QHBoxLayout()
        bot.addStretch()
        btn_cancel = QPushButton(tr("fai_cancel"))
        btn_cancel.setFixedHeight(34)
        btn_cancel.clicked.connect(self.reject)
        bot.addWidget(btn_cancel)
        btn_ok = QPushButton(tr("rai_load"))
        btn_ok.setFixedHeight(34)
        btn_ok.setStyleSheet(
            "QPushButton { background:#2d7a3a; color:#fff; border:none; border-radius:4px;"
            " font-weight:bold; font-size:12px; padding:0 20px; }"
            "QPushButton:hover { background:#379147; }")
        btn_ok.clicked.connect(self._load)
        bot.addWidget(btn_ok)
        lay.addLayout(bot)

        if getattr(self._ed, "_rec_ai_analysis", None):
            self._show_analysis_info(self._ed._rec_ai_analysis)

    # ── analyse ──
    def _analysis(self):
        """Analyse mise en cache sur l'éditeur : une seule fois par ouverture."""
        a = getattr(self._ed, "_rec_ai_analysis", None)
        if a:
            return a
        self._btn_copy.setEnabled(False)
        self._info.setText(tr("rai_analysing"))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.processEvents()
        try:
            wf = getattr(getattr(self._ed, "track_waveform", None), "waveform_data", None)
            a = analyze(getattr(self._ed, "media_path", None),
                        getattr(self._ed, "media_duration", 0), waveform=wf,
                        cancel_check=lambda: self._cancel)
        except AnalysisCancelled:
            a = None
        except Exception as e:
            print(f"[REC IA] analyse : {e}")
            a = None
        finally:
            QApplication.restoreOverrideCursor()
            self._btn_copy.setEnabled(True)
        if a:
            self._ed._rec_ai_analysis = a
            self._show_analysis_info(a)
        else:
            self._info.setText("")
        return a

    def _show_analysis_info(self, a):
        self._info.setText(tr("rai_analysis_info", bpm=f"{a['bpm']:.0f}",
                              bars=len(a["bars"]), sections=len(a["sections"])))

    def _copy_prompt(self):
        a = self._analysis()
        if not a:
            self._status.setText(tr("rai_err_analysis"))
            return
        mood = self._mood.toPlainText().strip()
        self._ed._rec_ai_mood = mood
        prompt = build_prompt(a, self._ed._ai_prompt_context(), mood,
                              getattr(self._ed, "media_name", "") or "")
        QApplication.clipboard().setText(prompt)
        orig = tr("rai_copy")
        self._btn_copy.setText(tr("fai_copied"))
        QTimer.singleShot(2000, lambda: self._btn_copy.setText(orig))

    def _load(self):
        a = self._analysis()
        if not a:
            self._status.setText(tr("rai_err_analysis"))
            return
        try:
            title, clips, rep = parse_ai_response(
                self._paste.toPlainText(), self._ed._ai_prompt_context(), a)
        except ValueError as e:
            self._status.setText(str(e))
            return
        tracks = sorted({c["track"] for c in clips})
        msg = tr("rai_summary", title=title or "—", n=rep["ok"],
                 tracks=", ".join(tracks))
        if rep["fixed"]:
            msg += "\n" + tr("rai_summary_fixed", n=rep["fixed"])
        if rep["dropped"]:
            uniq = sorted(set(rep["dropped"]))
            msg += "\n" + tr("rai_summary_dropped", n=len(rep["dropped"])) + \
                "\n  • " + "\n  • ".join(uniq[:8])
        msg += "\n\n" + tr("rai_summary_confirm")
        if QMessageBox.question(self, tr("rai_title"), msg,
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.Yes) != QMessageBox.Yes:
            return
        self._clips = clips
        self.accept()

    def reject(self):
        self._cancel = True
        super().reject()

    def result_clips(self):
        return list(self._clips or [])
