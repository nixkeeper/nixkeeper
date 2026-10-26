# The package lists' checker's test cases (nix/package-lists.nix): lists with
# known problems, and the problems the checker must find in them, in order.
{
  # One of each problem the checker looks for, beside entries that are fine.
  lists = {
    maintainers = [
      "iedame"
      "IEDAME"
      "no-such-handle-nixkeeper"
    ];
    extraPackages = [
      "opentyrian"
      "haskellPackages.pandoc"
      "python313Packages.requests"
      "python3Packages.requests"
      "nosuchpkg-nixkeeper"
      "cataclysmDDA" # a set of packages, not a package
      "opentyrian"
    ];
    updateChecks = {
      opentyrian = {
        github = "opentyrian/opentyrian"; # listed: fine
        tags = "^v(.+)$";
      };
      wesnoth = {
        github = "wesnoth/wesnoth"; # maintained by iedame: fine
        tags = "^(1\\.18\\.[0-9]+)$";
      };
      hello = {
        github = "not a repo";
        tag = "typo";
      };
      "haskellPackages.pandoc" = {
        github = "jgm/pandoc";
        url = "https://pandoc.org";
      };
      lincity = {
        url = "ftp://example.org";
        pattern = "([0-9.]+)";
      };
    };
    ignoredUpdates = {
      opentyrian."2.1.1" = "never released"; # fine
      hello."1.0" = "not tracked";
      wesnoth."1.18.9" = "";
      lincity = { };
    };
    upToDate = {
      opentyrian = {
        version = "2.1.20220318";
        reason = "fine";
      };
      hello = {
        version = "1";
        reason = "not tracked";
      };
      wesnoth = "1.18.8"; # the old format
      lincity = {
        version = "1";
        newest = "";
        why = "typo";
      };
    };
  };
  # Each problem's entry, as the checker reports it.
  expected = [
    "no-such-handle-nixkeeper"
    "opentyrian"
    "python3Packages.requests"
    "nosuchpkg-nixkeeper"
    "cataclysmDDA"
    "updateChecks.haskellPackages.pandoc" # both github and url
    "updateChecks.hello" # not tracked
    "updateChecks.hello" # github isn't owner/repo
    "updateChecks.hello" # no tags
    "updateChecks.hello" # unknown field "tag"
    "updateChecks.lincity" # url isn't http(s); tracked via iedame
    "ignoredUpdates.hello" # not tracked
    "ignoredUpdates.lincity" # no versions
    "ignoredUpdates.wesnoth" # empty reason
    "upToDate.hello" # not tracked
    "upToDate.lincity" # no reason
    "upToDate.lincity" # empty newest
    "upToDate.lincity" # unknown field "why"
    "upToDate.wesnoth" # not { version, reason }
  ];

  # Named lists: on two lists is fine, twice in one isn't, and "maintained"
  # is taken.
  named = {
    maintainers = [ "iedame" ];
    extraPackages = {
      extra = [ "opentyrian" ];
      gaming-team = [
        "opentyrian"
        "freedink"
        "freedink"
      ];
      maintained = [ ];
    };
  };
  expectedNamed = [
    "freedink"
    "extraPackages.maintained"
  ];

  # A set of packages says what's wrong (it passed this check before, and the
  # sync found nothing: nixkeeper/nixkeeper's cataclysmDDA).
  setOfPackages = {
    lists = {
      maintainers = [ ];
      extraPackages = [ "cataclysmDDA" ];
    };
    reason = "a set of packages, not a package: list the one you mean (its attribute or pname)";
  };
}
