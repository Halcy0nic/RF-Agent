# USRP B210 (Ettus B210 and the OpenSourceSDRLab Artix-7 B210)

The USRP B210 is a **full-duplex, 2×2 MIMO** SDR built around the Analog Devices **AD9361** RFIC:
**70 MHz – 6 GHz**, **12-bit** converters, up to **56 MHz** of instantaneous bandwidth over **USB 3.0**.
Compared with the HackRF it has more dynamic range, can receive and transmit at the same time, and has two
phase-coherent channels.

The board on this bench is the **OpenSourceSDRLab "USRP B210 Artix-7"**. It's a redesign of the Ettus
reference that swaps the Spartan-6 FPGA for a **Xilinx Artix-7 XC7A75T** (a XC7A200T bundle also
exists). It runs with stock UHD **but needs the vendor's FPGA image**. Everything else (FX3 USB firmware,
UHD tools, GNU Radio, SDRangel) is the same as for an Ettus B210.

> Verified on a second host (2026-10-26): Ubuntu Linux x86-64, UHD 4.9.0.1 (apt), same board (`Custom_SDR_B210`),
> USB 3. RX at 10 MS/s with no drops and over-the-air decoding of three CTF signals (OOK Morse, OOK and 2-FSK
> UART text). See [section 11](#11-linux-host-notes-ubuntu).
>
> Verified on this bench (2026-10-17): OpenSourceSDRLab B210, XC7A75T, name
> `Custom_SDR_B210`. UHD 4.10.0.0 (Homebrew) and UHD 4.9 (bundled in SDRangel 7.27.2), macOS on Apple
> Silicon, USB 3 through a USB-C hub. FW 8.0, FPGA 16.0. RX, TX, full duplex, GNU Radio Python and SDRangel
> all tested against a HackRF One at 433.92 MHz.

> **One program owns the board.** UHD tools, GNU Radio and SDRangel cannot use the B210 at the same time. If
> `uhd_find_devices` says "No UHD Devices Found" while `lsusb` still lists `2500:0020`, another program (often a
> forgotten SDRangel) is holding it: close it (`pkill -x sdrangel`) and retry.

| Tool in this folder | What |
|---|---|
| [`tools/setup_images.sh`](tools/setup_images.sh) | Download UHD images, install the Artix-7 FPGA image (`--variant 75T\|200T`), set `UHD_IMAGES_DIR` (shell + macOS LaunchAgent) |
| [`tools/b210_rx.py`](tools/b210_rx.py) | Record IQ (`.cf32`/`.cs16`) with a SigMF sidecar, one or both channels. Captures at 20 MB/s or more go through `/dev/shm` automatically (`--ram`/`--no-ram`), then the data and sidecar are moved together; reports overflow count and samples vs expected |
| [`tools/b210_tx.py`](tools/b210_tx.py) | Transmit any IQ file rfkit reads (HackRF `.cs8` too), with repeat/gap/dry-run |
| [`tools/b210_gr_capture.py`](tools/b210_gr_capture.py) | Capture straight into NumPy with GNU Radio's UHD block (Python) |
| [`../../tests/ota_b210.py`](../../tests/ota_b210.py) | Over-the-air test HackRF ↔ B210 for every modulation in the repo |

---

## 1. Specifications

| Item | Ettus B210 | OpenSourceSDRLab Artix-7 B210 | Notes |
|---|---|---|---|
| RFIC | AD9361 | AD9361 | |
| Frequency | 70 MHz – 6 GHz | 70 MHz – 6 GHz | UHD reports 50–6000 MHz tuning range |
| Channels | 2 RX + 2 TX, coherent | same | Shared LO: both channels on the same RX (and TX) frequency |
| ADC/DAC | 12-bit | 12-bit | Wire format `sc16` (default) or `sc8` |
| Max sample rate | 61.44 MS/s (1 ch), 30.72 MS/s (2 ch) | same | Measured limits on this Mac: §4 |
| Analog bandwidth | 200 kHz – 56 MHz | same | `--bw` |
| RX gain | 0 – 76 dB, 1 dB steps | same | UHD name `PGA` |
| TX gain | 0 – 89.75 dB, 0.25 dB steps | same | |
| TX power | up to ~+10 dBm | up to ~+7 dBm (vendor) | Frequency-dependent |
| RX noise figure | < 8 dB | < 3.5 dB @ 2.4 GHz (vendor) | |
| FPGA | Spartan-6 XC6SLX150 | **Artix-7 XC7A75T** (or XC7A200T) | FPGA image is loaded by UHD at every start |
| Reference | TCXO, optional GPSDO | 0.5 ppm TCXO, no GPSDO slot | External **10 MHz** and **PPS** inputs (MMCX on the Artix board) |
| Max RX input | 0 dBm (damage) | | Linear below about −15 dBm |
| Host link / power | USB 3.0 (micro-B), USB or 6 V external | USB 3.0 **Type-C**, USB bus power | |
| Size | 97 × 155 mm | 70 × 97 mm | |

### Ports and channel mapping

UHD sees two channels, each with two antenna names: **`TX/RX`** (transmit, or receive when not
transmitting) and **`RX2`** (receive only). TX only comes out of `TX/RX`. On the Artix-7 board
(verified by moving a HackRF tone between ports):

| UHD channel | UHD antenna | Board label | UHD frontend name |
|---|---|---|---|
| 0 | `TX/RX` | **TRX1** | RX `FE-RX2` / TX `FE-TX2` |
| 0 | `RX2` | **RX1** | RX `FE-RX2` |
| 1 | `TX/RX` | **TRX2** | RX `FE-RX1` / TX `FE-TX1` |
| 1 | `RX2` | **RX2** | RX `FE-RX1` |

The names don't line up, which is confusing: UHD calls every channel's RX-only port "RX2", and channel 0's
frontend is named `FE-RX2` (the AD9361's internal port). Use **channel 0 + `RX2`** for the RX1 connector.

LEDs on the Artix-7 board: PWR (power), STAS (FPGA/firmware loaded), CLK (flashes with PPS), USR (10 MHz
reference locked), TRX1/TRX2 (red = TX, blue = RX), RX1/RX2 (blue = RX). MX1.25 header: GPIO.

---

## 2. Install (drivers, images, environment)

```bash
# macOS
brew install uhd gnuradio              # gnuradio is optional (uhd_fft, uhd_siggen, Python gr-uhd)
# Debian / Ubuntu
sudo apt install uhd-host libuhd-dev python3-uhd gnuradio       # the apt package installs its own udev rules
# source builds only: sudo cp <prefix>/lib/uhd/utils/uhd-usrp.rules /etc/udev/rules.d/ && sudo udevadm control --reload && sudo udevadm trigger
```

UHD loads the FX3 USB firmware and the FPGA image from disk **every time it opens the device**. One command
sets everything up:

```bash
radios/usrp-b210/tools/setup_images.sh --variant 75T     # OpenSourceSDRLab XC7A75T (this board)
radios/usrp-b210/tools/setup_images.sh --variant 200T    # OpenSourceSDRLab XC7A200T
radios/usrp-b210/tools/setup_images.sh                   # genuine Ettus B210 (stock Spartan-6 image)
```

What it does:

1. Runs UHD's `uhd_images_downloader -t b2xx --refetch` into **`~/.local/share/uhd/images`**, a stable
   location that survives `brew upgrade`. The Homebrew default is inside the versioned Cellar path.
   The downloader needs the Python `requests` module.
2. For `--variant`: downloads `usrp_b210_fpga.bin` for that FPGA from
   [OpenSourceSDRLab/USRP-B210-Artix-7-AD9361](https://github.com/OpenSourceSDRLab/USRP-B210-Artix-7-AD9361)
   (`Bin file/XC7A75T/` or `XC7A200T/`) and verifies its git blob hash (75T `c6ad69d9…`, 2,853,184 bytes).
   It keeps the Ettus image as `usrp_b210_fpga.bin.ettus-spartan6` and installs the vendor image as
   `usrp_b210_fpga.bin`, plus a named copy `usrp_b210_fpga_opensourcesdrlab_xc7a75t.bin`.
3. Appends `export UHD_IMAGES_DIR=~/.local/share/uhd/images` to `~/.zshrc`.
4. macOS: installs `~/Library/LaunchAgents/local.uhd-images-dir.plist`, which runs `launchctl setenv
   UHD_IMAGES_DIR …` at login, and sets it now. GUI apps started from the Dock/Finder (SDRangel, GNU Radio
   Companion) need this, because they don't read `~/.zshrc`. Verified: `open -a SDRangel` finds the B210.

The FPGA image is a plain file, and UHD reloads it at every open. To switch images, overwrite
`usrp_b210_fpga.bin`, or point one run at another file with `--args "type=b200,fpga=/path/to/image.bin"`.
Nothing is flashed to the board.

### First contact

```bash
uhd_find_devices
uhd_usrp_probe --args type=b200
```

Real output from this board:

```text
[INFO] [B200] Loading firmware image: ~/.local/share/uhd/images/usrp_b200_fw.hex...
  serial: XXXXXXX   name: Custom_SDR_B210   product: B210   type: b200
[INFO] [B200] Detected Device: B210
[INFO] [B200] Loading FPGA image: ~/.local/share/uhd/images/usrp_b210_fpga.bin...
[INFO] [B200] Operating over USB 3.
[INFO] [B200] Register loopback test passed
|   Mboard: B210   revision: 4   FW Version: 8.0   FPGA Version: 16.0
|   RX Frontend: A  Name: FE-RX2  Antennas: TX/RX, RX2  Freq range: 50.000 to 6000.000 MHz
|                   Gain range PGA: 0.0 to 76.0 step 1.0 dB   Bandwidth range: 200000.0 to 56000000.0
|   TX Frontend: A  Name: FE-TX2  Antennas: TX/RX         Gain range PGA: 0.0 to 89.8 step 0.2 dB
```

USB behaviour: before firmware loads, the board enumerates as Cypress **"WestBridge"** (VID `0x2500`,
PID `0x0020`) at USB 2 speed. That's the FX3 bootloader, and it's normal. After UHD loads the firmware it
re-enumerates as **"USRP B200"** on the USB 3 bus. Check with `ioreg -p IOUSB -w0 | grep -iE "westbridge|usrp"`
(macOS) or `lsusb | grep 2500` (Linux). **"Operating over USB 2"** in the probe output means a USB 2 cable,
port or hub, and rates drop to about 8 MS/s.

Sensors (`$(brew --prefix uhd)/lib/uhd/examples/usrp_list_sensors --args type=b200`): RX/TX `LO: locked`,
`temp` ~32 °C idle, `RSSI`, and `Ref: unlocked` (normal with no external 10 MHz).

---

## 3. Receiving

### `b210_rx.py` (wrapper around UHD's `rx_samples_to_file`)

```bash
P=.venv/bin/python; T=radios/usrp-b210/tools
$P $T/b210_rx.py --freq 433.92e6 --rate 2e6 --gain 40 --seconds 5 -o cap.cf32                 # RX1 port
$P $T/b210_rx.py --freq 433.92e6 --rate 2e6 --gain 40 --ant TX/RX --seconds 5 -o cap.cf32     # TRX1 port
$P $T/b210_rx.py --freq 915e6 --rate 10e6 --gain 30 --channel 1 --seconds 2 -o cap.cs16       # RX2 port
$P $T/b210_rx.py --freq 2.44e9 --rate 15.36e6 --gain 50 --channels 0,1 --seconds 1 -o mimo.cf32  # -> mimo_ch0/1
$P $T/b210_rx.py --freq 98e6 --rate 56e6 --otw sc8 --seconds 1 -o wide.cs16                   # 56 MS/s needs sc8
$P tools/iq_inspect.py cap.cf32           # rate + centre come from cap.sigmf-meta: no --fs needed
$P tools/rx_decode.py fsk cap.cf32
```

It finds the UHD example programs (Homebrew keeps them in `$(brew --prefix uhd)/lib/uhd/examples`, not on
`PATH`), defaults `UHD_IMAGES_DIR`, records an exact sample count (`--nsamps`), and writes a
`<file>.sigmf-meta` with the actual rate, centre, gain, antenna and channel. `rfkit.iq.load()` reads that
sidecar automatically. Start-up (firmware + FPGA load + LO lock) takes about **3 s** before samples flow.
Anything transmitted before then is missed. `tests/ota_b210.py` waits for the file to start growing.

### UHD example directly

```bash
EX=$(brew --prefix uhd)/lib/uhd/examples        # Ubuntu apt: /usr/libexec/uhd/examples
$EX/rx_samples_to_file --args type=b200 --freq 433.92e6 --rate 2e6 --gain 40 --ant RX2 \
    --type float --nsamps 4000000 --file cap.cf32
```

Options: `--freq --rate --gain --ant TX/RX|RX2 --channels 0|1|0,1 --bw --type float|short|double
--nsamps N | --duration S --otw sc16|sc8 --ref internal|external|gpsdo --lo-offset --stats --progress`.
Multi-channel captures write `<name>_ch0.<ext>` and `<name>_ch1.<ext>`. Without `--nsamps`/`--duration`
it records until stopped.

### Live spectrum

| Tool | Command |
|---|---|
| SDRangel (GUI, demods, recording, REST API) | [../../software/sdrangel/README.md](../../software/sdrangel/README.md) |
| `uhd_fft` (GNU Radio) | `uhd_fft -a type=b200 -f 433.92e6 -s 10e6 -g 40` |
| Terminal | `$EX/rx_ascii_art_dft --args type=b200 --freq 433.92e6 --rate 2e6 --gain 40 --ref-lvl -40` |
| SDR++ | Not supported on macOS (no USRP source in the macOS build). Linux/Windows builds have a "USRP" source |

### Measured RX performance (HackRF transmitting at 433.92 MHz, TX gain 20, amp off, ~1 m)

`python tests/ota_b210.py --dir hackrf2b210` (B210 RX gain 40, RX1 port, 2 MS/s): **9/9 modulations
decoded, every packet CRC OK.**

| Case | SNR (peak bin) | | Case | SNR |
|---|---|---|---|---|
| tone | 50.8 dB | | 2-FSK | 41.8 dB |
| Morse | 46.7 dB | | GFSK | 42.1 dB |
| OOK | 38.8 dB | | BPSK 50 kBd | 38.3 dB |
| OOK Manchester | 40.4 dB | | QPSK 50 kBd | 27.4 dB (44.1 dB on TRX1) |
| NFM | 43.3 dB | | | |

For comparison, the RTL-SDR V4 saw the same 50 kBd PSK at 16–18 dB. The B210's 12-bit converters and
lower noise figure show most on wideband signals. The HackRF's transmit spurs (±0.4/0.8 MHz around the
carrier while it's keyed) are visible on the B210 but weren't on the RTL-SDR.

**Frequency accuracy.** The HackRF's +100 kHz test tone arrived at **+100.433 kHz**, so the HackRF crystal
is about +1.0 ppm high. B210 transmissions arrived at the HackRF **−436 Hz** off, the same 1 ppm the other
way. The B210's 0.5 ppm TCXO is the better reference on this bench.

---

## 4. Throughput (USB 3 via a USB-C hub, Apple Silicon Mac)

`$EX/benchmark_rate --args type=b200 --rx_rate R [--tx_rate R] [--channels 0,1] [--rx_otw sc8] --duration 5`

| Test | Result |
|---|---|
| RX 1 ch, sc16: 10 / 20 / **30.72 MS/s** | 0 dropped, 0 overruns |
| RX 1 ch, sc16: 40 / 50 / 56 MS/s | Overruns (2 / 7 / 28 in 5 s): too fast for sc16 here |
| RX 1 ch, **sc8**: 56 MS/s | 0 dropped |
| RX 2 ch, sc16: 10 / **15.36 MS/s** | 0 dropped |
| RX 2 ch, sc16: 20 MS/s | 3 overruns; 30.72 MS/s: heavy drops |
| RX 2 ch, **sc8**: 20 / 30.72 MS/s | 0 dropped |
| TX 1 ch: 20 MS/s | 0 underruns; 30.72 MS/s: 13 underruns |
| Full duplex RX+TX: 10/10, **20/20 MS/s** | 0 overruns, 0 underruns |

Rule of thumb on this host: one channel up to 30.72 MS/s, two channels up to 15.36 MS/s, full duplex up to
20 MS/s with `sc16`. Use `--otw sc8` (8-bit over the wire) beyond that. A host directly on a USB 3
controller (no hub) or a Linux box may do better. Re-run `benchmark_rate` on a new setup.

---

## 5. Transmitting

### `b210_tx.py` (wrapper around UHD's `tx_samples_from_file`)

```bash
P=.venv/bin/python
$P signal_generation/generate.py fsk --text "HELLO" --rate 5000 --dev 20e3 --repeat 3 -o sig.cs8   # HackRF format is fine
$P radios/usrp-b210/tools/b210_tx.py sig.cs8 --freq 433.92e6 --rate 2e6 --gain 50                 # TRX1
$P radios/usrp-b210/tools/b210_tx.py sig.cs8 --freq 433.92e6 --rate 2e6 --gain 50 --channel 1 --repeat 3 --gap 1   # TRX2
$P radios/usrp-b210/tools/b210_tx.py --dry-run sig.cs8 --freq 2.44e9 --rate 10e6 --gain 60
```

It converts any rfkit-readable file to complex float32 at 70 % of full scale (`--peak`; `--peak 0` skips the rescaling, so a `.cf32` file plays exactly as it is), then runs
`tx_samples_from_file --type float --ant TX/RX`. Like RX, the first ~3 s after start are device set-up
before RF comes out.

**TX gain calibration** (tone into the HackRF at ~1 m, HackRF RX LNA 24 / VGA 20):

| B210 TX gain | SNR at the HackRF |
|---|---|
| 40 dB | 44.5 dB |
| 50 dB | 54.4 dB |
| 60 dB | 57.2 dB (HackRF receiver starting to saturate) |

**B210 gain 50 ≈ HackRF `-x 20`** at the same distance. With `python tests/ota_b210.py --dir b210tohackrf
--tx-gain 50`, **9/9 modulations decoded** at the HackRF (OOK 43 dB, FSK 42 dB, BPSK 26 dB, QPSK 18 dB,
NFM 39 dB SNR).

### UHD examples directly

```bash
EX=$(brew --prefix uhd)/lib/uhd/examples
$EX/tx_samples_from_file --args type=b200 --file sig.cf32 --type float --rate 2e6 --freq 433.92e6 --gain 50 --ant TX/RX
$EX/tx_waveforms --args type=b200 --rate 1e6 --freq 433.92e6 --gain 40 --wave-type SINE --wave-freq 100e3 --wave-ampl 0.3
uhd_siggen -a type=b200 -f 433.92e6 -s 1e6 -g 40 --sine -x 100e3 -m 0.3      # GNU Radio
```

`tx_waveforms` and `uhd_siggen` run until stopped. `tx_samples_from_file --repeat` loops the file until
stopped. File types: `--type float` = `.cf32`, `short` = `.cs16`. Keep |x| ≤ ~0.7 of full scale.

### Full duplex

```bash
$EX/txrx_loopback_to_file --tx-args type=b200 --rx-args type=b200 --tx-freq 433.92e6 --rx-freq 433.92e6 \
  --tx-rate 2e6 --rx-rate 2e6 --tx-gain 40 --rx-gain 20 --tx-ant TX/RX --rx-ant RX2 --tx-channels 0 --rx-channels 0 \
  --wave-type SINE --wave-freq 100e3 --nsamps 2000000 --type float --file duplex.cf32
```

Verified: transmitting a 100 kHz tone on TRX1 while receiving on RX1 (antennas on both), the receiver saw its
own signal at +100.1 kHz with **77.5 dB** SNR. The mirror image at −100 kHz was 38.7 dB down (TX + RX IQ
image combined at these gains). A single "U" (underflow) at the end of the run is normal: the TX stream
ends.

---

## 6. Python

### GNU Radio's Python (works on this Mac today)

Homebrew's UHD is built **without** the `uhd` Python module, but GNU Radio's own Python has **gr-uhd**:

```bash
GR=$(ls -d "$(brew --prefix gnuradio)"/libexec/venv/bin/python)
$GR radios/usrp-b210/tools/b210_gr_capture.py --freq 433.92e6 --rate 2e6 --gain 40 --seconds 1 -o cap.cf32
```

```python
from gnuradio import blocks, gr, uhd
tb = gr.top_block()
src = uhd.usrp_source("type=b200", uhd.stream_args(cpu_format="fc32", channels=[0]))
src.set_samp_rate(2e6); src.set_center_freq(433.92e6, 0); src.set_gain(40, 0); src.set_antenna("RX2", 0)
head = blocks.head(gr.sizeof_gr_complex, 2_000_000); sink = blocks.vector_sink_c()
tb.connect(src, head, sink); tb.run()
x = np.asarray(sink.data(), np.complex64)        # 1 s of IQ in NumPy
```

Verified: captured the HackRF's tone at +100.433 kHz, 62.7 dB SNR. The `.cf32` + `.sigmf-meta` it writes
open directly in `tools/iq_inspect.py`. For TX, use `uhd.usrp_sink` the same way (vector source → sink).

### UHD's Python API (Linux: `apt install python3-uhd`)

```python
import uhd
usrp = uhd.usrp.MultiUSRP("type=b200")
x = usrp.recv_num_samps(2_000_000, 433.92e6, 2e6, [0], 40)[0]       # (num, freq, rate, chans, gain)
usrp.send_waveform(tx_samples, 1.0, 433.92e6, 2e6, [0], 50)         # (samples, seconds, freq, rate, chans, gain)
```

Not available with Homebrew's UHD (`import uhd` fails). Build UHD with `-DENABLE_PYTHON_API=ON`, use
conda-forge `uhd`, or use the GNU Radio route above.

### Without bindings

`b210_rx.py` / `b210_tx.py` / the UHD examples write and read plain files. `rfkit.iq` handles
`.cf32/.cs16` (and SDRangel's `.sigmf-data`, including 32-bit `ci32_le`).

---

## 7. Other software

| Software | Status |
|---|---|
| **SDRangel** (installed, 7.27.2, bundles UHD 4.9) | Works: USRP input/output, demods, SigMF recording, REST API control. Needs `UHD_IMAGES_DIR`. Set **Gain mode: Manual** (the default AGC pumps on bursty signals). See [../../software/sdrangel/README.md](../../software/sdrangel/README.md) |
| **GNU Radio** 3.10 | `UHD: USRP Source/Sink` blocks, `uhd_fft`, `uhd_siggen`, `uhd_rx_cfile` |
| **SDR++** | macOS build has no USRP source. Linux/Windows builds include one |
| **SoapySDR** | `brew install soapyuhd` adds `driver=uhd` (not installed here) |
| **srsRAN / OpenAirInterface** | Common on the B210. The XC7A75T has enough logic for the stock B210 design. The 200T has room for custom FPGA work |
| **Vivado** | The vendor's FPGA project (Vivado 2024.1) is linked from their GitHub repo |

---

## 8. Utilities

| Tool (`$(brew --prefix uhd)/lib/uhd/examples` or `/utils`) | Use |
|---|---|
| `uhd_find_devices`, `uhd_usrp_probe` | Discovery / capabilities |
| `benchmark_rate` | USB throughput, drops (§4) |
| `usrp_list_sensors` | `temp`, `lo_locked`, `rssi`, `ref_locked` |
| `rx_ascii_art_dft` | Terminal spectrum |
| `txrx_loopback_to_file` | Full-duplex test |
| `utils/b2xx_fx3_utils` | FX3 reset / firmware (`--reset-device`) |
| `utils/uhd_images_downloader.py` | Images (use `setup_images.sh`) |
| `uhd_cal_*` | Not needed: the AD9361 calibrates DC/IQ itself |

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Could not find path for image: usrp_b200_fw.hex` / `<no images directory located>` | Images not installed or `UHD_IMAGES_DIR` unset. Run `setup_images.sh`. GUI apps need the LaunchAgent (or `launchctl setenv`) |
| Stuck at "Loading FPGA image", or an FPGA load error (Artix-7 board) | Ettus Spartan-6 image in place. Re-run `setup_images.sh --variant 75T` (or 200T for that bundle) |
| `Expected FPGA compatibility number X, but got Y` | FPGA image built for a different UHD. The vendor 75T image (compat 16) works with UHD 4.9 and 4.10 |
| `Operating over USB 2` | USB 2 cable/port/hub. Use a USB 3 (SuperSpeed) path |
| `O` printed / overruns, `U` / underruns | Rate too high for the host (§4). Lower it, use `--otw sc8`, write to SSD |
| Nothing received at the start of a capture | The ~3 s start-up: begin the transmission after samples are flowing |
| SDRangel shows the B210 but the levels don't follow the gain slider | Gain mode is AGC. Set it to Manual (`gainMode: 1`) |
| SDRangel finds no USRP | `UHD_IMAGES_DIR` not in its environment (launched before the LaunchAgent existed). Log out/in, or start it from a shell |
| Device busy | Another program (SDRangel, GNU Radio, a stuck `rx_samples_to_file`) holds it: `pgrep -lf "uhd\|samples\|SDRangel\|gnuradio"` |
| Stops responding after a crash | `$(brew --prefix uhd)/lib/uhd/utils/b2xx_fx3_utils --reset-device`, or unplug/replug |

---

## 10. When to choose the B210

- **RX and TX at once** (protocol testing, loopback, transponders).
- **Two coherent channels** (direction finding, MIMO, interferometry).
- **Dynamic range and accuracy**: 12-bit converters, low noise figure, a 0.5 ppm TCXO (on the Artix board).
- **Wide, drop-free bandwidth**: 30 MHz (one channel, sc16) to 56 MHz (sc8) over USB 3.
- The HackRF still covers 1–70 MHz and sweeps fast (`hackrf_sweep`). The RTL-SDR is the cheap always-on
  receiver.

---

## 11. Linux host notes (Ubuntu)

The sections above were written on macOS. Verified on Ubuntu (x86-64, 2026-10-26) with the same board:

| Item | State |
|---|---|
| UHD | apt `uhd-host`, `libuhd4.9.0` **4.9.0.1**, `python3-uhd`. The repo `.venv` is created with `--system-site-packages`, so `import uhd` works in it. A plain venv (for example another project's) does not see it |
| UHD examples | Not on `PATH`; in `/usr/libexec/uhd/examples/`. `b210_rx.py` searches that path |
| udev | The apt package installs `/usr/lib/udev/rules.d/60-uhd-host.rules`; the user needs to be in `plugdev` |
| UHD images | **Per host.** UHD loads the FX3 firmware and the FPGA image from the host's disk every time it opens the board, nothing is flashed, so the images installed on another machine do not help. Run `tools/setup_images.sh --variant 75T` once per host. It writes `~/.local/share/uhd/images` and adds `UHD_IMAGES_DIR` to `~/.zshrc` (open a new shell afterwards) |
| Device | Before UHD opens it, `lsusb` shows `2500:0020` (FX3 bootloader, normal). `uhd_find_devices` then finds `Custom_SDR_B210`. `uhd_usrp_probe --args type=b200`: B210, FW 8.0, USB 3, register loopback passed, RX 50–6000 MHz, RX gain 0–76 dB |
| SDR++ / SDRangel | The Ubuntu SDR++ package has no USRP source. SDRangel works once installed from its release `.deb` (the snap has no UHD) with `UHD_IMAGES_DIR` set; see [../../software/sdrangel/README.md](../../software/sdrangel/README.md) section 11. Otherwise use UHD (`b210_rx.py`, `uhd_fft`) or GNU Radio. SDR++: [../../software/sdr++/README.md](../../software/sdr++/README.md) section 11 |

### UHD 4.9 versus 4.10 differences

| Symptom | Cause / fix |
|---|---|
| `rx_samples_to_file`: `unrecognised option '--otw'` | UHD 4.9 names it `--wirefmt`; 4.10 renamed it `--otw`. `b210_rx.py --otw` now picks the right flag |
| `AssertionError: Invalid stream command: num_samps exceeds maximum value` | One stream command holds at most 2^28 samples (26 s at 10 MS/s). Use `--duration` (`b210_rx.py` switches to it automatically above that) |

### Capturing long and wide (measured 2026-10-26, 10 MS/s sc16 = 40 MB/s)

- 10 MS/s over USB 3 was clean for 5 minutes (12 GB, no overflow). The first runs that wrote **straight to disk
  overflowed intermittently** ("O", dropped samples, then `Timeout while streaming` and a truncated file even though the
  exit code was 0). Recording to RAM (`-o /dev/shm/cap.cs16`, 30 GB tmpfs) never dropped; copy the file to disk afterwards
  and check `overflow_reported` in the JSON. Re-check the sample count against rate x seconds.
- A single 10 MS/s capture centred between two targets covers both: 436.5 MHz sees 431.5–441.5 MHz, enough for signals
  at 433 and 440 MHz at the same time. Use `iq_inspect.py` for a first look, then extract narrow channels (mix, low-pass,
  decimate) with SciPy.
- **Constant spur lines at exact multiples of 8 MHz** (432.000 and 440.000 MHz here) are B210 clock/LO artefacts at
  gain 40. They never carry modulation and are not signals. Judge by whether the line appears and disappears with
  other activity, or sits at an integer multiple of the 16 MHz master clock.
- Over the air at ~1 m (gain 40, RX2): a 433.05 MHz OOK signal was 44 dB over the noise floor in a 2.4 kHz bin.
- **One program owns the board.** If SDRangel (or any UHD program) is open, `uhd_find_devices` reports "No UHD Devices
  Found" even though `lsusb` still shows `2500:0020`. Close the other program first (`pkill -x sdrangel`, exact name match).
- **Wide captures:** 30 MS/s sc16 (120 MB/s) streamed from the B210 on USB 3 into `/dev/shm` for 60 s gave one reported
  overflow; the file was still usable for burst work, but check `overflow_reported` and avoid relying on timing across it.
  The tool's own help notes that 56 MS/s needs `--otw sc8`; the tool picks the right wire-format flag per UHD version.
