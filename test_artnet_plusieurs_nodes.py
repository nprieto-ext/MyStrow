"""Plusieurs nodes Art-Net 1 univers : chaque sortie part vers SON node.

Cas client (Discord, 07/10/2026) : 2x Art-Net POE Electroconcept, un univers
chacun. Avant, les 4 univers partaient tous vers target_ip : le second node
restait muet.
"""
import json
import os
import socket
import tempfile

import artnet_dmx
from artnet_dmx import ArtNetDMX


def _moteur(tmp):
    # Jamais la vraie ~/.mystrow_dmx.json
    ArtNetDMX.CONFIG_FILE = os.path.join(tmp, "dmx.json")
    return ArtNetDMX()


def _ecoute(ip, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((ip, port))
    s.settimeout(0.5)
    return s


def _univers_recus(s):
    recus = []
    try:
        while True:
            pkt, _ = s.recvfrom(1024)
            recus.append(pkt[14] | (pkt[15] << 8))
    except socket.timeout:
        pass
    return sorted(recus)


def test_chaque_sortie_vers_son_node():
    with tempfile.TemporaryDirectory() as tmp:
        d = _moteur(tmp)
        port = 16454
        a, b = _ecoute("127.0.0.1", port), _ecoute("127.0.0.2", port)
        try:
            d.target_ip, d.target_port = "127.0.0.1", port
            d.set_output_ips(["", "127.0.0.2", "", ""])
            d._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            assert d._send_artnet()
            assert _univers_recus(a) == [0, 2, 3]
            assert _univers_recus(b) == [1]
        finally:
            a.close(); b.close(); d._socket.close()


def test_defaut_tout_vers_node_principal():
    with tempfile.TemporaryDirectory() as tmp:
        d = _moteur(tmp)
        assert d.output_ips == ["", "", "", ""]
        assert all(d._artnet_dest(n) == d.target_ip for n in range(4))


def test_config_abimee_retombe_sur_principal():
    with tempfile.TemporaryDirectory() as tmp:
        d = _moteur(tmp)
        for mauvais in (None, "x", [1, 2], ["2.0.0", "abc", None, 5]):
            d.set_output_ips(mauvais)
            assert d.output_ips == ["", "", "", ""], mauvais


def test_sauvegarde_relecture():
    with tempfile.TemporaryDirectory() as tmp:
        d = _moteur(tmp)
        d.set_output_ips(["", "2.0.0.16", "", ""])
        d._save_config()
        with open(ArtNetDMX.CONFIG_FILE) as f:
            assert json.load(f)["output_ips"] == ["", "2.0.0.16", "", ""]
        assert ArtNetDMX().output_ips == ["", "2.0.0.16", "", ""]


if __name__ == "__main__":
    for nom, f in list(globals().items()):
        if nom.startswith("test_"):
            f(); print("OK", nom)
