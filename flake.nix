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
              # Without the plugins: they're for checks.lint's biome lint, and
              # their paths don't resolve from the config treefmt writes.
              settings = removeAttrs (builtins.fromJSON (builtins.readFile ./biome.json)) [ "plugins" ];
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
        # A check's source: only the files it reads, so an edit elsewhere (the
        # README, a screenshot) doesn't run it again.
        checkSource =
          files:
          lib.fileset.toSource {
            root = ./.;
            fileset = lib.fileset.unions files;
          };

        # A check in nix/checks/, given what every check may use and what it
        # needs besides. Each takes ... for the shared ones it doesn't use, so a
        # mistyped extra is ignored there, not refused: check the names.
        callCheck =
          path: extra:
          import path (
            {
              inherit
                pkgs
                lib
                self
                checkSource
                ;
            }
            // extra
          );

        # The brand files page/ has as copies of assets/brand/'s, as globs: the
        # brand app copies them, checks.brand holds each copy to its source.
        brandCopies = [
          "favicon*.svg"
          "nixkeeper-lockup-tight*.svg"
          "tokens.css"
        ];
        # The same files, for a fileset: keep it in step with brandCopies.
        isBrandCopy =
          name:
          (lib.hasPrefix "favicon" name && lib.hasSuffix ".svg" name)
          || (lib.hasPrefix "nixkeeper-lockup-tight" name && lib.hasSuffix ".svg" name)
          || name == "tokens.css";

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
          formatting = treefmt.config.build.check self;
          # The code: linters, the scripts' and the page's tests, the brand files.
          lint = callCheck ./nix/checks/lint.nix { inherit linters; };
          scripts = callCheck ./nix/checks/scripts.nix { };
          page = callCheck ./nix/checks/page.nix { };
          brand = callCheck ./nix/checks/brand.nix { inherit brandCopies isBrandCopy; };
          # The modules, evaluated.
          module-eval = callCheck ./nix/checks/module-eval.nix { nixpkgsInput = nixpkgs; };
          darwin-module-eval = callCheck ./nix/checks/darwin-module-eval.nix { inherit nix-darwin; };
          # The lists: this instance's, nixkeeper init's starter ones (valid, and
          # what the sync can read), notifications/ (handles and teams nixpkgs
          # has), the community's, and the lists' checker itself.
          package-lists = listsChecker.check (import ./package-lists);
          init-template = listsChecker.check (import ./nixkeeper/templates/package-lists);
          notifications = (import ./nix/notifications.nix { inherit pkgs; }).check (import ./notifications);
          community = callCheck ./nix/checks/community.nix { inherit listsChecker nixkeeper; };
          package-lists-checker = callCheck ./nix/checks/package-lists-checker.nix {
            inherit listsChecker;
          };
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
