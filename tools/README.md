# Tools

Analysis CLIs that work on any IQ recording. They are built on [`../rfkit`](../rfkit) and need only NumPy
and Matplotlib. Run them with the repo venv (`.venv/bin/python`) from the repo root.

| Tool | Does | Example |
|---|---|---|
| [`iq_inspect.py`](iq_inspect.py) | First look: duration, levels/clipping, DC spike, strongest signals (absolute MHz, SNR, bandwidth), bursts with timing, overview PNG | `iq_inspect.py cap.wav` · `iq_inspect.py cap.cu8 --fs 2.048e6 --center 433.92e6` |
| [`rx_decode.py`](rx_decode.py) | Decode Morse, OOK (NRZ/Manchester), FSK/GFSK, BPSK/QPSK packets, NFM/WFM audio. Auto-locates the signal and estimates the rate. Also: `uart` (unknown framing, brute-forces bit order/offset/polarity for text), `ofdm` (finds FFT size and prefix, equalises), `chirp` (LoRa-style symbols), `dsss` (finds chip rate, recovers an unknown spreading code), `psk --search-rate` | `rx_decode.py fsk cap.wav` · `rx_decode.py psk cap.wav --rate 50e3 --order 4 --search-rate` · `rx_decode.py uart cap.cu8 --fs 2e6 --via ook` |
| [`survey.py`](survey.py) | Wide-band survey: time-frequency event table (when, how long, which frequency) sorted into carriers, beacons, hoppers and one-offs, plus a map PNG and JSON. Use it on a 10-30 MS/s capture before choosing a channel | `survey.py cap.cs16 --fs 30e6 --center 915e6` |
| [`sweep_plot.py`](sweep_plot.py) | `hackrf_sweep` / `rtl_power` CSV → heatmap PNG + strongest frequencies with duty cycle | `sweep_plot.py sweep.csv --top 15` |

Related tools elsewhere:

| Tool | Where |
|---|---|
| Signal generator (`generate.py`) | [../signal_generation](../signal_generation/README.md) |
| HackRF TX helper (`hackrf_tx.py`) | [../radios/hackrf/tools](../radios/hackrf/tools/hackrf_tx.py) |
| SDR++ control (`sdrppctl.py`, `sdrpp.py`) | [../software/sdr++/tools](../software/sdr++/rigctl.md) |
| SDRangel control (`sdrangelctl.py`) | [../software/sdrangel](../software/sdrangel/README.md) |
| B210 setup / RX / TX / GNU Radio capture | [../radios/usrp-b210/tools](../radios/usrp-b210/README.md) |
| [`winlist.swift`](winlist.swift) | macOS window ID by app name (case-insensitive) for `screencapture -l`; built on first use by the SDR++/SDRangel tools |
| Loopback + over-the-air tests | [../tests](../tests) |

`rfkit.survey` (the engine behind `survey.py`), `rfkit.bits.bruteforce` (text search over framings) and the new
receivers in `rfkit.dsp` (`refine_symbol_rate`, `combine_repeats`, `ofdm_*`, `css_demod`, `cyclic_lines`, `bpsk_soft_chips`,
`dsss_*`) are importable on their own; `tests/test_advanced.py` shows each on a generated signal.

All inputs: `.cs8 .cu8 .cs16 .cs32 .cf32 .wav (2-ch IQ) .sigmf-data`. Raw formats need `--fs` unless a
`<name>.sigmf-meta` sidecar sits next to them (`b210_rx.py` writes one). WAV/SigMF carry the rate.
SDR++ file names and SigMF sidecars also give the centre frequency.

`rx_decode.py` subtracts the mean (DC offset) before decoding (`--keep-dc` to disable). A HackRF
receiver's DC offset was as strong as a received FSK burst and pulled the FSK centre estimate onto 0 Hz.

`rx_decode.py` packet framing is the repo default: preamble `AA AA`, sync `2D D4`, length byte, payload,
CRC-16/CCITT-FALSE. Pass `--whiten` for PN9-whitened frames and `--manchester` for Manchester OOK.
Output is JSON (offset, estimated rate, packets with `crc_ok`, `inverted`, time), so an agent can parse it.
