// Le faisceau 3D ne doit pas dépasser le plancher DESSINÉ.
//
// Remontée du 11/09/2026 (`depasse.png`) : les cônes traversaient la scène et
// leurs taches flottaient sur le noir, devant le bord du plateau. Deux causes,
// toutes deux vérifiées ici :
//
//   1. L'emprise du plancher (18 × 10, soit x ±9 et z ±5) ne correspondait pas
//      à la boîte qui bornait le point d'arrivée (x ±11, z ∈ [−8, 13]).
//   2. `fx`, `fy` et `fz` étaient rabotés SÉPARÉMENT : dès qu'une seule borne
//      mordait, le sommet du cône quittait l'axe du faisceau.
//
// On teste donc trois invariants de `beamFloor()`, sur toute la course :
//   A. le point d'arrivée est TOUJOURS sur le rayon ;
//   B. il est TOUJOURS dans l'emprise du plancher ;
//   C. `hitsFloor` équivaut à « le rayon rencontre le plancher dessiné »,
//      et la longueur reste continue (pas de saut au franchissement).

import { readFileSync } from 'node:fs';

const html = readFileSync('./plan_3d_web.html', 'utf8');
const src  = html.slice(html.indexOf('const BEAM_TMAX'),
                        html.indexOf('// Positionner / orienter un cône unit'));
const floorSrc = (html.match(/^const FLOOR_[A-Z0-9_]+ .*$/gm) || []).join('\n');
const env = new Function(
  `${floorSrc}\n${src}; return { beamFloor, FLOOR_X0, FLOOR_X1, FLOOR_Z0, FLOOR_Z1, BEAM_TMAX };`
)();
const { beamFloor, FLOOR_X0, FLOOR_X1, FLOOR_Z0, FLOOR_Z1, BEAM_TMAX } = env;

// Le plancher réellement ajouté à la scène. Lu dans le HTML pour que le test
// tombe si quelqu'un redimensionne le maillage sans toucher aux constantes.
const geo = html.match(/floorReflector = new THREE\.Mesh\(\s*new THREE\.PlaneGeometry\(([^)]*)\)/);
const pos = html.match(/floorReflector\.position\.set\(([^)]*)\)/);
if (!geo || !pos) { console.log('ECHEC  plancher introuvable dans le HTML'); process.exit(1); }
const [gw, gd] = geo[1].split(',').map(s => s.trim());
const [px, , pz] = pos[1].split(',').map(s => s.trim());

let echecs = 0;
function verifie(nom, ok, detail = '') {
  if (!ok) echecs++;
  console.log(`${ok ? 'OK  ' : 'ECHEC'} ${nom.padEnd(52)} ${detail}`);
}

// La grille de scène est tracée par-dessus le plancher : si elle déborde, on
// voit des lignes flotter sur le noir.
const grid = html.match(/new THREE\.GridHelper\((\d+(?:\.\d+)?)/);
const gHalf = grid ? parseFloat(grid[1]) / 2 : NaN;
verifie('le plancher contient la grille de scène',
        gHalf >= 0 && -gHalf >= FLOOR_X0 && gHalf <= FLOOR_X1
                   && -gHalf >= FLOOR_Z0 && gHalf <= FLOOR_Z1,
        `grille ±${gHalf} m, plancher x[${FLOOR_X0}, ${FLOOR_X1}] z[${FLOOR_Z0}, ${FLOOR_Z1}]`);

verifie('le maillage du plancher suit les constantes',
        gw === 'FLOOR_W' && gd === 'FLOOR_D' && px === 'FLOOR_CX' && pz === 'FLOOR_CZ',
        `PlaneGeometry(${gw}, ${gd}) en (${px}, ${pz})`);

// ── Balayage de toute la course pan/tilt, lyre et PAR ────────────────────────
const EPS = 1e-6;
let pireEcartRayon = 0, pireSautY = 0, horsSol = 0, tachesOrphelines = 0, cones = 0;
let pirePan = 0, pireTilt = 0;

function cas(p) {
  const bf = beamFloor(p);
  cones++;
  // A. le point d'arrivée est sur le rayon : (f - lens) doit être colinéaire
  //    ET de même sens que (bx, by, bz).
  const dx = bf.fx - bf.lensX, dy = bf.fy - bf.lensY, dz = bf.fz - bf.lensZ;
  const t  = Math.hypot(dx, dy, dz);
  const ecart = t < 1e-9 ? 0
              : Math.hypot(dx - bf.bx * t, dy - bf.by * t, dz - bf.bz * t);
  if (ecart > pireEcartRayon) pireEcartRayon = ecart;

  // B. dans l'emprise du plancher (tolérance : arrondis flottants)
  if (bf.fx < FLOOR_X0 - 1e-6 || bf.fx > FLOOR_X1 + 1e-6 ||
      bf.fz < FLOOR_Z0 - 1e-6 || bf.fz > FLOOR_Z1 + 1e-6) horsSol++;

  // C. hitsFloor ⇔ le rayon rencontre le plancher dessiné, à portée
  const tf = bf.by < -EPS ? bf.lensY / -bf.by : Infinity;
  const hx = bf.lensX + bf.bx * tf, hz = bf.lensZ + bf.bz * tf;
  const attendu = tf <= BEAM_TMAX
               && hx >= FLOOR_X0 && hx <= FLOOR_X1
               && hz >= FLOOR_Z0 && hz <= FLOOR_Z1;
  if (bf.hitsFloor !== attendu) tachesOrphelines++;
  return bf;
}

// `isMH` se décide sur `fixture_type === 'Moving Head'` — et sur rien d'autre.
// Une lyre patchée « Lyre Spot » passe donc par la branche PAR : les deux
// branches doivent tenir les mêmes invariants, c'est pourquoi on balaye les
// deux ici.
function fixture(isMH, pan, tilt) {
  return isMH
    ? { fixture_type: 'Moving Head', x: 0, z: 0, fixture_height: 7,
        pan, tilt, pan_range: 540, tilt_range: 270, fixture_scale: 1 }
    : { fixture_type: 'PAR LED', x: 0, z: 0, fixture_height: 7,
        rot3d_y: (pan / 65535) * 360, rot3d_x: (tilt / 65535) * 360,
        fixture_scale: 1 };
}

// Invariants A/B/C : balayage large.
for (const isMH of [true, false])
  for (let pan = 0; pan <= 65535; pan += 2048)
    for (let tilt = 0; tilt <= 65535; tilt += 512)
      cas(fixture(isMH, pan, tilt));

// Continuité : pas fin, pour que le seuil parle d'un VRAI saut et non de la
// vitesse de balayage. Un pas de 64 déplace l'arrivée d'au plus ~15 cm à la
// portée maximale (22 m × tan(0,35°)) ; le bug de juillet 2026 valait 14,47 m.
const PAS = 64;
for (const isMH of [true, false]) {
  for (let pan = 0; pan <= 65535; pan += 8192) {
    let prec = null;
    for (let tilt = 0; tilt <= 65535; tilt += PAS) {
      const bf = beamFloor(fixture(isMH, pan, tilt));
      if (prec) {
        const saut = Math.hypot(bf.fx - prec.fx, bf.fy - prec.fy, bf.fz - prec.fz);
        if (saut > pireSautY) { pireSautY = saut; pirePan = pan; pireTilt = tilt; }
      }
      prec = bf;
    }
  }
}

verifie('le point d\'arrivée reste sur le rayon', pireEcartRayon < 1e-9,
        `écart max ${pireEcartRayon.toExponential(2)} m sur ${cones} cônes`);
verifie('le point d\'arrivée reste sur le plancher', horsSol === 0,
        `${horsSol} cas hors emprise`);
verifie('pas de tache au sol orpheline', tachesOrphelines === 0,
        `${tachesOrphelines} désaccords hitsFloor`);
verifie('longueur continue (pas de saut au franchissement)', pireSautY < 0.5,
        `saut max ${pireSautY.toFixed(3)} m (pan ${pirePan}, tilt ${pireTilt})`);

// ── La tache au sol suit le cône ─────────────────────────────────────────────
//
// Elle avait sa propre formule — (0.35 + 2.2*lvl) * bs * (wash ? 1.6 : 1) *
// _angF — qui ignorait `_zoomF` et prenait 1.6 là où le cône prend 1.9 pour un
// wash. Mesuré sur le profil des deux shaders : tache 2,03× trop LARGE à zoom
// mini, 0,29× (donc trop étroite) à zoom maxi. Dérivée de `base_r`, elle suit
// le cône partout. Et elle est écrite DEUX fois (bloc `hitsFloor` et état
// `_fx` des copies du prisme) : les deux doivent rester la même expression.
const poolExprs = [...html.matchAll(/poolR[ :=]+\s*(base_r[^;,\r\n]*)/g)].map(m => m[1].trim());
verifie('la tache est dérivée du rayon du cône', poolExprs.length >= 2,
        `${poolExprs.length} expression(s) trouvée(s)`);
verifie('les deux écritures de poolR sont identiques',
        poolExprs.length >= 2 && poolExprs.every(e => e === poolExprs[0]),
        poolExprs.join(' | ') || '—');
// Le halo est la pénombre autour de la tache, pas une nappe : à 2.8 un spot à
// 7 m posait un disque de 14 m sur un plateau de 18 — c'est LUI qui faisait
// « la tache est plus large que le faisceau ».
const halo = html.match(/halo\.scale\.setScalar\(poolR \* ([\d.]+)\)/);
verifie('le halo au sol reste une pénombre', !!halo && parseFloat(halo[1]) <= 2.0,
        halo ? `poolR × ${halo[1]}` : 'introuvable');

console.log(echecs ? `\n${echecs} échec(s)` : '\nTous les cas passent');
process.exit(echecs ? 1 : 0);
