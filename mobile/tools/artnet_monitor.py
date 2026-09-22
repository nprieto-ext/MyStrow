"""Simulateur de node Art-Net : mesure la régularité d'une source DMX.

Sert à tester la sortie DMX de l'app tablette (mode autonome) sans node :
la tablette envoie au PC au lieu du node, ce script dit si le flux est
exploitable en show.

    python mobile/tools/artnet_monitor.py                 # port 6454
    python mobile/tools/artnet_monitor.py --port 6455     # si MyStrow occupe déjà 6454
    python mobile/tools/artnet_monitor.py --duration 600  # arrêt + bilan après 10 min

Une ligne par seconde, puis un bilan (Ctrl+C) :
  - trames/s, écart moyen et pire écart entre deux trames ;
  - trous : écart > 2 périodes (un projecteur peut « hoqueter ») ;
  - pertes : numéros de séquence Art-Net manquants (paquets perdus en route).
  - canal 1 : la page de test y met un compteur (+1 par mise à jour du JS) ;
    « figées » = trames où il n'a pas bougé, « sautées » = crans manqués.
"""
import argparse
import socket
import statistics
import time

HEADER = b"Art-Net\x00"
OP_DMX = 0x5000


def parse(pkt):
    """Renvoie (séquence, univers, données) d'un ArtDMX, sinon None."""
    if len(pkt) < 18 or pkt[:8] != HEADER:
        return None
    if int.from_bytes(pkt[8:10], "little") != OP_DMX:
        return None
    length = int.from_bytes(pkt[16:18], "big")
    universe = pkt[14] | (pkt[15] << 8)
    return pkt[12], universe, pkt[18:18 + length]


class Stats:
    def __init__(self):
        self.gaps_ms = []
        self.packets = 0
        self.lost = 0
        self.holes = 0
        self.frozen = 0
        self.skipped = 0

    def merge(self, other):
        self.gaps_ms += other.gaps_ms
        for k in ("packets", "lost", "holes", "frozen", "skipped"):
            setattr(self, k, getattr(self, k) + getattr(other, k))


def fmt(s, seconds, period_ms):
    if not s.gaps_ms:
        return f"{s.packets / seconds:5.1f} tr/s  (pas assez de trames)"
    avg = statistics.fmean(s.gaps_ms)
    jit = statistics.pstdev(s.gaps_ms)
    p99 = sorted(s.gaps_ms)[int(len(s.gaps_ms) * 0.99) - 1] if len(s.gaps_ms) >= 100 else max(s.gaps_ms)
    return (f"{s.packets / seconds:5.1f} tr/s  écart {avg:5.1f} ms ± {jit:4.1f}  p99 {p99:5.1f}  "
            f"pire {max(s.gaps_ms):6.1f} ms  trous {s.holes}  pertes {s.lost}  "
            f"ch1 figées {s.frozen} sautées {s.skipped}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=6454)
    ap.add_argument("--fps", type=float, default=40, help="cadence attendue (seuil des trous)")
    ap.add_argument("--duration", type=float, default=0, help="secondes (0 = jusqu'à Ctrl+C)")
    args = ap.parse_args()

    period_ms = 1000 / args.fps
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", args.port))
    sock.settimeout(0.2)
    print(f"En écoute Art-Net sur UDP {args.port} (cadence attendue {args.fps:g} tr/s)… Ctrl+C pour le bilan.",
          flush=True)

    total, sec = Stats(), Stats()
    last_t = last_seq = last_ch1 = None
    source = None
    t_first = t_sec = None
    try:
        while True:
            now = time.perf_counter()
            if args.duration and t_first and now - t_first >= args.duration:
                break
            if t_sec and now - t_sec >= 1:
                print(time.strftime("%H:%M:%S"), fmt(sec, now - t_sec, period_ms), flush=True)
                total.merge(sec)
                sec, t_sec = Stats(), now
            try:
                pkt, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            t = time.perf_counter()
            p = parse(pkt)
            if not p:
                continue
            seq, universe, data = p
            if source != addr[0]:
                source = addr[0]
                print(f"Source : {source}, univers {universe}", flush=True)
            if t_first is None:
                t_first = t_sec = t
            sec.packets += 1
            if last_t is not None:
                gap = (t - last_t) * 1000
                sec.gaps_ms.append(gap)
                if gap > 2 * period_ms:
                    sec.holes += 1
            if last_seq is not None and seq:
                sec.lost += (seq - last_seq - 1) % 255     # séquence 1..255
            if data:
                ch1 = data[0]
                if last_ch1 is not None:
                    step = (ch1 - last_ch1) % 256
                    if step == 0:
                        sec.frozen += 1
                    elif step > 1:
                        sec.skipped += step - 1
                last_ch1 = ch1
            last_t, last_seq = t, seq
    except KeyboardInterrupt:
        pass
    total.merge(sec)
    if t_first is None:
        print("\nAucune trame Art-Net reçue.")
        return
    elapsed = time.perf_counter() - t_first
    print(f"\n=== BILAN sur {elapsed:.0f} s, {total.packets} trames ===")
    print(fmt(total, elapsed, period_ms))
    if total.gaps_ms:
        worst = sorted(total.gaps_ms)[-5:]
        print("5 pires écarts (ms) :", ", ".join(f"{g:.0f}" for g in reversed(worst)))
        over = {lim: sum(g > lim for g in total.gaps_ms) for lim in (50, 100, 200, 500)}
        print("écarts > 50/100/200/500 ms :", " / ".join(str(v) for v in over.values()))


if __name__ == "__main__":
    main()
