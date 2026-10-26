# The community rules (community/): well formed, for packages in
# nixpkgs; the update checks also within the limits they're held to,
# with patterns Python compiles (nixkeeper/community.py).
{
  pkgs,
  lib,
  listsChecker,
  nixkeeper,
  ...
}:
let
  rules = import ../../community/update-checks.nix;
  found =
    map (p: p // { entry = "update-checks.nix: ${p.entry}"; }) (listsChecker.communityProblems rules)
    ++ map (p: p // { entry = "ignored-updates.nix: ${p.entry}"; }) (
      listsChecker.communityIgnoreProblems (import ../../community/ignored-updates.nix)
    )
    ++ map (p: p // { entry = "up-to-date.nix: ${p.entry}"; }) (
      listsChecker.communityUpToDateProblems (import ../../community/up-to-date.nix)
    );
in
if found != [ ] then
  throw (
    "community/ has problems:\n" + lib.concatMapStrings (p: "  - ${p.entry}: ${p.reason}\n") found
  )
else
  pkgs.runCommand "nixkeeper-community-ok"
    {
      nativeBuildInputs = [ pkgs.python3 ];
      rules = builtins.toJSON rules;
      passAsFile = [ "rules" ];
    }
    ''
      PYTHONPATH=${nixkeeper}/${pkgs.python3.sitePackages} python3 - "$rulesPath" <<'EOF'
      import json, sys
      from nixkeeper import community
      found = community.problems(json.load(open(sys.argv[1])))
      if found:
          sys.exit("community/update-checks.nix has problems:\n  - " + "\n  - ".join(found))
      EOF
      touch $out
    ''
