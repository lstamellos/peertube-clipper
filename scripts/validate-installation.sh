#!/usr/bin/env bash

# Read-only installation/permission preflight for PeerTube Clipper.
# It never prints database credentials or Bridge service tokens.

umask 077

PEERTUBE_ROOT=""
PEERTUBE_STORAGE=""
BRIDGE_URL="http://127.0.0.1:18100"
REPORT=""
SHOW_IDENTIFIERS=0
DB_NAME=""

say() {
  printf '%s\n' "$*"
  if [ -n "$REPORT" ]; then printf '%s\n' "$*" >> "$REPORT"; fi
}

die() {
  say "VALIDATION_RESULT=FAIL"
  say "ERROR=$*"
  exit 1
}

usage() {
  cat <<'EOF'
Usage: ./scripts/validate-installation.sh [options]

  --peertube-root PATH       Active PeerTube application tree
  --peertube-storage PATH    PeerTube storage directory (auto-detected when possible)
  --bridge-url URL           Default: http://127.0.0.1:18100
  --database NAME            PeerTube PostgreSQL database (auto-detected when possible)
  --report PATH              Optional private text report
  --show-identifiers         Include selected video UUID/usernames for manual E2E testing
  -h, --help

The script is read-only. It checks Bridge health, plugin installation/configuration,
and (when local PostgreSQL superuser access is available) locates a local source
video whose channel has an accepted collaborator/editor. No credentials or tokens
are printed.
EOF
}
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --peertube-root) PEERTUBE_ROOT="$2"; shift 2 ;;
    --peertube-storage) PEERTUBE_STORAGE="$2"; shift 2 ;;
    --bridge-url) BRIDGE_URL="$2"; shift 2 ;;
    --database) DB_NAME="$2"; shift 2 ;;
    --report) REPORT="$2"; shift 2 ;;
    --show-identifiers) SHOW_IDENTIFIERS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'ERROR: unknown option: %s\n' "$1" >&2; exit 1 ;;
  esac
done

if [ -n "$REPORT" ]; then
  mkdir -p "$(dirname "$REPORT")" 2>/dev/null || exit 1
  : > "$REPORT" || exit 1
  chmod 600 "$REPORT" 2>/dev/null || true
fi

say "PEERTUBE CLIPPER INSTALLATION VALIDATION"
say "generated_utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
say "changes_performed=no"
say "credentials_output=no"
say "tokens_output=no"

[ -n "$PEERTUBE_ROOT" ] || die "peertube_root_required"
PEERTUBE_ROOT="$(readlink -f "$PEERTUBE_ROOT" 2>/dev/null || printf '%s' "$PEERTUBE_ROOT")"
[ -f "$PEERTUBE_ROOT/package.json" ] || die "invalid_peertube_root"

PT_VERSION="$(node -e 'try { console.log(require(process.argv[1]).version || "unknown") } catch (_) { console.log("unknown") }' "$PEERTUBE_ROOT/package.json" 2>/dev/null)"
say "peertube_version=${PT_VERSION:-unknown}"
say "peertube_root_valid=yes"

if [ -z "$PEERTUBE_STORAGE" ]; then
  for base in \
    "$(dirname "$PEERTUBE_ROOT")" \
    "$(dirname "$(dirname "$PEERTUBE_ROOT")")" \
    "$(dirname "$(dirname "$(dirname "$PEERTUBE_ROOT")")")"
  do
    if [ -d "$base/storage" ]; then
      PEERTUBE_STORAGE="$base/storage"
      break
    fi
  done
fi

if [ -n "$PEERTUBE_STORAGE" ] && [ -d "$PEERTUBE_STORAGE" ]; then
  say "peertube_storage_detected=yes"
else
  say "peertube_storage_detected=no"
fi

if command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 "$BRIDGE_URL/healthz" >/dev/null 2>&1; then
  say "bridge_health=PASS"
else
  say "bridge_health=FAIL"
fi

PLUGIN_DIR=""
if [ -n "$PEERTUBE_STORAGE" ]; then
  for candidate in \
    "$PEERTUBE_STORAGE/plugins/node_modules/peertube-plugin-clipper" \
    "$PEERTUBE_STORAGE/plugins/node_modules/peertube-plugin-clipper/"
  do
    if [ -d "$candidate" ]; then PLUGIN_DIR="$candidate"; break; fi
  done
fi

if [ -n "$PLUGIN_DIR" ]; then
  say "plugin_installed=PASS"
  if [ -f "$PLUGIN_DIR/package.json" ]; then
    PLUGIN_VERSION="$(node -e 'try { console.log(require(process.argv[1]).version || "unknown") } catch (_) { console.log("unknown") }' "$PLUGIN_DIR/package.json" 2>/dev/null)"
    say "plugin_version=${PLUGIN_VERSION:-unknown}"
  fi
else
  say "plugin_installed=FAIL"
fi

CONFIG_FILE=""
if [ -n "$PEERTUBE_STORAGE" ]; then
  CONFIG_FILE="$PEERTUBE_STORAGE/plugins/data/peertube-plugin-clipper/bridge.json"
fi

if [ -n "$CONFIG_FILE" ] && [ -f "$CONFIG_FILE" ]; then
  say "plugin_private_config=PASS"
  MODE="$(stat -c '%a' "$CONFIG_FILE" 2>/dev/null || true)"
  say "plugin_private_config_mode=${MODE:-unknown}"
else
  say "plugin_private_config=FAIL"
fi

SERVICE_STATE="unknown"
for unit in peertube.service peertube; do
  if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q .; then
    SERVICE_STATE="$(systemctl is-active "$unit" 2>/dev/null || true)"
    break
  fi
done
say "peertube_service_state=${SERVICE_STATE:-unknown}"

psql_postgres() {
  if [ "$(id -u)" -eq 0 ] && command -v runuser >/dev/null 2>&1; then
    runuser -u postgres -- psql "$@"
    return $?
  fi

  if command -v sudo >/dev/null 2>&1 && sudo -n -u postgres true >/dev/null 2>&1; then
    sudo -n -u postgres psql "$@"
    return $?
  fi

  return 126
}

if ! command -v psql >/dev/null 2>&1; then
  say "database_permission_probe=SKIP"
  say "database_probe_reason=psql_unavailable"
else
  if [ -z "$DB_NAME" ]; then
    DBS="$(psql_postgres -Atqc 'SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname' 2>/dev/null || true)"
    while IFS= read -r candidate; do
      [ -n "$candidate" ] || continue
      MATCH="$(psql_postgres -d "$candidate" -Atqc 'SELECT CASE WHEN to_regclass('"'"'"videoChannelCollaborator"'"'"') IS NOT NULL AND to_regclass('"'"'video'"'"') IS NOT NULL THEN 1 ELSE 0 END' 2>/dev/null || true)"
      if [ "$MATCH" = "1" ]; then DB_NAME="$candidate"; break; fi
    done <<< "$DBS"
  fi

  if [ -z "$DB_NAME" ]; then
    say "database_permission_probe=SKIP"
    say "database_probe_reason=peertube_database_not_detected"
  else
    say "database_permission_probe=AVAILABLE"

    ROW="$(psql_postgres -d "$DB_NAME" -AtF $'\t' -c '
      SELECT
        video.uuid,
        video."duration",
        owner_user.id,
        owner_user.username,
        editor_user.id,
        editor_user.username,
        channel.id
      FROM video
      INNER JOIN "videoChannel" channel ON channel.id = video."channelId"
      INNER JOIN account owner_account ON owner_account.id = channel."accountId"
      INNER JOIN "user" owner_user ON owner_user.id = owner_account."userId"
      INNER JOIN "videoChannelCollaborator" collaborator
        ON collaborator."channelId" = channel.id
       AND collaborator.state = 2
      INNER JOIN account editor_account ON editor_account.id = collaborator."accountId"
      INNER JOIN "user" editor_user ON editor_user.id = editor_account."userId"
      WHERE video.remote = false
      ORDER BY video."publishedAt" DESC NULLS LAST, video.id DESC
      LIMIT 1
    ' 2>/dev/null || true)"

    if [ -z "$ROW" ]; then
      say "accepted_collaborator_source=NOT_FOUND"
    else
      IFS=$'\t' read -r SOURCE_UUID SOURCE_DURATION OWNER_ID OWNER_USER EDITOR_ID EDITOR_USER CHANNEL_ID <<< "$ROW"
      say "accepted_collaborator_source=FOUND"
      say "source_duration_seconds=${SOURCE_DURATION:-unknown}"

      DENY_ROW="$(psql_postgres -d "$DB_NAME" -AtF $'\t' -c "
        SELECT u.id, u.username
        FROM \"user\" u
        WHERE u.id NOT IN ($OWNER_ID, $EDITOR_ID)
          AND u.role = 2
          AND u.blocked = false
          AND NOT EXISTS (
            SELECT 1
            FROM \"videoChannelCollaborator\" c
            INNER JOIN account a ON a.id = c.\"accountId\"
            WHERE c.\"channelId\" = $CHANNEL_ID
              AND c.state = 2
              AND a.\"userId\" = u.id
          )
        ORDER BY u.id
        LIMIT 1
      " 2>/dev/null || true)"

      if [ -n "$DENY_ROW" ]; then
        IFS=$'\t' read -r DENY_ID DENY_USER <<< "$DENY_ROW"
        say "unrelated_user_candidate=FOUND"
      else
        say "unrelated_user_candidate=NOT_FOUND"
      fi

      if [ "$SHOW_IDENTIFIERS" -eq 1 ]; then
        say "source_video_uuid=$SOURCE_UUID"
        say "owner_username=$OWNER_USER"
        say "editor_username=$EDITOR_USER"
        [ -n "${DENY_USER:-}" ] && say "unrelated_username=$DENY_USER"
      fi
    fi
  fi
fi

if [ -n "$PLUGIN_DIR" ] && command -v curl >/dev/null 2>&1 && curl -fsS --max-time 3 "$BRIDGE_URL/healthz" >/dev/null 2>&1; then
  say "VALIDATION_RESULT=PASS"
else
  say "VALIDATION_RESULT=FAIL"
fi
