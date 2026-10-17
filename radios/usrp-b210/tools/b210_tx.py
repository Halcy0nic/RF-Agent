#!/usr/bin/env python3
"""Transmit an IQ file from a USRP B200/B210 with UHD's tx_samples_from_file.

Any format rfkit reads (.cs8 HackRF files, .cu8, .cs16, .cf32, .wav, .sigmf-data) is converted to complex
float32 on the fly, so files made for the HackRF play unchanged (pass the rate they were generated at).

    b210_tx.py signal.cs8 --freq 433.92e6 --rate 2e6 --gain 60
    b210_tx.py signal.cf32 --freq 915e6 --rate 2e6 --gain 70 --channel 1 --repeat 3 --gap 1
    b210_tx.py --dry-run signal.cs8 --freq 2.44e9 --rate 10e6 --gain 50

TX gain is 0-89.75 dB. TX only comes out of the TX/RX port of the chosen channel
(OpenSourceSDRLab Artix-7 board: channel 0 = TRX1, channel 1 = TRX2).
Needs UHD_IMAGES_DIR set (radios/usrp-b210/tools/setup_images.sh).
"""
from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
sys.path.insert(0, str(HERE))
from b210_rx import f_num, uhd_env, uhd_example  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--freq", type=f_num, required=True)
    ap.add_argument("--rate", type=f_num, required=True, help="sample rate the file was generated at")
    ap.add_argument("--gain", type=float, default=60, help="TX gain dB (0-89.75)")
    ap.add_argument("--channel", default="0")
    ap.add_argument("--peak", type=float, default=0.7, help="rescale so the peak is this fraction of full scale")
    ap.add_argument("--repeat", type=int, default=1, help="play the file this many times")
    ap.add_argument("--gap", type=float, default=0.5, help="seconds between plays")
    ap.add_argument("--args", default="type=b200")
    ap.add_argument("--extra", default="", help="extra tx_samples_from_file arguments")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src = Path(a.file)
    if not src.exists():
        sys.exit(f"no such file: {src}")
    tmpdir = None
    if src.suffix in (".cf32", ".fc32", ".cfile") and a.peak is None:
        play = src
    else:
        from rfkit import iq
        x, _ = iq.load(src, fs=a.rate)
        tmpdir = tempfile.TemporaryDirectory()
        play = Path(tmpdir.name) / "tx.cf32"
        iq.save(play, x, peak=a.peak)
    n = play.stat().st_size // 8
    cmd = [uhd_example("tx_samples_from_file"), "--args", a.args, "--file", str(play), "--type", "float",
           "--rate", str(a.rate), "--freq", str(a.freq), "--gain", str(a.gain), "--ant", "TX/RX",
           "--channels", a.channel]
    if a.extra:
        cmd += a.extra.split()
    print(f"file: {n:,} samples = {n / a.rate:.2f} s at {a.rate / 1e6:g} MS/s, x{a.repeat}")
    print("$ " + " ".join(cmd), flush=True)
    if a.dry_run:
        return
    rc = 0
    try:
        for i in range(a.repeat):
            if i:
                time.sleep(a.gap)
            p = subprocess.Popen(cmd, env=uhd_env())
            try:
                rc = p.wait()
            except KeyboardInterrupt:
                p.send_signal(signal.SIGINT)
                p.wait(5)
                rc = 130
                break
            if rc != 0:
                break
    finally:
        if tmpdir:
            tmpdir.cleanup()
    sys.exit(rc)


if __name__ == "__main__":
    main()
