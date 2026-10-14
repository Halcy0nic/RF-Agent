#!/usr/bin/env python3
"""Generate test signals as IQ files (CS8 for HackRF by default) with rfkit.

    generate.py tone   --offset 100e3 --seconds 2                         -o tone.cs8
    generate.py morse  --text "CQ TEST" --wpm 15                          -o morse.cs8
    generate.py ook    --text "HELLO" --rate 1000 [--manchester]          -o ook.cs8
    generate.py fsk    --text "HELLO" --rate 5000 --dev 20e3 [--bt 0.5] [--levels 4]  -o fsk.cs8
    generate.py psk    --text "HELLO" --scheme qpsk --rate 50e3           -o psk.cs8
    generate.py am|fm  --audio voice.wav | --audio-tone 1000 [--dev 75e3] -o fm.cs8
    generate.py chirp  --f0 -200e3 --f1 200e3 --seconds 0.01 --repeat 50  -o chirp.cs8
    generate.py css    --sf 7 --bw 125e3 --values 1,2,3                   -o lora_like.cs8
    generate.py text   --text "RF AGENT" --bw 150e3                       -o paint.cs8   (text in the waterfall)
    generate.py noise  --bw 200e3 --seconds 1                             -o noise.cs8

Common options: --fs (default 2e6), --offset (Hz from the tuned centre, default 100e3), --repeat N, --gap S,
--pad S (silence before/after), --snr DB (add noise), --peak (0-1 full-scale), --plot (PNG overview next to file).
Prints the matching hackrf_transfer command. Output format follows the extension: .cs8 .cu8 .cs16 .cf32 .wav .sigmf-data
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rfkit import bits, dsp, iq, mod  # noqa: E402


def f_num(s: str) -> float:
    s = s.strip().lower().replace("_", "")
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(s[-1], 1)
    return float(s[:-1] if s[-1] in "kmg" else s) * mult


def payload_bits(a) -> np.ndarray:
    data = a.text.encode() if a.text else bytes.fromhex(a.hex)
    if a.raw:
        return bits.from_bytes(data)
    pre_len = a.pre_len = a.preamble if a.preamble is not None else (8 if a.kind == "psk" else 2)
    return bits.frame(data, preamble=b"\xaa" * pre_len, whitening=a.whiten)


def load_audio(a, fs_out: float) -> np.ndarray:
    if a.audio:
        import wave
        with wave.open(a.audio) as w:
            n, ch, sw, afs = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = np.frombuffer(w.readframes(n), dtype={1: np.uint8, 2: np.int16, 4: np.int32}[sw])
        audio = raw.reshape(-1, ch).mean(1).astype(np.float64)
        audio = (audio - 128) / 128 if sw == 1 else audio / float(2 ** (8 * sw - 1))
        if a.seconds:
            audio = audio[: int(a.seconds * afs)]
    else:
        afs = 48_000
        t = np.arange(int((a.seconds or 2.0) * afs)) / afs
        audio = np.sin(2 * np.pi * a.audio_tone * t)
    audio = audio / (np.max(np.abs(audio)) or 1)
    return mod.resample_audio(audio, afs, fs_out)


def text_image(text: str, height: int = 24):
    """Render text to a 0..1 array with Pillow (bundled default font)."""
    from PIL import Image, ImageDraw, ImageFont
    try:
        font = ImageFont.load_default(size=height)
    except TypeError:
        font = ImageFont.load_default()
    l, t, r, b = ImageDraw.Draw(Image.new("L", (1, 1))).textbbox((0, 0), text, font=font)
    img = Image.new("L", (r - l + 8, b - t + 8), 0)
    ImageDraw.Draw(img).text((4 - l, 4 - t), text, fill=255, font=font)
    return np.asarray(img, np.float64) / 255.0


def build(a) -> np.ndarray:
    fs = a.fs
    k = a.kind
    if k == "tone":
        x = mod.tone(0, a.seconds or 2.0, fs)
    elif k == "morse":
        x = mod.morse(a.text or "CQ CQ TEST", fs, wpm=a.wpm)
    elif k == "ook":
        b = payload_bits(a)
        if a.manchester:
            # preamble stays plain 1010... (it already has a transition every bit); Manchester the rest
            n_pre = 0 if a.raw else 8 * a.pre_len
            pre, body = b[:n_pre], b[n_pre:]
            b = np.concatenate([pre, bits.manchester_encode(body)])
        # --rate is the DATA bit rate; Manchester puts 2 chips per bit on air
        x = mod.ook(np.concatenate([b, [0]]), fs, a.rate * (2 if a.manchester else 1))
    elif k == "fsk":
        b = payload_bits(a)
        if a.levels == 4:
            b = np.concatenate([b, np.zeros(len(b) % 2, np.uint8)])
            syms = mod.bits_to_symbols(b, 2)
            gray_to_level = np.array([0, 1, 3, 2])            # Gray-coded: neighbours differ by one bit
            x = mod.fsk(gray_to_level[syms], fs, a.rate, a.dev, m=4, bt=a.bt)
        else:
            x = mod.fsk(b, fs, a.rate, a.dev, bt=a.bt)
        x = mod.ramp_edges(x, int(fs / a.rate))
    elif k == "psk":
        b = payload_bits(a)
        x = mod.ramp_edges(mod.linear_mod(b, a.scheme, fs, a.rate, beta=a.beta), int(fs / a.rate))
    elif k == "am":
        x = mod.am(load_audio(a, fs), depth=a.depth)
    elif k == "fm":
        x = mod.fm(load_audio(a, fs), a.dev, fs)
    elif k == "chirp":
        x = mod.chirp(a.f0, a.f1, a.seconds or 0.01, fs)
    elif k == "css":
        vals = [int(v) for v in a.values.split(",")] if a.values else [0, 32, 64, 96]
        x = mod.css_frame(vals, a.sf, a.bw, fs)
    elif k == "text":
        img = text_image(a.text or "RF AGENT", a.height)
        # Image rows -> time, columns -> frequency. SDR++ draws the newest line at the TOP of a scrolling
        # waterfall, so send the bottom row first (img[::-1]) and the text ends up upright on screen.
        x = mod.image_to_iq(img[::-1], fs, a.bw, a.line_s)
    elif k == "noise":
        rng = np.random.default_rng(0)
        n = int((a.seconds or 1.0) * fs)
        w = (rng.standard_normal(n) + 1j * rng.standard_normal(n)).astype(np.complex64)
        x = dsp.lowpass(w, a.bw / 2, fs)
    else:
        raise SystemExit(f"unknown kind {k}")
    x = mod.normalize(x)
    if a.offset:
        x = mod.shift(x, a.offset, fs)
    if a.repeat > 1:
        x = mod.repeat_burst(x, a.repeat, a.gap, fs)
    if a.pad:
        x = mod.pad(x, fs, a.pad)
    if a.snr is not None:
        x = mod.awgn(x, a.snr)
    return x


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["tone", "morse", "ook", "fsk", "psk", "am", "fm", "chirp", "css", "text",
                                     "noise"])
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--fs", type=f_num, default=2e6, help="sample rate (HackRF: 2e6-20e6)")
    ap.add_argument("--offset", type=f_num, default=100e3, help="Hz from the tuned centre (keeps off the DC spike)")
    ap.add_argument("--seconds", type=float)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--gap", type=float, default=0.2)
    ap.add_argument("--pad", type=float, default=0.25)
    ap.add_argument("--snr", type=float, help="add AWGN at this SNR (dB, full bandwidth)")
    ap.add_argument("--peak", type=float, default=0.8, help="fraction of full scale (headroom vs clipping)")
    ap.add_argument("--plot", action="store_true")
    ap.add_argument("--center", type=f_num, default=433.92e6, help="only used for the printed TX command / plot")
    # payload
    ap.add_argument("--text")
    ap.add_argument("--hex")
    ap.add_argument("--raw", action="store_true", help="send payload bits only (no preamble/sync/len/CRC)")
    ap.add_argument("--whiten", action="store_true", help="PN9-whiten the frame body")
    ap.add_argument("--preamble", type=int, help="preamble length in 0xAA bytes (default 2; 8 for psk)")
    ap.add_argument("--manchester", action="store_true")
    # modulation parameters
    ap.add_argument("--rate", type=f_num, default=1000, help="bit/symbol rate")
    ap.add_argument("--wpm", type=float, default=15)
    ap.add_argument("--dev", type=f_num, default=20e3, help="FSK/FM deviation, Hz")
    ap.add_argument("--bt", type=float, help="Gaussian BT for GFSK (e.g. 0.5)")
    ap.add_argument("--levels", type=int, default=2, choices=[2, 4])
    ap.add_argument("--scheme", default="bpsk", choices=["bpsk", "qpsk", "8psk", "16qam", "64qam"])
    ap.add_argument("--beta", type=float, default=0.35)
    ap.add_argument("--audio", help="WAV file for am/fm")
    ap.add_argument("--audio-tone", type=float, default=1000)
    ap.add_argument("--depth", type=float, default=0.8)
    ap.add_argument("--f0", type=f_num, default=-100e3)
    ap.add_argument("--f1", type=f_num, default=100e3)
    ap.add_argument("--sf", type=int, default=7)
    ap.add_argument("--bw", type=f_num, default=125e3)
    ap.add_argument("--values")
    ap.add_argument("--height", type=int, default=24, help="text: font size in pixels (= image rows = time)")
    ap.add_argument("--line-s", type=float, default=0.06, help="text: seconds per image row (>= 2 waterfall lines)")
    a = ap.parse_args()
    if a.kind in ("ook", "fsk", "psk") and not (a.text or a.hex):
        a.text = "HELLO RF"

    x = build(a)
    out = Path(a.out)
    iq.save(out, x, fs=a.fs, peak=a.peak, center_hz=a.center)
    meta = {"file": str(out), "kind": a.kind, "fs": a.fs, "samples": len(x), "seconds": round(len(x) / a.fs, 3),
            "offset_hz": a.offset, "papr_db": round(dsp.papr_db(x[np.abs(x) > 0]), 1) if np.any(x) else None,
            "occupied_bw_99_hz": round(dsp.occupied_bandwidth(x, a.fs)[0])}
    print(json.dumps(meta, indent=2))
    if out.suffix == ".cs8":
        print(f"\nTX (bounded, low power):\n  gtimeout {int(len(x) / a.fs) + 5} hackrf_transfer -t {out} "
              f"-f {int(a.center)} -s {int(a.fs)} -x 20 -a 0")
    if a.plot:
        from rfkit import plot
        png = out.with_suffix(".png")
        plot.overview(x, a.fs, png, center_hz=a.center, title=out.name)
        print("plot:", png)


if __name__ == "__main__":
    main()
