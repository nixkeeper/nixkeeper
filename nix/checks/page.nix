# The page's tests (tests/js/), with Node's own test runner.
{ pkgs, checkSource, ... }:
let
  src = checkSource [
    ../../page
    ../../tests/js
    ../../tests/data/version-comparison-tests.txt # Repology's, for versions.js' order
  ];
in
pkgs.runCommand "nixkeeper-page-tests" { nativeBuildInputs = [ pkgs.nodejs-slim ]; } ''
  cd ${src}
  node --test 'tests/js/*.test.mjs'
  touch $out
''
