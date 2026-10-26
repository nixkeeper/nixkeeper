# The NixOS module, evaluated in a whole NixOS configuration (on any
# system: nothing is built, so this runs on macOS too).
{
  pkgs,
  lib,
  self,
  nixpkgsInput, # the flake input, for its lib.nixosSystem
  ...
}:
let
  nixos = nixpkgsInput.lib.nixosSystem {
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
)
