"""Receiver-side DSP: spectra, filtering, channel extraction, demodulation, timing and slicing.

NumPy only (SciPy is optional and not required). Functions take complex baseband ``x`` at sample rate ``fs``.

Typical offline flow for a recording::

    x, fs = iq.load("cap.wav")
    f, p = dsp.psd(x, fs)                                  # where is the energy?
    peaks = dsp.find_carriers(x, fs)                       # strongest carriers + bandwidths
    y, fs2 = dsp.channelize(x, fs, peaks[0]["freq_hz"], bw_hz=50e3)   # mix to 0 Hz, filter, decimate
    seg = dsp.bursts(y, fs2)                               # where in time
    env = np.abs(y)  or  inst = dsp.fm_discriminator(y, fs2)
    rate = dsp.estimate_symbol_rate(metric, fs2)
    bits = dsp.slice_symbols(metric, fs2 / rate)
"""
from __future__ import annotations

import numpy as np

TWO_PI = 2 * np.pi


# ----------------------------------------------------------------------------- spectra

def psd(x: np.ndarray, fs: float, nfft: int = 4096, overlap: float = 0.5, window: str = "hann",
        db: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Welch power spectral density, fftshifted. Returns (freq_hz, power[dB]) with freq from -fs/2 to fs/2."""
    x = np.asarray(x, np.complex64)
    nfft = min(nfft, len(x))
    w = _window(window, nfft)
    step = max(1, int(nfft * (1 - overlap)))
    acc = np.zeros(nfft)
    count = 0
    for i in range(0, len(x) - nfft + 1, step):
        seg = x[i:i + nfft] * w
        acc += np.abs(np.fft.fft(seg)) ** 2
        count += 1
    p = np.fft.fftshift(acc / max(count, 1) / np.sum(w ** 2))
    f = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs))
    return f, (10 * np.log10(p + 1e-20) if db else p)


def spectrogram(x: np.ndarray, fs: float, nfft: int = 1024, hop: int | None = None,
                window: str = "hann") -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Short-time FFT. Returns (freq_hz, time_s, S_dB) with S shaped (len(time), len(freq)), fftshifted —
    i.e. rows are time, exactly like a waterfall."""
    hop = hop or nfft // 2
    w = _window(window, nfft)
    n_frames = max(1, 1 + (len(x) - nfft) // hop)
    idx = np.arange(nfft)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = np.asarray(x, np.complex64)[idx] * w
    S = np.fft.fftshift(np.abs(np.fft.fft(frames, axis=1)) ** 2, axes=1) / np.sum(w ** 2)
    f = np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs))
    t = (np.arange(n_frames) * hop + nfft / 2) / fs
    return f, t, 10 * np.log10(S + 1e-20)


def _window(name: str, n: int) -> np.ndarray:
    return {"hann": np.hanning, "hamming": np.hamming, "blackman": np.blackman,
            "rect": np.ones, "rectangular": np.ones}[name](n)


def noise_floor_db(p_db: np.ndarray, pct: float = 20) -> float:
    """Robust noise-floor estimate from a dB spectrum (a low percentile, unaffected by carriers)."""
    return float(np.percentile(p_db, pct))


def find_carriers(x: np.ndarray, fs: float, nfft: int = 8192, min_snr_db: float = 10, max_peaks: int = 10,
                  exclude_dc_hz: float = 0.0, edge_db: float = 6.0) -> list[dict]:
    """Strongest signals in a capture, strongest first.

    For each peak: ``freq_hz`` (sub-bin interpolated, relative to the tuned centre), ``snr_db`` over the noise
    floor, ``bw_10db_hz`` (width where power is within 10 dB of the peak — right for carriers, CW, OOK) and
    ``bw_occ_hz`` / ``center_occ_hz`` (contiguous region more than ``edge_db`` over the floor — right for FM,
    FSK and other wide signals). Everything inside the occupied region is blanked before the next search, so
    one wideband station is reported once. ``exclude_dc_hz`` ignores +/- that much around 0 Hz (DC spike).
    """
    f, p = psd(x, fs, nfft)
    floor = noise_floor_db(p)
    work = p.copy()
    if exclude_dc_hz:
        work[np.abs(f) < exclude_dc_hz] = floor
    out = []
    df = f[1] - f[0]
    for _ in range(max_peaks):
        k = int(np.argmax(work))
        if work[k] - floor < min_snr_db:
            break
        lo = k
        while lo > 0 and p[lo] > p[k] - 10:
            lo -= 1
        hi = k
        while hi < len(p) - 1 and p[hi] > p[k] - 10:
            hi += 1
        olo = k
        while olo > 0 and p[olo - 1] > floor + edge_db:
            olo -= 1
        ohi = k
        while ohi < len(p) - 1 and p[ohi + 1] > floor + edge_db:
            ohi += 1
        if 0 < k < len(p) - 1:   # parabolic interpolation of the peak for sub-bin accuracy
            a, b, c = p[k - 1], p[k], p[k + 1]
            den = a - 2 * b + c
            frac = 0.5 * (a - c) / den if den else 0.0
        else:
            frac = 0.0
        out.append({"freq_hz": float(f[k] + frac * df), "power_db": float(p[k]), "snr_db": float(p[k] - floor),
                    "bw_10db_hz": float((hi - lo) * df), "bw_occ_hz": float((ohi - olo + 1) * df),
                    "center_occ_hz": float((f[olo] + f[ohi]) / 2)})
        work[max(0, min(lo, olo) - 2):max(hi, ohi) + 3] = floor
    return out


def signal_center(x: np.ndarray, fs: float, nfft: int = 8192, above_floor_db: float = 10,
                  exclude_dc_hz: float = 0.0) -> float:
    """Centre of the band occupied by the strongest signal: midpoint between the lowest and highest frequency
    that rise ``above_floor_db`` over the noise floor, in the contiguous region around the strongest peak.
    Use this (not the strongest peak, and not a power centroid) for FSK: it has one peak per tone and
    unequal numbers of 1s and 0s bias a centroid."""
    f, p = psd(x, fs, nfft)
    m = p > noise_floor_db(p) + above_floor_db
    if exclude_dc_hz:
        m &= np.abs(f) >= exclude_dc_hz
    if not m.any():
        return 0.0
    work = np.where(m, p, -np.inf)
    k = int(np.argmax(work))
    # grow the region around the peak, bridging gaps up to 5 % of the span (the dip between FSK tones)
    gap = max(2, int(0.05 * nfft))
    lo = hi = k
    while True:
        nxt = np.flatnonzero(m[max(0, lo - gap):lo])
        if not len(nxt):
            break
        lo = max(0, lo - gap) + int(nxt[0])
    while True:
        nxt = np.flatnonzero(m[hi + 1:hi + 1 + gap])
        if not len(nxt):
            break
        hi = hi + 1 + int(nxt[-1])
    return float((f[lo] + f[hi]) / 2)


def occupied_bandwidth(x: np.ndarray, fs: float, fraction: float = 0.99, nfft: int = 8192) -> tuple[float, float, float]:
    """Bandwidth containing ``fraction`` of the power. Returns (bw_hz, f_low, f_high)."""
    f, p = psd(x, fs, nfft, db=False)
    c = np.cumsum(p) / np.sum(p)
    lo = f[np.searchsorted(c, (1 - fraction) / 2)]
    hi = f[min(len(f) - 1, np.searchsorted(c, 1 - (1 - fraction) / 2))]
    return float(hi - lo), float(lo), float(hi)


def estimate_cfo(x: np.ndarray, fs: float, power: int = 1, nfft: int | None = None) -> float:
    """Carrier frequency offset from the FFT peak of x**power, divided by power.
    power=1 for a carrier/AM/OOK, 2 for BPSK, 4 for QPSK (removes the modulation)."""
    y = np.asarray(x, np.complex128) ** power
    nfft = nfft or int(2 ** np.ceil(np.log2(max(len(y), 1024))))
    Y = np.abs(np.fft.fft(y * np.hanning(len(y)), nfft))
    k = int(np.argmax(Y))
    if 0 < k < nfft - 1:
        a, b, c = np.log(Y[k - 1] + 1e-20), np.log(Y[k] + 1e-20), np.log(Y[k + 1] + 1e-20)
        den = a - 2 * b + c
        k = k + (0.5 * (a - c) / den if den else 0)
    f = (k if k < nfft / 2 else k - nfft) * fs / nfft
    return float(f / power)


# ----------------------------------------------------------------------------- filtering & resampling

def firwin_lowpass(num_taps: int, cutoff_hz: float, fs: float) -> np.ndarray:
    """Windowed-sinc low-pass (Blackman), unity DC gain. num_taps odd."""
    num_taps |= 1
    n = np.arange(num_taps) - (num_taps - 1) / 2
    h = np.sinc(2 * cutoff_hz / fs * n) * np.blackman(num_taps)
    return (h / h.sum()).astype(np.float32)


def lowpass(x: np.ndarray, cutoff_hz: float, fs: float, num_taps: int | None = None) -> np.ndarray:
    """Zero-delay (centre-aligned) low-pass filter. Taps default to ~4 / (transition width)."""
    num_taps = num_taps or int(min(4001, max(31, 4 * fs / max(cutoff_hz, 1))))
    h = firwin_lowpass(num_taps, cutoff_hz, fs)
    return fftconvolve_same(x, h).astype(np.result_type(x, np.float32))


def fftconvolve_same(x: np.ndarray, h: np.ndarray) -> np.ndarray:
    """np.convolve(x, h, 'same') via FFT (fast for long filters). Real inputs give real output."""
    n = len(x) + len(h) - 1
    nfft = 1 << int(np.ceil(np.log2(n)))
    if np.iscomplexobj(x) or np.iscomplexobj(h):
        y = np.fft.ifft(np.fft.fft(x, nfft) * np.fft.fft(h, nfft))[:n]
    else:
        y = np.fft.irfft(np.fft.rfft(x, nfft) * np.fft.rfft(h, nfft), nfft)[:n]
    start = (len(h) - 1) // 2
    return y[start:start + len(x)]


def decimate(x: np.ndarray, factor: int, fs: float) -> tuple[np.ndarray, float]:
    """Anti-alias filter then keep every factor-th sample."""
    if factor <= 1:
        return x, fs
    y = lowpass(x, 0.45 * fs / factor, fs)
    return y[::factor], fs / factor


def channelize(x: np.ndarray, fs: float, center_hz: float, bw_hz: float, out_fs: float | None = None
               ) -> tuple[np.ndarray, float]:
    """Pull one signal out of a wideband capture: mix ``center_hz`` to 0 Hz, low-pass to bw/2, decimate.
    out_fs defaults to the smallest integer decimation that keeps >= 2.5 * bw."""
    n = np.arange(len(x))
    y = np.asarray(x, np.complex64) * np.exp(-1j * TWO_PI * center_hz * n / fs).astype(np.complex64)
    y = lowpass(y, bw_hz / 2, fs)
    target = out_fs or 2.5 * bw_hz
    dec = max(1, int(fs // target))
    return y[::dec].astype(np.complex64), fs / dec


def dc_block(x: np.ndarray) -> np.ndarray:
    return (x - np.mean(x)).astype(np.complex64)


def moving_average(x: np.ndarray, n: int) -> np.ndarray:
    n = max(1, int(n))
    return np.convolve(x, np.ones(n) / n, mode="same")


# ----------------------------------------------------------------------------- detectors / demodulators

def envelope(x: np.ndarray) -> np.ndarray:
    """AM / OOK / ASK demodulator: magnitude of the complex sample."""
    return np.abs(x).astype(np.float32)


def fm_discriminator(x: np.ndarray, fs: float) -> np.ndarray:
    """Instantaneous frequency in Hz: angle(x[n] * conj(x[n-1])) * fs / 2pi. Length len(x) (first value repeated)."""
    d = np.angle(x[1:] * np.conj(x[:-1])) * fs / TWO_PI
    return np.concatenate([d[:1], d]).astype(np.float32)


def phase(x: np.ndarray, unwrap: bool = False) -> np.ndarray:
    p = np.angle(x)
    return np.unwrap(p) if unwrap else p


def am_demod(x: np.ndarray, fs: float, audio_fs: float = 48_000, audio_bw: float = 5_000) -> tuple[np.ndarray, float]:
    env = envelope(x) - np.mean(np.abs(x))
    env = lowpass(env, audio_bw, fs)
    dec = max(1, int(fs // audio_fs))
    a = env[::dec]
    return (a / (np.max(np.abs(a)) or 1)).astype(np.float32), fs / dec


def fm_demod(x: np.ndarray, fs: float, deviation_hz: float = 75e3, audio_fs: float = 48_000,
             deemph_us: float | None = 75.0) -> tuple[np.ndarray, float]:
    """Broadcast/NFM audio: discriminator / deviation, de-emphasis (75 us US, 50 us EU, None for NFM data),
    low-pass and decimate to ~audio_fs."""
    a = fm_discriminator(x, fs) / deviation_hz
    if deemph_us:
        alpha = 1 - np.exp(-1 / (fs * deemph_us * 1e-6))
        y = np.empty_like(a)
        acc = 0.0
        for i, v in enumerate(a):        # one-pole IIR; fine for offline use
            acc += alpha * (v - acc)
            y[i] = acc
        a = y
    a = lowpass(a, 15e3, fs)
    dec = max(1, int(fs // audio_fs))
    return a[::dec].astype(np.float32), fs / dec


# ----------------------------------------------------------------------------- bursts, thresholds, timing

def otsu_threshold(v: np.ndarray, bins: int = 256) -> float:
    """Two-class threshold that maximises between-class variance. Returns the midpoint between the two
    class means (more robust than the raw Otsu bin edge for clean two-level signals)."""
    v = np.asarray(v, np.float64)
    hist, edges = np.histogram(v, bins=bins)
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(hist)
    w1 = w0[-1] - w0
    m0 = np.cumsum(hist * centers) / np.maximum(w0, 1)
    m1 = (np.sum(hist * centers) - np.cumsum(hist * centers)) / np.maximum(w1, 1)
    k = int(np.argmax(w0 * w1 * (m0 - m1) ** 2))
    return float((m0[k] + m1[k]) / 2)


def bursts(x: np.ndarray, fs: float, threshold_db: float | None = None, min_len_s: float = 1e-3,
           merge_gap_s: float = 5e-3, smooth_s: float = 2e-4) -> list[tuple[int, int]]:
    """Find on-air segments. Threshold defaults to halfway (in dB) between the noise floor and the peak.
    Returns [(start_sample, end_sample), ...]."""
    p = moving_average(np.abs(x) ** 2, int(smooth_s * fs) or 1)
    pdb = 10 * np.log10(p + 1e-20)
    if threshold_db is None:
        floor, peak = np.percentile(pdb, 20), np.percentile(pdb, 99.9)
        threshold_db = (floor + peak) / 2
    on = pdb > threshold_db
    edges = np.flatnonzero(np.diff(on.astype(np.int8)))
    starts = list(edges[~on[edges]] + 1) if len(edges) else []
    ends = list(edges[on[edges]] + 1) if len(edges) else []
    if on[0]:
        starts = [0] + starts
    if on[-1]:
        ends = ends + [len(on)]
    segs = []
    for s, e in zip(starts, ends):
        if segs and s - segs[-1][1] < merge_gap_s * fs:
            segs[-1] = (segs[-1][0], e)
        else:
            segs.append((s, e))
    return [(int(s), int(e)) for s, e in segs if e - s >= min_len_s * fs]


def gate(x: np.ndarray, fs: float, **kw) -> np.ndarray:
    """Concatenate only the on-air bursts of x (see bursts()). Use before psd()/find_carriers() on a sparse,
    bursty capture: a 1 ms packet in a 1 s file is diluted by 30 dB in a time-averaged spectrum."""
    segs = bursts(x, fs, **kw)
    return np.concatenate([x[s:e] for s, e in segs]) if segs else x


def runs(levels: np.ndarray) -> list[tuple[int, int]]:
    """Run-length encode a 0/1 array -> [(level, length_samples), ...]."""
    v = np.asarray(levels).astype(np.int8)
    if len(v) == 0:
        return []
    idx = np.flatnonzero(np.diff(v)) + 1
    starts = np.r_[0, idx]
    lens = np.diff(np.r_[starts, len(v)])
    return [(int(v[s]), int(n)) for s, n in zip(starts, lens)]


def estimate_symbol_rate(metric: np.ndarray, fs: float, threshold: float | None = None,
                         min_sps: float = 2.0) -> float:
    """Symbol rate from a two-level waveform (envelope for OOK, discriminator for FSK).

    Every run between transitions is an integer number of symbols long. Start from the short-run cluster and
    refine T so that all runs are close to integer multiples of it (least squares)."""
    thr = otsu_threshold(metric) if threshold is None else threshold
    r = np.array([n for _, n in runs(metric > thr)][1:-1], np.float64)   # drop partial first/last runs
    r = r[r >= min_sps]
    if len(r) < 3:
        raise ValueError("not enough transitions to estimate a symbol rate")
    T = float(np.median(np.sort(r)[: max(3, len(r) // 4)]))
    for _ in range(5):
        k = np.maximum(1, np.round(r / T))
        T = float(np.sum(r * k) / np.sum(k * k))
    return fs / T


def slice_symbols(metric: np.ndarray, sps: float, threshold: float | None = None, start: int = 0
                  ) -> np.ndarray:
    """Integrate-and-dump each symbol, pick the sampling phase with the largest spread, threshold to bits.
    ``sps`` may be fractional (symbols are sampled at round(start + phase + k*sps + sps/2))."""
    m = np.asarray(metric, np.float64)[start:]
    box = max(1, int(round(sps)))
    mf = np.convolve(m, np.ones(box) / box, mode="same")        # one-symbol matched filter
    n_sym = int(np.ceil(len(mf) / sps))
    best, best_var = None, -1.0
    for ph in np.linspace(0, sps, num=min(16, max(2, int(sps))), endpoint=False):
        idx = np.round(ph + np.arange(n_sym) * sps + sps / 2).astype(int)
        idx = idx[idx < len(mf)]
        v = mf[idx]
        if np.var(v) > best_var:
            best_var, best = float(np.var(v)), v
    thr = otsu_threshold(best) if threshold is None else threshold
    return (best > thr).astype(np.uint8)


def slice_symbols_pll(metric: np.ndarray, sps: float, threshold: float | None = None, gain: float = 0.25,
                      freq_gain: float = 0.01) -> np.ndarray:
    """Slicer with a transition-tracking symbol clock (a simple digital PLL).

    The waveform is box-filtered over one symbol, then sampled once per symbol. Every threshold crossing
    (interpolated to a fraction of a sample) pulls the clock so that crossings fall half a symbol away from
    sampling instants; ``freq_gain`` also nudges the symbol period. This tolerates a symbol-rate estimate
    that is off by ~1-2 % over long packets, where slice_symbols() (fixed clock) slips bits."""
    m = np.asarray(metric, np.float64)
    box = max(1, int(round(sps)))
    mf = np.convolve(m, np.ones(box) / box, mode="same")
    thr = otsu_threshold(mf) if threshold is None else threshold
    d = mf - thr
    idx = np.flatnonzero(np.signbit(d[:-1]) != np.signbit(d[1:]))
    cross = idx + d[idx] / (d[idx] - d[idx + 1])            # linear interpolation of the crossing time
    if len(cross) == 0:
        return (mf[int(sps / 2)::max(1, int(round(sps)))] > thr).astype(np.uint8)
    t = cross[0] + sps / 2
    period = float(sps)
    out = []
    ci = 1
    while t < len(mf) - 1:
        while ci < len(cross) and cross[ci] < t + period / 2:
            err = cross[ci] - (t - period / 2) if cross[ci] < t else cross[ci] - (t + period / 2)
            if abs(err) < period / 2:
                t += gain * err
                period += freq_gain * err
            ci += 1
        k = int(round(t))
        if k >= len(mf):
            break
        out.append(1 if mf[k] > thr else 0)
        t += period
    return np.array(out, np.uint8)


def clock_recover_bits(metric: np.ndarray, sps: float, threshold: float | None = None) -> np.ndarray:
    """Edge-synchronous slicer: re-align the symbol clock on every transition (UART-like). Tolerates small
    rate errors over long packets better than slice_symbols()."""
    thr = otsu_threshold(metric) if threshold is None else threshold
    out = []
    for lv, n in runs(np.asarray(metric) > thr):
        k = int(round(n / sps))
        out += [lv] * k
    return np.array(out, np.uint8)


# ----------------------------------------------------------------------------- PSK receivers

def matched_filter_rrc(x: np.ndarray, sps: int, beta: float = 0.35, span: int = 10) -> np.ndarray:
    from .mod import rrc_taps
    return np.convolve(x, rrc_taps(sps, beta, span), mode="same").astype(np.complex64)


def best_timing(x: np.ndarray, sps: int) -> int:
    """Symbol-timing phase with the most energy (works after the matched filter)."""
    e = [np.mean(np.abs(x[p::sps]) ** 2) for p in range(sps)]
    return int(np.argmax(e))


def costas(symbols: np.ndarray, order: int = 2, loop_bw: float = 0.02) -> tuple[np.ndarray, np.ndarray]:
    """Decision-directed Costas loop on symbol-spaced samples. order 2 = BPSK, 4 = QPSK.
    Returns (derotated symbols, phase track). Absolute phase stays ambiguous by 360/order degrees — resolve
    it with a known preamble/sync word or differential coding."""
    zeta = 0.707
    theta = loop_bw / (zeta + 1 / (4 * zeta))
    k1 = 4 * zeta * theta / (1 + 2 * zeta * theta + theta ** 2)
    k2 = 4 * theta ** 2 / (1 + 2 * zeta * theta + theta ** 2)
    ph, freq = 0.0, 0.0
    out = np.empty_like(symbols)
    track = np.empty(len(symbols))
    for i, s in enumerate(symbols):
        y = s * np.exp(-1j * ph)
        out[i] = y
        if order == 2:
            err = np.sign(y.real) * y.imag
        else:
            err = np.sign(y.real) * y.imag - np.sign(y.imag) * y.real
        freq += k2 * err
        ph += freq + k1 * err
        track[i] = ph
    return out, track


def psk_demod(x: np.ndarray, fs: float, symbol_rate: float, order: int = 2, beta: float = 0.35
              ) -> np.ndarray:
    """Coarse CFO removal (M-th power) -> RRC matched filter -> timing -> Costas. Returns symbols."""
    sps = int(round(fs / symbol_rate))
    cfo = estimate_cfo(x, fs, power=order)
    n = np.arange(len(x))
    y = x * np.exp(-1j * TWO_PI * cfo * n / fs)
    y = matched_filter_rrc(y, sps, beta)
    syms = y[best_timing(y, sps)::sps]
    syms = syms / (np.sqrt(np.mean(np.abs(syms) ** 2)) or 1)
    out, _ = costas(syms, order)
    return out


def psk_bits(symbols: np.ndarray, order: int = 2) -> np.ndarray:
    """Hard decisions for bpsk (Re>0 -> 0) or Gray qpsk matching rfkit.mod.constellation('qpsk')."""
    if order == 2:
        return (symbols.real < 0).astype(np.uint8)
    b0 = (symbols.real < 0).astype(np.uint8)
    b1 = (symbols.imag < 0).astype(np.uint8)
    # qpsk table in mod.constellation: idx0 (1+1j), idx1 (-1+1j), idx2 (1-1j), idx3 (-1-1j) -> bits b1 b0
    out = np.empty(2 * len(symbols), np.uint8)
    out[0::2], out[1::2] = b1, b0
    return out


# ----------------------------------------------------------------------------- measurements

def snr_db(x: np.ndarray, fs: float, signal_bw_hz: float, center_hz: float = 0.0, nfft: int = 8192) -> float:
    """In-band SNR: mean PSD inside signal_bw around center vs. the noise floor elsewhere (both per Hz)."""
    f, p = psd(x, fs, nfft, db=False)
    inband = np.abs(f - center_hz) < signal_bw_hz / 2
    noise = np.median(p[~inband])
    sig = np.mean(p[inband]) - noise
    return float(10 * np.log10(max(sig, 1e-20) / noise))


def papr_db(x: np.ndarray) -> float:
    """Peak-to-average power ratio. High PAPR (OFDM, multitone) needs more headroom before the 8-bit DAC clips."""
    p = np.abs(x) ** 2
    return float(10 * np.log10(p.max() / np.mean(p)))
