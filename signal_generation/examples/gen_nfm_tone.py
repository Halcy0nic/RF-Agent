"""Narrow-band FM carrying a two-tone audio signal (listen to it in SDR++ NFM mode)."""
import numpy as np

from sdr_helpers import OFFSET_HZ, SAMPLE_RATE, pad_silence, save_cs8

DEVIATION_HZ = 5_000                                # NFM voice: 2.5-5 kHz peak deviation
DURATION_S = 3.0
t = np.arange(int(DURATION_S * SAMPLE_RATE)) / SAMPLE_RATE
audio = 0.5 * np.sin(2 * np.pi * 700 * t) + 0.5 * np.sin(2 * np.pi * 1_200 * t)   # in [-1, 1]
freq = OFFSET_HZ + DEVIATION_HZ * audio             # instantaneous frequency follows the audio
iq = np.exp(1j * 2 * np.pi * np.cumsum(freq) / SAMPLE_RATE)
save_cs8(pad_silence(iq), "nfm_two_tone.cs8")
