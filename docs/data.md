# The data

Everything the page shows comes from plain JSON files, which each sync
rewrites and commits to the `data` branch, under `data/`. That branch is
always `main` plus one commit with the latest data: each run replaces it, so
it keeps no history.

- `index.json`: the sync's details (when, which version, list problems)
  and the counts of rows and shards
- `summary.json`: a short entry per row, with what the page's list needs
  (below)
- `rows/<n>.json`: the rows in full, with their Repology entries, in shards
  (below)

This is the data's second format, which lets the page load only what it
shows. The first (0.11.0 and before; written beside the second until
0.13.0) had every row in `index.json` (`packages`) and each Repology
project's entries in a file of its own (`<project>.json`): the page no
longer reads it, and the next sync after upgrading rewrites it.

On GitHub they're at
`https://raw.githubusercontent.com/<owner>/<repo>/data/data/index.json`.

Fields are only present when they have something to say: a field missing
from a row means none (no open update PR, never outdated, ...). Dates are ISO
8601 in UTC (`2026-09-30T06:00:00+00:00`), or a plain day (`2026-09-26`) where
the source only has that. New fields may be added; existing ones change only
with a note in the [changelog](../CHANGELOG.md).

The files are compact JSON (no indentation) with keys sorted, so a file
whose data didn't change keeps the same bytes. For the same reason, three
dates are left out when they're the sync's own (`checkedAt` in
`index.json`): a row's `countedAt`, its update check's `checkedAt` and each
build's `checkedAt`. Each is always there otherwise, so a missing one means
"at `checkedAt`"; a package nothing new happened to then reads the same from
one sync to the next. Format them to read them by
hand (`jq . index.json`).

## `index.json`

```json
{ "format": 2, "checkedAt": "2026-09-30T06:00:00+00:00", "version": "0.13.0",
  "packageCount": 241, "shardCount": 1 }
```

`format` is the data's format (2; missing in data from before). `version`
is the nixkeeper that ran the last full sync (the page shows it at the
bottom). `checkedAt` is when the last full sync ran (the hourly checks update
single rows without changing it). `packageCount` is how many rows there are,
`shardCount` how many shards hold them.

`listProblems`, only when there are any, lists mistakes the sync found in the
package lists, as sentences: a maintainer handle no package lists, an extra
package nixpkgs doesn't have, an update check, ignore or up-to-date rule for
a package that isn't tracked, or 1,500 packages or more (the cost of a sync).
The page shows them above the table. `page`, only when the lists set it,
holds the page's settings: `{ "theme": "catppuccin" }` is
its default palette.

`sources` says where the last full sync's data came from, by source:
whether it was used (`used`), and if not, why (`why`: too old, or couldn't
be read; the sync then asked per package instead, an old versions digest
answering where Repology couldn't). `repology` is there only when lookups
failed: how many (`why`); those packages kept their last versions. `hydra` has the
evaluation its builds are from (`eval`) and when nixkeeper-hydra read it
(`at`); `versions`, when nixkeeper-versions last read the outdated projects
(`at`); `typst`, when nixkeeper-versions last read Typst Universe's index
(`at`) and how many packages it has (`packages`; not used, Repology's
versions stay); `emacs`, likewise for the Emacs archives (`at`, and
`melpa`, `melpaStable`, `nongnu`, `gnu`: how many packages each has);
`cran`, likewise for CRAN and Bioconductor (`at`, `biocVersion`: the
release nixpkgs pins, and `cran`, `bioc`, `annotation`, `experiment`: how
many packages each index has); `stackage`, likewise for Stackage LTS (`at`, `snapshot`: its newest,
`nixpkgs`: the one nixpkgs follows, `packages`: how many it pins);
`branch:haskell-updates`, when nixkeeper-hydra last read the
haskell-updates jobset (`at`), which evaluation (`eval`) and how many jobs
(`jobs`; not used, rows have no `branch`); `tracker` and `osv`, when
nixkeeper-vulnerabilities read the NixOS security tracker and OSV (`at`),
and how many CVEs (`suggestions`) or advisories (`advisories`) on how
many packages (`packages`), and for `tracker` the newest release fixes
are to be backported to (`release`, `26.05`); `updates`, when nixkeeper-updates made its digest (`at`) and how
many attempts it hasn't read yet (`pending`); `queue`, when the bot's queue
was made (`at`) and how many days it takes to go round (`cycleDays`);
`releases`, when nixkeeper-versions read GitHub releases (`at`) and for
how many packages (`packages`);
`nixpkgs`, the channel's commit (`revision`); `prs`, when nixkeeper-prs
made its digest (`at`) and what the sync took from it: how many open PRs
(`prs`) and issues (`issues`), and PRs merged since the channel's commit
(`merged`), with what it listed itself instead (`partly`: a list too old,
or merged since another channel commit); `github`, whether the open PRs
were listed in one go, when the sync listed them itself.
A source that's turned off isn't there; data from before 0.12.0 has none.
The page shows them under "checked … ago".

```json
"sources": {
  "hydra": { "used": true, "at": "2026-10-05T13:41:00+00:00", "eval": 1829853 },
  "versions": { "used": false, "why": "too old", "at": "2026-10-03T04:20:00+00:00" },
  "updates": { "used": true, "at": "2026-10-05T12:30:00+00:00", "pending": 1204 },
  "queue": { "used": true, "at": "2026-10-05T12:15:00+00:00", "cycleDays": 10.3 },
  "nixpkgs": { "used": true, "revision": "8f3a1c2…" },
  "github": { "used": true }
}
```

## `summary.json`

```json
{ "packages": [ ... ] }
```

One entry per row, sorted by name: the row (below) without what only its
details show (`dataFile`, `homepage`, `repoCount`, `repologyCheckedAt`,
`source`), its `queued` with only the versions, whether the bot runs its
updateScript and the day it's expected (`{ "to": ["4.22.7"], "script":
true, "by": "2026-10-22" }`, when there's a version or a script),
its builds with only `status` and `system`, its `update` with only
`outcome` and `failedBecause` (still `null` when the bot never tried, missing when it isn't in
nixpkgs), and its `upstream` with only `version`, `newer`, `community` and
`inferred`.

## `rows/<n>.json`

```json
{ "packages": [ ... ] }
```

The rows in full, sorted by name, each with its Repology project's entries
in `repology`: one entry per repository and package, with only what
nixkeeper reads (`repo`, `srcname`, `version`, `status`, and `vulnerable`
when flagged), each once; missing when there are none. Rows
are spread over `shardCount` shards (a power of two, about 500 rows each) by
a hash of their name: a row is in shard `crc32(name) % shardCount` (CRC-32
of the name's UTF-8 bytes, as zlib computes it), so a new package changes
only its own shard.

## Every package

With [every package](all-packages.md) tracked, `index.json` says
`"allPackages": true` and there's no `summary.json` (every package's entry
would be too much to load; the shards' entries are, for packages not on the
lists, nixpkgs' own and those of the 8 newest other repositories). Instead:

- `counts` in `index.json`: `tracked`, `outdated`, `failed` (failing in
  any way), `buildFailures` (a build of its own failed), `updateFailures`
  (nixpkgs-update's attempts failing), `vulnerable` (by the NixOS security
  tracker, OSV, Repology, or marked insecure by nixpkgs), `backport` (a CVE
  fixed on nixpkgs master, still affected on the newest release branch),
  `broken` (marked
  broken), `waiting` (outdated, the
  update merged on master) of the rows not in a set updated in bulk;
  `inSets`, how many are (`pending` before 0.14.0); and
  `failingBuilds`, every Hydra job of every row that didn't build (failed,
  a dependency failed, or unfinished), on every platform; and
  `buildFailuresOn`, the `buildFailures` by where they fail: `linux`,
  `darwin` and each Hydra system (`x86_64-linux`, ...), a package counted
  where it's available only, as the page's platform filter does;
- `highlights` in `index.json`: for `failing` (builds), `outdated` and
  `updateFailing`, of the rows not in such a set, `{ "count", "newest", "oldest" }`:
  how many there are (the same as `counts`' `buildFailures`, `outdated`
  and `updateFailures`), and the 8 most recent and 8 longest-standing of
  those that have their date, each `[name, since, status]`, with a fourth
  when it stands for its `family` (`{ "more", "label"? }`: how many others
  of it are left out of the list, and what they're called together,
  `"python313Packages.huaweicloudsdk*"`) (from
  `failingSince`, `outdatedSince`, `updateFailingSince`, which the daily
  sync sets: one counted since the last has none yet, and one whose
  failed builds never succeeded has none; `status` as in
  `names.json`);
- `blockers` in `index.json`: the failing dependencies that stop others'
  builds, of every row (in sets too, as zh.fail counts them): how many
  there are (`count`), how many packages have a build they stopped
  (`packages`, as many as `blocked.json` has, whether nixkeeper-hydra has
  read which dependency it was yet or not), and the 8 that stop the most
  (`top`), each `[name, row, packages, builds]`; and `stagingNext`, the
  same on staging-next for packages that build on master (`eval`,
  `evaluatedAt`, `count`, `packages`, `top`), when any are stopped there;
- `causes` in `index.json`: why things fail, across the rows not in a set
  (`causes.py`): `builds`, the 8 biggest groups of failed builds sharing an
  error, each `{ "key", "count", "reason", "signature", "line", "title"?,
  "about"? }` (`signature`: the error line with what differs between
  packages taken out, how they're grouped; `line`: one package's own;
  `reason`: the commonest nixkeeper-hydra reason in it; `title`, `about`: a
  friendly title and what it concerns, where the pattern is known), groups
  of 3 packages or more, the 40 biggest each in `views/cause/<key>.json`
  (its packages, as the other views, and the same fields), and all of them
  in `views/causes.json` (`{ "groups": [...] }`, the same fields: the card's
  "Show all", loaded on asking); `groups` and
  `packages`: how many in all; `bot`: the update bot's failures by cause
  (`{ "updateScript": 939, ... }`, the commonest first);
- `views` in `index.json`: how many rows `attention`, `broken` and `blocked` have, the `teams` and
  `lists` with their counts (`{ "Gaming": 12, ... }`), and the `sets`
  with how many packages each has, how many of them are outdated (from
  0.14.0; `onBranch`: of those, how many are already updated on the
  branch that updates the set before master, haskell-updates), fail, and
  nixpkgs marks broken; for R, `archived` (no longer on CRAN or in
  Bioconductor) and `archivedUnmarked` (those not marked broken). These
  counts overlap (a package can be outdated and broken); `bar` (from
  0.14.0) counts each package once, at its worst: failing, then broken,
  then outdated, what the overview's bar draws
  (`{ "haskellPackages": { "packages": 19423, "outdated": 1083, "failed": 83, "broken": 7600, "bar": { "failed": 83, "broken": 7530, "outdated": 560 } }, ... }`);
- `profiles` in `index.json`: what updates each set updated in bulk,
  `{ "rPackages": { "name": "R", "updatedBy": "the CRAN and Bioconductor
  import (generate-r-packages.R)", "short": "CRAN import", "link": ... },
  ... }` (`SET_PROFILES` in `config.py`);
- `views/`, each `{ "packages": [ ... ] }` of summary entries, sorted by
  name: `attention.json` (failing, outdated, flagged vulnerable or with a
  fix to backport, not in a set updated in bulk), `broken.json` (marked broken, not in such a set),
  `backport.json` (a CVE to backport: `backport`, not in such a set),
  `blocked.json` (a build not tried because a dependency failed, in such
  sets too), `unbuilt.json` (listed for a platform Hydra doesn't build it
  on, not in such a set: `datastore.unbuilt_where`, the page's struck
  platform tags; its count in `index.json`'s `views.unbuilt`),
  `superseded.json` (an open update PR nixpkgs is already past, or an
  init PR for a package it has: `supersededPRs`, in such sets too; its count in `views.superseded`),
  `maintainer/<handle>.json` (the handle in lowercase; `none.json`: no
  maintainer, not in such a set), `team/<slug>.json` and `list/<slug>.json` (the
  name in lowercase, each run of other characters than letters and digits
  a `-`: `Security review` is `security-review`), `set/<name>.json` (a
  set's rows);
- `merge` and `numbers` in `index.json` (with every package): the
  overview's "nixpkgs in numbers". `merge`: `{ "prs", "maintainers" (who
  could merge at least one), "over90" (waiting over 90 days) }` of
  `views/merge.json` (`prs_digest.merge_summary`); `numbers`: `{ "builds",
  "failing", "blocked", "unfinished" (Hydra's builds of every row, sets
  too, and of those not built, by kind: their own failure, a dependency's,
  timed out or aborted; together, the counts' `failingBuilds`),
  "behind" (update PRs behind upstream), "unmaintained" (packages outside
  the sets with no maintainer) }` (`datastore.numbers`).
- `close` in `index.json` (with every package): `{ "prs", "bot", "init" }`,
  the open update PRs nixpkgs is already past, how many are r-ryantm's,
  and the init PRs for a package it has (`prs_digest.mark_superseded`): "nixpkgs in numbers".
- `views/merge.json`: the open PRs a maintainer can merge now with nixpkgs'
  merge bot, from nixkeeper-prs' digest (eligible by nixpkgs CI's label, CI
  green, no conflict, no changes requested, not a draft, touching tracked
  packages), oldest first: `{ "checkedAt", "prs": [ { "number", "title",
  "author", "created", "base", "packages": [row names], "who": [the
  maintainers of every package it touches, GitHub handles], "approvedBy"?,
  "behind"?, "vulnerable"? },
  ... ] }`. With every package only. The maintainer and team views'
  "You can merge these" (`prs_digest.mergeable`);
- `history.json`: `{ "points": [ { "day", "tracked", "outdated", "failed",
  "buildFailures", "updateFailures", "vulnerable", "broken" }, ... ],
  "fixed": [ ... ] }`. `points`: the counts of the rows not in a set at each
  daily sync (the last 365 days; a second sync the same day replaces the
  first), the overview's trends. Points from before 0.13.0 have `failed`
  only; a sync adds `buildFailures` and `updateFailures` to the previous
  day's from that day's manifest.
  `fixed`: what each daily sync found fixed since the one before, the last
  30 days, each `{ "at", "name", "kind", "from"?, "to"? }`, of the rows not
  in a set, and only with something showing it: `build` (it was failing; no
  build fails now, and Hydra has a success), `update` (it was outdated; it
  isn't, and nixpkgs' version changed: `from` and `to`), `bot`
  (nixpkgs-update's attempts were failing; they aren't, and its attempt
  changed: a newer one, or superseded). A source that's late, or a change
  in how nixkeeper counts, so doesn't look like fixes. Credit, when known
  (since 2026-10-09): `pr`, `author` (who opened it) and `mergedBy` (GitHub
  logins, from nixkeeper-prs): an update's (and a bot failure it ended) to
  the update PR the last sync saw merged into master (`masterPR`); a
  build's to the PR merged since it began failing that touched it
  (`buildFixPR`), with `likely`. None when no PR was seen: never a wrong
  one. `events`: what
  marks the trends, the last 365 days: `{ "day", "kind": "staging-next",
  "pr", "title" }` for each merge of staging-next into master (mass
  rebuilds: failing builds jump for days after; asked of GitHub's search
  each daily sync, the last 30 days', kept once each), and `{ "day", "kind":
  "nixkeeper", "version", "from" }` when the sync ran a new nixkeeper
  version, and `{ "day", "kind": "counting", "text" }` for a change in how
  nixkeeper counts (`COUNTING_CHANGES` in `config.py`), on the first day the
  sync ran with it (a change can step a count overnight);
- `fixed` in `index.json`: of those, the last 7 days' (`days`): for
  `build`, `update` and `bot`, `{ "count", "newest" }`, 8 each, the
  longest-standing first (`since`), each `[name, at, from, to]`, a fifth,
  its credit (`{ "pr", "author"?, "mergedBy"?, "likely"? }`), a sixth,
  `since`, and a seventh when it stands for its family's fixes
  (`{ "more", "label"? }`, as in `highlights`), each `null` when absent
  before one that isn't;
- `maintainers.json`: `{ "maintainers": [ [handle, packages, outdated,
  failing], ... ] }`, every maintainer by handle (any case; as nixpkgs
  writes it first), with how many packages list them (in sets too)
  and how many of the rows not in a set are outdated and failing: the
  maintainers page, and suggestions for a search starting with `@`;
- `names.json`: `{ "names": [ [name, status], ... ] }` for every row, with
  its set as a third element when it's in a set updated in bulk. `status` is a letter as the
  page's dot: `f` failed, `m` outdated but merged on master, `o` outdated,
  `u` up to date, `n` can't be compared (or compared with nothing:
  `onlyNixpkgs`); then `v` when vulnerable (flagged
  by Repology, or marked insecure by nixpkgs).
- `facets.json`: `{ "handles": [...], "teams": [...], "rows": [...] }`, one
  entry in `rows` for each of `names.json`'s, in the same order: where it's
  available as bits (1 x86_64-linux, 2 aarch64-linux, 4 aarch64-darwin; 7
  when nixpkgs doesn't restrict it), alone when it has no maintainer or
  team, else `[bits, [maintainers], [teams]?]` by their place in `handles`
  (as nixpkgs writes them) and `teams`. The search's maintainer, team and
  platform filters; about 120 KB compressed for all of nixpkgs.
- `evaluations.json`: not for the page. nixpkgs' evaluations the sync
  made (`meta.broken` per platform, the sources the update checks are
  worked out from, patches named after a CVE), `{ "answers": {
  "<commit> <system> <expression>": { attribute: answer } } }`, so the
  next sync evaluates only what's new while the channel's commit hasn't
  moved.

## A row

### What it is

| Field | Meaning |
|---|---|
| `name` | the row's name: its nixpkgs attribute (`wesnoth-devel`), or the list entry when nixpkgs doesn't have it |
| `attrs` | the nixpkgs attributes the row covers (variants sharing a version, like `heroic` and `heroic-unwrapped`) |
| `searchTerm` | what GitHub searches for its PRs and issues: the attribute, with versioned sets under the name nixpkgs titles use |
| `lists` | the lists it's on: `maintained` (found through a maintainer handle), then the named lists (`gaming`, ...) |
| `project`, `dataFile` | its Repology project, and the key its entries are kept under (a file-name-safe form of the project's name: its file in `data/` in the first format) |
| `platforms` | `{ "linux": bool, "darwin": bool }` from `meta.platforms` less `meta.badPlatforms`; `null` when nixpkgs doesn't restrict them. From 0.14.0, `systems` too when those don't already say which of the systems nixpkgs builds it's on (`x86_64-linux`, `aarch64-linux`, `aarch64-darwin`): `{ "linux": true, "darwin": false, "systems": ["x86_64-linux"] }`, Linux on x86_64 only. Without `systems`, all of each family's |
| `homepage` | `meta.homepage` |
| `maintainers` | the GitHub handles in `meta.maintainers`, of all its attributes; `[]` when nixpkgs lists none (with a handle), missing when nixpkgs doesn't have it. nixpkgs includes its teams' members there |
| `nonTeamMaintainers` | with teams: the handles nixpkgs lists directly (`meta.nonTeamMaintainers`, not added as a team's members), when they're fewer than `maintainers`; missing when they're the same |
| `markedBroken` | `true` when nixpkgs marks one of its attributes broken (`meta.broken` in the package index, evaluated for x86_64-linux), even with no Hydra job to say so (a broken package often has none) |
| `teams` | the nixpkgs teams in `meta.teams` (`maintainers/team-list.nix`), of all its attributes, by their short name (`Gaming`, `Qt-KDE`); from 0.14.0, also the team a list named after it adds (`teamsByList`); missing when it has none |
| `teamsByList` | of `teams`, those only a list named after the team adds (the `gaming` list: `Gaming`), not `meta.teams`; missing when none |
| `set` | with every package: the set updated in bulk (`haskellPackages`, ...) of a row no list has: counted on its set's line, without GitHub's counts ([every package](all-packages.md)); `index.json`'s `profiles` says what updates it. Data from 0.13.0 and before has `"pending": true` beside it |
| `branch` | for a row built on a branch that updates its set before master (haskell-updates, from nixkeeper-hydra): `{ "name": "haskell-updates", "version", "status", "build" }`, the branch's version, how its build went there (as `builds`' statuses) and the build. Counts nothing: the page says an update waits for the branch's merge, or a failure is fixed there, or that a package breaks when it merges |
| `lookupFailed` | `true` for a package Repology couldn't be asked about on this sync (down, most likely) with no earlier data: shown as not looked up, `nixStatus` `unlisted` |
| `unversioned` | with every package: `true` for a row of `darwin` or `freebsd`, not versioned software: its builds are what's checked |
| `unread` | with every package: the sources this sync didn't read for the row and kept as they were (`["update"]`: its nixpkgs-update attempt, which nixkeeper-updates' digest hasn't read yet) |
| `source` | where nixpkgs defines it, on GitHub at the channel's commit and line |
| `family` | when one update moves it with other rows (the same package file in nixpkgs, the same version and homepage: the 187 `huaweicloudsdk*` Python packages, a kernel module once per kernel): a short key they share. The overview's lists show a family as one entry, and the package list folds three or more alike (the same status and newest version) into one row |
| `unfree` | `true` when every attribute is unfree (Hydra doesn't build those) |

### Versions (Repology, and nixkeeper's own checks)

| Field | Meaning |
|---|---|
| `nixVersion` | the version in nixos-unstable: Repology's, or the channel's own (its package index, as the sync read it) when that's newer, Repology not having read the channel since it moved; `nixStatus` is then worked out again (`outdated` turns `newest` when `refVersion` isn't newer than it) |
| `repologyVersion` | when `nixVersion` is the channel's: the older version Repology still has for it |
| `nixStatus` | Repology's status for it: `newest`, `outdated`, `devel`, `unique`, `legacy`, `untrusted`, `rolling`, `noscheme`, `incorrect`, ..., or `missing` when nixpkgs doesn't have it; `unsupported` when nixpkgs' version is `0-unsupported`, its version for a package it doesn't build in its default configuration (CUDA packages for another CUDA), so with nothing to compare; with every package, `unlisted` for one Repology doesn't know (`nixVersion` is then nixpkgs') |
| `refVersion` | the newest version seen elsewhere (for a devel row, the newest devel one), or what nixkeeper's update check found, or what master has (`master`), whichever is newest |
| `refFromMaster` | `true` when `refVersion` is master's: newer than anything Repology or an update check knows of |
| `repoCount` | how many other repositories Repology compares it with (each counted once) |
| `onlyNixpkgs` | `true` when no repository outside nixpkgs has it (nixpkgs' release channels aren't another). With `nixStatus` `unique` and no `upstream` or `feed`, its version was compared with nothing: the page shows it grey ("only in nixpkgs"), its status letter is `n`. Packages it's true for get the GitHub releases digest's result even when it only confirms their version |
| `devel` | a development variant of a split project: newer than its stable one, or named for one (`wesnoth-devel`, `_1password-gui-beta`); or a version Repology calls devel |
| `keptBeside` | for an older version nixpkgs keeps on purpose (Repology's `legacy`: `tracy_0_11`, `gnumake42`, `php82Extensions.zip`), the newer one beside it: `{ "attr", "version" }` |
| `feed` | when its versions are compared with its own source instead of Repology: `{ "name", "version", "released"?, "dated"?, "url" }`, its newest version there, the day it was published (when the source says), and `dated` when versions are a build's date and time (MELPA's `20251005.508`). `nixStatus` and `refVersion` are then from it. Typst packages, with Typst Universe: `outdated` or `newest` for a package's latest attribute (`typstPackages.cetz`), `legacy` for its other versions (`typstPackages.cetz_0_3_0`). Emacs packages, with the archive each comes from (`MELPA` for a MELPA version, else the first of `MELPA Stable`, `NonGNU ELPA` and `GNU ELPA` that has it, in nixpkgs' order); not the hand-written ones, the devel archives' versions or packages no archive has. Haskell packages nixpkgs pins to Stackage LTS, with that series' newest snapshot (`Stackage LTS 24`): also `snapshot` (`lts-24.62`), `followed` (the one nixpkgs follows, `lts-24.38`) and `heldBack` (Hackage's newer version, which Stackage holds back until its next series); the rest of `haskellPackages` keep Repology's verdict. R packages, with `CRAN` or the Bioconductor release nixpkgs pins (`Bioconductor 3.23`) |
| `archived` | `true` for an R package on neither CRAN nor the Bioconductor release nixpkgs pins any more (archived by CRAN, or dropped by Bioconductor); its status stays Repology's. nixpkgs marks most of those broken already |
| `nixVulnerable` | Repology flags `nixVersion` as vulnerable (its CVEs: `https://repology.org/project/<project>/cves`); not for an older version kept beside a newer one (`keptBeside`), which Repology judges by the newer series' CVE ranges: the security tracker's and OSV's verdicts decide there |
| `vulnerabilities` | from nixkeeper-vulnerabilities, when it has any for one of its attributes (the full row only): its CVEs (the NixOS security tracker's) and OSV's advisories, `[{"id", "source": "tracker" \| "osv", "verdict", "issue"?, "github"?, "severity"?, "score"?, "summary"?, "releases"?, "cves"?, "ecosystem"?}]`, counted ones first, worst severity first. `verdict`: `affected` (`nixVersion` is in the CVE's affected range), `tracker` (the ranges can't be read; the tracker said affected when it last evaluated the package), `wontFix`, `osv` (an OSV advisory lists `nixVersion`; not for a CVE the tracker has) count (`byVersion` in data from before nixkeeper checked every version itself, 2026-10-08: now `affected`); `fixed` (outside the ranges), `patched` (counted otherwise, but nixpkgs carries a patch named after the CVE: a file `CVE-2026-1234.patch`, a fetched patch's name or URL), `unconfirmed` (the ranges can't be read, and the tracker didn't say affected), `dismissed` (the security team says not affected) don't. `issue`: the tracker's `NIXPKGS-…`, `github` its nixpkgs issue; `releases`: its status on the release branches (`{"release-26.05": "affected"}`: a fix to backport), the newest's by the version its channel has now (nixos-26.05's package index), or `patched` when that channel carries a patch named after the CVE, the others' as the tracker last evaluated them |
| `backport` | the ids of its CVEs fixed on nixpkgs master (`verdict` `fixed`) but still affected on the newest release branch the tracker evaluates (`release-26.05`): a fix to backport |
| `vuln` | in the list's entries only, when the row has `vulnerabilities`: `{"n", "severity"?, "by"}`, how many of them count, the worst severity among those, and who says it's vulnerable (`tracker`, `osv`, `nixpkgs`, `repology`); `null` when none does. Missing: Repology's flag and nixpkgs' mark decide, as before |
| `markedInsecure` | nixpkgs marks one of its attributes insecure: its reasons (`meta.knownVulnerabilities` in the package index, each once: `["CVE-2018-19655"]`, `["Uses Electron 39.8.10, which was EOL ..."]`); such a package won't build unless allowed (`permittedInsecurePackages`). Counts as vulnerable |
| `outdatedSince` | when nixkeeper first saw it outdated; gone once it's caught up |
| `failingSince` | since when a build of it has been failing (its own build, not a dependency's): the failed builds' last success, the earliest (the failing began after it), as Hydra says it each sync; while that isn't known, kept from sync to sync (first seen, then); gone once it doesn't fail; none when every failed build never succeeded |
| `neverBuiltOn` | the systems where Hydra says its failed build never succeeded (`["aarch64-darwin"]`) |
| `updateFailingSince` | since when its nixpkgs-update attempts have been failing, the same way; first seen, the failed attempt's day |
| `staleSince` | Repology couldn't be reached for it: the version data is from this time |
| `repologyCheckedAt` | when its Repology data was read: when nixkeeper-versions' digest read it (every 12 hours for outdated projects, weekly for the rest), or when Repology was asked directly (daily while it's outdated, flagged vulnerable, changed in nixpkgs or new, otherwise every 3 days) |
| `upstream` | nixkeeper's own update check, when it has one (below): a rule of yours or the community's, or one worked out from nixpkgs |
| `repologySaid` | a rule's update check (yours, the community's, or one it follows; not a worked-out one) disagreed with Repology on whether `nixVersion` is outdated, and decided: `nixStatus` is the check's (`outdated` or `newest`, then with no `refVersion`), `status` is what Repology said and `newest` the version it showed as newest elsewhere (when there was one) |
| `upToDate` | an [up-to-date rule](community.md#up-to-date-rules-until-something-changes) applies: Repology gets `nixVersion` wrong, so `nixStatus` is `newest` and there's no `refVersion`. `status` is what Repology said, `newest` the version it showed as newest elsewhere (when there was one), `reason` the rule's, `ruleNewest` the rule's own `newest` (a worked-out update check finding that version doesn't count either), and `community` is `true` for a community rule |

A row counts as outdated when `nixStatus` is `outdated`, `upstream.newer`
is `true` (a newer release, for a versioned attribute in its own series),
or master has a newer version. `legacy` (an older version kept beside a
newer one, `keptBeside`) isn't outdated by itself, except for a devel row
behind the newest devel version elsewhere (`refVersion`), or one behind in
its own series: `nixStatus` is then `outdated` and `refVersion` its
series' newest, from releases in two distributions or more. The series is
told by nixpkgs' next newer version, preferably one whose first part
differs (thunderbird 158.0 for thunderbird-153's 153.4.0, not nixpkgs' own
thunderbird-esr-bin at 153.5.0, which would make it 153.4).

`upstream`:

| Field | Meaning |
|---|---|
| `version` | the newest version the check found (for an unstable version, nixpkgs' version moved to the newest commit's date) |
| `newer` | whether that counts as newer than nixpkgs' (for a branch check, only once `outdatedAfter` says so) |
| `label`, `url` | where it looked: `wesnoth/wesnoth tags`, `www.barebones.com`, ... |
| `repo` | the GitHub repository, for GitHub checks |
| `commit`, `behind`, `outdatedAfter` | branch checks: the newest commit, how many commits since nixpkgs' version, and the limits (`{ "days", "commits" }`) |
| `checkedAt` | when it was last checked (left out: at `checkedAt`) |
| `community` | `true` when the check is a [community rule](community.md) |
| `inferred` | `true` when the check was worked out from nixpkgs' source (the GitHub tags it fetches from), for a package without a rule |
| `digest` | `"releases"` when the worked-out check's result came from nixkeeper-versions' digest of GitHub releases (its `checkedAt`: the day the digest read the repository) |
| `tagged` | a newer tag matching the scheme than the release `version` is (pushed, not released yet: a release is preferred when the project makes them) |
| `rule` | a short fingerprint of the rule that found it: an edited rule runs again at once |
| `page` | page checks: the page's `etag` and `lastModified`, as its server gave them, and the `pattern` it was read with; next time the server is asked to send the page only if it changed, and if it didn't, `version` still holds |

### Master and update PRs

| Field | Meaning |
|---|---|
| `master` | the version Hydra built from master, when it's newer than the channel's. That makes the row outdated, waiting for the channel |
| `openPR` | an open update PR in nixpkgs (below) |
| `masterPR` | an update PR merged into master that the channel doesn't have yet |
| `stagingPR` | an update PR merged into staging or staging-next that master doesn't have yet (from nixkeeper-prs only) |
| `stagingNextBlockedBy` | builds on master, but on staging-next a dependency failing there stops it, at the same version: `eval`, `evaluatedAt`, `builds` (`system`, `build`, `by`: each dependency, `name` and `row` when it's a row) |
| `stagingNextBlocks` | its failure on staging-next stops others that build on master: `eval`, `evaluatedAt`, `packages`, `builds` |
| `stagingNextBreaks` | builds on master but fails its own build on staging-next at the same version, in Hydra's newest evaluation of it (nixkeeper-hydra's `staging-next.json.gz`): `eval`, `evaluatedAt`, `builds` (`attr`, `system`, `build`: each failing job there), and `cycle` (`n`, `cut`: the open staging-next PR into master). A forecast: no count includes it |
| `openPRs`, `openIssues` | how many open nixpkgs PRs and issues are about it: PRs whose titles name it or one of its `attrs` as nixpkgs' convention does (`pkg: 2.7.5 -> 2.8.2`), issues with its name or `searchTerm` whole in their title (`Build failure: pkg`, not `pkg-config`). Searched per package instead (the listing failed, or an instance of its own lists), GitHub's search counts them: titles with `searchTerm`'s words |
| `searchShowsMore` | `["pr"]`, `["issue"]` or both: GitHub's search of `searchTerm`'s words, which the page links, shows more than those (a name that's a word: pkg, linux) |
| `countedAt` | when those were last counted (left out: at `checkedAt`): daily, from a listing of all of nixpkgs' open PRs and issues (searched per package instead when that fails: then every 3 days for a package with none open and not outdated) |

`openPR` and `masterPR`: `number`, `title`, `url`, `draft`, `base` (the
branch it targets), and `from` / `to` (the versions in its title,
`name: from -> to`), and for `masterPR` from nixkeeper-prs, `author` and
`mergedBy` (who opened and merged it: an update's fix is credited to
them). `stagingPR` has `on` too (`staging` or `staging-next`: where it is),
`merged` (when), and on staging-next, `cycle` (`n`, `cut`: the open
staging-next PR into master it arrives with, cut from staging that day),
and how it builds there, from Hydra's newest evaluation of staging-next
(nixkeeper-hydra's `staging-next.json.gz`): `eval` (`eval`, `evaluatedAt`),
`inEval` (false: merged since that evaluation), and `builds` (`system`,
`status`, `build`: each platform's job at the PR's version, or at a newer
one when staging-next has moved past it: then `evalVersion`, that version). None of the staging-next build fields (these, `stagingNextBreaks`,
`stagingNextBlockedBy`, `stagingNextBlocks`) come from an evaluation made
before the last staging-next cycle was merged into master: that cycle is
master's now, and until Hydra evaluates the next, there are none.
`openPR` also has `facts` (the full row only), what
nixkeeper-prs found of it: `fixesBuild` (it touches the package while its
build fails on Hydra: then not in `fixPRs` too), `mergeBot` (`ready`: a maintainer can merge
it with the merge bot, CI green and no conflict; `eligible`: once those
are sorted), `state` (`overtaken`, `downgrade`, `snapshotToRelease`,
`preRelease`) with nixpkgs' version `now`, `blocksBot` (the day
nixpkgs-update is expected to try the update it blocks, or `true`), and
`duplicates` (open PRs with the same diff or change, or for the same
package and branch); and what nixkeeper adds (`prs_digest.cross_check`):
`behind` (upstream's newer version, `refVersion`, when it's newer than the
PR's `to`: merged, the package would still be outdated) and `vulnerable`
(`true`: the package counts as vulnerable). `views/merge.json`'s PRs have
the same two, by the update's package.

`dropPR` (in the list too): an open PR removes the package from nixpkgs,
its title naming the package itself: `{"number", "title"}`, with
`"proposed"` saying why the removal looks unlikely for now ("changes
requested", or "no activity since 2026-06-19" after 90 days); the same
`proposed` is on the removal in `otherPRs`. The list's "being removed"
badge is only for a removal without `proposed`.

`supersededPRs` (in the list too): its open update PRs nixpkgs is already
past, as nixkeeper-prs' digest finds them (state `superseded`: nixpkgs,
master's version else the channel's, has the PR's version or a newer one;
snapshots by their dates); and init PRs for it, nixpkgs having it already
(the digest's `alreadyIn`, added another way while they waited), with
`"init": true`. Oldest first: `[{"number", "title", "author", "created",
"now": nixpkgs' version, "draft"?, "init"?}]`. A maintainer's and a
team's "Can be closed", the list's **PR to close**, `views/superseded.json`.

`recentFixes` (the full row only): its fixes of the last 30 days, newest
first, at most 3, each as in `history.json`'s `fixed` (without the name):
`{"at", "kind", "from"?, "to"?, "pr"?, "author"?, "mergedBy"?, "likely"?}`,
for its panel.

`buildFixPR` (the full row only): while its build fails, the PR merged into
master since it began failing that touched it (by its title's package, or
its `pkgs/by-name` directory, of a PR touching at most 3; not one marking
packages broken): `{"number", "title", "url", "author"?, "mergedBy"?,
"merged"?}`, likely the fix, kept while it still fails.

From nixkeeper-prs too, the full row only, at most 5 of each:

| Field | Meaning |
|---|---|
| `fixPRs` | open PRs (not drafts) touching the package while its build fails on Hydra, maybe its fix, other than its update PR: `[{"number", "title", "url"}]` |
| `otherPRs` | its other open PRs (not drafts, nor its update PR or `fixPRs`), by the package their title names or the `pkgs/by-name` directory they touch, a removal first, then the newest: `[{"number", "title", "kind"?, "mergeBot"?}]`; `kind` `drop` (it removes the package its title names: "foo: drop", "remove package", "drop in favor of", not "drop unused bar"), `init` or `update` |
| `issueChecks` | its open issues nixkeeper-prs checked, where there's something to do: `[{"number", "title", "url", "kind", "verdict", "condition"?, "now"?}]`; `kind` `build` (a build failure: `verdict` `builds`, on Hydra now, a candidate to close unless `condition`, the title adding one only a person can check; or `failing`, still), `update` (an update request: `done`, nixpkgs has the version asked or newer, `now`; or `partly`, moved on but not that far), or `cve` (an issue whose title names CVEs, every one of them `fixed` or `patched` among the package's `vulnerabilities`: `verdict` `cveFixed`, with `cves`; worked out by the sync, `prs_digest.add_cve_issues`) |

### Builds (Hydra)

`builds`: one entry per attribute and platform Hydra builds it on
(x86_64-linux, aarch64-linux, aarch64-darwin); empty for unfree packages.

| Field | Meaning |
|---|---|
| `attr`, `system` | the job |
| `status` | `ok`, `failed`, `dependency` (a dependency failed), `unfinished` (timed out, aborted, ...), `notBuilt` (Hydra has no build), `broken` (nixpkgs marks it broken there), or `unknown` (Hydra couldn't be reached and there's no earlier result) |
| `blockedBy` | for a `dependency` build, which dependency failed, when nixkeeper-hydra's digest has read its page: `[{ "name", "row"? }]`, the row of that package (`row`: `true`; by its name here), or the name Hydra gave it when no job builds it (`source`, a download) |
| `failedBecause`, `failedExcerpt` | for a `failed` build, why, when nixkeeper-hydra's digest has read its log on Hydra: `compile`, `tests`, `link`, `header`, `cmake4`, `cmake`, `boost`, `pythonImport`, `pythonDeps`, `pythonBuild`, `pythonMetadata`, `haskellDeps`, `npm`, `lisp`, `home`, `download`, `hash`, `patch`, `substitute`, `missingFile`, `symlinks`, `patchelf`, `autotools`, `disk` (Hydra's side), `other`, `noLog`; and up to three lines of the log that say so (the full row only; list entries have `failedBecause`) |
| `build` | the latest build's id: `https://hydra.nixos.org/build/<id>` |
| `name`, `version` | what that build built (`wesnoth-devel-1.19.28`), and its version |
| `lastSuccess` | when it last built successfully, when the latest build didn't; `null` if it never did |
| `lastSuccessBuild`, `lastSuccessName`, `lastSuccessVersion` | that successful build |
| `checkedAt` | when this job was last read (left out: at `checkedAt`): daily from nixkeeper-hydra's digest; asked of Hydra itself, daily while something's going on, otherwise every 3 days (see [how it works](how-it-works.md)) |

Only `failed` counts as a failure.

### Updates (nixpkgs-update)

| Field | Meaning |
|---|---|
| `update` | the bot's latest attempt (below), or `null` if it never tried |
| `updateFailure` | whether that attempt counts as a failure |
| `queued` | when the bot will try it again, from its queue: `{ "by": "2026-10-12", "candidates": [["4.22.7", "https://github.com/…/releases"], …] }`, the day it's expected (its place in the queue as a share of the queue's cycle) and the versions it would update to that nixpkgs doesn't have, with where it found each (nothing makes the row outdated: the bot's pick can be wrong), and `"script": true` when it also runs the package's updateScript (which decides the version). Missing when it isn't in the queue (the bot sees nothing to update it to) or there's no queue (`sources.queue`) |

`update`:

| Field | Meaning |
|---|---|
| `attr`, `date` | the attribute it tried, and the day |
| `log` | the attempt's log |
| `outcome` | `failed`, `cantUpdate` (a newer version, but no way for the bot to update the package), `prOpened`, `prExists`, `branchExists` (the bot already pushed this update to its branch), `noChange`, `skipped` (the bot passes the package over on purpose), `superseded`, or `other` |
| `from`, `to` | the versions it tried (for an `updateScript` run, read from its diff, or `0` → `1` when it failed before writing one) |
| `was` | what nixpkgs had then: a version, or a name-version (`wesnoth-devel-1.19.24`) |
| `pr` | the PR it opened or found |
| `failedBecause` | for `failed`, why, from the log's first line that says: `bot` (the bot's own machine failed: its build users group, its nix daemon; not the package, still an update failure, worth telling nixpkgs-update's maintainers; also worked out from the excerpt of an attempt read before this reason was), `unavailable` (broken, insecure or not for x86_64-linux, the package or a dependency), `patch` (nixpkgs' patches or substitutions don't apply), `dependency` (missing or too old), `hash` (one not updated, or one the bot couldn't work out: vendored dependencies, mostly), `source` (the new version's can't be fetched), `updateScript` (the package's own failed), `tests`, `noLog` (the build failed, and nix kept no log), `build` (any other build error), `request` (the bot's own request failed, to GitHub mostly), or `other` |
| `excerpt` | why it failed, couldn't update, was skipped or had nothing to update: for a failure, the line that says what went wrong and the next (the last lines of the log when no line says); else the bot's reasons (for a failed request, its host and answer) |
| `supersededOn` | for `superseded`: `nixos-unstable` or `master` (nixpkgs moved past that version), or `ignored` (a manual rule) |
| `supersededOutcome` | what the attempt was before: `failed` or `cantUpdate` |
| `reason` | the manual rule's reason, for `ignored` |
| `community` | `true` when that rule is a [community rule](community.md) |
| `parser` | the version of the rules the log was read with: the next sync reuses this reading instead of downloading the same log again, unless those rules have changed since |

### Sources that couldn't be refreshed

`notRefreshed`: for each source that failed on the last sync (`builds`,
`update`, `upstream`), `{ "since", "reason" }`: since when it's been failing
and why. That part of the row is then the last known result.
