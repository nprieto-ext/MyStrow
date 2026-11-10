// Boîtier MyStrow branché sur la tablette → carte « activer la licence incluse ».
//
// Même logique que boitier_detect.py / boitier_card.py sur PC :
//   1. le boîtier (USB 1A86:5740) est vu ; son numéro de série USB = identité ;
//   2. on demande au serveur (`boitier_detect`) ce qu'il inclut — jamais au
//      boîtier lui-même (un périphérique USB peut mentir) ;
//   3. libre et avec des mois de licence → carte : « Les activer sur le compte
//      … ? » (connecté) ou adresse e-mail (pas connecté) → `activate_code`.
//   Confirmation obligatoire : un boîtier prêté ne s'active pas en silence.
//
// ANDROID SEULEMENT. Sur iPhone / iPad : Apple refuse le déblocage d'une
// licence hors App Store (3.1.1) et iOS ne donne pas le n° de série en MIDI.
// Chargé par l'accueil (launcher.html) et le jeu sans PC (remote.html), après
// account.js.
(function () {
  "use strict";
  const cap = window.Capacitor;
  if (!cap || !cap.getPlatform || cap.getPlatform() !== "android") return;
  const Dmx = cap.Plugins && cap.Plugins.MystrowDmx;
  const Account = window.MystrowAccount;
  if (!Dmx || !Dmx.usbSerial || !Account) return;

  const FN = "https://us-central1-mystrow-907be.cloudfunctions.net/";
  const VID = 0x1A86, PID = 0x5740;
  const SCAN_MS = 5000, RETRY_MS = 120000;
  const DISMISS_KEY = "mystrow.boitiers.ignores";     // « Ne plus me le proposer » (par tablette)
  const seen = new Set();                              // déjà traités pendant cette session
  const retryAt = {};
  let busy = false, card = null;

  const load = (k, d) => { try { return JSON.parse(localStorage.getItem(k) || "null") ?? d; } catch (e) { return d; } };
  const save = (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} };
  const lang = () => window.MYSTROW_LANG || "fr";

  async function post(fn, body, token) {
    const headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = "Bearer " + token;
    const r = await fetch(FN + fn, { method: "POST", headers, body: JSON.stringify(body) });
    return r.json().catch(() => ({ ok: false, error: "http_" + r.status }));
  }

  async function scan() {
    if (busy || card || document.hidden) return;
    busy = true;
    try {
      const r = await Dmx.usbDevices().catch(() => null);
      // Rien de MyStrow branché : pas de fenêtre d'autorisation inutile.
      const devs = (r && r.devices) || [];
      if (!devs.some((d) => d.vid === VID && d.pid === PID)) return;
      const s = await Dmx.usbSerial().catch(() => null);
      const id = s && s.usb_id;
      if (!id || seen.has(id) || (retryAt[id] || 0) > Date.now()) return;
      // « Ne plus proposer » ne vaut que tant que le compte a une licence :
      // sans licence, l'activer est dans l'intérêt du client, la carte revient.
      if (load(DISMISS_KEY, []).includes(id) && Account.status().licensed) { seen.add(id); return; }
      let token = null;
      if (Account.status().loggedIn) token = await Account.idToken().catch(() => null);
      let rep;
      try { rep = await post("boitier_detect", { usb_id: id }, token); }
      catch (e) { retryAt[id] = Date.now() + RETRY_MS; return; }   // hors ligne : on réessaiera
      if (!rep.ok) { retryAt[id] = Date.now() + RETRY_MS; return; }
      seen.add(id);
      console.log("[BOITIER] " + id + " : " + JSON.stringify(rep));
      if (rep.known && rep.status === "free" && +rep.months > 0 && rep.serial) showCard(id, rep.serial, +rep.months);
    } finally { busy = false; }
  }

  // ── Carte (façon AirPods, comme boitier_card.py) ───────────────────────────
  function showCard(usbId, serial, months) {
    const st = Account.status();
    const logged = st.loggedIn;
    card = document.createElement("div");
    card.id = "bx-card";
    card.innerHTML = `<div class="sheet" role="dialog" aria-modal="true" aria-labelledby="bx-t">
      <div class="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="7" width="18" height="11" rx="2"/><path d="M7 18v2M17 18v2M8 11h3M8 14h8"/><circle cx="16" cy="11" r="1"/></svg></div>
      <h3 id="bx-t"></h3><div class="badge"></div><p class="ask"></p>
      <input class="mail" type="email" autocomplete="email" autocapitalize="off" spellcheck="false" placeholder="vous@exemple.fr" hidden>
      <p class="msg" role="status"></p>
      <button type="button" class="go"></button><button type="button" class="later"></button>
      <a href="#" class="never"></a></div>`;
    const css = document.createElement("style");
    css.textContent = `
#bx-card{position:fixed;inset:0;z-index:80;background:rgba(0,0,0,.66);display:flex;align-items:flex-end;justify-content:center;padding:16px;
  font-family:'Barlow Condensed','Roboto Condensed','Arial Narrow',sans-serif;color:#f4f1e8;animation:bxf .2s ease-out}
#bx-card .sheet{width:min(94vw,440px);background:#11100e;border:1px solid rgba(226,206,22,.4);border-radius:22px;padding:22px 20px 18px;
  display:flex;flex-direction:column;align-items:center;gap:10px;text-align:center;animation:bxu .32s cubic-bezier(.2,.9,.3,1.15);margin-bottom:4vh}
#bx-card .ico{width:72px;height:72px;border-radius:18px;background:#1a1700;color:#E2CE16;display:flex;align-items:center;justify-content:center}
#bx-card .ico svg{width:44px;height:44px}
#bx-card h3{margin:2px 0 0;font:400 30px/1 'Bebas Neue',Impact,sans-serif;letter-spacing:1px;color:#E2CE16}
#bx-card .badge{font-weight:700;font-size:17px;color:#0c0b00;background:#E2CE16;border-radius:999px;padding:3px 12px}
#bx-card p{margin:0;font-weight:500;font-size:17px;line-height:1.4;color:#cfcabd;white-space:pre-line}
#bx-card p.msg{min-height:0;font-size:15px}#bx-card p.msg.err{color:#f19999}#bx-card p.msg.ok{color:#9fdcb4}
#bx-card input{height:50px;width:100%;padding:0 14px;border-radius:12px;border:1px solid #3a3830;background:#0c0b09;color:#f4f1e8;font-family:inherit;font-weight:600;font-size:19px}
#bx-card button{width:100%;min-height:52px;border-radius:12px;border:1px solid #3a3830;background:#13120e;color:#f4f1e8;font-family:inherit;font-weight:700;font-size:18px;letter-spacing:1px;cursor:pointer}
#bx-card button.go{background:#E2CE16;border:0;color:#0c0b00}
#bx-card button:disabled{opacity:.55}
#bx-card a.never{color:#8a8577;font-size:14px}
@keyframes bxu{from{transform:translateY(60px);opacity:0}to{transform:none;opacity:1}}@keyframes bxf{from{opacity:0}to{opacity:1}}`;
    card.appendChild(css);
    document.body.appendChild(card);
    const q = (s) => card.querySelector(s);
    const go = q(".go"), later = q(".later"), never = q(".never"), mail = q(".mail"), msg = q(".msg");
    q("#bx-t").textContent = "Boîtier MyStrow détecté";
    q(".badge").textContent = months + " mois de licence inclus";
    q(".ask").textContent = "Le boîtier " + serial + " est branché.\n" +
      (logged ? "Les activer sur le compte " + st.email + " ?" : "Entrez votre adresse email pour les activer :");
    mail.hidden = logged;
    go.textContent = "Activer";
    later.textContent = "Plus tard";
    never.textContent = "Ne plus me le proposer pour ce boîtier";
    const close = () => { if (card) card.remove(); card = null; };
    later.addEventListener("click", () => { seen.delete(usbId); retryAt[usbId] = Infinity; close(); });  // reproposé au prochain lancement
    never.addEventListener("click", (e) => {
      e.preventDefault();
      const l = load(DISMISS_KEY, []); if (!l.includes(usbId)) l.push(usbId); save(DISMISS_KEY, l);
      close();
    });
    go.addEventListener("click", async () => {
      const email = logged ? st.email : mail.value.trim().toLowerCase();
      if (!logged && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) { msg.className = "msg err"; msg.textContent = "Cette adresse email n'est pas valide."; return; }
      msg.className = "msg"; msg.textContent = "";
      go.disabled = later.disabled = true; go.textContent = "Activation en cours…";
      let rep;
      try { rep = await post("activate_code", { email, serial, lang: lang() }); }
      catch (e) { rep = { ok: false, error: "network" }; }
      console.log("[BOITIER] activation " + serial + " : " + JSON.stringify(rep));
      if (rep.ok) {
        const date = rep.expiry_label || "";
        q("#bx-t").textContent = "C'est prêt !";
        q(".badge").hidden = true; mail.hidden = true; never.hidden = true; later.hidden = true;
        q(".ask").textContent = logged
          ? "Licence activée jusqu'au " + date + "."
          : "Licence activée sur " + email + " jusqu'au " + date + ".\n\nConnectez-vous avec cette adresse. Nouveau compte : votre mot de passe vient de vous être envoyé par email (il peut mettre quelques minutes à arriver).";
        if (rep.billing_resumes_label) q(".ask").textContent += "\n\nVotre abonnement ne sera pas prélevé avant le " + rep.billing_resumes_label + ".";
        const l = load(DISMISS_KEY, []).filter((x) => x !== usbId); save(DISMISS_KEY, l);
        go.disabled = false;
        if (logged) {
          go.textContent = "OK";
          go.onclick = close;
          Account.refreshLicense().catch(() => {});   // lève la limite de 10 min tout de suite
        } else {
          go.textContent = "Me connecter";
          go.onclick = () => { close(); Account.openPanel(); };
        }
        return;
      }
      if (rep.error === "already_yours") { close(); Account.refreshLicense().catch(() => {}); return; }
      if (["network", "server", "throttled"].includes(rep.error)) seen.delete(usbId);   // reste libre : reproposé plus tard
      msg.className = "msg err";
      msg.textContent = { serial_used: "Ce boîtier est déjà activé sur un autre compte. Contactez-nous avec son numéro de série.",
                          already_lifetime: "Ce compte dispose déjà d'une licence à vie : rien à ajouter." }[rep.error]
        || "L'activation n'a pas abouti. Réessayez dans un instant, ou activez sur mystrow.fr/activate.";
      go.disabled = later.disabled = false; go.textContent = "Activer";
      if (rep.error === "serial_used" || rep.error === "already_lifetime") { go.textContent = "OK"; go.onclick = close; }
    });
  }

  setInterval(scan, SCAN_MS);
  setTimeout(scan, 1500);
  window.MystrowBoitier = { scan };
})();
