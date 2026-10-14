"""Modulators: build complex baseband IQ with NumPy.

Every function returns ``complex64`` samples at sample rate ``fs`` centred on 0 Hz unless it takes an
``offset_hz``. Move a signal anywhere in the band with ``shift()``. Compose a transmission with ``concat()``,
``pad()`` and ``repeat_burst()``, then write it with ``rfkit.iq.save("x.cs8", ...)``.

The recipe is always the same:

    bits / message -> symbols -> np.repeat (or pulse-shape) -> modulate -> shift -> save

Design rules followed throughout (they keep the spectrum clean on real hardware):
  * Never jump amplitude instantly: OOK/ASK/Morse edges are raised-cosine shaped.
  * Never jump phase: FSK is continuous-phase (frequency is integrated with cumsum); PSK/QAM use RRC pulses.
"""
from __future__ import annotations

import numpy as np

from . import bits as _bits
from .dsp import fftconvolve_same

TWO_PI = 2 * np.pi


# ----------------------------------------------------------------------------- helpers

def t_axis(n: int, fs: float) -> np.ndarray:
    return np.arange(n) / fs


def shift(x: np.ndarray, offset_hz: float, fs: float, phase0: float = 0.0) -> np.ndarray:
    """Frequency-shift by multiplying with exp(j*2*pi*f*t)."""
    n = np.arange(len(x))
    return (x * np.exp(1j * (TWO_PI * offset_hz * n / fs + phase0))).astype(np.complex64)


def pad(x: np.ndarray, fs: float, before_s: float = 0.25, after_s: float | None = None) -> np.ndarray:
    after_s = before_s if after_s is None else after_s
    z0 = np.zeros(int(before_s * fs), np.complex64)
    z1 = np.zeros(int(after_s * fs), np.complex64)
    return np.concatenate([z0, np.asarray(x, np.complex64), z1])


def silence(seconds: float, fs: float) -> np.ndarray:
    return np.zeros(int(seconds * fs), np.complex64)


def concat(*parts) -> np.ndarray:
    return np.concatenate([np.asarray(p, np.complex64) for p in parts])


def repeat_burst(burst: np.ndarray, count: int, gap_s: float, fs: float) -> np.ndarray:
    gap = silence(gap_s, fs)
    out = []
    for i in range(count):
        if i:
            out.append(gap)
        out.append(burst)
    return concat(*out)


def ramp_edges(x: np.ndarray, ramp_samples: int) -> np.ndarray:
    """Hann-taper the first/last ramp_samples of a burst (for constant-envelope modes)."""
    x = np.array(x, np.complex64)
    r = int(min(ramp_samples, len(x) // 2))
    if r > 0:
        w = np.hanning(2 * r).astype(np.float32)
        x[:r] *= w[:r]
        x[-r:] *= w[r:]
    return x


def smooth_envelope(env: np.ndarray, ramp_samples: int) -> np.ndarray:
    """Convolve an on/off envelope with a normalised Hann window -> raised-cosine edges, no key clicks."""
    if ramp_samples < 3:                      # np.hanning(1 or 2) is all zeros
        return np.asarray(env, np.float32)
    w = np.hanning(ramp_samples)
    return fftconvolve_same(np.asarray(env, np.float64), w / w.sum()).astype(np.float32)


def normalize(x: np.ndarray, peak: float = 1.0) -> np.ndarray:
    m = np.max(np.abs(x)) or 1.0
    return (x * (peak / m)).astype(np.complex64)


def sps_of(fs: float, rate: float) -> int:
    """Samples per symbol. Warns (raises) if it is not an integer — non-integer SPS silently changes the rate."""
    sps = fs / rate
    if abs(sps - round(sps)) > 1e-6:
        raise ValueError(f"fs/rate = {sps:.4f} is not an integer; choose fs as a multiple of the symbol rate")
    return int(round(sps))


# ----------------------------------------------------------------------------- pulse shapes

def rrc_taps(sps: int, beta: float = 0.35, span: int = 10) -> np.ndarray:
    """Root-raised-cosine filter, ``span`` symbols long, unit energy."""
    n = np.arange(-span * sps // 2, span * sps // 2 + 1) / sps
    taps = np.empty_like(n, dtype=np.float64)
    for i, t in enumerate(n):
        if abs(t) < 1e-12:
            taps[i] = 1 + beta * (4 / np.pi - 1)
        elif beta and abs(abs(4 * beta * t) - 1) < 1e-9:
            taps[i] = (beta / np.sqrt(2)) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * beta))
                                             + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            taps[i] = (np.sin(np.pi * t * (1 - beta)) + 4 * beta * t * np.cos(np.pi * t * (1 + beta))) / \
                      (np.pi * t * (1 - (4 * beta * t) ** 2))
    return (taps / np.sqrt(np.sum(taps ** 2))).astype(np.float32)


def gaussian_taps(sps: int, bt: float = 0.5, span: int = 4) -> np.ndarray:
    """Gaussian filter for GFSK/GMSK (BT=0.5 Bluetooth LE, 0.3 GSM). Sums to 1 (keeps deviation exact)."""
    t = np.arange(-span * sps // 2, span * sps // 2 + 1) / sps
    sigma = np.sqrt(np.log(2)) / (TWO_PI * bt)
    h = np.exp(-t ** 2 / (2 * sigma ** 2))
    return (h / h.sum()).astype(np.float32)


def upsample(symbols: np.ndarray, sps: int) -> np.ndarray:
    """Insert sps-1 zeros between symbols (impulse train for pulse shaping)."""
    out = np.zeros(len(symbols) * sps, dtype=np.complex64)
    out[::sps] = symbols
    return out


# ----------------------------------------------------------------------------- analog / continuous

def tone(freq_hz: float, seconds: float, fs: float, amplitude: float = 1.0) -> np.ndarray:
    """A pure carrier: exp(j*2*pi*f*t). Positive f lands above the tuned centre, negative below."""
    return (amplitude * np.exp(1j * TWO_PI * freq_hz * t_axis(int(seconds * fs), fs))).astype(np.complex64)


def multitone(freqs_hz, seconds: float, fs: float) -> np.ndarray:
    n = int(seconds * fs)
    t = t_axis(n, fs)
    x = sum(np.exp(1j * (TWO_PI * f * t + np.random.uniform(0, TWO_PI))) for f in freqs_hz)
    return normalize(x)


def am(audio: np.ndarray, depth: float = 0.8) -> np.ndarray:
    """Double-sideband full-carrier AM. ``audio`` in [-1, 1], already at the IQ sample rate."""
    a = np.asarray(audio, np.float32)
    return ((1 + depth * a) / (1 + depth)).astype(np.complex64)


def dsb_sc(audio: np.ndarray) -> np.ndarray:
    return np.asarray(audio, np.float32).astype(np.complex64)


def ssb(audio: np.ndarray, upper: bool = True) -> np.ndarray:
    """Single sideband via the analytic signal (Hilbert transform in the frequency domain)."""
    a = np.asarray(audio, np.float64)
    n = len(a)
    A = np.fft.fft(a)
    h = np.zeros(n)
    h[0] = 1
    if n % 2 == 0:
        h[n // 2] = 1
        h[1:n // 2] = 2
    else:
        h[1:(n + 1) // 2] = 2
    analytic = np.fft.ifft(A * h)
    return (analytic if upper else np.conj(analytic)).astype(np.complex64)


def fm(audio: np.ndarray, deviation_hz: float, fs: float) -> np.ndarray:
    """Frequency modulation: instantaneous frequency = deviation * audio. Phase = cumulative sum.
    Broadcast WFM uses 75 kHz deviation, NFM voice 2.5-5 kHz."""
    a = np.asarray(audio, np.float64)
    phase = TWO_PI * deviation_hz * np.cumsum(a) / fs
    return np.exp(1j * phase).astype(np.complex64)


def pm(audio: np.ndarray, index_rad: float = 1.0) -> np.ndarray:
    return np.exp(1j * index_rad * np.asarray(audio, np.float64)).astype(np.complex64)


def resample_audio(audio: np.ndarray, fs_in: float, fs_out: float) -> np.ndarray:
    """Linear-interpolation resampler (good enough for audio feeding an FM/AM modulator)."""
    n_out = int(len(audio) * fs_out / fs_in)
    return np.interp(np.arange(n_out) * fs_in / fs_out, np.arange(len(audio)), audio).astype(np.float32)


def chirp(f0: float, f1: float, seconds: float, fs: float) -> np.ndarray:
    """Linear frequency sweep f0 -> f1 (a radar / LoRa-like chirp)."""
    n = int(seconds * fs)
    t = t_axis(n, fs)
    k = (f1 - f0) / seconds
    return np.exp(1j * TWO_PI * (f0 * t + 0.5 * k * t ** 2)).astype(np.complex64)


# ----------------------------------------------------------------------------- on/off and amplitude keying

def morse(text: str, fs: float, wpm: float = 15, ramp_s: float = 0.005) -> np.ndarray:
    """CW Morse: PARIS timing, dot = 1.2/wpm seconds, with raised-cosine edges."""
    units = _bits.morse_units(text).astype(np.float32)
    spu = int(1.2 / wpm * fs)
    env = smooth_envelope(np.repeat(units, spu), int(ramp_s * fs))
    return env.astype(np.complex64)


def ook(b, fs: float, bit_rate: float, ramp_s: float | None = None) -> np.ndarray:
    """On-off keying: 1 = carrier on, 0 = off. ramp_s defaults to 10 % of a bit."""
    sps = sps_of(fs, bit_rate)
    env = np.repeat(np.asarray(b, np.float32), sps)
    ramp = int((ramp_s if ramp_s is not None else 0.1 / bit_rate) * fs)
    return smooth_envelope(env, ramp).astype(np.complex64)


def ask(symbols, fs: float, symbol_rate: float, levels=(0.25, 1.0), ramp_s: float | None = None) -> np.ndarray:
    """M-level amplitude-shift keying. ``symbols`` are integers indexing ``levels``."""
    sps = sps_of(fs, symbol_rate)
    lv = np.asarray(levels, np.float32)[np.asarray(symbols, int)]
    env = np.repeat(lv, sps)
    ramp = int((ramp_s if ramp_s is not None else 0.1 / symbol_rate) * fs)
    return smooth_envelope(env, ramp).astype(np.complex64)


def pwm_ook(b, fs: float, short_s: float, long_s: float, gap_s: float | None = None) -> np.ndarray:
    """Pulse-width OOK used by cheap 433 MHz remotes (EV1527/PT2262 style): 1 = long on + short off,
    0 = short on + long off."""
    gap_s = gap_s or short_s
    seg = []
    for v in np.asarray(b):
        on, off = (long_s, short_s) if v else (short_s, long_s)
        seg += [np.ones(int(on * fs)), np.zeros(int(off * fs))]
    env = np.concatenate(seg).astype(np.float32)
    return smooth_envelope(env, int(min(short_s, gap_s) * 0.1 * fs)).astype(np.complex64)


# ----------------------------------------------------------------------------- frequency keying

def fsk(symbols, fs: float, symbol_rate: float, deviation_hz: float, m: int = 2,
        bt: float | None = None, offset_hz: float = 0.0) -> np.ndarray:
    """Continuous-phase M-FSK (and GFSK when ``bt`` is given).

    2-FSK: bit 1 -> +deviation, bit 0 -> -deviation.
    4-FSK: symbols 0..3 -> -3d, -d, +d, +3d (deviation = d, inner tones), Gray-code the input if you need it.
    ``bt``: Gaussian filter bandwidth-time product (0.5 = BLE, 0.3 = GSM). None = plain rectangular FSK.
    Modulation index h = 2*deviation/symbol_rate (h=0.5 with rectangular pulses is MSK).
    """
    sps = sps_of(fs, symbol_rate)
    s = np.asarray(symbols, np.float64)
    levels = 2 * s - (m - 1)                 # 0..m-1 -> -(m-1)..(m-1) in steps of 2
    freq = np.repeat(levels, sps) * deviation_hz
    if bt is not None:
        freq = np.convolve(freq, gaussian_taps(sps, bt), mode="same")
    phase = TWO_PI * np.cumsum(freq + offset_hz) / fs
    return np.exp(1j * phase).astype(np.complex64)


def msk(b, fs: float, bit_rate: float) -> np.ndarray:
    return fsk(b, fs, bit_rate, deviation_hz=bit_rate / 4)


def gmsk(b, fs: float, bit_rate: float, bt: float = 0.3) -> np.ndarray:
    return fsk(b, fs, bit_rate, deviation_hz=bit_rate / 4, bt=bt)


# ----------------------------------------------------------------------------- phase / quadrature-amplitude keying

def constellation(name: str) -> np.ndarray:
    """Gray-mapped unit-average-power constellations: bpsk, qpsk, 8psk, 16qam, 64qam."""
    name = name.lower()
    if name == "bpsk":
        return np.array([1, -1], np.complex64)
    if name == "qpsk":  # Gray: 00 01 11 10 around the circle
        return (np.array([1 + 1j, -1 + 1j, 1 - 1j, -1 - 1j]) / np.sqrt(2)).astype(np.complex64)
    if name == "8psk":
        gray = [0, 1, 3, 2, 6, 7, 5, 4]
        pts = np.zeros(8, np.complex64)
        for k, g in enumerate(gray):
            pts[g] = np.exp(1j * TWO_PI * k / 8)
        return pts
    if name in ("16qam", "64qam"):
        m = 4 if name == "16qam" else 8
        axis = np.arange(-(m - 1), m, 2, dtype=np.float64)
        g = [i ^ (i >> 1) for i in range(m)]     # Gray code per axis
        pts = np.zeros(m * m, np.complex64)
        nb = int(np.log2(m))
        for i in range(m):
            for q in range(m):
                pts[(g[i] << nb) | g[q]] = axis[i] + 1j * axis[q]
        return (pts / np.sqrt(np.mean(np.abs(pts) ** 2))).astype(np.complex64)
    raise ValueError(name)


def bits_to_symbols(b, bits_per_symbol: int) -> np.ndarray:
    b = np.asarray(b, np.uint8)
    b = b[: len(b) // bits_per_symbol * bits_per_symbol].reshape(-1, bits_per_symbol)
    return (b * (1 << np.arange(bits_per_symbol - 1, -1, -1))).sum(1)


def linear_mod(b, scheme: str, fs: float, symbol_rate: float, beta: float = 0.35, span: int = 10,
               differential: bool = False) -> np.ndarray:
    """PSK/QAM with root-raised-cosine pulses (the receiver applies the matched RRC).

    scheme: bpsk | qpsk | 8psk | 16qam | 64qam. ``differential=True`` (BPSK only) differentially encodes first.
    Occupied bandwidth ~= symbol_rate * (1 + beta).
    """
    pts = constellation(scheme)
    k = int(np.log2(len(pts)))
    b = np.asarray(b, np.uint8)
    if differential:
        if scheme != "bpsk":
            raise ValueError("differential only implemented for bpsk")
        b = _bits.differential_encode(b)
    syms = pts[bits_to_symbols(b, k)]
    sps = sps_of(fs, symbol_rate)
    x = np.convolve(upsample(syms, sps), rrc_taps(sps, beta, span) * np.sqrt(sps), mode="full")
    return x.astype(np.complex64)


# ----------------------------------------------------------------------------- spread spectrum

def css_symbol(value: int, sf: int, bw: float, fs: float, down: bool = False) -> np.ndarray:
    """One LoRa-style chirp-spread-spectrum symbol: an up-chirp across ``bw`` cyclically shifted by ``value``.
    This is the physical waveform only (no LoRa whitening/Hamming/interleaving), useful for test signals."""
    n_chips = 2 ** sf
    osr = fs / bw
    if abs(osr - round(osr)) > 1e-9:
        raise ValueError("fs must be an integer multiple of bw")
    osr = int(round(osr))
    n = n_chips * osr
    k = np.arange(n) / osr                       # chip time
    f = ((k + value) % n_chips) / n_chips * bw - bw / 2   # instantaneous frequency, wraps at the band edge
    if down:
        f = -f
    phase = TWO_PI * np.cumsum(f) / fs
    return np.exp(1j * phase).astype(np.complex64)


def css_frame(values, sf: int, bw: float, fs: float, preamble: int = 8) -> np.ndarray:
    """preamble up-chirps + 2.25 down-chirps (sync) + data symbols (LoRa-shaped, not LoRa-decodable)."""
    up = css_symbol(0, sf, bw, fs)
    dn = css_symbol(0, sf, bw, fs, down=True)
    parts = [up] * preamble + [dn, dn, dn[: len(dn) // 4]]
    parts += [css_symbol(int(v), sf, bw, fs) for v in values]
    return concat(*parts)


def dsss(b, chips: np.ndarray, fs: float, chip_rate: float) -> np.ndarray:
    """Direct-sequence spread BPSK: each bit multiplies the whole chip sequence (e.g. an 11-chip Barker)."""
    c = 2 * np.asarray(chips, np.float32) - 1
    seq = np.concatenate([c * (1 if v else -1) for v in np.asarray(b)])
    return np.repeat(seq, sps_of(fs, chip_rate)).astype(np.complex64)


BARKER_11 = np.array([1, 0, 1, 1, 0, 1, 1, 1, 0, 0, 0], np.uint8)
BARKER_13 = np.array([1, 1, 1, 1, 1, 0, 0, 1, 1, 0, 1, 0, 1], np.uint8)


# ----------------------------------------------------------------------------- multicarrier

def ofdm(b, n_fft: int = 64, cp: int = 16, n_used: int = 48, scheme: str = "qpsk") -> np.ndarray:
    """Toy OFDM: map bits to ``n_used`` subcarriers around DC (DC left empty), IFFT, add a cyclic prefix.
    Sample rate = subcarrier spacing * n_fft."""
    pts = constellation(scheme)
    k = int(np.log2(len(pts)))
    syms = pts[bits_to_symbols(b, k)]
    n_sym = int(np.ceil(len(syms) / n_used))
    syms = np.concatenate([syms, np.zeros(n_sym * n_used - len(syms), np.complex64)])
    half = n_used // 2
    bins = np.r_[np.arange(1, half + 1), np.arange(n_fft - half, n_fft)]
    out = []
    for s in syms.reshape(n_sym, n_used):
        X = np.zeros(n_fft, np.complex64)
        X[bins] = s
        x = np.fft.ifft(X) * np.sqrt(n_fft)
        out.append(np.concatenate([x[-cp:], x]))
    return np.concatenate(out).astype(np.complex64)


# ----------------------------------------------------------------------------- images in the waterfall

def image_to_iq(img, fs: float, bandwidth_hz: float, line_s: float, invert: bool = False,
                gamma: float = 1.0) -> np.ndarray:
    """Paint a 2-D array (rows = time, top row first; cols = frequency, left = low) into the waterfall.

    Each image row becomes ``line_s`` seconds of a multitone signal whose tone amplitudes are the pixel values.
    A receiver's waterfall then shows the picture. ``img`` is a float array in [0, 1].
    Note: SDR++'s waterfall scrolls downward, so the first row you send appears at the bottom once the image
    has scrolled into view — flip the rows (img[::-1]) if you want it upright in a scrolling waterfall.
    """
    a = np.asarray(img, np.float64)
    if invert:
        a = 1 - a
    a = np.clip(a, 0, 1) ** gamma
    rows, cols = a.shape
    freqs = np.linspace(-bandwidth_hz / 2, bandwidth_hz / 2, cols)
    n = int(line_s * fs)
    t = t_axis(n, fs)
    rng = np.random.default_rng(0)
    phases = rng.uniform(0, TWO_PI, cols)          # random phases keep the peak-to-average ratio sane
    basis = np.exp(1j * (TWO_PI * np.outer(freqs, t) + phases[:, None]))   # cols x n
    out = np.empty(rows * n, np.complex64)
    for r in range(rows):
        out[r * n:(r + 1) * n] = a[r] @ basis
    return normalize(out)


# ----------------------------------------------------------------------------- noise & impairments

def awgn(x: np.ndarray, snr_db: float, rng=None, signal_power: float | None = None) -> np.ndarray:
    """Add complex white Gaussian noise for a given SNR (per sample, over the full sample-rate bandwidth).
    ``signal_power`` defaults to the mean power of the non-silent part of x."""
    rng = rng or np.random.default_rng()
    p = np.abs(x) ** 2
    if signal_power is None:
        active = p[p > 1e-3 * p.max()] if p.max() > 0 else p
        signal_power = float(np.mean(active)) if len(active) else 1.0
    n0 = signal_power / (10 ** (snr_db / 10))
    noise = (rng.standard_normal(len(x)) + 1j * rng.standard_normal(len(x))) * np.sqrt(n0 / 2)
    return (x + noise).astype(np.complex64)


def impair(x: np.ndarray, fs: float, cfo_hz: float = 0.0, phase_rad: float = 0.0, delay_samples: int = 0,
           iq_gain_db: float = 0.0, iq_phase_deg: float = 0.0, dc: complex = 0, sro_ppm: float = 0.0) -> np.ndarray:
    """Channel / front-end impairments for testing a receiver: carrier offset, phase, delay, IQ imbalance,
    DC offset and sample-rate offset."""
    y = np.asarray(x, np.complex64)
    if sro_ppm:
        n = np.arange(int(len(y) / (1 + sro_ppm * 1e-6)))
        src = n * (1 + sro_ppm * 1e-6)
        y = (np.interp(src, np.arange(len(y)), y.real) + 1j * np.interp(src, np.arange(len(y)), y.imag))
    if delay_samples:
        y = np.concatenate([np.zeros(delay_samples, np.complex64), y])
    if cfo_hz or phase_rad:
        y = shift(y, cfo_hz, fs, phase_rad)
    if iq_gain_db or iq_phase_deg:
        g = 10 ** (iq_gain_db / 20)
        ph = np.deg2rad(iq_phase_deg)
        i, q = y.real, y.imag
        y = i + 1j * g * (q * np.cos(ph) + i * np.sin(ph))
    return (y + dc).astype(np.complex64)
