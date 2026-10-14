# Software

Up-to-date notes on the SDR software used with the radios in [../radios](../radios/README.md).

| Software | Folder / link | Use |
|---|---|---|
| **SDR++** | [sdr++/](sdr++/README.md) | Main receive GUI: waterfall, demod, baseband recorder. Fully scriptable through the rigctl server ([sdr++/rigctl.md](sdr++/rigctl.md)) |

## Other tools on this bench (versions as installed 2026-10-14)

| Tool | Version | What for | Where documented |
|---|---|---|---|
| `hackrf_*` (libhackrf) | 2026.01.3 | HackRF TX/RX/sweep | [../radios/hackrf](../radios/hackrf/README.md) |
| `rtl_*` (librtlsdr) | 2.0.2 | RTL-SDR capture/demod/survey | [../radios/rtl-sdr](../radios/rtl-sdr/README.md) |
| `rtl_433` | 25.12 | ISM gadget decoding, pulse analyzer, flex decoders | [../radios/rtl-sdr](../radios/rtl-sdr/README.md#rtl_433-decode-ism-band-gadgets-and-analyse-unknown-ookfsk) |
| UHD | 4.10.0.0 | USRP B210 | [../radios/usrp-b210](../radios/usrp-b210/README.md) |
| GNU Radio | 3.10.12 | Flowgraphs, `uhd_fft`, `uhd_siggen`, `uhd_rx_cfile` | — |
| SoapySDR | 0.8.1 | Vendor-neutral device API (`SoapySDRUtil --find`) | — |
| SDRangel | installed | Alternative GUI with TX support and USRP plugins | — |
| `sox` | installed | Audio conversion (`rtl_fm` → WAV) | [../radios/rtl-sdr](../radios/rtl-sdr/README.md) |
| `gtimeout` (coreutils) | installed | Time-limiting commands in scripts | — |

Other software worth knowing (not installed or documented here yet): **GQRX** (simple receiver),
**Universal Radio Hacker (URH)** (record, demodulate and reverse packet protocols, with replay), **Inspectrum**
(offline IQ analysis with cursors for symbol timing), **multimon-ng** (POCSAG/AFSK/DTMF), **dump1090/readsb**
(ADS-B), **SatDump** (weather satellites), **Gpredict** (satellite tracking, drives SDR++ via rigctl
`AOS`/`LOS`).

## Python environment for this repo

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # numpy, scipy, matplotlib, pillow
.venv/bin/python tests/test_loopback.py                               # 15 software tests, no hardware
```
