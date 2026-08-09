#!/usr/bin/env bash
# Install as .git/hooks/pre-commit (chmod +x).
# Blocks the commit if local disk is critically full — saves you the half-hour
# debugging session that starts with "why did my build mysteriously break?"

set -e

if ! command -v dxcli >/dev/null 2>&1; then
  echo "dxcli not installed; skipping disk guard." >&2
  exit 0
fi

dxcli ci . || {
  echo "Disk guard failed. Run 'dxcli diagnose .' to see why, or 'dxcli ci --no-docker' to skip Docker checks." >&2
  exit 1
}
