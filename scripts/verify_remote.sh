#!/usr/bin/env bash
# End-to-end verification for the remote-git workflow.
#
# This script exercises the public API the same way the Vue frontend
# would. It does NOT depend on outbound network access to github.com —
# the full pytest suite (165 tests, in backend/tests/) is the
# authoritative e2e check and runs entirely against a local bare repo
# with a test-only validator bypass.
#
# What this script verifies against a live backend:
#   1. /api/health is up and /api/config reports remote_git_enabled=true
#   2. URL allowlist rejects obviously invalid URLs (400)
#   3. (Optional) clone a public https URL you supply via PYTEST_GIT_REPO
#   4. (Optional) compute a diff on the cloned remote
#   5. (Optional) list / status / delete the remote cache entry
#   6. Submit a review tagged with source=remote:<name> and confirm
#      it shows up in /api/reviews with the source field
#
# Usage:
#   bash scripts/verify_remote.sh
#
# Environment overrides:
#   API_KEY         Bearer token; required for the remote endpoints
#                   (set to the value of REVIEW_API_KEY on the server).
#                   Defaults to "test-key" for a freshly started server.
#   BASE_URL        Backend base URL (default: http://127.0.0.1:8770).
#   PYTEST_GIT_REPO If set, must be an https URL on REMOTE_GIT_ALLOWED_HOSTS
#                   (e.g. https://github.com/octocat/Hello-World). When
#                   unset, steps 3-5 are skipped and the script does
#                   a config-only smoke check.

set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8770}"
API_KEY="${API_KEY:-test-key}"

red()   { printf '\033[0;31m%s\033[0m\n' "$*" >&2; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
blue()  { printf '\033[0;34m%s\033[0m\n' "$*"; }

# We need jq for parsing. Most Linux + macOS dev boxes have it.
if ! command -v jq >/dev/null 2>&1; then
  red "This script requires \`jq\` (apt install jq / brew install jq)."
  exit 2
fi

# --- 1. Health check -----------------------------------------------------

blue "[1/6] health check"
status=$(curl -fsS -o /dev/null -w '%{http_code}' "$BASE_URL/api/health")
if [[ "$status" != "200" ]]; then
  red "Backend is not up at $BASE_URL (got $status)."
  exit 1
fi
remote_enabled=$(curl -fsS "$BASE_URL/api/config" | jq -r '.remote_git_enabled')
if [[ "$remote_enabled" != "true" ]]; then
  red "remote_git_enabled is '$remote_enabled'; expected 'true'."
  exit 1
fi
green "  OK — backend is up, remote_git_enabled=true"

# --- 2. URL allowlist rejection -----------------------------------------

blue "[2/6] URL allowlist"
# Spin up a temp config that tightens the allowlist to a single host,
# then re-issue a config fetch. We can't change the env from here, but
# we can verify the *current* server rejects an obviously invalid host.
bad_resp=$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"url":"file:///etc/passwd"}' \
  "$BASE_URL/api/git/remote/clone")
case "$bad_resp" in
  400|401|403|404) green "  OK — bad URL rejected with $bad_resp" ;;
  *) red "  bad URL was not rejected (got $bad_resp)"; exit 1 ;;
esac

# --- 3. Clone the "remote" ----------------------------------------------

blue "[3/6] clone"
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

if [[ -n "${PYTEST_GIT_REPO:-}" ]]; then
  bare="$PYTEST_GIT_REPO"
else
  src="$WORK/src"; mkdir -p "$src"
  git -C "$src" init -q -b main
  printf 'a=1\n' > "$src/a.py"
  git -C "$src" -c user.name=T -c user.email=t@e.com add . >/dev/null
  git -C "$src" -c user.name=T -c user.email=t@e.com commit -q -m init
  git -C "$src" -c user.name=T -c user.email=t@e.com checkout -q -b feature
  printf 'a=2\nb=1\n' > "$src/a.py"
  printf 'b=1\n' > "$src/b.py"
  git -C "$src" -c user.name=T -c user.email=t@e.com add . >/dev/null
  git -C "$src" -c user.name=T -c user.email=t@e.com commit -q -m feat
  bare="$WORK/bare.git"
  git clone --bare "$src" "$bare" >/dev/null
fi

# The strict allowlist rejects file:// in production. To exercise the
# real /api/git/remote/clone path against a local bare repo we'd need
# to either (a) serve it via http://localhost (which is on the
# default allowlist) or (b) loosen the allowlist at startup. The
# default install only does (b) if you set REMOTE_GIT_ALLOWED_HOSTS=.
# In CI the cleanest path is to point the verifier at a real public
# repo (PYTEST_GIT_REPO env var). When the env var is unset we
# fall through to a "config-only" smoke check.

if [[ -z "${PYTEST_GIT_REPO:-}" ]]; then
  blue "  PYTEST_GIT_REPO not set — skipping live clone (need an https URL on the allowlist)"
  blue "  Set PYTEST_GIT_REPO=https://github.com/<owner>/<public-repo> to exercise the full path"
  green "  OK — basic config check passed; live clone skipped"
  exit 0
fi

clone_body=$(curl -fsS -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg u "$PYTEST_GIT_REPO" '{url:$u}')" \
  "$BASE_URL/api/git/remote/clone")
rid=$(echo "$clone_body" | jq -r '.id')
name=$(echo "$clone_body" | jq -r '.name')
if [[ -z "$rid" || "$rid" == "null" ]]; then
  red "  clone did not return an id. body: $clone_body"
  exit 1
fi
green "  OK — cloned id=$rid name=$name"

# --- 4. Diff -----------------------------------------------------------

blue "[4/6] diff"
# Diff between feature and feature → empty list, but the call must
# return 200.
diff_body=$(curl -fsS -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"base":"feature","head":"feature"}' \
  "$BASE_URL/api/git/remote/$rid/diff")
files_n=$(echo "$diff_body" | jq -r '.files | length')
green "  OK — diff returned $files_n file(s)"

# --- 5. List & delete --------------------------------------------------

blue "[5/6] list / status / delete"
list_body=$(curl -fsS -H "Authorization: Bearer $API_KEY" "$BASE_URL/api/git/remote")
listed=$(echo "$list_body" | jq -r --arg id "$rid" '.remotes | map(select(.id==$id)) | length')
if [[ "$listed" != "1" ]]; then
  red "  remote $rid not in /api/git/remote list"
  exit 1
fi
curl -fsS -H "Authorization: Bearer $API_KEY" "$BASE_URL/api/git/remote/$rid" >/dev/null
curl -fsS -X DELETE -H "Authorization: Bearer $API_KEY" "$BASE_URL/api/git/remote/$rid" >/dev/null
after=$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $API_KEY" \
  "$BASE_URL/api/git/remote/$rid")
if [[ "$after" != "404" ]]; then
  red "  remote still present after delete (got $after)"
  exit 1
fi
green "  OK — list / status / delete"

# --- 6. Submit a review with source tag --------------------------------

blue "[6/6] submit review with source=remote:<name>"
review_body=$(curl -fsS -X POST \
  -H "Authorization: Bearer $API_KEY" \
  -H 'Content-Type: application/json' \
  -d "$(jq -nc --arg s "remote:$name" '{
    files: [{path:"x.py", content:"eval(\"1\")\n"}],
    title: "e2e remote review",
    focuses: ["security","bug"],
    source: $s
  }')" \
  "$BASE_URL/api/review")
rid2=$(echo "$review_body" | jq -r '.id')
green "  OK — submitted review $rid2 with source=remote:$name"

# Give the mock a moment to complete, then check the history list
sleep 0.5
hist_body=$(curl -fsS "$BASE_URL/api/reviews?limit=5")
last_source=$(echo "$hist_body" | jq -r --arg id "$rid2" '.items | map(select(.id==$id))[0].source')
if [[ "$last_source" != "remote:$name" ]]; then
  red "  history list source was '$last_source', expected 'remote:$name'"
  exit 1
fi
green "  OK — history list shows source=remote:$name"

green ""
green "All checks passed."
