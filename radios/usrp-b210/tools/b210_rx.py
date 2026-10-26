#!/usr/bin/env python3
"""Record IQ from a USRP B200/B210 with UHD's rx_samples_to_file, plus a SigMF sidecar.

    b210_rx.py --freq 433.92e6 --rate 2e6 --gain 40 --seconds 5 -o cap.cf32
    b210_rx.py --freq 915e6 --rate 10e6 --gain 30 --ant TX/RX --channel 1 --seconds 2 -o cap.cs16
    b210_rx.py --freq 2.44e9 --rate 20e6 --gain 50 --channels 0,1 --seconds 1 -o mimo.cf32   # -> mimo_ch0/1.cf32
    b210_rx.py --freq 98e6 --rate 56e6 --otw sc8 --seconds 1 -o wide.cs16                   # 56 MS/s needs sc8
    b210_rx.py --freq 915e6 --rate 30e6 --seconds 60 -o wide.cs16                           # >= 20 MB/s: auto RAM (see below)

Output format follows the extension: .cf32 (complex float32, rfkit default) or .cs16 (int16 I/Q).
A <file>.sigmf-meta is written next to each file (rate, centre, gain, antenna, channel) so
rfkit.iq / tools/iq_inspect.py can open it without extra arguments (open the .sigmf-data name, or pass --fs).

UHD antenna names on each channel: "TX/RX" and "RX2". On the OpenSourceSDRLab Artix-7 board,
channel 0 = TRX1 (TX/RX) + RX1 (RX2); channel 1 = TRX2 (TX/RX) + RX2 (RX2).
Needs UHD_IMAGES_DIR set (radios/usrp-b210/tools/setup_images.sh).

Long or wide captures (data rate >= 20 MB/s, or --ram): the recording goes to /dev/shm first and is moved to -o
together with its .sigmf-meta afterwards. Writing straight to disk at these rates dropped samples and ended in
a truncated file even though the exit code was 0; RAM did not. If /dev/shm is too small the tool falls back to
disk with a warning (--ram: error instead). --no-ram forces disk. The JSON reports overflow_count, samples vs
expected_samples and complete; the same check prints a WARNING on stderr when a capture is short or overflowed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_IMAGES = Path.home() / ".local/share/uhd/images"
SHM = Path("/dev/shm")
RAM_AUTO_BYTES_PER_S = 20e6        # at or above this, straight-to-disk recording has dropped samples


def f_num(s: str) -> float:
    s = s.strip().lower().replace("_", "")
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(s[-1], 1)
    return float(s[:-1] if s[-1] in "kmg" else s) * mult


def uhd_example(name: str) -> str:
    """Locate a UHD example program (Homebrew keeps them off PATH)."""
    cands = []
    if shutil.which(name):
        return shutil.which(name)
    try:
        prefix = subprocess.run(["brew", "--prefix", "uhd"], capture_output=True, text=True).stdout.strip()
        if prefix:
            cands.append(Path(prefix) / "lib/uhd/examples" / name)
    except FileNotFoundError:
        pass
    cands += [Path("/usr/lib/uhd/examples") / name, Path("/usr/local/lib/uhd/examples") / name,
              Path("/usr/libexec/uhd/examples") / name]
    for c in cands:
        if c.exists():
            return str(c)
    sys.exit(f"UHD example '{name}' not found (install UHD: brew install uhd / apt install uhd-host)")


def wire_flag(example: str, env: dict) -> str:
    """UHD 4.10 calls the over-the-wire option --otw, UHD 4.9 (Ubuntu apt) calls it --wirefmt."""
    h = subprocess.run([example, "--help"], env=env, capture_output=True, text=True)
    return "--wirefmt" if "--wirefmt" in (h.stdout + h.stderr) else "--otw"


def uhd_env() -> dict:
    env = dict(os.environ)
    if "UHD_IMAGES_DIR" not in env and DEFAULT_IMAGES.exists():
        env["UHD_IMAGES_DIR"] = str(DEFAULT_IMAGES)
    return env


def write_meta(data: Path, fmt: str, rate: float, freq: float, extra: dict) -> Path:
    dt = {"float": "cf32_le", "short": "ci16_le"}[fmt]
    meta = {"global": {"core:datatype": dt, "core:sample_rate": rate, "core:version": "1.0.0",
                       "core:hw": "USRP B210", "core:recorder": "rx_samples_to_file", **extra},
            "captures": [{"core:sample_start": 0, "core:frequency": freq}], "annotations": []}
    p = data.with_suffix(".sigmf-meta")
    p.write_text(json.dumps(meta, indent=2))
    return p


def count_overflows(log: str) -> int:
    """UHD's rx_samples_to_file prints a bare 'O' per overflow and the long explanation only the first time.
    Count the marks, and report at least 1 whenever the explanation appeared."""
    marks = sum(len(m) for m in re.findall(r"(?<![A-Za-z0-9_])(O+)(?![A-Za-z0-9_])", log))
    return max(marks, 1 if "Got an overflow" in log else 0)


def plan_ram(a, out: Path, bytes_needed: float, rate_bytes_per_s: float):
    """Decide where to record. Returns (record_path, use_ram, notes)."""
    want = a.ram or (not a.no_ram and rate_bytes_per_s >= RAM_AUTO_BYTES_PER_S)
    if not want:
        return out, False, []
    if not SHM.is_dir():
        if a.ram:
            sys.exit("--ram: /dev/shm does not exist on this system")
        return out, False, ["no /dev/shm here: recording straight to disk"]
    free = shutil.disk_usage(SHM).free
    if bytes_needed * 1.05 > free:
        msg = f"/dev/shm has {free / 1e9:.1f} GB free, capture needs {bytes_needed / 1e9:.1f} GB"
        if a.ram:
            sys.exit(f"--ram: {msg}")
        return out, False, [msg + ": recording straight to disk (expect overflows at this rate)"]
    return SHM / f"b210_rx_{os.getpid()}_{out.name}", True, []


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-o", "--out", required=True, help="output file (.cf32 or .cs16)")
    ap.add_argument("--freq", type=f_num, required=True)
    ap.add_argument("--rate", type=f_num, default=2e6)
    ap.add_argument("--gain", type=float, default=40, help="RX gain dB (0-76)")
    ap.add_argument("--ant", default="RX2", help="TX/RX or RX2")
    ap.add_argument("--channel", default="0", help="0 or 1")
    ap.add_argument("--channels", help="e.g. 0,1 for both (files get _ch0/_ch1 suffixes)")
    ap.add_argument("--seconds", type=float, default=2.0)
    ap.add_argument("--bw", type=f_num, help="analog filter bandwidth (default: UHD's choice)")
    ap.add_argument("--otw", choices=["sc16", "sc8"], help="over-the-wire format (sc8 for > 30 MS/s)")
    ap.add_argument("--args", default="type=b200", help="UHD device args (e.g. 'serial=XXXXXXX,master_clock_rate=32e6')")
    ap.add_argument("--ref", choices=["internal", "external", "gpsdo"])
    ap.add_argument("--extra", default="", help="extra rx_samples_to_file arguments")
    ap.add_argument("--ram", action="store_true", help="record to /dev/shm, then move (default for >= 20 MB/s)")
    ap.add_argument("--no-ram", action="store_true", help="always record straight to the output path")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.ram and a.no_ram:
        sys.exit("--ram and --no-ram are mutually exclusive")

    out = Path(a.out)
    fmt = {".cf32": "float", ".cfile": "float", ".fc32": "float", ".cs16": "short", ".s16": "short"}.get(out.suffix)
    if fmt is None:
        sys.exit("output must end in .cf32 or .cs16")
    out.parent.mkdir(parents=True, exist_ok=True)
    chans = a.channels or a.channel
    chan_list = chans.split(",")
    nsamps = int(round(a.seconds * a.rate))
    bps = 8 if fmt == "float" else 4
    rate_bytes = a.rate * bps * len(chan_list)
    # per-channel files are named <stem>_ch<N><suffix> when several channels are recorded
    rec, use_ram, notes = plan_ram(a, out, nsamps * bps * len(chan_list), rate_bytes)
    cmd = [uhd_example("rx_samples_to_file"), "--args", a.args, "--freq", str(a.freq), "--rate", str(a.rate),
           "--gain", str(a.gain), "--ant", a.ant, "--channels", chans, "--type", fmt]
    # one UHD stream command holds at most 2^28 samples (26 s at 10 MS/s): use --duration beyond that
    cmd += ["--duration", str(a.seconds)] if nsamps >= 2**28 else ["--nsamps", str(nsamps)]
    cmd += ["--file", str(rec)]
    if a.bw:
        cmd += ["--bw", str(a.bw)]
    if a.otw:
        cmd += [wire_flag(cmd[0], uhd_env()), a.otw]
    if a.ref:
        cmd += ["--ref", a.ref]
    if a.extra:
        cmd += a.extra.split()
    for n in notes:
        print("note: " + n, file=sys.stderr)
    print("$ " + " ".join(cmd) + ("   # recording to RAM, then moving to " + str(out) if use_ram else ""), flush=True)
    if a.dry_run:
        return

    def names(base: Path):
        return [base] if len(chan_list) == 1 else [base.with_name(f"{base.stem}_ch{c}{base.suffix}") for c in chan_list]

    rec_files, out_files = names(rec), names(out)
    p = subprocess.run(cmd, env=uhd_env(), capture_output=True, text=True)
    log = p.stdout + p.stderr
    m = re.search(r"Actual RX Rate: ([\d.]+) Msps", log)
    actual = float(m.group(1)) * 1e6 if m else a.rate
    overflow_count = count_overflows(log)
    if p.returncode != 0:
        print(log[-2000:], file=sys.stderr)
        for f in rec_files:
            if use_ram:
                f.unlink(missing_ok=True)
        sys.exit(p.returncode)
    expected = int(round(a.seconds * actual))
    result, warnings = [], []
    for ch, src, dst in zip(chan_list, rec_files, out_files):
        if not src.exists():
            print(f"missing output {src}", file=sys.stderr)
            continue
        samples = src.stat().st_size // bps
        if use_ram:
            shutil.move(str(src), str(dst))        # data first, then the sidecar next to its final home
        meta = write_meta(dst, fmt, actual, a.freq, {"rfagent:gain_db": a.gain, "rfagent:antenna": a.ant,
                                                      "rfagent:channel": int(ch)})
        complete = samples >= 0.999 * expected
        if not complete:
            warnings.append(f"{dst.name}: {samples} samples, expected {expected} ({100 * samples / max(expected, 1):.1f} %)"
                            ": capture is truncated")
        result.append({"file": str(dst), "meta": str(meta), "samples": samples, "expected_samples": expected,
                       "complete": complete})
    if overflow_count:
        warnings.append(f"{overflow_count} overflow(s) (UHD reports at least this many): samples were dropped, so timing across them is not "
                        "reliable" + ("" if use_ram else "; try --ram or a lower rate"))
    for w in warnings:
        print("WARNING: " + w, file=sys.stderr)
    print(json.dumps({"rate": actual, "freq": a.freq, "gain": a.gain, "antenna": a.ant, "channels": chans,
                      "recorded_via": "ram" if use_ram else "disk", "overflow_reported": "Got an overflow" in log,
                      "overflow_count": overflow_count, "warnings": warnings, "files": result}, indent=2))


if __name__ == "__main__":
    main()
