#!/usr/bin/env python3
"""Over-the-air test between a USRP B210 and a HackRF: generate -> TX -> RX -> decode.

    python tests/ota_b210.py --dir hackrf2b210                 # HackRF transmits, B210 receives (all cases)
    python tests/ota_b210.py --dir b210tohackrf --tx-gain 60   # B210 transmits, HackRF receives
    python tests/ota_b210.py --dir hackrf2b210 ook fsk --rx-ant TX/RX --rx-channel 0
    python tests/ota_b210.py --dir both                         # both directions

Cases, generators and expected decodes are shared with tests/ota_test.py.
The receiver is started first. Transmission begins only once the capture file is growing (UHD takes ~3 s to
load firmware/FPGA and lock), so nothing is missed.
Results: tmp/ota_b210/<dir>/<case>.{cs8,cf32,json} and summary.json
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))
from ota_test import CASES  # noqa: E402

from rfkit import dsp, iq  # noqa: E402

PY = sys.executable
FS = 2_000_000
B210 = REPO / "radios/usrp-b210/tools"
OUT = REPO / "tmp" / "ota_b210"


def wait_growing(path: Path, timeout: float = 25.0) -> bool:
    t0 = time.time()
    last = -1
    while time.time() - t0 < timeout:
        if path.exists():
            size = path.stat().st_size
            if size > 0 and last > 0 and size > last:
                return True
            last = size
        time.sleep(0.2)
    return False


def analyze(path: Path, fs: float | None) -> dict:
    x, fs = iq.load(path, fs=fs)
    x = x[int(0.05 * fs):]
    g = dsp.gate(x, fs)
    c = dsp.find_carriers(g if len(g) > 8192 else x, fs, exclude_dc_hz=5e3, max_peaks=1)
    return {"offset_hz": round(c[0]["freq_hz"]), "snr_db": round(c[0]["snr_db"], 1)} if c else {}


def decode(path: Path, dec, fs: float | None):
    cmd = [PY, str(REPO / "tools/rx_decode.py"), dec[0], str(path), *dec[1:]]
    if fs:
        cmd += ["--fs", str(fs)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stdout


def one(name, gen, dec, expect, direction, a, outdir: Path) -> dict:
    cs8 = outdir / f"{name}.cs8"
    g = subprocess.run([PY, str(REPO / "signal_generation/generate.py"), *gen, "-o", str(cs8),
                        "--center", str(a.freq)], capture_output=True, text=True)
    if g.returncode:
        return {"result": "GEN_FAIL", "err": g.stderr[-300:]}
    tx_s = cs8.stat().st_size / 2 / FS
    if direction == "hackrf2b210":
        rx_path, rx_fs = outdir / f"{name}.cf32", None
        rx = subprocess.Popen([PY, str(B210 / "b210_rx.py"), "--freq", str(a.freq), "--rate", str(FS),
                               "--gain", str(a.rx_gain), "--ant", a.rx_ant, "--channel", a.rx_channel,
                               "--seconds", str(tx_s + 2.5), "-o", str(rx_path)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tx_cmd = [PY, str(REPO / "radios/hackrf/tools/hackrf_tx.py"), str(cs8), "--freq", str(a.freq),
                  "--rate", str(FS), "--gain", str(a.tx_gain)]
    else:
        rx_path, rx_fs = outdir / f"{name}_rx.cs8", FS
        n = int((tx_s + 9) * FS)                      # b210_tx needs ~3-4 s to start before RF comes out
        rx = subprocess.Popen(["hackrf_transfer", "-r", str(rx_path), "-f", str(int(a.freq)), "-s", str(FS),
                               "-n", str(n), "-l", str(a.hackrf_lna), "-g", str(a.hackrf_vga), "-a", "0"],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        tx_cmd = [PY, str(B210 / "b210_tx.py"), str(cs8), "--freq", str(a.freq), "--rate", str(FS),
                  "--gain", str(a.tx_gain), "--channel", a.tx_channel]
    if not wait_growing(rx_path):
        rx.kill()
        return {"result": "RX_NOT_STARTED", "log": (rx.communicate()[0] or "")[-400:]}
    time.sleep(0.5)
    t = subprocess.run(tx_cmd, capture_output=True, text=True)
    rx.wait(timeout=120)
    res = {"tx_rc": t.returncode, **analyze(rx_path, rx_fs)}
    if dec:
        out = decode(rx_path, dec, rx_fs)
        (outdir / f"{name}.json").write_text(out)
        res["result"] = "PASS" if expect and expect in out else "FAIL"
        try:
            dj = json.loads(out)
            res["decoded"] = dj.get("text") or [p["payload"] for p in dj.get("packets", []) if p.get("crc_ok")] \
                or dj.get("dominant_audio_hz")
        except json.JSONDecodeError:
            res["decoded"] = out[-200:]
    else:
        res["result"] = "MEASURED"
    if a.keep_iq is False and rx_path.exists() and res.get("result") == "PASS":
        rx_path.unlink()
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("only", nargs="*")
    ap.add_argument("--dir", choices=["hackrf2b210", "b210tohackrf", "both"], default="hackrf2b210")
    ap.add_argument("--freq", type=float, default=433.92e6)
    ap.add_argument("--tx-gain", type=float, help="HackRF -x (default 20) or B210 TX gain (default 60)")
    ap.add_argument("--rx-gain", type=float, default=40, help="B210 RX gain")
    ap.add_argument("--rx-ant", default="RX2", help="B210 RX antenna: RX2 or TX/RX")
    ap.add_argument("--rx-channel", default="0")
    ap.add_argument("--tx-channel", default="0")
    ap.add_argument("--hackrf-lna", type=int, default=24)
    ap.add_argument("--hackrf-vga", type=int, default=20)
    ap.add_argument("--keep-iq", action="store_true", help="keep received IQ for passing cases")
    a = ap.parse_args()
    dirs = ["hackrf2b210", "b210tohackrf"] if a.dir == "both" else [a.dir]
    cases = {k: v for k, v in CASES.items() if (not a.only or any(o in k for o in a.only))
             and k not in ("text", "chirp", "css", "am")}
    summary = {}
    tx_gain_arg = a.tx_gain
    for d in dirs:
        a.tx_gain = tx_gain_arg if tx_gain_arg is not None else (20 if d == "hackrf2b210" else 60)
        outdir = OUT / d
        outdir.mkdir(parents=True, exist_ok=True)
        for name, (gen, dec, expect) in cases.items():
            r = one(name, gen, dec, expect, d, a, outdir)
            summary[f"{d}/{name}"] = r
            print(f"{d:13s} {name:15s} {json.dumps(r)}", flush=True)
    subprocess.run(["pkill", "-INT", "-x", "hackrf_transfer"], capture_output=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    fails = [k for k, v in summary.items() if v.get("result") not in ("PASS", "MEASURED")]
    print("FAILED:" if fails else "ALL PASS", fails or "")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
