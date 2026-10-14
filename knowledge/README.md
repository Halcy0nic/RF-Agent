# Knowledge base

General RF and DSP knowledge an RF agent needs: how to reason about signals, how to find and identify
them, how to turn IQ into bits, and how to stay legal and safe while doing it. These pages are written to
be read by an agent mid-task, so each one stands alone, is dense, and points to working code in
[`../rfkit`](../rfkit) and [`../tools`](../tools).

| Page | Read when |
|---|---|
| [rf_fundamentals.md](rf_fundamentals.md) | dB/dBm, power, noise floor, link budgets, antennas, impedance, mixers, images, intermod |
| [iq_and_sampling.md](iq_and_sampling.md) | Complex baseband, Nyquist, aliasing, DC spike, IQ imbalance, file formats and sizes |
| [dsp_fundamentals.md](dsp_fundamentals.md) | FFT, windows, resolution, PSD, spectrograms, filters, mixing, decimation, correlation |
| [modulation_reference.md](modulation_reference.md) | Every common modulation: math, bandwidth, waterfall fingerprint, how to demodulate |
| [demodulation_recipes.md](demodulation_recipes.md) | Step-by-step receivers (Morse, OOK, Manchester, FSK, GFSK, PSK, AM/FM) with rfkit code |
| [signal_identification.md](signal_identification.md) | Unknown signal → what is it? Fingerprints, band plan, common signals by frequency |
| [analysis_workflow.md](analysis_workflow.md) | The end-to-end method: survey → capture → identify → demodulate → decode, plus agent rules |
| [line_coding_and_framing.md](line_coding_and_framing.md) | Recovering bytes: line codes, preambles/sync words, CRC hunting, whitening, protocol reversing |
| [regulations_and_safety.md](regulations_and_safety.md) | What you may transmit, ISM bands, power limits, bench safety, agent guard rails |

## The grading ladder

Every receive task climbs the same ladder. When stuck, name the rung you are on:

```text
Carrier found → Modulation identified → Symbol rate estimated → Bits recovered → Framing understood → Payload decoded
```

A plot or a check should confirm each rung: a waterfall for the carrier, a fingerprint for the modulation,
an eye diagram or run-length histogram for the rate, a clean two-level waveform for the bits, a sync-word
hit for the framing, a passing CRC for the payload.
