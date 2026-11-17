# shellcheck shell=bash
# The data branch, for the data workflows (.github/workflows/data-*.yml): main
# with one commit on top, holding data/, the last published data. Each run
# starts from main's code with that data, and replaces the branch with main
# plus one new commit, so no history piles up (nothing reads it) and the data
# always sits on main's current code.
#
#   bash scripts/data-branch.sh restore [--required]
#       a branch "data" at main, with data/ as last published; on the first
#       run there's none yet (--required: fail instead, for the hourly
#       updates, which only refresh the daily sync's data)
#   bash scripts/data-branch.sh publish MESSAGE
#       commit data/ on main and replace the data branch with it, unless the
#       data is the same as last published
#
# For the workflows' checkouts: it makes nixkeeper-bot the committer there.
#
# Starting from no data resets every package's history (outdated since when,
# the last known results), so restore only does that when the branch surely
# doesn't exist: if GitHub can't be asked, it fails instead.

# A failed push is tried again, 4 attempts in all, NIXKEEPER_PUSH_PAUSE seconds
# apart (30 by default): GitHub sometimes answers a push with a 500, and the
# whole run's work would wait for the next run.

set -euo pipefail

PUBLISHED=refs/remotes/origin/data

git config user.name "nixkeeper-bot"
git config user.email "nixkeeper-bot@users.noreply.github.com"

case "${1:-}" in
  restore)
    git checkout -q -B data
    status=0
    git ls-remote --exit-code --heads origin data >/dev/null || status=$?
    if [ "$status" -eq 0 ]; then
      git fetch -q --depth=1 origin "+refs/heads/data:$PUBLISHED"
      git checkout -q "$PUBLISHED" -- data
      git reset -q # only on disk: the index stays main's
      echo "Restored the data published in $(git rev-parse --short "$PUBLISHED")."
    elif [ "$status" -eq 2 ] && [ "${2:-}" != --required ]; then
      echo "No data branch yet: this run starts it."
    elif [ "$status" -eq 2 ]; then
      echo "::error::No data branch yet: the daily sync makes it first."
      exit 1
    else
      echo "::error::Couldn't ask GitHub for the data branch (git ls-remote: $status)."
      exit 1
    fi
    ;;
  publish)
    message="${2:?publish needs a commit message}"
    if [ ! -f data/index.json ]; then
      echo "::error::No data/index.json: nothing to publish."
      exit 1
    fi
    git add -f data
    previous=$(git rev-parse -q --verify "$PUBLISHED" || true)
    if [ -n "$previous" ] && git diff --cached --quiet "$previous" -- data; then
      echo "The data hasn't changed since it was last published."
      exit 0
    fi
    git commit -q -m "$message"
    pause=${NIXKEEPER_PUSH_PAUSE:-30}
    attempts=4
    for attempt in $(seq "$attempts"); do
      # Only over what this run started from: never over another run's data.
      if git push -q --force-with-lease="data:$previous" origin HEAD:data; then
        break
      fi
      # What's there now, if GitHub answers: this push may have got through
      # with only its answer lost, or another run may have published.
      if remote=$(git ls-remote origin refs/heads/data | cut -f1); then
        if [ "$remote" = "$(git rev-parse HEAD)" ]; then
          break
        elif [ "$remote" != "$previous" ]; then
          echo "::error::Another run published the data ($remote): not replacing it."
          exit 1
        fi
      fi
      if [ "$attempt" -eq "$attempts" ]; then
        echo "::error::Pushing the data failed $attempts times."
        exit 1
      fi
      echo "::warning::Pushing the data failed (attempt $attempt of $attempts), trying again in $pause s."
      sleep "$pause"
    done
    echo "Published the data as $(git rev-parse --short HEAD), on main."
    ;;
  *)
    echo "usage: bash scripts/data-branch.sh restore [--required] | publish MESSAGE" >&2
    exit 2
    ;;
esac
