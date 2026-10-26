"""Tests for the harder receivers: brute-force bit decoding, symbol-rate search, repeat combining, OFDM, chirp
spread spectrum, blind spread-spectrum code recovery. No hardware needed.

Run:  python tests/test_advanced.py      (or: python -m pytest tests/)
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from rfkit import bits, dsp, mod  # noqa: E402

RNG = np.random.default_rng(7)


def _uart_stream(text: bytes, lead=5, tail=3, start=1):
    fr = []
    for c in text:
        fr += [start] + [(c >> i) & 1 for i in range(8)] + [1 - start]
    return np.array([1 - start] * lead + fr + [start] * tail, np.uint8)


def test_bruteforce_uart_and_manchester():
    top = bits.bruteforce(_uart_stream(b"HELLO UART 123"))[0]
    assert top["text"] == "HELLO UART 123" and top["mode"] == "uart10"
    m = bits.manchester_encode(bits.from_bytes(b"MANCHESTER OK!"))
    assert bits.bruteforce(np.r_[1, 0, m])[0]["text"] == "MANCHESTER OK!"


def test_uart_short_last_frame():
    s = _uart_stream(b"ABCDEF", lead=0, tail=0)[:-1]          # final stop bit missing
    assert bits.uart_decode(s)[0] == b"ABCDEF"
    assert bits.uart_decode(s, short_last=False)[0] == b"ABCDE"


def test_bruteforce_no_false_positives_on_noise():
    fp = sum(bool(bits.bruteforce(RNG.integers(0, 2, 400).astype(np.uint8))) for _ in range(100))
    assert fp <= 1


def test_refine_symbol_rate():
    fs, rate = 200_000, 25_000
    b = RNG.integers(0, 2, 4000).astype(np.uint8)
    x = mod.linear_mod(b, "qpsk", fs, rate)
    x = mod.impair(x, fs, cfo_hz=1500)
    x = mod.awgn(x, 20, RNG)
    best, rates, metric = dsp.refine_symbol_rate(x, fs, 24_000, rel_span=0.08, order=4)
    assert abs(best - rate) / rate < 0.01, best


def test_combine_repeats_gains_snr():
    fs = 100_000
    ref = mod.linear_mod(RNG.integers(0, 2, 600).astype(np.uint8), "qpsk", fs, 10_000)
    copies = [mod.awgn(np.roll(ref, d) * np.exp(1j * ph), 0, RNG, signal_power=np.mean(np.abs(ref) ** 2))
              for d, ph in [(0, 0.0), (7, 1.0), (-3, 2.0), (12, 3.0)]]
    comb = dsp.combine_repeats(copies)
    def err(a):
        a = a * np.exp(1j * np.angle(np.vdot(a, ref)))
        return np.mean(np.abs(a - ref) ** 2)
    assert err(comb) < 0.5 * err(copies[0])


def test_ofdm_with_echo():
    n_fft, cp = 64, 16
    tidx = RNG.integers(0, 4, 48)
    train = mod.constellation("qpsk")[tidx]
    payload = RNG.integers(0, 2, 48 * 2 * 12).astype(np.uint8)
    # the toy modulator maps bits to the 48 used bins; send a known training symbol first
    tbits = np.column_stack([tidx >> 1, tidx & 1]).astype(np.uint8).ravel()
    sig = mod.ofdm(np.r_[tbits, payload], n_fft=n_fft, cp=cp)
    fs = 20e6
    echo = sig + 0.5 * np.exp(1j * 0.7) * np.roll(sig, 3)                # a short echo: per-subcarrier fades
    echo = mod.awgn(echo, 25, RNG)
    d = dsp.ofdm_detect(echo, fs)
    assert d["n_fft"] == n_fft and d["cp"] == cp, d
    Y = dsp.ofdm_demod(echo, d["n_fft"], d["cp"], d["start"])
    bins = dsp.ofdm_occupied(Y)
    assert len(bins) >= 46
    eq = dsp.ofdm_equalize(Y, bins, training=_ref_symbols(tbits, bins))
    data = eq[1:]
    got = dsp.psk_bits(data.ravel(), 4)
    want = payload[: len(got)]
    assert np.mean(got == want) > 0.97


def _ref_symbols(tbits, bins):
    pts = mod.constellation("qpsk")
    idx = mod.bits_to_symbols(tbits, 2)
    full = pts[idx]
    # mod.ofdm places used subcarriers at bins 1..24 then 40..63; ofdm_occupied returns them in ascending order
    order = np.r_[np.arange(1, 25), np.arange(40, 64)]
    lookup = dict(zip(order, full))
    return np.array([lookup[b] for b in bins], np.complex64)


def test_css_demod():
    sf, bw = 7, 125e3
    fs = 4 * bw
    vals = RNG.integers(0, 2 ** sf, 20)
    x = mod.css_frame(vals, sf, bw, fs, preamble=8)
    x = np.r_[np.zeros(333, np.complex64), x, np.zeros(2000, np.complex64)]
    x = mod.awgn(x, 0, RNG, signal_power=1.0)                              # 0 dB per-sample SNR
    r = dsp.css_demod(x, fs, bw, sf)
    got = r["values"][: len(vals)]
    assert np.mean(got == vals[: len(got)]) > 0.9 and len(got) >= 18


def test_dsss_blind_code_recovery():
    period = 31
    code = RNG.integers(0, 2, period) * 2 - 1
    data = RNG.integers(0, 2, 400)
    chips = np.concatenate([code * (1 if b else -1) for b in data]).astype(float)
    soft = chips + RNG.normal(0, 1.2, len(chips))                          # per-chip SNR ~ -1.6 dB
    rec = dsp.dsss_recover_code(soft, period)
    assert abs(int(np.dot(rec, code))) == period                          # code recovered up to sign
    corr = dsp.dsss_despread(soft, rec)
    got = (corr > 0).astype(int)
    agree = np.mean(got == data)
    assert max(agree, 1 - agree) > 0.99


def test_cyclic_lines_find_chip_rate():
    fs, chip_rate = 200_000, 20_000
    code = RNG.integers(0, 2, 31).astype(np.uint8)
    b = RNG.integers(0, 2, 500).astype(np.uint8)
    x = mod.dsss(b, code, fs, chip_rate)
    x = np.convolve(x, np.ones(3) / 3, "same")                             # band-limit so |x|^2 is not constant
    x = mod.awgn(mod.impair(x, fs, cfo_hz=3000), -3, RNG)
    lines = dsp.cyclic_lines(x, fs, "abs2", n=3)
    assert any(abs(l["freq_hz"] - chip_rate) < 100 or abs(l["freq_hz"] - 2 * chip_rate) < 100 for l in lines), lines


def test_dsss_from_iq_with_carrier_and_noise():
    fs, chip_rate, period = 80_000, 20_000, 31
    code = RNG.integers(0, 2, period).astype(np.uint8)
    data = RNG.integers(0, 2, 300).astype(np.uint8)
    x = mod.dsss(data, code, fs, chip_rate)
    x = mod.awgn(mod.impair(x, fs, cfo_hz=1234.0, phase_rad=1.0), -3, RNG)    # -3 dB per sample (chip SNR ~ +3 dB)
    soft = dsp.bpsk_soft_chips(x, fs, chip_rate)
    off = dsp.dsss_find_alignment(soft, period)
    rec = dsp.dsss_recover_code(soft, period, off)
    got = (dsp.dsss_despread(soft, rec, off) > 0).astype(int)
    n = min(len(got), len(data))
    agree = np.mean(got[:n] == data[:n])
    assert max(agree, 1 - agree) > 0.95, agree


def _synthetic_survey(fs=2e6, secs=10.0):
    n = int(fs * secs)
    t = np.arange(n) / fs
    x = (RNG.normal(0, 0.05, n) + 1j * RNG.normal(0, 0.05, n)).astype(np.complex64)
    def burst(f, t0, dur, amp=0.5):
        a, b = int(t0 * fs), int((t0 + dur) * fs)
        x[a:b] += (amp * np.exp(2j * np.pi * f * t[a:b])).astype(np.complex64)
    for k in range(40):
        burst(400e3, 0.1 + 0.25 * k, 0.03)                        # beacon: every 250 ms for the whole capture
    for d, f in enumerate([-600e3, -250e3, 250e3, 650e3]):         # hopper: 4 dwells of 5 bursts
        for k in range(5):
            burst(f, 0.5 + 2.2 * d + 0.4 * k, 0.06)
    burst(-800e3, 6.0, 0.15)                                       # one-off
    x += (0.2 * np.exp(2j * np.pi * 100e3 * t)).astype(np.complex64)   # continuous carrier
    return x, fs


def test_survey_separates_beacon_hopper_oneoff():
    from rfkit import survey
    x, fs = _synthetic_survey()
    blocks = [x[i: i + int(fs)] for i in range(0, len(x), int(fs))]
    S, f = survey.tfmap(blocks, fs, 0.01, 2048)
    ev = survey.find_events(S, f, 0.01, 915e6)
    g = survey.classify(ev, len(x) / fs)
    assert any(abs(c["freq_hz"] - 915.1e6) < 5e3 for c in g["carriers"])
    assert len(g["beacons"]) == 1 and abs(g["beacons"][0]["freq_hz"] - 915.4e6) < 5e3
    assert len(g["hoppers"]) == 1 and len(g["hoppers"][0]["dwells"]) == 4
    got = sorted(round((d["freq_hz"] - 915e6) / 1e3) for d in g["hoppers"][0]["dwells"])
    assert all(abs(a - b) < 10 for a, b in zip(got, [-600, -250, 250, 650])), got
    assert any(abs(e["freq_hz"] - 914.2e6) < 5e3 for e in g["one_offs"])


def test_survey_fast_hopper_and_noise_events():
    from rfkit import survey
    rng = np.random.default_rng(11)
    ev = []
    for k in range(10):                                       # one burst per hop, steady 1 s schedule
        ev.append({"t_s": 1.0 + k * 1.0, "dur_s": 0.17, "freq_hz": 915e6 + rng.uniform(-9e6, 9e6), "bw_hz": 200e3,
                   "level_db": 55.0})
    for _ in range(60):                                       # junk: random times, short, weaker
        ev.append({"t_s": rng.uniform(0, 12), "dur_s": rng.choice([0.02, 0.03, 0.05]),
                   "freq_hz": 915e6 + rng.uniform(-10e6, 10e6), "bw_hz": 30e3, "level_db": rng.uniform(16, 30)})
    g = survey.classify(ev, 12.0)
    assert len(g["hoppers"]) == 1 and len(g["hoppers"][0]["dwells"]) == 10, g["hoppers"]


def test_b210_rx_helpers():
    import importlib.util
    spec = importlib.util.spec_from_file_location("b210_rx", Path(__file__).resolve().parents[1] /
                                                  "radios/usrp-b210/tools/b210_rx.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.count_overflows("[INFO] [UHD] linux; GNU C++\nOOO\n") == 3
    assert m.count_overflows("Got an overflow indication. Please consider...") == 1
    assert m.count_overflows("clean run, OpenSourceSDRLab") == 0


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
