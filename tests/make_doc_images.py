#!/usr/bin/env python3
"""Rebuild the documentation figures from over-the-air captures.

    python tests/ota_test.py                  # first: records tmp/ota/<case>.wav (HackRF -> RTL-SDR in SDR++)
    python tests/make_doc_images.py           # then: writes the PNGs used by knowledge/ and signal_generation/

Every figure is made from real received IQ (433.92 MHz, RTL-SDR Blog V4, 1.024 MS/s), not simulation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from rfkit import bits, dsp, iq  # noqa: E402

OTA = REPO / "tmp" / "ota"
KNOW = REPO / "knowledge" / "images"
GEN = REPO / "signal_generation" / "images"
OFFSET = 102e3            # nominal +100 kHz plus the measured ~2 kHz crystal error


def load(name, skip=0.05):
    x, fs = iq.load(OTA / f"{name}.wav")
    return x[int(skip * fs):], fs


def first_burst(x, fs, **kw):
    segs = dsp.bursts(x, fs, **kw)
    return segs[0][0] if segs else 0


def waterfall_panel(ax, name, title, span_s, half_bw, nfft, center=OFFSET, pre_s=None, merge=0.05):
    x, fs = load(name)
    y, fs2 = dsp.channelize(x, fs, center, 2 * half_bw * 1.1, out_fs=4 * half_bw)
    pre_s = min(0.02, span_s / 6) if pre_s is None else pre_s
    s0 = max(0, first_burst(y, fs2, merge_gap_s=merge, min_len_s=5e-4) - int(pre_s * fs2))
    y = y[s0:s0 + int(span_s * fs2)]
    hop = max(1, min(nfft // 2, len(y) // 400))
    f, t, S = dsp.spectrogram(y, fs2, nfft, hop)
    keep = np.abs(f) <= half_bw
    S = S[:, keep]
    vmax = np.percentile(S, 99.7)
    ax.imshow(S, aspect="auto", cmap="viridis", vmin=vmax - 45, vmax=vmax, interpolation="nearest",
              extent=[f[keep][0] / 1e3, f[keep][-1] / 1e3, t[-1] * 1e3, t[0] * 1e3])
    ax.set_title(title, fontsize=10)
    ax.set_xlabel("kHz from signal centre", fontsize=8)
    ax.set_ylabel("ms", fontsize=8)
    ax.tick_params(labelsize=7)


def gallery():
    panels = [
        ("tone", "Carrier (tone)", 0.4, 15e3, 2048),
        ("morse", "CW Morse, 20 WPM", 3.0, 3e3, 256),
        ("am", "AM, 800 Hz tone", 0.5, 6e3, 2048),
        ("nfm", "NFM, 1 kHz tone, ±5 kHz", 0.5, 15e3, 1024),
        ("ook", "OOK 1 kbit/s (3 packets)", 0.9, 10e3, 512),
        ("ook_manchester", "OOK Manchester 1 kbit/s", 0.9, 10e3, 512),
        ("fsk", "2-FSK 5 kBd, ±20 kHz", 0.12, 45e3, 256),
        ("gfsk", "GFSK BT 0.5, 10 kBd, ±10 kHz", 0.08, 30e3, 128),
        ("bpsk", "BPSK 50 kBd RRC (one 3 ms burst)", 0.006, 70e3, 32),
        ("qpsk", "QPSK 50 kBd RRC (one 3 ms burst)", 0.006, 70e3, 32),
        ("chirp", "Linear chirps ±100 kHz", 0.35, 120e3, 256),
        ("css", "LoRa-style CSS, SF8, 125 kHz (one frame)", 0.04, 80e3, 32),
    ]
    fig, axes = plt.subplots(3, 4, figsize=(16, 12))
    for ax, (name, title, span, hbw, nfft) in zip(axes.flat, panels):
        waterfall_panel(ax, name, title, span, hbw, nfft,
                        merge=0.3 if name in ("morse", "am", "nfm", "tone") else 0.05)
    fig.suptitle("Waterfall fingerprints — real over-the-air captures (HackRF TX → RTL-SDR, 433.92 MHz). "
                 "Time runs down.", fontsize=12)
    fig.tight_layout()
    KNOW.mkdir(parents=True, exist_ok=True)
    fig.savefig(KNOW / "waterfall_fingerprints.png", dpi=72)
    plt.close(fig)


def demod_steps():
    """OOK envelope + threshold, FSK discriminator, QPSK constellation, Morse envelope: one row each."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 8.5))
    # OOK
    x, fs = load("ook")
    y, fs2 = dsp.channelize(x, fs, OFFSET, 20e3)
    s, e = dsp.bursts(y, fs2, merge_gap_s=0.03)[0]
    env = np.abs(y[s - 200:e + 200])
    thr = dsp.otsu_threshold(env)
    sps = fs2 / 1000
    tt = np.arange(len(env)) / fs2 * 1e3
    ax = axes[0, 0]
    ax.plot(tt, env, lw=0.6)
    ax.axhline(thr, color="k", ls="--", lw=0.8, label="Otsu threshold")
    ax.set_xlim(0, 60)
    ax.set_title("OOK: envelope |x| and threshold (first 60 ms: preamble AA AA, sync 2D D4)")
    ax.set_xlabel("ms")
    ax.legend(loc="upper right", fontsize=8)
    # FSK
    x, fs = load("fsk")
    y, fs2 = dsp.channelize(x, fs, 102e3, 80e3)
    s, e = dsp.bursts(y, fs2)[0]
    inst = dsp.fm_discriminator(y[s:e], fs2)
    filt = dsp.lowpass(inst, 0.75 * 5000, fs2)
    tt = np.arange(len(inst)) / fs2 * 1e3
    ax = axes[0, 1]
    ax.plot(tt, inst / 1e3, lw=0.4, alpha=0.4, label="discriminator (raw)")
    ax.plot(tt, filt / 1e3, lw=1.0, label="post-detection low-pass")
    ax.axhline(dsp.otsu_threshold(filt) / 1e3, color="k", ls="--", lw=0.8, label="threshold")
    ax.set_xlim(0, 12)
    ax.set_ylim(-35, 35)
    ax.set_title("2-FSK: instantaneous frequency (first 12 ms of a packet)")
    ax.set_xlabel("ms")
    ax.set_ylabel("kHz")
    ax.legend(loc="upper right", fontsize=8)
    # QPSK constellation (all bursts)
    x, fs = load("qpsk")
    y, fs2 = dsp.channelize(x, fs, OFFSET, 75e3, out_fs=400e3)
    syms = []
    for s, e in dsp.bursts(y, fs2, min_len_s=5e-4, merge_gap_s=1e-3):
        out = dsp.psk_demod(y[s:e], fs2, 50e3, 4)
        syms.append(out[len(out) // 3:])            # after the Costas loop has settled
    syms = np.concatenate(syms)
    ax = axes[1, 0]
    ax.plot(syms.real, syms.imag, ".", ms=3, alpha=0.6)
    ax.set_aspect("equal")
    ax.set_xlim(-1.6, 1.6)
    ax.set_ylim(-1.6, 1.6)
    ax.axhline(0, color="k", lw=0.5)
    ax.axvline(0, color="k", lw=0.5)
    ax.set_title("QPSK: symbols after CFO removal, RRC matched filter, timing, Costas loop")
    ax.set_xlabel("I")
    ax.set_ylabel("Q")
    # Morse
    x, fs = load("morse")
    y, fs2 = dsp.channelize(x, fs, OFFSET, 1_000)
    env = dsp.moving_average(np.abs(y), int(0.004 * fs2))
    segs = dsp.bursts(y, fs2, merge_gap_s=0.6)
    s, e = segs[0][0], segs[-1][1]
    env = env[max(0, s - int(0.1 * fs2)):e + int(0.1 * fs2)]
    thr = dsp.otsu_threshold(env)
    ax = axes[1, 1]
    ax.plot(np.arange(len(env)) / fs2, env, lw=0.7)
    ax.axhline(thr, color="k", ls="--", lw=0.8)
    text = bits.morse_from_runs(dsp.runs(env > thr)[1:])
    ax.set_title(f"Morse: smoothed envelope → run lengths → \"{text}\"")
    ax.set_xlabel("s")
    fig.tight_layout()
    fig.savefig(KNOW / "demod_steps.png", dpi=72)
    plt.close(fig)


def single(name, path, title, span_s, half_bw, nfft, w=8, h=4.5):
    fig, ax = plt.subplots(figsize=(w, h))
    waterfall_panel(ax, name, title, span_s, half_bw, nfft)
    fig.tight_layout()
    fig.savefig(path, dpi=80)
    plt.close(fig)


def nfm_audio():
    from rfkit import dsp as d
    x, fs = load("nfm")
    y, fs2 = d.channelize(x, fs, OFFSET, 20e3, out_fs=96e3)
    s, e = d.bursts(y, fs2, merge_gap_s=0.3)[0]
    audio, afs = d.fm_demod(y[s:e], fs2, deviation_hz=5e3, deemph_us=None)
    audio -= audio.mean()
    f, p = d.psd(audio, afs, 8192)
    fig, (a0, a1) = plt.subplots(1, 2, figsize=(12, 3.8))
    tt = np.arange(len(audio)) / afs * 1e3
    a0.plot(tt, audio, lw=0.8)
    a0.set_xlim(100, 105)
    a0.set_ylim(-1.5, 1.5)
    a0.set_title("NFM demodulated audio (5 ms)")
    a0.set_xlabel("ms")
    m = (f >= 0) & (f < 5000)
    a1.plot(f[m], p[m], lw=0.8)
    a1.set_title("Audio spectrum: 1 kHz tone recovered")
    a1.set_xlabel("Hz")
    a1.set_ylabel("dB")
    fig.tight_layout()
    fig.savefig(GEN / "nfm_audio_ota.png", dpi=80)
    plt.close(fig)


if __name__ == "__main__":
    gallery()
    demod_steps()
    single("gfsk", GEN / "gfsk_ota_waterfall.png", "GFSK (BT 0.5, 10 kBd, ±10 kHz): one packet, over the air",
           0.035, 30e3, 64)
    single("fsk", GEN / "fsk_ota_waterfall.png", "2-FSK (5 kBd, ±20 kHz): one packet, over the air",
           0.045, 40e3, 128)
    single("chirp", GEN / "chirp_ota_waterfall.png", "Linear chirps −100 → +100 kHz, 50 ms each", 0.35, 120e3,
           256)
    single("css", GEN / "css_ota_waterfall.png", "LoRa-style CSS frame: 8 up-chirps, sync down-chirps, data",
           0.04, 80e3, 32)
    nfm_audio()
    print("done")
