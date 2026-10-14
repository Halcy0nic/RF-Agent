#!/usr/bin/env python3
"""HackRF transmit helper around `hackrf_transfer -t`.

Adds a few conveniences over calling hackrf_transfer directly: prints the file's duration at the given
rate, replays the file N times with a gap between plays, and can print the command without running it.

    hackrf_tx.py signal.cs8 --freq 433.92e6 --rate 2e6 --gain 20
    hackrf_tx.py signal.cs8 --freq 915e6 --rate 8e6 --gain 30 --amp --repeat 5 --gap 0.5
    hackrf_tx.py --dry-run signal.cs8 --freq 2.44e9 --rate 10e6 --gain 40
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time


def f_num(s: str) -> float:
    s = s.strip().lower().replace("_", "")
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(s[-1], 1)
    return float(s[:-1] if s[-1] in "kmg" else s) * mult


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="CS8 IQ file (int8 I/Q interleaved)")
    ap.add_argument("--freq", type=f_num, required=True, help="centre frequency, Hz")
    ap.add_argument("--rate", type=f_num, required=True, help="sample rate the file was generated at, Hz")
    ap.add_argument("--gain", type=int, default=20, help="TX VGA gain dB (0-47)")
    ap.add_argument("--amp", action="store_true", help="enable the RF amp (~+14 dB)")
    ap.add_argument("--repeat", type=int, default=1, help="play the file this many times")
    ap.add_argument("--gap", type=float, default=0.5, help="seconds between plays")
    ap.add_argument("--serial", help="HackRF serial (-d) when several are attached")
    ap.add_argument("--extra", default="", help="extra hackrf_transfer arguments, e.g. \"-b 5000000 -C 2\"")
    ap.add_argument("--dry-run", action="store_true", help="print the command only")
    a = ap.parse_args()

    if not os.path.exists(a.file):
        sys.exit(f"no such file: {a.file}")
    n = os.path.getsize(a.file) // 2
    seconds = n / a.rate
    cmd = ["hackrf_transfer", "-t", a.file, "-f", str(int(a.freq)), "-s", str(int(a.rate)), "-x", str(a.gain),
           "-a", "1" if a.amp else "0"]
    if a.serial:
        cmd += ["-d", a.serial]
    if a.extra:
        cmd += a.extra.split()
    print(f"file: {n:,} samples = {seconds:.2f} s at {a.rate / 1e6:g} MS/s, x{a.repeat}")
    print("$ " + " ".join(cmd))
    if a.dry_run:
        return
    rc = 0
    for i in range(a.repeat):
        if i:
            time.sleep(a.gap)
        p = subprocess.Popen(cmd)
        try:
            rc = p.wait()
        except KeyboardInterrupt:
            p.send_signal(signal.SIGINT)
            p.wait(5)
            rc = 130
            break
        if rc != 0:
            break
    sys.exit(rc)


if __name__ == "__main__":
    main()
