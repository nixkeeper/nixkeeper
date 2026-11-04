# The scripts' own logic (tests/sh/): the Cloudflare deploy's retry, against a
# fake wrangler, and the data branch's push retry, against a fake git.
{ pkgs, checkSource, ... }:
let
  src = checkSource [
    ../../scripts/cloudflare.sh # the scripts tests/sh/ runs
    ../../scripts/data-branch.sh
    ../../tests/sh
  ];
in
pkgs.runCommand "nixkeeper-script-tests" { nativeBuildInputs = [ pkgs.git ]; } ''
  cd ${src}
  export HOME=$TMPDIR
  bash tests/sh/cloudflare.sh
  bash tests/sh/data-branch.sh
  touch $out
''
