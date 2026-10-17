#!/usr/bin/env python3
"""Drive SDRangel through its REST API: pick a device (e.g. the USRP B210), tune, set gain, run, record
SigMF IQ, add channels, screenshot. Standard library only.

    sdrangelctl.py launch                                   # start SDRangel with the API on :8091
    sdrangelctl.py status
    sdrangelctl.py devices [--tx]                           # list devices SDRangel can open
    sdrangelctl.py select --hw USRP [--channel 0]           # put a device in device set 0
    sdrangelctl.py set --freq 433.92e6 --rate 2e6 --gain 40 --gain-mode manual --ant RX2 --bw 2e6
    sdrangelctl.py set --json '{"usrpInputSettings": {"loOffset": 0}}'   # any raw settings
    sdrangelctl.py run | stop
    sdrangelctl.py record 5 -o tmp/sdrangel/cap [--bits 16|32]   # -> cap.sigmf-data + cap.sigmf-meta
    sdrangelctl.py add-channel NFMDemod [--offset 25e3]     # FileSink, SigMFFileSink, WFMDemod, AMDemod, ...
    sdrangelctl.py channels
    sdrangelctl.py shot tmp/sdrangel/screen.png
    sdrangelctl.py get /sdrangel/deviceset/0/device/report  # raw GET (also: patch/post/put/delete PATH JSON)
    sdrangelctl.py quit

Environment: SDRANGEL_API (default http://127.0.0.1:8091), UHD_IMAGES_DIR (USRP images; set by
radios/usrp-b210/tools/setup_images.sh, defaulted to ~/.local/share/uhd/images when launching).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
API = os.environ.get("SDRANGEL_API", "http://127.0.0.1:8091")
APP_BIN = os.environ.get("SDRANGEL_BIN", "/Applications/SDRangel.app/Contents/MacOS/SDRangel")
OUT = REPO / "tmp" / "sdrangel"
WINLIST_SRC = REPO / "tools" / "winlist.swift"
WINLIST = REPO / "tools" / "winlist"


def f_num(s: str) -> float:
    s = s.strip().lower().replace("_", "")
    mult = {"k": 1e3, "m": 1e6, "g": 1e9}.get(s[-1], 1)
    return float(s[:-1] if s[-1] in "kmg" else s) * mult


# ----------------------------------------------------------------------------- HTTP

def call(method: str, path: str, body: dict | None = None, timeout: float = 10.0):
    url = API + (path if path.startswith("/") else "/" + path)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            txt = r.read().decode()
    except urllib.error.HTTPError as e:
        txt = e.read().decode()
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {txt[:300]}") from None
    return json.loads(txt) if txt.strip().startswith(("{", "[")) else txt


def up() -> bool:
    try:
        call("GET", "/sdrangel", timeout=2)
        return True
    except (OSError, RuntimeError):
        return False


# ----------------------------------------------------------------------------- lifecycle

def launch(port: int = 8091, scratch: bool = False, timeout: float = 60) -> None:
    if up():
        return
    env = dict(os.environ)
    env.setdefault("UHD_IMAGES_DIR", str(Path.home() / ".local/share/uhd/images"))
    OUT.mkdir(parents=True, exist_ok=True)
    args = [APP_BIN, "-p", str(port)] + (["--scratch"] if scratch else [])
    log = open(OUT / "sdrangel.log", "ab")
    subprocess.Popen(args, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    t0 = time.time()
    while time.time() - t0 < timeout:
        if up():
            time.sleep(2)               # device enumeration finishes just after the API comes up
            return
        time.sleep(0.5)
    raise RuntimeError("SDRangel API did not come up (see tmp/sdrangel/sdrangel.log)")


def quit_app() -> None:
    if up():
        try:
            call("DELETE", "/sdrangel", timeout=5)
        except (OSError, RuntimeError):
            pass
    t0 = time.time()
    while time.time() - t0 < 10 and subprocess.run(["pgrep", "-if", "SDRangel.app/Contents/MacOS"],
                                                     capture_output=True).returncode == 0:
        time.sleep(0.5)
    if subprocess.run(["pgrep", "-if", "SDRangel.app/Contents/MacOS"], capture_output=True).returncode == 0:
        subprocess.run(["osascript", "-e", 'quit app "SDRangel"'], capture_output=True)
        time.sleep(3)
        subprocess.run(["pkill", "-TERM", "-f", "SDRangel.app/Contents/MacOS"], capture_output=True)


# ----------------------------------------------------------------------------- devices

def devices(direction: int = 0) -> list[dict]:
    return call("GET", f"/sdrangel/devices?direction={direction}")["devices"]


def select(hw: str, channel: int = 0, direction: int = 0, deviceset: int = 0, serial: str | None = None) -> dict:
    """Open a device in a device set. For multi-stream devices (B210: 2 channels) SDRangel lists one entry
    per channel. `channel` picks the n-th entry of that hardware type."""
    cands = [d for d in devices(direction) if d["hwType"].lower() == hw.lower()
             and (serial is None or serial in (d.get("serial") or ""))]
    if not cands:
        raise RuntimeError(f"no {hw} device found (direction={direction}). Is UHD_IMAGES_DIR set for USRP?")
    d = cands[min(channel, len(cands) - 1)]
    return call("PUT", f"/sdrangel/deviceset/{deviceset}/device",
                {"hwType": d["hwType"], "direction": direction, "index": d["index"]})


def get_settings(deviceset: int = 0) -> dict:
    return call("GET", f"/sdrangel/deviceset/{deviceset}/device/settings")


def settings_key(s: dict) -> str:
    keys = [k for k in s if k.endswith("Settings")]
    if not keys:
        raise RuntimeError(f"no *Settings block in {list(s)}")
    return keys[0]


def set_settings(deviceset: int = 0, **kw) -> dict:
    """Patch common fields by name; only keys the device actually has are sent.
    kw: freq, rate, gain, gain_mode ('manual'|'auto'), ant, bw, raw (dict merged into the settings block)."""
    cur = get_settings(deviceset)
    key = settings_key(cur)
    have = cur[key]
    patch: dict = {}
    mapping = {"freq": "centerFrequency", "rate": "devSampleRate", "gain": "gain", "ant": "antennaPath",
               "bw": "lpfBW"}
    for k, field in mapping.items():
        if kw.get(k) is not None:
            if field not in have:
                raise RuntimeError(f"{key} has no '{field}'. Fields: {sorted(have)}")
            v = kw[k]
            patch[field] = int(v) if isinstance(have[field], int) and not isinstance(v, str) else v
    if kw.get("gain_mode"):
        patch["gainMode"] = {"auto": 0, "automatic": 0, "agc": 0, "manual": 1}[kw["gain_mode"]]
    if kw.get("raw"):
        raw = kw["raw"]
        patch.update(raw.get(key, raw))
    body = {"deviceHwType": cur["deviceHwType"], "direction": cur["direction"], key: patch}
    return call("PATCH", f"/sdrangel/deviceset/{deviceset}/device/settings", body)[key]


def run(deviceset: int = 0, on: bool = True) -> dict:
    return call("POST" if on else "DELETE", f"/sdrangel/deviceset/{deviceset}/device/run")


# ----------------------------------------------------------------------------- channels and recording

def channels(deviceset: int = 0) -> list[dict]:
    return call("GET", f"/sdrangel/deviceset/{deviceset}").get("channels", [])   # key absent when empty


def add_channel(ctype: str, deviceset: int = 0, direction: int = 0, offset_hz: float | None = None) -> int:
    before = len(channels(deviceset))
    call("POST", f"/sdrangel/deviceset/{deviceset}/channel", {"channelType": ctype, "direction": direction})
    for _ in range(40):
        ch = channels(deviceset)
        if len(ch) > before:
            idx = ch[-1]["index"]
            if offset_hz is not None:
                call("PATCH", f"/sdrangel/deviceset/{deviceset}/channel/{idx}/settings",
                     {"channelType": ctype, "direction": direction,
                      f"{ctype}Settings": {"inputFrequencyOffset": int(offset_hz)}})
            return idx
        time.sleep(0.1)
    raise RuntimeError(f"channel {ctype} did not appear")


def record(seconds: float, prefix: Path, bits: int = 16, deviceset: int = 0) -> dict:
    """Record baseband IQ with a SigMF File Sink channel (created if missing). bits: 16 (ci16) or 32 (ci32)."""
    prefix = Path(prefix).resolve()
    prefix.parent.mkdir(parents=True, exist_ok=True)
    # Reuse an existing SigMF sink. (Deleting channels over the API crashed SDRangel 7.27.2 on macOS.)
    # A sink created before the device was (re)selected writes its .sigmf-meta without core:sample_rate /
    # core:frequency; fix_meta() fills those in from the sink report and the device settings afterwards.
    sinks = [c for c in channels(deviceset) if c["id"] == "SigMFFileSink"]
    idx = sinks[0]["index"] if sinks else add_channel("SigMFFileSink", deviceset)
    base = f"/sdrangel/deviceset/{deviceset}/channel/{idx}"
    call("PATCH", base + "/settings", {"channelType": "SigMFFileSink", "direction": 0, "SigMFFileSinkSettings": {
        "fileRecordName": str(prefix), "log2RecordSampleSize": {16: 4, 32: 5}[bits], "inputFrequencyOffset": 0,
        "log2Decim": 0}})
    time.sleep(0.3)
    act = {"channelType": "SigMFFileSink", "direction": 0}
    call("POST", base + "/actions", {**act, "SigMFFileSinkActions": {"record": 1}})
    time.sleep(seconds)
    call("POST", base + "/actions", {**act, "SigMFFileSinkActions": {"record": 0}})
    time.sleep(0.8)
    rep = call("GET", base + "/report").get("SigMFFileSinkReport", {})
    meta_p = Path(str(prefix) + ".sigmf-meta")
    fixed = fix_meta(meta_p, rep.get("sinkSampleRate"), deviceset)
    return {"data": str(prefix) + ".sigmf-data", "meta": str(meta_p), "report": rep, "meta_fixed": fixed}


def fix_meta(meta_p: Path, rate, deviceset: int = 0) -> list[str]:
    """Fill core:sample_rate / core:frequency into a SigMF meta if SDRangel left them out."""
    if not meta_p.exists():
        return []
    m = json.loads(meta_p.read_text())
    added = []
    g = m.setdefault("global", {})
    if "core:sample_rate" not in g and rate:
        g["core:sample_rate"] = float(rate)
        added.append("core:sample_rate")
    caps = m.setdefault("captures", [{"core:sample_start": 0}])
    if caps and "core:frequency" not in caps[0]:
        try:
            cur = get_settings(deviceset)
            caps[0]["core:frequency"] = float(cur[settings_key(cur)]["centerFrequency"])
            added.append("core:frequency")
        except (RuntimeError, KeyError, OSError):
            pass
    caps[0].setdefault("core:sample_start", 0)
    if added:
        meta_p.write_text(json.dumps(m, indent=2))
    return added


# ----------------------------------------------------------------------------- screenshots

def grab(path) -> Path:
    if not WINLIST.exists() or WINLIST.stat().st_mtime < WINLIST_SRC.stat().st_mtime:
        subprocess.run(["swiftc", "-O", str(WINLIST_SRC), "-o", str(WINLIST)], check=True)
    out = subprocess.run([str(WINLIST), "SDRangel"], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("SDRangel window not found")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["screencapture", "-x", "-o", "-l", out.stdout.split()[0], str(path)], check=True)
    return path


# ----------------------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--deviceset", type=int, default=0)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("launch")
    sp.add_argument("--port", type=int, default=8091)
    sp.add_argument("--scratch", action="store_true", help="start without the saved configuration")
    sub.add_parser("quit")
    sub.add_parser("status")
    sub.add_parser("devices").add_argument("--tx", action="store_true")
    sp = sub.add_parser("select")
    sp.add_argument("--hw", required=True, help="USRP, HackRF, RTLSDR, ...")
    sp.add_argument("--channel", type=int, default=0, help="n-th entry of that hardware (B210: channel 0/1)")
    sp.add_argument("--serial")
    sp.add_argument("--tx", action="store_true")
    sp = sub.add_parser("set")
    sp.add_argument("--freq", type=f_num)
    sp.add_argument("--rate", type=f_num)
    sp.add_argument("--gain", type=float)
    sp.add_argument("--gain-mode", choices=["manual", "auto"])
    sp.add_argument("--ant", help="USRP: RX2 or TX/RX")
    sp.add_argument("--bw", type=f_num, help="analog low-pass bandwidth")
    sp.add_argument("--json", help="raw settings JSON merged into the device's *Settings block")
    sub.add_parser("run")
    sub.add_parser("stop")
    sub.add_parser("report")
    sub.add_parser("channels")
    sp = sub.add_parser("add-channel")
    sp.add_argument("type")
    sp.add_argument("--offset", type=f_num)
    sp = sub.add_parser("record")
    sp.add_argument("seconds", type=float)
    sp.add_argument("-o", "--out", default=str(OUT / "rec" / "capture"), help="file prefix (no extension)")
    sp.add_argument("--bits", type=int, choices=[16, 32], default=16)
    sub.add_parser("shot").add_argument("path")
    for m in ("get", "delete"):
        sub.add_parser(m).add_argument("path")
    for m in ("patch", "post", "put"):
        sp = sub.add_parser(m)
        sp.add_argument("path")
        sp.add_argument("body", nargs="?", default="{}")
    a = ap.parse_args()
    ds = a.deviceset

    def show(x):
        print(json.dumps(x, indent=2) if not isinstance(x, str) else x)

    if a.cmd == "launch":
        launch(a.port, a.scratch)
        show({"api": API, "up": up()})
    elif a.cmd == "quit":
        quit_app()
    elif a.cmd == "status":
        s = call("GET", "/sdrangel")
        show({"version": s.get("version"), "devicesets": [
            {k: d["samplingDevice"].get(k) for k in ("hwType", "serial", "centerFrequency", "bandwidth", "state")}
            | {"channels": d["channelcount"]} for d in s["devicesetlist"]["deviceSets"]]})
    elif a.cmd == "devices":
        show([{k: d.get(k) for k in ("index", "hwType", "serial", "displayedName", "deviceSetIndex")}
              for d in devices(1 if a.tx else 0)])
    elif a.cmd == "select":
        show(select(a.hw, a.channel, 1 if a.tx else 0, ds, a.serial))
    elif a.cmd == "set":
        show(set_settings(ds, freq=a.freq, rate=a.rate, gain=a.gain, gain_mode=a.gain_mode, ant=a.ant, bw=a.bw,
                          raw=json.loads(a.json) if a.json else None))
    elif a.cmd == "run":
        show(run(ds, True))
    elif a.cmd == "stop":
        show(run(ds, False))
    elif a.cmd == "report":
        show(call("GET", f"/sdrangel/deviceset/{ds}/device/report"))
    elif a.cmd == "channels":
        show(channels(ds))
    elif a.cmd == "add-channel":
        show({"index": add_channel(a.type, ds, 0, a.offset)})
    elif a.cmd == "record":
        show(record(a.seconds, Path(a.out), a.bits, ds))
    elif a.cmd == "shot":
        show(str(grab(a.path)))
    elif a.cmd in ("get", "delete"):
        show(call(a.cmd.upper(), a.path))
    else:
        show(call(a.cmd.upper(), a.path, json.loads(a.body)))


if __name__ == "__main__":
    main()
