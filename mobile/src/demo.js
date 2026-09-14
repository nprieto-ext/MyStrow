// Mode démo de l'app : un show d'exemple, sans PC ni lumières.
//
// Chargé à la fin de remote.html (voir scripts/build-www.mjs), actif seulement
// avec ?demo=1. Il remplace le PC : les actions de l'interface (window.MYSTROW_SEND)
// modifient un état local, renvoyé à la page sous forme de messages identiques à
// ceux du flux SSE (_handleMsg). Sert de vitrine et à la validation Apple, qui
// teste l'app sans le logiciel PC.
(function () {
  "use strict";
  if (!window.MYSTROW_DEMO) return;

  const COLORS = ["#ffffff", "#ff0000", "#ff8800", "#ffdd00", "#00ff00", "#00dddd", "#0000ff", "#ff00ff"];
  const LABELS = ["FACE", "LYRES", "LAT", "DCH 1", "DCH 2", "DCH 3", "CONTRE", "BARRE"];
  // Colonnes AKAI reliées à des projecteurs du plan de feu d'exemple.
  const COL_GROUP = { 0: "face", 1: "contre", 2: "lat" };
  const BANKS = 3;

  const active = { 0: 2, 1: 7, 2: 5, 3: 3, 4: 4, 5: 6, 6: 1, 7: 0 };
  const faders = [85, 90, 60, 62, 40, 100, 70, 30, 55];
  const effects = [true, false, false, false, false, false, false, false];
  let bank = 0;
  let rec = false;

  const seqItems = [
    { type: "media", title: "Ouverture — Also sprach Zarathustra.mp3", dur: "01:42", vol: "80", dmx: "Play Lumiere" },
    { type: "media", title: "Daft Punk — One More Time.mp3", dur: "05:20", vol: "90", dmx: "IA Lumiere" },
    { type: "pause", title: "PAUSE", dur: "--:--", vol: "--" },
    { type: "media", title: "Discours d'accueil.wav", dur: "03:05", vol: "70", dmx: "Manuel" },
    { type: "tempo", title: "Tempo 10 s", dur: "00:10", vol: "--" },
    { type: "media", title: "Remise des prix — Jingle.mp3", dur: "00:18", vol: "85", dmx: "Programme" },
    { type: "media", title: "Final — We Are The Champions.mp3", dur: "03:01", vol: "95", dmx: "Play Lumiere" },
  ];
  let current = 1;
  let playing = true;

  const carts = [
    { title: "Applaudissements", state: 0 },
    { title: "Jingle entrée", state: 0 },
    { title: "Sirène", state: 0 },
    { title: "Roulement", state: 0 },
  ];

  const projectors = [];
  for (let i = 0; i < 6; i++) {
    projectors.push({ name: "Face " + (i + 1), group: "face", x: 0.14 + i * 0.144, y: 0.8, color: COLORS[active[0]], base_color: COLORS[active[0]], level: faders[0], lit: true });
  }
  for (let i = 0; i < 4; i++) {
    projectors.push({ name: "Lyre " + (i + 1), group: "contre", x: 0.2 + i * 0.2, y: 0.22, color: COLORS[active[1]], base_color: COLORS[active[1]], level: faders[1], lit: true, is_lyre: true, ftype: "Moving Head", pan: 20000 + i * 8000, tilt: 30000, gobo: 0, color_wheel: 0 });
  }
  [0.05, 0.95].forEach((x, i) => {
    projectors.push({ name: "Lat " + (i + 1), group: "lat", x, y: 0.5, color: COLORS[active[2]], base_color: COLORS[active[2]], level: faders[2], lit: true, ftype: "Barre LED" });
  });
  projectors.push({ name: "Strobe", group: "strobe", x: 0.5, y: 0.5, color: "#ffffff", base_color: "#ffffff", level: 0, lit: false, ftype: "Stroboscope" });

  const surface = {
    cols: 6, rows: 4, blocks: [
      { col: 0, row: 0, span_c: 2, label: "BLACKOUT", color: "#ef4444", action: { type: "blackout" } },
      { col: 2, row: 0, label: "ROUGE", color: "#ff0000", action: { type: "color" } },
      { col: 3, row: 0, label: "BLEU", color: "#0044ff", action: { type: "color" } },
      { col: 4, row: 0, label: "AMBRE", color: "#ff8800", action: { type: "color" } },
      { col: 5, row: 0, span_r: 3, label: "MASTER", color: "#E2CE16", action: { type: "fader" } },
      { col: 0, row: 1, label: "Mém. 1", color: "#a78bfa", action: { type: "memory" } },
      { col: 1, row: 1, label: "Mém. 2", color: "#a78bfa", action: { type: "memory" } },
      { col: 2, row: 1, span_c: 3, label: "", color: "#333333", action: { type: "clock" } },
      { col: 0, row: 2, span_c: 2, label: "STROBE", color: "#ffffff", action: { type: "strobe" } },
      { col: 2, row: 2, span_c: 3, label: "MÉDIA SUIVANT", color: "#22c55e", action: { type: "next" } },
    ],
  };

  // ── Messages vers la page (mêmes formats que le flux SSE du PC) ────────────
  function emit(msg) {
    try { _conn.lastMsg = Date.now(); } catch (e) {}
    _handleMsg(msg);
  }
  function padMsgs(col) {
    for (let r = 0; r < 8; r++) {
      emit({ type: "pad", row: r, col, color: COLORS[r], bright: active[col] === r ? 100 : 20 });
    }
  }
  function projColors() {
    return projectors.map(p => ({
      color: p.color, base_color: p.base_color, level: p.level, muted: !!p.muted,
      lit: !!p.lit && !p.muted && p.level > 0, strobe: p.strobe || 0,
      pan: p.pan, tilt: p.tilt, gobo: p.gobo, color_wheel: p.color_wheel,
    }));
  }
  function applyColumnToStage(col) {
    const group = COL_GROUP[col];
    if (!group) return;
    const has = active[col] !== undefined && active[col] !== null;
    projectors.forEach(p => {
      if (p.group !== group) return;
      if (has) { p.color = p.base_color = COLORS[active[col]]; }
      p.level = faders[col];
      p.lit = has && faders[col] > 0;
    });
    emit({ type: "proj_colors", data: projColors() });
  }
  function seqRow() { emit({ type: "seq_row", current_row: current, playing }); }

  // ── Actions de l'interface → état d'exemple ────────────────────────────────
  function each(idxs, fn) { (idxs || []).forEach(i => { if (projectors[i]) fn(projectors[i]); }); }

  window.MYSTROW_SEND = function (ev) {
    switch (ev && ev.type) {
      case "pad":
        active[ev.col] = ev.row;
        padMsgs(ev.col);
        applyColumnToStage(ev.col);
        break;
      case "fader":
        faders[ev.idx] = ev.value;
        emit({ type: "fader", idx: ev.idx, value: ev.value });
        applyColumnToStage(ev.idx);
        break;
      case "effect":
        effects[ev.row] = !effects[ev.row];
        emit({ type: "effect", row: ev.row, active: effects[ev.row] });
        break;
      case "clear":
        for (let c = 0; c < 8; c++) { active[c] = null; padMsgs(c); applyColumnToStage(c); }
        break;
      case "rec_toggle":
        rec = !rec;
        emit({ type: "rec_state", active: rec });
        break;
      case "bankpage":
        bank = (bank + (ev.action === "prev" ? BANKS - 1 : 1)) % BANKS;
        emit({ type: "bank_pages", count: BANKS, index: bank });
        break;
      case "transport":
        if (ev.action === "play_pause") playing = !playing;
        else {
          const step = ev.action === "prev" ? -1 : 1;
          current = Math.max(0, Math.min(seqItems.length - 1, current + step));
          playing = true;
        }
        seqRow();
        break;
      case "seq_row":
        current = ev.row; playing = true;
        seqRow();
        break;
      case "cartouche": {
        const c = carts[ev.idx];
        if (!c) break;
        c.state = c.state === 1 ? 2 : 1;
        emit({ type: "cart", idx: ev.idx, title: c.title, state: c.state });
        break;
      }
      case "proj_color":
        each(ev.idxs, p => { p.color = p.base_color = ev.color; p.lit = true; if (!p.level) p.level = 100; });
        emit({ type: "proj_colors", data: projColors() });
        break;
      case "proj_level":
        each(ev.idxs, p => { p.level = ev.value; p.lit = ev.value > 0; });
        emit({ type: "proj_colors", data: projColors() });
        break;
      case "proj_mute":
        each(ev.idxs, p => { p.muted = !!ev.muted; });
        emit({ type: "proj_colors", data: projColors() });
        break;
      case "proj_strobe":
        each(ev.idxs, p => { p.strobe = ev.value; });
        emit({ type: "proj_colors", data: projColors() });
        break;
      case "proj_pantilt":
        each(ev.idxs, p => { p.pan = ev.pan; p.tilt = ev.tilt; });
        emit({ type: "proj_colors", data: projColors() });
        break;
      case "proj_gobo":
        each(ev.idxs, p => { p.gobo = ev.value; });
        emit({ type: "proj_colors", data: projColors() });
        break;
      case "proj_colorwheel":
        each(ev.idxs, p => { p.color_wheel = ev.value; });
        emit({ type: "proj_colors", data: projColors() });
        break;
      default:
        break; // scene_clear, scene_select_all, ext_action, ext_fader : rien à simuler
    }
  };

  // ── Bandeau « DÉMO » dans l'en-tête ────────────────────────────────────────
  const style = document.createElement("style");
  style.textContent =
    "#demo-badge{flex-shrink:0;height:100%;padding:0 12px;border-radius:10px;border:1px solid rgba(226,206,22,.45);" +
    "background:rgba(226,206,22,.10);color:#E2CE16;font-family:var(--f-label);font-weight:700;font-size:13px;" +
    "letter-spacing:1.5px;cursor:pointer;touch-action:manipulation}" +
    "#demo-badge:active{background:rgba(226,206,22,.22)}";
  document.head.appendChild(style);
  const badge = document.createElement("button");
  badge.id = "demo-badge";
  badge.type = "button";
  badge.textContent = "DÉMO";
  badge.title = "Mode démo : aucune lumière n'est pilotée. Toucher pour connecter un PC.";
  badge.addEventListener("click", () => { location.href = "index.html?choose=1"; });
  document.getElementById("conn-status").before(badge);

  // ── État initial ───────────────────────────────────────────────────────────
  const pads = {};
  for (let c = 0; c < 8; c++) for (let r = 0; r < 8; r++) {
    pads[r + "_" + c] = { color: COLORS[r], bright: active[c] === r ? 100 : 20 };
  }
  emit({
    type: "state",
    data: {
      pads,
      faders: Object.fromEntries(faders.map((v, i) => [String(i), v])),
      effects: Object.fromEntries(effects.map((v, i) => [String(i), v])),
      layout: LABELS.map(label => ({ label, type: "group" })),
      seq: { items: seqItems, current_row: current, playing },
      carts,
      projectors,
      bank_pages: { count: BANKS, index: bank },
      rec_active: rec,
      surface,
    },
  });
  try { _conn.state = "ok"; _conn.since = Date.now(); } catch (e) {}
  statusEl.textContent = "✓";
  statusEl.className = "ok";
})();
