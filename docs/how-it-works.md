# How it works

The diagram in the [README](../README.md#how-it-works) shows the parts; here
is what each does.

There's no server: nixkeeper is a program that gathers data, and a static
page that shows it.

- **The sync** (`nix run .#sync`, run by the "Data: sync" workflow, which
  starts every 3 hours and syncs when the last sync is due: every 3 hours on
  the community instance, nixkeeper.com, whose digests refresh hourly;
  daily on a fork, unless its `NIXKEEPER_SYNC_HOURS` variable says
  otherwise)
  works out which packages to track from `package-lists/` and the
  nixos-unstable channel's package index, then asks each source about them:
  Repology for versions, nixkeeper's own update checks, Hydra for builds
  (and nixpkgs for where it marks them broken), the nixpkgs-update logs for
  the bot's latest attempt, and GitHub for open PRs, issues and update PRs.
  It writes everything as JSON to the `data` branch ([data.md](data.md)) and
  rewrites the status issues (the instance's own, unless its lists turn it
  off, and one per maintainer or team in `notifications/`:
  [notifications.md](notifications.md)), commenting when something newly
  needs attention.
- **The hourly checks** ("Data: hourly updates") refresh a few rows of the
  last published data: the update checks marked `frequent` (browsers, for
  their security fixes) and outdated packages' update PRs: every outdated
  package's from nixkeeper-prs' digest (one download, made hourly), and the
  lists' maintainers' packages (the "maintained" list) searched for
  directly too, for the freshest "on master"; the other lists and teams
  only through the digest, so they can grow without the searches growing
  (without a usable digest, searched per package as before). They commit
  only when something changed. GitHub runs scheduled workflows on a best-effort
  basis, so "hourly" can stretch to a few hours when Actions is busy; the
  sync still covers everything. Asking per package doesn't grow with the
  syncs: what's quiet is asked every 3 days, what has something going on
  daily, whatever the interval.
- **The page** (`page/`, published to GitHub Pages by a workflow) is plain
  HTML and JavaScript that reads the JSON in your browser.

When a source can't be reached, the row keeps its last known result, marked
as not refreshed, and the status issue says so; the rest of the sync goes
on. nixkeeper asks each source one thing at a time, with a pause between
requests (update checks' pages: one a second per site, taking turns between
sites), and when a source says to slow down (a `Retry-After`), it waits as
long as asked, up to 5 minutes, before trying again. Hydra's builds come
first from [nixkeeper-hydra](https://github.com/nixkeeper/digest-builds), a
digest of every job in Hydra's newest evaluation of master that its own
workflow keeps up to date hourly: one download answers most jobs, every day.
The digest is used when it's from Hydra's newest evaluation, or was read in
the last 12 hours; otherwise (or when it can't be downloaded) Hydra is asked
about each job, as it is for the jobs the digest can't answer: missing from
it, not built yet, or failing with no known last success. Asked that way,
Hydra is the slowest source (a request or more per package and platform):
it's asked in the background while the other sources are, and the sync takes
about as long as Hydra rather than all of them in turn; each server still
gets one request at a time. It's also asked less about what's quiet: a job
that built fine, for a package that's up to date with nothing changed or
pending, is asked every 3 days (a third of them each day) instead of daily,
so a new build failure there can show up to 3 days late; anything failing,
outdated or with an update PR is asked daily, and what changed (a new
version in nixpkgs, a new package) at once. "Daily" and "every 3 days"
count time, not syncs: a sync run several times a day asks no more often.
Likewise nixpkgs is evaluated (`meta.broken`, sources, patches) only for
a commit, or packages, it hasn't evaluated yet. The builds
panel says when they were last checked. The same goes for update checks that
found nothing newer, unless they're marked `frequent`; and for Repology: a
package that's up to date, not flagged vulnerable and unchanged in nixpkgs
is looked up every 3 days, so its new releases can show up to 3 days late
(most packages are updated by nixpkgs-update, which comes round about every
ten days anyway). Most packages don't need Repology asked at all, though:
their projects come from
[nixkeeper-versions](https://github.com/nixkeeper/digest-versions), a digest
of every nixpkgs project that its own workflow reads in bulk daily, the way
nixpkgs-update reads Repology (outdated projects every day, the rest every
week). Repology is still asked about a package that isn't in the digest (new
in nixpkgs) or has another version there than the channel's (changed since),
and about every package, as above, when the digest is more than 36 hours old
or can't be read; an old digest still answers for the packages Repology
can't (when it's down, its digest's run couldn't read it either). Repology
itself reads nixos-unstable some hours after it moves, so where the channel
already has a newer version than Repology's, the version shown is the
channel's, and whether it's outdated is worked out again against the newest
version Repology shows elsewhere. nixpkgs-update's attempts likewise come from
[nixkeeper-updates](https://github.com/nixkeeper/digest-update-bot), a digest
of the bot's latest attempt at every package, its log read with nixkeeper's
own rules, made every 3 hours from the bot's state; a package's logs are
still read when the digest hasn't read its latest attempt yet, or is more
than 12 hours old. What's vulnerable comes from
[nixkeeper-vulnerabilities](https://github.com/nixkeeper/digest-vulnerabilities),
a digest of the NixOS security tracker (the CVEs it matched to nixpkgs
packages, triaged by the security team, with their status on master and
the release branches) and of OSV's advisories for language packages: a
CVE counts when nixpkgs' current version is in its affected range (the
check the tracker makes, but on today's version: the tracker's own status
is from when it last evaluated the package, often before a fix; it's used
only for ranges nixkeeper can't read), unless nixpkgs carries a patch
named after it (its `patches`, evaluated for those packages: many CVEs are
fixed that way, without a new version); a fix on unstable is to backport
when the newest release's channel (nixos-26.05, its package index) is
still in the range and has no such patch; besides those, nixpkgs' own insecure mark and
Repology's flag still count. The
digest is used once it has read the tracker through, while under 3 days
old. GitHub's open PRs and issues aren't searched package by
package: they come from
[nixkeeper-prs](https://github.com/nixkeeper/digest-prs), a digest of
every open PR and issue of nixpkgs and the PRs merged into master since the
channel's commit, made hourly, and each package's counts and update PRs are
found in their titles, every package daily. When the digest is over 6
hours old, or its merged PRs were listed since another channel commit,
the sync lists them itself (about 120 requests for the open ones, about
10 for the merged), and searches per package only when that fails too. nixkeeper doesn't ask
twice for what can't have changed: a package's Repology project is the one
the last sync found, a package whose bot logs haven't changed since (the log
site's index says when each last changed) isn't listed again, a release page
whose server says it hasn't changed isn't downloaded again, and a log
already read (the bot tries each package about every ten days) is taken from
the previous sync instead of downloaded again.

## How much it tracks

Most of a sync's cost is the same whatever the lists' size: the package
index, the digests of Hydra's builds and Repology's data, and the listings
of nixpkgs' open and merged PRs (about 150 requests and 2 minutes). On top
of that, a package costs about 0.3 requests and half a second on a typical
day (the Hydra jobs the digest can't answer, its update-log folder when it
changed), and about 3 requests and 3 seconds the first time it's synced
(its update-log folder read whole): 1,500 packages take about 12 minutes a
day. A sync starts by saying how long it should take, counting the packages
new to it (on GitHub, in the run's summary too). From 1,500 packages, the list check warns on the page
and in the status issue; above 5,000, the sync refuses to start, so a big
team or a typo can't send thousands of requests by accident. To track more
on purpose, raise the limit in the lists: `maxPackages = 6000;`
(`lists.maxPackages` in the modules). On GitHub Actions, a sync has to
finish within 6 hours, or nothing is published: about 8,000 new packages
at once. Add big lists in stages, since only new packages cost that much;
the sync warns when one may run that long. When Repology lookups fail
(Repology down, most likely), the sync goes on: each of those packages
keeps its last versions (from the versions digest, else the last run's),
marked "not refreshed", and Hydra's builds, nixpkgs-update's attempts and
the rest are refreshed as usual; a new package with no earlier data shows
as not looked up. The sources panel says how many lookups failed.

## What gets tracked

`package-lists/default.nix` lists GitHub handles under `maintainers` (every
nixpkgs package they maintain is tracked) and imports further named lists
under `extraPackages` (`extra`, `gaming`, ...) of nixpkgs attribute names
(exactly that package, e.g. `haskellPackages.pandoc`) or pnames (every
top-level package with that pname).

Each list is a filter on the page, next to `maintained` for the packages
found through `maintainers`. `?list=gaming` in the address is a page of
just that list, to share with the people it's for. A list named as a
nixpkgs team is (`gaming` for Gaming, compared as file names are: case and
punctuation aside) also joins the team: its packages show on the team's
page (`?team=Gaming`), in its counts and its filter, beside those nixpkgs
lists under it in `meta.teams`. For packages a team looks after that
nixpkgs doesn't list it on; their panel says the team comes from the list.

Update checks (`package-lists/update-checks.nix`) look for new releases
Repology doesn't count yet. A rule's check (yours or a community one) is
the package's own source: where it and Repology disagree on whether nixpkgs
is outdated, it decides, as when one of Repology's rules lags (Chrome's
"155 and up are betas", kept after 155 went stable), and the panel says
what Repology said. A package without one of its own (or a community
rule) gets one worked out from nixpkgs: fetched from a GitHub tag, it's
checked against that repository's tags, in the scheme nixpkgs' tag shows
(`v1.2.3`, ...), plain versions only, and is left to Repology when that
check fails. One fetched from a tag on a GitLab instance (gitlab.com,
freedesktop, GNOME, KDE, Debian's salsa) or on Codeberg is checked the
same way against its repository's tags there, through that forge's API
(no token), for the lists' packages; `workedOutChecks = false;` turns these off. These checks come
from [nixkeeper-versions](https://github.com/nixkeeper/digest-versions)'
digest of GitHub releases, which works them out the same way for every
package in nixpkgs and reads each repository at least weekly (daily when
Repology calls the package outdated): its latest release when the project
makes them, else its newest tag. A worked-out check only ever adds a newer
version Repology hasn't seen; it never makes a package Repology calls
outdated up to date (a project that moved leaves its old repository's tags
behind), nor counts a newer release for a version nixpkgs keeps on
purpose beside a newer one (Repology's "legacy": fuse 2, `llvmPackages_18`).
An up-to-date rule naming the wrong version (`newest`) silences a
worked-out check that finds it too, so one wrong result is fixed the same
way as a wrong Repology verdict. Coq and Rocq libraries
are left to Repology: they're released for each
version of the prover, so their newest waits on nixpkgs' own. The sync
works out its own for the lists' packages the digest read over a day ago,
or since bumped. The daily sync's
log compares them with Repology ("Worked-out update checks"). Ignore rules
(`package-lists/ignored-updates.nix`) mark failed nixpkgs-update attempts
that don't count, and up-to-date rules (`package-lists/up-to-date.nix`) mark
versions Repology gets wrong. With
`community = { ... }`, the lists also use the [community rules](community.md)
of each kind, which anyone can add to, for the packages they track.

To set the lists up for a dashboard of your own, see
[your own instance](your-own-instance.md); the data each sync writes is
described in [data.md](data.md).
