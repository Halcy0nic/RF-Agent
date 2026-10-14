# Spectrum regulations and equipment limits

Reference information on how radio spectrum is regulated and on the electrical limits of the hardware.
Rules differ by country and change over time. The national regulator is the authority: FCC (US), Ofcom
(UK), BNetzA (Germany), ISED (Canada), ACMA (Australia), and so on.

## Receiving

- In most countries receiving is unrestricted, with exceptions for specific bands (e.g. cellular in some
  countries).
- Many jurisdictions regulate **disclosing or using** the contents of communications that aren't intended
  for the public (US: 47 U.S.C. §605 and the ECPA for cellular, cordless and pager content; many EU
  countries have secrecy-of-communications laws), and decrypting encrypted transmissions.

## Transmitting: authorisation types

| Type | What it covers |
|---|---|
| **Licence-exempt (ISM/SRD)** | Certified devices within band-specific power, duty-cycle and emission limits. In the US, Part 15 assumes a certified intentional radiator |
| **Amateur radio licence** | Amateur bands (e.g. 70 cm: 420–450 MHz in the US, 430–440 MHz in many countries) with station ID requirements, no encryption, and power limits by licence class |
| **Experimental licence** (e.g. FCC Part 5) | Specific frequencies, power and location for research and development |
| **Commercial / service licences** | Land mobile, broadcast, cellular, etc. |
| **Cabled / shielded operation** | TX → attenuator → RX, or a shielded enclosure. Nothing radiates |

### Common ISM / SRD bands

| Band | Region | Notes |
|---|---|---|
| 433.05–434.79 MHz | ITU Region 1 ISM (EU/UK SRD); US: Part 15.231 (periodic) and amateur 70 cm | 433.92 MHz is the classic centre frequency for remotes and sensors |
| 863–870 MHz | EU SRD | Duty-cycle limits (0.1–10 % by sub-band), ERP limits (25 mW typical) |
| 902–928 MHz | US / Region 2 ISM | Part 15.247 / 15.249 |
| 2.400–2.4835 GHz | Worldwide ISM | Wi-Fi, Bluetooth, Zigbee, microwave ovens |
| 5.725–5.875 GHz | ISM | Wi-Fi, FPV video |

### Safety-of-life and protected allocations

| Band | Use |
|---|---|
| 108–137 MHz | Aviation navigation and voice (VOR/ILS, airband; 121.5 MHz emergency) |
| 156.8 MHz | Marine VHF channel 16 (distress) |
| 243 MHz, 406 MHz | Emergency beacons (military distress, COSPAS-SARSAT) |
| 960–1215 MHz | Aviation (DME, 1030/1090 MHz SSR and ADS-B) |
| 1164–1610 MHz | GNSS (GPS, Galileo, GLONASS, BeiDou) |
| Cellular, public-safety, broadcast bands | Licensed services |

## Emission characteristics of SDR transmitters

- **Spectral cleanliness** depends on the waveform: shaped edges, continuous phase and headroom (no
  clipping). See [../signal_generation](../signal_generation/README.md) guides 01–05.
- **HackRF artefacts:** LO leakage at the tuned centre and an IQ image at −offset (measured here ≈ 50 dB
  below the wanted signal), plus harmonics (2f, 3f): the HackRF has no output filter, so add a band-pass
  filter to suppress them.
- **Output power** (HackRF, approximate maxima with amp on): 5–15 dBm up to ~2.15 GHz, 13–15 dBm at
  2.15–2.75 GHz, 0–5 dBm at 2.75–4 GHz, −10–0 dBm at 4–6 GHz. B210: up to about +10 dBm.

## Equipment limits

| Item | Value / behaviour |
|---|---|
| Max RF input, HackRF One | −5 dBm (higher can damage the front end) |
| Max RF input, RTL-SDR Blog V4 | Linear below about −10 dBm; damage around +10 dBm |
| Max RF input, USRP B210 | Linear below about −15 dBm; damage at 0 dBm |
| Cabled TX → RX loop | 30–40 dB of attenuation keeps a HackRF/B210 output under these limits |
| Transmitting with no load | Low-power SDRs tolerate it; external power amplifiers generally don't |
| Bias-tee DC | HackRF 3.3 V / 50 mA, RTL-SDR V4 4.5 V / ~180 mA, both off by default. DC into a shorted antenna or test equipment input can damage either side |
| ESD | SMA centre pins are ESD-sensitive. Discharge before handling, especially with outdoor antennas |
| RF exposure | Negligible at SDR power levels (mW). MPE limits apply with amplifiers |
| Lightning | Outdoor antennas need grounding and disconnection in storms |
