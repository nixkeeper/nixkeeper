# The linters, each on what it scans: ruff and mypy (Python), deadnix and
# statix (Nix), actionlint (the workflows), shellcheck (the scripts) and Biome
# (the page and its tests, with the page's own rules in biome-plugins/).
{
  pkgs,
  lib,
  checkSource,
  linters,
  ...
}:
let
  src = checkSource [
    ../../nixkeeper
    ../../tests
    ../../scripts
    ../../page
    ../../.github/workflows
    # deadnix and statix: every Nix file, wherever it is.
    (lib.fileset.fileFilter (f: f.hasExt "nix") ../../.)
    ../../pyproject.toml # ruff's and mypy's settings
    ../../biome.json
    ../../biome-plugins # its rules for the page (no-raw-html.grit)
  ];
in
pkgs.runCommand "nixkeeper-lint" { nativeBuildInputs = linters; } ''
  cd ${src}
  export HOME=$TMPDIR
  ruff check --no-cache .
  mypy --cache-dir "$TMPDIR/mypy"
  deadnix --fail .
  statix check .
  # Named explicitly: on its own actionlint looks for .git, which the
  # flake source (CI's view of the repo) doesn't include.
  actionlint .github/workflows/*.yml
  shellcheck scripts/*.sh tests/sh/*.sh
  biome lint page tests/js
  touch $out
''
