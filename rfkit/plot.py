"""Matplotlib helpers that write PNGs (headless, Agg backend). An agent can look at the PNG to "see" a signal.

    plot.overview(x, fs, "cap.png", center_hz=433.92e6)   # PSD + waterfall + magnitude in one image
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from . import dsp  # noqa: E402


def _save(fig, path, dpi=110):
    from pathlib import Path
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi)


def _fmt_freq_axis(ax, center_hz, axis="x"):
    unit = "kHz offset" if not center_hz else "MHz"
    (ax.set_xlabel if axis == "x" else ax.set_ylabel)(f"Frequency ({unit})")


def _f(f, center_hz):
    return (center_hz + f) / 1e6 if center_hz else f / 1e3


def psd(x, fs, path, center_hz=0.0, nfft=4096, title=None):
    f, p = dsp.psd(x, fs, nfft)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(_f(f, center_hz), p, lw=0.8)
    ax.set_ylabel("Power (dB, relative)")
    _fmt_freq_axis(ax, center_hz)
    ax.grid(alpha=0.3)
    ax.set_title(title or "Power spectral density")
    fig.tight_layout()
    _save(fig, path, dpi=110)
    plt.close(fig)
    return path


def waterfall(x, fs, path, center_hz=0.0, nfft=1024, hop=None, title=None, max_rows=2000, dyn_range_db=60,
              time_down=True):
    """Spectrogram drawn like an SDR waterfall: frequency across, time running downward."""
    hop = hop or max(nfft // 2, len(x) // max_rows)
    f, t, S = dsp.spectrogram(x, fs, nfft, hop)
    vmax = np.percentile(S, 99.9)
    fig, ax = plt.subplots(figsize=(10, 6))
    extent = [_f(f[0], center_hz), _f(f[-1], center_hz), t[-1], t[0]] if time_down else \
             [_f(f[0], center_hz), _f(f[-1], center_hz), t[0], t[-1]]
    ax.imshow(S if time_down else S[::-1], aspect="auto", extent=extent, vmin=vmax - dyn_range_db, vmax=vmax,
              cmap="viridis", interpolation="nearest")
    ax.set_ylabel("Time (s)")
    _fmt_freq_axis(ax, center_hz)
    ax.set_title(title or "Waterfall")
    fig.tight_layout()
    _save(fig, path, dpi=110)
    plt.close(fig)
    return path


def overview(x, fs, path, center_hz=0.0, nfft=2048, title=None):
    """Three panels: PSD, waterfall, |x| vs time. The first thing to look at for an unknown recording."""
    f, p = dsp.psd(x, fs, nfft)
    hop = max(nfft // 2, len(x) // 1500)
    fs_, t, S = dsp.spectrogram(x, fs, nfft, hop)
    fig = plt.figure(figsize=(11, 10))
    gs = fig.add_gridspec(3, 1, height_ratios=[1, 2.2, 1])
    a0 = fig.add_subplot(gs[0])
    a0.plot(_f(f, center_hz), p, lw=0.7)
    a0.set_ylabel("dB")
    a0.grid(alpha=0.3)
    a0.set_xlim(_f(f[0], center_hz), _f(f[-1], center_hz))
    a0.set_title(title or "Overview")
    a1 = fig.add_subplot(gs[1], sharex=a0)
    vmax = np.percentile(S, 99.9)
    a1.imshow(S, aspect="auto", extent=[_f(fs_[0], center_hz), _f(fs_[-1], center_hz), t[-1], t[0]],
              vmin=vmax - 60, vmax=vmax, cmap="viridis", interpolation="nearest")
    a1.set_ylabel("Time (s)")
    _fmt_freq_axis(a1, center_hz)
    a2 = fig.add_subplot(gs[2])
    dec = max(1, len(x) // 200_000)
    a2.plot(np.arange(0, len(x), dec) / fs, np.abs(x[::dec]), lw=0.5)
    a2.set_xlabel("Time (s)")
    a2.set_ylabel("|x|")
    a2.grid(alpha=0.3)
    fig.tight_layout()
    _save(fig, path, dpi=100)
    plt.close(fig)
    return path


def timeseries(y, fs, path, title=None, ylabel="", threshold=None, marks=None):
    fig, ax = plt.subplots(figsize=(11, 3.5))
    ax.plot(np.arange(len(y)) / fs * 1e3, y, lw=0.7)
    if threshold is not None:
        ax.axhline(threshold, color="k", ls="--", lw=0.8)
    if marks is not None:
        idx, vals = marks
        ax.plot(np.asarray(idx) / fs * 1e3, vals, "k.", ms=3)
    ax.set_xlabel("Time (ms)")
    ax.set_ylabel(ylabel)
    ax.grid(alpha=0.3)
    ax.set_title(title or "")
    fig.tight_layout()
    _save(fig, path, dpi=110)
    plt.close(fig)
    return path


def constellation(symbols, path, title=None):
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot(symbols.real, symbols.imag, ".", ms=2, alpha=0.5)
    lim = 1.5 * np.max(np.abs(symbols))
    ax.set_xlim(-lim, lim)
    ax.set_ylim(-lim, lim)
    ax.axhline(0, color="k", lw=0.5)
    ax.axvline(0, color="k", lw=0.5)
    ax.set_aspect("equal")
    ax.set_xlabel("I")
    ax.set_ylabel("Q")
    ax.set_title(title or "Constellation")
    fig.tight_layout()
    _save(fig, path, dpi=110)
    plt.close(fig)
    return path


def eye(y, sps, path, n_traces=200, title=None):
    sps = int(round(sps))
    fig, ax = plt.subplots(figsize=(6, 4))
    for k in range(min(n_traces, len(y) // sps - 2)):
        ax.plot(np.real(y[k * sps:k * sps + 2 * sps]), color="C0", alpha=0.15, lw=0.7)
    ax.set_xlabel("Sample within 2 symbols")
    ax.set_title(title or "Eye diagram")
    fig.tight_layout()
    _save(fig, path, dpi=110)
    plt.close(fig)
    return path
