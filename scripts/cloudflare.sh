# shellcheck shell=bash
# Publishes the page with its data (page/ and data/, one site) to Cloudflare,
# as a Worker serving only static assets, for an instance served from there:
# the community one, at https://nixkeeper.com/. The page then finds its data
# next to it (data/), from Cloudflare's edge, instead of on
# raw.githubusercontent.com. Run by the data workflows
# (.github/workflows/data-*.yml) after they publish the data branch, which
# stays the syncs' own copy (they restore from it).
#
#   bash scripts/cloudflare.sh deploy [--force]
#
# Only when the page or the data changed since the last deploy (or --force):
# the site's version.json (the page's git tree, a hash of the data) is
# compared with the live one first, so a run that changed nothing deploys
# nothing, and a page change goes out with the next run of either workflow.
#
# Needs CLOUDFLARE_WORKER (the Worker's name; without it, this does nothing:
# an instance on GitHub Pages only), CLOUDFLARE_SITE_URL (where it's served,
# https://nixkeeper.com), CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_API_TOKEN (a
# token with only Account → Workers Scripts → Edit). wrangler is nixpkgs'
# (this flake's lock), unless NIXKEEPER_WRANGLER names another command (a
# fake one in tests/sh/cloudflare.sh).
#
# A failed deploy is tried again, 3 attempts in all, NIXKEEPER_DEPLOY_PAUSE
# seconds apart (30 by default, 0 in the tests): Cloudflare's API sometimes
# fails one request ("An unknown error has occurred", code 10013,
# 2026-10-25), and the site then kept the last sync's data until the next
# one.

set -euo pipefail

case "${1:-}" in
deploy) ;;
*)
  echo "usage: bash scripts/cloudflare.sh deploy [--force]" >&2
  exit 2
  ;;
esac
force=false
[ "${2:-}" = --force ] && force=true

worker=${CLOUDFLARE_WORKER:-}
if [ -z "$worker" ]; then
  echo "No Cloudflare Worker (CLOUDFLARE_WORKER): not published there."
  exit 0
fi
: "${CLOUDFLARE_SITE_URL:?CLOUDFLARE_SITE_URL is needed with a Worker}"
: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID is needed with a Worker}"
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is needed with a Worker}"
if [ ! -f data/index.json ]; then
  echo "::error::No data/index.json: nothing to publish to Cloudflare."
  exit 1
fi

# What's going out: the page as on this commit, and every data file's bytes.
page=$(git rev-parse HEAD:page)
data=$(cd data && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -c1-64)
version="{\"data\":\"$data\",\"page\":\"$page\"}"
live=$(curl -fsS --max-time 30 "${CLOUDFLARE_SITE_URL%/}/version.json" 2>/dev/null || true)
if [ "$live" = "$version" ] && ! $force; then
  echo "Cloudflare already has this page and data."
  exit 0
fi

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
site=$work/site
mkdir "$site"
cp -R page/. "$site/"
cp -R data "$site/data"
printf '%s\n' "$version" >"$site/version.json"
# Served on its custom domain only (given in Cloudflare's dashboard): no
# <name>.<account>.workers.dev address or preview addresses, which wrangler
# would otherwise turn on with each deploy and print in the (public) log.
# Beside the site, not in it: it isn't served.
cat >"$work/wrangler.json" <<EOF
{
  "name": "$worker",
  "compatibility_date": "2026-10-01",
  "assets": { "directory": "site" },
  "workers_dev": false,
  "preview_urls": false
}
EOF

export WRANGLER_SEND_METRICS=false # no usage telemetry from our runs
read -r -a wrangler <<<"${NIXKEEPER_WRANGLER:-nix run --inputs-from . nixpkgs#wrangler --}"
# Static assets only (no Worker code): wrangler uploads only the files
# Cloudflare doesn't have yet, and the new version replaces the old all at
# once, never a new index.json with yesterday's shards.
# Trying again is safe: the same files deploy to the same site, and the ones
# Cloudflare already has aren't uploaded again. Every failure is tried again,
# a lasting one too (a revoked token): telling a passing one from a lasting
# one isn't worth it here, for a minute more before the run fails.
message="page $(git rev-parse --short HEAD:page), data ${data:0:12}"
pause=${NIXKEEPER_DEPLOY_PAUSE:-30}
attempts=3
for attempt in $(seq "$attempts"); do
  if "${wrangler[@]}" deploy --config "$work/wrangler.json" --message "$message"; then
    break
  fi
  if [ "$attempt" -eq "$attempts" ]; then
    echo "::error::Cloudflare deploy failed $attempts times."
    exit 1
  fi
  echo "::warning::Cloudflare deploy failed (attempt $attempt of $attempts), trying again in $pause s."
  sleep "$pause"
done
echo "Published to Cloudflare ($worker): page $page, data ${data:0:12}."
