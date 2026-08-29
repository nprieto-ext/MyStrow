// Le faisceau d'un PAR LED doit sortir DU CÔTÉ où pointe sa lentille.
//
// Remontée du 27/08/2026 (`Bug_affichage3D.png`) : des PAR retournés galette
// vers le public lavaient de rouge la structure DERRIÈRE eux. `beamFloor()`
// appliquait Rx(-tilt) là où le maillage applique Rx(+tilt) — corps et
// faisceau partaient à l'opposé l'un de l'autre.
//
// Le test compare la direction calculée par `beamFloor()` (extraite du HTML)
// à celle du VRAI groupe Three.js, construit avec le three vendorisé du projet.

import * as THREE from './vendor/three/three.module.js';
import { readFileSync } from 'node:fs';

// ── beamFloor() extrait du HTML, tel quel ────────────────────────────────────
const html = readFileSync('./plan_3d_web.html', 'utf8');
const src  = html.slice(html.indexOf('const BEAM_TMAX'),
                        html.indexOf('// Positionner / orienter un cône unit'));
const beamFloor = new Function(`${src}; return beamFloor;`)();

// ── Direction réelle du maillage ─────────────────────────────────────────────
// La galette de LED est montée sous le corps : l'émission suit le nadir local.
function directionCorps(p) {
  const g = new THREE.Group();
  g.rotation.order = 'YXZ';                 // cf. construction de `parGrp`
  g.rotation.x = (p.rot3d_x ?? 0) * Math.PI / 180;
  g.rotation.y = (p.rot3d_y ?? 0) * Math.PI / 180;
  g.updateMatrixWorld(true);
  return new THREE.Vector3(0, -1, 0).applyQuaternion(g.quaternion);
}

let echecs = 0;
function verifie(nom, p) {
  const bf = beamFloor(p);
  const d  = directionCorps(p);
  const ecart = Math.hypot(bf.bx - d.x, bf.by - d.y, bf.bz - d.z);
  const ok = ecart < 1e-9;
  if (!ok) echecs++;
  console.log(`${ok ? 'OK  ' : 'ECHEC'} ${nom.padEnd(42)} ` +
    `faisceau=(${bf.bx.toFixed(3)},${bf.by.toFixed(3)},${bf.bz.toFixed(3)}) ` +
    `corps=(${d.x.toFixed(3)},${d.y.toFixed(3)},${d.z.toFixed(3)})`);
}

const base = { x: 0, z: 0, fixture_height: 7, fixture_type: 'PAR LED', fixture_scale: 1 };

verifie('au repos (nadir)',            { ...base });
verifie('retourné vers le haut (180)', { ...base, rot3d_x: 180 });
verifie('incliné vers le public',      { ...base, rot3d_x: -60 });
verifie('incliné vers le lointain',    { ...base, rot3d_x: 60 });
verifie('incliné + lacet 90',          { ...base, rot3d_x: -60, rot3d_y: 90 });
verifie('incliné + lacet 45',          { ...base, rot3d_x: 35,  rot3d_y: 45 });
verifie('incliné + lacet -120',        { ...base, rot3d_x: -25, rot3d_y: -120 });
verifie('rasant (89)',                 { ...base, rot3d_x: 89,  rot3d_y: 200 });

// ── La lentille doit suivre le corps, pas rester sous l'accroche ─────────────
{
  const bf = beamFloor({ ...base, rot3d_x: 180 });      // PAR retourné vers le haut
  const ok = bf.lensY > 7;
  if (!ok) echecs++;
  console.log(`${ok ? 'OK  ' : 'ECHEC'} ${'lentille au-dessus si retourné'.padEnd(42)} lensY=${bf.lensY.toFixed(3)} (accroche 7.000)`);
}
{
  const bf = beamFloor({ ...base });                    // au repos : inchangé
  const ok = Math.abs(bf.lensY - (7 - 0.333)) < 1e-9 &&
             Math.abs(bf.lensX) < 1e-9 && Math.abs(bf.lensZ) < 1e-9;
  if (!ok) echecs++;
  console.log(`${ok ? 'OK  ' : 'ECHEC'} ${'au repos, lentille sous l\'accroche'.padEnd(42)} lensY=${bf.lensY.toFixed(3)}`);
}

// ── Le cas de la capture : galette vers le public ⇒ tache vers le public ─────
{
  const bf = beamFloor({ ...base, rot3d_x: -70, fixture_height: 6 });
  const ok = bf.fz > 0 && bf.bz > 0;         // +Z = côté salle
  if (!ok) echecs++;
  console.log(`${ok ? 'OK  ' : 'ECHEC'} ${'galette vers la salle ⇒ tache salle'.padEnd(42)} fz=${bf.fz.toFixed(2)}`);
}

console.log(echecs ? `\n${echecs} ECHEC(S)` : '\nTous les cas passent');
process.exit(echecs ? 1 : 0);
