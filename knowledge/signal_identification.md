# Signal identification

## Waterfall fingerprints

Three visual dimensions: **brightness = power, horizontal = frequency, vertical = time.** The spectrum
answers "where in frequency", the waterfall "when and how".

| Looks like | Probably |
|---|---|
| Thin solid vertical line, constant | Unmodulated carrier, a spur (check: does it move with the antenna?), a beacon, PLL leakage |
| Thin line that blinks in dots and dashes | CW Morse / OOK at low rate |
| Short horizontal smudges, repeating every N seconds | Periodic telemetry: weather sensors, TPMS, meters, beacons |
| Short bursts with fine vertical striping | OOK/ASK packets (stripes = bit pattern) |
| Two parallel rails hopping left/right | 2-FSK (four rails: 4-FSK) |
| A narrow wobbling line, ~10–25 kHz | NFM voice / analog two-way radio |
| A wide fuzzy band ~200 kHz with a bright centre, constant | Broadcast FM (stereo pilot at ±19 kHz, RDS ±57 kHz) |
| Flat-topped rectangle, sharp edges, noise-like inside | PSK/QAM (single carrier) or OFDM (wider, very flat top). DAB, DVB-T, LTE, Wi-Fi |
| Diagonal lines (same slope) | LoRa / chirp spread spectrum, radar chirps |
| Short dots scattered randomly across a wide band | Frequency hopping (Bluetooth Classic, some drones/remotes) |
| Regular bursts in time slots | TDMA: DMR (30 ms slots), GSM (577 µs), TETRA |
| A comb of evenly spaced lines | Harmonics/spurs of a clock, a switching supply, or intermod. Or deliberate multitone |
| A copy of a strong signal mirrored about the centre | IQ image (not a real signal) |
| A spike exactly at the centre | DC offset (not a real signal) |
| Text or pictures | Waterfall art (see `signal_generation/09`) |

## Measure before you guess

```bash
.venv/bin/python tools/iq_inspect.py capture.wav          # signals with abs freq, SNR, BW; burst timing; PNG
```

| Measurement | Narrows down |
|---|---|
| Centre frequency | Band → regulated uses (table below) |
| Occupied bandwidth | 1–3 kHz CW/OOK-slow; 10–25 kHz NFM/narrow FSK; 50–200 kHz fast FSK/WFM; ≥ 1 MHz Wi-Fi/LTE/DVB |
| Burst length and period | Packet protocol vs continuous; TDMA structure; duty cycle |
| Envelope (constant or not) | Constant: FSK/FM/PSK-ish. Varying: AM/OOK/QAM/OFDM |
| Discriminator histogram | 2/4 clusters: FSK. Continuous: FM audio |
| Symbol rate | Common rates point to standards (table below) |

## Common symbol rates and parameters

| Rate | Typical source |
|---|---|
| 512 / 1200 / 2400 bd, ±4.5 kHz FSK | POCSAG pagers |
| 1600 / 3200 / 6400 bps | FLEX pagers |
| 1200 bd AFSK (1200/2200 Hz on NFM) | APRS / AX.25 packet |
| 9600 bd GMSK | AIS (161.975/162.025 MHz), 9k6 packet |
| 1 Mbps GFSK (BT 0.5) | Bluetooth LE |
| 2 Mbps | Bluetooth LE 2M |
| 4.8 kbaud 4-FSK | DMR (12.5 kHz) |
| 1 Mbps PPM | ADS-B Mode S (1090 MHz) |
| 300–10k bps OOK/FSK | 315/433/868/915 MHz ISM gadgets (rtl_433 territory) |
| 19.2 kbps / 38.4 kbps / 100 kbps 2-FSK | Utility meters, Z-Wave (9.6/40/100k), Sub-GHz IoT (CC1101, Si446x) |
| 125/250/500 kHz chirps, SF7–12 | LoRa (433/868/915 MHz) |

## Frequency guide (US-centric. Check your region)

| Frequency | What's there |
|---|---|
| 0.53–1.7 MHz | AM broadcast |
| 3–30 MHz | HF: shortwave broadcast, amateur, maritime, aviation HF, time stations (WWV 2.5/5/10/15/20 MHz) |
| 26.965–27.405 MHz | CB radio (AM/SSB) |
| 50–54, 144–148, 222–225, 420–450 MHz | Amateur 6 m, 2 m, 1.25 m, 70 cm |
| 88–108 MHz | FM broadcast (WFM) |
| 108–118 MHz | VOR/ILS aviation navigation |
| 118–137 MHz | Airband voice (AM, 25/8.33 kHz) |
| 137–138 MHz | NOAA/Meteor weather satellites (APT/LRPT) |
| 144.390 MHz (US) / 144.800 (EU) | APRS |
| 150–174 MHz | VHF land mobile, pagers (POCSAG/FLEX around 152–158, 929–932), marine VHF (156–162) |
| 161.975 / 162.025 MHz | AIS (ships) |
| 162.400–162.550 MHz | NOAA Weather Radio (NFM) |
| 315 MHz | US car key fobs, garage remotes, TPMS (US) |
| 433.05–434.79 MHz | ISM (Region 1) / US Part 15: remotes, weather stations, sensors, LoRa (EU433) |
| 446.0–446.2 MHz | PMR446 (EU license-free radio) |
| 462/467 MHz | FRS/GMRS (US) |
| 470–608 MHz | UHF TV (DVB-T / ATSC) |
| 698–960 MHz | Cellular bands (LTE/5G) |
| 863–870 MHz | EU SRD/ISM: LoRa EU868, Z-Wave 868.42, alarms, meters |
| 902–928 MHz | US ISM: LoRa US915, Z-Wave 908.42, meters, RFID, Wi-Fi HaLow |
| 1090 MHz (and 978 UAT) | ADS-B (aircraft) |
| 1176/1227/1575.42 MHz | GPS L5/L2/L1 (below the noise floor without despreading) |
| 1.6–1.7 GHz | Inmarsat/Iridium (1616–1626.5) satellite phones/data |
| 2.400–2.4835 GHz | Wi-Fi, Bluetooth, BLE, Zigbee, drones, microwave ovens |
| 5.15–5.85 GHz | Wi-Fi 5 GHz, drone video (5.8 GHz analog FPV) |

RTL-SDR Blog V4 covers up to 1.766 GHz. HackRF and B210 go to 6 GHz.

## Decision tree

```text
Is it at exactly the centre?  → DC spike. Ignore.
Is there a mirror at −f?      → IQ image. Ignore the weaker one.
Does it vanish with the antenna removed? No → internal spur.
Continuous or bursty?
├─ continuous
│   ├─ constant envelope, width ~200 kHz, audio in WFM → broadcast FM
│   ├─ narrow wobble, voice in NFM → analog two-way
│   ├─ flat-top block → digital (PSK/QAM/OFDM): measure BW, look for cyclic prefix/pilots
│   └─ single line → carrier/beacon/spur
└─ bursty
    ├─ on/off within burst → OOK/ASK → envelope recipe
    ├─ two rails → FSK → discriminator recipe
    ├─ diagonal → LoRa/chirp → de-chirp
    ├─ hopping dots → FHSS
    └─ time slots → TDMA standard (DMR/TETRA/GSM)
```

Then match frequency + bandwidth + rate against the tables above, and try a purpose-built decoder
(`rtl_433`, `multimon-ng`, `dump1090`, `AIS-catcher`, `dsd-fme`) before writing your own.
