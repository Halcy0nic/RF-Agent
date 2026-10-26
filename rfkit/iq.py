"""Read and write IQ sample files.

Every SDR tool picks its own sample format. This module converts all of them to and from one in-memory
representation: a 1-D ``numpy.complex64`` array scaled to roughly [-1, 1].

| Format  | Extension(s)          | Layout                                    | Produced by                          |
|---------|-----------------------|-------------------------------------------|--------------------------------------|
| CS8     | .cs8 .s8              | int8  I,Q interleaved                     | hackrf_transfer -r / -t              |
| CU8     | .cu8 .u8              | uint8 I,Q interleaved, 127.5 = zero       | rtl_sdr                              |
| CS16    | .cs16 .s16            | int16 I,Q interleaved                     | rtl_fm -M raw, uhd_rx_cfile -t short |
| CS32    | .cs32 .s32            | int32 I,Q interleaved                     | SDRangel SigMF sink (32-bit, ci32_le)|
| CF32    | .cf32 .cfile .fc32    | float32 I,Q interleaved (= complex64)     | GNU Radio file sink, uhd_rx_cfile    |
| WAV     | .wav                  | 2-channel RIFF, ch0 = I, ch1 = Q          | SDR++ / SDR# baseband recorder       |
| SigMF   | .sigmf-data + -meta   | any of the above, described by JSON       | SigMF-aware tools                    |

Usage::

    from rfkit import iq
    x, fs = iq.load("capture.cu8", fs=2_048_000)      # raw formats need fs from you
    x, fs = iq.load("baseband_433920000Hz_12-00-00.wav")  # WAV carries fs
    iq.save("tone.cs8", x)                            # format from the extension
"""
from __future__ import annotations

import json
import re
import wave
from pathlib import Path

import numpy as np

RAW_FORMATS = {
    ".cs8": "cs8", ".s8": "cs8",
    ".cu8": "cu8", ".u8": "cu8",
    ".cs16": "cs16", ".s16": "cs16",
    ".cs32": "cs32", ".s32": "cs32",
    ".cf32": "cf32", ".cfile": "cf32", ".fc32": "cf32",
}

SIGMF_DATATYPE = {"cs8": "ci8", "cu8": "cu8", "cs16": "ci16_le", "cs32": "ci32_le", "cf32": "cf32_le"}


def fmt_of(path) -> str:
    """Infer the sample format from a file name."""
    p = str(path).lower()
    if p.endswith(".sigmf-data") or p.endswith(".sigmf-meta"):
        return "sigmf"
    ext = Path(p).suffix
    if ext == ".wav":
        return "wav"
    if ext in RAW_FORMATS:
        return RAW_FORMATS[ext]
    raise ValueError(f"unknown IQ format for {path!r}; pass fmt= one of cs8, cu8, cs16, cf32, wav")


# ----------------------------------------------------------------------------- decode / encode raw bytes

def from_bytes(buf: bytes | np.ndarray, fmt: str) -> np.ndarray:
    """Raw interleaved bytes -> complex64 in [-1, 1]."""
    if fmt == "cs8":
        a = np.frombuffer(buf, dtype=np.int8).astype(np.float32) / 128.0
    elif fmt == "cu8":
        a = (np.frombuffer(buf, dtype=np.uint8).astype(np.float32) - 127.5) / 127.5
    elif fmt == "cs16":
        a = np.frombuffer(buf, dtype="<i2").astype(np.float32) / 32768.0
    elif fmt == "cs32":
        a = (np.frombuffer(buf, dtype="<i4").astype(np.float64) / 2147483648.0).astype(np.float32)
    elif fmt == "cf32":
        a = np.frombuffer(buf, dtype="<f4")
    else:
        raise ValueError(fmt)
    a = a[: len(a) // 2 * 2]
    return (a[0::2] + 1j * a[1::2]).astype(np.complex64)


def to_bytes(x: np.ndarray, fmt: str, peak: float | None = None) -> bytes:
    """complex -> raw interleaved bytes.

    ``peak`` (0-1] rescales so max(|I|,|Q|) hits that fraction of full scale. Leave it None to keep the
    amplitude you gave (values beyond full scale are clipped, which causes splatter — see save()).
    """
    x = np.asarray(x, dtype=np.complex64)
    if peak is not None:
        m = max(np.max(np.abs(x.real)), np.max(np.abs(x.imag)), 1e-12)
        x = x * (peak / m)
    inter = np.empty(2 * len(x), dtype=np.float32)
    inter[0::2], inter[1::2] = x.real, x.imag
    if fmt == "cs8":
        return np.clip(np.round(inter * 127), -127, 127).astype(np.int8).tobytes()
    if fmt == "cu8":
        return np.clip(np.round(inter * 127.5 + 127.5), 0, 255).astype(np.uint8).tobytes()
    if fmt == "cs16":
        return np.clip(np.round(inter * 32767), -32767, 32767).astype("<i2").tobytes()
    if fmt == "cs32":
        return np.clip(np.round(inter.astype(np.float64) * 2147483647), -2147483647, 2147483647).astype("<i4").tobytes()
    if fmt == "cf32":
        return inter.astype("<f4").tobytes()
    raise ValueError(fmt)


# ----------------------------------------------------------------------------- files

def load(path, fs: float | None = None, fmt: str | None = None, offset_s: float = 0.0,
         seconds: float | None = None) -> tuple[np.ndarray, float | None]:
    """Load an IQ file. Returns (samples, sample_rate).

    WAV and SigMF files carry their sample rate. Raw files do not, so pass ``fs`` (it is just returned, and
    needed only for offset_s/seconds). ``offset_s``/``seconds`` read a slice without loading the whole file.
    """
    fmt = fmt or fmt_of(path)
    path = Path(path)
    if fmt == "wav":
        return _load_wav(path, offset_s, seconds)
    if fmt == "sigmf":
        meta_p = path.with_suffix(".sigmf-meta")
        data_p = path.with_suffix(".sigmf-data")
        meta = json.loads(meta_p.read_text())
        g = meta["global"]
        dt = g["core:datatype"]
        inv = {v: k for k, v in SIGMF_DATATYPE.items()}
        if dt not in inv:
            raise ValueError(f"unsupported SigMF datatype {dt}")
        return load(data_p, fs=g.get("core:sample_rate"), fmt=inv[dt], offset_s=offset_s, seconds=seconds)
    if fs is None:                       # a SigMF sidecar next to a raw file (e.g. b210_rx.py output) gives fs
        side = sidecar_meta(path)
        if side:
            fs = side["global"].get("core:sample_rate")
    bps = {"cs8": 2, "cu8": 2, "cs16": 4, "cs32": 8, "cf32": 8}[fmt]  # bytes per complex sample
    start = int(offset_s * fs) if (offset_s and fs) else 0
    count = int(seconds * fs) if (seconds and fs) else -1
    with open(path, "rb") as f:
        f.seek(start * bps)
        buf = f.read(-1 if count < 0 else count * bps)
    return from_bytes(buf, fmt), fs


def _load_wav(path: Path, offset_s: float, seconds: float | None):
    """2-channel WAV (SDR++ / SDR#). Handles int16 PCM and float32 (format tag 3) without scipy."""
    raw = path.read_bytes()
    if raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError(f"{path} is not a RIFF/WAVE file")
    pos, fmt_tag, ch, fs, bits, data_off, data_len = 12, None, None, None, None, None, None
    while pos + 8 <= len(raw):
        cid, clen = raw[pos:pos + 4], int.from_bytes(raw[pos + 4:pos + 8], "little")
        body = pos + 8
        if cid == b"fmt ":
            fmt_tag = int.from_bytes(raw[body:body + 2], "little")
            ch = int.from_bytes(raw[body + 2:body + 4], "little")
            fs = int.from_bytes(raw[body + 4:body + 8], "little")
            bits = int.from_bytes(raw[body + 14:body + 16], "little")
            if fmt_tag == 0xFFFE and clen >= 40:  # WAVE_FORMAT_EXTENSIBLE: real tag is in the sub-format GUID
                fmt_tag = int.from_bytes(raw[body + 24:body + 26], "little")
        elif cid == b"data":
            data_off = body
            # Recorders that were killed mid-write leave a 0 or bogus length; trust the file size instead.
            data_len = clen if 0 < clen <= len(raw) - body else len(raw) - body
            break
        pos = body + clen + (clen & 1)
    if ch != 2 or data_off is None:
        raise ValueError(f"{path}: expected a 2-channel IQ WAV (got channels={ch})")
    fmt = {(1, 16): "cs16", (3, 32): "cf32", (1, 8): "cu8"}.get((fmt_tag, bits))
    if fmt is None:
        raise ValueError(f"{path}: unsupported WAV sample format tag={fmt_tag} bits={bits}")
    bps = bits // 8 * 2
    start = int(offset_s * fs) * bps
    end = data_len if seconds is None else min(data_len, start + int(seconds * fs) * bps)
    return from_bytes(raw[data_off + start:data_off + end], fmt), float(fs)


def save(path, x: np.ndarray, fs: float | None = None, fmt: str | None = None, peak: float | None = 0.8,
         center_hz: float | None = None, description: str | None = None) -> Path:
    """Write IQ to ``path`` in the format implied by its extension.

    ``peak=0.8`` (default) normalises so the largest I or Q value is 80 % of full scale: loud enough to use the
    8-bit range of a HackRF, with headroom so nothing clips. Pass peak=None to write values unchanged.
    For ``.wav`` and ``.sigmf-data``, ``fs`` is required. SigMF also writes the ``.sigmf-meta`` sidecar.
    """
    path = Path(path)
    fmt = fmt or fmt_of(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "wav":
        if fs is None:
            raise ValueError("fs required for WAV")
        with wave.open(str(path), "wb") as w:
            w.setnchannels(2)
            w.setsampwidth(2)
            w.setframerate(int(fs))
            w.writeframes(to_bytes(x, "cs16", peak))
        return path
    if fmt == "sigmf":
        if fs is None:
            raise ValueError("fs required for SigMF")
        data_p = path.with_suffix(".sigmf-data")
        data_p.write_bytes(to_bytes(x, "cf32", peak))
        g = {"core:datatype": "cf32_le", "core:sample_rate": float(fs), "core:version": "1.0.0"}
        if description:
            g["core:description"] = description
        cap = {"core:sample_start": 0}
        if center_hz is not None:
            cap["core:frequency"] = float(center_hz)
        meta = {"global": g, "captures": [cap], "annotations": []}
        data_p.with_suffix(".sigmf-meta").write_text(json.dumps(meta, indent=2))
        return data_p
    path.write_bytes(to_bytes(x, fmt, peak))
    return path


def sidecar_meta(path) -> dict | None:
    """SigMF metadata stored next to a raw file as <name>.sigmf-meta (b210_rx.py writes these)."""
    p = Path(path).with_suffix(".sigmf-meta")
    if p.exists():
        try:
            return json.loads(p.read_text())
        except (OSError, ValueError):
            return None
    return None


def info_from_name(path) -> dict:
    """Centre frequency from a SigMF sidecar, else from common recorder file names.

    SDR++:   baseband_433920000Hz_12-34-56_14-10-2026.wav
    SDR#:    SDRSharp_20261014_123456Z_433920000Hz_IQ.wav
    HackRF -w: HackRF_20261014_123456Z_433920kHz_IQ.wav
    """
    side = sidecar_meta(path)
    if side and side.get("captures") and "core:frequency" in side["captures"][0]:
        return {"center_hz": float(side["captures"][0]["core:frequency"])}
    name = Path(path).name
    out = {}
    m = re.search(r"(\d+(?:\.\d+)?)(Hz|kHz|MHz)", name)
    if m:
        out["center_hz"] = float(m.group(1)) * {"Hz": 1, "kHz": 1e3, "MHz": 1e6}[m.group(2)]
    return out


def samples_for(seconds: float, fs: float) -> int:
    return int(round(seconds * fs))


def file_bytes(seconds: float, fs: float, fmt: str = "cs8") -> int:
    """How big will a recording be? (CS8 at 8 MS/s = 16 MB/s.) fmt: cs8, cu8, cs16, cs32 or cf32."""
    return int(seconds * fs) * {"cs8": 2, "cu8": 2, "cs16": 4, "cs32": 8, "cf32": 8}[fmt]
