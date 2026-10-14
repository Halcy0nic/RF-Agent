# Ettus USRP B210

The USRP B210 (Ettus Research / NI) is a **full-duplex, 2×2 MIMO** SDR built around the Analog Devices
**AD9361** RFIC. It covers **70 MHz – 6 GHz** with **12-bit** converters and up to **56 MHz** of
instantaneous bandwidth over **USB 3.0**. Compared with the HackRF it has much better dynamic range, can
receive and transmit at the same time, and has two phase-coherent channels.

> **Bench status (2026-10-14): no B210 attached. This page has NOT been verified on hardware.**
> Commands and flags were checked against the UHD **4.10.0.0** tools installed here (Homebrew
> `uhd 4.10.0.0_2`, GNU Radio 3.10.12). When a B210 is connected, run §2 and update this note.

---

## 1. Specifications

| Item | Value | Notes |
|---|---|---|
| Frequency range | 70 MHz – 6 GHz (RX and TX) | The AD9361 tunes lower, but the board's baluns are specified from 70 MHz |
| Channels | 2 RX + 2 TX, coherent (shared LO) | `--channels 0,1`. The B200 is the 1×1 version |
| Duplex | Full duplex | RX and TX at once, on different (or the same) frequencies |
| ADC/DAC | 12-bit | Wire format sc16 (default) or sc8 to save USB bandwidth |
| Master clock rate (MCR) | 5 – 61.44 MHz | Sample rate = MCR / decimation. UHD picks the MCR automatically, or set it with `--args "master_clock_rate=..."` |
| Max sample rate | 61.44 MS/s on 1 channel; 30.72 MS/s per channel with 2 channels | Over USB 3. Sustained 56 MS/s needs a good USB 3 controller and fast storage |
| Analog bandwidth | 200 kHz – 56 MHz (programmable filters) | `--bw` |
| RX gain | 0 – 76 dB (1 dB steps) | |
| TX gain | 0 – 89.75 dB (0.25 dB steps) | Output up to about +10 dBm (frequency-dependent) |
| RX input | Keep below about −15 dBm for linear operation. **Damage level 0 dBm** | Never connect TX straight to RX. Use ≥ 30 dB of attenuation for loopback |
| Antenna ports | Per channel: **TX/RX** (TX, or RX when not transmitting) and **RX2** (RX only) | TX is **only** possible on TX/RX |
| Reference | TCXO ±2 ppm. Optional GPSDO (±25 ppb disciplined). External 10 MHz + PPS SMA inputs | `--ref external`, `--ref gpsdo` |
| FPGA | Xilinx Spartan-6 XC6SLX150 | Image loaded by UHD at every start |
| Power | USB bus power, or an external 6 V supply | Use external power for 2-channel TX or long high-rate runs |
| Host interface | USB 3.0 (works at USB 2 at much lower rates, ~8 MS/s sc16) | |

---

## 2. Install and first contact

```bash
# macOS
brew install uhd                    # also: brew install gnuradio (for uhd_fft, uhd_siggen, uhd_rx_cfile)
# Debian / Ubuntu
sudo apt install uhd-host libuhd-dev python3-uhd
# Linux USB permissions
sudo cp /usr/lib/uhd/utils/uhd-usrp.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger
```

UHD loads the B210's firmware and FPGA image from disk **every time it opens the device**. Download the
images once (and again after every UHD upgrade):

```bash
# macOS / Homebrew (path verified for uhd 4.10)
python3 "$(brew --prefix uhd)/lib/uhd/utils/uhd_images_downloader.py" -t b2xx
# Linux
sudo uhd_images_downloader -t b2xx
uhd_config_info --images-dir         # where UHD looks; override with UHD_IMAGES_DIR=/path
```

Find and probe:

```bash
uhd_find_devices                     # lists serial, name, product (B210). "No UHD Devices Found" = not attached
uhd_usrp_probe --args "type=b200"    # loads images, prints the full RX/TX tree: ranges, gains, antennas, sensors
```

`uhd_usrp_probe` is the B210's `hackrf_info`. Expect FW and FPGA versions, the "B210" product, two RX and
two TX frontends with antennas `TX/RX`, `RX2`, gain ranges and the `ref_locked` sensor. If it says
"Operating over USB 2", change the cable or port.

Throughput check before trusting a capture:

```bash
/opt/homebrew/lib/uhd/examples/benchmark_rate --args "type=b200" --rx_rate 20e6 --duration 10
/opt/homebrew/lib/uhd/examples/benchmark_rate --args "type=b200" --rx_rate 10e6 --tx_rate 10e6 --channels "0,1" --duration 10
```

Read the summary for **dropped samples / overflows ("O")** and **underflows ("U")**. Any of those mean
your rate is too high for the host. On Linux the examples live in `/usr/lib/uhd/examples/`. Homebrew puts
them in `$(brew --prefix uhd)/lib/uhd/examples/` and they are not on `PATH`.

---

## 3. Receiving

### `rx_samples_to_file` (UHD example, no GNU Radio needed)

```bash
EX=$(brew --prefix uhd)/lib/uhd/examples
# 2 s at 433.92 MHz, 2 MS/s, complex float32 (= .cf32), RX2 port, 40 dB gain
$EX/rx_samples_to_file --args "type=b200" --freq 433.92e6 --rate 2e6 --gain 40 --ant RX2 \
    --type float --duration 2 --file cap_433.cf32
# 16-bit ints (half the size) = .cs16
$EX/rx_samples_to_file --args "type=b200" --freq 915e6 --rate 10e6 --gain 30 --ant RX2 \
    --type short --nsamps 20000000 --file cap_915.cs16
# both channels (writes one file per channel)
$EX/rx_samples_to_file --args "type=b200" --channels 0,1 --freq 2.44e9 --rate 20e6 --gain 40 \
    --type short --duration 1 --file ism.cs16
```

Key options: `--freq`, `--rate`, `--gain`, `--ant TX/RX|RX2`, `--bw`, `--type float|short|double`,
`--nsamps N` or `--duration S` (**always bound it**), `--channels`, `--ref internal|external|gpsdo`,
`--otw sc16|sc8`, `--lo-offset`, `--stats`, `--progress`.

**Use the actual rate printed in the console.** UHD coerces the requested rate to MCR/decimation. For
exact rates, pick an MCR that's an integer multiple (e.g. `--args "type=b200,master_clock_rate=32e6"` for
2 MS/s × 16).

Load in Python: `rfkit.iq.load("cap_433.cf32", fs=2e6)` or `np.fromfile(path, np.complex64)` for float, or
`rfkit.iq.load("cap.cs16", fs=...)` for short.

### GNU Radio helpers (installed with `brew install gnuradio`)

```bash
uhd_fft -a "type=b200" -f 98e6 -s 10e6 -g 30          # live spectrum/waterfall GUI
uhd_rx_cfile -a "type=b200" -f 433.92e6 -r 2e6 -g 40 -A RX2 -N 4000000 cap.cf32   # -s for shorts
uhd_rx_nogui -a "type=b200" -f 162.55e6 --demod NBFM   # simple audio receiver
```

### Gain and level tips

- Start at 30–40 dB RX gain. The AD9361 runs its own AGC if you ask for it
  (`usrp.set_rx_agc(True)`). Keep AGC **off** for measurement and packet decoding.
- The AD9361 has an internal DC-offset and IQ-imbalance tracking loop, so the centre spike is much smaller
  than on an RTL-SDR or HackRF. Offsetting the signal from the centre is still good practice.
- Strong out-of-band signals can still desensitise it. The B210 has no preselector filters beyond the
  baluns, so add band filters near broadcast or cellular towers.

---

## 4. Transmitting

```bash
EX=$(brew --prefix uhd)/lib/uhd/examples
# Replay a complex-float file (generate with rfkit: iq.save("sig.cf32", x, peak=0.7)) — bounded with gtimeout
gtimeout 10 $EX/tx_samples_from_file --args "type=b200" --file sig.cf32 --type float \
    --rate 2e6 --freq 433.92e6 --gain 40 --ant TX/RX
# Test waveforms (CW / sine / square) — runs until killed, so always bound it
gtimeout 5 $EX/tx_waveforms --args "type=b200" --rate 1e6 --freq 433.92e6 --gain 30 \
    --wave-type SINE --wave-freq 100e3 --wave-ampl 0.3
# GNU Radio signal generator
gtimeout 5 uhd_siggen -a "type=b200" -f 433.92e6 -s 1e6 -g 30 --sine -x 100e3 -m 0.3
```

- **Formats:** `--type float` = CF32 (`.cf32`, what rfkit writes), `short` = CS16. CS8 HackRF files must
  be converted: `iq.save("sig.cf32", iq.load("sig.cs8")[0])`.
- **Amplitude:** keep |x| ≤ ~0.7 of full scale for headroom. The AD9361 DAC is 12-bit, so you can run
  much lower amplitudes than on a HackRF without losing SNR.
- **Gain:** 0–89.75 dB. Roughly 40 dB on the bench is comparable to HackRF `-x 20`, but **measure**,
  don't assume. Start at 0 and step up while watching a receiver.
- `--repeat` in `tx_samples_from_file` loops forever. Never use it without `gtimeout`.
- **TX happens only on the `TX/RX` port.** Always use an antenna or a 50 Ω load. Same legal rules as the
  HackRF: [../../knowledge/regulations_and_safety.md](../../knowledge/regulations_and_safety.md).
- **Full-duplex self-test:** TX on channel 0 TX/RX → 30–40 dB attenuator → channel 0 RX2. Or simply TX
  with an antenna and receive on RX2 of the other channel.

---

## 5. Python (UHD API)

```python
import numpy as np, uhd                                  # apt: python3-uhd; pip wheels exist for some platforms
usrp = uhd.usrp.MultiUSRP("type=b200")
x = usrp.recv_num_samps(2_000_000, 433.92e6, 2e6, [0], 40)   # (num, freq, rate, channels, gain) -> (chans, N) complex64
x = x[0]

# Transmit a NumPy array (blocking, bounded by its length)
tx = (0.5 * np.exp(2j * np.pi * 100e3 * np.arange(2_000_000) / 2e6)).astype(np.complex64)
usrp.send_waveform(tx, 1.0, 433.92e6, 2e6, [0], 30)        # (samples, duration_s, freq, rate, chans, gain)
```

The Homebrew UHD on this Mac was built **without** the Python module (`import uhd` fails). Use the CLI
examples plus `rfkit.iq.load`, or install UHD's Python bindings from source/conda. SoapySDR with
`soapyuhd` is an alternative (`driver=uhd`).

Lower-level streaming follows the usual UHD pattern: `usrp.set_rx_rate/freq/gain/antenna`,
`streamer = usrp.get_rx_stream(uhd.usrp.StreamArgs("fc32", "sc16"))`, `issue_stream_cmd`, then `recv()` into
a NumPy buffer in a loop. Watch `metadata.error_code` for overflows.

---

## 6. Other software

| Software | Notes |
|---|---|
| **GNU Radio** | `UHD: USRP Source/Sink` blocks (gr-uhd). The reference way to build B210 flowgraphs |
| **SDR++** | Linux/Windows builds have a "USRP" source module. **The macOS build installed here has no USRP source** (no `usrp_source.dylib` in its Plugins) |
| **SoapySDR** | `soapyuhd` gives `driver=uhd` to any Soapy app (CubicSDR, URH, Pothos, SDRangel) |
| **SDRangel** | Installed here. Has native USRP input/output plugins |
| **srsRAN / OpenAirInterface / OpenBTS / gr-gsm** | Cellular stacks commonly run on the B210 (licensed spectrum or a shielded box only) |

---

## 7. Utilities and calibration

| Tool | Use |
|---|---|
| `uhd_find_devices`, `uhd_usrp_probe` | Discovery / capabilities |
| `uhd_image_loader` / `uhd_images_downloader.py` | Images |
| `b2xx_fx3_utils` (`$(brew --prefix uhd)/lib/uhd/utils/`) | Low-level FX3 USB controller tools (reset, firmware) |
| `query_gpsdo_sensors` | GPSDO lock and time (B210 with GPSDO) |
| `rx_ascii_art_dft` | Terminal spectrum display |
| `usrp_list_sensors` | `ref_locked`, `lo_locked`, `temp` |
| `uhd_cal_rx_iq_balance`, `uhd_cal_tx_iq_balance`, `uhd_cal_tx_dc_offset` | Calibration for daughterboard USRPs. **The B2xx calibrate inside the AD9361 automatically**, so these normally aren't needed |

---

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `No UHD Devices Found` | Not attached / cable / permissions (Linux udev rules) |
| `RuntimeError: ... images ... not found` | Run the images downloader (§2) or set `UHD_IMAGES_DIR` |
| `Operating over USB 2` | USB 2 cable or port. Use a blue USB 3 port and the supplied cable |
| `O` printed in the console (overflow) | Host can't keep up. Lower the rate, use `--otw sc8`, write to a fast SSD or RAM disk |
| `U` printed (underflow) on TX | You aren't supplying samples fast enough. Pre-generate to a file and replay |
| `L` (late) | Timed commands in the past. Set the time correctly / add a delay |
| Requested rate coerced | Choose an MCR that divides evenly (§3) |
| Spurs at fixed offsets | AD9361 LO/clock spurs. Move the LO with `--lo-offset` and re-tune digitally |
| Device stops responding after a crash | `b2xx_fx3_utils --reset-device`, or unplug/replug |

---

## 9. When to choose the B210 over the HackRF / RTL-SDR

- You need **RX and TX at once** (protocol testing, loopback measurement, transponders).
- You need **two coherent channels** (direction finding, MIMO, interferometry).
- You need **dynamic range**: 12-bit converters and better filtering pick out weak signals next to strong
  ones far better than 8-bit radios.
- You need **wide bandwidth with no drops**: 30–56 MHz over USB 3.
- The HackRF still wins on frequency coverage below 70 MHz and on cost. The RTL-SDR wins as a cheap,
  always-on monitor receiver.
