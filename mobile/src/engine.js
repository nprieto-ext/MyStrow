// Moteur DMX du mode autonome (tablette sans PC) : projecteurs → 512 canaux.
//
// PORT de ArtNetDMX._update_from_projectors_locked (artnet_dmx.py), limité en
// v1 aux projecteurs à LED (R G B W, dimmer, strobe, shutter) et aux lyres en
// position de repos. Même arithmétique que le PC, à l'entier près (int() Python
// = Math.trunc) : un écart ici est un bug, pas un choix. Le harnais de trames
// de référence PC ↔ tablette viendra verrouiller cette parité.
//
// Fonction pure, sans DOM ni Capacitor : testable sous Node.
(function (root) {
  "use strict";

  // Sous-ensemble de DMX_PROFILES (artnet_dmx.py), mêmes noms et mêmes canaux.
  const PROFILES = {
    DIM:         ["Dim"],
    RGB:         ["R", "G", "B"],
    RGBD:        ["R", "G", "B", "Dim"],
    RGBDS:       ["R", "G", "B", "Dim", "Strobe"],
    RGBSD:       ["R", "G", "B", "Strobe", "Dim"],
    DRGB:        ["Dim", "R", "G", "B"],
    DRGBS:       ["Dim", "R", "G", "B", "Strobe"],
    RGBW:        ["R", "G", "B", "W"],
    RGBWD:       ["R", "G", "B", "W", "Dim"],
    RGBWDS:      ["R", "G", "B", "W", "Dim", "Strobe"],
    RGBWA:       ["R", "G", "B", "W", "Ambre"],
    RGBWAD:      ["R", "G", "B", "W", "Ambre", "Dim"],
    MOVING_RGB:  ["Pan", "Tilt", "R", "G", "B", "Dim", "Shutter", "Speed"],
    MOVING_RGBW: ["Pan", "Tilt", "R", "G", "B", "W", "Dim", "Shutter", "Speed"],
    STROBE_2CH:  ["Shutter", "Dim"],
  };

  // Libellés du choix de profil dans le patch (ordre d'affichage).
  const PROFILE_LABELS = [
    ["RGBDS", "PAR LED · R G B Dim Strobe (5 canaux)"],
    ["RGB", "PAR LED · R G B (3 canaux)"],
    ["RGBD", "PAR LED · R G B Dim (4 canaux)"],
    ["DRGB", "PAR LED · Dim R G B (4 canaux)"],
    ["DRGBS", "PAR LED · Dim R G B Strobe (5 canaux)"],
    ["RGBSD", "PAR LED · R G B Strobe Dim (5 canaux)"],
    ["RGBW", "PAR LED · R G B W (4 canaux)"],
    ["RGBWD", "PAR LED · R G B W Dim (5 canaux)"],
    ["RGBWDS", "PAR LED · R G B W Dim Strobe (6 canaux)"],
    ["RGBWA", "PAR LED · R G B W Ambre (5 canaux)"],
    ["RGBWAD", "PAR LED · R G B W Ambre Dim (6 canaux)"],
    ["DIM", "Gradateur · 1 canal"],
    ["STROBE_2CH", "Stroboscope · Shutter Dim (2 canaux)"],
    ["MOVING_RGB", "Lyre LED · Pan Tilt R G B Dim Shutter Vitesse (8 canaux)"],
    ["MOVING_RGBW", "Lyre LED · Pan Tilt R G B W Dim Shutter Vitesse (9 canaux)"],
  ];

  function hexToRgb(hex) {
    const h = (hex || "#000000").replace("#", "");
    return [parseInt(h.slice(0, 2), 16) || 0, parseInt(h.slice(2, 4), 16) || 0, parseInt(h.slice(4, 6), 16) || 0];
  }

  /**
   * Remplit `dmx` (Uint8Array(512), canal 1 = index 0) à partir des projecteurs.
   * Projecteur : { address (1..512), profile, color "#rrggbb" (couleur PURE,
   * = base_color du PC), level 0..100, muted, strobe 0..100 (strobe_speed),
   * pan/tilt 0..65535 }.
   */
  function render(fixtures, dmx) {
    dmx = dmx || new Uint8Array(512);
    dmx.fill(0);
    for (const f of fixtures) {
      const profile = PROFILES[f.profile];
      if (!profile) continue;
      const set = (idx, v) => {
        const ch = f.address - 1 + idx;
        if (ch >= 0 && ch < 512) dmx[ch] = Math.max(0, Math.min(255, Math.trunc(v)));
      };
      if (f.muted) continue;                      // tout à 0 (pas de trichromie soustractive en v1)

      const level = f.level || 0;
      const dimmer = Math.trunc((level / 100) * 255);
      const hasDimmer = profile.includes("Dim");
      const [br, bg, bb] = hexToRgb(f.color);
      let r, g, b;
      if (hasDimmer) { r = br; g = bg; b = bb; }  // RGB = couleur pure, le niveau passe par Dim
      else {
        // Pas de canal Dim : proj.color porte déjà le niveau (Projector.set_color)
        r = Math.trunc(br * level / 100); g = Math.trunc(bg * level / 100); b = Math.trunc(bb * level / 100);
      }
      const hasStrobe = profile.includes("Strobe");
      const hasRgb = profile.includes("R") && profile.includes("G") && profile.includes("B");
      const wExtract = hasRgb && profile.includes("W") ? Math.min(r, g, b) : 0;
      const spd = f.strobe || 0;

      profile.forEach((type, idx) => {
        let v = 0;
        switch (type) {
          case "R": v = Math.max(0, r - wExtract); break;
          case "G": v = Math.max(0, g - wExtract); break;
          case "B": v = Math.max(0, b - wExtract); break;
          case "W": v = hasRgb ? wExtract : Math.trunc(r * 0.30 + g * 0.59 + b * 0.11); break;
          case "Dim": case "Dim2": v = dimmer; break;
          case "Strobe": v = spd > 0 ? Math.trunc(16 + (spd / 100) * (250 - 16)) : 0; break;
          case "Shutter": {
            v = 255;                                // ouvert
            if (spd > 0 && !hasStrobe) v = Math.trunc(64 + (spd / 100) * (95 - 64));
            break;
          }
          case "Pan": v = (f.pan ?? 32768) >> 8; break;
          case "Tilt": v = (f.tilt ?? 32768) >> 8; break;
          default: v = 0;                           // Ambre, Speed… : repos
        }
        set(idx, v);
      });
    }
    return dmx;
  }

  function channelCount(profile) { return (PROFILES[profile] || []).length; }

  const api = { PROFILES, PROFILE_LABELS, render, channelCount, hexToRgb };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.MystrowEngine = api;
})(typeof window !== "undefined" ? window : globalThis);
