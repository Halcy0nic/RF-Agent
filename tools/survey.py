#!/usr/bin/env python3
"""Wide-band survey of an IQ recording: when and where is there activity, and what is it doing?

    survey.py cap.cs16 --fs 30e6 --center 915e6              # table + PNG + JSON next to the file
    survey.py cap.cu8 --fs 2.4e6 --center 433.92e6 --row-ms 5 --thresh 12
    survey.py cap.sigmf-data --png map.png --json events.json --top 20

Output sections:
  carriers   continuous lines (always on): spurs, LO leakage, steady transmitters
  beacons    one frequency, regular repeats for the whole capture (fixed chatter, decoys)
  hoppers    the same burst shape repeating on one frequency for a while, then a different frequency (dwells)
  one-offs   everything else
Frequencies are refined with a long FFT inside each event, so they are good to a few hundred Hz even though the
map has kHz-wide bins. The PNG marks every event on the map; the JSON has all of them for scripts.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rfkit import iq, survey  # noqa: E402


def f_num(s: str) -> float:
    s = s.strip().lower().replace("_", "")
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(s[-1], 1)
    return float(s[:-1] if s[-1] in "kmg" else s) * mult


def refine(path, fs, fc, ev, fmt):
    """Long-FFT frequency inside the strongest part of each event (the map's bins are too coarse)."""
    for e in ev:
        if e.get("kind") == "carrier":
            continue
        x, _ = iq.load(path, fs=fs, fmt=fmt, offset_s=e["t_s"], seconds=max(e["dur_s"], 0.005))
        n = 1 << int(np.floor(np.log2(min(len(x), 1 << 20))))
        if n < 1024:
            continue
        seg = x[:n]
        sp = np.abs(np.fft.fft(seg * np.hanning(n))) ** 2
        fr = np.fft.fftfreq(n, 1 / fs)
        sel = np.abs(fr - (e["freq_hz"] - fc)) < max(e["bw_hz"], 20e3)
        if sel.any():
            e["freq_hz"] = float(fc + fr[sel][np.argmax(sp[sel])])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--fs", type=f_num)
    ap.add_argument("--center", type=f_num, help="tuned centre frequency, Hz (default: from the file name/sidecar)")
    ap.add_argument("--row-ms", type=float, default=10.0, help="time resolution of the map")
    ap.add_argument("--nfft", type=int, default=4096)
    ap.add_argument("--thresh", type=float, default=15.0, help="dB over the noise floor for an event")
    ap.add_argument("--min-ms", type=float, default=20.0, help="shortest event kept")
    ap.add_argument("--offset", type=float, default=0.0, help="start at this many seconds")
    ap.add_argument("--seconds", type=float, help="only survey this many seconds")
    ap.add_argument("--top", type=int, default=15, help="rows to print per section")
    ap.add_argument("--no-refine", action="store_true")
    ap.add_argument("--png", help="map image (default <file>_survey.png, 'none' to skip)")
    ap.add_argument("--json", help="event list (default <file>_survey.json, 'none' to skip)")
    a = ap.parse_args()

    fmt = iq.fmt_of(a.file)
    _, fs0 = iq.load(a.file, fs=a.fs, seconds=1e-6)
    fs = a.fs or fs0
    if not fs:
        sys.exit("raw file: pass --fs")
    center = a.center if a.center is not None else iq.info_from_name(a.file).get("center_hz", 0.0)
    block_s = max(1.0, 100 * a.row_ms / 1e3)
    block_s = round(block_s / (a.row_ms / 1e3)) * a.row_ms / 1e3          # whole number of rows
    total = a.seconds
    def blocks():
        t = a.offset
        while True:
            want = block_s if total is None else min(block_s, a.offset + total - t)
            if want <= 0:
                return
            x, _ = iq.load(a.file, fs=fs, fmt=fmt, offset_s=t, seconds=want)
            if len(x) < int(0.5 * want * fs):
                if len(x):
                    yield x
                return
            yield x
            t += want
    S, f = survey.tfmap(blocks(), fs, a.row_ms / 1e3, a.nfft)
    row_s = a.row_ms / 1e3
    span = S.shape[0] * row_s
    ev = survey.find_events(S, f, row_s, center, a.thresh, a.min_ms / 1e3)
    ev = [dict(e, t_s=e["t_s"] + a.offset) if "t_s" in e else e for e in ev]
    if not a.no_refine and len(ev) < 2000:
        refine(a.file, fs, center, ev, fmt)
    groups = survey.classify(ev, span)

    def mhz(v):
        return f"{v / 1e6:.4f}"

    print(f"{a.file}: {span:.2f} s, fs {fs / 1e6:g} MS/s, centre {center / 1e6:g} MHz, floor {survey.noise_floor(S):.1f} dB, "
          f"{S.shape[0]} rows x {S.shape[1]} bins")
    if groups["carriers"]:
        print(f"\ncarriers (always on): {len(groups['carriers'])}")
        for c in sorted(groups["carriers"], key=lambda c: -c["level_db"])[: a.top]:
            print(f"  {mhz(c['freq_hz'])} MHz  +{c['level_db']:.0f} dB")
    print(f"\nbeacons (regular repeats all capture long): {len(groups['beacons'])}")
    for b in sorted(groups["beacons"], key=lambda b: -b["level_db"])[: a.top]:
        print(f"  {mhz(b['freq_hz'])} MHz  {b['count']}x  every {b['period_s'] * 1e3:.0f} ms, {b['dur_s'] * 1e3:.0f} ms long, +{b['level_db']:.0f} dB")
    print(f"\nhoppers (same burst shape, frequency changes in steps): {len(groups['hoppers'])}")
    for h in groups["hoppers"]:
        print(f"  burst {h['dur_s'] * 1e3:.0f} ms every {h['period_s'] * 1e3:.0f} ms, {len(h['dwells'])} dwells:")
        for d in h["dwells"][: a.top]:
            print(f"    {d['first_s']:7.2f}-{d['last_s'] + d['dur_s']:7.2f} s  {mhz(d['freq_hz'])} MHz  {d['count']} bursts  +{d['level_db']:.0f} dB")
    print(f"\none-offs: {len(groups['one_offs'])}")
    for e in sorted(groups["one_offs"], key=lambda e: -e["level_db"])[: a.top]:
        print(f"  {e['t_s']:7.2f} s  {e['dur_s'] * 1e3:6.0f} ms  {mhz(e['freq_hz'])} MHz  bw {e['bw_hz'] / 1e3:.0f} kHz  +{e['level_db']:.0f} dB")

    stem = str(Path(a.file).with_suffix(""))
    js = None if (a.json or "").lower() == "none" else (a.json or stem + "_survey.json")
    if js:
        Path(js).write_text(json.dumps({"file": a.file, "fs": fs, "center_hz": center, "span_s": span, **groups}, indent=2))
        print(f"\njson: {js}")
    png = None if (a.png or "").lower() == "none" else (a.png or stem + "_survey.png")
    if png:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        floor = survey.noise_floor(S)
        fig, ax = plt.subplots(figsize=(11, 7))
        ax.imshow(S, aspect="auto", origin="upper", cmap="viridis", vmin=floor, vmax=floor + 45,
                  extent=[(center + f[0]) / 1e6, (center + f[-1]) / 1e6, a.offset + span, a.offset])
        for b in groups["beacons"]:
            ax.plot([b["freq_hz"] / 1e6] * 2, [a.offset, a.offset + span], color="w", lw=0.4, alpha=0.5)
        for h in groups["hoppers"]:
            for d in h["dwells"]:
                ax.plot([d["freq_hz"] / 1e6] * 2, [d["first_s"], d["last_s"] + d["dur_s"]], color="red", lw=2)
        ax.set_xlabel("MHz")
        ax.set_ylabel("s")
        ax.set_title("survey: red = hopper dwells, white = beacons")
        fig.tight_layout()
        fig.savefig(png, dpi=110)
        print(f"png: {png}")


if __name__ == "__main__":
    main()
