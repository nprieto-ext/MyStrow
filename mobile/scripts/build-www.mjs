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
copyFileSync(join(mobile, "src", "dmxtest.html"), join(www, "dmxtest.html"));
copyFileSync(join(mobile, "src", "patch.html"), join(www, "patch.html"));

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
const inject = `<meta charset="utf-8">
  <script>
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
remote = replaceOnce(remote, "</body>",
  '<script src="demo.js"></script>\n<script src="engine.js"></script>\n<script src="effects.js"></script>\n<script src="standalone.js"></script>\n<script src="media.js"></script>\n</body>');
// PWA du navigateur uniquement : l'app n'a ni manifeste ni service worker.
remote = replaceOnce(remote, '<link rel="manifest" href="/manifest.json">', "");

writeFileSync(join(www, "remote.html"), remote);
console.log("www prêt :", www);
