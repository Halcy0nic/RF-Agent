# RF fundamentals

## Decibels

| Quantity | Formula | Remember |
|---|---|---|
| Power ratio | dB = 10·log10(P2/P1) | +3 dB = ×2, +10 dB = ×10, +20 dB = ×100 |
| Voltage/amplitude ratio | dB = 20·log10(V2/V1) | ×2 amplitude = +6 dB |
| Absolute power | dBm = 10·log10(P / 1 mW) | 0 dBm = 1 mW; +30 dBm = 1 W; +20 dBm = 100 mW; −30 dBm = 1 µW; −100 dBm = 0.1 pW |
| Relative to carrier | dBc | "spur at −50 dBc" = 50 dB below the wanted signal |
| Full scale | dBFS | 0 dBFS = ADC/DAC maximum. SDR displays are usually dBFS-ish, **uncalibrated** |
| Antenna gain | dBi (vs isotropic), dBd (vs dipole) | dBi = dBd + 2.15 |
| Field/voltage | dBµV = 20·log10(V/1 µV) | 0 dBm in 50 Ω = 107 dBµV |

Converting: P(mW) = 10^(dBm/10). In 50 Ω, V_rms = √(P·50): 0 dBm ≈ 224 mV_rms, −100 dBm ≈ 2.24 µV_rms.

## Noise

- **Thermal noise floor**: kTB = −174 dBm/Hz at 290 K. In bandwidth B: N = −174 + 10·log10(B) dBm.
  12.5 kHz → −133 dBm; 200 kHz → −121 dBm; 2 MHz → −111 dBm.
- **Noise figure (NF)** adds to it: receiver floor = −174 + 10·log10(B) + NF. RTL-SDR NF ~4–6 dB (V4,
  VHF/UHF), HackRF ~10–15 dB without the amp, B210 ~5–8 dB.
- **Sensitivity** = floor + required SNR. To decode 2-FSK at 10 kbit/s (B ≈ 30 kHz) needing 12 dB SNR with
  NF 6 dB: −174 + 44.8 + 6 + 12 ≈ −111 dBm.
- **SNR in a display**: an FFT bin's noise depends on the bin width. A narrower FFT bin (larger FFT) lowers
  the floor shown per bin, so a CW carrier "rises" out of noise as the FFT size grows. Compare SNRs only at
  equal resolution bandwidths, or normalise per Hz.
- **Processing gain**: integrating over time or despreading raises SNR by 10·log10(gain) (e.g. LoRa SF12
  decodes around −20 dB SNR).

## Link budget

```text
P_rx (dBm) = P_tx + G_tx − L_tx_cable − FSPL − L_other + G_rx − L_rx_cable
FSPL (dB)  = 20·log10(d_km) + 20·log10(f_MHz) + 32.44
```

| Distance | 433 MHz | 915 MHz | 2.44 GHz |
|---|---|---|---|
| 1 m | 25.2 dB | 31.7 dB | 40.2 dB |
| 100 m | 65.2 dB | 71.7 dB | 80.2 dB |
| 1 km | 85.2 dB | 91.7 dB | 100.2 dB |

Bench example: HackRF at ~0 dBm (TX VGA 20, no amp, 434 MHz is a rough guess), 1 m, small antennas
(~0 dBi): P_rx ≈ −25 to −35 dBm. That's strong. The RTL-SDR's 8-bit ADC sets the floor near −80 to −90 dBm
equivalent at moderate gain, which matches the 40–55 dB SNRs measured here. Indoors, add 10–30 dB for
walls and multipath.

## Antennas and impedance

| Topic | Key facts |
|---|---|
| Wavelength | λ (m) = 300 / f (MHz). 433.92 MHz → 69 cm; 915 MHz → 33 cm; 2.44 GHz → 12.3 cm |
| Quarter-wave whip | λ/4 = 75/f(MHz) m: 17.3 cm at 433.92, 8.2 cm at 915. Needs a ground plane |
| Dipole | λ/2 overall (×0.95 for end effect) |
| 50 Ω | Every SDR port and coax is 50 Ω. 75 Ω TV coax is fine for RX |
| VSWR / return loss | VSWR 2:1 ≈ 11 % reflected (−9.5 dB RL), fine for RX and low-power TX. Never TX into an open port (no antenna) at high power |
| Polarisation | Mismatch (vertical vs horizontal) costs 10–20+ dB |
| Telescopic "rabbit ears" | Set each arm to λ/4 for the band. The RTL-SDR Blog dipole kit is a good default |
| Dummy load / attenuator | Cable TX→RX only through ≥ 30–40 dB of attenuation. HackRF RX max −5 dBm, RTL ~−10 dBm, B210 0 dBm |

## Receivers: why things appear where they shouldn't

- **Zero-IF (direct conversion)** receivers (RTL-SDR, HackRF baseband, AD9361) mix straight to 0 Hz.
  Artefacts: a **DC spike** at the centre; an **image** at −f from IQ gain/phase imbalance (typically
  −40 to −60 dBc); LO leakage on TX.
- **Mixers produce sums and differences**: f_RF ± f_LO, plus harmonics m·f_LO ± n·f_RF. Spurs that move
  differently from real signals when you retune are mixer products.
- **Intermodulation**: two strong signals f1, f2 make third-order products at 2f1 − f2 and 2f2 − f1. These
  land close to the originals, inside your band. They grow 3 dB for every 1 dB of input, so reduce gain
  and they drop quickly. That's the test: if a "signal" drops by more than the gain reduction, it's
  intermod.
- **Overload / desense**: a strong out-of-band signal (FM broadcast, pager tower, cellular) compresses
  the front end. The noise floor rises and everything weakens. Fix: lower gain, a band-pass filter, an FM
  notch.
- **Harmonics of your own TX**: 2f, 3f. A 433 MHz signal also appears at 868 and 1302 MHz, which is why
  real transmitters need output filters.
- **Clock spurs**: fixed-frequency spurs from USB, the SDR's clocks and nearby computers. Map them once
  with no antenna (or a 50 Ω load) so you don't chase them.

## Frequency accuracy

Error (Hz) = ppm × f(MHz). 1 ppm at 433.92 MHz = 434 Hz; at 2.4 GHz = 2.4 kHz. Measured on this bench:
HackRF → RTL-SDR combined about +5 ppm (+2.15 to +2.18 kHz at 433.92 MHz). Temperature changes drift
crystals (warm-up drift of a few hundred Hz is normal). Lock to a 10 MHz reference (HackRF CLKIN, B210
external ref/GPSDO) when it matters.

## Units cheat sheet

| Symbol rate vs bit rate | baud = symbols/s; bit rate = baud × bits per symbol |
|---|---|
| Eb/N0 | SNR per bit: Eb/N0 = SNR + 10·log10(B / bit_rate) |
| Occupied bandwidth | The bandwidth holding 99 % of the power (regulatory definition) |
| ERP / EIRP | Effective radiated power vs a dipole / an isotropic antenna. EIRP = P_tx + G_ant(dBi) − losses |
