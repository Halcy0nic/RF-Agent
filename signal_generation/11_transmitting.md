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

## USRP B210

`radios/usrp-b210/tools/b210_tx.py` plays any file `generate.py` makes (it converts `.cs8` to complex float):

```bash
P=.venv/bin/python
$P radios/usrp-b210/tools/b210_tx.py signal.cs8 --freq 433.92e6 --rate 2e6 --gain 50                 # TRX1
$P radios/usrp-b210/tools/b210_tx.py signal.cs8 --freq 433.92e6 --rate 2e6 --gain 50 --channel 1     # TRX2
```

| Parameter | Notes |
|---|---|
| `--rate` = the rate you generated at | Same rule as the HackRF |
| `--gain` (0–89.75 dB) | Measured at ~1 m into a HackRF: 40 → 44.5 dB SNR, 50 → 54.4 dB, 60 → 57.2 dB. **Gain 50 ≈ HackRF `-x 20`** |
| `--channel 0/1` | TX comes out of that channel's `TX/RX` port (TRX1 / TRX2 on the Artix-7 board) |
| `--peak` | Rescale to this fraction of full scale (default 0.7). The 12-bit DAC keeps SNR at lower levels than the HackRF |
| start-up | ~3 s of device set-up (firmware, FPGA, LO lock) before RF comes out |

Over the air into the HackRF at gain 50, all nine decodable cases (Morse, OOK, Manchester, FSK, GFSK, BPSK,
QPSK, NFM) decoded: `python tests/ota_b210.py --dir b210tohackrf --tx-gain 50`. Raw UHD equivalent:
`$(brew --prefix uhd)/lib/uhd/examples/tx_samples_from_file --args type=b200 --file signal.cf32 --type float
--rate 2e6 --freq 433.92e6 --gain 50 --ant TX/RX`. See [../radios/usrp-b210/README.md](../radios/usrp-b210/README.md).

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
pgrep -lf "hackrf_transfer|tx_samples_from_file|tx_waveforms" || echo "nothing transmitting"
```

## Field notes from this bench

- HackRF TX gain 20 at ~1 m → RTL-SDR (gain index 20 = 37.2 dB) saw 40–55 dB SNR for narrowband signals,
  16–18 dB for 67 kHz-wide QPSK.
- Expect the received frequency about +2.2 kHz high at 433.92 MHz (crystal error), a faint carrier at the
  tuned centre and a mirror image at −offset, both ≈ 50 dB down.
