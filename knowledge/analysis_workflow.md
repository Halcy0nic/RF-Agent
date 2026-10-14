# Analysis workflow (and rules for agents)

The method that works, end to end, plus the operating rules an autonomous agent must follow when it
controls real radios.

## The loop

```text
1. SURVEY      where is the energy?           hackrf_sweep / rtl_power → tools/sweep_plot.py
2. CAPTURE     record IQ, short and bounded    SDR++ rigctl recorder, rtl_sdr -n, hackrf_transfer -n
3. INSPECT     look before you decode          tools/iq_inspect.py → overview PNG + JSON
4. IDENTIFY    what modulation/protocol?       knowledge/signal_identification.md, rtl_433 -A
5. DEMODULATE  waveform → symbols → bits       knowledge/demodulation_recipes.md, tools/rx_decode.py
6. DECODE      bits → frames → payload         line codes, sync, CRC (knowledge/line_coding_and_framing.md)
7. VERIFY      prove it                        CRC passes, repeats agree, re-transmit and re-decode
```

### 1 · Survey

```bash
hackrf_sweep -f 400:500 -w 50000 -N 30 -r tmp/sweep.csv          # 30 sweeps, ~seconds
rtl_power -f 430M:440M:10k -g 37 -i 5 -e 2m tmp/power.csv        # 2 minutes of activity
.venv/bin/python tools/sweep_plot.py tmp/sweep.csv               # strongest frequencies + duty cycle + PNG
```

Look for peaks over the floor and their **duty** (fraction of sweeps active). Bursty signals need several
sweeps or a long `rtl_power` run to be caught.

### 2 · Capture

- Centre 50–200 kHz away from the target (DC spike). Choose the smallest sample rate that covers it.
- Gain: the lowest setting where the target is clearly above the floor. No AGC.
- **5–15 seconds**, and for bursty targets long enough to catch ≥ 3 bursts.
- Name files with centre frequency and rate, or use SDR++ WAV/SigMF, which carry metadata.

```bash
P=.venv/bin/python; T=software/sdr++/tools/sdrppctl.py
$P $T setup --freq 433.92e6 --rate 1.024e6 --gain 20 && $P $T record 10 --out tmp/cap.wav && $P $T shot tmp/cap.png
# or without SDR++:
rtl_sdr -f 433920000 -s 1024000 -g 37.2 -n 10240000 tmp/cap.cu8
```

### 3 · Inspect

```bash
$P tools/iq_inspect.py tmp/cap.wav           # carriers (abs MHz, SNR, BW), bursts (start, duration), clipping
```

Open the PNG. Note the offset, bandwidth, burst length and period, and whether the envelope is
constant.

### 4–6 · Identify, demodulate, decode

Follow [demodulation_recipes.md](demodulation_recipes.md). Work **one rung at a time** and check each
with a plot. When a CRC fails, go back to the earlier stage (rate, polarity, alignment, convention). Don't
"fix" the CRC.

### 7 · Verify

- CRC/checksum passes, and repeated packets decode identically.
- Decoded values make sense (temperatures, IDs, counters that increment).
- For your own signals: transmit a known payload and confirm it round-trips (`tests/ota_test.py`).

## Using vision models on waterfalls

Screenshots help identify the modulation family. Measurements must come from IQ. When asking a
multimodal model:

1. **Image**: spectrum + waterfall + the settings panel, with the frequency axis visible
   (`sdrppctl.py shot`, or `rfkit.plot.overview`).
2. **Context**: radio, centre, sample rate, gain, FFT size/rate. E.g. "RTL-SDR V4, 433.92 MHz,
   1.024 MS/s, gain 37 dB, FFT 8192 @ 30 fps".
3. **One question**: "What modulation is the burst at +100 kHz and what symbol rate does the striping
   suggest?"

The model proposes and the IQ measurements decide.

## Rules for an agent driving radios

These are mandatory.

1. **Every command is bounded.** `-n` samples, `-1`/`-N` sweeps, `-T`/`-e` timers, `--duration`, or
   `gtimeout N`. Never start a stream that runs until killed. Never use `hackrf_transfer -R` without
   `gtimeout`.
2. **Transmit only when the human has approved it, on approved frequencies, at the approved power.** On
   this bench (approved 2026-10-14): HackRF TX at **433.92 MHz** only, **TX gain ≤ 20, amp off**, short
   bursts. Use `radios/hackrf/tools/hackrf_tx.py`, which enforces it. Anything else: ask first.
3. **Verify nothing is left transmitting**: `pgrep -lf hackrf_transfer` must be empty after every TX.
4. **One program per radio.** Check `pgrep -lf "sdrpp|rtl_|hackrf_|gqrx|uhd"` before opening a device. Close
   what you opened.
5. **Don't clobber the user's software config.** Drive SDR++ in isolated mode (`-r tmp/sdrpp/root`, the
   default in `software/sdr++/tools/sdrpp.py`). If you must touch the real config, back it up first and
   restore it after.
6. **Scratch goes in `tmp/`** (git-ignored). Recordings are large. Delete them when done, and never commit
   IQ files.
7. **Measure, don't assume.** Report SNR, frequency error and bandwidth from data, and say what wasn't
   verified (e.g. "B210 docs not hardware-tested").
8. **Receiving is passive, but decoding has rules too.** Don't decode or publish the contents of private
   communications (cellular, pagers carrying personal data, encrypted traffic). Many jurisdictions
   restrict *divulging* intercepted content even when receiving is legal. See
   [regulations_and_safety.md](regulations_and_safety.md).
9. **Public repo hygiene.** Don't commit captures of other people's signals, device serials beyond your
   own, credentials, or private challenge material.
