"""Drive SDR++ without the mouse: config edits, the rigctl server, the baseband recorder and window screenshots.

Works on macOS (`open -a`, `screencapture`) and Linux (direct launch, SIGTERM quit, GNOME/X11 screenshots).

Isolated mode (default): SDR++ is launched with its `-r <root>` flag pointing at a private config directory
(tmp/sdrpp/root, seeded once from your normal config), so the normal SDR++ config is left as it was. Set SDRPP_ISOLATED=0 to drive the normal config instead (then use
backup_config()/restore_config()).

How SDR++ behaves (and why this module looks the way it does):
  * SDR++ reads source/display settings ONLY at startup and REWRITES its JSON config on exit. A settings change
    is therefore always: quit -> edit JSON -> relaunch. Never edit the JSON while SDR++ is running; your edit
    is overwritten when it exits.
  * Runtime control goes through the Rigctl Server module (Hamlib rigctld protocol, TCP localhost:4532):
        F <hz> | f                 set / get frequency (VFO or, with no VFO selected, the centre frequency)
        M <mode> <bw> | m          set / get demod mode of the selected Radio VFO (Hamlib names: FM (= NFM),
                                   WFM AM DSB USB LSB CW RAW; "NFM" is rejected)
        \\start | \\stop             start / stop the source (same as the play button)
        \\recorder_start | \\recorder_stop   (aliases AOS / LOS) start / stop the Recorder module
        \\dump_state, \\chk_vfo, \\get_powerstat, q | \\quit
    Replies are Hamlib style: "RPRT 0" = OK, negative = error.
  * \\recorder_start replies RPRT 0 but does NOTHING unless rigctl_server_config.json has
    "recording": true and "recorder": "<recorder instance name>".
  * Screenshots use `screencapture -l <windowID>`; the ID comes from winlist.swift (CoreGraphics window list).

Typical use::

    import sdrpp
    sdrpp.backup_config()                                  # once, before touching anything
    sdrpp.restart_with(dict(source="RTL-SDR", freq=433.92e6, sample_rate=1_024_000, gain=20))
    sdrpp.tune(433_920_000)
    wav = sdrpp.record(5.0)                                # -> Path of the baseband WAV
    sdrpp.grab("waterfall.png")
    sdrpp.restore_config()                                 # put the user's settings back
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

MAC = sys.platform == "darwin"
USER_CFG_DIR = (Path.home() / "Library/Application Support/sdrpp" if MAC       # SDR++'s normal config
                else Path.home() / ".config/sdrpp")
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = Path(os.environ.get("SDRPP_OUT", REPO / "tmp" / "sdrpp"))
ISOLATED = os.environ.get("SDRPP_ISOLATED", "1") != "0"
ROOT = OUT / "root"
CFG_DIR = Path(os.environ.get("SDRPP_CONFIG_DIR", ROOT if ISOLATED else USER_CFG_DIR))
REC_DIR = OUT / "rec"
BACKUP_DIR = OUT / "config_backup"
WINLIST_SRC = REPO / "tools" / "winlist.swift"      # shared with software/sdrangel/tools
WINLIST = REPO / "tools" / "winlist"
XDISPLAY = os.environ.get("SDRPP_XDISPLAY", ":99")
APP = "SDR++"
PROC = "sdrpp"
RIGCTL = ("localhost", int(os.environ.get("SDRPP_RIGCTL_PORT", 4532)))

# RTL-SDR gain index (what SDR++ stores) -> dB for R820T/R828D tuners (RTL-SDR Blog V3/V4)
RTL_GAIN_DB = [0.0, 0.9, 1.4, 2.7, 3.7, 7.7, 8.7, 12.5, 14.4, 15.7, 16.6, 19.7, 20.7, 22.9, 25.4, 28.0, 29.7,
               32.8, 33.8, 36.4, 37.2, 38.6, 40.2, 42.1, 43.4, 43.9, 44.5, 48.0, 49.6]

# HackRF baseband filter index used by SDR++ ("bandwidth" key). 16 = Auto (follows the sample rate).
HACKRF_BW_AUTO = 16


# ----------------------------------------------------------------------------- config backup / restore

def ensure_root() -> Path:
    """Create the isolated config root by copying the user's SDR++ JSON files once (device names, module
    list and plugin paths then match the installed SDR++). If there is no user config yet, SDR++ creates
    defaults in the empty root on first launch."""
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    if CFG_DIR != USER_CFG_DIR and not (CFG_DIR / "config.json").exists():
        for p in USER_CFG_DIR.glob("*.json"):
            shutil.copy2(p, CFG_DIR / p.name)
    return CFG_DIR


def backup_config(dst: Path = BACKUP_DIR, overwrite: bool = False) -> Path:
    """Copy the user's SDR++ *.json config (USER_CFG_DIR). Does not overwrite an existing backup unless asked,
    so the FIRST backup (the user's real settings) survives repeated runs. Quits SDR++ first so the files are
    current. Not needed in isolated mode, but harmless."""
    quit_app()
    dst.mkdir(parents=True, exist_ok=True)
    if overwrite or not any(dst.glob("*.json")):
        for p in USER_CFG_DIR.glob("*.json"):
            shutil.copy2(p, dst / p.name)
    return dst


def restore_config(src: Path = BACKUP_DIR, relaunch: bool = False) -> None:
    """Quit SDR++ and copy the backed-up JSON files back into the user's config directory."""
    quit_app()
    files = list(src.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no backup in {src}")
    for p in files:
        shutil.copy2(p, USER_CFG_DIR / p.name)
    if relaunch:
        subprocess.run(["open", "-a", APP] if MAC else [PROC])


def read_config(name: str = "config.json") -> dict:
    return json.loads((CFG_DIR / name).read_text())


def edit_config(name: str, fn) -> None:
    """Load a config file, let fn mutate the dict, write it back. SDR++ must not be running."""
    assert not running(), "quit SDR++ before editing its config (it rewrites the file on exit)"
    p = CFG_DIR / name
    c = json.loads(p.read_text()) if p.exists() else {}
    fn(c)
    p.write_text(json.dumps(c, indent=4))


# ----------------------------------------------------------------------------- app lifecycle

def running() -> bool:
    return subprocess.run(["pgrep", "-x", PROC], capture_output=True).returncode == 0


def quit_app(timeout: float = 15) -> None:
    """Graceful quit (SDR++ saves its config), then SIGTERM if it hangs."""
    if not running():
        return
    if MAC:
        subprocess.run(["osascript", "-e", f'quit app "{APP}"'], capture_output=True)
    else:
        subprocess.run(["pkill", "-INT", "-x", PROC])
    t0 = time.time()
    while running() and time.time() - t0 < timeout:
        time.sleep(0.3)
    if running():
        subprocess.run(["pkill", "-TERM", "-x", PROC])
        time.sleep(2)


def _linux_env() -> dict:
    """Linux: run SDR++ on a private virtual X display (Xvfb) so screenshots work under Wayland/GNOME, which
    blocks window grabs. Needs: sudo apt install xvfb xdotool imagemagick. SDRPP_HEADLESS=0 uses your desktop
    (then grab() cannot work under Wayland)."""
    env = dict(os.environ)
    if os.environ.get("SDRPP_HEADLESS", "1") == "0":
        return env
    if subprocess.run(["pgrep", "-f", f"Xvfb {XDISPLAY}"], capture_output=True).returncode != 0:
        subprocess.Popen(["Xvfb", XDISPLAY, "-screen", "0", "1600x900x24"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1.5)
    env.pop("WAYLAND_DISPLAY", None)
    env.update(DISPLAY=XDISPLAY, XDG_SESSION_TYPE="x11", LIBGL_ALWAYS_SOFTWARE="1")
    return env


def launch(timeout: float = 60) -> None:
    """Open SDR++ (with -r <root> in isolated mode) and wait until the rigctl server accepts connections.
    `open -a ... --args` only passes arguments to a fresh launch, so SDR++ must not already be running."""
    args = ["-r", str(CFG_DIR)] if CFG_DIR != USER_CFG_DIR else []
    if MAC:
        subprocess.run(["open", "-a", APP, *(["--args", *args] if args else [])])
    else:
        OUT.mkdir(parents=True, exist_ok=True)
        log = open(OUT / "sdrpp.log", "ab")
        subprocess.Popen([PROC, *args], stdout=log, stderr=log, start_new_session=True, env=_linux_env())
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(RIGCTL, timeout=1):
                time.sleep(1.5)       # let the source module finish initialising
                return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError("SDR++ rigctl server did not come up. Is autoStart set? Is a macOS "
                       "'reopen windows' / crash dialog waiting for a click?")


def apply_profile(p: dict) -> None:
    """Write a capture profile into the SDR++ config. SDR++ must be stopped.

    Keys (all optional except freq):
      source       "RTL-SDR" (default) | "HackRF"
      freq         centre frequency, Hz
      sample_rate  Hz (RTL: 250e3, 1.024e6, 2.048e6, 2.4e6 ... ; HackRF: 2e6 - 20e6)
      gain         RTL gain INDEX 0-28 (see RTL_GAIN_DB; 20 = 37.2 dB)      [RTL-SDR]
      ppm          RTL frequency correction                                   [RTL-SDR]
      lna, vga     HackRF LNA (0-40, step 8) and VGA (0-62, step 2) gains    [HackRF]
      amp          HackRF RF amp on/off (default off)                         [HackRF]
      fft_size, fft_rate, min_db, max_db, colormap, decimation, show_menu, show_waterfall, fft_height
      radio        True to keep the Radio VFO (needed for demod/audio and the rigctl M command)
      rec_mode     0 = baseband IQ (default), 1 = audio (needs radio=True)
      rec_dir      where the Recorder writes (default tmp/sdrpp/rec)
      rigctl_port  default 4532
    """
    assert not running(), "quit SDR++ before editing its config"
    ensure_root()
    src = p.get("source", "RTL-SDR")
    rec_dir = Path(p.get("rec_dir", REC_DIR))
    rec_dir.mkdir(parents=True, exist_ok=True)
    radio = bool(p.get("radio", False))

    def main(c):
        c.update({
            "source": src,
            "frequency": float(p["freq"]),
            "fftSize": int(p.get("fft_size", 8192)),
            "fftRate": int(p.get("fft_rate", 30)),
            "colorMap": p.get("colormap", "Classic"),
            "min": float(p.get("min_db", -80)),
            "max": float(p.get("max_db", -30)),
            "showMenu": bool(p.get("show_menu", True)),
            "showWaterfall": bool(p.get("show_waterfall", True)),
            "fftHeight": int(p.get("fft_height", 250)),
            "fftHold": False,
            "fftSmoothing": False,
            "centerTuning": False,
            "bandPlanEnabled": False,
            "decimation": int(p.get("decimation", 1)),
            "maximized": bool(p.get("maximized", True)),
        })
        mi = c.setdefault("moduleInstances", {})
        mi.setdefault("Radio", {"enabled": True, "module": "radio"})["enabled"] = radio
        mi.setdefault("Recorder", {"enabled": True, "module": "recorder"})["enabled"] = True
        mi.setdefault("Rigctl Server", {"enabled": True, "module": "rigctl_server"})["enabled"] = True
        if not radio:
            # No demod VFO: avoids a known SDR++ segfault when decimation makes the VFO wider than the span,
            # and keeps the VFO overlay out of screenshots. Baseband recording does not need it.
            c["vfoOffsets"] = {}
    edit_config("config.json", main)

    if src == "RTL-SDR":
        def rtl(c):
            dev = c.get("device") or next(iter(c.get("devices", {})), "")
            c["device"] = dev
            d = c.setdefault("devices", {}).setdefault(dev, {})
            d.update({"sampleRate": float(p.get("sample_rate", 2_048_000)), "gain": int(p.get("gain", 20)),
                      "ppm": int(p.get("ppm", 0)), "rtlAgc": False, "tunerAgc": False,
                      "biasT": bool(p.get("bias_t", False)), "offsetTuning": False,
                      "directSampling": int(p.get("direct_sampling", 0))})
        edit_config("rtl_sdr_config.json", rtl)
    elif src == "HackRF":
        def hrf(c):
            serial = c.get("device") or next((k for k in c.get("devices", {}) if k), "")
            c["device"] = serial
            d = c.setdefault("devices", {}).setdefault(serial, {})
            d.update({"sampleRate": float(p.get("sample_rate", 4_000_000)), "lnaGain": int(p.get("lna", 24)),
                      "vgaGain": int(p.get("vga", 20)), "amp": bool(p.get("amp", False)),
                      "biasT": False, "bandwidth": int(p.get("hackrf_bw", HACKRF_BW_AUTO))})
        edit_config("hackrf_config.json", hrf)
    else:
        raise ValueError(f"unsupported source {src!r}")

    def rec(c):
        r = c.setdefault("Recorder", {})
        r.update({"mode": int(p.get("rec_mode", 0)), "recPath": str(rec_dir),
                  "nameTemplate": p.get("name_template", "$t_$f_$h-$m-$s_$d-$M-$y")})
        # container / sampleType are STRINGS in current SDR++. An integer here makes SDR++ abort at launch
        # (nlohmann::json type_error in RecorderModule). Drop anything non-string so the defaults (WAV/int16) apply.
        for k in ("container", "sampleType"):
            if k in r and not isinstance(r[k], str):
                r.pop(k)
    edit_config("recorder_config.json", rec)

    def rig(c):
        c.setdefault("Rigctl Server", {}).update({
            "autoStart": True, "host": "localhost", "port": int(p.get("rigctl_port", RIGCTL[1])),
            "recorder": "Recorder", "recording": True, "tuning": True, "vfo": "Radio" if radio else ""})
    edit_config("rigctl_server_config.json", rig)


def restart_with(profile: dict, attempts: int = 3, start_source: bool = True) -> None:
    """quit -> apply_profile -> launch -> \\start, with retries (a slow first launch can miss the timeout)."""
    for i in range(attempts):
        quit_app()
        apply_profile(profile)
        try:
            launch()
            if start_source:
                start()
            return
        except RuntimeError:
            if i == attempts - 1:
                raise
            time.sleep(5)


# ----------------------------------------------------------------------------- rigctl

def rig(cmd: str, timeout: float = 3.0) -> str:
    """Send one rigctl command line and return the reply text (stripped)."""
    with socket.create_connection(RIGCTL, timeout=timeout) as s:
        s.sendall((cmd.rstrip("\n") + "\n").encode())
        s.settimeout(timeout)
        chunks = []
        t0 = time.time()
        while time.time() - t0 < timeout:
            try:
                b = s.recv(4096)
            except socket.timeout:
                break
            if not b:
                break
            chunks.append(b)
            if b.endswith(b"\n") and (b"RPRT" in b or cmd.strip() in ("f", "m", "v", "\\get_freq", "\\get_mode",
                                                                         "\\get_vfo", "\\get_powerstat")):
                break
            if cmd.startswith("\\dump_state"):
                s.settimeout(0.3)
        return b"".join(chunks).decode(errors="replace").strip()


def ok(reply: str) -> bool:
    return reply.strip().endswith("RPRT 0")


def start() -> str:
    return rig("\\start")


def stop() -> str:
    return rig("\\stop")


def tune(hz: float) -> str:
    return rig(f"F {int(round(hz))}")


def get_freq() -> float:
    return float(rig("f").split()[0])


def set_mode(mode: str, bandwidth_hz: int = 0) -> str:
    """Needs a Radio VFO selected for rigctl (profile radio=True). Hamlib modes: FM (SDR++ NFM), WFM, AM, DSB,
    USB, LSB, CW, RAW. "NFM" itself is rejected with RPRT 1."""
    return rig(f"M {mode} {int(bandwidth_hz)}")


def rec_start() -> str:
    return rig("\\recorder_start")


def rec_stop() -> str:
    return rig("\\recorder_stop")


def record(seconds: float, rec_dir: Path = REC_DIR, dest: Path | None = None) -> Path:
    """Record `seconds` of whatever the Recorder is set to (baseband by default). Returns the new file."""
    before = set(rec_dir.glob("*.wav"))
    r = rec_start()
    if not ok(r):
        raise RuntimeError(f"recorder_start failed: {r!r}")
    time.sleep(seconds)
    rec_stop()
    time.sleep(0.8)                      # the recorder closes/patches the WAV header asynchronously
    new = sorted(set(rec_dir.glob("*.wav")) - before, key=lambda q: q.stat().st_mtime)
    if not new:
        raise RuntimeError(f"no recording appeared in {rec_dir}. Check rigctl 'recording'/'recorder' settings.")
    if dest:
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        return Path(shutil.move(str(new[-1]), dest))
    return new[-1]


# ----------------------------------------------------------------------------- screenshots

def ensure_winlist() -> Path:
    if not WINLIST.exists() or WINLIST.stat().st_mtime < WINLIST_SRC.stat().st_mtime:
        subprocess.run(["swiftc", "-O", str(WINLIST_SRC), "-o", str(WINLIST)], check=True)
    return WINLIST


def window() -> tuple[int, int, int, int, int]:
    """(window_id, x, y, w, h) of the largest SDR++ window."""
    out = subprocess.run([str(ensure_winlist()), APP], capture_output=True, text=True, check=True).stdout
    wid, x, y, w, h = map(int, out.split())
    return wid, x, y, w, h


def grab(path, retries: int = 3) -> Path:
    """Screenshot the SDR++ window (no shadow). Needs Screen Recording permission for the calling app.
    If the display is asleep, screencapture fails; we nudge it awake with `caffeinate -u` and retry."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not MAC:
        env = _linux_env()
        for _ in range(retries):
            ids = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", "SDR\\+\\+"], env=env,
                                 capture_output=True, text=True).stdout.split()
            if ids:
                subprocess.run(["import", "-window", ids[-1], str(path)], env=env, check=True)
                return path
            time.sleep(1)
        raise RuntimeError("SDR++ window not found on the Xvfb display (sudo apt install xvfb xdotool imagemagick)")
    last = None
    for _ in range(retries):
        try:
            wid = window()[0]
            subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), str(path)], check=True)
            return path
        except subprocess.CalledProcessError as e:
            last = e
            subprocess.run(["caffeinate", "-u", "-t", "2"])
    raise RuntimeError(f"screenshot failed: {last}")


def status() -> dict:
    """Snapshot of what SDR++ is doing (safe to call any time)."""
    d = {"running": running(), "rigctl": False, "config_dir": str(CFG_DIR), "isolated": CFG_DIR != USER_CFG_DIR}
    if d["running"]:
        try:
            d["freq_hz"] = get_freq()
            d["rigctl"] = True
            d["mode"] = rig("m")
        except OSError:
            pass
    try:
        c = read_config()
        d.update({"source": c.get("source"), "config_freq_hz": c.get("frequency")})
        rs = read_config("rigctl_server_config.json").get("Rigctl Server", {})
        d["rigctl_config"] = rs
    except FileNotFoundError:
        pass
    return d
