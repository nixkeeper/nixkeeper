# shellcheck shell=bash
# Starts a nixkeeper instance's runs through GitHub's API (workflow
# dispatch), from a machine that's always on: GitHub's own schedule is
# best-effort and skips runs when it's busy (nixkeeper-hydra's hourly digest
# ran 3 times on 2026-10-06). Run it hourly at :15 UTC (the nix-darwin agent
# and NixOS timer in docs/all-packages.md); by the hour in UTC it starts:
#
#   every hour      the hourly updates of NIXKEEPER_START_REPO (default
#                   nixkeeper/nixkeeper), except every 3 hours (00, 03, 06...)
#   every 3 hours   its sync instead, when due by the instance's interval
#                   (if_older "auto": every 3 hours on the community
#                   instance, daily on a fork; it checks update PRs too).
#                   Not both at once: they share the data branch's
#                   concurrency group, where only one run can wait and a
#                   newer one cancels it, so fewer runs queued means less
#                   chance of losing the sync
#
# and the digests in NIXKEEPER_START_DIGESTS' repositories (default nixkeeper;
# empty for none: a fork reads nixkeeper's digests, run by nixkeeper):
#
#   every hour      nixkeeper-hydra's (stops early with no newer evaluation),
#                   nixkeeper-vulnerabilities' (a new repository's
#                   schedule ran once in its first 7 hours, 2026-10-08)
#                   and nixkeeper-prs' (its open PRs, and their diffs)
#   every 3 hours   nixkeeper-updates'
#   04 and 16 UTC   nixkeeper-versions', if its last run is over 10 hours old
#   every hour      status' check (nixkeeper/status: whether all of the above
#                   are on time, on a page and as issues), last, so it sees
#                   this hour's starts; its own schedule keeps it going if
#                   this machine stops, which is one of the things it checks
#
# The workflows keep their own schedules as a fallback: a run started twice
# (by both) either waits for the other and finds nothing new, or stops at
# once (if_older).
#
# The token: a fine-grained one for those repositories with only "Actions:
# read and write" (it can start and cancel runs, nothing else), from the
# file NIXKEEPER_START_TOKEN_FILE, else systemd's credential "token"
# (LoadCredential), else the macOS Keychain item "nixkeeper-start-runs".
# --dry-run prints what it would start, without one.
#
# A start GitHub answers with a server error (5xx), or doesn't answer, is
# tried again after 1 minute and then 3 (NIXKEEPER_START_RETRY_WAITS, in
# seconds): on 2026-10-07 one hour's starts all got 500s, and a lost start
# of nixkeeper-updates' is 3 hours lost. Other answers (a bad token, a
# wrong workflow) aren't: they won't change by waiting. Should a failed
# start have started the run after all, the second is harmless (see above).

set -euo pipefail

repo=${NIXKEEPER_START_REPO-nixkeeper/nixkeeper}
read -ra retry_waits <<<"${NIXKEEPER_START_RETRY_WAITS-60 180}"
digests=${NIXKEEPER_START_DIGESTS-nixkeeper}
dry_run=false
case "${1:-}" in
--dry-run) dry_run=true ;;
"") ;;
*)
  echo "usage: start-runs [--dry-run]" >&2
  exit 2
  ;;
esac
hour=$((10#$(date -u +%H)))

token=
if ! $dry_run; then
  if [ -n "${NIXKEEPER_START_TOKEN_FILE:-}" ]; then
    token=$(<"$NIXKEEPER_START_TOKEN_FILE")
  elif [ -n "${CREDENTIALS_DIRECTORY:-}" ] && [ -f "$CREDENTIALS_DIRECTORY/token" ]; then
    token=$(<"$CREDENTIALS_DIRECTORY/token")
  elif [ -x /usr/bin/security ]; then
    token=$(/usr/bin/security find-generic-password -s nixkeeper-start-runs -w)
  else
    echo "No token: set NIXKEEPER_START_TOKEN_FILE, or LoadCredential=token:<file>." >&2
    exit 2
  fi
fi

failed=0
start() {
  local target=$1 workflow=$2 inputs=${3:-"{}"}
  local stamp
  stamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  if $dry_run; then
    echo "$stamp would start $target $workflow $inputs"
    return
  fi
  local code wait
  for wait in "${retry_waits[@]}" ""; do
    # The token's header from stdin (--config -), not the command line,
    # where anyone on the machine could read it (ps).
    code=$(printf 'header = "Authorization: Bearer %s"\n' "$token" |
      curl --config - --silent --show-error --max-time 30 --output /dev/null \
        --write-out '%{http_code}' --request POST \
        --header "Accept: application/vnd.github+json" \
        --header "X-GitHub-Api-Version: 2022-11-28" \
        --data "{\"ref\":\"main\",\"inputs\":$inputs}" \
        "https://api.github.com/repos/$target/actions/workflows/$workflow/dispatches") ||
      code="no answer"
    if [ "$code" = 204 ]; then
      echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) started $target $workflow"
      return
    fi
    case "$code" in
    5?? | "no answer" | 000) ;;
    *) wait= ;; # not worth trying again
    esac
    if [ -z "$wait" ]; then
      break
    fi
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) could not start $target $workflow: $code, trying again in ${wait}s" >&2
    sleep "$wait"
  done
  echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) FAILED to start $target $workflow: $code" >&2
  failed=1
}

if [ -n "$digests" ]; then
  start "$digests/digest-builds" digest.yml
  start "$digests/digest-vulnerabilities" digest.yml
  start "$digests/digest-prs" digest.yml
  if ((hour % 3 == 0)); then
    start "$digests/digest-update-bot" digest.yml
  fi
  if ((hour % 12 == 4)); then
    start "$digests/digest-versions" digest.yml '{"if_older":"10"}'
  fi
fi
if [ -n "$repo" ]; then
  if ((hour % 3 == 0)); then
    start "$repo" data-daily.yml '{"if_older":"auto"}'
  else
    start "$repo" data-hourly.yml
  fi
fi
if [ -n "$digests" ]; then
  start "$digests/status" check.yml
fi
exit "$failed"
