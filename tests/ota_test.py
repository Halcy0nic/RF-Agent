#!/usr/bin/env python3
"""Over-the-air end-to-end test: generate -> HackRF TX -> RTL-SDR in SDR++ (rigctl recorder) -> decode.

    python tests/ota_test.py                 # all cases
    python tests/ota_test.py ook fsk         # name filter
    python tests/ota_test.py --freq 915e6 --tx-gain 30 --rx-gain 28 --amp
    python tests/make_doc_images.py          # afterwards: rebuild the doc figures from tmp/ota/*.wav

Needs: HackRF + RTL-SDR attached, SDR++ installed, antennas (or an attenuated cable) on both radios.
TX goes through radios/hackrf/tools/hackrf_tx.py. SDR++ uses its own config root (tmp/sdrpp/root).
At the end the SDR++ instance is closed (unless --keep-sdrpp).
Results: tmp/ota/<case>.{cs8,wav,json,png} and tmp/ota/summary.json
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
sys.path.insert(0, str(REPO / "software/sdr++/tools"))
import sdrpp  # noqa: E402

PY = sys.executable
OUT = REPO / "tmp" / "ota"
FS_TX = 2_000_000

# name: (generate.py args, rx_decode.py args, expected substring in the decoded output)
CASES = {
    "tone":  (["tone", "--seconds", "1.5"], None, None),
    "morse": (["morse", "--text", "RF AGENT TEST", "--wpm", "20"], ["morse"], "RF AGENT TEST"),
    "ook":   (["ook", "--text", "OOK HELLO", "--rate", "1000", "--repeat", "3"], ["ook"], "OOK HELLO"),
    "ook_manchester": (["ook", "--manchester", "--text", "MANCHESTER", "--rate", "1000", "--repeat", "3"],
                       ["ook", "--manchester"], "MANCHESTER"),
    "fsk":   (["fsk", "--text", "FSK HELLO", "--rate", "5000", "--dev", "20e3", "--repeat", "3"], ["fsk"],
              "FSK HELLO"),
    "gfsk":  (["fsk", "--bt", "0.5", "--text", "GFSK HELLO", "--rate", "10000", "--dev", "10e3", "--repeat", "3"],
              ["fsk"], "GFSK HELLO"),
    "bpsk":  (["psk", "--scheme", "bpsk", "--rate", "50e3", "--text", "BPSK HELLO", "--repeat", "3"],
              ["psk", "--rate", "50e3", "--order", "2"], "BPSK HELLO"),
    "qpsk":  (["psk", "--scheme", "qpsk", "--rate", "50e3", "--text", "QPSK HELLO", "--repeat", "3"],
              ["psk", "--rate", "50e3", "--order", "4"], "QPSK HELLO"),
    "nfm":   (["fm", "--audio-tone", "1000", "--dev", "5e3", "--seconds", "1.5"], ["fm", "--nfm"], '"dominant_audio_hz": 1'),
    "text":  (["text", "--text", "RF AGENT", "--bw", "150e3"], None, None),
    "chirp": (["chirp", "--f0", "-100e3", "--f1", "100e3", "--seconds", "0.05", "--repeat", "20", "--gap", "0.03"],
              None, None),
    "css":   (["css", "--sf", "8", "--bw", "125e3", "--values", "0,64,128,192,32,224", "--repeat", "4",
               "--gap", "0.1"], None, None),
    "am":    (["am", "--audio-tone", "800", "--seconds", "1.5"], None, None),
}


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*")
    ap.add_argument("--freq", type=float, default=433.92e6, help="centre frequency for TX and RX, Hz")
    ap.add_argument("--rx-rate", type=float, default=1_024_000, help="RTL-SDR sample rate in SDR++")
    ap.add_argument("--tx-gain", type=int, default=20)
    ap.add_argument("--amp", action="store_true", help="HackRF RF amp on")
    ap.add_argument("--rx-gain", type=int, default=20, help="RTL gain index (20 = 37.2 dB)")
    ap.add_argument("--keep-sdrpp", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    cases = {k: v for k, v in CASES.items() if not a.only or any(o in k for o in a.only)}

    sdrpp.restart_with(dict(source="RTL-SDR", freq=a.freq, sample_rate=a.rx_rate, gain=a.rx_gain,
                            min_db=-80, max_db=-20, fft_size=8192, fft_rate=30))
    time.sleep(2)
    summary = {}
    try:
        for name, (gen, dec, expect) in cases.items():
            cs8 = OUT / f"{name}.cs8"
            g = run([PY, REPO / "signal_generation/generate.py", *gen, "-o", cs8, "--center", str(a.freq)])
            if g.returncode:
                summary[name] = {"result": "GEN_FAIL", "err": g.stderr[-400:]}
                continue
            before = set(sdrpp.REC_DIR.glob("*.wav"))
            sdrpp.rec_start()
            time.sleep(0.8)
            tx = subprocess.Popen([PY, str(REPO / "radios/hackrf/tools/hackrf_tx.py"), str(cs8), "--freq", str(a.freq),
                                   "--rate", str(FS_TX), "--gain", str(a.tx_gain)] + (["--amp"] if a.amp else []),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            # waterfall screenshot: mid-transmission, or after it ends for waterfall art (so it has scrolled in)
            if name != "text":
                time.sleep(1.2)
            txout, _ = (tx.communicate(timeout=120) if name == "text" else (None, None))
            try:
                sdrpp.grab(OUT / f"{name}_sdrpp.png")
            except Exception as e:  # noqa: BLE001
                print("screenshot failed", e)
            if name != "text":
                txout, _ = tx.communicate(timeout=120)
            time.sleep(0.8)
            sdrpp.rec_stop()
            time.sleep(1.0)
            new = sorted(set(sdrpp.REC_DIR.glob("*.wav")) - before, key=lambda q: q.stat().st_mtime)
            if not new:
                summary[name] = {"result": "NO_RECORDING"}
                continue
            wav = OUT / f"{name}.wav"
            new[-1].rename(wav)
            info = json.loads(run([PY, REPO / "software/sdr++/tools/sdrppctl.py", "analyze", wav, "--png",
                                   OUT / f"{name}.png", "--center", str(a.freq)]).stdout)
            top = info["carriers"][0] if info["carriers"] else {}
            res = {"tx_rc": tx.returncode, "carrier_offset_hz": round(top.get("freq_hz", 0)),
                   "snr_db": round(top.get("snr_db", 0), 1), "freq_error_hz": round(top.get("freq_hz", 0) - 100e3)}
            if dec:
                d = run([PY, REPO / "tools/rx_decode.py", dec[0], wav, *dec[1:]])
                (OUT / f"{name}.json").write_text(d.stdout + d.stderr)
                res["result"] = "PASS" if expect and expect in d.stdout else "FAIL"
                try:
                    dj = json.loads(d.stdout)
                    res["decoded"] = dj.get("text") or [p["payload"] for p in dj.get("packets", []) if p.get("crc_ok")] \
                        or dj.get("dominant_audio_hz")
                    if "rate" in dj:
                        res["rate"] = dj["rate"]
                except json.JSONDecodeError:
                    res["decoded"] = d.stderr[-300:]
            else:
                res["result"] = "CHECK_PNG"
            summary[name] = res
            print(name, json.dumps(res), flush=True)
    finally:
        subprocess.run(["pkill", "-INT", "-x", "hackrf_transfer"], capture_output=True)
        try:
            sdrpp.rec_stop()
        except OSError:
            pass
        if not a.keep_sdrpp:
            sdrpp.quit_app()
            if not sdrpp.ISOLATED:
                sdrpp.restore_config()
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    fails = [k for k, v in summary.items() if v.get("result") not in ("PASS", "CHECK_PNG")]
    print("FAILED:" if fails else "ALL PASS", fails or "")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
