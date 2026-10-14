# 07 · Framing, line codes and checksums

Modulation moves bits through the air. **Framing and coding** let a receiver find the bits, align them
into bytes and prove they are right. A perfectly demodulated waveform is useless if the receiver can't tell
where the packet starts.

## The standard sub-GHz packet

```text
┌──────────┬────────────┬────────┬──────────────┬──────────────┐
│ preamble │ sync word  │ length │   payload    │    CRC-16    │
│ AA AA .. │   2D D4    │   N    │  N bytes     │  over len+pl │
└──────────┴────────────┴────────┴──────────────┴──────────────┘
```

| Field | Job |
|---|---|
| **Preamble** `1010…` | Lets the receiver set its gain/threshold, lock its symbol clock and (for FSK/PSK) its carrier |
| **Sync word** | A pattern with low autocorrelation sidelobes that marks "byte 0 starts here". `2D D4` is the TI CC1101 default and widely copied |
| **Length** | How many bytes to read |
| **Payload** | Data (binary, ASCII, Base64 ...) |
| **CRC** | Error detection. If it fails, the bits are wrong. Fix the demodulation, don't "fix" the CRC |

```python
from rfkit import bits
b = bits.frame(b"HELLO")                         # AA AA 2D D4 05 'HELLO' CRC16 -> numpy 0/1 array
b = bits.frame(b"HELLO", preamble=b"\xaa" * 8)   # longer preamble for PSK
b = bits.frame(b"HELLO", whitening=True)         # PN9-whiten len+payload+CRC
r = bits.parse_frame(received_bits)              # {'start', 'payload', 'crc_ok', 'inverted'} or None
```

`parse_frame` tolerates one bit error in the sync word by default and also tries the inverted stream (FSK
and PSK polarity is often unknown).

## CRCs

| Name | Poly | Init | Check value of `"123456789"` | rfkit |
|---|---|---|---|---|
| CRC-16/CCITT-FALSE | 0x1021 | 0xFFFF | 0x29B1 | `bits.crc16_ccitt` |
| CRC-8/SMBUS | 0x07 | 0x00 | 0xF4 | `bits.crc8` |
| CRC-32 (zlib) | 0x04C11DB7 refl. | 0xFFFFFFFF | 0xCBF43926 | `bits.crc32` |
| 8-bit sum | — | — | — | `bits.checksum8` |

When reversing an unknown protocol, the check value test pins down a CRC variant fast. Tools like
`reveng` (CRC RevEng) can solve for poly/init/xorout from a few known packets.

## Line codes

| Code | Rule | Why | rfkit |
|---|---|---|---|
| **NRZ-L** | 1 = high, 0 = low for the whole bit | Simplest, bandwidth-efficient, no guaranteed transitions | (plain bits) |
| **Manchester (IEEE 802.3)** | 1 = low→high (`01`), 0 = high→low (`10`) | A transition in every bit: self-clocking, DC-free. Costs 2× bandwidth | `manchester_encode(b, ieee=True)` |
| **Manchester (G.E. Thomas)** | Opposite: 1 = `10`, 0 = `01` | Same, other convention. Check both | `ieee=False` |
| **NRZI** | 0 = toggle, 1 = hold (USB/HDLC style) | Polarity-independent | `nrzi_encode/decode` |
| **Differential** | d[n] = d[n−1] ⊕ b[n] | Removes PSK phase ambiguity | `differential_encode/decode` |
| **PWM** | Pulse width encodes the bit | Cheap remotes | `mod.pwm_ook` |

Manchester-coded OOK on air (as `generate.py ook --manchester` makes it): the preamble stays plain
`1010…` at the chip rate, then the sync and body are Manchester chips. `--rate` is the **data** rate, so
the chip rate on air is double. Receiver side:

```python
chips = dsp.slice_symbols_pll(envelope, fs / (2 * bit_rate))
k = bits.find(chips, bits.manchester_encode(bits.from_bytes(b"\x2d\xd4")))[0]   # sync in chips
data, bad_pairs = bits.manchester_decode(chips[k:])          # bad_pairs > 0 -> wrong phase or convention
```

Tip: if the measured transition rate is twice what you expect, try Manchester. If decoding gives garbage
with many invalid pairs, shift by one chip or flip the convention.

## Whitening (scrambling)

Long runs of identical bits starve the receiver's clock recovery, and OOK zeros are silent. Whitening XORs
the data with a pseudo-random sequence (PN9: x⁹ + x⁵ + 1, seed 0x1FF, as in CC1101/SX127x) so the
on-air bits look random. The same XOR undoes it:

```python
w = bits.whiten(b)           # and bits.whiten(w) == b
```

## Error correction (FEC), briefly

CRCs only detect errors. To **correct** them, radios add redundancy: repetition (send 3×, majority vote),
Hamming(7,4) (LoRa uses Hamming-like codes), BCH (POCSAG: BCH(31,21)), convolutional codes + Viterbi
(802.11, GSM), Reed-Solomon (DVB, QR), LDPC/turbo (modern cellular/Wi-Fi). For test signals, sending the
packet 3–5 times is usually enough.

## Text packing

| Encoding | Recognise it by |
|---|---|
| ASCII | Bytes 0x20–0x7E |
| Base64 | A–Z a–z 0–9 + /, length a multiple of 4, `=` padding |
| 7-bit packed (POCSAG alpha, SMS GSM-7) | Characters LSB-first across byte boundaries |
| BCD | Nibbles 0–9 (pager numeric, meters) |
| Morse | Variable-length dots/dashes (see guide 03) |

## Designing your own test packet: checklist

- Preamble ≥ 16 bits (≥ 64 for PSK), alternating.
- A 16- or 32-bit sync word with good autocorrelation (`2DD4`, `D391`, `7CD215D8`, Barker-like).
- An explicit length (or fixed size), and a CRC-16.
- Repeat 3× with gaps ≥ 10 bit times, and pad silence before the first packet.
- Document bit order (MSB first here), bit rate, deviation and offset next to the file.
