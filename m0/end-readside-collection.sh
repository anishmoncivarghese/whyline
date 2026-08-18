#!/usr/bin/env bash
# Restore the real whyline binary and score the read-side check.
# Run this when collection ends — leaving the shim installed indefinitely means
# every invocation keeps appending to a log nobody reads.
set -eu
REAL=/Users/anish/.local/share/uv/tools/whyline/bin/whyline
ln -sf "$REAL" /Users/anish/.local/bin/whyline
echo "restored: $(ls -la /Users/anish/.local/bin/whyline | sed 's/.*whyline ->/whyline ->/')"
whyline --version
echo
python3 "$(dirname "$0")/analyse-readside.py"
