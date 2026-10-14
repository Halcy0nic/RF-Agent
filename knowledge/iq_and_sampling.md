# IQ and sampling

## Complex baseband in one paragraph

An SDR mixes the RF band around its tuned frequency fc down to 0 Hz with two local oscillators 90° apart,
giving two real streams: I (in-phase, cos) and Q (quadrature, −sin). Together, x = I + jQ is a complex
signal whose spectrum from −fs/2 to +fs/2 is an exact copy of the RF spectrum from fc − fs/2 to
fc + fs/2. **Positive baseband frequency = above fc; negative = below.** Magnitude |x| is the envelope
(AM), angle ∠x is the phase (PM), and the rate of change of the angle is the instantaneous frequency (FM).

```python
amplitude = np.abs(x)
phase     = np.angle(x)                                  # radians, wrapped to (-π, π]
inst_freq = np.angle(x[1:] * np.conj(x[:-1])) * fs / (2 * np.pi)   # Hz (FM discriminator)
```

## Nyquist for complex samples

- Complex sampling at fs captures a band **fs wide** (−fs/2 … +fs/2). A real ADC at fs captures only
  fs/2.
- A frequency f outside that range **aliases** to f − k·fs. E.g. a 1.2 MHz tone in a 2 MS/s capture shows
  at −0.8 MHz.
- Real hardware has anti-alias filters that roll off near the edges. Trust the middle ~80 % of the span.
  Strong signals just outside the span can still alias in, attenuated, and look like real signals.

## Choosing a sample rate

| Need | Rule |
|---|---|
| See a signal of width B at offset f0 | fs ≥ 2·(|f0| + B/2) × 1.25 |
| Demodulate a signal of width B | Channelise to fs₂ ≈ 2–4 × B (plenty of room for the filter) |
| Integer samples per symbol | fs = k × symbol_rate (k ≥ 4 for slicing, ≥ 8 for nice eye diagrams) |
| Small files | The lowest rate that satisfies the above (RTL: 250k, 1.024M; HackRF: 2M) |

## Artefacts every capture has

| Artefact | Where | Cause | Handling |
|---|---|---|---|
| **DC spike** | Exactly 0 Hz | ADC/mixer DC offset, LO leakage | Offset-tune; `x - x.mean()`; `exclude_dc_hz` in `dsp.find_carriers` |
| **IQ image** | −f for every signal at +f | Gain/phase mismatch between I and Q | Typically −40 to −60 dBc (≈ −51 to −57 dB measured on this bench). SDR++ "IQ correction" |
| **Roll-off** | Span edges | Anti-alias filter | Keep targets central |
| **Spurs** | Fixed offsets | Clocks, USB, mixer products | Map them with no antenna; they don't move with the antenna |
| **Settling transient** | First ms after start/retune | PLL lock, AGC, filter warm-up | Skip the first ~50 ms (`rx_decode.py --skip`) |
| **Dropped samples** | Random gaps | USB/CPU too slow | Lower the rate; `hackrf_transfer -B`; UHD prints `O` |

## Inverted spectrum

If I and Q are swapped (or Q negated), the spectrum is mirrored: +f appears at −f, and LSB/USB swap.
FSK polarity flips. Images painted in the waterfall are mirrored. Fix with `x = np.conj(x)` or SDR++'s
"Invert IQ".

## File formats

| Format | dtype | Zero | Bytes/sample | Typical source | Load |
|---|---|---|---|---|---|
| CS8 | int8 I,Q | 0 | 2 | HackRF | `np.fromfile(p, np.int8).astype(np.float32).view(np.complex64)/128` |
| CU8 | uint8 I,Q | 127.5 | 2 | rtl_sdr | `((np.fromfile(p, np.uint8)-127.5)/127.5).astype(np.float32).view(np.complex64)` |
| CS16 | int16 I,Q | 0 | 4 | UHD short, rtl_fm raw | `np.fromfile(p, np.int16).astype(np.float32).view(np.complex64)/32768` |
| CF32 | float32 I,Q | 0 | 8 | GNU Radio, UHD float | `np.fromfile(p, np.complex64)` |
| WAV IQ | 2-ch int16/float | 0 | 4/8 | SDR++, SDR# | `rfkit.iq.load(p)` |
| SigMF | any + JSON | | | Interchange | `rfkit.iq.load(p.sigmf-data)` |

`rfkit.iq.load(path, fs=..., offset_s=..., seconds=...)` handles all of them and reads slices without
loading whole files. File names carry metadata by convention: SDR++ `baseband_<Hz>Hz_<time>_<date>.wav`;
SDR# `SDRSharp_<date>_<time>Z_<Hz>Hz_IQ.wav`; HackRF `-w` `HackRF_<date>_<time>Z_<kHz>kHz_IQ.wav`; rtl_433
`g001_433.92M_250k.cu8`. `rfkit.iq.info_from_name()` extracts the frequency.

## Data rates

| Rate | CS8/CU8 | CS16 / SDR++ WAV | CF32 |
|---|---|---|---|
| 250 kS/s | 0.5 MB/s | 1 MB/s | 2 MB/s |
| 1.024 MS/s | 2 MB/s | 4.1 MB/s | 8.2 MB/s |
| 2.048 MS/s | 4.1 MB/s | 8.2 MB/s | 16.4 MB/s |
| 8 MS/s | 16 MB/s | 32 MB/s | 64 MB/s |
| 20 MS/s | 40 MB/s | 80 MB/s | 160 MB/s |

Record **seconds, not minutes**: 5–15 s captures are enough for almost any analysis, and you can replay
them forever offline.

## Changing rates and centres offline

```python
from rfkit import dsp
y, fs2 = dsp.channelize(x, fs, center_hz=+125e3, bw_hz=50e3)   # mix to 0, low-pass, decimate
y, fs2 = dsp.decimate(x, 4, fs)                                  # anti-alias + keep every 4th sample
```

Changing to a non-integer rate: interpolate (`np.interp` on I and Q, see `tools/rx_decode.py psk`) or use
`scipy.signal.resample_poly(x, up, down)`.
