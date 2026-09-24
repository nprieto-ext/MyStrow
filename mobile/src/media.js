// Mode autonome : playlist audio et cartouches, jouées par la tablette.
//
// Chargé après standalone.js, actif seulement avec ?solo=1. Reçoit les
// actions MEDIA de l'interface (transport, seq_row, cartouche) par
// window.MystrowSoloMedia, renvoie l'état à la page avec les MÊMES messages
// que le PC (seq, seq_row, cart) : l'onglet MEDIA n'est pas dupliqué.
//
// Les fichiers sont COPIÉS dans la tablette (IndexedDB « mystrow-media ») :
// la playlist marche encore si la clé USB ou le fichier d'origine disparaît.
// L'ordre de la playlist et les cartouches : localStorage mystrow.solo.media.
//
// Gestes propres au mode autonome :
//   « + AJOUTER » (en-tête MEDIA)   choisir un ou plusieurs morceaux
//   appui long sur un morceau        monter / descendre / retirer
//   appui long sur une cartouche     choisir son son (ou la vider)
(function () {
  "use strict";
  if (!window.MYSTROW_SOLO || !window.MystrowSolo || !window.MystrowSolo.mediaEnabled) return;
  const { emit, toast, openMenu } = window.MystrowSolo;

  // ── Fichiers (IndexedDB) ───────────────────────────────────────────────────
  let dbp = null;
  function db() {
    dbp = dbp || new Promise((res, rej) => {
      const r = indexedDB.open("mystrow-media", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("files", { keyPath: "id" });
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
    return dbp;
  }
  async function tx(mode, fn) {
    const d = await db();
    return new Promise((res, rej) => {
      const t = d.transaction("files", mode);
      const req = fn(t.objectStore("files"));
      t.oncomplete = () => res(req && req.result);
      t.onerror = () => rej(t.error);
      t.onabort = () => rej(t.error || new Error("stockage plein ?"));
    });
  }
  const putFile = (rec) => tx("readwrite", (s) => s.put(rec));
  const getFile = (id) => tx("readonly", (s) => s.get(id));
  const delFile = (id) => tx("readwrite", (s) => s.delete(id));

  // ── État ───────────────────────────────────────────────────────────────────
  let lib;
  try { lib = JSON.parse(localStorage.getItem("mystrow.solo.media") || "null"); } catch (e) {}
  lib = Object.assign({ playlist: [], carts: [null, null, null, null] }, lib || {});
  const saveLib = () => { try { localStorage.setItem("mystrow.solo.media", JSON.stringify(lib)); } catch (e) {} };
  // Un fichier n'est effacé que si plus rien (playlist, cartouche) ne s'en sert.
  function usedIds() { return new Set([...lib.playlist.map((it) => it.id), ...lib.carts.filter(Boolean).map((c) => c.id)]); }
  async function forget(id) { if (!usedIds().has(id)) await delFile(id).catch(() => {}); }

  const fmt = (s) => (s > 0 && isFinite(s) ? Math.floor(s / 60) + ":" + String(Math.floor(s % 60)).padStart(2, "0") : "");
  const player = new Audio();
  let current = -1;
  const playing = () => !player.paused && !player.ended;

  function seqMsg() {
    emit({
      type: "seq",
      items: lib.playlist.map((it) => ({ type: "media", title: it.title, dur: fmt(it.dur), vol: "" })),
      current_row: current, playing: playing(),
    });
  }
  const rowMsg = () => emit({ type: "seq_row", current_row: current, playing: playing() });
  player.addEventListener("play", rowMsg);
  player.addEventListener("pause", rowMsg);
  // Fin du morceau : on enchaîne ; après le dernier, la playlist s'arrête.
  player.addEventListener("ended", () => { if (current + 1 < lib.playlist.length) playRow(current + 1); else rowMsg(); });

  let url = null;
  async function load(el, id) {
    const rec = await getFile(id);
    if (!rec) throw new Error("fichier introuvable dans la tablette");
    if (el === player) { if (url) URL.revokeObjectURL(url); url = URL.createObjectURL(rec.blob); el.src = url; }
    else { if (el._url) URL.revokeObjectURL(el._url); el._url = URL.createObjectURL(rec.blob); el.src = el._url; }
  }
  async function playRow(i) {
    const it = lib.playlist[i];
    if (!it) return;
    try {
      current = i;
      await load(player, it.id);
      await player.play();
    } catch (e) {
      toast("Lecture impossible : " + (e.message || e));
    }
    rowMsg();
  }

  // ── Cartouches : un son chacune, appui = lecture, réappui = stop ──────────
  const cartPlayers = [0, 1, 2, 3].map((idx) => {
    const a = new Audio();
    const msg = () => emit({ type: "cart", idx, title: lib.carts[idx] ? lib.carts[idx].title : "—", state: !a.paused && !a.ended ? 1 : 0 });
    a.addEventListener("play", msg); a.addEventListener("pause", msg); a.addEventListener("ended", msg);
    a._msg = msg;
    return a;
  });
  async function toggleCart(idx) {
    const c = lib.carts[idx], a = cartPlayers[idx];
    if (!c) { toast("Cartouche vide : appui long pour choisir un son"); return; }
    if (!a.paused && !a.ended) { a.pause(); a.currentTime = 0; return; }
    try { await load(a, c.id); a.currentTime = 0; await a.play(); } catch (e) { toast("Lecture impossible : " + (e.message || e)); }
  }

  // ── Actions de l'interface ─────────────────────────────────────────────────
  window.MystrowSoloMedia = function (ev) {
    switch (ev.type) {
      case "transport":
        if (ev.action === "play_pause") {
          if (current < 0 || !player.src) playRow(Math.max(0, current));
          else if (playing()) player.pause();
          else player.play().catch(() => {});
        } else if (ev.action === "next") {
          if (current + 1 < lib.playlist.length) playRow(current + 1);
        } else if (ev.action === "prev") {
          // Comme un lecteur : au-delà de 3 s, « précédent » reprend le morceau.
          if (player.currentTime > 3 || current <= 0) { player.currentTime = 0; }
          else playRow(current - 1);
        }
        return true;
      case "seq_row":
        if (skipClick) { skipClick = false; return true; }
        if (ev.row === current && player.src) { if (playing()) player.pause(); else player.play().catch(() => {}); }
        else playRow(ev.row);
        return true;
      case "cartouche":
        toggleCart(ev.idx);
        return true;
    }
    return false;
  };

  // ── Ajouter des morceaux ───────────────────────────────────────────────────
  function duration(blob) {
    return new Promise((res) => {
      const a = new Audio(), u = URL.createObjectURL(blob);
      const done = () => { URL.revokeObjectURL(u); res(a.duration || 0); };
      a.preload = "metadata"; a.onloadedmetadata = done; a.onerror = done; a.src = u;
      setTimeout(done, 5000);
    });
  }
  async function importFile(file) {
    const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
    // Copie des octets : un File Android pointe sur l'original, qui peut disparaître.
    const blob = new Blob([await file.arrayBuffer()], { type: file.type || "audio/mpeg" });
    await putFile({ id, name: file.name, blob });
    return { id, title: file.name.replace(/\.[^.]+$/, ""), dur: await duration(blob) };
  }
  function chooseFiles(multiple) {
    return new Promise((res) => {
      const inp = document.createElement("input");
      inp.type = "file"; inp.accept = "audio/*"; inp.multiple = multiple;
      inp.onchange = () => res([...(inp.files || [])]);
      inp.click();
    });
  }
  async function addTracks() {
    const files = await chooseFiles(true);
    if (!files.length) return;
    toast(files.length > 1 ? `Import de ${files.length} morceaux…` : "Import…");
    let ok = 0;
    for (const f of files) {
      try { lib.playlist.push(await importFile(f)); ok++; saveLib(); seqMsg(); }
      catch (e) { toast(`« ${f.name} » : ${e.message || e}`); }
    }
    if (ok) toast(ok > 1 ? `${ok} morceaux ajoutés` : "Morceau ajouté");
  }

  // ── Habillage ──────────────────────────────────────────────────────────────
  const style = document.createElement("style");
  style.textContent =
    "#media-add{flex-shrink:0;height:clamp(46px,8.4vh,76px);padding:0 clamp(14px,2vw,22px);border-radius:12px;" +
    "border:1px solid rgba(226,206,22,.45);background:rgba(226,206,22,.10);color:#E2CE16;font-family:var(--f-label);" +
    "font-weight:700;font-size:clamp(14px,1.8vw,18px);letter-spacing:1.5px;cursor:pointer;touch-action:manipulation}" +
    "#media-prog{display:flex;align-items:center;gap:10px;margin-top:4px}" +
    "#media-prog span{font-family:var(--f-label);font-weight:700;font-size:13px;color:var(--muted);min-width:42px;font-variant-numeric:tabular-nums}" +
    "#media-prog .d{text-align:right}" +
    "#media-prog .bar{flex:1;height:22px;display:flex;align-items:center;cursor:pointer;touch-action:none}" +
    "#media-prog .bar{background:linear-gradient(#2a2822,#2a2822) center/100% 6px no-repeat;border-radius:3px;position:relative}" +
    "#media-prog .fill{height:6px;background:#E2CE16;border-radius:3px;box-shadow:0 0 8px rgba(226,206,22,.5)}" +
    "#seq-list:empty::after{content:'Touchez « + AJOUTER » pour choisir des morceaux sur la tablette.';display:block;" +
    "padding:28px 20px;text-align:center;color:var(--muted);font-family:var(--f-label);font-size:16px}" +
    "";
  document.head.appendChild(style);

  const addBtn = document.createElement("button");
  addBtn.id = "media-add"; addBtn.type = "button"; addBtn.textContent = "+ AJOUTER";
  addBtn.addEventListener("click", addTracks);
  document.getElementById("transport").appendChild(addBtn);

  // Appui long : repéré au pointerdown, le clic qui suit est avalé.
  let skipClick = false;
  function onLongPress(el, pick, fn) {
    let timer = null;
    el.addEventListener("pointerdown", (e) => {
      const target = pick(e);
      if (target === null) return;
      clearTimeout(timer);
      timer = setTimeout(() => { skipClick = true; fn(target); }, 600);
    });
    ["pointerup", "pointercancel", "pointerleave"].forEach((t) => el.addEventListener(t, () => clearTimeout(timer)));
    el.addEventListener("click", (e) => { if (skipClick) { skipClick = false; e.stopImmediatePropagation(); e.preventDefault(); } }, true);
  }

  function move(i, d) {
    const j = i + d;
    if (j < 0 || j >= lib.playlist.length) return;
    [lib.playlist[i], lib.playlist[j]] = [lib.playlist[j], lib.playlist[i]];
    if (current === i) current = j; else if (current === j) current = i;
    saveLib(); seqMsg();
  }
  onLongPress(document.getElementById("seq-list"),
    (e) => { const it = e.target.closest(".seq-item"); return it ? +it.dataset.row : null; },
    (i) => openMenu(lib.playlist[i].title, [
      ["▲ Monter", () => move(i, -1)],
      ["▼ Descendre", () => move(i, +1)],
      ["Retirer de la playlist", async () => {
        const [it] = lib.playlist.splice(i, 1);
        if (current === i) { player.pause(); player.removeAttribute("src"); current = -1; }
        else if (current > i) current--;
        saveLib(); seqMsg(); await forget(it.id);
      }, "danger"],
    ]));

  document.querySelectorAll(".cart-btn").forEach((btn) => {
    const idx = +btn.dataset.idx;
    onLongPress(btn, () => idx, () => openMenu("Cartouche C" + (idx + 1), [
      ["Choisir un son…", async () => {
        const [f] = await chooseFiles(false);
        if (!f) return;
        try {
          const old = lib.carts[idx];
          lib.carts[idx] = await importFile(f);
          saveLib(); cartPlayers[idx]._msg();
          if (old) await forget(old.id);
        } catch (e) { toast("Import impossible : " + (e.message || e)); }
      }],
      ...(lib.carts[idx] ? [["Vider la cartouche", async () => {
        const old = lib.carts[idx];
        cartPlayers[idx].pause(); lib.carts[idx] = null;
        saveLib(); cartPlayers[idx]._msg(); await forget(old.id);
      }, "danger"]] : []),
    ]));
  });

  // Barre de progression sous le titre : temps écoulé / durée, toucher pour
  // sauter dans le morceau.
  const prog = document.createElement("div");
  prog.id = "media-prog";
  prog.innerHTML = '<span class="t">0:00</span><div class="bar"><div class="fill"></div></div><span class="d">—</span>';
  document.getElementById("now-playing").appendChild(prog);
  const bar = prog.querySelector(".bar"), fill = prog.querySelector(".fill");
  const tEl = prog.querySelector(".t"), dEl = prog.querySelector(".d");
  function paintProg() {
    const d = player.duration, t = player.currentTime || 0;
    const ok = current >= 0 && isFinite(d) && d > 0;
    fill.style.width = ok ? Math.min(100, (t / d) * 100) + "%" : "0";
    tEl.textContent = ok ? fmt(t) || "0:00" : "0:00";
    dEl.textContent = ok ? "-" + (fmt(d - t) || "0:00") : "—";
  }
  ["timeupdate", "loadedmetadata", "ended", "emptied"].forEach((e) => player.addEventListener(e, paintProg));
  function seek(e) {
    const d = player.duration;
    if (current < 0 || !isFinite(d) || d <= 0) return;
    const r = bar.getBoundingClientRect();
    player.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * d;
    paintProg();
  }
  let seeking = false;
  bar.addEventListener("pointerdown", (e) => { seeking = true; bar.setPointerCapture(e.pointerId); seek(e); });
  bar.addEventListener("pointermove", (e) => { if (seeking) seek(e); });
  bar.addEventListener("pointerup", () => { seeking = false; });
  bar.addEventListener("pointercancel", () => { seeking = false; });
  paintProg();

  // ── État initial ───────────────────────────────────────────────────────────
  seqMsg();
  cartPlayers.forEach((a) => a._msg());
  // Garder les morceaux importés même si Android manque de place.
  if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
  window.addEventListener("pagehide", () => { player.pause(); cartPlayers.forEach((a) => a.pause()); });
})();
