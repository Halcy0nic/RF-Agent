# 08 · Chirps, spread spectrum and OFDM

These are the "boss level" waveforms. You won't build a standards-compliant LoRa or Wi-Fi transmitter in a
page, but you can build signals with the right *structure*: for receiver testing, classifier datasets and
learning what they look like.

## Linear chirps

Frequency ramps linearly from f0 to f1 over T seconds. Phase is the integral:
φ(t) = 2π(f0·t + ½·k·t²), with k = (f1 − f0)/T.

```python
from rfkit import mod
c = mod.chirp(-200e3, 200e3, 0.01, fs)        # 10 ms up-chirp across 400 kHz
x = mod.repeat_burst(c, 20, 0.01, fs)          # radar-like pulse train
```

```bash
.venv/bin/python signal_generation/generate.py chirp --f0 -200e3 --f1 200e3 --seconds 0.01 --repeat 20 --gap 0.01 -o chirp.cs8
```

Waterfall: diagonal lines. Radar uses chirps (pulse compression: a matched filter squeezes a long chirp
into a sharp peak), as do sounders and LoRa.

## Chirp spread spectrum (LoRa-style)

LoRa sends each symbol as an up-chirp across bandwidth BW, cyclically shifted by the symbol value (0 …
2^SF − 1). Spreading factor SF = 7–12 sets chips per symbol (2^SF) and the symbol time 2^SF / BW.

```python
s = mod.css_symbol(value=42, sf=7, bw=125e3, fs=500e3)             # one symbol (fs must be k·BW)
frame = mod.css_frame([1, 2, 3, 100], sf=7, bw=125e3, fs=500e3)    # 8 up-chirps, 2.25 down-chirps, data
```

```bash
.venv/bin/python signal_generation/generate.py css --sf 7 --bw 125e3 --values 1,2,3,100 --fs 2e6 -o css.cs8
```

| SF | Symbol time at BW 125 kHz | Raw bit rate (SF bits / symbol) |
|---|---|---|
| 7 | 1.024 ms | ~6.8 kbit/s |
| 9 | 4.096 ms | ~2.2 kbit/s |
| 12 | 32.8 ms | ~366 bit/s |

**Receiving it:** multiply by a down-chirp ("de-chirp"). Each symbol collapses to a single tone whose FFT
bin is the symbol value. That's why LoRa works far below the noise floor.

Limits: this is the physical-layer shape only. Real LoRa adds whitening, Hamming FEC, diagonal
interleaving, Gray mapping, a header and CRC. Off-the-shelf LoRa receivers (`gr-lora_sdr`, SX127x chips)
won't decode it. It is ideal for teaching, waterfall recognition and de-chirp exercises.

## DSSS (direct-sequence spread spectrum)

Multiply each bit by a fast pseudo-random chip sequence. The signal spreads over chip_rate bandwidth. The
receiver correlates with the same sequence (despreading), gaining 10·log10(chips per bit) dB of
processing gain.

```python
x = mod.dsss(bits_, mod.BARKER_11, fs, chip_rate=1e6)      # 802.11b-style Barker-11
```

Barker codes (lengths 2, 3, 4, 5, 7, 11, 13) have the lowest possible autocorrelation sidelobes, which
also makes them good sync words. GPS uses 1023-chip Gold codes at 1.023 Mchip/s.

## OFDM (toy)

Put data symbols on many narrow subcarriers at once with an IFFT, and prepend a cyclic prefix so
multipath echoes don't smear symbols together:

```python
x = mod.ofdm(bits_, n_fft=64, cp=16, n_used=48, scheme="qpsk")   # 802.11a-like numerology
# subcarrier spacing = fs / n_fft (fs = 2 MS/s -> 31.25 kHz; 48 used -> 1.5 MHz occupied)
```

Waterfall: a flat rectangular block with sharp edges. Watch the **PAPR** (`dsp.papr_db(x)`, often
10–12 dB): back the level off so peaks don't clip in an 8-bit DAC. Clipped OFDM grows "shoulders" either
side of the block.

Real OFDM systems add pilots, preambles (802.11 short/long training fields), channel estimation and coding.
`mod.ofdm` is the bare mechanism.

## Frequency hopping

Hop a narrowband signal between channels. Just concatenate bursts shifted to different offsets:

```python
hops = [-300e3, 120e3, -50e3, 280e3]
x = mod.concat(*[mod.shift(burst, f, fs) for f in hops])
```

Bluetooth Classic hops 1600 times per second over 79 × 1 MHz channels. That's far wider than one SDR
capture, which is why sniffing it needs special hardware.
