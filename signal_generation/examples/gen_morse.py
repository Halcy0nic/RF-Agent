"""CW Morse: switch the carrier on and off with PARIS timing, with 5 ms raised-cosine edges."""
import numpy as np

from sdr_helpers import SAMPLE_RATE, pad_silence, raised_cosine_edges, save_cs8, shift_to_offset

MESSAGE = "SDR TEST"
WPM = 18
DOT_S = 1.2 / WPM                       # PARIS: one dot unit = 1.2 / WPM seconds (18 WPM -> 66.7 ms)
MORSE = {"S": "...", "D": "-..", "R": ".-.", "T": "-", "E": "."}


def keying(text: str) -> np.ndarray:
    units = []
    for wi, word in enumerate(text.split()):
        if wi:
            units += [0] * 7                         # word gap = 7 units
        for li, ch in enumerate(word):
            if li:
                units += [0] * 3                     # letter gap = 3 units
            for si, sym in enumerate(MORSE[ch]):
                if si:
                    units += [0]                     # gap inside a letter = 1 unit
                units += [1] if sym == "." else [1, 1, 1]
    return np.array(units, dtype=np.float32)


envelope = np.repeat(keying(MESSAGE), int(DOT_S * SAMPLE_RATE))   # symbols -> samples
envelope = raised_cosine_edges(envelope, 0.005)                   # remove key clicks
save_cs8(pad_silence(shift_to_offset(envelope.astype(np.complex64))), "morse.cs8")
