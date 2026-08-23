#!/usr/bin/env bash

# Destructive-to-test-state, self-cleaning E2E validation for PeerTube Clipper.
# It creates short-lived OAuth sessions for existing test actors, seeds a
# temporary Bridge workflow, validates shared review/authorization semantics,
# then revokes every temporary session and deletes the workflow.
# No password, OAuth token or Bridge credential is printed.

umask 077

PEERTUBE_URL=""
PEERTUBE_STORAGE=""
BRIDGE_URL="http://127.0.0.1:18100"
BRIDGE_ENV="/var/lib/peertube-clipper/bridge.env"
DB_NAME=""
VIDEO_UUID=""
OWNER_USER=""
EDITOR_USER=""
UNRELATED_USER=""
REPORT=""

OWNER_TOKEN=""
EDITOR_TOKEN=""
UNRELATED_TOKEN=""
BRIDGE_TOKEN=""
WORKFLOW_CREATED=0
CLEANUP_OK=1
LAST_CANDIDATE=""

say() {
  printf '%s\n' "$*"
  if [ -n "$REPORT" ]; then printf '%s\n' "$*" >> "$REPORT"; fi
}

die() {
  say "E2E_RESULT=FAIL"
  say "ERROR=$*"
  exit 1
}

usage() {
  cat <<'USAGE'
Usage: ./scripts/validate-review-e2e.sh [options]

Required:
  --peertube-url URL
  --peertube-storage PATH
  --video-uuid UUID
  --owner USERNAME
  --editor USERNAME
  --unrelated USERNAME

Optional:
  --bridge-url URL          default: http://127.0.0.1:18100
  --bridge-env PATH         default: /var/lib/peertube-clipper/bridge.env
  --database NAME           auto-detected when possible
  --report PATH

This script intentionally writes temporary test state and temporary OAuth
sessions, but cleans both before exit. It does not modify the PeerTube video,
caption, channel, collaborator relation, password or existing sessions.
USAGE
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --peertube-url) PEERTUBE_URL="$2"; shift 2 ;;
    --peertube-storage) PEERTUBE_STORAGE="$2"; shift 2 ;;
    --bridge-url) BRIDGE_URL="$2"; shift 2 ;;
    --bridge-env) BRIDGE_ENV="$2"; shift 2 ;;
    --database) DB_NAME="$2"; shift 2 ;;
    --video-uuid) VIDEO_UUID="$2"; shift 2 ;;
    --owner) OWNER_USER="$2"; shift 2 ;;
    --editor) EDITOR_USER="$2"; shift 2 ;;
    --unrelated) UNRELATED_USER="$2"; shift 2 ;;
    --report) REPORT="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'ERROR: unknown option: %s\n' "$1" >&2; exit 1 ;;
  esac
done

[ -n "$PEERTUBE_URL" ] || die "missing_peertube_url"
[ -n "$PEERTUBE_STORAGE" ] || die "missing_peertube_storage"
[ -n "$VIDEO_UUID" ] || die "missing_video_uuid"
[ -n "$OWNER_USER" ] || die "missing_owner"
[ -n "$EDITOR_USER" ] || die "missing_editor"
[ -n "$UNRELATED_USER" ] || die "missing_unrelated"

for command in curl node python3 openssl psql; do
  command -v "$command" >/dev/null 2>&1 || die "missing_command_$command"
done

if [ -n "$REPORT" ]; then
  mkdir -p "$(dirname "$REPORT")" 2>/dev/null || die "report_directory_failed"
  : > "$REPORT" || die "report_create_failed"
  chmod 600 "$REPORT" 2>/dev/null || true
fi

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

json_field() {
  local field="$1"
  python3 -c 'import json,sys; d=json.load(sys.stdin); v=d; [v:=v[p] for p in sys.argv[1].split(".")]; print(v)' "$field"
}

http_json() {
  local method="$1" url="$2" token="$3" body="${4:-}"
  local response_file code
  response_file="$(mktemp /tmp/peertube-clipper-http.XXXXXX)" || return 1
  if [ -n "$body" ]; then
    code="$(curl -sS --max-time 10 -o "$response_file" -w '%{http_code}' -X "$method" -H "Authorization: Bearer $token" -H 'Content-Type: application/json' --data "$body" "$url" 2>/dev/null || true)"
  else
    code="$(curl -sS --max-time 10 -o "$response_file" -w '%{http_code}' -X "$method" -H "Authorization: Bearer $token" "$url" 2>/dev/null || true)"
  fi
  printf '%s\t%s\n' "$code" "$response_file"
}

bridge_json() {
  local method="$1" route="$2" body="${3:-}"
  local response_file code
  response_file="$(mktemp /tmp/peertube-clipper-bridge.XXXXXX)" || return 1
  if [ -n "$body" ]; then
    code="$(curl -sS --max-time 10 -o "$response_file" -w '%{http_code}' -X "$method" -H "X-Peertube-Clipper-Token: $BRIDGE_TOKEN" -H 'Content-Type: application/json' --data "$body" "${BRIDGE_URL%/}$route" 2>/dev/null || true)"
  else
    code="$(curl -sS --max-time 10 -o "$response_file" -w '%{http_code}' -X "$method" -H "X-Peertube-Clipper-Token: $BRIDGE_TOKEN" "${BRIDGE_URL%/}$route" 2>/dev/null || true)"
  fi
  printf '%s\t%s\n' "$code" "$response_file"
}

revoke_token() {
  local token="$1" label="$2" code
  [ -n "$token" ] || return 0
  code="$(curl -sS --max-time 10 -o /dev/null -w '%{http_code}' -X POST -H "Authorization: Bearer $token" "${PEERTUBE_URL%/}/api/v1/users/revoke-token" 2>/dev/null || true)"
  if [ "$code" = "200" ]; then
    say "${label}_temporary_session_revoked=PASS"
    return 0
  fi
  say "${label}_temporary_session_revoked=FAIL"
  CLEANUP_OK=0
  return 1
}

cleanup() {
  revoke_token "$OWNER_TOKEN" owner >/dev/null 2>&1 || true
  revoke_token "$EDITOR_TOKEN" editor >/dev/null 2>&1 || true
  revoke_token "$UNRELATED_TOKEN" unrelated >/dev/null 2>&1 || true

  if [ "$WORKFLOW_CREATED" -eq 1 ] && [ -n "$BRIDGE_TOKEN" ]; then
    local result code file
    result="$(bridge_json DELETE "/v1/videos/$VIDEO_UUID")"
    code="${result%%$'\t'*}"
    file="${result#*$'\t'}"
    rm -f "$file" 2>/dev/null || true
    if [ "$code" != "200" ] && [ "$code" != "404" ]; then CLEANUP_OK=0; fi
  fi
}
trap cleanup EXIT HUP INT TERM

say "PEERTUBE CLIPPER SHARED REVIEW E2E"
say "generated_utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
say "source_video_uuid=$VIDEO_UUID"
say "owner_username=$OWNER_USER"
say "editor_username=$EDITOR_USER"
say "unrelated_username=$UNRELATED_USER"
say "existing_sessions_used=no"
say "passwords_changed=no"
say "tokens_output=no"
say "video_metadata_modified=no"
say "captions_modified=no"
say "transcodes_modified=no"

[ -r "$BRIDGE_ENV" ] || die "bridge_env_unreadable"
BRIDGE_TOKEN="$(sed -n 's/^PEERTUBE_CLIPPER_SERVICE_TOKEN=//p' "$BRIDGE_ENV" | head -n 1)"
[ -n "$BRIDGE_TOKEN" ] || die "bridge_token_unavailable"

PLUGIN_PACKAGE="$PEERTUBE_STORAGE/plugins/node_modules/peertube-plugin-clipper/package.json"
[ -f "$PLUGIN_PACKAGE" ] || die "plugin_package_missing"
PLUGIN_VERSION="$(node -e 'console.log(require(process.argv[1]).version)' "$PLUGIN_PACKAGE" 2>/dev/null || true)"
[ -n "$PLUGIN_VERSION" ] || die "plugin_version_unavailable"
PLUGIN_BASE="${PEERTUBE_URL%/}/plugins/clipper/${PLUGIN_VERSION}/router"

preflight="$(bridge_json GET "/v1/videos/$VIDEO_UUID")"
pre_code="${preflight%%$'\t'*}"
pre_file="${preflight#*$'\t'}"
rm -f "$pre_file" 2>/dev/null || true
[ "$pre_code" = "404" ] || die "source_already_has_clipper_workflow"

if [ -z "$DB_NAME" ]; then
  DBS="$(psql_postgres -Atqc 'SELECT datname FROM pg_database WHERE datallowconn AND NOT datistemplate ORDER BY datname' 2>/dev/null || true)"
  while IFS= read -r candidate; do
    [ -n "$candidate" ] || continue
    match="$(psql_postgres -d "$candidate" -Atqc "SELECT CASE WHEN to_regclass('\"oAuthToken\"') IS NOT NULL AND to_regclass('\"videoChannelCollaborator\"') IS NOT NULL THEN 1 ELSE 0 END" 2>/dev/null || true)"
    if [ "$match" = "1" ]; then DB_NAME="$candidate"; break; fi
  done <<< "$DBS"
fi
[ -n "$DB_NAME" ] || die "peertube_database_not_detected"

OWNER_ID="$(psql_postgres -d "$DB_NAME" -Atq -v username="$OWNER_USER" -c "SELECT id FROM \"user\" WHERE username = :'username' LIMIT 1" 2>/dev/null || true)"
EDITOR_ID="$(psql_postgres -d "$DB_NAME" -Atq -v username="$EDITOR_USER" -c "SELECT id FROM \"user\" WHERE username = :'username' LIMIT 1" 2>/dev/null || true)"
UNRELATED_ID="$(psql_postgres -d "$DB_NAME" -Atq -v username="$UNRELATED_USER" -c "SELECT id FROM \"user\" WHERE username = :'username' LIMIT 1" 2>/dev/null || true)"
[ -n "$OWNER_ID" ] && [ -n "$EDITOR_ID" ] && [ -n "$UNRELATED_ID" ] || die "test_actor_lookup_failed"

create_session() {
  local username="$1" access refresh inserted
  access="$(openssl rand -hex 32)" || return 1
  refresh="$(openssl rand -hex 32)" || return 1
  inserted="$(psql_postgres -d "$DB_NAME" -Atq -v username="$username" -v access="$access" -v refresh="$refresh" <<'SQL'
WITH selected_user AS (
  SELECT id FROM "user" WHERE username = :'username' LIMIT 1
), selected_client AS (
  SELECT id FROM "oAuthClient" ORDER BY id LIMIT 1
)
INSERT INTO "oAuthToken"(
  "accessToken", "accessTokenExpiresAt", "refreshToken", "refreshTokenExpiresAt",
  "loginDevice", "loginIP", "loginDate",
  "lastActivityDevice", "lastActivityIP", "lastActivityDate",
  "createdAt", "updatedAt", "userId", "oAuthClientId"
)
SELECT
  :'access', now() + interval '3 minutes',
  :'refresh', now() + interval '5 minutes',
  'PeerTube Clipper E2E', '127.0.0.1', now(),
  'PeerTube Clipper E2E', '127.0.0.1', now(),
  now(), now(), selected_user.id, selected_client.id
FROM selected_user CROSS JOIN selected_client
RETURNING id;
SQL
)"
  [ -n "$inserted" ] || return 1
  printf '%s' "$access"
}

OWNER_TOKEN="$(create_session "$OWNER_USER")" || die "owner_test_session_failed"
EDITOR_TOKEN="$(create_session "$EDITOR_USER")" || die "editor_test_session_failed"
UNRELATED_TOKEN="$(create_session "$UNRELATED_USER")" || die "unrelated_test_session_failed"
say "temporary_sessions_created=PASS"

seed_candidate() {
  local body="$1" result code file
  result="$(bridge_json POST "/v1/videos/$VIDEO_UUID/candidates" "$body")"
  code="${result%%$'\t'*}"
  file="${result#*$'\t'}"
  if [ "$code" != "200" ]; then rm -f "$file"; return 1; fi
  LAST_CANDIDATE="$(cat "$file" | json_field candidate_id 2>/dev/null || true)"
  rm -f "$file"
  [ -n "$LAST_CANDIDATE" ] || return 1
  WORKFLOW_CREATED=1
  return 0
}

seed_candidate '{"anchor_start":60,"anchor_end":65,"suggested_start":55,"suggested_end":80,"canonical_transcript":"PeerTube Clipper temporary E2E candidate one."}' || die "seed_candidate_1_failed"
C1="$LAST_CANDIDATE"
seed_candidate '{"anchor_start":95,"anchor_end":100,"suggested_start":90,"suggested_end":120,"canonical_transcript":"PeerTube Clipper temporary E2E candidate two."}' || die "seed_candidate_2_failed"
C2="$LAST_CANDIDATE"
seed_candidate '{"anchor_start":155,"anchor_end":160,"suggested_start":150,"suggested_end":180,"canonical_transcript":"PeerTube Clipper temporary E2E candidate three."}' || die "seed_candidate_3_failed"
C3="$LAST_CANDIDATE"
say "temporary_candidates_seeded=3"

owner_get="$(http_json GET "$PLUGIN_BASE/videos/$VIDEO_UUID/state" "$OWNER_TOKEN")"
owner_code="${owner_get%%$'\t'*}"; owner_file="${owner_get#*$'\t'}"
[ "$owner_code" = "200" ] || { rm -f "$owner_file"; die "owner_get_expected_200_got_$owner_code"; }
OWNER_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["workflow"]["candidates"]))' "$owner_file" 2>/dev/null || true)"
rm -f "$owner_file"
[ "$OWNER_COUNT" = "3" ] || die "owner_candidate_count_mismatch"
say "owner_access=PASS"

editor_get="$(http_json GET "$PLUGIN_BASE/videos/$VIDEO_UUID/state" "$EDITOR_TOKEN")"
editor_code="${editor_get%%$'\t'*}"; editor_file="${editor_get#*$'\t'}"
[ "$editor_code" = "200" ] || { rm -f "$editor_file"; die "editor_get_expected_200_got_$editor_code"; }
EDITOR_COUNT="$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))["workflow"]["candidates"]))' "$editor_file" 2>/dev/null || true)"
rm -f "$editor_file"
[ "$EDITOR_COUNT" = "3" ] || die "editor_candidate_count_mismatch"
say "editor_shared_state_access=PASS"

unrelated_get="$(http_json GET "$PLUGIN_BASE/videos/$VIDEO_UUID/state" "$UNRELATED_TOKEN")"
unrelated_code="${unrelated_get%%$'\t'*}"; unrelated_file="${unrelated_get#*$'\t'}"
rm -f "$unrelated_file"
[ "$unrelated_code" = "403" ] || die "unrelated_expected_403_got_$unrelated_code"
say "unrelated_access_denied=PASS"

owner_edit="$(http_json PATCH "$PLUGIN_BASE/videos/$VIDEO_UUID/candidates/$C1" "$OWNER_TOKEN" '{"status":"edited","editorStart":56,"editorEnd":79}')"
owner_edit_code="${owner_edit%%$'\t'*}"; owner_edit_file="${owner_edit#*$'\t'}"
[ "$owner_edit_code" = "200" ] || { rm -f "$owner_edit_file"; die "owner_edit_failed_$owner_edit_code"; }
OWNER_ACTOR="$(cat "$owner_edit_file" | json_field acted_by_user_id 2>/dev/null || true)"
rm -f "$owner_edit_file"
[ "$OWNER_ACTOR" = "$OWNER_ID" ] || die "owner_audit_actor_mismatch"
say "owner_edit_and_audit=PASS"

editor_approve="$(http_json PATCH "$PLUGIN_BASE/videos/$VIDEO_UUID/candidates/$C2" "$EDITOR_TOKEN" '{"status":"approved","editorStart":92,"editorEnd":118}')"
editor_approve_code="${editor_approve%%$'\t'*}"; editor_approve_file="${editor_approve#*$'\t'}"
[ "$editor_approve_code" = "200" ] || { rm -f "$editor_approve_file"; die "editor_approve_failed_$editor_approve_code"; }
EDITOR_ACTOR="$(cat "$editor_approve_file" | json_field acted_by_user_id 2>/dev/null || true)"
rm -f "$editor_approve_file"
[ "$EDITOR_ACTOR" = "$EDITOR_ID" ] || die "editor_audit_actor_mismatch"
say "editor_approve_and_audit=PASS"

editor_reject="$(http_json PATCH "$PLUGIN_BASE/videos/$VIDEO_UUID/candidates/$C3" "$EDITOR_TOKEN" '{"status":"rejected","editorStart":150,"editorEnd":180}')"
editor_reject_code="${editor_reject%%$'\t'*}"; editor_reject_file="${editor_reject#*$'\t'}"
[ "$editor_reject_code" = "200" ] || { rm -f "$editor_reject_file"; die "editor_reject_failed_$editor_reject_code"; }
rm -f "$editor_reject_file"
say "editor_reject=PASS"

editor_seen="$(http_json GET "$PLUGIN_BASE/videos/$VIDEO_UUID/state" "$EDITOR_TOKEN")"
editor_seen_code="${editor_seen%%$'\t'*}"; editor_seen_file="${editor_seen#*$'\t'}"
[ "$editor_seen_code" = "200" ] || { rm -f "$editor_seen_file"; die "editor_shared_refresh_failed"; }
C1_STATUS="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); cid=sys.argv[2]; print(next(c["status"] for c in d["workflow"]["candidates"] if c["candidate_id"] == cid))' "$editor_seen_file" "$C1" 2>/dev/null || true)"
rm -f "$editor_seen_file"
[ "$C1_STATUS" = "edited" ] || die "shared_edit_not_visible"
say "cross_user_shared_state=PASS"

owner_final="$(http_json PATCH "$PLUGIN_BASE/videos/$VIDEO_UUID/candidates/$C1" "$OWNER_TOKEN" '{"status":"approved","editorStart":56,"editorEnd":79}')"
owner_final_code="${owner_final%%$'\t'*}"; owner_final_file="${owner_final#*$'\t'}"
[ "$owner_final_code" = "200" ] || { rm -f "$owner_final_file"; die "owner_final_approve_failed_$owner_final_code"; }
rm -f "$owner_final_file"

final_get="$(http_json GET "$PLUGIN_BASE/videos/$VIDEO_UUID/state" "$EDITOR_TOKEN")"
final_code="${final_get%%$'\t'*}"; final_file="${final_get#*$'\t'}"
[ "$final_code" = "200" ] || { rm -f "$final_file"; die "final_state_read_failed"; }
FINAL_WORKFLOW="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["workflow"]["video"]["status"])' "$final_file" 2>/dev/null || true)"
rm -f "$final_file"
[ "$FINAL_WORKFLOW" = "reviewed" ] || die "final_workflow_not_reviewed"
say "review_lifecycle=PASS"

if revoke_token "$OWNER_TOKEN" owner; then OWNER_TOKEN=""; fi
if revoke_token "$EDITOR_TOKEN" editor; then EDITOR_TOKEN=""; fi
if revoke_token "$UNRELATED_TOKEN" unrelated; then UNRELATED_TOKEN=""; fi

cleanup_result="$(bridge_json DELETE "/v1/videos/$VIDEO_UUID")"
cleanup_code="${cleanup_result%%$'\t'*}"; cleanup_file="${cleanup_result#*$'\t'}"
rm -f "$cleanup_file" 2>/dev/null || true
[ "$cleanup_code" = "200" ] || die "workflow_cleanup_failed_$cleanup_code"
WORKFLOW_CREATED=0
say "workflow_cleanup=PASS"

verify_cleanup="$(bridge_json GET "/v1/videos/$VIDEO_UUID")"
verify_code="${verify_cleanup%%$'\t'*}"; verify_file="${verify_cleanup#*$'\t'}"
rm -f "$verify_file" 2>/dev/null || true
[ "$verify_code" = "404" ] || die "workflow_cleanup_verification_failed"
say "workflow_cleanup_verified=PASS"

trap - EXIT HUP INT TERM

if [ "$CLEANUP_OK" -eq 1 ] && [ -z "$OWNER_TOKEN$EDITOR_TOKEN$UNRELATED_TOKEN" ]; then
  say "temporary_sessions_cleanup=PASS"
  say "E2E_RESULT=PASS"
  exit 0
fi

say "temporary_sessions_cleanup=FAIL"
say "E2E_RESULT=FAIL"
exit 1
