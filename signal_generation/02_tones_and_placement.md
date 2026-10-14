# 02 · Tones and frequency placement

## One tone

```python
import numpy as np
from rfkit import iq
fs, f, seconds = 2_000_000, 100e3, 2.0
t = np.arange(int(seconds * fs)) / fs
x = np.exp(2j * np.pi * f * t)
iq.save("tone.cs8", x)
```

```bash
.venv/bin/python signal_generation/generate.py tone --offset 100e3 --seconds 2 -o tone.cs8
gtimeout 10 hackrf_transfer -t tone.cs8 -f 433920000 -s 2000000 -x 20 -a 0
```

Over the air on this bench, that tone arrived at **+102.18 kHz** with 53.5 dB SNR on the RTL-SDR. The
2.18 kHz error is the combined crystal error of the two radios (~5 ppm at 434 MHz). That's normal, and
receivers should search for it.

## Placing any signal: shift by multiplication

Build every signal around 0 Hz, then multiply by a complex exponential:

```python
def shift(x, offset_hz, fs):
    n = np.arange(len(x))
    return x * np.exp(2j * np.pi * offset_hz * n / fs)
```

Multiplying in time = shifting in frequency (the modulation theorem). Multiplying by `exp(−j…)` shifts
down. This is also how a receiver **brings a signal back to 0 Hz** before filtering
(`rfkit.dsp.channelize`).

### Why offset from the centre at all?

At exactly the tuned frequency, transmitters leak their local oscillator and receivers see their own DC
offset (the "DC spike"). Measured here with a +100 kHz offset: centre leakage was 48–58 dB below the signal,
and the IQ-imbalance **image** at −100 kHz was 51–57 dB below. Rules of thumb:

- Offset 50–200 kHz (more for wide signals). Use the same offset on TX and RX so they cancel.
- Never place two signals symmetric about 0 Hz (±f). Each one's image lands on the other.
- Keep the whole occupied band inside ±0.4·fs.

## Phase continuity

Concatenating tones at different frequencies, each starting at phase 0, creates **phase jumps** at the
joins. They splatter. Carry the phase forward instead:

```python
def tone_sequence(freqs, seg_s, fs):
    phase, out = 0.0, []
    n = int(seg_s * fs)
    for f in freqs:
        ph = phase + 2 * np.pi * f * np.arange(1, n + 1) / fs
        out.append(np.exp(1j * ph))
        phase = ph[-1]
    return np.concatenate(out)
```

Even simpler: describe the instantaneous frequency of every sample and integrate it (`np.cumsum`). This is
exactly how FSK and FM are built in guides 04 and 06.

## Several tones at once

```python
from rfkit import mod
x = mod.multitone([-200e3, 50e3, 120e3], 1.0, 2e6)      # random start phases keep peaks low
```

Summing N equal tones raises the peak-to-average power ratio (PAPR) up to 10·log10(N) dB. Random phases
reduce it, but you still need back-off (guide 01). `rfkit.dsp.papr_db(x)` reports it.

## Frequency resolution: how close can two tones be?

On the receive side an FFT of N samples has bin width `fs / N`. To separate tones Δf apart you need
`N ≳ 2·fs/Δf` samples (with a window). At 1.024 MS/s, 8192-point FFTs give 125 Hz bins: fine for FSK tones
kHz apart, too coarse for CW tones 50 Hz apart.

## Sweeps and steps (useful test signals)

```python
x = mod.chirp(-400e3, 400e3, 0.5, 2e6)          # linear sweep: shows the receiver's passband shape
```

A slow sweep across the band, received on another radio, gives that radio's frequency response
(filter roll-off, notches, spurs) in one capture.

## CW without a file

```bash
gtimeout 5 hackrf_transfer -c 100 -f 433920000 -s 2000000 -x 10 -a 0
```

`-c` makes the HackRF transmit a constant DC value, which appears as a carrier at exactly `-f`. Handy for
ppm calibration of a receiver.
