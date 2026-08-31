#!/usr/bin/env bash

# Isolated Phase 2C repository validation.
# Uses a disposable Python environment under /tmp and does not touch
# production Bridge state, PeerTube state, Ollama models, or rendering services.
#
# Preferred mode is a standard venv. On Debian/Ubuntu hosts where the stdlib
# venv module exists but ensurepip/python3-venv is unavailable, the checker
# falls back to a disposable pip --target tree under /tmp instead of requiring
# a system package installation.

umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP="$(mktemp -d /tmp/peertube-clipper-phase2c-check.XXXXXX)" || exit 1
VENV="$TMP/venv"
TARGET="$TMP/site"
STATUS=0
PYTHON=""
PYTHON_ENV=()

cleanup() {
  rm -rf "$TMP" 2>/dev/null || true
}
trap cleanup EXIT

printf '[phase2c-check] root=%s\n' "$ROOT"
printf '[phase2c-check] production_changes=no\n'

# Compile source syntax before dependency installation. This is intentionally
# independent of venv/pip availability.
python3 -m compileall -q \
  "$ROOT/services/clip-bridge/clip_bridge" \
  "$ROOT/services/analysis-worker/clipper_worker" || STATUS=1

if [ "$STATUS" -eq 0 ]; then
  if python3 -m venv "$VENV" >/dev/null 2>&1 && [ -x "$VENV/bin/python" ]; then
    PYTHON="$VENV/bin/python"
    printf '[phase2c-check] python_environment=venv\n'

    "$PYTHON" -m pip install --disable-pip-version-check -q \
      "$ROOT/services/clip-bridge[dev]" \
      "$ROOT/services/analysis-worker[dev]" || STATUS=1
  else
    rm -rf "$VENV" 2>/dev/null || true

    if python3 -m pip --version >/dev/null 2>&1; then
      mkdir -p "$TARGET" || STATUS=1
      PYTHON="python3"
      PYTHON_ENV=(
        "PYTHONPATH=$TARGET:$ROOT/services/clip-bridge:$ROOT/services/analysis-worker"
        "PYTHONNOUSERSITE=1"
      )
      printf '[phase2c-check] python_environment=pip-target\n'

      if [ "$STATUS" -eq 0 ]; then
        python3 -m pip install --disable-pip-version-check -q \
          --target "$TARGET" \
          "$ROOT/services/clip-bridge[dev]" \
          "$ROOT/services/analysis-worker[dev]" || STATUS=1
      fi
    else
      printf '[phase2c-check] python_environment=unavailable\n' >&2
      printf '[phase2c-check] ERROR=no functional venv and python3 -m pip is unavailable\n' >&2
      STATUS=1
    fi
  fi
fi

run_python() {
  if [ "${#PYTHON_ENV[@]}" -gt 0 ]; then
    env "${PYTHON_ENV[@]}" "$PYTHON" "$@"
  else
    "$PYTHON" "$@"
  fi
}

if [ "$STATUS" -eq 0 ]; then
  (
    cd "$ROOT/services/clip-bridge" || exit 1
    run_python -m pytest -q
  ) || STATUS=1
fi

if [ "$STATUS" -eq 0 ]; then
  (
    cd "$ROOT/services/analysis-worker" || exit 1
    run_python -m pytest -q
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
