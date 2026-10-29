"""
assistant_nlu.py — Compréhension des demandes de l'assistant MyStrow.

100 % local, sans modèle de langue : un vocabulaire par langue (fr, en, es,
de, pt, ja) et quelques règles. Une phrase devient une liste d'actions :

    parse("allume la face en rouge et envoie un effet rapide", effects)
    → Parsed(lang="fr", actions=[
          {"do": "color", "hex": "#ff0000", "color": "red", "target": {"group": "A"}, "level": 100},
          {"do": "effect", "name": "Chase Rapide", "speed": 85}])

Module pur (aucun import Qt) : testé par test_assistant_nlu.py. L'exécution
et les réponses sont dans assistant_panel.py.

Pour enrichir le vocabulaire : ajouter des mots dans les tables ci-dessous ;
les phrases que l'assistant n'a pas comprises sont gardées par le panneau
(~/.mystrow_assistant.json, clé "unknown") pour savoir quoi ajouter.
"""

import re
import unicodedata
from dataclasses import dataclass, field

LANGS = ("fr", "en", "es", "de", "pt", "ja")


# ── Normalisation ────────────────────────────────────────────────────────────

def normalize(text: str) -> str:
    """Minuscules, sans accents latins, ponctuation → espaces.

    NFKC d'abord (chiffres et ％ pleine chasse du japonais → ASCII), puis on
    retire les accents des seules lettres latines : un NFKD global ferait
    perdre les dakuten du japonais (ド → ト)."""
    t = unicodedata.normalize("NFKC", text or "").lower()
    out = []
    for ch in t:
        if ord(ch) < 0x250:
            ch = "".join(c for c in unicodedata.normalize("NFKD", ch)
                         if not unicodedata.combining(c))
        out.append(ch)
    t = "".join(out).replace("ß", "ss")
    # On garde . , entre chiffres (2.3), % et = ; le reste devient espace.
    t = re.sub(r"(?<=\d)[.,](?=\d)", ".", t)
    t = re.sub(r"[^\w%=.\s]|_", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _is_latin(word: str) -> bool:
    return all(ord(c) < 0x250 for c in word)


def _pattern(word: str):
    w = re.escape(word).replace(r"\ ", r"\s+")
    if _is_latin(word):
        return re.compile(rf"(?<![a-z0-9]){w}(?![a-z0-9])")
    return re.compile(w)          # japonais : pas d'espaces entre les mots


class Vocab:
    """{clé: {langue: [mots]}} → recherche avec langue détectée."""

    def __init__(self, table: dict):
        # (clé, langues, mot, motif) du plus long au plus court. Un mot commun à
        # plusieurs langues (« fixture », « strobe ») vote pour chacune d'elles.
        langs_of = {}
        for key, by_lang in table.items():
            for lang, words in by_lang.items():
                for w in words:
                    langs_of.setdefault((key, normalize(w)), []).append(lang)
        self.entries = [(key, tuple(langs), w, _pattern(w)) for (key, w), langs in langs_of.items()]
        self.entries.sort(key=lambda e: -len(e[2]))

    def find(self, t: str):
        """Première clé trouvée (mots longs d'abord) : (clé, langues, match) ou None."""
        for key, lang, _w, pat in self.entries:
            m = pat.search(t)
            if m:
                return key, lang, m
        return None

    def find_all(self, t: str) -> list:
        """Toutes les clés trouvées, dans l'ordre de la phrase, sans chevauchement."""
        taken, out = [], []
        for key, lang, _w, pat in self.entries:
            for m in pat.finditer(t):
                if any(m.start() < b and a < m.end() for a, b in taken):
                    continue
                taken.append((m.start(), m.end()))
                out.append((m.start(), key, lang))
        return [(key, lang) for _s, key, lang in sorted(out)]


# ── Vocabulaire ──────────────────────────────────────────────────────────────

COLORS = {
    "red":     {"fr": ["rouge", "rouges"], "en": ["red"], "es": ["rojo", "roja", "rojos"],
                "de": ["rot", "rote", "roten", "rotes"], "pt": ["vermelho", "vermelha", "vermelhos"],
                "ja": ["赤", "レッド"]},
    "blue":    {"fr": ["bleu", "bleue", "bleus"], "en": ["blue"], "es": ["azul", "azules"],
                "de": ["blau", "blaue", "blauen", "blaues"], "pt": ["azul"], "ja": ["青", "ブルー"]},
    "green":   {"fr": ["vert", "verte", "verts"], "en": ["green"], "es": ["verde", "verdes"],
                "de": ["grun", "grune", "grunen", "gruen"], "pt": ["verde"], "ja": ["緑", "グリーン"]},
    "yellow":  {"fr": ["jaune", "jaunes"], "en": ["yellow"], "es": ["amarillo", "amarilla"],
                "de": ["gelb", "gelbe", "gelben"], "pt": ["amarelo", "amarela"], "ja": ["黄色", "黄", "イエロー"]},
    "white":   {"fr": ["blanc", "blanche", "blancs"], "en": ["white"], "es": ["blanco", "blanca"],
                "de": ["weiss", "weisse", "weissen"], "pt": ["branco", "branca"], "ja": ["白", "ホワイト"]},
    "warm":    {"fr": ["blanc chaud", "chaud", "chaude"], "en": ["warm white", "warm"],
                "es": ["blanco calido", "calido", "calida"], "de": ["warmweiss", "warm"],
                "pt": ["branco quente", "quente"], "ja": ["暖色", "電球色"]},
    "cold":    {"fr": ["blanc froid", "froid", "froide"], "en": ["cool white", "cold white", "cold", "cool"],
                "es": ["blanco frio", "frio", "fria"], "de": ["kaltweiss", "kalt"],
                "pt": ["branco frio", "frio", "fria"], "ja": ["寒色", "昼光色"]},
    "orange":  {"fr": ["orange", "oranges"], "en": ["orange"], "es": ["naranja"], "de": ["orange"],
                "pt": ["laranja"], "ja": ["オレンジ"]},
    "purple":  {"fr": ["violet", "violette", "mauve"], "en": ["purple", "violet"], "es": ["morado", "violeta"],
                "de": ["lila", "violett"], "pt": ["roxo", "roxa", "violeta"], "ja": ["紫", "パープル"]},
    "pink":    {"fr": ["rose", "roses"], "en": ["pink"], "es": ["rosa", "rosado"], "de": ["rosa", "pink"],
                "pt": ["rosa"], "ja": ["ピンク"]},
    "cyan":    {"fr": ["cyan", "turquoise", "bleu ciel"], "en": ["cyan", "turquoise", "light blue"],
                "es": ["cian", "turquesa", "celeste"], "de": ["cyan", "turkis", "hellblau"],
                "pt": ["ciano", "turquesa"], "ja": ["シアン", "水色"]},
    "magenta": {"fr": ["magenta"], "en": ["magenta"], "es": ["magenta"], "de": ["magenta"],
                "pt": ["magenta"], "ja": ["マゼンタ"]},
    "amber":   {"fr": ["ambre"], "en": ["amber"], "es": ["ambar"], "de": ["bernstein", "amber"],
                "pt": ["ambar"], "ja": ["アンバー", "琥珀"]},
}

COLOR_HEX = {
    "red": "#ff0000", "blue": "#0000ff", "green": "#00ff00", "yellow": "#ffdd00",
    "white": "#ffffff", "warm": "#ffb46b", "cold": "#cfe3ff", "orange": "#ff8800",
    "purple": "#8800ff", "pink": "#ff44aa", "cyan": "#00dddd", "magenta": "#ff00ff",
    "amber": "#ffaa00",
}

# Mot de la couleur dans les noms d'effets intégrés (en français).
COLOR_IN_EFFECT_NAMES = {
    "red": "rouge", "blue": "bleu", "green": "vert", "white": "blanc", "orange": "orange",
    "purple": "violet", "pink": "rose", "cyan": "cyan", "magenta": "magenta", "amber": "amber",
}

TARGETS = {
    "all":     {"fr": ["tout", "toutes les lumieres", "tous les projecteurs", "tout le monde", "partout"],
                "en": ["all", "everything", "all lights", "all the lights", "everywhere"],
                "es": ["todo", "todas las luces", "todos los focos"], "de": ["alle", "alles", "alle lichter"],
                "pt": ["tudo", "todas as luzes", "todos os projetores"], "ja": ["全部", "すべて", "全て"]},
    "g:face":  {"fr": ["face", "faces"], "en": ["front", "front light", "front lights"],
                "es": ["frontal", "frontales", "frente"], "de": ["front", "frontlicht"],
                "pt": ["frente", "frontal", "frontais"], "ja": ["フロント", "正面"]},
    "g:contre": {"fr": ["contre", "contres", "contre jour"], "en": ["backlight", "backlights", "back light"],
                 "es": ["contra", "contraluz", "contras"], "de": ["gegenlicht"],
                 "pt": ["contra luz", "contraluz"], "ja": ["バック", "逆光"]},
    "g:lat":   {"fr": ["lat", "lateraux", "laterales", "lateral", "cote", "cotes"],
                "en": ["side", "sides", "side lights"], "es": ["laterales", "lateral"],
                "de": ["seite", "seitenlicht", "seitlich"], "pt": ["laterais", "lateral"], "ja": ["サイド", "横"]},
    "k:douche": {"fr": ["douche", "douches"], "en": ["top light", "toplight", "top lights", "overhead"],
                 "es": ["cenital", "cenitales"], "de": ["oberlicht"], "pt": ["contrapicado", "topo"],
                 "ja": ["トップ"]},
    "k:lyre":  {"fr": ["lyre", "lyres", "tete mobile", "tetes mobiles"],
                "en": ["moving head", "moving heads", "movers", "heads"],
                "es": ["cabeza movil", "cabezas moviles", "cabezas"], "de": ["moving head", "moving heads", "kopfe"],
                "pt": ["cabeca movel", "cabecas moveis", "moving heads"], "ja": ["ムービング", "ムービングヘッド"]},
    # Jamais « par » seul : c'est aussi une préposition (fr, es, pt).
    "k:par":   {"fr": ["pars", "par led", "les par"], "en": ["pars", "par cans", "par lights", "the pars"],
                "es": ["pares", "los par"], "de": ["pars", "par scheinwerfer", "die pars"],
                "pt": ["pares", "os par"], "ja": ["パーライト"]},
    "k:barre": {"fr": ["barre", "barres", "barre led"], "en": ["bar", "bars", "led bar", "led bars"],
                "es": ["barra", "barras"], "de": ["leiste", "leisten", "led leiste"],
                "pt": ["barra", "barras"], "ja": ["バー"]},
    "k:laser": {"fr": ["laser", "lasers", "l aserre", "laserre"], "en": ["laser", "lasers"], "es": ["laser", "laseres"],
                "de": ["laser"], "pt": ["laser", "lasers"], "ja": ["レーザー"]},
    # « états-celles », « et tes celles » : ce que la dictée fait d'« étincelles ».
    "k:etincelle": {"fr": ["etincelles", "etincelle", "machine a etincelles", "machines a etincelles", "etats celles",
                           "etat celles", "etat celle", "sparkular", "jets d etincelles"],
                    "en": ["sparks", "spark machine", "spark machines", "sparkular", "cold spark", "cold sparks"],
                    "es": ["chispas", "maquina de chispas"], "de": ["funken", "funkenmaschine"],
                    "pt": ["faiscas", "maquina de faiscas"], "ja": ["スパーク"]},
    "k:fumee": {"fr": ["fumee", "machine a fumee", "brouillard", "machine a brouillard"],
                "en": ["smoke", "fog", "haze", "smoke machine", "fog machine"], "es": ["humo", "maquina de humo"],
                "de": ["nebel", "nebelmaschine"], "pt": ["fumo", "maquina de fumo"], "ja": ["スモーク"]},
}

# « les lumières », « mes projecteurs » : toutes les lumières (sans numéro derrière).
LIGHTS = {"fr": ["lumieres", "lumiere", "projecteurs", "projos", "spots", "eclairage", "la lumiere"],
          "en": ["lights", "the lights", "fixtures", "lamps", "lighting"],
          "es": ["luces", "las luces", "focos", "proyectores"], "de": ["lichter", "licht", "scheinwerfer", "lampen"],
          "pt": ["luzes", "as luzes", "projetores", "focos"], "ja": ["ライト", "照明", "ライト全部"]}
# Nom d'un projecteur suivi de son numéro : « projecteur 3 », « spots 1 et 2 ».
_PROJ_NUM_RE = re.compile(
    r"(?<![a-z])(?:projecteurs?|projos?|proj|spots?|lampes?|fixtures?|lights?|lamps?|focos?|proyectores?|"
    r"scheinwerfer|lampen?|projetor(?:es)?|numeros?|numbers?|nummer|nr)\s*"
    r"(\d{1,3}(?:\s*(?:,|et|and|y|und|e|&|a|to|bis|ate|-)\s*\d{1,3})*)(?![0-9.%])")
_NUMS_RE = re.compile(r"\d{1,3}(?:\s*(?:,|et|and|y|und|e|&|a|to|bis|ate|-)\s*\d{1,3})*")
_RANGE_RE = re.compile(r"(\d{1,3})\s*(?:a|to|bis|ate|-)\s*(\d{1,3})")

EXCEPT = {"fr": ["sauf", "excepte", "a part", "hormis", "mais pas"], "en": ["except", "except for", "apart from", "but not"],
          "es": ["excepto", "salvo", "menos", "pero no"], "de": ["ausser", "bis auf", "aber nicht", "ohne"],
          "pt": ["exceto", "menos", "salvo", "mas nao"], "ja": ["以外", "を除いて"]}
PARITY = {
    "odd":  {"fr": ["impairs", "impaires", "impair"], "en": ["odd", "odd ones"], "es": ["impares", "impar"],
             "de": ["ungeraden", "ungerade"], "pt": ["impares", "impar"], "ja": ["奇数"]},
    "even": {"fr": ["pairs", "paires", "pair"], "en": ["even", "even ones"], "es": ["numeros pares", "los pares"],
             "de": ["geraden", "gerade"], "pt": ["numeros pares", "os pares"], "ja": ["偶数"]},
}
# « un sur deux », « en alternance » : couleurs posées tour à tour.
ALTERNATE = {"fr": ["un sur deux", "1 sur 2", "un sur 2", "en alternance", "alterne", "alternes", "alterner",
                    "un coup sur deux", "chacun son tour"],
             "en": ["every other", "one out of two", "one in two", "every second", "alternate", "alternating",
                    "in alternation"],
             "es": ["uno de cada dos", "uno si uno no", "alternando", "alterna", "en alternancia", "alternados"],
             "de": ["jeder zweite", "jede zweite", "jeden zweiten", "abwechselnd", "im wechsel"],
             "pt": ["um sim um nao", "um em cada dois", "alternado", "alternando", "alterna", "em alternancia"],
             "ja": ["交互", "1つおき", "一つおき", "ひとつおき"]}
# « … sur N » : un projecteur sur N (le mot entre les deux est libre : « un projo sur 3 »).
_ONE_IN_N_RE = re.compile(r"(?<![a-z0-9])(?:un|une|1|one|uno|una|um|uma|jeder|jede)\s+(?:[a-z]+\s+){0,2}"
                          r"(?:sur|in|out of|de cada|em cada|em|von)\s+(\d|deux|trois|quatre|two|three|four|"
                          r"dos|tres|cuatro|dois|quatro|zwei|drei|vier)(?![a-z0-9])")
OTHER = {"fr": ["l autre", "les autres", "le reste", "autre", "autres", "le suivant"],
         "en": ["the other", "the others", "the rest", "other", "others"],
         "es": ["el otro", "los otros", "el resto", "otro", "otros"],
         "de": ["der andere", "die anderen", "den rest", "andere", "anderen"],
         "pt": ["o outro", "os outros", "o resto", "outro", "outros"], "ja": ["他", "残り", "もう一つ"]}

FADE = {"fr": ["progressivement", "progressif", "progressive", "en fondu", "fondu", "petit a petit", "doucement",
               "lentement", "tout doucement", "en douceur", "graduellement"],
        "en": ["gradually", "slowly", "fade in", "fade out", "fade", "progressively", "smoothly", "little by little"],
        "es": ["progresivamente", "poco a poco", "lentamente", "despacio", "fundido", "gradualmente", "suavemente"],
        "de": ["langsam", "allmahlich", "nach und nach", "einblenden", "ausblenden", "sanft", "uberblenden"],
        "pt": ["progressivamente", "aos poucos", "devagar", "lentamente", "gradualmente", "suavemente"],
        "ja": ["徐々に", "だんだん", "ゆっくり", "フェード"]}
_DURATION_RE = re.compile(
    r"(\d{1,3}(?:\.\d)?)\s*(?:s|sec|secs|seconde|secondes|second|seconds|segundo|segundos|sekunde|sekunden|秒)"
    r"(?![a-z])|(\d{1,2})\s*(?:min|mins|minute|minutes|minuto|minutos|minuten|分)(?![a-z])"
    r"|(?<![a-z])(une|one|una|eine|uma)\s+(?:minute|minuto|minute|minuten)(?![a-z])")
FADE_DEFAULT_S = 4

# « Regler » (allemand) n'est pas dans la liste : c'est aussi « régler » sans accent.
FADER = {"fr": ["fader", "faders", "curseur", "curseurs", "potard", "potards", "tirette", "tirettes"],
         "en": ["fader", "faders", "slider", "sliders"], "es": ["fader", "faders", "deslizador", "deslizadores"],
         "de": ["fader", "schieberegler"], "pt": ["fader", "faders", "deslizante"], "ja": ["フェーダー"]}
_FADER_WORDS = r"(?:faders?|curseurs?|potards?|tirettes?|sliders?|deslizador(?:es)?|schieberegler|deslizante|フェーダー)"
_FADER_NUM_RE = re.compile(_FADER_WORDS + r"\s*(\d(?:\s*(?:,|et|and|y|und|e|&|a|to|bis|ate|-)\s*\d)*)(?![0-9%])")
_N_FADERS_RE = re.compile(r"(?<![a-z0-9])(\d|deux|trois|quatre|cinq|six|sept|huit|two|three|four|five|six|seven|eight|"
                          r"dos|tres|cuatro|cinco|seis|siete|ocho|zwei|drei|vier|funf|sechs|sieben|acht|dois|quatro|"
                          r"sete|oito)\s+(?:premiers?\s+|first\s+|primeros?\s+|ersten?\s+|primeiros?\s+)?" + _FADER_WORDS)

# « Pourquoi ça bug ? », « mes projecteurs s'allument pas » : diagnostic de l'état réel.
TROUBLE = {"fr": ["bug", "bugue", "beug", "ca marche pas", "marche pas", "marche plus", "fonctionne pas", "fonctionne plus",
                  "s allume pas", "s allument pas", "s allume plus", "s allument plus", "rien ne s allume", "rien ne se passe",
                  "rien ne sort", "ne reagit pas", "ne reagissent pas", "reagit plus", "reagissent plus", "probleme", "panne",
                  "en panne", "plante", "rien ne marche", "ne repond pas", "ne repond plus", "repond plus", "repond pas", "bouge pas", "bougent pas",
                  "bouge plus", "bougent plus", "y a rien", "il se passe rien", "ca deconne", "pas de lumiere"],
            "en": ["bug", "not working", "doesn t work", "does not work", "won t turn on", "nothing happens", "broken",
                   "no light", "problem", "issue", "not responding"],
            "es": ["no funciona", "no se enciende", "no se encienden", "no pasa nada", "problema", "falla", "no responde"],
            "de": ["funktioniert nicht", "geht nicht", "gehen nicht", "passiert nichts", "kein licht", "problem", "kaputt"],
            "pt": ["nao funciona", "nao acende", "nao acendem", "nao acontece nada", "problema", "avaria", "nao responde"],
            "ja": ["動かない", "つかない", "点かない", "反応しない", "故障", "バグ"]}

# Sujets des questions de branchement (« peut-on brancher une tablette ? »).
TOPICS = {
    "tablet":     {"fr": ["tablette", "telephone", "portable", "ipad", "smartphone"], "en": ["tablet", "phone", "ipad", "smartphone"],
                   "es": ["tableta", "telefono", "movil", "ipad"], "de": ["tablet", "handy", "smartphone", "ipad"],
                   "pt": ["tablet", "telemovel", "celular", "ipad"], "ja": ["タブレット", "スマホ", "携帯"]},
    "controller": {"fr": ["controleur", "controleurs", "console", "pupitre", "akai", "launchpad", "midi", "apc",
                          "surface de controle", "table lumiere"],
                   "en": ["controller", "console", "akai", "launchpad", "midi", "apc", "control surface", "lighting desk"],
                   "es": ["controlador", "consola", "mesa de luces", "akai", "midi"], "de": ["controller", "pult", "lichtpult", "akai", "midi"],
                   "pt": ["controlador", "consola", "mesa de luz", "akai", "midi"], "ja": ["コントローラー", "コンソール", "midi"]},
    "dmx":        {"fr": ["boitier", "interface", "interface dmx", "usb dmx", "node", "art net", "artnet", "enttec", "dongle"],
                   "en": ["interface", "dmx interface", "usb dmx", "node", "art net", "artnet", "enttec", "dongle", "box"],
                   "es": ["interfaz", "interfaz dmx", "usb dmx", "node", "art net", "artnet"], "de": ["interface", "box", "usb dmx", "node", "art net", "artnet"],
                   "pt": ["interface", "usb dmx", "node", "art net", "artnet"], "ja": ["インターフェース", "インターフェイス"]},
}

_GROUP_LETTER_RE = re.compile(r"(?<![a-z])(?:groupe|group|grupo|gruppe)\s+([a-z])(?![a-z])")
_GROUP_LETTER_JA = re.compile(r"グループ\s*([a-z])")

VERBS = {
    "on":   {"fr": ["allume", "allumer", "allumes", "allumez", "mets", "met", "mettez", "mettre", "passe", "passer",
                    "passez", "envoie"],
             "en": ["turn on", "switch on", "light up", "lights on", "put", "set", "make"],
             "es": ["enciende", "encender", "pon", "poner", "cambia"],
             "de": ["mach an", "einschalten", "schalte ein", "mach", "setze", "stelle"],
             "pt": ["acende", "acender", "liga", "ligar", "coloca", "poe", "mete"],
             "ja": ["つけて", "点けて", "点灯", "にして"]},
    "off":  {"fr": ["eteins", "eteindre", "eteint", "eteints", "eteignez", "eteigne", "coupe", "couper", "coupez"],
             "en": ["turn off", "switch off", "lights off", "kill"],
             "es": ["apaga", "apagar"], "de": ["mach aus", "ausschalten", "schalte aus", "aus"],
             "pt": ["apaga", "apagar", "desliga", "desligar"], "ja": ["消して", "消灯"]},
}

BLACKOUT = {"fr": ["noir", "blackout", "black out", "noir complet", "eteins tout", "eteints tout", "coupe tout"],
            "en": ["blackout", "black out", "all off", "everything off"],
            "es": ["oscuro", "apagon", "negro", "apaga todo"], "de": ["blackout", "dunkel", "alles aus", "schwarz"],
            "pt": ["blackout", "escuro", "apaga tudo"], "ja": ["暗転", "ブラックアウト", "全部消して"]}

LEVEL_FULL = {"fr": ["plein feu", "plein feux", "a fond", "au max", "maximum"], "en": ["full", "max", "maximum"],
              "es": ["a tope", "al maximo", "maximo"], "de": ["voll", "maximal"], "pt": ["no maximo", "maximo"],
              "ja": ["全開", "最大"]}
LEVEL_HALF = {"fr": ["moitie", "mi hauteur", "a moitie"], "en": ["half"], "es": ["mitad", "a la mitad"],
              "de": ["halb", "halbe"], "pt": ["metade", "a metade"], "ja": ["半分"]}
BRIGHTER = {"fr": ["plus fort", "plus de lumiere", "monte", "augmente", "plus lumineux"],
            "en": ["brighter", "more light", "turn up", "louder"], "es": ["mas fuerte", "mas luz", "sube"],
            "de": ["heller", "mehr licht", "lauter"], "pt": ["mais forte", "mais luz", "aumenta", "sobe"],
            "ja": ["明るく", "もっと明るく"]}
DIMMER = {"fr": ["moins fort", "moins de lumiere", "baisse", "diminue", "plus sombre", "tamise", "descends", "descend",
                 "descendre", "redescends"],
          "en": ["dimmer", "darker", "less light", "turn down", "dim"], "es": ["menos fuerte", "menos luz", "baja"],
          "de": ["dunkler", "weniger licht", "leiser"], "pt": ["mais fraco", "menos luz", "diminui", "baixa"],
          "ja": ["暗く", "もっと暗く"]}

SPEED_WORD = {"fr": ["vitesse"], "en": ["speed", "tempo"], "es": ["velocidad"], "de": ["geschwindigkeit", "tempo"],
              "pt": ["velocidade"], "ja": ["速度", "スピード"]}
FASTER = {"fr": ["plus vite", "plus rapide", "accelere", "accelerer", "acceleres"],
          "en": ["faster", "speed up", "quicker"], "es": ["mas rapido", "mas deprisa", "acelera"],
          "de": ["schneller"], "pt": ["mais rapido", "acelera", "mais depressa"], "ja": ["速く", "もっと速く"]}
SLOWER = {"fr": ["moins vite", "plus lent", "plus doucement", "ralentis", "ralentir", "ralenti"],
          "en": ["slower", "slow down"], "es": ["mas lento", "mas despacio", "frena"],
          "de": ["langsamer"], "pt": ["mais lento", "mais devagar"], "ja": ["遅く", "もっと遅く", "ゆっくりに"]}

EFFECT_WORD = {"fr": ["effet", "effets", "animation"], "en": ["effect", "effects", "animation"],
               "es": ["efecto", "efectos"], "de": ["effekt", "effekte"], "pt": ["efeito", "efeitos"],
               "ja": ["エフェクト", "効果"]}
STYLE = {
    "fast": {"fr": ["rapide", "rapides", "vite", "nerveux", "energique", "pechu"],
             "en": ["fast", "quick", "energetic", "rapid"], "es": ["rapido", "rapida", "energico"],
             "de": ["schnell", "schnelle", "schnellen"], "pt": ["rapido", "rapida", "energico"],
             "ja": ["速い", "激しい"]},
    "slow": {"fr": ["lent", "lente", "doux", "douce", "calme", "tranquille"],
             "en": ["slow", "soft", "calm", "gentle", "chill"], "es": ["lento", "lenta", "suave", "tranquilo"],
             "de": ["langsam", "langsame", "sanft", "ruhig"], "pt": ["lento", "lenta", "suave", "calmo"],
             "ja": ["ゆっくり", "遅い", "穏やか"]},
}
# Familles d'effets → mot cherché dans les noms intégrés (français).
EFFECT_TYPES = {
    "strobe":  {"fr": ["strobe", "stroboscope", "stroboscopique", "strober", "strobo", "strobes"], "en": ["strobe", "strobes"],
                "es": ["estrobo", "estroboscopio", "strobe"], "de": ["stroboskop", "strobe"],
                "pt": ["estrobo", "estroboscopio", "strobe"], "ja": ["ストロボ"]},
    "chase":   {"fr": ["chenillard", "chase", "poursuite"], "en": ["chase", "chaser"], "es": ["persecucion", "chase"],
                "de": ["lauflicht", "chase"], "pt": ["perseguicao", "chase"], "ja": ["チェイス"]},
    "rainbow": {"fr": ["arc en ciel", "rainbow"], "en": ["rainbow"], "es": ["arcoiris", "arco iris"],
                "de": ["regenbogen"], "pt": ["arco iris", "arco-iris"], "ja": ["レインボー", "虹"]},
    "pulse":   {"fr": ["pulsation", "pulse", "respiration"], "en": ["pulse", "breathing", "breathe"],
                "es": ["pulso", "respiracion"], "de": ["puls", "atmen"], "pt": ["pulso", "respiracao"],
                "ja": ["パルス"]},
    "wave":    {"fr": ["vague", "vagues"], "en": ["wave", "waves"], "es": ["ola", "olas"], "de": ["welle", "wellen"],
                "pt": ["onda", "ondas"], "ja": ["ウェーブ", "波"]},
    "flash":   {"fr": ["flash"], "en": ["flash"], "es": ["flash", "destello"], "de": ["blitz", "flash"],
                "pt": ["flash"], "ja": ["フラッシュ"]},
    "fire":    {"fr": ["effet feu", "flammes"], "en": ["fire"], "es": ["fuego"], "de": ["feuer"], "pt": ["fogo"],
                "ja": ["炎", "ファイヤー"]},
    # Mouvement de lyres (« fais tourner les lyres ») → effets de la catégorie Lyre.
    "movement": {"fr": ["tourner", "tourne", "tournent", "bouger", "bouge", "bougent", "mouvement", "mouvements",
                        "cercle", "cercles", "balancier", "pendule", "figure 8", "figure de 8", "en huit", "infini",
                        "spirale", "balayage", "balaye", "balayer"],
                 "en": ["move", "movement", "spin", "rotate", "circle", "circles", "swing", "pendulum",
                        "figure 8", "figure eight", "infinity", "spiral", "sweep"],
                 "es": ["mover", "muevan", "movimiento", "girar", "giren", "circulo", "circulos", "pendulo", "espiral",
                        "barrido"],
                 "de": ["bewegen", "bewegung", "drehen", "kreis", "kreise", "pendel", "spirale"],
                 "pt": ["mexer", "movimento", "girar", "circulo", "circulos", "pendulo", "espiral", "varrer"],
                 "ja": ["動かして", "回して", "円", "ムーブ"]},
}
_EFFECT_TYPE_TOKEN = {"strobe": "strobe", "chase": "chase", "rainbow": "rainbow", "pulse": "pulse",
                      "wave": "vague", "flash": "flash", "fire": "feu", "movement": "lyre"}
# Forme du mouvement → mot du nom de l'effet Lyre (« Lyre Cercle »…). Sans forme dite, un cercle.
MOVE_SHAPES = {
    "figure": ["figure 8", "figure de 8", "en huit", "figure eight"],
    "infini": ["infini", "infinity"],
    "balancier": ["balancier", "swing"],
    "pendule": ["pendule", "pendulum", "pendulo", "pendel"],
    "spiral": ["spirale", "spiral", "espiral"],
    "sweep": ["balayage", "balaye", "balayer", "sweep", "barrido", "varrer"],
    "carre": ["carre", "square"],
    "cercle": ["cercle", "cercles", "circle", "circles", "circulo", "circulos", "kreis", "kreise", "円"],
}

# Ambiances à thème → couleurs posées en alternance.
THEMES = {
    "halloween": {"fr": ["halloween", "citrouille"], "en": ["halloween", "spooky"], "es": ["halloween"],
                  "de": ["halloween"], "pt": ["halloween", "dia das bruxas"], "ja": ["ハロウィン"]},
    "christmas": {"fr": ["noel", "sapin"], "en": ["christmas", "xmas"], "es": ["navidad", "navideno"],
                  "de": ["weihnachten", "weihnachtlich"], "pt": ["natal", "natalino"], "ja": ["クリスマス"]},
    "romantic":  {"fr": ["romantique", "saint valentin", "amoureux"], "en": ["romantic", "valentine"],
                  "es": ["romantico", "romantica", "san valentin"], "de": ["romantisch", "valentinstag"],
                  "pt": ["romantico", "romantica", "dia dos namorados"], "ja": ["ロマンチック", "バレンタイン"]},
    "ocean":     {"fr": ["ocean", "sous marin", "sous marine", "aquatique", "plage", "marin", "marine"], "en": ["ocean", "underwater", "beach"],
                  "es": ["oceano", "submarino", "playa"], "de": ["ozean", "meer", "unterwasser", "strand"],
                  "pt": ["oceano", "submarino", "praia"], "ja": ["海", "オーシャン"]},
    "forest":    {"fr": ["foret", "nature", "jungle"], "en": ["forest", "nature", "jungle"],
                  "es": ["bosque", "naturaleza", "selva"], "de": ["wald", "natur", "dschungel"],
                  "pt": ["floresta", "natureza", "selva"], "ja": ["森", "ジャングル"]},
    "hell":      {"fr": ["enfer", "infernal", "volcan"], "en": ["hell", "hellish", "volcano"],
                  "es": ["infierno", "infernal", "volcan"], "de": ["holle", "hollisch", "vulkan"],
                  "pt": ["inferno", "infernal", "vulcao"], "ja": ["地獄", "火山"]},
    "ice":       {"fr": ["glace", "hiver", "neige", "polaire", "banquise"], "en": ["ice", "winter", "snow", "frozen"],
                  "es": ["hielo", "invierno", "nieve"], "de": ["eis", "winter", "schnee"],
                  "pt": ["gelo", "inverno", "neve"], "ja": ["氷", "冬", "雪"]},
    "sunset":    {"fr": ["coucher de soleil", "soleil couchant", "crepuscule"], "en": ["sunset", "dusk"],
                  "es": ["atardecer", "puesta de sol"], "de": ["sonnenuntergang", "abendrot"],
                  "pt": ["por do sol", "entardecer"], "ja": ["夕焼け", "サンセット"]},
    "club":      {"fr": ["club", "boite de nuit", "discotheque", "soiree dansante"], "en": ["club", "nightclub", "dance party"],
                  "es": ["discoteca"], "de": ["club", "disco"], "pt": ["discoteca", "balada"],
                  "ja": ["クラブ"]},
    "france":    {"fr": ["bleu blanc rouge", "tricolore", "14 juillet"], "en": ["french flag"],
                  "es": ["bandera francesa"], "de": ["franzosische flagge"], "pt": ["bandeira francesa"], "ja": ["フランス国旗"]},
}
THEME_COLORS = {"halloween": ["orange", "purple"], "christmas": ["red", "green"], "romantic": ["pink", "red"],
                "ocean": ["blue", "cyan"], "forest": ["green", "yellow"], "hell": ["red", "orange"],
                "ice": ["cyan", "white"], "sunset": ["orange", "pink"], "club": ["magenta", "cyan", "purple"],
                "france": ["blue", "white", "red"]}

# Ajouter au patch : « ajoute une lyre Shields », « patche-moi 4 PAR Betopper ».
_PATCH_RE = re.compile(r"(?<![a-z])(?:patche|patcher|patch|patches|ajoute|ajouter|ajoutes|rajoute|rajouter|"
                       r"installe|add|anade|agrega|anadir|agregar|fuge|hinzufugen|adiciona|adicionar)(?![a-z])|追加")
# Appareil → recherche générique quand aucune marque ni modèle n'est dit (clé vide : rien à chercher).
GEAR = {
    "moving head": ["lyre", "lyres", "moving head", "moving heads", "cabeza movil", "cabezas moviles",
                    "cabeca movel", "ムービング"],
    "par": ["par", "pars", "par led", "par leds"],
    "barre": ["barre", "barres", "barre led", "led bar", "barra", "barras", "leiste"],
    "strob": ["stroboscope", "stroboscopes", "strobe", "strobes", "estrobo"],
    "laser": ["laser", "lasers"],
    "wash": ["wash"], "beam": ["beam", "beams"],
    "fumee": ["machine a fumee", "machine a brouillard", "fumee", "brouillard", "smoke machine", "fog machine",
              "hazer", "humo", "nebelmaschine", "fumo"],
    "": ["projecteur", "projecteurs", "projo", "projos", "appareil", "appareils", "light", "lights", "fixture",
         "fixtures", "foco", "focos", "proyector", "proyectores", "scheinwerfer", "projetor", "projetores"],
}
# Marques courantes : « add a Chauvet Intimidator » se comprend sans « lyre » ni « patch ».
BRANDS = ["chauvet", "american dj", "adj", "eurolite", "stairville", "showtec", "cameo", "martin", "pro lights",
          "prolights", "robe", "clay paky", "varytec", "futurelight", "beamz", "briteq", "glp", "uking", "u king",
          "elation", "shehds", "jb systems", "lightmaxx", "blizzard", "starway", "equinox", "contest", "involight",
          "betopper", "ayra", "laserworld", "ghost", "mac mah", "algam", "power lighting", "boomtone", "ibiza",
          "fun generation", "high end", "vari lite", "ayrton", "sgm", "astera", "jade dragon", "nicols", "kam",
          "acme", "infinity", "lumiere", "eliminator", "stage right", "lixada", "u king", "ehaho"]
_BRAND_RE = re.compile(r"(?<![a-z])(?:" + "|".join(re.escape(b) for b in BRANDS if b != "lumiere") + r")(?![a-z])")
# Mots qui ne disent ni la marque ni le modèle.
_PATCH_FILLER = set("""moi me m ma mon mes une un des de du d le la les l au aux en dans sur pour stp svp merci
tu peux peux pourrais vous pouvez est ce que nouveau nouvelle nouvel nouveaux nouvelles please the a an
my new to in into of can you could i want je veux voudrais aimerais j patch dmx plan feu el los las mi mis una
nuevo nueva por favor den die das ein eine einen meine neue neuen bitte o os as meu minha meus novo nova e
modele marque model brand s il te plait bibliotheque librairie library biblioteca bibliothek
biblioteque""".split())

# REC Lumière : « programme-moi les lumières sur cette musique ».
_MUSIC_RE = re.compile(r"(?<![a-z])(?:musique|chanson|morceau|titre|zik|song|music|track|tune|cancion|musica|"
                       r"tema|lied|musik|titel|cancao|faixa)(?![a-z])|曲|音楽")
_PROG_RE = re.compile(r"(?<![a-z])(?:programme|programmer|programmes|programmez|program|programa|programar|"
                      r"programmiere|programmieren|light ?show|show lumiere|show de lumiere|sequence lumiere|"
                      r"lichtshow|genere|generer|generate|genera|generar|erstelle|gera|gerar|show|shows|"
                      r"sequence|secuencia|sequencia|espectaculo)(?![a-z])|プログラム|ライトショー")
_RAINBOW_RE = re.compile(r"(?<![a-z])(?:multicolore|toutes les couleurs|arc en ciel|rainbow|colorful|colourful|"
                         r"arcoiris|regenbogen|arco iris|bunt)(?![a-z])")

STOP = {"fr": ["stop", "arrete", "arreter", "arretes", "coupe l effet", "coupe les effets", "coupe l animation",
               "arrete l animation", "plus d effet", "stoppe"],
        "en": ["stop", "halt"], "es": ["parar", "deten", "detener"],
        "de": ["stopp", "stop", "halt", "anhalten", "beende"], "pt": ["parar", "pare"],
        "ja": ["止めて", "停止", "ストップ"]}

MEMORY_WORD = {"fr": ["memoire", "mem", "ambiance"], "en": ["memory", "mem", "cue", "scene"],
               "es": ["memoria", "escena"], "de": ["speicher", "szene"], "pt": ["memoria", "cena"],
               "ja": ["メモリ", "メモリー", "シーン"]}
_NUM_WORDS = {
    "un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "seven": 7, "eight": 8,
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7, "ocho": 8,
    "eins": 1, "zwei": 2, "drei": 3, "vier": 4, "funf": 5, "sechs": 6, "sieben": 7, "acht": 8,
    "um": 1, "dois": 2, "duas": 2, "quatro": 4, "sete": 7, "oito": 8,
}
_NUM = r"(\d|(?:" + "|".join(sorted(_NUM_WORDS, key=len, reverse=True)) + r")(?![a-z]))"
_MEM_RE = re.compile(r"(?<![a-z])" + _NUM + r"\s*(?:\.|,|point|punto|punkt|ponto|dot|/|-)?\s*" + _NUM
                     + r"(?![a-z0-9])")

PLAYBACK = {
    "next":       {"fr": ["suivant", "suivante", "morceau suivant", "titre suivant"], "en": ["next", "next song", "skip"],
                   "es": ["siguiente"], "de": ["nachster", "nachste", "nachstes", "weiter"],
                   "pt": ["proximo", "proxima", "seguinte"], "ja": ["次", "次の曲"]},
    "prev":       {"fr": ["precedent", "precedente"], "en": ["previous", "previous song"], "es": ["anterior"],
                   "de": ["vorherige", "vorheriger", "zuruck"], "pt": ["anterior"], "ja": ["前の曲"]},
    "play_pause": {"fr": ["play", "pause", "lecture", "joue", "reprends", "lance la musique", "mets la musique",
                          "lancer la musique", "lance la playlist", "lancer la playlist", "lance le morceau",
                          "lancer le morceau", "mets la playlist"],
                   "en": ["play", "pause", "resume", "play music", "play the music", "start the playlist"], "es": ["play", "pausa", "reproduce", "reproducir"],
                   "de": ["play", "pause", "abspielen", "wiedergabe"], "pt": ["play", "pausa", "toca", "tocar"],
                   "ja": ["再生", "一時停止"]},
    "go_back":    {"fr": ["go moins", "go retour", "go arriere"], "en": ["go back", "go minus"],
                   "es": ["go atras"], "de": ["go zuruck"], "pt": ["go atras"], "ja": ["ゴーバック"]},
    "go":         {"fr": ["go", "go plus"], "en": ["go", "go plus"], "es": ["go"], "de": ["go"], "pt": ["go"],
                   "ja": ["ゴー"]},
}

OPEN_VERB = {"fr": ["ouvre", "ouvrir", "affiche", "afficher", "montre", "montre moi"],
             "en": ["open", "show", "display", "show me"], "es": ["abre", "abrir", "muestra", "muestrame"],
             "de": ["offne", "oeffne", "offnen", "zeige", "zeig", "zeig mir"],
             "pt": ["abre", "abrir", "mostra", "mostrar"], "ja": ["開いて", "開く", "表示"]}
WINDOWS = {
    "patch":     {"fr": ["patch", "patch dmx", "patcher"], "en": ["patch", "dmx patch"], "es": ["patch"],
                  "de": ["patch"], "pt": ["patch"], "ja": ["パッチ"]},
    "effects":   {"fr": ["editeur d effets", "editeur des effets", "editeur effets", "effets"],
                  "en": ["effect editor", "effects editor", "effects"], "es": ["editor de efectos", "efectos"],
                  "de": ["effekt editor", "effekteditor", "effekte"], "pt": ["editor de efeitos", "efeitos"],
                  "ja": ["エフェクトエディタ", "エフェクト"]},
    "3d":        {"fr": ["3d", "plan de feu", "plan 3d", "vue 3d"], "en": ["3d", "3d view", "stage plot"],
                  "es": ["3d", "vista 3d"], "de": ["3d", "3d ansicht"], "pt": ["3d", "vista 3d"], "ja": ["3d"]},
    "rec":       {"fr": ["rec lumiere", "rec", "timeline", "editeur lumiere"], "en": ["light rec", "rec", "timeline", "light editor"],
                  "es": ["rec de luz", "rec", "linea de tiempo"], "de": ["rec licht", "rec", "zeitleiste"],
                  "pt": ["rec luz", "rec", "linha do tempo"], "ja": ["タイムライン"]},
    "output":    {"fr": ["sortie dmx", "sortie", "connexion dmx", "reglages dmx"], "en": ["dmx output", "output", "dmx settings"],
                  "es": ["salida dmx", "salida"], "de": ["dmx ausgang", "ausgang"], "pt": ["saida dmx", "saida"],
                  "ja": ["dmx出力", "出力"]},
    "tester":    {"fr": ["testeur", "testeur dmx"], "en": ["tester", "dmx tester"], "es": ["probador"],
                  "de": ["tester", "dmx tester"], "pt": ["testador"], "ja": ["テスター"]},
    "monitor":   {"fr": ["moniteur", "moniteur dmx"], "en": ["monitor", "dmx monitor"], "es": ["monitor"],
                  "de": ["monitor"], "pt": ["monitor"], "ja": ["モニター"]},
    "tablet":    {"fr": ["tablette", "telephone"], "en": ["tablet", "phone"], "es": ["tableta", "telefono"],
                  "de": ["tablet", "handy"], "pt": ["tablet", "telemovel", "celular"], "ja": ["タブレット"]},
    "ia":        {"fr": ["ia lumiere", "reglages ia"], "en": ["ai lighting", "ai settings"], "es": ["ia de luz"],
                  "de": ["licht ki", "ki einstellungen"], "pt": ["ia de luz"], "ja": ["ai照明"]},
    "akai":      {"fr": ["akai", "parametres akai", "apc"], "en": ["akai", "akai settings", "apc"], "es": ["akai"],
                  "de": ["akai"], "pt": ["akai"], "ja": ["akai"]},
    "shortcuts": {"fr": ["raccourcis", "raccourcis clavier"], "en": ["shortcuts", "keyboard shortcuts"],
                  "es": ["atajos"], "de": ["tastenkurzel", "kurzbefehle"], "pt": ["atalhos"], "ja": ["ショートカット"]},
    "obs":       {"fr": ["obs"], "en": ["obs"], "es": ["obs"], "de": ["obs"], "pt": ["obs"], "ja": ["obs"]},
    "vmix":      {"fr": ["vmix"], "en": ["vmix"], "es": ["vmix"], "de": ["vmix"], "pt": ["vmix"], "ja": ["vmix"]},
    "gamepad":   {"fr": ["manette"], "en": ["gamepad", "controller"], "es": ["mando"], "de": ["gamepad", "controller"],
                  "pt": ["comando", "manete"], "ja": ["コントローラー", "ゲームパッド"]},
    "news":      {"fr": ["nouveautes"], "en": ["what s new", "whats new", "news"], "es": ["novedades"],
                  "de": ["neuigkeiten"], "pt": ["novidades"], "ja": ["新機能"]},
    "tutorials": {"fr": ["tutos", "tutoriels", "tutoriel"], "en": ["tutorials", "tutorial"], "es": ["tutoriales"],
                  "de": ["tutorials", "anleitungen"], "pt": ["tutoriais"], "ja": ["チュートリアル"]},
}

SAVE = {"fr": ["enregistre le show", "sauvegarde", "sauvegarder"], "en": ["save the show", "save"],
        "es": ["guarda", "guardar"], "de": ["speichere", "speichern"], "pt": ["guarda", "salva", "salvar"],
        "ja": ["保存"]}

CONNECT = {"fr": ["connecte", "connecter", "reconnecte", "branche", "brancher"], "en": ["connect", "reconnect"],
           "es": ["conecta", "conectar", "reconecta"], "de": ["verbinde", "verbinden", "verbindung"],
           "pt": ["conecta", "conectar", "reconecta"], "ja": ["接続", "つないで"]}

FIXTURE_WORD = {"fr": ["fixture", "fixtures", "profil", "nouvel appareil", "nouveau projecteur", "nouvelle lyre"],
                "en": ["fixture", "fixtures", "fixture profile"], "es": ["fixture", "perfil"],
                "de": ["fixture", "gerat", "geratprofil"], "pt": ["fixture", "perfil"], "ja": ["フィクスチャ", "フィクスチャー"]}
CREATE_VERB = {"fr": ["cree", "creer", "crees", "ajoute", "ajouter", "fais", "fabrique", "nouvelle", "nouveau", "nouvel"],
               "en": ["create", "make", "add", "new", "build"], "es": ["crea", "crear", "anade", "nueva", "nuevo", "haz"],
               "de": ["erstelle", "erstellen", "neue", "neues", "neu", "anlegen"],
               "pt": ["cria", "criar", "adiciona", "nova", "novo", "faz"], "ja": ["作成", "作って", "追加", "新しい"]}

HELP = {"fr": ["aide", "que sais tu faire", "tu sais faire quoi", "qu est ce que tu sais faire"],
        "en": ["help", "what can you do"], "es": ["ayuda", "que puedes hacer", "que sabes hacer"],
        "de": ["hilfe", "was kannst du"], "pt": ["ajuda", "o que sabes fazer", "o que voce sabe fazer"],
        "ja": ["ヘルプ", "何ができる"]}
STATUS = {"fr": ["etat", "statut", "quels projecteurs", "combien de projecteurs"],
          "en": ["status", "state", "which fixtures", "how many fixtures"], "es": ["estado", "cuantos focos"],
          "de": ["status", "zustand"], "pt": ["estado", "quantos projetores"], "ja": ["状態", "ステータス"]}

_LEARN_RE = re.compile(
    r"^\s*(?:apprends|apprend|retiens|learn|remember|aprende|lerne|merke dir|覚えて)\s*[:]?\s*"
    r"[«\"']?(.+?)[»\"']?\s*(?:=|->|→|veut dire|means|significa|bedeutet|quiere decir|quer dizer)\s*(.+?)\s*$",
    re.IGNORECASE)
_FORGET_RE = re.compile(r"^\s*(?:oublie|forget|olvida|vergiss|esquece|忘れて)\s*[:]?\s*[«\"']?(.+?)[»\"']?\s*$",
                        re.IGNORECASE)

# « et » entre deux nombres (« projecteurs 1 et 3 ») ne coupe pas la phrase.
_SPLIT_RE = re.compile(r"(?<!\d)\s+(?:et|puis|and|then|y|luego|und|dann|e|depois)\s+"
                       r"|\s+(?:et|puis|and|then|y|luego|und|dann|e|depois)\s+(?!\d)"
                       r"|、|そして|それから|;|(?<!\d),|,(?!\s*\d)"
                       r"|[.!?。！？](?=\s)")      # fin de phrase (dictée : « c'est le MyStrow. Est-ce que tu peux… »)

_V = {name: Vocab(tbl) for name, tbl in {
    "color": COLORS, "target": TARGETS, "verb": VERBS, "playback": PLAYBACK, "window": WINDOWS,
    "style": STYLE, "etype": EFFECT_TYPES, "parity": PARITY, "topic": TOPICS, "theme": THEMES,
    "gear": {k or "generic": {"fr": v} for k, v in GEAR.items()},
}.items()}
_W = {name: Vocab({name: tbl}) for name, tbl in {
    "blackout": BLACKOUT, "full": LEVEL_FULL, "half": LEVEL_HALF, "brighter": BRIGHTER, "dimmer": DIMMER,
    "speed": SPEED_WORD, "faster": FASTER, "slower": SLOWER, "effect": EFFECT_WORD, "stop": STOP,
    "memory": MEMORY_WORD, "open": OPEN_VERB, "save": SAVE, "connect": CONNECT, "fixture": FIXTURE_WORD,
    "create": CREATE_VERB, "help": HELP, "status": STATUS, "lights": LIGHTS, "except": EXCEPT,
    "alternate": ALTERNATE, "other": OTHER, "fade": FADE, "fader": FADER, "trouble": TROUBLE,
}.items()}


# ── Analyse ──────────────────────────────────────────────────────────────────

@dataclass
class Parsed:
    lang: str
    actions: list = field(default_factory=list)

    @property
    def understood(self) -> bool:
        return bool(self.actions) and all(a["do"] != "unknown" for a in self.actions)


class _Votes:
    def __init__(self):
        self.n = {}

    def add(self, hit):
        if hit:
            for lang in hit[1]:
                self.n[lang] = self.n.get(lang, 0) + 1
        return hit

    def lang(self, default):
        if not self.n:
            return default
        best = max(self.n.values())
        tops = [l for l, c in self.n.items() if c == best]
        return default if default in tops else tops[0]


def _hit(name, t, votes):
    return votes.add(_W[name].find(t))


def _nums(s: str) -> list:
    """« 1 et 3 », « 2, 4 », « 1 à 4 » → [1, 3] / [2, 4] / [1, 2, 3, 4] (numéros affichés, base 1)."""
    out = []
    for a, b in _RANGE_RE.findall(s):
        out.extend(range(int(a), int(b) + 1))
    s = _RANGE_RE.sub(" ", s)
    out.extend(int(x) for x in re.findall(r"\d{1,3}", s))
    return sorted(set(n for n in out if n >= 1))


def _base_target(t, votes, bare_nums=False):
    tgt = None
    m = _PROJ_NUM_RE.search(t) or (bare_nums and _NUMS_RE.search(t))
    if m:
        tgt = {"nums": _nums(m.group(1) if m.lastindex else m.group(0))}
    else:
        m = _GROUP_LETTER_RE.search(t) or _GROUP_LETTER_JA.search(t)
        if m:
            tgt = {"group": m.group(1).upper()}
        else:
            hit = votes.add(_V["target"].find(t))
            if hit:
                key = hit[0]
                if key == "all":
                    tgt = {"all": True}
                else:
                    kind, val = key.split(":", 1)
                    tgt = {"group": {"face": "A", "lat": "B", "contre": "C"}[val]} if kind == "g" else {"kind": val}
            elif _hit("lights", t, votes):
                tgt = {"all": True}
    par = votes.add(_V["parity"].find(t))
    if par:
        tgt = tgt or {"all": True}
        tgt["parity"] = par[0]
    return tgt


def _target(t, votes):
    """Cible de la phrase : groupe, famille, numéros, pairs/impairs, avec « sauf … »."""
    exc = _hit("except", t, votes)
    if exc:
        excluded = _base_target(t[exc[2].end():], votes, bare_nums=True)
        tgt = _base_target(t[:exc[2].start()], votes) or {"all": True}
        if excluded:
            tgt["except"] = excluded
        return tgt
    return _base_target(t, votes)


def _fade(t, votes):
    """Durée du fondu en secondes, ou None (« progressivement », « en 10 secondes »)."""
    m = _DURATION_RE.search(t)
    if m:
        if m.group(1):
            return float(m.group(1))
        return 60.0 * (int(m.group(2)) if m.group(2) else 1)
    return float(FADE_DEFAULT_S) if _hit("fade", t, votes) else None


_N_WORDS = {"deux": 2, "two": 2, "dos": 2, "dois": 2, "zwei": 2, "trois": 3, "three": 3, "tres": 3, "drei": 3,
            "quatre": 4, "four": 4, "cuatro": 4, "quatro": 4, "vier": 4}


def _alternation(t, votes):
    """Période d'une alternance (« un sur deux » → 2, « un sur trois » → 3), 0 si aucune."""
    m = _ONE_IN_N_RE.search(t)
    if m:
        g = m.group(1)
        return int(g) if g.isdigit() else _N_WORDS.get(g, 2)
    return 2 if _hit("alternate", t, votes) else 0


def _level(t, votes):
    m = re.search(r"(\d{1,3})\s*(?:%|pour ?cent|percent|por ?ciento|por ?cento|prozent|パーセント)", t) or \
        re.search(r"(?<![a-z0-9])(?:a|at|to|al|auf|em|para|de)\s+(\d{1,3})(?![0-9.])", t)
    if m:
        return max(0, min(100, int(m.group(1))))
    if re.search(r"(?<![a-z])(?:a|at|to|al|auf|em|sur)\s+(?:zero|cero|null)(?![a-z])", t):
        return 0
    if _hit("full", t, votes):
        return 100
    if _hit("half", t, votes):
        return 50
    return None


def _pick_effect(effects, t, style, etype, color, lyre, alt=False):
    """Nom de l'effet le plus adapté, ou None. `alt` : « un sur deux » (strobe en alternance)."""
    shape = None
    if etype == "movement":
        lyre, etype = True, None
        shape = next((tok for tok, words in MOVE_SHAPES.items()
                      if any(_pattern(x).search(t) for x in words)), "cercle")
    def speed(e):
        layers = e.get("layers")
        if isinstance(layers, list) and layers:
            return max(int(l.get("speed", 50) or 0) for l in layers if isinstance(l, dict))
        return int(e.get("speed", 50) or 50)

    # 1. Nom d'effet cité tel quel (le plus long gagne). Un nom d'un seul mot
    #    court (« Feu ») n'est retenu qu'avec le mot « effet ».
    named = []
    for e in effects:
        n = normalize(e.get("name", ""))
        toks = n.split()
        if not toks:
            continue
        if all(re.search(rf"(?<![a-z0-9]){re.escape(x)}(?![a-z0-9])", t) for x in toks):
            if len(toks) > 1 or len(toks[0]) >= 5 or _W["effect"].find(t):
                named.append((len(n), e.get("name")))
    if named:
        return max(named)[1]

    pool = [e for e in effects if e.get("name")]
    if lyre:
        pool = [e for e in pool if e.get("category") == "Lyre"] or pool
        if shape:
            pool = [e for e in pool if shape in normalize(e.get("name", ""))] or pool
            if not style:       # « Lyre Cercle » plutôt que ses variantes (« Lyre Cercle Haché »)
                return min(pool, key=lambda e: len(e.get("name", "")))["name"]
    else:
        pool = [e for e in pool if e.get("category") not in ("Lyre", "Spécial")
                and "custom" not in normalize(e.get("name", ""))] or pool
    if etype:
        tok = _EFFECT_TYPE_TOKEN[etype]
        pool = [e for e in pool if tok in normalize(e.get("name", ""))
                or tok == normalize(e.get("type", ""))] or pool
    if alt:
        pool = [e for e in pool if "alternance" in normalize(e.get("name", ""))] or pool
    if color and color in COLOR_IN_EFFECT_NAMES:
        word = COLOR_IN_EFFECT_NAMES[color]
        pool = [e for e in pool if word in normalize(e.get("name", "")).split()] or pool
    if not pool:
        return None
    if style in ("fast", "slow"):
        # Le nom prime sur la vitesse réglée : un effet perso « Pulse Doux »
        # poussé à 100 n'est pas ce qu'on attend d'« un effet rapide ».
        def says(e, st):
            words = set(normalize(e.get("name", "")).split())
            return any(normalize(x) in words for by_lang in STYLE[st].values() for x in by_lang)
        other = "slow" if style == "fast" else "fast"
        pool = [e for e in pool if says(e, style)] or [e for e in pool if not says(e, other)] or pool
        if style == "fast":
            return max(pool, key=lambda e: (speed(e), "chase" in normalize(e.get("name", ""))))["name"]
        if not etype:     # « doux » : jamais un strobe, sauf s'il est demandé
            pool = [e for e in pool if e.get("type") not in ("Strobe", "Flash")] or pool
        return min(pool, key=speed)["name"]
    if not etype:
        pool = [e for e in pool if e.get("type") not in ("Strobe", "Flash")] or pool
    classic = [e for e in pool if "classique" in normalize(e.get("name", ""))]
    if classic:
        return classic[0]["name"]
    return min(pool, key=lambda e: abs(speed(e) - 50))["name"]


def _rec_generate(t, votes):
    """« programme les lumières sur cette musique » → génération IA du REC Lumière
    (couleur dite, « multicolore », sinon celle par défaut de la fenêtre)."""
    if not (_MUSIC_RE.search(t) and _PROG_RE.search(t)):
        return None
    if _W["effect"].find(t) or _W["memory"].find(t):
        return None
    colors = []
    for key, langs in _V["color"].find_all(t):
        votes.add((key, langs, None))
        if key not in colors:
            colors.append(key)
    if _RAINBOW_RE.search(t) or len(colors) >= 2:
        color = "rainbow"
    else:
        color = colors[0] if colors else None
    return {"do": "rec_generate", "color": color}


def _patch_add(t, votes):
    """« ajoute une lyre Shields », « patche-moi 4 PAR Betopper » → bibliothèque de
    fixtures ouverte sur cette recherche. Pas une couleur ni un effet à ajouter."""
    m = _PATCH_RE.search(t)
    etype = _V["etype"].find(t)
    if not m or _W["effect"].find(t) or (etype and etype[0] != "movement") or _V["color"].find(t):
        return None
    if re.search(r"(?<![a-z])(?:cree|creer|fabrique|profil|create)(?![a-z])", t):
        return None
    rest = t[m.end():]
    gear = _V["gear"].find(rest)
    patch_verb = m.group(0) in ("patche", "patcher", "patches")      # « le patch » est la fenêtre
    if not gear and not patch_verb and not _BRAND_RE.search(rest):
        return None
    if gear:
        votes.add(gear)
        rest = rest[:gear[2].start()] + " " + rest[gear[2].end():]
    qty = 1
    q = re.search(_NUM, rest)
    if q:
        n = int(q.group(1)) if q.group(1).isdigit() else _NUM_WORDS.get(q.group(1), 1)
        if 1 <= n <= 20 and not re.search(r"\d", rest[q.end():q.end() + 1] or ""):
            qty = n
            rest = rest[:q.start()] + " " + rest[q.end():]
    words = [x for x in re.split(r"[\s'’-]+", rest) if x and x not in _PATCH_FILLER and x not in _NUM_WORDS]
    if words and gear and gear[0] in ("par", "laser", "wash", "beam"):
        words.append(gear[0])       # « betopper par » : le type figure dans la fiche, il affine
    query = " ".join(words) or (gear[0] if gear and gear[0] != "generic" else "")
    return {"do": "patch_add", "query": query, "qty": qty}


def _topic(t, votes):
    """Sujet d'une question (« peut-on brancher une tablette ? ») ou d'un « branche … »."""
    hit = votes.add(_V["topic"].find(t))
    return hit[0] if hit else None


def _faders(t, votes, fade):
    """« monte progressivement les 4 faders », « fader 2 à 50 », « descends tous les faders »."""
    hit = _hit("fader", t, votes)
    if not hit:
        return None
    m = _FADER_NUM_RE.search(t)
    if m:
        nums = _nums(m.group(1))
    else:
        m = _N_FADERS_RE.search(t)        # « les 4 faders », « les quatre premiers faders »
        n = (int(m.group(1)) if m.group(1).isdigit() else _NUM_WORDS.get(m.group(1), 8)) if m else 8
        nums = list(range(1, min(9, n) + 1))
    nums = [n for n in nums if 1 <= n <= 9]
    level = _level(t, votes)
    if level is None:
        verb = _V["verb"].find(t)
        down = _hit("dimmer", t, votes) or (verb and verb[0] == "off")
        level = 0 if down else 100
    act = {"do": "fader", "faders": nums or list(range(1, 9)), "level": level}
    if fade:
        act["fade"] = fade
    return [act]


def _parse_clause(raw: str, t: str, effects, votes, question=False) -> list:
    # Apprendre / oublier : sur le texte brut, pour garder la phrase telle quelle.
    m = _LEARN_RE.match(raw)
    if m:
        return [{"do": "learn", "phrase": m.group(1).strip(), "command": m.group(2).strip()}]
    m = _FORGET_RE.match(raw)
    if m:
        return [{"do": "forget", "phrase": m.group(1).strip()}]

    # Panne (« pourquoi ça bug », « mes projos s'allument pas ») : diagnostic. Avec
    # un ordre de reconnexion (« … ne répond plus, relance-le »), on reconnecte.
    if _hit("trouble", t, votes) and not _hit("connect", t, votes) and not re.search(r"(?<![a-z])relance", t):
        return [{"do": "diagnose"}]

    # Question sur un branchement : on répond (et on ouvre la bonne fenêtre si
    # c'est la tablette) au lieu d'agir sur un mot-clé.
    if question:
        topic = _topic(t, votes)
        if topic:
            acts = [{"do": "answer", "topic": topic}]
            if topic == "tablet":
                acts.append({"do": "open", "window": "tablet"})
            return acts

    rec = _rec_generate(t, votes)
    if rec:
        return [rec]
    if _CHAT_RE.match(t.strip()):
        return [{"do": "chat"}]
    if _STATE_RE.search(t) and not _V["verb"].find(t) and not _W["open"].find(t):
        return [{"do": "chat"}]
    if _LIVE_RE.search(t):
        if question:
            return [{"do": "answer", "topic": "live"}, {"do": "live", "on": True}]
        return [{"do": "live", "on": not _LIVE_OFF_RE.search(t)}]
    if _GOBO_RE.search(t):
        tgt = _target(t, votes)
        return [{"do": "gobo", "open": bool(_GOBO_OPEN_RE.search(t)), "target": tgt or {"all": True}}]
    if _GRADIENT_RE.search(t):
        cols = []
        for key, langs in _V["color"].find_all(t):
            votes.add((key, langs, None))
            if key not in cols:
                cols.append(key)
        if _RAINBOW_RE.search(t) or len(cols) < 2 and re.search(r"toutes les couleurs|all colou?rs|todos los colores", t):
            cols = cols[:1] + [c for c in RAINBOW_COLORS if c not in cols[:1]] if len(cols) == 1 else RAINBOW_COLORS
        if len(cols) >= 2:
            return [{"do": "gradient", "colors": cols, "target": _target(t, votes) or {"all": True},
                     "level": _level(t, votes)}]
    patch = _patch_add(t, votes)
    if patch:
        return [patch]

    if _hit("help", t, votes):
        return [{"do": "help"}]
    if _hit("status", t, votes) and not _V["target"].find(t):     # « état-celles » = étincelles
        return [{"do": "status"}]
    if _hit("fixture", t, votes) and (_hit("create", t, votes) or len(t.split()) <= 2):
        return [{"do": "fixture"}]
    if _hit("connect", t, votes):
        # « branche la tablette » ouvre la tablette ; « connecte le boîtier » la sortie DMX.
        topic = _topic(t, votes)
        if topic == "tablet":
            return [{"do": "open", "window": "tablet"}]
        if topic == "controller":
            return [{"do": "open", "window": "akai"}]
        w = _V["window"].find(t)
        if w and w[0] in ("obs", "vmix", "gamepad"):
            votes.add(w)
            return [{"do": "open", "window": w[0]}]
        return [{"do": "connect"}]

    fd = _faders(_DURATION_RE.sub(" ", t), votes, _fade(t, votes))
    if fd:
        return fd
    if _hit("save", t, votes):
        return [{"do": "save"}]
    if _hit("open", t, votes):
        w = votes.add(_V["window"].find(t))
        if w:
            return [{"do": "open", "window": w[0]}]

    # Mémoire 2.3
    mem_hit = _hit("memory", t, votes)
    if mem_hit:
        m = _MEM_RE.search(t, mem_hit[2].end())
        if m:
            a, b = (int(x) if x.isdigit() else _NUM_WORDS[x] for x in m.groups())
            if 1 <= a <= 8 and 1 <= b <= 8:
                return [{"do": "memory", "id": f"{a}.{b}"}]

    # Le fondu (« en 10 secondes ») est retiré avant de chercher le niveau ou la vitesse.
    fade = _fade(t, votes)
    t = _DURATION_RE.sub(" ", t)
    target = _target(t, votes)
    color_hit = votes.add(_V["color"].find(t))
    color = color_hit[0] if color_hit else None
    style_hit = votes.add(_V["style"].find(t))
    etype_hit = votes.add(_V["etype"].find(t))
    effect_word = _hit("effect", t, votes)
    speed_word = _hit("speed", t, votes)
    faster, slower = _hit("faster", t, votes), _hit("slower", t, votes)
    verb = votes.add(_V["verb"].find(t))

    # Alternance : « un projecteur sur deux en rouge, l'autre en violet »,
    # « alterne rouge et bleu », « éteins un projecteur sur trois ».
    period = 0 if (effect_word or etype_hit) else _alternation(t, votes)
    if period:
        colors = []
        for key, langs in _V["color"].find_all(t):
            votes.add((key, langs, None))
            if key not in colors:
                colors.append(key)
        if colors:
            slots = [{"hex": COLOR_HEX[c], "color": c} for c in colors]
        elif verb and verb[0] == "off":
            slots = [{"level": 0}]
        else:
            slots = [{"hex": COLOR_HEX["white"], "color": "white"}]
        slots += [None] * (max(period, len(slots)) - len(slots))
        act = {"do": "pattern", "slots": slots, "target": target or {"all": True}, "level": _level(t, votes)}
        if fade:
            act["fade"] = fade
        return [act]
    theme = None if (effect_word or etype_hit) else votes.add(_V["theme"].find(t))
    if theme:
        act = {"do": "pattern", "slots": [{"hex": COLOR_HEX[c], "color": c} for c in THEME_COLORS[theme[0]]],
               "target": target or {"all": True}, "level": _level(t, votes)}
        if fade:
            act["fade"] = fade
        return [act]
    if fade and not (effect_word or etype_hit):
        # « doucement », « langsam » disent ici le fondu, pas un effet lent.
        style_hit = None

    # Vitesse : « vitesse 80 », « plus vite », « ralentis »
    if speed_word:
        m = re.search(r"(\d{1,3})", t)
        if m:
            return [{"do": "speed", "value": max(0, min(100, int(m.group(1))))}]
    if (faster or slower) and not etype_hit and not effect_word:
        return [{"do": "speed_rel", "delta": 20 if faster else -20}]
    if speed_word and (_hit("brighter", t, votes) or _hit("dimmer", t, votes)):
        return [{"do": "speed_rel", "delta": 20 if _W["brighter"].find(t) else -20}]

    # Arrêt des effets (« stop », « arrête l'effet ») — « stop » seul ne fait pas le noir.
    if _hit("stop", t, votes) and not color_hit:
        return [{"do": "stop_effects"}]

    # Lecture
    pb = votes.add(_V["playback"].find(t))
    if pb and not (color_hit or etype_hit or effect_word):
        return [{"do": "playback", "what": pb[0]}]

    # Effet
    if effect_word or etype_hit or (style_hit and not color_hit and not target):
        style = style_hit[0] if style_hit else None
        lyre = bool(target and target.get("kind") == "lyre")
        alt = bool(_ONE_IN_N_RE.search(t) or _W["alternate"].find(t) or _V["parity"].find(t))
        name = _pick_effect(effects, t, style, etype_hit[0] if etype_hit else None, color, lyre, alt)
        if name:
            act = {"do": "effect", "name": name}
            if style == "fast":
                act["speed"] = 85
            elif style == "slow":
                act["speed"] = 25
            return [act]
        return [{"do": "no_effect"}]
    # Nom d'effet cité sans le mot « effet » (« lance Police », « Rainbow »)
    name = _pick_effect(effects, t, None, None, None, False) if effects else None
    if name and normalize(name) in t and not color_hit:
        return [{"do": "effect", "name": name}]

    level = _level(t, votes)
    off = verb and verb[0] == "off"
    acts = _light_clause(t, votes, target, color, level, verb, off)
    if fade and not acts and (target or _hit("fade", t, votes)):
        # « fade in the lights », « ausblenden » : sans verbe, le sens du fondu suffit.
        out = re.search(r"fade out|ausblenden|fundido a negro|en fondu au noir", t)
        acts = [{"do": "level", "target": target or {"all": True}, "level": 0 if out else 100}]
    if fade:
        for a in acts:
            if a["do"] == "blackout":       # noir en fondu = tout descendre à 0
                a.clear()
                a.update({"do": "level", "target": {"all": True}, "level": 0})
            if a["do"] in ("color", "level", "level_rel"):
                a["fade"] = fade
    return acts or [{"do": "unknown", "text": raw}]


def _light_clause(t, votes, target, color, level, verb, off) -> list:
    whole = not target or (target.get("all") and len(target) == 1)
    if _hit("blackout", t, votes):
        # « noir » seul : noir général ; « la face en noir » : cette cible à 0 (pas allumée en blanc).
        if whole:
            return [{"do": "blackout"}]
        if not color:
            return [{"do": "level", "target": target, "level": 0}]
    if off:
        return [{"do": "blackout"}] if whole else [{"do": "level", "target": target, "level": 0}]
    if color:
        return [{"do": "color", "hex": COLOR_HEX[color], "color": color,
                 "target": target or {"all": True}, "level": 100 if level is None else level}]
    if level is not None:
        return [{"do": "level", "target": target or {"all": True}, "level": level}]
    if _hit("brighter", t, votes):
        return [{"do": "level_rel", "target": target or {"all": True}, "delta": 20}]
    if _hit("dimmer", t, votes):
        return [{"do": "level_rel", "target": target or {"all": True}, "delta": -20}]
    if verb and verb[0] == "on":
        return [{"do": "color", "hex": COLOR_HEX["white"], "color": "white",
                 "target": target or {"all": True}, "level": 100}]
    return []


_QUESTION_RE = re.compile(
    r"^(?:est ce que|est ce qu|peut on|peux ton|peut ton|on peut|comment|pourquoi|c est quoi|qu est ce|"
    r"how|what|why|can i|can we|can you|is it|is there|does|do i|"
    r"como|que es|por que|se puede|puedo|hay|kann man|kann ich|wie|was ist|warum|gibt es|"
    r"posso|pode se|o que|porque|da para)(?![a-z])")


# Questions qui demandent une explication (« comment je fais pour… ») : jamais
# d'action, même si la phrase contient un ordre (« mettre mes lyres en mouvement »).
_HOW_RE = re.compile(r"^(?:comment|pourquoi|c est quoi|qu est ce|how|why|what|como|por que|que es|wie|warum|"
                     r"was ist|o que|porque)(?![a-z])")


def _is_question(text: str) -> bool:
    return (text or "").strip().endswith(("?", "？", "か")) or bool(_QUESTION_RE.match(normalize(text)))


def _merge_alternation(parts: list) -> list:
    """Recolle les morceaux d'une alternance que le découpage sur « et » a séparés :
    « un sur deux en rouge » + « l'autre en violet », « rouge » + « bleu en alternance »."""
    def alt(t):
        return bool(_ONE_IN_N_RE.search(t) or _W["alternate"].find(t))

    def colors_only(t):
        return bool(_V["color"].find(t)) and (bool(_W["other"].find(t)) or len(t.split()) <= 3) \
            and not (_W["effect"].find(t) or _V["etype"].find(t))

    out = []
    for raw in parts:
        if raw is None:
            continue
        t = normalize(raw)
        if out:
            prev = normalize(out[-1])
            if (alt(prev) and colors_only(t)) or (alt(t) and colors_only(prev) and not alt(prev)):
                out[-1] = out[-1] + " , " + raw
                continue
        out.append(raw)
    return out


_GRADIENT_RE = re.compile(r"(?<![a-z])(?:degrade|degrades|degrader|gradient|gradation|degradado|farbverlauf|"
                          r"verlauf)(?![a-z])")
_GOBO_RE = re.compile(r"(?<![a-z])gobos?(?![a-z])")
_GOBO_OPEN_RE = re.compile(r"(?<![a-z])(?:enleve|enlever|retire|retirer|sans|ouvert|open|no|quita|sin|ohne|tira|sem)(?![a-z])")
# Mode LIVE : les lumières suivent le son (carte son, micro).
_LIVE_RE = re.compile(r"(?<![a-z])(?:mode live|le live|live mode|modo live|live modus|modo ao vivo|reagi\w* au son|reagi\w* a la musique|suis la musique|suivre la musique|"
                      r"au rythme de la musique|au son de|carte son|sound to light|follow the music|react\w* to (?:the )?(?:music|sound)|"
                      r"al ritmo de la musica|carta de sonido|tarjeta de sonido|auf die musik|soundkarte|"
                      r"ao ritmo da musica|placa de som)(?![a-z])")
_LIVE_OFF_RE = re.compile(r"(?<![a-z])(?:arrete|quitte|sors|coupe|stop|desactive|exit|leave|turn off|para|sal|beende|sai)(?![a-z])")
# Discussion sans demande (« ouais pas mal », « parfait », « merci ») : rien à faire.
_CHAT_WORDS = ("ouais oui ok okay d accord parfait super genial top cool pas mal trop bien merci nickel bien tres "
               "excellent c est bon ah oh bah euh hum voila ca marche ca roule nice great thanks thank you perfect "
               "good awesome gracias perfecto genial vale danke prima perfekt obrigado perfeito otimo bom "
               "c est parti let s go allez yes yeah wow bravo impeccable magnifique").split()
_CHAT_RE = re.compile(r"^(?:(?:" + "|".join(sorted(set(_CHAT_WORDS), key=len, reverse=True)) + r")(?![a-z])[\s,!.]*)+$")
# « ils sont encore en blanc », « c'est tout rouge » : on décrit, on ne demande rien.
_STATE_RE = re.compile(r"(?<![a-z])(?:ils|elles|il|elle|ca|c|ce|tout|they|it|its|it s|ellos|sie|es|eles)\s+"
                       r"(?:sont|est|restent|reste|etaient|etait|are|is|were|was|estan|esta|sind|ist|sao|estao)(?![a-z])")
RAINBOW_COLORS = ["red", "orange", "yellow", "green", "cyan", "blue", "purple"]

# Ambiance tamisée / feutrée / cosy : lumière basse, blanc chaud sauf couleur dite.
_DIM_RE = re.compile(r"(?<![a-z])(?:tamise|tamisee|tamisees|tamises|feutre|feutree|cosy|cozy|cocooning|intime|"
                     r"dimmed|subdued|acogedor|acogedora|gedimmt|gemutlich|aconchegante|intimo|intima)(?![a-z])")
DIM_LEVEL = 40
_MOOD_RE = re.compile(r"(?<![a-z])(?:ambiance|ambiances|atmosphere|mood|vibe|ambiente|stimmung|clima)(?![a-z])")
# « une ambiance chaude » : alternance orange / ambre / rouge ; « blanc chaud » dit reste du blanc chaud.
WARM_MOOD = ["orange", "amber", "red"]
_WARM_WORD_RE = re.compile(r"(?<![a-z])(?:chaleureuse|chaleureux|chaleureuses|chaleureux|calurosa|caluroso|"
                           r"acolhedora|acolhedor)(?![a-z])")
_WARM_WHITE_RE = re.compile(r"(?<![a-z])(?:blanc chaud|blancs chauds|warm white|blanco calido|warmweiss|branco quente)(?![a-z])")


def warm_mood(t: str) -> bool:
    """Ambiance chaude demandée sans autre couleur ni blanc chaud explicite (t normalisé)."""
    if _DIM_RE.search(t) or _WARM_WHITE_RE.search(t) or _V["theme"].find(t):
        return False
    cols = {k for k, _ in _V["color"].find_all(t)}
    if _WARM_WORD_RE.search(t):
        return not cols - {"warm"}
    return cols == {"warm"} and bool(_MOOD_RE.search(t))


# ── Suite de conversation ────────────────────────────────────────────────────
# « non, … » : correction de la demande précédente. Jamais un ordre en soi : le
# modèle lisait « non » comme « stop » et coupait les effets.
_CORRECTION_RE = re.compile(r"^\s*(?:(?:mais|ah|oh|euh)\s+)?(?:non|nan|no|nope|nein|nao)(?![a-z])[\s,!.]*")
# « je parlais de l'effet » : précision sans ordre.
_MEANT_RE = re.compile(r"^(?:je parlais|je parle|je voulais dire|je veux dire|i meant|i mean|i was talking|"
                       r"me referia|hablaba|ich meinte|eu queria dizer|falava)(?![a-z])")
# « pas blanc chaud » : couleur refusée, retirée avant d'analyser la phrase.
_NEG_RE = re.compile(r"(?<![a-z])(?:pas|sans|not|sin|nicht|kein|sem)\s+(?:de |du |en |le |la |un |une |the |a )?"
                     r"([a-z]+(?: [a-z]+)?)")
# Pronom qui reprend ce qu'on vient de faire : « baisse-les », « remets-le », « coupe ça ».
_PRONOUN_RE = re.compile(
    r"(?<![a-z])(baisse|baisser|descends|redescends|monte|remonte|pousse|remets|remet|mets|met|coupe|eteins|"
    r"eteint|rallume|allume|lower|raise|dim|bring)[\s-]+(les|le|la|ca|them|it|those)(?![a-z])"
    # Pronom seulement s'il n'est pas suivi d'un nom (« mets les étincelles à fond » n'en est pas un).
    r"(?=\s*(?:$|[,.!?]|a |au |en |doucement|progressivement|lentement|tranquillement|mais|plus|moins|un peu|"
    r"\d|tout de suite|stp|s il|down|up|slowly|again|please))")
_RELAUNCH_RE = re.compile(r"(?<![a-z])(?:remets|remet|relance|relancer|rallume|reprends|remettre|restart|relaunch|"
                          r"again)(?![a-z])")
_ALL_SCOPE_RE = re.compile(r"(?<![a-z])(?:tous les (?:projos|projecteurs|groupes|appareils)|toutes les lumieres|"
                           r"sur tout|partout|all (?:the )?(?:lights|fixtures|groups)|everywhere|todos los|alle)(?![a-z])")
_UP_RE = re.compile(r"(?<![a-z])(?:monte|remonte|pousse|rallume|allume|remets|remet|raise|bring)(?![a-z])")
_OFF_RE = re.compile(r"(?<![a-z])(?:coupe|eteins|eteint)(?![a-z])")


_YES_RE = re.compile(r"^(?:oui|ouais|ok|okay|vas y|go|d accord|yes|yep|sure|si|vale|claro|ja|klar|sim|pode|はい|お願い)"
                     r"(?![a-z])[\s,!.]*(?:vas y|go|ouvre|ouvre le|oui|stp|merci|please|bitte)?[\s,!.]*$")
_NO_RE = re.compile(r"^(?:non|nan|no|nope|nein|nao|いいえ|laisse tomber|annule|cancel|pas maintenant)(?![a-z])[\s,!.]*"
                    r"(?:merci|thanks|danke|obrigado|gracias)?[\s,!.]*$")


def yes_no(text: str):
    """Réponse à une question Oui / Non de l'assistant : True, False, ou None (autre chose)."""
    t = _WAKE_RE.sub("", normalize(text)).strip()
    if _YES_RE.match(t):
        return True
    if _NO_RE.match(t):
        return False
    return None


def followup(text: str, last: dict):
    """Lit une phrase qui dépend de la précédente. `last` : dernière action exécutée,
    {"kind": "fader"|"target"|"effect", …} (cf. AssistantExecutor). Rend
    (actions, texte) : des actions déjà résolues, ou None et le texte nettoyé (sans
    « non, », sans la couleur refusée) à analyser normalement."""
    raw = text or ""
    t = normalize(raw)
    m = _CORRECTION_RE.match(t)
    correction = bool(m)
    if m:
        t = t[m.end():]
        raw = re.sub(r"^\s*(?:(?:mais|ah|oh|euh)\s+)?(?:non|nan|no|nope|nein|não|nao)\b[\s,!.]*", "", raw,
                     flags=re.IGNORECASE)
    last = last or {}
    votes = _Votes()

    if _MEANT_RE.match(t) or (correction and not t.strip()):
        about = "effect" if _W["effect"].find(t) else last.get("kind") or "generic"
        return [{"do": "clarify", "about": about}], raw

    # « remets les effets », « relance l'effet (sur tous les groupes) » : le dernier effet lancé.
    if last.get("effect") and _RELAUNCH_RE.search(t) and (_W["effect"].find(t) or _PRONOUN_RE.search(t)):
        return [{"do": "effect", "name": last["effect"], "all": bool(_ALL_SCOPE_RE.search(t))}], raw
    # « que ça prenne sur tous les projos » juste après un effet.
    if (last.get("kind") == "effect" and _ALL_SCOPE_RE.search(t) and not _V["color"].find(t)
            and re.search(r"(?<![a-z])(?:ca|le|l effet|it|that)(?![a-z])", t)):
        return [{"do": "effect", "name": last["effect"], "all": True}], raw

    pm = _PRONOUN_RE.search(t)
    if pm and last.get("kind") in ("fader", "target"):
        fade = _fade(t, votes)
        color = votes.add(_V["color"].find(t))
        if color:       # « mets-les en rouge » : une couleur ne va qu'à des projecteurs
            if last["kind"] != "target":
                return None, raw
            act = {"do": "color", "hex": COLOR_HEX[color[0]], "color": color[0], "target": last["target"],
                   "level": _level(t, votes) or 100}
            if fade:
                act["fade"] = fade
            return [act], raw
        level = _level(_DURATION_RE.sub(" ", t), votes)
        if _OFF_RE.search(pm.group(1)):
            level = 0
        elif level is None and last["kind"] == "target" and pm.group(1) in ("allume", "rallume"):
            level = 100
        if level is None and pm.group(1) in ("mets", "met"):
            return None, raw            # « mets-les » sans niveau ni couleur : rien de sûr
        delta = None if level is not None else (20 if _UP_RE.search(pm.group(1)) else -20)
        if last["kind"] == "fader":
            act = ({"do": "fader", "faders": last["faders"], "level": level} if delta is None
                   else {"do": "fader_rel", "faders": last["faders"], "delta": delta})
        else:
            act = ({"do": "level", "target": last["target"], "level": level} if delta is None
                   else {"do": "level_rel", "target": last["target"], "delta": delta})
        if fade:
            act["fade"] = fade
        return [act], raw

    # Couleurs refusées (« pas blanc chaud ») : la négation et tous les mots de cette
    # couleur (« … type chaude rouge et blanc ») sont retirés de la phrase.
    refused = set()
    for nm in list(_NEG_RE.finditer(t)):
        hit = _V["color"].find(nm.group(1))
        if hit:
            refused.add(hit[0])
            t = t.replace(nm.group(0), " ")
    if not refused:
        return None, raw.strip(" ,")
    for key, _langs, word, pat in _V["color"].entries:
        if key in refused:
            t = pat.sub(" ", t)
    return None, re.sub(r"\s+", " ", t).strip(" ,")


# « Ok MyStrow, … » : l'appel n'est pas une demande (découpé à la virgule, il
# répondait « je n'ai pas compris « Ok MyStrow » »).
_WAKE_RE = re.compile(r"^\s*(?:(?:ok|okay|hey|he|hé|eh|dis|salut|bonjour|hola|hallo|ola|olá)[\s,!.]*)?"
                      r"my\s?strow\b[\s,!.:]*", re.IGNORECASE)


def parse(text: str, effects=(), default_lang: str = "fr", aliases: dict = None) -> Parsed:
    """Analyse une demande. `aliases` : {phrase normalisée: commande} appris."""
    stripped = _WAKE_RE.sub("", text or "")
    if stripped != (text or "") and not stripped.strip():
        return Parsed(default_lang, [{"do": "help"}])        # « Ok MyStrow » seul : ce que je sais faire
    text = stripped
    aliases = aliases or {}
    votes = _Votes()
    t_all = normalize(text)
    if t_all in aliases:
        return parse(aliases[t_all], effects, default_lang, None)

    # Apprendre / oublier : la phrase entière, sans découpage en propositions.
    if _LEARN_RE.match(text or "") or _FORGET_RE.match(text or ""):
        return Parsed(default_lang, _parse_clause(text, t_all, effects, votes))

    # Panne + demande de relance sur toute la phrase (« le boîtier ne marche plus, relance-le ») :
    # reconnexion, sans découper à la virgule.
    if _W["trouble"].find(t_all) and (_W["connect"].find(t_all) or re.search(r"(?<![a-z])(?:relance|redemarre)", t_all)):
        votes.add(_W["trouble"].find(t_all))
        return Parsed(votes.lang(default_lang), [{"do": "connect"}])

    if _GRADIENT_RE.search(t_all):
        acts = _parse_clause(text, t_all, effects, votes)
        if acts and acts[0]["do"] == "gradient":
            return Parsed(votes.lang(default_lang), acts)
    # « une ambiance rouge et blanc » : plusieurs couleurs pour une seule ambiance → alternance.
    if _MOOD_RE.search(t_all) and not _V["theme"].find(t_all):
        cols = []
        for key, langs in _V["color"].find_all(t_all):
            votes.add((key, langs, None))
            if key not in cols:
                cols.append(key)
        if len(cols) >= 2:
            return Parsed(votes.lang(default_lang), [{"do": "pattern", "target": _target(t_all, votes) or {"all": True},
                                                      "level": None,
                                                      "slots": [{"hex": COLOR_HEX[c], "color": c} for c in cols]}])

    if warm_mood(t_all) and not _is_question(text):
        return Parsed(votes.lang(default_lang), [{"do": "pattern", "target": _target(t_all, votes) or {"all": True},
                                                  "level": None,
                                                  "slots": [{"hex": COLOR_HEX[c], "color": c} for c in WARM_MOOD]}])

    # « une ambiance tamisée » : pas un effet, une lumière basse et chaude.
    if _DIM_RE.search(t_all) and not _V["theme"].find(t_all) and not _is_question(text):
        hit = votes.add(_V["color"].find(t_all))
        color = hit[0] if hit else "warm"
        return Parsed(votes.lang(default_lang), [{"do": "color", "hex": COLOR_HEX[color], "color": color,
                                                  "target": _target(t_all, votes) or {"all": True},
                                                  "level": DIM_LEVEL}])

    question = _is_question(text)
    if question:
        # Une question porte sur toute la phrase : son sujet n'est pas découpé.
        acts = _parse_clause(text, t_all, effects, votes, question=True)
        if acts and acts[0]["do"] in ("answer", "diagnose"):
            return Parsed(votes.lang(default_lang), acts)

    actions = []
    for raw in _merge_alternation(_SPLIT_RE.split(text or "")):
        t = normalize(raw)
        if not t:
            continue
        if t in aliases:
            actions.extend(parse(aliases[t], effects, default_lang, None).actions)
            continue
        actions.extend(_parse_clause(raw, t, effects, votes))
    if any(a["do"] not in ("chat", "unknown") for a in actions):
        # « Ok, escu, mets les étincelles à fond » : les bouts de bavardage autour d'une
        # vraie demande ne valent ni réponse ni « je n'ai pas compris ». Plus largement, en dictée, le reste n'est que de la conversation autour de l'ordre.
        actions = [a for a in actions if a["do"] not in ("chat", "unknown")]
    if question and (not actions or any(a["do"] == "unknown" for a in actions) or _HOW_RE.match(t_all)):
        # « c'est quoi un gobo ? » : pas de réponse toute faite, on le dit simplement.
        return Parsed(votes.lang(default_lang), [{"do": "answer", "topic": "generic", "text": text}])
    return Parsed(votes.lang(default_lang), actions or [{"do": "unknown", "text": text}])
