#!/usr/bin/env python3
"""Turn hackrf_sweep or rtl_power CSV into a waterfall/heatmap PNG and a list of the strongest frequencies.

    hackrf_sweep -f 400:500 -w 100000 -N 20 -r sweep.csv      # 20 sweeps, 100 kHz bins
    rtl_power -f 88M:108M:100k -i 2 -e 60 power.csv           # 60 s, 2 s integration
    sweep_plot.py sweep.csv [--png sweep.png] [--top 15]

Both tools write the same row layout:  date, time, hz_low, hz_high, hz_bin_width, num_samples, dB, dB, ...
Rows with the same timestamp are one sweep; they are stitched into one spectrum per sweep.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import OrderedDict
from pathlib import Path

import numpy as np


def load(path):
    sweeps: "OrderedDict[str, dict]" = OrderedDict()
    with open(path) as f:
        for row in csv.reader(f):
            if len(row) < 7:
                continue
            ts = row[0].strip() + " " + row[1].strip()
            lo, hi, step = float(row[2]), float(row[3]), float(row[4])
            vals = [float(v) for v in row[6:] if v.strip() not in ("", "nan", "-nan")]
            freqs = lo + step * (np.arange(len(vals)) + 0.5)
            d = sweeps.setdefault(ts, {})
            for fq, v in zip(freqs, vals):
                d[round(fq)] = v
    if not sweeps:
        sys.exit("no data rows")
    all_f = sorted({fq for d in sweeps.values() for fq in d})
    idx = {fq: i for i, fq in enumerate(all_f)}
    M = np.full((len(sweeps), len(all_f)), np.nan)
    for r, d in enumerate(sweeps.values()):
        for fq, v in d.items():
            M[r, idx[fq]] = v
    return np.array(all_f, float), list(sweeps.keys()), M


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--png")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--min-sep", type=float, default=200e3, help="Hz between reported peaks")
    a = ap.parse_args()
    f, times, M = load(a.csv)
    peak = np.nanmax(M, axis=0)
    mean = np.nanmean(M, axis=0)
    floor = float(np.nanpercentile(mean, 20))
    order = np.argsort(peak)[::-1]
    picks = []
    for i in order:
        if np.isnan(peak[i]):
            continue
        if all(abs(f[i] - f[j]) >= a.min_sep for j in picks):
            picks.append(i)
        if len(picks) >= a.top:
            break
    rep = {"file": a.csv, "sweeps": len(times), "span_mhz": [round(f[0] / 1e6, 3), round(f[-1] / 1e6, 3)],
           "bin_hz": round(float(np.median(np.diff(f)))) if len(f) > 1 else None, "floor_db": round(floor, 1),
           "strongest": [{"mhz": round(f[i] / 1e6, 4), "peak_db": round(float(peak[i]), 1),
                          "mean_db": round(float(mean[i]), 1), "over_floor_db": round(float(peak[i] - floor), 1),
                          "duty": round(float(np.nanmean(M[:, i] > floor + 10)), 2)} for i in picks]}
    png = a.png or str(Path(a.csv).with_suffix(".png"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[1, 2], sharex=True)
    ax0.plot(f / 1e6, peak, lw=0.6, label="max hold")
    ax0.plot(f / 1e6, mean, lw=0.6, label="mean")
    ax0.set_ylabel("dB")
    ax0.legend()
    ax0.grid(alpha=0.3)
    vmax = np.nanpercentile(M, 99.5)
    ax1.imshow(M, aspect="auto", extent=[f[0] / 1e6, f[-1] / 1e6, len(times), 0], vmin=floor - 5, vmax=vmax,
               cmap="viridis", interpolation="nearest")
    ax1.set_xlabel("Frequency (MHz)")
    ax1.set_ylabel("Sweep #")
    fig.tight_layout()
    fig.savefig(png, dpi=100)
    rep["png"] = png
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
