# 11 · Transmitting generated signals

> **Before transmitting anything, read [../knowledge/regulations_and_safety.md](../knowledge/regulations_and_safety.md).**
> You are responsible for every emission. Use frequencies you may legally use, the lowest power that
> works, an antenna or dummy load, and bounded commands.

## HackRF (CS8)

```bash
# The canonical bounded, low-power command
gtimeout 10 hackrf_transfer -t signal.cs8 -f 433920000 -s 2000000 -x 20 -a 0
```

| Must match / decide | Why |
|---|---|
| `-s` = the rate you generated at | Otherwise every frequency and duration is scaled by the ratio |
| `-f` = the centre you planned offsets around | Your +100 kHz offset lands at f + 100 kHz |
| `-x` TX gain (0–47) | Start 0–20. 20 was plenty at 1 m on this bench |
| `-a 0` | Amp off. +14 dB is rarely needed on a bench |
| `gtimeout` / finite file | Nothing should ever run unbounded |

The guard-railed wrapper enforces all of that plus a frequency allow-list:

```bash
P=.venv/bin/python
$P radios/hackrf/tools/hackrf_tx.py signal.cs8 --freq 433.92e6 --rate 2e6 --gain 20 --occupied-bw 300e3
$P radios/hackrf/tools/hackrf_tx.py signal.cs8 --freq 433.92e6 --rate 2e6 --repeat 3 --gap 1
$P radios/hackrf/tools/hackrf_tx.py --dry-run signal.cs8 --freq 433.92e6 --rate 2e6
```

It refuses frequencies outside `ALLOWED_BANDS` (by default only 433.05–434.79 MHz), gain above the cap
(20), the amp, and runs over 120 s, unless you pass `--i-know`. `--occupied-bw` tells the band check how
wide the signal really is. Without it, the whole ±fs/2 span must fit inside the band. Edit
`ALLOWED_BANDS` for your licence and region.

### Repeating

Prefer generating repeats into the file (`--repeat N --gap S`) or looping a bounded number of times
(`hackrf_tx.py --repeat`). `hackrf_transfer -R` repeats forever. Only use it under `gtimeout`.

### Level and headroom

- Files from `rfkit.iq.save` peak at 80 % of full scale (`peak=0.8`, i.e. ±101 of ±127).
- Constant-envelope signals (FSK, FM, tones) can go to 90 %. Peaky ones (QPSK RRC ~4 dB PAPR, OFDM
  10–12 dB, multitone) need their **peaks** below full scale. `iq.save` normalises the peak, so the
  average power simply ends up lower. Raise `-x` to compensate rather than clipping.
- Signs of overdrive at the receiver: harmonics/odd spurs, a widened spectrum, constellation compression.

## USRP B210 (CF32/CS16)

```bash
EX=$(brew --prefix uhd)/lib/uhd/examples
.venv/bin/python -c "from rfkit import iq; x,_=iq.load('signal.cs8', fs=2e6); iq.save('signal.cf32', x, peak=0.7)"
gtimeout 10 $EX/tx_samples_from_file --args type=b200 --file signal.cf32 --type float \
    --rate 2e6 --freq 433.92e6 --gain 40 --ant TX/RX
```

TX gain is 0–89.75 dB. Start low and measure. See [../radios/usrp-b210/README.md](../radios/usrp-b210/README.md).
(Not verified on this bench: no B210 attached.)

## Streaming instead of files

For signals generated on the fly, pipe int8 bytes to `hackrf_transfer -t -`:

```python
import subprocess, numpy as np
from rfkit import iq, mod
p = subprocess.Popen(["gtimeout", "30", "hackrf_transfer", "-t", "-", "-f", "433920000", "-s", "2000000",
                      "-x", "20", "-a", "0"], stdin=subprocess.PIPE)
for k in range(10):                                   # bounded: 10 chunks
    chunk = mod.shift(mod.tone(0, 0.5, 2e6), 100e3 + 1e3 * k, 2e6)
    p.stdin.write(iq.to_bytes(chunk, "cs8", peak=0.8))
p.stdin.close(); p.wait()
```

The generator must keep up with the sample rate (2 MS/s = 4 MB/s). If it can't, you get underruns (gaps).
Pre-generating to a file is more reliable.

## After every transmission

```bash
pgrep -lf hackrf_transfer || echo "nothing transmitting"
```

## Field notes from this bench

- HackRF TX gain 20 at ~1 m → RTL-SDR (gain index 20 = 37.2 dB) saw 40–55 dB SNR for narrowband signals,
  16–18 dB for 67 kHz-wide QPSK. That's ample. Lower `-x` for weaker tests.
- Expect the received frequency about +2.2 kHz high at 433.92 MHz (crystal error), a faint carrier at the
  tuned centre and a mirror image at −offset, both ≈ 50 dB down.
