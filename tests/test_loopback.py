"""Software loopback tests: generate -> impair (noise, carrier offset, delay) -> demodulate -> compare.

Run:  python tests/test_loopback.py      (or: python -m pytest tests/)
No hardware needed. Every modulator in rfkit.mod that has a matching receiver in rfkit.dsp is exercised.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rfkit import bits, dsp, iq, mod  # noqa: E402

FS = 2_000_000
RNG = np.random.default_rng(1234)
PAYLOAD = b"RF-AGENT TEST 123"


def test_crc_check_values():
    assert bits.crc16_ccitt(b"123456789") == 0x29B1
    assert bits.crc8(b"123456789") == 0xF4


def test_manchester_roundtrip():
    b = bits.from_bytes(PAYLOAD)
    for ieee in (True, False):
        out, bad = bits.manchester_decode(bits.manchester_encode(b, ieee), ieee)
        assert bad == 0 and np.array_equal(out, b)


def test_whitening_and_frame():
    f = bits.frame(PAYLOAD, whitening=True)
    r = bits.parse_frame(f, whitening=True)
    assert r and r["payload"] == PAYLOAD and r["crc_ok"]


def test_iq_formats_roundtrip():
    x = mod.tone(50e3, 0.01, FS) * 0.7
    with tempfile.TemporaryDirectory() as d:
        for ext, tol in ((".cs8", 1 / 64), (".cu8", 1 / 64), (".cs16", 1e-3), (".cf32", 1e-6), (".wav", 1e-3),
                         (".sigmf-data", 1e-6)):
            p = iq.save(Path(d) / f"t{ext}", x, fs=FS, peak=None)
            y, fs = iq.load(p, fs=FS)
            assert len(y) == len(x), ext
            assert np.max(np.abs(y - x)) < tol, (ext, np.max(np.abs(y - x)))
            if ext in (".wav", ".sigmf-data"):
                assert fs == FS


def _rx(x, snr_db=20, cfo=2_000.0):
    """Typical bench channel: +2 kHz crystal error, a little delay, noise."""
    y = mod.impair(mod.pad(x, FS, 0.01), FS, cfo_hz=cfo, phase_rad=1.0, delay_samples=137)
    return mod.awgn(y, snr_db, RNG)


def test_tone_cfo():
    y = _rx(mod.tone(100e3, 0.05, FS), snr_db=10)
    f = dsp.find_carriers(y, FS)[0]["freq_hz"]
    assert abs(f - 102e3) < 300, f


def test_morse():
    text = "CQ TEST DE RF AGENT"
    y = _rx(mod.morse(text, FS, wpm=20), snr_db=10)
    yc, fs2 = dsp.channelize(y, FS, 2e3, 2e3)
    env = dsp.moving_average(np.abs(yc), int(0.003 * fs2))
    thr = dsp.otsu_threshold(env)
    r = dsp.runs(env > thr)[1:]       # first run is leading silence
    assert bits.morse_from_runs([(lv, n) for lv, n in r]) == text


def test_ook_packet():
    rate = 2_000
    b = bits.frame(PAYLOAD)
    y = _rx(mod.shift(mod.ook(b, FS, rate), 100e3, FS), snr_db=15)
    c = dsp.find_carriers(y, FS, exclude_dc_hz=5e3)[0]["freq_hz"]
    yc, fs2 = dsp.channelize(y, FS, c, 4 * rate)
    seg = dsp.bursts(yc, fs2)[0]
    env = np.abs(yc[seg[0]:seg[1]])
    est = dsp.estimate_symbol_rate(env, fs2)
    assert abs(est - rate) / rate < 0.02, est
    r = bits.parse_frame(dsp.slice_symbols(env, fs2 / est))
    assert r and r["payload"] == PAYLOAD and r["crc_ok"]


def test_ook_manchester():
    rate = 1_000
    b = np.concatenate([bits.from_bytes(b"\xaa\xaa"), bits.manchester_encode(bits.frame(PAYLOAD, preamble=b""))])
    y = _rx(mod.shift(mod.ook(b, FS, 2 * rate), -150e3, FS), snr_db=15)
    yc, fs2 = dsp.channelize(y, FS, -148e3, 8 * rate)
    seg = dsp.bursts(yc, fs2)[0]
    env = np.abs(yc[seg[0]:seg[1]])
    chips = dsp.slice_symbols(env, fs2 / (2 * rate))
    sw = bits.manchester_encode(bits.from_bytes(bits.DEFAULT_SYNC))
    k = bits.find(chips, sw)[0]
    dec, bad = bits.manchester_decode(chips[k:])
    r = bits.parse_frame(dec)
    assert r and r["payload"] == PAYLOAD and r["crc_ok"]


def test_2fsk_packet():
    rate, dev = 5_000, 10e3
    b = bits.frame(PAYLOAD)
    y = _rx(mod.ramp_edges(mod.fsk(b, FS, rate, dev, offset_hz=200e3), 200), snr_db=12)
    c = dsp.signal_center(y, FS, exclude_dc_hz=5e3)        # FSK has two peaks: use the centroid
    assert abs(c - 202e3) < 1e3, c
    yc, fs2 = dsp.channelize(y, FS, c, 2 * dev + 2 * rate)
    seg = dsp.bursts(yc, fs2)[0]
    inst = dsp.fm_discriminator(yc[seg[0]:seg[1]], fs2)
    inst = dsp.lowpass(inst, rate, fs2)       # post-detection filter; Otsu (not 0 or the median) sets the slicer
    est = dsp.estimate_symbol_rate(inst, fs2)
    assert abs(est - rate) / rate < 0.02, est
    r = bits.parse_frame(dsp.slice_symbols(inst, fs2 / est))
    assert r and r["payload"] == PAYLOAD and r["crc_ok"]


def test_pll_slicer_tolerates_rate_error():
    """A 1.5 % wrong symbol-rate estimate slips bits with a fixed clock but not with the PLL slicer."""
    rate = 10_000
    b = bits.frame(PAYLOAD * 3)                     # long packet (~450 bits)
    x = mod.fsk(b, FS, rate, 10e3, bt=0.5)
    inst = dsp.lowpass(dsp.fm_discriminator(mod.awgn(x, 15, RNG), FS), 0.75 * rate, FS)
    wrong_sps = FS / (rate * 1.015)
    r = bits.parse_frame(dsp.slice_symbols_pll(inst, wrong_sps))
    assert r and r["crc_ok"] and r["payload"] == PAYLOAD * 3


def test_gfsk_4fsk_spectra():
    b = RNG.integers(0, 2, 2000)
    rect = mod.fsk(b, FS, 10e3, 25e3)
    gauss = mod.fsk(b, FS, 10e3, 25e3, bt=0.5)
    assert dsp.occupied_bandwidth(gauss, FS)[0] < dsp.occupied_bandwidth(rect, FS)[0]
    s4 = mod.fsk(RNG.integers(0, 4, 500), FS, 10e3, 5e3, m=4)
    inst = dsp.fm_discriminator(s4, FS)
    levels = np.unique(np.round(inst[200::200] / 5e3))
    assert set(levels.astype(int)) <= {-3, -1, 1, 3}


def test_bpsk_qpsk():
    for scheme, order in (("bpsk", 2), ("qpsk", 4)):
        b = np.concatenate([bits.frame(PAYLOAD), RNG.integers(0, 2, 64).astype(np.uint8)])
        sym_rate = 50e3
        x = mod.linear_mod(b, scheme, FS, sym_rate)
        y = mod.awgn(mod.impair(x, FS, cfo_hz=1500, phase_rad=0.7), 20, RNG)
        syms = dsp.psk_demod(y, FS, sym_rate, order)
        found = None
        for rot in range(order):                      # resolve phase ambiguity with the sync word
            out = dsp.psk_bits(syms * np.exp(1j * 2 * np.pi * rot / order), order)
            r = bits.parse_frame(out)
            if r and r["crc_ok"] and r["payload"] == PAYLOAD:
                found = r
                break
        assert found, scheme


def test_fm_audio():
    afs = 48_000
    t = np.arange(int(0.2 * afs)) / afs
    audio = 0.8 * np.sin(2 * np.pi * 1_000 * t)
    x = mod.fm(mod.resample_audio(audio, afs, 240_000), 75e3, 240_000)
    a, fa = dsp.fm_demod(x, 240_000, deemph_us=None)
    f, p = dsp.psd(a - a.mean(), fa, 4096)
    assert abs(abs(f[np.argmax(p)]) - 1_000) < 50


def test_am_audio():
    t = np.arange(int(0.2 * 250e3)) / 250e3
    x = mod.am(np.sin(2 * np.pi * 800 * t))
    a, fa = dsp.am_demod(x, 250e3)
    f, p = dsp.psd(a, fa, 4096)
    assert abs(abs(f[np.argmax(p)]) - 800) < 50


def test_chirp_and_css():
    c = mod.chirp(-100e3, 100e3, 0.01, FS)
    inst = dsp.fm_discriminator(c, FS)
    assert abs(inst[100] + 100e3) < 2e3 and abs(inst[-100] - 100e3) < 2e3
    s = mod.css_frame([5, 100], sf=7, bw=125e3, fs=500e3)
    assert len(s) > 0 and abs(np.mean(np.abs(s)) - 1) < 1e-3


def test_image_and_ofdm():
    img = np.zeros((8, 16))
    img[:, 4] = 1
    x = mod.image_to_iq(img, FS, 100e3, 0.01)
    f, p = dsp.psd(x, FS, 8192)
    expect = np.linspace(-50e3, 50e3, 16)[4]
    assert abs(f[np.argmax(p)] - expect) < 1e3
    o = mod.ofdm(RNG.integers(0, 2, 960).astype(np.uint8))
    assert dsp.papr_db(o) > 6        # OFDM is peaky: needs back-off before the DAC


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except Exception as e:  # noqa: BLE001
                fails += 1
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    sys.exit(1 if fails else 0)
