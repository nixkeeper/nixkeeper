# The darwin module, evaluated in a whole nix-darwin configuration
# (on any system, as module-eval.nix does the NixOS one): the agents' launchd
# plists and the shell environment.
{
  pkgs,
  lib,
  self,
  nix-darwin,
  ...
}:
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
)
