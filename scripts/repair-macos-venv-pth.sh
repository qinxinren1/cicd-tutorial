#!/usr/bin/env bash
# macOS: PEP 660 editable installs add __editable__*.pth under site-packages.
# If those files have the UF_HIDDEN flag (common under iCloud Desktop), Python 3.11+
# skips them (site.addpackage), so imports like jobpilot_enrich fail until you reinstall.
# Clearing the flag fixes it without reinstall. Re-run after pip install -e . if needed.
#
# Usage: ./scripts/repair-macos-venv-pth.sh [path/to/venv]
# Default: .venv-jobpilot next to this repo when run from job-pilot/

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="${1:-$ROOT/.venv-jobpilot}"
SP="$VENV/lib/python3.11/site-packages"
if [[ ! -d "$SP" ]]; then
  # Try generic layout (any Python version)
  SP="$(find "$VENV/lib" -maxdepth 2 -type d -name site-packages 2>/dev/null | head -1)"
fi
if [[ -z "${SP:-}" || ! -d "$SP" ]]; then
  echo "Could not find site-packages under: $VENV" >&2
  exit 1
fi
shopt -s nullglob
for f in "$SP"/*.pth; do
  chflags nohidden "$f" 2>/dev/null || true
done
echo "Cleared hidden flag on .pth files in: $SP"
echo "Test: $VENV/bin/python -c 'import jobpilot_enrich'"
