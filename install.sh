#!/usr/bin/env bash
# Installs the transcode command into ~/.local/bin.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"

command -v python3 >/dev/null || { echo "transcode needs python3." >&2; exit 1; }
command -v ffmpeg >/dev/null || echo "Note: ffmpeg not found. Install it with: sudo pacman -S ffmpeg"

mkdir -p ~/.local/bin
chmod +x "$here/transcode.py"
ln -sf "$here/transcode.py" ~/.local/bin/transcode

case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "Note: add ~/.local/bin to your PATH to run 'transcode' from a terminal." ;;
esac
echo "Installed. Open a terminal in a folder with videos and run 'transcode'."
