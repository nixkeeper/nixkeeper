# Checks package-lists/ against nixpkgs, mirroring how the sync reads them
# (nixkeeper/tracking.py): an entry is a nixpkgs attribute name, including
# nested ones in sets the channel index covers (haskellPackages.foo), or a
# top-level pname. Catches typos and aliases (python3Packages.foo) at
# `nix flake check` time instead of as a "not in nixpkgs" row after a sync.
#
# pkgs should be imported with config.allowAliases = false: aliases aren't in
# the channel index either.
{ pkgs }:
let
  inherit (pkgs) lib;

  # Sets the channel index descends into: python313Packages yes,
  # python3Packages (an alias for the default version) no.
  indexed = set: (builtins.tryEval (pkgs.${set}.recurseForDerivations or false)).value == true;

  # A package: what the channel index lists. An attribute that's a set of
  # packages (cataclysmDDA: stable, git, ...) isn't one, nor is one that
  # throws when evaluated.
  isPackage = value: (builtins.tryEval (lib.isDerivation value)).value == true;

  # An attribute name the sync can find in the channel index: a package, at
  # the top level or in a set the index covers.
  isAttribute =
    name:
    let
      path = lib.splitString "." name;
    in
    (
      if builtins.length path == 1 then
        pkgs ? ${name}
      else
        indexed (builtins.head path) && lib.hasAttrByPath path pkgs
    )
    && isPackage (lib.attrByPath path null pkgs);

  # Only evaluated when some entry isn't an attribute name: scanning every
  # top-level package takes ~10 s.
  topLevelPnames = lib.genAttrs (builtins.filter (x: x != null) (
    map (
      attr:
      let
        r = builtins.tryEval (
          let
            p = pkgs.${attr};
          in
          if builtins.isAttrs p && p ? pname then p.pname else null
        );
      in
      if r.success then r.value else null
    ) (builtins.attrNames pkgs)
  )) (_: true);

  githubHandles = lib.genAttrs (map (m: lib.toLower m.github) (
    builtins.filter (m: m ? github) (builtins.attrValues lib.maintainers)
  )) (_: true);

  # Whether the sync tracks a row of this name: listed itself, listed by
  # pname, or maintained by one of the handles (see nixkeeper/tracking.py).
  # extraPackages as named lists ({ extra = [ ... ]; gaming-team = [ ... ]; });
  # a plain list counts as "extra" (see nixkeeper/tracking.py).
  extraLists =
    lists:
    let
      extra = lists.extraPackages or [ ];
    in
    if builtins.isList extra then { inherit extra; } else extra;
  # The page's palettes (page/palette.js PALETTES), for page.theme.
  themes = [
    "classic"
    "catppuccin"
  ];

  allEntries = lists: lib.concatLists (builtins.attrValues (extraLists lists));

  isTracked =
    lists: name:
    let
      pkg = lib.attrByPath (lib.splitString "." name) null pkgs;
      meta = (builtins.tryEval (if builtins.isAttrs pkg then pkg.meta or { } else { })).value;
      handles = map lib.toLower lists.maintainers;
    in
    builtins.elem name (allEntries lists)
    || (
      isAttribute name
      && (
        builtins.elem (pkg.pname or null) (allEntries lists)
        || builtins.any (m: builtins.elem (lib.toLower (m.github or "")) handles) (meta.maintainers or [ ])
      )
    );

  checkProblems =
    lists: name: check:
    let
      at = reason: {
        entry = "updateChecks.${name}";
        inherit reason;
      };
      # A check is github + tags, github + branch, or url + pattern.
      kind =
        fields: valid:
        let
          second = builtins.elemAt fields 1;
        in
        lib.optional (!builtins.isString (check.${second} or null)) (
          at (if second == "branch" then "branch must be a string" else "${second} must be a regex string")
        )
        ++ lib.optional (!valid) (
          at (
            if check ? github then
              ''github must be "owner/repo"''
            else
              "url must start with https:// or http://"
          )
        )
        ++ lib.optional (!builtins.isBool (check.frequent or false)) (at "frequent must be true or false")
        ++ map (k: at "unknown field ${k}") (
          builtins.filter (k: !builtins.elem k (fields ++ [ "frequent" ])) (builtins.attrNames check)
        );
      # outdatedAfter = { days = 90; commits = 50; }: null turns one off, and
      # what's left out keeps its default (days = 90, commits off).
      limits = check.outdatedAfter or { };
      limit =
        field: least:
        lib.optional (
          limits ? ${field}
          && !(limits.${field} == null || builtins.isInt limits.${field} && limits.${field} >= least)
        ) (at "outdatedAfter.${field} must be a whole number of at least ${toString least}, or null");
      outdatedAfterProblems =
        if !(check ? outdatedAfter) then
          [ ]
        else if !builtins.isAttrs limits then
          [ (at "outdatedAfter must be { days = ...; commits = ...; }") ]
        else
          map (k: at "outdatedAfter: unknown field ${k} (days, commits)") (
            builtins.filter (k: k != "days" && k != "commits") (builtins.attrNames limits)
          )
          ++ limit "days" 0
          ++ limit "commits" 1
          ++ lib.optional ((limits.days or 90) == null && (limits.commits or null) == null) (
            at "outdatedAfter turns off both days and commits: it could never be outdated"
          );
    in
    lib.optional (!isTracked lists name) (at "not a tracked package (use its row name, the attribute)")
    ++ (
      # follows = "<package>": updated together with it (nixkeeper/follows.py).
      if check ? follows then
        let
          target = check.follows;
        in
        if !builtins.isString target then
          [ (at "follows must be a package's attribute name (a string)") ]
        else
          lib.optional (target == name) (at "follows itself")
          ++ lib.optional (target != name && !isAttribute target) (
            at "follows ${target}, which isn't a nixpkgs attribute"
          )
          ++ lib.optional (target != name && isAttribute target && !isTracked lists target) (
            at "follows ${target}, which isn't tracked (track it too: its versions and PRs are where this one's come from)"
          )
          ++ map (k: at "follows takes no other fields (${k})") (
            builtins.filter (k: k != "follows") (builtins.attrNames check)
          )
      else if check ? github && check ? url then
        [ (at "use either github (+ tags or branch) or url (+ pattern), not both") ]
      else if check ? github && check ? tags && check ? branch then
        [ (at "use either tags or branch with github, not both") ]
      else if check ? github && check ? branch then
        kind [ "github" "branch" "outdatedAfter" ] (builtins.match "[^/ ]+/[^/ ]+" check.github != null)
        ++ outdatedAfterProblems
      else if check ? github then
        kind [ "github" "tags" ] (builtins.match "[^/ ]+/[^/ ]+" check.github != null)
      else if check ? url then
        kind [ "url" "pattern" ] (builtins.match "https?://.+" check.url != null)
      else
        [ (at "needs github + tags, github + branch, url + pattern, or follows") ]
    );

  # ignoredUpdates.<name> = { "<version>" = "why"; }.
  ignoredProblems =
    lists: name: rules:
    let
      at = reason: {
        entry = "ignoredUpdates.${name}";
        inherit reason;
      };
    in
    lib.optional (!isTracked lists name) (at "not a tracked package (use its row name, the attribute)")
    ++ (
      if !builtins.isAttrs rules || rules == { } then
        [ (at ''must be { "<version>" = "why it's ignored"; }'') ]
      else
        map (v: at ''"${v}" needs a reason: a non-empty string'') (
          builtins.filter (v: !(builtins.isString rules.${v} && rules.${v} != "")) (builtins.attrNames rules)
        )
    );

  # upToDate.<name> = { version = "<nixpkgs' version>"; newest = "<Repology's
  # newest elsewhere>"; reason = "why"; } (newest left out when there's none).
  upToDateProblems =
    lists: name: rule:
    let
      at = reason: {
        entry = "upToDate.${name}";
        inherit reason;
      };
      nonEmpty = field: builtins.isString (rule.${field} or null) && rule.${field} != "";
    in
    lib.optional (!isTracked lists name) (at "not a tracked package (use its row name, the attribute)")
    ++ (
      if !builtins.isAttrs rule then
        [ (at ''must be { version = "..."; newest = "..."; reason = "..."; }'') ]
      else
        lib.optional (!nonEmpty "version") (
          at "version must be the version nixpkgs has: a non-empty string"
        )
        ++ lib.optional (!nonEmpty "reason") (at "needs a reason: a non-empty string")
        ++ lib.optional (rule ? newest && !nonEmpty "newest") (
          at "newest must be the version Repology shows as newest elsewhere (or left out when it shows none)"
        )
        ++ map (k: at "unknown field ${k} (version, newest, reason)") (
          builtins.filter (
            k:
            !builtins.elem k [
              "version"
              "newest"
              "reason"
            ]
          ) (builtins.attrNames rule)
        )
    );
in
rec {
  # [ { entry, reason } ] for the community update checks
  # (community/update-checks.nix): each a well-formed check, as your own are,
  # for a package that exists in nixpkgs (row names are attributes). Checked
  # as if the package were tracked: community rules are for anyone's lists.
  communityProblems =
    rules:
    lib.concatLists (
      lib.mapAttrsToList (
        name: check:
        if !isAttribute name then
          [
            {
              entry = name;
              reason = "not a nixpkgs attribute (rules are keyed by the package's attribute)";
            }
          ]
        else
          map (p: p // { entry = name; }) (
            checkProblems {
              maintainers = [ ];
              # As if both were tracked: a follows rule only applies when they are.
              extraPackages = [ name ] ++ lib.optional (builtins.isString (check.follows or null)) check.follows;
            } name check
          )
      ) rules
    );

  # [ { entry, reason } ] for the community ignore rules
  # (community/ignored-updates.nix), checked like communityProblems.
  communityIgnoreProblems =
    rules:
    lib.concatLists (
      lib.mapAttrsToList (
        name: versions:
        if !isAttribute name then
          [
            {
              entry = name;
              reason = "not a nixpkgs attribute (rules are keyed by the package's attribute)";
            }
          ]
        else
          map (p: p // { entry = name; }) (
            ignoredProblems {
              maintainers = [ ];
              extraPackages = [ name ];
            } name versions
          )
      ) rules
    );

  # [ { entry, reason } ] for the community up-to-date rules
  # (community/up-to-date.nix), checked like communityProblems.
  communityUpToDateProblems =
    rules:
    lib.concatLists (
      lib.mapAttrsToList (
        name: rule:
        if !isAttribute name then
          [
            {
              entry = name;
              reason = "not a nixpkgs attribute (rules are keyed by the package's attribute)";
            }
          ]
        else
          map (p: p // { entry = name; }) (
            upToDateProblems {
              maintainers = [ ];
              extraPackages = [ name ];
            } name rule
          )
      ) rules
    );

  # [ { entry, reason } ] for everything the sync would get wrong.
  problems =
    lists:
    let
      badHandles = builtins.filter (h: !(githubHandles ? ${lib.toLower h})) lists.maintainers;
      entries = allEntries lists;
      # Within one list: being on two lists is fine (it shows under both).
      duplicates = lib.concatLists (
        lib.mapAttrsToList (
          list: es:
          map (e: {
            entry = e;
            reason = "listed more than once in ${list}";
          }) (lib.unique (builtins.filter (e: lib.count (x: x == e) es > 1) es))
        ) (extraLists lists)
      );
      unknown = builtins.filter (e: !(isAttribute e) && !(topLevelPnames ? ${e})) (lib.unique entries);
      reason =
        e:
        let
          path = lib.splitString "." e;
        in
        if lib.hasAttrByPath path pkgs && !isPackage (lib.attrByPath path null pkgs) then
          "a set of packages, not a package: list the one you mean (its attribute or pname)"
        else if builtins.length path > 1 && lib.hasAttrByPath path pkgs then
          "${builtins.head path} is an alias the sync can't see; use the versioned set (e.g. python313Packages)"
        else
          "not a nixpkgs attribute or top-level pname";
    in
    map (h: {
      entry = h;
      reason = "maintainers: no nixpkgs maintainer has this GitHub handle";
    }) badHandles
    ++ duplicates
    ++ lib.optional (extraLists lists ? maintained) {
      entry = "extraPackages.maintained";
      reason = "that list name is taken: it's the packages found through maintainers";
    }
    ++ map (e: {
      entry = e;
      reason = reason e;
    }) unknown
    ++ lib.concatLists (lib.mapAttrsToList (checkProblems lists) (lists.updateChecks or { }))
    ++ lib.concatLists (lib.mapAttrsToList (ignoredProblems lists) (lists.ignoredUpdates or { }))
    ++ lib.concatLists (lib.mapAttrsToList (upToDateProblems lists) (lists.upToDate or { }))
    ++ lib.optional (!builtins.isBool (lists.workedOutChecks or true)) {
      entry = "workedOutChecks";
      reason = "must be true or false";
    }
    ++ lib.optional (!(builtins.elem ((lists.page or { }).theme or "classic") themes)) {
      entry = "page.theme";
      reason = "not one of the page's themes (${lib.concatStringsSep ", " themes})";
    };

  # A derivation that builds only if lists has no problems. The update checks'
  # patterns are Python regexes, so Python compiles them.
  check =
    lists:
    let
      ps = problems lists;
    in
    if ps == [ ] then
      pkgs.runCommand "package-lists-ok"
        {
          nativeBuildInputs = [ pkgs.python3 ];
          checks = builtins.toJSON (lists.updateChecks or { });
          passAsFile = [ "checks" ];
        }
        ''
          python3 - "$checksPath" <<'EOF'
          import json, re, sys
          bad = []
          for name, check in json.load(open(sys.argv[1])).items():
              if "branch" in check:
                  continue  # no pattern: the branch's newest commit
              field = "tags" if "github" in check else "pattern"
              try:
                  if re.compile(check[field]).groups > 1:
                      bad.append(f"{name}: {field} has more than one capture group")
              except re.error as e:
                  bad.append(f"{name}: {field} is not a valid regex ({e})")
          if bad:
              sys.exit("package-lists/update-checks.nix has problems:\n  - " + "\n  - ".join(bad))
          EOF
          touch $out
        ''
    else
      throw (
        "package-lists/ has problems:\n"
        + lib.concatMapStrings (p: "  - ${p.entry}: ${p.reason}\n") ps
        + "(checked against this flake's pinned nixpkgs: for a package newer than that, run `nix flake update`)"
      );
}
