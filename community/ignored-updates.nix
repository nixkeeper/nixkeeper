# Community ignore rules: failed nixpkgs-update (r-ryantm) attempts that
# shouldn't count as the bot's failure, for any nixpkgs package, so everyone
# who opts in gets the same answer without writing the rule themselves. Opt
# in with
#
#   community.ignoredUpdates = true;
#
# in your package lists (package-lists/default.nix, or lists.community in the
# NixOS or nix-darwin module). Each sync then applies the rules here to the
# packages it tracks. Your own ignore rules win over these for the same
# version. The rules come with nixkeeper, so they change only when you update
# it.
#
# The format is your own ignore rules' (package-lists/ignored-updates.nix):
# keyed by the package's row name (its nixpkgs attribute), then the version
# the bot tried (or, when its updateScript failed before picking one and the
# package isn't outdated, the version nixpkgs has), with why it doesn't count:
#
#   foo."1.2.3" = "Upstream tagged it by mistake; it was never released.";
#
# A rule only matters while the bot's latest attempt is a failure at that
# version (for an updateScript failure, also only until a newer release comes
# out): once the bot tries another version, it does nothing, and the weekly
# community run lists it as one that can go.
# So these are short-lived, and they're not the fix at the source: to stop the
# bot trying a version, that's Repology's ignore rules or nixpkgs-update's
# skiplist. A rule here only stops the failure it already made from showing.
{
  # keep-sorted start newline_separated=yes
  blackvoxel."2.5" = "Temporary: v prefix removal at 2.5 causes update error.";

  tetris."7.9.0" = "Incorrect version: package name collision, reported to Repology.";

  xskat."4.0-9" = "Never released: an upstream versioning mistake. Repology ignores it too.";
  # keep-sorted end
}
