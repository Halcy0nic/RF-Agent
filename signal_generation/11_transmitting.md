# 11 · Transmitting generated signals

## HackRF (CS8)

```bash
# Transmit a generated file once
hackrf_transfer -t signal.cs8 -f 433920000 -s 2000000 -x 20 -a 0
```

| Parameter | Notes |
|---|---|
| `-s` = the rate you generated at | Otherwise every frequency and duration is scaled by the ratio |
| `-f` = the centre you planned offsets around | Your +100 kHz offset lands at f + 100 kHz |
| `-x` TX gain (0–47 dB) | For reference, 20 gave 40–55 dB SNR at 1 m on this bench |
| `-a 0/1` | RF amp off/on (~+14 dB) |
| `-R` | Repeat the file until stopped |

The helper in `radios/hackrf/tools/` prints the file's duration, replays it N times with a gap and can
show the command without running it:

```bash
P=.venv/bin/python
$P radios/hackrf/tools/hackrf_tx.py signal.cs8 --freq 433.92e6 --rate 2e6 --gain 20
$P radios/hackrf/tools/hackrf_tx.py signal.cs8 --freq 915e6 --rate 2e6 --gain 30 --amp --repeat 3 --gap 1
$P radios/hackrf/tools/hackrf_tx.py --dry-run signal.cs8 --freq 433.92e6 --rate 2e6
```

### Repeating

Three ways: generate repeats into the file (`generate.py --repeat N --gap S`), replay the file N times
(`hackrf_tx.py --repeat N --gap S`), or loop it continuously with `hackrf_transfer -R`.

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
$EX/tx_samples_from_file --args type=b200 --file signal.cf32 --type float \
    --rate 2e6 --freq 433.92e6 --gain 40 --ant TX/RX
```

TX gain is 0–89.75 dB. Start low and measure. See [../radios/usrp-b210/README.md](../radios/usrp-b210/README.md).
(Not verified on this bench: no B210 attached.)

## Streaming instead of files

For signals generated on the fly, pipe int8 bytes to `hackrf_transfer -t -`:

```python
import subprocess, numpy as np
from rfkit import iq, mod
p = subprocess.Popen(["hackrf_transfer", "-t", "-", "-f", "433920000", "-s", "2000000",
                      "-x", "20", "-a", "0"], stdin=subprocess.PIPE)
for k in range(10):                                   # 10 chunks
    chunk = mod.shift(mod.tone(0, 0.5, 2e6), 100e3 + 1e3 * k, 2e6)
    p.stdin.write(iq.to_bytes(chunk, "cs8", peak=0.8))
p.stdin.close(); p.wait()
```

The generator must keep up with the sample rate (2 MS/s = 4 MB/s). If it can't, you get underruns (gaps).
Pre-generating to a file is more reliable.

## Checking for a running transmitter

```bash
pgrep -lf hackrf_transfer || echo "nothing transmitting"
```

## Field notes from this bench

- HackRF TX gain 20 at ~1 m → RTL-SDR (gain index 20 = 37.2 dB) saw 40–55 dB SNR for narrowband signals,
  16–18 dB for 67 kHz-wide QPSK.
- Expect the received frequency about +2.2 kHz high at 433.92 MHz (crystal error), a faint carrier at the
  tuned centre and a mirror image at −offset, both ≈ 50 dB down.
