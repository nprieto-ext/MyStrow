// Mode autonome de l'app : la tablette pilote les projecteurs SANS PC.
//
// Chargé à la fin de remote.html (voir scripts/build-www.mjs), actif seulement
// avec ?solo=1. Même contrat que demo.js : il remplace le PC — les actions de
// l'interface (window.MYSTROW_SEND) modifient l'état, renvoyé à la page sous
// forme de messages identiques au flux SSE (_handleMsg). Mais ici l'état est
// réel : engine.js le traduit en DMX, envoyé par le module natif MystrowDmx
// (interface USB-DMX ou node Art-Net).
//
// Page 1 (COULEURS) : colonnes = groupes A à H du patch (patch.html), pads =
// couleur du groupe, faders = niveau du groupe.
// Page 2 (MÉMOIRES) : 64 looks. REC puis un pad = enregistrer, pad = rappeler,
// même pad une 2e fois = éteindre.
// Boutons d'effet : un effet à la fois (mode exclusif du PC), appui long =
// choisir l'effet du bouton. Fader VIT = vitesse des effets (fader 9 du PC).
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
  const PAGE_COLORS = 0, PAGE_MEMORIES = 1, N_PAGES = 2;
  const effectByName = Object.fromEntries(Library.effects.map((e) => [e.name, e]));

  // ── Show (patch) et état du jeu, gardés sur la tablette ─────────────────────
  function load(key, def) {
    try { const v = JSON.parse(localStorage.getItem(key) || "null"); return v || def; } catch (e) { return def; }
  }
  function save(key, v) { try { localStorage.setItem(key, JSON.stringify(v)); } catch (e) {} }

  const show = load("mystrow.solo.show", { fixtures: [], output: { transport: "usb" } });
  const play = Object.assign({
    active: {},                                     // colonne → rangée de couleur (ou absent)
    faders: [100, 100, 100, 100, 100, 100, 100, 100, 50],
    effect: null,                                   // nom de l'effet en cours
    buttons: Library.defaults.slice(0, 8),          // effet de chaque bouton
    page: PAGE_COLORS,
    memories: {},                                   // "rangée_colonne" → look
    memActive: null,                                // mémoire rappelée
    positions: {},                                  // n° de projecteur → [pan, tilt]
    gobos: {},                                      // n° de projecteur → valeur DMX du gobo
    symPan: false,                                  // pad POSITION : miroir du pan
    symTilt: false,                                 // pad POSITION : miroir du tilt
    moveSize: 100,                                  // TAILLE des effets de mouvement, en %
  }, load("mystrow.solo.play", {}));
  delete play.strobe;                               // v1 : effet 1 = strobe matériel
  if (play.sym) { play.symPan = true; } delete play.sym;   // SYM unique d'avant le 24/09 (pan)
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
    const color = o.color ?? (hasColor ? COLORS[row] : "#000000");
    // Lyre à roue : un filtre choisi à la main (SCÈNE) prime ; sinon la roue
    // suit la couleur (MainWindow._update_color_wheel), et reste où elle est
    // sur un noir.
    if (o.color_wheel !== undefined) p.color_wheel = o.color_wheel;
    else Engine.updateColorWheel(p, Engine.hexToRgb(color));
    return {
      address: p.address, profile: p.profile, group: p.group, fixture_type: p.fixture_type,
      color_wheel_slots: p.color_wheel_slots, color_wheel: p.color_wheel || 0, gobo: p.gobo || 0,
      color,
      level: hasColor ? (o.level ?? play.faders[col] ?? 0) : 0,
      muted: !!o.muted,
      strobe: o.strobe ?? 0,
      pan: p.pos[0], tilt: p.pos[1], x: p.x,
    };
  }

  // Horloge de phase des effets, comme sur le PC : le temps avance au rythme
  // du fader VIT, sans saut quand on le bouge.
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
  const MOVE_ATTRS = new Set(["Pan", "Tilt", "Pan/Tilt"]);
  let scaledCache = { src: null, size: null, fx: null };
  function scaledEffect(fx) {
    if (!fx || play.moveSize === 100) return fx;
    if (scaledCache.src !== fx || scaledCache.size !== play.moveSize) {
      scaledCache = { src: fx, size: play.moveSize, fx: { ...fx, layers: fx.layers.map((ld) => (MOVE_ATTRS.has(ld.attribute)
        ? { ...ld, size: Math.min(400, (ld.size ?? 100) * play.moveSize / 100) } : ld)) } };
    }
    return scaledCache.fx;
  }

  const frame = new Uint8Array(512);
  let lastSent = "";
  function output() {
    const states = projectors.map(fixtureState);
    const fx = play.effect && scaledEffect(effectByName[play.effect]);
    if (fx) { tickClock(); Engine.effectFrame(fx, states, clock.t, Library.shapes); }
    Engine.render(states, frame);
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
  const memKey = (row, col) => row + "_" + col;
  function memColor(m) {
    const col = Object.keys(m.active || {})[0];
    if (col !== undefined) return COLORS[m.active[col]];
    return m.effect ? "#ffffff" : "#555555";
  }
  function padLook(row, col) {
    if (play.page === PAGE_MEMORIES) {
      const m = play.memories[memKey(row, col)];
      if (!m) return { color: recArmed ? "#3a0808" : "#000000", bright: recArmed ? 100 : 0 };
      return { color: memColor(m), bright: play.memActive === memKey(row, col) ? 100 : 20 };
    }
    return { color: COLORS[row], bright: play.active[col] === row ? 100 : 20 };
  }
  function padMsgs(col) {
    for (let r = 0; r < 8; r++) emit({ type: "pad", row: r, col, ...padLook(r, col) });
  }
  function allPads() { for (let c = 0; c < 8; c++) padMsgs(c); }
  function effectMsgs() {
    // Un seul bouton allumé, même si deux boutons portent le même effet : celui
    // qu'on a touché, sinon (mémoire rappelée) le premier qui le porte.
    let on = play.effect && play.buttons[play.effectRow] === play.effect ? play.effectRow
      : play.buttons.indexOf(play.effect);
    for (let r = 0; r < 8; r++) emit({ type: "effect", row: r, active: !!play.effect && r === on });
    labelEffects();
  }
  function pageMsgs() {
    pageTabs.forEach((b, i) => b.classList.toggle("on", i === play.page));
    pageTabs[PAGE_MEMORIES].textContent = recArmed ? "● REC" : "MÉMOIRES";
    pageTabs[PAGE_MEMORIES].classList.toggle("rec", recArmed);
    emit({ type: "bank_pages", count: N_PAGES, index: play.page });
    allPads();
  }

  let lastScene = 0;
  function refresh(force) {
    const states = output();
    const now = performance.now();
    if (force || now - lastScene > 100) {            // la SCÈNE n'a pas besoin de 40 images/s
      lastScene = now;
      emit({ type: "proj_colors", data: projColors(states) });
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
  function clearGroupOverrides(col) {
    (byGroup[GROUPS[col]] || []).forEach((p) => { p.override = null; });
  }
  function each(idxs, fn) {
    (idxs || []).forEach((i) => { const p = projectors[i]; if (p) { p.override = p.override || {}; fn(p.override); } });
  }

  // ── Effets ─────────────────────────────────────────────────────────────────
  let fxTimer = null;
  function setEffect(name, row) {
    play.effect = name && effectByName[name] ? name : null;
    play.effectRow = row ?? -1;
    clock.t = 0; clock.last = null;
    clearInterval(fxTimer); fxTimer = null;
    if (play.effect) fxTimer = setInterval(() => refresh(false), 25);
    effectMsgs();
  }

  // ── Mémoires ───────────────────────────────────────────────────────────────
  function snapshot() {
    return {
      active: { ...play.active },
      faders: play.faders.slice(0, 8),
      effect: play.effect,
      overrides: projectors.map((p) => (p.override ? { ...p.override } : null)),
      positions: projectors.map((p) => p.pos.slice()),
      gobos: projectors.map((p) => p.gobo || 0),
      moveSize: play.moveSize,
    };
  }
  function recall(m) {
    play.active = { ...(m.active || {}) };
    (m.faders || []).forEach((v, i) => { play.faders[i] = v; emit({ type: "fader", idx: i, value: v }); });
    projectors.forEach((p, i) => { const o = (m.overrides || [])[i]; p.override = o ? { ...o } : null; });
    (m.positions || []).forEach((pos, i) => { if (projectors[i] && pos) setPos(projectors[i], i, pos); });
    (m.gobos || []).forEach((g, i) => { if (projectors[i]) { projectors[i].gobo = g; play.gobos[i] = g; } });
    if (m.moveSize) { play.moveSize = m.moveSize; paintMoveSize(); }
    setEffect(m.effect);
  }
  function blackout() {
    play.active = {};
    projectors.forEach((p) => { p.override = null; });
    play.memActive = null;
    setEffect(null);
  }
  function setRec(on) {
    recArmed = on;
    emit({ type: "rec_state", active: on });
    if (on && play.page !== PAGE_MEMORIES) play.page = PAGE_MEMORIES;
    pageMsgs();
  }
  function memoryPad(row, col) {
    const k = memKey(row, col);
    if (recArmed) {
      play.memories[k] = snapshot();
      play.memActive = k;
      setRec(false);
      toast("Mémoire enregistrée");
      return;
    }
    const m = play.memories[k];
    if (!m) return;
    if (play.memActive === k) { blackout(); allPads(); return; }   // réappui = éteint
    play.memActive = k;
    recall(m);
    allPads();
  }

  // ── Actions de l'interface ─────────────────────────────────────────────────
  window.MYSTROW_SEND = function (ev) {
    switch (ev && ev.type) {
      case "pad":
        if (play.page === PAGE_MEMORIES) { memoryPad(ev.row, ev.col); break; }
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
      case "effect": {
        const name = play.buttons[ev.row];
        setEffect(play.effect === name && play.effectRow === ev.row ? null : name, ev.row);
        break;
      }
      case "bankpage":
        play.page = (play.page + (ev.action === "prev" ? N_PAGES - 1 : 1)) % N_PAGES;
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
        break;
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
    // Nom de l'effet dans chaque bouton
    ".eff-btn{display:flex;align-items:center;justify-content:center;overflow:hidden;padding:2px 3px;" +
    "font-family:var(--f-label);font-weight:700;font-size:clamp(9px,1.25vmin,13px);line-height:1.05;" +
    "text-align:center;color:#8fd9a0;user-select:none;-webkit-user-select:none}" +
    ".eff-btn.on{color:#052a0d}" +
    // Onglets COULEURS | MÉMOIRES à la place de « Page 1/2 ◀ ▶ »
    "#akai-pagenav #pg-label,#akai-pagenav #pg-num,#akai-pagenav #pg-btns{display:none}" +
    "#akai-pagenav .solo-tab{flex:none;height:clamp(40px,6.5vh,56px);font-family:var(--f-label);font-size:clamp(13px,1.6vw,17px);" +
    "letter-spacing:1.5px;color:var(--muted)}" +
    "#akai-pagenav .solo-tab.on{background:rgba(226,206,22,.16);border-color:#E2CE16;color:#E2CE16}" +
    "#akai-pagenav .solo-tab.rec{background:#3a0808;border-color:#ef4444;color:#fff}" +
    "@media (orientation:portrait){#akai-pagenav .solo-tab{flex:1;min-width:130px}}" +
    "#solo-toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);z-index:60;background:#1b1a17;" +
    "border:1px solid rgba(226,206,22,.45);color:#E2CE16;padding:10px 18px;border-radius:10px;font-family:var(--f-label);" +
    "font-weight:700;letter-spacing:1px;opacity:0;transition:opacity .2s;pointer-events:none}" +
    "#solo-toast.show{opacity:1}" +
    // Choix de l'effet d'un bouton
    "#fx-pick{position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center}" +
    "#fx-pick[hidden]{display:none}" +
    "#fx-pick .box{width:min(92vw,760px);max-height:86vh;display:flex;flex-direction:column;background:#11100e;" +
    "border:1px solid rgba(226,206,22,.35);border-radius:14px;padding:14px}" +
    "#fx-pick h3{margin:0 0 10px;font-family:var(--f-title);font-weight:400;font-size:26px;letter-spacing:1px;color:#E2CE16}" +
    "#fx-pick .list{overflow:auto;display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px}" +
    "#fx-pick .cat{grid-column:1/-1;margin-top:6px;font-family:var(--f-label);font-size:12px;letter-spacing:2px;color:var(--muted)}" +
    "#fx-pick button{min-height:44px;border-radius:8px;border:1px solid #1a5e26;background:#0d2e12;color:#cfeed6;" +
    "font-family:var(--f-label);font-weight:700;font-size:14px;cursor:pointer;touch-action:manipulation}" +
    "#fx-pick button.cur{background:var(--green);color:#052a0d;border-color:#4ade80}" +
    "#fx-pick .close{margin-top:10px;border-color:var(--line2);background:var(--bg2);color:var(--text)}" +
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
    "#solo-menu{position:fixed;inset:0;z-index:50;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center}" +
    "#solo-menu[hidden]{display:none}" +
    "#solo-menu .box{width:min(88vw,380px);background:#11100e;border:1px solid rgba(226,206,22,.35);border-radius:14px;" +
    "padding:14px;display:flex;flex-direction:column;gap:8px}" +
    "#solo-menu h3{margin:0 0 4px;font-family:var(--f-title);font-weight:400;font-size:24px;color:#E2CE16;" +
    "white-space:nowrap;overflow:hidden;text-overflow:ellipsis}" +
    "#solo-menu button{min-height:48px;border-radius:10px;border:1px solid var(--line2);background:var(--bg2);color:var(--text);" +
    "font-family:var(--f-label);font-weight:700;font-size:16px;cursor:pointer}" +
    "#solo-menu button.danger{border-color:rgba(248,113,113,.5);color:#f87171}";
  document.head.appendChild(style);

  const badge = document.createElement("button");
  badge.id = "solo-badge";
  badge.type = "button";
  badge.textContent = "SANS PC";
  badge.title = "Mode autonome : la tablette pilote les projecteurs. Toucher pour revenir à l'accueil.";
  badge.addEventListener("click", () => {
    if (Dmx) Dmx.stop().catch(() => {});
    location.href = "index.html?choose=1";
  });
  document.getElementById("conn-status").before(badge);

  const toastEl = document.createElement("div");
  toastEl.id = "solo-toast";
  document.body.appendChild(toastEl);
  let toastTimer = null;
  function toast(text) {
    toastEl.textContent = text; toastEl.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => toastEl.classList.remove("show"), 1600);
  }

  // Pages de la grille : deux onglets COULEURS | MÉMOIRES bien visibles, à la
  // place du « Page 1/2 ◀ ▶ » du PC, trop discret (l'utilisateur ne l'a pas
  // trouvé seul, 24/09/2026).
  const pageNav = document.getElementById("akai-pagenav");
  const pageTabs = ["COULEURS", "MÉMOIRES"].map((label, i) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "solo-tab"; b.textContent = label;
    b.addEventListener("click", () => {
      if (play.page === i) return;
      play.page = i; savePlay(); pageMsgs();
    });
    pageNav.appendChild(b);
    return b;
  });

  // Nom de l'effet dans chaque bouton + appui long = changer d'effet.
  const effBtns = [...document.querySelectorAll("#effects .eff-btn")];
  function labelEffects() {
    effBtns.forEach((el, r) => { el.textContent = play.buttons[r] || "—"; });
  }
  const pick = document.createElement("div");
  pick.id = "fx-pick";
  pick.hidden = true;
  pick.innerHTML = '<div class="box"><h3></h3><div class="list"></div><button class="close" type="button">Annuler</button></div>';
  document.body.appendChild(pick);
  let pickPrev = null;
  function openPicker(row, prevEffect) {
    pickPrev = prevEffect;
    pick.querySelector("h3").textContent = "Effet du bouton " + (row + 1);
    const list = pick.querySelector(".list");
    list.innerHTML = "";
    let cat = null;
    Library.effects.forEach((e) => {
      if (e.category !== cat) {
        cat = e.category;
        const h = document.createElement("div"); h.className = "cat"; h.textContent = cat.toUpperCase();
        list.appendChild(h);
      }
      const b = document.createElement("button");
      b.type = "button"; b.textContent = e.name;
      if (e.name === play.buttons[row]) b.className = "cur";
      b.addEventListener("click", () => {
        play.buttons[row] = e.name;
        pick.hidden = true;
        setEffect(e.name, row);                     // on le voit tout de suite
        savePlay(); refresh(true);
      });
      list.appendChild(b);
    });
    pick.hidden = false;
  }
  pick.querySelector(".close").addEventListener("click", () => {
    pick.hidden = true;
    setEffect(pickPrev.effect, pickPrev.row);       // annuler = l'effet d'avant l'appui
    savePlay(); refresh(true);
  });
  effBtns.forEach((el, r) => {
    let timer = null, before = null;
    el.addEventListener("pointerdown", () => {
      before = { effect: play.effect, row: play.effectRow };   // avant la bascule par la page
      clearTimeout(timer);
      timer = setTimeout(() => openPicker(r, before), 650);
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach((t) => el.addEventListener(t, () => clearTimeout(timer)));
  });

  // ── Sortie DMX ─────────────────────────────────────────────────────────────
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

  // TAILLE des mouvements : dans la carte en haut à droite de l'onglet AKAI,
  // sous COULEURS | MÉMOIRES — c'est un réglage d'effet, on le touche pendant
  // que l'effet tourne. Seulement s'il y a des lyres dans le patch.
  // (Au 24/09 il était sous le pad POSITION : l'utilisateur ne l'a pas trouvé.)
  const SIZE_STEPS = [25, 50, 75, 100, 125, 150, 200, 250, 300, 400];
  const sizeBox = document.createElement("div");
  sizeBox.className = "solo-move";
  sizeBox.innerHTML = '<span>TAILLE MVT</span><div><button type="button">−</button><b title="Toucher : 100 %"></b><button type="button">+</button></div>';
  const [sizeMinus, sizePlus] = sizeBox.querySelectorAll("button"), sizeVal = sizeBox.querySelector("b");
  function paintMoveSize() { sizeVal.textContent = play.moveSize + "%"; sizeVal.classList.toggle("mod", play.moveSize !== 100); }
  function stepSize(dir) {
    const cur = play.moveSize;
    const next = dir > 0 ? SIZE_STEPS.find((v) => v > cur) : [...SIZE_STEPS].reverse().find((v) => v < cur);
    if (next === undefined) return;
    play.moveSize = next;
    paintMoveSize(); savePlay();
  }
  sizeMinus.addEventListener("click", () => stepSize(-1));
  sizePlus.addEventListener("click", () => stepSize(+1));
  sizeVal.addEventListener("click", () => { play.moveSize = 100; paintMoveSize(); savePlay(); });   // effet d'origine
  if (projectors.some(Engine.isLyre)) pageNav.appendChild(sizeBox);
  paintMoveSize();
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
    };
  }
  function redrawPad() {
    try {
      if (projPanel.classList.contains("open") && _projectors[_selectedProjIdx]) drawPanTiltPad(_projectors[_selectedProjIdx]);
    } catch (e) {}
  }

  // Appui long sur un pad MÉMOIRE : l'effacer. (L'appui a déjà rappelé ou
  // éteint la mémoire, comme sur l'AKAI : effacer une mémoire allumée éteint
  // aussi la scène.)
  document.querySelectorAll("#grid .pad").forEach((el) => {
    let timer = null;
    el.addEventListener("pointerdown", () => {
      clearTimeout(timer);
      if (play.page !== PAGE_MEMORIES || recArmed) return;
      const r = +el.dataset.r, c = +el.dataset.c, k = memKey(r, c);
      if (!play.memories[k]) return;
      timer = setTimeout(() => openMenu("Mémoire " + (c + 1) + "." + (r + 1), [
        ["Effacer la mémoire", () => {
          delete play.memories[k];
          if (play.memActive === k) blackout();
          savePlay(); allPads(); refresh(true);
          toast("Mémoire effacée");
        }, "danger"],
      ]), 650);
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach((t) => el.addEventListener(t, () => clearTimeout(timer)));
  });

  // Menu contextuel partagé (mémoires ici, playlist et cartouches dans media.js).
  const menu = document.createElement("div");
  menu.id = "solo-menu"; menu.hidden = true;
  menu.innerHTML = '<div class="box"><h3></h3><div class="acts" style="display:flex;flex-direction:column;gap:8px"></div></div>';
  menu.addEventListener("click", (e) => { if (e.target === menu) menu.hidden = true; });
  document.body.appendChild(menu);
  function openMenu(title, actions) {
    menu.querySelector("h3").textContent = title;
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

  // Pour media.js (playlist, cartouches) : même canal de messages vers la page.
  window.MystrowSolo = { emit, toast, openMenu, mediaEnabled: MEDIA_SOLO };

  // ── État initial ───────────────────────────────────────────────────────────
  const states = projectors.map(fixtureState);
  const pads = {};
  for (let c = 0; c < 8; c++) for (let r = 0; r < 8; r++) pads[r + "_" + c] = padLook(r, c);
  emit({
    type: "state",
    data: {
      pads,
      faders: Object.fromEntries(play.faders.map((v, i) => [String(i), v])),
      effects: {},
      layout: GROUPS.map((g) => ({ label: byGroup[g] ? g + " · " + byGroup[g].length : "—", type: "group" })),
      seq: { items: [], current_row: -1, playing: false },
      carts: [],
      projectors: projectors.map((p, i) => ({
        name: p.name, group: p.group, x: p.x, y: p.y,
        ...projColors([states[i]])[0],
        is_lyre: Engine.isLyre(p), ftype: p.fixture_type || "",
        ...wheelMeta(p),
      })),
      bank_pages: { count: N_PAGES, index: play.page },
      rec_active: false,
      surface: { cols: 1, rows: 1, blocks: [] },
    },
  });
  pageMsgs();
  setEffect(play.effect, play.effectRow);
  refresh(true);
  startOutput();
  window.addEventListener("pagehide", () => { if (Dmx) Dmx.stop().catch(() => {}); });
})();
