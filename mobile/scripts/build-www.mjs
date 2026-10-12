// Construit mobile/www à partir de la page tablette du PC.
//
// Une seule source d'interface : tablet/index.html (servie par tablet_server.py
// aux navigateurs) est COPIÉE ici, jamais dupliquée à la main. L'app ajoute
// seulement l'écran de connexion (src/launcher.html) et l'adresse du PC choisi.
import { copyFileSync, cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";

const mobile = join(dirname(fileURLToPath(import.meta.url)), "..");
const repo = join(mobile, "..");
const www = join(mobile, "www");

rmSync(www, { recursive: true, force: true });
mkdirSync(www, { recursive: true });

cpSync(join(repo, "tablet", "fonts"), join(www, "fonts"), { recursive: true });
copyFileSync(join(repo, "logo.png"), join(www, "icon.png"));
// Langue (src/i18n.js) : chargée en tête de chaque page, avant tout autre script.
const I18N_TAG = '<meta charset="utf-8">\n  <script src="i18n.js"></script>';
copyFileSync(join(mobile, "src", "i18n.js"), join(www, "i18n.js"));
for (const [src, dst] of [["launcher.html", "index.html"], ["dmxtest.html", "dmxtest.html"], ["patch.html", "patch.html"]]) {
  const page = readFileSync(join(mobile, "src", src), "utf8");
  if (page.split('<meta charset="utf-8">').length !== 2) throw new Error(`build-www : <meta charset> introuvable ou double dans ${src}`);
  writeFileSync(join(www, dst), page.replace('<meta charset="utf-8">', I18N_TAG));
}

let remote = readFileSync(join(repo, "tablet", "index.html"), "utf8");

function replaceOnce(text, anchor, replacement) {
  const n = text.split(anchor).length - 1;
  if (n !== 1) throw new Error(`build-www : « ${anchor} » trouvé ${n} fois dans tablet/index.html`);
  return text.replace(anchor, replacement);
}

// Avant tout autre script : l'adresse du PC choisi dans l'écran de connexion.
// Sans PC mémorisé, retour à cet écran.
// ?demo=1 : mode démo (src/demo.js), aucun PC nécessaire.
// ?solo=1 : mode autonome (src/standalone.js), la tablette pilote seule le DMX.
// Version affichée dans Réglages : version du paquet + date de construction +
// commit (« + modifs » si construit avec des changements non commités).
const pkg = JSON.parse(readFileSync(join(mobile, "package.json"), "utf8"));
let commit = "";
try {
  commit = execSync("git rev-parse --short HEAD", { cwd: repo }).toString().trim();
  if (execSync("git status --porcelain -- mobile tablet", { cwd: repo }).toString().trim()) commit += " + modifs";
} catch (e) { /* pas de git : version et date seulement */ }
const d = new Date(), z = (n) => String(n).padStart(2, "0");
const BUILD = {
  version: pkg.version,
  date: z(d.getDate()) + "/" + z(d.getMonth() + 1) + "/" + d.getFullYear() + " " + z(d.getHours()) + ":" + z(d.getMinutes()),
  commit,
};

const inject = `<meta charset="utf-8">
  <script src="i18n.js"></script>
  <script>
    window.MYSTROW_BUILD = ${JSON.stringify(BUILD)};
    window.MYSTROW_APP = true;
    var demo = /[?&]demo=1(&|$)/.test(location.search);
    if (demo) window.MYSTROW_DEMO = true;
    if (/[?&]solo=1(&|$)/.test(location.search)) { window.MYSTROW_SOLO = true; demo = true; }   // pas de PC à chercher
    try {
      var pc = JSON.parse(localStorage.getItem("mystrow.pc") || "null");
      if (pc && pc.base) window.MYSTROW_API_BASE = pc.base;
      else if (!demo) location.replace("index.html");
    } catch (e) { if (!demo) location.replace("index.html"); }
  </script>`;
remote = replaceOnce(remote, '<meta charset="utf-8">', inject);
copyFileSync(join(mobile, "src", "demo.js"), join(www, "demo.js"));
copyFileSync(join(mobile, "src", "engine.js"), join(www, "engine.js"));
copyFileSync(join(mobile, "src", "effects.js"), join(www, "effects.js"));
// Bibliothèque de fixtures (export_library.py) : chargée par la seule page de patch.
copyFileSync(join(mobile, "src", "library.js"), join(www, "library.js"));
copyFileSync(join(mobile, "src", "standalone.js"), join(www, "standalone.js"));
copyFileSync(join(mobile, "src", "media.js"), join(www, "media.js"));
copyFileSync(join(mobile, "src", "live.js"), join(www, "live.js"));
copyFileSync(join(mobile, "src", "fxeditor.js"), join(www, "fxeditor.js"));
// Compte MyStrow (licence, config du PC) : jeu sans PC ET accueil.
copyFileSync(join(mobile, "src", "account.js"), join(www, "account.js"));
remote = replaceOnce(remote, "</body>",
  '<script src="demo.js"></script>\n<script src="engine.js"></script>\n<script src="effects.js"></script>\n<script src="account.js"></script>\n<script src="standalone.js"></script>\n<script src="media.js"></script>\n<script src="live.js"></script>\n<script src="fxeditor.js"></script>\n</body>');
// PWA du navigateur uniquement : l'app n'a ni manifeste ni service worker.
remote = replaceOnce(remote, '<link rel="manifest" href="/manifest.json">', "");

writeFileSync(join(www, "remote.html"), remote);
console.log("www prêt :", www);
