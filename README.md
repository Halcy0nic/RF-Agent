# RF-Agent

Documentation, knowledge and working tools for an all-purpose AI agent that automates **radio-frequency
engineering, signal analysis, digital signal processing and signal synthesis** with real software-defined
radios.

Everything here is meant to be read and executed by an agent (and by people): dense reference pages,
copy-paste commands, and Python tools that emit JSON and PNGs. The tools were verified on a real
bench: HackRF One + RTL-SDR Blog V4 + SDR++ 1.3.0 on macOS, 2026-10-14.

## Layout

| Folder | Contents |
|---|---|
| [`radios/`](radios/README.md) | Usage docs per radio: [HackRF One](radios/hackrf/README.md), [RTL-SDR](radios/rtl-sdr/README.md), [USRP B210](radios/usrp-b210/README.md). Specs, every CLI tool, gain staging, troubleshooting, measured bench facts. TX helper `radios/hackrf/tools/hackrf_tx.py` |
| [`software/`](software/README.md) | Software suites. [SDR++](software/sdr++/README.md): UI, sources, recorder, config files, CLI flags, and [rigctl control + automated capture and screenshots](software/sdr++/rigctl.md), with `sdrpp.py` / `sdrppctl.py` |
| [`signal_generation/`](signal_generation/README.md) | Twelve walkthroughs on generating signals with Python/NumPy (IQ basics → OOK/FSK/PSK/QAM → chirps/OFDM → waterfall art → transmitting → over-the-air verification), `generate.py`, and standalone examples |
| [`knowledge/`](knowledge/README.md) | General RF/DSP knowledge: RF fundamentals, IQ and sampling, DSP, modulation reference, demodulation recipes, signal identification, analysis workflow, framing and protocol reversing, regulations and equipment limits |
| [`rfkit/`](rfkit/__init__.py) | Small NumPy library used by everything: `iq` (file I/O), `bits` (framing/CRC/line codes), `mod` (modulators), `dsp` (receivers), `plot` (PNGs) |
| [`tools/`](tools/README.md) | Analysis CLIs: `iq_inspect.py`, `rx_decode.py`, `sweep_plot.py` |
| [`tests/`](tests/) | `test_loopback.py` (16 software tests, no hardware) and `ota_test.py` (HackRF → RTL-SDR/SDR++ end-to-end) |

## Quick start

```bash
git clone <this repo> && cd RF-Agent
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python tests/test_loopback.py                              # no hardware needed

# Hardware check (macOS: brew install hackrf librtlsdr rtl_433 coreutils)
hackrf_info
rtl_test -t
```

Generate → transmit → receive → decode:

```bash
P=.venv/bin/python
$P signal_generation/generate.py fsk --text "HELLO" --rate 5000 --dev 20e3 --repeat 3 -o tmp/fsk.cs8
$P software/sdr++/tools/sdrppctl.py capture demo --freq 433.92e6 --seconds 5 --analyze -- \
   $P radios/hackrf/tools/hackrf_tx.py tmp/fsk.cs8 --freq 433.92e6 --rate 2e6 --gain 20
$P tools/rx_decode.py fsk tmp/sdrpp/caps/demo.wav            # -> 3 x "HELLO", crc_ok true
```

Analyse any recording:

```bash
$P tools/iq_inspect.py some_capture.wav                      # signals, SNR, bandwidth, bursts + overview PNG
```

## Verified on the bench (2026-10-14)

| Item | Result |
|---|---|
| HackRF One (fw 2.4.0) | RX via `hackrf_transfer`/`hackrf_sweep` and as an SDR++ source; TX at 433.92 MHz, gain 20, amp off |
| RTL-SDR Blog V4 | `rtl_test`, `rtl_sdr`, `rtl_fm`, `rtl_power`, `rtl_433` (live + file, pulse analyzer, flex decoder), SDR++ source |
| SDR++ v1.3.0 | Config profiles, isolated `-r` config root, every rigctl server command, recorder automation, window screenshots |
| Over the air, HackRF → RTL-SDR | 10/10 cases: tone, Morse, OOK, OOK-Manchester, 2-FSK, GFSK, BPSK, QPSK, NFM, waterfall text. Every packet CRC OK ([results](signal_generation/12_verifying_over_the_air.md)) |
| USRP B210 | **Not attached.** Docs checked against the UHD 4.10 tools only |

## Requirements

Python ≥ 3.9 with NumPy and Matplotlib (SciPy and Pillow optional; Pillow is needed for `generate.py
text`). Radio tools: `hackrf`, `librtlsdr` (≥ 2.0.2 for the RTL-SDR V4), `rtl_433`, `uhd` (B210),
`coreutils` (`gtimeout` on macOS, optional). SDR++ from its GitHub releases. Screenshot automation is macOS-specific
(`screencapture` + Swift); everything else is cross-platform.
