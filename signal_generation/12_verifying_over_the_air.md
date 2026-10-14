# 12 · Verifying over the air

A generated file is only proven when a separate receiver decodes it. This bench closes the loop
automatically:

```text
generate.py ─► case.cs8 ─► hackrf_tx.py (433.92 MHz, TX gain 20, amp off, bounded)
                                 │  ~1 m of air
SDR++ (RTL-SDR Blog V4, 1.024 MS/s, gain idx 20 = 37.2 dB, isolated config) ◄─ rigctl \recorder_start/stop
        └─► case.wav ─► sdrppctl.py analyze (carrier, SNR, PNG) ─► rx_decode.py ─► PASS/FAIL
```

```bash
.venv/bin/python tests/ota_test.py                 # all 13 cases (10 decoded, 3 visual), ~4 minutes
.venv/bin/python tests/ota_test.py ook fsk         # filter by name
.venv/bin/python tests/ota_test.py --tx-gain 10    # weaker link
```

`python tests/make_doc_images.py` then rebuilds every figure in `knowledge/images/` and
`signal_generation/images/` from these captures. Chirp, CSS and AM were captured in a later run (same
settings) for those figures.

Outputs in `tmp/ota/`: `<case>.cs8` (transmitted), `<case>.wav` (received), `<case>.png` (analysis),
`<case>_sdrpp.png` (SDR++ window), `<case>.json` (decoder output), `summary.json`.

## Results (2026-10-14, final run)

| Case | Generated with | Result | SNR (peak bin) | Decoded |
|---|---|---|---|---|
| tone | `tone --seconds 1.5` | carrier at **+102.063 kHz** (nominal +100) | 53.3 dB | — (visual check) |
| morse | `morse --text "RF AGENT TEST" --wpm 20` | **PASS** | 52.0 dB | `RF AGENT TEST` |
| ook | `ook --rate 1000 --repeat 3` | **PASS** 3/3 CRC OK | 42.6 dB | `OOK HELLO` ×3, rate 1000.1 |
| ook_manchester | `ook --manchester --rate 1000 --repeat 3` | **PASS** 3/3 | 42.3 dB | `MANCHESTER` ×3, rate 1000.0 |
| fsk | `fsk --rate 5000 --dev 20e3 --repeat 3` | **PASS** 3/3 | 36.7 dB | `FSK HELLO` ×3, rate 4999.7 |
| gfsk | `fsk --bt 0.5 --rate 10000 --dev 10e3 --repeat 3` | **PASS** 3/3 | 32.0 dB | `GFSK HELLO` ×3 |
| bpsk | `psk --scheme bpsk --rate 50e3 --repeat 3` | **PASS** 3/3 | 17.9 dB | `BPSK HELLO` ×3 |
| qpsk | `psk --scheme qpsk --rate 50e3 --repeat 3` | **PASS** 3/3 | 16.9 dB | `QPSK HELLO` ×3 |
| nfm | `fm --audio-tone 1000 --dev 5e3` | **PASS** | 45.3 dB | 1000.0 Hz audio tone |
| text | `text --text "RF AGENT" --bw 150e3` | readable upright in SDR++ | 26.8 dB | (visual: see [09](09_waterfall_art.md)) |
| chirp | `chirp --f0 -100e3 --f1 100e3 --seconds 0.05 --repeat 20` | visual | 24.2 dB | see [08](08_chirps_spread_ofdm.md) |
| css | `css --sf 8 --bw 125e3 --repeat 4` | visual | 21.3 dB | see [08](08_chirps_spread_ofdm.md) |
| am | `am --audio-tone 800` | visual | 49.4 dB | carrier + ±800 Hz sidebands |

The SNR column is the strongest PSD bin over the noise floor across the 1.024 MHz span. Wideband signals
spread their power over more bins, which is why PSK reads lower; it's not a weaker link.

## What the loop taught us (fixes now in rfkit / rx_decode)

| Problem seen | Root cause | Fix |
|---|---|---|
| Every signal ~2.06–2.18 kHz high | HackRF + RTL crystal error (~5 ppm at 434 MHz) | Decoders locate the signal instead of trusting the nominal offset |
| Short PSK packets "not found" | 1–2 ms packets in a 3 s file: diluted ~30 dB in a time-averaged PSD | Time-gate to bursts before the spectral search (`dsp.gate`) |
| OOK packet split in two | Runs of 0-bits are silent, so the burst detector split the packet | Merge gaps shorter than ~24 bit times |
| Last OOK/Manchester bits missing | Packet ends with no energy | Widen burst windows a few symbols |
| FSK decoded at double rate | Threshold at the median sat on the majority tone | Otsu threshold between the tone clusters |
| FSK channel cut one tone off | Strongest peak is a tone, not the centre | Discriminator midpoint (`refine_center`) |
| GFSK packet tails corrupted | 0.8 % symbol-rate estimate error accumulates | PLL slicer (`dsp.slice_symbols_pll`) |
| NFM audio "0 Hz" | Spectral centroid pulled toward unrelated energy | Discriminator centring + DC removal from audio |

## Doing it by hand

```bash
P=.venv/bin/python
$P signal_generation/generate.py ook --text "HELLO" --rate 1000 --repeat 3 -o tmp/ook.cs8
$P software/sdr++/tools/sdrppctl.py capture ook_manual --freq 433.92e6 --seconds 5 --shots 1 --analyze -- \
   $P radios/hackrf/tools/hackrf_tx.py tmp/ook.cs8 --freq 433.92e6 --rate 2e6 --gain 20 --occupied-bw 300e3
$P tools/rx_decode.py ook tmp/sdrpp/caps/ook_manual.wav
```

Without SDR++ (the RTL-SDR used directly). Run the receiver in the background, then transmit:

```bash
rtl_sdr -f 433920000 -s 1024000 -g 37.2 -n 6144000 tmp/rx.cu8 &       # 6 s
sleep 1; $P radios/hackrf/tools/hackrf_tx.py tmp/ook.cs8 --freq 433.92e6 --rate 2e6 --gain 20 --occupied-bw 300e3
wait; $P tools/rx_decode.py ook tmp/rx.cu8 --fs 1.024e6
```

## Software-only verification (no radios)

```bash
.venv/bin/python tests/test_loopback.py      # 16 tests: every modulator through noise + CFO + delay → decoder
$P tools/rx_decode.py fsk tmp/fsk.cs8 --fs 2e6   # any generated file decodes as-is
```
