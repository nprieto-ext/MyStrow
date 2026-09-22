// Mode autonome de l'app : la tablette pilote les projecteurs SANS PC.
//
// Chargé à la fin de remote.html (voir scripts/build-www.mjs), actif seulement
// avec ?solo=1. Même contrat que demo.js : il remplace le PC — les actions de
// l'interface (window.MYSTROW_SEND) modifient l'état, renvoyé à la page sous
// forme de messages identiques au flux SSE (_handleMsg). Mais ici l'état est
// réel : engine.js le traduit en DMX, envoyé par le module natif MystrowDmx
// (interface USB-DMX ou node Art-Net).
//
// v1 : colonnes AKAI = groupes A à H du patch (patch.html), pads = couleur du
// groupe, faders = niveau du groupe, VIT = vitesse du strobe, effet 1 = strobe.
(function () {
  "use strict";
  if (!window.MYSTROW_SOLO) return;

  const Engine = window.MystrowEngine;
  const Dmx = window.Capacitor && window.Capacitor.Plugins && window.Capacitor.Plugins.MystrowDmx;
  const COLORS = ["#ffffff", "#ff0000", "#ff8800", "#ffdd00", "#00ff00", "#00dddd", "#0000ff", "#ff00ff"];
  const GROUPS = ["A", "B", "C", "D", "E", "F", "G", "H"];
  const SPEED = 8;                                  // 9e fader « VIT »
  const STROBE_ROW = 0;                             // 1er bouton d'effet

  // ── Show (patch) et état du jeu, gardés sur la tablette ─────────────────────
  function load(key, def) {
    try { const v = JSON.parse(localStorage.getItem(key) || "null"); return v || def; } catch (e) { return def; }
  }
  function save(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch (e) {} }

  const show = load("mystrow.solo.show", { fixtures: [], output: { transport: "usb" } });
  const play = load("mystrow.solo.play", {
    active: {},                                     // colonne → rangée de couleur (ou absent)
    faders: [100, 100, 100, 100, 100, 100, 100, 100, 50],
    strobe: false,
  });
  const savePlay = () => save("mystrow.solo.play", play);

  // Projecteurs du plan de feu : un rang par groupe, dans l'ordre du patch.
  const projectors = show.fixtures.map((f) => ({ ...f, override: null }));
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

  // ── État → projecteurs → DMX ────────────────────────────────────────────────
  // Réglage par projecteur (onglet SCÈNE) prioritaire, remis à zéro dès que la
  // colonne de son groupe change sur l'AKAI.
  function fixtureState(p) {
    const col = GROUPS.indexOf(p.group);
    const row = play.active[col];
    const o = p.override || {};
    const hasColor = o.color !== undefined || (row !== undefined && row !== null);
    return {
      address: p.address, profile: p.profile,
      color: o.color ?? (hasColor ? COLORS[row] : "#000000"),
      level: hasColor ? (o.level ?? play.faders[col] ?? 0) : 0,
      muted: !!o.muted,
      strobe: o.strobe ?? (play.strobe ? Math.max(1, play.faders[SPEED]) : 0),
    };
  }

  const frame = new Uint8Array(512);
  let lastSent = "";
  function output() {
    const states = projectors.map(fixtureState);
    Engine.render(states, frame);
    const key = frame.join(",");
    if (key !== lastSent && Dmx) {
      lastSent = key;
      Dmx.setChannels({ start: 1, values: Array.from(frame) }).catch(() => {});
    }
    return states;
  }

  function projColors(states) {
    return states.map((s) => ({
      color: s.color, base_color: s.color, level: s.level, muted: s.muted,
      lit: !s.muted && s.level > 0 && s.color !== "#000000", strobe: s.strobe,
    }));
  }

  // ── Messages vers la page (mêmes formats que le flux SSE du PC) ────────────
  function emit(msg) {
    try { _conn.lastMsg = Date.now(); } catch (e) {}
    _handleMsg(msg);
  }
  function padMsgs(col) {
    for (let r = 0; r < 8; r++) emit({ type: "pad", row: r, col, color: COLORS[r], bright: play.active[col] === r ? 100 : 20 });
  }
  function refresh() { emit({ type: "proj_colors", data: projColors(output()) }); }
  function clearGroupOverrides(col) {
    (byGroup[GROUPS[col]] || []).forEach((p) => { p.override = null; });
  }
  function each(idxs, fn) {
    (idxs || []).forEach((i) => { const p = projectors[i]; if (p) { p.override = p.override || {}; fn(p.override); } });
  }

  // ── Actions de l'interface ─────────────────────────────────────────────────
  window.MYSTROW_SEND = function (ev) {
    switch (ev && ev.type) {
      case "pad":
        // Même pad une seconde fois = la colonne s'éteint.
        if (play.active[ev.col] === ev.row) delete play.active[ev.col];
        else play.active[ev.col] = ev.row;
        clearGroupOverrides(ev.col);
        padMsgs(ev.col);
        break;
      case "fader":
        play.faders[ev.idx] = ev.value;
        emit({ type: "fader", idx: ev.idx, value: ev.value });
        if (ev.idx < 8) (byGroup[GROUPS[ev.idx]] || []).forEach((p) => { if (p.override) delete p.override.level; });
        break;
      case "effect":
        if (ev.row === STROBE_ROW) {
          play.strobe = !play.strobe;
          emit({ type: "effect", row: ev.row, active: play.strobe });
        }
        break;
      case "clear":
        play.active = {};
        play.strobe = false;
        projectors.forEach((p) => { p.override = null; });
        for (let c = 0; c < 8; c++) padMsgs(c);
        emit({ type: "effect", row: STROBE_ROW, active: false });
        break;
      case "proj_color": each(ev.idxs, (o) => { o.color = ev.color; if (o.level === undefined) o.level = 100; }); break;
      case "proj_level": each(ev.idxs, (o) => { o.level = ev.value; }); break;
      case "proj_mute": each(ev.idxs, (o) => { o.muted = !!ev.muted; }); break;
      case "proj_strobe": each(ev.idxs, (o) => { o.strobe = ev.value; }); break;
      case "scene_clear":
        projectors.forEach((p) => { p.override = null; });
        break;
      default:
        return;   // playlist, cartouches, REC… : pas encore en mode autonome
    }
    savePlay();
    refresh();
  };

  // ── Sortie DMX ─────────────────────────────────────────────────────────────
  const badge = document.createElement("button");
  const style = document.createElement("style");
  style.textContent =
    "#solo-badge{flex-shrink:0;height:100%;padding:0 12px;border-radius:10px;border:1px solid rgba(226,206,22,.45);" +
    "background:rgba(226,206,22,.10);color:#E2CE16;font-family:var(--f-label);font-weight:700;font-size:13px;" +
    "letter-spacing:1.5px;cursor:pointer;touch-action:manipulation;white-space:nowrap}" +
    "#solo-badge.err{border-color:rgba(248,113,113,.6);background:rgba(248,113,113,.12);color:#f87171}";
  document.head.appendChild(style);
  badge.id = "solo-badge";
  badge.type = "button";
  badge.textContent = "SANS PC";
  badge.title = "Mode autonome : la tablette pilote les projecteurs. Toucher pour revenir à l'accueil.";
  badge.addEventListener("click", () => {
    if (Dmx) Dmx.stop().catch(() => {});
    location.href = "index.html?choose=1";
  });
  document.getElementById("conn-status").before(badge);

  function setOutputState(ok, text) {
    badge.classList.toggle("err", !ok);
    badge.textContent = ok ? "SANS PC" : "SANS PC ⚠";
    badge.title = text;
    try { _conn.state = ok ? "ok" : "err"; } catch (e) {}
    statusEl.textContent = ok ? "✓" : "⚠";
    statusEl.className = ok ? "ok" : "err";
  }

  async function startOutput() {
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
      setOutputState(false, "Sortie DMX : " + (e.message || e) + ". Toucher pour revenir à l'accueil.");
      // Interface débranchée ou refusée : on réessaie toutes les 3 s.
      setTimeout(startOutput, 3000);
    }
  }

  // ── État initial ───────────────────────────────────────────────────────────
  const states = projectors.map(fixtureState);
  const pads = {};
  for (let c = 0; c < 8; c++) for (let r = 0; r < 8; r++) {
    pads[r + "_" + c] = { color: COLORS[r], bright: play.active[c] === r ? 100 : 20 };
  }
  const effects = {};
  for (let r = 0; r < 8; r++) effects[r] = r === STROBE_ROW && play.strobe;
  emit({
    type: "state",
    data: {
      pads,
      faders: Object.fromEntries(play.faders.map((v, i) => [String(i), v])),
      effects,
      layout: GROUPS.map((g) => ({ label: byGroup[g] ? g + " · " + byGroup[g].length : "—", type: "group" })),
      seq: { items: [], current_row: -1, playing: false },
      carts: [],
      projectors: projectors.map((p, i) => ({
        name: p.name, group: p.group, x: p.x, y: p.y,
        ...projColors([states[i]])[0],
        is_lyre: p.profile.startsWith("MOVING"),
      })),
      bank_pages: { count: 1, index: 0 },
      rec_active: false,
      surface: { cols: 1, rows: 1, blocks: [] },
    },
  });
  startOutput();
  window.addEventListener("pagehide", () => { if (Dmx) Dmx.stop().catch(() => {}); });
})();
