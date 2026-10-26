#!/usr/bin/env python3
"""Decode a recording made of a signal from signal_generation/generate.py (or anything with the same framing).

    rx_decode.py morse cap.wav
    rx_decode.py ook   cap.wav [--manchester] [--rate 1000]          # rate is estimated if omitted
    rx_decode.py fsk   cap.wav [--rate 5000]
    rx_decode.py psk   cap.wav --rate 50e3 [--order 4] [--search-rate]   # --search-rate: rate is only approximate
    rx_decode.py uart  cap.wav [--via ook|fsk] [--rate 1000]               # unknown framing: brute-force text search
    rx_decode.py ofdm  cap.wav [--order 4]                                 # finds FFT size / prefix, blind equalise
    rx_decode.py chirp cap.wav --bw 125e3 --sf 7                           # LoRa-style chirp symbols
    rx_decode.py dsss  cap.wav [--chip-rate 12e3 --code-len 127]           # no rate given: lists candidate rates
    rx_decode.py fm    cap.wav --out audio.wav [--nfm]                 # broadcast / NFM audio to a WAV
    rx_decode.py ook   cap.cu8 --fs 1.024e6                            # raw files need --fs

Packet framing (default): preamble AA AA | sync 2D D4 | len | payload | CRC-16/CCITT-FALSE.
Signal is found automatically (strongest signal away from DC) unless --offset is given.
Prints JSON: carrier offset, estimated rate, every packet with CRC status. --plot writes diagnostic PNGs.
"""
from __future__ import annotations

import argparse
import json
import sys
import wave
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rfkit import bits, dsp, iq  # noqa: E402


def f_num(s: str) -> float:
    s = s.strip().lower().replace("_", "")
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(s[-1], 1)
    return float(s[:-1] if s[-1] in "kmg" else s) * mult


def locate(x, fs, a, kind):
    """Coarse signal offset: the strongest peak away from DC (time-gated so short bursts count fully).
    For FSK/FM that peak is one tone or Bessel line; refine_center() then finds the true centre."""
    if a.offset is not None:
        return a.offset
    g = dsp.gate(x, fs, min_len_s=a.min_burst)
    cs = dsp.find_carriers(g if len(g) > 4096 else x, fs, exclude_dc_hz=a.dc_guard, max_peaks=3)
    if not cs:
        raise SystemExit("no signal found above the noise floor")
    return cs[0]["freq_hz"]


def refine_center(x, fs, coarse, span):
    """Centre of an FM/FSK signal from the discriminator: midpoint of the 10th/90th percentile instantaneous
    frequency during bursts. Robust to unequal 1/0 counts and to sinc sidelobes (unlike spectral centroids).
    Returns (centre_offset_hz, peak_to_peak_hz)."""
    wide, fsw = dsp.channelize(x, fs, coarse, min(0.8 * fs, span))
    g = dsp.gate(wide, fsw)
    inst = dsp.lowpass(dsp.fm_discriminator(g, fsw), span / 8, fsw)
    lo, hi = np.percentile(inst, [10, 90])
    return coarse + (lo + hi) / 2, hi - lo


def packets_from_bits(stream, a):
    out = []
    pos = 0
    while True:
        r = bits.parse_frame(stream[pos:], whitening=a.whiten)
        if not r:
            break
        out.append({"payload": r["payload"].decode("latin-1"), "hex": r["payload"].hex(), "crc_ok": r["crc_ok"],
                    "inverted": r["inverted"]})
        pos += r["start"] + 16 + 8 * (len(r["payload"]) + 3)
    return out


def decode_bursts(y, fs2, a, metric_fn, rate_mult=1, widen=False):
    """Per burst: metric -> rate -> bits -> frames. Returns (bit_rate, packets, n_bursts).

    metric_fn(segment, rate_or_None) -> real waveform. It is called twice: first without a rate (wide
    post-detection filter) to estimate the symbol rate, then with that rate to filter tightly before slicing.
    rate_mult = symbols per data bit on air (2 for Manchester)."""
    # merge gaps shorter than ~24 symbols so runs of 0-bits inside an OOK packet do not split it
    gap = a.merge_gap if a.merge_gap else (24 / (a.rate * rate_mult) if a.rate else 0.03)
    segs = dsp.bursts(y, fs2, min_len_s=a.min_burst, merge_gap_s=gap)
    result, rates = [], []
    for s, e in segs:
        # OOK only: widen each burst a little. A packet ending in 0-bits (or a Manchester 1->0 half) has no
        # energy at its tail, so the burst detector cuts it short. (For FSK the edges are noise: don't.)
        pad = 0 if not widen else (int(0.004 * fs2) if not a.rate else int(3 * fs2 / (a.rate * rate_mult)))
        seg = y[max(0, s - pad):e + pad]
        try:
            rate = a.rate * rate_mult if a.rate else dsp.estimate_symbol_rate(metric_fn(seg, None), fs2)
        except ValueError:
            continue
        rates.append(rate)
        b = dsp.slice_symbols_pll(metric_fn(seg, rate), fs2 / rate)
        if a.manchester:
            sw = bits.manchester_encode(bits.from_bytes(bits.DEFAULT_SYNC))
            hits = bits.find(b, sw, 1)
            if not hits:
                continue
            dec, _ = bits.manchester_decode(b[hits[0]:])
            b = np.concatenate([bits.from_bytes(bits.DEFAULT_PREAMBLE), dec])
        for p in packets_from_bits(b, a):
            p["t_s"] = round(s / fs2, 4)
            result.append(p)
    rate = float(np.median(rates)) / rate_mult if rates else None
    return rate, result, len(segs)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("kind", choices=["morse", "ook", "fsk", "psk", "fm", "uart", "ofdm", "chirp", "dsss"])
    ap.add_argument("file")
    ap.add_argument("--fs", type=f_num, help="sample rate for raw files (.cu8/.cs8/...)")
    ap.add_argument("--offset", type=f_num, help="signal offset from the tuned centre, Hz (default: auto)")
    ap.add_argument("--bw", type=f_num, help="channel filter width (default: depends on kind/rate)")
    ap.add_argument("--rate", type=f_num, help="bit/symbol rate (default: estimate)")
    ap.add_argument("--manchester", action="store_true")
    ap.add_argument("--whiten", action="store_true")
    ap.add_argument("--order", type=int, default=2, help="psk: 2=BPSK, 4=QPSK")
    ap.add_argument("--dc-guard", type=f_num, default=5e3, help="ignore +/- this around 0 Hz when searching")
    ap.add_argument("--min-burst", type=float, default=5e-4)
    ap.add_argument("--merge-gap", type=float, help="join bursts separated by less than this (s)")
    ap.add_argument("--skip", type=float, default=0.05, help="seconds to drop at the start (RX settling)")
    ap.add_argument("--keep-dc", action="store_true", help="don't subtract the mean (DC offset) before decoding")
    ap.add_argument("--search-rate", action="store_true", help="psk: refine --rate by searching +/-8 percent")
    ap.add_argument("--via", choices=["ook", "fsk"], default="ook", help="uart: keying of the serial data")
    ap.add_argument("--sf", type=int, help="chirp: spreading factor (bits per symbol)")
    ap.add_argument("--chip-rate", type=f_num, help="dsss: chip rate (default: list candidates and stop)")
    ap.add_argument("--code-len", type=int, help="dsss: chips per bit")
    ap.add_argument("--out", help="fm: output audio WAV")
    ap.add_argument("--nfm", action="store_true", help="fm: narrow FM (5 kHz deviation, no de-emphasis)")
    ap.add_argument("--plot", help="write diagnostic PNGs with this path prefix")
    a = ap.parse_args()

    x, fs = iq.load(a.file, fs=a.fs)
    if fs is None:
        raise SystemExit("raw file: pass --fs")
    x = x[int(a.skip * fs):]
    if not a.keep_dc:
        x = dsp.dc_block(x)      # a receiver's DC offset can rival a weak signal (HackRF RX) and bias FM/FSK
    off = locate(x, fs, a, a.kind)
    if a.kind in ("ofdm", "chirp", "dsss") and a.offset is None:
        # wide, flat signals: the strongest bin is just noise ripple; use the centre of the occupied band
        g = dsp.gate(x, fs, min_len_s=a.min_burst)
        off = dsp.signal_center(g if len(g) > 8192 else x, fs, above_floor_db=6)
    rep = {"file": a.file, "fs": fs, "offset_hz": round(off, 1)}

    if a.kind == "morse":
        bw = a.bw or 1_000
        y, fs2 = dsp.channelize(x, fs, off, bw)
        env = dsp.moving_average(np.abs(y), int(0.004 * fs2))
        thr = dsp.otsu_threshold(env)
        r = dsp.runs(env > thr)
        if r and r[0][0] == 0:
            r = r[1:]
        dot = np.median(sorted(n for lv, n in r if lv)[: max(1, len([1 for lv, _ in r if lv]) // 3)])
        rep.update(text=bits.morse_from_runs(r), wpm=round(1.2 / (dot / fs2), 1))
        if a.plot:
            from rfkit import plot
            plot.timeseries(env, fs2, a.plot + "_envelope.png", "Morse envelope", "|x|", thr)
    elif a.kind == "ook":
        bw = a.bw or (8 * a.rate if a.rate else 20e3)
        y, fs2 = dsp.channelize(x, fs, off, bw)
        rate, pk, nb = decode_bursts(y, fs2, a, lambda s, r: np.abs(s), rate_mult=2 if a.manchester else 1,
                                     widen=True)
        rep.update(bursts=nb, rate=round(rate, 2) if rate else None, packets=pk)
        if a.plot:
            from rfkit import plot
            plot.timeseries(np.abs(y), fs2, a.plot + "_envelope.png", "OOK envelope", "|x|")
    elif a.kind == "fsk":
        bw = a.bw or 80e3
        if a.offset is None:     # strongest peak is one tone: find the midpoint between the tones
            off, spacing = refine_center(x, fs, off, max(4 * bw, 200e3))
            rep["offset_hz"] = round(off, 1)
            rep["tone_spacing_hz"] = round(spacing, 1)
        y, fs2 = dsp.channelize(x, fs, off, bw)

        def metric(seg, rate):
            inst = dsp.fm_discriminator(seg, fs2)
            return dsp.lowpass(inst, 0.75 * rate if rate else 20e3, fs2)   # post-detection filter
        rate, pk, nb = decode_bursts(y, fs2, a, metric)
        rep.update(bursts=nb, rate=round(rate, 2) if rate else None, packets=pk)
        if a.plot:
            from rfkit import plot
            plot.timeseries(dsp.fm_discriminator(y, fs2), fs2, a.plot + "_freq.png", "FSK discriminator", "Hz")
    elif a.kind == "psk":
        if not a.rate:
            raise SystemExit("psk: pass --rate (symbol rate)")
        bw = a.bw or 1.5 * a.rate
        if a.search_rate:
            seg0 = dsp.channelize(x, fs, off, bw, out_fs=max(4 * a.rate, 8 * bw / 1.5 / 2))
            g = dsp.gate(seg0[0], seg0[1])
            best, _, metric = dsp.refine_symbol_rate(g, seg0[1], a.rate, rel_span=0.08, order=a.order)
            rep["rate_input"], rep["rate_refined"] = a.rate, round(best, 2)
            rep["rate_metric"] = round(float(metric.max()), 3)
            a.rate = best
        sps_target = 8
        y, fs2 = dsp.channelize(x, fs, off, bw, out_fs=a.rate * sps_target)
        packets = []
        syms = np.array([])
        for s, e in dsp.bursts(y, fs2, min_len_s=a.min_burst, merge_gap_s=a.merge_gap or 1e-3):
            seg = y[s:e]
            sps = fs2 / a.rate
            if abs(sps - round(sps)) > 0.01:     # resample to an integer SPS
                n_out = int(len(seg) * round(sps) / sps)
                t = np.arange(n_out) * sps / round(sps)
                seg = np.interp(t, np.arange(len(seg)), seg.real) + 1j * np.interp(t, np.arange(len(seg)), seg.imag)
            syms = dsp.psk_demod(seg, a.rate * round(sps), a.rate, a.order)
            for rot in range(a.order):
                b = dsp.psk_bits(syms * np.exp(2j * np.pi * rot / a.order), a.order)
                pk = packets_from_bits(b, a)
                if any(p["crc_ok"] for p in pk):
                    for p in pk:
                        p.update(t_s=round(s / fs2, 4), rotation_deg=360 * rot / a.order)
                    packets += pk
                    break
            if a.plot and not packets:
                from rfkit import plot
                plot.constellation(syms, a.plot + "_constellation.png")
        rep.update(packets=packets)
        if a.plot and len(syms):
            from rfkit import plot
            plot.constellation(syms, a.plot + "_constellation.png")
    elif a.kind == "uart":
        bw = a.bw or (8 * a.rate if a.rate else (20e3 if a.via == "ook" else 80e3))
        if a.via == "fsk" and a.offset is None:
            off, spacing = refine_center(x, fs, off, max(4 * bw, 200e3))
            rep["offset_hz"] = round(off, 1)
        y, fs2 = dsp.channelize(x, fs, off, bw)
        if a.via == "ook":
            def metric(seg, rate):
                return np.abs(seg)
        else:
            def metric(seg, rate):
                return dsp.lowpass(dsp.fm_discriminator(seg, fs2), 0.75 * rate if rate else 20e3, fs2)
        segs = dsp.bursts(y, fs2, min_len_s=a.min_burst, merge_gap_s=a.merge_gap or (24 / a.rate if a.rate else 0.03))
        found, seen = [], set()
        for s_, e_ in segs:
            seg = y[s_:e_]
            try:
                rate = a.rate or dsp.estimate_symbol_rate(metric(seg, None), fs2)
            except ValueError:
                continue
            stream = dsp.clock_recover_bits(metric(seg, rate), fs2 / rate)
            for h in bits.bruteforce(stream, top=3):
                key = (h["mode"], h["text"])
                if key not in seen:
                    seen.add(key)
                    found.append({**h, "rate": round(float(rate), 2), "t_s": round(s_ / fs2, 4),
                                  "bits": "".join(map(str, stream[:200]))})
        found.sort(key=lambda h: h["score"] * min(1.0, len(h["text"]) / 16), reverse=True)
        rep.update(bursts=len(segs), via=a.via, candidates=found[:8])
    elif a.kind == "ofdm":
        bw = a.bw or dsp.occupied_bandwidth(dsp.gate(x, fs), fs)[0] * 1.2
        y, fs2 = dsp.channelize(x, fs, off, bw, out_fs=bw * 1.25)
        g = dsp.gate(y, fs2)
        d = dsp.ofdm_detect(g, fs2)
        if "n_fft" not in d:
            raise SystemExit("ofdm: no cyclic-prefix structure found (try --bw, or this is not OFDM)")
        Y = dsp.ofdm_demod(g, d["n_fft"], d["cp"], d["start"])
        used = dsp.ofdm_occupied(Y)
        eq = dsp.ofdm_equalize(Y, used, order=a.order if a.order in (2, 4) else 4)
        order = a.order if a.order in (2, 4) else 4
        stream = dsp.psk_bits(eq.ravel(), order)
        rep.update(ofdm=d, symbols=len(Y), used_subcarriers=len(used),
                   note="blind equalisation: each subcarrier has a %d-fold phase ambiguity; use a known training "
                        "symbol (dsp.ofdm_equalize training=...) to resolve it" % order,
                   candidates=bits.bruteforce(stream, top=5))
        if a.plot:
            from rfkit import plot
            plot.constellation(eq[1:].ravel(), a.plot + "_constellation.png")
    elif a.kind == "chirp":
        if not (a.bw and a.sf):
            raise SystemExit("chirp: pass --bw (chirp bandwidth) and --sf (spreading factor)")
        from fractions import Fraction
        from scipy.signal import resample_poly
        y, fs2 = dsp.channelize(x, fs, off, a.bw * 1.1, out_fs=a.bw * 2)
        g = dsp.gate(y, fs2)
        fr = Fraction(2 * a.bw / fs2).limit_denominator(1000)
        g = resample_poly(g, fr.numerator, fr.denominator).astype(np.complex64)
        r = dsp.css_demod(g, 2 * a.bw, a.bw, a.sf)
        stream = np.unpackbits(r["values"].astype(">u2").view(np.uint8).reshape(-1, 2), axis=1)[:, -a.sf:].ravel()
        rep.update(symbols=int(len(r["values"])), start=r["start"], reference_bin=r["reference_bin"],
                   values=[int(v) for v in r["values"][:64]], candidates=bits.bruteforce(stream, top=5))
    elif a.kind == "dsss":
        bw = a.bw or 0
        if not a.chip_rate:
            occ = dsp.occupied_bandwidth(x, fs)[0]
            y, fs2 = dsp.channelize(x, fs, off, a.bw or occ * 1.2)
            rep.update(note="pass --chip-rate (and --code-len); candidates from cyclostationary lines",
                       abs2_lines=dsp.cyclic_lines(y, fs2, "abs2"), square_lines=dsp.cyclic_lines(y, fs2, "sq"))
        else:
            y, fs2 = dsp.channelize(x, fs, off, bw or 1.6 * a.chip_rate, out_fs=a.chip_rate * 4)
            soft = dsp.bpsk_soft_chips(y, fs2, a.chip_rate)
            if not a.code_len:
                rep.update(chips=len(soft), note="pass --code-len (chips per bit); try periods near the "
                           "autocorrelation peaks of the soft chips")
                ac = np.abs(np.fft.ifft(np.abs(np.fft.fft(soft - soft.mean())) ** 2))[: 4096]
                rep["autocorr_peaks_chips"] = [int(i) for i in np.argsort(ac[8:])[::-1][:8] + 8]
            else:
                off_c = dsp.dsss_find_alignment(soft, a.code_len)
                code = dsp.dsss_recover_code(soft, a.code_len, off_c)
                corr = dsp.dsss_despread(soft, code, off_c)
                stream = (corr > 0).astype(np.uint8)
                rep.update(chip_offset=off_c, bits=len(stream), code="".join("1" if c > 0 else "0" for c in code),
                           candidates=bits.bruteforce(stream, top=5))
    elif a.kind == "fm":
        dev = 5e3 if a.nfm else 75e3
        bw = a.bw or (2 * (dev + 5e3) if a.nfm else 200e3)
        if a.offset is None:
            off, _ = refine_center(x, fs, off, 2 * bw)
            rep["offset_hz"] = round(off, 1)
        y, fs2 = dsp.channelize(x, fs, off, bw, out_fs=max(bw * 1.25, 96e3))
        audio, afs = dsp.fm_demod(y, fs2, deviation_hz=dev, deemph_us=None if a.nfm else 75.0)
        audio = audio - np.mean(audio)                 # residual carrier offset shows up as DC
        audio = audio / (np.max(np.abs(audio)) or 1)
        out = a.out or str(Path(a.file).with_suffix("")) + "_audio.wav"
        with wave.open(out, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(afs))
            w.writeframes((audio * 32000).astype("<i2").tobytes())
        f, p = dsp.psd(audio, afs, 4096)
        rep.update(audio=out, audio_fs=afs, seconds=round(len(audio) / afs, 2),
                   dominant_audio_hz=round(abs(float(f[np.argmax(p)])), 1))
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    main()
