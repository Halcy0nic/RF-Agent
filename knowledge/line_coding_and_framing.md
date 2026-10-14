# Line coding, framing and protocol reversing

After demodulation you have a stream of symbols. Getting from there to meaningful bytes is its own
discipline. Generation-side details are in
[../signal_generation/07_framing_and_coding.md](../signal_generation/07_framing_and_coding.md). This page
is about **recovering** structure from an unknown stream.

## Layer model

```text
RF ─► demodulated waveform ─► sliced symbols ─► line-decoded bits ─► framed bytes ─► fields/payload
          (rung 2-3)              (rung 4)          (Manchester...)    (preamble/sync/CRC)  (ASCII/BCD/Base64)
```

A failure at any layer looks like random bits. Debug layer by layer.

## Identify the line code from the symbol stream

| Observation | Line code |
|---|---|
| Run lengths are only 1T and 2T, never 3T+ | Manchester (or biphase). Decode pairs |
| Pulses of two different widths with a fixed period | PWM (short = 0, long = 1, or the reverse) |
| Fixed-width pulses with variable gaps | PPM (gap encodes the bit) |
| Arbitrary runs, long runs present | NRZ (maybe NRZI, maybe whitened) |
| Long preamble of 1010… then data | NRZ/Manchester with a training preamble |
| Mostly random-looking bits with no long runs, but a clear sync word | Whitened NRZ |

`rtl_433 -A` automates much of this for OOK/FSK pulse trains: it prints pulse/gap width histograms and
guesses PCM (NRZ), PWM, PPM or Manchester.

## Find the frame boundaries

1. **Repeated transmissions**: most devices send the same packet 2–10 times. Correlate bursts against
   each other. The aligned region is the packet.
2. **Preamble**: a run of alternating bits (`0xAA`/`0x55`) or a fixed tone. It ends where the pattern
   breaks.
3. **Sync word**: the first non-preamble 16–32 bits that are identical in every packet. Common ones:
   `0x2DD4` (CC1101 default), `0xD391` (also common in TI parts), `0x7CD215D8` (POCSAG frame sync),
   `0x8E89BED6` (BLE advertising access address), `0x0000F0F0`. Search for known ones with
   `bits.find(stream, pattern, max_errors=1)`.
4. **Length field**: a byte right after the sync that matches the number of following bytes (± CRC).

## Bit order and polarity checklist

Try all combinations when bytes look "almost" right:

- MSB-first vs LSB-first per byte (`bits.to_bytes(b, lsb_first=True)`).
- Inverted bits (FSK tone mapping, active-low OOK).
- Manchester convention (IEEE vs Thomas) and pair alignment (offset by one chip).
- Whitening (`bits.whiten` with PN9 seed 0x1FF, or the device's own LFSR).
- Byte alignment: shift the start by 1–7 bits.

## Hunting the checksum

- The last 1, 2 or 4 bytes change whenever any other byte changes → checksum/CRC.
- Try a sum of bytes mod 256, XOR of bytes, CRC-8 (0x07, 0x31 Dallas/Maxim), CRC-16 CCITT
  (0x1021, init 0xFFFF or 0x0000), CRC-16/IBM (0x8005), and CRC-32.
- Collect packets that differ in one bit. For a CRC, the checksum difference is the CRC of the difference
  (linearity). Solvers like **reveng** use this to find poly/init/xorout from a few examples.
- Remember that preamble and sync are usually **not** covered by the CRC, and the length byte usually is.

## Payload encodings

| Pattern | Likely |
|---|---|
| Bytes 0x20–0x7E | ASCII text |
| `[A-Za-z0-9+/]` with `=` padding | Base64 → decode again |
| Nibbles 0–9 only | BCD (meters, pager numeric) |
| 7-bit groups, LSB first | POCSAG alphanumeric / GSM-7 |
| Fields that increment by 1 per packet | Rolling counter (rolling-code remotes encrypt it: KeeLoq) |
| Two's-complement 12-bit value ÷ 10 | Temperature in 0.1 °C (weather sensors) |

## Error correction you'll meet

| Code | Where | Notes |
|---|---|---|
| BCH(31,21) + parity | POCSAG | Corrects 2 bits per 32-bit codeword |
| Hamming(7,4)/(8,4) | LoRa (CR 4/5–4/8), some telemetry | |
| Convolutional K=7 r=1/2 + Viterbi | 802.11, GSM, satellites | |
| Reed-Solomon | DVB, CDs, QR, deep space | Byte-oriented |
| Repetition | Cheap remotes (send 5–10×) | Majority vote across repeats |

## Worked mini-example (from this bench)

`rtl_433 -A` on a 1 kbit/s OOK capture reported pulse widths 984/1983/2984/3984/5984 µs and gaps
1015/2016/3016/4014/6015 µs, all multiples of ~1000 µs: **NRZ at 1000 bit/s**. A flex decoder
`-X "n=x,m=OOK_PCM,s=1000,l=1000,r=8000,preamble=aaaa2dd4"` printed `094f4f4b2048454c4c4fd7b9`:

```text
09                      length = 9
4f 4f 4b 20 48 45 4c 4c 4f   "OOK HELLO"
d7 b9                   CRC-16/CCITT-FALSE over [09 .. 4f]  ✓
```
