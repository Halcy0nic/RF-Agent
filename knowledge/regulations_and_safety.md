# Regulations and safety

> Not legal advice. Rules differ by country and change. Check your national regulator (FCC in the US,
> Ofcom in the UK, BNetzA in Germany, ISED in Canada, ACMA in Australia...) before transmitting.

## Receiving

In most countries **receiving** radio signals is legal, with important exceptions:

- **Divulging or using** the contents of communications not meant for the public is often illegal even
  when receiving is legal (US: 47 U.S.C. §605 and the ECPA for cellular, cordless and pager content; many
  EU countries have similar secrecy-of-communications rules).
- Decrypting encrypted transmissions, or interfering with them, is a separate offence in many places.
- Some countries restrict scanners or specific bands (cellular).

Agent rule: analyse modulation and structure freely; **don't decode, store or publish personal content**
of third-party communications. Use your own devices and generated signals for protocol work.

## Transmitting

Transmitting needs authorisation: a licence (amateur, commercial) or a licence exemption (ISM/SRD rules
for **certified** devices). An SDR is not a certified device. In the US, Part 15 unlicensed operation
generally assumes a certified intentional radiator; a HackRF emitting arbitrary waveforms is at best
experimental. Practical, defensible options:

| Option | What it allows |
|---|---|
| **Cabled / shielded tests** | TX → attenuator (≥ 30–40 dB) → RX, or a shielded box / Faraday bag. Nothing radiates. The cleanest choice for experiments |
| **Very low power on an ISM band, short range, short duration** | What this bench does: 433.92 MHz, HackRF TX gain ≤ 20, amp off, ~1 m, bursts of seconds. Keep emissions minimal and inside the band |
| **Amateur radio licence** | Wide privileges on amateur bands (70 cm includes 420–450 MHz in the US; 430–440 in many countries) with ID requirements, no encryption, and power limits |
| **Experimental licence** (e.g. FCC Part 5) | Specific frequencies/power for research |

### ISM / SRD bands commonly used for bench tests

| Band | Region | Notes |
|---|---|---|
| 433.05–434.79 MHz | ITU Region 1 ISM (EU/UK SRD); US: Part 15.231 (periodic, limited) and amateur 70 cm | 433.92 MHz is the classic centre. **Default allow-list in `hackrf_tx.py`** |
| 863–870 MHz | EU SRD | Duty-cycle limits (0.1–10 % by sub-band) and ERP limits (25 mW typical) |
| 902–928 MHz | US/Region 2 ISM | Part 15.247/15.249 rules. Not in the default allow-list |
| 2.400–2.4835 GHz | Worldwide ISM | Crowded (Wi-Fi/BT). Avoid causing interference |

**Never transmit on** aviation (108–137 MHz, 960–1215 MHz incl. 1090 ADS-B), GNSS (1164–1610 MHz),
marine/emergency (156.8 MHz ch16, 121.5/243/406 MHz beacons), cellular, public-safety or broadcast bands.
Jamming is illegal essentially everywhere and can endanger lives.

### Technical emission hygiene

- Generate clean signals: shaped edges, continuous phase, headroom (no clipping). See signal_generation 01–05.
- Offset from the LO, and remember **the HackRF also emits its LO leakage at the centre and an IQ image at
  −offset** (measured here ≈ 50 dB below the wanted signal), plus **harmonics** (2f, 3f) because it has no
  output filter. Add a band-pass filter for anything beyond bench tests.
- Use the lowest power that works. At 1 m, HackRF `-x 20` with no amp gave 40–55 dB SNR, so go lower when
  you can.
- Keep transmissions short and bounded (`gtimeout`, finite files).

## Equipment safety

| Hazard | Rule |
|---|---|
| Receiver damage from strong RF | Never connect a transmitter directly to an SDR input. HackRF RX max −5 dBm, RTL-SDR about −10 dBm (damage ~+10 dBm), B210 0 dBm. Use ≥ 30–40 dB of attenuation in cabled loops |
| Transmitting into no load | Always attach an antenna or 50 Ω dummy load before TX (low-power SDRs survive it, but amplifiers don't) |
| Bias-tee DC | HackRF 3.3 V, RTL-SDR V4 4.5 V, both off by default. Turn on only for LNAs/active antennas. Never into a DC-shorted antenna or test equipment |
| ESD | Touch ground before handling SMA connectors and antennas, especially outdoors |
| RF exposure | Irrelevant at SDR power levels (mW). Respect MPE limits with amplifiers |
| Lightning | Disconnect outdoor antennas in storms. Ground masts |

## Guard rails built into this repo

- `radios/hackrf/tools/hackrf_tx.py`: frequency allow-list (433.05–434.79 MHz by default), TX gain cap 20 dB,
  amp off, 120 s maximum, `gtimeout` wrapper, kills any stray `hackrf_transfer`. Overrides need `--i-know`.
- `tests/ota_test.py` transmits only through that wrapper.
- All capture tools use bounded sample counts. SDR++ automation runs in an isolated config root.
- `.gitignore` excludes IQ recordings, captures and scratch (`tmp/`) so nothing captured is published by
  accident.
