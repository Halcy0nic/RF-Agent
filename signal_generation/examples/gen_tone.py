"""A pure carrier: the "hello world" of SDR. One line of NumPy: exp(j*2*pi*f*t)."""
import numpy as np

from sdr_helpers import OFFSET_HZ, SAMPLE_RATE, save_cs8

DURATION_S = 2.0
t = np.arange(int(DURATION_S * SAMPLE_RATE)) / SAMPLE_RATE
iq = np.exp(2j * np.pi * OFFSET_HZ * t)          # cos(2*pi*f*t) + j*sin(2*pi*f*t), spinning at +100 kHz
save_cs8(iq, "tone.cs8")
