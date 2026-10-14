#!/usr/bin/env python3
"""First look at any IQ recording: summary JSON + an overview PNG (PSD, waterfall, magnitude).

    iq_inspect.py baseband_433920000Hz_12-00-00_14-10-2026.wav           # SDR++ WAV: rate + centre from file
    iq_inspect.py capture.cu8 --fs 2.048e6 --center 433.92e6              # rtl_sdr
    iq_inspect.py capture.cs8 --fs 8e6 --center 915e6 --seconds 2         # hackrf_transfer
    iq_inspect.py capture.cf32 --fs 1e6 --png out.png --nfft 4096

Prints: duration, level statistics (clipping check), strongest signals with absolute frequency, SNR and
bandwidth, number of bursts with their timing, DC-spike level. The PNG goes next to the input by default.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rfkit import dsp, iq, plot  # noqa: E402


def f_num(s: str) -> float:
    s = s.strip().lower().replace("_", "")
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(s[-1], 1)
    return float(s[:-1] if s[-1] in "kmg" else s) * mult


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--fs", type=f_num, help="sample rate (required for raw .cu8/.cs8/.cs16/.cf32)")
    ap.add_argument("--center", type=f_num, help="tuned centre frequency, Hz (for absolute frequencies)")
    ap.add_argument("--offset", type=float, default=0.0, help="start at this many seconds")
    ap.add_argument("--seconds", type=float, help="only analyse this many seconds")
    ap.add_argument("--nfft", type=int, default=8192)
    ap.add_argument("--png", help="overview image path (default: <file>.png; 'none' to skip)")
    ap.add_argument("--max-peaks", type=int, default=8)
    a = ap.parse_args()

    x, fs = iq.load(a.file, fs=a.fs, offset_s=a.offset, seconds=a.seconds)
    if fs is None:
        sys.exit("raw file: pass --fs")
    center = a.center if a.center is not None else iq.info_from_name(a.file).get("center_hz", 0.0)
    mag = np.abs(x)
    i_q = np.concatenate([x.real, x.imag])
    full_scale = 1.0
    clip = float(np.mean(np.abs(i_q) >= 0.99 * full_scale))
    f, p = dsp.psd(x, fs, a.nfft)
    floor = dsp.noise_floor_db(p)
    dc_bin = int(np.argmin(np.abs(f)))
    segs = dsp.bursts(x, fs)
    gated = dsp.gate(x, fs) if segs and sum(e - s for s, e in segs) < 0.5 * len(x) else x
    peaks = dsp.find_carriers(gated if len(gated) > a.nfft else x, fs, a.nfft, exclude_dc_hz=2 * fs / a.nfft * 3,
                              max_peaks=a.max_peaks)
    rep = {
        "file": a.file, "fs": fs, "center_hz": center, "samples": len(x), "seconds": round(len(x) / fs, 4),
        "levels": {"rms": round(float(np.sqrt(np.mean(mag ** 2))), 4), "peak": round(float(mag.max()), 4),
                   "clipped_fraction": round(clip, 6),
                   "dc_offset": [round(float(x.real.mean()), 4), round(float(x.imag.mean()), 4)]},
        "noise_floor_db": round(floor, 1),
        "dc_spike_db_over_floor": round(float(p[dc_bin] - floor), 1),
        "signals": [{"abs_freq_mhz": round((center + s["freq_hz"]) / 1e6, 6), "offset_hz": round(s["freq_hz"], 1),
                     "snr_db": round(s["snr_db"], 1), "bw_10db_hz": round(s["bw_10db_hz"]),
                     "bw_occupied_hz": round(s["bw_occ_hz"])} for s in peaks],
        "bursts": {"count": len(segs),
                   "first": [[round(s / fs, 4), round((e - s) / fs * 1e3, 2)] for s, e in segs[:10]],
                   "note": "[start_s, duration_ms]"},
    }
    if clip > 1e-4:
        rep["warning"] = "clipping: lower the RX gain"
    png = None if (a.png or "").lower() == "none" else (a.png or str(Path(a.file).with_suffix("")) + "_overview.png")
    if png:
        plot.overview(x, fs, png, center_hz=center, nfft=min(2048, a.nfft), title=Path(a.file).name)
        rep["png"] = png
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
