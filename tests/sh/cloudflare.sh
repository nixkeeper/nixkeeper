# shellcheck shell=bash
# scripts/cloudflare.sh's retry, against a fake wrangler that fails a given
# number of times: run from the repository's root (the flake's scripts check).
#
#   bash tests/sh/cloudflare.sh

set -euo pipefail

script=$PWD/scripts/cloudflare.sh
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# A repository with a page and data, as the script expects to run in.
repo=$work/repo
mkdir -p "$repo/page" "$repo/data"
echo '<!doctype html>' >"$repo/page/index.html"
echo '{}' >"$repo/data/index.json"
git -C "$repo" init -q
git -C "$repo" add .
git -C "$repo" -c user.name=test -c user.email=test@example.com commit -qm page

# Fails while it has been called fewer than FAILS times, and logs each call's
# arguments.
# Run through bash: a #! line needs /usr/bin/env, which the build sandbox
# doesn't have.
cat >"$work/wrangler" <<'FAKE'
echo "$*" >>"$CALLS"
[ "$(wc -l <"$CALLS")" -gt "$FAILS" ]
FAKE

failed=0
# deploy FAILS: the exit status and the number of calls, as "exit N, calls N".
deploy() {
  rm -f "$work/calls"
  touch "$work/calls"
  local status=0
  (cd "$repo" && CALLS=$work/calls FAILS=$1 NIXKEEPER_WRANGLER="bash $work/wrangler" \
    NIXKEEPER_DEPLOY_PAUSE=0 CLOUDFLARE_WORKER=test \
    CLOUDFLARE_SITE_URL=http://127.0.0.1:9 CLOUDFLARE_ACCOUNT_ID=test \
    CLOUDFLARE_API_TOKEN=test bash "$script" deploy >"$work/out" 2>&1) || status=$?
  echo "exit $status, calls $(wc -l <"$work/calls" | tr -d ' ')"
}
expect() {
  if [ "$2" = "$3" ]; then
    echo "ok: $1"
  else
    echo "FAIL: $1: got '$2', expected '$3'"
    cat "$work/out"
    failed=1
  fi
}

expect "deployed at once" "$(deploy 0)" "exit 0, calls 1"
expect "deployed on the third attempt" "$(deploy 2)" "exit 0, calls 3"
expect "every attempt with the same message" "$(sort -u "$work/calls" | wc -l | tr -d ' ')" 1
expect "never deployed: the run fails" "$(deploy 9)" "exit 1, calls 3"
expect "said in the log" "$(grep -c '::error::Cloudflare deploy failed 3 times' "$work/out")" 1

exit "$failed"
