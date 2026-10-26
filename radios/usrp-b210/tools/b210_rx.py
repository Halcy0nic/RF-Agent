#!/usr/bin/env python3
"""Record IQ from a USRP B200/B210 with UHD's rx_samples_to_file, plus a SigMF sidecar.

    b210_rx.py --freq 433.92e6 --rate 2e6 --gain 40 --seconds 5 -o cap.cf32
    b210_rx.py --freq 915e6 --rate 10e6 --gain 30 --ant TX/RX --channel 1 --seconds 2 -o cap.cs16
    b210_rx.py --freq 2.44e9 --rate 20e6 --gain 50 --channels 0,1 --seconds 1 -o mimo.cf32   # -> mimo_ch0/1.cf32
    b210_rx.py --freq 98e6 --rate 56e6 --otw sc8 --seconds 1 -o wide.cs16                   # 56 MS/s needs sc8

Output format follows the extension: .cf32 (complex float32, rfkit default) or .cs16 (int16 I/Q).
A <file>.sigmf-meta is written next to each file (rate, centre, gain, antenna, channel) so
rfkit.iq / tools/iq_inspect.py can open it without extra arguments (open the .sigmf-data name, or pass --fs).

UHD antenna names on each channel: "TX/RX" and "RX2". On the OpenSourceSDRLab Artix-7 board,
channel 0 = TRX1 (TX/RX) + RX1 (RX2); channel 1 = TRX2 (TX/RX) + RX2 (RX2).
Needs UHD_IMAGES_DIR set (radios/usrp-b210/tools/setup_images.sh).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_IMAGES = Path.home() / ".local/share/uhd/images"


def f_num(s: str) -> float:
    s = s.strip().lower().replace("_", "")
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(s[-1], 1)
    return float(s[:-1] if s[-1] in "kmg" else s) * mult


def uhd_example(name: str) -> str:
    """Locate a UHD example program (Homebrew keeps them off PATH)."""
    cands = []
    if shutil.which(name):
        return shutil.which(name)
    try:
        prefix = subprocess.run(["brew", "--prefix", "uhd"], capture_output=True, text=True).stdout.strip()
        if prefix:
            cands.append(Path(prefix) / "lib/uhd/examples" / name)
    except FileNotFoundError:
        pass
    cands += [Path("/usr/lib/uhd/examples") / name, Path("/usr/local/lib/uhd/examples") / name,
              Path("/usr/libexec/uhd/examples") / name]
    for c in cands:
        if c.exists():
            return str(c)
    sys.exit(f"UHD example '{name}' not found (install UHD: brew install uhd / apt install uhd-host)")


def wire_flag(example: str, env: dict) -> str:
    """UHD 4.10 calls the over-the-wire option --otw, UHD 4.9 (Ubuntu apt) calls it --wirefmt."""
    h = subprocess.run([example, "--help"], env=env, capture_output=True, text=True)
    return "--wirefmt" if "--wirefmt" in (h.stdout + h.stderr) else "--otw"


def uhd_env() -> dict:
    env = dict(os.environ)
    if "UHD_IMAGES_DIR" not in env and DEFAULT_IMAGES.exists():
        env["UHD_IMAGES_DIR"] = str(DEFAULT_IMAGES)
    return env


def write_meta(data: Path, fmt: str, rate: float, freq: float, extra: dict) -> Path:
    dt = {"float": "cf32_le", "short": "ci16_le"}[fmt]
    meta = {"global": {"core:datatype": dt, "core:sample_rate": rate, "core:version": "1.0.0",
                       "core:hw": "USRP B210", "core:recorder": "rx_samples_to_file", **extra},
            "captures": [{"core:sample_start": 0, "core:frequency": freq}], "annotations": []}
    p = data.with_suffix(".sigmf-meta")
    p.write_text(json.dumps(meta, indent=2))
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", required=True, help="output file (.cf32 or .cs16)")
    ap.add_argument("--freq", type=f_num, required=True)
    ap.add_argument("--rate", type=f_num, default=2e6)
    ap.add_argument("--gain", type=float, default=40, help="RX gain dB (0-76)")
    ap.add_argument("--ant", default="RX2", help="TX/RX or RX2")
    ap.add_argument("--channel", default="0", help="0 or 1")
    ap.add_argument("--channels", help="e.g. 0,1 for both (files get _ch0/_ch1 suffixes)")
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--bw", type=f_num, help="analog filter bandwidth (default: UHD's choice)")
    ap.add_argument("--otw", choices=["sc16", "sc8"], help="over-the-wire format (sc8 for > 30 MS/s)")
    ap.add_argument("--args", default="type=b200", help="UHD device args (e.g. 'serial=XXXXXXX,master_clock_rate=32e6')")
    ap.add_argument("--ref", choices=["internal", "external", "gpsdo"])
    ap.add_argument("--extra", default="", help="extra rx_samples_to_file arguments")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    out = Path(a.out)
    fmt = {".cf32": "float", ".cfile": "float", ".fc32": "float", ".cs16": "short", ".s16": "short"}.get(out.suffix)
    if fmt is None:
        sys.exit("output must end in .cf32 or .cs16")
    out.parent.mkdir(parents=True, exist_ok=True)
    chans = a.channels or a.channel
    nsamps = int(round(a.seconds * a.rate))
    cmd = [uhd_example("rx_samples_to_file"), "--args", a.args, "--freq", str(a.freq), "--rate", str(a.rate),
           "--gain", str(a.gain), "--ant", a.ant, "--channels", chans, "--type", fmt]
    # one UHD stream command holds at most 2^28 samples (26 s at 10 MS/s): use --duration beyond that
    cmd += ["--duration", str(a.seconds)] if nsamps >= 2**28 else ["--nsamps", str(nsamps)]
    cmd += ["--file", str(out)]
    if a.bw:
        cmd += ["--bw", str(a.bw)]
    if a.otw:
        cmd += [wire_flag(cmd[0], uhd_env()), a.otw]
    if a.ref:
        cmd += ["--ref", a.ref]
    if a.extra:
        cmd += a.extra.split()
    print("$ " + " ".join(cmd), flush=True)
    if a.dry_run:
        return
    p = subprocess.run(cmd, env=uhd_env(), capture_output=True, text=True)
    log = p.stdout + p.stderr
    m = re.search(r"Actual RX Rate: ([\d.]+) Msps", log)
    actual = float(m.group(1)) * 1e6 if m else a.rate
    overflows = log.count("O") if "Got an overflow" in log else 0
    if p.returncode != 0:
        print(log[-2000:], file=sys.stderr)
        sys.exit(p.returncode)
    files = [out] if "," not in chans else [out.with_name(f"{out.stem}_ch{c}{out.suffix}") for c in chans.split(",")]
    result = []
    for ch, f in zip(chans.split(","), files):
        if not f.exists():
            print(f"missing output {f}", file=sys.stderr)
            continue
        meta = write_meta(f, fmt, actual, a.freq, {"rfagent:gain_db": a.gain, "rfagent:antenna": a.ant,
                                                    "rfagent:channel": int(ch)})
        bps = 8 if fmt == "float" else 4
        result.append({"file": str(f), "meta": str(meta), "samples": f.stat().st_size // bps})
    print(json.dumps({"rate": actual, "freq": a.freq, "gain": a.gain, "antenna": a.ant, "channels": chans,
                      "overflow_reported": "Got an overflow" in log, "files": result}, indent=2))


if __name__ == "__main__":
    main()
