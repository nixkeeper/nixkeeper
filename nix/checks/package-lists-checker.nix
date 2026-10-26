# The package lists' checker itself (nix/package-lists.nix): on lists with
# known problems (cases.nix), it finds exactly those, and says why.
{
  pkgs,
  lib,
  listsChecker,
  ...
}:
let
  cases = import ./package-lists-checker/cases.nix;
  entries = lists: map (p: p.entry) (listsChecker.problems lists);
  found = entries cases.lists;
  foundNamed = entries cases.named;
  setOfPackages = lib.findFirst (p: p.entry == "cataclysmDDA") { } (
    listsChecker.problems cases.setOfPackages.lists
  );
in
assert lib.assertMsg (
  found == cases.expected
) "package-lists checker found ${builtins.toJSON found}";
assert lib.assertMsg (
  setOfPackages.reason or "" == cases.setOfPackages.reason
) "package-lists checker: a set of packages should say so";
assert lib.assertMsg (
  foundNamed == cases.expectedNamed
) "package-lists checker found ${builtins.toJSON foundNamed} (named lists)";
pkgs.runCommand "package-lists-checker-ok" { } "touch $out"
