# nixkeeper's package, in nixpkgs' by-name style. The flake builds it from the
# checkout, passing src and version (pyproject.toml's). For nixpkgs
# (pkgs/by-name/ni/nixkeeper/package.nix) it's this file with those two
# arguments replaced by a release:
#
#   version = "x.y.z";
#   src = fetchFromGitHub {
#     owner = "iedame";
#     repo = "nixkeeper";
#     tag = "v${finalAttrs.version}";
#     hash = "sha256-...";
#   };
#
# (For the hash: start with `hash = lib.fakeHash;`, build, and copy the real
# one from the error.)
#
# nix comes from the user's PATH, not from here: the package lists evaluate
# with the user's own Nix and its settings. gh is optional (a GitHub token
# from the local login, when there's no other).
{
  lib,
  python3Packages,
  versionCheckHook,
  src,
  version,
}:

python3Packages.buildPythonApplication (finalAttrs: {
  pname = "nixkeeper";
  inherit src version;
  pyproject = true;

  build-system = [ python3Packages.setuptools ];

  dependencies = [ python3Packages.brotli ];

  # The page goes in the Python package (nixkeeper page and nixkeeper serve
  # find it there), and in share/ for anything else that wants it. So do the
  # community rules (community.updateChecks, .ignoredUpdates, .upToDate in the
  # lists).
  preBuild = ''
    cp -r page nixkeeper/page
    mkdir -p nixkeeper/community
    cp community/*.nix nixkeeper/community/
  '';

  postInstall = ''
    mkdir -p $out/share/nixkeeper
    ln -s $out/${python3Packages.python.sitePackages}/nixkeeper/page $out/share/nixkeeper/www
  '';

  # The tests are offline: every source is faked.
  nativeCheckInputs = [
    python3Packages.unittestCheckHook
    versionCheckHook
    # Only for tests/test_versions.py: the port of libversion's algorithm
    # (nixkeeper/versions.py) compared with libversion itself.
    python3Packages.libversion
  ];

  unittestFlagsArray = [
    "-s"
    "tests"
    "-t"
    "."
    "-v"
  ];

  # nixkeeper serve's tests talk to it on 127.0.0.1, which macOS's build
  # sandbox blocks unless asked.
  __darwinAllowLocalNetworking = true;

  pythonImportsCheck = [ "nixkeeper" ];

  meta = {
    description = "Health dashboard for every nixpkgs package";
    longDescription = ''
      nixkeeper tracks the nixpkgs packages you maintain, and any others you
      list, and shows on one static page what needs attention: new releases
      (from Repology and its own update checks), build failures on Hydra,
      nixpkgs-update's failed attempts, open update PRs, and known
      vulnerabilities.
    '';
    homepage = "https://github.com/nixkeeper/nixkeeper";
    changelog = "https://github.com/nixkeeper/nixkeeper/blob/v${finalAttrs.version}/CHANGELOG.md";
    license = lib.licenses.mit;
    maintainers = with lib.maintainers; [ iedame ];
    mainProgram = "nixkeeper";
  };
})
