# page/'s brand files match assets/brand/, and assets/brand/'s tokens
# match what tokens.py writes.
{
  pkgs,
  lib,
  checkSource,
  brandCopies,
  isBrandCopy,
  ...
}:
let
  copies = lib.concatStringsSep " " brandCopies;
  src = checkSource [
    ../../scripts/brand/tokens.py
    ../../scripts/brand/geometry.py
    ../../assets/brand/tokens.json
    (lib.fileset.fileFilter (f: isBrandCopy f.name) ../../assets/brand)
    (lib.fileset.fileFilter (f: isBrandCopy f.name) ../../page)
  ];
in
pkgs.runCommand "nixkeeper-brand-check" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  drift() {
    echo "$1: $2" >&2
    exit 1
  }
  cd ${src}
  PYTHONDONTWRITEBYTECODE=1 python3 scripts/brand/tokens.py "$TMPDIR/tokens" > /dev/null
  for f in tokens.css tokens.json; do
    cmp -s "$TMPDIR/tokens/$f" "assets/brand/$f" ||
      drift "assets/brand/$f" "differs from what scripts/brand/tokens.py writes: edit that, then run nix run .#brand"
  done
  # A glob that matches nothing is left out, not taken as a name.
  shopt -s nullglob
  cd ${src}/assets/brand
  for glob in ${lib.concatMapStringsSep " " (g: "'${g}'") brandCopies}; do
    found=($glob)
    [ ''${#found[@]} -gt 0 ] ||
      drift "assets/brand/$glob" "matches no file: run nix run .#brand"
  done
  for f in ${copies}; do
    cmp -s "$f" "../../page/$f" ||
      drift "page/$f" "differs from assets/brand/$f: run nix run .#brand"
  done
  cd ${src}/page
  for f in ${copies}; do
    [ -e "../assets/brand/$f" ] ||
      drift "page/$f" "has no source in assets/brand/: remove it"
  done
  touch $out
''
