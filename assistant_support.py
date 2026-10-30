"""
assistant_support.py — Dépannage : les problèmes que les clients nous signalent par mail.

Chaque sujet = des motifs reconnus sur la phrase normalisée (assistant_nlu.normalize)
et une réponse écrite à la main dans les 6 langues. Rien n'est inventé par le modèle :
il reconnaît au mieux le sujet, la réponse vient d'ici.

Un sujet est reconnu si un de ses motifs « seuls » trouve, ou si son sujet ET un signe
de panne apparaissent dans la phrase. L'ordre compte : du plus précis au plus vague.
"""
import re

SUPPORT_EMAIL = "nicolas@mystrow.fr"


def _re(*alts):
    return re.compile(r"(?<![a-z])(?:" + "|".join(alts) + r")(?![a-z])")


# Signe de panne (phrase normalisée : sans accents, ponctuation → espaces).
PROBLEM = re.compile(
    r"(?<![a-z])(?:(?:ne|n)\s+(?:[a-z]+\s+){0,3}?(?:pas|plus|rien|jamais)|"
    r"(?:trouve|trouves|vois|voit|arrive|apparait|affiche|detecte|reconnait|marche|fonctionne|repond|connecte|"
    r"ouvre|lance|demarre|allume|sort|reagit|installe|charge|s ouvre|s allume|s affiche)\s+(?:pas|plus|jamais|rien)|pas detecte|pas detectee|pas reconnu|"
    r"pas reconnue|marche pas|marche plus|fonctionne pas|fonctionne plus|rien ne|rien|aucun|aucune|bug|bugge|beug|"
    r"plante|crash|crashe|bloque|probleme|souci|impossible|a coupe|ont coupe|perdu|perdue|"
    r"not|doesn t|don t|won t|can t|cannot|isn t|nothing|no signal|problem|issue|broken|fails|failed|"
    r"stopped|anymore|no longer|"
    r"no funciona|no detecta|no aparece|no conecta|no se|no responde|nada|ningun|ninguna|problema|falla|"
    r"funktioniert nicht|geht nicht|nicht erkannt|nicht gefunden|kein|keine|nichts|nicht|kaputt|"
    r"nao funciona|nao|nada|nenhum|nenhuma|avaria)(?![a-z])"
    r"|ない|しない|できない|動かない|つながらない|認識しない")

_FIXTURE = r"lyres?|projos?|projecteurs?|spots?|wash|par|pars|moving heads?|lights?|fixtures?|focos?|cabezas moviles|" \
           r"scheinwerfer|moving heads|projetores?|luzes|ライト|ムービング"

# (sujet, motifs seuls, motif de sujet qui demande aussi un signe de panne)
TOPICS = [
    ("integrity", [_re(r"integrite", r"integrity", r"integridad", r"integritat", r"integridade"), re.compile("整合性")], None),
    ("network", [_re(r"getaddrinfo", r"errno", r"11001", r"erreur reseau", r"erreur de reseau", r"network error",
                     r"error de red", r"netzwerkfehler", r"erro de rede", r"pas d internet", r"pas internet",
                     r"sans internet", r"no internet", r"sin internet", r"kein internet", r"sem internet"),
                 re.compile("ネットワークエラー")], None),
    ("antivirus", [_re(r"anti ?virus", r"antivirus", r"trend ?micro", r"avg", r"avast", r"norton", r"kaspersky",
                       r"defender", r"mcafee", r"bitdefender", r"eset", r"quarantaine", r"quarantine", r"cuarentena",
                       r"quarantane", r"quarentena", r"virus", r"virenschutz", r"trojan", r"troj", r"malware"),
                   re.compile("ウイルス|ウィルス")], None),
    ("licence_mail", [re.compile(
        # mail/licence + reçu + négation, dans n'importe quel ordre (« no me ha llegado el correo »)
        r"^(?=.*(?<![a-z])(?:mail|email|e mail|mails|courriel|correo|code|cle|licence|license|licencia|lizenz|"
        r"licenca|identifiants?|mot de passe|mdp|password|contrasena|passwort|senha)(?![a-z]))"
        r"(?=.*(?<![a-z])(?:recu|recue|recus|recois|arrive|arrivee|received|receive|got|get|recibido|recibi|llega|"
        r"llegado|erhalten|bekommen|angekommen|recebi|recebido|chegou)(?![a-z]))"
        r"(?=.*(?<![a-z])(?:pas|jamais|toujours pas|never|not|didn t|haven t|hasn t|no|nunca|nie|nicht|kein|keine|"
        r"nao)(?![a-z]))"),
                      _re(r"mot de passe oublie", r"oublie mon mot de passe", r"oublie le mot de passe", r"mdp oublie",
                          r"forgot my password", r"forgotten password", r"password reset", r"reset my password",
                          r"olvide mi contrasena", r"olvide la contrasena", r"passwort vergessen",
                          r"esqueci a senha", r"esqueci minha senha", r"esqueci me da senha"),
                      re.compile("メールが届かない|パスワードを忘れ")], None),
    ("mac_background", [re.compile(
        r"(?<![a-z])(?:fenetre|fenetres|window|windows|ventana|fenster|janela|arriere plan|background|minimise|"
        r"minimisee|reduit|reduite|segundo plano|hintergrund|plano de fundo)(?![a-z])"
        r".*(?<![a-z])(?:coupe|coupent|perd|perds|s arrete|s arretent|s eteint|s eteignent|decroche|drop|drops|drop out|stop|stops|"
        r"cuts|cut out|lost|lose|se corta|se apaga|se apagan|bricht ab|geht aus|gehen aus|corta|desliga|apagam)(?![a-z])"
        r"|(?<![a-z])(?:coupe|coupent|perd|s arrete|s eteint|s eteignent|drop|drops|drop out|stop|stops|cuts|se corta|se apaga|"
        r"bricht ab|geht aus|desliga|apagam)(?![a-z])"
        r".*(?<![a-z])(?:fenetre|window|ventana|fenster|janela|arriere plan|background|segundo plano|hintergrund)(?![a-z])")],
     None),
    ("fixture_mode", [re.compile(r"(?<![a-z])(?:" + _FIXTURE + r")(?![a-z]).*(?<![a-z])(?:toutes seules|tout seuls|"
                                 r"tout seul|toute seule|n importe quoi|au hasard|aleatoirement|by themselves|on their own|"
                                 r"randomly|crazy|go wild|solos|solas|por su cuenta|sin control|locos|von selbst|"
                                 r"von alleine|allein|verruckt|sozinhos|sozinhas|aleatoriamente|loucos)(?![a-z])"),
                      re.compile(r"(?<![a-z])(?:bougent|bouge|tournent|clignotent|s allument|changent|partent|move|moving|"
                                 r"se mueven|bewegen sich|mexem)(?![a-z]).*(?<![a-z])(?:toutes seules|tout seuls|tout seul|"
                                 r"n importe comment|by themselves|on their own|solos|solas|von selbst|sozinhos|sozinhas)(?![a-z])"),
                      re.compile("勝手に")], None),
    ("fixture_profile", [re.compile(r"(?<![a-z])(?:couleur|couleurs|gobo|gobos|roue|colou?rs?|colores?|farben?|cores?|"
                                    r"jaune|orange|rouge|bleu|vert)(?![a-z]).*(?<![a-z])(?:decale|decalee|decalees|decales|"
                                    r"mauvais|mauvaise|mauvaises|pas la bonne|pas les bonnes|pas le bon|pas les bons|faux|"
                                    r"fausse|fausses|inverse|inversee|inversees|inverses|"
                                    r"wrong|incorrect|mixed up|swapped|shifted|equivocad[oa]s?|incorrect[oa]s?|"
                                    r"falsch|vertauscht|errad[oa]s?|trocad[oa]s?)(?![a-z])"),
                         # « j'ai jaune au lieu d'orange » : un constat, pas « mets orange au lieu du rouge »
                         re.compile(r"(?<![a-z])(?:j ai|j obtiens|ca fait|ca donne|ca sort|on a|il y a|ils sont|elles sont|"
                                    r"c est|i get|i got|it shows|it gives|comes out|they are|tengo|sale|salen|da|ich habe|"
                                    r"kommt|es ist|tenho|sai|da)\s+(?:du |de l |de la |des |en )?[a-z]+\s+(?:au lieu d|"
                                    r"au lieu du|au lieu de|instead of|en lugar de|en vez de|statt|anstatt|em vez de)(?![a-z])"),
                         re.compile("色が違う|ゴボが違う")], None),
    ("strobe", [], re.compile(r"(?<![a-z])(?:strobe|strob|stroboscope|strobo|estrobo|stroboskop|estroboscopio|"
                              r"shutter|obturateur)(?![a-z])|ストロボ")),
    ("tablet_trouble", [re.compile(r"(?<![a-z])(?:site inaccessible|page inaccessible|site unreachable|can t reach this page|"
                           r"403|401|forbidden|unauthorized)(?![a-z])")],
     re.compile(r"(?<![a-z])(?:tablette|tablettes|telephone|ipad|smartphone|portable|tablet|tablets|phone|tableta|"
                r"telefono|movil|handy|telemovel|celular)(?![a-z])|タブレット|スマホ")),
    ("mac_launch", [_re(r"rebondit", r"rebondi", r"bounces", r"bouncing", r"rebota", r"springt", r"salta no dock")],
     re.compile(r"(?<![a-z])(?:ouvre|ouvrir|lance|lancer|demarre|demarrer|ferme|referme|open|opens|start|starts|"
                r"launch|launches|quits|closes|abre|abrir|inicia|arranca|cierra|startet|offnet|schliesst|fecha)(?![a-z])"
                r".*(?<![a-z])(?:mac|macos|macbook|imac|mac mini)(?![a-z])"
                r"|(?<![a-z])(?:mac|macos|macbook|imac|dock|mac mini)(?![a-z]).*(?<![a-z])(?:ouvre|ouvrir|lance|lancer|demarre|"
        r"demarrer|ferme|referme|rebondit|bounce|bounces|bouncing|open|opens|start|starts|launch|launches|quits|closes|"
        r"abre|abrir|inicia|arranca|cierra|startet|offnet|schliesst|abre|fecha|inicia)(?![a-z])")),
    ("update", [re.compile(r"(?<![a-z])(?:ancienne version|vieille version|meme version|old version|same version|"
                           r"version antigua|misma version|alte version|versao antiga|mesma versao)(?![a-z])")],
     re.compile(r"(?<![a-z])(?:mise a jour|mises a jour|maj|update|updates|updater|actualizacion|actualizar|"
                r"aktualisierung|update|atualizacao|atualizar)(?![a-z])|アップデート|更新")),
    # « ça marche dans QLC+ mais pas dans MyStrow » : le boîtier est pris par l'autre logiciel.
    ("usb_dmx", [re.compile(r"(?<![a-z])(?:qlc|qlc plus|freestyler|dmxcontrol|daslight|sunlite|lightkey)(?![a-z])"
                            r".*(?<![a-z])(?:mais pas|pas dans|pas avec|pas sur|but not|not in|not with|pero no|"
                            r"aber nicht|mas nao)(?![a-z])")], None),
    ("artnet", [], re.compile(r"(?<![a-z])(?:art ?net|node|noeud|nodes|reseau|ethernet|wi ?fi|ip|routeur|router|"
                              r"network|la red|netzwerk|rede)(?![a-z])|ネットワーク|ノード")),
    ("usb_dmx", [], re.compile(r"(?<![a-z])(?:boitier|boitiers|interface|interfaces|dongle|enttec|open dmx|opto|usb|"
                               r"box|interfaz|schnittstelle|adaptateur|adapter|adaptador|cable dmx|sortie dmx|dmx)(?![a-z])"
                               r"|インターフェース|インターフェイス")),
]


def topic(t: str):
    """Sujet de dépannage de la phrase normalisée `t`, ou None."""
    has_problem = None
    for key, alone, subject in TOPICS:
        if any(p.search(t) for p in alone):
            return key
        if subject is not None and subject.search(t):
            if has_problem is None:
                has_problem = bool(PROBLEM.search(t))
            if has_problem:
                return key
    return None


# Réponses : courtes, concrètes, une commande à dire quand MyStrow peut aider.
ANSWERS = {
    "usb_dmx": {
        "fr": "🔌 Boîtier USB-DMX muet ou non détecté :\n1) Ferme tout autre logiciel lumière (QLC+, Freestyler…) : un seul logiciel à la fois peut utiliser le boîtier.\n2) Change de câble ou de port USB (évite les hubs).\n3) Dis « ouvre la sortie DMX » et choisis ton interface. Pour un Open DMX ou un boîtier FTDI, installe le pilote FTDI si l'assistant le propose.\n4) Dis « pourquoi ça marche pas ? » : je vérifie l'état de MyStrow.",
        "en": "🔌 USB-DMX box silent or not detected:\n1) Close any other lighting software (QLC+, Freestyler…): only one program at a time can use the box.\n2) Try another USB cable or port (avoid hubs).\n3) Say “open the DMX output” and pick your interface. For an Open DMX or FTDI box, install the FTDI driver if the wizard offers it.\n4) Say “why isn't it working?”: I'll check MyStrow's state.",
        "es": "🔌 Interfaz USB-DMX muda o no detectada:\n1) Cierra cualquier otro programa de luces (QLC+, Freestyler…): solo un programa a la vez puede usar la interfaz.\n2) Prueba otro cable o puerto USB (evita los hubs).\n3) Di «abre la salida DMX» y elige tu interfaz. Para un Open DMX o una interfaz FTDI, instala el driver FTDI si el asistente lo propone.\n4) Di «¿por qué no funciona?»: reviso el estado de MyStrow.",
        "de": "🔌 USB-DMX-Box stumm oder nicht erkannt:\n1) Schließe jede andere Lichtsoftware (QLC+, Freestyler…): nur ein Programm kann die Box gleichzeitig nutzen.\n2) Anderes USB-Kabel oder anderen Port probieren (keine Hubs).\n3) Sag „öffne DMX Ausgang“ und wähle dein Interface. Bei Open DMX oder FTDI-Boxen den FTDI-Treiber installieren, wenn der Assistent ihn anbietet.\n4) Sag „warum geht es nicht?“: ich prüfe den Zustand von MyStrow.",
        "pt": "🔌 Interface USB-DMX muda ou não detetada:\n1) Feche qualquer outro programa de luz (QLC+, Freestyler…): só um programa de cada vez pode usar a interface.\n2) Experimente outro cabo ou porta USB (evite hubs).\n3) Diga «abre a saída DMX» e escolha a interface. Para um Open DMX ou interface FTDI, instale o driver FTDI se o assistente o propuser.\n4) Diga «porque não funciona?»: verifico o estado do MyStrow.",
        "ja": "🔌 USB-DMXボックスが反応しない・認識されない：\n1) 他の照明ソフト（QLC+、Freestyler など）を閉じてください。ボックスを使えるのは同時に1つのソフトだけです。\n2) 別のUSBケーブルやポートを試してください（ハブは避ける）。\n3)「DMX出力を開いて」と言ってインターフェースを選択。Open DMX や FTDI のボックスは、案内に従って FTDI ドライバーを入れてください。\n4)「なぜ動かない？」と言えば MyStrow の状態を確認します。",
    },
    "artnet": {
        "fr": "🌐 Node Art-Net introuvable :\n1) Le node et l'ordinateur doivent être sur le même réseau, de préférence en câble Ethernet plutôt qu'en Wi-Fi.\n2) Leurs adresses IP doivent être dans la même plage : souvent 2.x.x.x ou 192.168.x.x (voir l'écran ou la notice du node).\n3) Autorise MyStrow dans le pare-feu (Windows le demande au premier lancement).\n4) Dis « ouvre la sortie DMX », choisis Art-Net et sélectionne ton node. Sur Mac, vérifie qu'elle n'est pas restée sur « USB ».",
        "en": "🌐 Art-Net node not found:\n1) The node and the computer must be on the same network, preferably over Ethernet rather than Wi-Fi.\n2) Their IP addresses must be in the same range: often 2.x.x.x or 192.168.x.x (see the node's screen or manual).\n3) Allow MyStrow in the firewall (Windows asks on first launch).\n4) Say “open the DMX output”, choose Art-Net and select your node. On Mac, check it didn't stay on “USB”.",
        "es": "🌐 Node Art-Net no encontrado:\n1) El node y el ordenador deben estar en la misma red, mejor por cable Ethernet que por Wi-Fi.\n2) Sus direcciones IP deben estar en el mismo rango: a menudo 2.x.x.x o 192.168.x.x (ver la pantalla o el manual del node).\n3) Autoriza MyStrow en el cortafuegos (Windows lo pide al primer arranque).\n4) Di «abre la salida DMX», elige Art-Net y selecciona tu node. En Mac, comprueba que no se quedó en «USB».",
        "de": "🌐 Art-Net-Node nicht gefunden:\n1) Node und Computer müssen im selben Netzwerk sein, am besten per Ethernet-Kabel statt WLAN.\n2) Ihre IP-Adressen müssen im selben Bereich liegen: oft 2.x.x.x oder 192.168.x.x (siehe Display oder Anleitung des Nodes).\n3) MyStrow in der Firewall zulassen (Windows fragt beim ersten Start).\n4) Sag „öffne DMX Ausgang“, wähle Art-Net und deinen Node. Auf dem Mac prüfen, dass er nicht auf „USB“ geblieben ist.",
        "pt": "🌐 Node Art-Net não encontrado:\n1) O node e o computador têm de estar na mesma rede, de preferência por cabo Ethernet e não por Wi-Fi.\n2) Os endereços IP têm de estar na mesma gama: muitas vezes 2.x.x.x ou 192.168.x.x (ver o ecrã ou o manual do node).\n3) Autorize o MyStrow na firewall (o Windows pergunta no primeiro arranque).\n4) Diga «abre a saída DMX», escolha Art-Net e selecione o node. No Mac, verifique que não ficou em «USB».",
        "ja": "🌐 Art-Netノードが見つからない：\n1) ノードとPCを同じネットワークに。Wi-Fiより有線LANがおすすめです。\n2) IPアドレスを同じ範囲に（多くは 2.x.x.x か 192.168.x.x。ノードの画面か説明書を確認）。\n3) ファイアウォールで MyStrow を許可してください（Windows は初回起動時に確認します）。\n4)「DMX出力を開いて」と言い、Art-Net を選んでノードを選択。Mac では「USB」のままになっていないか確認してください。",
    },
    "mac_background": {
        "fr": "🍎 Sur Mac, le DMX qui décroche quand tu changes de fenêtre vient de la mise en veille des apps en arrière-plan (App Nap). C'est corrigé dans les dernières versions : mets MyStrow à jour depuis mystrow.fr. En attendant, garde la fenêtre MyStrow visible.",
        "en": "🍎 On Mac, DMX dropping when you switch windows comes from macOS putting background apps to sleep (App Nap). It's fixed in recent versions: update MyStrow from mystrow.fr. Until then, keep the MyStrow window visible.",
        "es": "🍎 En Mac, el DMX que se corta al cambiar de ventana viene de que macOS duerme las apps en segundo plano (App Nap). Está corregido en las últimas versiones: actualiza MyStrow desde mystrow.fr. Mientras tanto, deja la ventana de MyStrow visible.",
        "de": "🍎 Auf dem Mac bricht DMX beim Fensterwechsel ab, weil macOS Apps im Hintergrund schlafen legt (App Nap). In aktuellen Versionen behoben: MyStrow über mystrow.fr aktualisieren. Bis dahin das MyStrow-Fenster sichtbar lassen.",
        "pt": "🍎 No Mac, o DMX que cai ao mudar de janela vem do macOS adormecer as apps em segundo plano (App Nap). Está corrigido nas últimas versões: atualize o MyStrow em mystrow.fr. Até lá, mantenha a janela do MyStrow visível.",
        "ja": "🍎 Mac でウィンドウを切り替えると DMX が途切れるのは、macOS が背面のアプリを休止させる機能（App Nap）が原因です。最新版で修正済みなので mystrow.fr から MyStrow を更新してください。それまでは MyStrow のウィンドウを表示したままにしてください。",
    },
    "fixture_mode": {
        "fr": "🎛 Projecteurs qui bougent ou changent tout seuls : presque toujours, le mode DMX réglé sur le projecteur (son nombre de canaux, dans son menu ou ses dipswitchs) n'est pas celui du patch. Exemple : projecteur en 7 canaux, patché en 9 canaux → les canaux se décalent et l'un tombe sur « auto/son ».\n1) Regarde le mode affiché sur le projecteur.\n2) Dis « ouvre le patch » et choisis le même mode (ou la fiche exacte du modèle).\n3) Vérifie que son adresse DMX est celle du patch.",
        "en": "🎛 Fixtures moving or changing on their own: almost always, the DMX mode set on the fixture (its channel count, in its menu or dipswitches) isn't the one in the patch. Example: fixture in 7 channels, patched as 9 → channels shift and one lands on “auto/sound”.\n1) Check the mode shown on the fixture.\n2) Say “open the patch” and choose the same mode (or the exact profile for the model).\n3) Check its DMX address matches the patch.",
        "es": "🎛 Focos que se mueven o cambian solos: casi siempre, el modo DMX del foco (su número de canales, en su menú o dipswitches) no es el del patch. Ejemplo: foco en 7 canales, en el patch con 9 → los canales se desplazan y uno cae en «auto/sonido».\n1) Mira el modo que muestra el foco.\n2) Di «abre el patch» y elige el mismo modo (o la ficha exacta del modelo).\n3) Comprueba que su dirección DMX es la del patch.",
        "de": "🎛 Scheinwerfer bewegen oder ändern sich von selbst: fast immer passt der am Gerät eingestellte DMX-Modus (Kanalzahl, im Menü oder per Dipschalter) nicht zum Patch. Beispiel: Gerät auf 7 Kanälen, gepatcht mit 9 → die Kanäle verschieben sich und einer landet auf „Auto/Sound“.\n1) Den am Gerät angezeigten Modus ablesen.\n2) Sag „öffne den Patch“ und wähle denselben Modus (oder das exakte Profil des Modells).\n3) Prüfen, dass die DMX-Adresse dem Patch entspricht.",
        "pt": "🎛 Projetores que se mexem ou mudam sozinhos: quase sempre, o modo DMX do projetor (número de canais, no menu ou nos dipswitches) não é o do patch. Exemplo: projetor em 7 canais, no patch com 9 → os canais deslocam-se e um cai em «auto/som».\n1) Veja o modo indicado no projetor.\n2) Diga «abre o patch» e escolha o mesmo modo (ou a ficha exata do modelo).\n3) Verifique que o endereço DMX é o do patch.",
        "ja": "🎛 機材が勝手に動く・色が変わる：ほとんどの場合、機材側のDMXモード（チャンネル数。メニューやディップスイッチで設定）がパッチと違います。例：機材は7ch、パッチは9ch → チャンネルがずれて1つが「オート／サウンド」に当たります。\n1) 機材に表示されているモードを確認。\n2)「パッチを開いて」と言い、同じモード（またはその機種の正確なプロファイル）を選択。\n3) DMXアドレスがパッチと同じか確認してください。",
    },
    "fixture_profile": {
        "fr": "🎨 Couleurs ou gobos qui ne correspondent pas : la fiche du projecteur dans le patch n'est pas la bonne (ou pas dans le bon mode).\n1) Dis « ajoute » suivi de la marque et du modèle (ex. « ajoute une lyre Shehds ») pour prendre sa fiche exacte dans la bibliothèque, dans le mode réglé sur le projecteur.\n2) Pour une roue de couleurs ou de gobos, ouvre le patch et calibre la roue.\n3) Ton modèle n'est pas dans la bibliothèque ? Envoie-nous sa notice (tableau des canaux DMX), on l'ajoute.",
        "en": "🎨 Colours or gobos don't match: the fixture's profile in the patch is wrong (or in the wrong mode).\n1) Say “add” followed by the brand and model (e.g. “add a Shehds moving head”) to take its exact profile from the library, in the mode set on the fixture.\n2) For a colour or gobo wheel, open the patch and calibrate the wheel.\n3) Your model isn't in the library? Send us its manual (DMX channel chart) and we'll add it.",
        "es": "🎨 Colores o gobos que no corresponden: la ficha del foco en el patch no es la correcta (o no está en el modo correcto).\n1) Di «añade» seguido de la marca y el modelo (ej. «añade una cabeza móvil Shehds») para tomar su ficha exacta de la biblioteca, en el modo del foco.\n2) Para una rueda de colores o gobos, abre el patch y calibra la rueda.\n3) ¿Tu modelo no está en la biblioteca? Envíanos su manual (tabla de canales DMX) y lo añadimos.",
        "de": "🎨 Farben oder Gobos stimmen nicht: das Profil im Patch ist falsch (oder im falschen Modus).\n1) Sag „füge hinzu“ mit Marke und Modell (z. B. „füge einen Shehds Moving Head hinzu“), um das exakte Profil aus der Bibliothek zu nehmen, im am Gerät eingestellten Modus.\n2) Bei Farb- oder Goborad: Patch öffnen und das Rad kalibrieren.\n3) Dein Modell fehlt in der Bibliothek? Schick uns die Anleitung (DMX-Kanaltabelle), wir fügen es hinzu.",
        "pt": "🎨 Cores ou gobos que não correspondem: a ficha do projetor no patch não é a certa (ou não está no modo certo).\n1) Diga «adiciona» seguido da marca e do modelo (ex. «adiciona uma cabeça móvel Shehds») para usar a ficha exata da biblioteca, no modo do projetor.\n2) Para uma roda de cores ou gobos, abra o patch e calibre a roda.\n3) O seu modelo não está na biblioteca? Envie-nos o manual (tabela de canais DMX) e adicionamo-lo.",
        "ja": "🎨 色やゴボが合わない：パッチの機材プロファイルが違う（またはモードが違う）可能性があります。\n1)「追加」とメーカー名・機種名を言うと（例：「Shehds のムービングを追加」）、ライブラリから正確なプロファイルを機材と同じモードで使えます。\n2) カラーホイールやゴボホイールは、パッチを開いてホイールを調整してください。\n3) ライブラリに機種がない場合は、説明書（DMXチャンネル表）を送ってください。追加します。",
    },
    "strobe": {
        "fr": "⚡ Strobe qui ne marche pas sur un projecteur : sa fiche n'a pas le bon canal strobe/shutter, ou le projecteur n'est pas dans le mode du patch.\n1) Dis « ouvre le patch » et vérifie le mode et la fiche du projecteur.\n2) Mets MyStrow à jour : plusieurs fiches avec un canal « shutter » ont été corrigées.\n3) Toujours rien ? Envoie-nous la notice du projecteur, on corrige sa fiche.",
        "en": "⚡ Strobe not working on a fixture: its profile doesn't have the right strobe/shutter channel, or the fixture isn't in the patch's mode.\n1) Say “open the patch” and check the fixture's mode and profile.\n2) Update MyStrow: several profiles with a “shutter” channel were fixed.\n3) Still nothing? Send us the fixture's manual and we'll fix its profile.",
        "es": "⚡ El estrobo no funciona en un foco: su ficha no tiene el canal estrobo/shutter correcto, o el foco no está en el modo del patch.\n1) Di «abre el patch» y revisa el modo y la ficha del foco.\n2) Actualiza MyStrow: se corrigieron varias fichas con canal «shutter».\n3) ¿Nada? Envíanos el manual del foco y corregimos su ficha.",
        "de": "⚡ Strobe funktioniert an einem Gerät nicht: das Profil hat nicht den richtigen Strobe-/Shutter-Kanal, oder das Gerät ist nicht im Modus des Patches.\n1) Sag „öffne den Patch“ und prüfe Modus und Profil.\n2) MyStrow aktualisieren: mehrere Profile mit „Shutter“-Kanal wurden korrigiert.\n3) Immer noch nichts? Schick uns die Anleitung, wir korrigieren das Profil.",
        "pt": "⚡ O strobe não funciona num projetor: a ficha não tem o canal strobe/shutter certo, ou o projetor não está no modo do patch.\n1) Diga «abre o patch» e verifique o modo e a ficha do projetor.\n2) Atualize o MyStrow: várias fichas com canal «shutter» foram corrigidas.\n3) Continua sem funcionar? Envie-nos o manual do projetor e corrigimos a ficha.",
        "ja": "⚡ 機材でストロボが効かない：プロファイルのストロボ／シャッターチャンネルが合っていないか、機材のモードがパッチと違います。\n1)「パッチを開いて」と言い、モードとプロファイルを確認。\n2) MyStrow を更新してください（シャッターチャンネルのプロファイルをいくつか修正済み）。\n3) それでもだめなら説明書を送ってください。プロファイルを直します。",
    },
    "tablet_trouble": {
        "fr": "📱 Tablette qui ne se connecte pas :\n1) La tablette et l'ordinateur doivent être sur le même Wi-Fi (pas le réseau invité, pas la 4G).\n2) Autorise MyStrow dans le pare-feu de l'ordinateur.\n3) Sur Mac, si la page affiche une erreur 403 ou 401 : le récepteur AirPlay occupe le port de MyStrow. Désactive-le dans Réglages Système > Général > AirDrop et Handoff > Récepteur AirPlay.\n4) Dis « ouvre la tablette » et rescanne le QR code.",
        "en": "📱 Tablet won't connect:\n1) Tablet and computer must be on the same Wi-Fi (not a guest network, not 4G).\n2) Allow MyStrow in the computer's firewall.\n3) On Mac, if the page shows a 403 or 401 error: the AirPlay Receiver is using MyStrow's port. Turn it off in System Settings > General > AirDrop & Handoff > AirPlay Receiver.\n4) Say “open the tablet” and scan the QR code again.",
        "es": "📱 La tableta no se conecta:\n1) La tableta y el ordenador deben estar en la misma Wi-Fi (ni red de invitados ni 4G).\n2) Autoriza MyStrow en el cortafuegos del ordenador.\n3) En Mac, si la página muestra un error 403 o 401: el Receptor AirPlay ocupa el puerto de MyStrow. Desactívalo en Ajustes del Sistema > General > AirDrop y Handoff > Receptor AirPlay.\n4) Di «abre la tableta» y vuelve a escanear el código QR.",
        "de": "📱 Tablet verbindet sich nicht:\n1) Tablet und Computer müssen im selben WLAN sein (kein Gastnetz, kein Mobilfunk).\n2) MyStrow in der Firewall des Computers zulassen.\n3) Auf dem Mac, wenn die Seite Fehler 403 oder 401 zeigt: der AirPlay-Empfänger belegt den Port von MyStrow. Deaktivieren unter Systemeinstellungen > Allgemein > AirDrop & Handoff > AirPlay-Empfänger.\n4) Sag „öffne Tablet“ und scanne den QR-Code erneut.",
        "pt": "📱 O tablet não liga:\n1) O tablet e o computador têm de estar na mesma rede Wi-Fi (nem rede de convidados, nem 4G).\n2) Autorize o MyStrow na firewall do computador.\n3) No Mac, se a página mostrar o erro 403 ou 401: o Recetor AirPlay ocupa a porta do MyStrow. Desative-o em Definições do Sistema > Geral > AirDrop e Handoff > Recetor AirPlay.\n4) Diga «abre o tablet» e leia de novo o código QR.",
        "ja": "📱 タブレットがつながらない：\n1) タブレットとPCを同じWi-Fiに（ゲストネットワークやモバイル回線は不可）。\n2) PCのファイアウォールで MyStrow を許可してください。\n3) Mac でページに 403 や 401 のエラーが出る場合：AirPlay レシーバーが MyStrow のポートを使っています。システム設定 > 一般 > AirDrop と Handoff > AirPlay レシーバー をオフにしてください。\n4)「タブレットを開いて」と言って QR コードを読み直してください。",
    },
    "antivirus": {
        "fr": "🛡 Antivirus qui bloque ou supprime MyStrow (Trend Micro, AVG, Avast…) : c'est une fausse alerte, MyStrow est signé numériquement.\n1) Dans ton antivirus, restaure MyStrow de la quarantaine et ajoute une exception pour son dossier.\n2) Réinstalle MyStrow depuis mystrow.fr (un fichier a pu être abîmé).\nSur Mac, un antivirus qui bloque un fichier peut faire planter MyStrow ~30 secondes après le lancement : même remède.",
        "en": "🛡 Antivirus blocking or deleting MyStrow (Trend Micro, AVG, Avast…): it's a false alarm, MyStrow is digitally signed.\n1) In your antivirus, restore MyStrow from quarantine and add an exception for its folder.\n2) Reinstall MyStrow from mystrow.fr (a file may have been damaged).\nOn Mac, an antivirus blocking a file can make MyStrow crash ~30 seconds after launch: same fix.",
        "es": "🛡 Antivirus que bloquea o borra MyStrow (Trend Micro, AVG, Avast…): es una falsa alarma, MyStrow está firmado digitalmente.\n1) En tu antivirus, restaura MyStrow de la cuarentena y añade una excepción para su carpeta.\n2) Reinstala MyStrow desde mystrow.fr (un archivo pudo dañarse).\nEn Mac, un antivirus que bloquea un archivo puede cerrar MyStrow ~30 segundos tras abrirlo: mismo remedio.",
        "de": "🛡 Antivirus blockiert oder löscht MyStrow (Trend Micro, AVG, Avast…): das ist ein Fehlalarm, MyStrow ist digital signiert.\n1) MyStrow im Antivirus aus der Quarantäne holen und eine Ausnahme für seinen Ordner anlegen.\n2) MyStrow von mystrow.fr neu installieren (eine Datei kann beschädigt sein).\nAuf dem Mac kann ein Antivirus, der eine Datei blockiert, MyStrow ~30 Sekunden nach dem Start abstürzen lassen: gleiche Lösung.",
        "pt": "🛡 Antivírus que bloqueia ou apaga o MyStrow (Trend Micro, AVG, Avast…): é um falso alarme, o MyStrow tem assinatura digital.\n1) No antivírus, restaure o MyStrow da quarentena e adicione uma exceção para a pasta dele.\n2) Reinstale o MyStrow em mystrow.fr (um ficheiro pode ter ficado danificado).\nNo Mac, um antivírus que bloqueia um ficheiro pode fazer o MyStrow fechar ~30 segundos depois de abrir: mesma solução.",
        "ja": "🛡 ウイルス対策ソフトが MyStrow をブロック・削除する（Trend Micro、AVG、Avast など）：誤検知です。MyStrow はデジタル署名されています。\n1) ウイルス対策ソフトで MyStrow を隔離から復元し、フォルダーを除外に追加してください。\n2) mystrow.fr から MyStrow を再インストールしてください（ファイルが壊れている可能性があります）。\nMac では、ファイルがブロックされると起動から約30秒で落ちることがあります。対処は同じです。",
    },
    "integrity": {
        "fr": "🔒 « L'intégrité de l'application n'a pas pu être vérifiée » : un fichier de MyStrow a été modifié, souvent par une mise à jour interrompue ou un antivirus.\n1) Télécharge la dernière version sur mystrow.fr et installe-la par-dessus (tes shows et réglages sont conservés).\n2) Si ça revient, ajoute une exception pour MyStrow dans ton antivirus.",
        "en": "🔒 “The application's integrity could not be verified”: a MyStrow file was changed, often by an interrupted update or an antivirus.\n1) Download the latest version from mystrow.fr and install it over the old one (your shows and settings are kept).\n2) If it comes back, add an exception for MyStrow in your antivirus.",
        "es": "🔒 «No se pudo verificar la integridad de la aplicación»: un archivo de MyStrow cambió, a menudo por una actualización interrumpida o un antivirus.\n1) Descarga la última versión en mystrow.fr e instálala encima (tus shows y ajustes se conservan).\n2) Si vuelve a pasar, añade una excepción para MyStrow en tu antivirus.",
        "de": "🔒 „Die Integrität der Anwendung konnte nicht geprüft werden“: eine MyStrow-Datei wurde verändert, oft durch ein abgebrochenes Update oder ein Antivirus.\n1) Die neueste Version von mystrow.fr laden und darüber installieren (Shows und Einstellungen bleiben erhalten).\n2) Kommt es wieder, eine Ausnahme für MyStrow im Antivirus anlegen.",
        "pt": "🔒 «Não foi possível verificar a integridade da aplicação»: um ficheiro do MyStrow foi alterado, muitas vezes por uma atualização interrompida ou um antivírus.\n1) Descarregue a última versão em mystrow.fr e instale-a por cima (os seus shows e definições são mantidos).\n2) Se voltar a acontecer, adicione uma exceção para o MyStrow no antivírus.",
        "ja": "🔒「アプリの整合性を確認できませんでした」：MyStrow のファイルが変更されています（更新の中断やウイルス対策ソフトが原因のことが多いです）。\n1) mystrow.fr から最新版をダウンロードして上書きインストールしてください（ショーと設定は残ります）。\n2) 再発する場合は、ウイルス対策ソフトで MyStrow を除外に追加してください。",
    },
    "update": {
        "fr": "⬆ Mise à jour qui ne s'applique pas : télécharge la dernière version sur mystrow.fr et installe-la par-dessus, tes shows et réglages sont conservés. Sur Mac, ferme MyStrow, ouvre le DMG et remplace l'app dans le dossier Applications.",
        "en": "⬆ Update not applying: download the latest version from mystrow.fr and install it over the old one, your shows and settings are kept. On Mac, quit MyStrow, open the DMG and replace the app in the Applications folder.",
        "es": "⬆ La actualización no se aplica: descarga la última versión en mystrow.fr e instálala encima, tus shows y ajustes se conservan. En Mac, cierra MyStrow, abre el DMG y reemplaza la app en la carpeta Aplicaciones.",
        "de": "⬆ Update wird nicht übernommen: die neueste Version von mystrow.fr laden und darüber installieren, Shows und Einstellungen bleiben erhalten. Auf dem Mac MyStrow beenden, die DMG öffnen und die App im Ordner Programme ersetzen.",
        "pt": "⬆ A atualização não se aplica: descarregue a última versão em mystrow.fr e instale-a por cima, os shows e definições são mantidos. No Mac, feche o MyStrow, abra o DMG e substitua a app na pasta Aplicações.",
        "ja": "⬆ 更新が反映されない：mystrow.fr から最新版をダウンロードして上書きインストールしてください（ショーと設定は残ります）。Mac では MyStrow を終了し、DMG を開いてアプリケーションフォルダーのアプリを置き換えてください。",
    },
    "mac_launch": {
        "fr": "🍎 MyStrow ne s'ouvre pas sur Mac (l'icône rebondit puis disparaît) :\n1) Vérifie ta version de macOS (menu  > À propos de ce Mac) : les Mac Apple Silicon (M1 à M5) demandent macOS 13 Ventura ou plus récent, les Mac Intel macOS 11 Big Sur ou plus récent.\n2) Si MyStrow se ferme une trentaine de secondes après s'être ouvert, c'est souvent un antivirus (AVG…) : ajoute une exception et réinstalle.\n3) Retélécharge le DMG sur mystrow.fr, en choisissant bien Apple Silicon ou Intel.",
        "en": "🍎 MyStrow won't open on Mac (the icon bounces then disappears):\n1) Check your macOS version ( menu > About This Mac): Apple Silicon Macs (M1 to M5) need macOS 13 Ventura or later, Intel Macs macOS 11 Big Sur or later.\n2) If MyStrow closes about thirty seconds after opening, it's often an antivirus (AVG…): add an exception and reinstall.\n3) Download the DMG again from mystrow.fr, picking Apple Silicon or Intel correctly.",
        "es": "🍎 MyStrow no se abre en Mac (el icono rebota y desaparece):\n1) Mira tu versión de macOS (menú  > Acerca de este Mac): los Mac Apple Silicon (M1 a M5) necesitan macOS 13 Ventura o posterior, los Mac Intel macOS 11 Big Sur o posterior.\n2) Si MyStrow se cierra unos treinta segundos después de abrirse, suele ser un antivirus (AVG…): añade una excepción y reinstala.\n3) Vuelve a descargar el DMG en mystrow.fr, eligiendo bien Apple Silicon o Intel.",
        "de": "🍎 MyStrow öffnet sich auf dem Mac nicht (das Symbol hüpft und verschwindet):\n1) macOS-Version prüfen (Menü  > Über diesen Mac): Apple-Silicon-Macs (M1 bis M5) brauchen macOS 13 Ventura oder neuer, Intel-Macs macOS 11 Big Sur oder neuer.\n2) Schließt sich MyStrow etwa dreißig Sekunden nach dem Öffnen, ist es oft ein Antivirus (AVG…): Ausnahme anlegen und neu installieren.\n3) Die DMG erneut von mystrow.fr laden und dabei Apple Silicon oder Intel richtig wählen.",
        "pt": "🍎 O MyStrow não abre no Mac (o ícone salta e desaparece):\n1) Verifique a versão do macOS (menu  > Acerca deste Mac): os Mac Apple Silicon (M1 a M5) precisam do macOS 13 Ventura ou mais recente, os Mac Intel do macOS 11 Big Sur ou mais recente.\n2) Se o MyStrow fecha uns trinta segundos depois de abrir, é muitas vezes um antivírus (AVG…): adicione uma exceção e reinstale.\n3) Descarregue de novo o DMG em mystrow.fr, escolhendo bem Apple Silicon ou Intel.",
        "ja": "🍎 Mac で MyStrow が開かない（アイコンが跳ねて消える）：\n1) macOS のバージョンを確認（ メニュー > この Mac について）。Apple シリコン（M1〜M5）は macOS 13 Ventura 以降、Intel Mac は macOS 11 Big Sur 以降が必要です。\n2) 開いて30秒ほどで閉じる場合は、ウイルス対策ソフト（AVG など）が原因のことが多いです。除外に追加して再インストールしてください。\n3) mystrow.fr から DMG を再ダウンロードしてください（Apple シリコン用か Intel 用かを正しく選択）。",
    },
    "licence_mail": {
        "fr": "✉ Mail de licence ou de mot de passe pas reçu :\n1) Regarde dans les spams / courrier indésirable (et l'onglet Promotions sur Gmail).\n2) Vérifie l'adresse tapée au paiement : une faute (ex. « @homail.com ») et le mail part dans le vide.\n3) Mot de passe oublié : utilise « Mot de passe oublié » dans la fenêtre de connexion de MyStrow.",
        "en": "✉ Licence or password email not received:\n1) Check your spam / junk folder (and the Promotions tab in Gmail).\n2) Check the address typed at checkout: a typo (e.g. “@homail.com”) and the email goes nowhere.\n3) Forgot your password: use “Forgot password” in MyStrow's sign-in window.",
        "es": "✉ No recibí el correo de licencia o de contraseña:\n1) Mira en spam / correo no deseado (y la pestaña Promociones en Gmail).\n2) Revisa la dirección escrita al pagar: una errata (ej. «@homail.com») y el correo no llega.\n3) Contraseña olvidada: usa «Contraseña olvidada» en la ventana de conexión de MyStrow.",
        "de": "✉ Lizenz- oder Passwort-Mail nicht erhalten:\n1) Im Spam-/Junk-Ordner nachsehen (und im Tab „Werbung“ bei Gmail).\n2) Die beim Kauf eingegebene Adresse prüfen: ein Tippfehler (z. B. „@homail.com“) und die Mail geht ins Leere.\n3) Passwort vergessen: „Passwort vergessen“ im Anmeldefenster von MyStrow nutzen.",
        "pt": "✉ Não recebi o e-mail de licença ou de palavra-passe:\n1) Veja no spam / lixo eletrónico (e no separador Promoções do Gmail).\n2) Verifique o endereço escrito no pagamento: um erro (ex. «@homail.com») e o e-mail não chega.\n3) Palavra-passe esquecida: use «Esqueci a palavra-passe» na janela de ligação do MyStrow.",
        "ja": "✉ ライセンスやパスワードのメールが届かない：\n1) 迷惑メールフォルダー（Gmail はプロモーションタブも）を確認してください。\n2) 購入時に入力したアドレスを確認してください（「@homail.com」などの打ち間違いだと届きません）。\n3) パスワードを忘れた場合は、MyStrow のログイン画面の「パスワードを忘れた」を使ってください。",
    },
    "network": {
        "fr": "📶 « Erreur réseau » ou « getaddrinfo failed » : MyStrow n'arrive pas à joindre internet (pas de connexion, Wi-Fi capté sans internet, ou souci DNS). Vérifie ta connexion puis réessaie. Pas d'inquiétude pour le spectacle : la licence fonctionne 7 jours sans internet, et la lumière n'en a pas besoin.",
        "en": "📶 “Network error” or “getaddrinfo failed”: MyStrow can't reach the internet (no connection, Wi-Fi without internet, or a DNS issue). Check your connection and try again. No worries for the show: the licence works 7 days offline, and the lighting doesn't need internet.",
        "es": "📶 «Error de red» o «getaddrinfo failed»: MyStrow no llega a internet (sin conexión, Wi-Fi sin internet o un problema de DNS). Revisa la conexión y vuelve a intentarlo. Tranquilo para el show: la licencia funciona 7 días sin internet y la luz no lo necesita.",
        "de": "📶 „Netzwerkfehler“ oder „getaddrinfo failed“: MyStrow erreicht das Internet nicht (keine Verbindung, WLAN ohne Internet oder DNS-Problem). Verbindung prüfen und erneut versuchen. Keine Sorge für die Show: die Lizenz läuft 7 Tage offline, und das Licht braucht kein Internet.",
        "pt": "📶 «Erro de rede» ou «getaddrinfo failed»: o MyStrow não chega à internet (sem ligação, Wi-Fi sem internet ou problema de DNS). Verifique a ligação e tente de novo. Sem preocupações para o espetáculo: a licença funciona 7 dias sem internet e a luz não precisa dela.",
        "ja": "📶「ネットワークエラー」や「getaddrinfo failed」：MyStrow がインターネットにつながりません（未接続、インターネットのないWi-Fi、DNSの問題）。接続を確認して再試行してください。本番は心配いりません。ライセンスはオフラインで7日間使え、照明にインターネットは不要です。",
    },
}

FOOTER = {
    "fr": "Toujours bloqué ? Écris-nous à {mail} avec une capture d'écran, on t'aide.",
    "en": "Still stuck? Email us at {mail} with a screenshot, we'll help.",
    "es": "¿Sigues bloqueado? Escríbenos a {mail} con una captura de pantalla, te ayudamos.",
    "de": "Immer noch nicht gelöst? Schreib uns an {mail} mit einem Screenshot, wir helfen.",
    "pt": "Continua bloqueado? Escreva-nos para {mail} com uma captura de ecrã, ajudamos.",
    "ja": "解決しない場合は、スクリーンショットを添えて {mail} までご連絡ください。",
}


# Tutos de la playlist « Les tutos de MyStrow » qui aident sur un sujet (vidéos en français).
VIDEOS = {
    "usb_dmx": "https://www.youtube.com/watch?v=cXyJaINXok8",          # Les bases du DMX (câblage)
    "fixture_mode": "https://www.youtube.com/watch?v=cXyJaINXok8",
}
VIDEO_LINE = {
    "fr": "🎬 Le tuto qui montre tout ça : {url}",
    "en": "🎬 Video tutorial (in French): {url}",
    "es": "🎬 Tutorial en vídeo (en francés): {url}",
    "de": "🎬 Video-Tutorial (auf Französisch): {url}",
    "pt": "🎬 Tutorial em vídeo (em francês): {url}",
    "ja": "🎬 動画チュートリアル（フランス語）：{url}",
}


def answer(key: str, lang: str) -> str:
    texts = ANSWERS[key]
    body = texts.get(lang) or texts["en"]
    if key in VIDEOS:
        body += "\n" + (VIDEO_LINE.get(lang) or VIDEO_LINE["en"]).format(url=VIDEOS[key])
    return body + "\n" + (FOOTER.get(lang) or FOOTER["en"]).format(mail=SUPPORT_EMAIL)
