/**
 * MyStrow Stream Deck Plugin — app.js
 *
 * Communique avec MyStrow via HTTP REST sur http://127.0.0.1:8765/api/
 * Documentation API : streamdeck_api.py dans le projet MyStrow
 */

const API_BASE    = "http://127.0.0.1:8765/api";
const POLL_MS     = 2000;   // intervalle de polling état (ms)

// ── Contexte Stream Deck ──────────────────────────────────────────────────────

var $SD = {
    ws:            null,
    pluginUUID:    null,
    registerEvent: null,

    // Map context → { action, settings }
    buttons: {},

    // Dernier état connu retourné par /api/state
    lastState: null,
};

// ── Point d'entrée — appelé par le Stream Deck software ──────────────────────

function connectElgatoStreamDeckSocket(port, pluginUUID, registerEvent, info) {
    $SD.pluginUUID    = pluginUUID;
    $SD.registerEvent = registerEvent;

    $SD.ws = new WebSocket("ws://127.0.0.1:" + port);

    $SD.ws.onopen = function () {
        _send({ event: registerEvent, uuid: pluginUUID });
        // Démarrer le polling état
        setInterval(_pollState, POLL_MS);
        _pollState();
    };

    $SD.ws.onmessage = function (evt) {
        var msg = JSON.parse(evt.data);
        _dispatch(msg);
    };
}

// ── Dispatcher événements Stream Deck ────────────────────────────────────────

function _dispatch(msg) {
    var event   = msg.event;
    var action  = msg.action;
    var context = msg.context;
    var payload = msg.payload || {};

    switch (event) {

        case "keyDown":
            _onKeyDown(action, context, payload);
            break;

        case "dialRotate":
            _onDialRotate(action, context, payload);
            break;

        case "dialDown":
            _onDialDown(action, context, payload);
            break;

        case "willAppear":
            $SD.buttons[context] = {
                action:     action,
                settings:   payload.settings || {},
                controller: payload.controller || "Keypad",  // "Encoder" sur Stream Deck+
            };
            if ($SD.lastState) _updateButton(context, action, payload.settings || {}, $SD.lastState);
            break;

        case "willDisappear":
            delete $SD.buttons[context];
            break;

        case "didReceiveSettings":
            if ($SD.buttons[context]) {
                $SD.buttons[context].settings = payload.settings || {};
            }
            break;
    }
}

// ── Gestion appui touche ──────────────────────────────────────────────────────

function _onKeyDown(action, context, payload) {
    var settings = (payload && payload.settings) ? payload.settings : {};

    switch (action) {

        case "com.mystrow.streamdeck.play":
            _apiPost("/play");
            break;

        case "com.mystrow.streamdeck.next":
            _apiPost("/next");
            break;

        case "com.mystrow.streamdeck.prev":
            _apiPost("/prev");
            break;

        case "com.mystrow.streamdeck.seq": {
            var seqRow = parseInt(settings.seq_row, 10);
            if (isNaN(seqRow)) seqRow = 0;
            _apiPost("/goto/" + seqRow);
            break;
        }

        case "com.mystrow.streamdeck.effect": {
            var idx = parseInt(settings.effect_idx, 10);
            if (isNaN(idx) || idx < 0 || idx > 7) idx = 0;
            _apiPost("/effect/" + idx);
            break;
        }

        case "com.mystrow.streamdeck.level": {
            var fader = parseInt(settings.fader_idx, 10);
            var val   = parseInt(settings.level_val, 10);
            if (isNaN(fader) || fader < 0 || fader > 8) fader = 0;
            if (isNaN(val)   || val   < 0 || val   > 100) val = 100;
            _apiPost("/level/" + fader + "/" + val);
            break;
        }

        case "com.mystrow.streamdeck.mute": {
            // Toggle : on lit l'état courant pour inverser
            var fi = parseInt(settings.fader_idx, 10);
            if (isNaN(fi) || fi < 0 || fi > 7) fi = 0;
            if ($SD.lastState && $SD.lastState.projectors && $SD.lastState.projectors[fi]) {
                var currentMute = $SD.lastState.projectors[fi].muted ? 1 : 0;
                _apiPost("/mute/" + fi + "/" + (1 - currentMute));
            } else {
                _apiPost("/mute/" + fi + "/1");
            }
            break;
        }

        case "com.mystrow.streamdeck.scene": {
            var mc  = parseInt(settings.mem_col, 10);
            var row = parseInt(settings.mem_row, 10);
            if (isNaN(mc)  || mc  < 0 || mc  > 7) mc  = 0;
            if (isNaN(row) || row < 0 || row > 7) row = 0;
            _apiPost("/scene/" + mc + "/" + row);
            break;
        }
    }
}

// ── Encodeur rotatif (Stream Deck+) ──────────────────────────────────────────

function _onDialRotate(action, context, payload) {
    var settings = $SD.buttons[context] ? $SD.buttons[context].settings : {};
    if (action === "com.mystrow.streamdeck.level") {
        var fader = parseInt(settings.fader_idx, 10);
        if (isNaN(fader)) fader = 0;
        var ticks = payload.ticks || 0;
        var delta = ticks * 5;  // 5% par cran
        var sign  = delta >= 0 ? "+" : "";
        _apiPost("/level/" + fader + "/" + sign + delta);

        // Feedback LCD immédiat (optimiste, sans attendre le polling)
        if ($SD.lastState && $SD.lastState.fader_levels) {
            var cur = ($SD.lastState.fader_levels[fader] || 0) + delta;
            cur = Math.max(0, Math.min(100, cur));
            $SD.lastState.fader_levels[fader] = cur;
            _setFeedback(context, cur);
        }
    }
}

function _onDialDown(action, context, payload) {
    var settings = $SD.buttons[context] ? $SD.buttons[context].settings : {};
    if (action === "com.mystrow.streamdeck.level") {
        var fader = parseInt(settings.fader_idx, 10);
        if (isNaN(fader)) fader = 0;
        _apiPost("/level/" + fader + "/100");  // reset à 100% en appuyant
        // Feedback LCD immédiat
        if ($SD.lastState && $SD.lastState.fader_levels) {
            $SD.lastState.fader_levels[fader] = 100;
        }
        _setFeedback(context, 100);
    }
}

// ── Polling état ──────────────────────────────────────────────────────────────

function _pollState() {
    _apiFetch("/state", function (state) {
        if (!state) return;
        $SD.lastState = state;
        // Mettre à jour tous les boutons visibles
        for (var ctx in $SD.buttons) {
            var btn = $SD.buttons[ctx];
            _updateButton(ctx, btn.action, btn.settings, state);
        }
    });
}

// ── Mise à jour visuelle des boutons ─────────────────────────────────────────

function _updateButton(context, action, settings, state) {
    switch (action) {

        case "com.mystrow.streamdeck.play":
            _setTitle(context, state.playing ? "⏸ PAUSE" : "▶ PLAY");
            _setState(context, state.playing ? 1 : 0);
            break;

        case "com.mystrow.streamdeck.next":
            _setTitle(context, "⏭ NEXT");
            break;

        case "com.mystrow.streamdeck.prev":
            _setTitle(context, "⏮ PREV");
            break;

        case "com.mystrow.streamdeck.seq": {
            var seqRow = parseInt(settings.seq_row, 10);
            if (isNaN(seqRow)) seqRow = 0;
            var seqItems = state.seq_items || [];
            var seqItem  = seqItems[seqRow];
            var seqTitle = seqItem ? seqItem.title : ("Piste " + (seqRow + 1));
            var isCurrent = (state.current_row === seqRow);
            _setTitle(context, (isCurrent ? "▶ " : "") + seqTitle.substring(0, 10));
            _setState(context, isCurrent ? 1 : 0);
            break;
        }

        case "com.mystrow.streamdeck.effect": {
            var idx = parseInt(settings.effect_idx, 10);
            if (isNaN(idx)) idx = 0;
            var effects = state.active_effects || [];
            var eff = null;
            for (var ei = 0; ei < effects.length; ei++) {
                if (effects[ei].index === idx) { eff = effects[ei]; break; }
            }
            var active  = eff && eff.active;
            var effName = (eff && eff.name) ? eff.name.substring(0, 8) : ("Effet " + (idx + 1));
            _setTitle(context, (active ? "✦\n" : "◇\n") + effName);
            _setState(context, active ? 1 : 0);
            break;
        }

        case "com.mystrow.streamdeck.level": {
            var fader = parseInt(settings.fader_idx, 10);
            var val   = parseInt(settings.level_val, 10);
            if (isNaN(fader)) fader = 0;
            if (isNaN(val))   val   = 100;
            var current = (state.fader_levels && state.fader_levels[fader] !== undefined)
                ? state.fader_levels[fader] : 0;
            var btn = $SD.buttons[context];
            if (btn && btn.controller === "Encoder") {
                // Stream Deck+ : mise à jour LCD strip (barre + valeur)
                _setFeedback(context, current);
            } else {
                _setTitle(context, "F" + fader + "\n" + val + "%\n[" + current + "]");
            }
            break;
        }

        case "com.mystrow.streamdeck.mute": {
            var fi = parseInt(settings.fader_idx, 10);
            if (isNaN(fi)) fi = 0;
            var projs = state.projectors || [];
            var muted = projs[fi] && projs[fi].muted;
            _setTitle(context, muted ? "🔇 MUTE\n" + fi : "🔊 UN\n" + fi);
            _setState(context, muted ? 1 : 0);
            break;
        }

        case "com.mystrow.streamdeck.scene": {
            var mc  = parseInt(settings.mem_col, 10);
            var row = parseInt(settings.mem_row, 10);
            if (isNaN(mc))  mc  = 0;
            if (isNaN(row)) row = 0;
            var scenes = state.scenes || [];
            var pad = (scenes[mc] && scenes[mc][row]) ? scenes[mc][row] : null;
            if (!pad || !pad.stored) {
                _setTitle(context, "C" + mc + "R" + row + "\n(vide)");
                _setState(context, 0);
            } else {
                _setTitle(context, pad.active ? "★ C" + mc + "\nR" + row : "☆ C" + mc + "\nR" + row);
                _setState(context, pad.active ? 1 : 0);
            }
            break;
        }
    }
}

// ── Helpers Stream Deck WebSocket ─────────────────────────────────────────────

function _send(obj) {
    if ($SD.ws && $SD.ws.readyState === WebSocket.OPEN) {
        $SD.ws.send(JSON.stringify(obj));
    }
}

function _setTitle(context, title) {
    _send({
        event:   "setTitle",
        context: context,
        payload: { title: title, target: 0 },
    });
}

function _setState(context, state) {
    _send({
        event:   "setState",
        context: context,
        payload: { state: state },
    });
}

function _showOk(context) {
    _send({ event: "showOk", context: context });
}

function _showAlert(context) {
    _send({ event: "showAlert", context: context });
}

function _setFeedback(context, levelPct) {
    // Met à jour l'écran LCD du bouton rotatif Stream Deck+ (layout $B1)
    _send({
        event:   "setFeedback",
        context: context,
        payload: {
            value:     levelPct + "%",
            indicator: { value: levelPct, enabled: true },
        },
    });
}

// ── Helpers HTTP → MyStrow API ────────────────────────────────────────────────

function _apiPost(endpoint) {
    fetch(API_BASE + endpoint, { method: "POST", signal: AbortSignal.timeout(1500) })
        .catch(function () {});
}

function _apiFetch(endpoint, callback) {
    fetch(API_BASE + endpoint, { signal: AbortSignal.timeout(1500) })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) { callback(data); })
        .catch(function () { callback(null); });
}

// ── Bootstrap Node.js (Stream Deck 6+) ───────────────────────────────────────
// En mode navigateur (SDK legacy), connectElgatoStreamDeckSocket est appelée
// par l'hôte. En Node.js, on lit les arguments de la ligne de commande.
(function () {
    if (typeof process === 'undefined' || !process.versions || !process.versions.node) return;

    // WebSocket polyfill pour Node.js < 21
    if (typeof WebSocket === 'undefined') {
        try { global.WebSocket = require('ws'); } catch (e) {}
    }

    // fetch polyfill minimal si absent (ne devrait pas arriver sur Node 18+)
    if (typeof fetch === 'undefined') {
        global.fetch = function (url, opts) {
            return new Promise(function (resolve, reject) {
                var http = require(url.startsWith('https') ? 'https' : 'http');
                var options = { method: (opts && opts.method) || 'GET' };
                var req = http.request(url, options, function (res) {
                    var body = '';
                    res.on('data', function (c) { body += c; });
                    res.on('end', function () {
                        resolve({ ok: res.statusCode >= 200 && res.statusCode < 300,
                                  json: function () { return Promise.resolve(JSON.parse(body)); } });
                    });
                });
                req.on('error', reject);
                req.end();
            });
        };
    }

    // Lire les arguments --port --pluginUUID --registerEvent --info
    var args = {};
    var argv = process.argv.slice(2);
    for (var i = 0; i < argv.length - 1; i++) {
        var key = argv[i].replace(/^-+/, '');
        args[key] = argv[i + 1];
        i++;
    }

    if (args.port && args.pluginUUID) {
        connectElgatoStreamDeckSocket(args.port, args.pluginUUID, args.registerEvent || 'registerPlugin', args.info || '{}');
    }
}());
