"""
IA Lumiere - Analyse audio et generation de show lumineux reactif
"""
import wave
import array
import math
import os
import subprocess
import json

from PySide6.QtGui import QColor

try:
    import miniaudio
    HAS_MINIAUDIO = True
except ImportError:
    HAS_MINIAUDIO = False


class AudioColorAI:
    """IA reactive au son - analyse l'audio et genere des etats lumiere"""

    def __init__(self):
        self.dominant_color = QColor("#ff0000")
        self.palette = []
        self.energy_map = []  # energie par fenetre de 50ms (0.0-1.0)
        self.beats = []  # timestamps en ms des beats detectes
        self.analyzed = False
        self.window_ms = 50

        # Sections detectees
        self.drops = []    # [time_ms] — instants de drop detectes
        self.sections = [] # [(start_ms, 'quiet'|'verse'|'build'|'high'|'drop')]

        # Etat courant pour les changements de couleur
        self._contre_color_idx = 0
        self._lat_color_idx = 0
        self._last_beat_idx = -1
        self._beat_group_count = 0
        self._flash_until = 0

        # Effets creatifs
        self._effect_contre_until = 0
        self._effect_lat_until = 0
        self._effect_contre_type = None  # "pulse" ou "strobe"
        self._effect_lat_type = None
        self._contre_alt_color_idx = 0
        self._lat_alt_color_idx = 0
        self._bicolor_active = False
        self._bicolor_until = 0

        # Face (Groupe A)
        self._face_color_idx = 0
        self._face_alt_color_idx = 0

        # Douches — chase sequentiel (D/E/F)
        self._def_chase_idx = 0  # 0,1,2 = douche1,2,3

    def set_dominant_color(self, color):
        """Definit la couleur dominante et genere la palette"""
        self.dominant_color = color
        self._generate_palette()

    def load_analysis(self, data):
        """Charge des donnees d'analyse pre-calculees (evite re-analyse au play)"""
        self.energy_map = data["energy_map"]
        self.beats = data["beats"]
        self.analyzed = True
        self._detect_sections()

    def _generate_palette(self):
        """Genere 8 variations de couleur autour de la dominante"""
        base_hue = self.dominant_color.hsvHue()
        base_sat = self.dominant_color.hsvSaturation()
        base_val = self.dominant_color.value()

        # Si couleur sans hue (blanc/gris/noir), utiliser rouge
        if base_hue < 0:
            base_hue = 0
            base_sat = 255
            base_val = 255

        self.palette = []
        offsets = [0, 20, -20, 40, -40, 60, -60, 180]
        for offset in offsets:
            hue = (base_hue + offset) % 360
            sat = max(150, min(255, base_sat))
            val = max(200, min(255, base_val))
            self.palette.append(QColor.fromHsv(hue, sat, val))

    def analyze(self, filepath):
        """Analyse complete du fichier audio"""
        self.analyzed = False
        self.energy_map = []
        self.beats = []
        self._contre_color_idx = 0
        self._lat_color_idx = 0
        self._last_beat_idx = -1
        self._beat_group_count = 0
        self._flash_until = 0

        samples = self._read_audio(filepath)

        if not samples and not self.energy_map:
            # Ni samples ni energy_map (tout a echoue)
            print("IA Lumiere: Analyse impossible, mode fallback")
            self._generate_fallback()
            self.analyzed = True
            return

        if samples:
            # Calculer l'energie par fenetre de 50ms
            sample_rate = 22050
            window_size = int(sample_rate * self.window_ms / 1000)

            for i in range(0, len(samples), window_size):
                chunk = samples[i:i + window_size]
                if len(chunk) > 0:
                    rms = math.sqrt(sum(s * s for s in chunk) / len(chunk))
                    self.energy_map.append(rms)

            # Normaliser
            if self.energy_map:
                max_e = max(self.energy_map)
                if max_e > 0:
                    self.energy_map = [e / max_e for e in self.energy_map]

        # Detecter les beats puis les sections
        self._detect_beats()
        self._detect_sections()
        self.analyzed = True
        print(f"IA Lumiere: {len(self.energy_map)} fenetres, {len(self.beats)} beats, "
              f"{len(self.drops)} drops")

    def _read_audio(self, filepath):
        """Lit un fichier audio, retourne des samples normalises mono 22050Hz"""
        # Essai 1 : WAV natif
        try:
            with wave.open(filepath, 'rb') as wf:
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                framerate = wf.getframerate()
                n_frames = wf.getnframes()
                frames = wf.readframes(n_frames)

                if sampwidth == 2:
                    raw = array.array('h', frames)
                elif sampwidth == 1:
                    raw = array.array('B', frames)
                    raw = array.array('h', [int((x - 128) * 256) for x in raw])
                else:
                    return None

                # Mix mono
                if n_channels == 2:
                    mono = [(raw[i] + raw[i + 1]) / 2 for i in range(0, len(raw), 2)]
                else:
                    mono = [float(x) for x in raw]

                # Resample vers 22050Hz si besoin
                if framerate != 22050:
                    ratio = framerate / 22050
                    resampled = []
                    pos = 0.0
                    while int(pos) < len(mono):
                        resampled.append(mono[int(pos)])
                        pos += ratio
                    mono = resampled

                # Normaliser -1.0 a 1.0
                max_val = max((abs(s) for s in mono), default=1)
                if max_val > 0:
                    mono = [s / max_val for s in mono]

                print(f"IA Lumiere: WAV lu ({len(mono)} samples)")
                return mono

        except wave.Error:
            pass
        except Exception as e:
            print(f"IA Lumiere: Erreur WAV: {e}")

        # Essai 2 : miniaudio direct
        if HAS_MINIAUDIO:
            try:
                decoded = miniaudio.decode_file(
                    filepath,
                    output_format=miniaudio.SampleFormat.SIGNED16,
                    nchannels=1,
                    sample_rate=22050
                )
                raw = array.array('h', decoded.samples)
                max_val = max((abs(s) for s in raw), default=1)
                samples = [s / max_val for s in raw] if max_val > 0 else [0.0] * len(raw)
                print(f"IA Lumiere: miniaudio direct ({len(samples)} samples)")
                return samples
            except Exception as e:
                print(f"IA Lumiere: miniaudio echoue: {e}")

        # Essai 3 : subprocess Python 3.12 (calcule energy_map directement)
        return self._read_via_subprocess(filepath)

    def _read_via_subprocess(self, filepath):
        """Decode et analyse via subprocess Python qui a miniaudio"""
        py312 = r"C:\Users\nikop\AppData\Local\Programs\Python\Python312\python.exe"
        if not os.path.exists(py312):
            for p in [r"C:\Python312\python.exe", r"C:\Python\python.exe"]:
                if os.path.exists(p):
                    py312 = p
                    break
            else:
                return None

        # Le subprocess calcule directement l'energy_map (evite transfert de millions de samples)
        script = f'''
import miniaudio, array, json, math
decoded = miniaudio.decode_file(
    r"{filepath}",
    output_format=miniaudio.SampleFormat.SIGNED16,
    nchannels=1,
    sample_rate=22050
)
raw = array.array("h", decoded.samples)
window = 1102
energy = []
for i in range(0, len(raw), window):
    chunk = raw[i:i+window]
    if chunk:
        rms = math.sqrt(sum(s*s for s in chunk) / len(chunk))
        energy.append(rms)
max_e = max(energy) if energy else 1
energy = [e/max_e for e in energy] if max_e > 0 else energy
print(json.dumps(energy))
'''
        try:
            result = subprocess.run(
                [py312, "-c", script],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode == 0:
                self.energy_map = json.loads(result.stdout.strip())
                print(f"IA Lumiere: subprocess ({len(self.energy_map)} fenetres)")
                return None  # energy_map deja rempli
        except subprocess.TimeoutExpired:
            print("IA Lumiere: subprocess timeout")
        except Exception as e:
            print(f"IA Lumiere: subprocess echoue: {e}")

        return None

    def _generate_fallback(self):
        """Genere des beats artificiels (~120 BPM) quand l'analyse echoue"""
        duration_ms = 300000  # 5 minutes
        nb_windows = duration_ms // self.window_ms

        self.energy_map = []
        for i in range(nb_windows):
            base = 0.5 + 0.3 * math.sin(i * 0.05)
            self.energy_map.append(max(0.0, min(1.0, base)))

        # Beats reguliers a 120 BPM
        beat_interval = 500
        t = 0
        while t < duration_ms:
            self.beats.append(t)
            t += beat_interval

    def _detect_beats(self):
        """Detecte les beats par pics d'energie au-dessus de la moyenne mobile"""
        self.beats = []
        if not self.energy_map:
            return

        avg_window = 40  # ~2 secondes
        min_spacing = int(300 / self.window_ms)  # 300ms min entre beats

        running_avg = []
        for i in range(len(self.energy_map)):
            start = max(0, i - avg_window)
            avg = sum(self.energy_map[start:i + 1]) / (i - start + 1)
            running_avg.append(avg)

        last_beat_idx = -min_spacing
        for i in range(len(self.energy_map)):
            if i - last_beat_idx < min_spacing:
                continue
            threshold = max(running_avg[i] * 1.4, 0.25)
            if self.energy_map[i] > threshold:
                self.beats.append(i * self.window_ms)
                last_beat_idx = i

    def _detect_sections(self):
        """Detecte les drops, refrains, montees et couplets dans l'energy_map.

        Algorithme :
         - Moyenne courte  (0.5s)  vs moyenne longue (4s) => detecte les sauts
         - Drop     : saut d'energie > 0.35 ET energie courante > 0.60
         - High     : energie soutenue > 0.55 pendant > 3s (apres un drop)
         - Build    : energie montante sur 2-4s avant un drop
         - Quiet    : energie < 0.25
         - Verse    : le reste
        """
        self.drops = []
        self.sections = []

        n = len(self.energy_map)
        if n < 40:
            return

        w = self.window_ms
        long_w  = max(1, 4000  // w)   # 4 secondes
        short_w = max(1, 500   // w)   # 500 ms
        min_drop_gap = max(1, 3000 // w)   # 3s min entre deux drops

        # Calcul des moyennes glissantes longues
        long_avg = []
        for i in range(n):
            s = max(0, i - long_w)
            long_avg.append(sum(self.energy_map[s:i + 1]) / (i - s + 1))

        # Detection des drops
        last_drop_idx = -min_drop_gap
        for i in range(short_w, n):
            short = sum(self.energy_map[max(0, i - short_w):i + 1]) / short_w
            curr  = self.energy_map[i]
            jump  = short - long_avg[i]
            if curr > 0.60 and jump > 0.30 and (i - last_drop_idx) >= min_drop_gap:
                self.drops.append(i * w)
                last_drop_idx = i

        # Construction des sections (parcours chronologique)
        DROP_WINDOW_MS  = 1200   # duree du "moment drop" en ms
        BUILD_BEFORE_MS = 3500   # fenetre build-up avant un drop
        HIGH_THRESH     = 0.55   # seuil energie haute soutenue
        QUIET_THRESH    = 0.22   # seuil silence

        total_ms = n * w
        t = 0
        while t < total_ms:
            # Est-on dans la fenetre d'un drop ?
            in_drop = any(d <= t < d + DROP_WINDOW_MS for d in self.drops)
            if in_drop:
                self.sections.append((t, 'drop'))
                t += DROP_WINDOW_MS
                continue

            # Est-on dans un build-up avant un drop ?
            in_build = any(d - BUILD_BEFORE_MS <= t < d for d in self.drops)
            if in_build:
                self.sections.append((t, 'build'))
                t += 500
                continue

            # Sinon : qualifier par l'energie locale
            idx = min(n - 1, t // w)
            e   = long_avg[idx]
            if e > HIGH_THRESH:
                self.sections.append((t, 'high'))
            elif e < QUIET_THRESH:
                self.sections.append((t, 'quiet'))
            else:
                self.sections.append((t, 'verse'))
            t += 500

    def get_section_at(self, time_ms):
        """Retourne la section courante : 'drop'|'build'|'high'|'verse'|'quiet'."""
        sec = 'verse'
        for start, label in self.sections:
            if start <= time_ms:
                sec = label
            else:
                break
        return sec

    def get_energy_at(self, time_ms):
        """Retourne l'energie a un instant donne (0.0-1.0)"""
        idx = int(time_ms / self.window_ms)
        if 0 <= idx < len(self.energy_map):
            return self.energy_map[idx]
        return 0.5

    def get_state_at(self, time_ms, duration_ms, max_dimmers=None):
        """Retourne l'etat lumiere pour chaque groupe de projecteurs

        L'IA joue uniquement sur face, lat et contre (pas les douches).
        Effets creatifs: pulse/strobe ponctuels, bicolore, flash sur beats forts.

        Args:
            max_dimmers: dict optionnel {group: 0-100} pour plafonner les niveaux

        Returns: dict avec (QColor, level) par groupe + cles d'effets creatifs
        """
        if not self.palette:
            self._generate_palette()

        if max_dimmers is None:
            max_dimmers = {}

        energy = self.get_energy_at(time_ms)

        # Groupes eteints explicitement (max_dimmers == 0)
        face_max = max_dimmers.get('face', 100) / 100.0
        contre_max = max_dimmers.get('contre', 100) / 100.0
        lat_max = max_dimmers.get('lat', 100) / 100.0

        # Trouver le beat courant
        beat_idx = -1
        for i, bt in enumerate(self.beats):
            if bt <= time_ms:
                beat_idx = i
            else:
                break

        # Changement de couleur au beat
        if beat_idx >= 0 and beat_idx != self._last_beat_idx:
            self._last_beat_idx = beat_idx
            self._beat_group_count += 1

            # Contres changent a chaque beat
            self._contre_color_idx = beat_idx % len(self.palette)

            # Bicolore: tous les 4 beats, lat prend une couleur differente (complementaire)
            if self._beat_group_count % 4 == 0:
                self._lat_color_idx = (self._contre_color_idx + 2) % len(self.palette)
            else:
                self._lat_color_idx = self._contre_color_idx

            # Face change de couleur tous les 2 beats (rythme plus lent)
            if self._beat_group_count % 2 == 0:
                self._face_color_idx = (self._contre_color_idx + 3) % len(self.palette)

            # Chase douches : avancer d'une douche a chaque beat
            self._def_chase_idx = beat_idx % 3

            # Flash sur beats forts (energie > 0.75) toutes les 4 mesures
            if energy > 0.75 and self._beat_group_count % 4 == 0:
                self._flash_until = time_ms + 150  # flash 150ms

            # --- Effets creatifs ponctuels ---
            # Pulse sur contres tous les ~8 beats quand energie forte
            if self._beat_group_count % 8 == 0 and energy > 0.6:
                self._effect_contre_type = "pulse"
                self._effect_contre_until = time_ms + 2000

            # Strobe court sur lateraux tous les ~16 beats
            if self._beat_group_count % 16 == 0 and energy > 0.5:
                self._effect_lat_type = "strobe"
                self._effect_lat_until = time_ms + 1000

            # Mode bicolore tous les ~6 beats pendant 4 beats
            if self._beat_group_count % 6 == 0:
                self._bicolor_active = True
                # Couleur alternative = complementaire dans la palette
                self._contre_alt_color_idx = (self._contre_color_idx + 4) % len(self.palette)
                self._lat_alt_color_idx = (self._lat_color_idx + 3) % len(self.palette)
                self._face_alt_color_idx = (self._face_color_idx + 2) % len(self.palette)
                # Estimer duree de 4 beats
                avg_beat_ms = 500
                if len(self.beats) > 1:
                    total = self.beats[-1] - self.beats[0]
                    avg_beat_ms = total / (len(self.beats) - 1)
                self._bicolor_until = time_ms + int(avg_beat_ms * 4)

        # Desactiver effets expires
        if time_ms >= self._effect_contre_until:
            self._effect_contre_type = None
        if time_ms >= self._effect_lat_until:
            self._effect_lat_type = None
        if time_ms >= self._bicolor_until:
            self._bicolor_active = False

        # Calcul du fade global (entree 5s, sortie 5s)
        fade_in_ms = 5000
        fade_out_ms = 5000

        if time_ms < fade_in_ms:
            global_fade = time_ms / fade_in_ms
        elif duration_ms > 0 and (duration_ms - time_ms) < fade_out_ms:
            global_fade = (duration_ms - time_ms) / fade_out_ms
        else:
            global_fade = 1.0

        # Flash actif ?
        is_flashing = time_ms < self._flash_until

        # === FACE : couleur reactive au beat (rythme x0.5 par rapport aux contres) ===
        if face_max == 0:
            face_color = QColor(0, 0, 0)
            face_level = 0
        elif is_flashing:
            face_color = QColor(255, 255, 255)
            face_level = int(100 * global_fade * face_max)
        else:
            face_color = self.palette[self._face_color_idx] if self.palette else self.dominant_color
            face_level = int((65 + energy * 25) * global_fade * face_max)

        # === CONTRES : couleur reactive au beat ===
        if contre_max == 0:
            contre_color = QColor(0, 0, 0)
            contre_level = 0
        elif is_flashing:
            contre_color = QColor(255, 255, 255)
            contre_level = int(100 * global_fade * contre_max)
        else:
            contre_color = self.palette[self._contre_color_idx] if self.palette else self.dominant_color
            contre_level = int((65 + energy * 25) * global_fade * contre_max)

        # Appliquer effet pulse sur contres
        if self._effect_contre_type == "pulse" and contre_max > 0:
            pulse_mod = math.sin(time_ms * 8 / 1000.0) * 0.5 + 0.5
            contre_level = int(contre_level * (0.3 + 0.7 * pulse_mod))

        # === LAT : symetrique avec bicolore ponctuel ===
        if lat_max == 0:
            lat_color = QColor(0, 0, 0)
            lat_level = 0
        elif is_flashing:
            lat_color = QColor(255, 255, 255)
            lat_level = int(100 * global_fade * lat_max)
        else:
            lat_color = self.palette[self._lat_color_idx] if self.palette else self.dominant_color
            lat_level = int((65 + energy * 25) * global_fade * lat_max)

        # Appliquer effet strobe sur lateraux
        if self._effect_lat_type == "strobe" and lat_max > 0:
            strobe_on = (int(time_ms / 80) % 2) == 0
            if not strobe_on:
                lat_level = 0

        # === GROUPES D/E/F : tous actifs — accent qui tourne sur les beats ===
        grp_d_max = max_dimmers.get('douche1', 100) / 100.0
        grp_e_max = max_dimmers.get('douche2', 100) / 100.0
        grp_f_max = max_dimmers.get('douche3', 100) / 100.0
        def_base_level = int((70 + energy * 30) * global_fade)
        pal = self.palette if self.palette else [self.dominant_color]
        if is_flashing:
            # Flash : tous à blanc max
            grp_d_level = grp_e_level = grp_f_level = 100
            def_color_d = def_color_e = def_color_f = QColor(255, 255, 255)
        else:
            # Tous actifs : groupe accentué à plein niveau, les autres à ~45 %
            accent = def_base_level
            base   = max(20, int(def_base_level * 0.45))
            grp_d_level = accent if self._def_chase_idx == 0 else base
            grp_e_level = accent if self._def_chase_idx == 1 else base
            grp_f_level = accent if self._def_chase_idx == 2 else base
            # Couleurs décalées dans la palette pour chaque groupe
            def_color_d = pal[self._contre_color_idx % len(pal)]
            def_color_e = pal[(self._contre_color_idx + 2) % len(pal)]
            def_color_f = pal[(self._contre_color_idx + 4) % len(pal)]
        def_color = def_color_d  # compat retour

        # Couleurs alternatives pour mode bicolore
        contre_alt = None
        lat_alt = None
        face_alt = None
        if self._bicolor_active and self.palette:
            contre_alt = self.palette[self._contre_alt_color_idx]
            lat_alt = self.palette[self._lat_alt_color_idx]
            face_alt = self.palette[self._face_alt_color_idx]

        return {
            'face': (face_color, max(0, min(100, face_level))),
            'contre': (contre_color, max(0, min(100, contre_level))),
            'lat': (lat_color, max(0, min(100, lat_level))),
            'douche1': (def_color_d, max(0, min(100, int(grp_d_level * grp_d_max)))),
            'douche2': (def_color_e, max(0, min(100, int(grp_e_level * grp_e_max)))),
            'douche3': (def_color_f, max(0, min(100, int(grp_f_level * grp_f_max)))),
            'contre_alt': contre_alt,
            'lat_alt': lat_alt,
            'face_alt': face_alt,
            'contre_effect': self._effect_contre_type if contre_max > 0 else None,
            'lat_effect': self._effect_lat_type if lat_max > 0 else None,
            'section': self.get_section_at(time_ms),
            'energy': energy,
            'global_fade': global_fade,
        }

    def reset(self):
        """Reinitialise l'IA"""
        self.energy_map = []
        self.beats = []
        self.analyzed = False
        self._contre_color_idx = 0
        self._lat_color_idx = 0
        self._last_beat_idx = -1
        self._beat_group_count = 0
        self._flash_until = 0
        self._effect_contre_until = 0
        self._effect_lat_until = 0
        self._effect_contre_type = None
        self._effect_lat_type = None
        self._contre_alt_color_idx = 0
        self._lat_alt_color_idx = 0
        self._face_color_idx = 0
        self._face_alt_color_idx = 0
        self._def_chase_idx = 0
        self._bicolor_active = False
        self._bicolor_until = 0
