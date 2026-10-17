# Radios

Usage documentation for each SDR on the bench, plus the concepts that apply to all of them.

| Radio | Folder | Role on this bench | Status |
|---|---|---|---|
| HackRF One | [hackrf/](hackrf/README.md) | Transmitter (replays generated IQ), wideband RX, fast sweeper | Attached, verified 2026-10-14 |
| RTL-SDR Blog V4 | [rtl-sdr/](rtl-sdr/README.md) | Receiver for verification, SDR++ source, `rtl_433`/`rtl_power` | Attached, verified 2026-10-14 |
| USRP B210 (OpenSourceSDRLab Artix-7) | [usrp-b210/](usrp-b210/README.md) | Full-duplex 2×2 MIMO TX/RX, SDRangel source | Attached, verified 2026-10-17 (RX, TX, duplex, Python, SDRangel) |

## Side-by-side

| | RTL-SDR Blog V4 | HackRF One | USRP B210 |
|---|---|---|---|
| Frequency | 0.5 MHz – 1.766 GHz | 1 MHz – 6 GHz | 70 MHz – 6 GHz |
| TX | No | Yes (half duplex) | Yes (full duplex, 2 ch) |
| Max sample rate | 2.4 MS/s reliable (3.2 max) | 20 MS/s | 61.44 MS/s (1 ch), 30.72 MS/s (2 ch) |
| ADC bits | 8 | 8 | 12 |
| Native file format | CU8 (`rtl_sdr`) | CS8 (`hackrf_transfer`) | CF32 / CS16 (`rx_samples_to_file`) |
| Gain control | 29 steps 0–49.6 dB | Amp 0/14, LNA 0–40/8, VGA 0–62/2 (RX); Amp + VGA 0–47 (TX) | 0–76 dB RX, 0–89.75 dB TX |
| Frequency accuracy | 1 ppm TCXO | ~10–20 ppm crystal (10 MHz CLKIN); this unit measured ~+1 ppm | 0.5 ppm TCXO (Artix board; Ettus 2 ppm + GPSDO option), 10 MHz/PPS in |
| Max safe input | ~−10 dBm (damage ~+10 dBm) | −5 dBm | 0 dBm (linear below ~−15 dBm) |
| Host link | USB 2 | USB 2 | USB 3 (measured clean: 30.72 MS/s 1 ch, 15.36 MS/s 2 ch, 20/20 duplex; sc8 to 56 MS/s) |
| Host library | librtlsdr | libhackrf | UHD |
| SoapySDR driver | `rtlsdr` | `hackrf` | `uhd` |

## Concepts common to every SDR

**Complex sample rate = visible bandwidth.** An SDR that delivers complex (I/Q) samples at *fs* shows
−fs/2 … +fs/2 around the tuned centre. 2.048 MS/s shows about 2 MHz, minus filter roll-off at the edges.
See [../knowledge/iq_and_sampling.md](../knowledge/iq_and_sampling.md).

**The centre is dirty.** Every direct-conversion (zero-IF) receiver has a DC/LO-leakage spike at exactly
0 Hz offset, and most transmitters leak their LO there too. Put the signal of interest 50–200 kHz away from
the centre, on both RX and TX.

**Gain staging.** Raise gain until the noise floor rises a few dB above the radio's own floor and the
signal is clear. Stop there. More gain only adds overload, images and intermodulation. With 8-bit radios
there is very little headroom: one strong station in the passband limits how much gain you can use for a
weak one.

**ppm error.** Crystal error scales with frequency: 5 ppm at 434 MHz is 2.2 kHz; at 2.4 GHz it is 12 kHz.
Measure it on a known carrier and correct it in software (`-p`/`-C ppm`/PPM field), or design the decoder
to search for it. On this bench, HackRF TX → RTL-SDR RX measured **+2.15 to +2.18 kHz at 433.92 MHz**.

**Only one program per radio.** Libusb devices are exclusive. SDR++ holding the RTL-SDR blocks `rtl_sdr`
and `rtl_433`. `pgrep -lf "sdrpp|rtl_|hackrf_|gqrx|uhd"` shows who has it.

**Capture length.** Capture tools stream until stopped by default. Set the length with a sample count
(`-n`, `--nsamps`, `--duration`), a sweep count (`-1`, `-N`) or a timer (`-T`, `-e`), or wrap the command
in `gtimeout N` (`brew install coreutils`; `timeout` on Linux) when scripting.

**File sizes.** Bytes = samples × bytes per complex sample: CS8/CU8 = 2, CS16 = 4, CF32 = 8.
8 MS/s CS8 = 16 MB/s; 2.048 MS/s SDR++ int16 WAV = 8.2 MB/s; 20 MS/s CF32 = 160 MB/s.

## Typical bench workflow

```text
signal_generation/generate.py  ──► signal.cs8 ──► radios/hackrf/tools/hackrf_tx.py
                                                         │ air (~1 m)
SDR++ (RTL-SDR source) ◄── rigctl :4532 ◄── software/sdr++/tools/sdrppctl.py capture ...
        └── baseband WAV ──► tools/iq_inspect.py / tools/rx_decode.py ──► decoded payload

B210:  radios/usrp-b210/tools/b210_rx.py / b210_tx.py   (UHD CLI, .cf32 + .sigmf-meta)
       software/sdrangel/tools/sdrangelctl.py          (SDRangel REST: tune, record SigMF, screenshot)
```

`tests/ota_test.py` runs the HackRF → RTL-SDR/SDR++ loop for ten modulations and checks every decode.
`tests/ota_b210.py` does the same between the HackRF and the B210, in both directions.
