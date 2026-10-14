#!/usr/bin/env python3
"""Command-line control of SDR++ (config profiles, rigctl, recorder, screenshots, analysis).

    sdrppctl.py backup                       # save the user's SDR++ config (first time only; optional)
    sdrppctl.py restore [--relaunch]         # put it back
    sdrppctl.py user                         # quit the automation instance, relaunch SDR++ normally
    sdrppctl.py setup --freq 433.92e6 --rate 1.024e6 --gain 20 [--source HackRF --lna 24 --vga 20] [--radio]
    sdrppctl.py status
    sdrppctl.py rig "F 433920000"            # any raw rigctl command (also: f, m, "M WFM 200000", \\start ...)
    sdrppctl.py tune 433.92e6
    sdrppctl.py record 5 [--out cap.wav]     # baseband WAV via \\recorder_start / \\recorder_stop
    sdrppctl.py shot waterfall.png           # window screenshot
    sdrppctl.py capture NAME --freq 433.92e6 --seconds 6 [--shots 2] [--analyze] [-- <tx command ...>]
    sdrppctl.py analyze cap.wav [--png cap.png]
    sdrppctl.py quit | launch

Outputs default to tmp/sdrpp/ in the repo (git-ignored). Run from anywhere.
By default SDR++ runs in ISOLATED mode (`-r tmp/sdrpp/root`): your own SDR++ settings are never edited.
SDRPP_ISOLATED=0 drives the normal config instead (then backup/restore matter).
"""
from __future__ import annotations

import argparse
import json
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2]))          # repo root, for rfkit
import sdrpp  # noqa: E402


def f_hz(s: str) -> float:
    """Accept 433.92e6, 433920000, 433.92M, 915k."""
    s = s.strip().lower().replace("_", "")
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(s[-1], 1)
    return float(s[:-1] if s[-1] in "kmg" else s) * mult


def profile_from(a) -> dict:
    p = {"source": a.source, "freq": a.freq, "sample_rate": a.rate, "fft_size": a.fft_size, "fft_rate": a.fft_rate,
         "min_db": a.min_db, "max_db": a.max_db, "radio": a.radio, "show_menu": not a.hide_menu}
    if a.source == "RTL-SDR":
        p.update(gain=a.gain, ppm=a.ppm)
    else:
        p.update(lna=a.lna, vga=a.vga, amp=False)
    return p


def add_profile_args(sp, need_freq=True):
    sp.add_argument("--freq", type=f_hz, required=need_freq, help="centre frequency (433.92e6, 915M ...)")
    sp.add_argument("--source", default="RTL-SDR", choices=["RTL-SDR", "HackRF"])
    sp.add_argument("--rate", type=f_hz, default=None, help="sample rate (RTL default 1.024M, HackRF 4M)")
    sp.add_argument("--gain", type=int, default=20, help="RTL gain index 0-28 (20 = 37.2 dB)")
    sp.add_argument("--ppm", type=int, default=0)
    sp.add_argument("--lna", type=int, default=24, help="HackRF LNA gain 0-40 step 8")
    sp.add_argument("--vga", type=int, default=20, help="HackRF VGA gain 0-62 step 2")
    sp.add_argument("--fft-size", type=int, default=8192)
    sp.add_argument("--fft-rate", type=int, default=30)
    sp.add_argument("--min-db", type=float, default=-80)
    sp.add_argument("--max-db", type=float, default=-30)
    sp.add_argument("--radio", action="store_true", help="keep the Radio VFO (for demod/audio and rigctl M)")
    sp.add_argument("--hide-menu", action="store_true", help="hide the side menu (bigger waterfall in screenshots)")


def fix_rate(a):
    if a.rate is None:
        a.rate = 1_024_000 if a.source == "RTL-SDR" else 4_000_000


def analyze(path: Path, png: Path | None, center_hz: float | None = None) -> dict:
    from rfkit import dsp, iq, plot
    x, fs = iq.load(path)
    center_hz = center_hz or iq.info_from_name(path).get("center_hz", 0.0)
    # skip the first 50 ms (RTL settling transient) when there is enough data
    if len(x) > fs * 0.5:
        x = x[int(0.05 * fs):]
    peaks = dsp.find_carriers(x, fs, exclude_dc_hz=2e3, max_peaks=5)
    out = {"file": str(path), "fs": fs, "seconds": round(len(x) / fs, 3), "center_hz": center_hz,
           "carriers": [{**p, "abs_freq_hz": center_hz + p["freq_hz"]} for p in peaks],
           "bursts": len(dsp.bursts(x, fs))}
    if png:
        plot.overview(x, fs, png, center_hz=center_hz, title=Path(path).name)
        out["png"] = str(png)
    return out


def cmd_capture(a, tx: list[str]):
    out = Path(a.out_dir)
    caps, shots, logs = out / "caps", out / "shots", out / "logs"
    for d in (caps, shots, logs):
        d.mkdir(parents=True, exist_ok=True)
    if not sdrpp.ISOLATED:
        sdrpp.backup_config()                   # no-op after the first time
    fix_rate(a)
    sdrpp.restart_with(profile_from(a))
    time.sleep(a.settle)
    print("tuned:", sdrpp.rig("f"), flush=True)
    before = set(sdrpp.REC_DIR.glob("*.wav"))
    print("recorder_start:", sdrpp.rec_start(), flush=True)
    time.sleep(a.pre)
    proc = None
    t0 = time.time()
    if tx:
        log = open(logs / f"{a.name}_tx.log", "w")
        log.write("$ " + shlex.join(tx) + "\n")
        log.flush()
        proc = subprocess.Popen(tx, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    try:
        for k in range(a.shots):
            t_shot = t0 + (k + 1) * a.seconds / (a.shots + 1)
            while time.time() < t_shot:
                time.sleep(0.05)
            try:
                print("shot:", sdrpp.grab(shots / f"{a.name}_{k}.png"), flush=True)
            except Exception as e:  # noqa: BLE001  never abort a capture over a screenshot
                print("screenshot failed:", e, flush=True)
        while time.time() < t0 + a.seconds:
            if proc and proc.poll() is not None and not a.full:
                break
            time.sleep(0.05)
        if proc:
            try:
                proc.wait(timeout=max(0.0, a.tx_timeout - (time.time() - t0)))
            except subprocess.TimeoutExpired:
                print("TX still running at timeout: sending SIGINT", flush=True)
                proc.send_signal(signal.SIGINT)
                proc.wait(5)
            print(f"tx exit {proc.returncode} after {time.time() - t0:.1f}s", flush=True)
    except BaseException:
        if proc:
            proc.send_signal(signal.SIGINT)
        subprocess.run(["pkill", "-INT", "-x", "hackrf_transfer"])
        sdrpp.rec_stop()
        raise
    time.sleep(a.post)
    print("recorder_stop:", sdrpp.rec_stop(), flush=True)
    time.sleep(1.0)
    new = sorted(set(sdrpp.REC_DIR.glob("*.wav")) - before, key=lambda q: q.stat().st_mtime)
    if not new:
        sys.exit("no recording produced (check rigctl_server_config.json: recording=true, recorder=Recorder)")
    dst = caps / f"{a.name}.wav"
    new[-1].rename(dst)
    print(f"capture: {dst} ({dst.stat().st_size / 1e6:.1f} MB)", flush=True)
    if a.analyze:
        print(json.dumps(analyze(dst, out / "results" / f"{a.name}.png", a.freq), indent=2))
    if subprocess.run(["pgrep", "-x", "hackrf_transfer"], capture_output=True).returncode == 0:
        print("WARNING: hackrf_transfer still running", flush=True)


def main():
    argv = sys.argv[1:]
    tx: list[str] = []
    if "--" in argv:
        cut = argv.index("--")
        argv, tx = argv[:cut], argv[cut + 1:]
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backup").add_argument("--overwrite", action="store_true")
    sub.add_parser("restore").add_argument("--relaunch", action="store_true")
    sub.add_parser("status")
    sub.add_parser("launch")
    sub.add_parser("quit")
    sub.add_parser("user", help="quit the automation instance and relaunch SDR++ with the user's own config")
    sp = sub.add_parser("setup", help="quit, write a capture profile, relaunch, start the source")
    add_profile_args(sp)
    sp.add_argument("--no-start", action="store_true")
    sub.add_parser("rig").add_argument("command")
    sub.add_parser("tune").add_argument("freq", type=f_hz)
    sp = sub.add_parser("record")
    sp.add_argument("seconds", type=float)
    sp.add_argument("--out")
    sub.add_parser("shot").add_argument("path")
    sp = sub.add_parser("analyze")
    sp.add_argument("path")
    sp.add_argument("--png")
    sp.add_argument("--center", type=f_hz)
    sp = sub.add_parser("capture", help="profile + record + screenshots (+ optional TX command after --)")
    sp.add_argument("name")
    add_profile_args(sp)
    sp.add_argument("--seconds", type=float, default=6.0, help="record length (TX runs inside it)")
    sp.add_argument("--shots", type=int, default=2)
    sp.add_argument("--pre", type=float, default=1.0, help="seconds recorded before TX starts")
    sp.add_argument("--post", type=float, default=1.0)
    sp.add_argument("--settle", type=float, default=2.0)
    sp.add_argument("--tx-timeout", type=float, default=60.0)
    sp.add_argument("--full", action="store_true", help="keep recording for --seconds even if TX ends early")
    sp.add_argument("--analyze", action="store_true")
    sp.add_argument("--out-dir", default=str(sdrpp.OUT))
    a = ap.parse_args(argv)

    if a.cmd == "backup":
        print(sdrpp.backup_config(overwrite=a.overwrite))
    elif a.cmd == "restore":
        sdrpp.restore_config(relaunch=a.relaunch)
        print("restored from", sdrpp.BACKUP_DIR)
    elif a.cmd == "status":
        print(json.dumps(sdrpp.status(), indent=2))
    elif a.cmd == "launch":
        sdrpp.launch()
        print("rigctl up")
    elif a.cmd == "quit":
        sdrpp.quit_app()
    elif a.cmd == "user":
        sdrpp.quit_app()
        subprocess.run(["open", "-a", sdrpp.APP])
    elif a.cmd == "setup":
        fix_rate(a)
        if not sdrpp.ISOLATED:
            sdrpp.backup_config()
        sdrpp.restart_with(profile_from(a), start_source=not a.no_start)
        print(json.dumps(sdrpp.status(), indent=2))
    elif a.cmd == "rig":
        print(sdrpp.rig(a.command))
    elif a.cmd == "tune":
        print(sdrpp.tune(a.freq))
    elif a.cmd == "record":
        print(sdrpp.record(a.seconds, dest=a.out))
    elif a.cmd == "shot":
        print(sdrpp.grab(a.path))
    elif a.cmd == "analyze":
        print(json.dumps(analyze(Path(a.path), Path(a.png) if a.png else None, a.center), indent=2))
    elif a.cmd == "capture":
        cmd_capture(a, tx)


if __name__ == "__main__":
    main()
