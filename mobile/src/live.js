// Page LIVE du mode sans PC : l'écran simple pour un DJ, un bar, une salle.
//
// Chargé après standalone.js (voir scripts/build-www.mjs). Ce n'est PAS un
// second moteur : la page agit sur le même état que l'AKAI (play.active,
// play.faders, play.effect…, exposés par MystrowSolo.core). On peut passer de
// l'une à l'autre (⚙ Réglages) sans rien perdre.
//
//   ZONES      : « Tout » + chaque groupe du patch (nommé dans le patch).
//   COULEUR    : 8 couleurs = les 8 rangées de l'AKAI, appliquées à la zone.
//   EFFET      : 8 effets de la bibliothèque, pour tous les projecteurs
//                (le moteur n'a qu'un effet à la fois, comme le PC).
//   AMBIANCES  : looks nommés (play.scenes), distincts des 64 mémoires AKAI.
//   INTENSITÉ  : faders des groupes de la zone. VITESSE : fader VIT.
//   FLASH/NOIR : maintenus, par-dessus tout (hold de standalone.js).
(function () {
  "use strict";
  const Solo = window.MystrowSolo;
  if (!window.MYSTROW_SOLO || !Solo || !Solo.core) return;
  const C = Solo.core;
  const { play, show, GROUPS, COLORS } = C;

  const COLOR_NAMES = ["Blanc", "Rouge", "Orange", "Jaune", "Vert", "Cyan", "Bleu", "Magenta"];
  const DARK_INK = new Set([0, 2, 3, 4, 5]);       // couleurs claires : texte foncé
  // [nom affiché, explication, effet de la bibliothèque (null = couleur fixe)]
  const EFFECTS = [
    ["Fixe", "couleur pleine", null],
    ["Respiration", "monte et descend", "Respiration"],
    ["Vague", "d'un côté à l'autre", "Vague"],
    ["Chenillard", "un par un", "Chase Doux"],
    ["Arc-en-ciel", "toutes les couleurs", "Rainbow"],
    ["Pulse", "bat doucement", "Pulse Doux"],
    ["Ping-pong", "aller-retour", "Ping Pong"],
    ["Mouvement", "les lyres balaient", "Lyre Sweep"],
  ].filter(([, , lib]) => !lib || C.effectByName[lib]);
  const MAX_SCENES = 16;

  play.scenes = Array.isArray(play.scenes) ? play.scenes : [];
  if (play.liveZone === undefined) play.liveZone = "tout";
  const usedCols = () => C.usedGroups.map((g) => GROUPS.indexOf(g));
  const zoneCols = () => (play.liveZone === "tout" ? usedCols() : [GROUPS.indexOf(play.liveZone)]).filter((c) => c >= 0);
  const groupName = (g) => (show.groupNames && show.groupNames[g]) || "Groupe " + g;

  // ── Actions sur l'état partagé ──────────────────────────────────────────
  function commit() { C.savePlay(); C.refresh(true); render(); }
  function leaveScene() { play.liveScene = null; play.memActive = null; }
  function setColor(row) {
    zoneCols().forEach((col) => { play.active[col] = row; C.clearGroupOverrides(col); C.padMsgs(col); });
    leaveScene(); commit();
  }
  function setEffect(lib) {
    const row = lib ? play.buttons.indexOf(lib) : -1;
    C.setEffect(lib, row);
    // Une zone encore éteinte : l'effet serait invisible → couleur blanche.
    if (lib && !zoneCols().some((c) => play.active[c] !== undefined)) zoneCols().forEach((c) => { play.active[c] = 0; C.padMsgs(c); });
    leaveScene(); commit();
  }
  function setLevel(v) {
    zoneCols().forEach((col) => {
      play.faders[col] = v;
      C.emit({ type: "fader", idx: col, value: v });
      (C.byGroup[GROUPS[col]] || []).forEach((p) => { if (p.override) delete p.override.level; });
    });
    C.savePlay(); C.refresh(false);
  }
  function setSpeed(v) {
    play.faders[C.SPEED] = v;
    C.emit({ type: "fader", idx: C.SPEED, value: v });
    C.savePlay(); C.refresh(false);
  }
  function recallScene(i) {
    const sc = play.scenes[i];
    if (!sc) return;
    C.recall(sc.look);
    play.liveScene = i; play.memActive = null;
    C.allPads(); commit();
  }
  function saveScene(name, i) {
    const entry = { name: name.slice(0, 24), look: C.snapshot() };
    if (i === undefined) { play.scenes.push(entry); i = play.scenes.length - 1; } else play.scenes[i] = entry;
    play.liveScene = i;
    Solo.toast("Ambiance « " + entry.name + " » enregistrée");
    commit();
  }
  function setHold(kind, on) {
    if (C.hold[kind] === on) return;
    C.hold[kind] = on;
    C.refresh(true); paintHold();
  }

  // ── Tempo tapé : BPM → VITESSE (120 BPM = 50, la vitesse naturelle des effets) ─
  let taps = [], bpm = null;
  function tap() {
    const now = performance.now();
    taps = taps.filter((t) => now - t < 3000).concat(now);
    if (taps.length < 2) { paintTap(); return; }
    bpm = Math.round(60000 / ((taps[taps.length - 1] - taps[0]) / (taps.length - 1)));
    setSpeed(Math.max(5, Math.min(100, Math.round((bpm / 120) * 50))));
    paintFaders(); paintTap();
  }

  // ── Construction de la page ─────────────────────────────────────────────
  const root = document.createElement("div");
  root.id = "solo-live";
  root.hidden = true;
  root.innerHTML = `
    <header class="lv-head">
      <div class="lv-brand">MY<span>STROW</span></div>
      <div class="lv-zones" role="group" aria-label="Zone pilotée"></div>
      <button type="button" class="lv-dmx" aria-label="État de la sortie DMX"><i></i><span>DMX…</span></button>
      <button type="button" class="lv-gear" aria-label="Réglages">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>
      </button>
    </header>
    <div class="lv-body">
      <main class="lv-main">
        <div class="lv-now"><i></i><b>EN COURS</b><span></span></div>
        <section><div class="lv-title">COULEUR</div><div class="lv-colors"></div></section>
        <section><div class="lv-title">EFFET</div><div class="lv-fx"></div></section>
        <section class="lv-scn-sec">
          <div class="lv-title">AMBIANCES <small>appui long = renommer, remplacer, effacer</small></div>
          <div class="lv-scenes"></div>
        </section>
      </main>
      <aside class="lv-side">
        <div class="lv-faders">
          <div class="lv-fcard"><div class="lv-flbl">INTENSITÉ</div><div class="lv-fader" data-f="level"><div class="lv-fill"></div><div class="lv-thumb"></div></div><div class="lv-fval" data-v="level"></div></div>
          <div class="lv-fcard"><div class="lv-flbl">VITESSE</div><div class="lv-fader" data-f="speed"><div class="lv-fill"></div><div class="lv-thumb"></div></div><button type="button" class="lv-tap">TAP</button></div>
        </div>
        <button type="button" class="lv-flash">FLASH</button>
        <button type="button" class="lv-black">NOIR</button>
      </aside>
    </div>
    <div class="lv-dialog" hidden><form class="lv-dbox"><label for="lv-dname">Nom de l'ambiance</label>
      <input id="lv-dname" maxlength="24" autocomplete="off" placeholder="Apéro, Dancefloor, Slow…">
      <div class="lv-drow"><button type="button" class="lv-dcancel">Annuler</button><button type="submit" class="lv-dok">Enregistrer</button></div></form></div>`;
  document.body.appendChild(root);
  const $ = (sel) => root.querySelector(sel);

  // Appui long générique (650 ms, comme le reste de l'app).
  function longPress(el, onLong, onTap) {
    let timer = null, fired = false;
    el.addEventListener("pointerdown", () => { fired = false; clearTimeout(timer); timer = setTimeout(() => { fired = true; onLong(); }, 650); });
    ["pointerup", "pointercancel", "pointerleave"].forEach((t) => el.addEventListener(t, () => clearTimeout(timer)));
    el.addEventListener("click", () => { if (!fired) onTap(); });
    el.addEventListener("contextmenu", (e) => e.preventDefault());
  }

  // Petite fenêtre de saisie du nom (pas de prompt() : bloquant dans l'app).
  let dialogCb = null;
  function askName(value, cb) {
    dialogCb = cb;
    $("#lv-dname").value = value || "";
    $(".lv-dialog").hidden = false;
    setTimeout(() => $("#lv-dname").focus(), 50);
  }
  $(".lv-dbox").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("#lv-dname").value.trim();
    if (!v) { $("#lv-dname").focus(); return; }
    $(".lv-dialog").hidden = true;
    if (dialogCb) dialogCb(v);
  });
  $(".lv-dcancel").addEventListener("click", () => { $(".lv-dialog").hidden = true; });

  // Zones
  function renderZones() {
    const box = $(".lv-zones");
    box.innerHTML = "";
    const zones = [["tout", "Tout"], ...C.usedGroups.map((g) => [g, groupName(g)])];
    if (!zones.some(([id]) => id === play.liveZone)) play.liveZone = "tout";
    // Un seul groupe : « Tout » suffit.
    (zones.length > 2 ? zones : zones.slice(0, 1)).forEach(([id, label]) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label;
      b.className = play.liveZone === id ? "on" : "";
      b.setAttribute("aria-pressed", play.liveZone === id);
      b.addEventListener("click", () => { play.liveZone = id; C.savePlay(); render(); });
      box.appendChild(b);
    });
  }

  // Couleurs
  const colorBtns = COLORS.map((hex, row) => {
    const b = document.createElement("button");
    b.type = "button"; b.textContent = COLOR_NAMES[row];
    b.style.setProperty("--c", hex);
    b.classList.toggle("dark", DARK_INK.has(row));
    b.addEventListener("click", () => setColor(row));
    $(".lv-colors").appendChild(b);
    return b;
  });

  // Effets
  const fxBtns = EFFECTS.map(([name, hint, lib]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.innerHTML = "<b></b><small></small>";
    b.querySelector("b").textContent = name;
    b.querySelector("small").textContent = hint;
    b.addEventListener("click", () => setEffect(lib));
    $(".lv-fx").appendChild(b);
    return b;
  });

  // Ambiances
  function sceneSwatch(look) {
    const rows = Object.values((look && look.active) || {});
    const cols = [...new Set(rows)].slice(0, 3).map((r) => COLORS[r]);
    if (look && look.effect === "Rainbow") return "linear-gradient(135deg,#ff0000,#ffdd00,#00ff00,#0000ff,#ff00ff)";
    if (!cols.length) return "#2a2820";
    return cols.length === 1 ? cols[0] : "linear-gradient(135deg," + cols.join(",") + ")";
  }
  function renderScenes() {
    const box = $(".lv-scenes");
    box.innerHTML = "";
    play.scenes.forEach((sc, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = play.liveScene === i ? "on" : "";
      b.innerHTML = "<i></i><b></b>";
      b.querySelector("i").style.background = sceneSwatch(sc.look);
      b.querySelector("b").textContent = sc.name;
      longPress(b, () => Solo.openMenu(sc.name, [
        ["Renommer", () => askName(sc.name, (v) => { sc.name = v.slice(0, 24); C.savePlay(); render(); })],
        ["Remplacer par ce qui joue", () => saveScene(sc.name, i)],
        ["Effacer", () => { play.scenes.splice(i, 1); if (play.liveScene === i) play.liveScene = null;
                            else if (play.liveScene > i) play.liveScene--; C.savePlay(); render(); }, "danger"],
      ]), () => recallScene(i));
      box.appendChild(b);
    });
    if (play.scenes.length < MAX_SCENES) {
      const add = document.createElement("button");
      add.type = "button"; add.className = "add";
      add.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>ENREGISTRER';
      add.addEventListener("click", () => askName("", (v) => saveScene(v)));
      box.appendChild(add);
    }
  }

  // Faders tactiles (dessinés à la main : le curseur vertical natif n'existe
  // pas sur les vieux WebView Android).
  const zoneLevel = () => {
    const cols = zoneCols();
    return cols.length ? Math.round(cols.reduce((a, c) => a + (play.faders[c] ?? 0), 0) / cols.length) : 0;
  };
  function paintFader(el, v) {
    el.querySelector(".lv-fill").style.height = v + "%";
    el.querySelector(".lv-thumb").style.bottom = "calc(" + v + "% - " + (v / 100) * 22 + "px)";
  }
  function paintFaders() {
    const lv = zoneLevel();
    paintFader($('[data-f="level"]'), lv);
    $('[data-v="level"]').textContent = lv + "%";
    paintFader($('[data-f="speed"]'), play.faders[C.SPEED]);
  }
  root.querySelectorAll(".lv-fader").forEach((el) => {
    const apply = (e) => {
      const r = el.getBoundingClientRect();
      const v = Math.round(Math.max(0, Math.min(1, (r.bottom - e.clientY) / r.height)) * 100);
      if (el.dataset.f === "level") setLevel(v); else setSpeed(v);
      paintFaders();
    };
    el.addEventListener("pointerdown", (e) => { el.setPointerCapture(e.pointerId); apply(e); });
    el.addEventListener("pointermove", (e) => { if (el.hasPointerCapture(e.pointerId)) apply(e); });
    // Double-tap : intensité pleine / vitesse naturelle.
    el.addEventListener("dblclick", () => { if (el.dataset.f === "level") setLevel(100); else setSpeed(50); paintFaders(); });
  });
  function paintTap() { $(".lv-tap").textContent = bpm ? "TAP " + bpm : "TAP"; }
  $(".lv-tap").addEventListener("click", tap);

  // FLASH / NOIR : actifs tant que le doigt reste dessus.
  [["flash", ".lv-flash"], ["black", ".lv-black"]].forEach(([kind, sel]) => {
    const el = $(sel);
    el.addEventListener("pointerdown", (e) => { el.setPointerCapture(e.pointerId); setHold(kind, true); });
    ["pointerup", "pointercancel", "lostpointercapture"].forEach((t) => el.addEventListener(t, () => setHold(kind, false)));
    el.addEventListener("contextmenu", (e) => e.preventDefault());
  });
  function paintHold() {
    $(".lv-flash").classList.toggle("on", C.hold.flash);
    $(".lv-black").classList.toggle("on", C.hold.black);
    paintNow();
  }

  // Bandeau « EN COURS »
  function paintNow() {
    let text, dot;
    const cols = zoneCols();
    const rows = [...new Set(cols.map((c) => play.active[c]))];
    const fx = EFFECTS.find(([, , lib]) => lib === play.effect);
    const zone = play.liveZone === "tout" ? "Tout" : groupName(play.liveZone);
    if (C.hold.black) { text = "NOIR (relâchez pour revenir)"; dot = "#000"; }
    else if (C.hold.flash) { text = "FLASH blanc plein feu"; dot = "#fff"; }
    else if (play.liveScene !== null && play.liveScene !== undefined && play.scenes[play.liveScene]) {
      text = "Ambiance « " + play.scenes[play.liveScene].name + " »"; dot = "#E2CE16";
    } else {
      const col = rows.length === 1 && rows[0] !== undefined ? COLOR_NAMES[rows[0]] : rows.length > 1 ? "Plusieurs couleurs" : "Éteint";
      text = zone + " · " + col + " · " + (fx ? fx[0] : play.effect || "Fixe");
      dot = rows.length === 1 && rows[0] !== undefined ? COLORS[rows[0]] : "#2a2820";
    }
    $(".lv-now span").textContent = text;
    $(".lv-now i").style.background = dot;
  }

  function render() {
    renderZones();
    const rows = [...new Set(zoneCols().map((c) => play.active[c]))];
    const inScene = play.liveScene !== null && play.liveScene !== undefined;
    colorBtns.forEach((b, row) => b.classList.toggle("on", !inScene && rows.length === 1 && rows[0] === row));
    fxBtns.forEach((b, i) => b.classList.toggle("on", !inScene && (EFFECTS[i][2] || null) === (play.effect || null)));
    renderScenes();
    paintFaders(); paintTap(); paintHold();
  }

  // En-tête : voyant DMX (recopié de celui de la page) et réglages.
  const statusEl = document.getElementById("conn-status");
  function paintDmx() {
    const ok = statusEl && statusEl.classList.contains("ok"), err = statusEl && statusEl.classList.contains("err");
    $(".lv-dmx").className = "lv-dmx" + (ok ? " ok" : err ? " err" : "");
    $(".lv-dmx span").textContent = ok ? "DMX OK" : err ? "DMX COUPÉ" : "DMX…";
  }
  if (statusEl) new MutationObserver(paintDmx).observe(statusEl, { attributes: true, attributeFilter: ["class"] });
  paintDmx();
  $(".lv-dmx").addEventListener("click", () => C.openOutputPanel());
  $(".lv-gear").addEventListener("click", () => C.openSettings());

  // Bascule Live ↔ Expert, mémorisée.
  function setVisible(on) {
    root.hidden = !on;
    play.ui = on ? "live" : "expert";
    C.savePlay();
    if (on) render(); else { C.allPads(); C.refresh(true); }
  }
  window.MystrowLive = { visible: () => !root.hidden, toggle: () => setVisible(root.hidden), render };
  // Le jeu s'ouvre toujours sur l'AKAI ; la page Live s'ouvre par ⚙ Réglages.
  setVisible(false);

  const css = document.createElement("style");
  css.textContent = `
#solo-live{position:fixed;inset:0;z-index:40;background:#080807;color:#f2efe6;display:flex;flex-direction:column;gap:12px;
  padding:max(12px,env(safe-area-inset-top)) max(16px,env(safe-area-inset-right)) max(14px,env(safe-area-inset-bottom)) max(16px,env(safe-area-inset-left));
  font-family:var(--f-label);overflow:hidden}
#solo-live[hidden]{display:none}
#solo-live button{font-family:var(--f-label);cursor:pointer;touch-action:manipulation;-webkit-user-select:none;user-select:none}
#solo-live button:focus-visible{outline:2px solid #E2CE16;outline-offset:2px}
.lv-head{display:flex;align-items:center;gap:12px;flex-shrink:0;height:clamp(44px,7vh,56px)}
.lv-brand{font-family:var(--f-title);font-size:clamp(26px,4vh,38px);line-height:1;letter-spacing:1px}.lv-brand span{color:#E2CE16}
.lv-zones{flex:1;display:flex;gap:8px;justify-content:center;overflow-x:auto;scrollbar-width:none}
.lv-zones button{flex-shrink:0;height:clamp(40px,6vh,48px);padding:0 20px;border-radius:24px;border:1px solid #2a2820;background:#13120e;
  color:#f2efe6;font-weight:700;font-size:clamp(15px,2.2vh,18px);letter-spacing:1.5px;text-transform:uppercase}
.lv-zones button.on{background:#E2CE16;color:#0c0b00;border-color:#E2CE16}
.lv-dmx{display:flex;align-items:center;gap:8px;height:clamp(40px,6vh,48px);padding:0 14px;border-radius:12px;border:1px solid #2a2820;
  background:transparent;color:#8a8577;font-weight:700;font-size:15px;letter-spacing:1.2px}
.lv-dmx i{width:9px;height:9px;border-radius:50%;background:#555}
.lv-dmx.ok{color:#9fdcb4}.lv-dmx.ok i{background:#22c55e;box-shadow:0 0 8px rgba(34,197,94,.9)}
.lv-dmx.err{color:#f19999;border-color:rgba(239,68,68,.45)}.lv-dmx.err i{background:#ef4444;box-shadow:0 0 8px rgba(239,68,68,.8)}
.lv-gear{width:clamp(40px,6vh,48px);height:clamp(40px,6vh,48px);border-radius:12px;border:1px solid rgba(226,206,22,.35);background:transparent;
  color:#E2CE16;display:grid;place-items:center;padding:0}.lv-gear svg{width:24px;height:24px}
.lv-body{flex:1;min-height:0;display:flex;gap:14px}
.lv-main{flex:1;min-width:0;display:flex;flex-direction:column;gap:clamp(8px,1.6vh,14px);min-height:0}
.lv-now{display:flex;align-items:center;gap:12px;min-height:36px;padding:0 16px;border-radius:12px;background:#0f0e0b;border:1px solid #1f1d17;
  font-size:clamp(15px,2.2vh,17px);color:#cfcabd;flex-shrink:0}
.lv-now i{width:14px;height:14px;border-radius:50%;flex-shrink:0;box-shadow:0 0 10px rgba(255,255,255,.15)}
.lv-now b{color:#f2efe6;letter-spacing:1.2px}.lv-now span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lv-main section{display:flex;flex-direction:column;gap:6px}
.lv-title{font-weight:700;font-size:13px;letter-spacing:2.5px;color:#E2CE16}
.lv-title small{margin-left:10px;font-size:13px;letter-spacing:.3px;font-weight:500;color:#8a8577}
.lv-colors{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:10px}
.lv-colors button{height:clamp(52px,10vh,80px);border-radius:16px;border:0;background:var(--c);color:rgba(255,255,255,.88);
  display:flex;align-items:flex-end;justify-content:center;padding:0 0 6px;font-weight:700;font-size:clamp(12px,1.8vh,14px);letter-spacing:1px;
  text-transform:uppercase;box-shadow:inset 0 -24px 30px rgba(0,0,0,.18)}
.lv-colors button.dark{color:rgba(0,0,0,.65)}
.lv-colors button.on{box-shadow:0 0 0 3px #080807,0 0 0 6px #E2CE16,0 0 22px var(--c)}
.lv-fx{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
.lv-fx button{height:clamp(50px,9vh,74px);border-radius:14px;border:1px solid #2a2820;background:#13120e;color:#f2efe6;display:flex;
  flex-direction:column;align-items:flex-start;justify-content:center;gap:2px;padding:0 14px;text-align:left;min-width:0}
.lv-fx b{font-family:var(--f-title);font-weight:400;font-size:clamp(20px,3.3vh,27px);line-height:1;letter-spacing:.5px}
.lv-fx small{font-size:clamp(12px,1.8vh,14px);opacity:.75;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:100%}
.lv-fx button.on{background:#E2CE16;color:#0c0b00;border-color:#E2CE16}
.lv-scn-sec{flex:1;min-height:0}
.lv-scenes{flex:1;min-height:0;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));grid-auto-rows:minmax(56px,92px);align-content:start;gap:10px;overflow-y:auto}
.lv-scenes button{border-radius:14px;border:1px solid #2a2820;background:#13120e;color:#f2efe6;display:flex;align-items:center;gap:12px;
  padding:0 14px;text-align:left;min-width:0;min-height:52px}
.lv-scenes button i{width:32px;height:32px;border-radius:10px;flex-shrink:0}
.lv-scenes button b{font-family:var(--f-title);font-weight:400;font-size:clamp(20px,3.2vh,26px);line-height:1;letter-spacing:.5px;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.lv-scenes button.on{background:rgba(226,206,22,.14);border:2px solid #E2CE16}
.lv-scenes button.add{border:1px dashed rgba(226,206,22,.5);background:transparent;color:#E2CE16;justify-content:center;gap:8px;
  font-weight:700;font-size:16px;letter-spacing:1.5px}.lv-scenes button.add svg{width:20px;height:20px}
.lv-side{width:clamp(200px,23vw,270px);flex-shrink:0;display:flex;flex-direction:column;gap:12px;min-height:0}
.lv-faders{flex:1;min-height:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.lv-fcard{display:flex;flex-direction:column;align-items:center;gap:8px;padding:12px 8px;border-radius:16px;background:#0f0e0b;border:1px solid #1f1d17;min-height:0}
.lv-flbl{font-weight:700;font-size:14px;letter-spacing:2px;color:#cfcabd}
.lv-fader{position:relative;flex:1;min-height:80px;width:46px;border-radius:12px;background:#1b1a15;touch-action:none;cursor:pointer}
.lv-fill{position:absolute;left:0;right:0;bottom:0;border-radius:12px;background:linear-gradient(0deg,rgba(226,206,22,.35),rgba(226,206,22,.75))}
.lv-thumb{position:absolute;left:-6px;right:-6px;height:22px;border-radius:8px;background:#f2efe6;box-shadow:0 2px 8px rgba(0,0,0,.6)}
.lv-fval{font-family:var(--f-title);font-size:clamp(24px,4vh,34px);line-height:1;color:#E2CE16}
.lv-tap{width:100%;height:40px;border-radius:10px;border:1px solid rgba(226,206,22,.45);background:transparent;color:#E2CE16;
  font-weight:700;font-size:15px;letter-spacing:1.5px}
.lv-tap:active{background:rgba(226,206,22,.2)}
.lv-flash,.lv-black{flex-shrink:0;border-radius:16px;font-family:var(--f-title)!important;letter-spacing:2px;touch-action:none}
.lv-flash{height:clamp(64px,12vh,96px);font-size:clamp(30px,5vh,40px);background:#E2CE16;color:#0c0b00;border:0}
.lv-flash.on{background:#fff;color:#080807;box-shadow:0 0 40px rgba(255,255,255,.6)}
.lv-black{height:clamp(52px,9vh,72px);font-size:clamp(24px,4vh,32px);background:#13120e;color:#f2efe6;border:1px solid #3a3830}
.lv-black.on{background:#000;color:#E2CE16;border:2px solid #E2CE16}
.lv-dialog{position:fixed;inset:0;z-index:55;background:rgba(0,0,0,.65);display:flex;align-items:center;justify-content:center}
.lv-dialog[hidden]{display:none}
.lv-dbox{width:min(88vw,420px);background:#11100e;border:1px solid rgba(226,206,22,.35);border-radius:16px;padding:18px;display:flex;flex-direction:column;gap:12px}
.lv-dbox label{font-weight:700;font-size:14px;letter-spacing:2px;color:#E2CE16;text-transform:uppercase}
.lv-dbox input{height:52px;padding:0 14px;border-radius:12px;border:1px solid #3a3830;background:#0c0b09;color:#f2efe6;font:700 22px/1 var(--f-label)}
.lv-drow{display:flex;gap:10px}.lv-drow button{flex:1;height:50px;border-radius:12px;font-weight:700;font-size:17px;letter-spacing:1.2px}
.lv-dcancel{background:transparent;border:1px solid #3a3830;color:#cfcabd}.lv-dok{background:#E2CE16;border:0;color:#0c0b00}
@media (orientation:portrait){
  .lv-body{flex-direction:column}
  .lv-colors{grid-template-columns:repeat(4,minmax(0,1fr))}
  .lv-fx{grid-template-columns:repeat(2,minmax(0,1fr))}
  .lv-scenes{grid-template-columns:repeat(2,minmax(0,1fr))}
  .lv-side{width:auto;flex-direction:row;height:clamp(190px,24vh,260px)}
  .lv-faders{flex:1.4}
  .lv-side>.lv-flash,.lv-side>.lv-black{flex:1;height:auto}
  .lv-zones{justify-content:flex-start}
}`;
  document.head.appendChild(css);
})();
