#!/usr/bin/env python3
"""Guard-railed HackRF transmit wrapper around `hackrf_transfer -t`.

Every transmission is:
  * bounded       — the file is finite (no -R repeat unless --repeat N, which is implemented by looping
                    a bounded number of times) and the process is killed after a hard timeout;
  * explicit      — frequency, sample rate and TX gain are always passed, never left to defaults;
  * low power     — TX VGA gain capped (default 20 of 47 dB) and the RF amp OFF unless --amp AND --i-know;
  * band-checked  — frequency must be inside an allow-list (default: 433.05-434.79 MHz ISM / LPD433).
    Edit ALLOWED_BANDS for your licence and jurisdiction. You are responsible for what you transmit.

    hackrf_tx.py signal.cs8 --freq 433.92e6 --rate 2e6            # one shot at TX gain 20
    hackrf_tx.py signal.cs8 --freq 433.92e6 --rate 2e6 --gain 10 --repeat 3 --gap 1
    hackrf_tx.py --dry-run signal.cs8 --freq 433.92e6 --rate 2e6   # print the command only

Always use an antenna or a 50-ohm load on the HackRF port when transmitting.
"""
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time

# (low_hz, high_hz, label). Keep this list tight. Add bands only where you are licensed/permitted.
ALLOWED_BANDS = [
    (433.05e6, 434.79e6, "433 MHz ISM (ITU Region 1) / LPD433 — US Part 15.231 periodic"),
]
MAX_GAIN_DEFAULT = 20      # dB of TX VGA (0-47)
HARD_MAX_SECONDS = 120


def f_num(s: str) -> float:
    s = s.strip().lower().replace("_", "")
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(s[-1], 1)
    return float(s[:-1] if s[-1] in "kmg" else s) * mult


def band_ok(freq: float, rate: float, occupied: float | None) -> str | None:
    half = (occupied or rate) / 2      # assume the whole sample-rate span may carry energy unless told otherwise
    for lo, hi, label in ALLOWED_BANDS:
        if lo <= freq - half and freq + half <= hi:
            return label
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="CS8 IQ file (int8 I/Q interleaved)")
    ap.add_argument("--freq", type=f_num, required=True, help="centre frequency, Hz")
    ap.add_argument("--rate", type=f_num, required=True, help="sample rate the file was generated at, Hz")
    ap.add_argument("--gain", type=int, default=MAX_GAIN_DEFAULT, help="TX VGA gain dB (0-47)")
    ap.add_argument("--max-gain", type=int, default=MAX_GAIN_DEFAULT)
    ap.add_argument("--amp", action="store_true", help="enable the +14 dB RF amp (requires --i-know)")
    ap.add_argument("--i-know", action="store_true", help="acknowledge high power / out-of-list operation")
    ap.add_argument("--occupied-bw", type=f_num, help="actual signal bandwidth for the band check "
                                                      "(default: assume the full sample rate)")
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--gap", type=float, default=0.5)
    ap.add_argument("--serial", help="HackRF serial (-d) when several are attached")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.file):
        sys.exit(f"no such file: {a.file}")
    n = os.path.getsize(a.file) // 2
    seconds = n / a.rate
    if seconds * a.repeat > HARD_MAX_SECONDS:
        sys.exit(f"refusing: {seconds * a.repeat:.1f} s total exceeds HARD_MAX_SECONDS={HARD_MAX_SECONDS}")
    if not 0 <= a.gain <= 47:
        sys.exit("TX gain must be 0-47")
    if a.gain > a.max_gain and not a.i_know:
        sys.exit(f"refusing: --gain {a.gain} > cap {a.max_gain}. Lower it, or raise --max-gain with --i-know.")
    if a.amp and not a.i_know:
        sys.exit("refusing: --amp adds ~14 dB. Add --i-know if you really mean it.")
    label = band_ok(a.freq, a.rate, a.occupied_bw)
    if not label and not a.i_know:
        sys.exit(f"refusing: {a.freq / 1e6:.4f} MHz +/- {(a.occupied_bw or a.rate) / 2e3:.0f} kHz is outside "
                 f"ALLOWED_BANDS. Pass --occupied-bw if the signal is narrower than the sample rate.")
    if not 2e6 <= a.rate <= 20e6:
        print("warning: HackRF sample rates below 2 MS/s are unsupported/unreliable", file=sys.stderr)

    cmd = ["hackrf_transfer", "-t", a.file, "-f", str(int(a.freq)), "-s", str(int(a.rate)), "-x", str(a.gain),
           "-a", "1" if a.amp else "0"]
    if a.serial:
        cmd += ["-d", a.serial]
    timeout = shutil.which("gtimeout") or shutil.which("timeout")
    limit = int(seconds + 5)
    full = ([timeout, "-s", "INT", "-k", "3", str(limit)] if timeout else []) + cmd
    print(f"band: {label or 'OVERRIDDEN (--i-know)'}")
    print(f"file: {n:,} samples = {seconds:.2f} s at {a.rate / 1e6:g} MS/s, x{a.repeat}")
    print("$ " + " ".join(full))
    if a.dry_run:
        return
    rc = 0
    for i in range(a.repeat):
        if i:
            time.sleep(a.gap)
        p = subprocess.Popen(full)
        try:
            rc = p.wait(timeout=limit + 5)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            p.send_signal(signal.SIGINT)
            p.wait(5)
            rc = 130
            break
        if rc not in (0,):
            break
    # make absolutely sure nothing is left keyed up
    if subprocess.run(["pgrep", "-x", "hackrf_transfer"], capture_output=True).returncode == 0:
        subprocess.run(["pkill", "-INT", "-x", "hackrf_transfer"])
        print("warning: stray hackrf_transfer killed", file=sys.stderr)
    sys.exit(rc)


if __name__ == "__main__":
    main()
