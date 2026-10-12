// Éditeur d'effets du mode sans PC : les COUCHES de l'éditeur du PC
// (effect_editor.py, EffectLayer), au doigt.
//
// Chargé après standalone.js (voir scripts/build-www.mjs). Un effet = une liste
// de couches ; chaque couche = un canal (couleur, intensité, mouvement…), une
// forme d'onde et ses réglages (VIT, AMP, DÉC, DÉPART…). Mêmes champs, mêmes
// noms et mêmes plages que le PC : engine.js (effectFrame) joue ces couches
// exactement comme MainWindow._update_effect_from_layers.
//
// Effets perso gardés sur la tablette (localStorage « mystrow.solo.fx », via
// standalone.js). Un effet de la bibliothèque n'est jamais modifié en place :
// « Modifier » en fait une copie perso.
// Aperçu : pendant l'édition, l'effet joue sur les projecteurs (et sur la
// mini-scène de l'éditeur) à la place de ce qui tournait ; il s'arrête à la
// fermeture.
(function () {
  "use strict";
  const Solo = window.MystrowSolo;
  if (!window.MYSTROW_SOLO || !Solo || !Solo.core) return;
  const C = Solo.core;

  // [attribut moteur, libellé, aide]
  const ATTRS = [
    ["RGB", "Couleur", "la couleur 1 suit la forme"],
    ["Permut", "Permutation", "passe de la couleur 1 à la couleur 2"],
    ["Dimmer", "Intensité", "fait varier la couleur posée sur l'AKAI"],
    ["Strobe", "Strobe", "intensité hachée"],
    ["R", "Rouge", "canal rouge seul"],
    ["V", "Vert", "canal vert seul"],
    ["B", "Bleu", "canal bleu seul"],
    ["Pan/Tilt", "Mouvement", "trajectoire des lyres"],
    ["Pan", "Pan", "balayage gauche-droite"],
    ["Tilt", "Tilt", "balayage haut-bas"],
  ];
  const MOVE = new Set(["Pan", "Tilt", "Pan/Tilt"]);
  const FORMES = ["Sinus", "Flash", "Triangle", "Montée", "Descente", "Un par un", "Aléatoire", "Fixe", "Off"];
  const SHAPES = [["cercle", "○ Cercle"], ["huit", "8 Huit"], ["infini", "∞ Infini"], ["balancier", "↔ Balancier"],
                  ["pendule", "↕ Pendule"], ["carre", "□ Carré"]];
  // core.SPREAD_MODES du PC
  const SPREAD = [["lineaire", "Linéaire", "1, 2, 3, 4… — chenillard classique"],
                  ["miroir", "Miroir (centre)", "part du centre vers les extrémités"],
                  ["miroir_in", "Miroir (bords)", "1&8, puis 2&7, puis 3&6"],
                  ["pair_impair", "Pair / impair", "une fixture sur deux, en alternance"],
                  ["aleatoire", "Aléatoire", "ordre dispersé, mais reproductible"]];
  const SENS = [[1, "→ Avant"], [-1, "← Arrière"], [0, "↔ Aller-retour"]];
  const PALETTE = ["#ffffff", "#ff0000", "#ff8800", "#ffdd00", "#00ff00", "#00dddd", "#0000ff", "#ff00ff",
                   "#ffaa00", "#ff66aa", "#aaff00", "#8800ff"];
  // Réglages numériques : [champ, libellé, min, max, pas, défaut, aide]. AMP monte
  // à 400 sur les couches de mouvement (LayerRow._AMP_MAX_PT du PC).
  const NUMS = [
    ["speed", "VIT", 0, 100, 0.1, 50, "vitesse du cycle"],
    ["size", "AMP", 0, 100, 1, 100, "force de l'effet"],
    ["spread", "DÉC", 0, 360, 1, 0, "décalage entre projecteurs (0 = tous ensemble)"],
    ["phase", "DÉPART", 0, 100, 1, 0, "décale le départ de la couche"],
    ["fade", "FONDU", 0, 100, 1, 0, "adoucit la forme"],
    ["min_val", "MIN", 0, 100, 1, 0, "plancher"],
    ["max_val", "MAX", 0, 100, 1, 100, "plafond"],
    ["block", "GROUPER", 1, 16, 1, 1, "projecteurs qui partent ensemble"],
  ];
  const newLayer = () => ({
    attribute: "RGB", forme: "Sinus", target_preset: "Tous", target_groups: [],
    speed: 50, size: 100, spread: 0, phase: 0, fade: 0, direction: 1, min_val: 0, max_val: 100,
    color1: "#ff0000", color2: "#0000ff", mouvement_shape: "cercle", sym_pan: false, sym_tilt: false,
    spread_mode: "lineaire", block: 1,
  });
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const groupName = (g) => (C.show.groupNames && C.show.groupNames[g]) || "";

  // ── État de l'édition ───────────────────────────────────────────────────────
  let draft = null;            // effet en cours d'édition (copie)
  let origCustom = null;       // nom de l'effet perso d'origine (null = nouveau / copie)
  let sel = 0;                 // couche affichée
  let dirty = false;
  let previewOn = true;
  let onSaved = null;          // rappel : poser l'effet sur un bouton / pad
  let tick = null;

  const root = document.createElement("div");
  root.id = "fxe";
  root.hidden = true;
  root.innerHTML = `
    <header class="fxe-head">
      <button type="button" class="fxe-back">‹ Retour</button>
      <input class="fxe-name" maxlength="32" autocomplete="off" aria-label="Nom de l'effet">
      <button type="button" class="fxe-prev" aria-pressed="true"><i></i>APERÇU</button>
      <button type="button" class="fxe-save">ENREGISTRER</button>
    </header>
    <div class="fxe-body">
      <aside class="fxe-side">
        <div class="fxe-stage"><canvas></canvas><p class="fxe-hint" hidden></p></div>
        <div class="fxe-ttl">COUCHES</div>
        <div class="fxe-layers"></div>
        <button type="button" class="fxe-add">＋ AJOUTER UNE COUCHE</button>
        <button type="button" class="fxe-del" hidden>Supprimer l'effet</button>
      </aside>
      <main class="fxe-main"></main>
    </div>`;
  document.body.appendChild(root);
  const $ = (s) => root.querySelector(s);

  function touch() { dirty = true; renderLayers(); updateHint(); }

  // ── Ouverture / fermeture ───────────────────────────────────────────────────
  // name : effet à modifier (null = nouveau). after(name) : appelé après
  // l'enregistrement, avec le nom final.
  function open(name, after) {
    const src = name ? C.getEffect(name) : null;
    const isCustom = !!(src && C.customEffects().some((e) => e.name === name));
    if (src) {
      draft = { name: isCustom ? src.name : freeName(src.name + " (perso)"), no_color: !!src.no_color,
                layers: clone(src.layers || []).map((ld) => ({ ...newLayer(), ...ld })) };
    } else {
      draft = { name: freeName("Mon effet"), layers: [newLayer()] };
    }
    if (!draft.layers.length) draft.layers.push(newLayer());
    origCustom = isCustom ? name : null;
    onSaved = after || null;
    sel = 0; dirty = !isCustom && !!src;          // une copie n'existe pas encore : à enregistrer
    $(".fxe-name").value = draft.name;
    $(".fxe-del").hidden = !isCustom;
    root.hidden = false;
    setPreview(true);
    render();
    clearInterval(tick);
    tick = setInterval(drawStage, 80);
  }
  function close() {
    root.hidden = true;
    clearInterval(tick); tick = null;
    C.setPreview(null);
    draft = null;
  }
  function freeName(base) {
    const taken = (n) => !!C.getEffect(n) && n !== origCustom;
    if (!taken(base)) return base;
    for (let i = 2; ; i++) if (!taken(base + " " + i)) return base + " " + i;
  }
  function setPreview(on) {
    previewOn = on;
    $(".fxe-prev").classList.toggle("on", on);
    $(".fxe-prev").setAttribute("aria-pressed", on);
    C.setPreview(on ? draft : null);
    updateHint();
  }

  $(".fxe-back").addEventListener("click", () => {
    if (!dirty) { close(); return; }
    Solo.openMenu("Quitter l'éditeur ?", [
      ["Enregistrer", () => saveDraft()],
      ["Quitter sans enregistrer", () => close(), "danger"],
    ], "Les changements de « " + draft.name + " » ne sont pas enregistrés.");
  });
  $(".fxe-prev").addEventListener("click", () => setPreview(!previewOn));
  $(".fxe-save").addEventListener("click", () => saveDraft());
  $(".fxe-name").addEventListener("input", () => { dirty = true; });
  $(".fxe-del").addEventListener("click", () => {
    Solo.openMenu("Supprimer « " + origCustom + " » ?", [
      ["Supprimer l'effet", () => { C.deleteCustomEffect(origCustom); Solo.toast("Effet supprimé"); close(); }, "danger"],
    ], "Les boutons et pads qui le portaient n'auront plus d'effet. Les mémoires gardent leur copie.");
  });
  $(".fxe-add").addEventListener("click", () => {
    const base = draft.layers[sel];
    // Nouvelle couche : même cible que la couche affichée, le plus souvent voulu.
    draft.layers.push({ ...newLayer(), target_preset: base ? base.target_preset : "Tous",
                        target_groups: base ? (base.target_groups || []).slice() : [] });
    sel = draft.layers.length - 1;
    touch(); renderMain();
  });

  function saveDraft() {
    let name = $(".fxe-name").value.trim();
    if (!name) { Solo.toast("Donnez un nom à l'effet"); $(".fxe-name").focus(); return; }
    // Le nom d'un effet de la bibliothèque reste à la bibliothèque.
    if (C.builtinByName[name]) name = freeName(name + " (perso)");
    else if (name !== origCustom && C.getEffect(name)) name = freeName(name);
    draft.name = name;
    C.saveCustomEffect(draft, origCustom);
    Solo.toast("Effet « " + name + " » enregistré");
    const cb = onSaved;
    close();
    if (cb) cb(name);
  }

  // ── Liste des couches ───────────────────────────────────────────────────────
  const attrLabel = (a) => (ATTRS.find(([k]) => k === a) || [a, a])[1];
  function layerSummary(ld) {
    const what = MOVE.has(ld.attribute) && ld.attribute === "Pan/Tilt"
      ? (SHAPES.find(([k]) => k === ld.mouvement_shape) || ["", "Cercle"])[1] : ld.forme;
    const target = (ld.target_groups || []).length ? (ld.target_groups || []).join("+")
      : /^[A-H]$/.test(ld.target_preset) ? ld.target_preset : ld.target_preset;
    return what + " · " + target;
  }
  function renderLayers() {
    const box = $(".fxe-layers");
    box.innerHTML = "";
    draft.layers.forEach((ld, i) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "fxe-layer" + (i === sel ? " on" : "");
      b.innerHTML = "<i></i><span><b></b><small></small></span>";
      const dot = b.querySelector("i");
      if (ld.attribute === "RGB") dot.style.background = ld.color1;
      else if (ld.attribute === "Permut") dot.style.background = "linear-gradient(135deg," + ld.color1 + " 50%," + ld.color2 + " 50%)";
      else if (MOVE.has(ld.attribute)) { dot.textContent = "✥"; dot.className = "mv"; }
      else dot.style.background = { R: "#ff2020", V: "#20ff40", B: "#2050ff" }[ld.attribute] || "#c9c4b4";
      b.querySelector("b").textContent = (i + 1) + ". " + attrLabel(ld.attribute);
      b.querySelector("small").textContent = layerSummary(ld);
      b.addEventListener("click", () => { sel = i; renderLayers(); renderMain(); });
      box.appendChild(b);
    });
  }

  // ── Réglages de la couche affichée ──────────────────────────────────────────
  function section(title, help) {
    const s = document.createElement("section");
    s.className = "fxe-sec";
    s.innerHTML = '<div class="fxe-ttl"></div>';
    s.firstChild.textContent = title;
    if (help) { const h = document.createElement("small"); h.textContent = help; s.firstChild.appendChild(h); }
    $(".fxe-main").appendChild(s);
    return s;
  }
  function chips(sec, items, isOn, onPick, cls) {
    const row = document.createElement("div");
    row.className = "fxe-chips" + (cls ? " " + cls : "");
    items.forEach(([val, label, help]) => {
      const b = document.createElement("button");
      b.type = "button"; b.textContent = label;
      if (help) b.title = help;
      b.classList.toggle("on", isOn(val));
      b.addEventListener("click", () => { onPick(val); touch(); renderMain(); });
      row.appendChild(b);
    });
    sec.appendChild(row);
    return row;
  }
  function colorRow(sec, ld, key, label) {
    const row = document.createElement("div");
    row.className = "fxe-colors";
    const lbl = document.createElement("span"); lbl.textContent = label; row.appendChild(lbl);
    PALETTE.forEach((hex) => {
      const b = document.createElement("button");
      b.type = "button"; b.style.background = hex; b.title = hex;
      b.classList.toggle("on", (ld[key] || "").toLowerCase() === hex);
      b.addEventListener("click", () => { ld[key] = hex; touch(); renderMain(); });
      row.appendChild(b);
    });
    // Couleur libre : sélecteur natif (absent de certains WebView : la palette suffit).
    const inp = document.createElement("input");
    inp.type = "color"; inp.value = ld[key] || "#ffffff"; inp.title = "Autre couleur";
    inp.addEventListener("input", () => { ld[key] = inp.value; touch(); });
    inp.addEventListener("change", () => renderMain());
    row.appendChild(inp);
    sec.appendChild(row);
  }
  function numRow(sec, ld, [key, label, min, max, step, def, help]) {
    const row = document.createElement("div");
    row.className = "fxe-num";
    row.innerHTML = '<span></span><button type="button" class="m">−</button><input type="range"><button type="button" class="p">+</button><b></b>';
    row.querySelector("span").textContent = label;
    row.querySelector("span").title = help;
    const inp = row.querySelector("input"), val = row.querySelector("b");
    inp.min = min; inp.max = max; inp.step = step;
    const fmt = (v) => (step < 1 ? (Math.round(v * 10) / 10).toString().replace(".", ",") : String(Math.round(v)));
    const set = (v) => {
      v = Math.max(min, Math.min(max, Math.round(v / step) * step));
      if (step < 1) v = Math.round(v * 10) / 10;
      ld[key] = v; inp.value = v; val.textContent = fmt(v);
      if (key === "min_val" && ld.max_val < v) ld.max_val = v;
      if (key === "max_val" && ld.min_val > v) ld.min_val = v;
      touch();
    };
    inp.value = ld[key] ?? def; val.textContent = fmt(ld[key] ?? def);
    inp.addEventListener("input", () => set(+inp.value));
    inp.addEventListener("change", () => { if (key === "min_val" || key === "max_val") renderMain(); });
    row.querySelector(".m").addEventListener("click", () => set((ld[key] ?? def) - (step < 1 ? 1 : step)));
    row.querySelector(".p").addEventListener("click", () => set((ld[key] ?? def) + (step < 1 ? 1 : step)));
    // Toucher la valeur = valeur par défaut.
    val.title = "Toucher : " + def;
    val.addEventListener("click", () => set(def));
    sec.appendChild(row);
  }

  function renderMain() {
    const main = $(".fxe-main");
    main.innerHTML = "";
    const ld = draft.layers[sel];
    if (!ld) return;
    const isMove = MOVE.has(ld.attribute);

    // En-tête de la couche : déplacer, dupliquer, supprimer.
    const head = document.createElement("div");
    head.className = "fxe-lhead";
    head.innerHTML = '<b></b><button type="button" data-a="up" aria-label="Monter">▲</button><button type="button" data-a="down" aria-label="Descendre">▼</button>' +
      '<button type="button" data-a="dup">Dupliquer</button><button type="button" data-a="del" class="danger">Supprimer</button>';
    head.querySelector("b").textContent = "COUCHE " + (sel + 1) + " / " + draft.layers.length;
    head.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      const a = b.dataset.a, L = draft.layers;
      if (a === "up" && sel > 0) { [L[sel - 1], L[sel]] = [L[sel], L[sel - 1]]; sel--; }
      else if (a === "down" && sel < L.length - 1) { [L[sel + 1], L[sel]] = [L[sel], L[sel + 1]]; sel++; }
      else if (a === "dup") { L.splice(sel + 1, 0, clone(ld)); sel++; }
      else if (a === "del") {
        if (L.length === 1) { Solo.toast("Un effet garde au moins une couche"); return; }
        L.splice(sel, 1); sel = Math.min(sel, L.length - 1);
      } else return;
      touch(); renderMain();
    }));
    main.appendChild(head);

    chips(section("CANAL", "ce que la couche fait varier"), ATTRS, (v) => v === ld.attribute, (v) => {
      ld.attribute = v;
      if (!MOVE.has(v) && ld.size > 100) ld.size = 100;
    });
    if (isMove && !C.projectors.some(C.isLyre)) {
      const w = document.createElement("p"); w.className = "fxe-warn";
      w.textContent = "Pas de lyre dans le patch : cette couche ne bougera rien.";
      main.lastChild.appendChild(w);
    }

    if (ld.attribute === "Pan/Tilt") {
      chips(section("TRAJECTOIRE"), SHAPES, (v) => v === (ld.mouvement_shape || "cercle"), (v) => { ld.mouvement_shape = v; });
    } else {
      chips(section("FORME", "allure de la variation dans le temps"), FORMES.map((f) => [f, f]), (v) => v === ld.forme, (v) => { ld.forme = v; });
    }

    if (ld.attribute === "RGB" || ld.attribute === "Permut") {
      const s = section("COULEURS");
      colorRow(s, ld, "color1", ld.attribute === "Permut" ? "1" : "");
      if (ld.attribute === "Permut") colorRow(s, ld, "color2", "2");
    }

    // Cible : tous / pairs / impairs, et/ou des groupes précis.
    const groups = (ld.target_groups || []).slice();
    if (/^[A-H]$/.test(ld.target_preset)) { if (!groups.includes(ld.target_preset)) groups.push(ld.target_preset); ld.target_preset = "Tous"; ld.target_groups = groups; }
    const sc = section("CIBLE", "projecteurs concernés par la couche");
    chips(sc, [["Tous", "Tous"], ["Pair", "Pairs"], ["Impair", "Impairs"]], (v) => v === ld.target_preset, (v) => { ld.target_preset = v; });
    if (C.usedGroups.length > 1) {
      chips(sc, C.usedGroups.map((g) => [g, groupName(g) ? g + " · " + groupName(g) : "Groupe " + g]),
        (v) => (ld.target_groups || []).includes(v),
        (v) => { const t = new Set(ld.target_groups || []); if (t.has(v)) t.delete(v); else t.add(v); ld.target_groups = C.usedGroups.filter((g) => t.has(g)); },
        "groups");
      const h = document.createElement("small"); h.className = "fxe-note";
      h.textContent = (ld.target_groups || []).length ? "Seulement les groupes allumés en jaune." : "Aucun groupe coché : tous les groupes.";
      sc.appendChild(h);
    }

    const sn = section("RÉGLAGES", "toucher une valeur = valeur par défaut");
    NUMS.forEach((n) => {
      if (isMove && (n[0] === "min_val" || n[0] === "max_val" || n[0] === "fade")) return;
      if (n[0] === "size" && isMove) n = ["size", "AMP", 0, 400, 1, 100, "largeur du mouvement (100 = petit, 400 = toute la course)"];
      numRow(sn, ld, n);
    });

    chips(section("RÉPARTITION", "ordre dans lequel le décalage (DÉC) parcourt les projecteurs"),
      SPREAD, (v) => v === (ld.spread_mode || "lineaire"), (v) => { ld.spread_mode = v; });
    chips(section("SENS"), SENS, (v) => v === (ld.direction ?? 1), (v) => { ld.direction = v; });
    if (isMove) {
      chips(section("SYMÉTRIE", "les lyres de l'autre côté partent en miroir"),
        [["sym_pan", "SYM PAN"], ["sym_tilt", "SYM TILT"]], (v) => !!ld[v], (v) => { ld[v] = !ld[v]; });
    }
  }

  function render() { renderLayers(); renderMain(); updateHint(); }

  // ── Mini-scène : ce que jouent les projecteurs, en direct ───────────────────
  function drawStage() {
    if (root.hidden) return;
    const cv = $(".fxe-stage canvas"), box = cv.parentElement;
    const w = box.clientWidth, h = box.clientHeight, dpr = window.devicePixelRatio || 1;
    if (cv.width !== Math.round(w * dpr) || cv.height !== Math.round(h * dpr)) { cv.width = Math.round(w * dpr); cv.height = Math.round(h * dpr); }
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    const states = C.lastStates(), P = C.projectors;
    const r = Math.max(6, Math.min(16, w / (2.6 * Math.max(4, ...C.usedGroups.map((g) => (C.byGroup[g] || []).length)))));
    P.forEach((p, i) => {
      const s = states[i];
      if (!s) return;
      const x = 12 + (p.x ?? 0.5) * (w - 24), y = 12 + (p.y ?? 0.5) * (h - 24);
      let rgb;
      if (s.fx) rgb = s.fx;
      else if (s.muted || !s.level) rgb = [0, 0, 0];
      else { const c = parseInt((s.color || "#000000").slice(1), 16); const k = s.level / 100; rgb = [(c >> 16 & 255) * k, (c >> 8 & 255) * k, (c & 255) * k]; }
      ctx.beginPath(); ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = "rgb(" + rgb.map((v) => v | 0).join(",") + ")"; ctx.fill();
      ctx.lineWidth = 1; ctx.strokeStyle = "#3a3830"; ctx.stroke();
      if (C.isLyre(p)) {                                // visée de la lyre
        const dx = ((s.pan ?? 32768) / 65535 - 0.5) * 2 * r * 1.6, dy = ((s.tilt ?? 32768) / 65535 - 0.5) * 2 * r * 1.6;
        ctx.beginPath(); ctx.arc(x + dx, y + dy, 2.5, 0, Math.PI * 2);
        ctx.fillStyle = "#E2CE16"; ctx.fill();
      }
    });
  }
  // Effet d'intensité seul sur des projecteurs éteints : rien à voir.
  function updateHint() {
    const el = $(".fxe-hint");
    if (!draft) return;
    const onlyDim = draft.layers.every((ld) => ld.attribute === "Dimmer" || ld.attribute === "Strobe");
    const lit = C.lastStates().some((s) => s && s.level > 0 && s.color && s.color !== "#000000");
    el.hidden = !(previewOn && onlyDim && !lit);
    el.textContent = "Effet d'intensité : allumez une couleur sur l'AKAI pour le voir.";
    if (!previewOn) { el.hidden = false; el.textContent = "Aperçu coupé : les projecteurs jouent ce qui tournait avant."; }
  }

  window.MystrowFxEditor = { open, close, isOpen: () => !root.hidden };

  const css = document.createElement("style");
  css.textContent = `
#fxe{position:fixed;inset:0;z-index:46;background:#080807;color:#f2efe6;display:flex;flex-direction:column;gap:10px;
  padding:max(10px,env(safe-area-inset-top)) max(14px,env(safe-area-inset-right)) max(10px,env(safe-area-inset-bottom)) max(14px,env(safe-area-inset-left));
  font-family:var(--f-label)}
#fxe[hidden]{display:none}
#fxe button{font-family:var(--f-label);cursor:pointer;touch-action:manipulation;-webkit-user-select:none;user-select:none}
#fxe button:focus-visible,#fxe input:focus-visible{outline:2px solid #E2CE16;outline-offset:2px}
.fxe-head{display:flex;align-items:center;gap:10px;flex-shrink:0}
.fxe-head>button{height:48px;padding:0 16px;border-radius:12px;font-weight:700;font-size:16px;letter-spacing:1.2px;white-space:nowrap}
.fxe-back{background:transparent;border:1px solid #3a3830;color:#cfcabd}
.fxe-name{flex:1;min-width:0;height:48px;padding:0 14px;border-radius:12px;border:1px solid #3a3830;background:#0c0b09;color:#f2efe6;
  font:400 26px/1 var(--f-title);letter-spacing:.5px}
.fxe-prev{display:flex;align-items:center;gap:8px;background:transparent;border:1px solid #3a3830;color:#8a8577}
.fxe-prev i{width:10px;height:10px;border-radius:50%;background:#555}
.fxe-prev.on{color:#9fdcb4;border-color:rgba(34,197,94,.5)}.fxe-prev.on i{background:#22c55e;box-shadow:0 0 8px rgba(34,197,94,.9)}
.fxe-save{background:#E2CE16;border:0;color:#0c0b00}
.fxe-body{flex:1;min-height:0;display:flex;gap:14px}
.fxe-side{width:clamp(220px,26vw,300px);flex-shrink:0;display:flex;flex-direction:column;gap:8px;min-height:0}
.fxe-stage{position:relative;height:clamp(110px,20vh,170px);flex-shrink:0;border-radius:12px;background:#0f0e0b;border:1px solid #1f1d17;overflow:hidden}
.fxe-stage canvas{position:absolute;inset:0;width:100%;height:100%}
.fxe-hint{position:absolute;left:8px;right:8px;bottom:6px;margin:0;font-size:12px;line-height:1.3;color:#E2CE16;text-align:center;
  background:rgba(8,8,7,.8);border-radius:8px;padding:4px 6px}
.fxe-hint[hidden]{display:none}
.fxe-ttl{font-weight:700;font-size:13px;letter-spacing:2.5px;color:#E2CE16}
.fxe-ttl small{margin-left:10px;font-size:12px;letter-spacing:.3px;font-weight:500;color:#8a8577}
.fxe-layers{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:6px}
.fxe-layer{display:flex;align-items:center;gap:10px;min-height:56px;padding:6px 10px;border-radius:12px;border:1px solid #2a2820;
  background:#13120e;color:#f2efe6;text-align:left}
.fxe-layer.on{border:2px solid #E2CE16;background:rgba(226,206,22,.10)}
.fxe-layer i{width:26px;height:26px;border-radius:8px;flex-shrink:0;display:grid;place-items:center;font-style:normal;font-size:16px}
.fxe-layer i.mv{background:#1d2a4a;color:#9fb8ff}
.fxe-layer span{display:flex;flex-direction:column;min-width:0}
.fxe-layer b{font-size:16px;letter-spacing:.5px}
.fxe-layer small{font-size:12px;color:#8a8577;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.fxe-add{min-height:48px;border-radius:12px;border:1px dashed rgba(226,206,22,.55);background:transparent;color:#E2CE16;font-weight:700;font-size:15px;letter-spacing:1.2px}
.fxe-del{min-height:40px;border-radius:10px;border:1px solid rgba(248,113,113,.45);background:transparent;color:#f87171;font-weight:700;font-size:14px}
.fxe-del[hidden]{display:none}
.fxe-main{flex:1;min-width:0;overflow-y:auto;display:flex;flex-direction:column;gap:14px;padding:2px 4px 16px 0}
.fxe-lhead{display:flex;align-items:center;gap:8px;position:sticky;top:0;z-index:1;background:#080807;padding-bottom:4px}
.fxe-lhead b{flex:1;font-family:var(--f-title);font-weight:400;font-size:24px;letter-spacing:1px}
.fxe-lhead button{height:40px;min-width:44px;padding:0 12px;border-radius:10px;border:1px solid #3a3830;background:#13120e;color:#f2efe6;font-weight:700;font-size:14px}
.fxe-lhead button.danger{color:#f87171;border-color:rgba(248,113,113,.45)}
.fxe-sec{display:flex;flex-direction:column;gap:8px}
.fxe-chips{display:flex;flex-wrap:wrap;gap:6px}
.fxe-chips button{min-height:42px;padding:0 14px;border-radius:21px;border:1px solid #2a2820;background:#13120e;color:#f2efe6;font-weight:700;font-size:15px}
.fxe-chips button.on{background:#E2CE16;border-color:#E2CE16;color:#0c0b00}
.fxe-chips.groups button.on{background:rgba(226,206,22,.18);color:#E2CE16}
.fxe-note{font-size:12px;color:#8a8577}
.fxe-warn{margin:0;font-size:13px;color:#f19999}
.fxe-colors{display:flex;flex-wrap:wrap;align-items:center;gap:8px}
.fxe-colors span{min-width:14px;font-weight:700;color:#8a8577}
.fxe-colors button{width:40px;height:40px;border-radius:10px;border:2px solid #2a2820;padding:0}
.fxe-colors button.on{border-color:#E2CE16;box-shadow:0 0 0 2px #080807 inset}
.fxe-colors input{width:48px;height:40px;padding:0;border:1px solid #3a3830;border-radius:10px;background:#0c0b09}
.fxe-num{display:grid;grid-template-columns:78px 40px 1fr 40px 54px;align-items:center;gap:8px}
.fxe-num span{font-weight:700;font-size:14px;letter-spacing:1.5px;color:#cfcabd}
.fxe-num button{height:40px;border-radius:10px;border:1px solid #3a3830;background:#13120e;color:#f2efe6;font-size:20px;font-weight:700;padding:0}
.fxe-num input{width:100%;accent-color:#E2CE16;height:32px}
.fxe-num b{font-family:var(--f-title);font-weight:400;font-size:24px;color:#E2CE16;text-align:right;cursor:pointer;font-variant-numeric:tabular-nums}
@media (orientation:portrait){
  .fxe-body{flex-direction:column}
  .fxe-side{width:auto;max-height:42vh}
  .fxe-layers{flex-direction:row;flex-wrap:wrap;flex:none;max-height:22vh}
  .fxe-layer{flex:1 1 200px}
  .fxe-head>button{padding:0 10px;font-size:14px}
}`;
  document.head.appendChild(css);
})();
