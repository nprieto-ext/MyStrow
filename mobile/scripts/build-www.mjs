// Construit mobile/www à partir de la page tablette du PC.
//
// Une seule source d'interface : tablet/index.html (servie par tablet_server.py
// aux navigateurs) est COPIÉE ici, jamais dupliquée à la main. L'app ajoute
// seulement l'écran de connexion (src/launcher.html) et l'adresse du PC choisi.
import { copyFileSync, cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const mobile = join(dirname(fileURLToPath(import.meta.url)), "..");
const repo = join(mobile, "..");
const www = join(mobile, "www");

rmSync(www, { recursive: true, force: true });
mkdirSync(www, { recursive: true });

cpSync(join(repo, "tablet", "fonts"), join(www, "fonts"), { recursive: true });
copyFileSync(join(repo, "logo.png"), join(www, "icon.png"));
copyFileSync(join(mobile, "src", "launcher.html"), join(www, "index.html"));

let remote = readFileSync(join(repo, "tablet", "index.html"), "utf8");

function replaceOnce(text, anchor, replacement) {
  const n = text.split(anchor).length - 1;
  if (n !== 1) throw new Error(`build-www : « ${anchor} » trouvé ${n} fois dans tablet/index.html`);
  return text.replace(anchor, replacement);
}

// Avant tout autre script : l'adresse du PC choisi dans l'écran de connexion.
// Sans PC mémorisé, retour à cet écran.
// ?demo=1 : mode démo (src/demo.js), aucun PC nécessaire.
const inject = `<meta charset="utf-8">
  <script>
    window.MYSTROW_APP = true;
    var demo = /[?&]demo=1(&|$)/.test(location.search);
    if (demo) window.MYSTROW_DEMO = true;
    try {
      var pc = JSON.parse(localStorage.getItem("mystrow.pc") || "null");
      if (pc && pc.base) window.MYSTROW_API_BASE = pc.base;
      else if (!demo) location.replace("index.html");
    } catch (e) { if (!demo) location.replace("index.html"); }
  </script>`;
remote = replaceOnce(remote, '<meta charset="utf-8">', inject);
copyFileSync(join(mobile, "src", "demo.js"), join(www, "demo.js"));
remote = replaceOnce(remote, "</body>", '<script src="demo.js"></script>\n</body>');
// PWA du navigateur uniquement : l'app n'a ni manifeste ni service worker.
remote = replaceOnce(remote, '<link rel="manifest" href="/manifest.json">', "");

writeFileSync(join(www, "remote.html"), remote);
console.log("www prêt :", www);
