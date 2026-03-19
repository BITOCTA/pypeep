#!/usr/bin/env bash
# Runs parse.py on inline Python code passed via stdin.
# Handles temp file creation and cleanup automatically.
#
# Usage: echo 'print("hi")' | bash run_snippet.sh [--mode overview|locals|full]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TMPFILE=$(mktemp /tmp/pypeep_XXXXXX.py)
trap 'rm -f "$TMPFILE"' EXIT

cat > "$TMPFILE"
python "$SCRIPT_DIR/parse.py" "$TMPFILE" "$@"
