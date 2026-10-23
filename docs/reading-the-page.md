# Reading the page

What each part of nixkeeper's page shows, from the overview down to a single
badge. Sections:

- [The overview](#the-overview): the page's start with every package
- [Lists](#lists): rows, counts, search, finding yours
- [Narrowing a list](#narrowing-a-list): the filters under the counts
- [A package's details](#a-packages-details): its panel, On GitHub, fixes,
  maintainers and teams
- [Where the data is from](#where-the-data-is-from): how fresh each source is
- [The dot](#the-dot), [the version](#the-version), [badges](#badges),
  [build failures](#build-failures), [update failures](#update-failures)
- [The tab's icon](#the-tabs-icon) and [the Theme menu](#the-theme-menu)

Every filter, search and view stays in the address, so any list is a link to
share.

## The overview

On a page tracking [every package](all-packages.md) (a community instance,
such as nixkeeper.com), the page starts from an overview of nixpkgs, with no
list. From the top:

- **How many packages** nixpkgs has, how many are **fully checked** and how
  many are in **sets updated in bulk** (R, Haskell, Emacs, TeX Live, Typst,
  SBCL: kept current by their own tooling, the CRAN import or hackage2nix,
  say, not one PR per package; counted per set, not in the cards).
- **Five cards** for the fully checked ones, each opening its list:

  | Card | Counts |
  |---|---|
  | Outdated | fewer than Repology's nixpkgs page: that includes the sets updated in bulk, counts every attribute of a package, and takes any newer version it knows of, where nixkeeper's own update checks overrule it |
  | Build failures | a build of its own failing; with how many Hydra builds fail in all, as [zh.fail](https://zh.fail/) counts them (every job on every platform, a dependency's failure counted for each package it stops), and how many fail on Linux and on Darwin, each Hydra system on hover |
  | Update failures | nixpkgs-update's attempts failing: often a sign the update needs doing by hand rather than something broken. While the digest of the bot's attempts is still reading past ones, the card says how many are to go: failures that were there all along keep turning up until then, so it rises without anything breaking |
  | Vulnerable | flagged vulnerable (see [badges](#badges)) |
  | Marked broken | nixpkgs marks it broken |

  Each has its **trend** (from the second sync on, the last 30 days at
  most) and its change over the last week (since the first sync until
  there's a week: hover it for which). A solid grey mark on the trends is
  a staging-next merge into master (mass rebuilds: failing builds jump for
  days after), a dashed amber one a change in how nixkeeper counts (it can
  step a count overnight). The line under the cards names each kind with its days
  ("counting changed Oct 6, Oct 7"), and hovering a day says what happened
  (a staging-next day links its PR). nixkeeper's own releases aren't
  marked: the footer says the version, and one that changes counting has
  its own mark.
- **A search box** (a package's name, or `@handle`) and a team picker. While
  searching, the matches take the place of what follows, which comes back
  once the search is cleared. Typing `@` and part of a handle suggests the
  maintainers whose handle matches, with their counts (the overview stays
  while you type: a click or Enter opens theirs); "browse every maintainer"
  (`?view=maintainers`) lists them all by handle, the search narrowing them.
- **The newest and longest-standing** build failures, outdated packages
  (not those whose update is merged and only waits for the channel) and
  update failures (a switch on each), and "show all" for the whole list.
  Packages one update moves together (one package file in nixpkgs, one
  version: `python313Packages.huaweicloudsdk*`, 187 of them, or a kernel
  module once per kernel) are one line, with how many, opening a search
  for them; the same in "what was fixed".
  Beside them, the failing packages **blocking the most** others: a build
  that fails because one of its dependencies did, as zh.fail counts them in
  all of nixpkgs (fix that one, and they all build again), and "show all"
  for every package blocked (`?view=blocked`). While Hydra has evaluated
  the current staging-next, "Master | Next" switches it to staging-next,
  before its merge into master: the dependencies failing there that stop
  the most packages building on master (its evaluation's day said). The panels of both say it too: "its
  failure stops N other packages' builds on staging-next", "on
  staging-next, its build is stopped by X".
- **Why things fail**: failed builds grouped by the same error (the line of
  their log that says why, with paths, numbers and names left out: one
  cause, one fix pattern, like "Broken by the abseil-cpp update" or "Python
  module missing: pkg_resources"). The biggest groups have a title where
  the pattern is known, else the error line itself; each opens its packages
  (`?cause=`, with the shared line at the top). Beside them, why the update
  bot fails, by cause, each opening those packages (`?updateFailed=`).
- **What was fixed in the last week**: builds that work again, packages
  updated (from and to which version), and nixpkgs-update failures cleared.
  Each list has the fixes that took longest first ("after 5 m": how long it
  had been failing or outdated; a build's from Hydra's last success, an
  outdated package's from when nixkeeper first saw it so), each with who
  fixed it: the author of its PR (hover for the PR and who merged it; a
  build fix's PR is a likely one, merged since the build began failing and
  touching the package; a bot's name isn't shown).
- **The sets updated in bulk**, each with its size, what updates it, how
  many are outdated (for Haskell, how many of those are already updated on
  haskell-updates, waiting for its merge), and how much of it is marked
  broken or failing (a bar).
- **nixpkgs in numbers**, last, for the curious: open PRs and issues, PRs
  ready for the merge bot and waiting for their own maintainers (yours are
  on your page), update PRs behind upstream, how long the update bot takes
  to go through its queue, Hydra's builds not built (the failing builds at
the top, split: their own failure, a dependency's, unfinished), packages not built where
  listed, the share up to date, and packages without a maintainer, each
  opening its list where there is one.

## Lists

Each row is a package. Clicking it opens [its details](#a-packages-details);
clicking its build or update cell opens that panel instead. Several can be
open at once, each closing on its own; with two or more open, **Close all**
beside the list's count, or Esc, closes them. A package's name is a link to
it alone (`?pkg=`): Ctrl/Cmd-click or middle-click opens it in a tab of its
own. Its **Open on GitHub** cell
counts the open nixpkgs PRs and issues with its name in the title, each
with GitHub's icon and a link to that search ("—" when there are none).

**Opening a list.** At the top of every page:

- **needs attention**: failing, outdated, flagged vulnerable or with a fix
  to backport, worst first;
- **Your packages** (your GitHub handle) and **Your team**, once given:
  they're kept in your browser only, and ✎ changes them.

A list says what it is under "Showing" (✕ goes back to the overview):

| List | In the address |
|---|---|
| what needs attention | |
| a maintainer's packages | `?maintainer=handle` (`none` for those with none) |
| a team's | `?team=gaming` (any case) |
| a set's | `?set=haskellPackages` |
| one package alone, its details open | `?pkg=firefox` |
| marked broken, blocked by a dependency | |
| fixes to backport: a CVE fixed on nixpkgs master but still affected on the newest release branch (on the overview, a note under Vulnerable, as unstable has the fix; the details say which) | `?view=backport` |
| update PRs to close: every package with an open update PR nixpkgs is already past (it has the PR's version or a newer one), up to date or not, sets too (linked from "Can be closed", from **PR to close** in another list, and from "nixpkgs in numbers") | `?view=superseded` |
| one of the instance's lists | `?list=` (by address only) |

**Counts and tiles.** On a page tracking its own lists, the counts at the
top (tracked, outdated, failed, and flagged vulnerable or blocked when any
are) filter the list, as do the list names beside them and a row's
platform tags (Linux, Darwin, or "Linux x86_64" for a package on only one
Linux system). A tag struck through and dimmed is a platform nixpkgs lists
the package for but Hydra doesn't build it on: no build exists there,
usually because a dependency isn't available there (built on one Linux
system only, the tags split: "Linux x86_64 · ~~aarch64~~"). A package
nixpkgs doesn't restrict ("any platform") shows these tags too when Hydra
doesn't build it somewhere. On a page tracking every package, a list's tiles do the same
(outdated, failing, vulnerable, fixes to backport (`?filter=backport`),
marked broken, blocked).

**Searching.** The search box matches names; `@handle` lists a maintainer's
packages instead (their whole GitHub handle, as nixpkgs lists it in
`meta.maintainers`), and `@none` the packages with no maintainer (a
package's panel links them too, when it has none: "see all packages without
one"). Within a
list, the search and order work on it too, and a search also lists the
packages beyond it whose names match, closest first. The browser's find
(Ctrl+F) only sees the page shown: the search box looks through every
package. It filters as you type; `/` jumps to it, and so does typing with
a row of the list focused (after clicking one, or tabbing to it). Python
packages are found as nixpkgs titles write them too: `python3Packages.`
finds `python313Packages.…`.

Those matches in all of nixpkgs show 50 at a time ("Show 200 more" for the
next), and narrow by **in** a package set (the same `?in=` as the list's,
so it narrows both) and **status**, as their dot says: failing, outdated,
waiting for the channel, up to date, can't be compared, or vulnerable
(`?status=failing`, `outdated`, `waiting`, `uptodate`, `notcompared`,
`vulnerable`). Then, once their data has loaded (a moment after the first
search), **by** a maintainer and **on** a platform (the list's own `?by=`
and `?platform=` too) and **team** (`?ofteam=Python`: not `?team=`, which
opens a team's page). Each choice says how many match with the others
picked; **Clear filters** goes back to every match. `?q=python&status=outdated` is
every outdated package with "python" in its name.

**Order.** **Sort** under the tiles picks it, and ↓/↑ beside it reverses
it (`?sort=…&order=reverse`); packages with nothing to sort by stay last
either way:

| Sort | First |
|---|---|
| most pressing (the default) | failing, then outdated, the longest-standing of each first (vulnerable ones by severity, on Vulnerable) |
| longest-standing | how long it's been failing or outdated, the tile's kind when one is picked (`?sort=oldest`); outdated dates only go back to when nixkeeper started following a package |
| newest | the opposite (`?sort=newest`) |
| biggest version gap | the biggest update: a new first part (2.8.2 → 3.2.4) before a new second (1.2 → 1.9), and so on; within those, the bigger step relative to the old number; a date as a version (20221026) by years. Numbering changes (2026-10 → 202610050438) after them (`?sort=gap`). Its top often shows Repology matching the wrong project |
| name A–Z | by name (`?sort=az`) |

**Pages.** The list shows 200 packages at a time, in that order; the page links under it go through the rest (`?page=2`). "Per page"
beside them shows 50, 100, 200, 500 or 1,000 at a time instead (`?per=500`,
kept when moving between views; the maintainers' list too), staying on the
page that holds the first package you were looking at. Changing a filter,
the search or the order goes back to the first page.

**One update, one row.** Three or more packages one update moves together
(one package file in nixpkgs, one version and homepage, the same dot and
the same newest version: `python313Packages.huaweicloudsdk*`, 187 of them)
are one row, the first of them, with "+186 like it" under its name. The
button shows the others right after it ("fold 186" folds them again).
One of them failing to build, or behind on another version, keeps its own
row.

**Two words you'll see.** "not on Repology" is a package Repology doesn't
know; "not read" an update attempt the sync didn't read (with every
package, attempts come from a digest of the bot's, which hasn't read that
one yet).

## Narrowing a list

Any list can be narrowed further, together with everything else (under the
counts; with every package, under a list's tiles). Each count then counts
what's left.

| Filter | Keeps | In the address |
|---|---|---|
| **without maintainer** | packages with no maintainer | `?refine=unmaintained` |
| **not marked broken** | failures nobody has marked yet | `?refine=notbroken` |
| **not merged yet** | outdated packages, leaving out those whose update is already merged: on master (waiting for nixos-unstable), into staging or staging-next, or a branch like haskell-updates | `?refine=notonmaster` |
| **breaks on staging-next** | packages that build on master but fail their own build on staging-next, at the same version, in Hydra's newest evaluation of it (a day or two old): unless fixed, they fail on master when staging-next is merged into it. A forecast: no count includes it, and a fix may already be waiting on staging. The details link each failing build | `?refine=stagingnext` |
| **not built where listed** | packages nixpkgs lists for a platform Hydra doesn't build them on (no build exists there: usually a dependency isn't available there, or `meta.platforms` promises too much); with a platform picked, that platform's only. Packages Hydra builds nowhere (unfree, kept off it) aren't. For all of nixpkgs at once, its own list: **Not built where listed** (`?view=unbuilt`, linked from Marked broken), where a platform picked keeps those not built there (`?view=unbuilt&platform=darwin`, `aarch64-linux`) | `?refine=unbuilt` |
| **open PR**: with one, or without | with one: packages an open PR touches; with **Marked broken**, those a PR may fix (or that it's moot for, while it stays broken: a person checks; the panel says so too) Without one: those no open PR touches, nobody on them yet | `?refine=withpr`, `?refine=nopr` |
| **newer version**: known, or none known | whether a newer version than nixpkgs' is known (outdated, merged or not); with Build failures, none known means an update won't fix it, the build does (`?filter=builds&newer=no`), known with **Open PR: without** that nobody has opened the update that might | `?newer=yes`, `?newer=no` |
| **PR to close** | packages with an open update PR nixpkgs is already past (see [Can be closed](#maintainers-and-teams)); in any list, with a link to all of nixpkgs' | `?refine=superseded` |
| **bot won't update it** | outdated packages nixpkgs-update won't update by itself, so it takes someone: it can't, skips them on purpose, or has never tried them and they aren't in its queue; none with an update PR open or merged | `?refine=nobot` |
| **not via a team** (on a maintainer's page) | see [teams](#maintainers-and-teams) | `?team=none` |
| **build failed because** | build failures for one reason, as the build's log on Hydra says (read by nixkeeper-hydra): compile error, tests, link error, missing header, CMake 4 (it refuses projects asking for CMake older than 3.5), CMake, Python import, dependencies, build or metadata, writes to `$HOME`, hash, patch, download, out of disk (Hydra's side), other, and more; "not read yet" while nixkeeper-hydra catches up. Each with how many there are in the list, on the platform picked | `?buildFailed=cmake4` |
| **update failed because** | update failures for one reason, as nixpkgs-update's log says: build, updateScript, source, dependency, patch, unavailable, tests, hash, request, "build, no log", bot (the bot's own machine failed, not the package: when that was in the last 3 days, its details link nixpkgs-update's issues, to tell them; older, it was a past outage the bot's next round clears), or other when none was recognised. Each with how many there are in the list | `?updateFailed=patch` |
| **older than** a month, 6 months, a year, 2 or 3 years | how long it's been failing or outdated (the counts' kind, when one is picked: failing for over 6 months, say) | `?age=1m`, `6m`, `1y`, `2y`, `3y` |
| **never built** | a failing build that never succeeded on Hydra, which has no date. With **on**, only there: when it's all that fails, the list shows "n/a" instead of how long, and the build column "never: darwin", say | `?age=never` |
| **on** Linux, Linux x86_64, Linux aarch64 or Darwin (macOS, as nixpkgs calls it) | the packages available there, and only their builds there (build failures on aarch64-linux, say), as clicking a row's platform tag does; not those listed there but not built there by Hydra (a struck tag), unless **not built where listed** is on | `?platform=linux`, `x86_64-linux`, `aarch64-linux`, `darwin` (`macos` still works) |
| **in** a package set | one set, by the attribute's first part (`python313Packages` for `python313Packages.requests`, `vimPlugins`), or the top-level packages; `python3Packages`, as nixpkgs writes it, is every `python3…Packages` | `?in=python313Packages`, `?in=python3Packages`, `?in=top-level` |
| **by** a maintainer | the packages a maintainer is listed for (`meta.maintainers`), within the list shown (needs attention, a team's...): type their GitHub handle; those with the most there are suggested. Not on a maintainer's own page, which is theirs already | `?by=fabaff` |

**On**, **in** and **by** say how many each choice would show, counted
with every other filter (the tiles, the search, the others of the three):
with `by` fabaff, `in` offers python313Packages with fabaff's count there.
A set's count is in packages; the pages under the list count rows, where
[one update moving many](#lists) is one.

A chip that's on is tinted, with ✕ at its end, as the list's own chip
("Needs attention ✕"): clicking it turns it off.

The `?refine=` words combine (`?refine=unmaintained,notbroken`), so
"failing for 6 months, with no maintainer" is a link. A build failure's date
is Hydra's last success; the others only go back to when nixkeeper started
following a package, so "older than" finds more of them as time goes on.

## A package's details

Its panel starts with where its newest version is from, a badge linking
there: the release on GitHub, the package archive, the update merged on
master, a community rule, or Repology's project. Then only what the badge
doesn't say: another source's newest version when it differs, newer
commits, or how many repositories it was compared with. While it isn't up
to date, the repositories Repology compares it with follow (`nixkeeper`
first when an update check found a version: hover it for where).

Links are text ending in ↗ (Homepage, package.nix, a build's Build and
Job, "full log"); actions are outlined buttons (Hide).

**Its fixes of the last month**: "Updated 1.9.0 → 1.10.0 on Oct 9 (after
3 w), in #N, by @alice, merged by @bob", and, while its build fails, a PR
merged since that likely fixes it, waiting for Hydra.

**On GitHub**: what nixkeeper-prs found of the package's PRs and issues,
each with GitHub's icon for it (an open PR, a draft, a merged one in violet,
an issue), and a short label ("merge-bot ready", "likely fix", "builds now ·
can close"), the sentence behind it on hover:

- its update PR ready for the merge bot, superseded or overtaken, blocking
  the update bot, or duplicated; **behind** when upstream has a newer
  version than it brings (merged, the package would still be outdated:
  worth updating the PR first). For a vulnerable package, it's under its
  vulnerabilities instead (below);
- open PRs touching it while its build fails on Hydra (maybe its fix), and
  for a package marked broken, that open PRs touch it (one may fix it);
- its other open PRs, a removal first ("removes it from nixpkgs": the list
  says **being removed** too; when the removal PR has changes requested or
  no activity in 90 days, it's only "removal proposed (changes requested)"
  or "(no activity since ...)", and the list says nothing);
- its issues that look done (a build failure that builds on Hydra now, an
  update request nixpkgs has met, an issue about CVEs none of which affect
  nixpkgs' version as nixkeeper reads them; "check it" when the
  title names something Hydra doesn't build) or still fail.

A merged PR's author and merger are on its link's hover.

**Vulnerabilities**: the CVEs and advisories that count, worst first, with
what they share said once above them ("24 CVEs: 4 critical, 8 high ... · all
affected · still affected on 26.05"); grouped by the security tracker's
issue (linked once, with its nixpkgs issue), a line each: the id, its
severity and its summary (cut short, whole on hover), and what it doesn't
share. The worst five, then **Show all**. When an update PR is open, it's
under them: "updates it to 3.20.1: check whether that fixes it, and review
it first" (the tracker gives no fixed version). Those not counted (fixed,
unconfirmed, dismissed) are folded below.

These are worked out automatically, from titles, Hydra's builds and the
merge bot's rules: hints for a person to check before acting (closing an
issue, merging a PR), not decisions. nixkeeper itself never comments on,
closes or merges anything in nixpkgs.

### Maintainers and teams

The panel lists the package's maintainers, each with their GitHub avatar
(loaded from github.com only while a panel is open, without saying which
page asked: no referrer): clicking one searches for theirs, and the address becomes `?maintainer=yourhandle`, a link to your own
(`?q=@yourhandle`, as it was first written, still opens it and becomes
that). Its teams (nixpkgs' `meta.teams`), when it has any, are listed too:
clicking one shows only that team's packages, as `?team=` does in the
address (`?team=gaming`, in any case).

**You can merge these:** on a maintainer's page, above the list, the open
PRs they can merge themselves with nixpkgs' merge bot: CI passed (nixpkgs
CI's own verdict, its `no PR failures` status), nixpkgs' CI labels it
merge-bot eligible, and they maintain every package it touches
(their own PRs first, then those for a vulnerable package, then the
longest waiting; each says so, and when it's behind upstream). Each says who opened it,
how long it has waited, the branch when it isn't master, and who approved
it. Review it, then comment `@NixOS/nixpkgs-merge-bot merge` on the PR (the
block's **Copy** button): the bot merges it, if they're also in
[@NixOS/nixpkgs-maintainers](https://github.com/orgs/NixOS/teams/nixpkgs-maintainers),
which the bot asks for too (who's in it isn't public, so nixkeeper can't
check). On a team's page, the same for
the packages nixpkgs lists under the team (`meta.teams`, whose members are
their maintainers), each with who can merge it; not those a list of the
team's name adds, which their own maintainers merge. Left out: drafts, PRs with
a conflict or changes requested, and those only committers can merge.
Each PR has a **Hide**: it leaves the block, in this browser only, until it
changes (a newer version in its title, or a CVE; not upstream moving on,
so an update held back on purpose stays hidden), with "N hidden · show
them" to see them again, greyed. From
nixkeeper-prs' digest, as of the last sync.

**Can be closed:** below it, on a maintainer's or a team's page, the open
update PRs on their packages that nixpkgs is already past: it has the
PR's version or a newer one (`ocamlPackages.trace: 0.5 -> 0.12` with
nixpkgs at 0.12), so the PR can be closed, with a word on why, or updated
to the newest. Each says who opened it, how long it's been open, what
nixpkgs has now, and when it's a draft; oldest first, with **Hide** as
above, and a link to all of nixpkgs' (`?view=superseded`). Snapshots are
compared by their dates: a snapshot nixpkgs only renamed
(`unstable-2023-12-06` to `0.18.1-unstable-2023-12-06`) doesn't count as
past a PR's newer one. A package's details say it too, under On GitHub.

**Hide until it changes:** a package that needs attention has this button
in its panel, for what you've looked at and decided to leave (an update
held back on purpose, a failure you can't fix there). It leaves your lists
until what it needs attention for changes: a newer version than the one
it was outdated against, another failing build, a new update failure,
nixpkgs' broken mark, a new CVE; a vulnerable package comes back at the
next sync anyway. "N hidden · show them", beside the list's count, shows
them again, greyed, each with **Show it again** in its panel. Kept in this
browser only (its local storage, nothing sent anywhere): another browser,
a private window or clearing the site's data starts over. Wrong for
everyone, not just you? Report it, or add a community rule instead.

Leaving packages out, each a chip to undo it:

- `?team=-Geospatial` leaves a team's packages out, on any list
  (`?maintainer=l0b0&team=-Geospatial`; several: `team=-Geospatial,-Gaming`).
- `?team=none` keeps only what isn't through a team: on a maintainer's page
  (its **Not via a team** button), the packages that list them themselves,
  leaving out those they maintain only as a member of the package's team
  (nixpkgs adds a team's members to each of its packages' maintainers);
  elsewhere, packages without a team.
- `?maintainer=-iedame` leaves out the packages iedame maintains (directly
  or through a team), on any list (`?team=Gaming&maintainer=-iedame`, or
  beside a maintainer's own page: `?maintainer=l0b0,-iedame`), a
  "not @iedame" chip.

## Where the data is from

"checked … ago", at the top, opens when the last sync ran and the nixpkgs
commit it read. On nixkeeper.com, every source and how fresh it is is on
[status.nixkeeper.com](https://status.nixkeeper.com), each digest's row
with what the sync read from it; an instance of its own lists the sources
in the panel instead:

| Digest | Read |
|---|---|
| [digest-builds](https://github.com/nixkeeper/digest-builds) | the Hydra evaluations of master (which the channels follow), staging-next (only the jobs that differ from master, while its cycle isn't merged) and haskell-updates |
| [digest-versions](https://github.com/nixkeeper/digest-versions) | Repology and the other version sources, when each was read |
| [digest-update-bot](https://github.com/nixkeeper/digest-update-bot) | nixpkgs-update's attempts, with how many are still to read, and its queue |
| [digest-vulnerabilities](https://github.com/nixkeeper/digest-vulnerabilities) | the NixOS security tracker and OSV |
| [digest-prs](https://github.com/nixkeeper/digest-prs) | nixpkgs' open PRs and issues, the PRs merged since the channel's commit, and those merged into staging or staging-next |

A source the sync didn't use (too old, or it couldn't be read) says so in
yellow: its packages were then asked about one by one instead. Why
staging-next wasn't used (its cycle already merged into master) is on the
**breaks on staging-next** chip's hover.

## The dot

In front of each package (hover it for what it means, or open the `?` next
to "checked" at the top for all of them):

| Dot | Means |
|---|---|
| green | up to date: nixpkgs has the newest version (for a devel package, the newest devel one), or is the only one packaging it and nixkeeper's update check (GitHub's releases, a package archive) confirms its version, or an [up-to-date rule](community.md#up-to-date-rules-until-something-changes) says Repology gets its version wrong (the details say why). Also when the newer version is only another spelling of the same snapshot: `unstable-2022-10-20` against nixpkgs' older channels' `2022-10-20`; or only nixpkgs' own earlier version: one only its old release channels have (no longer updated: a numbering nixpkgs has since changed), or one only its release channels have while PyPI, CRAN or another upstream index has unstable's (azure's 39.0.0, a mistake since reverted); or only another commit on a nixpkgs channel (tree-sitter grammars' `0.0.0+rev=e45dbac` against 26.05's `rev=9566ca7`: commits have no order) |
| orange | outdated: Repology or nixkeeper's own update check knows a newer version |
| violet | outdated, but the update is already merged on master, waiting for nixos-unstable (usually a few days). Master having a newer version than the channel counts too, even before Repology or an update check knows of it |
| pink | not in nixpkgs unstable (counted as failed) |
| grey | Repology can't compare the version: `untrusted`, `rolling`, `noscheme`, `incorrect` (shown as a badge); **only in nixpkgs**: no other repository packages it and no update check of nixkeeper's knows its releases, so nothing compared it; **unsupported**: nixpkgs' version is `0-unsupported`, as it doesn't build the package in its default configuration (CUDA packages for another CUDA); or an **older version** nixpkgs keeps on purpose beside a newer one (`tracy_0_11` beside `tracy`, `php82Extensions` beside PHP 8.4's): not outdated while nothing newer is out in its own series, and the details name the newer one |

## The version

nixpkgs unstable's. For an outdated package, the newest
version is under it, after a `→`, with the start they share faded, so the
part that changes stands out (orange; violet when the update is already on
master):

```
  1.19.24
→ 1.19.28          ("1.19." faded, "28" in colour)
```

Versions are compared by whole parts (split at `.`, `-`, `_`, `+`, `~`), so
`1.19.24 → 1.19.28` colours `28`, and an unstable version only its new date.
When an update is merged into master but a newer release is already out,
master's version gets a line of its own in between, with its `on master`
badge, and the newest under it with its PR:

```
  154.0.8037.57
→ 154.0.8037.92    on master
→ 154.0.8037.97    PR #569374
```

Click the versions to copy the update's title as nixpkgs writes it, for a
commit or a PR: `unciv: 4.22.1 -> 4.22.6` (from master's version when it's
partway there).

How long a package has been outdated shows after its name (`3 d`; violet
when the update is merged and waiting for the channel), and how long it's
been failing, in red, when it fails (its builds since their last success,
its update attempts since the first failed one nixkeeper read). Failing
packages come longest first, as outdated ones do.

## Badges

At the right of the versions: beside nixpkgs' version, the badges
about it (`devel`, `vulnerable`, ...); beside the newest, the update's
(`PR #123`, `on staging`, `on master`, `check failing`). When it's the
version's only badge, it sits between the two versions, level with the
PR and issue counts:

| Badge | Means |
|---|---|
| `PR #123` (green) | an open update PR in nixpkgs; grey while it's a draft |
| `on master` (violet) | the update is merged into master; links to its PR |
| `on staging`, `on staging-next` (violet) | the update is merged into staging or staging-next, the branches mass rebuilds go through (libraries, compilers, curl, coreutils): it reaches master when staging-next is merged into it, about every two to three weeks; staging's goes to the next staging-next first. Links to its PR; the details say since when, which staging-next, and for staging-next's, how it builds there in Hydra's newest evaluation of it (a day or two old: its day is said). Still outdated until then |
| `devel` | a development release, compared against other devel versions |
| `insecure` | nixpkgs itself marks it insecure (`meta.knownVulnerabilities`): it won't build unless allowed; the details give nixpkgs' reasons, their CVEs linked |
| `vulnerable` | vulnerable, says one or more of: the NixOS security tracker (a CVE affecting the package), OSV (an advisory listing its version), Repology; hovering says who, and how many CVEs. Red for critical or high severity, orange for medium, grey for low; the vulnerable list goes worst first. The details list them, grouped by the tracker's issue: each one's severity and summary, the verdict and the release branches still affected (a fix to backport), said once when shared; the ones not counted (fixed, unconfirmed, dismissed) folded below |
| `untrusted`, `rolling`, ... | Repology's status for a version it can't compare |
| `not refreshed` | Repology couldn't be reached on the last sync: older data |
| `check failing` | nixkeeper's own update check for it isn't working: fix it in `package-lists/update-checks.nix` |

## Build failures

From Hydra, which builds nixpkgs master. The cell opens the
builds panel: a line per system with how it stands there (why it failed,
"missing file", from its log; "not built"; blocked by which dependency),
when it last built (the date on hover), its Hydra build and job (or source)
to open, and for a failure the log's lines that say why, with the **full
log ↗**; "checked on Hydra N days ago" under them when it wasn't today.
Builds failing alike (the same reason and log lines, a test run's timing
aside: python313Packages and python314Packages on two platforms) are
together, each its own line, their log's lines once under the last: "the
same on all 4". For pytest, the lines are its failed tests and its count
of them.

**Show errors** (with the Build failures or Failed tile: `?errors=1`)
opens every failing package's builds under its row, loaded as they scroll
into view: a page of errors to read through, with **build failed because**
to keep one kind.

| Shows | Means |
|---|---|
| a hard hat, then why (pink) | its latest build failed on a platform, and why, from its log on Hydra (`compile error`, `tests`, `CMake 4`, `patch`...: as **build failed because** above), when every failed build says the same; `failure` when they differ or their logs aren't read yet (screen readers say "failed:" before it). `never: x86_64-linux` when it never built there. The panel says each build's reason with the log's lines that say so, links the log, and says when it last built, and at which version |
| a hard hat, marked broken (gold) | nixpkgs marks it broken on a platform (known, so not counted as failed) |
| a hard hat, blocked (gold) | it didn't build because a dependency failed: not its own failure, so not counted as failed (the "blocked" count and tile, `?filter=blocked`, list them); the panel says which dependency (its package, to open), once nixkeeper-hydra has read the build |
| not built by Hydra | unfree, or kept off Hydra by nixpkgs |
| none reported | no failure of its own; an unfinished build shows only in the panel |

## Update failures

From the nixpkgs-update bot (r-ryantm): its latest attempt. The cell opens the update panel: the outcome ("Failed: patch", "PR opened",
"Can't update"...), when it was attempted and from which version to which,
why (unless the outcome already says it all: "Failed: build"), the log's last lines, the next attempt from the bot's queue (when, and
what it would update to), and the log and every attempt to open:

| Shows | Means |
|---|---|
| a robot, then why (pink) | the bot's update failed, and why, from its log: `tests`, `build`, `dependency` (one missing or too old), `patch` (nixpkgs' patches no longer apply), `source` (couldn't be fetched), `hash` (one the bot couldn't work out), `updateScript` (the package's own failed), `unavailable` (broken, insecure or not for x86_64-linux), `request` (the bot's own request failed, not the package). The panel says it in full, with the log's line that says so. `failure` when the log doesn't say (screen readers say "failed:" before it). The robot is red, or the queue's colour (below) when the bot will try again |
| a robot, can't update (gold) | a newer version exists, but none of the bot's ways of updating apply to this package: update it by hand, or give it an updateScript |
| skipped | the bot passes this package over on purpose (the package opts out, GNOME's release cycle, too many rebuilds, ...: the panel says which): while it does, updates are done by hand |
| superseded | the attempt no longer matters: nixpkgs has moved past that version (in the channel, or merged on master), or a manual rule ignores it (`package-lists/ignored-updates.nix`) |
| not attempted | the bot has never tried this package |
| the robot's colour | in front of any of these, where the dot was: nixpkgs-update will try it, from its queue (screen readers say "queued for an update"). Green when to the newest version and its last attempt didn't fail, so its PR should follow; amber when it will try but it's unsure: its last attempt didn't work, it would update to another version, or only the package's updateScript runs, which decides the version (for outdated packages). Hover the cell for which; the update panel says when. When green and nothing's reported, the cell says when instead of "—": **auto update in 4 days** (in green), so you can leave it to the bot. No robot when the bot isn't set to try it and nothing went wrong, or while an update PR is open or merged |
| none reported | the bot opened a PR, found one open, had already pushed the update to its branch, had nothing to update (nothing newer by Nix's version order, say), or finished without a recognisable result (the panel says which) |

The update panel also says when the bot will try the package again, from
[its queue](https://nixpkgs-update-logs.nixos.org/~supervisor/queue.html),
which goes round every 10 days or so, and what it would update it to: a
version it found on GitHub or Repology that nixpkgs doesn't have yet. That
doesn't make the package outdated here (the bot's pick can be wrong). A
package not in the queue has nothing the bot could update it to right now.

## When a source couldn't be reached

A `not refreshed` tag on a build or update cell means Hydra or the update
logs couldn't be reached on the last sync, so it shows the last known result.
The time at the top right is the last sync; it turns pink when that was over
two days ago.

## The tab's icon

It shows what needs attention, so a pinned tab tells you at a
glance: each of the mark's three chevrons lights up for its own signal, the
top right orange for a new release (not counting updates already on master),
the left pink for a failure, the bottom pink for a vulnerability. With none,
the top right is green: all good. It follows the list filter, like the counts.

## The Theme menu

Top right, it picks the page's colours, Classic or
[Catppuccin](https://catppuccin.com) (Latte when light, Mocha when dark), and
light, dark, or Auto (your system's setting). Your choice is kept in your
browser (its local storage, nothing is sent anywhere) and wins over the
page's default, which its owner sets with `page.theme` in the package lists.
The colours keep their meanings in either palette.
