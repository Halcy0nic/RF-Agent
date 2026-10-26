# Software

Up-to-date notes on the SDR software used with the radios in [../radios](../radios/README.md).

| Software | Folder / link | Use |
|---|---|---|
| **SDR++** | [sdr++/](sdr++/README.md) | Main receive GUI: waterfall, demod, baseband recorder. Fully scriptable through the rigctl server ([sdr++/rigctl.md](sdr++/rigctl.md)) |
| **SDRangel** | [sdrangel/](sdrangel/README.md) | GUI for the USRP B210 (and most other SDRs), RX and TX, SigMF recording. Fully scriptable through its REST API (`sdrangelctl.py`) |

## Other tools on this bench (versions as installed 2026-10-14)

| Tool | Version | What for | Where documented |
|---|---|---|---|
| `hackrf_*` (libhackrf) | 2026.01.3 | HackRF TX/RX/sweep | [../radios/hackrf](../radios/hackrf/README.md) |
| `rtl_*` (librtlsdr) | 2.0.2 | RTL-SDR capture/demod/survey | [../radios/rtl-sdr](../radios/rtl-sdr/README.md) |
| `rtl_433` | 25.12 | ISM gadget decoding, pulse analyzer, flex decoders | [../radios/rtl-sdr](../radios/rtl-sdr/README.md#rtl_433-decode-ism-band-gadgets-and-analyse-unknown-ookfsk) |
| UHD | 4.10.0.0 | USRP B210 (images in `~/.local/share/uhd/images`, Artix-7 FPGA image) | [../radios/usrp-b210](../radios/usrp-b210/README.md) |
| GNU Radio | 3.10.12 | Flowgraphs, `uhd_fft`, `uhd_siggen`, `uhd_rx_cfile`; its Python has gr-uhd for B210 scripting | [../radios/usrp-b210](../radios/usrp-b210/README.md#6-python) |
| SoapySDR | 0.8.1 | Vendor-neutral device API (`SoapySDRUtil --find`) | — |
| SDRangel | 7.27.2 (bundles UHD 4.9) | B210 GUI, REST API | [sdrangel/](sdrangel/README.md) |
| `sox` | installed | Audio conversion (`rtl_fm` → WAV) | [../radios/rtl-sdr](../radios/rtl-sdr/README.md) |
| `gtimeout` (coreutils) | installed | Time-limiting commands in scripts | — |

Other software worth knowing (not installed or documented here yet): **GQRX** (simple receiver),
**Universal Radio Hacker (URH)** (record, demodulate and reverse packet protocols, with replay), **Inspectrum**
(offline IQ analysis with cursors for symbol timing), **multimon-ng** (POCSAG/AFSK/DTMF), **dump1090/readsb**
(ADS-B), **SatDump** (weather satellites), **Gpredict** (satellite tracking, drives SDR++ via rigctl
`AOS`/`LOS`).

## Linux host (Ubuntu, checked 2026-10-26)

| Tool | Version | Note |
|---|---|---|
| UHD (apt) | 4.9.0.1 | `python3-uhd` installed. Examples in `/usr/libexec/uhd/examples`. 4.9 uses `--wirefmt` where 4.10 uses `--otw` ([../radios/usrp-b210](../radios/usrp-b210/README.md#11-linux-host-notes-ubuntu)) |
| GNU Radio (apt) | 3.10.12 | `gr-uhd`, `uhd_fft` |
| SDR++ (deb nightly) | 1.2.1-1517 | **No USRP source**; Airspy/HackRF/RTL-SDR etc. only ([sdr++](sdr++/README.md#11-linux-host-notes-ubuntu)) |
| SDRangel | not installed | |
| Hamlib `rigctl` | 4.6.5 | |

## Python environment for this repo

```bash
python3 -m venv --system-site-packages .venv && .venv/bin/pip install -r requirements.txt   # numpy, scipy, matplotlib, pillow
.venv/bin/python tests/test_loopback.py                               # 15 software tests, no hardware
```

`--system-site-packages` lets the venv import the distribution's `uhd` module (Linux `python3-uhd`). Without it, `import uhd` fails inside the venv.
