# Community up-to-date rules: versions nixpkgs has that Repology gets wrong
# (calls them untrusted, incorrect or ignored, or compares them with a version
# that isn't really newer), for any nixpkgs package, so everyone who opts in
# sees them as up to date without writing the rule themselves. Opt in with
#
#   community.upToDate = true;
#
# in your package lists (package-lists/default.nix, or lists.community in the
# NixOS or nix-darwin module). Each sync then applies the rules here to the
# packages it tracks. Your own up-to-date rules win over these for the same
# package. The rules come with nixkeeper, so they change only when you update
# it.
#
# The format is your own up-to-date rules' (package-lists/up-to-date.nix):
# keyed by the package's row name (its nixpkgs attribute), the version nixpkgs
# has, the version Repology shows as newest elsewhere (left out when it shows
# none), and why nixpkgs' version is right:
#
#   foo = {
#     version = "2024-01-02";
#     newest = "1.0";
#     reason = "A snapshot from after the 1.0 release.";
#   };
#
# A rule only applies while nixpkgs has that version and Repology shows
# nothing newer than `newest` elsewhere: once nixpkgs moves on or a newer
# release comes out, it does nothing, and the weekly community run lists it
# as one that can go. Where Repology itself is wrong, the fix at the source
# is a report to Repology; a rule here only stops it from showing meanwhile.
{
  # keep-sorted start block=yes newline_separated=yes
  asc = {
    version = "2.6.3.0";
    newest = "2.6.1.0";
    reason = "nixpkgs builds a ValHaris/asc-hq commit it versions 2.6.3.0; the other repositories have the 2.6.1.0 release, and Repology flags 2.6.3.0 as incorrect.";
  };

  steamtinkerlaunch = {
    version = "12.12-unstable-2025-07-14";
    newest = "12.12";
    reason = "A snapshot from after the 12.12 release; Repology ignores unstable versions.";
  };

  wesnoth-devel = {
    version = "1.19.28";
    newest = "1.19.24";
    reason = "The newest development release; Repology ignores it, and the other repositories that package devel releases are behind.";
  };
  # keep-sorted end
}
