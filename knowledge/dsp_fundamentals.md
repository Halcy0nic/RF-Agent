# DSP fundamentals for RF work

The handful of operations that do 95 % of the work: **FFT/PSD, spectrogram, mixing, filtering,
decimation, detection (envelope, discriminator), correlation.** All are in `rfkit.dsp`, NumPy only.

## What an SDR is, in DSP terms

A traditional radio hard-wires one demodulator. An SDR delivers raw IQ (see
[iq_and_sampling.md](iq_and_sampling.md)), and tuning, filtering, demodulation and decoding all happen in
code. One recording can be demodulated as many ways as you like, so **record IQ first, then experiment
offline.**

## The FFT

`np.fft.fft(x[:N])` turns N time samples into N frequency bins spaced **fs/N** apart. For complex IQ,
`np.fft.fftshift` puts −fs/2 on the left and +fs/2 on the right.

| Parameter | Effect |
|---|---|
| N (FFT size) | Resolution fs/N. Bigger N = finer frequency detail but a longer time window (N/fs s) |
| Window | Trades main-lobe width for sidelobe level. **Hann** = good default (−31 dB sidelobes). **Blackman** = −58 dB for strong+weak signals. Rectangular = sharpest but −13 dB sidelobes: leakage hides weak signals |
| Averaging (Welch) | Averaging K windows cuts the noise variance by K, so the floor gets smoother and weak carriers show. Doesn't improve resolution |
| Zero padding | Interpolates the spectrum (prettier peaks). Adds no resolution |

```python
f, p_db = dsp.psd(x, fs, nfft=8192)              # Welch, Hann, 50 % overlap, fftshifted, dB
peaks = dsp.find_carriers(x, fs, exclude_dc_hz=5e3)   # freq (sub-bin interpolated), SNR, bandwidths
```

**Frequency estimation** better than one bin: fit a parabola through the peak bin and its neighbours
(`find_carriers` does this), or zero-pad a long FFT. For carriers hidden in modulation: FFT of x² (BPSK)
or x⁴ (QPSK) shows a line at 2× / 4× the offset (`dsp.estimate_cfo(x, fs, power=M)`).

## Spectrogram / waterfall

Slide an FFT along the signal: `dsp.spectrogram(x, fs, nfft, hop)` returns S[time, freq].

- Time resolution = hop / fs. Frequency resolution = fs / nfft. **You can't have both** (the uncertainty
  principle). Short bursts need a small nfft. Close tones need a large nfft.
- Rule of thumb for packets: nfft ≈ fs / (4 × symbol_rate) shows individual FSK symbols.
- `rfkit.plot.overview()` draws PSD + waterfall + |x| in one PNG, the first thing to look at.

## Mixing (frequency shifting)

```python
y = x * np.exp(-2j * np.pi * f0 * np.arange(len(x)) / fs)     # moves f0 down to 0 Hz
```

This is how you "tune" inside a recording. Complex mixing moves the spectrum without creating an image
(real mixing creates both sum and difference).

## Filtering

| Filter | Use | rfkit |
|---|---|---|
| FIR low-pass (windowed sinc) | Channel selection, anti-aliasing, post-detection smoothing. Linear phase | `dsp.lowpass(x, cutoff, fs)`, `dsp.firwin_lowpass` |
| Moving average | Cheap low-pass; envelope smoothing; integrate-and-dump matched filter for rectangular symbols | `dsp.moving_average` |
| Matched filter | Maximises SNR for a known pulse shape: correlate with the pulse (RRC for PSK) | `dsp.matched_filter_rrc` |
| DC block | Remove the DC spike / offset | `dsp.dc_block` |
| IIR one-pole | De-emphasis, AGC | in `dsp.fm_demod` |

FIR taps needed ≈ 4 / (transition width / fs). A 1 kHz-sharp filter at 2 MS/s needs ~8000 taps, so
**decimate first, then filter narrowly** at the low rate. `rfkit` filters long signals with FFT convolution
(`dsp.fftconvolve_same`), which matters: a 10,000-tap `np.convolve` on 5 M samples took 36 s versus
under 1 s with FFT convolution.

## Decimation and channelisation

```python
y, fs2 = dsp.channelize(x, fs, center_hz=f0, bw_hz=B)   # mix f0→0, low-pass B/2, decimate to ≥ 2.5·B
```

Always low-pass before discarding samples, or everything outside the new band aliases in.

## Detectors

| Detector | Output | For |
|---|---|---|
| Envelope `|x|` | Amplitude | AM, OOK, ASK, bursts |
| Power `|x|²`, in dB | Energy | Burst detection, squelch |
| Phase `angle(x)` | Radians | PSK (after carrier recovery), PM |
| Discriminator `angle(x[n]·x*[n−1])·fs/2π` | Hz | FM, FSK, chirps |
| Analytic-signal tricks | SSB | `mod.ssb`, Hilbert |

## Correlation: finding known things

Cross-correlating with a known pattern (preamble, sync word, chirp, Barker code) gives a peak where it
occurs: `np.correlate(signal, pattern, "valid")`. On bits, `rfkit.bits.find(stream, pattern,
max_errors)` does this with ±1 mapping and tolerates bit errors. Autocorrelation of a signal shows its
periodicity (symbol period, repetition interval, OFDM cyclic prefix).

## Thresholds and statistics

- **Otsu's method** (`dsp.otsu_threshold`) splits a two-level signal (OOK envelope, FSK discriminator)
  by maximising between-class variance. rfkit returns the midpoint of the two class means.
  **Don't use 0 or the median as an FSK threshold**: a carrier offset or a 1/0 imbalance shifts the
  right value, and on this bench the median put the threshold on one tone and halved the decoded rate.
- Noise floor estimate: a low percentile (20th) of the PSD in dB (`dsp.noise_floor_db`).
- Burst detection: smooth |x|², threshold halfway (in dB) between floor and peak, merge short gaps
  (`dsp.bursts`). Merge gaps longer than the longest run of zero bits for OOK.
- Time-gate before spectral analysis of bursty captures (`dsp.gate`). A 1 ms packet in a 1 s file is
  diluted ~30 dB in a time-averaged PSD.

## Symbol timing

1. **Estimate the rate**: run lengths between threshold crossings are integer multiples of the symbol
   period. Take the short-run cluster, then least-squares refine (`dsp.estimate_symbol_rate`). Or look
   at the spectrum of |d/dt metric|, which has a line at the symbol rate.
2. **Sample**: integrate-and-dump over each symbol, choose the phase with the largest spread
   (`dsp.slice_symbols`). Or, better for long packets and imperfect rate estimates, **track the clock
   on every transition** (`dsp.slice_symbols_pll`, a simple digital PLL). Verified here: with a 1.5 %
   rate error, the fixed clock slipped bits within a 450-bit packet, and the PLL slicer decoded it.
3. For PSK: matched filter, then pick the max-energy phase (`dsp.best_timing`), or Gardner/Mueller-Müller
   loops for continuous tracking.

## Carrier recovery (PSK/QAM)

Coarse: M-th power FFT (`estimate_cfo(x, fs, power=M)`). Fine: a Costas loop on symbol-rate samples
(`dsp.costas(symbols, order)`). Then resolve the M-fold phase ambiguity with a known sync word or
differential coding.

## Measurements

| Want | Use |
|---|---|
| Carrier frequency | `find_carriers` (sub-bin), `estimate_cfo` |
| Occupied bandwidth (99 %) | `dsp.occupied_bandwidth` |
| In-band SNR | `dsp.snr_db(x, fs, signal_bw_hz, center_hz)` |
| PAPR | `dsp.papr_db` |
| Burst timing | `dsp.bursts` → start/end samples |
| Clipping | fraction of |I| or |Q| ≥ 0.99 FS (`tools/iq_inspect.py`) |
