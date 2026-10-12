// Onglet LIVE du mode sans PC : la lumière réagit à la musique (micro de la
// tablette, ou entrée ligne d'un adaptateur audio USB).
//
// Chargé après standalone.js (voir scripts/build-www.mjs). Port de l'ESSENTIEL
// du mode LIVE « Musical IA » du logiciel PC (choix du 12/10/2026) :
//   - analyse : live_audio.LiveAudioEngine (_audio_cb, _update_bands,
//     _detect_transients, _process_chunk, _detect_section_live, _update_bpm),
//     morceaux de 50 ms comme le PC ;
//   - état par groupe : audio_ai.AudioColorAI (palette, get_state_at) ;
//   - rendu : MainWindow._apply_live_state_inner en mode « musical » — base
//     par groupe + bicolore, couleurs restreintes aux tuiles choisies, drop /
//     montée, flashs sur kick et caisse claire, flash et strobe « intelligents »,
//     strobe blanc du drop, lyres qui tournent au rythme, fondu au silence.
// Pas portés (v1) : effets spéciaux, séquences LIVE, tuiles Flash/Strobe/Gobo,
// pool de gobos, canal Strobe matériel, sources MIDI Clock / Virtual DJ.
// Le LIVE prend la main sur l'AKAI tant qu'il écoute (comme le PC en Musical IA).
// (Avant le 12/10/2026, cet onglet était une page simple DJ / bar.)
(function () {
  "use strict";
  const Solo = window.MystrowSolo;
  if (!window.MYSTROW_SOLO || !Solo || !Solo.core) return;
  const C = Solo.core;
  const Engine = window.MystrowEngine;
  const { play, projectors } = C;

  // Groupes du PC ↔ lettres de la tablette (main_window.AKAI_GROUP_MAP).
  const INTERNAL = { A: "face", B: "lat", C: "contre", D: "douche1", E: "douche2", F: "douche3", G: "groupe_g", H: "groupe_h" };
  const ACCENT_GROUPS = ["douche1", "douche2", "douche3", "groupe_g", "groupe_h"];          // audio_ai.ACCENT_GROUPS
  const BASE_COLOR_GROUPS = new Set(["face", "lat", "contre", "douche1", "douche2", "douche3"]); // _IA_BASE_COLOR_GROUPS
  // Tuiles couleur du panneau LIVE (LiveModePanel._COLOR_TILES, sans AUTO) : [clé, c1, c2, nom].
  const TILES = [
    ["rouge", "#ff1133", null, "Rouge"], ["orange", "#ff8800", null, "Orange"], ["jaune", "#ffee00", null, "Jaune"],
    ["ambre", "#ffaa00", null, "Ambre"], ["rose", "#ff44aa", null, "Rose"], ["rose_chaud", "#ff2266", null, "Rose chaud"],
    ["vert", "#00ff55", null, "Vert"], ["cyan", "#00eeff", null, "Cyan"], ["bleu", "#0055ff", null, "Bleu"],
    ["bleu_nuit", "#001aff", null, "Bleu nuit"], ["violet", "#aa22ff", null, "Violet"], ["lavande", "#cc88ff", null, "Lavande"],
    ["blanc", "#ffffff", null, "Blanc"],
    ["bi_rb", "#ff1133", "#0055ff", "Rouge / bleu"], ["bi_vo", "#aa22ff", "#ff8800", "Violet / orange"],
    ["bi_vj", "#00ff55", "#ffee00", "Vert / jaune"], ["bi_rv", "#ff1133", "#aa22ff", "Rouge / violet"],
    ["bi_cc", "#ff8800", "#00eeff", "Orange / cyan"], ["bi_bv", "#0055ff", "#00ff55", "Bleu / vert"],
  ];
  const tileByKey = Object.fromEntries(TILES.map((t) => [t[0], t]));
  const MOVES = [["cercle", "Cercle"], ["huit", "Huit"], ["vague", "Vague"], ["diagonale", "Diagonale"],
                 ["bounce", "Rebond"], ["spirale", "Spirale"], ["lissajous", "Lissajous"], ["random", "Aléatoire"]];
  const DROPS = [["flash_blanc", "Flash blanc"], ["color_explosion", "Explosion couleur"], ["blackout_punch", "Noir puis flash"],
                 ["stroboscope", "Stroboscope"], ["strobe_sync", "Strobe couleur"]];
  const SECTIONS = { quiet: "CALME", verse: "COUPLET", build: "MONTÉE", high: "INTENSE", drop: "DROP" };
  const SMART_STROBE_CHANCE = 0.25, SMART_STROBE_COOLDOWN_S = 2.0, SMART_STROBE_MS = 320;   // main_window

  // Réglages (défauts du panneau LIVE du PC), gardés avec l'état du jeu.
  play.live = Object.assign({
    pool: ["rouge", "rose", "vert", "bleu"], cur: "rouge", colorDuration: 40,
    moves: ["cercle"], mov: "cercle", movSpeed: 50, movSize: 70, movDuration: 40,
    nerv: 50, sens: 70, strob: "fast", drop: "flash_blanc", master: 100,
  }, play.live || {});
  const L = play.live;
  delete play.scenes; delete play.liveZone; delete play.liveScene; delete play.ui;   // ancienne page DJ / bar
  const nowS = () => performance.now() / 1000;

  // ── Analyse audio (live_audio.LiveAudioEngine) ──────────────────────────────
  const A = {
    running: false, ctx: null, stream: null, analyser: null, buf: null, timer: null, sr: 44100,
    rms: [], norm: [], beatTimes: [], lastBeatTs: 0, bpm: 0, elapsed: 0,
    section: "verse", votes: [], bandShort: {}, bandLong: {}, bandNorm: {},
    lastTr: { kick: 0, snare: 0, hihat: 0 }, beatPending: false, energyMap: [], beats: [], vu: 0,
  };
  const push = (arr, v, max) => { arr.push(v); if (arr.length > max) arr.shift(); };
  const BANDS = { sub: [20, 80], bass: [80, 300], mids: [300, 3000], highs: [3000, 16000] };
  function resetAnalysis() {
    Object.assign(A, { rms: [], norm: [], beatTimes: [], lastBeatTs: nowS(), bpm: 0, elapsed: 0, section: "verse", votes: [],
      lastTr: { kick: 0, snare: 0, hihat: 0 }, beatPending: false, energyMap: [], beats: [], vu: 0 });
    Object.keys(BANDS).forEach((k) => { A.bandShort[k] = []; A.bandLong[k] = []; A.bandNorm[k] = 0; });
  }
  // FFT réelle (radix 2) → module des raies 0..n/2.
  function fftMag(x) {
    const n = x.length, re = Float64Array.from(x), im = new Float64Array(n);
    for (let i = 1, j = 0; i < n; i++) {
      let bit = n >> 1;
      for (; j & bit; bit >>= 1) j ^= bit;
      j ^= bit;
      if (i < j) { const t = re[i]; re[i] = re[j]; re[j] = t; }
    }
    for (let len = 2; len <= n; len <<= 1) {
      const ang = -2 * Math.PI / len, wr = Math.cos(ang), wi = Math.sin(ang);
      for (let i = 0; i < n; i += len) {
        let cr = 1, ci = 0;
        for (let k = 0; k < len / 2; k++) {
          const a = i + k, b = a + len / 2;
          const tr = re[b] * cr - im[b] * ci, ti = re[b] * ci + im[b] * cr;
          re[b] = re[a] - tr; im[b] = im[a] - ti; re[a] += tr; im[a] += ti;
          const nr = cr * wr - ci * wi; ci = cr * wi + ci * wr; cr = nr;
        }
      }
    }
    const out = new Float64Array(n / 2 + 1);
    for (let k = 0; k <= n / 2; k++) out[k] = Math.hypot(re[k], im[k]);
    return out;
  }
  function updateBands(mono) {
    const n = mono.length;
    const w = new Float64Array(n);
    for (let i = 0; i < n; i++) w[i] = mono[i] * (0.5 - 0.5 * Math.cos(2 * Math.PI * i / (n - 1)));   // numpy.hanning
    const spec = fftMag(w);
    Object.entries(BANDS).forEach(([k, [lo, hi]]) => {
      let s = 0, c = 0;
      for (let i = 0; i < spec.length; i++) { const f = i * A.sr / n; if (f >= lo && f < hi) { s += spec[i] * spec[i]; c++; } }
      const v = c ? Math.sqrt(s / c) / Math.max(n * 0.5, 1) : 0;
      push(A.bandShort[k], v, 6); push(A.bandLong[k], v, 80);
      const longMax = Math.max(0, ...A.bandLong[k]);
      A.bandNorm[k] = Math.min(1, v / Math.max(longMax, 1e-9));
    });
    detectTransients();
  }
  function detectTransients() {
    const now = nowS();
    const spike = (band, hit, threshold, refract) => {
      const lg = A.bandLong[band], sh = A.bandShort[band];
      if (!lg.length || !sh.length) return false;
      const avg = lg.reduce((a, b) => a + b, 0) / lg.length;
      if (avg < 1e-9) return false;
      return sh[sh.length - 1] > avg * threshold && now - A.lastTr[hit] > refract;
    };
    if (spike("sub", "kick", 1.9, 0.35)) {
      A.lastTr.kick = now;
      A.lastBeatTs = now; A.beats.push(A.elapsed); push(A.beatTimes, now, 16); A.beatPending = true;
      updateBpm(); onTransient("kick");
    }
    if (spike("mids", "snare", 1.7, 0.15)) { A.lastTr.snare = now; onTransient("snare"); }
    if (spike("highs", "hihat", 1.5, 0.08)) { A.lastTr.hihat = now; onTransient("hihat"); }
  }
  function processChunk(rms) {
    push(A.rms, rms, 80);
    const localMax = Math.max(Math.max(...A.rms, 0.01), 0.001);
    const norm = Math.min(1, rms / localMax);
    push(A.norm, norm, 80);
    A.energyMap.push(norm);
    A.elapsed += 50;
    if (A.energyMap.length > 18000) {                  // _trim_if_needed
      const trimN = A.energyMap.length - 9000, trimMs = trimN * 50;
      A.energyMap.splice(0, trimN);
      A.beats = A.beats.filter((b) => b >= trimMs).map((b) => b - trimMs);
      A.elapsed -= trimMs;
      AI.lastBeatIdx = A.beats.length - 1;
      AI.beatGroupCount = Math.max(0, AI.beatGroupCount - trimN);
    }
    A.vu = Math.min(100, norm * 100);
    push(A.votes, detectSection(), 6);
    if (A.votes.length >= 4) {
      const counts = {};
      A.votes.forEach((s) => { counts[s] = (counts[s] || 0) + 1; });
      const dom = Object.keys(counts).reduce((a, b) => (counts[b] > counts[a] ? b : a));
      if (counts[dom] >= 4) A.section = dom;
    }
    if (A.rms.length >= 12) {
      const now = nowS();
      if (!(now - A.lastTr.kick < 4.0)) {             // sans kick depuis 4 s : détection RMS
        const avg = A.rms.reduce((a, b) => a + b, 0) / A.rms.length;
        const sens = L.sens / 100, nerv = L.nerv / 100;
        const threshold = avg * (2.0 + (sens - 0.5) * 0.7);
        const minGap = 0.43 - nerv * 0.09;
        if (norm > threshold && norm > 0.20 && now - A.lastBeatTs > minGap) {
          A.lastBeatTs = now; A.beats.push(A.elapsed); push(A.beatTimes, now, 16); A.beatPending = true;
          updateBpm();
        }
      }
    }
  }
  function detectSection() {
    const h = A.norm, n = h.length;
    if (n < 10) return "quiet";
    if (A.rms.length) {
      const r = A.rms.slice(-20);
      if (r.reduce((a, b) => a + b, 0) / r.length < 0.01) return "quiet";
    }
    const mean = (a) => a.reduce((x, y) => x + y, 0) / a.length;
    const curr = mean(h.slice(-10)), long = mean(h), past = n >= 40 ? mean(h.slice(-40, -20)) : long;
    const jump = curr - long, trend = curr - past;
    if (jump > 0.26 && curr > 0.55) return "drop";
    if (curr > 0.55 && long > 0.48) return "high";
    if (trend > 0.11 && curr > 0.30) return "build";
    if (curr < 0.18) return "quiet";
    return "verse";
  }
  function updateBpm() {
    if (A.beatTimes.length < 4) return;
    const recent = A.beatTimes.slice(-8);
    const valid = recent.slice(1).map((t, i) => t - recent[i]).filter((iv) => iv > 0.32 && iv < 1.0);
    if (valid.length < 3) return;
    let best = valid[0], bestN = 0;
    valid.forEach((c) => { const k = valid.filter((iv) => Math.abs(iv - c) / c < 0.15).length; if (k > bestN) { bestN = k; best = c; } });
    const cl = valid.filter((iv) => Math.abs(iv - best) / best < 0.15);
    let nb = 60 / (cl.reduce((a, b) => a + b, 0) / cl.length);
    if (A.bpm > 0) {
      const ratio = nb / A.bpm;
      if (ratio > 1.8 && ratio < 2.2) nb /= 2; else if (ratio > 0.45 && ratio < 0.56) nb *= 2;
      const alpha = Math.abs(nb - A.bpm) / A.bpm < 0.08 ? 0.25 : 0.12;
      A.bpm = A.bpm * (1 - alpha) + nb * alpha;
    } else A.bpm = nb;
  }
  function chunk() {
    if (!A.running || !A.analyser) return;
    A.analyser.getFloatTimeDomainData(A.buf);
    const mono = A.buf;                                 // 2048 dernières valeurs (~45 ms)
    let s = 0;
    for (let i = 0; i < mono.length; i++) s += mono[i] * mono[i];
    const raw = Math.sqrt(s / mono.length);
    const rms = raw > 0.0003 ? raw * 3.0 : 0.0;
    updateBands(mono);
    processChunk(rms);
  }
  async function startAudio() {
    if (A.running) return true;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) { Solo.toast("Micro indisponible sur cet appareil", 3000); return false; }
    try {
      // Pas d'annulation d'écho, ni de réduction de bruit, ni de gain auto :
      // ils sont faits pour la voix et écraseraient la dynamique de la musique.
      A.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    } catch (e) {
      Solo.toast("Accès au micro refusé : autorisez-le dans les réglages de la tablette.", 4500);
      return false;
    }
    A.ctx = new (window.AudioContext || window.webkitAudioContext)();
    if (A.ctx.state === "suspended") await A.ctx.resume().catch(() => {});
    A.sr = A.ctx.sampleRate;
    A.analyser = A.ctx.createAnalyser();
    A.analyser.fftSize = 2048;
    A.buf = new Float32Array(2048);
    A.ctx.createMediaStreamSource(A.stream).connect(A.analyser);
    resetAnalysis(); resetRender();
    AI.reset(); AI.setDominant(tileByKey[L.cur] ? tileByKey[L.cur][1] : "#ff1133");
    A.running = true;
    A.timer = setInterval(chunk, 50);
    C.runTimer();                                  // boucle de sortie à 40 images/s
    C.refresh(true);
    return true;
  }
  function stopAudio() {
    A.running = false;
    clearInterval(A.timer); A.timer = null;
    if (A.stream) A.stream.getTracks().forEach((t) => t.stop());
    if (A.ctx) A.ctx.close().catch(() => {});
    A.stream = A.ctx = A.analyser = null;
    C.runTimer();
    C.allPads(); C.refresh(true);
  }

  // ── AudioColorAI (audio_ai.py) ──────────────────────────────────────────────
  // HSV au sens de QColor (teinte 0-359, -1 pour un gris ; saturation et valeur 0-255).
  function toHsv(hex) {
    const [r, g, b] = Engine.hexToRgb(hex), mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
    let h = -1;
    if (d) {
      if (mx === r) h = 60 * (((g - b) / d) % 6); else if (mx === g) h = 60 * ((b - r) / d + 2); else h = 60 * ((r - g) / d + 4);
      h = Math.round((h + 360) % 360);
    }
    return [h, mx ? Math.round(d * 255 / mx) : 0, mx];
  }
  function fromHsv(h, s, v) {
    const S = s / 255, V = v / 255, c = V * S, x = c * (1 - Math.abs(((h / 60) % 2) - 1)), m = V - c;
    const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
    return [r, g, b].map((u) => Math.round((u + m) * 255));
  }
  const AI = {
    dominant: "#ff0000", palette: [],
    reset() {
      Object.assign(this, { contreIdx: 0, latIdx: 0, lastBeatIdx: -1, beatGroupCount: 0, flashUntil: 0,
        effContreUntil: 0, effLatUntil: 0, effContre: null, effLat: null, contreAlt: 0, latAlt: 0,
        bicolor: false, bicolorUntil: 0, faceIdx: 0, faceAlt: 0, chaseIdx: 0 });
    },
    setDominant(hex) {
      this.dominant = hex;
      let [h, s, v] = toHsv(hex);
      if (h < 0) { h = 0; s = 255; v = 255; }
      this.palette = [0, 20, -20, 40, -40, 60, -60, 180].map((o) => fromHsv(((h + o) % 360 + 360) % 360,
        Math.max(150, Math.min(255, s)), Math.max(200, Math.min(255, v))));
    },
    altDistinct(idx, principal) {
      const n = this.palette.length;
      for (let k = 0; k < n; k++) { const c = this.palette[(idx + k) % n]; if (c.join() !== principal.join()) return c; }
      return this.palette[idx % n];
    },
    // get_state_at(time_ms, 0, accent_groups) — couleurs [r,g,b].
    stateAt(t, accentPool) {
      const P = this.palette, nP = P.length;
      const idx = Math.trunc(t / 50);
      const energy = idx >= 0 && idx < A.energyMap.length ? A.energyMap[idx] : 0.5;
      let beatIdx = -1;
      for (let i = 0; i < A.beats.length; i++) { if (A.beats[i] <= t) beatIdx = i; else break; }
      if (beatIdx >= 0 && beatIdx !== this.lastBeatIdx) {
        this.lastBeatIdx = beatIdx;
        this.beatGroupCount++;
        this.contreIdx = beatIdx % nP;
        this.latIdx = this.beatGroupCount % 4 === 0 ? (this.contreIdx + 2) % nP : this.contreIdx;
        if (this.beatGroupCount % 2 === 0) this.faceIdx = (this.contreIdx + 3) % nP;
        this.chaseIdx = beatIdx % Math.max(1, accentPool.length);
        if (energy > 0.75 && this.beatGroupCount % 4 === 0) this.flashUntil = t + 150;
        if (this.beatGroupCount % 8 === 0 && energy > 0.6) { this.effContre = "pulse"; this.effContreUntil = t + 2000; }
        if (this.beatGroupCount % 16 === 0 && energy > 0.5) { this.effLat = "strobe"; this.effLatUntil = t + 1000; }
        if (this.beatGroupCount % 6 === 0) {
          this.bicolor = true;
          this.contreAlt = (this.contreIdx + 4) % nP; this.latAlt = (this.latIdx + 3) % nP; this.faceAlt = (this.faceIdx + 2) % nP;
          let avg = 500;
          if (A.beats.length > 1) avg = (A.beats[A.beats.length - 1] - A.beats[0]) / (A.beats.length - 1);
          this.bicolorUntil = t + Math.trunc(avg * 4);
        }
      }
      if (t >= this.effContreUntil) this.effContre = null;
      if (t >= this.effLatUntil) this.effLat = null;
      if (t >= this.bicolorUntil) this.bicolor = false;
      const fade = t < 5000 ? t / 5000 : 1.0;
      const flashing = t < this.flashUntil, W = [255, 255, 255];
      const lvl = (base) => Math.trunc(base * fade);
      const face = flashing ? [W, lvl(100)] : [P[this.faceIdx], lvl(65 + energy * 25)];
      const contre = flashing ? [W, lvl(100)] : [P[this.contreIdx], lvl(65 + energy * 25)];
      if (this.effContre === "pulse") contre[1] = Math.trunc(contre[1] * (0.3 + 0.7 * (Math.sin(t * 8 / 1000) * 0.5 + 0.5)));
      const lat = flashing ? [W, lvl(100)] : [P[this.latIdx], lvl(65 + energy * 25)];
      if (this.effLat === "strobe" && Math.trunc(t / 80) % 2 !== 0) lat[1] = 0;
      const defBase = Math.trunc((70 + energy * 30) * fade);
      const st = {};
      accentPool.forEach((g, i) => {
        st[g] = flashing ? [W, 100] : [P[(this.contreIdx + 2 * i) % nP], i === this.chaseIdx ? defBase : Math.max(20, Math.trunc(defBase * 0.45))];
      });
      const clamp = (x) => [x[0], Math.max(0, Math.min(100, x[1]))];
      return { face: clamp(face), contre: clamp(contre), lat: clamp(lat), ...Object.fromEntries(Object.entries(st).map(([k, v]) => [k, clamp(v)])),
        contre_alt: this.bicolor ? this.altDistinct(this.contreAlt, contre[0]) : null,
        lat_alt: this.bicolor ? this.altDistinct(this.latAlt, lat[0]) : null,
        face_alt: this.bicolor ? this.altDistinct(this.faceAlt, face[0]) : null,
        lat_effect: this.effLat, energy };
    },
  };
  AI.reset();

  // ── Rendu « Musical IA » (MainWindow._apply_live_state_inner) ───────────────
  const R = {};
  function resetRender() {
    Object.keys(R).forEach((k) => delete R[k]);
    Object.assign(R, { sec: { last: null, dropStart: -1 }, tr: {}, bs: { smartFlashUntil: 0, smartStrobeUntil: 0 },
      sfx: { lastFlash: 0, lastStrobe: 0, dropStrobe: false }, lyre: null, silenceStart: null, colorSwitch: null, movSwitch: null });
  }
  resetRender();
  const curTile = () => tileByKey[L.cur] || tileByKey[L.pool[0]] || TILES[0];
  // Transitoires (_on_live_transient_inner).
  function onTransient(hit) {
    const pos = A.elapsed;
    if (hit === "kick") {
      R.tr.contreUntil = pos + 70;
      beatDot();
      const now = nowS(), sfx = R.sfx;
      sfx.dropStrobe = A.section === "drop";
      if (A.section === "drop" || A.section === "high") {
        if (now - sfx.lastFlash > 1.8 && Math.random() < 0.22) { sfx.lastFlash = now; R.bs.smartFlashUntil = pos + 140; }
        if (now - sfx.lastStrobe > SMART_STROBE_COOLDOWN_S && Math.random() < SMART_STROBE_CHANCE) { sfx.lastStrobe = now; R.bs.smartStrobeUntil = pos + SMART_STROBE_MS; }
      }
    } else if (hit === "snare") R.tr.faceUntil = pos + 55;
    else if (hit === "hihat") R.tr.lyreChopUntil = pos + 40;
  }
  // Zone autorisée d'une lyre (MainWindow._pantilt_in_limits).
  function inLimits(p, axis, norm, amp) {
    let lo = p[axis + "_min"] ?? 0, hi = p[axis + "_max"] ?? 65535;
    if (!(hi > lo)) { lo = 0; hi = 65535; }
    const center = Math.floor((lo + hi + 1) / 2);
    amp = Math.min(Math.abs(amp), (hi - lo) / 2);
    return Math.trunc(Math.max(lo, Math.min(hi, center + Math.trunc(norm * amp))));
  }
  function apply(states) {
    const pos = A.elapsed, now = nowS(), section = A.section;
    const nerv = L.nerv / 100, W = [255, 255, 255], K = [0, 0, 0];
    const groupOf = (i) => INTERNAL[projectors[i].group] || "face";
    const fxm = (i) => Engine.isFxMachine(projectors[i]);
    const accentPool = ACCENT_GROUPS.filter((g) => projectors.some((p) => INTERNAL[p.group] === g));
    const state = AI.stateAt(pos, accentPool);
    const energy = state.energy;
    // Silence absolu en section calme : fondu au noir en 2 s.
    if (section === "quiet") {
      const r = A.rms.slice(-10);
      if (r.length >= 10 && r.reduce((a, b) => a + b, 0) / 10 < 0.008) { if (!R.silenceStart) R.silenceStart = now; }
      else R.silenceStart = null;
    } else R.silenceStart = null;
    // Projecteur PC : base (couleur pure), niveau, couleur finale.
    const P = projectors.map(() => ({ base: K, level: 0, color: K }));
    const set = (i, color, level) => {
      const q = P[i]; q.level = Math.max(0, Math.min(100, Math.trunc(level))); q.base = color;
      q.color = q.level > 0 ? color.map((c) => Math.trunc(c * q.level / 100)) : K;
    };
    const black = (i) => { P[i].level = 0; P[i].color = K; };

    // 1. État de base par groupe (+ bicolore une fixture sur deux, strobe des latéraux).
    const idx = { face: 0, contre: 0, lat: 0 };
    projectors.forEach((p, i) => {
      const g = groupOf(i);
      if (!state[g]) return;
      let [color, level] = state[g];
      if (g === "face" || g === "contre" || g === "lat") {
        if (state[g + "_alt"] && idx[g] % 2 === 1) color = state[g + "_alt"];
        if (g === "lat" && state.lat_effect === "strobe" && Math.trunc(pos / Math.trunc(80 - nerv * 45)) % 2 !== 0) level = 0;
        idx[g]++;
      }
      set(i, color, level);
    });

    // Cycle des tuiles couleur (une tuile tous les N temps, réglage DURÉE).
    const beatsN = (d) => Math.max(2, Math.trunc(2 + (d / 100) * 30));
    const bpmNow = () => Math.max(60, A.bpm || 120);
    if (L.pool.length > 1) {
      if (!R.colorSwitch) R.colorSwitch = pos + Math.trunc(beatsN(L.colorDuration) * 60000 / bpmNow());
      if (pos >= R.colorSwitch) {
        const ci = L.pool.indexOf(L.cur);
        L.cur = L.pool[(ci + 1) % L.pool.length];
        R.colorSwitch = pos + Math.trunc(beatsN(L.colorDuration) * 60000 / bpmNow());
      }
    } else R.colorSwitch = null;

    // 2. Couleurs restreintes aux tuiles choisies (au plus 4) : l'INDICE de la
    // teinte IA donne l'indice dans le pool (répartit les couleurs choisies).
    const pal = L.pool.slice(0, 4).map((k) => Engine.hexToRgb(tileByKey[k][1]));
    if (pal.length) {
      const mapPal = (c) => {
        if (pal.length === 1) return pal[0];
        let bi = 0, bd = Infinity;
        AI.palette.forEach((pc, k) => { const d = (pc[0] - c[0]) ** 2 + (pc[1] - c[1]) ** 2 + (pc[2] - c[2]) ** 2; if (d < bd) { bd = d; bi = k; } });
        return pal[bi % pal.length];
      };
      P.forEach((q, i) => { if (!fxm(i) && q.level > 0) { const m = mapPal(q.base); q.base = m; q.color = m.map((c) => Math.trunc(c * q.level / 100)); } });
    }
    const palAll = pal.length ? pal : AI.palette;
    const smsFast = Math.trunc(38 - nerv * 13), smsMed = Math.trunc(55 - nerv * 20);
    const on = (ms) => Math.trunc(pos / ms) % 2 === 0;

    // 3. Sections : drop (effet choisi) et montée.
    if (section === "drop") {
      if (R.sec.last !== "drop") R.sec.dropStart = now;
      const dp = Math.min(1, (now - R.sec.dropStart) / 1.2);
      if (L.drop === "flash_blanc") {
        if (dp < 0.30) { const punch = 1 - dp / 0.30; P.forEach((q, i) => { if (!fxm(i) && Math.trunc(100 * punch) > q.level) set(i, W, 100 * punch); }); }
        if (!on(smsFast)) P.forEach((q, i) => { const g = groupOf(i); if (g === "lat" || g === "contre") black(i); });
      } else if (L.drop === "color_explosion") {
        P.forEach((q, i) => { if (fxm(i)) return; if (on(smsFast)) set(i, palAll[i % palAll.length], 100); else black(i); });
      } else if (L.drop === "blackout_punch") {
        if (dp < 0.12) P.forEach((q, i) => { if (!fxm(i)) black(i); });
        else {
          const punch = Math.max(0, 1 - (dp - 0.12) / 0.35);
          P.forEach((q, i) => { if (!fxm(i)) set(i, W, 100 * punch); });
          if (dp > 0.20 && !on(smsMed)) P.forEach((q, i) => { if (!fxm(i)) black(i); });
        }
      } else if (L.drop === "stroboscope") {
        const ms = Math.trunc(45 - nerv * 20);
        P.forEach((q, i) => { if (fxm(i)) return; if (on(ms)) set(i, W, 100); else black(i); });
      } else if (L.drop === "strobe_sync") {
        const c = pal[0] || W, ms = Math.trunc(40 - nerv * 16);
        P.forEach((q, i) => { if (fxm(i)) return; if (on(ms)) set(i, c, 100); else black(i); });
      }
      R.sec.last = "drop";
    } else if (section === "build") {
      const bp = Math.min(1, energy * 1.4), hz = 2.5 + bp * 10;
      const pm = Math.sin(pos / 1000 * hz * 2 * Math.PI) * 0.5 + 0.5;
      P.forEach((q, i) => {
        if (fxm(i)) return;
        const g = groupOf(i), b = q.base;
        if (g === "contre") set(i, [Math.min(255, Math.trunc(b[0] + bp * (255 - b[0]) * 0.7)), Math.trunc(b[1] * (1 - bp * 0.5)), Math.trunc(b[2] * (1 - bp * 0.6))],
          Math.min(100, Math.trunc(q.level * (1 + bp * 0.35) * (0.35 + 0.65 * pm))));
        else if (g === "face") set(i, b, Math.min(100, Math.trunc(q.level * (1 + bp * 0.2))));
      });
      R.sec.last = "build";
    } else R.sec.last = section;

    // 4. Kick → contres, caisse claire → face.
    const bump = (g, add) => P.forEach((q, i) => {
      if (groupOf(i) !== g || fxm(i)) return;
      q.level = Math.min(100, q.level + add);
      if (q.level > 0) q.color = q.base.map((c) => Math.trunc(c * q.level / 100));
    });
    if ((R.tr.contreUntil || 0) > pos) bump("contre", 30);
    if ((R.tr.faceUntil || 0) > pos) bump("face", 20);

    // 5. Flash « intelligent » (drop / intense), teinté de la couleur en cours.
    const fc = Engine.hexToRgb(curTile()[1]);
    if (R.bs.smartFlashUntil > pos) {
      const punch = Math.max(0, 1 - (pos - (R.bs.smartFlashUntil - 140)) / 140);
      P.forEach((q, i) => {
        if (fxm(i)) return;
        const fl = Math.trunc(100 * punch);
        if (fl > q.level) { q.level = fl; q.color = fc.map((c) => Math.min(255, Math.trunc(c * punch * 1.25))); }
      });
    }

    // 6. Lyres : rotation continue dont la vitesse suit la musique.
    const lyres = projectors.map((p, i) => i).filter((i) => Engine.isLyre(projectors[i]));
    if (lyres.length) {
      if (!R.lyre) R.lyre = { e: energy, phase: 0, speed: 0.08, last: pos, chopUntil: 0, beatIdx: -1 };
      const ly = R.lyre, ea = section === "quiet" ? 0.07 : 0.12;
      ly.e = ea * energy + (1 - ea) * ly.e;
      const e = ly.e;
      const dt = Math.max(0, Math.min(0.12, (pos - ly.last) / 1000));
      ly.last = pos;
      const ms = L.movSpeed / 100;
      const tgtSec = { quiet: 0.04 + e * 0.02, verse: 0.12 + e * 0.08, build: 0.22 + e * 0.10, high: 0.30 + e * 0.12, drop: 0.50 + e * 0.22 }[section] ?? 0.12 + e * 0.08;
      const tgt = (tgtSec * (1 - ms * 0.7) + ms * 0.60) * ms ** 2;
      if (ms < 0.02) ly.speed = 0; else ly.speed += (section !== "quiet" ? 0.07 : 0.02) * (tgt - ly.speed);
      ly.phase = (ly.phase + dt * ly.speed * 2 * Math.PI) % (2 * Math.PI);
      if (AI.lastBeatIdx >= 0 && AI.lastBeatIdx !== ly.beatIdx) {
        ly.beatIdx = AI.lastBeatIdx;
        if (e > 0.30 && section !== "quiet") ly.chopUntil = pos + 55;
      }
      if ((R.tr.lyreChopUntil || 0) > pos) ly.chopUntil = Math.max(ly.chopUntil, R.tr.lyreChopUntil);
      const [, c1, c2] = curTile();
      const lyreColor = Engine.hexToRgb(c1);
      const lyreLevel = pos < ly.chopUntil ? 0 : section === "quiet" ? Math.trunc(18 + e * 14) : section === "drop" ? Math.trunc(65 + e * 35)
        : section === "build" ? Math.trunc(55 + e * 35) : Math.trunc(45 + e * 45);
      // Plusieurs mouvements choisis : on passe au suivant tous les N temps.
      if (L.moves.length > 1) {
        if (!R.movSwitch) R.movSwitch = pos + Math.trunc(beatsN(L.movDuration) * 60000 / bpmNow());
        if (pos >= R.movSwitch) {
          L.mov = L.moves[(L.moves.indexOf(L.mov) + 1) % L.moves.length];
          R.movSwitch = pos + Math.trunc(beatsN(L.movDuration) * 60000 / bpmNow());
        }
      } else { R.movSwitch = null; L.mov = L.moves[0] || "cercle"; }
      const msz = L.movSize / 100, ampPan = Math.trunc(2000 + msz * 22000), ampTilt = Math.trunc(1500 + msz * 14000);
      lyres.forEach((i, k) => {
        const p = projectors[i], ph = ly.phase + k * (2 * Math.PI / lyres.length);
        let pv, tv;
        switch (L.mov) {
          case "cercle": pv = Math.cos(ph); tv = Math.sin(ph); break;
          case "huit": pv = Math.sin(ph); tv = Math.sin(2 * ph) * 0.5; break;
          case "vague": pv = Math.sin(ph); tv = 0; break;
          case "diagonale": pv = tv = Math.sin(ph); break;
          case "bounce": pv = Math.abs(Math.sin(ph * 0.5)) * 2 - 1; tv = 0; break;
          case "spirale": { const r = (ph % (2 * Math.PI)) / (2 * Math.PI); pv = r * Math.cos(ph * 3); tv = r * Math.sin(ph * 3); break; }
          case "random": { const s = Math.trunc(ph / (0.5 * Math.PI)); pv = (((s * 1664525 + 1013904223) & 0xffff) / 32767.5) - 1; tv = (((s * 22695477 + 1) & 0xffff) / 32767.5) - 1; break; }
          default: pv = Math.cos(ph); tv = Math.sin(ph * 1.618);
        }
        states[i].pan = inLimits(p, "pan", pv, ampPan);
        states[i].tilt = inLimits(p, "tilt", tv, ampTilt);
        if (!BASE_COLOR_GROUPS.has(groupOf(i))) {
          const col = c2 && k % 2 === 1 ? Engine.hexToRgb(c2) : lyreColor;
          set(i, col, lyreLevel);
        }
      });
    }

    // 7. Strobes : intelligent (drop / intense) et blanc continu du drop.
    if (L.strob !== "none" && R.bs.smartStrobeUntil > pos) {
      let sms = Math.max(22, Math.trunc(45 - nerv * 12));
      if (L.strob === "fast") sms = Math.max(16, Math.trunc(sms * 0.7));
      if (!on(sms)) P.forEach((q, i) => { if (!fxm(i)) black(i); });
    }
    if (section !== "drop") R.sfx.dropStrobe = false;
    if (R.sfx.dropStrobe && L.strob === "fast") {
      const sms = Math.max(25, Math.trunc(55 - nerv * 25));
      P.forEach((q, i) => { if (fxm(i)) return; if (on(sms)) set(i, W, 100); else black(i); });
    }

    // 8. Intensité générale, puis fondu au silence.
    const fade = R.silenceStart ? 1 - Math.min(1, (now - R.silenceStart) / 2) : 1;
    const k = (L.master / 100) * fade;
    P.forEach((q, i) => {
      if (fxm(i)) return;
      if (k < 1) { q.level = Math.trunc(q.level * k); q.color = q.color.map((c) => Math.trunc(c * k)); }
      const s = states[i];
      s.color = "#" + q.base.map((c) => Math.max(0, Math.min(255, c | 0)).toString(16).padStart(2, "0")).join("");
      s.level = q.level; s.fx = q.color.slice(); s.muted = false; s.strobe = 0;
      Engine.updateColorWheel(s, q.base);
    });
  }
  C.setLiveHook({ active: () => A.running, apply });

  // ── Onglet LIVE ─────────────────────────────────────────────────────────────
  const root = document.createElement("div");
  root.id = "solo-live";
  root.className = "page";
  root.innerHTML = `
    <div class="lv-top">
      <button type="button" class="lv-go"><i></i><span>ÉCOUTER LA MUSIQUE</span></button>
      <div class="lv-meter"><div class="lv-vu"><b></b></div><div class="lv-hits"><i data-h="kick">KICK</i><i data-h="snare">CAISSE</i><i data-h="hihat">CHARLEY</i></div></div>
      <div class="lv-bpm"><b>—</b><small>BPM</small></div>
      <div class="lv-sec"><i></i><b>—</b></div>
    </div>
    <div class="lv-body">
      <main class="lv-main">
        <section><div class="lv-ttl">COULEURS <small>elles tournent au rythme de la musique</small></div><div class="lv-tiles"></div>
          <div class="lv-row"><span>CHANGER TOUS LES</span><input type="range" min="0" max="100" data-k="colorDuration"><b></b></div></section>
        <section class="lv-mv"><div class="lv-ttl">MOUVEMENT DES LYRES <small>plusieurs choisis = ils s'enchaînent</small></div><div class="lv-chips lv-moves"></div>
          <div class="lv-row"><span>VITESSE</span><input type="range" min="0" max="100" data-k="movSpeed"><b></b></div>
          <div class="lv-row"><span>TAILLE</span><input type="range" min="0" max="100" data-k="movSize"><b></b></div></section>
        <section><div class="lv-ttl">RÉACTION</div>
          <div class="lv-row"><span>NERVOSITÉ</span><input type="range" min="0" max="100" data-k="nerv"><b></b></div>
          <div class="lv-row"><span>SENSIBILITÉ</span><input type="range" min="0" max="100" data-k="sens"><b></b></div>
          <div class="lv-sub">STROBE</div><div class="lv-chips lv-strob"></div>
          <div class="lv-sub">AU DROP</div><div class="lv-chips lv-drop"></div></section>
      </main>
      <aside class="lv-side">
        <div class="lv-fcard"><div class="lv-flbl">INTENSITÉ</div><div class="lv-fader"><div class="lv-fill"></div><div class="lv-thumb"></div></div><div class="lv-fval"></div></div>
      </aside>
    </div>`;
  document.getElementById("app").appendChild(root);
  const $ = (q) => root.querySelector(q);
  const save = () => C.savePlay();

  function paintTiles() {
    const box = $(".lv-tiles");
    box.innerHTML = "";
    TILES.forEach(([k, c1, c2, name]) => {
      const b = document.createElement("button");
      b.type = "button"; b.title = name;
      b.className = (L.pool.includes(k) ? "on" : "") + (A.running && k === L.cur ? " cur" : "");
      b.style.background = c2 ? "linear-gradient(135deg," + c1 + " 50%," + c2 + " 50%)" : c1;
      b.innerHTML = "<span></span>"; b.querySelector("span").textContent = name;
      b.addEventListener("click", () => {
        if (L.pool.includes(k)) { if (L.pool.length === 1) { Solo.toast("Gardez au moins une couleur"); return; } L.pool = L.pool.filter((x) => x !== k); }
        else L.pool = TILES.map((t) => t[0]).filter((x) => x === k || L.pool.includes(x));
        if (!L.pool.includes(L.cur)) L.cur = L.pool[0];
        save(); paintTiles();
      });
      box.appendChild(b);
    });
  }
  function chips(sel, items, isOn, pick) {
    const box = $(sel);
    box.innerHTML = "";
    items.forEach(([k, label]) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label; b.classList.toggle("on", isOn(k));
      b.addEventListener("click", () => { pick(k); save(); paintAll(); });
      box.appendChild(b);
    });
  }
  function paintMoves() {
    chips(".lv-moves", MOVES, (k) => L.moves.includes(k), (k) => {
      if (L.moves.includes(k)) { if (L.moves.length > 1) L.moves = L.moves.filter((x) => x !== k); }
      else L.moves = MOVES.map((m) => m[0]).filter((x) => x === k || L.moves.includes(x));
      if (!L.moves.includes(L.mov)) L.mov = L.moves[0];
    });
    root.querySelectorAll(".lv-moves button").forEach((b, i) => b.classList.toggle("cur", A.running && MOVES[i][0] === L.mov && L.moves.length > 1));
  }
  function paintAll() {
    paintTiles(); paintMoves();
    chips(".lv-strob", [["fast", "Rapide"], ["slow", "Lent"], ["none", "Aucun"]], (k) => L.strob === k, (k) => { L.strob = k; });
    chips(".lv-drop", DROPS, (k) => L.drop === k, (k) => { L.drop = k; });
    root.querySelectorAll("input[data-k]").forEach((inp) => {
      inp.value = L[inp.dataset.k];
      inp.nextElementSibling.textContent = inp.dataset.k === "colorDuration"
        ? Math.max(2, Math.trunc(2 + (L.colorDuration / 100) * 30)) + " temps" : L[inp.dataset.k];
    });
    $(".lv-mv").hidden = !projectors.some(Engine.isLyre);
    paintFader(); paintGo();
  }
  root.querySelectorAll("input[data-k]").forEach((inp) => inp.addEventListener("input", () => {
    L[inp.dataset.k] = +inp.value; save();
    inp.nextElementSibling.textContent = inp.dataset.k === "colorDuration"
      ? Math.max(2, Math.trunc(2 + (L.colorDuration / 100) * 30)) + " temps" : inp.value;
  }));

  // Intensité générale (fader dessiné à la main : vieux WebView).
  function paintFader() {
    const v = L.master;
    $(".lv-fill").style.height = v + "%";
    $(".lv-thumb").style.bottom = "calc(" + v + "% - " + (v / 100) * 22 + "px)";
    $(".lv-fval").textContent = v + "%";
  }
  const fader = $(".lv-fader");
  const setFader = (e) => { const r = fader.getBoundingClientRect(); L.master = Math.round(Math.max(0, Math.min(1, (r.bottom - e.clientY) / r.height)) * 100); paintFader(); save(); };
  fader.addEventListener("pointerdown", (e) => { fader.setPointerCapture(e.pointerId); setFader(e); });
  fader.addEventListener("pointermove", (e) => { if (fader.hasPointerCapture(e.pointerId)) setFader(e); });
  fader.addEventListener("dblclick", () => { L.master = 100; paintFader(); save(); });

  // Démarrer / arrêter l'écoute.
  const tab = document.createElement("button");
  tab.className = "tab-btn"; tab.dataset.tab = "solo-live"; tab.textContent = "LIVE";
  function paintGo() {
    $(".lv-go").classList.toggle("on", A.running);
    $(".lv-go span").textContent = A.running ? "ARRÊTER L'ÉCOUTE" : "ÉCOUTER LA MUSIQUE";
    tab.textContent = A.running ? "LIVE ●" : "LIVE";
  }
  $(".lv-go").addEventListener("click", async () => {
    if (A.running) stopAudio(); else if (await startAudio()) Solo.toast("LIVE : la lumière suit la musique (l'AKAI ne pilote plus)", 2600);
    paintAll();
  });

  // Indicateurs : VU, BPM, section, coups ; tuile et mouvement en cours.
  let beatT = 0, lastCur = null, lastMov = null;
  function beatDot() { beatT = performance.now(); }
  setInterval(() => {
    if (!root.classList.contains("active")) return;
    $(".lv-vu b").style.width = (A.running ? A.vu : 0) + "%";
    $(".lv-bpm b").textContent = A.running && A.bpm ? Math.round(A.bpm) : "—";
    const sec = $(".lv-sec");
    sec.className = "lv-sec s-" + (A.running ? A.section : "off");
    sec.querySelector("b").textContent = A.running ? SECTIONS[A.section] || A.section : "—";
    sec.querySelector("i").classList.toggle("beat", A.running && performance.now() - beatT < 120);
    const t = nowS();
    root.querySelectorAll(".lv-hits i").forEach((el) => el.classList.toggle("on", A.running && t - A.lastTr[el.dataset.h] < 0.15));
    if (L.cur !== lastCur || L.mov !== lastMov) { lastCur = L.cur; lastMov = L.mov; paintTiles(); paintMoves(); }
  }, 50);

  // Onglet : même mécanique que ceux de la page (classe .active).
  document.getElementById("tabs").appendChild(tab);
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".page").forEach((pg) => pg.classList.remove("active"));
    tab.classList.add("active"); root.classList.add("active");
    paintAll();
  });
  const visible = () => root.classList.contains("active");
  window.MystrowLive = { visible, render: paintAll, running: () => A.running, stop: () => { stopAudio(); paintAll(); } };

  const css = document.createElement("style");
  css.textContent = `
#solo-live{color:#f2efe6;gap:12px;font-family:var(--f-label);overflow:hidden}
#solo-live.active{display:flex;flex-direction:column}
#solo-live button{font-family:var(--f-label);cursor:pointer;touch-action:manipulation;-webkit-user-select:none;user-select:none;color:#f2efe6}
#solo-live [hidden]{display:none!important}
.lv-top{display:flex;align-items:stretch;gap:12px;flex-shrink:0;height:clamp(64px,10vh,84px)}
.lv-go{display:flex;align-items:center;gap:12px;padding:0 22px;border-radius:16px;border:0;background:#E2CE16;color:#0c0b00!important;
  font-weight:700;font-size:clamp(17px,2.4vh,21px);letter-spacing:1.5px;white-space:nowrap}
.lv-go i{width:16px;height:16px;border-radius:50%;background:#0c0b00}
.lv-go.on{background:#2a0a0a;border:2px solid #ef4444;color:#fca5a5!important}.lv-go.on i{background:#ef4444;box-shadow:0 0 12px #ef4444;border-radius:3px}
.lv-meter{flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;gap:8px;padding:10px 14px;border-radius:16px;background:#0f0e0b;border:1px solid #1f1d17}
.lv-vu{height:14px;border-radius:7px;background:#1b1a15;overflow:hidden}.lv-vu b{display:block;height:100%;width:0;background:linear-gradient(90deg,#22c55e,#E2CE16 70%,#ef4444);transition:width .05s}
.lv-hits{display:flex;gap:8px}.lv-hits i{font-style:normal;font-weight:700;font-size:12px;letter-spacing:1.5px;padding:2px 8px;border-radius:6px;background:#1b1a15;color:#6b675d}
.lv-hits i.on{background:#E2CE16;color:#0c0b00}
.lv-bpm{display:flex;flex-direction:column;align-items:center;justify-content:center;min-width:96px;border-radius:16px;background:#0f0e0b;border:1px solid #1f1d17}
.lv-bpm b{font-family:var(--f-title);font-weight:400;font-size:clamp(30px,4.6vh,40px);line-height:1;color:#E2CE16}.lv-bpm small{font-size:12px;letter-spacing:2px;color:#8a8577}
.lv-sec{display:flex;align-items:center;gap:10px;min-width:150px;padding:0 16px;border-radius:16px;background:#0f0e0b;border:1px solid #1f1d17}
.lv-sec i{width:16px;height:16px;border-radius:50%;background:#2a2820;transition:background .05s}.lv-sec i.beat{background:#fff;box-shadow:0 0 14px #fff}
.lv-sec b{font-family:var(--f-title);font-weight:400;font-size:clamp(24px,3.6vh,32px);letter-spacing:1px}
.lv-sec.s-drop{border-color:#ef4444}.lv-sec.s-drop b{color:#f87171}.lv-sec.s-build b{color:#fb923c}.lv-sec.s-high b{color:#E2CE16}.lv-sec.s-quiet b{color:#8a8577}
.lv-body{flex:1;min-height:0;display:flex;gap:14px}
.lv-main{flex:1;min-width:0;overflow-y:auto;display:flex;flex-direction:column;gap:12px;padding-right:4px}
.lv-main section{display:flex;flex-direction:column;gap:8px;padding:12px 14px;border-radius:16px;background:#0f0e0b;border:1px solid #1f1d17}
.lv-ttl{font-weight:700;font-size:13px;letter-spacing:2.5px;color:#E2CE16}.lv-ttl small{margin-left:10px;font-size:13px;letter-spacing:.3px;font-weight:500;color:#8a8577}
.lv-sub{margin-top:4px;font-weight:700;font-size:12px;letter-spacing:2px;color:#8a8577}
.lv-tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(84px,1fr));gap:8px}
.lv-tiles button{position:relative;height:58px;border-radius:12px;border:0;opacity:.35;display:flex;align-items:flex-end;justify-content:center;padding:0 2px 4px}
.lv-tiles button span{font-weight:700;font-size:12px;letter-spacing:.5px;color:#fff;text-shadow:0 1px 3px #000,0 0 4px #000}
.lv-tiles button.on{opacity:1;box-shadow:inset 0 0 0 3px #080807,0 0 0 2px #E2CE16}
.lv-tiles button.cur{box-shadow:inset 0 0 0 3px #080807,0 0 0 2px #E2CE16,0 0 18px rgba(255,255,255,.55)}
.lv-chips{display:flex;flex-wrap:wrap;gap:6px}
.lv-chips button{min-height:42px;padding:0 16px;border-radius:21px;border:1px solid #2a2820;background:#13120e;font-weight:700;font-size:15px}
.lv-chips button.on{background:#E2CE16;border-color:#E2CE16;color:#0c0b00!important}
.lv-chips button.cur{box-shadow:0 0 0 3px rgba(255,255,255,.6)}
.lv-row{display:grid;grid-template-columns:150px 1fr 74px;align-items:center;gap:10px}
.lv-row span{font-weight:700;font-size:14px;letter-spacing:1.5px;color:#cfcabd}.lv-row input{width:100%;accent-color:#E2CE16;height:30px}
.lv-row b{font-family:var(--f-title);font-weight:400;font-size:20px;color:#E2CE16;text-align:right}
.lv-side{width:clamp(170px,19vw,230px);flex-shrink:0;display:flex;flex-direction:column;gap:12px;min-height:0}
.lv-fcard{flex:1;min-height:0;display:flex;flex-direction:column;align-items:center;gap:8px;padding:12px 8px;border-radius:16px;background:#0f0e0b;border:1px solid #1f1d17}
.lv-flbl{font-weight:700;font-size:14px;letter-spacing:2px;color:#cfcabd}
.lv-fader{position:relative;flex:1;min-height:80px;width:52px;border-radius:12px;background:#1b1a15;touch-action:none;cursor:pointer}
.lv-fill{position:absolute;left:0;right:0;bottom:0;border-radius:12px;background:linear-gradient(0deg,rgba(226,206,22,.35),rgba(226,206,22,.75))}
.lv-thumb{position:absolute;left:-6px;right:-6px;height:22px;border-radius:8px;background:#f2efe6;box-shadow:0 2px 8px rgba(0,0,0,.6)}
.lv-fval{font-family:var(--f-title);font-size:clamp(24px,4vh,32px);line-height:1;color:#E2CE16}
@media (orientation:portrait){
  .lv-top{flex-wrap:wrap;height:auto}.lv-go{flex:1 1 100%;height:64px;justify-content:center}.lv-meter{flex:1 1 40%;height:64px}.lv-bpm,.lv-sec{height:64px}
  .lv-body{flex-direction:column}.lv-side{width:auto;flex-direction:row;height:clamp(170px,20vh,230px)}
  .lv-side>*{flex:1;height:auto!important}.lv-row{grid-template-columns:110px 1fr 64px}
}`;
  document.head.appendChild(css);
})();
