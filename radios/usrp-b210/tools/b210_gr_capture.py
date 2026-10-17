#!/usr/bin/env python3
"""Capture IQ from a USRP B210 straight into NumPy with GNU Radio's UHD block (gr-uhd).

Homebrew's UHD has no `import uhd` Python module, but GNU Radio's own Python has gr-uhd. Run this with it:

    GR=$(ls -d "$(brew --prefix gnuradio)"/libexec/venv/bin/python)
    $GR radios/usrp-b210/tools/b210_gr_capture.py --freq 433.92e6 --rate 2e6 --gain 40 --seconds 2 -o cap.cf32
    # Linux (apt gnuradio): python3 radios/usrp-b210/tools/b210_gr_capture.py ...

Writes complex64 (.cf32) plus a .sigmf-meta sidecar and prints a short JSON summary (strongest signal,
power). Import `capture()` from your own GNU Radio-Python code to get the NumPy array directly.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np

os.environ.setdefault("UHD_IMAGES_DIR", str(Path.home() / ".local/share/uhd/images"))
from gnuradio import blocks, gr, uhd  # noqa: E402


def capture(freq: float, rate: float, gain: float, seconds: float, antenna: str = "RX2", channel: int = 0,
            args: str = "type=b200") -> np.ndarray:
    """Return `seconds` of complex64 samples from the B210."""
    n = int(seconds * rate)
    tb = gr.top_block()
    src = uhd.usrp_source(args, uhd.stream_args(cpu_format="fc32", channels=[channel]))
    src.set_samp_rate(rate)
    src.set_center_freq(freq, 0)
    src.set_gain(gain, 0)
    src.set_antenna(antenna, 0)
    head = blocks.head(gr.sizeof_gr_complex, n)
    sink = blocks.vector_sink_c()
    tb.connect(src, head, sink)
    tb.run()
    return np.asarray(sink.data(), dtype=np.complex64), src.get_samp_rate()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--freq", type=float, required=True)
    ap.add_argument("--rate", type=float, default=2e6)
    ap.add_argument("--gain", type=float, default=40)
    ap.add_argument("--seconds", type=float, default=1.0)
    ap.add_argument("--ant", default="RX2")
    ap.add_argument("--channel", type=int, default=0)
    ap.add_argument("--args", default="type=b200")
    ap.add_argument("-o", "--out", default="b210_capture.cf32")
    a = ap.parse_args()

    x, fs = capture(a.freq, a.rate, a.gain, a.seconds, a.ant, a.channel, a.args)
    out = Path(a.out)
    x.tofile(out)
    meta = {"global": {"core:datatype": "cf32_le", "core:sample_rate": fs, "core:version": "1.0.0",
                       "core:hw": "USRP B210", "core:recorder": "gr-uhd"},
            "captures": [{"core:sample_start": 0, "core:frequency": a.freq}], "annotations": []}
    out.with_suffix(".sigmf-meta").write_text(json.dumps(meta, indent=2))
    spec = np.fft.fftshift(np.abs(np.fft.fft(x[-65536:] * np.hanning(min(65536, len(x))))) ** 2)
    f = np.fft.fftshift(np.fft.fftfreq(len(spec), 1 / fs))
    k = int(np.argmax(spec * (np.abs(f) > 5e3)))
    print(json.dumps({"file": str(out), "samples": len(x), "fs": fs, "rms": float(np.sqrt(np.mean(np.abs(x) ** 2))),
                      "strongest_offset_hz": float(f[k]),
                      "strongest_over_median_db": float(10 * np.log10(spec[k] / np.median(spec)))}, indent=2))


if __name__ == "__main__":
    main()
