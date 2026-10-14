# 09 · Waterfall art: text and images in the spectrum

A waterfall plots frequency across and time down, with brightness = power. If you transmit, for every
moment in time, a set of tones whose amplitudes are the pixels of one image row, the receiver's waterfall
draws the picture. (Aphex Twin hid a face in a song's spectrogram the same way.)

## The mechanism

```text
image row r (pixels p[0..W-1]) ──► W tones at frequencies f[0..W-1] spread over BW, amplitudes = p
                                  sent for line_s seconds, then the next row
```

```python
from rfkit import mod
x = mod.image_to_iq(img, fs=2e6, bandwidth_hz=150e3, line_s=0.06)   # img: 2-D array in [0, 1]
```

Inside `image_to_iq`: a basis of W complex exponentials (one per column, random fixed phases to keep the
peak-to-average ratio sane) is weighted by each row's pixel values (`row @ basis`).

## Text from the command line

```bash
.venv/bin/python signal_generation/generate.py text --text "RF AGENT" --bw 150e3 -o text.cs8 --plot
.venv/bin/python radios/hackrf/tools/hackrf_tx.py text.cs8 --freq 433.92e6 --rate 2e6 --gain 20
```

The text is rendered with Pillow's default font (`--height` pixels tall, so that many rows), and each row
lasts `--line-s` seconds.

![RF AGENT in SDR++](../software/sdr++/images/waterfall_text_433.png)

*Received over the air in SDR++ on the RTL-SDR (1.024 MS/s, FFT 8192, 30 lines/s).*

## Orientation (the part everyone gets wrong)

- **SDR++ (and most live waterfalls) draw the newest line at the top** and scroll down. The first row you
  transmit ends up at the **bottom** of the picture. `generate.py text` therefore sends `img[::-1]`
  (bottom row first), so the text is upright on a live display.
- An offline spectrogram with time running downward (`rfkit.plot.waterfall`) shows the first row at the
  top, so the same file looks upside-down there. That's expected.
- Left/right: column 0 maps to the **lowest** frequency. If your receiver has inverted IQ (or you swapped
  I/Q), the image is mirrored left-right.

## Making it legible

| Knob | Effect |
|---|---|
| `--line-s` | Seconds per image row. The receiver needs ≥ 2–3 waterfall lines per row: `line_s ≥ 3 / fft_rate`. At SDR++'s 30 lines/s that's ≥ 0.1 s. The default 0.06 s gives a squashed but readable image |
| `--bw` | Picture width in Hz. Each column is a tone BW/W apart, and the receiver's FFT bin must be finer than that ("RF AGENT" at 24 px renders 120 columns: 150 kHz / 120 ≈ 1.25 kHz per column, vs SDR++ bins of 125 Hz at FFT 8192 and 1.024 MS/s) |
| `--height` | Font size = number of rows = transmission time (rows × line_s) |
| Gamma / invert | `image_to_iq(..., gamma=0.5)` brightens mid-tones. `invert=True` for dark-on-light |
| Receiver display | Set min/max dB so the background is dark and tones saturate |

## Photos

```python
from PIL import Image
img = np.asarray(Image.open("logo.png").convert("L").resize((96, 64)), float) / 255
x = mod.image_to_iq(img[::-1], fs=2e6, bandwidth_hz=200e3, line_s=0.1)   # upright in SDR++
iq.save("logo.cs8", mod.pad(x, 2e6))
```

Keep images small (≤ ~100 columns): the PAPR grows with the number of lit columns, and every row costs
transmission time.

## Uses beyond fun

- Instantly visible **"is my TX chain working?"** test: a spectrum analyser or waterfall shows the
  image's correct orientation and frequency span at a glance.
- **Calibration:** a grid image shows receiver frequency response, image rejection (a faint mirrored copy
  around the centre) and timing/rate errors (a sheared image).
- **Visual datasets** for training a waterfall classifier.
