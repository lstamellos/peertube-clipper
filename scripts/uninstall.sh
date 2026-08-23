#!/usr/bin/env bash

umask 077

PLUGIN_NPM_NAME="peertube-plugin-clipper"
MODE="container"
PEERTUBE_DEPLOYMENT="skip"
PEERTUBE_ROOT=""
PEERTUBE_USER=""
PEERTUBE_CONFIG_DIR=""
PEERTUBE_STORAGE_DIR=""
PEERTUBE_COMPOSE_DIR=""
PEERTUBE_SERVICE="peertube"
PEERTUBE_CONTAINER_ROOT="/app"
PEERTUBE_PLUGIN_DATA_DIR=""
STATE_DIR=""
PURGE=0
RESTART_PEERTUBE=1
DRY_RUN=0

log() { printf '[peertube-clipper] %s\n' "$*"; }
die() { printf '[peertube-clipper] ERROR: %s\n' "$*" >&2; exit 1; }
run() { if [ "$DRY_RUN" -eq 1 ]; then log "DRY-RUN: $*"; else "$@"; fi; }

usage() {
  cat <<'EOF'
Usage: ./scripts/uninstall.sh [options]

  --mode container|native|external
  --peertube-deployment native|docker|skip
  --peertube-root PATH
  --peertube-user USER
  --peertube-config-dir PATH
  --peertube-storage-dir PATH
  --peertube-compose-dir PATH
  --peertube-service NAME
  --peertube-container-root PATH
  --peertube-plugin-data-dir PATH
  --state-dir PATH
  --purge               Remove persistent Bridge data as well
  --no-restart
  --dry-run
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --peertube-deployment) PEERTUBE_DEPLOYMENT="$2"; shift 2 ;;
    --peertube-root) PEERTUBE_ROOT="$2"; shift 2 ;;
    --peertube-user) PEERTUBE_USER="$2"; shift 2 ;;
    --peertube-config-dir) PEERTUBE_CONFIG_DIR="$2"; shift 2 ;;
    --peertube-storage-dir) PEERTUBE_STORAGE_DIR="$2"; shift 2 ;;
    --peertube-compose-dir) PEERTUBE_COMPOSE_DIR="$2"; shift 2 ;;
    --peertube-service) PEERTUBE_SERVICE="$2"; shift 2 ;;
    --peertube-container-root) PEERTUBE_CONTAINER_ROOT="$2"; shift 2 ;;
    --peertube-plugin-data-dir) PEERTUBE_PLUGIN_DATA_DIR="$2"; shift 2 ;;
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --purge) PURGE=1; shift ;;
    --no-restart) RESTART_PEERTUBE=0; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

case "$PEERTUBE_DEPLOYMENT" in
  native)
    [ -n "$PEERTUBE_ROOT" ] || die "--peertube-root is required for native plugin uninstall"
    [ -n "$PEERTUBE_USER" ] || PEERTUBE_USER="$(stat -c '%U' "$PEERTUBE_ROOT" 2>/dev/null || printf peertube)"
    if [ -z "$PEERTUBE_CONFIG_DIR" ]; then
      base="$(dirname "$(dirname "$(readlink -f "$PEERTUBE_ROOT" 2>/dev/null || printf '%s' "$PEERTUBE_ROOT")")")"
      [ -d "$base/config" ] && PEERTUBE_CONFIG_DIR="$base/config"
    fi
    [ -n "$PEERTUBE_CONFIG_DIR" ] || die "Pass --peertube-config-dir"
    if [ "$DRY_RUN" -eq 1 ]; then
      log "DRY-RUN: uninstall $PLUGIN_NPM_NAME from native PeerTube"
    else
      if [ "$(id -u)" -eq 0 ]; then
        (cd "$PEERTUBE_ROOT" && runuser -u "$PEERTUBE_USER" -- env NODE_CONFIG_DIR="$PEERTUBE_CONFIG_DIR" NODE_ENV=production npm run plugin:uninstall -- --npm-name "$PLUGIN_NPM_NAME") || die "Plugin uninstall failed"
      elif command -v sudo >/dev/null 2>&1; then
        (cd "$PEERTUBE_ROOT" && sudo -u "$PEERTUBE_USER" env NODE_CONFIG_DIR="$PEERTUBE_CONFIG_DIR" NODE_ENV=production npm run plugin:uninstall -- --npm-name "$PLUGIN_NPM_NAME") || die "Plugin uninstall failed"
      else
        die "Cannot run plugin uninstall as $PEERTUBE_USER"
      fi
    fi
    ;;
  docker)
    [ -n "$PEERTUBE_COMPOSE_DIR" ] || die "--peertube-compose-dir is required"
    cid="$(cd "$PEERTUBE_COMPOSE_DIR" && docker compose ps -q "$PEERTUBE_SERVICE" 2>/dev/null)"
    [ -n "$cid" ] || die "PeerTube container not found"
    run docker exec -u peertube -w "$PEERTUBE_CONTAINER_ROOT" "$cid" npm run plugin:uninstall -- --npm-name "$PLUGIN_NPM_NAME" || die "Plugin uninstall failed"
    ;;
  skip) ;;
  *) die "Invalid --peertube-deployment" ;;
esac

case "$MODE" in
  container)
    if [ -z "$STATE_DIR" ]; then
      if [ "${EUID:-$(id -u)}" -eq 0 ]; then STATE_DIR="/var/lib/peertube-clipper"; else STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/peertube-clipper"; fi
    fi
    if [ -f "$STATE_DIR/stack/compose.yaml" ] && [ -f "$STATE_DIR/bridge.env" ]; then
      args=(docker compose --project-name peertube-clipper --env-file "$STATE_DIR/bridge.env" -f "$STATE_DIR/stack/compose.yaml" down)
      [ "$PURGE" -eq 1 ] && args+=(--volumes)
      run "${args[@]}" || die "Could not stop container stack"
    fi
    [ "$PURGE" -eq 1 ] && run rm -rf "$STATE_DIR"
    ;;
  native)
    [ "${EUID:-$(id -u)}" -eq 0 ] || die "Native uninstall requires root"
    run systemctl disable --now peertube-clipper-bridge.service >/dev/null 2>&1 || true
    run rm -f /etc/systemd/system/peertube-clipper-bridge.service
    run systemctl daemon-reload || true
    run rm -rf /opt/peertube-clipper /etc/peertube-clipper
    [ "$PURGE" -eq 1 ] && run rm -rf /var/lib/peertube-clipper
    ;;
  external) ;;
  *) die "Invalid --mode" ;;
esac

if [ "$RESTART_PEERTUBE" -eq 1 ] && [ "$PEERTUBE_DEPLOYMENT" = "docker" ]; then
  (cd "$PEERTUBE_COMPOSE_DIR" && run docker compose restart "$PEERTUBE_SERVICE") || true
fi

log "Uninstall complete"
[ "$PURGE" -eq 0 ] && log "Persistent Bridge data was preserved where applicable"
