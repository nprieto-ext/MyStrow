// Moteur DMX du mode autonome (tablette sans PC) : projecteurs → 512 canaux.
//
// PORT de deux fonctions du PC :
//   - render()      ← ArtNetDMX._update_from_projectors_locked (artnet_dmx.py)
//   - effectFrame() ← MainWindow._update_effect_from_layers (main_window.py),
//                     couches lumière (RGB, Dimmer, Strobe, R, V, B, Permut) et
//                     mouvement (Pan, Tilt, Pan/Tilt) ; pas de Gobo ni de roue.
// Même arithmétique que le PC, à l'entier près (int() Python = Math.trunc,
// % Python = pmod) : un écart ici est un bug, pas un choix.
// mobile/tools/test_engine_parity.py le vérifie contre le vrai code du PC.
//
// Fonctions pures, sans DOM ni Capacitor : testables sous Node.
(function (root) {
  "use strict";

  // Sous-ensemble de DMX_PROFILES (artnet_dmx.py), mêmes noms et mêmes canaux.
  const PROFILES = {
    DIM:         ["Dim"],
    RGB:         ["R", "G", "B"],
    RGBD:        ["R", "G", "B", "Dim"],
    RGBDS:       ["R", "G", "B", "Dim", "Strobe"],
    RGBSD:       ["R", "G", "B", "Strobe", "Dim"],
    DRGB:        ["Dim", "R", "G", "B"],
    DRGBS:       ["Dim", "R", "G", "B", "Strobe"],
    RGBW:        ["R", "G", "B", "W"],
    RGBWD:       ["R", "G", "B", "W", "Dim"],
    RGBWDS:      ["R", "G", "B", "W", "Dim", "Strobe"],
    RGBWA:       ["R", "G", "B", "W", "Ambre"],
    RGBWAD:      ["R", "G", "B", "W", "Ambre", "Dim"],
    MOVING_RGB:  ["Pan", "Tilt", "R", "G", "B", "Dim", "Shutter", "Speed"],
    MOVING_RGBW: ["Pan", "Tilt", "R", "G", "B", "W", "Dim", "Shutter", "Speed"],
    STROBE_2CH:  ["Shutter", "Dim"],
    // Fixtures précises (profil de la bibliothèque du PC, recopié tel quel)
    MACMAH_IZY715Z: ["Pan", "Tilt", "Speed", "Dim", "Strobe", "R", "G", "B", "W", "Zoom", "Mode", "Mode", "Speed", "Reset"],
  };

  // Libellés du choix de profil dans le patch (ordre d'affichage).
  const PROFILE_LABELS = [
    ["RGBDS", "PAR LED · R G B Dim Strobe (5 canaux)"],
    ["RGB", "PAR LED · R G B (3 canaux)"],
    ["RGBD", "PAR LED · R G B Dim (4 canaux)"],
    ["DRGB", "PAR LED · Dim R G B (4 canaux)"],
    ["DRGBS", "PAR LED · Dim R G B Strobe (5 canaux)"],
    ["RGBSD", "PAR LED · R G B Strobe Dim (5 canaux)"],
    ["RGBW", "PAR LED · R G B W (4 canaux)"],
    ["RGBWD", "PAR LED · R G B W Dim (5 canaux)"],
    ["RGBWDS", "PAR LED · R G B W Dim Strobe (6 canaux)"],
    ["RGBWA", "PAR LED · R G B W Ambre (5 canaux)"],
    ["RGBWAD", "PAR LED · R G B W Ambre Dim (6 canaux)"],
    ["DIM", "Gradateur · 1 canal"],
    ["STROBE_2CH", "Stroboscope · Shutter Dim (2 canaux)"],
    ["MOVING_RGB", "Lyre LED · Pan Tilt R G B Dim Shutter Vitesse (8 canaux)"],
    ["MOVING_RGBW", "Lyre LED · Pan Tilt R G B W Dim Shutter Vitesse (9 canaux)"],
    ["MACMAH_IZY715Z", "MacMah IZY 715 Zoom · lyre (14 canaux)"],
  ];

  const trunc = Math.trunc;
  // % de Python sur des flottants : le résultat a le signe du diviseur.
  function pmod(a, m) { const r = a % m; return r !== 0 && (r < 0) !== (m < 0) ? r + m : r; }

  function hexToRgb(hex) {
    const h = (hex || "#000000").replace("#", "");
    return [parseInt(h.slice(0, 2), 16) || 0, parseInt(h.slice(2, 4), 16) || 0, parseInt(h.slice(4, 6), 16) || 0];
  }
  // QColor.redF() : composante 16 bits divisée en float32 (≠ r / 255 en double).
  const qF = (c) => Math.fround((c * 257) / 65535);

  // Couleur effective d'un projecteur sans effet = Projector.set_color du PC.
  function plainColor(base, level) {
    return level > 0 ? base.map((c) => trunc(c * (level / 100))) : [0, 0, 0];
  }

  // ── Tables du PC (artnet_dmx.py, core.py) ─────────────────────────────────
  const FX_MACHINE_TYPES = new Set(["Machine a fumee", "Machine a brouillard", "Machine a etincelles", "Lance-flamme"]);
  const FX_MACHINE_OUTPUT_CHANNELS = ["Smoke", "Spark", "Flame"];
  const RING_DRIVEN = ["RingDim", "RingR", "RingG", "RingB", "RingW", "RingStrobe"];
  const PRESET_ATTR = { Preset1: "preset1", Preset2: "preset2", Preset3: "preset3", Preset4: "preset4" };
  // core.CW_DEFAULT_SLOTS : roue non calibrée (= MainWindow._GENERIC_WHEEL_SLOTS).
  const CW_DEFAULT_SLOTS = [
    { dmx: 0, color: "#ffffff" }, { dmx: 20, color: "#ff3300" }, { dmx: 42, color: "#ff8800" },
    { dmx: 64, color: "#ffff00" }, { dmx: 85, color: "#00cc44" }, { dmx: 106, color: "#00ccff" },
    { dmx: 128, color: "#0044ff" }, { dmx: 149, color: "#cc00ff" }, { dmx: 170, color: "#ff99cc" },
    { dmx: 192, color: "#ffee88" },
  ];

  /** Profil d'un projecteur : liste de canaux (bibliothèque) ou nom de profil intégré. */
  function profileOf(f) {
    return Array.isArray(f.profile) ? f.profile : (PROFILES[f.profile] || null);
  }
  const isFxMachine = (f) => FX_MACHINE_TYPES.has(f.fixture_type);
  // Lyre : type de fixture comme sur le PC ; à défaut (patch d'avant la
  // bibliothèque), présence d'un canal Pan.
  function isLyre(f) {
    if (f.fixture_type) return f.fixture_type === "Moving Head" || f.fixture_type === "Lyre";
    return (profileOf(f) || []).includes("Pan");
  }

  // ── Roue de couleurs (core.cw_full_value / cw_slot_for_color / cw_slot_at) ──
  function cwFullValue(c) {
    const m = Math.max(c[0], c[1], c[2]);
    return m === 0 ? c.slice() : c.map((v) => Math.floor((v * 255) / m));
  }
  function cwSlotForColor(slots, rgb) {
    if (!slots || !slots.length || Math.max(rgb[0], rgb[1], rgb[2]) === 0) return null;
    const c = cwFullValue(rgb);
    let best = null, bestD = Infinity;
    for (const s of slots) {
      const sc = cwFullValue(hexToRgb(s.color || "#ffffff"));
      const d = (sc[0] - c[0]) ** 2 + (sc[1] - c[1]) ** 2 + (sc[2] - c[2]) ** 2;
      if (d < bestD) { bestD = d; best = s; }
    }
    return best;
  }
  function cwSlotAt(slots, dmx) {
    slots = slots && slots.length ? slots : CW_DEFAULT_SLOTS;
    let passed = null, lowest = null;
    for (const s of slots) {
      const v = trunc(s.dmx || 0);
      if (v <= dmx && (!passed || v > trunc(passed.dmx || 0))) passed = s;
      if (!lowest || v < trunc(lowest.dmx || 0)) lowest = s;
    }
    return passed || lowest;
  }
  /**
   * MainWindow._update_color_wheel : une lyre à roue (ColorWheel sans R) se
   * place sur le filtre le plus proche de la couleur. Noir : la roue reste où
   * elle est. Mute `f.color_wheel`.
   */
  function updateColorWheel(f, rgb) {
    const prof = profileOf(f) || [];
    if (!prof.includes("ColorWheel") || prof.includes("R")) return;
    const slots = f.color_wheel_slots && f.color_wheel_slots.length ? f.color_wheel_slots : CW_DEFAULT_SLOTS;
    const best = cwSlotForColor(slots, rgb);
    if (best) f.color_wheel = best.dmx || 0;
  }
  /** core.effect_dim_base_color : couleur que module un effet « Dimmer seul ». */
  function effectDimBaseColor(f, current) {
    const prof = profileOf(f) || [];
    if (!prof.length || prof.includes("R") || prof.includes("G") || prof.includes("B")) return current;
    if (prof.includes("ColorWheel")) return hexToRgb(cwSlotAt(f.color_wheel_slots, trunc(f.color_wheel || 0)).color || "#ffffff");
    return [255, 255, 255];
  }

  /**
   * Remplit `dmx` (Uint8Array(512), canal 1 = index 0) à partir des projecteurs.
   * Port de ArtNetDMX._update_from_projectors_locked, tous types de canaux.
   * Projecteur : { address (1..512), profile (liste de canaux ou nom intégré),
   * fixture_type, color "#rrggbb" (couleur PURE = base_color du PC), level
   * 0..100, muted, strobe 0..100 (strobe_speed), pan/tilt 0..65535, fx [r,g,b]
   * facultatif (= proj.color du PC quand un effet l'a réécrite ; absent =
   * couleur × niveau), color_wheel, gobo… (attributs de Projector, 0 par
   * défaut) }. `now` : secondes (strobe artificiel des gradateurs).
   */
  function render(fixtures, dmx, now) {
    dmx = dmx || new Uint8Array(512);
    dmx.fill(0);
    now = now ?? Date.now() / 1000;
    for (const f of fixtures) {
      const profile = profileOf(f);
      if (!profile) continue;
      const set = (idx, v) => {
        const ch = f.address - 1 + idx;
        if (ch >= 0 && ch < 512) dmx[ch] = Math.max(0, Math.min(255, trunc(v)));
      };
      const attr = (k, d = 0) => (f[k] ?? d);
      const muted = !!f.muted;
      const extras = f.channel_extras || {}, defaults = f.channel_defaults || {};

      // ── Machines à effet : un canal de sortie piloté par le niveau ─────────
      const outCh = FX_MACHINE_OUTPUT_CHANNELS.find((c) => profile.includes(c));
      if (outCh !== undefined) {
        const outIdx = profile.indexOf(outCh), fanIdx = profile.indexOf("Fan");
        const fxCh = muted ? {} : (f.effect_channels || {});
        let outVal = muted ? 0 : trunc(((f.level || 0) / 100) * 255);
        if (fxCh[outIdx + 1] !== undefined) outVal = fxCh[outIdx + 1];
        set(outIdx, outVal);
        if (fanIdx >= 0) set(fanIdx, fxCh[fanIdx + 1] ?? (muted ? 0 : attr("fan_speed")));
        profile.forEach((type, idx) => {
          if (idx === outIdx || idx === fanIdx) return;
          set(idx, fxCh[idx + 1] ?? extras[idx + 1] ?? extras[String(idx + 1)] ?? extras[type] ?? defaults[type] ?? 0);
        });
        continue;
      }

      // ── Mute : tout à 0, sauf une trichromie soustractive (filtres fermés) ─
      if (muted) {
        const subCmy = !(profile.includes("R") && profile.includes("G") && profile.includes("B"));
        profile.forEach((type, idx) => set(idx, subCmy && (type === "C" || type === "M" || type === "Y") ? 255 : 0));
        continue;
      }

      const level = f.level || 0;
      let dimmer = trunc((level / 100) * 255);
      const hasDimmer = profile.includes("Dim");
      const bc = hexToRgb(f.color);
      const ec = f.fx || plainColor(bc, level);
      let r, g, b;
      if (hasDimmer) {
        // Un effet a-t-il réécrit la couleur (proj.color ≠ base_color × niveau) ?
        let effectActive = false;
        if (level > 0) {
          const exp = bc.map((c) => trunc(c * level / 100));
          effectActive = ec.some((c, k) => Math.abs(c - exp[k]) > 4);
        } else if (ec[0] || ec[1] || ec[2]) {
          effectActive = true;                    // niveau 0 mais couleur non noire
        }
        if (effectActive) {
          // Couleur pure + luminosité extraites de la couleur de l'effet
          const maxC = Math.max(ec[0], ec[1], ec[2]);
          if (maxC > 0) {
            const scale = 255.0 / maxC;
            [r, g, b] = ec.map((c) => Math.min(255, trunc(c * scale)));
            dimmer = maxC;
          } else { r = g = b = 0; dimmer = 0; }
        } else { [r, g, b] = bc; }                // RGB = couleur pure, le niveau passe par Dim
      } else {
        [r, g, b] = ec;                           // pas de Dim : la couleur porte déjà le niveau
      }
      const hasStrobe = profile.includes("Strobe");
      const spd = f.strobe || 0;

      // Pan/Tilt : limites d'abord (repère de l'app), puis swap et inversion.
      let pan = Math.max(attr("pan_min", 0), Math.min(attr("pan_max", 65535), attr("pan", 32768)));
      let tilt = Math.max(attr("tilt_min", 0), Math.min(attr("tilt_max", 65535), attr("tilt", 32768)));
      if (f.pan_tilt_swap) [pan, tilt] = [tilt, pan];
      if (f.pan_invert) pan = 65535 - pan;
      if (f.tilt_invert) tilt = 65535 - tilt;

      const hasRgb = profile.includes("R") && profile.includes("G") && profile.includes("B");
      const wExtract = hasRgb && profile.includes("W") ? Math.min(r, g, b) : 0;

      // Couronne LED : suit la couleur, le niveau et le strobe du faisceau.
      const ringTypes = new Set(RING_DRIVEN.filter((t) => profile.includes(t)));
      const ringVals = {};
      if (ringTypes.size && f.ring_follow !== false) {
        let rc, rint;
        if (hasDimmer) { rc = [r, g, b]; rint = dimmer; }
        else {
          const m = Math.max(r, g, b);
          rc = m ? [trunc(r * 255 / m), trunc(g * 255 / m), trunc(b * 255 / m)] : [0, 0, 0];
          rint = m;
        }
        if (!ringTypes.has("RingDim")) rc = rc.map((c) => trunc(c * rint / 255));
        const rHasRgb = ringTypes.has("RingR") && ringTypes.has("RingG") && ringTypes.has("RingB");
        const rW = rHasRgb && ringTypes.has("RingW") ? Math.min(...rc) : 0;
        const all = {
          RingDim: rint,
          RingR: Math.max(0, rc[0] - rW), RingG: Math.max(0, rc[1] - rW), RingB: Math.max(0, rc[2] - rW),
          RingW: rHasRgb ? rW : Math.min(255, trunc(rc[0] * 0.30 + rc[1] * 0.59 + rc[2] * 0.11)),
          RingStrobe: spd > 0 ? trunc(16 + (spd / 100.0) * (250 - 16)) : 0,
        };
        for (const k of Object.keys(all)) ringVals[k] = all[k];
      }
      const fxCh = f.effect_channels || {};

      profile.forEach((type, idx) => {
        // Couche d'effet « Canal », puis contrôle brut par numéro, puis par type.
        if (fxCh[idx + 1] !== undefined) { set(idx, fxCh[idx + 1]); return; }
        const raw = extras[idx + 1] ?? extras[String(idx + 1)];
        if (raw !== undefined) { set(idx, raw); return; }
        if (extras[type] !== undefined) { set(idx, extras[type]); return; }

        let v = 0;
        switch (type) {
          case "R": v = Math.max(0, r - wExtract); break;
          case "G": v = Math.max(0, g - wExtract); break;
          case "B": v = Math.max(0, b - wExtract); break;
          case "W":
            v = hasRgb ? Math.min(255, wExtract + attr("white_boost"))
              : Math.min(255, trunc(r * 0.30 + g * 0.59 + b * 0.11) + attr("white_boost"));
            break;
          case "Ambre": v = Math.min(255, attr("amber_boost")); break;
          case "Orange": v = Math.min(255, attr("orange_boost")); break;
          case "UV": v = attr("uv"); break;
          case "Zoom": v = attr("zoom"); break;
          case "Iris": v = attr("iris"); break;
          case "Dim": case "Dim2":
            v = dimmer;
            // Strobe artificiel des gradateurs 1 canal (pas de canal Strobe)
            if (spd > 0 && !hasStrobe && f.fixture_type === "Gradateur") {
              const freq = 0.5 + (spd / 100.0) * 14.5;
              if (pmod(Math.floor(now * freq * 2), 2) === 1) v = 0;
            }
            break;
          case "Reset": case "Unused": v = 0; break;
          case "Strobe": v = spd > 0 ? trunc(16 + (spd / 100.0) * (250 - 16)) : 0; break;
          case "Pan": v = pan >> 8; break;
          case "PanFine": v = pan & 0xFF; break;
          case "Tilt": v = tilt >> 8; break;
          case "TiltFine": v = tilt & 0xFF; break;
          case "Gobo1": v = attr("gobo"); break;
          case "Gobo1Rot": v = attr("gobo_rotation"); break;
          case "ColorWheel": v = attr("color_wheel"); break;
          case "Shutter": {
            const sh = attr("shutter", 255);
            v = f.shutter_inverted ? 255 - sh : sh;
            // Strobe porté par le shutter quand le profil n'a pas de canal Strobe
            if (spd > 0 && !hasStrobe) {
              let lo = trunc(attr("shutter_strobe_min", 64)), hi = trunc(attr("shutter_strobe_max", 95));
              if (hi < lo) [lo, hi] = [hi, lo];
              v = Math.max(0, Math.min(255, trunc(lo + (spd / 100.0) * (hi - lo))));
            }
            break;
          }
          case "Prism": v = attr("prism"); break;
          case "PrismRot": v = attr("prism_rotation"); break;
          case "Effects": v = attr("effects"); break;
          case "C": case "M": case "Y":
            // LED additive C/M/Y : manuel seulement. Spot à drapeaux : soustractif.
            v = hasRgb ? 0 : 255 - (type === "C" ? r : type === "M" ? g : b);
            break;
          case "Lime": v = 0; break;
          case "CTO": case "CTB": v = 0; break;
          case "Focus": v = attr("focus"); break;
          case "Gobo2": v = attr("gobo2"); break;
          case "Speed": v = attr("speed"); break;
          case "Mode": v = attr("mode_value"); break;
          default:
            if (PRESET_ATTR[type]) v = attr(PRESET_ATTR[type]);
            else if (ringVals[type] !== undefined) v = Math.max(0, Math.min(255, trunc(ringVals[type])));
            else v = 0;                            // canaux manuels (Frost, Anim…) et inconnus : repos
        }
        // Valeur par défaut : appliquée quand le canal sortirait 0
        if (v === 0 && defaults[type] !== undefined) v = defaults[type];
        set(idx, v);
      });
    }
    return dmx;
  }

  function channelCount(profile) { return (Array.isArray(profile) ? profile : PROFILES[profile] || []).length; }

  // ── Effets à couches ───────────────────────────────────────────────────────

  // random.Random(seed).random() de Python (Mersenne Twister, graine entière
  // découpée en mots de 32 bits) : la forme « Aléatoire » doit tirer les MÊMES
  // nombres que le PC (core.random_wave).
  function pyRandom(seed) {
    const mt = new Uint32Array(624);
    const mul = (a, b) => Math.imul(a, b) >>> 0;
    mt[0] = 19650218;
    for (let i = 1; i < 624; i++) mt[i] = (mul(1812433253, mt[i - 1] ^ (mt[i - 1] >>> 30)) + i) >>> 0;
    let n = Math.abs(seed);
    const key = [];
    do { key.push(n % 4294967296 >>> 0); n = Math.floor(n / 4294967296); } while (n > 0);
    let i = 1, j = 0;
    for (let k = Math.max(624, key.length); k > 0; k--) {
      mt[i] = ((mt[i] ^ mul(mt[i - 1] ^ (mt[i - 1] >>> 30), 1664525)) + key[j] + j) >>> 0;
      i++; j++;
      if (i >= 624) { mt[0] = mt[623]; i = 1; }
      if (j >= key.length) j = 0;
    }
    for (let k = 623; k > 0; k--) {
      mt[i] = ((mt[i] ^ mul(mt[i - 1] ^ (mt[i - 1] >>> 30), 1566083941)) - i) >>> 0;
      i++;
      if (i >= 624) { mt[0] = mt[623]; i = 1; }
    }
    mt[0] = 0x80000000;
    // Deux tirages 32 bits → un double, comme random_random() de CPython.
    let idx = 624;
    function next() {
      if (idx >= 624) {
        for (let k = 0; k < 624; k++) {
          const y = (mt[k] & 0x80000000) | (mt[(k + 1) % 624] & 0x7fffffff);
          mt[k] = (mt[(k + 397) % 624] ^ (y >>> 1) ^ (y & 1 ? 0x9908b0df : 0)) >>> 0;
        }
        idx = 0;
      }
      let y = mt[idx++];
      y ^= y >>> 11; y = (y ^ ((y << 7) & 0x9d2c5680)) >>> 0;
      y = (y ^ ((y << 15) & 0xefc60000)) >>> 0; y ^= y >>> 18;
      return y >>> 0;
    }
    const a = next() >>> 5, b = next() >>> 6;
    return (a * 67108864.0 + b) * (1.0 / 9007199254740992.0);
  }

  // Ports de core.py (points uniques côté PC : même formule ici).
  function layerFrequency(speed, mult = 1.0) {
    const s = Math.max(0.0, Number(speed || 0)) * mult;
    return s <= 0 ? 0.0 : 0.05 + s / 100.0 * 7.0;
  }
  function spreadRank(i, n, mode) {
    n = Math.max(1, trunc(n));
    if (n === 1) return 0.0;
    const dist = Math.abs(i - (n - 1) / 2.0) / ((n - 1) / 2.0);
    if (mode === "miroir") return dist;
    if (mode === "miroir_in") return 1.0 - dist;
    if (mode === "pair_impair") return i % 2 === 0 ? 0.0 : 0.5;
    if (mode === "aleatoire") {
      let h = Number((BigInt(i + 1) * 2654435761n) % 4294967296n);
      h ^= h >>> 13; h >>>= 0;
      h = Number((BigInt(h) * 1274126177n) % 4294967296n);
      h = (h ^ (h >>> 16)) >>> 0;
      return (h % 10000) / 10000.0;
    }
    return i / n;
  }
  function blockIndex(i, n, block) {
    n = Math.max(1, trunc(n));
    const b = Math.max(1, trunc(block || 1));
    if (b <= 1) return [trunc(i), n];
    return [Math.floor(trunc(i) / b), Math.max(1, Math.floor((n + b - 1) / b))];
  }
  function chaseSlot(posCycles, n, direction) {
    n = Math.max(1, trunc(n));
    if (n === 1) return 0;
    const p = Math.floor(posCycles * n);
    if (direction === 0) { const m = 2 * n - 2; const q = pmod(p, m); return q < n ? q : m - q; }
    if (direction === -1) return pmod(-p, n);
    return pmod(p, n);
  }
  function randomWave(freq, t, index) {
    return pyRandom(trunc(freq * t) * 1000 + trunc(index));
  }
  function wave(forme, x) {
    switch (forme) {
      case "Sinus": return (Math.sin(2 * Math.PI * x) + 1) / 2;
      case "Flash": return x < 0.5 ? 1.0 : 0.0;
      case "Triangle": return 1.0 - Math.abs(2 * x - 1);
      case "Montée": return x;
      case "Descente": return 1.0 - x;
      case "Un par un": return x < 0.25 ? 1.0 : 0.0;
      case "Fixe": return 1.0;
      default: return 0.0;
    }
  }


  // Lyres qui partent en Pan miroir (plan_de_feu.sym_mirror_ids) : celles à
  // droite de l'axe, sur leur position `x` du plan.
  function symMirror(lyres) {
    if (lyres.length < 2) return new Set();
    const xs = lyres.map((p) => p.x ?? 0.5);
    const lo = Math.min(...xs), hi = Math.max(...xs);
    if (hi - lo < 1e-6) return new Set(lyres.slice(Math.floor(lyres.length / 2)));
    const axis = (lo + hi) / 2.0, tol = (hi - lo) * 0.02;
    return new Set(lyres.filter((p, k) => xs[k] > axis + tol));
  }

  /**
   * Une frame d'effet, au temps de phase `t` (secondes × vitesse générale,
   * cf. l'horloge de phase du PC). Mute chaque projecteur : `fx` (= proj.color),
   * `level`, `pan`, `tilt`, à partir de `color` (base_color), `group` (lettre
   * A-H), `pan`/`tilt` (la visée d'avant l'effet, centre du mouvement) et `x`
   * (position sur le plan, pour SYM). `shapes` = PAN_TILT_SHAPES du PC.
   * `fixtures` = tout le patch, dans l'ordre : les machines à effet (fumée,
   * étincelles…) en sont retirées, comme sur le PC (core.fixture_is_fx_machine).
   */
  function effectFrame(effect, allFixtures, t, shapes) {
    const layers = (effect && effect.layers) || [];
    const fixtures = allFixtures.filter((f) => !isFxMachine(f));
    const n = fixtures.length;
    if (!layers.length || n === 0) return;
    const groupAmp = {};
    layers.forEach((ld) => Object.assign(groupAmp, ld.group_amp || {}));
    const lyres = fixtures.filter(isLyre);
    const mhN = Math.max(lyres.length, 1);
    const symMir = layers.some((ld) => ld.sym_pan || ld.sym_tilt) ? symMirror(lyres) : new Set();
    shapes = shapes || {};

    fixtures.forEach((proj, i) => {
      // Centre du mouvement : la visée d'avant l'effet (capture du PC).
      const ctrPan = proj.pan ?? 32768, ctrTilt = proj.tilt ?? 32768;
      const mhI = lyres.indexOf(proj) >= 0 ? lyres.indexOf(proj) : i;
      // core.pan_angular_ratio : tilt° / pan° (540/270 par défaut → 0,5)
      const panRatio = (proj.tilt_range || 270) / (proj.pan_range || 540);
      let dim = 0, r = 0, g = 0, b = 0;
      let hasDim = false, hasRgbLayer = false;
      for (const ld of layers) {
        const preset = ld.target_preset || "Tous";
        const groups = ld.target_groups || [];
        if (preset === "Selection") continue;       // pas de sélection sur la tablette
        if (preset === "Pair" && i % 2 !== 0) continue;
        if (preset === "Impair" && i % 2 !== 1) continue;
        if (/^[A-H]$/.test(preset) && proj.group !== preset) continue;
        if (groups.length && !groups.includes(proj.group)) continue;

        const speed = ld.speed ?? 50, size = ld.size ?? 100, spread = ld.spread ?? 0;
        const phase = (ld.phase ?? 0) / 100.0, fade = (ld.fade ?? 0) / 100.0;
        const direction = ld.direction ?? 1, forme = ld.forme || "Sinus";
        const attr = ld.attribute || "Dimmer";
        const freq = layerFrequency(speed);
        const sp = spread / 180.0;
        const [iRk, nRk] = blockIndex(i, n, ld.block ?? 1);
        const rk = spreadRank(iRk, nRk, ld.spread_mode || "lineaire");
        let x;
        if (direction === 0) x = pmod(Math.abs(2 * pmod(freq * t, 1.0) - 1) + rk * sp + phase, 1.0);
        else if (direction === -1) x = pmod(freq * t - rk * sp + phase, 1.0);
        else x = pmod(freq * t + rk * sp + phase, 1.0);

        let raw;
        if (forme === "Un par un") raw = chaseSlot(freq * t + phase, nRk, direction) === iRk ? 1.0 : 0.0;
        else if (forme === "Audio" || forme === "Aléatoire") raw = randomWave(freq, t, iRk);
        else raw = wave(forme, x);
        if (fade > 0 && forme !== "Un par un") raw = raw * (1 - fade) + ((Math.sin(2 * Math.PI * x) + 1) / 2) * fade;
        let minV, maxV;
        if (groupAmp[proj.group]) { minV = groupAmp[proj.group][0] / 100.0; maxV = groupAmp[proj.group][1] / 100.0; }
        else { minV = (ld.min_val ?? 0) / 100.0; maxV = (ld.max_val ?? 100) / 100.0; }
        const scaled = (minV + raw * (maxV - minV)) * size / 100.0;

        if (attr === "Dimmer" || attr === "Strobe") { dim += scaled; hasDim = true; }
        else if (attr === "R") { r += scaled; hasRgbLayer = true; }
        else if (attr === "V") { g += scaled; hasRgbLayer = true; }
        else if (attr === "B") { b += scaled; hasRgbLayer = true; }
        else if (attr === "RGB") {
          hasRgbLayer = true;
          const c1 = hexToRgb(ld.color1 || "#ffffff");
          r += qF(c1[0]) * scaled; g += qF(c1[1]) * scaled; b += qF(c1[2]) * scaled;
        } else if (attr === "Pan" || attr === "Tilt") {
          // AMP 100 = ±8192 (±12,5 % de course), cf. le commentaire du PC.
          const amplitude = (size / 100.0) * 8192;
          const [mi, mn] = blockIndex(mhI, mhN, ld.block ?? 1);
          const spMove = Math.min(1.0, spread / 100.0);
          let rawMv;
          if (forme === "Audio" || forme === "Aléatoire" || forme === "Un par un") rawMv = raw;
          else {
            let xMv;
            if (direction === 0) xMv = pmod(Math.abs(2 * pmod(freq * t, 1.0) - 1) + mi / mn * spMove + phase, 1.0);
            else if (direction === -1) xMv = pmod(freq * t - mi / mn * spMove + phase, 1.0);
            else xMv = pmod(freq * t + mi / mn * spMove + phase, 1.0);
            rawMv = wave(forme, xMv);
          }
          if (attr === "Pan") {
            const sign = ld.sym_pan && symMir.has(proj) ? -1 : 1;
            proj.pan = trunc(Math.max(0, Math.min(65535, ctrPan + sign * (rawMv - 0.5) * 2 * amplitude * panRatio)));
          } else {
            const sign = ld.sym_tilt && symMir.has(proj) ? -1 : 1;
            proj.tilt = trunc(Math.max(0, Math.min(65535, ctrTilt + sign * (rawMv - 0.5) * 2 * amplitude)));
          }
        } else if (attr === "Pan/Tilt") {
          const def = shapes[ld.mouvement_shape || "cercle"] || shapes.cercle || {};
          const [panForme, panPh, panMult] = def.pan || ["Sinus", 0, 1.0];
          const [tiltForme, tiltPh, tiltMult] = def.tilt || ["Sinus", 25, 1.0];
          const amplitude = (size / 100.0) * 8192;
          const [mi, mn] = blockIndex(mhI, mhN, ld.block ?? 1);
          const panSign = ld.sym_pan && symMir.has(proj) ? -1 : 1;
          const tiltSign = ld.sym_tilt && symMir.has(proj) ? -1 : 1;
          const spMove = Math.min(1.0, spread / 100.0);
          const ptTime = (f) => (direction === 0 ? Math.abs(2 * pmod(f * t, 1.0) - 1) : direction === -1 ? -f * t : f * t);
          if (panForme && panForme !== "Fixe") {
            const pf = layerFrequency(speed, panMult);
            const px = pmod(ptTime(pf) + mi / mn * spMove + phase + panPh / 100.0, 1.0);
            proj.pan = trunc(Math.max(0, Math.min(65535, ctrPan + panSign * (wave(panForme, px) - 0.5) * 2 * amplitude * panRatio)));
          }
          if (tiltForme && tiltForme !== "Fixe") {
            const tf = layerFrequency(speed, tiltMult);
            const tx = pmod(ptTime(tf) + mi / mn * spMove + phase + tiltPh / 100.0, 1.0);
            proj.tilt = trunc(Math.max(0, Math.min(65535, ctrTilt + tiltSign * (wave(tiltForme, tx) - 0.5) * 2 * amplitude)));
          }
        } else if (attr === "Permut") {
          hasRgbLayer = true;
          const c1 = hexToRgb(ld.color1 || "#ff0000"), c2 = hexToRgb(ld.color2 || "#0000ff");
          const r2 = 1.0 - raw, amp = size / 100.0;
          r += (qF(c1[0]) * raw + qF(c2[0]) * r2) * amp;
          g += (qF(c1[1]) * raw + qF(c2[1]) * r2) * amp;
          b += (qF(c1[2]) * raw + qF(c2[2]) * r2) * amp;
        }
      }

      const bv = hasDim ? Math.min(1.0, dim) : 1.0;
      const hasColorVal = r > 0 || g > 0 || b > 0;
      if (hasColorVal || hasRgbLayer) proj.level = 100;   // ouvre le dimmer pour laisser passer l'effet
      if (hasColorVal) {
        const c = [r, g, b].map((v) => Math.min(255, trunc(v * 255)));
        proj.fx = c.map((v) => trunc(v * bv));
        updateColorWheel(proj, proj.fx);           // lyre à roue : suit la couleur de l'effet
      } else if (hasRgbLayer) {
        proj.fx = [0, 0, 0];
        updateColorWheel(proj, proj.fx);
      } else if (hasDim) {
        // Dimmer seul : module la couleur posée (core.effect_dim_base_color :
        // couleur de la roue, sinon blanc pour un profil sans R/G/B).
        proj.level = trunc(bv * 100);
        const stable = effectDimBaseColor(proj, hexToRgb(proj.color));
        proj.fx = stable.map((v) => trunc(v * bv));
      }
    });
  }

  const api = { PROFILES, PROFILE_LABELS, render, channelCount, hexToRgb, effectFrame, pyRandom, symMirror, isLyre,
                profileOf, isFxMachine, updateColorWheel, cwSlotAt, CW_DEFAULT_SLOTS };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MystrowEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
