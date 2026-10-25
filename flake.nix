{
  description = "Health dashboard for every nixpkgs package: new releases, build and update failures, vulnerabilities and open PRs, by maintainer and team";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # Only for checking the darwin module (checks.darwin-module-eval).
    nix-darwin = {
      url = "github:nix-darwin/nix-darwin";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
      treefmt-nix,
      nix-darwin,
    }:
    {
      # services.nixkeeper (nix/module.nix, nix/darwin-module.nix).
      nixosModules.default = import ./nix/module.nix self;
      darwinModules.default = import ./nix/darwin-module.nix self;
    }
    // flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };
        inherit (pkgs) lib;

        # nixkeeper's package (nix/package.nix, in nixpkgs' style), built from
        # this checkout.
        nixkeeper = pkgs.callPackage ./nix/package.nix {
          # One version for both: bump it in pyproject.toml.
          inherit ((lib.importTOML ./pyproject.toml).project) version;
          src = lib.fileset.toSource {
            root = ./.;
            fileset = lib.fileset.unions [
              ./LICENSE # shipped with the package (pyproject.toml: license-files)
              ./pyproject.toml
              ./nixkeeper
              ./tests
              ./page # the page, shipped with the package
              ./community # the community rules, too
              ./docs/data.md # the data's description: tests hold nixkeeper/shape.py to it
            ];
          };
        };

        listsChecker = import ./nix/package-lists.nix {
          pkgs = import nixpkgs {
            inherit system;
            config.allowAliases = false;
          };
        };

        # `nix fmt` formats everything; checks.formatting fails on anything
        # unformatted. Settings for ruff and biome live in pyproject.toml and
        # biome.json, so running the tools directly gives the same result.
        treefmt = treefmt-nix.lib.evalModule pkgs {
          projectRootFile = "flake.nix";
          programs = {
            nixfmt.enable = true;
            # Keeps marked parts of files sorted (between its start and end
            # comments): the package lists and the community rules.
            keep-sorted.enable = true;
            ruff-format.enable = true;
            ruff-check.enable = true; # safe auto-fixes, e.g. import order
            biome = {
              enable = true;
              settings = builtins.fromJSON (builtins.readFile ./biome.json);
            };
          };
          settings.formatter.biome.includes = [
            "page/*.js"
            "page/*.css"
            "tests/js/*.mjs"
          ];
        };

        linters = with pkgs; [
          ruff
          mypy # the row's type (shape.Row), where the verdict is built
          deadnix
          statix
          actionlint
          shellcheck # used by actionlint for the workflows' run: scripts
          biome
        ];

        # `nix run .#<command>`: `nixkeeper <command>` on the checkout's
        # package-lists/ and data/ (the installed command's defaults are the
        # user's own folders). NIXKEEPER_LISTS / NIXKEEPER_DATA_DIR, or flags
        # after `--`, still choose others.
        command = name: description: {
          type = "app";
          program = lib.getExe (
            pkgs.writeShellScriptBin "nixkeeper-${name}" ''
              checkout=()
              [ -n "''${NIXKEEPER_LISTS:-}" ] || checkout+=(--lists package-lists)
              [ -n "''${NIXKEEPER_DATA_DIR:-}" ] || checkout+=(--data-dir data)
              exec ${lib.getExe nixkeeper} ${name} "''${checkout[@]}" "$@"
            ''
          );
          meta = { inherit description; };
        };
        sync = command "sync" "Sync data/: Repology, update checks, Hydra, nixpkgs-update logs, GitHub";
        # The hourly updates (.github/workflows/data-hourly.yml), against data/.
        frequent-check = command "frequent-check" "Run the frequent update checks (frequent = true) against data/";
        # Runs the community update checks for real (-- NAME... for some).
        community-check = command "community-check" "Run the community update checks for real (-- NAME ... to test some)";
        pr-check = command "pr-check" "Look for outdated packages' update PRs, open and merged, against data/";
        # The wordmark's typeface, Oxanium (SIL Open Font License), from the
        # google/fonts commit this nixpkgs' google-fonts uses: just the one file,
        # not the whole collection.
        oxanium = pkgs.fetchurl {
          name = "oxanium.ttf";
          url = "https://raw.githubusercontent.com/google/fonts/5174b3333331c966c38f4355d50b03ca1c1df2f9/ofl/oxanium/Oxanium%5Bwght%5D.ttf";
          hash = "sha256-LOAdlG4eH/yNfuz/+9qGI77dY+r4EaIEiMS2mvRbq7A=";
        };
        # The brand files page/ has as copies of assets/brand/'s, as globs: the
        # brand app copies them, checks.brand holds each copy to its source.
        brandCopies = [
          "favicon*.svg"
          "nixkeeper-lockup-tight*.svg"
          "tokens.css"
        ];
        isBrandCopy =
          name:
          lib.any (
            glob: builtins.match (lib.replaceStrings [ "." "*" ] [ "\\." ".*" ] glob) name != null
          ) brandCopies;

        # Regenerates the brand assets in assets/brand/ (scripts/brand/): the
        # mark's SVGs, the lockups with the wordmark outlined, the colour
        # tokens, the identity sheet, and the page's copies of the favicons,
        # the header's lockups and the tokens (only page/ is published).
        brand = {
          type = "app";
          program = lib.getExe (
            pkgs.writeShellApplication {
              name = "nixkeeper-brand";
              runtimeInputs = [ (pkgs.python3.withPackages (ps: [ ps.uharfbuzz ])) ];
              text = ''
                [ -f flake.nix ] && [ -d assets/brand ] || {
                  echo "Run this from the repository's root." >&2
                  exit 1
                }
                python3 scripts/brand/generate.py assets/brand ${oxanium}
                python3 scripts/brand/tokens.py assets/brand
                python3 scripts/brand/identity.py assets/brand
                cd assets/brand
                for f in ${lib.concatStringsSep " " brandCopies}; do
                  cp "$f" ../../page/
                done
              '';
            }
          );
          meta.description = "Regenerate the brand assets in assets/brand/, and the page's favicon and colour tokens";
        };
        # Retakes the page's screenshots in assets/screenshots/ (scripts/screenshots.sh),
        # with the browser named by --browser: a path, or a package from this
        # nixpkgs, fetched only then.
        screenshots = {
          type = "app";
          program = lib.getExe (
            pkgs.writeShellApplication {
              name = "nixkeeper-screenshots";
              runtimeInputs = with pkgs; [
                python3
                pngquant
                imagemagick
                git
                procps
                coreutils
                gnused
              ];
              runtimeEnv.NIXPKGS = "${nixpkgs}";
              text = builtins.readFile ./scripts/screenshots.sh;
            }
          );
          meta.description = "Retake the page's screenshots in assets/screenshots/ (-- --browser <name or path>; --help for the options)";
        };
        # Starts an instance's runs through GitHub's API, hourly
        # from a machine that's always on (scripts/start-runs.sh; the
        # nix-darwin agent and NixOS timer in docs/all-packages.md).
        start-runs = pkgs.writeShellApplication {
          name = "nixkeeper-start-runs";
          runtimeInputs = with pkgs; [
            curl
            coreutils
          ];
          text = builtins.readFile ./scripts/start-runs.sh;
        };
      in
      {
        packages = {
          default = nixkeeper;
          inherit start-runs;
        };

        apps = {
          inherit
            sync
            frequent-check
            pr-check
            community-check
            screenshots
            brand
            ;
          start-runs = {
            type = "app";
            program = lib.getExe start-runs;
            meta.description = "Start the community instance's runs through GitHub's API (-- --dry-run to see which)";
          };
          fetch = sync; # old name, kept as an alias
          quick-check = frequent-check; # old name, kept as an alias
          # `nix run github:nixkeeper/nixkeeper -- <command>`: the command as
          # installed, on your own folders.
          default = {
            type = "app";
            program = lib.getExe nixkeeper;
            meta.description = "The nixkeeper command (sync, init, paths, ...), on your own folders";
          };
        };

        formatter = treefmt.config.build.wrapper;

        checks = {
          inherit nixkeeper; # building it runs the tests
          # The darwin module, evaluated in a whole nix-darwin configuration
          # (on any system, as module-eval below): the agents' launchd plists and
          # the shell environment.
          darwin-module-eval =
            let
              darwin = nix-darwin.lib.darwinSystem {
                system = "aarch64-darwin";
                modules = [
                  self.darwinModules.default
                  {
                    system.stateVersion = 6;
                    system.primaryUser = "someone";
                    services.nixkeeper = {
                      enable = true;
                      lists.maintainers = [ "iedame" ];
                      githubTokenFile = "/Users/someone/.config/nixkeeper/github-token";
                      serve.enable = true;
                    };
                  }
                ];
              };
              agents = lib.mapAttrs (_: agent: agent.serviceConfig) (
                lib.filterAttrs (name: _: lib.hasPrefix "nixkeeper-" name) darwin.config.launchd.user.agents
              );
              # What shells get, so commands typed by hand use the same lists.
              shell = lib.filterAttrs (
                name: _: lib.hasPrefix "NIXKEEPER_" name
              ) darwin.config.environment.variables;
            in
            assert shell ? NIXKEEPER_LISTS;
            pkgs.writeText "nixkeeper-darwin-module-eval" (
              builtins.unsafeDiscardStringContext (
                builtins.seq darwin.system.drvPath (builtins.toJSON { inherit agents shell; })
              )
            );
          # The NixOS module, evaluated in a whole NixOS configuration (on any
          # system: nothing is built, so this runs on macOS too).
          module-eval =
            let
              nixos = nixpkgs.lib.nixosSystem {
                system = "x86_64-linux";
                modules = [
                  self.nixosModules.default
                  {
                    boot.isContainer = true;
                    system.stateVersion = lib.trivial.release;
                    services.nixkeeper = {
                      enable = true;
                      lists.maintainers = [ "iedame" ];
                      githubTokenFile = "/run/secrets/github-token";
                      notify = "github-issue";
                      githubRepo = "nixkeeper/nixkeeper";
                      nginx.virtualHost = "nixkeeper.example.org";
                    };
                  }
                ];
              };
              unit = nixos.config.systemd.units."nixkeeper-sync.service".text;
            in
            # The text only: its store paths are Linux builds, not this system's.
            pkgs.writeText "nixkeeper-module-eval" (
              builtins.unsafeDiscardStringContext (builtins.seq nixos.config.system.build.toplevel.drvPath unit)
            );
          formatting = treefmt.config.build.check self;
          lint = pkgs.runCommand "nixkeeper-lint" { nativeBuildInputs = linters; } ''
            cd ${self}
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
          '';
          # The scripts' own logic (tests/sh/), for now the Cloudflare deploy's
          # retry, against a fake wrangler.
          scripts = pkgs.runCommand "nixkeeper-script-tests" { nativeBuildInputs = [ pkgs.git ]; } ''
            cd ${self}
            export HOME=$TMPDIR
            bash tests/sh/cloudflare.sh
            touch $out
          '';
          # page/'s brand files match assets/brand/, and assets/brand/'s tokens
          # match what tokens.py writes.
          brand =
            let
              copies = lib.concatStringsSep " " brandCopies;
              src = lib.fileset.toSource {
                root = ./.;
                fileset = lib.fileset.unions [
                  ./scripts/brand/tokens.py
                  ./scripts/brand/geometry.py
                  ./assets/brand/tokens.json
                  (lib.fileset.fileFilter (f: isBrandCopy f.name) ./assets/brand)
                  (lib.fileset.fileFilter (f: isBrandCopy f.name) ./page)
                ];
              };
            in
            pkgs.runCommand "nixkeeper-brand-check" { nativeBuildInputs = [ pkgs.python3 ]; } ''
              drift() {
                echo "$1: $2" >&2
                exit 1
              }
              cd ${src}
              PYTHONDONTWRITEBYTECODE=1 python3 scripts/brand/tokens.py "$TMPDIR/tokens" > /dev/null
              for f in tokens.css tokens.json; do
                cmp -s "$TMPDIR/tokens/$f" "assets/brand/$f" ||
                  drift "assets/brand/$f" "differs from what scripts/brand/tokens.py writes: edit that, then run nix run .#brand"
              done
              cd ${src}/assets/brand
              for f in ${copies}; do
                cmp -s "$f" "../../page/$f" ||
                  drift "page/$f" "differs from assets/brand/$f: run nix run .#brand"
              done
              cd ${src}/page
              for f in ${copies}; do
                [ -e "../assets/brand/$f" ] ||
                  drift "page/$f" "has no source in assets/brand/: remove it"
              done
              touch $out
            '';
          # The page's rules (page/logic.js), with Node's own test runner.
          page = pkgs.runCommand "nixkeeper-page-tests" { nativeBuildInputs = [ pkgs.nodejs-slim ]; } ''
            cd ${self}
            node --test 'tests/js/*.test.mjs'
            touch $out
          '';
          package-lists = listsChecker.check (import ./package-lists);
          # notifications/: well formed, for handles and teams nixpkgs has.
          notifications = (import ./nix/notifications.nix { inherit pkgs; }).check (import ./notifications);
          # The community rules (community/): well formed, for packages in
          # nixpkgs; the update checks also within the limits they're held to,
          # with patterns Python compiles (nixkeeper/community.py).
          community =
            let
              rules = import ./community/update-checks.nix;
              found =
                map (p: p // { entry = "update-checks.nix: ${p.entry}"; }) (listsChecker.communityProblems rules)
                ++ map (p: p // { entry = "ignored-updates.nix: ${p.entry}"; }) (
                  listsChecker.communityIgnoreProblems (import ./community/ignored-updates.nix)
                )
                ++ map (p: p // { entry = "up-to-date.nix: ${p.entry}"; }) (
                  listsChecker.communityUpToDateProblems (import ./community/up-to-date.nix)
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
                '';
          # nixkeeper init's starter lists: valid, and what the sync can read.
          init-template = listsChecker.check (import ./nixkeeper/templates/package-lists);
          # The checker itself, against lists with known problems.
          package-lists-checker =
            let
              found = map (p: p.entry) (
                listsChecker.problems {
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
                }
              );
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
              # Named lists: on two lists is fine, twice in one isn't, and
              # "maintained" is taken.
              foundNamed = map (p: p.entry) (
                listsChecker.problems {
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
                }
              );
              expectedNamed = [
                "freedink"
                "extraPackages.maintained"
              ];
            in
            assert lib.assertMsg (found == expected) "package-lists checker found ${builtins.toJSON found}";
            # A set of packages says what's wrong (it passed this check before, and
            # the sync found nothing: nixkeeper/nixkeeper's cataclysmDDA).
            assert lib.assertMsg (
              (lib.findFirst (p: p.entry == "cataclysmDDA") { } (
                listsChecker.problems {
                  maintainers = [ ];
                  extraPackages = [ "cataclysmDDA" ];
                }
              )).reason or ""
              == "a set of packages, not a package: list the one you mean (its attribute or pname)"
            ) "package-lists checker: a set of packages should say so";
            assert lib.assertMsg (
              foundNamed == expectedNamed
            ) "package-lists checker found ${builtins.toJSON foundNamed} (named lists)";
            pkgs.runCommand "package-lists-checker-ok" { } "touch $out";
        }
        // lib.optionalAttrs pkgs.stdenv.hostPlatform.isLinux {
          # The module in a NixOS VM (needs KVM: CI has it).
          module = import ./nix/module-test.nix { inherit pkgs self; };
        };

        devShells.default = pkgs.mkShell {
          packages = [
            # libversion: for the tests only (tests/test_versions.py).
            (pkgs.python3.withPackages (ps: [
              ps.brotli
              ps.libversion
            ]))
            pkgs.nodejs-slim # the page's tests (tests/js/)
            treefmt.config.build.wrapper
          ]
          ++ linters;
        };
      }
    );
}
