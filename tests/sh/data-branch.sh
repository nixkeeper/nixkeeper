# shellcheck shell=bash
# scripts/data-branch.sh publish's retry, against a local repository and a fake
# git whose pushes fail a given number of times: run from the repository's root
# (the flake's scripts check).
#
#   bash tests/sh/data-branch.sh

set -euo pipefail

script=$PWD/scripts/data-branch.sh
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
real_git=$(command -v git)

export GIT_AUTHOR_NAME=test GIT_AUTHOR_EMAIL=test@example.com
export GIT_COMMITTER_NAME=test GIT_COMMITTER_EMAIL=test@example.com

# Counts its pushes. The first FAILS fail like GitHub's 500: without pushing,
# or (LOST=1) after pushing, with only the answer lost.
mkdir "$work/bin"
cat >"$work/bin/git" <<FAKE
#!$(command -v bash)
if [ "\$1" = push ]; then
  echo push >>"\$CALLS"
  if [ "\$(wc -l <"\$CALLS")" -le "\$FAILS" ]; then
    if [ "\${LOST:-}" = 1 ]; then "$real_git" "\$@"; fi
    echo "remote: Internal Server Error" >&2
    exit 1
  fi
fi
exec "$real_git" "\$@"
FAKE
chmod +x "$work/bin/git"

# A checkout of main with new data on disk, as a run has before it publishes,
# and the data branch it started from.
setup() {
  rm -rf "$work/origin.git" "$work/repo" "$work/calls"
  touch "$work/calls"
  git init -q --bare -b main "$work/origin.git"
  git init -q -b main "$work/repo"
  (
    cd "$work/repo"
    git remote add origin "$work/origin.git"
    echo code >code
    git add code
    git commit -qm code
    git push -q origin main
    git switch -qc data
    mkdir data
    echo old >data/index.json
    git add data
    git commit -qm old
    git push -q origin data
    git fetch -q origin "+refs/heads/data:refs/remotes/origin/data"
    git switch -q main
    mkdir -p data
    echo new >data/index.json
  )
}

# publish FAILS: the exit status and the number of pushes, as "exit N, pushes N".
publish() {
  local status=0
  (cd "$work/repo" && PATH=$work/bin:$PATH CALLS=$work/calls FAILS=$1 \
    NIXKEEPER_PUSH_PAUSE=0 bash "$script" publish new >"$work/out" 2>&1) || status=$?
  echo "exit $status, pushes $(wc -l <"$work/calls" | tr -d ' ')"
}
on_data_branch() { git -C "$work/origin.git" show data:data/index.json; }

failed=0
expect() {
  if [ "$2" = "$3" ]; then
    echo "ok: $1"
  else
    echo "FAIL: $1: got '$2', expected '$3'"
    cat "$work/out"
    failed=1
  fi
}

setup
expect "published at once" "$(publish 0)" "exit 0, pushes 1"
expect "the new data" "$(on_data_branch)" new

setup
expect "published on the third attempt" "$(publish 2)" "exit 0, pushes 3"
expect "the new data, after failing" "$(on_data_branch)" new

setup
expect "never published: the run fails" "$(publish 9)" "exit 1, pushes 4"
expect "said in the log" "$(grep -c '::error::Pushing the data failed 4 times' "$work/out")" 1
expect "the old data stays" "$(on_data_branch)" old

# The push got through and only its answer was lost: done, not a lease failure.
setup
export LOST=1
expect "the answer lost" "$(publish 1)" "exit 0, pushes 1"
unset LOST
expect "the new data, its answer lost" "$(on_data_branch)" new

# Another run published since this one started: not retried, not replaced.
setup
other=$(git -C "$work/origin.git" commit-tree -m other 'main^{tree}')
git -C "$work/origin.git" update-ref refs/heads/data "$other"
expect "another run's data" "$(publish 0)" "exit 1, pushes 1"
expect "said so in the log" "$(grep -c '::error::Another run published' "$work/out")" 1
expect "its data stays" "$(git -C "$work/origin.git" rev-parse data)" "$other"

exit "$failed"
