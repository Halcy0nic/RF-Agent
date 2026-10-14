# 01 · IQ fundamentals

## What an SDR actually sends

An SDR transmitter doesn't take "a waveform at 433.92 MHz". It takes a stream of **complex baseband
samples** at a fixed **sample rate** *fs*, and its hardware mixes them up to the RF centre frequency *fc*.
Each sample is

```text
x[n] = I[n] + j·Q[n]          (I = in-phase / real part, Q = quadrature / imaginary part)
```

and the RF output is (ignoring scaling) `Re{ x(t) · e^(j·2π·fc·t) } = I(t)·cos(2π·fc·t) − Q(t)·sin(2π·fc·t)`.

Because x is complex, it can describe **amplitude and phase** at once, and can contain energy at **negative
frequencies**. A baseband tone at +100 kHz lands at fc + 100 kHz. One at −100 kHz lands at fc − 100 kHz.
A real-valued baseband signal (Q = 0) is always symmetric about 0 Hz. That's why AM from a real envelope
shows both sidebands.

```python
import numpy as np
fs = 2_000_000
t = np.arange(20) / fs
x = np.exp(2j * np.pi * 100e3 * t)      # = cos(2π·100k·t) + j·sin(2π·100k·t): 20 samples per cycle
```

The phasor `e^(jθ)` spins counter-clockwise for positive frequency and clockwise for negative. At
100 kHz and 2 MS/s it advances 2π·100e3/2e6 = 0.314 rad (18°) per sample.

## Sample rate = visible bandwidth (complex Nyquist)

With complex samples you can represent any frequency in **[−fs/2, +fs/2)**. Anything you put outside that
range aliases (wraps around): a tone at +1.1 MHz generated at 2 MS/s appears at −0.9 MHz. So:

- Pick *fs* comfortably larger than the signal's occupied bandwidth plus its offset:
  `fs > 2·(|offset| + bandwidth/2)` with margin. The hardware's anti-alias filters roll off near ±fs/2.
- Bit and symbol timing come from samples per symbol: `sps = fs / symbol_rate`. Keep it an integer.
- Duration is `N / fs`. File size is `N × bytes_per_sample`.

| Rate | Sample period | 1 s of CS8 | Notes |
|---|---|---|---|
| 2 MS/s | 0.5 µs | 4 MB | Lowest HackRF rate. Plenty for anything under ~1 MHz wide |
| 8 MS/s | 125 ns | 16 MB | |
| 20 MS/s | 50 ns | 40 MB | HackRF max |

## File formats

| Format | Element | Zero | Full scale | Bytes/sample | Tool |
|---|---|---|---|---|---|
| **CS8** | int8 I, int8 Q | 0 | ±127 | 2 | `hackrf_transfer` (TX and RX) |
| **CU8** | uint8 I, uint8 Q | 127.5 | 0 / 255 | 2 | `rtl_sdr` |
| **CS16** | int16 I, int16 Q | 0 | ±32767 | 4 | `rtl_fm -M raw`, UHD `--type short`, SDR++ WAV data |
| **CF32** (= `.cfile`, `.fc32`) | float32 I, float32 Q | 0 | ±1.0 | 8 | GNU Radio, UHD `--type float`, NumPy `complex64` |
| **WAV (IQ)** | 2-channel PCM, ch0 = I, ch1 = Q | | | 4 (int16) | SDR++ / SDR# recorders |
| **SigMF** | `.sigmf-data` (any above) + `.sigmf-meta` JSON | | | | Interchange with metadata (rate, centre, annotations) |

None of the raw formats has a header. **The sample rate and centre frequency live only in your head or in
the file name**, so name files like `ook_433.92M_2M.cs8`, or use SigMF/WAV.

Writing CS8 by hand (what `hackrf_transfer -t` plays):

```python
def save_cs8(iq, path, peak=100):
    iq = iq / np.max(np.abs(iq)) * peak                  # normalise to ±peak of ±127: headroom, no clipping
    out = np.empty(2 * len(iq), dtype=np.int8)
    out[0::2] = np.clip(np.round(iq.real), -127, 127)    # I0 Q0 I1 Q1 ...
    out[1::2] = np.clip(np.round(iq.imag), -127, 127)
    out.tofile(path)
```

Reading any of them (the `view` trick: interleaved float32 pairs *are* complex64 in memory):

```python
x = np.fromfile("a.cs8", np.int8).astype(np.float32).view(np.complex64) / 128
x = ((np.fromfile("a.cu8", np.uint8).astype(np.float32) - 127.5) / 127.5).view(np.complex64)
x = np.fromfile("a.cs16", np.int16).astype(np.float32).view(np.complex64) / 32768
x = np.fromfile("a.cf32", np.complex64)
```

Or with rfkit, which also handles WAV and SigMF and can read just a slice:

```python
from rfkit import iq
x, fs = iq.load("baseband_433920000Hz_12-50-01_14-10-2026.wav")         # SDR++: fs from the header
x, _ = iq.load("capture.cu8", fs=2.048e6, offset_s=1.0, seconds=0.5)     # raw: you supply fs
iq.save("signal.cs8", x)                    # peak=0.8 default (80 % of full scale)
iq.save("signal.sigmf-data", x, fs=2e6, center_hz=433.92e6, description="test burst")
```

## 8-bit quantisation and dynamic range

CS8 has 255 levels, which gives about 6 dB per bit × 8 ≈ 48 dB of dynamic range at best. Consequences:

- A weak signal next to a strong one in the same file loses resolution. Generate one signal per file, or
  mind the level ratio.
- Peaky waveforms (OFDM, many tones, QAM) must be backed off further so their peaks don't clip, which
  costs average power.
- Leave the silence between bursts as exact zeros. It quantises to 0 and costs nothing.

## Checklist before transmitting a file

```bash
.venv/bin/python tools/iq_inspect.py signal.cs8 --fs 2e6 --center 433.92e6
```

Check: duration as expected; `clipped_fraction` 0; the strongest signal at the intended offset; occupied
bandwidth as expected; nothing near ±fs/2.
