#!/usr/bin/env bash

# Isolated Phase 2C repository validation.
# Creates a disposable virtualenv under /tmp and does not touch production
# Bridge state, PeerTube state, Ollama models, or rendering services.

umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d /tmp/peertube-clipper-phase2c-check.XXXXXX)" || exit 1
VENV="$TMP/venv"
STATUS=0

cleanup() {
  rm -rf "$TMP" 2>/dev/null || true
}
trap cleanup EXIT

printf '[phase2c-check] root=%s\n' "$ROOT"
printf '[phase2c-check] production_changes=no\n'

python3 -m venv "$VENV" || STATUS=1

if [ "$STATUS" -eq 0 ]; then
  "$VENV/bin/python" -m pip install --disable-pip-version-check -q \
    "$ROOT/services/clip-bridge[dev]" \
    "$ROOT/services/analysis-worker[dev]" || STATUS=1
fi

if [ "$STATUS" -eq 0 ]; then
  (
    cd "$ROOT/services/clip-bridge" || exit 1
    "$VENV/bin/python" -m pytest -q
  ) || STATUS=1
fi

if [ "$STATUS" -eq 0 ]; then
  (
    cd "$ROOT/services/analysis-worker" || exit 1
    "$VENV/bin/python" -m pytest -q
  ) || STATUS=1
fi

if [ "$STATUS" -eq 0 ]; then
  (
    cd "$ROOT" || exit 1
    npm run check
  ) || STATUS=1
fi

if [ "$STATUS" -eq 0 ]; then
  printf '[phase2c-check] PHASE2C_ISOLATED_CHECK=PASS\n'
else
  printf '[phase2c-check] PHASE2C_ISOLATED_CHECK=FAIL\n' >&2
fi

exit "$STATUS"
