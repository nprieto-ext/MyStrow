"""
assistant_panel.py — L'assistant intégré, onglet à côté du Journal.

On lui écrit ou on lui parle (bouton micro, maintenir pour parler) :
« allume mes projecteurs en rouge », « envoie un effet rapide », « ouvre le
patch », « connecte le boîtier », « crée ma fixture »… Tout est local :
compréhension par assistant_nlu, voix par assistant_voice, exécution par
light_actions et les méthodes de la fenêtre principale.

Il répond dans la langue de la phrase. On peut lui apprendre des tournures
(« apprends ambiance club = mémoire 2.1 ») ; les phrases non comprises sont
gardées dans ~/.mystrow_assistant.json pour enrichir le vocabulaire.
"""

import html
import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal, QThread, QEvent
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QStackedWidget, QTextBrowser,
    QLineEdit, QLabel, QLayout,
)

from i18n import tr, get_language
import assistant_nlu as nlu
import light_actions as la

STORE_FILE = Path.home() / ".mystrow_assistant.json"
_MAX_UNKNOWN = 200
_MAX_HISTORY = 500


# ── Mémoire de l'assistant (tournures apprises, phrases non comprises) ───────

class AssistantStore:
    def __init__(self, path: Path = None):
        self.path = path = path or STORE_FILE
        self.data = {"aliases": {}, "unknown": [], "history": [], "tab": "log"}
        try:
            if path.exists():
                d = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(d, dict):
                    self.data.update(d)
        except Exception:
            pass

    def save(self):
        try:
            self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            print(f"[Assistant] enregistrement impossible : {exc}")

    @property
    def aliases(self) -> dict:
        return self.data["aliases"]

    def learn(self, phrase: str, command: str):
        self.aliases[nlu.normalize(phrase)] = command
        self.save()

    def forget(self, phrase: str) -> bool:
        found = self.aliases.pop(nlu.normalize(phrase), None) is not None
        self.save()
        return found

    def note(self, text: str, lang: str, actions: list, replies: list, source: str = "rules"):
        """Historique de toutes les demandes : ce qui a été dit, compris (par les
        règles ou le modèle local) et répondu. C'est la matière pour améliorer le
        vocabulaire (ce qui a été mal compris n'apparaît pas dans « unknown »)."""
        lst = self.data.setdefault("history", [])
        lst.append({"t": text, "ts": int(time.time()), "lang": lang, "src": source, "did": actions, "r": replies})
        del lst[:-_MAX_HISTORY]
        self.save()

    def note_unknown(self, text: str):
        lst = self.data["unknown"]
        lst.append({"t": text, "ts": int(time.time())})
        del lst[:-_MAX_UNKNOWN]
        self.save()


# ── Réponses, dans la langue de la phrase ────────────────────────────────────

R = {
    "color":   {"fr": "✓ {n} projecteur(s) en {c} à {l} %", "en": "✓ {n} fixture(s) {c} at {l} %",
                "es": "✓ {n} foco(s) en {c} al {l} %", "de": "✓ {n} Scheinwerfer {c} auf {l} %",
                "pt": "✓ {n} projetor(es) em {c} a {l} %", "ja": "✓ {n} 台を{c}・{l}% にしました"},
    "diag_license": {"fr": "🔒 Ta licence ne permet pas la sortie DMX (essai fini ou licence expirée) : les projecteurs ne reçoivent rien.",
                     "en": "🔒 Your licence doesn't allow DMX output (trial over or licence expired): the fixtures receive nothing.",
                     "es": "🔒 Tu licencia no permite la salida DMX (prueba terminada o licencia caducada): los focos no reciben nada.",
                     "de": "🔒 Deine Lizenz erlaubt keinen DMX-Ausgang (Test vorbei oder Lizenz abgelaufen): die Scheinwerfer bekommen nichts.",
                     "pt": "🔒 A sua licença não permite a saída DMX (teste terminado ou licença expirada): os projetores não recebem nada.",
                     "ja": "🔒 ライセンスでDMX出力が許可されていません（試用終了または期限切れ）。機材には何も届きません。"},
    "diag_dmx": {"fr": "🔌 La sortie DMX n'est pas connectée : c'est sûrement ça. Dis « connecte le boîtier » ou vérifie le câble USB / réseau.",
                 "en": "🔌 The DMX output isn't connected: that's probably it. Say “connect” or check the USB / network cable.",
                 "es": "🔌 La salida DMX no está conectada: seguramente es eso. Di «conecta» o revisa el cable USB / red.",
                 "de": "🔌 Der DMX-Ausgang ist nicht verbunden: das ist es wohl. Sag „verbinde“ oder prüfe das USB- / Netzwerkkabel.",
                 "pt": "🔌 A saída DMX não está ligada: deve ser isso. Diga «conecta» ou verifique o cabo USB / rede.",
                 "ja": "🔌 DMX出力が接続されていません。原因はおそらくこれです。「接続」と言うか、USB／ネットワークケーブルを確認してください。"},
    "diag_disabled": {"fr": "⏸ L'envoi DMX est désactivé (bouton DMX du plan de feu) : réactive-le.",
                      "en": "⏸ DMX sending is turned off (DMX button on the stage plot): turn it back on.",
                      "es": "⏸ El envío DMX está desactivado (botón DMX del plano): actívalo.",
                      "de": "⏸ DMX-Senden ist aus (DMX-Taste im Bühnenplan): wieder einschalten.",
                      "pt": "⏸ O envio DMX está desligado (botão DMX do plano): volte a ligá-lo.",
                      "ja": "⏸ DMX送信がオフです（ステージプランのDMXボタン）。オンにしてください。"},
    "diag_patch": {"fr": "📋 Ton patch est vide : ajoute tes projecteurs (dis « ouvre le patch »).",
                   "en": "📋 Your patch is empty: add your fixtures (say “open the patch”).",
                   "es": "📋 Tu patch está vacío: añade tus focos (di «abre el patch»).",
                   "de": "📋 Dein Patch ist leer: füge deine Scheinwerfer hinzu („öffne den Patch“).",
                   "pt": "📋 O seu patch está vazio: adicione os projetores (diga «abre o patch»).",
                   "ja": "📋 パッチが空です。機材を追加してください（「パッチを開いて」）。"},
    "diag_blackout": {"fr": "⚫ Le blackout est enclenché (bouton noir) : désactive-le pour rallumer.",
                      "en": "⚫ Blackout is on (blackout button): turn it off to bring the lights back.",
                      "es": "⚫ El apagón está activado (botón blackout): desactívalo.",
                      "de": "⚫ Blackout ist aktiv (Blackout-Taste): ausschalten.",
                      "pt": "⚫ O blackout está ativo (botão blackout): desative-o.",
                      "ja": "⚫ ブラックアウトが有効です。解除してください。"},
    "diag_master": {"fr": "🎚 Le master est à 0 : rien ne sort, même si les projecteurs sont allumés. Remonte-le.",
                    "en": "🎚 The master is at 0: nothing goes out even if fixtures are on. Bring it up.",
                    "es": "🎚 El master está a 0: no sale nada aunque los focos estén encendidos. Súbelo.",
                    "de": "🎚 Der Master steht auf 0: es kommt nichts raus. Hochziehen.",
                    "pt": "🎚 O master está a 0: não sai nada mesmo com os projetores ligados. Suba-o.",
                    "ja": "🎚 マスターが0です。上げてください。"},
    "diag_levels": {"fr": "💡 Tous les projecteurs sont à 0 % : dis par exemple « allume tout » ou monte les faders.",
                    "en": "💡 All fixtures are at 0 %: say “turn everything on” or push the faders up.",
                    "es": "💡 Todos los focos están al 0 %: di «enciende todo» o sube los faders.",
                    "de": "💡 Alle Scheinwerfer stehen auf 0 %: sag „alles an“ oder zieh die Fader hoch.",
                    "pt": "💡 Todos os projetores estão a 0 %: diga «acende tudo» ou suba os faders.",
                    "ja": "💡 全機材が0%です。「全部つけて」と言うかフェーダーを上げてください。"},
    "diag_ok": {"fr": "✓ Côté MyStrow tout va bien : sortie DMX connectée, {n} projecteur(s) patché(s), lumière envoyée. Si un projecteur ne réagit pas, vérifie : 1) son adresse DMX = celle du patch, 2) son mode (nombre de canaux) = celui du patch, 3) qu'il est en mode DMX (pas auto / son), 4) le câble DMX et le bouchon en bout de ligne. Dis « ouvre le testeur DMX » pour tester canal par canal.",
                "en": "✓ MyStrow looks fine: DMX output connected, {n} fixture(s) patched, light being sent. If a fixture doesn't react, check: 1) its DMX address = the patch, 2) its mode (channel count) = the patch, 3) it's in DMX mode (not auto / sound), 4) the DMX cable and terminator. Say “open the DMX tester” to test channel by channel.",
                "es": "✓ En MyStrow todo bien: salida DMX conectada, {n} foco(s) en el patch, luz enviada. Si un foco no reacciona, revisa: 1) su dirección DMX = la del patch, 2) su modo (n.º de canales) = el del patch, 3) que esté en modo DMX, 4) el cable DMX y el terminador. Di «abre el probador DMX».",
                "de": "✓ In MyStrow ist alles ok: DMX verbunden, {n} Scheinwerfer gepatcht, Licht wird gesendet. Reagiert ein Gerät nicht: 1) DMX-Adresse = Patch, 2) Modus (Kanalzahl) = Patch, 3) DMX-Modus (nicht Auto/Sound), 4) DMX-Kabel und Abschlusswiderstand prüfen. „Öffne den DMX-Tester“ zum Testen.",
                "pt": "✓ No MyStrow está tudo bem: saída DMX ligada, {n} projetor(es) no patch, luz enviada. Se um projetor não reage, verifique: 1) o endereço DMX = o do patch, 2) o modo (n.º de canais) = o do patch, 3) que está em modo DMX, 4) o cabo DMX e o terminador. Diga «abre o testador DMX».",
                "ja": "✓ MyStrow側は正常です（DMX接続、{n}台パッチ済み、出力中）。反応しない機材は 1) DMXアドレス 2) モード（チャンネル数） 3) DMXモードか 4) DMXケーブルと終端 を確認してください。「テスターを開いて」で1チャンネルずつ試せます。"},
    "fader":   {"fr": "✓ Fader(s) {f} à {l} %", "en": "✓ Fader(s) {f} at {l} %", "es": "✓ Fader(s) {f} al {l} %",
                "de": "✓ Fader {f} auf {l} %", "pt": "✓ Fader(s) {f} a {l} %", "ja": "✓ フェーダー {f} を {l}% に"},
    "q_tablet": {"fr": "Oui ! Je t'ouvre la connexion tablette : connecte ta tablette ou ton téléphone au même Wi-Fi que l'ordinateur et suis les indications.",
                 "en": "Yes! Opening the tablet connection: put your tablet or phone on the same Wi-Fi as the computer and follow the steps.",
                 "es": "¡Sí! Abro la conexión de tableta: conecta tu tableta o teléfono a la misma Wi-Fi que el ordenador y sigue las indicaciones.",
                 "de": "Ja! Ich öffne die Tablet-Verbindung: Tablet oder Handy ins selbe WLAN wie den Computer und den Schritten folgen.",
                 "pt": "Sim! Abro a ligação do tablet: ligue o tablet ou telemóvel à mesma rede Wi-Fi do computador e siga as indicações.",
                 "ja": "はい！タブレット接続を開きます。タブレットかスマホをPCと同じWi-Fiにつないで、手順に従ってください。"},
    "q_controller": {"fr": "Oui : branche ton contrôleur MIDI en USB (AKAI APC mini, APC40, Launchpad…), MyStrow le reconnaît tout seul. Pour le régler, dis « ouvre les réglages AKAI ». Une console DMX peut aussi piloter MyStrow par l'entrée DMX.",
                     "en": "Yes: plug your MIDI controller in over USB (AKAI APC mini, APC40, Launchpad…), MyStrow detects it on its own. To set it up, say “open akai settings”. A DMX console can also drive MyStrow through the DMX input.",
                     "es": "Sí: conecta tu controlador MIDI por USB (AKAI APC mini, APC40, Launchpad…), MyStrow lo detecta solo. Para ajustarlo, di «abre akai». Una consola DMX también puede controlar MyStrow por la entrada DMX.",
                     "de": "Ja: MIDI-Controller per USB anschließen (AKAI APC mini, APC40, Launchpad…), MyStrow erkennt ihn selbst. Zum Einstellen „öffne akai“ sagen. Ein DMX-Pult kann MyStrow auch über den DMX-Eingang steuern.",
                     "pt": "Sim: ligue o controlador MIDI por USB (AKAI APC mini, APC40, Launchpad…), o MyStrow reconhece-o sozinho. Para o configurar, diga «abre akai». Uma consola DMX também pode controlar o MyStrow pela entrada DMX.",
                     "ja": "はい。MIDIコントローラー（AKAI APC mini、APC40、Launchpad など）をUSBでつなぐと自動で認識します。設定は「akaiを開いて」と言ってください。DMX卓もDMX入力から操作できます。"},
    "q_dmx": {"fr": "Oui : branche le boîtier USB-DMX (ou un node Art-Net sur le réseau), puis dis « connecte le boîtier ». Pour choisir l'interface : « ouvre la sortie DMX ».",
              "en": "Yes: plug in the USB-DMX box (or an Art-Net node on the network), then say “connect”. To pick the interface: “open the DMX output”.",
              "es": "Sí: conecta la interfaz USB-DMX (o un node Art-Net en la red) y di «conecta». Para elegir la interfaz: «abre la salida DMX».",
              "de": "Ja: USB-DMX-Box (oder Art-Net-Node im Netzwerk) anschließen, dann „verbinde“ sagen. Interface wählen: „öffne DMX Ausgang“.",
              "pt": "Sim: ligue a interface USB-DMX (ou um node Art-Net na rede) e diga «conecta». Para escolher a interface: «abre a saída DMX».",
              "ja": "はい。USB-DMXボックス（またはネットワーク上のArt-Netノード）をつないで「接続」と言ってください。インターフェースの選択は「DMX出力を開いて」。"},
    "q_generic": {"fr": "Je ne sais pas encore répondre à ce genre de question (je suis en bêta) : je garde ta phrase pour progresser. Par contre je peux agir : « allume la face en rouge », « effet rapide », « ouvre le patch »…",
                  "en": "I can't answer that kind of question yet (beta): I'm keeping your sentence to improve. But I can act: “front lights red”, “fast effect”, “open the patch”…",
                  "es": "Aún no sé responder a ese tipo de pregunta (beta): guardo tu frase para mejorar. Pero puedo actuar: «frontal en rojo», «efecto rápido», «abre el patch»…",
                  "de": "Solche Fragen kann ich noch nicht beantworten (Beta): Ich merke mir den Satz, um besser zu werden. Aber ich kann handeln: „Front rot“, „schneller Effekt“, „öffne den Patch“…",
                  "pt": "Ainda não sei responder a esse tipo de pergunta (beta): guardo a frase para melhorar. Mas posso agir: «frente em vermelho», «efeito rápido», «abre o patch»…",
                  "ja": "その種の質問にはまだ答えられません（ベータ版）。改善のために記録します。操作ならできます:「フロントを赤に」「速いエフェクト」「パッチを開いて」"},
    "pattern": {"fr": "✓ {n} projecteur(s) en alternance : {c}", "en": "✓ {n} fixture(s) alternating: {c}",
                "es": "✓ {n} foco(s) alternando: {c}", "de": "✓ {n} Scheinwerfer abwechselnd: {c}",
                "pt": "✓ {n} projetor(es) alternados: {c}", "ja": "✓ {n} 台を交互に: {c}"},
    "unchanged": {"fr": "inchangé", "en": "unchanged", "es": "sin cambio", "de": "unverändert",
                  "pt": "inalterado", "ja": "そのまま"},
    "off":     {"fr": "éteint", "en": "off", "es": "apagado", "de": "aus", "pt": "apagado", "ja": "消灯"},
    "fade":    {"fr": " (fondu {s} s)", "en": " (fade {s} s)", "es": " (fundido {s} s)", "de": " (Überblendung {s} s)",
                "pt": " (fade {s} s)", "ja": "（フェード {s} 秒）"},
    "level":   {"fr": "✓ {n} projecteur(s) à {l} %", "en": "✓ {n} fixture(s) at {l} %",
                "es": "✓ {n} foco(s) al {l} %", "de": "✓ {n} Scheinwerfer auf {l} %",
                "pt": "✓ {n} projetor(es) a {l} %", "ja": "✓ {n} 台を {l}% にしました"},
    "no_target": {"fr": "Je ne trouve aucun projecteur pour ça. Groupes du patch : {g}",
                  "en": "No fixture matches that. Groups in the patch: {g}",
                  "es": "Ningún foco corresponde. Grupos del patch: {g}",
                  "de": "Kein passender Scheinwerfer. Gruppen im Patch: {g}",
                  "pt": "Nenhum projetor corresponde. Grupos do patch: {g}",
                  "ja": "該当する機材がありません。パッチのグループ: {g}"},
    "blackout": {"fr": "✓ Noir.", "en": "✓ Blackout.", "es": "✓ Apagón.", "de": "✓ Blackout.",
                 "pt": "✓ Blackout.", "ja": "✓ 暗転しました"},
    "effect":  {"fr": "✓ Effet « {e} » lancé", "en": "✓ Effect “{e}” started", "es": "✓ Efecto «{e}» lanzado",
                "de": "✓ Effekt „{e}“ gestartet", "pt": "✓ Efeito «{e}» iniciado", "ja": "✓ エフェクト「{e}」開始"},
    "effect_speed": {"fr": ", vitesse {v}", "en": ", speed {v}", "es": ", velocidad {v}", "de": ", Tempo {v}",
                     "pt": ", velocidade {v}", "ja": "（速度 {v}）"},
    "no_effect": {"fr": "Je ne trouve pas d'effet qui corresponde.", "en": "I can't find a matching effect.",
                  "es": "No encuentro un efecto que corresponda.", "de": "Kein passender Effekt gefunden.",
                  "pt": "Não encontro um efeito correspondente.", "ja": "該当するエフェクトがありません"},
    "speed":   {"fr": "✓ Vitesse des effets : {v}", "en": "✓ Effect speed: {v}", "es": "✓ Velocidad de efectos: {v}",
                "de": "✓ Effekt-Tempo: {v}", "pt": "✓ Velocidade dos efeitos: {v}", "ja": "✓ エフェクト速度: {v}"},
    "stop":    {"fr": "✓ Effets arrêtés.", "en": "✓ Effects stopped.", "es": "✓ Efectos detenidos.",
                "de": "✓ Effekte gestoppt.", "pt": "✓ Efeitos parados.", "ja": "✓ エフェクトを停止しました"},
    "memory":  {"fr": "✓ Mémoire {m} lancée", "en": "✓ Memory {m} triggered", "es": "✓ Memoria {m} lanzada",
                "de": "✓ Speicher {m} gestartet", "pt": "✓ Memória {m} iniciada", "ja": "✓ メモリ {m} を再生"},
    "memory_empty": {"fr": "La mémoire {m} est vide.", "en": "Memory {m} is empty.", "es": "La memoria {m} está vacía.",
                     "de": "Speicher {m} ist leer.", "pt": "A memória {m} está vazia.", "ja": "メモリ {m} は空です"},
    "playback": {"fr": "✓ OK", "en": "✓ OK", "es": "✓ OK", "de": "✓ OK", "pt": "✓ OK", "ja": "✓ OK"},
    "open":    {"fr": "✓ Je l'ouvre.", "en": "✓ Opening it.", "es": "✓ Lo abro.", "de": "✓ Wird geöffnet.",
                "pt": "✓ A abrir.", "ja": "✓ 開きます"},
    "save":    {"fr": "✓ J'enregistre le show.", "en": "✓ Saving the show.", "es": "✓ Guardo el show.",
                "de": "✓ Show wird gespeichert.", "pt": "✓ A guardar o show.", "ja": "✓ ショーを保存します"},
    "connect": {"fr": "Je connecte la sortie DMX…", "en": "Connecting the DMX output…", "es": "Conectando la salida DMX…",
                "de": "DMX-Ausgang wird verbunden…", "pt": "A ligar a saída DMX…", "ja": "DMX出力に接続中…"},
    "connect_ok": {"fr": "✓ Sortie DMX connectée.", "en": "✓ DMX output connected.", "es": "✓ Salida DMX conectada.",
                   "de": "✓ DMX-Ausgang verbunden.", "pt": "✓ Saída DMX ligada.", "ja": "✓ DMX出力に接続しました"},
    "connect_fail": {"fr": "Le boîtier ne répond pas. Vérifie le câble, ou dis « ouvre la sortie DMX ».",
                     "en": "The interface doesn't answer. Check the cable, or say “open the DMX output”.",
                     "es": "La interfaz no responde. Revisa el cable, o di «abre la salida DMX».",
                     "de": "Das Interface antwortet nicht. Kabel prüfen oder „öffne DMX Ausgang“ sagen.",
                     "pt": "A interface não responde. Verifique o cabo, ou diga «abre a saída DMX».",
                     "ja": "インターフェースが応答しません。ケーブルを確認するか「DMX出力を開いて」と言ってください"},
    "connect_locked": {"fr": "La sortie DMX demande une licence active.", "en": "DMX output needs an active licence.",
                       "es": "La salida DMX requiere una licencia activa.", "de": "Der DMX-Ausgang braucht eine aktive Lizenz.",
                       "pt": "A saída DMX requer uma licença ativa.", "ja": "DMX出力には有効なライセンスが必要です"},
    "fixture": {"fr": "J'ouvre la création de fixture : copie le texte proposé dans ton IA avec le tableau DMX du manuel, puis recolle sa réponse.",
                "en": "Opening fixture creation: copy the prompt into your AI with the manual's DMX chart, then paste its answer back.",
                "es": "Abro la creación de fixture: copia el texto en tu IA con la tabla DMX del manual y pega su respuesta.",
                "de": "Fixture-Erstellung wird geöffnet: Prompt mit der DMX-Tabelle des Handbuchs in deine KI kopieren, Antwort zurück einfügen.",
                "pt": "Abro a criação de fixture: copie o texto para a sua IA com a tabela DMX do manual e cole a resposta.",
                "ja": "フィクスチャ作成を開きます。プロンプトとマニュアルのDMX表をAIに渡し、回答を貼り付けてください"},
    "fixture_done": {"fr": "✓ Fixture « {f} » ajoutée : Patch DMX → Ajouter.", "en": "✓ Fixture “{f}” added: DMX Patch → Add.",
                     "es": "✓ Fixture «{f}» añadida: Patch DMX → Añadir.", "de": "✓ Fixture „{f}“ hinzugefügt: DMX-Patch → Hinzufügen.",
                     "pt": "✓ Fixture «{f}» adicionada: Patch DMX → Adicionar.", "ja": "✓ フィクスチャ「{f}」を追加しました"},
    "status":  {"fr": "{n} projecteur(s), groupes {g}. Sortie DMX : {d}. Effet : {e}.",
                "en": "{n} fixture(s), groups {g}. DMX output: {d}. Effect: {e}.",
                "es": "{n} foco(s), grupos {g}. Salida DMX: {d}. Efecto: {e}.",
                "de": "{n} Scheinwerfer, Gruppen {g}. DMX-Ausgang: {d}. Effekt: {e}.",
                "pt": "{n} projetor(es), grupos {g}. Saída DMX: {d}. Efeito: {e}.",
                "ja": "機材 {n} 台、グループ {g}。DMX出力: {d}。エフェクト: {e}。"},
    "yes":     {"fr": "connectée", "en": "connected", "es": "conectada", "de": "verbunden", "pt": "ligada", "ja": "接続中"},
    "no":      {"fr": "non connectée", "en": "not connected", "es": "no conectada", "de": "nicht verbunden",
                "pt": "desligada", "ja": "未接続"},
    "none":    {"fr": "aucun", "en": "none", "es": "ninguno", "de": "keiner", "pt": "nenhum", "ja": "なし"},
    "learned": {"fr": "✓ Retenu : « {p} » = {c}", "en": "✓ Learned: “{p}” = {c}", "es": "✓ Aprendido: «{p}» = {c}",
                "de": "✓ Gemerkt: „{p}“ = {c}", "pt": "✓ Aprendido: «{p}» = {c}", "ja": "✓ 覚えました:「{p}」= {c}"},
    "learn_bad": {"fr": "Je ne comprends pas « {c} » non plus : donne-moi une commande que je connais.",
                  "en": "I don't understand “{c}” either: give me a command I know.",
                  "es": "Tampoco entiendo «{c}»: dame una orden que conozca.",
                  "de": "„{c}“ verstehe ich auch nicht: nenne einen Befehl, den ich kenne.",
                  "pt": "Também não percebo «{c}»: dê-me um comando que eu conheça.",
                  "ja": "「{c}」も分かりません。知っているコマンドを指定してください"},
    "forgot":  {"fr": "✓ Oublié : « {p} »", "en": "✓ Forgotten: “{p}”", "es": "✓ Olvidado: «{p}»",
                "de": "✓ Vergessen: „{p}“", "pt": "✓ Esquecido: «{p}»", "ja": "✓ 忘れました:「{p}」"},
    "not_known": {"fr": "Je ne connaissais pas « {p} ».", "en": "I didn't know “{p}”.", "es": "No conocía «{p}».",
                  "de": "„{p}“ kannte ich nicht.", "pt": "Não conhecia «{p}».", "ja": "「{p}」は登録されていません"},
    "unknown": {"fr": "Je n'ai pas compris « {t} ». Pour me l'apprendre : apprends {t} = mémoire 1.1",
                "en": "I didn't understand “{t}”. To teach me: learn {t} = memory 1.1",
                "es": "No entendí «{t}». Para enseñarme: aprende {t} = memoria 1.1",
                "de": "„{t}“ habe ich nicht verstanden. Beibringen: lerne {t} = Speicher 1.1",
                "pt": "Não percebi «{t}». Para me ensinar: aprende {t} = memória 1.1",
                "ja": "「{t}」が分かりませんでした。教えるには: 覚えて {t} = メモリ 1.1"},
    "help":    {"fr": "Exemples : « allume tout en rouge », « la face en bleu à 50 % », « effet rapide », « plus vite », "
                      "« stop », « noir », « monte les 4 faders », « un projecteur sur deux en rouge », « allume progressivement », « mémoire 2.3 », « suivant », « ouvre le patch », « connecte le boîtier », "
                      "« crée ma fixture », « apprends ambiance club = mémoire 2.1 ».",
                "en": "Examples: “all lights red”, “front blue at 50 %”, “fast effect”, “faster”, “stop”, “blackout”, "
                      "“memory 2.3”, “next”, “open the patch”, “connect the interface”, “create a fixture”, "
                      "“learn club vibe = memory 2.1”.",
                "es": "Ejemplos: «todo en rojo», «frontal en azul al 50 %», «efecto rápido», «más rápido», «parar», "
                      "«apagón», «memoria 2.3», «siguiente», «abre el patch», «conecta la interfaz», «crea un fixture».",
                "de": "Beispiele: „alles rot“, „Front blau auf 50 %“, „schneller Effekt“, „schneller“, „stopp“, "
                      "„Blackout“, „Speicher 2.3“, „nächster“, „öffne den Patch“, „verbinde die Box“, „neue Fixture“.",
                "pt": "Exemplos: «tudo em vermelho», «frente em azul a 50 %», «efeito rápido», «mais rápido», «parar», "
                      "«blackout», «memória 2.3», «seguinte», «abre o patch», «conecta a interface», «cria uma fixture».",
                "ja": "例:「全部赤にして」「フロントを青 50%」「速いエフェクト」「速く」「止めて」「暗転」「メモリ 2.3」"
                      "「次」「パッチを開いて」「接続」「フィクスチャを作成」"},
}


def _r(key, lang, **kw):
    t = R[key].get(lang) or R[key]["en"]
    return t.format(**kw)


def _color_name(key, lang):
    words = nlu.COLORS.get(key, {}).get(lang) or nlu.COLORS.get(key, {}).get("en") or [key]
    return words[0]


# Fenêtres ouvrables → méthode de MainWindow (+ arguments).
_WINDOWS = {
    "patch": ("show_dmx_patch_config",), "effects": ("open_effect_editor",), "3d": ("toggle_3d_window",),
    "rec": ("open_light_editor",), "output": ("open_node_connection",), "tester": ("open_dmx_tester",),
    "monitor": ("open_dmx_monitor",), "tablet": ("_start_tablet_server",), "ia": ("show_ia_lumiere_config",),
    "akai": ("_open_akai_layout_editor",), "shortcuts": ("show_shortcuts_dialog",), "obs": ("_open_obs_dialog",),
    "vmix": ("_open_vmix_dialog",), "gamepad": ("_open_gamepad_dialog",), "news": ("_open_whats_new",),
    "tutorials": ("_show_tutorials_dialog",),
}


# ── Exécution ────────────────────────────────────────────────────────────────

class AssistantExecutor:
    """Exécute les actions dans le thread Qt et rend les réponses."""

    def __init__(self, window, store: AssistantStore, say):
        self.w = window
        self.store = store
        self.say = say          # say(texte) : ajoute une réponse différée (connexion, fixture)

    def handle(self, text: str) -> list:
        """Compréhension par les règles seules, puis exécution."""
        return self.run(text, self.rules(text))

    def rules(self, text: str):
        return nlu.parse(text, la.all_effects(), get_language(), self.store.aliases)

    def needs_model(self, text: str, parsed) -> bool:
        """Le modèle local (s'il est installé) lit la phrase, sauf pour :
        - les urgences courtes (« noir », « stop ») : instantané, sans attendre ;
        - les tournures apprises et « apprends … » / « oublie … » (règles exactes)."""
        if nlu.normalize(text) in self.store.aliases:
            return False
        kinds = {a["do"] for a in parsed.actions}
        if kinds & {"learn", "forget"}:
            return False
        if kinds <= {"blackout", "stop_effects"} and len(text.split()) <= 3:
            return False
        if kinds == {"blackout"}:      # un noir reconnu ne se discute pas (le modèle a déjà lu « noir » en bleu)
            return False
        if kinds == {"diagnose"}:      # « ça bug » : le diagnostic lit l'état réel, pas besoin du modèle
            return False
        return True

    def run(self, text: str, parsed, model_actions=None) -> list:
        """Exécute les actions des règles, ou celles du modèle si on les a.
        La langue de la réponse vient toujours des règles (vote sur les mots)."""
        lang = parsed.lang
        actions = parsed.actions if model_actions is None else model_actions
        out = []
        for act in actions:
            try:
                out.append(self._do(act, lang, text))
            except Exception as exc:
                print(f"[Assistant] {act} : {exc}")
                out.append(f"✖ {exc}")
        out = [o for o in out if o]
        self.store.note(text, lang, actions, out, source="rules" if model_actions is None else "model")
        return out

    def _select(self, target) -> list:
        if "nums" in target:      # numéros affichés (1 = premier projecteur du patch)
            idxs = la.resolve(self.w, idxs=[n - 1 for n in target["nums"]])
        elif target.get("group") or target.get("kind"):
            idxs = la.resolve(self.w, group=target.get("group"), kind=target.get("kind"))
        else:
            idxs = la.resolve(self.w)
        if target.get("parity"):
            first = 0 if target["parity"] == "odd" else 1     # 1er, 3e… = impairs
            idxs = idxs[first::2]
        if target.get("except"):
            excluded = set(self._select(target["except"]))
            idxs = [i for i in idxs if i not in excluded]
        return idxs

    def _targets(self, target, lang):
        idxs = self._select(target)
        if not idxs:
            raise _Reply(_r("no_target", lang, g=", ".join(la.groups_present(self.w)) or "—"))
        return idxs

    def _do(self, a, lang, text):
        w, do = self.w, a["do"]
        try:
            fade = a.get("fade")
            tail = _r("fade", lang, s=f"{fade:g}") if fade else ""
            if do == "color":
                idxs = self._targets(a["target"], lang)
                if fade:
                    la.fade_to(w, idxs, a["level"], fade, a["hex"])
                else:
                    la.set_color(w, idxs, a["hex"], a["level"])
                return _r("color", lang, n=len(idxs), c=_color_name(a["color"], lang), l=a["level"]) + tail
            if do == "level":
                idxs = self._targets(a["target"], lang)
                if fade:
                    la.fade_to(w, idxs, a["level"], fade)
                else:
                    la.set_level(w, idxs, a["level"])
                return _r("level", lang, n=len(idxs), l=a["level"]) + tail
            if do == "level_rel":
                idxs = self._targets(a["target"], lang)
                if fade:
                    goal = max(0, min(100, round(sum(w.projectors[i].level for i in idxs) / len(idxs)) + a["delta"]))
                    la.fade_to(w, idxs, goal, fade)
                    return _r("level", lang, n=len(idxs), l=goal) + tail
                return _r("level", lang, n=len(idxs), l=la.adjust_level(w, idxs, a["delta"]))
            if do == "pattern":
                return self._pattern(a, lang) + tail
            if do == "fader":
                la.set_faders(w, [n - 1 for n in a["faders"]], a["level"], fade or 0)
                return _r("fader", lang, f=", ".join(map(str, a["faders"])), l=a["level"]) + tail
        except _Reply as r:
            return str(r)

        if do == "diagnose":
            return self._diagnose(lang)
        if do == "answer":
            if a["topic"] == "generic":
                self.store.note_unknown(a.get("text") or text)
            return _r("q_" + a["topic"], lang)
        if do == "blackout":
            la.blackout(w)
            return _r("blackout", lang)
        if do == "effect":
            if not la.fire_effect(w, a["name"]):
                return _r("no_effect", lang)
            msg = _r("effect", lang, e=a["name"])
            if "speed" in a:
                msg += _r("effect_speed", lang, v=la.set_speed(w, a["speed"]))
            return msg
        if do == "no_effect":
            return _r("no_effect", lang)
        if do == "speed":
            return _r("speed", lang, v=la.set_speed(w, a["value"]))
        if do == "speed_rel":
            return _r("speed", lang, v=la.set_speed(w, getattr(w, "effect_speed", 50) + a["delta"]))
        if do == "stop_effects":
            la.stop_effects(w)
            return _r("stop", lang)
        if do == "memory":
            col, row = (int(x) - 1 for x in a["id"].split("."))
            if w.memories[col][row] is None:
                return _r("memory_empty", lang, m=a["id"])
            w.trigger_memory(col, row)
            return _r("memory", lang, m=a["id"])
        if do == "playback":
            self._playback(a["what"])
            return _r("playback", lang)
        if do == "open":
            meth = getattr(w, _WINDOWS[a["window"]][0], None)
            if meth is None:
                return _r("unknown", lang, t=text)
            QTimer.singleShot(0, meth)        # fenêtres modales : après la réponse
            return _r("open", lang)
        if do == "save":
            QTimer.singleShot(0, w.save_show)
            return _r("save", lang)
        if do == "connect":
            return self._connect(lang)
        if do == "fixture":
            QTimer.singleShot(0, lambda: self._fixture(lang))
            return _r("fixture", lang)
        if do == "status":
            eff = getattr(w, "active_effect", None) or _r("none", lang)
            dmx = _r("yes", lang) if getattr(w.dmx, "connected", False) else _r("no", lang)
            return _r("status", lang, n=len(w.projectors), g=", ".join(la.groups_present(w)) or "—", d=dmx, e=eff)
        if do == "help":
            return _r("help", lang)
        if do == "learn":
            check = nlu.parse(a["command"], la.all_effects(), lang)
            if not check.understood or any(x["do"] in ("learn", "forget") for x in check.actions):
                return _r("learn_bad", lang, c=a["command"])
            self.store.learn(a["phrase"], a["command"])
            return _r("learned", lang, p=a["phrase"], c=a["command"])
        if do == "forget":
            return _r("forgot" if self.store.forget(a["phrase"]) else "not_known", lang, p=a["phrase"])
        self.store.note_unknown(a.get("text") or text)
        return _r("unknown", lang, t=(a.get("text") or text).strip())

    def _diagnose(self, lang):
        """« Pourquoi ça bug ? » : on regarde l'état réel de MyStrow, cause la plus probable d'abord."""
        w = self.w
        found = []
        lic = getattr(w, "_license", None)
        if lic is not None and not getattr(lic, "dmx_allowed", True):
            found.append("diag_license")
        dmx = getattr(w, "dmx", None)
        if dmx is not None and not getattr(dmx, "connected", False):
            found.append("diag_dmx")
        pdf = getattr(w, "plan_de_feu", None)
        try:
            if pdf is not None and not pdf.is_dmx_enabled():
                found.append("diag_disabled")
        except Exception:
            pass
        projs = list(getattr(w, "projectors", []) or [])
        if not projs:
            found.append("diag_patch")
        if getattr(w, "blackout_active", False):
            found.append("diag_blackout")
        if getattr(w, "master_level", 100) <= 0:
            found.append("diag_master")
        if projs and all((getattr(p, "level", 0) or 0) <= 0 for p in projs) and "diag_blackout" not in found:
            found.append("diag_levels")
        if not found:
            return _r("diag_ok", lang, n=len(projs))
        return "\n".join(_r(k, lang) for k in found)

    def _pattern(self, a, lang):
        """Alternance : le 1er projecteur prend la 1re case, le 2e la 2e… en boucle."""
        w, slots = self.w, a["slots"]
        idxs = self._targets(a["target"], lang)
        level = 100 if a.get("level") is None else a["level"]
        fade = a.get("fade")
        for k, slot in enumerate(slots):
            ids = idxs[k::len(slots)]
            if not ids or slot is None:
                continue
            goal = slot.get("level", level)
            if fade:
                la.fade_to(w, ids, goal, fade, slot.get("hex"))
            elif "hex" in slot:
                la.set_color(w, ids, slot["hex"], goal)
            else:
                la.set_level(w, ids, goal)
        names = [_r("unchanged", lang) if s is None else
                 _color_name(s["color"], lang) if "color" in s else _r("off", lang) for s in slots]
        return _r("pattern", lang, n=len(idxs), c=" / ".join(names))

    def _playback(self, what):
        w = self.w
        if what == "next":
            w.next_media()
        elif what == "prev":
            w.previous_media()
        elif what == "go":
            w._go_advance()
        elif what == "go_back":
            w._go_back()
        else:
            has_source = bool(w.player.source().toString())
            if not has_source and getattr(w.seq, "current_row", -1) < 0:
                if w.seq.table.rowCount() > 0:
                    w.seq.play_row(0)
            else:
                w.toggle_play()

    def _connect(self, lang):
        w = self.w
        if not w._license.dmx_allowed:
            return _r("connect_locked", lang)

        def ok():
            w._on_startup_dmx_ready()
            self.say(_r("connect_ok", lang))

        w._connect_dmx_async(on_ok=ok)

        def check():
            if not getattr(w.dmx, "connected", False):
                self.say(_r("connect_fail", lang))
        QTimer.singleShot(8000, check)
        return _r("connect", lang)

    def _fixture(self, lang):
        from PySide6.QtWidgets import QDialog
        from fixture_ai_prompt import AIFixtureDialog, save_to_library
        dlg = AIFixtureDialog(self.w)
        if dlg.exec() != QDialog.Accepted:
            return
        fx = dlg.result_fixture()
        if fx.get("profile"):
            self.say(_r("fixture_done", lang, f=save_to_library(fx)))


class _Reply(Exception):
    pass


# ── Interface ────────────────────────────────────────────────────────────────

_CHAT_SS = (
    "QTextBrowser { background:#0c0c0c; border:1px solid #1e1e1e; border-radius:4px; "
    "font-size:12px; padding:4px; } "
    "QScrollBar:vertical { background:#111; width:5px; border:none; } "
    "QScrollBar::handle:vertical { background:#2a2a2a; border-radius:2px; } "
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }"
)
_BTN_SS = (
    "QPushButton { background:#1e1e1e; color:#aaa; border:1px solid #333; border-radius:4px; font-size:13px; } "
    "QPushButton:hover { border-color:#0077bb; color:#fff; } "
    "QPushButton:disabled { color:#444; border-color:#222; }"
)
_MIC_REC_SS = (
    "QPushButton { background:#4a0d0d; color:#ff6666; border:1px solid #ff4444; border-radius:4px; font-size:13px; }"
)


class _ModelWorker(QThread):
    """Le modèle local lit la phrase hors du thread Qt (~1 s sur le processeur)."""

    done = Signal(list)
    failed = Signal(str)

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self._text = text

    def run(self):
        try:
            import assistant_llm
            self.done.emit(assistant_llm.ask(self._text))
        except Exception as exc:
            self.failed.emit(str(exc))


class AssistantPanel(QWidget):
    def __init__(self, window, store: AssistantStore, parent=None):
        super().__init__(parent)
        self.store = store
        self.exec = AssistantExecutor(window, store, self._say_assistant)
        self._history, self._hist_pos = [], 0
        self._recorder, self._worker = None, None
        try:
            import assistant_llm
            self._model_ok = assistant_llm.available()
        except Exception:
            self._model_ok = False
        self._queue, self._thinking = [], None     # demandes en attente du modèle
        self._rec_t0 = 0.0
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self._build_model_banner(lay)

        self._chat = QTextBrowser()
        self._chat.setOpenExternalLinks(False)
        self._chat.setMinimumHeight(60)
        self._chat.setStyleSheet(_CHAT_SS)
        lay.addWidget(self._chat, 1)

        self._status = QLabel("")
        self._status.setStyleSheet("color:#00d4ff; font-size:10px; background:transparent;")
        self._status.hide()
        lay.addWidget(self._status)

        row = QHBoxLayout()
        row.setSpacing(4)
        self._input = QLineEdit()
        self._input.setPlaceholderText(tr("asst_placeholder"))
        self._input.setStyleSheet(
            "QLineEdit { background:#111; color:#ddd; border:1px solid #2a2a2a; border-radius:4px; "
            "padding:4px 6px; font-size:12px; } QLineEdit:focus { border-color:#0077bb; }")
        self._input.returnPressed.connect(self._send)
        self._input.installEventFilter(self)
        row.addWidget(self._input, 1)

        self._mic = QPushButton("🎤")
        self._mic.setFixedSize(30, 26)
        self._mic.setStyleSheet(_BTN_SS)
        from assistant_voice import available
        why = available()
        self._mic.setEnabled(not why)
        self._mic.setToolTip(tr("asst_mic_tip") if not why else tr("asst_voice_unavailable", why=why))
        # Moteur vocal absent (pas embarqué dans l'installeur) : pas de micro du tout.
        self._mic.setVisible(why != "faster-whisper")
        if why == "faster-whisper":
            self._input.setPlaceholderText(tr("asst_placeholder_text"))
        self._mic.pressed.connect(self._mic_pressed)
        self._mic.released.connect(self._mic_released)
        row.addWidget(self._mic)

        send = QPushButton("➤")
        send.setFixedSize(30, 26)
        send.setStyleSheet(_BTN_SS)
        send.setToolTip(tr("asst_send"))
        send.clicked.connect(self._send)
        row.addWidget(send)
        lay.addLayout(row)

        self._say_assistant(tr("asst_welcome"))

    # ── messages ──
    def _bubble(self, text, mine):
        body = html.escape(text).replace("\n", "<br>")
        if mine:
            cell = (f'<table align="right" cellpadding="6" bgcolor="#0d2a33" style="margin:3px 0 3px 30px;">'
                    f'<tr><td style="color:#00d4ff;">{body}</td></tr></table>')
        else:
            cell = (f'<table align="left" cellpadding="6" bgcolor="#181818" style="margin:3px 30px 3px 0;">'
                    f'<tr><td style="color:#cccccc;">{body}</td></tr></table>')
        self._chat.append(cell)
        sb = self._chat.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _say_assistant(self, text):
        self._bubble(text, mine=False)

    def submit(self, text: str):
        text = (text or "").strip()
        if not text:
            return
        self._bubble(text, mine=True)
        self._history.append(text)
        self._hist_pos = len(self._history)
        parsed = self.exec.rules(text)
        if self._model_ok and self.exec.needs_model(text, parsed):
            self._queue.append((text, parsed))
            self._next_model()
            return
        for reply in self.exec.run(text, parsed):
            self._say_assistant(reply)

    # ── modèle local : téléchargement et mises à jour ──
    def _build_model_banner(self, lay):
        """Bandeau au-dessus de la discussion : proposer le modèle, ses mises à
        jour, et montrer le téléchargement. Invisible sans le moteur (llama_cpp)."""
        self._banner = QWidget()
        self._banner.setStyleSheet("QWidget { background:#141f24; border:1px solid #1f3a44; border-radius:4px; }"
                                   "QLabel { border:none; color:#9fd8ea; font-size:10px; }")
        row = QHBoxLayout(self._banner)
        row.setContentsMargins(6, 4, 4, 4)
        row.setSpacing(4)
        self._banner_lbl = QLabel("")
        self._banner_lbl.setWordWrap(True)
        row.addWidget(self._banner_lbl, 1)
        self._banner_btn = QPushButton("")
        self._banner_btn.setStyleSheet(_BTN_SS + " QPushButton { font-size:10px; padding:2px 8px; }")
        self._banner_btn.clicked.connect(self._banner_action)
        row.addWidget(self._banner_btn)
        self._banner_close = QPushButton("✕")
        self._banner_close.setFixedSize(18, 18)
        self._banner_close.setStyleSheet("QPushButton { background:transparent; color:#567; border:none; } "
                                         "QPushButton:hover { color:#fff; }")
        self._banner_close.clicked.connect(self._banner_dismiss)
        row.addWidget(self._banner_close)
        lay.addWidget(self._banner)
        self._banner.hide()
        self._dl, self._dl_manifest, self._update_manifest, self._checker = None, None, None, None
        self._refresh_banner()

    def _refresh_banner(self):
        import assistant_model as am
        if not am.engine_available():
            self._banner.hide()
            return
        if self._dl is not None:
            return                                    # la progression met le texte à jour
        if not am.installed():
            self._banner_lbl.setText(tr("asst_model_offer"))
            self._banner_btn.setText(tr("asst_model_download"))
            self._banner_close.hide()
            self._banner.show()
        elif self._update_manifest is not None:
            self._banner_lbl.setText(tr("asst_model_update", v=self._update_manifest["version"]))
            self._banner_btn.setText(tr("asst_model_update_btn"))
            self._banner_close.show()
            self._banner.show()
        else:
            self._banner.hide()

    def check_model_update(self):
        """Appelé quand l'onglet Assistant s'affiche : au plus une vérification par jour."""
        import assistant_model as am
        if self._checker is not None or not am.engine_available() or not am.installed() or not am.check_due():
            return
        self._checker = am.ManifestCheck(self)
        self._checker.found.connect(self._on_update_found)
        self._checker.finished.connect(lambda: setattr(self, "_checker", None))
        self._checker.start()

    def _on_update_found(self, manifest):
        import assistant_model as am
        if manifest["version"] > am.dismissed_version():
            self._update_manifest = manifest
            self._refresh_banner()

    def _banner_dismiss(self):
        import assistant_model as am
        if self._update_manifest is not None:
            am.dismiss(self._update_manifest["version"])
        self._update_manifest = None
        self._banner.hide()

    def _banner_action(self):
        import assistant_model as am
        if self._dl is not None:                      # « Annuler »
            self._dl.cancel()
            return
        self._dl = am.ModelDownload(self._update_manifest, self)
        self._dl.progress.connect(self._on_dl_progress)
        self._dl.done.connect(self._on_dl_done)
        self._dl.failed.connect(self._on_dl_failed)
        self._dl.finished.connect(self._dl.deleteLater)
        self._banner_lbl.setText(tr("asst_model_connecting"))
        self._banner_btn.setText(tr("asst_model_cancel"))
        self._banner_close.hide()
        self._dl.start()

    def _on_dl_progress(self, got, total):
        mb = 1024 * 1024
        self._banner_lbl.setText(tr("asst_model_progress", p=int(100 * got / max(1, total)),
                                    got=got // mb, total=total // mb))

    def _on_dl_done(self, manifest, part):
        self._dl = None
        self._banner_btn.hide()
        self._install(manifest, part)

    def _install(self, manifest, part):
        if self._thinking is not None:                # le modèle répond : on le remplace juste après
            QTimer.singleShot(500, lambda: self._install(manifest, part))
            return
        import assistant_model as am
        self._banner_btn.show()
        try:
            am.install(part, manifest)
        except Exception as exc:
            self._on_dl_failed(str(exc))
            return
        self._update_manifest = None
        self._model_ok = True
        self._banner.hide()
        self._say_assistant(tr("asst_model_ready"))

    def _on_dl_failed(self, msg):
        self._dl = None
        self._banner_lbl.setText(tr("asst_model_failed", e=msg))
        self._banner_btn.setText(tr("asst_model_retry"))
        self._banner_close.show()
        self._banner.show()

    def _next_model(self):
        if self._thinking is not None or not self._queue:
            return
        text, parsed = self._queue.pop(0)
        w = _ModelWorker(text, self)
        self._thinking = (w, text, parsed)
        w.done.connect(self._on_model_done)
        w.failed.connect(self._on_model_failed)
        w.finished.connect(w.deleteLater)
        self._show_status(tr("asst_thinking"))
        w.start()

    def _on_model_done(self, raw):
        import assistant_llm
        _w, text, parsed = self._thinking
        self._thinking = None
        self._show_status("")
        actions = assistant_llm.to_nlu(raw, text, la.all_effects())
        for reply in self.exec.run(text, parsed, actions):
            self._say_assistant(reply)
        self._next_model()

    def _on_model_failed(self, msg):
        # Modèle illisible ou absent : les règles prennent le relais, sans bruit.
        print(f"[Assistant] modèle local indisponible : {msg}")
        _w, text, parsed = self._thinking
        self._thinking = None
        self._model_ok = False
        self._show_status("")
        for reply in self.exec.run(text, parsed):
            self._say_assistant(reply)
        self._next_model()

    def _send(self):
        text = self._input.text()
        self._input.clear()
        self.submit(text)

    def eventFilter(self, obj, ev):
        # Flèches haut/bas : rappel des demandes précédentes.
        if obj is self._input and ev.type() == ev.Type.KeyPress and self._history:
            if ev.key() == Qt.Key_Up:
                self._hist_pos = max(0, self._hist_pos - 1)
                self._input.setText(self._history[self._hist_pos])
                return True
            if ev.key() == Qt.Key_Down:
                self._hist_pos = min(len(self._history), self._hist_pos + 1)
                self._input.setText(self._history[self._hist_pos] if self._hist_pos < len(self._history) else "")
                return True
        return super().eventFilter(obj, ev)

    # ── voix : maintenir pour parler, ou clic court = marche / arrêt ──
    def _show_status(self, text):
        self._status.setText(text)
        self._status.setVisible(bool(text))

    def _mic_pressed(self):
        if self._recorder is not None:          # 2e clic en mode marche/arrêt
            self._stop_recording()
            return
        if self._worker is not None:
            return
        from assistant_voice import Recorder
        try:
            self._recorder = Recorder()
            self._recorder.start()
        except Exception as exc:
            self._recorder = None
            self._say_assistant(f"✖ {exc}")
            return
        self._rec_t0 = time.monotonic()
        self._mic.setStyleSheet(_MIC_REC_SS)
        self._show_status(tr("asst_listening"))
        QTimer.singleShot(15000, self._auto_stop)

    def _mic_released(self):
        # Maintenu plus d'un tiers de seconde : on parlait en tenant le bouton.
        if self._recorder is not None and time.monotonic() - self._rec_t0 > 0.35:
            self._stop_recording()

    def _auto_stop(self):
        if self._recorder is not None and time.monotonic() - self._rec_t0 >= 14.5:
            self._stop_recording()

    def _stop_recording(self):
        rec, self._recorder = self._recorder, None
        self._mic.setStyleSheet(_BTN_SS)
        audio = rec.stop()
        if len(audio) < 4000:                   # moins d'un quart de seconde
            self._show_status("")
            return
        from assistant_voice import TranscribeWorker, model_ready
        self._show_status(tr("asst_transcribing") if model_ready() else tr("asst_downloading"))
        self._mic.setEnabled(False)
        self._worker = TranscribeWorker(audio, get_language(), parent=self)
        self._worker.done.connect(self._on_transcribed)
        self._worker.failed.connect(self._on_transcribe_failed)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_transcribed(self, text, _lang):
        self._show_status("")
        if text:
            self.submit(text)

    def _on_transcribe_failed(self, msg):
        self._show_status("")
        self._say_assistant(f"✖ {msg}")

    def _on_worker_finished(self):
        self._worker.deleteLater()
        self._worker = None
        self._mic.setEnabled(True)


# Bêta cachée : 3 clics sur le titre « JOURNAL » (ou ce raccourci) montrent ou
# cachent l'assistant. Sinon le cadre n'affiche que le Journal, exactement comme
# avant, et rien ne part sur le réseau (la vérification du modèle n'a lieu qu'à
# l'ouverture de l'onglet).
UNLOCK_SHORTCUT = "Ctrl+Alt+Shift+A"
UNLOCK_CLICKS, UNLOCK_CLICK_GAP_MS = 3, 600


class AssistantDock(QWidget):
    """Journal et Assistant dans le même cadre, avec bascule et agrandissement
    sur toute la colonne de gauche."""

    expanded_changed = Signal(bool)

    def __init__(self, window, log_widget: QWidget, parent=None):
        super().__init__(parent)
        self.store = AssistantStore()
        self._root_layout = None
        self._zone = None
        self._hidden = []
        self._expanded = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)

        self._bar = QWidget()
        bar = QHBoxLayout(self._bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(4)
        tab_ss = ("QPushButton { background:transparent; color:#555; border:none; border-bottom:2px solid transparent; "
                  "font-size:9px; font-weight:bold; padding:2px 6px; } "
                  "QPushButton:hover { color:#999; } "
                  "QPushButton:checked { color:#00d4ff; border-bottom-color:#00d4ff; }")
        self._tab_log = QPushButton(tr("mw_log").upper())
        self._tab_asst = QPushButton("🤖 " + tr("asst_tab").upper())
        for b in (self._tab_log, self._tab_asst):
            b.setCheckable(True)
            b.setStyleSheet(tab_ss)
            bar.addWidget(b)
        beta = QLabel(tr("asst_beta"))
        beta.setToolTip(tr("asst_beta_tip"))
        beta.setStyleSheet("color:#ffaa00; border:1px solid #ffaa00; border-radius:3px; "
                           "font-size:8px; font-weight:bold; padding:0 3px;")
        bar.addWidget(beta)
        bar.addStretch()
        self._btn_expand = QPushButton("⤢")
        self._btn_expand.setFixedSize(20, 16)
        self._btn_expand.setToolTip(tr("asst_expand_tip"))
        self._btn_expand.setStyleSheet(
            "QPushButton { background:transparent; color:#666; border:none; font-size:12px; } "
            "QPushButton:hover { color:#00d4ff; }")
        self._btn_expand.clicked.connect(lambda: self.set_expanded(not self._expanded))
        bar.addWidget(self._btn_expand)
        lay.addWidget(self._bar)

        self._stack = QStackedWidget()
        self._stack.addWidget(log_widget)
        self.panel = AssistantPanel(window, self.store)
        self._stack.addWidget(self.panel)
        lay.addWidget(self._stack, 1)

        self._tab_log.clicked.connect(lambda: self.show_tab("log"))
        self._tab_asst.clicked.connect(lambda: self.show_tab("assistant"))
        self._unlock_sc = QShortcut(QKeySequence(UNLOCK_SHORTCUT), window)
        self._unlock_sc.setContext(Qt.ApplicationShortcut)
        self._unlock_sc.activated.connect(lambda: self.set_unlocked(not self.unlocked()))
        self._clicks, self._last_click = 0, 0.0
        title = getattr(log_widget, "_title", None)
        if title is not None:
            title.installEventFilter(self)
        self._bar.setVisible(self.unlocked())
        self.show_tab(self.store.data.get("tab", "log") if self.unlocked() else "log", remember=False)

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            now = time.monotonic()
            self._clicks = self._clicks + 1 if now - self._last_click < UNLOCK_CLICK_GAP_MS / 1000 else 1
            self._last_click = now
            if self._clicks >= UNLOCK_CLICKS:
                self._clicks = 0
                self.set_unlocked(not self.unlocked())
        return False

    def unlocked(self) -> bool:
        return bool(self.store.data.get("unlocked"))

    def set_unlocked(self, on: bool):
        if not on and self._expanded:
            self.set_expanded(False)
        self.store.data["unlocked"] = on
        self.store.save()
        self._bar.setVisible(on)
        self.show_tab("assistant" if on else "log")

    def show_tab(self, name, remember=True):
        asst = name == "assistant"
        self._stack.setCurrentIndex(1 if asst else 0)
        self._tab_log.setChecked(not asst)
        self._tab_asst.setChecked(asst)
        if asst:
            self.panel._input.setFocus()
            self.panel.check_model_update()
        if remember and self.store.data.get("tab") != name:
            self.store.data["tab"] = name
            self.store.save()

    # ── agrandissement ──
    def set_root(self, root_layout: QLayout, zone: QWidget):
        """`root_layout` : la colonne de gauche ; `zone` : son enfant qui contient ce dock."""
        self._root_layout, self._zone = root_layout, zone

    def _hide_siblings(self, layout: QLayout):
        for i in range(layout.count()):
            item = layout.itemAt(i)
            wdg, sub = item.widget(), item.layout()
            if wdg is not None:
                if wdg is self:
                    continue
                if wdg.isAncestorOf(self):
                    if wdg.layout() is not None:
                        self._hide_siblings(wdg.layout())
                elif wdg.isVisible():
                    wdg.hide()
                    self._hidden.append(wdg)
            elif sub is not None:
                self._hide_siblings(sub)

    def set_expanded(self, on: bool):
        if self._root_layout is None or on == self._expanded:
            return
        self._expanded = on
        if on:
            self._hidden = []
            self._hide_siblings(self._root_layout)
            self._root_layout.setStretchFactor(self._zone, 1000)
            self._root_layout.setAlignment(self._zone, Qt.Alignment())
            self.show_tab("assistant")
        else:
            for wdg in self._hidden:
                wdg.show()
            self._hidden = []
            self._root_layout.setStretchFactor(self._zone, 0)
            self._root_layout.setAlignment(self._zone, Qt.AlignHCenter)
        self._btn_expand.setText("⤡" if on else "⤢")
        self.expanded_changed.emit(on)
