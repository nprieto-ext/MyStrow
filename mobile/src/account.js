// Compte MyStrow sur la tablette : connexion, licence, config envoyée par le PC.
//
// Chargé par l'accueil (launcher.html) et par le jeu sans PC (remote.html,
// avant standalone.js). Même compte et même API que le logiciel PC
// (firebase_client.py / license_manager.py), sans SDK : REST Firebase.
//
//   Licence : seule une licence PAYANTE active (plan « license », pas l'essai)
//   lève la limite de 10 minutes de DMX par lancement. La tablette ne prend
//   PAS de place parmi les 2 machines du compte : elle ne s'y inscrit pas.
//   Hors ligne : la dernière vérification vaut 7 jours (comme le PC).
//
//   Config du PC : document Firestore user_configs/{uid}, écrit par le PC
//   (tablet_cloud.py, menu Connexion › Contrôle › Envoyer ma config vers la
//   tablette). Champ `payload` = JSON déjà converti au format de la tablette.
(function (root) {
  "use strict";
  const API_KEY = "AIzaSyAQjGJXGCSWzOE-wvKXh6sbZy6JDhL8tqA";      // firebase_config.py
  const PROJECT = "mystrow-907be";
  const FS = "https://firestore.googleapis.com/v1/projects/" + PROJECT + "/databases/(default)/documents";
  const KEY = "mystrow.account";
  const OFFLINE_MS = 7 * 86400 * 1000;

  const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k) || "null") ?? d; } catch (e) { return d; } };
  const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
  let token = null, tokenExp = 0;                    // jeton d'accès, en mémoire seulement
  const listeners = [];
  const changed = () => listeners.forEach((fn) => { try { fn(status()); } catch (e) {} });

  // Messages Firebase → texte lisible.
  const ERRORS = {
    EMAIL_NOT_FOUND: "Aucun compte avec cet e-mail.",
    INVALID_PASSWORD: "Mot de passe incorrect.",
    INVALID_LOGIN_CREDENTIALS: "E-mail ou mot de passe incorrect.",
    INVALID_EMAIL: "Adresse e-mail invalide.",
    USER_DISABLED: "Ce compte est désactivé.",
    TOO_MANY_ATTEMPTS_TRY_LATER: "Trop d'essais : réessayez dans quelques minutes.",
  };
  async function call(url, opts) {
    let r;
    try { r = await fetch(url, opts); } catch (e) { throw new Error("Pas de connexion Internet."); }
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      const code = ((data.error || {}).message || "").split(" ")[0];
      const err = new Error(ERRORS[code] || (r.status === 403 ? "Accès refusé par le compte." : "Erreur du compte (" + (code || r.status) + ")."));
      err.status = r.status;
      throw err;
    }
    return data;
  }

  async function signIn(email, password) {
    const d = await call("https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=" + API_KEY, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: email.trim(), password, returnSecureToken: true }),
    });
    token = d.idToken; tokenExp = Date.now() + (+d.expiresIn || 3600) * 1000 - 60000;
    save(KEY, { email: d.email, uid: d.localId, refresh: d.refreshToken });
    await refreshLicense();
    return status();
  }
  async function idToken() {
    const a = load(KEY, null);
    if (!a) throw new Error("Pas connecté.");
    if (token && Date.now() < tokenExp) return token;
    const d = await call("https://securetoken.googleapis.com/v1/token?key=" + API_KEY, {
      method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: "grant_type=refresh_token&refresh_token=" + encodeURIComponent(a.refresh),
    });
    token = d.id_token; tokenExp = Date.now() + (+d.expires_in || 3600) * 1000 - 60000;
    if (d.refresh_token && d.refresh_token !== a.refresh) save(KEY, { ...a, refresh: d.refresh_token });
    return token;
  }
  const fsValue = (v) => (v == null ? null : "stringValue" in v ? v.stringValue : "doubleValue" in v ? +v.doubleValue
    : "integerValue" in v ? +v.integerValue : "booleanValue" in v ? v.booleanValue
    : "mapValue" in v ? Object.fromEntries(Object.entries(v.mapValue.fields || {}).map(([k, x]) => [k, fsValue(x)]))
    : "arrayValue" in v ? (v.arrayValue.values || []).map(fsValue) : null);
  async function getDoc(path) {
    const t = await idToken();
    try {
      const d = await call(FS + "/" + path, { headers: { Authorization: "Bearer " + t } });
      return Object.fromEntries(Object.entries(d.fields || {}).map(([k, v]) => [k, fsValue(v)]));
    } catch (e) { if (e.status === 404) return null; throw e; }
  }
  // Licence : relue à chaque lancement si Internet ; sinon le cache tient 7 jours.
  async function refreshLicense() {
    const a = load(KEY, null);
    if (!a) return status();
    const doc = await getDoc("licenses/" + a.uid);
    save(KEY, { ...load(KEY, a), plan: doc ? doc.plan || "trial" : "none", expiry: doc ? +doc.expiry_utc || 0 : 0, checked: Date.now() });
    changed();
    return status();
  }
  function status() {
    const a = load(KEY, null);
    if (!a) return { loggedIn: false, paid: false };
    const fresh = a.checked && Date.now() - a.checked < OFFLINE_MS;
    const active = a.plan === "license" && a.expiry * 1000 > Date.now();
    return { loggedIn: true, email: a.email, plan: a.plan, expiry: a.expiry, checked: a.checked,
             paid: !!(fresh && active), stale: !fresh };
  }
  function signOut() { localStorage.removeItem(KEY); token = null; changed(); }

  async function fetchPcConfig() {
    const a = load(KEY, null);
    if (!a) throw new Error("Pas connecté.");
    const doc = await getDoc("user_configs/" + a.uid);
    if (!doc || !doc.payload) return null;
    return { payload: JSON.parse(doc.payload), updated: doc.updated_utc, label: doc.label || "", summary: doc.summary || {} };
  }
  // Remplace le patch, les pages, les mémoires, les positions et les effets
  // de la tablette par ceux du PC. L'état d'avant est gardé (un seul retour).
  function applyPcConfig(p) {
    const show = load("mystrow.solo.show", { fixtures: [], output: { transport: "usb" } });
    const play = load("mystrow.solo.play", {});
    const fx = load("mystrow.solo.fx", []);
    save("mystrow.solo.backup", { show, play, fx, at: Date.now() });
    show.fixtures = p.fixtures || [];
    save("mystrow.solo.show", show);
    const buttons = (p.buttons || []).map((n, i) => n || (play.buttons || [])[i] || null);
    Object.assign(play, {
      pages: p.pages && p.pages.length ? p.pages : play.pages, pageIdx: p.pageIdx || 0,
      memories: p.memories || {}, fxPads: p.fxPads || {}, posPresets: p.posPresets || {},
      superpose: !!p.superpose, buttons: buttons.length ? buttons : play.buttons,
      memRows: {}, memLevels: {}, posActive: {}, fxStack: [], active: {}, groupTs: {}, memTs: 0,
      positions: {}, gobos: {}, qfx: {},
    });
    save("mystrow.solo.play", play);
    const names = new Set((p.effects || []).map((e) => e.name));
    save("mystrow.solo.fx", [...(p.effects || []), ...(Array.isArray(fx) ? fx : []).filter((e) => !e.from_pc && !names.has(e.name))]);
  }
  const backup = () => load("mystrow.solo.backup", null);
  function restoreBackup() {
    const b = backup();
    if (!b) return false;
    save("mystrow.solo.show", b.show); save("mystrow.solo.play", b.play); save("mystrow.solo.fx", b.fx);
    localStorage.removeItem("mystrow.solo.backup");
    return true;
  }

  // ── Fenêtre « Mon compte » ──────────────────────────────────────────────────
  // opts.onImported : après l'import (le jeu se recharge).
  let panel = null;
  const fmtDate = (sec) => { const d = new Date(sec * 1000), z = (n) => String(n).padStart(2, "0");
    return z(d.getDate()) + "/" + z(d.getMonth() + 1) + "/" + d.getFullYear() + " " + z(d.getHours()) + ":" + z(d.getMinutes()); };
  function licenceText(s) {
    if (!s.loggedIn) return "";
    if (s.paid) return "Licence active jusqu'au " + fmtDate(s.expiry).slice(0, 10) + " : DMX sans limite.";
    if (s.stale) return "Licence non vérifiée depuis plus de 7 jours : connectez la tablette à Internet.";
    if (s.plan === "license") return "Licence expirée : la sortie DMX reste limitée à 10 minutes.";
    return "Ce compte n'a pas de licence payante (essai) : la sortie DMX reste limitée à 10 minutes par lancement.";
  }
  function openPanel(opts) {
    opts = opts || {};
    if (!panel) {
      panel = document.createElement("div");
      panel.id = "acct";
      panel.innerHTML = '<div class="box" role="dialog" aria-modal="true" aria-labelledby="acct-t"><h3 id="acct-t">Mon compte MyStrow</h3><div class="body"></div></div>';
      panel.addEventListener("click", (e) => { if (e.target === panel) panel.hidden = true; });
      document.body.appendChild(panel);
      const css = document.createElement("style");
      css.textContent = `
#acct{position:fixed;inset:0;z-index:65;background:rgba(0,0,0,.72);display:flex;align-items:center;justify-content:center;padding:16px;
  font-family:'Barlow Condensed','Roboto Condensed','Arial Narrow',sans-serif;color:#f4f1e8}
#acct[hidden]{display:none}
#acct .box{width:min(92vw,460px);max-height:90vh;overflow:auto;background:#11100e;border:1px solid rgba(226,206,22,.35);border-radius:16px;padding:18px;display:flex;flex-direction:column;gap:12px}
#acct h3{margin:0;font:400 28px/1 'Bebas Neue',Impact,sans-serif;letter-spacing:1px;color:#E2CE16}
#acct .body{display:flex;flex-direction:column;gap:10px}
#acct p{margin:0;font-family:inherit;font-weight:500;font-size:16px;line-height:1.4;color:#cfcabd}
#acct p.ok{color:#9fdcb4}#acct p.err{color:#f19999}#acct p.small{font-size:14px;color:#8a8577}
#acct label{font-weight:700;font-size:13px;letter-spacing:2px;color:#E2CE16;text-transform:uppercase}
#acct input{height:50px;padding:0 14px;border-radius:12px;border:1px solid #3a3830;background:#0c0b09;color:#f4f1e8;font-family:inherit;font-weight:600;font-size:19px;width:100%}
#acct button{min-height:50px;border-radius:12px;border:1px solid #3a3830;background:#13120e;color:#f4f1e8;font-family:inherit;font-weight:700;font-size:17px;letter-spacing:1px;cursor:pointer;touch-action:manipulation}
#acct button.main{background:#E2CE16;border:0;color:#0c0b00}
#acct button.danger{border-color:rgba(248,113,113,.5);color:#f87171}
#acct button:disabled{opacity:.5}
#acct .who{font-size:20px;font-weight:700;color:#f4f1e8;word-break:break-all}`;
      document.head.appendChild(css);
    }
    const body = panel.querySelector(".body");
    const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; };
    const btn = (text, cls, fn) => { const b = el("button", cls, text); b.type = "button"; b.addEventListener("click", fn); return b; };
    const msg = el("p", "", "");
    const busy = (b, on, text) => { b.disabled = on; if (text) b.textContent = text; };

    function renderOut() {
      body.innerHTML = "";
      body.append(el("p", "", "Connectez-vous avec le compte de votre licence MyStrow : la sortie DMX n'est plus coupée au bout de 10 minutes, et vous récupérez la config de votre PC (patch, mémoires, effets)."));
      const form = el("form");
      form.style.cssText = "display:flex;flex-direction:column;gap:8px";
      form.innerHTML = '<label for="acct-mail">E-mail</label><input id="acct-mail" type="email" autocomplete="username" autocapitalize="off" spellcheck="false">' +
        '<label for="acct-pw">Mot de passe</label><input id="acct-pw" type="password" autocomplete="current-password">';
      const go = el("button", "main", "Se connecter"); go.type = "submit";
      form.append(go, msg);
      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        msg.className = ""; msg.textContent = "";
        busy(go, true, "Connexion…");
        try { await signIn(form.querySelector("#acct-mail").value, form.querySelector("#acct-pw").value); render(); }
        catch (err) { msg.className = "err"; msg.textContent = err.message; busy(go, false, "Se connecter"); }
      });
      body.append(form, el("p", "small", "Mot de passe oublié : depuis le logiciel MyStrow sur le PC (Mon compte) ou sur mystrow.fr."),
        btn("Fermer", "", () => { panel.hidden = true; }));
      setTimeout(() => { const i = body.querySelector("#acct-mail"); if (i) i.focus(); }, 60);
    }
    function renderIn() {
      const s = status();
      body.innerHTML = "";
      body.append(el("div", "who", s.email), el("p", s.paid ? "ok" : "err", licenceText(s)));
      const get = btn("Récupérer la config du PC", "main", async () => {
        msg.className = ""; msg.textContent = "";
        busy(get, true, "Recherche…");
        try {
          const cfg = await fetchPcConfig();
          busy(get, false, "Récupérer la config du PC");
          if (!cfg) {
            msg.textContent = "Rien n'a encore été envoyé. Sur le PC : menu Connexion › Contrôle › « Envoyer ma config vers la tablette ».";
            return;
          }
          renderImport(cfg);
        } catch (err) { msg.className = "err"; msg.textContent = err.message; busy(get, false, "Récupérer la config du PC"); }
      });
      body.append(get, msg);
      if (backup()) body.append(btn("Revenir à la config d'avant l'import", "", () => {
        if (restoreBackup()) { if (opts.onImported) opts.onImported(); else location.reload(); }
      }));
      body.append(btn("Se déconnecter", "danger", () => { signOut(); render(); }), btn("Fermer", "", () => { panel.hidden = true; }));
      // Licence relue en arrière-plan (achat fait depuis l'ouverture de l'app…).
      refreshLicense().then((n) => { const p = body.querySelector("p.ok,p.err"); if (p && n.loggedIn) { p.className = n.paid ? "ok" : "err"; p.textContent = licenceText(n); } }).catch(() => {});
    }
    function renderImport(cfg) {
      const sm = cfg.summary || {}, p = cfg.payload;
      body.innerHTML = "";
      body.append(el("p", "", "Config envoyée le " + (cfg.updated ? fmtDate(cfg.updated) : "?") + (cfg.label ? " depuis « " + cfg.label + " »" : "") + " :"),
        el("div", "who", (sm.fixtures ?? (p.fixtures || []).length) + " projecteurs · " + (sm.memories ?? 0) + " mémoires · "
          + (sm.effects ?? 0) + " effets · " + (sm.positions ?? 0) + " positions"));
      (p.warnings || []).forEach((w) => body.append(el("p", "small", "⚠ " + w)));
      body.append(el("p", "", "Elle remplace le patch, les pages AKAI, les mémoires et les positions de la tablette. La sortie DMX (USB ou node) ne change pas. Vos effets créés sur la tablette restent."));
      body.append(btn("Remplacer la config de la tablette", "main", () => {
        applyPcConfig(p);
        if (opts.onImported) opts.onImported(); else location.reload();
      }), btn("Annuler", "", () => render()));
    }
    function render() { if (status().loggedIn) renderIn(); else renderOut(); changed(); }
    render();
    panel.hidden = false;
  }

  root.MystrowAccount = { signIn, signOut, status, refreshLicense, fetchPcConfig, applyPcConfig, restoreBackup, openPanel,
    onChange: (fn) => listeners.push(fn) };
})(window);
