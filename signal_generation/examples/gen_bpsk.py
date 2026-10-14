"""BPSK packet with root-raised-cosine pulse shaping: bit 0 -> +1, bit 1 -> -1 (180 degree phase flip)."""
import numpy as np

from sdr_helpers import SAMPLE_RATE, bytes_to_bits, packet, pad_silence, save_cs8, shift_to_offset

SYMBOL_RATE = 50_000
SPS = SAMPLE_RATE // SYMBOL_RATE                    # 40 samples per symbol
BETA = 0.35                                         # roll-off: occupied BW ~= 50 kHz * 1.35 = 67.5 kHz


def rrc(sps: int, beta: float, span: int = 10) -> np.ndarray:
    t = np.arange(-span * sps // 2, span * sps // 2 + 1) / sps
    h = np.empty_like(t)
    for i, ti in enumerate(t):
        if ti == 0:
            h[i] = 1 + beta * (4 / np.pi - 1)
        elif abs(abs(4 * beta * ti) - 1) < 1e-9:
            h[i] = beta / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * beta))
                                        + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            h[i] = (np.sin(np.pi * ti * (1 - beta)) + 4 * beta * ti * np.cos(np.pi * ti * (1 + beta))) / \
                   (np.pi * ti * (1 - (4 * beta * ti) ** 2))
    return h / np.sqrt(np.sum(h ** 2))


# a longer preamble gives the receiver's carrier/timing loops time to lock
payload_bits = bytes_to_bits(b"\xaa" * 6 + packet(b"PING 42"))
symbols = 1.0 - 2.0 * payload_bits                  # 0 -> +1, 1 -> -1
impulses = np.zeros(len(symbols) * SPS)
impulses[::SPS] = symbols                           # one impulse per symbol, zeros between
baseband = np.convolve(impulses, rrc(SPS, BETA), mode="full")    # pulse shaping
burst = shift_to_offset(baseband.astype(np.complex64))
gap = np.zeros(int(0.1 * SAMPLE_RATE), dtype=np.complex64)
save_cs8(pad_silence(np.concatenate([burst, gap, burst, gap, burst])), "bpsk.cs8")
