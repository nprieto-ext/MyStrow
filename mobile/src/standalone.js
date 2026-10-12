// Mode autonome de l'app : la tablette pilote les projecteurs SANS PC.
//
// Chargé à la fin de remote.html (voir scripts/build-www.mjs), actif seulement
// avec ?solo=1. Même contrat que demo.js : il remplace le PC — les actions de
// l'interface (window.MYSTROW_SEND) modifient l'état, renvoyé à la page sous
// forme de messages identiques au flux SSE (_handleMsg). Mais ici l'état est
// réel : engine.js le traduit en DMX, envoyé par le module natif MystrowDmx
// (interface USB-DMX ou node Art-Net).
//
// Grille AKAI = 20 PAGES de 8 colonnes, comme le PC (◀ ▶). Chaque colonne a un
// type, réglable (appui long sur son nom sous le fader) :
//   A…H    : pads = couleur du groupe, fader = niveau du groupe ;
//   MEM n  : 8 mémoires, fader = niveau de la mémoire ; plusieurs colonnes MEM
//            se mélangent (couleurs additives, comme _recompute_memory_mix) ;
//   FX n   : 8 effets, fader = amplitude de l'effet de la colonne ;
//   POS n  : 8 positions de lyres (REC puis pad = enregistrer).
// Une page est une SURFACE DE CONTRÔLE : en changer ne touche jamais à la
// lumière (cf. project_bank_pages côté PC).
// Entre les pads couleur et les mémoires, le DERNIER GESTE gagne, projecteur
// par projecteur (le PC : la dernière écriture sur le projecteur).
// Effets : un seul à la fois (mode exclusif du PC) ou superposés (réglage
// « Superposition d'effets »). Boutons de droite : appui long = choisir l'effet,
// le modifier, en créer un (éditeur : fxeditor.js). Fader VIT = vitesse.
// Lyres : visée par le pad POSITION de l'onglet SCÈNE, centre des effets de
// mouvement. Playlist et cartouches : media.js, branché par window.MystrowSolo.
(function () {
  "use strict";
  if (!window.MYSTROW_SOLO) return;

  const Engine = window.MystrowEngine;
  const Library = window.MystrowEffects || { effects: [], defaults: [] };
  const Dmx = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.MystrowDmx;
  const COLORS = ["#ffffff", "#ff0000", "#ff8800", "#ffdd00", "#00ff00", "#00dddd", "#0000ff", "#ff00ff"];
  const GROUPS = ["A", "B", "C", "D", "E", "F", "G", "H"];
  const SPEED = 8;                                  // 9e fader « VIT »
  const N_PAGES = 20;                               // _N_BANK_PAGES du PC
  const MEM_COL_MAX = 99, FX_COL_MAX = 8, POS_COL_MAX = 5;   // _MEM_COL_MAX… du PC
  const MOVE_ATTRS = new Set(["Pan", "Tilt", "Pan/Tilt"]);   // couches de mouvement (TAILLE)

  // Sans licence payante (account.js) : 10 minutes de DMX par lancement de
  // l'app, puis la sortie passe au noir. Le départ est gardé pour la session
  // (sessionStorage) : aller au patch et revenir ne redonne pas 10 minutes,
  // relancer l'app, oui (choix du 12/10/2026).
  const Account = window.MystrowAccount || null;
  const DEMO_MS = 10 * 60 * 1000;
  let licensed = !!(Account && Account.status().paid);
  let demoStart = Date.now();
  try {
    const v = +sessionStorage.getItem("mystrow.demo.start");
    if (v && v <= Date.now()) demoStart = v; else sessionStorage.setItem("mystrow.demo.start", String(demoStart));
  } catch (e) {}
  const demoLeft = () => (licensed ? Infinity : DEMO_MS - (Date.now() - demoStart));

  // ── Show (patch) et état du jeu, gardés sur la tablette ─────────────────────
  function load(key, def) {
    try { const v = JSON.parse(localStorage.getItem(key) || "null"); return v || def; } catch (e) { return def; }
  }
  function save(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch (e) {} }

  // Effets : bibliothèque du PC (effects.js) + effets créés sur la tablette.
  let customFx = load("mystrow.solo.fx", []);
  if (!Array.isArray(customFx)) customFx = [];
  const builtinByName = Object.fromEntries(Library.effects.map((e) => [e.name, e]));
  const effectByName = {};                          // vue fusionnée, perso d'abord
  function indexEffects() {
    Object.keys(effectByName).forEach((k) => delete effectByName[k]);
    Object.assign(effectByName, builtinByName);
    customFx.forEach((e) => { effectByName[e.name] = e; });
  }
  indexEffects();
  const getEffect = (name) => (name && effectByName[name]) || null;

  const show = load("mystrow.solo.show", { fixtures: [], output: { transport: "usb" } });
  const play = Object.assign({
    active: {},                                     // groupe (0-7) → rangée de couleur (ou absent)
    faders: [100, 100, 100, 100, 100, 100, 100, 100, 50],   // niveaux des groupes A-H + VIT
    groupTs: {},                                    // groupe → heure du dernier geste
    effect: null,                                   // nom de l'effet affiché (déduit de fxStack)
    buttons: Library.defaults.slice(0, 8),          // effet de chaque bouton de droite
    fxStack: [],                                    // effets lancés : {src: btn|pad|name, row, f, name}
    superpose: false,                               // superposition d'effets (sinon exclusif)
    pages: null,                                    // 20 pages × 8 colonnes
    pageIdx: 0,
    memories: {},                                   // "rangée_colonneMEM" → mémoire
    memRows: {},                                    // colonne MEM → rangée allumée
    memLevels: {},                                  // colonne MEM → niveau (fader), 100 par défaut
    memTs: 0,                                       // heure du dernier geste sur les mémoires
    fxPads: {},                                     // colonne FX → [8 noms d'effet]
    fxAmp: {},                                      // colonne FX → amplitude (fader), 100 par défaut
    posPresets: {},                                 // colonne POS → [8 × {name, pos: {n°: [pan, tilt]}}]
    posActive: {},                                  // colonne POS → rangée rappelée
    positions: {},                                  // n° de projecteur → [pan, tilt]
    gobos: {},                                      // n° de projecteur → valeur DMX du gobo
    symPan: false,                                  // pad POSITION : miroir du pan
    symTilt: false,                                 // pad POSITION : miroir du tilt
    moveSize: 100,                                  // TAILLE des effets de mouvement, en %
    qfx: {},                                        // n° de projecteur → effet rapide (SCÈNE)
    qe: { speed: 50, amp: 50, phase: 0 },           // curseurs des effets rapides (50 = naturel)
  }, load("mystrow.solo.play", {}));
  delete play.strobe;                               // v1 : effet 1 = strobe matériel
  if (play.sym) { play.symPan = true; } delete play.sym;   // SYM unique d'avant le 24/09 (pan)
  play.qfx = {};                                    // effets rapides : jamais relancés seuls au démarrage
  let recArmed = false;
  const savePlay = () => save("mystrow.solo.play", play);

  // Projecteurs du plan de feu : un rang par groupe, dans l'ordre du patch.
  const projectors = show.fixtures.map((f, i) => ({ ...f, override: null, pos: play.positions[i] || [32768, 32768],
                                                    gobo: play.gobos[i] || 0, color_wheel: 0 }));
  // Roue et gobo dans le panneau SCÈNE (mêmes champs que le PC, _proj_gobo_wheel_meta).
  const GENERIC_GOBOS = [0, 1, 2, 3, 4, 5, 6, 7].map((i) => ({ dmx: i * 32, label: i ? "Gobo " + i : "Ouvert" }));
  function wheelMeta(p) {
    const prof = Engine.profileOf(p) || [];
    const hasWheel = prof.includes("ColorWheel") && !prof.includes("R");
    const hasGobo = prof.includes("Gobo1");
    return {
      has_wheel: hasWheel,
      wheel_slots: hasWheel ? ((p.color_wheel_slots || []).length ? p.color_wheel_slots : Engine.CW_DEFAULT_SLOTS) : [],
      has_gobo: hasGobo,
      gobo_slots: hasGobo ? ((p.gobo_wheel_slots || []).length
        ? p.gobo_wheel_slots.map((g) => ({ dmx: g.dmx, label: g.name || "DMX " + g.dmx })) : GENERIC_GOBOS) : [],
    };
  }
  const isWheelOnly = (p) => { const prof = Engine.profileOf(p) || []; return prof.includes("ColorWheel") && !prof.includes("R"); };
  const byGroup = {};
  projectors.forEach((p) => { (byGroup[p.group] = byGroup[p.group] || []).push(p); });
  const usedGroups = GROUPS.filter((g) => byGroup[g]);
  usedGroups.forEach((g, gi) => {
    const list = byGroup[g];
    list.forEach((p, i) => {
      p.x = (i + 1) / (list.length + 1);
      p.y = usedGroups.length === 1 ? 0.5 : 0.15 + (0.7 * gi) / (usedGroups.length - 1);
    });
  });
  const hasLyres = projectors.some(Engine.isLyre);

  // ── Pages de colonnes (AKAI_BANK_PRESETS du PC) ─────────────────────────────
  const gSlot = (g) => ({ type: "group", group: g });
  const mSlot = (m) => ({ type: "memory", mem_col: m });
  const PAGE_PRESETS = [
    ["A B C D E F G H", GROUPS.map(gSlot)],
    ["A B C D  |  MEM 1-4", [...GROUPS.slice(0, 4).map(gSlot), ...[0, 1, 2, 3].map(mSlot)]],
    ["A B C D E F  |  MEM 1-2", [...GROUPS.slice(0, 6).map(gSlot), mSlot(0), mSlot(1)]],
    ["MEM 1-4  |  A B C D", [...[0, 1, 2, 3].map(mSlot), ...GROUPS.slice(0, 4).map(gSlot)]],
    ["MEM 1-8", [0, 1, 2, 3, 4, 5, 6, 7].map(mSlot)],
    ["A B C D  |  FX 1  |  MEM 1-2  |  POS 1", [...GROUPS.slice(0, 4).map(gSlot), { type: "fx", fx_col: 0 },
      mSlot(0), mSlot(1), { type: "pos", pos_col: 0 }]],
  ];
  function validSlot(s) {
    if (!s || typeof s !== "object") return false;
    if (s.type === "group") return GROUPS.includes(s.group);
    if (s.type === "memory") return s.mem_col >= 0 && s.mem_col < MEM_COL_MAX;
    if (s.type === "fx") return s.fx_col >= 0 && s.fx_col < FX_COL_MAX;
    if (s.type === "pos") return s.pos_col >= 0 && s.pos_col < POS_COL_MAX;
    return s.type === "none";                       // colonne vide (PLAY, VIDÉO… du PC)
  }
  // Avant les pages (≤ 12/10/2026) : deux onglets COULEURS | MÉMOIRES. On garde
  // ces deux surfaces en pages 1 et 2, les mémoires restent où elles étaient.
  if (!Array.isArray(play.pages)) {
    play.pages = Array.from({ length: N_PAGES }, (_, i) => (i === 1 ? PAGE_PRESETS[4][1] : PAGE_PRESETS[0][1]).map((s) => ({ ...s })));
    play.pageIdx = play.page === 1 ? 1 : 0;
    if (typeof play.memActive === "string") {
      const [r, c] = play.memActive.split("_").map(Number);
      play.memRows[c] = r; play.memTs = 1;
    }
    if (play.effect) play.fxStack = play.buttons[play.effectRow] === play.effect
      ? [{ src: "btn", row: play.effectRow }] : [{ src: "name", name: play.effect }];
  }
  while (play.pages.length < N_PAGES) play.pages.push(PAGE_PRESETS[0][1].map((s) => ({ ...s })));
  play.pages = play.pages.slice(0, N_PAGES).map((pg) => GROUPS.map((g, c) => (validSlot((pg || [])[c]) ? pg[c] : gSlot(g))));
  play.pageIdx = Math.max(0, Math.min(N_PAGES - 1, play.pageIdx | 0));
  delete play.page; delete play.memActive; delete play.effectRow;
  if (!Array.isArray(play.fxStack)) play.fxStack = [];
  // FX 1 prérempli avec les effets des boutons : une colonne FX vide ne dirait rien.
  if (!play.fxPads[0]) play.fxPads[0] = Library.defaults.slice(0, 8);
  const curPage = () => play.pages[play.pageIdx];
  const slotAt = (col) => curPage()[col] || null;

  function slotLabel(s) {
    if (!s) return "—";
    if (s.type === "group") return s.group;          // comme le PC : la lettre seule
    if (s.type === "memory") return "M" + String(s.mem_col + 1).padStart(2, "0");
    if (s.type === "fx") return "FX " + (s.fx_col + 1);
    if (s.type === "pos") return "POS " + (s.pos_col + 1);
    return "—";                                     // colonne vide
  }

  // ── Mémoires : une photo du rig, projecteur par projecteur ──────────────────
  const memKey = (row, m) => row + "_" + m;
  const memLevel = (m) => play.memLevels[m] ?? 100;
  const scaledCacheMap = new WeakMap();
  // Copie FIGÉE de l'effet (avec la TAILLE du moment) : modifier ou effacer
  // l'effet ensuite ne change pas la mémoire.
  function freezeEffect(fx, size) {
    if (!fx) return null;
    const s = size ?? 100;
    return { name: fx.name, layers: JSON.parse(JSON.stringify(fx.layers || [])).map((ld) => (MOVE_ATTRS.has(ld.attribute) && s !== 100
      ? { ...ld, size: Math.min(400, (ld.size ?? 100) * s / 100) } : ld)) };
  }
  // Mémoires d'avant les pages : un look complet (couleurs des colonnes,
  // faders, réglages SCÈNE…). Converties une fois en photo par projecteur.
  function convertV1(m) {
    return {
      v: 2,
      projectors: projectors.map((p, i) => {
        const gi = GROUPS.indexOf(p.group), row = (m.active || {})[gi], o = (m.overrides || [])[i] || {};
        const has = o.color !== undefined || (row !== undefined && row !== null);
        const pos = (m.positions || [])[i];
        return { color: o.color ?? (has ? COLORS[row] : "#000000"),
                 level: o.muted ? 0 : has ? (o.level ?? (m.faders || [])[gi] ?? 100) : 0,
                 strobe: o.strobe || 0, pan: pos ? pos[0] : null, tilt: pos ? pos[1] : null,
                 gobo: (m.gobos || [])[i] || 0, cw: o.color_wheel };
      }),
      effect: freezeEffect(getEffect(m.effect), m.moveSize),
      qfx: { ...(m.qfx || {}) },
    };
  }
  Object.keys(play.memories).forEach((k) => { if (play.memories[k] && !play.memories[k].v) play.memories[k] = convertV1(play.memories[k]); });

  // Mémoires allumées dont le fader est levé, de la plus haute à la plus basse.
  function activeMems() {
    const out = [];
    Object.entries(play.memRows).forEach(([m, row]) => {
      const mem = play.memories[memKey(row, m)], L = memLevel(m);
      if (mem && L > 0) out.push({ m: +m, row, L, mem });
    });
    return out.sort((a, b) => b.L - a.L);
  }
  // Couche « mémoires » d'un projecteur (MainWindow._recompute_memory_mix) :
  // RGB = mélange additif pondéré par niveau × fader ; roue de couleur =
  // mémoire dominante ; strobe = la mémoire la plus haute.
  function memLayer(p, i, mems) {
    let r = 0, g = 0, b = 0, best = null, bestEff = -1, strobe = null, n = 0;
    mems.forEach(({ L, mem }) => {
      const st = (mem.projectors || [])[i];
      if (!st) return;
      n++;
      if (strobe === null && st.strobe) strobe = st.strobe;
      const eff = (st.level || 0) * L / 100;
      if (eff <= 0) return;
      if (eff > bestEff) { bestEff = eff; best = st; }
      const c = Engine.hexToRgb(st.color || "#000000");
      r += c[0] * eff / 100; g += c[1] * eff / 100; b += c[2] * eff / 100;
    });
    if (!n) return null;
    if (!best) return { color: "#000000", level: 0, strobe: strobe || 0 };
    // Une seule mémoire : sa couleur telle quelle (pas d'arrondi du mélange).
    if (n === 1 || isWheelOnly(p)) return { color: best.color, level: Math.round(bestEff), strobe: strobe || 0, cw: best.cw };
    const R = Math.min(255, r), G = Math.min(255, g), B = Math.min(255, b), mx = Math.max(R, G, B);
    if (mx <= 0) return { color: "#000000", level: 0, strobe: strobe || 0 };
    return { color: toHex([R * 255 / mx, G * 255 / mx, B * 255 / mx]), level: Math.round(mx / 255 * 100), strobe: strobe || 0 };
  }

  // ── État → projecteurs → DMX ────────────────────────────────────────────────
  // Réglage par projecteur (onglet SCÈNE) prioritaire, remis à zéro dès que la
  // couleur de son groupe change sur l'AKAI.
  function fixtureState(p, i, mems) {
    const gi = GROUPS.indexOf(p.group);
    const row = play.active[gi];
    const grp = row !== undefined && row !== null ? { color: COLORS[row], level: play.faders[gi] ?? 0, ts: play.groupTs[gi] || 0 } : null;
    const mem = mems.length ? memLayer(p, i, mems) : null;
    // Dernier geste gagne : pad couleur du groupe ou mémoire.
    const base = grp && mem ? (grp.ts > play.memTs ? grp : mem) : grp || mem;
    const o = p.override || {};
    const hasColor = o.color !== undefined || !!base;
    const color = o.color ?? (base ? base.color : "#000000");
    // Lyre à roue : un filtre choisi à la main (SCÈNE) ou enregistré dans la
    // mémoire prime ; sinon la roue suit la couleur (MainWindow._update_color_wheel),
    // et reste où elle est sur un noir.
    if (o.color_wheel !== undefined) p.color_wheel = o.color_wheel;
    else if (base === mem && mem && mem.cw !== undefined && mem.cw !== null) p.color_wheel = mem.cw;
    else Engine.updateColorWheel(p, Engine.hexToRgb(color));
    return {
      address: p.address, profile: p.profile, group: p.group, fixture_type: p.fixture_type,
      color_wheel_slots: p.color_wheel_slots, color_wheel: p.color_wheel || 0, gobo: p.gobo || 0,
      color,
      level: hasColor ? (o.level ?? (base ? base.level : 100)) : 0,
      muted: !!o.muted,
      strobe: o.strobe ?? (base === mem && mem ? mem.strobe : 0),
      pan: p.pos[0], tilt: p.pos[1], x: p.x,
    };
  }

  // Horloge de phase des effets, comme sur le PC : le temps avance au rythme
  // du fader VIT, sans saut quand on le bouge. Chaque effet lancé garde son
  // départ (t0) : en superposition, chacun repart de zéro à son lancement.
  const clock = { t: 0, last: null };
  function tickClock() {
    const now = performance.now() / 1000;
    const dt = clock.last === null ? 0 : Math.min(0.25, Math.max(0, now - clock.last));
    clock.last = now;
    clock.t += dt * Math.max(0.01, play.faders[SPEED] / 100);
  }

  // TAILLE : agrandit les couches de mouvement (Pan, Tilt, Pan/Tilt) de
  // l'effet joué. 100 % = l'effet tel que sur le PC ; plafond 400, celui de la
  // colonne AMP du PC pour les canaux de mouvement (course complète).
  function scaledEffect(fx) {
    if (!fx || play.moveSize === 100) return fx;
    const c = scaledCacheMap.get(fx);
    if (c && c.size === play.moveSize && c.n === fx.layers.length) return c.fx;
    const out = { ...fx, layers: fx.layers.map((ld) => (MOVE_ATTRS.has(ld.attribute)
      ? { ...ld, size: Math.min(400, (ld.size ?? 100) * play.moveSize / 100) } : ld)) };
    scaledCacheMap.set(fx, { size: play.moveSize, n: fx.layers.length, fx: out });
    return out;
  }

  // ── Effets lancés ───────────────────────────────────────────────────────────
  const sameEntry = (a, b) => a.src === b.src && a.row === b.row && a.f === b.f && a.name === b.name;
  function entryName(e) {
    if (e.src === "btn") return play.buttons[e.row];
    if (e.src === "pad") return (play.fxPads[e.f] || [])[e.row];
    return e.name;
  }
  // Effet porté par les mémoires : celui de la plus haute qui en porte un.
  const memFxState = { key: null, t0: 0 };
  function memoryEffect(mems) {
    const top = mems.find((x) => x.mem.effect && (x.mem.effect.layers || []).length);
    const key = top ? memKey(top.row, top.m) : null;
    if (key !== memFxState.key) { memFxState.key = key; memFxState.t0 = clock.t; }
    return top ? { fx: top.mem.effect, t0: memFxState.t0, amp: 1 } : null;
  }
  let preview = null, previewT0 = 0;                // éditeur d'effets : effet en cours d'édition
  function runningEffects(mems) {
    if (preview) return [{ fx: preview, t0: previewT0, amp: 1 }];
    const stack = play.fxStack.map((e) => ({ fx: scaledEffect(getEffect(entryName(e))), t0: e.t0 || 0,
      amp: e.src === "pad" ? (play.fxAmp[e.f] ?? 100) / 100 : 1 })).filter((x) => x.fx);
    const mf = memoryEffect(mems);
    if (!play.superpose) return stack.length ? [stack[stack.length - 1]] : mf ? [mf] : [];
    return [...(mf ? [mf] : []), ...stack];
  }

  // Effets rapides des mémoires allumées (la plus haute l'emporte), puis ceux
  // posés à la main dans SCÈNE.
  function effectiveQfx(mems) {
    const out = {};
    mems.slice().reverse().forEach(({ mem }) => Object.assign(out, mem.qfx || {}));
    return Object.assign(out, play.qfx);
  }

  const hold = { flash: false, black: false };    // FLASH / NOIR maintenus (onglet LIVE)
  let liveHook = null;                              // live.js : {active(), apply(states)}
  const frame = new Uint8Array(512);
  let lastSent = "", lastStates = [];
  function baseStates() {
    const mems = activeMems();
    return { mems, states: projectors.map((p, i) => fixtureState(p, i, mems)) };
  }
  function output() {
    const { mems, states } = baseStates();
    // LIVE (live.js) à l'écoute : la musique pilote tout, comme le PC en
    // « Musical IA » — l'AKAI, les mémoires et les effets attendent.
    if (liveHook && liveHook.active()) {
      liveHook.apply(states);
      return finishOutput(states);
    }
    const running = runningEffects(mems);
    // Amplitude : le fader de la colonne FX (exclusif) ; en superposition, la
    // plus forte des colonnes lancées (MainWindow._fx_col_amp). 0 = rien ne tourne.
    const amp = running.length ? Math.max(...running.map((x) => x.amp)) : 0;
    if (running.length && amp > 0) {
      tickClock();
      running.forEach((x) => Engine.effectFrame(x.fx, states, Math.max(0, clock.t - x.t0), Library.shapes));
      if (amp < 1) states.forEach((s) => { if (s.fx) s.fx = s.fx.map((v) => Math.trunc(v * amp)); });
    }
    applyQuick(states, effectiveQfx(mems));
    return finishOutput(states);
  }
  function finishOutput(states) {
    // FLASH / NOIR maintenus de l'onglet LIVE : par-dessus tout le reste.
    if (hold.black) states.forEach((s) => { s.level = 0; delete s.fx; });
    else if (hold.flash) states.forEach((s) => {
      s.color = "#ffffff"; s.level = 100; s.strobe = 0; delete s.fx;
      Engine.updateColorWheel(s, [255, 255, 255]);
    });
    Engine.render(states, frame);
    if (demoLeft() <= 0) frame.fill(0);             // démo terminée : noir sur le fil
    lastStates = states;
    const key = frame.join(",");
    if (key !== lastSent && Dmx) {
      lastSent = key;
      Dmx.setChannels({ start: 1, values: Array.from(frame) }).catch(() => {});
    }
    return states;
  }

  const toHex = (rgb) => "#" + rgb.map((v) => Math.max(0, Math.min(255, v | 0)).toString(16).padStart(2, "0")).join("");
  function projColors(states) {
    return states.map((s) => {
      // Couleur affichée sur la SCÈNE : celle de l'effet, luminosité comprise
      // (c'est ce qui fait voir passer un chenillard).
      let color = s.color, lit = !s.muted && s.level > 0 && s.color !== "#000000";
      if (s.fx) {
        color = toHex(s.fx);
        lit = !s.muted && Math.max(...s.fx) > 8;
      }
      return { color, base_color: s.color, level: s.level, muted: s.muted, lit, strobe: s.strobe,
               pan: s.pan, tilt: s.tilt, color_wheel: s.color_wheel, gobo: s.gobo };
    });
  }

  // ── Messages vers la page (mêmes formats que le flux SSE du PC) ────────────
  function emit(msg) {
    try { _conn.lastMsg = Date.now(); } catch (e) {}
    _handleMsg(msg);
  }
  function memColor(m) {
    const st = (m.projectors || []).find((s) => s && s.level > 0 && s.color && s.color !== "#000000");
    if (st) return st.color;
    return m.effect ? "#ffffff" : "#555555";
  }
  const isRunning = (entry) => play.fxStack.some((e) => sameEntry(e, entry));
  function padLook(row, col) {
    const s = slotAt(col);
    if (!s || s.type === "none") return { color: "#000000", bright: 0 };
    if (s.type === "group") {
      const gi = GROUPS.indexOf(s.group);
      return { color: COLORS[row], bright: play.active[gi] === row ? 100 : 20 };
    }
    if (s.type === "memory") {
      const m = play.memories[memKey(row, s.mem_col)];
      if (!m) return { color: "#000000", bright: 0 };
      return { color: memColor(m), bright: play.memRows[s.mem_col] === row ? 100 : 20 };
    }
    if (s.type === "fx") {
      const name = (play.fxPads[s.fx_col] || [])[row];
      if (!name) return { color: "#000000", bright: 0 };
      return { color: "#22dd44", bright: isRunning({ src: "pad", f: s.fx_col, row }) ? 100 : 20 };
    }
    const pr = (play.posPresets[s.pos_col] || [])[row];
    if (!pr) return { color: "#000000", bright: 0 };
    return { color: "#2266ff", bright: play.posActive[s.pos_col] === row ? 100 : 20 };
  }
  // Nom écrit dans les pads FX et POS (un pad vert ne dit pas quel effet il porte).
  function padText(row, col) {
    const s = slotAt(col);
    if (!s) return "";
    if (s.type === "fx") return (play.fxPads[s.fx_col] || [])[row] || "";
    if (s.type === "pos") { const pr = (play.posPresets[s.pos_col] || [])[row]; return pr ? pr.name : ""; }
    return "";
  }
  function padMsgs(col) {
    for (let r = 0; r < 8; r++) {
      emit({ type: "pad", row: r, col, ...padLook(r, col) });
      const el = padEls[r + "_" + col];
      if (el) {
        const t = padText(r, col); if (t) el.dataset.label = t; else delete el.dataset.label; el.title = t;
        // REC : les cases libres d'une colonne MEM / POS montrent un « + »
        // pointillé, celles où l'on ne peut rien enregistrer s'effacent.
        // (Avant le 12/10 toutes les cases libres s'allumaient en rouge.)
        const s = slotAt(col), memOrPos = s && (s.type === "memory" || s.type === "pos");
        const free = memOrPos && (s.type === "memory" ? !play.memories[memKey(r, s.mem_col)] : !(play.posPresets[s.pos_col] || [])[r]);
        el.classList.toggle("rec-free", recArmed && free);
        el.classList.toggle("rec-no", recArmed && !memOrPos);
      }
    }
  }
  function allPads() { for (let c = 0; c < 8; c++) padMsgs(c); }
  function effectMsgs() {
    play.effect = play.fxStack.length ? entryName(play.fxStack[play.fxStack.length - 1]) : null;
    for (let r = 0; r < 8; r++) emit({ type: "effect", row: r, active: isRunning({ src: "btn", row: r }) });
    labelEffects();
  }
  function faderValue(col) {
    const s = slotAt(col);
    if (!s) return 0;
    if (s.type === "group") return play.faders[GROUPS.indexOf(s.group)] ?? 0;
    if (s.type === "memory") return memLevel(s.mem_col);
    if (s.type === "fx") return play.fxAmp[s.fx_col] ?? 100;
    return 0;
  }
  function pageMsgs() {
    emit({ type: "bank_pages", count: N_PAGES, index: play.pageIdx });
    emit({ type: "layout", labels: curPage().map((s) => ({ label: slotLabel(s) })) });
    for (let c = 0; c < 8; c++) emit({ type: "fader", idx: c, value: faderValue(c) });
    allPads();
  }

  let lastScene = 0;
  function refresh(force) {
    const states = output();
    const now = performance.now();
    if (force || now - lastScene > 100) {            // la SCÈNE n'a pas besoin de 40 images/s
      lastScene = now;
      emit({ type: "proj_colors", data: projColors(states) });
      redrawPad();                                   // la visée qui bouge, dans le pad POSITION
    }
  }
  function setPos(p, i, pos) { p.pos = pos; play.positions[i] = pos; }

  // SYM (plan_de_feu.sym_apply du PC) : modèle RELATIF. Chaque lyre part de SA
  // visée et se déplace du même écart que le doigt ; pour celles de l'autre
  // côté de l'axe du plan, le pan (SYM PAN) et/ou le tilt (SYM TILT) partent à
  // l'envers. La lyre du point affiché suit le doigt.
  // Sans SYM : toutes les lyres sélectionnées vont au point touché.
  let symDrag = null;
  const clamp16 = (v) => Math.max(0, Math.min(65535, Math.trunc(v)));
  function panTilt(idxs, ev) {
    const target = [ev.pan !== undefined ? clamp16(ev.pan * 65535) : null,
                    ev.tilt !== undefined ? clamp16(ev.tilt * 65535) : null];
    const lyres = idxs.filter((i) => Engine.isLyre(projectors[i]));
    if (!(play.symPan || play.symTilt) || lyres.length < 2) {
      symDrag = null;
      idxs.forEach((i) => { const p = projectors[i]; setPos(p, i, [target[0] ?? p.pos[0], target[1] ?? p.pos[1]]); });
      return;
    }
    const now = performance.now(), key = lyres.join(",");
    if (!symDrag || symDrag.key !== key || now - symDrag.last > 400) {   // nouveau geste
      let sel = -1;
      try { sel = _selectedProjIdx; } catch (e) {}
      const ref = lyres.includes(sel) ? sel : lyres[0];
      symDrag = { key, ref, origins: Object.fromEntries(lyres.map((i) => [i, projectors[i].pos.slice()])),
                  mirror: Engine.symMirror(lyres.map((i) => projectors[i])) };
    }
    symDrag.last = now;
    const o = symDrag.origins, refO = o[symDrag.ref];
    const d = [target[0] === null ? 0 : target[0] - refO[0], target[1] === null ? 0 : target[1] - refO[1]];
    const refMir = symDrag.mirror.has(projectors[symDrag.ref]);
    lyres.forEach((i) => {
      const p = projectors[i], m = symDrag.mirror.has(p) !== refMir;
      setPos(p, i, [clamp16(o[i][0] + (m && play.symPan ? -d[0] : d[0])),
                    clamp16(o[i][1] + (m && play.symTilt ? -d[1] : d[1]))]);
    });
  }
  // `gi` = numéro de groupe (0 = A).
  function clearGroupOverrides(gi) {
    (byGroup[GROUPS[gi]] || []).forEach((p) => { p.override = null; });
  }
  function each(idxs, fn) {
    (idxs || []).forEach((i) => { const p = projectors[i]; if (p) { p.override = p.override || {}; fn(p.override); } });
  }

  // ── Effets rapides (SCÈNE) ─────────────────────────────────────────────────
  // Port du clic droit du plan de feu PC (plan_de_feu._EffectState et
  // _tick_effects) : un effet PAR PROJECTEUR, qui passe par-dessus l'AKAI.
  // Lyres : mouvement autour de la visée (pad POSITION). PAR : couleur.
  // Curseurs : 50 = naturel, multiplicateur max(0,1 ; v/50) comme le PC ;
  // déphasage = un cycle réparti sur les projecteurs du même effet.
  const QE_LYRE = [["cercle", "⭕", "Cercle"], ["figure8", "∞", "Huit"],
                   ["balayage_h", "↔", "Balayage pan"], ["balayage_v", "↕", "Balayage tilt"]];
  const QE_LED = [["rainbow", "🌈", "Arc-en-ciel"], ["strobe", "⚡", "Strobe"], ["rouge_blanc", "R→B", "Rouge → blanc"]];
  const QE_HZ = { cercle: 0.5, figure8: 0.5, balayage_h: 0.5, balayage_v: 0.5, rainbow: 0.3, strobe: 5.0, rouge_blanc: 0.5 };
  const QE_AMP = 10000;                               // course naturelle des lyres (start_effect du PC)
  const qeMult = (v) => Math.max(0.1, v / 50);
  const qPhase = {};                                  // n° de projecteur → phase (radians), non sauvegardée
  const qClock = { last: null };
  function hsvHex(h) {
    const c = 255, x = Math.round(c * (1 - Math.abs(((h / 60) % 2) - 1)));
    const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
    return toHex([r, g, b]);
  }
  function applyQuick(states, qfx) {
    const keys = Object.keys(qfx);
    if (!keys.length) { qClock.last = null; return; }
    const now = performance.now() / 1000;
    const dt = qClock.last === null ? 0 : Math.min(0.25, now - qClock.last);
    qClock.last = now;
    const spread = (play.qe.phase / 100) * 2 * Math.PI;
    const byKey = {};
    keys.map(Number).sort((a, b) => a - b).forEach((i) => { (byKey[qfx[i]] = byKey[qfx[i]] || []).push(i); });
    Object.entries(byKey).forEach(([key, idxs]) => idxs.forEach((i, rank) => {
      const s = states[i];
      if (!s) return;
      qPhase[i] = (qPhase[i] || 0) + 2 * Math.PI * QE_HZ[key] * qeMult(play.qe.speed) * dt;
      const ph = qPhase[i] + (rank / idxs.length) * spread;
      if (QE_HZ[key] && QE_LYRE.some(([k]) => k === key)) {
        // Lyre éteinte : allumée en blanc, comme le PC (sinon l'effet est invisible).
        if (s.level < 5) { s.level = 100; if (s.color === "#000000") s.color = "#ffffff"; delete s.fx; }
        const a = QE_AMP * qeMult(play.qe.amp);
        const [cp, ct] = projectors[i].pos;
        let pan = cp, tilt = ct;
        if (key === "cercle") { pan = cp + a * Math.sin(ph); tilt = ct + a * Math.cos(ph); }
        else if (key === "figure8") { pan = cp + a * Math.sin(ph); tilt = ct + (a / 2) * Math.sin(2 * ph); }
        else if (key === "balayage_h") pan = cp + a * Math.sin(ph);
        else if (key === "balayage_v") tilt = ct + a * Math.sin(ph);
        s.pan = clamp16(pan); s.tilt = clamp16(tilt);
        return;
      }
      const lvl = s.level > 0 ? Math.max(10, s.level) : 80;
      let color = s.color, level = lvl;
      if (key === "rainbow") color = hsvHex(Math.trunc(ph * 57.296) % 360);
      else if (key === "strobe") { if (Math.sin(ph) >= 0) color = "#ffffff"; else { color = "#000000"; level = 0; } }
      else if (key === "rouge_blanc") { const gb = Math.trunc(((Math.sin(ph) + 1) / 2) * 255); color = toHex([255, gb, gb]); }
      s.color = color; s.level = level;
      delete s.fx;                                    // l'effet rapide prime sur la couleur d'effet AKAI
      Engine.updateColorWheel(s, Engine.hexToRgb(color));
    }));
  }
  function setQuick(idxs, key) {
    idxs.forEach((i) => { if (key) { play.qfx[i] = key; qPhase[i] = 0; } else { delete play.qfx[i]; delete qPhase[i]; } });
    runTimer();
  }

  // ── Effets ─────────────────────────────────────────────────────────────────
  // Une seule boucle d'animation pour tous les effets (AKAI, mémoires, rapides, aperçu).
  let fxTimer = null;
  function runTimer() {
    const mems = activeMems();
    const need = !!preview || !!(liveHook && liveHook.active()) || play.fxStack.length > 0 || Object.keys(effectiveQfx(mems)).length > 0
      || mems.some((x) => x.mem.effect && (x.mem.effect.layers || []).length);
    if (need && !fxTimer) fxTimer = setInterval(() => refresh(false), 25);
    if (!need && fxTimer) { clearInterval(fxTimer); fxTimer = null; }
  }
  function fxChanged() { runTimer(); effectMsgs(); allPads(); }
  // Lance / coupe un effet. Exclusif : il remplace celui qui tourne ;
  // superposition : il s'ajoute, et un réappui le retire seul.
  function toggleEntry(entry) {
    if (!getEffect(entryName(entry))) return;
    if (isRunning(entry)) {
      if (play.superpose) play.fxStack = play.fxStack.filter((e) => !sameEntry(e, entry));
      else play.fxStack = [];
    } else {
      const e = { ...entry, t0: clock.t };
      play.fxStack = play.superpose ? [...play.fxStack, e] : [e];
    }
    fxChanged();
  }
  // Pour la page Live et le choix d'un effet : cet effet SEUL (row = bouton qui le porte).
  function setEffect(name, row) {
    const fx = getEffect(name);
    if (!fx) play.fxStack = [];
    else if (row !== undefined && row !== null && row >= 0 && play.buttons[row] === name) play.fxStack = [{ src: "btn", row, t0: clock.t }];
    else play.fxStack = [{ src: "name", name, t0: clock.t }];
    fxChanged();
  }
  function setPreview(fx) {
    preview = fx || null;
    previewT0 = clock.t;
    runTimer();
    refresh(true);
  }

  // ── Mémoires ───────────────────────────────────────────────────────────────
  // Effet qui tourne, à figer dans une mémoire : le plus récent.
  function currentEffect() {
    const mems = activeMems();
    const run = runningEffects(mems).filter((x) => x.fx);
    if (!run.length) return null;
    const top = run[run.length - 1];
    return { name: top.fx.name, layers: JSON.parse(JSON.stringify(top.fx.layers || [])) };
  }
  function recordMemory(m, row) {
    const { states } = baseStates();
    play.memories[memKey(row, m)] = {
      v: 2,
      projectors: projectors.map((p, i) => {
        const s = states[i], o = p.override || {};
        return { color: s.color, level: s.muted ? 0 : s.level, strobe: s.strobe || 0,
                 pan: Engine.isLyre(p) ? p.pos[0] : null, tilt: Engine.isLyre(p) ? p.pos[1] : null,
                 gobo: p.gobo || 0, cw: o.color_wheel };
      }),
      effect: currentEffect(),
      qfx: { ...play.qfx },
    };
    play.memRows[m] = row;
    play.memTs = Date.now();
  }
  // Une mémoire posée reprend la main : visée et gobo des lyres (la plus
  // haute l'emporte), réglages SCÈNE des projecteurs qu'elle allume.
  function applyMemoryBeams() {
    const mems = activeMems();
    projectors.forEach((p, i) => {
      const st = mems.map((x) => (x.mem.projectors || [])[i]).find((s) => s && s.pan !== null && s.pan !== undefined);
      if (st && Engine.isLyre(p)) setPos(p, i, [st.pan, st.tilt]);
      const sg = mems.map((x) => (x.mem.projectors || [])[i]).find((s) => s);
      if (sg) { p.gobo = sg.gobo || 0; play.gobos[i] = p.gobo; }
      if (mems.some((x) => ((x.mem.projectors || [])[i] || {}).level > 0)) p.override = null;
    });
  }
  // Mémoire à effet posée en mode exclusif : son effet prend la main
  // (MainWindow._mem_drive_effect → _stop_button_effects).
  function memoryTakesEffect(mem) {
    if (!play.superpose && mem.effect && (mem.effect.layers || []).length) play.fxStack = [];
  }
  function memoryPad(m, row) {
    const k = memKey(row, m);
    if (recArmed) {
      recordMemory(m, row);
      setRec(false);
      toast("Mémoire " + (m + 1) + "." + (row + 1) + " enregistrée");
      return;
    }
    const mem = play.memories[k];
    if (!mem) return;
    if (play.memRows[m] === row) {                  // réappui = éteint
      delete play.memRows[m];
      // Plus aucune mémoire : les couleurs qu'elle recouvrait s'éteignent
      // avec elle (le PC noircit tout au dernier pad mémoire éteint).
      if (!Object.keys(play.memRows).length) {
        Object.keys(play.active).forEach((gi) => { if ((play.groupTs[gi] || 0) < play.memTs) delete play.active[gi]; });
      }
    } else {
      play.memRows[m] = row;
      play.memTs = Date.now();
      if (memLevel(m) === 0) toast("Fader MEM " + (m + 1) + " à zéro : montez-le pour voir la mémoire");
      memoryTakesEffect(mem);
      applyMemoryBeams();
    }
    fxChanged();
  }

  // ── Positions (colonnes POS) ───────────────────────────────────────────────
  function posPad(pc, row) {
    const list = play.posPresets[pc] = play.posPresets[pc] || [];
    if (recArmed) {
      setRec(false);
      recordPosition(pc, row, (list[row] && list[row].name) || "Pos " + (pc + 1) + "-" + (row + 1));
      return;
    }
    const pr = list[row];
    if (!pr) return;
    let n = 0;
    projectors.forEach((p, i) => { const v = pr.pos[i]; if (v && Engine.isLyre(p)) { setPos(p, i, v.slice()); n++; } });
    if (!n) { toast("Aucune lyre de cette position dans le patch"); return; }
    play.posActive[pc] = row;
    padsOfType("pos");
    redrawPad();
  }
  function recordPosition(pc, row, name) {
    if (!hasLyres) { toast("Pas de lyre dans le patch"); return; }
    const pos = {};
    projectors.forEach((p, i) => { if (Engine.isLyre(p)) pos[i] = p.pos.slice(); });
    (play.posPresets[pc] = play.posPresets[pc] || [])[row] = { name, pos };
    play.posActive[pc] = row;
    toast("Position « " + name + " » enregistrée");
    padsOfType("pos");
  }
  function padsOfType(type) { curPage().forEach((s, c) => { if (s.type === type) padMsgs(c); }); }

  function blackout() {
    play.active = {};
    projectors.forEach((p) => { p.override = null; });
    play.memRows = {};
    play.posActive = {};
    play.qfx = {};
    play.fxStack = [];
    fxChanged();
  }
  function setRec(on) {
    recArmed = on;
    emit({ type: "rec_state", active: on });
    // Pas de colonne MEM ni POS sur cette page : on le dit, sans changer de
    // page (comme le PC ; jusqu'au 12/10 on sautait à la 1re page avec MEM).
    if (on && !curPage().some((s) => s.type === "memory" || s.type === "pos")) {
      const i = play.pages.findIndex((pg) => pg.some((s) => s.type === "memory"));
      toast(i >= 0 ? "REC : pas de colonne MEM sur cette page, les mémoires sont en page " + (i + 1) + " (◀ ▶)"
        : "REC : aucune colonne MEM, appui long sur un nom de fader pour en régler une", 3500);
    }
    allPads();
  }

  // ── Look complet (ambiances de la page Live) ────────────────────────────────
  function snapshot() {
    return {
      v: 2,
      active: { ...play.active },
      faders: play.faders.slice(0, 8),
      effect: play.effect,
      fxStack: play.fxStack.map((e) => ({ src: e.src, row: e.row, f: e.f, name: e.name })),
      memRows: { ...play.memRows },
      memLevels: { ...play.memLevels },
      overrides: projectors.map((p) => (p.override ? { ...p.override } : null)),
      positions: projectors.map((p) => p.pos.slice()),
      gobos: projectors.map((p) => p.gobo || 0),
      moveSize: play.moveSize,
      qfx: { ...play.qfx },
    };
  }
  function recall(m) {
    const now = Date.now();
    play.active = { ...(m.active || {}) };
    Object.keys(play.active).forEach((gi) => { play.groupTs[gi] = now + 1; });
    (m.faders || []).forEach((v, i) => { play.faders[i] = v; });
    projectors.forEach((p, i) => { const o = (m.overrides || [])[i]; p.override = o ? { ...o } : null; });
    (m.positions || []).forEach((pos, i) => { if (projectors[i] && pos) setPos(projectors[i], i, pos); });
    (m.gobos || []).forEach((g, i) => { if (projectors[i]) { projectors[i].gobo = g; play.gobos[i] = g; } });
    play.qfx = { ...(m.qfx || {}) };
    play.memRows = { ...(m.memRows || {}) };
    if (m.memLevels) play.memLevels = { ...m.memLevels };
    play.memTs = now;
    if (m.v) play.fxStack = (m.fxStack || []).map((e) => ({ ...e, t0: clock.t }));
    else setEffect(m.effect);
    pageMsgs();
    fxChanged();
  }
  // Couleur d'un groupe depuis la page Live (même geste qu'un pad couleur).
  function setGroupColor(gi, row) {
    if (row === null || row === undefined) delete play.active[gi]; else play.active[gi] = row;
    play.groupTs[gi] = Date.now();
    clearGroupOverrides(gi);
  }
  function setGroupLevel(gi, v) {
    play.faders[gi] = v;
    if (play.active[gi] !== undefined) play.groupTs[gi] = Date.now();
    (byGroup[GROUPS[gi]] || []).forEach((p) => { if (p.override) delete p.override.level; });
    curPage().forEach((s, c) => { if (s.type === "group" && s.group === GROUPS[gi]) emit({ type: "fader", idx: c, value: v }); });
  }

  // ── Actions de l'interface ─────────────────────────────────────────────────
  window.MYSTROW_SEND = function (ev) {
    switch (ev && ev.type) {
      case "pad": {
        const s = slotAt(ev.col);
        if (!s || s.type === "none") break;
        if (s.type === "memory") { memoryPad(s.mem_col, ev.row); break; }
        if (s.type === "pos") { posPad(s.pos_col, ev.row); break; }
        if (s.type === "fx") {
          if (recArmed) { setRec(false); toast("On n'enregistre pas sur un pad FX : REC annulé"); break; }
          toggleEntry({ src: "pad", f: s.fx_col, row: ev.row });
          break;
        }
        // Couleur : même pad une seconde fois = le groupe s'éteint.
        const gi = GROUPS.indexOf(s.group);
        setGroupColor(gi, play.active[gi] === ev.row ? null : ev.row);
        allPads();                                  // le groupe peut être sur deux colonnes
        break;
      }
      case "fader": {
        if (ev.idx === SPEED) { play.faders[SPEED] = ev.value; emit({ type: "fader", idx: SPEED, value: ev.value }); break; }
        const s = slotAt(ev.idx);
        if (!s) break;
        if (s.type === "group") { setGroupLevel(GROUPS.indexOf(s.group), ev.value); break; }
        if (s.type === "memory") {
          play.memLevels[s.mem_col] = ev.value;
          if (play.memRows[s.mem_col] !== undefined) play.memTs = Date.now();
          runTimer();
        } else if (s.type === "fx") play.fxAmp[s.fx_col] = ev.value;
        else { emit({ type: "fader", idx: ev.idx, value: 0 }); break; }   // POS : pas de fader
        emit({ type: "fader", idx: ev.idx, value: ev.value });
        break;
      }
      case "effect": toggleEntry({ src: "btn", row: ev.row }); break;
      case "bankpage":
        play.pageIdx = ev.action === "set" ? Math.max(0, Math.min(N_PAGES - 1, ev.index | 0))
          : (play.pageIdx + (ev.action === "prev" ? N_PAGES - 1 : 1)) % N_PAGES;
        pageMsgs();
        break;
      case "rec_toggle":
        setRec(!recArmed);
        break;
      case "clear":
        blackout();
        if (recArmed) setRec(false);
        allPads();
        break;
      case "proj_color": each(ev.idxs, (o) => { o.color = ev.color; if (o.level === undefined) o.level = 100; }); break;
      case "proj_level": each(ev.idxs, (o) => { o.level = ev.value; }); break;
      case "proj_mute": each(ev.idxs, (o) => { o.muted = !!ev.muted; }); break;
      case "proj_strobe": each(ev.idxs, (o) => { o.strobe = ev.value; }); break;
      case "proj_colorwheel":
        // Filtre choisi à la main : la couleur affichée suit le filtre (comme le
        // PC, _apply_color_wheel_dmx).
        (ev.idxs || []).forEach((i) => {
          const p = projectors[i];
          if (!p) return;
          p.override = p.override || {};
          p.override.color_wheel = Math.max(0, Math.min(255, Math.trunc(ev.value)));
          p.override.color = Engine.cwSlotAt(p.color_wheel_slots, p.override.color_wheel).color || "#ffffff";
          if (p.override.level === undefined) p.override.level = 100;
        });
        break;
      case "proj_gobo":
        (ev.idxs || []).forEach((i) => {
          const p = projectors[i];
          if (p) { p.gobo = Math.max(0, Math.min(255, Math.trunc(ev.value))); play.gobos[i] = p.gobo; }
        });
        break;
      case "proj_pantilt":
        // Pad POSITION (0..1) → 0..65535, comme le PC. La visée survit aux
        // changements de couleur : elle n'est pas dans `override`.
        panTilt((ev.idxs || []).filter((i) => projectors[i]), ev);
        setTimeout(redrawPad, 0);             // après le dessin de la page
        break;
      case "scene_clear":
        projectors.forEach((p) => { p.override = null; });
        setQuick(Object.keys(play.qfx).map(Number), null);
        break;
      case "proj_qfx": setQuick((ev.idxs || []).filter((i) => projectors[i]), ev.key || null); break;
      case "proj_qe": if (ev.param in play.qe) play.qe[ev.param] = Math.max(0, Math.min(100, +ev.value || 0)); break;
      default:
        if (window.MystrowSoloMedia) window.MystrowSoloMedia(ev);   // playlist, cartouches
        return;
    }
    savePlay();
    refresh(true);
  };

  // ── Habillage propre au mode autonome ──────────────────────────────────────
  const style = document.createElement("style");
  style.textContent =
    "#solo-badge{flex-shrink:0;height:100%;padding:0 12px;border-radius:10px;border:1px solid rgba(226,206,22,.45);" +
    "background:rgba(226,206,22,.10);color:#E2CE16;font-family:var(--f-label);font-weight:700;font-size:13px;" +
    "letter-spacing:1.5px;cursor:pointer;touch-action:manipulation;white-space:nowrap}" +
    "#solo-badge.err{border-color:rgba(248,113,113,.6);background:rgba(248,113,113,.12);color:#f87171}" +
    "#solo-demo{flex-shrink:0;height:100%;padding:0 12px;border-radius:10px;border:1px solid rgba(255,255,255,.18);background:#13120e;" +
    "color:#cfcabd;font-family:var(--f-label);font-weight:700;font-size:13px;letter-spacing:1.5px;cursor:pointer;touch-action:manipulation;" +
    "white-space:nowrap;font-variant-numeric:tabular-nums}#solo-demo[hidden]{display:none}" +
    "#solo-demo.soon{border-color:rgba(251,146,60,.7);color:#fdba74}" +
    "#solo-demo.over{border-color:rgba(248,113,113,.7);background:rgba(248,113,113,.15);color:#f87171}" +
    // Nom de l'effet dans chaque bouton
    ".eff-btn{display:flex;align-items:center;justify-content:center;overflow:hidden;padding:2px 3px;" +
    "font-family:var(--f-label);font-weight:700;font-size:clamp(9px,1.25vmin,13px);line-height:1.05;" +
    "text-align:center;color:#8fd9a0;user-select:none;-webkit-user-select:none}" +
    ".eff-btn.on{color:#052a0d}" +
    // Nom de l'effet / de la position dans les pads FX et POS
    // (::after est déjà le reflet des pads allumés de la page : on prend ::before.)
    "#grid .pad[data-label]::before{content:attr(data-label);position:absolute;inset:3px;z-index:1;" +
    "display:flex;align-items:center;justify-content:center;overflow:hidden;" +
    "font-family:var(--f-label);font-weight:700;font-size:clamp(8px,1.2vmin,13px);line-height:1.05;text-align:center;" +
    "color:#fff;text-shadow:0 1px 2px #000,0 0 4px #000;pointer-events:none;word-break:break-word}" +
    // Nom de colonne : appui long = changer de type
    "body.solo .fader-label{cursor:pointer;-webkit-user-select:none;user-select:none;border-bottom:1px dotted rgba(226,206,22,.35)}" +
    "#akai-pagenav .solo-cols{flex:none;height:clamp(34px,5.5vh,46px);font-family:var(--f-label);font-size:clamp(12px,1.5vw,15px);" +
    "letter-spacing:1.5px;color:#E2CE16;border-color:rgba(226,206,22,.45)}" +
    "@media (orientation:portrait){#akai-pagenav .solo-cols{width:auto!important;padding:0 12px;margin-left:8px}}" +
    "#solo-toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:70;background:#1b1a17;" +
    "border:1px solid rgba(226,206,22,.45);color:#E2CE16;padding:10px 18px;border-radius:10px;font-family:var(--f-label);" +
    "font-weight:700;letter-spacing:1px;opacity:0;transition:opacity .2s;pointer-events:none;max-width:min(560px,calc(100vw - 32px));text-align:center}" +
    "#solo-toast.show{opacity:1}" +
    // Choix d'un effet / d'un type de colonne
    "#fx-pick{position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center}" +
    "#fx-pick[hidden]{display:none}" +
    "#fx-pick .box{width:min(92vw,760px);max-height:86vh;display:flex;flex-direction:column;background:#11100e;" +
    "border:1px solid rgba(226,206,22,.35);border-radius:14px;padding:14px}" +
    "#fx-pick h3{margin:0 0 10px;font-family:var(--f-title);font-weight:400;font-size:26px;letter-spacing:1px;color:#E2CE16}" +
    "#fx-pick .tools{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}#fx-pick .tools[hidden]{display:none}" +
    "#fx-pick .tools button{flex:1;min-width:160px;border-color:rgba(226,206,22,.5);background:rgba(226,206,22,.1);color:#E2CE16}" +
    "#fx-pick .list{overflow:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px}" +
    "#fx-pick .cat{grid-column:1/-1;margin-top:6px;font-family:var(--f-label);font-size:12px;letter-spacing:2px;color:var(--muted)}" +
    "#fx-pick button{min-height:44px;border-radius:8px;border:1px solid #1a5e26;background:#0d2e12;color:#cfeed6;" +
    "font-family:var(--f-label);font-weight:700;font-size:14px;cursor:pointer;touch-action:manipulation}" +
    "#fx-pick button.cur{background:var(--green);color:#052a0d;border-color:#4ade80}" +
    "#fx-pick button.mine{border-color:#7a6a10;background:#2a250a;color:#f3e69a}" +
    "#fx-pick button.mine.cur{background:#E2CE16;color:#0c0b00}" +
    "#fx-pick button.k-memory{border-color:#1a3f66;background:#0b1d33;color:#cfe3ff}" +
    "#fx-pick button.k-pos{border-color:#2a3a99;background:#0d1440;color:#d3dbff}" +
    "#fx-pick button.k-group{border-color:#5a5440;background:#1d1b14;color:#f2efe6}" +
    "#fx-pick .close{margin-top:10px;border-color:var(--line2);background:var(--bg2);color:var(--text)}" +
    // Fenêtre COLONNES
    "#solo-cols{position:fixed;inset:0;z-index:48;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center;padding:14px}" +
    "#solo-cols[hidden]{display:none}" +
    "#solo-cols .box{width:min(96vw,900px);max-height:94vh;overflow:auto;background:#0e0d0a;border:1px solid rgba(226,206,22,.3);" +
    "border-radius:18px;padding:16px 18px;display:flex;flex-direction:column;gap:12px;font-family:var(--f-label);color:var(--text)}" +
    "#solo-cols button{font-family:var(--f-label);cursor:pointer;touch-action:manipulation;color:var(--text)}" +
    "#solo-cols header{display:flex;align-items:center;justify-content:space-between}" +
    "#solo-cols h2{margin:0;font-family:var(--f-title);font-weight:400;font-size:32px;letter-spacing:1px;color:#E2CE16}" +
    "#solo-cols .x{width:48px;height:48px;border-radius:12px;border:1px solid var(--line2);background:transparent;font-size:20px}" +
    "#solo-cols .pg{display:flex;align-items:center;gap:10px}" +
    "#solo-cols .pg button{width:52px;height:46px;border-radius:12px;border:1px solid var(--line2);background:#15140f;font-size:18px}" +
    "#solo-cols .pg b{min-width:120px;text-align:center;font-family:var(--f-title);font-weight:400;font-size:26px;letter-spacing:1px}" +
    "#solo-cols .pg small{flex:1;text-align:right;font-size:14px;color:var(--muted)}" +
    "#solo-cols .board{display:grid;grid-template-columns:repeat(8,minmax(0,1fr)) minmax(0,.8fr);gap:6px;padding:14px 10px 12px;" +
    "border-radius:14px;background:#111;border:1px solid #1e1e1e}" +
    "#solo-cols .bc{display:flex;flex-direction:column;align-items:center;gap:8px;min-width:0}" +
    "#solo-cols .bc small{font-size:12px;font-weight:700;color:#5a564c}" +
    "#solo-cols .fd{position:relative;width:10px;height:clamp(70px,14vh,120px);border-radius:5px;background:#1d1c17}" +
    "#solo-cols .fd i{position:absolute;left:-13px;right:-13px;top:38%;height:14px;border-radius:4px;background:var(--kc)}" +
    "#solo-cols .pick{width:100%;min-height:48px;padding:0 2px;border-radius:10px;border:1px solid var(--line2);border-bottom:3px solid var(--kc);" +
    "background:#1b1a14;font-weight:700;font-size:15px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
    "#solo-cols .bc.f9{border-left:1px solid #222;padding-left:6px}#solo-cols .bc.f9 .fd i{background:#3b4a7a}" +
    "#solo-cols .bc.f9 span{min-height:48px;display:flex;align-items:center;font-weight:700;font-size:14px;color:#6b7bb0}" +
    "#solo-cols .k-group,#solo-slot .k-group{--kc:#f4f1e8}#solo-cols .k-memory,#solo-slot .k-memory{--kc:#3b82f6}" +
    "#solo-cols .k-fx,#solo-slot .k-fx{--kc:#22c55e}#solo-cols .k-pos,#solo-slot .k-pos{--kc:#6366f1}#solo-cols .k-none,#solo-slot .k-none{--kc:#4a4640}" +
    // Liste de choix d'un fader
    "#solo-slot{position:fixed;inset:0;z-index:49;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center;padding:14px}" +
    "#solo-slot[hidden]{display:none}" +
    "#solo-slot .box{width:min(96vw,760px);max-height:94vh;overflow:auto;background:#0e0d0a;border:1px solid rgba(226,206,22,.3);" +
    "border-radius:18px;padding:16px 18px;display:flex;flex-direction:column;gap:10px;font-family:var(--f-label);color:var(--text)}" +
    "#solo-slot button{font-family:var(--f-label);cursor:pointer;touch-action:manipulation;color:var(--text)}" +
    "#solo-slot header{display:flex;align-items:center;justify-content:space-between}" +
    "#solo-slot h2{margin:0;font-family:var(--f-title);font-weight:400;font-size:30px;letter-spacing:1px;color:#E2CE16}" +
    "#solo-slot .x{width:48px;height:48px;border-radius:12px;border:1px solid var(--line2);background:transparent;font-size:20px}" +
    "#solo-slot .list{display:flex;flex-direction:column;gap:8px}" +
    "#solo-slot .st{margin-top:6px}#solo-slot .st b{font-size:13px;letter-spacing:2.5px;color:var(--muted)}" +
    "#solo-slot .st small{margin-left:10px;font-size:13px;color:#7a766b}" +
    "#solo-slot .vals{display:grid;grid-template-columns:repeat(auto-fill,minmax(84px,1fr));gap:6px}" +
    "#solo-slot .vals button{height:58px;border-radius:12px;border:1px solid var(--line2);background:#1b1a14;display:flex;flex-direction:column;" +
    "align-items:center;justify-content:center;gap:1px;border-left:4px solid var(--kc)}" +
    "#solo-slot .vals button b{font-size:18px}#solo-slot .vals button small{font-size:12px;color:var(--muted)}" +
    "#solo-slot .vals button.on{background:#E2CE16;border-color:#E2CE16;color:#0c0b00}#solo-slot .vals button.on small{color:#3a3500}" +
    "#solo-cols .ttl{margin-top:2px;font-weight:700;font-size:13px;letter-spacing:2.5px;color:var(--muted)}" +
    "#solo-cols .ttl small{margin-left:8px;letter-spacing:.3px;font-weight:500}" +
    "#solo-cols .presets{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:6px}" +
    "#solo-cols .presets button{min-height:46px;border-radius:12px;border:1px solid var(--line2);background:#15140f;font-weight:700;font-size:15px}" +
    "#solo-cols .sw{display:flex;align-items:center;gap:14px;padding:14px 16px;border-radius:14px;border:1px solid var(--line2);background:#15140f;cursor:pointer}" +
    "#solo-cols .sw span{flex:1;display:flex;flex-direction:column}#solo-cols .sw b{font-size:19px}#solo-cols .sw small{font-size:14px;color:#9a958a}" +
    "#solo-cols .sw input{position:absolute;opacity:0;pointer-events:none}" +
    "#solo-cols .sw i{width:58px;height:32px;border-radius:16px;background:#3a3830;position:relative;transition:background .15s;flex-shrink:0}" +
    "#solo-cols .sw i::after{content:'';position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#f4f1e8;transition:left .15s}" +
    "#solo-cols .sw input:checked+i{background:#E2CE16}#solo-cols .sw input:checked+i::after{left:29px}" +
    "@media (orientation:portrait){#solo-cols .pg small{display:none}#solo-cols .pick{font-size:13px}}" +
    // En-tête du pad POSITION : SYM + CENTRER
    ".solo-pt-head{display:flex;align-items:center;gap:8px}.solo-pt-head #proj-pantilt-lbl{flex:1}" +
    ".solo-pt-head button{height:34px;padding:0 14px;border-radius:8px;border:1px solid var(--line2);background:var(--bg3);" +
    "color:var(--muted);font-family:var(--f-label);font-weight:700;font-size:13px;letter-spacing:1.5px;cursor:pointer;touch-action:manipulation}" +
    ".solo-pt-head button.on{background:rgba(226,206,22,.16);border-color:#E2CE16;color:#E2CE16}" +
    "#akai-pagenav .solo-move{display:flex;flex-direction:column;gap:5px;margin-top:4px;padding-top:8px;border-top:1px solid var(--line)}" +
    "#akai-pagenav .solo-move span{font-family:var(--f-label);font-weight:700;font-size:11px;letter-spacing:1.5px;color:var(--muted);text-align:center}" +
    "#akai-pagenav .solo-move div{display:flex;align-items:center;gap:4px}" +
    "#akai-pagenav .solo-move button{flex:none;width:clamp(30px,3.4vw,40px);height:clamp(34px,5.5vh,44px);padding:0;font-size:20px}" +
    "#akai-pagenav .solo-move b{flex:1;text-align:center;font-family:var(--f-title);font-weight:400;font-size:clamp(18px,2.2vw,24px);" +
    "color:var(--text);cursor:pointer}#akai-pagenav .solo-move b.mod{color:#E2CE16}" +
    "@media (orientation:portrait){#akai-pagenav .solo-move{margin:0 0 0 6px;padding:0 0 0 8px;border-top:0;border-left:1px solid var(--line)}}" +
    // Menu contextuel (appui long : mémoires, playlist, cartouches)
    "#solo-menu{position:fixed;inset:0;z-index:58;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center}" +
    "#solo-menu[hidden]{display:none}" +
    "#solo-menu .box{width:min(88vw,380px);max-height:90vh;overflow:auto;background:#11100e;border:1px solid rgba(226,206,22,.35);border-radius:14px;" +
    "padding:14px;display:flex;flex-direction:column;gap:8px}" +
    "#solo-menu h3{margin:0 0 4px;font-family:var(--f-title);font-weight:400;font-size:24px;color:#E2CE16;" +
    "white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
    "#solo-menu button{min-height:48px;border-radius:10px;border:1px solid var(--line2);background:var(--bg2);color:var(--text);" +
    "font-family:var(--f-label);font-weight:700;font-size:16px;cursor:pointer}" +
    "#solo-menu button.danger{border-color:rgba(248,113,113,.5);color:#f87171}" +
    // Saisie d'un nom
    "#solo-ask{position:fixed;inset:0;z-index:62;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center}" +
    "#solo-ask[hidden]{display:none}" +
    "#solo-ask form{width:min(88vw,420px);background:#11100e;border:1px solid rgba(226,206,22,.35);border-radius:16px;padding:18px;display:flex;flex-direction:column;gap:12px}" +
    "#solo-ask label{font-family:var(--f-label);font-weight:700;font-size:14px;letter-spacing:2px;color:#E2CE16;text-transform:uppercase}" +
    "#solo-ask input{height:52px;padding:0 14px;border-radius:12px;border:1px solid #3a3830;background:#0c0b09;color:#f2efe6;font:700 22px/1 var(--f-label)}" +
    "#solo-ask .row{display:flex;gap:10px}#solo-ask .row button{flex:1;height:50px;border-radius:12px;font-family:var(--f-label);font-weight:700;font-size:17px;cursor:pointer}" +
    "#solo-ask .no{background:transparent;border:1px solid #3a3830;color:#cfcabd}#solo-ask .ok{background:#E2CE16;border:0;color:#0c0b00}";
  document.head.appendChild(style);

  // Bouton RÉGLAGES (remplace l'ancien badge « SANS PC ») : patch, sortie DMX,
  // test de sortie, accueil. ⚠ quand la sortie DMX est en erreur.
  const badge = document.createElement("button");
  badge.id = "solo-badge";
  badge.type = "button";
  badge.textContent = "⚙ RÉGLAGES";
  badge.title = "Réglages : projecteurs, sortie DMX, accueil";
  badge.addEventListener("click", () => openSettings());
  document.getElementById("conn-status").before(badge);

  // Pastille DÉMO : temps restant sans licence ; toucher = Mon compte.
  const demoChip = document.createElement("button");
  demoChip.id = "solo-demo"; demoChip.type = "button";
  // Le décompte n'est plus affiché en permanence : il se lit au toucher.
  demoChip.addEventListener("click", () => {
    openMenu("Version démo", [["Se connecter", () => openAccount()], ...packAction()], demoText());
    const info = menu.querySelector(".info");
    const t = setInterval(() => { if (menu.hidden || !demoChip.isConnected) clearInterval(t); else info.textContent = demoText(); }, 1000);
  });
  function demoText() {
    const left = Math.max(0, demoLeft());
    const m = Math.floor(left / 60000), sec = Math.floor((left % 60000) / 1000);
    return "Il reste " + m + " min " + String(sec).padStart(2, "0") + " s avant que la sortie DMX se coupe.\n" +
      "Connectez-vous avec un compte MyStrow sous licence pour jouer sans limite.";
  }
  badge.before(demoChip);
  let demoWarned = false;
  function paintDemo() {
    const left = demoLeft();
    demoChip.hidden = licensed;
    if (licensed) { if (demoWarned) { demoWarned = false; paintStatus(); } return; }
    if (left <= 0) {
      // Démo finie : pas de fenêtre, la pastille disparaît et le voyant
      // passe à DMX COUPÉ (son toucher explique et propose de se connecter).
      demoChip.hidden = true;
      if (!demoWarned) { demoWarned = true; lastSent = ""; refresh(true); paintStatus(); }
      return;
    }
    demoChip.textContent = "DÉMO";
    demoChip.classList.toggle("soon", left < 60000);
  }
  // ── Pack MyStrow (boîtier + licence) sur Amazon ─────────────────────────────
  // Même carte que le logiciel (updater._carte_pack) et que /shop : photo,
  // deux offres, liens directs amazon.fr/dp/<ASIN> sans tag affilié.
  // Pas sur iPhone / iPad : le pack contient la licence, et Apple refuse les
  // liens d'achat qui débloquent l'app hors de l'App Store (règle 3.1.1).
  const PACK_OK = !(window.Capacitor && window.Capacitor.getPlatform && window.Capacitor.getPlatform() === "ios");
  const packAction = () => (PACK_OK ? [["Acheter le pack MyStrow (Amazon)", () => openPack()]] : []);
  const PACK = {
    img: "https://mystrow.fr/img-shop/mystrow-pack-usb-dmx.webp",
    offers: [["Licence 2 mois · 99 €", "https://www.amazon.fr/dp/B0HK4YF5FS"],
             ["Licence 1 an · 199 €", "https://www.amazon.fr/dp/B0HK5539BK"]],
  };
  const packDlg = document.createElement("div");
  packDlg.id = "solo-pack"; packDlg.hidden = true;
  packDlg.innerHTML = '<div class="box" role="dialog" aria-modal="true" aria-labelledby="pack-t">' +
    '<header><span class="bdg">NOUVEAU · DISPONIBLE SUR AMAZON</span><button type="button" class="x" aria-label="Fermer">✕</button></header>' +
    '<div class="row"><img alt="" src="' + PACK.img + '"><div><h2 id="pack-t">Pack MyStrow</h2>' +
    '<p class="sub">Interface USB-DMX + licence</p>' +
    '<p>Notre propre interface, pensée pour MyStrow : on la branche, MyStrow la reconnaît tout seul, et la licence est dans la boîte. ' +
    'La licence débloque le logiciel PC/Mac et l\'app tablette, sans limite de 10 minutes.</p></div></div>' +
    '<div class="offers"></div><p class="note">La page s\'ouvre dans Amazon (ou le navigateur).</p></div>';
  document.body.appendChild(packDlg);
  packDlg.querySelector("img").addEventListener("error", (e) => { e.target.hidden = true; });
  packDlg.addEventListener("click", (e) => { if (e.target === packDlg) packDlg.hidden = true; });
  packDlg.querySelector(".x").addEventListener("click", () => { packDlg.hidden = true; });
  PACK.offers.forEach(([label, url], k) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = k ? "full" : ""; b.textContent = label + " ↗";
    b.addEventListener("click", () => { packDlg.hidden = true; openExternal(url); });
    packDlg.querySelector(".offers").appendChild(b);
  });
  function openPack() { packDlg.hidden = false; }
  // Lien externe : Capacitor ouvre hors de l'app (appli Amazon ou navigateur)
  // toute navigation vers un autre domaine ; dans un navigateur, nouvel onglet.
  function openExternal(url) {
    if (window.Capacitor && window.Capacitor.isNativePlatform && window.Capacitor.isNativePlatform()) location.href = url;
    else window.open(url, "_blank", "noopener");
  }
  style.textContent +=
    "#solo-pack{position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center;padding:16px}" +
    "#solo-pack[hidden]{display:none}" +
    "#solo-pack .box{width:min(94vw,640px);max-height:92vh;overflow:auto;background:#0e0d0a;border:2px solid #E2CE16;border-radius:18px;" +
    "padding:16px 18px;display:flex;flex-direction:column;gap:12px;font-family:var(--f-label);color:var(--text)}" +
    "#solo-pack header{display:flex;align-items:center;justify-content:space-between}" +
    "#solo-pack .bdg{background:#E2CE16;color:#000;border-radius:8px;padding:3px 10px;font-weight:700;font-size:12px;letter-spacing:1px}" +
    "#solo-pack .x{width:46px;height:46px;border-radius:12px;border:1px solid var(--line2);background:transparent;color:var(--text);font-size:20px;cursor:pointer}" +
    "#solo-pack .row{display:flex;gap:16px;align-items:flex-start}" +
    "#solo-pack img{width:170px;height:auto;border-radius:12px;flex-shrink:0;background:#1a1700}" +
    "#solo-pack h2{margin:0;font-family:var(--f-title);font-weight:400;font-size:32px;letter-spacing:1px;color:#E2CE16}" +
    "#solo-pack .sub{margin:0 0 6px;font-weight:700;font-size:17px;color:#f4f1e8}" +
    "#solo-pack p{margin:0;font-size:15px;line-height:1.4;color:#cfcabd}" +
    "#solo-pack .offers{display:grid;grid-template-columns:1fr 1fr;gap:10px}" +
    "#solo-pack .offers button{min-height:56px;border-radius:12px;border:1px solid rgba(226,206,22,.6);background:transparent;color:#E2CE16;" +
    "font-family:var(--f-label);font-weight:700;font-size:17px;cursor:pointer;touch-action:manipulation}" +
    "#solo-pack .offers button.full{background:#E2CE16;color:#000;border-color:#E2CE16}" +
    "#solo-pack .note{font-size:13px;color:#7a766b;text-align:center}" +
    "@media (max-width:600px){#solo-pack .row{flex-direction:column}#solo-pack img{width:100%}#solo-pack .offers{grid-template-columns:1fr}}";
  function openAccount() {
    if (!Account) { toast("Compte indisponible dans cette version"); return; }
    Account.openPanel({ onImported: () => goTo("remote.html?solo=1") });
  }
  if (Account) {
    Account.onChange((st) => {
      const was = licensed;
      licensed = !!st.paid;
      if (licensed !== was) { lastSent = ""; refresh(true); if (licensed) toast("Licence reconnue : DMX sans limite"); }
      paintDemo();
    });
    if (Account.status().loggedIn) Account.refreshLicense().catch(() => {});
  }
  setInterval(paintDemo, 1000);
  setTimeout(paintDemo, 0);

  // Quitter le jeu pour une page de réglages : on coupe la sortie (la page
  // de réglage ouvre la sienne) ; « ?from=play » y ramène ici au retour.
  function goTo(url) {
    if (Dmx) Dmx.stop().catch(() => {});
    location.href = url;
  }
  // ── Réglages : un écran à tuiles (le 12/10/2026, la liste de boutons
  // empilés n'était « pas du tout intuitive »). Compte en haut, puis le
  // matériel (patch, sortie DMX), puis le jeu (colonnes, effets, Live).
  const ICONS = {
    user: '<circle cx="12" cy="8" r="4"/><path d="M4 21c0-4 4-6 8-6s8 2 8 6"/>',
    spot: '<path d="M7 4h10l-2 7H9z"/><path d="M9 11l-3 9M15 11l3 9M12 11v10"/>',
    plug: '<path d="M9 2v6M15 2v6"/><path d="M6 8h12v3a6 6 0 0 1-12 0z"/><path d="M12 17v5"/>',
    pulse: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    wand: '<path d="M4 20L16 8"/><path d="M15 3v3M18 6h3M19 2l-2 2M13 7l4 4"/>',
    live: '<circle cx="12" cy="12" r="3"/><path d="M6.3 6.3a8 8 0 0 0 0 11.4M17.7 6.3a8 8 0 0 1 0 11.4M3.5 3.5a12 12 0 0 0 0 17M20.5 3.5a12 12 0 0 1 0 17"/>',
    home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
    box: '<path d="M3 7l9-4 9 4v10l-9 4-9-4z"/><path d="M3 7l9 4 9-4M12 11v10"/>',
  };
  const svg = (k) => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' + ICONS[k] + "</svg>";
  const setDlg = document.createElement("div");
  setDlg.id = "solo-set"; setDlg.hidden = true;
  setDlg.addEventListener("click", (e) => { if (e.target === setDlg) setDlg.hidden = true; });
  document.body.appendChild(setDlg);
  function openSettings() {
    const acc = Account ? Account.status() : { loggedIn: false };
    const n = projectors.length, o = show.output || {};
    const dmxOk = statusEl.classList.contains("ok");
    const out = o.transport === "artnet" ? "Node Art-Net " + (o.host || "2.0.0.15") : "Interface USB";
    setDlg.innerHTML = '<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="set-t">' +
      '<header><h2 id="set-t">Réglages</h2><button type="button" class="x" aria-label="Fermer">✕</button></header>' +
      '<button type="button" class="acct" data-a="account"><i>' + svg("user") + '</i><span><b></b><small></small></span><em></em></button>' +
      (PACK_OK ? '<button type="button" class="pack" data-a="pack"><i>' + svg("box") + '</i><span><b>Pack MyStrow</b>' +
      '<small>Interface USB-DMX + licence · disponible sur Amazon</small></span><em>›</em></button>' : '') +
      '<div class="ttl">MON MATÉRIEL</div><div class="tiles">' +
      '<button type="button" data-a="patch"><i>' + svg("spot") + '</i><b>Projecteurs</b><small></small></button>' +
      '<button type="button" data-a="output"><i>' + svg("plug") + '</i><b>Sortie DMX</b><small></small></button>' +
      '<button type="button" data-a="test"><i>' + svg("pulse") + '</i><b>Tester la sortie</b><small>Allumer canal par canal</small></button></div>' +
      '<div class="ttl">JEU</div><div class="tiles">' +
      '<button type="button" data-a="cols"><i>' + svg("grid") + '</i><b>Réglages de l\'AKAI</b><small>Dispositions toutes faites, superposition d\'effets</small></button>' +
      '<button type="button" data-a="fx"><i>' + svg("wand") + '</i><b>Éditeur d\'effets</b><small></small></button>' +
      '</div>' +
      '<footer><button type="button" data-a="home"><i>' + svg("home") + '</i>Accueil</button><span></span></footer></div>';
    const $s = (q) => setDlg.querySelector(q);
    $s(".acct b").textContent = acc.loggedIn ? acc.email : "Se connecter";
    $s(".acct small").textContent = acc.loggedIn ? (licensed ? "Licence active : DMX sans limite" : "Pas de licence payante : DMX limité à 10 min")
      : "DMX limité à 10 min sans compte · récupérer la config du PC";
    $s(".acct em").textContent = licensed ? "✓" : "›";
    $s(".acct").classList.toggle("ok", licensed);
    $s('[data-a="patch"] small').textContent = n ? n + " projecteur" + (n > 1 ? "s" : "") : "Aucun projecteur";
    $s('[data-a="output"] small').textContent = out + " · " + (dmxOk ? "OK" : "coupée");
    $s('[data-a="output"]').classList.toggle("bad", !dmxOk);
    $s('[data-a="fx"] small').textContent = customFx.length ? customFx.length + " effet" + (customFx.length > 1 ? "s" : "") + " perso" : "Créer vos effets";
    $s("footer span").textContent = versionText().replace("\n", " · ");
    const ACT = {
      account: () => openAccount(), patch: () => goTo("patch.html?from=play"), output: () => goTo("patch.html?from=play#sortie"),
      test: () => goTo("dmxtest.html?from=play"), cols: () => openColumns(), fx: () => openFxManager(), pack: () => openPack(),
      live: () => window.MystrowLive.toggle(), home: () => goTo("index.html?view=solo"),
    };
    setDlg.querySelectorAll("[data-a]").forEach((b) => b.addEventListener("click", () => { setDlg.hidden = true; ACT[b.dataset.a](); }));
    $s(".x").addEventListener("click", () => { setDlg.hidden = true; });
    setDlg.hidden = false;
  }
  style.textContent +=
    "#solo-set{position:fixed;inset:0;z-index:47;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center;padding:16px}" +
    "#solo-set[hidden]{display:none}" +
    "#solo-set .sheet{width:min(96vw,860px);max-height:92vh;overflow:auto;background:#0e0d0a;border:1px solid rgba(226,206,22,.3);border-radius:18px;" +
    "padding:18px 20px;display:flex;flex-direction:column;gap:12px;font-family:var(--f-label);color:var(--text)}" +
    "#solo-set header{display:flex;align-items:center;justify-content:space-between}" +
    "#solo-set h2{margin:0;font-family:var(--f-title);font-weight:400;font-size:34px;letter-spacing:1px;color:#E2CE16}" +
    "#solo-set button{font-family:var(--f-label);cursor:pointer;touch-action:manipulation;color:var(--text)}" +
    "#solo-set .x{width:48px;height:48px;border-radius:12px;border:1px solid var(--line2);background:transparent;font-size:20px}" +
    "#solo-set i{display:grid;place-items:center;flex-shrink:0}#solo-set svg{width:28px;height:28px}" +
    "#solo-set .acct{display:flex;align-items:center;gap:14px;text-align:left;padding:14px 16px;border-radius:14px;" +
    "border:1px solid rgba(226,206,22,.45);background:rgba(226,206,22,.08)}" +
    "#solo-set .acct i{width:48px;height:48px;border-radius:50%;background:#E2CE16;color:#0c0b00}" +
    "#solo-set .acct span{flex:1;display:flex;flex-direction:column;min-width:0}" +
    "#solo-set .acct b{font-size:20px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
    "#solo-set .acct small{font-size:15px;color:#fdba74}#solo-set .acct.ok small{color:#9fdcb4}" +
    "#solo-set .acct em{font-style:normal;font-size:28px;color:#E2CE16}#solo-set .acct.ok em{color:#22c55e}" +
    "#solo-set .ttl{margin-top:4px;font-weight:700;font-size:13px;letter-spacing:2.5px;color:var(--muted)}" +
    "#grid .pad.rec-free{border:2px dashed rgba(248,113,113,.75)!important;background:rgba(248,113,113,.06)!important;box-shadow:none!important}" +
    "#grid .pad.rec-free::after{content:'+';position:absolute;inset:0;display:flex;align-items:center;justify-content:center;" +
    "font-size:clamp(20px,3.4vmin,32px);font-weight:300;color:rgba(248,113,113,.9);pointer-events:none}" +
    "#grid .pad.rec-no{opacity:.22;transition:opacity .15s}" +
    "#solo-set .pack{display:flex;align-items:center;gap:14px;padding:12px 16px;border-radius:14px;border:1px solid rgba(226,206,22,.55);" +
    "background:#1a1700;color:var(--text);font-family:var(--f-label);text-align:left;cursor:pointer;touch-action:manipulation}" +
    "#solo-set .pack i{width:40px;height:40px;flex-shrink:0;color:#E2CE16}#solo-set .pack i svg{width:100%;height:100%}" +
    "#solo-set .pack span{flex:1;display:flex;flex-direction:column}#solo-set .pack b{font-size:19px;color:#E2CE16}" +
    "#solo-set .pack small{font-size:14px;color:#cfcabd}#solo-set .pack em{font-style:normal;font-size:26px;color:#E2CE16}" +
    "#solo-set .tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}" +
    "#solo-set .tiles button{min-height:118px;padding:14px;border-radius:14px;border:1px solid var(--line2);background:#15140f;" +
    "display:flex;flex-direction:column;align-items:flex-start;justify-content:flex-end;gap:4px;text-align:left}" +
    "#solo-set .tiles button:active{background:rgba(226,206,22,.12)}" +
    "#solo-set .tiles i{color:#E2CE16;margin-bottom:auto}" +
    "#solo-set .tiles b{font-size:19px;line-height:1.1}#solo-set .tiles small{font-size:14px;color:#9a958a}" +
    "#solo-set .tiles button.bad small{color:#f87171}" +
    "#solo-set .sw{display:flex;align-items:center;gap:14px;padding:14px 16px;border-radius:14px;border:1px solid var(--line2);background:#15140f;cursor:pointer}" +
    "#solo-set .sw span{flex:1;display:flex;flex-direction:column}#solo-set .sw b{font-size:19px}#solo-set .sw small{font-size:14px;color:#9a958a}" +
    "#solo-set .sw input{position:absolute;opacity:0;pointer-events:none}" +
    "#solo-set .sw i{width:58px;height:32px;border-radius:16px;background:#3a3830;position:relative;transition:background .15s}" +
    "#solo-set .sw i::after{content:'';position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#f4f1e8;transition:left .15s}" +
    "#solo-set .sw input:checked+i{background:#E2CE16}#solo-set .sw input:checked+i::after{left:29px}" +
    "#solo-set footer{display:flex;align-items:center;gap:12px;margin-top:2px}" +
    "#solo-set footer button{display:flex;align-items:center;gap:8px;height:46px;padding:0 16px;border-radius:12px;border:1px solid var(--line2);background:transparent;font-weight:700;font-size:16px}" +
    "#solo-set footer svg{width:20px;height:20px}#solo-set footer span{flex:1;text-align:right;font-size:12px;color:var(--muted)}" +
    "@media (orientation:portrait){#solo-set .tiles{grid-template-columns:repeat(2,minmax(0,1fr))}}";
  // Injectée par scripts/build-www.mjs : sert à savoir quelle construction tourne.
  function versionText() {
    const b = window.MYSTROW_BUILD;
    if (!b) return "";
    const os = window.Capacitor && window.Capacitor.getPlatform ? window.Capacitor.getPlatform() : "web";
    return "MyStrow tablette " + b.version + " (" + (os === "ios" ? "iPad" : os === "android" ? "Android" : os) + ")"
      + "\nConstruite le " + b.date + (b.commit ? " · " + b.commit : "");
  }

  // Le voyant EN LIGNE / HORS LIGNE parle ici de la SORTIE DMX, pas d'un PC :
  // on intercepte le toucher avant la fenêtre « connexion au PC » de la page.
  document.body.classList.add("solo");
  style.textContent += "body.solo #conn-status.ok::after{content:'DMX OK'}" +
    "body.solo #conn-status.err::after{content:'DMX COUPÉ'}" +
    "body.solo #conn-status:not(.ok):not(.err)::after{content:'DMX…'}";
  document.addEventListener("click", (e) => {
    if (!e.target.closest || !e.target.closest("#conn-status")) return;
    e.stopPropagation(); e.preventDefault();
    openOutputPanel();
  }, true);
  async function openOutputPanel() {
    if (demoOver()) {
      openMenu("DMX coupé", [["Se connecter", () => openAccount()], ...packAction()],
        "Sans licence, la sortie DMX s'arrête au bout de 10 minutes.\nConnectez-vous avec un compte MyStrow sous licence pour jouer sans limite, ou relancez l'app pour 10 nouvelles minutes.");
      return;
    }
    let detail = badge.title || "";
    try {
      const s = Dmx ? await Dmx.stats() : null;
      if (s) detail = (s.running ? "Sortie : " + s.output : badge.title || "Sortie arrêtée")
        + "\n" + s.sent + " trames envoyées, " + s.errors + " erreurs"
        + (s.lastError ? "\nDernière erreur : " + s.lastError : "");
    } catch (e) {}
    openMenu("Sortie DMX", [
      ["Relancer la sortie", () => startOutput()],
      ["Régler la sortie (USB ou node)", () => goTo("patch.html?from=play#sortie")],
      ["Tester la sortie DMX", () => goTo("dmxtest.html?from=play")],
    ], detail);
  }

  const toastEl = document.createElement("div");
  toastEl.id = "solo-toast";
  document.body.appendChild(toastEl);
  let toastTimer = null;
  function toast(text, ms) {
    toastEl.textContent = text; toastEl.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => toastEl.classList.remove("show"), ms || 1600);
  }

  // Saisie d'un nom (pas de prompt() : bloquant dans l'app).
  const ask = document.createElement("div");
  ask.id = "solo-ask"; ask.hidden = true;
  ask.innerHTML = '<form><label for="solo-ask-in"></label><input id="solo-ask-in" maxlength="32" autocomplete="off">' +
    '<div class="row"><button type="button" class="no">Annuler</button><button type="submit" class="ok">OK</button></div></form>';
  document.body.appendChild(ask);
  let askCb = null;
  function askText(title, value, cb) {
    askCb = cb;
    ask.querySelector("label").textContent = title;
    ask.querySelector("input").value = value || "";
    ask.hidden = false;
    setTimeout(() => ask.querySelector("input").focus(), 50);
  }
  ask.querySelector("form").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = ask.querySelector("input").value.trim();
    if (!v) return;
    ask.hidden = true;
    if (askCb) askCb(v);
  });
  ask.querySelector(".no").addEventListener("click", () => { ask.hidden = true; });

  // Navigation des pages : ◀ x/20 ▶ comme le PC. (Le bouton COLONNES a été
  // retiré le 12/10 : une colonne se règle par appui long sur son nom.)
  const pageNav = document.getElementById("akai-pagenav");

  // Appui long générique (650 ms, comme le reste de l'app).
  function longPress(el, onLong, onDown) {
    let timer = null;
    el.addEventListener("pointerdown", () => {
      const before = onDown ? onDown() : undefined;
      clearTimeout(timer);
      timer = setTimeout(() => onLong(before), 650);
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach((t) => el.addEventListener(t, () => clearTimeout(timer)));
    el.addEventListener("contextmenu", (e) => e.preventDefault());
  }

  // ── Choix d'un effet (boutons de droite, pads FX, éditeur) ──────────────────
  const pick = document.createElement("div");
  pick.id = "fx-pick";
  pick.hidden = true;
  pick.innerHTML = '<div class="box"><h3></h3><div class="tools"></div><div class="list"></div><button class="close" type="button">Annuler</button></div>';
  document.body.appendChild(pick);
  let pickCancel = null;
  // opts : {title, current, onPick(name), onCancel, tools: [[label, fn]], kind}
  function openPicker(opts) {
    pickCancel = opts.onCancel || null;
    pick.querySelector("h3").textContent = opts.title;
    const tools = pick.querySelector(".tools");
    tools.innerHTML = "";
    (opts.tools || []).forEach(([label, fn]) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label;
      b.addEventListener("click", () => { pick.hidden = true; fn(); });
      tools.appendChild(b);
    });
    tools.hidden = !(opts.tools || []).length;
    const list = pick.querySelector(".list");
    list.innerHTML = "";
    let cat = null;
    const items = opts.items || [...customFx.map((e) => ({ ...e, category: "Mes effets" })), ...Library.effects];
    items.forEach((e) => {
      if (e.category !== cat) {
        cat = e.category;
        const h = document.createElement("div"); h.className = "cat"; h.textContent = (cat || "").toUpperCase();
        list.appendChild(h);
      }
      const b = document.createElement("button");
      b.type = "button"; b.textContent = e.label || e.name;
      b.className = [e.category === "Mes effets" ? "mine" : "", e.cls || "", e.name === opts.current ? "cur" : ""].join(" ").trim();
      b.addEventListener("click", () => { pick.hidden = true; opts.onPick(e.value !== undefined ? e.value : e.name); });
      list.appendChild(b);
    });
    pick.hidden = false;
  }
  pick.querySelector(".close").addEventListener("click", () => {
    pick.hidden = true;
    if (pickCancel) pickCancel();
  });
  const editor = () => window.MystrowFxEditor;
  // Créer / modifier un effet puis le poser sur un bouton ou un pad (assign).
  function editTools(current, assign) {
    const t = [];
    if (editor()) {
      t.push(["＋ Créer un effet", () => editor().open(null, assign)]);
      if (current && getEffect(current)) t.push(["✎ Modifier « " + current + " »", () => editor().open(current, assign)]);
    }
    return t;
  }

  // Nom de l'effet dans chaque bouton + appui long = changer d'effet.
  const effBtns = [...document.querySelectorAll("#effects .eff-btn")];
  function labelEffects() {
    effBtns.forEach((el, r) => { el.textContent = play.buttons[r] || "—"; });
  }
  function assignButton(r, name, launch) {
    play.buttons[r] = name;
    const entry = { src: "btn", row: r };
    if (launch && !isRunning(entry)) toggleEntry(entry);
    fxChanged(); savePlay(); refresh(true);
  }
  effBtns.forEach((el, r) => longPress(el, (before) => {
    // L'appui a déjà basculé l'effet : on remet ce qui tournait avant.
    play.fxStack = before; fxChanged(); refresh(true);
    openPicker({
      title: "Effet du bouton " + (r + 1), current: play.buttons[r],
      tools: editTools(play.buttons[r], (name) => assignButton(r, name, true)),
      onPick: (name) => assignButton(r, name, true),
    });
  }, () => play.fxStack.slice()));

  // Gestion des effets (⚙ Réglages) : choisir un effet = l'ouvrir dans l'éditeur.
  function openFxManager() {
    if (!editor()) return;
    openPicker({ title: "Éditeur d'effets : choisir un effet à modifier",
      tools: [["＋ Créer un effet", () => editor().open(null)]],
      onPick: (name) => editor().open(name) });
  }

  // ── Réglages de l'AKAI : comme AkaiLayoutEditorDialog du PC ───────────────
  // La page (◀ ▶) et ses 8 faders ; sous chacun, un bouton qui dit ce qu'il
  // pilote. Le toucher ouvre la liste de tout ce qu'on peut lui donner
  // (groupes, mémoires, effets, positions, vide). Le 9e (VIT) n'est pas
  // réglable, comme sur le PC. Appui long sur le nom d'un fader de l'onglet
  // AKAI = la même liste, directement.
  const colsDlg = document.createElement("div");
  colsDlg.id = "solo-cols"; colsDlg.hidden = true;
  colsDlg.innerHTML = '<div class="box" role="dialog" aria-modal="true" aria-labelledby="cols-t">' +
    '<header><h2 id="cols-t">Réglages de l\'AKAI</h2><button type="button" class="x" aria-label="Fermer">✕</button></header>' +
    '<div class="pg"><button type="button" class="pp" aria-label="Page précédente">◀</button><b></b>' +
    '<button type="button" class="pn" aria-label="Page suivante">▶</button><small>Touchez le bouton sous un fader pour choisir ce qu\'il pilote.</small></div>' +
    '<div class="board"></div>' +
    '<div class="ttl">DISPOSITIONS TOUTES FAITES <small>pour cette page</small></div><div class="presets"></div>' +
    '<label class="sw"><span><b>Superposition d\'effets</b><small></small></span><input type="checkbox"><i></i></label></div>';
  document.body.appendChild(colsDlg);
  const $c = (q) => colsDlg.querySelector(q);
  colsDlg.addEventListener("click", (e) => { if (e.target === colsDlg) colsDlg.hidden = true; });
  $c(".x").addEventListener("click", () => { colsDlg.hidden = true; });
  const goPage = (d) => { play.pageIdx = (play.pageIdx + d + N_PAGES) % N_PAGES; savePlay(); pageMsgs(); renderColumns(); };
  $c(".pp").addEventListener("click", () => goPage(-1));
  $c(".pn").addEventListener("click", () => goPage(1));
  const copyBtn = document.createElement("button");
  copyBtn.type = "button"; copyBtn.textContent = "Copier la page précédente";
  copyBtn.addEventListener("click", () => {
    play.pages[play.pageIdx] = play.pages[(play.pageIdx + N_PAGES - 1) % N_PAGES].map((x) => ({ ...x }));
    savePlay(); pageMsgs(); refresh(true); renderColumns();
  });
  PAGE_PRESETS.forEach(([label, slots]) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = label;
    b.addEventListener("click", () => { play.pages[play.pageIdx] = slots.map((x) => ({ ...x })); savePlay(); pageMsgs(); refresh(true); renderColumns(); });
    $c(".presets").appendChild(b);
  });
  $c(".presets").appendChild(copyBtn);
  const swIn = $c(".sw input");
  const swText = () => { $c(".sw small").textContent = play.superpose
    ? "Les effets s'ajoutent : un 2e effet tourne par-dessus le 1er" : "Un seul effet à la fois : le nouveau remplace l'ancien"; };
  swIn.addEventListener("change", () => {
    play.superpose = swIn.checked;
    if (!play.superpose && play.fxStack.length > 1) play.fxStack = play.fxStack.slice(-1);
    savePlay(); fxChanged(); refresh(true); swText();
  });
  const sameSlot = (a, b) => a.type === b.type && a.group === b.group && a.mem_col === b.mem_col && a.fx_col === b.fx_col && a.pos_col === b.pos_col;
  // Nom long d'une affectation (bouton sous le fader, liste de choix).
  const slotName = (sl) => sl.type === "memory" ? "MEM " + (sl.mem_col + 1) : sl.type === "none" ? "Vide" : slotLabel(sl);
  function renderColumns() {
    $c(".pg b").textContent = "PAGE " + (play.pageIdx + 1) + " / " + N_PAGES;
    const board = $c(".board");
    board.innerHTML = "";
    curPage().forEach((sl, c) => {
      const col = document.createElement("div");
      col.className = "bc k-" + sl.type;
      col.innerHTML = '<small></small><div class="fd"><i></i></div><button type="button" class="pick"></button>';
      col.querySelector("small").textContent = c + 1;
      const b = col.querySelector(".pick");
      b.textContent = slotName(sl) + " ▾";
      b.addEventListener("click", () => pickSlot(c));
      board.appendChild(col);
    });
    const f9 = document.createElement("div");
    f9.className = "bc f9";
    f9.innerHTML = '<small>9</small><div class="fd"><i></i></div><span>VIT</span>';
    board.appendChild(f9);
    swIn.checked = !!play.superpose; swText();
  }
  function openColumns() {
    renderColumns();
    colsDlg.hidden = false;
  }

  // Liste de choix d'un fader : tout ce qu'on peut lui donner, rangé par type.
  const slotDlg = document.createElement("div");
  slotDlg.id = "solo-slot"; slotDlg.hidden = true;
  slotDlg.innerHTML = '<div class="box" role="dialog" aria-modal="true"><header><h2></h2>' +
    '<button type="button" class="x" aria-label="Fermer">✕</button></header><div class="list"></div></div>';
  document.body.appendChild(slotDlg);
  slotDlg.addEventListener("click", (e) => { if (e.target === slotDlg) slotDlg.hidden = true; });
  slotDlg.querySelector(".x").addEventListener("click", () => { slotDlg.hidden = true; });
  function slotSections() {
    const sec = [];
    sec.push(["group", "COULEURS", "les pads donnent la couleur du groupe, le fader règle son niveau",
      GROUPS.map((g) => [gSlot(g), g, byGroup[g] ? byGroup[g].length + " proj." : "vide"])]);
    const mems = [];
    for (let m = 0; m < MEM_COL_MAX; m++) {
      const n = [0, 1, 2, 3, 4, 5, 6, 7].filter((r) => play.memories[memKey(r, m)]).length;
      if (m >= 16 && !n) continue;                  // au-delà de 16 : celles qui ont des mémoires
      mems.push([mSlot(m), "MEM " + (m + 1), n ? n + " mém." : "vide"]);
    }
    sec.push(["memory", "MÉMOIRES", "8 mémoires par colonne, le fader règle leur niveau", mems]);
    const fx = [];
    for (let f = 0; f < FX_COL_MAX; f++) {
      const n = (play.fxPads[f] || []).filter(Boolean).length;
      fx.push([{ type: "fx", fx_col: f }, "FX " + (f + 1), n ? n + " effet" + (n > 1 ? "s" : "") : "vide"]);
    }
    sec.push(["fx", "EFFETS", "8 effets par colonne, le fader règle l'amplitude", fx]);
    const pos = [];
    for (let q = 0; q < POS_COL_MAX; q++) {
      const n = (play.posPresets[q] || []).filter(Boolean).length;
      pos.push([{ type: "pos", pos_col: q }, "POS " + (q + 1), n ? n + " pos." : "vide"]);
    }
    sec.push(["pos", "POSITIONS", "8 positions de lyres" + (hasLyres ? "" : " (pas de lyre dans le patch)"), pos]);
    sec.push(["none", "AUTRE", "", [[{ type: "none" }, "Vide", "rien"]]]);
    return sec;
  }
  function pickSlot(col) {
    const cur = curPage()[col];
    slotDlg.querySelector("h2").textContent = "Fader " + (col + 1) + " · page " + (play.pageIdx + 1);
    const list = slotDlg.querySelector(".list");
    list.innerHTML = "";
    slotSections().forEach(([kind, title, hint, opts]) => {
      const h = document.createElement("div");
      h.className = "st"; h.innerHTML = "<b></b><small></small>";
      h.querySelector("b").textContent = title; h.querySelector("small").textContent = hint;
      const g = document.createElement("div");
      g.className = "vals k-" + kind;
      opts.forEach(([slot, label, sub]) => {
        const b = document.createElement("button");
        b.type = "button"; b.className = sameSlot(slot, cur) ? "on" : "";
        b.innerHTML = "<b></b><small></small>";
        b.querySelector("b").textContent = label; b.querySelector("small").textContent = sub;
        b.addEventListener("click", () => {
          curPage()[col] = slot; savePlay(); pageMsgs(); refresh(true);
          slotDlg.hidden = true;
          if (!colsDlg.hidden) renderColumns();
        });
        g.appendChild(b);
      });
      list.append(h, g);
    });
    slotDlg.hidden = false;
    const on = list.querySelector("button.on");
    if (on) on.scrollIntoView({ block: "center" });
  }
  // Nom sous un fader : appui long = choisir ce qu'il pilote.
  faderLbls.forEach((el, c) => { if (el) longPress(el, () => pickSlot(c)); });

  // ── Sortie DMX ─────────────────────────────────────────────────────────────
  let outOk = null;
  function setOutputState(ok, text) {
    badge.title = text;   // l'état se lit sur le voyant DMX OK / DMX COUPÉ
    outOk = ok;
    paintStatus();
  }
  // Démo de 10 min écoulée = DMX COUPÉ, quel que soit l'état de l'interface.
  const demoOver = () => !licensed && demoLeft() <= 0;
  function paintStatus() {
    if (outOk === null && !demoOver()) return;
    const ok = outOk && !demoOver();
    try { _conn.state = ok ? "ok" : "err"; } catch (e) {}
    statusEl.textContent = ok ? "✓" : "⚠";
    statusEl.className = ok ? "ok" : "err";
  }

  let retryTimer = null;
  async function startOutput() {
    clearTimeout(retryTimer);
    if (!Dmx) { setOutputState(false, "Module DMX absent"); return; }
    const o = show.output || {};
    try {
      await Dmx.start(o.transport === "artnet"
        ? { transport: "artnet", host: o.host || "2.0.0.15", port: 6454, fps: 40 }
        : { transport: "usb", fps: 30 });
      lastSent = "";
      output();
      const s = await Dmx.stats();
      setOutputState(true, "Sortie : " + s.output);
    } catch (e) {
      setOutputState(false, "Sortie DMX : " + (e.message || e) + ". Nouvel essai toutes les 20 s.");
      // Interface débranchée ou refusée : on réessaie toutes les 20 s
      // (un seul essai en attente, même si on appuie sur « Relancer »).
      clearTimeout(retryTimer);
      retryTimer = setTimeout(startOutput, 20000);
    }
  }

  // Pad POSITION : boutons SYM PAN, SYM TILT (symétrie) et CENTRER.
  const ptLbl = document.getElementById("proj-pantilt-lbl");
  if (ptLbl) {
    const head = document.createElement("div");
    head.className = "solo-pt-head";
    ptLbl.before(head);
    head.appendChild(ptLbl);
    const symBtns = [["symPan", "SYM PAN", "gauche ↔ droite"], ["symTilt", "SYM TILT", "haut ↕ bas"]].map(([key, label, sens]) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label;
      b.title = "Symétrie : les lyres de l'autre côté partent en miroir (" + sens + ")";
      const paint = () => b.classList.toggle("on", !!play[key]);
      b.addEventListener("click", () => { play[key] = !play[key]; symDrag = null; paint(); savePlay(); });
      paint();
      return b;
    });
    const ctrBtn = document.createElement("button");
    ctrBtn.type = "button"; ctrBtn.textContent = "CENTRER";
    ctrBtn.addEventListener("click", () => {
      let idxs = [];
      try { idxs = _selIdxs(); } catch (e) {}
      idxs.forEach((i) => { if (projectors[i]) setPos(projectors[i], i, [32768, 32768]); });
      symDrag = null; savePlay(); refresh(true); redrawPad();
    });
    symBtns.forEach((b) => head.appendChild(b));
    head.appendChild(ctrBtn);
  }

  // TAILLE MVT retiré le 12/10/2026 (jugé inutile) : les effets de mouvement
  // jouent à leur taille d'origine, y compris si une ancienne valeur était sauvée.
  play.moveSize = 100;
  // Le panneau d'un projecteur peut dépasser la hauteur de l'écran : on le fait défiler.
  const pp = document.getElementById("proj-panel");
  if (pp) { pp.style.maxHeight = "92vh"; pp.style.overflowY = "auto"; }

  // Pad POSITION : un point par lyre sélectionnée (la page ne dessine que
  // celle qu'on pilote). Les autres viennent de la visée réelle — en SYM on
  // les voit partir en miroir.
  if (typeof drawPanTiltPad === "function") {
    const drawOne = drawPanTiltPad;
    window.drawPanTiltPad = function (p) {
      drawOne(p);
      let idxs = [], sel = -1;
      try { idxs = _selIdxs(); sel = _selectedProjIdx; } catch (e) { return; }
      const cv = document.getElementById("proj-pantilt-pad"), ctx = cv.getContext("2d");
      idxs.forEach((i) => {
        const q = projectors[i];
        if (i === sel || !q || !Engine.isLyre(q)) return;
        const x = (q.pos[0] / 65535) * cv.width, y = (q.pos[1] / 65535) * cv.height;
        ctx.beginPath(); ctx.arc(x, y, 7, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(226,206,22,.35)"; ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,.7)"; ctx.lineWidth = 1.5; ctx.stroke();
        ctx.fillStyle = "#fff"; ctx.font = "bold 10px sans-serif"; ctx.textAlign = "center";
        ctx.fillText(q.name || "", x, y - 11);
      });
      // Effet rapide ou effet de mouvement en cours : un anneau suit la visée
      // réelle (sortie DMX) autour du point de base.
      idxs.forEach((i) => {
        const q = projectors[i], st = lastStates[i];
        if (!q || !Engine.isLyre(q) || !st || st.pan == null || st.tilt == null) return;
        if (Math.abs(st.pan - q.pos[0]) < 200 && Math.abs(st.tilt - q.pos[1]) < 200) return;
        const bx = (q.pos[0] / 65535) * cv.width, by = (q.pos[1] / 65535) * cv.height;
        ctx.strokeStyle = "rgba(226,206,22,.7)"; ctx.lineWidth = 2;   // + = centre de l'effet (la visée réglée)
        ctx.beginPath(); ctx.moveTo(bx - 7, by); ctx.lineTo(bx + 7, by); ctx.moveTo(bx, by - 7); ctx.lineTo(bx, by + 7); ctx.stroke();
        const x = (st.pan / 65535) * cv.width, y = (st.tilt / 65535) * cv.height;
        ctx.beginPath(); ctx.arc(x, y, 8, 0, Math.PI * 2);
        ctx.fillStyle = "rgba(255,255,255,.9)"; ctx.fill();
        ctx.strokeStyle = "#E2CE16"; ctx.lineWidth = 3; ctx.stroke();
      });
    };
  }
  function redrawPad() {
    try {
      if (projPanel.classList.contains("open") && _projectors[_selectedProjIdx]) drawPanTiltPad(_projectors[_selectedProjIdx]);
    } catch (e) {}
  }

  // Appui long sur un pad : menu selon la colonne (mémoire, effet, position).
  // L'appui a déjà agi (rappel, bascule) comme sur l'AKAI ; pour un pad FX on
  // remet l'effet d'avant, le menu sert à régler le pad, pas à le jouer.
  document.querySelectorAll("#grid .pad").forEach((el) => longPress(el, (before) => {
    if (recArmed || !before) return;
    const r = +el.dataset.r, c = +el.dataset.c, s = slotAt(c);
    if (!s) return;
    if (s.type === "memory") {
      const k = memKey(r, s.mem_col);
      if (!play.memories[k]) return;
      openMenu("Mémoire " + (s.mem_col + 1) + "." + (r + 1), [
        ["Remplacer par ce qui joue", () => { recordMemory(s.mem_col, r); savePlay(); allPads(); refresh(true); toast("Mémoire remplacée"); }],
        ["Effacer la mémoire", () => {
          delete play.memories[k];
          if (play.memRows[s.mem_col] === r) delete play.memRows[s.mem_col];
          savePlay(); fxChanged(); refresh(true);
          toast("Mémoire effacée");
        }, "danger"],
      ]);
    } else if (s.type === "fx") {
      play.fxStack = before.stack; fxChanged(); refresh(true);
      const f = s.fx_col, list = play.fxPads[f] = play.fxPads[f] || [];
      const assign = (name) => { list[r] = name; savePlay(); fxChanged(); refresh(true); };
      openPicker({ title: "Pad FX " + (f + 1) + "." + (r + 1), current: list[r],
        tools: [...editTools(list[r], assign), ...(list[r] ? [["✕ Vider le pad", () => {
          play.fxStack = play.fxStack.filter((e) => !sameEntry(e, { src: "pad", f, row: r }));
          list[r] = null; savePlay(); fxChanged(); refresh(true);
        }]] : [])],
        onPick: assign });
    } else if (s.type === "pos") {
      const pc = s.pos_col, list = play.posPresets[pc] = play.posPresets[pc] || [], pr = list[r];
      openMenu("Position " + (pc + 1) + "." + (r + 1) + (pr ? " · " + pr.name : ""), [
        ["Enregistrer la visée actuelle ici", () => askText("Nom de la position", pr ? pr.name : "Pos " + (pc + 1) + "-" + (r + 1),
          (name) => { recordPosition(pc, r, name); savePlay(); })],
        ...(pr ? [["Renommer", () => askText("Nom de la position", pr.name, (name) => { pr.name = name; savePlay(); padsOfType("pos"); })],
                  ["Effacer", () => { list[r] = null; if (play.posActive[pc] === r) delete play.posActive[pc]; savePlay(); padsOfType("pos"); }, "danger"]] : []),
      ]);
    }
  }, () => ({ stack: play.fxStack.slice() })));

  // Menu contextuel partagé (mémoires ici, playlist et cartouches dans media.js).
  const menu = document.createElement("div");
  menu.id = "solo-menu"; menu.hidden = true;
  menu.innerHTML = '<div class="box"><h3></h3><p class="info" hidden style="margin:0 0 4px;white-space:pre-line;' +
    'color:#cfcabd;font-size:14px;line-height:1.4"></p><div class="acts" style="display:flex;flex-direction:column;gap:8px"></div></div>';
  menu.addEventListener("click", (e) => { if (e.target === menu) menu.hidden = true; });
  document.body.appendChild(menu);
  function openMenu(title, actions, info) {
    menu.querySelector("h3").textContent = title;
    const p = menu.querySelector(".info");
    p.textContent = info || ""; p.hidden = !info;
    const acts = menu.querySelector(".acts");
    acts.innerHTML = "";
    [...actions, ["Fermer", null]].forEach(([label, fn, cls]) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label; if (cls) b.className = cls;
      b.addEventListener("click", async () => { menu.hidden = true; if (fn) await fn(); });
      acts.appendChild(b);
    });
    menu.hidden = false;
  }


  // Onglet MEDIA masqué en mode sans PC (décision du 24/09/2026) : sans lien
  // avec la lumière, un simple lecteur de musique n'apportait rien. media.js
  // reste prêt (playlist, cartouches) : passer MEDIA_SOLO à true pour le rendre.
  // SURFACE (exécuteurs du PC) n'a rien à montrer sans PC : masqué aussi.
  const MEDIA_SOLO = false;
  const hiddenTabs = ["surface-page", ...(MEDIA_SOLO ? [] : ["media-page"])];
  hiddenTabs.forEach((id) => {
    const tab = document.querySelector('.tab-btn[data-tab="' + id + '"]');
    if (tab) tab.hidden = true;
  });
  style.textContent += ".tab-btn[hidden]{display:none}";

  // Effets rapides dans le panneau d'un projecteur (SCÈNE). Comme le PC :
  // lyres = mouvements, PAR = couleurs ; sélection mêlant lyres et PAR ou
  // machines à effet (fumée…) = pas d'effets rapides.
  const qeRow = document.createElement("div");
  qeRow.id = "solo-qe";
  qeRow.innerHTML = '<div class="qe-lbl">EFFETS RAPIDES</div><div class="qe-btns"></div><div class="qe-sliders"></div>';
  const panelBtns = document.getElementById("proj-panel-btns");
  if (panelBtns) panelBtns.before(qeRow);
  const QE_SLIDERS = [["speed", "VITESSE", false], ["amp", "AMPLITUDE", true], ["phase", "DÉPHASAGE", false]];
  function buildQuickRow() {
    let idxs = [];
    try { idxs = _selIdxs().filter((i) => projectors[i]); } catch (e) {}
    const sel = idxs.map((i) => projectors[i]);
    const lyres = sel.filter((p) => Engine.isLyre(p)).length;
    const machines = sel.filter((p) => Engine.isFxMachine(p)).length;
    const leds = sel.length - lyres - machines;
    const kind = machines || !sel.length || (lyres && leds) ? null : lyres ? "lyre" : "led";
    qeRow.hidden = !kind;
    if (!kind) return;
    const active = play.qfx[idxs[idxs.length - 1]];
    const btns = qeRow.querySelector(".qe-btns");
    btns.innerHTML = "";
    (kind === "lyre" ? QE_LYRE : QE_LED).forEach(([key, icon, label]) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = icon; b.title = label;
      b.className = active === key ? "on" : "";
      b.addEventListener("click", () => { window.MYSTROW_SEND({ type: "proj_qfx", idxs, key }); buildQuickRow(); });
      btns.appendChild(b);
    });
    const stop = document.createElement("button");
    stop.type = "button"; stop.textContent = "■"; stop.title = "Arrêter"; stop.className = "stop";
    stop.addEventListener("click", () => { window.MYSTROW_SEND({ type: "proj_qfx", idxs, key: null }); buildQuickRow(); });
    btns.appendChild(stop);
    const sl = qeRow.querySelector(".qe-sliders");
    sl.innerHTML = "";
    QE_SLIDERS.forEach(([param, label, lyreOnly]) => {
      if (lyreOnly && kind !== "lyre") return;
      const r = document.createElement("label");
      r.innerHTML = "<span></span><input type=\"range\" min=\"0\" max=\"100\"><b></b>";
      r.querySelector("span").textContent = label;
      const inp = r.querySelector("input"), val = r.querySelector("b");
      inp.value = play.qe[param]; val.textContent = play.qe[param];
      inp.addEventListener("input", () => { val.textContent = inp.value; window.MYSTROW_SEND({ type: "proj_qe", param, value: +inp.value }); });
      // Double-tap = valeur naturelle (50), ou 0 pour le déphasage.
      inp.addEventListener("dblclick", () => { inp.value = param === "phase" ? 0 : 50; inp.dispatchEvent(new Event("input")); });
      sl.appendChild(r);
    });
  }
  // Le panneau est ouvert par la page (openProjPanel) : on complète après elle.
  if (typeof window.openProjPanel === "function") {
    const openOrig = window.openProjPanel;
    window.openProjPanel = function (idx) { openOrig(idx); buildQuickRow(); };
  }
  style.textContent += "#solo-qe{display:flex;flex-direction:column;gap:8px;padding-top:4px}#solo-qe[hidden]{display:none}" +
    "#solo-qe .qe-lbl{font-family:var(--f-label);font-weight:700;font-size:12px;letter-spacing:1.5px;color:var(--muted)}" +
    "#solo-qe .qe-btns{display:flex;gap:6px;flex-wrap:wrap}" +
    "#solo-qe .qe-btns button{min-width:52px;height:44px;padding:0 10px;border-radius:10px;border:1px solid var(--line2);background:var(--bg3);" +
    "color:var(--text);font-size:20px;font-weight:700;cursor:pointer;touch-action:manipulation}" +
    "#solo-qe .qe-btns button.on{background:rgba(226,206,22,.16);border-color:#E2CE16;color:#E2CE16}" +
    "#solo-qe .qe-btns button.stop{color:#f87171;border-color:rgba(248,113,113,.45);font-size:16px}" +
    "#solo-qe .qe-sliders{display:flex;flex-direction:column;gap:4px}" +
    "#solo-qe .qe-sliders label{display:grid;grid-template-columns:96px 1fr 34px;align-items:center;gap:8px}" +
    "#solo-qe .qe-sliders span{font-family:var(--f-label);font-weight:700;font-size:12px;letter-spacing:1.2px;color:var(--muted)}" +
    "#solo-qe .qe-sliders input{width:100%;accent-color:#E2CE16}" +
    "#solo-qe .qe-sliders b{font-family:var(--f-label);font-size:14px;color:var(--text);text-align:right;font-variant-numeric:tabular-nums}";

  // ── Effets perso (éditeur : fxeditor.js) ─────────────────────────────────────
  // Enregistre un effet perso. `oldName` : nom d'avant (renommage) ⇒ boutons
  // et pads qui le portaient suivent.
  function saveCustomEffect(fx, oldName) {
    const clean = { name: fx.name, category: "Mes effets", custom: true,
                    no_color: !!fx.no_color, layers: JSON.parse(JSON.stringify(fx.layers || [])) };
    const i = customFx.findIndex((e) => e.name === (oldName || fx.name));
    if (i >= 0) customFx[i] = clean; else customFx.unshift(clean);
    if (oldName && oldName !== fx.name) {
      play.buttons = play.buttons.map((n) => (n === oldName ? fx.name : n));
      Object.values(play.fxPads).forEach((list) => (list || []).forEach((n, r) => { if (n === oldName) list[r] = fx.name; }));
      play.fxStack.forEach((e) => { if (e.src === "name" && e.name === oldName) e.name = fx.name; });
    }
    save("mystrow.solo.fx", customFx);
    indexEffects(); savePlay(); fxChanged();
  }
  function deleteCustomEffect(name) {
    customFx = customFx.filter((e) => e.name !== name);
    save("mystrow.solo.fx", customFx);
    indexEffects();
    play.fxStack = play.fxStack.filter((e) => getEffect(entryName(e)));
    savePlay(); fxChanged();
  }

  // Pour media.js (playlist, cartouches) : même canal de messages vers la page.
  window.MystrowSolo = { emit, toast, openMenu, askText, mediaEnabled: MEDIA_SOLO,
    // Pour live.js et fxeditor.js : ils jouent sur le MÊME état que l'AKAI.
    core: { show, play, projectors, GROUPS, COLORS, SPEED, byGroup, usedGroups, effectByName, hold,
            setEffect, refresh, savePlay, snapshot, recall, clearGroupOverrides, allPads, padMsgs,
            setGroupColor, setGroupLevel, openSettings, openOutputPanel, emit,
            getEffect, builtinByName, customEffects: () => customFx, saveCustomEffect, deleteCustomEffect,
            setPreview, lastStates: () => lastStates, isLyre: Engine.isLyre, shapes: Library.shapes || {},
            openPicker, longPress,
            setLiveHook: (h) => { liveHook = h; }, runTimer } };

  // ── État initial ───────────────────────────────────────────────────────────
  const { states } = baseStates();
  const pads = {};
  for (let c = 0; c < 8; c++) for (let r = 0; r < 8; r++) pads[r + "_" + c] = padLook(r, c);
  emit({
    type: "state",
    data: {
      pads,
      faders: Object.fromEntries([...curPage().map((_, c) => faderValue(c)), play.faders[SPEED]].map((v, i) => [String(i), v])),
      effects: {},
      layout: curPage().map((s) => ({ label: slotLabel(s), type: s.type })),
      seq: { items: [], current_row: -1, playing: false },
      carts: [],
      projectors: projectors.map((p, i) => ({
        name: p.name, group: p.group, x: p.x, y: p.y,
        ...projColors([states[i]])[0],
        is_lyre: Engine.isLyre(p), ftype: p.fixture_type || "",
        ...wheelMeta(p),
      })),
      bank_pages: { count: N_PAGES, index: play.pageIdx },
      rec_active: false,
      surface: { cols: 1, rows: 1, blocks: [] },
    },
  });
  play.fxStack.forEach((e) => { e.t0 = 0; });
  pageMsgs();
  fxChanged();                              // relance aussi la boucle des effets sauvegardés
  refresh(true);
  startOutput();
  window.addEventListener("pagehide", () => { if (Dmx) Dmx.stop().catch(() => {}); });

  // iPad / iPhone : iOS gèle l'app ~30 s après la bascule en arrière-plan, et le
  // DMX s'arrête (le natif reprend seul au retour). On le dit au retour.
  const IOS = !!(window.Capacitor && window.Capacitor.getPlatform && window.Capacitor.getPlatform() === "ios");
  let hiddenAt = 0;
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      hiddenAt = Date.now();
      // FLASH / NOIR maintenus : le doigt ne sera jamais « relâché » si l'app part en arrière-plan.
      if (hold.flash || hold.black) {
        hold.flash = hold.black = false;
        refresh(true);
        if (window.MystrowLive) window.MystrowLive.render();
      }
      return;
    }
    lastSent = ""; output();   // renvoie la trame courante au natif
    if (IOS && hiddenAt && Date.now() - hiddenAt > 25000)
      toast("Sur iPad, le DMX s'arrête si MyStrow reste en arrière-plan. Gardez l'app au premier plan pendant le show (Accès guidé).", 7000);
    hiddenAt = 0;
  });
})();
