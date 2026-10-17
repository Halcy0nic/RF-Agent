#!/usr/bin/env bash
# Install UHD images for a USRP B200/B210, including the OpenSourceSDRLab Artix-7 B210 FPGA image,
# and point UHD (CLI tools, GNU Radio, SDRangel) at them via UHD_IMAGES_DIR.
#
#   radios/usrp-b210/tools/setup_images.sh                       # stock Ettus B210 (Spartan-6)
#   radios/usrp-b210/tools/setup_images.sh --variant 75T         # OpenSourceSDRLab Artix-7 XC7A75T
#   radios/usrp-b210/tools/setup_images.sh --variant 200T        # OpenSourceSDRLab Artix-7 XC7A200T
#   options: --dir <images dir>   (default ~/.local/share/uhd/images)
#            --no-shell           (don't add UHD_IMAGES_DIR to ~/.zshrc)
#            --no-launchagent     (macOS: don't install the login LaunchAgent)
#
# Idempotent: safe to re-run (e.g. after a UHD upgrade, to refresh the stock images).
set -euo pipefail

VARIANT="ettus"
DIR="$HOME/.local/share/uhd/images"
SHELL_RC=1
AGENT=1
while [ $# -gt 0 ]; do
  case "$1" in
    --variant) VARIANT="$2"; shift 2 ;;
    --dir) DIR="$2"; shift 2 ;;
    --no-shell) SHELL_RC=0; shift ;;
    --no-launchagent) AGENT=0; shift ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
done

REPO_RAW="https://raw.githubusercontent.com/OpenSourceSDRLab/USRP-B210-Artix-7-AD9361/main/Bin%20file"
# git blob SHA-1 of each vendor image (from the GitHub tree API), used to verify the download
SHA_75T="c6ad69d99ce350fd87a2fec9df0677377d4ad23f"
SHA_200T="b343fc0bd4f5e1f5b9a74afbfc99a85e851ea6d6"

mkdir -p "$DIR"

# 1. Stock UHD images for B2xx (FX3 firmware, bootloader, Ettus FPGA images)
DL=""
if command -v brew >/dev/null 2>&1 && [ -f "$(brew --prefix uhd 2>/dev/null)/lib/uhd/utils/uhd_images_downloader.py" ]; then
  DL="$(brew --prefix uhd)/lib/uhd/utils/uhd_images_downloader.py"
elif command -v uhd_images_downloader >/dev/null 2>&1; then
  DL="$(command -v uhd_images_downloader)"
elif [ -f /usr/lib/uhd/utils/uhd_images_downloader.py ]; then
  DL=/usr/lib/uhd/utils/uhd_images_downloader.py
fi
[ -n "$DL" ] || { echo "uhd_images_downloader not found (install UHD first)" >&2; exit 1; }
PY=python3
"$PY" -c "import requests" 2>/dev/null || PY="$(dirname "$0")/../../../.venv/bin/python"
"$PY" -c "import requests" 2>/dev/null || { echo "python 'requests' module needed: pip install requests" >&2; exit 1; }
# --refetch: always rewrite the stock files, so usrp_b210_fpga.bin is the Ettus image again before step 2
if [[ "$DL" == *.py ]]; then "$PY" "$DL" -t b2xx -i "$DIR" --refetch; else "$DL" -t b2xx -i "$DIR" --refetch; fi

# 2. Vendor FPGA image for the Artix-7 boards. The downloader just rewrote usrp_b210_fpga.bin with the
#    Ettus Spartan-6 image: keep that as .ettus-spartan6 and put the vendor image in its place.
if [ "$VARIANT" != "ettus" ]; then
  case "$VARIANT" in
    75T|75t) PART=XC7A75T; SHA=$SHA_75T ;;
    200T|200t) PART=XC7A200T; SHA=$SHA_200T ;;
    *) echo "--variant must be 75T, 200T or ettus" >&2; exit 1 ;;
  esac
  TMP="$(mktemp -d)"
  curl -fsSL -o "$TMP/fpga.bin" "$REPO_RAW/$PART/usrp_b210_fpga.bin"
  GOT="$(git hash-object "$TMP/fpga.bin")"
  if [ "$GOT" != "$SHA" ]; then echo "hash mismatch for $PART image: $GOT (expected $SHA)" >&2; exit 1; fi
  if [ "$(git hash-object "$DIR/usrp_b210_fpga.bin")" != "$SHA" ]; then
    cp "$DIR/usrp_b210_fpga.bin" "$DIR/usrp_b210_fpga.bin.ettus-spartan6"
  fi
  cp "$TMP/fpga.bin" "$DIR/usrp_b210_fpga.bin"
  cp "$TMP/fpga.bin" "$DIR/usrp_b210_fpga_opensourcesdrlab_$(echo "$PART" | tr 'A-Z' 'a-z').bin"
  rm -rf "$TMP"
  echo "installed OpenSourceSDRLab $PART FPGA image as $DIR/usrp_b210_fpga.bin"
fi

# 3. UHD_IMAGES_DIR for shells
if [ "$SHELL_RC" = 1 ]; then
  RC="$HOME/.zshrc"; [ -n "${BASH_VERSION:-}" ] && [ "$(basename "${SHELL:-}")" = bash ] && RC="$HOME/.bashrc"
  LINE="export UHD_IMAGES_DIR=\"$DIR\""
  grep -qF "$LINE" "$RC" 2>/dev/null || { printf '\n# UHD images (USRP B2xx)\n%s\n' "$LINE" >> "$RC"; echo "added UHD_IMAGES_DIR to $RC"; }
fi

# 4. macOS: make GUI apps (SDRangel, GNU Radio Companion) launched from the Dock/Finder see it too
if [ "$(uname)" = Darwin ] && [ "$AGENT" = 1 ]; then
  PLIST="$HOME/Library/LaunchAgents/local.uhd-images-dir.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.uhd-images-dir</string>
  <key>ProgramArguments</key>
  <array><string>/bin/launchctl</string><string>setenv</string><string>UHD_IMAGES_DIR</string><string>$DIR</string></array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
  launchctl unload "$PLIST" 2>/dev/null || true
  launchctl load "$PLIST"
  launchctl setenv UHD_IMAGES_DIR "$DIR"
  echo "LaunchAgent installed: $PLIST (GUI apps started from now on see UHD_IMAGES_DIR)"
fi

echo "UHD_IMAGES_DIR=$DIR"
ls -l "$DIR" | grep -E "b200_fw|b210_fpga" || true
