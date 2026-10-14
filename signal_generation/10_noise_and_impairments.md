# 10 · Noise and impairments: realistic test signals

A decoder that only ever sees perfect signals will fail on its first real capture. Generate the problems
on purpose.

## AWGN at a chosen SNR

```python
from rfkit import mod
y = mod.awgn(x, snr_db=10)            # complex white Gaussian noise
```

`mod.awgn` measures the signal power over the **non-silent** samples (so padding doesn't dilute it), and
the SNR is defined **over the full sample-rate bandwidth**. The SNR a receiver sees after filtering to the
signal's bandwidth B is higher by 10·log10(fs / B):

| fs | Signal BW | Full-band SNR 0 dB → in-band SNR |
|---|---|---|
| 2 MS/s | 50 kHz (2-FSK) | +16 dB |
| 2 MS/s | 3 kHz (OOK 1 kbit/s) | +28 dB |
| 2 MS/s | 67.5 kHz (QPSK 50 kBd) | +14.7 dB |

So `generate.py ... --snr 0` still decodes cleanly for narrow signals. Use `rfkit.dsp.snr_db(x, fs,
signal_bw_hz, center_hz)` to measure in-band SNR on a capture. Eb/N0 = SNR_in-band + 10·log10(B / bit_rate).

Don't add noise to files you'll **transmit**. The air adds plenty, and noise wastes 8-bit dynamic range.
Use `--snr` for software tests and datasets only.

## Front-end and channel impairments

```python
y = mod.impair(x, fs,
               cfo_hz=2_200,        # crystal error (bench: +2.2 kHz at 434 MHz)
               phase_rad=1.0,       # unknown carrier phase (PSK ambiguity)
               delay_samples=137,   # unknown start time
               iq_gain_db=0.5,      # IQ amplitude imbalance -> image at -f
               iq_phase_deg=3,      # IQ phase imbalance
               dc=0.02 + 0.01j,     # DC offset -> spike at 0 Hz
               sro_ppm=20)          # sample-rate offset: symbol timing drifts
```

| Impairment | What it breaks | What the receiver needs |
|---|---|---|
| Carrier frequency offset (CFO) | Narrow filters miss the signal; PSK constellations spin | Search ±(ppm × f) and track (FFT peak, x^M, Costas) |
| Phase offset | Absolute-phase PSK decisions | Sync word / differential coding |
| Timing offset / delay | Where bits start | Preamble + sync search, clock recovery |
| Sample-rate offset | Long packets slip bits | PLL slicer (`dsp.slice_symbols_pll`), re-estimate rate |
| IQ imbalance | Image at −f (a ghost), constellation ellipse | Avoid symmetric placements, IQ correction |
| DC offset | Spike at 0 Hz, OOK threshold bias | Offset tuning, `dsp.dc_block` |
| Clipping / saturation | Harmonics, splatter, AM-AM distortion | Lower gain / back-off |
| Multipath | Frequency-selective fading, ISI | Equaliser, OFDM cyclic prefix |
| Interference | Strong neighbours, intermod | Filtering, gain discipline |

Multipath in two lines:

```python
h = np.array([1.0, 0, 0, 0.5 * np.exp(1j * 0.7), 0, 0.2])      # direct path + two echoes
y = np.convolve(x, h)[: len(x)]
```

## Building a decoder test matrix

```python
from rfkit import bits, mod, dsp
rng = np.random.default_rng(0)
for snr in (20, 10, 5, 0, -3):
    for cfo in (0, 2e3, 10e3):
        y = mod.awgn(mod.impair(x, fs, cfo_hz=cfo, phase_rad=rng.uniform(0, 6.28)), snr, rng)
        ok = decode(y)            # your receiver
        print(snr, cfo, ok)
```

`tests/test_loopback.py` uses this pattern: +2 kHz CFO, a random phase, a 137-sample delay and 10–20 dB
SNR for every modulation.

## Classic test signals

| Signal | How | Shows |
|---|---|---|
| Single tone | `mod.tone` | Frequency error, phase noise, spurs, image |
| Two-tone (close spacing) | `mod.multitone([f1, f2])` | Intermodulation (3rd-order products at 2f1−f2, 2f2−f1) |
| Slow sweep | `mod.chirp` over the whole band | Receiver passband shape, notches |
| Band-limited noise | `generate.py noise --bw 200e3` | Filter shape (noise shows the passband), noise-loading tests |
| Pulse train | `mod.repeat_burst(tone, N, gap)` | AGC behaviour, burst detection |
| PRBS data | `rng.integers(0, 2, N)` through any modulator | BER testing |
