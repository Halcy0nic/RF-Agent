"""Wide-band survey: where and when is there activity, and which of it behaves like a beacon, a hopper or a one-off?

    S, f = survey.tfmap(chunks, fs)                  # coarse time-frequency map (rows = time)
    ev = survey.find_events(S, f, row_s, center_hz)  # [{t_s, dur_s, freq_hz, bw_hz, level_db}, ...]
    groups = survey.classify(ev, span_s)             # beacons / hoppers / one-offs

Everything is NumPy + SciPy (ndimage). The classification is behavioural, not level-based: a loud beacon and a
quiet hopper are told apart by what their events do over time.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def tfmap(blocks, fs: float, row_s: float = 0.01, nfft: int = 4096):
    """Average-power spectrogram in dB. ``blocks`` yields complex arrays (any length; trailing partial rows are
    dropped per block, so use blocks that are a whole number of rows). Returns (S[rows, nfft], f_hz)."""
    row = int(round(row_s * fs))
    win = np.hanning(nfft).astype(np.float32)
    rows = []
    for x in blocks:
        x = np.asarray(x, np.complex64)
        for i in range(len(x) // row):
            seg = x[i * row:(i + 1) * row]
            k = len(seg) // nfft
            if k == 0:
                continue
            fr = seg[: k * nfft].reshape(k, nfft) * win
            rows.append(np.mean(np.abs(np.fft.fftshift(np.fft.fft(fr, axis=1), axes=1)) ** 2, axis=0))
    S = 10 * np.log10(np.array(rows, np.float32) + 1e-20)
    return S, np.fft.fftshift(np.fft.fftfreq(nfft, 1 / fs))


def noise_floor(S: np.ndarray) -> float:
    """Typical noise level: the median of per-bin medians (insensitive to carriers, bursts and spurs)."""
    return float(np.median(np.median(S, axis=0)))


def find_events(S: np.ndarray, f: np.ndarray, row_s: float, center_hz: float = 0.0, thresh_db: float = 15.0,
                min_s: float = 0.02, min_rows_bins: int = 1, dc_guard_bins: int = 3,
                persistent_db: float = 8.0) -> list[dict]:
    """Connected blobs above the noise floor in the time-frequency map.

    thresh_db       blob threshold above the floor.
    min_s           shortest event kept (rejects single-row noise ticks).
    persistent_db   bins whose *median* over time sits this far above the floor are continuous carriers; they
                    are reported separately as {"kind": "carrier"} and excluded from burst detection.
    Event fields: t_s, dur_s, freq_hz (absolute, level-weighted), bw_hz, level_db (peak over floor)."""
    floor = noise_floor(S)
    med = np.median(S, axis=0)
    carriers = med > floor + persistent_db
    work = S - floor
    mask = work > thresh_db
    mask[:, carriers] = False
    mid = S.shape[1] // 2
    mask[:, mid - dc_guard_bins: mid + dc_guard_bins + 1] = False
    # join a burst's sidebands (a few bins) and tiny time gaps (one row) into one blob
    mask = ndimage.binary_closing(mask, structure=np.ones((2, 3)))
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    df = f[1] - f[0]
    ev = []
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        r0, r1, c0, c1 = sl[0].start, sl[0].stop, sl[1].start, sl[1].stop
        dur = (r1 - r0) * row_s
        if dur < min_s or (c1 - c0) < min_rows_bins:
            continue
        sub = np.where(lab[sl] == i, work[sl], 0)
        w = np.clip(sub, 0, None) ** 2
        cols = np.arange(c0, c1)
        fc = float((w.sum(axis=0) * f[cols]).sum() / (w.sum() + 1e-12))
        ev.append({"t_s": round(r0 * row_s, 4), "dur_s": round(dur, 4), "freq_hz": center_hz + fc,
                   "bw_hz": float((c1 - c0) * df), "level_db": float(sub.max())})
    ev.sort(key=lambda e: e["t_s"])
    out = ev
    idx = np.flatnonzero(carriers)
    idx = idx[np.abs(idx - mid) > dc_guard_bins]
    for grp in np.split(idx, np.flatnonzero(np.diff(idx) > 2) + 1) if len(idx) else []:
        k = grp[np.argmax(med[grp])]                       # one line per spectral peak, not one per skirt bin
        out.append({"kind": "carrier", "freq_hz": center_hz + float(f[k]), "level_db": float(med[k] - floor)})
    return out


def _cluster_by_freq(ev: list[dict], tol_hz: float) -> list[list[dict]]:
    cl: list[list[dict]] = []
    for e in sorted(ev, key=lambda e: e["freq_hz"]):
        if cl and abs(e["freq_hz"] - np.mean([c["freq_hz"] for c in cl[-1]])) <= tol_hz:
            cl[-1].append(e)
        else:
            cl.append([e])
    return cl


def _regular(t: np.ndarray, tol: float = 0.03, frac: float = 0.8) -> bool:
    """True if most gaps are (close to) whole multiples of one interval: a steady schedule with a few misses."""
    if len(t) < 4:
        return False
    iv = np.diff(np.sort(t))
    base = np.median(iv)
    if base <= 0:
        return False
    k = np.round(iv / base)
    return float(np.mean((k >= 1) & (k <= 2) & (np.abs(iv - k * base) < tol * base * k))) >= frac


def _fast_hoppers(singles: list[dict], tol_hz: float, min_events: int = 4):
    """Hoppers that move after every burst: same duration/level/width, a steady schedule, a different frequency
    each time. They never repeat on one frequency, so the per-frequency pass above cannot see them. Returns
    (remaining_singles, hopper_entries)."""
    if len(singles) < min_events:
        return singles, []
    found, used = [], set()
    for shift in (0.0, 0.5):                       # two bucket phases so a cluster is not cut in half
        buckets: dict = {}
        for i, e in enumerate(singles):
            key = (round(np.log2(max(e["dur_s"], 1e-3)) * 3 + shift), round(e["level_db"] / 6 + shift),
                   round(np.log2(max(e["bw_hz"], 1.0)) + shift))
            buckets.setdefault(key, []).append(i)
        for idx in buckets.values():
            if len(idx) < min_events:
                continue
            ev = [singles[i] for i in idx]
            fr = np.array([e["freq_hz"] for e in ev])
            t = np.array([e["t_s"] for e in ev])
            if np.ptp(fr) < 4 * tol_hz or not _regular(t):
                continue
            found.append((len(idx), idx))
    found.sort(key=lambda f: -f[0])
    hoppers = []
    for _, idx in found:
        idx = [i for i in idx if i not in used]
        if len(idx) < min_events:
            continue
        ev = sorted((singles[i] for i in idx), key=lambda e: e["t_s"])
        if not _regular(np.array([e["t_s"] for e in ev])):
            continue
        used.update(idx)
        iv = np.diff([e["t_s"] for e in ev])
        hoppers.append({"period_s": float(np.median(iv)), "dur_s": float(np.median([e["dur_s"] for e in ev])),
                        "dwells": [{"freq_hz": e["freq_hz"], "count": 1, "first_s": e["t_s"], "last_s": e["t_s"],
                                    "period_s": 0.0, "dur_s": e["dur_s"], "level_db": e["level_db"], "cv": 0.0}
                                   for e in ev]})
    return [e for i, e in enumerate(singles) if i not in used], hoppers


def classify(ev: list[dict], span_s: float, tol_hz: float = 25e3, min_repeats: int = 3) -> dict:
    """Sort events by behaviour.

    Events are first grouped by frequency. A frequency with >= min_repeats events at a steady interval is
    "periodic". Periodic frequencies with the same burst length and interval whose active periods do not
    overlap are the dwells of one **hopper**; the same shape repeating over the whole capture is a **beacon**.
    Everything else is a **one-off**. Returns {"beacons": [...], "hoppers": [...], "one_offs": [...],
    "carriers": [...]} where hopper entries list their dwells in time order."""
    bursts = [e for e in ev if e.get("kind") != "carrier"]
    carriers = [e for e in ev if e.get("kind") == "carrier"]
    periodic, singles = [], []
    for c in _cluster_by_freq(bursts, tol_hz):
        t = np.array(sorted(e["t_s"] for e in c))
        if len(c) >= min_repeats:
            iv = np.diff(t)
            cv = float(np.std(iv) / (np.mean(iv) + 1e-12))
            if cv < 0.25:
                periodic.append({"freq_hz": float(np.mean([e["freq_hz"] for e in c])), "count": len(c),
                                 "first_s": float(t[0]), "last_s": float(t[-1]),
                                 "period_s": float(np.median(iv)), "dur_s": float(np.median([e["dur_s"] for e in c])),
                                 "level_db": float(max(e["level_db"] for e in c)), "cv": round(cv, 3)})
                continue
        singles += c
    # periodic frequencies with matching shape: beacon (spans the capture) or dwells of a hopper (short, disjoint)
    shapes: list[list[dict]] = []
    for p in periodic:
        for s in shapes:
            q = s[0]
            if abs(p["period_s"] - q["period_s"]) < 0.2 * q["period_s"] and abs(p["dur_s"] - q["dur_s"]) < 0.3 * q["dur_s"]:
                s.append(p)
                break
        else:
            shapes.append([p])
    singles, fast = _fast_hoppers(singles, tol_hz)
    beacons, hoppers = [], []
    hoppers += fast
    for s in shapes:
        s.sort(key=lambda p: p["first_s"])
        disjoint = len(s) >= 2 and all(b["first_s"] >= a["last_s"] - 0.5 * a["period_s"] for a, b in zip(s, s[1:]))
        short = all((p["last_s"] - p["first_s"]) < 0.6 * span_s for p in s)
        if disjoint and short:
            hoppers.append({"period_s": float(np.median([p["period_s"] for p in s])),
                            "dur_s": float(np.median([p["dur_s"] for p in s])), "dwells": s})
        else:
            beacons += s
    return {"beacons": beacons, "hoppers": hoppers, "one_offs": singles, "carriers": carriers}
