# Tools

Analysis CLIs that work on any IQ recording. They are built on [`../rfkit`](../rfkit) and need only NumPy
and Matplotlib. Run them with the repo venv (`.venv/bin/python`) from the repo root.

| Tool | Does | Example |
|---|---|---|
| [`iq_inspect.py`](iq_inspect.py) | First look: duration, levels/clipping, DC spike, strongest signals (absolute MHz, SNR, bandwidth), bursts with timing, overview PNG | `iq_inspect.py cap.wav` · `iq_inspect.py cap.cu8 --fs 2.048e6 --center 433.92e6` |
| [`rx_decode.py`](rx_decode.py) | Decode Morse, OOK (NRZ/Manchester), FSK/GFSK, BPSK/QPSK packets, NFM/WFM audio. Auto-locates the signal and estimates the rate | `rx_decode.py fsk cap.wav` · `rx_decode.py psk cap.wav --rate 50e3 --order 4` |
| [`sweep_plot.py`](sweep_plot.py) | `hackrf_sweep` / `rtl_power` CSV → heatmap PNG + strongest frequencies with duty cycle | `sweep_plot.py sweep.csv --top 15` |

Related tools elsewhere:

| Tool | Where |
|---|---|
| Signal generator (`generate.py`) | [../signal_generation](../signal_generation/README.md) |
| Guard-railed HackRF TX (`hackrf_tx.py`) | [../radios/hackrf/tools](../radios/hackrf/tools/hackrf_tx.py) |
| SDR++ control (`sdrppctl.py`, `sdrpp.py`) | [../software/sdr++/tools](../software/sdr++/rigctl.md) |
| Loopback + over-the-air tests | [../tests](../tests) |

All inputs: `.cs8 .cu8 .cs16 .cf32 .wav (2-ch IQ) .sigmf-data`. Raw formats need `--fs`. WAV/SigMF carry
the rate. SDR++ file names also give the centre frequency.

`rx_decode.py` packet framing is the repo default: preamble `AA AA`, sync `2D D4`, length byte, payload,
CRC-16/CCITT-FALSE. Pass `--whiten` for PN9-whitened frames and `--manchester` for Manchester OOK.
Output is JSON (offset, estimated rate, packets with `crc_ok`, `inverted`, time), so an agent can parse it.
