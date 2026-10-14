# Modulation reference

For each scheme: what carries the information, the baseband math, bandwidth, what it looks like, and how
to demodulate. Generators are in `rfkit.mod` (see [../signal_generation](../signal_generation/README.md));
receivers in `rfkit.dsp` and [demodulation_recipes.md](demodulation_recipes.md).

## Overview

| Family | Scheme | Information in | Baseband x(t) | Bandwidth (approx.) | Waterfall | Demodulate with |
|---|---|---|---|---|---|---|
| Analog | AM (DSB-FC) | Amplitude | (1 + m·a(t)) | 2 × audio BW | Carrier + symmetric sidebands, brightness varies | `|x|` (envelope) |
| Analog | DSB-SC | Amplitude, sign | a(t) | 2 × audio BW | Sidebands, no carrier | Coherent (needs phase) |
| Analog | SSB (USB/LSB) | Amp + phase | a + j·H{a} (analytic) | audio BW | One-sided "voice" texture | Mix to audio, take Re |
| Analog | FM | Inst. frequency | exp(j·2π·Δf·∫a) | 2(Δf + fm) (Carson) | Width wobbles with audio | Discriminator |
| Analog | PM | Phase | exp(j·k·a) | similar to FM | similar to FM | Phase, unwrap |
| Digital | OOK | On/off | b(t) ∈ {0,1} | ~2–3 × bit rate (shaped) | Blinking dashes | Envelope + threshold |
| Digital | ASK (M-level) | Amplitude levels | levels[s] | like OOK | Brightness steps | Envelope + multi-threshold |
| Digital | 2-FSK / M-FSK | Frequency | exp(j·2π·∫d·s(t)) | 2(d + R) | Two (M) rails | Discriminator + threshold, or a filter bank |
| Digital | MSK / GMSK / GFSK | Frequency (smooth) | FSK, h = 0.5 / Gaussian pulses | ~1–1.5 × R | One smooth hump | Discriminator, or coherent |
| Digital | BPSK | Phase 0/180° | ±1 × RRC pulses | R(1 + β) | Solid block | Carrier recovery + sign |
| Digital | QPSK / 8PSK | Phase | e^(jθ) × RRC | R(1 + β) | Solid block | Costas, slice angle |
| Digital | QAM-16/64/256 | Amp + phase | grid × RRC | R(1 + β) | Solid block | Costas + equaliser, slice grid |
| Spread | DSSS | Phase × chips | b × PN chips | chip rate | Wide block, low PSD | Correlate with the PN code |
| Spread | CSS (LoRa) | Chirp start offset | chirps | BW (125/250/500 kHz) | Diagonal lines | De-chirp + FFT |
| Spread | FHSS | Narrowband, hopping | hops | per-hop BW | Dots jumping across | Follow hops |
| Multi-carrier | OFDM | Many subcarriers | IFFT(symbols) + CP | N × Δf | Flat rectangle, sharp edges | CP sync, FFT, equalise |

## Key relationships

- **Bit rate** = symbol rate × log2(M).
- **Modulation index (FSK)** h = 2·d / R = tone spacing / symbol rate. h = 0.5 is MSK. h ≥ 1 shows distinct
  tones on a waterfall.
- **Carson's rule (FM/FSK)**: B ≈ 2·(Δf + f_m) where f_m is the highest modulating frequency (or R/2…R for
  data).
- **Linear modulations**: B = R·(1 + β) with RRC roll-off β.
- **Spectral efficiency**: OOK/FSK ≈ 0.5–1 bit/s/Hz; QPSK ≈ 1.5; 64QAM ≈ 4.5.
- **Robustness to noise**, roughly best to worst at equal Eb/N0: coherent BPSK/QPSK > coherent FSK >
  non-coherent FSK > OOK > 16QAM > 64QAM. Spreading (LoRa, DSSS) trades bandwidth or time for working
  below the noise floor.

## Recognising each by ear (SDR++)

| Mode | Listen in | Sounds like |
|---|---|---|
| CW Morse | CW or USB, narrow | Clean beeps, rhythmic dits and dahs |
| OOK packets | AM | Short buzzes/clicks |
| 2-FSK | NFM | Two-tone warble ("RTTY") at the bit rate |
| AFSK (APRS) | NFM | 1200/2200 Hz modem screech |
| POCSAG | NFM | Rapid two-tone chirping bursts, 512/1200/2400 bd |
| PSK/QAM | any | Hiss. **That absence of structure is the clue** |
| LoRa | NFM/USB | Rising "whoop" sweeps |
| FM voice | NFM/WFM | Voice. Wrong width = distorted/quiet |
| AM voice | AM | Voice with carrier hum |
| SSB voice | USB/LSB | Voice, shifted if mistuned |
| Digital voice (DMR, P25, NXDN, D-STAR) | NFM | Harsh buzzy "data" with a rhythm: TDMA bursts for DMR |

## Line codes vs modulation (don't mix up the layers)

**Modulation** maps symbols onto the carrier (OOK, FSK, PSK). **Line coding** maps bits onto symbols (NRZ,
Manchester, NRZI, PWM). Then **framing** (preamble, sync, length, CRC) and **payload encoding** (ASCII,
BCD, Base64) sit above. A perfect FSK demodulator still yields garbage if the bits are Manchester-coded and
you don't decode them. Work through the layers in order. See
[line_coding_and_framing.md](line_coding_and_framing.md).
