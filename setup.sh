#!/bin/bash
#
# One-time After Effects permissions setup for the motion graphics pipeline.
#
# nexrender patches AE's commandLineRenderer.jsx so the pipeline can drive AE
# headlessly. The patch step needs to write inside /Applications/Adobe After
# Effects */, which is owned by root. This script creates the Backup.Scripts
# folder and hands ownership to the current user so subsequent pipeline runs
# can patch without sudo.
#
# Usage:
#   sudo bash setup.sh
#
set -e

if [ "$EUID" -ne 0 ]; then
    echo "This script must be run with sudo:"
    echo "  sudo bash setup.sh"
    exit 1
fi

AE_DIR=$(ls -d "/Applications/Adobe After Effects "* 2>/dev/null | sort -V | tail -1)

if [ -z "$AE_DIR" ]; then
    echo "Error: No Adobe After Effects install found in /Applications/"
    echo "Install After Effects 2026 or newer, then re-run this script."
    exit 1
fi

echo "Found: $AE_DIR"

mkdir -p "$AE_DIR/Backup.Scripts/Startup"
mkdir -p "$AE_DIR/Support Files/Startup"
chown -R "$SUDO_USER" "$AE_DIR/Backup.Scripts"
chown -R "$SUDO_USER" "$AE_DIR/Support Files/Startup"

echo ""
echo "Done. You can now run the pipeline normally."
