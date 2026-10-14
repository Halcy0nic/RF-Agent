"""Tiny shared helpers for the standalone examples (NumPy only, no rfkit).

Every example builds complex baseband IQ at SAMPLE_RATE, places it OFFSET_HZ above the tuned centre, and
writes CS8 (signed 8-bit I/Q interleaved) — the format `hackrf_transfer -t` plays.
"""
import numpy as np

SAMPLE_RATE = 2_000_000   # 2 MS/s: the lowest rate the HackRF supports well
OFFSET_HZ = 100_000       # keep the signal 100 kHz away from the centre (DC / LO leakage lives at 0 Hz)


def bytes_to_bits(data: bytes) -> np.ndarray:
    """b'\\x2d' -> [0,0,1,0,1,1,0,1] (MSB first)."""
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def crc16_ccitt(data: bytes) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF). crc16_ccitt(b'123456789') == 0x29B1."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def packet(payload: bytes) -> bytes:
    """AA AA (preamble) | 2D D4 (sync) | length | payload | CRC-16 (big-endian, over length+payload)."""
    body = bytes([len(payload)]) + payload
    c = crc16_ccitt(body)
    return b"\xaa\xaa\x2d\xd4" + body + bytes([c >> 8, c & 0xFF])


def shift_to_offset(baseband: np.ndarray, offset_hz: float = OFFSET_HZ, fs: float = SAMPLE_RATE) -> np.ndarray:
    """Multiply by e^(j*2*pi*f*t): moves the whole signal up by offset_hz."""
    t = np.arange(len(baseband)) / fs
    return baseband * np.exp(2j * np.pi * offset_hz * t)


def raised_cosine_edges(envelope: np.ndarray, ramp_s: float, fs: float = SAMPLE_RATE) -> np.ndarray:
    """Smooth 0/1 keying with a Hann window so on/off edges don't splatter ("key clicks")."""
    n = max(2, int(ramp_s * fs))
    w = np.hanning(n)
    return np.convolve(envelope, w / w.sum(), mode="same")


def pad_silence(iq: np.ndarray, seconds: float = 0.25, fs: float = SAMPLE_RATE) -> np.ndarray:
    z = np.zeros(int(seconds * fs), dtype=np.complex64)
    return np.concatenate([z, iq.astype(np.complex64), z])


def save_cs8(iq: np.ndarray, path: str, peak: int = 100, fs: float = SAMPLE_RATE) -> None:
    """Scale to +/-peak (of 127), interleave I/Q as int8, write. peak=100 leaves headroom so nothing clips."""
    iq = iq / np.max(np.abs(iq)) * peak
    out = np.empty(2 * len(iq), dtype=np.int8)
    out[0::2] = np.clip(np.round(iq.real), -127, 127)
    out[1::2] = np.clip(np.round(iq.imag), -127, 127)
    out.tofile(path)
    print(f"wrote {path}: {len(iq):,} samples, {len(iq) / fs:.2f} s, {out.nbytes / 1e6:.1f} MB")
    print(f"TX: gtimeout {int(len(iq) / fs) + 5} hackrf_transfer -t {path} -f 433920000 -s {int(fs)} -x 20 -a 0")
