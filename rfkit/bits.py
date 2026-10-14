"""Bits, line codes, framing, checksums and whitening.

Everything here operates on numpy uint8 arrays of 0/1 values, MSB first unless a function says otherwise.

    >>> from rfkit import bits
    >>> b = bits.frame(b"HI!")                      # preamble AA AA + sync 2D D4 + len + payload + CRC16
    >>> bits.parse_frame(b)["payload"]
    b'HI!'
"""
from __future__ import annotations

import numpy as np

DEFAULT_PREAMBLE = b"\xaa\xaa"
DEFAULT_SYNC = b"\x2d\xd4"   # the same sync word TI CC1101 / many sub-GHz radios default to

# ----------------------------------------------------------------------------- bytes <-> bits

def from_bytes(data: bytes, lsb_first: bool = False) -> np.ndarray:
    a = np.frombuffer(bytes(data), dtype=np.uint8)
    return np.unpackbits(a, bitorder="little" if lsb_first else "big")


def to_bytes(b, lsb_first: bool = False) -> bytes:
    b = np.asarray(b, dtype=np.uint8)
    b = b[: len(b) // 8 * 8]
    return np.packbits(b, bitorder="little" if lsb_first else "big").tobytes()


def from_str(s: str) -> np.ndarray:
    """'1011 0010' -> array([1,0,1,1,0,0,1,0])"""
    return np.array([int(c) for c in s if c in "01"], dtype=np.uint8)


def to_str(b, group: int = 8) -> str:
    s = "".join(str(int(v)) for v in b)
    return " ".join(s[i:i + group] for i in range(0, len(s), group)) if group else s


def find(haystack, needle, max_errors: int = 0) -> list[int]:
    """Indices where bit pattern ``needle`` occurs in ``haystack`` (allowing up to max_errors bit errors)."""
    h = np.asarray(haystack, dtype=np.int8)
    n = np.asarray(needle, dtype=np.int8)
    if len(h) < len(n):
        return []
    # correlation of +/-1 versions: matches - mismatches = len - 2*errors
    hs, ns = 2 * h - 1, 2 * n - 1
    c = np.correlate(hs.astype(np.int32), ns.astype(np.int32), mode="valid")
    return [int(i) for i in np.where(c >= len(n) - 2 * max_errors)[0]]


# ----------------------------------------------------------------------------- line codes

def manchester_encode(b, ieee: bool = True) -> np.ndarray:
    """Each bit -> two half-bits.

    IEEE 802.3 convention (ieee=True):  1 -> 01 (low->high), 0 -> 10.
    G.E. Thomas convention (ieee=False): 1 -> 10, 0 -> 01.
    """
    b = np.asarray(b, dtype=np.uint8)
    first = (1 - b) if ieee else b
    out = np.empty(2 * len(b), dtype=np.uint8)
    out[0::2], out[1::2] = first, 1 - first
    return out


def manchester_decode(chips, ieee: bool = True) -> tuple[np.ndarray, int]:
    """Half-bit chips -> bits. Returns (bits, number_of_invalid_pairs). Invalid pairs (00/11) decode as 0.

    If errors are high, try the other alignment (chips[1:]) and the other convention.
    """
    c = np.asarray(chips, dtype=np.uint8)
    c = c[: len(c) // 2 * 2]
    a, b = c[0::2], c[1::2]
    bad = int(np.sum(a == b))
    bits_ = (b if ieee else a).astype(np.uint8)
    return bits_, bad


def nrzi_encode(b, start: int = 0) -> np.ndarray:
    """NRZ-I (USB/HDLC style): a 0 toggles the level, a 1 keeps it."""
    out, lvl = [], start
    for v in np.asarray(b):
        if v == 0:
            lvl ^= 1
        out.append(lvl)
    return np.array(out, dtype=np.uint8)


def nrzi_decode(levels, start: int = 0) -> np.ndarray:
    lv = np.concatenate([[start], np.asarray(levels, dtype=np.uint8)])
    return (lv[1:] == lv[:-1]).astype(np.uint8)


def differential_encode(b) -> np.ndarray:
    """d[n] = d[n-1] XOR b[n]; resolves the 180-degree ambiguity of BPSK (DBPSK)."""
    return (np.cumsum(np.asarray(b, dtype=np.int64)) % 2).astype(np.uint8)


def differential_decode(d) -> np.ndarray:
    d = np.asarray(d, dtype=np.uint8)
    return np.concatenate([[d[0]], d[1:] ^ d[:-1]]).astype(np.uint8)


# ----------------------------------------------------------------------------- whitening / scrambling

def pn9(n: int, seed: int = 0x1FF) -> np.ndarray:
    """PN9 sequence (x^9 + x^5 + 1), as used for data whitening by CC1101/CC2500/SX127x FSK modes."""
    out = np.empty(n, dtype=np.uint8)
    s = seed
    for i in range(n):
        out[i] = s & 1
        s = (s >> 1) | (((s ^ (s >> 5)) & 1) << 8)
    return out


def whiten(b, seed: int = 0x1FF) -> np.ndarray:
    """XOR with PN9. The same call un-whitens."""
    b = np.asarray(b, dtype=np.uint8)
    return b ^ pn9(len(b), seed)


# ----------------------------------------------------------------------------- checksums

def crc16_ccitt(data: bytes, init: int = 0xFFFF, poly: int = 0x1021) -> int:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, no reflection, no xorout). check('123456789') = 0x29B1"""
    crc = init
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def crc8(data: bytes, poly: int = 0x07, init: int = 0x00) -> int:
    """CRC-8/SMBUS (poly 0x07). check('123456789') = 0xF4"""
    crc = init
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ poly) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def crc32(data: bytes) -> int:
    import zlib
    return zlib.crc32(data) & 0xFFFFFFFF


def checksum8(data: bytes) -> int:
    """Sum of bytes mod 256 (cheap remotes / sensors)."""
    return sum(data) & 0xFF


# ----------------------------------------------------------------------------- simple packet framing

def frame(payload: bytes, preamble: bytes = DEFAULT_PREAMBLE, sync: bytes = DEFAULT_SYNC,
          length_byte: bool = True, crc: bool = True, whitening: bool = False) -> np.ndarray:
    """Build a typical sub-GHz packet as bits::

        preamble | sync | [len] | payload | [CRC-16/CCITT-FALSE over len+payload, big-endian]

    With whitening=True the len/payload/CRC section is XORed with PN9 (preamble and sync stay clear).
    """
    body = (bytes([len(payload)]) if length_byte else b"") + bytes(payload)
    if crc:
        c = crc16_ccitt(body)
        body += bytes([c >> 8, c & 0xFF])
    body_bits = from_bytes(body)
    if whitening:
        body_bits = whiten(body_bits)
    return np.concatenate([from_bytes(preamble), from_bytes(sync), body_bits]).astype(np.uint8)


def parse_frame(b, sync: bytes = DEFAULT_SYNC, length_byte: bool = True, crc: bool = True,
                whitening: bool = False, max_sync_errors: int = 1, payload_len: int | None = None) -> dict | None:
    """Find the sync word in a bit stream and decode the first packet after it.

    Returns {"start": bit_index, "payload": bytes, "crc_ok": bool|None} or None if no sync found.
    Tries the inverted stream too (FSK/PSK polarity is often unknown) and reports ``inverted``.
    """
    b = np.asarray(b, dtype=np.uint8)
    sw = from_bytes(sync)
    for inverted in (False, True):
        stream = 1 - b if inverted else b
        for idx in find(stream, sw, max_sync_errors):
            body = stream[idx + len(sw):]
            if whitening:
                body = whiten(body)
            if length_byte:
                if len(body) < 8:
                    continue
                n = to_bytes(body[:8])[0]
                total = 1 + n + (2 if crc else 0)
            else:
                n = payload_len if payload_len is not None else (len(body) // 8 - (2 if crc else 0))
                total = n + (2 if crc else 0)
            if len(body) < total * 8:
                continue
            raw = to_bytes(body[: total * 8])
            pl = raw[1:1 + n] if length_byte else raw[:n]
            ok = None
            if crc:
                covered = raw[: len(raw) - 2]
                ok = crc16_ccitt(covered) == int.from_bytes(raw[-2:], "big")
            return {"start": idx, "payload": pl, "crc_ok": ok, "inverted": inverted}
    return None


# ----------------------------------------------------------------------------- Morse

MORSE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.", "G": "--.", "H": "....", "I": "..",
    "J": ".---", "K": "-.-", "L": ".-..", "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-", "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-", "5": ".....", "6": "-....",
    "7": "--...", "8": "---..", "9": "----.", ".": ".-.-.-", ",": "--..--", "?": "..--..", "/": "-..-.",
    "=": "-...-", "+": ".-.-.", "-": "-....-", "@": ".--.-.", "'": ".----.", "!": "-.-.--", "(": "-.--.",
    ")": "-.--.-", ":": "---...", ";": "-.-.-.", '"': ".-..-.", "_": "..--.-", "&": ".-...",
}
MORSE_REV = {v: k for k, v in MORSE.items()}


def morse_units(text: str) -> np.ndarray:
    """Text -> on/off keying in Morse units (dot=1 on, dash=3 on, intra=1 off, letter=3 off, word=7 off)."""
    out: list[int] = []
    for wi, word in enumerate(text.upper().split()):
        if wi:
            out += [0] * 7
        for li, ch in enumerate(word):
            if ch not in MORSE:
                continue
            if li:
                out += [0] * 3
            for si, sym in enumerate(MORSE[ch]):
                if si:
                    out += [0]
                out += [1] if sym == "." else [1, 1, 1]
    return np.array(out, dtype=np.uint8)


def morse_from_runs(runs: list[tuple[int, float]]) -> str:
    """Decode a list of (level, duration) runs (any time unit) into text. The dot length is estimated from the
    shortest on-runs, so the speed does not need to be known."""
    on = sorted(d for lv, d in runs if lv)
    if not on:
        return ""
    dot = float(np.median(on[: max(1, len(on) // 3)]))
    text, sym = "", ""
    for lv, d in runs:
        u = d / dot
        if lv:
            sym += "." if u < 2 else "-"
        else:
            if u >= 5:          # word gap (7)
                text += MORSE_REV.get(sym, "?") if sym else ""
                text += " "
                sym = ""
            elif u >= 2:        # letter gap (3)
                text += MORSE_REV.get(sym, "?") if sym else ""
                sym = ""
    if sym:
        text += MORSE_REV.get(sym, "?")
    return text.strip()
