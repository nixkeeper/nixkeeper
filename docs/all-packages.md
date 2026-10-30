# Every package

nixkeeper normally tracks the packages your lists name. It can also track
**every package in nixpkgs**, for a community instance anyone can look up
their packages on (`?maintainer=handle`, `?team=`): about 150,000 attributes, in
about 120,000 rows (the attributes of one Repology project share a row,
like python313Packages.requests and python314Packages.requests).

Turn it on for one instance only:

- on GitHub: the repository variable `NIXKEEPER_ALL_PACKAGES` set to `1`
  (Settings → Secrets and variables → Actions → Variables). A variable,
  not a setting in `package-lists/`: forks copy those files, and a fork
  that only changes `maintainers` shouldn't start tracking all of nixpkgs;
- with the NixOS or nix-darwin module: `services.nixkeeper.allPackages = true`;
- with the command: `nixkeeper sync --all-packages`, or
  `NIXKEEPER_ALL_PACKAGES=1`.

## What each package gets

Your lists still count: their packages are read as always (every source,
looked up one by one when the bulk sources can't answer), and only they are
in the status issue. The rest of nixpkgs is read in bulk only, with nothing
asked package by package:

| Source | Packages not on the lists |
|---|---|
| Repology | from [nixkeeper-versions](https://github.com/nixkeeper/digest-versions)' digest, as it has them; a package it doesn't have is "unlisted" (nixpkgs' version, nothing to compare it with) |
| Hydra | from [nixkeeper-hydra](https://github.com/nixkeeper/digest-builds)'s digest; a queued job keeps its last result |
| `meta.broken` | the package index's (x86_64-linux), not evaluated per platform |
| Update checks | your own and the community's rules; none worked out from nixpkgs |
| nixpkgs-update | from [nixkeeper-updates](https://github.com/nixkeeper/digest-update-bot)' digest, its last read attempt; a package whose attempts it hasn't read yet says so (`unread`). Without the digest, not read (about 4,000 packages' logs change a day, more than a sync can read politely) |
| GitHub | PR and issue counts and update PRs from the bulk listings only |

Packages of **sets updated in bulk** (rPackages, haskellPackages,
emacsPackages, typstPackages, texlivePackages, sbclPackages,
chickenPackages_5 and _6, akkuPackages, gnomeExtensions,
azure-cli-extensions: their own
tooling generates them from CRAN, Hackage and so on, and keeps them current
as a whole, not one PR per package) have Repology's versions, Hydra's
builds and nixpkgs-update's attempts where it makes any (some TeX Live and
Emacs packages), but no GitHub counts, and each says what updates it
(`SET_PROFILES` in `config.py`). They're counted on their set's line on the
overview, not in "needs attention" or the cards: an R package behind CRAN
waits for the next CRAN import, which no one PR does. Packages of `darwin`
and `freebsd` aren't versioned software: they say so, and their builds are
what's checked.

Typst packages are compared with [Typst Universe](https://typst.app/universe/),
their source (nixkeeper-versions reads its index daily), instead of
Repology, which mostly can't compare them: each package's latest attribute
(`typstPackages.cetz`) against Universe's newest version, its versioned
ones (`typstPackages.cetz_0_3_0`) as older versions kept. Emacs packages
likewise, with the archive nixpkgs takes each from (MELPA, whose versions
are a build's date, MELPA Stable, NonGNU ELPA or GNU ELPA; nixpkgs'
hand-written ones keep Repology's verdict). Haskell packages nixpkgs pins
to Stackage LTS (`stackage.yaml`, about 3,400) are compared with that
series' newest snapshot, not Hackage's newest, which Stackage holds back
until its next series: those at it show a "Stackage LTS" badge instead of
outdated. R packages are compared with CRAN, or the Bioconductor release
nixpkgs pins; those on neither any more show "archived" (nixpkgs marks
most of them broken already; R's card counts those it doesn't). CHICKEN
eggs, Akku packages, GNOME Shell extensions and Azure CLI extensions are
compared with the index each set is generated from: CHICKEN's egg index,
Akku's, extensions.gnome.org (the newest version for the GNOME Shells
nixpkgs merges into `gnomeExtensions`) and the Azure CLI's extension index
(the newest version nixpkgs' `azure-cli` runs).

## The page

It starts from an overview of all of nixpkgs: the fully checked packages'
outdated, failing, vulnerable and broken counts with their trends (from
`history.json`, a point a day: the day's last sync's), a search (and every maintainer, by
handle), the newest and longest-standing failures, what was fixed in the
last week, and the sets updated in bulk. Each opens a list: what needs
attention, a maintainer's packages (`?maintainer=handle`), a team's, a
set's, or one package (`?pkg=`); visitors can keep their own handle and
team, in their browser. See [reading the page](reading-the-page.md).

## Starting the runs on time

GitHub runs scheduled workflows on a best-effort basis and skips runs when
it's busy: some days the hourly digests ran a handful of times. Any machine
that stays on can start them on time instead, through GitHub's API:
`nix run .#start-runs`, hourly at :15 UTC, starts the hourly updates every
hour (the sync instead every 3 hours, at 00, 03, 06... UTC, which syncs
when it's due by the instance's interval) and each digest's run when it's due
([scripts/start-runs.sh](../scripts/start-runs.sh) lists when; `-- --dry-run`
shows what it would start now, without starting anything). The workflows
keep their own schedules as a fallback: a run started twice finds nothing
new, or stops at once. A start GitHub answers with a server error, or
doesn't answer, is tried again after 1 minute and then 3.

Then set the repository variable `NIXKEEPER_STARTED_OUTSIDE` to `true`
(Settings → Secrets and variables → Actions → Variables): the sync's own
schedule becomes only the fallback, syncing when the last sync is over the
interval and half an hour old (a start was missed). Without it, GitHub's
scheduled runs, which often come hours late, sync whenever the last sync is
due, and the next start finds nothing to do: syncs at GitHub's times
instead of yours.

It needs a [fine-grained token](https://github.com/settings/personal-access-tokens/new)
for the repositories it starts runs in, with only **Actions: read and
write**: it can start and cancel runs, nothing else.

### Whose runs

By default it starts the community instance's: its hourly updates and
sync, the digests (in the `nixkeeper` organisation: digest-builds,
-update-bot, -versions, -vulnerabilities and -prs), and
[status](https://github.com/nixkeeper/status)' hourly check of all of them.
Elsewhere, two variables say which:

- `NIXKEEPER_START_REPO`: your nixkeeper repository (`you/nixkeeper`),
  whose hourly updates and sync it starts; empty for none.
- `NIXKEEPER_START_DIGESTS`: the owner of the digest repositories whose
  runs it starts; empty for none. A fork reads the community instance's
  digests (unless you point `NIXKEEPER_*_DIGEST` at your own), which it
  keeps running: leave them out.

So for a fork, `NIXKEEPER_START_REPO=you/nixkeeper` and
`NIXKEEPER_START_DIGESTS=` (empty), with a token for your nixkeeper
repository only. Your fork's sync workflow starts every 3 hours on its own
too, and syncs once a day is due (or every `NIXKEEPER_SYNC_HOURS`, a
repository variable), so a skipped run is caught up within 3 hours: this
is optional for a fork.

### On macOS, with nix-darwin

Keep the token in the Keychain (this asks for it):

```bash
security add-generic-password -a "$USER" -s nixkeeper-start-runs -w
```

and run it as a launchd agent, with nixkeeper as a flake input:

```nix
launchd.user.agents.nixkeeper-start-runs.serviceConfig = {
  ProgramArguments = [
    (lib.getExe inputs.nixkeeper.packages.${pkgs.stdenv.hostPlatform.system}.start-runs)
  ];
  # For a fork (see above):
  # EnvironmentVariables = {
  #   NIXKEEPER_START_REPO = "you/nixkeeper";
  #   NIXKEEPER_START_DIGESTS = "";
  # };
  StartCalendarInterval = [ { Minute = 15; } ]; # hourly, at :15
  StandardOutPath = "/Users/you/Library/Logs/nixkeeper-start-runs.log";
  StandardErrorPath = "/Users/you/Library/Logs/nixkeeper-start-runs.log";
};
```

A user agent runs while that user is logged in (the Keychain is theirs).
launchd's minute is the Mac's local time: in a time zone with a
half-hour offset, choose the minute that's :15 in UTC (45 for UTC+5:30).

### On Linux, with NixOS

Keep the token in a file only root can read (say
`/etc/nixkeeper/start-runs-token`, mode 600), and run it from a systemd
timer, with nixkeeper as a flake input. systemd hands the token to the
service as a credential, so the service runs as a throwaway user that
can read nothing else:

```nix
systemd.services.nixkeeper-start-runs = {
  serviceConfig = {
    Type = "oneshot";
    DynamicUser = true;
    LoadCredential = "token:/etc/nixkeeper/start-runs-token";
    ExecStart = lib.getExe inputs.nixkeeper.packages.${pkgs.stdenv.hostPlatform.system}.start-runs;
  };
  # For a fork (see above):
  # environment = {
  #   NIXKEEPER_START_REPO = "you/nixkeeper";
  #   NIXKEEPER_START_DIGESTS = "";
  # };
};
systemd.timers.nixkeeper-start-runs = {
  wantedBy = [ "timers.target" ];
  timerConfig.OnCalendar = "*-*-* *:15:00 UTC"; # hourly, at :15 UTC
};
```

Its output is in the journal (`journalctl -u nixkeeper-start-runs`).

### Elsewhere

Any scheduler that runs `nixkeeper-start-runs` hourly at :15 UTC will do
(cron, say), with the token in a file named by
`NIXKEEPER_START_TOKEN_FILE`.

## Serving it from Cloudflare

GitHub Pages serves the page, and the page reads its data from
raw.githubusercontent.com, which isn't meant for heavy traffic. The
community instance is served from Cloudflare instead, at
https://nixkeeper.com/: the page and its data as one site, a
[Worker](https://developers.cloudflare.com/workers/static-assets/) serving
only static assets, from Cloudflare's edge (about 5,300 files and 335 MB,
within its free plan's 20,000 files and 25 MiB a file). The data workflows
publish there after they publish the data branch, which stays the syncs'
own copy ([scripts/cloudflare.sh](../scripts/cloudflare.sh)), and only when
the page or the data changed: a page change goes out with the next hourly
run. Cloudflare doesn't build anything or read the repository; the
workflows upload what they made. A failed deploy is tried again (3
attempts, 30 s apart) before the run fails.

To do the same for an instance:

1. In Cloudflare, create a Worker (Workers & Pages → Create → Worker,
   starting from the "Hello World" one; a name, say `nixkeeper`: the first
   publish replaces what it serves), and give it your domain (its Settings
   → Domains & Routes → Add → Custom domain; the domain's DNS has to be on
   Cloudflare).
2. Create an API token with only **Account → Workers Scripts → Edit**.
3. In the repository's Settings → Secrets and variables → Actions: the
   secrets `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` (in
   Cloudflare's dashboard, beside your account), and the variables
   `CLOUDFLARE_WORKER` (the Worker's name) and `CLOUDFLARE_SITE_URL`
   (`https://` and your domain). Without the Worker variable nothing is
   published there. A variable's value shows in the workflows' logs, public
   for a public repository: the account ID is a secret to keep it out.
   The Worker is served on your domain only: the workflow turns off its
   `workers.dev` address (named after your account's subdomain, at first
   your email address's) and preview addresses, so none is printed in the
   logs, and the account needs no `workers.dev` subdomain.
4. Run "Data: hourly updates" once: it publishes the page and data (the
   first time takes a few minutes, uploading every file; after that, only
   the files that changed).
5. Run "Pages: publish the page" once: with `CLOUDFLARE_SITE_URL` set,
   your `<owner>.github.io` address no longer serves the page but sends
   visitors to your site, with their search and filters (`?q=`,
   `?view=`, ...), so links to it keep working. From then on pushes don't
   run it (the page reaches your site with the data runs); run it by hand
   again only if `scripts/pages-redirect.sh` changes.

## What it costs

No requests beyond the bulk ones a list-based instance makes. The data is a few hundred MB (about 30 MB gzipped),
written as [views](data.md#every-package) the page starts from instead of
one summary of every package. The sync holds every row at once: a few GB
of memory.
