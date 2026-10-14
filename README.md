# RF-Agent

Documentation, knowledge and working tools for an all-purpose AI agent that automates **radio-frequency
engineering, signal analysis, digital signal processing and signal synthesis** with real software-defined
radios.

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
