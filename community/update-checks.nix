# Community update checks: rules anyone can add by pull request, for any
# nixpkgs package, so every nixkeeper that opts in gets quicker, more precise
# new-release checks than Repology alone gives. Opt in with
#
#   community.updateChecks = true;
#
# in your package lists (package-lists/default.nix, or lists.community in the
# NixOS or nix-darwin module). Each sync then uses the rules here for
# the packages it tracks, and only those: nothing is fetched for the rest.
# Your own update checks win over these for the same package. The rules come
# with nixkeeper, so they change only when you update it.
#
# The format is your own update checks' (package-lists/update-checks.nix):
# keyed by the package's row name (its nixpkgs attribute), each one of
#
#   github = "owner/repo";  tags = "regex";           a repository's tags
#   github = "owner/repo";  branch = "name";          an unstable version's
#                                                     branch (+ outdatedAfter)
#   url = "https://...";    pattern = "regex";        a web page
#   follows = "package";                              updated together with
#                                                     that package (same
#                                                     version, same PRs)
#
# plus `frequent = true;` to also be checked by the hourly checks. Because
# these run on everyone's machines, they're held to limits your own rules
# aren't, and a rule beyond them is refused, never fetched:
#
#   - url: https only, to a public host by name: no IP addresses, no
#     localhost or local-network names, and redirects must stay public;
#     a page is read up to 2 MB;
#   - tags and pattern: at most 200 characters, with no repeated repeats
#     like (a+)+ and no back-references, which can take forever to match;
#   - only the fields above; follows takes no others, and fetches nothing
#     (it only uses that package's results, when you track both).
#
# A good rule follows what nixpkgs packages: the stable series it tracks, the
# page its source comes from. Explain that in the pull request that adds it
# (where the version comes from, and why this rule): the rules themselves
# stay a plain list, sorted by package (nix fmt keeps it so).
{
  # keep-sorted start block=yes newline_separated=yes
  bbedit = {
    url = "https://www.barebones.com/support/bbedit/updates.html";
    pattern = "BBEdit ([0-9]+\\.[0-9]+(?:\\.[0-9]+)?)";
  };

  google-chrome = {
    url = "https://versionhistory.googleapis.com/v1/chrome/platforms/linux/channels/stable/versions";
    pattern = "\"version\": \"([0-9.]+)\"";
    frequent = true;
  };

  microsoft-edge = {
    url = "https://packages.microsoft.com/repos/edge/dists/stable/main/binary-amd64/Packages";
    pattern = "Package: microsoft-edge-stable\nVersion: ([0-9.]+)";
    frequent = true;
  };

  msedgedriver = {
    follows = "microsoft-edge";
  };

  stepmania = {
    github = "stepmania/stepmania";
    branch = "5_1-new";
  };

  wesnoth = {
    github = "wesnoth/wesnoth";
    tags = "^(1\\.[0-9]*[02468]\\.[0-9]+)$";
  };

  wesnoth-devel = {
    github = "wesnoth/wesnoth";
    tags = "^(1\\.19\\.[0-9]+)$";
  };
  # keep-sorted end
}
