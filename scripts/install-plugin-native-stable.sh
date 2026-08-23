#!/usr/bin/env bash

# Stable native PeerTube plugin installer.
# Keeps the local file: dependency source at a persistent path so pnpm can
# resolve it on future upgrades. Also repairs legacy ephemeral /tmp staging
# references created by older PeerTube Clipper installer versions, including
# references that survive only in pnpm-lock.yaml.
#
# No persistent strict-mode shell options are enabled.

umask 077

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGIN_SOURCE="$ROOT/packages/peertube-plugin-clipper"
PLUGIN_NAME="peertube-plugin-clipper"

PT_ROOT=""
PT_USER=""
PT_CONFIG=""
PT_STORAGE=""
NO_RESTART=0
DRY_RUN=0

say()  { printf '[peertube-clipper] %s\n' "$*"; }
warn() { printf '[peertube-clipper] WARNING: %s\n' "$*" >&2; }
die()  { printf '[peertube-clipper] ERROR: %s\n' "$*" >&2; exit 1; }

usage() {
  cat <<'USAGE'
Usage: bash ./scripts/install-plugin-native-stable.sh [options]

Required:
  --peertube-root PATH
  --peertube-user USER
  --peertube-config-dir PATH
  --peertube-storage-dir PATH

Optional:
  --no-restart
  --dry-run
  -h, --help
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --peertube-root) PT_ROOT="$2"; shift 2 ;;
    --peertube-user) PT_USER="$2"; shift 2 ;;
    --peertube-config-dir) PT_CONFIG="$2"; shift 2 ;;
    --peertube-storage-dir) PT_STORAGE="$2"; shift 2 ;;
    --no-restart) NO_RESTART=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown option: $1" ;;
  esac
done

[ -d "$PLUGIN_SOURCE" ] || die "Plugin source is missing: $PLUGIN_SOURCE"
[ -n "$PT_ROOT" ] && [ -f "$PT_ROOT/package.json" ] || die "Invalid --peertube-root"
[ -n "$PT_USER" ] || die "Missing --peertube-user"
id "$PT_USER" >/dev/null 2>&1 || die "PeerTube user does not exist: $PT_USER"
[ -n "$PT_CONFIG" ] && [ -d "$PT_CONFIG" ] || die "Invalid --peertube-config-dir"
[ -n "$PT_STORAGE" ] && [ -d "$PT_STORAGE" ] || die "Invalid --peertube-storage-dir"
command -v node >/dev/null 2>&1 || die "node is required"
command -v runuser >/dev/null 2>&1 || die "runuser is required"

PLUGINS_DIR="$PT_STORAGE/plugins"
PACKAGE_JSON="$PLUGINS_DIR/package.json"
PNPM_LOCK="$PLUGINS_DIR/pnpm-lock.yaml"
STABLE_PARENT="$PLUGINS_DIR/.peertube-clipper-source"
STABLE_STAGE="$STABLE_PARENT/$PLUGIN_NAME"
LEGACY_LIST=""

stage_tree() {
  local source="$1" destination="$2"

  rm -rf "$destination" || return 1
  mkdir -p "$destination" || return 1
  cp -a "$source/." "$destination/" || return 1
  chmod -R u+rwX,go+rX "$destination" || return 1
  chown -R "$PT_USER:$PT_USER" "$destination" || return 1
}

find_legacy_stages() {
  python3 - "$PACKAGE_JSON" "$PNPM_LOCK" <<'PY'
import pathlib
import re
import sys

pattern = re.compile(r"/tmp/peertube-clipper-stage\.[A-Za-z0-9_-]+/peertube-plugin-clipper")
seen = set()

for name in sys.argv[1:]:
    path = pathlib.Path(name)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        continue

    for match in pattern.findall(text):
        if match not in seen:
            seen.add(match)
            print(match)
PY
}

verify_persistent_dependency() {
  [ -f "$PACKAGE_JSON" ] || return 1

  node - "$PACKAGE_JSON" "$PLUGIN_NAME" "$STABLE_STAGE" <<'NODE'
const fs = require('fs')
const path = require('path')
const [file, name, stable] = process.argv.slice(2)
let pkg
try {
  pkg = JSON.parse(fs.readFileSync(file, 'utf8'))
} catch (_) {
  process.exit(1)
}
let value = null
for (const key of ['dependencies', 'devDependencies', 'optionalDependencies']) {
  if (typeof pkg?.[key]?.[name] === 'string') {
    value = pkg[key][name]
    break
  }
}
if (!value || !value.startsWith('file:')) process.exit(1)
const target = value.slice(5)
const resolved = path.resolve(path.dirname(file), target)
process.exit(resolved === path.resolve(stable) ? 0 : 1)
NODE
}

verify_no_legacy_reference() {
  local found
  found="$(find_legacy_stages 2>/dev/null || true)"
  [ -z "$found" ]
}

cleanup_legacy_stages() {
  local legacy parent
  [ -n "$LEGACY_LIST" ] || return 0

  while IFS= read -r legacy; do
    [ -n "$legacy" ] || continue
    parent="$(dirname "$legacy")"
    case "$parent" in
      /tmp/peertube-clipper-stage.*)
        rm -rf "$parent" 2>/dev/null || true
        ;;
    esac
  done <<< "$LEGACY_LIST"
}

if [ "$DRY_RUN" -eq 1 ]; then
  say "DRY-RUN: persist plugin source at $STABLE_STAGE"
  say "DRY-RUN: inspect package.json and pnpm-lock.yaml for legacy ephemeral dependencies"
  say "DRY-RUN: recreate only referenced legacy staging paths temporarily"
  say "DRY-RUN: run PeerTube plugin installer as $PT_USER from persistent source"
  say "DRY-RUN: verify package.json migrated to persistent file dependency"
  say "DRY-RUN: verify no legacy ephemeral reference remains"
  [ "$NO_RESTART" -eq 1 ] || say "DRY-RUN: restart PeerTube"
  exit 0
fi

mkdir -p "$PLUGINS_DIR" "$STABLE_PARENT" || die "Cannot create persistent plugin staging path"
chmod 755 "$STABLE_PARENT" || die "Cannot make persistent staging parent traversable"
chown "$PT_USER:$PT_USER" "$STABLE_PARENT" || die "Cannot set persistent staging parent ownership"
stage_tree "$PLUGIN_SOURCE" "$STABLE_STAGE" || die "Cannot stage persistent plugin source"
[ "$(basename "$STABLE_STAGE")" = "$PLUGIN_NAME" ] || die "Invalid persistent plugin staging basename"

LEGACY_LIST="$(find_legacy_stages 2>/dev/null || true)"
if [ -n "$LEGACY_LIST" ]; then
  say "Repairing legacy ephemeral PeerTube plugin dependency metadata for one upgrade"

  while IFS= read -r legacy; do
    [ -n "$legacy" ] || continue
    parent="$(dirname "$legacy")"

    case "$parent" in
      /tmp/peertube-clipper-stage.*) ;;
      *) cleanup_legacy_stages; die "Refusing unexpected legacy plugin dependency path" ;;
    esac

    mkdir -p "$legacy" || { cleanup_legacy_stages; die "Cannot recreate legacy plugin staging path"; }
    stage_tree "$PLUGIN_SOURCE" "$legacy" || { cleanup_legacy_stages; die "Cannot populate legacy plugin staging path"; }
    chmod 755 "$parent" "$legacy" || { cleanup_legacy_stages; die "Cannot make legacy staging path traversable"; }
  done <<< "$LEGACY_LIST"
else
  say "No legacy ephemeral PeerTube plugin dependency metadata detected"
fi

if ! (
  cd "$PT_ROOT" &&
  runuser -u "$PT_USER" -- \
    env NODE_CONFIG_DIR="$PT_CONFIG" NODE_ENV=production \
    npm run plugin:install -- --plugin-path "$STABLE_STAGE"
); then
  cleanup_legacy_stages
  die "PeerTube plugin installation failed"
fi

cleanup_legacy_stages

verify_persistent_dependency || die "PeerTube plugin dependency did not migrate to the persistent staging path"
verify_no_legacy_reference || die "Legacy ephemeral plugin dependency remains after installation"
[ -d "$STABLE_STAGE" ] || die "Persistent plugin source disappeared after installation"

say "PeerTube plugin installed from persistent source: $STABLE_STAGE"

if [ "$NO_RESTART" -eq 0 ]; then
  UNIT=""
  for candidate in peertube.service peertube; do
    if systemctl list-unit-files "$candidate" --no-legend 2>/dev/null | grep -q .; then
      UNIT="$candidate"
      break
    fi
  done

  if [ -z "$UNIT" ]; then
    warn "PeerTube service not detected; restart it manually"
  else
    systemctl restart "$UNIT" || die "PeerTube restart failed"
  fi
fi

say "Stable native plugin installation complete"
