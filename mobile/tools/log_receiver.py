"""Reçoit le journal de la page de test DMX de l'app tablette (mobile/src/dmxtest.html).

Pendant un test USB-DMX, la seule prise de la tablette est prise par l'interface :
plus d'adb par câble. La page envoie alors ses mesures au PC par le Wi-Fi.

    python mobile/tools/log_receiver.py        # écoute HTTP sur le port 6456
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 6456


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            print(json.dumps(json.loads(body), ensure_ascii=False), flush=True)
        except ValueError:
            print(body.decode("utf-8", "replace"), flush=True)
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def log_message(self, *args):
        pass


print(f"Journal de la tablette : HTTP {PORT}…", flush=True)
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
