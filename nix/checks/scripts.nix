# The scripts' own logic (tests/sh/), for now the Cloudflare deploy's
# retry, against a fake wrangler.
{ pkgs, checkSource, ... }:
let
  src = checkSource [
    ../../scripts/cloudflare.sh # the one script tests/sh/ runs
    ../../tests/sh
  ];
in
pkgs.runCommand "nixkeeper-script-tests" { nativeBuildInputs = [ pkgs.git ]; } ''
  cd ${src}
  export HOME=$TMPDIR
  bash tests/sh/cloudflare.sh
  touch $out
''
