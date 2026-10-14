"""Continuous-phase 2-FSK packet: describe the frequency at every sample, integrate it (cumsum) for phase."""
import numpy as np

from sdr_helpers import OFFSET_HZ, SAMPLE_RATE, bytes_to_bits, packet, pad_silence, save_cs8

BIT_RATE = 5_000
DEVIATION_HZ = 20_000                               # 1 -> +20 kHz, 0 -> -20 kHz around the offset

bits = bytes_to_bits(packet(b"PING 42"))
symbols = 2.0 * bits - 1.0                          # 0/1 -> -1/+1
freq = OFFSET_HZ + DEVIATION_HZ * np.repeat(symbols, SAMPLE_RATE // BIT_RATE)    # Hz at every sample
phase = 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE   # integrate frequency -> continuous phase, no jumps
burst = np.exp(1j * phase).astype(np.complex64)

ramp = np.hanning(800)                              # constant envelope: only taper the burst ends
burst[:400] *= ramp[:400]
burst[-400:] *= ramp[400:]
gap = np.zeros(int(0.2 * SAMPLE_RATE), dtype=np.complex64)
save_cs8(pad_silence(np.concatenate([burst, gap, burst, gap, burst])), "2fsk.cs8")
