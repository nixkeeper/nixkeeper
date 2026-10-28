# nixkeeper on NixOS

The flake's NixOS module runs it all on a server: the sync daily, the
frequent and update PR checks hourly, the data in `/var/lib/nixkeeper/data`,
and optionally the page on nginx.

```nix
{
  inputs.nixkeeper.url = "github:nixkeeper/nixkeeper";

  outputs = { nixpkgs, nixkeeper, ... }: {
    nixosConfigurations.server = nixpkgs.lib.nixosSystem {
      modules = [
        ./configuration.nix # your server's own configuration
        nixkeeper.nixosModules.default
        {
          services.nixkeeper = {
            enable = true;
            lists.maintainers = [ "your-github-handle" ];
            lists.extraPackages.extra = [ "firefox" ];
            # A token file, read only; never a path inside the Nix store.
            githubTokenFile = "/run/secrets/nixkeeper-github-token";
            nginx.virtualHost = "nixkeeper.example.org";
          };
          # TLS and the rest as for any nginx host:
          services.nginx.virtualHosts."nixkeeper.example.org" = {
            enableACME = true;
            forceSSL = true;
          };
        }
      ];
    };
  };
}
```

| Option | Default | What it sets |
|---|---|---|
| `lists` | – (this or `listsPath`) | what to track, as `package-lists/` has it (`maintainers`, `extraPackages`, `updateChecks`, `ignoredUpdates`, `upToDate`) |
| `listsPath` | – | a `package-lists/` folder or JSON file instead (a folder is evaluated with the system's Nix) |
| `lists.community.updateChecks`, `.ignoredUpdates`, `.upToDate` | `false`, `false`, `false` | also use the [community rules](community.md) for the packages you track |
| `lists.workedOutChecks` | `true` | check packages without an update check of their own against the repository nixpkgs fetches them from: on GitHub, a GitLab instance or Codeberg ([how it works](how-it-works.md)) |
| `lists.maxPackages` | `5000` | the most packages a sync may track: above it, the sync refuses to start ([how much it tracks](how-it-works.md#how-much-it-tracks)) |
| `lists.page.theme` | `"classic"` | the page's colours for visitors who haven't picked any: `"classic"` or `"catppuccin"` |
| `syncAt` | `"06:00"` | when the sync runs (systemd `OnCalendar`) |
| `frequentChecks.enable`, `.at` | `true`, `"hourly"` | the frequent update checks and the update PR check |
| `githubTokenFile` | – | a GitHub token, passed as a systemd credential; without it, PR and issue counts and update PRs are skipped |
| `notify`, `githubRepo`, `pageUrl` | `"none"` | `"github-issue"` keeps a status issue in `githubRepo` up to date |
| `contact` | – | how you can be reached (an email or a URL), added to the User-Agent sent to the sources ([the command](command.md)) |
| `allPackages` | `false` | track every nixpkgs package, not only the lists' ([every package](all-packages.md)) |
| `nginx.virtualHost` | – | serve the page and the data on this nginx host |
| `package` | this flake's | the nixkeeper package to run |

The jobs run as their own `nixkeeper` user, hardened (read-only system, no
home, no privileges). Like any nixkeeper commands on the same data, they run
one at a time: each holds a lock (`data.lock`, next to the data) and the next
waits for it.

**The first sync** runs within a few minutes of enabling the module: at
boot, and when the module is first switched on, a catch-up job
(`nixkeeper-catch-up`) syncs if there's no data yet or the last sync is over
20 hours old, which also makes up for a day missed while the machine was
down. After that, the daily sync and the hourly checks run on their own. To
sync right away, or just in case one didn't run:

```bash
sudo systemctl start nixkeeper-sync
```

```bash
journalctl -u nixkeeper-sync -u nixkeeper-catch-up -f
```

To pin a version rather than follow `main`, see
[pinning a version](command.md#pinning-a-version). When something doesn't
run: [troubleshooting](troubleshooting.md#on-nixos).
