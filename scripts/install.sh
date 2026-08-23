#!/usr/bin/env bash

# PeerTube Clipper general installer.
# No persistent strict-mode shell options are enabled, so this script is safe
# to invoke from an interactive administration shell.

umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN="$ROOT/packages/peertube-plugin-clipper"
PLUGIN_NAME="peertube-plugin-clipper"

MODE="container"
PT_MODE="auto"
PT_ROOT=""
PT_USER=""
PT_CONFIG=""
PT_STORAGE=""
PT_COMPOSE=""
PT_SERVICE="peertube"
PT_CONTAINER_ROOT="/app"
PT_PLUGIN_DATA=""

BRIDGE_BIND="127.0.0.1"
BRIDGE_PORT="18100"
BRIDGE_URL=""
TOKEN_FILE=""
STATE_DIR=""
WITH_ANALYSIS=0
MODEL="qwen3:1.7b"

DRY_RUN=0
NO_RESTART=0
SKIP_PLUGIN=0
TOKEN=""

say()  { printf '[peertube-clipper] %s\n' "$*"; }
warn() { printf '[peertube-clipper] WARNING: %s\n' "$*" >&2; }
die()  { printf '[peertube-clipper] ERROR: %s\n' "$*" >&2; exit 1; }

run() {
  if [ "$DRY_RUN" -eq 1 ]; then
    printf '[peertube-clipper] DRY-RUN:'
    printf ' %q' "$@"
    printf '\n'
  else
    "$@"
  fi
}

need() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

usage() {
  cat <<'USAGE'
Usage: ./scripts/install.sh [options]

Companion services:
  --mode container|native|external   default: container
  --bridge-bind ADDRESS              default: 127.0.0.1
  --bridge-port PORT                 default: 18100
  --bridge-url URL                   URL used by the PeerTube plugin
  --bridge-token-file PATH           token for external mode
  --state-dir PATH                   container deployment state directory
  --with-analysis                    provision Ollama in container mode
  --model NAME                       default: qwen3:1.7b

PeerTube:
  --peertube-deployment auto|native|docker|skip
  --peertube-root PATH
  --peertube-user USER
  --peertube-config-dir PATH
  --peertube-storage-dir PATH
  --peertube-compose-dir PATH
  --peertube-service NAME            default: peertube
  --peertube-container-root PATH     default: /app
  --peertube-plugin-data-dir PATH
  --skip-plugin
  --no-restart

Other:
  --dry-run
  -h, --help
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --bridge-bind) BRIDGE_BIND="$2"; shift 2 ;;
    --bridge-port) BRIDGE_PORT="$2"; shift 2 ;;
    --bridge-url) BRIDGE_URL="$2"; shift 2 ;;
    --bridge-token-file) TOKEN_FILE="$2"; shift 2 ;;
    --state-dir) STATE_DIR="$2"; shift 2 ;;
    --with-analysis) WITH_ANALYSIS=1; shift ;;
    --model) MODEL="$2"; shift 2 ;;
    --peertube-deployment) PT_MODE="$2"; shift 2 ;;
    --peertube-root) PT_ROOT="$2"; shift 2 ;;
    --peertube-user) PT_USER="$2"; shift 2 ;;
    --peertube-config-dir) PT_CONFIG="$2"; shift 2 ;;
    --peertube-storage-dir) PT_STORAGE="$2"; shift 2 ;;
    --peertube-compose-dir) PT_COMPOSE="$2"; shift 2 ;;
    --peertube-service) PT_SERVICE="$2"; shift 2 ;;
    --peertube-container-root) PT_CONTAINER_ROOT="$2"; shift 2 ;;
    --peertube-plugin-data-dir) PT_PLUGIN_DATA="$2"; shift 2 ;;
    --skip-plugin) SKIP_PLUGIN=1; PT_MODE="skip"; shift ;;
    --no-restart) NO_RESTART=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

case "$MODE" in container|native|external) ;; *) die "Invalid --mode: $MODE" ;; esac
case "$PT_MODE" in auto|native|docker|skip) ;; *) die "Invalid --peertube-deployment: $PT_MODE" ;; esac
case "$BRIDGE_PORT" in ''|*[!0-9]*) die "Invalid --bridge-port" ;; esac
[ "$BRIDGE_PORT" -ge 1 ] 2>/dev/null && [ "$BRIDGE_PORT" -le 65535 ] 2>/dev/null || die "Invalid --bridge-port"
[ -d "$PLUGIN" ] || die "Plugin source is missing: $PLUGIN"

if [ "$PT_MODE" = auto ]; then
  if [ -n "$PT_COMPOSE" ]; then
    PT_MODE="docker"
  elif [ -n "$PT_ROOT" ]; then
    PT_MODE="native"
  elif [ -d /var/www/peertube/peertube-latest ]; then
    PT_ROOT=/var/www/peertube/peertube-latest
    PT_MODE="native"
  else
    die "PeerTube not detected; pass --peertube-root, --peertube-compose-dir or --skip-plugin"
  fi
fi

make_token() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -hex 32
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import secrets; print(secrets.token_hex(32))'
  else
    die "openssl or python3 is required to generate a service token"
  fi
}

private_file() {
  local file="$1" text="$2"
  if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY-RUN: write private file $file"
    return 0
  fi
  mkdir -p "$(dirname "$file")" || return 1
  printf '%s\n' "$text" > "$file" || return 1
  chmod 600 "$file" || return 1
}

normalize_public_tree() {
  local dir="$1"
  [ "$DRY_RUN" -eq 1 ] && return 0
  chmod -R u+rwX,go+rX "$dir" || return 1
}

wait_bridge() {
  [ "$DRY_RUN" -eq 1 ] && return 0
  local n=0
  while [ "$n" -lt 30 ]; do
    if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "http://127.0.0.1:$BRIDGE_PORT/healthz" >/dev/null 2>&1; then
      return 0
    fi
    n=$((n + 1))
    sleep 1
  done
  return 1
}

install_bridge_container() {
  need docker
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is required"

  if [ -z "$STATE_DIR" ]; then
    if [ "$(id -u)" -eq 0 ]; then
      STATE_DIR=/var/lib/peertube-clipper
    else
      STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/peertube-clipper"
    fi
  fi

  local stack="$STATE_DIR/stack" envfile="$STATE_DIR/bridge.env"

  if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY-RUN: stage stack in $stack"
  else
    mkdir -p "$stack/services" || die "Cannot create $stack"
    rm -rf "$stack/services/clip-bridge"
    cp -a "$ROOT/services/clip-bridge" "$stack/services/clip-bridge" || die "Cannot stage Bridge"
    normalize_public_tree "$stack/services/clip-bridge" || die "Cannot normalize Bridge build context permissions"
    cp "$ROOT/compose.yaml" "$stack/compose.yaml" || die "Cannot stage compose file"
  fi

  private_file "$envfile" "PEERTUBE_CLIPPER_SERVICE_TOKEN=$TOKEN
PEERTUBE_CLIPPER_BIND=$BRIDGE_BIND
PEERTUBE_CLIPPER_PORT=$BRIDGE_PORT
OLLAMA_MODEL=$MODEL" || die "Cannot write Bridge environment"

  local dc=(docker compose --project-name peertube-clipper --env-file "$envfile" -f "$stack/compose.yaml")
  run "${dc[@]}" up -d --build clip-bridge || die "Bridge container failed"

  if [ "$WITH_ANALYSIS" -eq 1 ]; then
    run "${dc[@]}" --profile analysis up -d ollama || die "Ollama failed"
    run "${dc[@]}" exec -T ollama ollama pull "$MODEL" || die "Model pull failed"
  fi

  wait_bridge || die "Bridge health check failed"
}

install_bridge_native() {
  [ "$(id -u)" -eq 0 ] || die "Native mode requires root"
  need python3
  need systemctl

  local user=peertube-clipper app=/opt/peertube-clipper data=/var/lib/peertube-clipper cfg=/etc/peertube-clipper
  local unit=/etc/systemd/system/peertube-clipper-bridge.service

  id "$user" >/dev/null 2>&1 || run useradd --system --home "$data" --shell /usr/sbin/nologin "$user" || die "Cannot create service user"
  run mkdir -p "$app" "$data" "$cfg" || die "Cannot create service directories"
  run chown "$user:$user" "$data" || die "Cannot set data ownership"

  if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY-RUN: stage Bridge in $app/bridge"
  else
    rm -rf "$app/bridge"
    cp -a "$ROOT/services/clip-bridge" "$app/bridge" || die "Cannot stage Bridge"
    normalize_public_tree "$app/bridge" || die "Cannot normalize Bridge source permissions"
  fi

  run python3 -m venv "$app/venv" || die "Cannot create Python venv"
  run "$app/venv/bin/pip" install --disable-pip-version-check --no-cache-dir "$app/bridge" || die "Cannot install Bridge"
  private_file "$cfg/bridge.env" "PEERTUBE_CLIPPER_SERVICE_TOKEN=$TOKEN
PEERTUBE_CLIPPER_DATABASE=$data/peertube-clipper.sqlite3" || die "Cannot write Bridge config"

  if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY-RUN: write $unit"
  else
    cat > "$unit" <<UNIT
[Unit]
Description=PeerTube Clipper Bridge
After=network-online.target
Wants=network-online.target

[Service]
User=$user
Group=$user
EnvironmentFile=$cfg/bridge.env
ExecStart=$app/venv/bin/uvicorn clip_bridge.main:app --host $BRIDGE_BIND --port $BRIDGE_PORT
WorkingDirectory=$data
Restart=on-failure
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$data

[Install]
WantedBy=multi-user.target
UNIT
    chmod 644 "$unit"
  fi

  run systemctl daemon-reload || die "systemd reload failed"
  run systemctl enable --now peertube-clipper-bridge.service || die "Bridge service failed"
  [ "$WITH_ANALYSIS" -eq 0 ] || warn "Native mode does not install Ollama; configure the analyzer separately"
  wait_bridge || die "Bridge health check failed"
}

prepare_bridge() {
  if [ "$MODE" = external ]; then
    [ -n "$BRIDGE_URL" ] || die "External mode requires --bridge-url"
    if [ -n "$TOKEN_FILE" ]; then
      [ -r "$TOKEN_FILE" ] || die "Cannot read token file"
      TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
    else
      TOKEN="${PEERTUBE_CLIPPER_SERVICE_TOKEN:-}"
    fi
    [ -n "$TOKEN" ] || die "External mode requires --bridge-token-file or PEERTUBE_CLIPPER_SERVICE_TOKEN"
    return 0
  fi

  TOKEN="$(make_token)"
  [ -n "$TOKEN" ] || die "Token generation failed"

  if [ "$PT_MODE" = docker ] && [ -z "$BRIDGE_URL" ]; then
    die "Dockerized PeerTube requires explicit --bridge-url reachable from its container"
  fi

  case "$MODE" in
    container) install_bridge_container ;;
    native) install_bridge_native ;;
  esac

  [ -n "$BRIDGE_URL" ] || BRIDGE_URL="http://127.0.0.1:$BRIDGE_PORT"
}

find_native_base() {
  local r b
  r="$(readlink -f "$PT_ROOT" 2>/dev/null || printf '%s' "$PT_ROOT")"
  for b in "$(dirname "$r")" "$(dirname "$(dirname "$r")")" "$(dirname "$(dirname "$(dirname "$r")")")"; do
    if [ -d "$b/storage" ] || [ -d "$b/config" ]; then
      printf '%s' "$b"
      return 0
    fi
  done
  dirname "$PT_ROOT"
}

write_native_plugin_config() {
  local file="$PT_PLUGIN_DATA/bridge.json"
  case "$BRIDGE_URL$TOKEN" in *$'\n'*|*$'\r'*|*'"'*|*'\\'*) die "Bridge URL/token contains unsupported characters" ;; esac
  if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY-RUN: write private plugin config $file"
    return 0
  fi
  mkdir -p "$PT_PLUGIN_DATA" || die "Cannot create plugin data directory"
  printf '{"bridgeUrl":"%s","bridgeToken":"%s"}\n' "$BRIDGE_URL" "$TOKEN" > "$file" || die "Cannot write plugin config"
  chmod 600 "$file" || die "Cannot protect plugin config"
  chown -R "$PT_USER:$PT_USER" "$PT_PLUGIN_DATA" || die "Cannot set plugin data ownership"
}

install_plugin_native() {
  [ -d "$PT_ROOT" ] && [ -f "$PT_ROOT/package.json" ] || die "Invalid PeerTube root: $PT_ROOT"

  local base stage_parent stage
  base="$(find_native_base)"
  [ -n "$PT_CONFIG" ] || PT_CONFIG="$base/config"
  [ -d "$PT_CONFIG" ] || die "Pass --peertube-config-dir"
  [ -n "$PT_STORAGE" ] || PT_STORAGE="$base/storage"
  [ -d "$PT_STORAGE" ] || die "Pass --peertube-storage-dir"
  [ -n "$PT_USER" ] || PT_USER="$(stat -c '%U' "$PT_ROOT" 2>/dev/null || printf peertube)"

  stage_parent="$(mktemp -d /tmp/peertube-clipper-stage.XXXXXX)" || die "Cannot create plugin staging parent"
  stage="$stage_parent/$PLUGIN_NAME"

  if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY-RUN: stage plugin at $stage"
  else
    mkdir -p "$stage" || die "Cannot create plugin staging directory"
    cp -a "$PLUGIN/." "$stage/" || die "Cannot stage plugin"
    [ "$(basename "$stage")" = "$PLUGIN_NAME" ] || die "Invalid plugin staging basename"
    normalize_public_tree "$stage" || die "Cannot normalize plugin staging permissions"
    chmod 755 "$stage_parent" "$stage" || die "Cannot make plugin staging traversable"
  fi

  if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY-RUN: install plugin as $PT_USER from $stage"
  else
    ( cd "$PT_ROOT" && runuser -u "$PT_USER" -- env NODE_CONFIG_DIR="$PT_CONFIG" NODE_ENV=production npm run plugin:install -- --plugin-path "$stage" ) || {
      rm -rf "$stage_parent" 2>/dev/null || true
      die "PeerTube plugin installation failed"
    }
  fi

  rm -rf "$stage_parent" 2>/dev/null || true
  [ -n "$PT_PLUGIN_DATA" ] || PT_PLUGIN_DATA="$PT_STORAGE/plugins/data/$PLUGIN_NAME"
  write_native_plugin_config

  if [ "$NO_RESTART" -eq 0 ]; then
    local unit="" u
    for u in peertube.service peertube; do
      if systemctl list-unit-files "$u" --no-legend 2>/dev/null | grep -q .; then unit="$u"; break; fi
    done
    [ -z "$unit" ] && warn "PeerTube service not detected; restart it manually" || run systemctl restart "$unit" || die "PeerTube restart failed"
  fi
}

install_plugin_docker() {
  need docker
  [ -n "$PT_COMPOSE" ] && [ -d "$PT_COMPOSE" ] || die "Docker mode requires --peertube-compose-dir"

  local cid stage="/tmp/$PLUGIN_NAME"
  cid="$(cd "$PT_COMPOSE" && docker compose ps -q "$PT_SERVICE" 2>/dev/null)"
  [ -n "$cid" ] || die "PeerTube container not found"

  if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY-RUN: copy and install plugin in container at $stage"
  else
    docker exec -u 0 "$cid" rm -rf "$stage" >/dev/null 2>&1 || true
    docker exec -u 0 "$cid" mkdir -p "$stage" || die "Cannot create plugin staging directory"
    docker cp "$PLUGIN/." "$cid:$stage" || die "Cannot copy plugin"
    docker exec -u 0 "$cid" chmod -R a+rX "$stage" || die "Cannot normalize plugin permissions"
    docker exec -u peertube -w "$PT_CONTAINER_ROOT" "$cid" npm run plugin:install -- --plugin-path "$stage" || die "Plugin install failed"
    docker exec -u 0 "$cid" rm -rf "$stage" >/dev/null 2>&1 || true
  fi

  [ -n "$PT_PLUGIN_DATA" ] || PT_PLUGIN_DATA="/data/plugins/data/$PLUGIN_NAME"
  case "$BRIDGE_URL$TOKEN" in *$'\n'*|*$'\r'*|*'"'*|*'\\'*) die "Bridge URL/token contains unsupported characters" ;; esac

  if [ "$DRY_RUN" -eq 1 ]; then
    say "DRY-RUN: write private plugin config in container"
  else
    printf '{"bridgeUrl":"%s","bridgeToken":"%s"}\n' "$BRIDGE_URL" "$TOKEN" | docker exec -i -u peertube "$cid" sh -c "umask 077; mkdir -p '$PT_PLUGIN_DATA'; cat > '$PT_PLUGIN_DATA/bridge.json'; chmod 600 '$PT_PLUGIN_DATA/bridge.json'" || die "Cannot configure plugin"
  fi

  if [ "$NO_RESTART" -eq 0 ]; then
    ( cd "$PT_COMPOSE" && run docker compose restart "$PT_SERVICE" ) || die "PeerTube restart failed"
  fi
}

prepare_bridge
case "$BRIDGE_URL" in http://*|https://*) ;; *) die "Bridge URL must start with http:// or https://" ;; esac

if [ "$SKIP_PLUGIN" -eq 0 ]; then
  case "$PT_MODE" in
    native) install_plugin_native ;;
    docker) install_plugin_docker ;;
    skip) ;;
    *) die "Unexpected PeerTube mode" ;;
  esac
fi

say "Installation complete"
say "Companion mode: $MODE"
say "PeerTube mode: $PT_MODE"
say "Bridge URL: $BRIDGE_URL"
say "Service credential was not printed"
exit 0
