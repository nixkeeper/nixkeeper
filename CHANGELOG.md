# Changelog

Notable changes to nixkeeper. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/) (before 1.0, a minor bump means new
features).

The version lives in `pyproject.toml`; `flake.nix` reads it from there.

## [Unreleased]

### Added

- **Newer version: known / none known** (`?newer=yes`, `?newer=no`), with
  any tile: build failures an update won't fix (`?filter=builds&newer=no`,
  852 rows on 2026-10-23), or that one might and nobody has opened
  (`?newer=yes&refine=nopr`).
- **Show errors** with Build failures or Failed (`?errors=1`): every failing
  package's builds open under its row, with its log's lines, loaded as they
  scroll into view.
- **Can be closed**, on a maintainer's and a team's page: their open update
  PRs nixpkgs is already past (it has the PR's version or a newer one), each
  with what nixpkgs has now, Hide, and a link to all of them. Also a
  **PR to close** filter (`?refine=superseded`), a view of every package
  with one (**Update PRs to close**, `?view=superseded`), the PR in a
  package's details, and its count in "nixpkgs in numbers" (253 PRs on
  2026-10-23, 203 of them the update bot's). Rows have `supersededPRs`;
  `index.json` has `close`.
- Sorting the list: **Sort** (most pressing, longest-standing, newest,
  biggest version gap, name A–Z: `?sort=`) and ↓/↑ reversing it
  (`?order=reverse`), under the tiles. The A–Z button in the header goes:
  name A–Z is one of the orders (`?sort=az` links still work).
- **Open PR: with one / without** (`?refine=nopr` for packages no PR
  touches), instead of the one-sided "With an open PR" chip.
- Typing with a row of the list focused goes into the search, which filters
  as you type. `python3Packages.` finds `python313Packages.…` (as nixpkgs
  titles write it), in the list and in all of nixpkgs, and
  `?in=python3Packages` is every `python3…Packages` set.
- Facets in the list's filters: **in** a package set (`?in=python313Packages`,
  `?in=top-level`) and **by** a maintainer within the list shown
  (`?by=fabaff`, typed or picked from the 300 with the most there), and
  each platform of **on** with its count. Every choice says how many it
  would show with the other filters on.
- Search across all of nixpkgs: its matches beyond the list narrow by
  **in** a package set and **status** (failing, outdated, waiting for the
  channel, up to date, can't be compared, vulnerable: `?status=outdated`),
  each with its count, and show 200 more at a time instead of stopping at
  50. **Clear filters** when they leave none. And by **maintainer**,
  **team** (`?ofteam=`) and **platform**, from a new `facets.json` (every
  package's maintainers, teams and platforms beside `names.json`, about
  120 KB compressed), loaded on the first search.

### Changed

- Several packages open at once: opening one no longer closes the others;
  **Close all** beside the list's count, or Esc, closes them. A package's
  name is a link to it alone (`?pkg=`), for a tab of its own.
- The builds panel brings failures alike together (same reason and log
  lines: python313Packages and python314Packages, on two platforms), their
  log's lines shown once: "the same on all 4".
- A package's details: "On GitHub" labels a few words long ("likely fix",
  "merge-bot ready", "builds now · can close"), the sentence on hover; a
  merged PR's people on its link's hover; no "a draft" (its icon says it).
  The update PR of a vulnerable package is under its vulnerabilities, which
  say what their CVEs share once, group them by the tracker's issue, a line
  each (the worst five, then Show all: zitadel's 24 took 48 lines), and
  short verdicts ("affected", the sentence on hover).
- **Open on GitHub**: GitHub's icons and the counts above 0 ("PRs 2" is
  the PR icon and 2), and "—" when there are none (two thirds of the
  attention list showed "PRs 0 issues 0": two links to an empty search).
  In a package's details, each PR and issue has GitHub's icon too: open,
  draft, merged (in violet), issue.
- Headings in the details, the popovers and the Theme menu ("Maintainers",
  "Outdated since") the size of what they head, in sentence case, instead
  of small capitals a size and a half smaller.
- A package with no maintainer says "none in nixpkgs · see all packages
  without one" instead of "(@none)", which read like a GitHub mention.
- The robot of a "—" the bot is queued for anyway is inside its button
  too, as in every other update cell (the separate robot button is gone).
- The build and update columns: a **hard hat** (Hydra's builders) and a
  **robot** (nixpkgs-update) in place of the dot, then only why ("compile
  error", "patch"; "failure" when the logs don't say), without "failed:"
  on every line (screen readers still hear it). Red for a failure, gold
  for blocked, marked broken or can't update; the update cell's robot in
  the queue's colour (green, amber) when the bot will try it, instead of a
  second robot beside the text.
- The list no longer moves between lists: its
  columns have fixed widths (they were sized to each list's content, and
  Build failures scrolled sideways at 1,280px), the filters' selects too
  (their counts changed their width), and every collapsed row is 78px
  (room for a name or versions on two lines); a long version's badges go
  on a line under it rather than squeezing it into one line per few
  characters. Names with no dot near the column's edge break anywhere.
- Loading: grey shapes where the overview or the list will be (a
  skeleton), the same size as what replaces them, instead of "Loading
  package data…" (screen readers still hear that). Layout shift while
  loading: 0.0006, from 0.013.
- "Where the data is from": its two links on lines of their own.
- The builds panel says each platform once: one badge with why it failed
  ("missing file"; "failed: missing file" for screen readers), "last built
  1 y ago" (the date on hover), its Build and Job at the line's end, and
  "full log ↗" under the log's lines instead of a Log button. No dot, no
  "Failing on 2 of 2" or jobset above the lines, no note that
  x86_64-darwin isn't built any more.
- The update panel leaves out the sentence when its outcome already says
  it ("Failed: build", "Failed: updateScript").
- A package's panel says each thing once: the badge naming where its
  newest version is from links there (the release, the archive, the PR
  merged on master, Repology's project), and the text below only adds what
  it doesn't say. No **Why?** button (that text is always shown), no
  "nixpkgs unstable" line, no Repology button; its repositories only while
  it isn't up to date. Maintainers have their GitHub avatar (loaded only
  while a panel is open, no referrer).
- Links and actions look different: links are text ending in ↗ (Homepage,
  package.nix, Build, Job, "full log"); **Hide** is a small outlined
  button, like the maintainer page's PRs' Hide.
- "Where the data is from" on nixkeeper.com is three lines (the last sync,
  the nixpkgs commit, a link to status.nixkeeper.com, where each digest's
  row now says what the sync read from it); instances of their own keep
  the full list. Why staging-next wasn't used is on the **breaks on
  staging-next** chip's hover.
- "Not fixed on master yet" is **Not merged yet**: it also leaves out
  updates merged into staging, staging-next or a branch like
  haskell-updates (`?refine=notonmaster` unchanged).
- A filter chip that's on ends in ✕, as the list's chip does, instead of
  starting with ✓.
- The line by the logo and the tab's title: "health of every nixpkgs
  package", as nixkeeper.com covers all of nixpkgs now; and the
  description (page, flake, package), in nixpkgs' style (no article, no
  final period): "Health dashboard for every nixpkgs package: new
  releases, build and update failures, vulnerabilities and open PRs, by
  maintainer and team". An instance of its own lists says "health of your
  nixpkgs packages" (set once its data loads; link previews show
  index.html's).
- Screenshots retaken with the new lines. Link previews of nixkeeper.com
  and the release notes' card show the overview's social preview
  ("Health dashboard for every nixpkgs package"); the list's says
  "Health dashboard for your nixpkgs packages".
- **Open on GitHub** counts the PRs about the package (titled with its name
  or an attribute, by nixpkgs' convention) and the issues with its name
  whole in their title, not every title with its name's words: "pkg" was
  120 PRs and 96 issues (pkgs/..., pkg-config), now 2 and 8; 1,409 of the
  13,523 packages needing attention count fewer, 51 a little more
  (2026-10-23). The link searches for the name in quotes, and says when
  GitHub's search shows more. Rows have `searchShowsMore`.

### Fixed

- thunderbird-153 (153.4.0) wasn't outdated in its own series though
  153.5.1 was out: nixpkgs' own thunderbird-esr-bin at 153.5.0 made its
  series 153.4. The next series is now one whose first number differs,
  when nixpkgs has one. And a kept series behind in its own (39, glibmm_2_4
  to go) says so in its details, without the newer series' repositories
  (glibmm 2.90.0 beside glibmm_2_4's newest, 2.66.10).
- firefox-esr read as outdated against Firefox's 158.0.1 and "on master":
  master's `153.5.1esr` was compared with the channel's `153.5.1`, which
  Repology writes without the suffix. A version that only adds a suffix
  Repology drops (not a pre-release's) is the same release, in the sync
  and on the page. And for an older version kept beside a newer one,
  Repology's vulnerable flag no longer counts (firefox-esr, thunderbird-153
  and libxml2_13 flagged by it alone, nothing open in the tracker or OSV),
  nor do its details list the newer series' repositories and betas.
- A package only nixpkgs packages, whose version nothing compared, is grey
  ("only in nixpkgs"), not green: Repology's "unique" with no other
  repository and no update check of nixkeeper's (17,988 packages on
  2026-10-23). The rows say `onlyNixpkgs`; its status letter is `n`.
  Those GitHub's releases confirm stay green: the GitHub releases digest's
  result is now used for them even when it only confirms the version
  (3,488, python313Packages.pbar2).

## [0.21.0] - 2026-10-21

Fewer packages wrongly shown as outdated, over 400 of them: snapshots
spelt differently, versions only nixpkgs' own older channels have (or a
mistake an upstream index contradicts), commits that have no order, and
CUDA's `0-unsupported`, now a status of its own (`unsupported`, grey). One
update moving many packages is **one row** in the list ("+186 like it"),
and "being removed" only shows when the removal looks likely.

### Added

- One update, one row: in the package list, three or more packages one
  update moves together (the same family, status and newest version) are
  one row with "+186 like it", a button showing the others after it.
  fabaff's outdated list: 578 rows to 393 (the 187 huaweicloudsdk*).

### Fixed

- Outdated only by another spelling of the same snapshot
  (`unstable-2022-10-20` against nixpkgs' older channels' `2022-10-20`):
  up to date now. 104 packages on 2026-10-20 (gawkextlib's 17,
  celeste-classic, haste-server...).
- Outdated only by nixpkgs' own earlier version: one only its old release
  channels have (24.05 to 25.11, no longer updated: rPackages' MeSH
  1.15.1, yaziPlugins' old numbering), or one only its release channels
  have while an upstream index (PyPI, CRAN...) has unstable's
  (python3Packages.azure-ai-vision-imageanalysis: 39.0.0 on 25.11 and
  26.05, a mistake reverted to PyPI's 1.0.0). Compared with the other
  repositories instead: 231 packages up to date on 2026-10-20. The newest
  channel ahead with no index saying otherwise still counts (a backport,
  firefly-iii's 6.7.9 on 26.05).
- Outdated only by another commit on a nixpkgs channel (tree-sitter
  grammars' `0.0.0+rev=e45dbac` against 26.05's `rev=9566ca7`, which
  Repology ranks as letters): up to date. 75 packages on 2026-10-20.
- nixpkgs' `0-unsupported` (CUDA packages it doesn't build for its default
  CUDA) is `unsupported`, grey: 14 packages on 2026-10-20, 10 of them outdated before.

### Changed

- "being removed" in the list only when removal looks likely: the removal
  PR has no changes requested and activity in the last 90 days (19 of 26
  on 2026-10-20). Otherwise the panel says "removal proposed (changes
  requested)" or "(no activity since ...)", and `dropPR` carries
  `proposed`.

## [0.20.0] - 2026-10-19

The open PRs a maintainer can merge themselves become a list on their page:
**You can merge these**, the PRs ready for the merge bot that they maintain
every package of, with the comment to post (over 1,000 on nixkeeper.com,
for some 830 maintainers, about 200 waiting over three months). Update PRs
say when they're **behind** upstream or **for a vulnerable package**, and
CVE issues nixkeeper finds fixed are candidates to close. Platforms a
package is listed for but Hydra never builds it on show struck through,
with a list of all 2,600 of them. What you've looked at can be **hidden
until it changes**, packages and PRs alike, in your own browser. The update
column says **auto update in 4 days** when the bot has it in hand, and the
overview ends with **nixpkgs in numbers**.

### Added

- **Hide** on each PR of "You can merge these": it leaves the block, in this
  browser only, until it changes (a newer version in its title, or a CVE),
  with "N hidden · show them" to see them again.
- **nixpkgs in numbers**, at the bottom of the overview: open PRs (12,514
  on 2026-10-19), ready for the merge bot and waiting for their own
  maintainers (1,018), update PRs behind upstream (582), the update bot's
  round (10.8 days), builds not built on Hydra (the top card's, split:
  failing themselves, blocked by a dependency, unfinished), not built
  where listed (2,617), up to date (79%), without a maintainer (14,136).
- **Hide until it changes**, in a package's panel: it leaves your lists,
  in this browser only, until what it needs attention for changes (a
  newer version, another failing build, a new update failure, the broken
  mark, a new CVE; a vulnerable package comes back at the next sync).
  "N hidden · show them" beside the list's count shows them again, greyed.
- **Not built where listed** (`?view=unbuilt`, linked from Marked broken):
  every package nixpkgs lists for a platform Hydra doesn't build it on,
  outside the sets, and with a platform picked, those not built there
  (`?view=unbuilt&platform=darwin`, `aarch64-linux`). On 2026-10-19:
  2,624, of them 2,253 for Darwin and 806 for aarch64-linux. Written by the
  sync (`views/unbuilt.json`) with the same rule as the page's struck tags.
- An issue about CVEs that none affect nixpkgs' version, as nixkeeper reads
  them (fixed or patched), is a candidate to close in the package's panel,
  beside the build and update checks (4 of the 17 open CVE issues on
  2026-10-18, crewai's and urllib3's among them).
- A package marked broken with open PRs says so in its panel (one may fix
  it, or be moot), and **With an open PR** (`?refine=withpr`) keeps only
  packages an open PR touches: with Marked broken, 49 on 2026-10-18.
- An update PR **behind** upstream ("behind: upstream has 7.3.2": merged,
  the package would still be outdated) or **for a vulnerable package**
  (worth reviewing first) says so, in the package's panel and in "You can
  merge these", where those for a vulnerable package come right after the
  maintainer's own. On 2026-10-18, 582 packages' update PRs were behind
  and 110 were for a vulnerable package; of the PRs ready to merge, 44 and
  11. Worked out by the sync from its versions and vulnerabilities
  (`prs_digest.cross_check`), again in the hourly checks.
- "You can merge these" on a maintainer's page: the open PRs they can merge
  themselves with nixpkgs' merge bot (CI green, merge-bot eligible, they
  maintain every package it touches), their own first, then the longest
  waiting, with the comment to post and a button to copy it (the merge bot
  also asks that they be in @NixOS/nixpkgs-maintainers). On a team's
  page, those on the packages nixpkgs lists under the team (`meta.teams`,
  not a list of the same name), with who can merge each. On
  2026-10-18, 479 PRs, for 499 maintainers; 87 waiting over three months.
  "CI passed" is nixpkgs CI's own verdict (its `no PR failures` status), as
  the merge bot reads it, once nixkeeper-prs has it: not every check's,
  which ofborg's, queued for weeks, kept pending for 526 more.
  From nixkeeper-prs' digest (`views/merge.json`).
- start-runs also starts [nixkeeper/status](https://github.com/nixkeeper/status)'
  hourly check, which says on a page whether every workflow, digest and
  token is on time and opens an issue for what needs attention (its token
  needs the status repository too).
- What blocks staging-next: a dependency failing there that stops packages
  building on master says how many in its details ("its failure stops N
  other packages' builds on staging-next"), a package it stops says which
  dependency, and the overview's "Blocking the most" has the top ones on
  staging-next under it (clang-22.0.0-rocm stopped about 750 builds on
  2026-10-16). From nixkeeper-hydra's `staging-next.json.gz`, which now
  names each such build's blocker. A forecast: no count includes it.

- The README and `llms.txt` point to
  [nixkeeper-mcp](https://github.com/nixkeeper/nixkeeper-mcp), an MCP server
  that lets an AI assistant answer questions about nixpkgs packages from
  nixkeeper's data: one package's state, what needs attention for a
  maintainer or a team, build failures, PRs, issues, update attempts, CVEs.


### Changed

- A platform a package is listed for but Hydra doesn't build it on (no
  build exists there, usually as a dependency isn't available there) has
  its tag struck through and dimmed: "Linux · ~~Darwin~~", and "Linux
  x86_64 · ~~aarch64~~" when one Linux system is missing. Picking that
  platform no longer counts it as available there, and **Not built where
  listed** (`?refine=unbuilt`) finds them: on 2026-10-19, 1,659 listed for
  Darwin and about 900 for aarch64-linux alone, among packages outside the
  sets.
- When nixpkgs-update is set to update a package to the newest version (the
  green robot) and nothing's reported, its update cell says when instead of
  "—": **auto update in 4 days**, in green, so it's clear the bot has it
  in hand. The list's entries carry the queue's day (`queued.by`) for it.
- The overview's "Blocking the most" switches between master and
  staging-next ("Master | Next") as the other lists switch between newest
  and oldest, instead of a line under it: the line, its names wrapping,
  made the card taller and left an empty band under the build failures,
  outdated and update failures beside it. Without staging-next data (as
  between a cycle's merge and Hydra's evaluation of the next), no switch.

### Fixed

- A package nixpkgs doesn't restrict to platforms ("any platform") that
  Hydra doesn't build somewhere shows the struck tags too ("Linux ·
  ~~Darwin~~", fzssh's), not "any platform" (334 on 2026-10-19).
- Where the data is from: the digests under their names since the move to
  the nixkeeper organisation (digest-builds, not nixkeeper-hydra); Hydra's
  evaluations named by branch (master, staging-next, haskell-updates), each
  linking to its jobset; staging-next's evaluation and the PRs merged into
  staging or staging-next listed; "Last sync", not "Daily sync" (every 3
  hours on nixkeeper.com).

- Once a staging-next cycle is merged into master, what Hydra's last
  evaluation of it said (what breaks there, what blocks it, how an update
  builds there) is no longer shown as a forecast: it's master's now. Until
  Hydra evaluates the next cycle, there's none. After #571813's merge on
  2026-10-16, 86 packages still said they'd break "when staging-next is
  merged", and 302 that they were stopped there.

- An outdated package's newest version isn't one distribution's packaging
  of it, a part added to a release more distributions have: curl 8.23.0,
  not Baulk's 8.23.0.1; rakudo 2026.09, not AUR's 2026.09_01; yacreader
  10.4.0, not a build number (9 packages on 2026-10-16). Not when that
  would leave nothing newer than nixpkgs' version: then the added part may
  be a real release, seen first in one distribution.

## [0.19.0] - 2026-10-16

Mass rebuilds become visible on their way to master. An update merged into
**staging or staging-next** says where it is (bash, coreutils, curl and
about 100 others had shown nothing for weeks), and on staging-next whether
it builds there. A package that builds on master but fails on staging-next
is flagged in its details, with a filter to find them: **what breaks when
staging-next is merged**, before it does. Kept older series (python313,
firefox-esr, glibmm_2_4) are compared within their own series, and count as
outdated when a newer release of that series is out. Update PRs are found
however their titles are written. On phones, pages no longer open zoomed
out, and the cards line up.

### Added

- What staging-next will break: a package that builds on master but fails
  its own build on staging-next, at the same version, in Hydra's newest
  evaluation of it, says so in its details (each failing build linked,
  the evaluation's day, the staging-next PR it arrives with), and the
  "Breaks on staging-next" filter (`?refine=stagingnext`) finds them in a
  maintainer's or a team's list: 314 packages on 2026-10-16, most of them
  Python. Unless fixed, they fail on master when staging-next is merged.
  A forecast: no count includes it, and a fix may already be on staging.
  Not a dependency's failure (that's the dependency's to fix), nor an
  update in progress there.

- An update on staging-next says how it builds there, from Hydra's newest
  evaluation of staging-next (about daily, its day said): on every
  platform, failing where (each build linked), not built yet, or not in
  that evaluation yet. From nixkeeper-hydra's new `staging-next.json.gz`
  (the jobs that differ from master); 54 of the 64 updates there built
  everywhere in the 2026-10-14 evaluation, systemd 262, openssh 10.6p1
  and vim each failing on a platform.
  When staging-next has already moved past the PR's version, it says so
  and how that newer one builds (harfbuzz: a PR to 14.5.0, staging-next
  at 14.5.1), rather than "isn't in the evaluation yet".

- An update merged into staging or staging-next, the branches mass rebuilds
  go through, shows where it is: `on staging` or `on staging-next` instead
  of nothing for the two or three weeks it takes to reach master, and in
  the details, since when and with which staging-next it arrives (bash,
  coreutils, curl, cmake, expat and about 100 others on 2026-10-16). From
  nixkeeper-prs' new staging list (`stagingPR`); still outdated until
  master has it, and the update bot's icon isn't shown for it.

- `llms.txt` beside the page (nixkeeper.com/llms.txt): for AI assistants
  and tools, what nixkeeper is, the page's addresses, where the data and the
  digests are and how to read them (the page itself is drawn by JavaScript),
  and that its suggestions are hints for a person to check.

### Changed

- In the table, an update's badge (its PR, "on master", or the branch that
  has it) that's the version's only badge sits between the two versions,
  level with the row's PR and issue counts, rather than beside the newest
  version below them. With other badges, and on phones and tablets (the
  counts on a line of their own), where it was.

- On phones and tablets, a package's PR and issue counts are on a line of
  their own in every card, not beside the build when it happened to fit
  (cards looked uneven), and a badge that's a link (an update PR) is a pill
  like the others: its tap area made 32px tall had made it an oval with
  its text at the top. The tap area is still that size.

- A phone no longer shows a team's, a maintainer's or a package's page
  zoomed out: the team's or maintainer's box was as wide as its row of
  filters (about 1,400px, which now swipes sideways on its own), and a
  package's panel as wide as its longest source label (which now ends in
  "…", in full on hover). A version too long for its card breaks rather
  than push the card's badges past its edge.

- A staging-next merge's mark on the trends is solid, a counting change's
  still dashed: at a sparkline's size their grey and amber were hard to
  tell apart. The key under the cards matches.

- An older series nixpkgs keeps beside a newer one is outdated when a newer
  release is out in its own series, as the page always said ("not outdated
  while nothing newer is out in its own series"): glibmm_2_4 2.66.8 with
  2.66.10 out, tcl 8.6.16 (8.6.18), electron_40, thunderbird-153, go 1.26,
  django 5.2 (40 packages on 2026-10-15). It's still named beside the newer
  one, and kept again once the channel has its series' newest. Counted only
  on good evidence: two distributions or more besides nixpkgs (debian_13
  and debian_unstable are one), the newest of them but not a packaging's
  added part (ruby 3.4.11, not Chocolatey's 3.4.11.1), in the version's
  shape, no pre-release, packaging revision or added part, not
  for an attribute naming its whole version (sbcl_2_4_6), and for a series
  not named by its attribute, of three parts or more, its major.minor
  (linux 6.18, not 6.19). Marked on the trends as a counting change.
  nixkeeper's own release checks, which can't tell a series, leave such a
  series' target alone as they do a kept one's: electron_42 42.11.10
  suggests 42.11.14, not Electron's newest, 44.7.2 (and electron 43,
  libtorrent-rasterbar-1_2_x, cython, django 5.2 on the first sync).

- The overview's lists (the newest and longest-standing, what was fixed)
  show packages one update moves together as one line, with how many: the
  same package file in nixpkgs, version and homepage (the rows'
  `family`), like the 187 `python313Packages.huaweicloudsdk*` packages or a
  kernel module once per kernel, which filled a list of 8 by themselves.
  The line opens a search for them. Fixes are grouped from the sync after
  the one that marks the families. The cards still count packages.

### Fixed

- An update PR is found wherever its title makes the update: after
  another change ("minimage: init at 0.1.4; d-seams: 2.10.0 -> 2.11.0"),
  or for one of several names ("chromium,chromedriver: ... -> ...", "goose-
  cli, goose-desktop: ..."): 15 more packages with their update PR on
  2026-10-16 (d-seams, gnome-graphs, bcftools and htslib, torch, ...).

- A package Repology calls outdated without naming a newer version (in
  its "-unclassified" projects, every repository outdated) no longer shows
  "newer version unknown" when an update PR of it, merged or open, brings
  one: that version (chatgpt 26.1013.31256, swift 6.4.0: 8 packages on
  2026-10-16), the details saying it's the PR's. The other 150 stay
  unknown: the newer versions other repositories have there are mostly
  other software of the same name.

- An update PR whose title goes on after the version ("fribidi: 1.0.16 ->
  1.0.17, also fix cross", "python313: ... -> 3.13.16; ...") gives that
  version without the comma or semicolon: 103 PR badges and notes said
  "9.3.0," or "1.3.2;" (shipwright, vtk, barman, ...) on 2026-10-16.

- A package's open update PR is found when its title names another of the
  package's attributes, all at its one version: heroic's update is titled
  "heroic-unwrapped: 2.22.3 -> 2.22.4", and showed only under "On GitHub",
  not as the update PR. The same for firefoxpwa, rust-bindgen, dart
  (dart-bin), quarto (quartoMinimal) and others (25 on 2026-10-15), and
  for update PRs merged into master.

- A package Repology calls outdated only because one distribution packages
  a snapshot of the same release, its version with a date added, is the
  newest: python3Packages.mintotp 0.3.0, against SlackBuilds' git snapshot
  0.3.0.20240120 (also langid, hg-git and rcshist: 4 packages on
  2026-10-15). Not when an upstream index has the version (iso4217's
  1.16.20260101 is a release on PyPI), nor when two distributions or more
  do (fcitx5-pinyin-zhwiki's 0.3.0.20260416). Marked on the trends as a
  counting change.

- An older series nixpkgs keeps beside a newer one (python313 beside
  python315), and behind in its own series, is compared within it:
  python313 3.13.15 suggests 3.13.16, not Python's newest, 3.15.0; the same
  for python3 and python314 (3.14.8), mariadb's series, ffmpeg_8, lua5_4,
  gtkmm3 and others (33 on 2026-10-15). Still outdated; only the version it
  points to changes.
  The same evidence rules as for a kept series, except one distribution is
  enough: libsigcxx_2_0 2.12.1 suggests 2.12.2, not 2.99.13 (sigc++ 3's
  previews), vlc-bin 3.0.24, not 3.0.23_2.

- A release Repology calls legacy only because nixpkgs also packages its
  beta (firefox 157.0.1 beside firefox-devedition 158.0b1) is the main
  line: outdated when a newer release is out (Firefox 158.0), so its update,
  once merged, shows as on master. It never counted as outdated before. 3
  packages on 2026-10-15 (firefox, hbase, premake). Marked on the trends as
  a counting change, with the coq fix.
  A version named a release (godot's 4.7.2-stable, whisparr's
  3.6.2-release.1727) isn't taken for a beta: the 2026-10-15 13:14 sync
  showed 40 kept godot series (godot3, godot_4_3 to godot_4_6 and their
  templates and mono builds) and 2 others as outdated against 4.7.2; they
  are kept again.

- godot 4.7.2-stable is no longer outdated against 4.7.2: Repology ranks a
  word naming the release ("stable") lower, so it called nixpkgs' godot
  (and godot_4, godot_4_7) outdated since nixkeeper began. Only when that
  word is the whole difference.

- A kept series names the release it's kept beside at the channel's
  version, as that release's own row shows it, not Repology's older one
  (firefox-esr beside firefox 158.0, not 157.0.1; kernel modules beside the
  newest kernel's: 206 on 2026-10-15). Nothing counts differently.

- A package shown at the channel's version, newer than Repology's, no
  longer carries Repology's vulnerable flag, which was for Repology's
  version (firefox-esr 153.5.0esr was flagged for 153.4.0's CVEs); the
  NixOS security tracker's and OSV's verdicts are checked against the
  version shown. A kept series names the release it's kept beside rather
  than a beta (firefox-esr beside firefox, not firefox-devedition).

- A kept older series (firefox-esr beside Firefox, a kernel module for an
  older kernel) shows the channel's version when Repology is behind, as
  other packages do: firefox-esr showed Repology's 153.4.0 while
  nixos-unstable had 153.5.0esr, and its vulnerable flag with it (108
  such on 2026-10-15). Its status stays a kept series.

- A Repology project of kept series only (coq's, since its current
  version moved to rocq) takes its newest series as the stable one, not the
  shortest name: every newer series (`coq_8_8` to `coq_8_20`) had become a
  devel variant behind the newest and counted as outdated, filling the
  overview's newest outdated.

## [0.18.0] - 2026-10-14

Ready to be shown around. A live dashboard of lists,
[demo.nixkeeper.com](https://demo.nixkeeper.com/), sits beside the
community one to compare, and a copy of the repository no longer opens the
community's subscribers' issues. **Questions and feedback** go to
Discussions, under the NixOS community's code of conduct. The docs a
newcomer reads are rewritten: the README, Reading the page (in sections),
a dashboard of your own (tried on a fresh account), and new screenshots of
both views. On phones, a list no longer starts with an empty band, and a
link to a package opens its details. Why things fail files kernel modules
under the kernel's change, not the compiler's.

### Changed

- The repository's front door: questions, ideas and feedback go to
  [Discussions](https://github.com/nixkeeper/nixkeeper/discussions) (the
  issue forms and the README link there); "Something looks wrong" asks
  where it was seen (nixkeeper.com, the demo, or a copy) and says how fresh
  the data is; "Track a package" is gone (nixkeeper.com tracks every
  package); "Get notified" is among the issue links. A code of conduct (the
  NixOS community's), the digests in SECURITY.md's scope, and the README
  says nixkeeper isn't affiliated with the NixOS Foundation. The pull
  request template says what a subscription or a community rule needs (just
  why), and asks for `nix flake check` and `docs/command.md` too.

- `nix run .#screenshots` takes both sets in nixkeeper's repository: the
  overview's from the community instance's data and the list's from the
  demo's (demo.nixkeeper.com), with `--overview-data` and `--list-data` to
  point either elsewhere (or `none`); a copy still takes its own data's
  set, and `--data` one data alone, as before. The list's panel opens on the
  4th row by default (was the 10th, below the shot since the rows grew).

- A copy of this repository no longer opens status issues for the
  maintainers and teams in `notifications/`: those files are the community
  instance's subscribers, and a copy's syncs opened their issues and
  mentioned them. They're read with every package (the community instance)
  or where `NIXKEEPER_SUBSCRIBERS` is `true` (a copy with subscribers of its
  own). A copy's own status issue is as before. The guide to a dashboard of
  your own loses its "delete these files" step, and links
  [demo.nixkeeper.com](https://demo.nixkeeper.com/), a live dashboard of
  lists, to compare with nixkeeper.com.

- With the repository variable `NIXKEEPER_STARTED_OUTSIDE` set (the
  community instance: start-runs starts its syncs), the sync's own schedule
  is only the fallback: a scheduled run syncs when the last sync is over the
  interval and half an hour old, so GitHub's late runs no longer take the
  outside start's turn (2026-10-14: a sync at 08:18, the 09:15 start
  skipped, the next at 12:15). Without it, as before.

### Fixed

- A link to one package (`?pkg=firefox`, and the overview's package links)
  opens its details: it showed the package alone with its panel closed, one
  more tap, on a phone the whole screen's worth. Closed, they stay closed.

- On phones and narrow windows, the ways to narrow a list (Without
  maintainer, Older than...) stay in the counts' sideways row: they wrapped
  into a column that left a tall empty band above the list.

- **Why things fail**: a kernel module failing with an implicit function
  declaration or incompatible pointer types is under "Kernel driver vs. a
  newer kernel's API" (the kernel dropped the function or changed the
  callback), not "Implicit function declarations (C23 by default)" or
  "Incompatible pointer types (newer compiler)": on 2026-10-14, 47 kernel
  modules of those two groups' 61 packages. And the same error is one
  group whether its log names the file with its directory or not
  (`/build/source/src/foo.c:12:3` and `foo.c:12:3`): "use of undeclared
  identifier" was split in three.

## [0.17.0] - 2026-10-14

nixkeeper moves to the **nixkeeper organisation** on GitHub
(`github:nixkeeper/nixkeeper`), its digests beside it and named by what
they hold; the old addresses keep working. **Recently fixed** lists the
week's longest-standing fixes, saying how long each had lasted, instead of
the last sync's. New GitHub releases and Repology's verdicts are at most
12 hours old instead of a day (up to a week for releases).

### Changed

- nixkeeper lives in the [nixkeeper organisation](https://github.com/nixkeeper)
  on GitHub: `github.com/nixkeeper/nixkeeper`, and its digests beside it,
  named by what they hold (`digest-builds`, was nixkeeper-hydra;
  `digest-versions`; `digest-update-bot`, was nixkeeper-updates;
  `digest-vulnerabilities`; `digest-prs`). The old addresses redirect
  (`github:iedame/nixkeeper` still works, and earlier releases keep
  reading the digests), but name the new one:
  `inputs.nixkeeper.url = "github:nixkeeper/nixkeeper"`. `start-runs`
  starts the organisation's runs by default, and needs a token that can
  (a start through GitHub's API doesn't follow the redirect).

- The overview's **Recently fixed** lists the week's fixes that took
  longest first, each saying how long it had been failing or outdated
  ("after 5 m"; hover for the dates), instead of the newest: with a
  hundred fixes a day those were always the last sync's, all "<1 d". A
  package's panel says it too ("Build fixed on Oct 9 (after 5 m)"). For
  fixes from now on (a build's from Hydra's last success; an outdated
  package's from when nixkeeper first saw it so); the ones recorded before
  come after, newest first, as they were.

- The overview's newest and longest-standing outdated packages leave out
  those whose update is already merged and only waits for the channel:
  nothing to do about them (they stay in the card's count, and in its
  list). The cards' heading says how many days their trends span ("last 9
  days") instead of "since Oct 5" until there were 30.

- `start-runs` starts nixkeeper-versions' digest every 12 hours (04 and 16
  UTC, if its last run is over 10 hours old) instead of daily: Repology's
  verdicts at most 12 hours old, and, the digest now reading every GitHub
  repository each run instead of weekly, a new release shows within 12
  hours (vacuum-tube 2.0.0 would have waited up to a week).

## [0.16.0] - 2026-10-11

nixpkgs' open PRs and issues come from the new nixkeeper-prs digest, and a
package's panel says what it found **On GitHub**: an update PR ready for
the merge bot or blocking the update bot, issues that look done, a package
**being removed**. **GitHub releases** are read for every package, not
only the lists'. The overview says **why things fail** (failed builds
grouped by the same error, the update bot's failures by cause) and gives
**credit for fixes** (who opened and merged each one). The community
instance syncs **every 3 hours** instead of daily, asking its sources no
more often than before.

### Added

- **Why things fail**, on the overview: failed builds grouped by the same
  error (the line of their log that says why, paths, numbers and names
  left out), so one cause breaking many packages shows as one line ("Broken
  by the abseil-cpp update", "Python module missing: pkg_resources": 32,
  "Implicit function declarations (C23 by default)": 42), friendly titles
  where the pattern is known, else the error line; each opens its packages
  (`?cause=`). Automatic: a new compiler or library breaking packages the
  same way is a new group on the next sync. Beside it, why the update bot
  fails, by cause, each opening its packages.

- **Credit for fixes**: each update fixed is credited to its update PR, with
  who opened it and who merged it (from nixkeeper-prs); a build fixed,
  likely, to the PR merged since it began failing that touched it (not a
  treewide change in passing, nor one marking packages broken). The
  overview's "Recently fixed" shows who (hover for the PR, and who merged
  it); a package's panel says its fixes of the last month ("Updated 1.9.0 →
  1.10.0 on Oct 9, in #N, by @alice, merged by @bob"), who opened and
  merged an update waiting on master for the channel, and, while its build
  fails, a likely fix waiting for Hydra under On GitHub. Credit starts with
  fixes from now on.

- GitHub releases for every package fetched from GitHub, from
  nixkeeper-versions' digest: the update check nixkeeper works out from a
  package's source, until now for the lists' packages only, now for all of
  nixpkgs (33,816 packages on 2026-10-09), read in bulk instead of one
  request each. Like the worked-out checks before it, it only adds a newer
  version Repology hasn't seen (about 1,650 more outdated packages on
  nixkeeper.com), and never makes one Repology calls outdated up to date,
  nor counts a newer release for a version nixpkgs keeps on purpose beside
  a newer one (fuse 2, `llvmPackages_18`). Coq and Rocq libraries, released
  for each version of the prover, stay with Repology. An up-to-date rule
  naming a version (`newest`) now also silences a worked-out check that
  finds it, as it does Repology's. A
  release is preferred over a newer tag, which the panel mentions ("Tagged
  2.4.0 on GitHub, not released yet"). The sync still checks the lists'
  packages itself when the digest read them over a day ago.

- **On GitHub**, in a package's panel: what nixkeeper-prs found of its
  PRs and issues. Its update PR ready for the merge bot (or eligible),
  overtaken or a downgrade, blocking the update bot (and when the bot
  would try), or duplicated by another; open PRs touching it while its
  build fails on Hydra; and its issues with something to do, a build
  failure that builds on Hydra now or an update request nixpkgs has met
  (candidates to close), or one still failing; and its other open PRs, a
  removal first. A package an open PR removes from nixpkgs says **being
  removed** in the list (43 on 2026-10-09). The hourly PR check keeps an
  update PR's facts while it finds the same PR.

### Changed

- The hourly PR check takes every outdated package's update PRs (open,
  merged into master, and what nixkeeper-prs found of them) from
  nixkeeper-prs' digest: with every package, all of nixpkgs' every hour
  instead of the lists' only, with no search. The maintainers' own packages
  (the "maintained" list) are still searched for directly, for the
  freshest "on master" (the digest is up to an hour old); other lists' and
  teams' aren't, so they can grow freely. Without a usable digest, as
  before.

- The sync workflow ("Data: sync", still `data-daily.yml`) starts every 3
  hours and syncs when the last sync is due: every 3 hours on the community
  instance (nixkeeper.com: builds, vulnerabilities, bot attempts, PRs and
  GitHub releases at most ~3 hours old instead of up to a day), daily on a
  fork, or every `NIXKEEPER_SYNC_HOURS` (a repository variable). The 14:00
  catch-up is gone: a skipped run is caught up within 3 hours. `start-runs`
  starts it every 3 hours (if_older "auto"), the hourly updates the other
  hours.

- The marks on the overview's trends: a change in how nixkeeper counts is
  amber, a staging-next merge grey, and nixkeeper's own releases aren't
  drawn (the footer says the version; a release that changes counting has
  its own mark). The legend under the cards is one short line, a label per
  kind with its days ("counting changed Oct 6, Oct 7"); hover a day for
  what happened (a staging-next day links its PR).

- What's asked daily, or every 3 days when quiet, counts time, not syncs:
  a sync run several times a day asks Hydra, Repology and the update
  checks no more often than a daily one (a quiet package once on its slot
  day; one with something going on once every 22 hours), and what changed
  (a version moved, a new package, an edited rule) at once. nixpkgs'
  evaluations (`meta.broken`, the sources worked-out checks come from, CVE
  patches) are kept between syncs while the channel's commit hasn't moved
  (`data/evaluations.json`). Ready for syncing more often than daily.

- nixpkgs' open PRs and issues, and the PRs merged into master since the
  channel's commit, come from nixkeeper-prs' digest (made hourly) instead
  of the sync listing them itself: no GitHub token is needed for a
  package's PR and issue counts, its open update PR and its update merged
  into master. The sync lists them itself, as before, when the digest is
  over 6 hours old or its merged PRs were listed since another channel
  commit (`NIXKEEPER_PRS_DIGEST=""` turns it off). "checked … ago" shows it
  under nixkeeper-prs.

### Fixed

- A package nixpkgs has, whose Repology project lists other repositories
  only, no longer shows as not packaged: Repology leaves out nixpkgs
  packages whose version it can't read (keeperrl "alpha34", airstrike
  "pre6a"), and a list's package looked up by name found the project of
  that name without it. It shows nixpkgs' version, not compared ("not on
  Repology"), as a package Repology doesn't know at all.

## [0.15.0] - 2026-10-09

Vulnerabilities come from the NixOS security tracker and OSV, through the
new nixkeeper-vulnerabilities digest, with nixkeeper's own check of
nixpkgs' current version against each CVE (unstable and the newest
release), patches named after a CVE counted as fixes, and **fixes to
backport** as a list, a tile and a note under Vulnerable. Failures say
why: **Build failed because** (from Hydra's logs, read by
nixkeeper-hydra) beside **Update failed because** (`?updateFailed=`,
with a `bot` reason for the update bot's own outages). A package's
version is the channel's own when Repology hasn't caught up. The logo goes
back to the overview.

### Changed

- `start-runs` also starts nixkeeper-prs' digest every hour (a digest of
  nixpkgs' open pull requests, a proof of concept for now). Its token
  needs that repository too.

- A package's nixpkgs version is the nixos-unstable channel's own when
  Repology hasn't caught up with it yet: Repology reads the channel some
  hours after it moves (and nixkeeper-versions' digest reads Repology once
  a day), so a package updated in the channel still read as outdated until
  then (microsoft-edge 154.0.4258.62, 2026-10-08). The sync compares the
  channel's package index, which it reads anyway, with Repology's version,
  and works out again whether it's outdated (2026-10-08: 392 packages
  behind on Repology, 148 of them no longer outdated). `repologyVersion`
  keeps what Repology had. The hourly frequent check, which doesn't read
  the index, keeps the version the daily sync took from it.

- A CVE nixpkgs fixes with a patch named after it (`CVE-2026-56391.patch`,
  a `fetchpatch` of upstream's fix), without a new version, isn't counted:
  the daily sync evaluates the `patches` of the packages with a counted CVE
  (about 20 seconds), and of those to backport on nixos-26.05, where a
  patch means it was backported already (2026-10-08: 28 packages patched
  on unstable, coreutils, cpio, gzip...; 10 already patched in 26.05,
  pretix's 6 CVEs among them). Their verdict is `patched`, folded with the
  others not counted. A fix whose patch doesn't name the CVE still isn't
  seen.

- A CVE's verdict is nixkeeper's own check of nixpkgs' **current** version
  against the CVE's affected ranges: the NixOS security tracker's status is
  that same check, but on the version a branch had when it last evaluated
  the package, often before a fix (2026-10-08: 487 of its 873 "affected on
  master" already fixed in nixpkgs, adguardhome 0.107.79 against
  `<0.107.77`). Its status is used only for ranges nixkeeper can't read
  (`tracker`). Fixes to backport likewise go by the version nixos-26.05
  has now (its channel's package index, read by the daily sync), not the
  tracker's 26.05 status (flatpak: 1.18.4 now, the tracker's 1.16.6). On
  2026-10-08's data: vulnerable 848 → about 682; fixes to backport from
  51 (19 of which already fixed in 26.05) to over 135 (most of the new
  ones hidden before behind a stale "affected on master").

- Opening a list from the overview (a card, "needs attention", "Show
  all") starts at the top of the page: its tiles were under the sticky top
  bar. The overview's cards keep their big numbers on one line, whatever
  they hold under them.

### Added

- **Why builds failed**, from their logs on Hydra (nixkeeper-hydra reads
  each failed build's log once and classifies it, with rules from
  nixpkgs-failure-dashboard's): a **Build failed because** filter
  (`?buildFailed=cmake4`) beside the update failures' (now **Update failed
  because**), the reason on the list's build button ("failed: CMake 4")
  when a package's failed builds share one, and in the builds panel each
  build's reason with the log's lines that say so. Builds whose logs
  nixkeeper-hydra hasn't read yet say "not read yet" (its first pass over
  ~3,000 failed jobs takes a few hours). `failedBecause` and
  `failedExcerpt` on builds.

- The nixkeeper logo goes back to the overview from anywhere on the page,
  with every filter, search, sort, page and open package dropped (a page
  load). Only the parameters saying where the data lives (`?data=`,
  `?owner=&repo=`) are kept, so a copy pointed at other data stays on it.

- **Failed because** (`?updateFailed=patch`; `?because=`, its name for a
  few hours, still read), narrowing any list to the update
  failures of one reason, as nixpkgs-update's log says (build,
  updateScript, source, dependency, patch, unavailable, tests, hash,
  request, "build, no log", other), each with how many there are in the
  list, the commonest first: on 2026-10-08, of 5,784 update failures,
  1,976 build, 880 updateScript, 789 source, 638 dependency, 506 patch.
- A new reason, **bot**: the bot's own machine failed ("the build users
  group 'nixbld' has no members", its nix daemon unreachable), not the
  package: 1,306 of 2026-10-08's "build" failures, all from four hours on
  2026-09-28 (an outage, fixed the same day, which the bot's next round
  clears). Still update failures, so a new outage stands out: within 3
  days, the details link nixpkgs-update's issues to tell its maintainers;
  older, they say it was a past problem of the bot's. Worked out from the excerpts already read (nothing
  read again), and by the log rules from now on.

- **Fixes to backport**: packages with a CVE that's fixed on nixpkgs master
  but still affected on the newest release branch the NixOS security
  tracker evaluates (26.05): they need attention (in that list even when
  nixos-unstable is fine), with a **Fixes to backport** tile next to
  Vulnerable (`?filter=backport`, on maintainer and team pages too), and
  their own list (`?view=backport`). On the overview, a note under
  Vulnerable ("189 fixed, to backport to 26.05"): not part of its count,
  as unstable has the fix. The details say which CVE and branch.
  `backport` on rows, `counts.backport`, `views/backport.json`, and
  `sources.tracker.release`.
- Status issues name a package's CVEs: up to three, each with its severity
  and the security tracker's issue (linked on the tracker, never the
  nixpkgs issue: no "mentioned" lines there), and comment when a package
  is vulnerable to a CVE it wasn't before, not only when it first becomes
  vulnerable. Repology's flag is said as Repology's.

- What's vulnerable comes from the NixOS security tracker and OSV too, read
  from nixkeeper-vulnerabilities' digest by the daily sync (once it has
  read the tracker through, while under 3 days old): the CVEs the tracker
  matched to nixpkgs packages, and OSV's advisories for language packages
  (PyPI, Hackage, CRAN, RubyGems, opam). A CVE counts when the tracker
  says the package is affected on nixpkgs master, or, when it can't say
  (most of them), nixpkgs' version is in the CVE's affected range; the
  security team's "won't fix" counts, "not affected" doesn't; an OSV
  advisory counts when it lists nixpkgs' version (not for a CVE the
  tracker has). nixpkgs' own insecure mark and Repology's flag still
  count: the tracker's entries cover some of a package's CVEs, not
  necessarily Repology's. The "vulnerable" badge says who says so and is
  coloured by the worst severity (critical/high red, medium orange, low
  grey), the vulnerable list goes worst first, and the details list each
  CVE: severity, verdict, the tracker's `NIXPKGS-…` issue and its nixpkgs
  issue, and the release branches still affected (a fix to backport).
  "Needs attention" on 2026-10-08: 599 vulnerable instead of 355. Rows
  have `vulnerabilities`, the lists' entries `vuln`; the sources panel
  lists the tracker and OSV (`docs/data.md`).

## [0.14.1] - 2026-10-08

The release 0.14.0 was meant to be: its tag went on the wrong commit (see
below). Nothing differs from what 0.14.0 was to have, apart from the
version.

nixkeeper relies less on Repology: R, Haskell (Stackage LTS and
haskell-updates), Emacs and Typst packages are compared with their own
sources, a package's own update check decides where it and Repology
disagree, and versions are ordered as Repology orders them. Anyone can
get a **status issue** for their packages or their team's
(`notifications/`). Build failures say how long they've really failed
(Hydra's last success, for every package) and where a build **never**
succeeded; packages nixpkgs marks insecure count as vulnerable. Lists can
leave out a team's or a maintainer's packages, or keep only what a
maintainer looks after themselves (**Not via a team**); a maintainer's page
is at `?maintainer=`. The page says Darwin, as nixpkgs does, and Linux by
system; the package panels are redesigned, and lists load faster.

### Added

- Packages compared with their own sources instead of Repology, read daily
  by nixkeeper-versions; rows have `feed` (`docs/data.md`), the panel says
  the source's newest version, and the sources panel when it was read:
  - **R** with CRAN, or the Bioconductor release nixpkgs pins (3.23), from
    their index files (`cran.json.gz`), as nixpkgs' own update script
    does. It agrees with Repology on current packages, and catches
    Bioconductor patch releases Repology doesn't flag. A package on
    neither any more (archived by CRAN, dropped by Bioconductor) shows
    "archived" where Repology could only say "unique": 6,004 on
    2026-10-07, nearly all of which nixpkgs marks broken already; R's card
    on the overview counts the 163 it doesn't ("6,004 archived (163 not
    marked broken)"). Rows have `archived`.
  - **Haskell** packages nixpkgs pins to Stackage LTS (about 3,400, its
    `stackage.yaml`) with that series' newest snapshot instead of
    Hackage's newest, which Stackage holds back on purpose until its next
    series (`stackage.json.gz`): outdated when behind the snapshot
    (nixpkgs follows LTS 24.38; 24.62 is out), and at it, a "Stackage LTS"
    badge when Hackage has newer, instead of outdated. On 2026-10-07,
    Haskell's outdated from 1,084 to 984: 237 behind their LTS snapshot,
    406 held back by Stackage no longer counted.
  - **Emacs** packages with the archives nixpkgs makes them from
    (`emacs.json.gz`; Repology can't compare MELPA's date versions,
    "untrusted"): MELPA when its version is MELPA's, else the first of
    MELPA Stable, NonGNU ELPA and GNU ELPA that has it, as nixpkgs layers
    them; its hand-written packages keep Repology's verdict. On
    2026-10-07, 6,722 of 6,804 Emacs rows compared (2,984 before), 310
    outdated (34 before). The panel says MELPA's versions as days ("a build
    from Sep 23; nixpkgs' is from Sep 11").
  - **Typst** packages with Typst Universe (`typst.json.gz`; Repology saw
    nixpkgs alone, "unique", for most): each package's latest attribute is
    outdated or newest against Universe's newest version, its versioned
    ones older versions kept. On 2026-10-07, 89 of 4,900 Typst rows
    outdated, where Repology could compare none.

  The version sources share one module (`sources/feeds.py`).
- Haskell packages say what **haskell-updates** has, the branch where the
  Haskell team updates them before merging into master about every two
  weeks (its Hydra jobset, from nixkeeper-hydra's `haskell-updates.json.gz`):
  an outdated package already updated there gets an "on haskell-updates"
  badge, as one merged on master gets "on master", and its panel says the
  branch's version and how it builds there: waiting for the merge, fixed
  there, failing there too, or breaking when the branch merges. Haskell's
  card on the overview counts those updated there ("1,092 outdated, 564 on
  haskell-updates" on 2026-10-07). Rows have `branch` (`docs/data.md`).
- **Status issues for any maintainer or team**: a file in `notifications/`
  (`maintainers/iedame.nix`: `{ maintainer = "iedame"; }`;
  `teams/gaming.nix`: `{ team = "Gaming"; mention = [ ... ]; }`) opens
  "nixkeeper status: @iedame" or "nixkeeper status: Gaming team",
  rewritten by every daily sync with only their packages (not the sets
  updated in bulk) and commenting when something newly needs attention
  (the hourly checks too, for what's new); the issue mentions them, which
  subscribes them, and links their page. Removing the file closes it. You
  can only add yourself: CI checks that each handle a pull request newly
  mentions is its author, and that its handles and teams are
  nixos-unstable's (`scripts/check-notifications.py`); `nix flake check`
  checks the files' format (`nix/notifications.nix`). The instance's own
  status issue can be turned off (`statusIssue = false;` in the lists; the
  sync closes it): this one's is. See
  [docs/notifications.md](docs/notifications.md).
- **Never built**: where a failing build never succeeded on Hydra
  (`neverBuiltOn` in the data: its systems). The build column says where
  instead of "failure reported" ("never: darwin", "never: aarch64-linux",
  "never: linux" for both Linux systems), the package's other failures in
  its panel. Such a build has no date: when it's all that fails, the list
  shows "n/a" where it shows how long a package has failed, and the
  overview's longest-standing build failures leave it out. "Older than"
  has **never built** (`?age=never`; with **On**, only those that never
  built there), and 2 or 3 years too.
- Packages **nixpkgs itself marks insecure** (`meta.knownVulnerabilities`,
  read from the package index the sync already downloads: 109 on
  2026-10-08, 59 of them not flagged by Repology) count as vulnerable: an
  "insecure" badge, nixpkgs' reasons in the details (CVE ids linked to
  NVD), the vulnerable filter and count, the tab's icon, and
  notifications ("marked insecure in nixpkgs"). `markedInsecure` in the
  data.
- Lists narrowed **by people**, in the address:
  - `?team=-Geospatial` leaves a team's packages out of any list (several:
    `team=-Geospatial,-Gaming`), and `?maintainer=-iedame` a maintainer's
    (directly or through a team): `?team=Gaming&maintainer=-iedame`,
    `?maintainer=l0b0,-iedame`. Each is a chip ("not Geospatial", "not
    @iedame") to undo it.
  - `?team=none` keeps what isn't through a team. On a maintainer's page
    that's its **Not via a team** button: only the packages that list them
    themselves, leaving out those they maintain only as a member of the
    package's team (nixpkgs adds a team's members to its packages'
    `meta.maintainers`; @l0b0 on 2026-10-08: 204 packages, 23 direct, 181
    through the Geospatial and Gaming teams), from nixpkgs'
    `meta.nonTeamMaintainers` (`nonTeamMaintainers` in the data);
    elsewhere, packages without a team.
- A list named as a nixpkgs team is (`gaming` for Gaming: case and
  punctuation aside) **joins the team**: its packages show on the team's
  page (`?team=Gaming`), in its counts and filter, beside those nixpkgs
  lists under the team in `meta.teams`. For packages a team looks after
  that nixpkgs doesn't list it on; their panel marks the team "list". Rows
  have `teamsByList` (`docs/data.md`). This instance's `gaming-team` list
  is now `gaming` (`?list=gaming-team` links show nothing now).
- **Packages per page**: 50, 100, 200 (still the default), 500 or 1,000,
  picked under the list ("Per page") or in the address (`?per=500`, kept
  when moving between views, so a team's or maintainer's link can carry
  it); the maintainers' list too. Only those sizes: a huge one would draw
  every package at once.
- **Platforms by system**: the "On" choice under the tiles has Linux
  x86_64 and Linux aarch64 beside Linux and Darwin
  (`?platform=x86_64-linux`, `aarch64-linux`), each narrowing builds to
  that system's; and a package on only one Linux system says which ("Linux
  x86_64" instead of "Linux"), about 1,900 of nixpkgs' 151,000 attributes.
  Rows' `platforms` gain `systems` where that's so (`docs/data.md`), and
  `meta.badPlatforms` now takes systems away (about 220 attributes exclude
  a system nixpkgs builds this way).
- "Bot won't update it", narrowing any list (`?refine=nobot`): outdated
  packages nixpkgs-update won't update by itself, so they take someone:
  the bot can't (none of its ways apply), skips them on purpose, or has
  never tried them and they aren't in its queue; none with an update PR
  open or merged. 1,560 of nixpkgs' 8,848 outdated packages on
  2026-10-07.
- Each set's card on the overview counts its outdated packages too
  (`outdated` in `views.sets`), and its bar draws them in orange beside
  failing and broken, each package once, at its worst (`bar` in
  `views.sets`).

### Changed

- **Since when builds have been failing** (`failingSince`) is Hydra's last
  success of the failed builds, read each sync, no longer the day nixkeeper
  first saw them fail when that wasn't known (most packages'
  2026-10-05, the day nixkeeper started tracking every package); carried
  from sync to sync only while Hydra's answer isn't known. nixkeeper-hydra
  now knows the last success of every failing job (it asked Hydra about the
  4,805 it didn't, 2026-10-07), so "last built ..." shows beyond the lists'
  packages; a job Hydra says never succeeded comes as `lastSuccessAt`
  "never" in its digest, which the sync reads as such instead of asking
  Hydra again every day. The overview's longest-standing build failures
  and the list's order go by how long they really have failed.
- A package's own **update check decides** whether it's outdated where it
  and Repology disagree (a rule of yours or the community's, or one it
  follows), as the version sources do: before, a check could only add
  "outdated". google-chrome read as outdated since 2026-10-06 against an
  older stable (154.0.8037.97), Repology's rule still calling 155 a beta
  after it went stable, while its check (Google's version history) found
  nixpkgs' 155 current. The panel says what Repology said
  (`repologySaid`); worked-out checks, and a rule's last result while it
  fails, still only add newer versions. Repository chips no longer mark an
  older "newest" as ahead.
- A **maintainer's page** is at `?maintainer=l0b0` (the search still shows
  `@l0b0`); links from before, `?q=@l0b0`, open it and become that. The
  page's own links and the status issues use the new address.
- The **package panels, redesigned**. Its details: the verdict first ("Up
  to date", "Outdated", "Waiting for the channel", "Older version
  kept"...) with nixpkgs' version, the newest and since when, and a badge
  for the source that decided (its update check's tags or page, Typst
  Universe, an up-to-date rule, master: in the accent's tint; Repology:
  grey). The explanation and context notes fold behind "Why?" (remembered
  in your browser); notes that call for something (vulnerable, a failing
  check, archived) stay in view. Then "Compared against", maintainers and
  teams side by side as pills, and the links as buttons with icons (Tabler
  Icons, MIT, inline), each section apart. Its builds: how it stands
  ("Failing on 2 of 3", "Blocked on 1 of 3", "Building on all 3"), then a
  row per system with its status, when it last built, and its Log and
  Build (failed), Build (blocked), Source (marked broken) and Job, instead
  of the job links apart at the end. Its update: the outcome as a pill
  ("Failed: patch", "PR opened", "Can't update"), when it was attempted and
  the versions tried, why, the log's last lines, the next attempt from the
  bot's queue as its own section, and Log and All attempts as buttons.
  One package open at a time: opening another row's panel closes the one
  open (the same row still switches between its panels in place), and the
  clicked row stays where it was on screen. The update cell's robot
  (nixpkgs-update will try it) is plain beside the status, no longer in a
  grey pill, so those rows don't stand out.
- The page says **Darwin** for macOS, as nixpkgs does
  (`lib.platforms.darwin`, `aarch64-darwin`): the platform tags under a
  package's name, the "On" choice under the tiles, and the build failures
  card ("Linux 812 · Darwin 268"); hovering a tag says "Darwin (macOS)" and
  its systems. The address is `?platform=darwin`; `?platform=macos` still
  works.
- **Faster lists**, on a slow phone especially (Lighthouse's mid-range
  phone on "needs attention", 2026-10-07: Total Blocking Time 990 ms →
  600 ms):
  - a list loads in steps, the browser free in between: filtering and
    sorting; then the counts, tiles and the first 50 rows, drawn together
    so nothing above the list moves; then the page's other rows. A newer
    update (typing, say) stops an older one between steps; the pager's
    move to the first row waits for the new page;
  - sorting works out each package's rank and date once, not at every
    comparison (11,579 packages: 48-89 ms on a fast laptop, half a second
    of the phone's longest task, now about 7 ms; undated rows go last, as
    intended);
  - a package's panel starts loading its data when the pointer rests on
    its row (or keyboard focus reaches it), not at the click: the pause
    before a click hides most of a first open (0.3-0.6 s when Cloudflare's
    nearest location doesn't have it yet). Sweeping the pointer over the
    list loads nothing.
- With every package, the generated sets (R, Haskell, Emacs, TeX Live,
  Typst, SBCL) are no longer "pending": they're **sets updated in bulk**,
  each saying what keeps it current (the CRAN import, hackage2nix on
  haskell-updates, the Quicklisp import, TeX Live's snapshot, the
  ELPA/MELPA scripts, the Typst Universe import), linked in nixpkgs, on
  the overview, on its list and on each of its packages, in place of the
  "pending" badge. nixpkgs-update's attempts are shown for them where the
  bot makes any (some TeX Live and Emacs packages); they're still counted
  on their set's line, not in the cards (an R package behind CRAN waits
  for the next import, which no one PR does). `darwin` and `freebsd`
  packages say they're not versioned software instead of "unlisted",
  their builds being what's checked. In the data: `set` without `pending`,
  `unversioned`, `profiles` and `counts.inSets` in `index.json`
  (`docs/data.md`); the page still reads data from before. The overview's
  top bar draws them in a shade of the logo's, not grey, beside fully
  checked: a split of nixpkgs, not progress.
- The daily sync no longer stops when Repology can't be reached (more than
  half of its lookups failing): Hydra's builds, nixpkgs-update's attempts,
  the other version sources and GitHub's PRs are refreshed anyway, and
  the packages Repology couldn't answer keep their last versions, from the
  versions digest even when it's old (Repology being down, its run
  couldn't read it either), else from the last run, marked "not
  refreshed". A new package with no earlier data is shown as not looked up
  (`lookupFailed`) instead of left out of the run. The sources panel says
  how many lookups failed (`sources.repology`).
- "Where the data is from" groups the sources read from nixkeeper's
  digests under each one, linked once (nixkeeper-hydra: builds,
  haskell-updates; nixkeeper-versions: nixkeeper's own update checks, from
  the daily sync, then Repology, Typst Universe, Emacs archives, Stackage
  LTS, CRAN and Bioconductor; nixkeeper-updates: update attempts, the
  queue).
- An instance served from its own site (Cloudflare, `CLOUDFLARE_SITE_URL`)
  no longer has a second copy of the page on GitHub Pages: its
  `<owner>.github.io` address sends visitors to the site, keeping their
  search, filters and view (`scripts/pages-redirect.sh`). The community
  dashboard's old address, https://iedame.github.io/nixkeeper/, goes to
  https://nixkeeper.com/. "Pages: publish the page" then no longer runs on
  every page change: its redirect doesn't change with the page, which
  reaches the site with the data runs. Run it by hand after changing
  `scripts/pages-redirect.sh`.
- `start-runs` tries a start again when GitHub answers with a server
  error or not at all, after 1 minute and then 3 (on 2026-10-07 one hour's
  starts all got 500s, losing nixkeeper-updates' run for 3 hours), and
  also starts nixkeeper-vulnerabilities' digest every hour. Its token
  needs that repository too.

### Fixed

- Versions are ordered as Repology orders them (its libversion algorithm,
  in Python and in the page; tested against Repology's own test suite,
  `tests/data/version-comparison-tests.txt`): a pre-release before its
  release (`1.0rc1 < 1.0`, `2.0.0-beta.1 < 2.0.0`; before, after it), `1`
  the same as `1.0`, any letter case alike, `1.0 < 1.0patch1 < 1.0.1 <
  1.0a`. nixkeeper's own comparisons (update checks, what master has, the
  version sources, update PRs) got 47 of the suite's 177 cases wrong; a
  release candidate tag could make a package look outdated. Marked on the
  trends as a change in how nixkeeper counts.
- The hourly PR check found "merged into master" update PRs that the
  channel already has: it searched merged PRs without the daily sync's
  bound, so an old one whose version sorts above nixpkgs' (xmage's 1.4.60,
  above its later 1.4.60-dev_2026-06-28 snapshot) made the bot's failed
  attempt look superseded until the next daily sync said otherwise, and
  the package was "newly failed" every day. Merged PRs are now searched
  from the channel's commit only, as the daily sync lists them; when that
  date can't be known, the row keeps what it had.
- The status issue no longer links nixpkgs pull requests: each link added
  a "mentioned this pull request" line on the PR every time the issue was
  rewritten. They're named by number, in code (`` `#562674` ``), which
  neither links nor points at this repository's issue of that number.
- The overview's newest and longest-standing failures and outdated
  packages agree with the cards above them: their count is the card's, and
  they list only what counts now. The hourly checks recount, but only the
  daily sync sets and drops the dates the lists go by, so a change in how
  nixkeeper counts (as the version ordering did) left them apart for up to
  a day (8,695 outdated listed under a card of 8,684).
- nixpkgs evaluations (where packages are marked broken, where their
  sources come from) read the list of attributes from a file instead of
  nix's command line, which Linux limits to 128 KB an argument: an
  instance tracking a few thousand packages failed there ("Argument list
  too long"), as did nixkeeper-versions' evaluation of every package. The
  evaluation is `--impure` to read it; what it evaluates is still the
  channel's revision.

## [0.14.0] - 2026-10-08 [YANKED]

Not released: the `v0.14.0` tag was pushed on the commit before the
release's (its `flake.lock` update, where nixkeeper still says 0.13.0), and
version tags can't be moved here, so the release checks stopped and
published nothing. Use 0.14.1, the same changes.

## [0.13.0] - 2026-10-07

The community dashboard moves to **https://nixkeeper.com/**, served from
Cloudflare, and says more about why packages fail: which dependency
blocks a build, where builds fail (Linux, macOS), and why nixpkgs-update's
attempts failed or did nothing, read from its logs, with when the bot will
try again from its queue. Runs start on time from a machine that's always
on (`start-runs`), and the data's first format is no longer written.

### Added

- The dashboard is at https://nixkeeper.com/, served from Cloudflare (a
  Worker serving static assets): the page and its data as one site, from
  Cloudflare's edge, instead of the data from raw.githubusercontent.com.
  The data workflows publish it there when the page or the data changed,
  for an instance with a Worker set (`CLOUDFLARE_WORKER`;
  `docs/all-packages.md`); the data branch stays the syncs' own copy, and
  GitHub Pages the page of every other instance. GitHub Pages' workflow
  also writes where the data is into the page, so one on a custom domain
  finds it as on github.io.
- Which dependency failed, from nixkeeper-hydra's digest (which reads each
  dependency-failed build's page on Hydra, as zh.fail does): a build that
  didn't build because a dependency failed says "blocked by" it, linking
  its package; the list shows those packages as "blocked" (amber, not
  counted as failed: before, "none reported"); and the overview lists the
  failing packages blocking the most others, in all of nixpkgs. In the
  data: `blockedBy` on such builds, `blockers` in `index.json`
  (`docs/data.md`).
- A "blocked" filter (`?filter=blocked`): packages with a build Hydra
  didn't try because a dependency failed, which no other count has (they
  aren't failing themselves). A count at the top when there are any; with
  every package, a tile in each list, and a view of them all
  (`?view=blocked`, `views/blocked.json`) that the overview's "Blocking the
  most" opens ("Show all"). Its count is now every blocked package's,
  whether nixkeeper-hydra has read which dependency it was yet or not.
- Build failures by platform: the overview's card says how many fail on
  Linux and on macOS (each Hydra system on hover; `buildFailuresOn` in
  `index.json`), and every list can be narrowed to one platform under its
  counts or tiles ("On Linux / macOS", `?platform=`), as a row's platform
  tag already did: build failures on macOS are a link now.
- Why a nixpkgs-update attempt failed, from its log (parser 5, so every
  log is read again): tests, build, dependency (missing or too old), patch
  (nixpkgs' patches or substitutions no longer apply), source (couldn't be
  fetched), hash (one the bot couldn't work out), updateScript, unavailable
  (broken, insecure or not for x86_64-linux), or request (the bot's own,
  not the package). The list says it ("failed: tests"), the update panel in
  full, its excerpt starting at the log's line that says so instead of the
  log's last lines; rows have it as `failedBecause` (`docs/data.md`). Read
  from 200 failed attempts' logs, 97% of which it says.
- nixpkgs-update attempts that ended "other" (15% of them) now say what
  happened, with the log's own line (parser 4, so every log is read again):
  `branchExists` (the bot already pushed that update to its branch: its PR
  is open or on its way), `skipped` (the bot passes the package over on
  purpose: it opts out, GNOME's release cycle, too many rebuilds, ...;
  "skipped" in the list), and, for `noChange` and `cantUpdate`, why
  (nothing newer by Nix's version order, the same hashes, the source URL
  unchanged). A request that failed (GitHub answering 500, say) is a
  failure, its excerpt the host and the answer, not the request's dump.
  nixpkgs-update's own messages that end an attempt are read too (as its
  source writes them, checked against r-ryantm-orbit's list): too many open
  PRs (`prExists`), no rewrites performed, the same revision or
  dependencies' hash, edits that rebuild nothing (`noChange`), no
  `version` attribute (`cantUpdate`), and its checks of a build that went
  wrong (`failed`).
- When nixpkgs-update will try a package again, and what it would update
  it to, from the bot's queue (nixkeeper-updates' copy of it): "Next
  attempt expected around Oct 12, from its queue: it would update it to
  4.22.7 (GitHub release · Repology)" in the update panel, or "not in the
  queue" when it sees nothing to update to; and in the list, a robot's
  head joined to the update cell ("queued" to screen readers; green when
  to the newest version and its last attempt didn't fail: its PR should
  follow; amber when the bot will try but it's unsure, its last attempt
  having failed, another version, or an outdated package's updateScript
  deciding the version), which opens that panel too. Rows have it as
  `queued` (`docs/data.md`); the sources panel says when the queue is from.
- While nixkeeper-updates' digest is still reading nixpkgs-update's past
  attempts (a backfill), the Update failures card says how many are to go:
  update failures that were there all along keep turning up, so it rises
  without anything breaking.
- Marks on the overview's trends: each merge of staging-next into nixpkgs
  master (mass rebuilds: failing builds jump for days after), from GitHub's
  search; each nixkeeper update a sync ran; and each change in how
  nixkeeper counts (`COUNTING_CHANGES`, the first being 0.12.0's older
  versions kept), on the day it first ran. Named and dated under the
  cards; in `history.json` as `events` (`docs/data.md`).
- `nix run .#start-runs`: starts an instance's runs through GitHub's API,
  hourly from a machine that's always on (a nix-darwin agent or a NixOS
  timer, in `docs/all-packages.md`), since GitHub's schedule skips runs
  when it's busy. The community instance's hourly updates (every hour but
  06 UTC), daily sync and digests by default; a fork's with
  `NIXKEEPER_START_REPO` and `NIXKEEPER_START_DIGESTS=` (it reads iedame's
  digests). The daily sync can be started with `if_older` (only when the
  last sync is older than that many hours), and its 06:00 run now stops
  when the last sync is under 12 hours old: started both ways, it syncs
  once.

### Changed

- With every package, failing is split in two on the overview and in a
  list's tiles: **build failures** (a build of its own failing) and
  **update failures** (nixpkgs-update's attempts failing), each its own
  card, trend and filter (`?filter=builds`, `?filter=updates`;
  `?filter=failed` still shows both). The history records both
  (`buildFailures`, `updateFailures`), and a sync adds them to the day
  before's point from that day's manifest, so the split trends start at
  once.
- The overview's trends show from the second daily sync, not after a
  week; until there's a week, each card's change is since the first sync
  (hover it for which).
- `nix run .#screenshots` takes every package's overview too, when the data
  is a community instance's: the same shots, starting with `overview-`
  (the desktop ones taller, no panel; the social preview's card says
  "every nixpkgs package"), beside the list's, which a run with a
  list-based instance's data retakes as before. `--data` can be a local
  folder too, served next to the page.

### Fixed

- The page no longer jumps as it loads (its layout shift, 0.15 to 0.8
  depending on the screen, now about 0): the footer stays hidden until the
  data is there, the loading line sits above where the list or overview
  appears, and the scrollbar has its room from the start.
- The page for screen readers, phones and low vision (a pass before the
  community page is announced):
  - muted text (labels, dates, zeros, headers) is now 4.5:1 against its
    background in all four palettes (it was 2.6 to 4.4:1);
  - the overview's sections and cards are headings, and each list has one
    (its name), to move between with a screen reader;
  - a package's status dot says what it means, the cards' changes say "up"
    or "down" and since when, and how many packages a filter, tile or
    search leaves is announced;
  - on touch screens, everything tapped is at least 24px each way (the
    platform tags, the ✕ back from a list, the help button, the narrowing
    buttons and pickers, PR badges, "Show all"), and the header's buttons
    no longer stick out past the screen's margin;
  - the build, update and platform buttons have the page's focus ring.
- The list no longer widens the page past the screen (scrolling it
  sideways, the last column cut off) for a long package name or a long
  version with badges beside it: a name wraps after a dot or at a hyphen
  (`home-assistant-custom-components.` / `homematicip_local`), and the
  badges under each other. With every package, "needs attention" was
  1,400px wide in a 1,280px window.
- Which dependency failed was left out for every build whose last success
  nixkeeper-hydra's digest doesn't know (one that never built, say): with
  every package, most of them (the overview counted 61 blocked packages
  instead of about 580), and with lists, every one asked of Hydra (which
  doesn't say). It's kept now, and added to Hydra's answer for the same
  build.

### Removed

- The data's first format is no longer written: no `packages` in
  `index.json` and no `<project>.json` files (the shards have had the same
  since 0.12.0), so `data/` is smaller (a few files instead of one per
  Repology project) and syncs and the hourly checks write less. A page from
  0.11.0 or before can't show the new data: update it with the data (the
  modules and the GitHub workflows do). The page no longer reads the first
  format either, and says so for data from 0.11.0 or before; the sync
  still reads it, so upgrading from 0.11.0 keeps the last run's data, and
  rewrites it in the second format (`docs/data.md`).

## [0.12.0] - 2026-10-06

nixkeeper can now track **every nixpkgs package**, for a community
instance (`NIXKEEPER_ALL_PACKAGES=1`, `allPackages` in the modules): about
126,000 rows, read in bulk from three digests (Hydra's builds, Repology's
versions, nixpkgs-update's attempts), with a page that starts from an
overview of all of nixpkgs. Instances that track their lists, as before,
get the new data format, paging, teams, failing ages, the narrowing
filters and the sources panel; their page looks as it did otherwise.

### Added

- Every package: `NIXKEEPER_ALL_PACKAGES=1` (a repository variable on
  GitHub, `allPackages` in the modules, `sync --all-packages`) tracks every
  nixpkgs package, not only the lists', for a community instance
  (`docs/all-packages.md`). The lists' packages are read as always and are
  the only ones in the status issue; the rest only from the digests and
  bulk listings, with nothing asked per package (nixpkgs-update's attempts
  from nixkeeper-updates' digest, above). Generated sets (R, Haskell,
  Emacs, Typst, TeX Live, SBCL) are pending: only Repology's versions and
  Hydra's builds. The data then has views (needs attention, marked broken,
  per maintainer, team, list and set), a name index, counts and their
  history, instead of one summary of every package
  (`docs/data.md`). The page then starts from an overview of all of
  nixpkgs (fully checked, and in generated sets): cards for the outdated,
  failing, vulnerable and broken packages with their weekly change and
  trend (`history.json`, from the first sync on), a search with a team
  picker (its matches in place of what follows, while searching), the
  newest and longest-standing build failures, outdated packages and update
  failures, and the generated sets with how much of
  each is marked broken or failing; each opens a list (what needs
  attention, marked broken, a maintainer's, a team's, a generated set's,
  one package's), whose tiles count and filter it. Visitors can keep their
  own GitHub handle and team (in their browser) for "Your packages" and
  "Your team"; the instance's own lists open by address only. A search
  also lists matching names beyond the list shown.
- A second format for the data, beside the first: `summary.json`, a short
  entry per package with what the page's list needs (about a third of
  `index.json` today), and `rows/<n>.json`, the packages in full with their
  Repology data, split by a hash of the name. `index.json` says
  `"format": 2` and how many packages and shards there are. The first
  format is still written, unchanged (`docs/data.md`).
- The page reads the second format when the data has it: the list from
  `summary.json` (about a third of the download), and a package's full row
  from its shard when one of its panels opens (once a shard). It still reads
  the first format, so it works with data from before.
- The list is paged: 200 packages at a time, most in need of attention
  first, with page links under it and `?page=` in the address. Drawing stays
  fast however many packages there are; changing a filter, the search or the
  order goes back to the first page.
- Packages' nixpkgs teams (`meta.teams`): in the data (`teams`), in the
  details panel, and as a filter (`?team=gaming`, or a team's name in the
  panel).
- How long a package has been failing: `failingSince` (its builds, since
  their last success when first seen) and `updateFailingSince` (its update
  attempts), carried from sync to sync like `outdatedSince`; a red age tag
  after the name, and failing packages listed longest first.
- Packages nixpkgs marks broken show "marked broken" even when Hydra has no
  job for them (`markedBroken`, from the package index's `meta.broken`):
  until now, a broken package with no Hydra job (as hackage2nix makes them)
  only said "not built by Hydra".
- nixpkgs-update's attempts from
  [nixkeeper-updates](https://github.com/iedame/nixkeeper-updates), a digest
  of the bot's latest attempt at every package (its log read with
  nixkeeper's own rules, every 3 hours, from the bot's state), instead of
  reading each package's logs; still read per package when the digest
  hasn't read the latest attempt, or isn't current
  (`NIXKEEPER_UPDATES_DIGEST`). With every package, every package gets its
  attempt this way.
- Where the data is from: "checked … ago" on the page opens each source's
  time (the daily sync; the Hydra evaluation its builds are from and when
  it was read; when Repology's versions and nixpkgs-update's attempts were
  read, and how many attempts are still to read; the nixpkgs commit), and
  says when the sync didn't use a digest (too old, or unreadable) and why.
  In the data: `sources` in `index.json` (`docs/data.md`).
- Narrowing any list, together with its other filters: without
  maintainer, not marked broken, not fixed on master yet (an outdated
  package whose update is merged, waiting for nixos-unstable), and older
  than a month, 6 months or a year (failing or outdated for that long).
  Under the counts, or with every package under a list's tiles; in the
  address as `?refine=` and `?age=` (`docs/reading-the-page.md`).
- Recently fixed, with every package: each daily sync notes what's fixed
  since the one before (a build that works again, a package updated, a
  nixpkgs-update failure cleared), only with something showing it (Hydra's
  success, a new version in nixpkgs, a newer attempt), so a late source or
  a change in how nixkeeper counts never looks like a wave of fixes. The
  last 30 days' in `history.json` (`fixed`); the overview shows the last
  week's, newest first.
- Maintainers, with every package: `maintainers.json` (every maintainer,
  with their packages, outdated and failing counts); "browse every
  maintainer" on the overview (`?view=maintainers`), by handle, the search
  narrowing them; and typing `@` and part of a handle suggests the
  maintainers whose handle matches.

### Changed

- An older version nixpkgs keeps on purpose beside a newer one under
  another attribute (Repology's "legacy": `tracy_0_11` beside `tracy`,
  `gnumake42`, `php82Extensions`, older kernels' modules) isn't counted as
  outdated anymore: it's shown as an "older version", with the newer one
  named (`keptBeside`). It's still outdated by a newer release in its own
  series (the worked-out update checks look there), and a beta behind the
  newest betas still is. On 2026-10-06's data, about 1,650 fewer outdated
  packages (16%): the Outdated trend steps down once, at the first sync
  with this. The community up-to-date rules for `tracy_0_11` and
  `tracy_0_12` are gone, as this covers them.
- The daily sync workflow runs again at 14:00 UTC as a catch-up: it only
  syncs if the last sync is over 20 hours old (GitHub skipped or badly
  delayed the 06:00 one), and otherwise stops at once.
- The files in `data/` are written as compact JSON, without indentation:
  about a third smaller for the browser to read (a few percent smaller to
  download, as servers send it gzipped). The data is the same: tools that
  parse JSON aren't affected.
- Dates that are the sync's own time are left out of the data: a package's
  `countedAt`, its update check's `checkedAt` and each build's `checkedAt`,
  when they equal `checkedAt` in `index.json` (a missing one means that).
  A package nothing new happened to now reads the same from one sync to the
  next (222 of 224 rows on today's data), instead of every row changing
  every day.

### Fixed

- A project's attributes split into rows by version counted every one
  after the first as a devel variant, older series too (`gnumake42`,
  `php82Extensions`, `flatbuffers_23` had a "devel" badge and were compared
  with devel versions). Now only one newer than the stable one, or named
  for one (`-devel`, `-beta`, `-unstable`, ...), is.
- With every package, an hourly check that changed something took half an
  hour or more to write it (an Edge release did, and two runs were stopped
  after 22 minutes): it read each row's Repology entries on its own,
  reading and parsing a whole shard again for nearly every one of about
  126,000 rows. It now reads each shard once: about 20 seconds in all.
- A site sending its answer a little at a time could hold a run for hours:
  a request's timeout only bounded each wait for the next bytes. Now a
  whole answer has a minute to arrive (5 for a digest's download), or the
  request has failed, is retried, and the package keeps its previous result
  as when a site is down. The data workflows also have time limits (20
  minutes hourly, an hour daily), so a run that hangs can't hold the data
  branch, which the other one waits for, up to GitHub's default of 6 hours.

## [0.11.0] - 2026-10-05

Ready for big lists: Hydra's builds, Repology's data and GitHub's PRs and
issues now come in bulk, at about the same cost whatever the lists' size (a
daily sync of 1,500 packages is estimated at about 12 minutes, down from
about 45; 241 take under 4); update checks are worked out from nixpkgs for
packages without a rule; and team members can find their own packages on the
page.

### Added

- Update checks worked out from nixpkgs itself, a first step towards
  relying less on Repology. A package without an update check of its own
  (or a community rule) that nixpkgs fetches from a GitHub tag is checked
  against that repository's tags, in the scheme its own tag shows (`v1.2.3`,
  `release-1.2.3`, ...), plain versions only, shaped like nixpkgs' (a dotted
  version doesn't take a lone number such as a `20240214` date tag) and, for
  a versioned attribute (`tracy_0_11`, `gcc13`, `python313`), in its series
  only: a newer one there makes it outdated, as any update check's does, so
  new releases show before Repology counts them. On by default;
  `workedOutChecks = false;` in the lists (`lists.workedOutChecks` in the
  modules) leaves those packages to Repology. One that fails (a renamed
  repository, no matching tag) leaves its package to Repology without a
  warning: nobody wrote it to fix. A rule of your own or the community's
  wins, for a package these get wrong (Wesnoth's stable series has one now).
  Each daily sync's log compares them with Repology and with the packages'
  rules, in a collapsed group. They cost one nixpkgs evaluation (seconds)
  and one GitHub request per 50 repositories.

- Search by maintainer: `@handle` in the search box lists the packages
  nixpkgs gives that maintainer (their GitHub handle, in any case), and
  `@none` those with no maintainer, so `?q=@yourhandle` is a link to a team
  member's own packages. The details panel lists a package's maintainers,
  each a search for theirs and a link to their GitHub profile. Rows get
  `maintainers` from the nixpkgs index the sync already reads (no new
  requests); the page finds them after the first sync with this version.

- The details panel lists `nixkeeper` first among the repositories a
  package is compared against, with the version its update check found
  (highlighted when it's newer than nixpkgs', as the others are); hover it
  for where that came from.

### Changed

- Hydra's builds come from [nixkeeper-hydra](https://github.com/iedame/nixkeeper-hydra)
  first: a digest of every job in Hydra's newest evaluation of nixpkgs
  master, kept up to date hourly by its own workflow. One download (about
  2.6 MB) answers most jobs, every day, instead of a request or two per job:
  a new build failure shows up the next day for every package. Hydra is
  still asked about the jobs the digest can't answer (missing from it, not
  built yet, or failing with no known last success), and about every job
  when the digest isn't current (from an older evaluation and over 12 hours
  old) or can't be downloaded. `NIXKEEPER_HYDRA_DIGEST` points elsewhere, or
  empty turns it off. Hydra's newest evaluation is read from its list of
  evaluations, not from `latest-eval`, which is the newest whose builds have
  all finished.

- Repology's data comes from [nixkeeper-versions](https://github.com/iedame/nixkeeper-versions)
  first: a digest of every nixpkgs project on Repology, which its own
  workflow reads in bulk daily, as nixpkgs-update does (outdated projects
  every day, the rest every week; about 200 requests a day for all of
  nixpkgs, within Repology's API rules). One download (about 12 MB, read a
  project at a time, so little memory) answers most tracked packages: a
  sync of 241 packages looked up 2 of them. Repology is still
  asked about packages missing from the digest (new in nixpkgs) or with
  another version there than the channel's (changed since), and about
  every package when the digest is more than 36 hours old or can't be read.
  `NIXKEEPER_VERSIONS_DIGEST` points elsewhere, or empty turns it off.

- Open PR and issue counts and update PRs come from bulk listings instead
  of two or three GitHub searches per package: every open nixpkgs PR and
  issue (about 120 GraphQL requests, 100 of each per request) and the PRs
  merged into master since the channel's commit (about 10 more), however
  many packages are tracked, with each package's counts and update PRs
  found in the titles locally. A sync of 241 packages made about 300
  searches before. Counts match GitHub's title search (whole words, plurals
  included, checked side by side: 126 of 128 packages agreed, and every
  update PR); its deeper stemming isn't copied, so a package named like an
  English word can count a few fewer ("trigger" doesn't count "triggered").
  Every package is counted daily. When a listing fails, or there's no token
  for it, the sync searches per package; the hourly update-PR check, for a
  few packages, still searches.

- When nixkeeper asks per package (the digests or listings aren't
  available, or for what they can't answer), it asks less about what's
  quiet, as nixpkgs-update spreads its queue: a Hydra job that built fine
  with nothing pending, an update check that found nothing newer (unless
  it's `frequent`), a Repology lookup for a package that's up to date, not
  vulnerable and unchanged in nixpkgs, and the PR and issue searches of a
  package with none open, each every 3 days (a third each day) instead of
  daily. Anything failing, outdated, newly changed, with an update PR, or
  whose lookup failed is still asked daily, and so is everything the first
  time. Each result records when it was read (`builds[].checkedAt`,
  `upstream.checkedAt`, `repologyCheckedAt`, `countedAt`), and the details
  say how old it is when it isn't from today. An update check also runs
  again at once when its rule is edited (`upstream.rule`, a fingerprint of
  it).

- New sizes: the list check warns from 1,500 packages instead of 500, and
  the sync refuses to start above 5,000 instead of 2,000 (`maxPackages` to
  go beyond). The estimate a sync starts with is measured anew: about 150
  requests and 2 minutes whatever the lists' size, then per package about
  0.3 requests and half a second on a typical day, about 3 and 3 seconds the
  first time it's synced (1,500 packages: about 12 minutes a day), and it
  counts the packages new to this sync. On GitHub Actions it warns when a
  sync may outlast the job's 6 hours (about 8,000 new packages at once),
  which would publish nothing: big lists are best added in stages.

- The daily sync asks Hydra in the background from the start, while it
  asks the other sources, instead of after them. Each server is still asked
  one request at a time.

- Fewer requests to the sources, for the same results:
  - Repology: a package looked up directly is looked up by the project the
    last sync found for it, one request instead of two (asking by attribute
    is answered with a redirect to the project). If Repology has moved the
    package to another project, it's looked up by attribute as before.
  - nixpkgs-update's logs: the log site's index (one request, compressed)
    says when each package's logs last changed, so a package whose logs
    haven't changed since the last sync isn't listed again, and one with no
    logs isn't asked about. For 72 attributes, a sync made 3 requests
    instead of at least 72, with the same results.
  - Update checks against a web page ask its server to send it only if it
    changed since the last check (the page's `ETag` and `Last-Modified`),
    and keep what they found when it didn't: the hourly microsoft-edge
    check read a 1 MB file each time, now only when Edge has changed. A rule
    whose page or pattern changes reads the page whole again
    (`upstream.page` records what's sent).
  - Update checks against GitHub ask about tags and branches 50
    repositories per request, and a request that fails only affects its
    own 50.

- Update checks against web pages ask each site at most once a second, and
  take turns between sites, so many rules on one site (PyPI, a vendor's)
  don't arrive back to back. The other sources already paced themselves.

- The page stays responsive with big lists. With 3,000 packages, redrawing
  the list on a phone or tablet takes about a third of the time it did
  (cards off screen are only laid out when scrolled near), searching redraws
  once typing pauses instead of at every key, and a row's panel is only made
  when it's first opened. On wide screens, a table of that size still takes
  about half a second to redraw on a fast computer: about a quarter of a
  second at 1,500 packages.

- The `data` branch no longer piles up a commit for every sync and hourly
  update: each run publishes `main` plus one commit with the latest data,
  replacing the last (the history was never read). The first run after
  updating does this to the existing branch, keeping its data. If GitHub
  can't say whether the branch exists, the run now stops at once, instead of
  carrying on as if it were the first run (against no previous data).

- Each package's Repology file in `data/` keeps only what nixkeeper reads
  (`repo`, `srcname`, `version`, `status`, `vulnerable`), each entry once,
  instead of everything Repology returns: about 4 times smaller (1.4 MB to
  0.35 MB for 70 packages, about 30 MB to 7 MB at 1,500), and about 3 times
  less to download for the details panels. If you read these files yourself,
  the other fields are gone.

- For readers of the data (`docs/data.md`): rows have new fields,
  `maintainers`, `repologyCheckedAt` and `countedAt`; builds have
  `checkedAt`; update checks have `rule`, `page` and `inferred` (worked out
  from nixpkgs). `repoCount` now counts repositories
  (below).

### Fixed

- Repology is asked at `repology.org` only: its mirror `repology.amdmi3.ru`,
  which nixkeeper fell back to when `repology.org` failed, is discontinued
  on 2026-10-09. A failing `repology.org` is retried as before, and
  `REPOLOGY_BASE_URL` still sets another address.

- The NixOS module always puts Nix on the jobs' path: the sync evaluates
  nixpkgs, for worked-out update checks and where nixpkgs marks packages
  broken. Before, with lists set in the configuration and no community
  rules, it had no Nix, and skipped `meta.broken` with a warning.

- The package lists' check (`nix flake check`) accepted an entry that names
  a set of packages rather than a package (`cataclysmDDA`, which holds
  `stable`, `git`, ...): it passed CI, then the sync couldn't find it and
  the page showed a list problem. Entries, update checks and rules now have
  to name a package, and a set of packages is reported as such.

- `repoCount` counted Repology's entries, so a repository listing a package
  more than once (subpackages) counted more than once. It now counts
  repositories, as documented.

- When a package's Repology file couldn't be loaded (a network hiccup, say),
  its details said "compared with 0 other repositories". They now say the
  file couldn't be loaded, and opening the package again tries again.

## [0.10.0] - 2026-10-04

### Added

- `follows`, a new kind of update check, for a package updated together with
  another, to the same version, by the same PRs:
  `msedgedriver = { follows = "microsoft-edge"; };`. It counts the other's
  newest version and update PRs (merged and open) as its own, in the daily
  sync and the hourly checks; their titles name only the other package, so
  nixkeeper couldn't find them before. Checked like the other kinds (the
  package followed has to be tracked too; no chains). The community update
  checks have it for msedgedriver.

- Up-to-date rules (`package-lists/up-to-date.nix`, `upToDate` in the
  lists), for a version nixpkgs has that Repology gets wrong: calls it
  untrusted, incorrect or ignored, or compares it with a version that isn't
  really newer. A rule names the version, the version Repology shows as
  newest elsewhere, and why nixpkgs' is right; while nixpkgs has that version
  and Repology shows nothing newer, the row counts as up to date, and its
  details say why and what Repology said. A real new release or nixpkgs
  moving on ends it, and the sync says the rule can go. Only Repology's
  verdict changes: update checks and master still count. The community rules
  have them too (`community.upToDate = true;`, `lists.community.upToDate` in
  the modules), for asc, pacvim, steamtinkerlaunch and wesnoth-devel, and
  `nixkeeper community-check` and the weekly run report the ones that can go.

- Fewer requests to the nixpkgs-update logs: a sync no longer downloads the
  log of an attempt it read the day before (the bot tries each package about
  every ten days), and takes the previous reading instead, judged afresh
  against nixpkgs and the ignore rules. Each attempt records the version of
  the rules it was read with (`parser`), so a fix to how logs are read
  applies at the next sync.

- Keeping syncs reasonable as the lists grow: a sync starts by saying how
  long it should take (and on GitHub, in the run's summary); from 500
  packages the list check warns, on the page and in the status issue; above
  2,000 the sync refuses to start, unless the lists raise the limit with
  `maxPackages` (`lists.maxPackages` in the modules). Each package costs
  about 8 requests to public services and 7 seconds per sync.

### Changed

- When a source answers "too many requests" or "unavailable" with how long
  to wait (`Retry-After`), nixkeeper waits that long before trying again,
  up to 5 minutes; asked to wait longer, it gives that request up and the
  package keeps its previous data. GitHub's rate limits get the same: one
  more try after the wait it asks for.

- nixkeeper introduces itself properly to the sources it reads: its
  User-Agent is now `nixkeeper/<version> (+https://github.com/iedame/nixkeeper)`
  (it was a fixed `nixkeeper/1.0 (personal package tracker)`), plus the
  repository running it on GitHub Actions. Self-hosters can add how they can
  be reached with `NIXKEEPER_CONTACT` (`contact` in the modules).

- When master is partway there (an update merged, waiting for the channel,
  and a newer release already out, as with Chrome's quick security
  releases), the page shows master's version on a line of its own with its
  `on master` badge, between nixpkgs' version and the newest with its PR.
  Clicking the versions then copies the next update's title, from master's
  version.

### Fixed

- `nixkeeper community-check NAME` tried each name as both an update check
  and an ignore rule: a package with only an update check said its "ignore
  rules still apply", and one with only ignore rules failed as a missing
  update check. Each name is now tried for the rules it has; a name with
  neither is reported as such (a typo, most likely).
- A package only Nix packages (msedgedriver) showed its update as `→ ?`:
  Repology marks no repository "newest" then, but the one ahead (a stable
  branch with a backport) "unique", which now counts. The newest version is
  also the highest of those Repology marks, not the first listed. Should no
  newer version be known, the page says "newer version unknown".
- `ignoredUpdates` couldn't match a failed `updateScript` run, because the
  bot's log header writes `0 -> 1` instead of the versions. When the script
  wrote a diff before the build failed, nixkeeper now reads the versions from
  that diff (so the page also shows `from → to` instead of `updateScript`).
  When the script failed before picking a version (such as `nix-update`
  mistaking an older tag for newer), a rule for the version nixpkgs has
  ignores the failure while the package is up to date, and lets it show again
  once a newer release is out. The community ignore rules have it for
  blackvoxel 2.5.

### Security

- The page builds its markup with an `html` template tag that escapes every
  value from the data (package names, PR titles, rule reasons, ...) unless
  it's markup the page writes itself, instead of an `escapeHtml` call at
  each of about 50 places: a value can't add markup by a forgotten escape.
  Nothing on the page looks different. And `?owner=&repo=`, which points the
  page at another repository's data, now only takes names GitHub allows.

## [0.9.0] - 2026-10-01

### Added

- A link to nixkeeper's repository on the page: a GitHub button in the
  toolbar, and a quiet last line with the version that made the data
  ("nixkeeper 0.9.0 on GitHub"). The sync writes that version into
  `index.json` (`version`).
- Link previews for the page: shared on Discourse, Matrix, Mastodon and
  the like, a link to a nixkeeper page shows nixkeeper's card (the social
  preview). Releases' notes start with the card too.
- Screenshots in both palettes (`assets/screenshots/*-catppuccin.png`); the
  README shows the Catppuccin ones in a collapsible section.
- A Theme menu on the page: Classic or [Catppuccin](https://catppuccin.com)
  colours (Latte when light, Mocha when dark), and light, dark or Auto (the
  system's setting). The choice is kept in the visitor's browser and applied
  before the page draws. The page's owner sets the default palette with
  `page.theme = "catppuccin";` in the package lists (`lists.page.theme` in
  the modules); the sync checks it and writes it to the data.
- Community rules (`community/`): rules anyone can add by pull request, for
  any nixpkgs package, in the format of your own lists: update checks
  (`community/update-checks.nix`, where to look for new releases) and ignore
  rules (`community/ignored-updates.nix`, failed nixpkgs-update attempts that
  don't count). Opt in to each in your package lists,
  `community = { updateChecks = true; ignoredUpdates = true; };` (or
  `lists.community` in the modules): each sync then uses them for the
  packages you track, and only those, your own rules winning (an update
  check per package, an ignore rule per version). They come with nixkeeper,
  so they change only when you update it, and the page says when a result
  comes from one. Because community update checks run on every subscriber's
  machine, they're held to limits: web pages over https to public hosts only
  (redirects too), at most 2 MB; short patterns without the shapes that can
  take forever. One beyond them is refused, never fetched. See
  `docs/community.md`.
- Keeping the community rules healthy: CI checks `community/` on every pull
  request (each rule well formed, for a package in nixpkgs; update checks
  within the limits, their patterns valid). The "Community: update checks
  still work" workflow tries every rule for real weekly and keeps a
  "Community rules status" issue up to date: which update checks are broken,
  why and since when (commenting when one breaks or works again), and which
  ignore rules can go, the bot having moved on. On pull requests it tries the
  rules they add or change, failing if an update check finds nothing or an
  ignore rule doesn't match the bot's latest failed attempt.
  `nixkeeper community-check [NAME...]` (`nix run .#community-check` from a
  checkout) does the same by hand, to try a rule before proposing it; there's
  also an issue form for proposing an update check.
- `docs/troubleshooting.md`: how to check that nixkeeper runs as it should on
  GitHub, as the command, and with the NixOS and nix-darwin modules (the
  jobs, their schedules, logs and data), and what the page's warnings mean.

### Changed

- The page, refreshed:
  - The toolbar: a search field with an icon and a `/` shortcut, and icon
    buttons for A–Z and the Theme menu. The Refresh button is gone
    (reloading does the same).
  - The counts and the lists are one bar of filter chips. On phones and
    tablets it's one row that swipes sideways and stays at the top while
    scrolling. On desktop, the header, the filters and the table's column
    headings stay at the top.
  - Versions: the newest version sits under nixpkgs', with the part that
    changes in colour. Click them to copy the update's title as nixpkgs
    writes it (`unciv: 4.22.1 -> 4.22.6`). The update's badge (PR, on
    master) and the rest line up at the right of the versions. How long a
    package has been outdated shows after its name.
  - Quieter rows: "none reported", "not built by Hydra", "not attempted"
    and "superseded" are muted, and zero PR or issue counts are faint, so
    what needs a look stands out.
  - The platforms are one small label under the package's name. Rows open
    with a clearer chevron, and the open row and its panel read as one.
  - A package's panel compares nixpkgs with one entry per repository,
    newest first: the first 8, then "Show all".
  - The legend is a `?` beside "checked …" that opens what each dot means
    (on master's violet included), and each row's dot says so on hover.
    Hovering "checked …" shows the exact time of the last sync.
  - A package's panel: rounded repository chips under a small heading, and
    "compared with N other repositories" counting them the way it shows
    them.
  - Touch screens get larger targets, and animations stop when the system
    asks for reduced motion.
  - The card layout now starts below 1080px (was 940px).
- The documentation lives in `docs/`, one page per topic: reading the page,
  how it works, a dashboard of your own, the command, the NixOS and
  nix-darwin modules, the data (was `DATA.md`) and troubleshooting. The
  README is now a short introduction with the three ways to start, and
  links to them; the page's "what these mean" link goes to
  `docs/reading-the-page.md`.
- The nix-darwin module's logs (`~/Library/Logs/nixkeeper/`) date each run:
  a line with the time and the job's name before its output, and one with
  how it ended after it, so a run can be told from the next (and the
  catch-up from the daily sync, which share `sync.log`).

## [0.8.0] - 2026-10-01

nixkeeper as a service: modules for NixOS and nix-darwin that run the sync
and the frequent checks on their own, catch up after the machine was off,
and serve the page. Also: master's newer version counts as "on master" by
itself, and every sync checks the package lists for mistakes.

### Added

- A NixOS module (`nixosModules.default`, `services.nixkeeper`): the sync
  daily and the frequent and update PR checks hourly on systemd timers, as
  their own hardened user, with the lists in the configuration, a GitHub
  token as a systemd credential, and optionally the page and its data on
  nginx. At boot, and when first enabled, it syncs if there's no data yet or
  the last sync is over 20 hours old. Tested in a NixOS VM in CI.
- A nix-darwin module (`darwinModules.default`, `services.nixkeeper`): the
  same jobs as launchd agents of your user, on the command's own folders
  (or the lists in the configuration), with their output in
  `~/Library/Logs/nixkeeper/`, and optionally `nixkeeper serve` kept running
  for the page on this Mac. At login, and when first loaded, it syncs if
  there's no data yet or the last sync is over 20 hours old. Lists or a data
  folder set in the configuration are also exported to your shell, so
  commands you type agree with the jobs.
- Runs on the same data take turns: `sync`, `frequent-check`, `pr-check`
  and `page` hold a lock next to the data folder (`<data dir>.lock`), and a
  second run waits for the first, saying so.
- `nixkeeper sync --if-older HOURS`: only sync when there's no data yet or
  the last sync is older than that.
- Every sync checks the package lists for mistakes that would otherwise go
  unnoticed: a maintainer handle no nixpkgs package lists (a typo would track
  nothing), an extra package nixpkgs doesn't have, and an update check or
  ignore rule for a package that isn't tracked. They're in the sync's log and
  the data (`listProblems`), and the page shows them above the table, so
  lists set in a NixOS or nix-darwin configuration, or by `nixkeeper init`,
  get the same safety net as the repository's `nix flake check`.
- The README says how to pin nixkeeper to a release, a version tag in the
  flake input's URL, instead of following `main`.

### Changed

- `nixkeeper serve` starts before the first sync: the page says it has no
  data yet, and shows it once a sync has written it.
- A package whose master already has a newer version than the channel
  (Hydra's build) counts as outdated, with that version as the one to update
  to, and shows "on master": waiting for the channel, nothing to do. Before,
  it only did when Repology or an update check knew of the new release too
  (wesnoth-devel's 1.19.28 showed as up to date without its update check).

## [0.7.0] - 2026-10-01

nixkeeper as a program you can install and run yourself: one `nixkeeper`
command that works from anywhere, `nixkeeper init` to start your lists, and
the page shipped with it (`nixkeeper serve`, `nixkeeper page`). Forks: set
Settings → Pages → Source to "GitHub Actions" after updating (see Changed).

### Added

- One `nixkeeper` command, with a subcommand for each job: `nixkeeper sync`,
  `nixkeeper frequent-check` and `nixkeeper pr-check`, plus `nixkeeper paths`
  (where the lists and data are, and which setting says so) and
  `nixkeeper --version`. Flags (`--lists`, `--data-dir`, `--notify`) set what
  the `NIXKEEPER_*` variables do, and win over them. `nix run .#sync` and the
  other apps run the new command; the old names (`nixkeeper-sync`,
  `nixkeeper-frequent-check`, `nixkeeper-pr-check`) still work until 1.0,
  with a hint.
- `nixkeeper init --maintainer <handle>` starts your package lists: a folder
  of Nix files with your handle and commented examples, to edit.
- The page ships with nixkeeper (also as `share/nixkeeper/www/` in the
  package). `nixkeeper serve` shows it on this computer with the data as it
  is; `nixkeeper page <dir>` writes it with a copy of the data into a folder
  for any static host.
- `nix/package.nix`: nixkeeper's package in nixpkgs' style (the same file,
  with a release as its source, can later go to nixpkgs), with a version
  check and the package's metadata. It installs with
  `nix profile install github:iedame/nixkeeper`.
- Tests for the page: its rules (statuses, version order, "on master",
  ages, safe links, the tab icon's signals) moved into `page/logic.js`, which
  `tests/js/` tests with Node's test runner as part of `nix flake check`. The
  lint check now also catches undeclared variables in the page's code.

### Changed

- The `nixkeeper` command works from anywhere: by default it keeps the lists
  in `~/.config/nixkeeper/package-lists/` (or `lists.json` there) and the
  data in `~/.local/state/nixkeeper/data/`, following the XDG variables.
  `nix run .#sync` and the other apps still use the checkout's
  `package-lists/` and `data/`, so the workflows and local runs from a
  checkout are unchanged; `nix run .` (and `nix run github:iedame/nixkeeper`)
  is now the command itself, on your own folders, rather than a sync.
- A workflow publishes the page to GitHub Pages ("Pages: publish the page")
  whenever it changes on `main`, instead of Pages deploying a folder from
  the branch. Forks set Settings → Pages → Source to "GitHub Actions", then
  run the workflow once (see the README's setup steps).
- The page's folder is `page/` instead of `docs/`: it's the page, not
  documentation, and the workflow that publishes it can take any folder.
- Missing package lists, lists that don't evaluate, and a missing `nix` stop
  the sync with a message saying what to do, not a traceback.

## [0.6.0] - 2026-10-01

nixkeeper's own visual identity: a mark, a wordmark and colours, on the page,
in the README and in the repository's social preview.

### Added

- nixkeeper's mark: a hexagonal ring of three chevrons (new releases, build
  and update failures, vulnerabilities) around a solid centre (the package),
  in violet turning to mauve. It's the page's favicon.
- The wordmark: "nixkeeper" in Oxanium Bold, lowercase. The lockups (the mark
  with the wordmark) carry it as outlines, so they look the same everywhere
  without the font, on transparent backgrounds for light and dark. The
  page's header and the README's title are now the lockup.
- The page's tab icon shows what needs attention: the mark's chevrons light
  up for a new release (orange), a failure or a vulnerability (pink), and the
  releases chevron turns green when all is well. It follows the list filter,
  like the counts.
- nixkeeper's identity, in `assets/brand/`: a guide (`BRAND.md`), the mark
  and its variants, status versions (all good, a new release, a failure, a
  vulnerability), lockups, colour tokens and an identity sheet, generated by
  `scripts/brand/` (`nix run .#brand`, which fetches the wordmark's font, one
  pinned file, and outlines it with HarfBuzz). Under the MIT License, like
  the code. The pages the wordmark was chosen from are kept in
  `assets/brand/explorations/`.
- The social preview is a card: the lockup, what nixkeeper watches, and the
  page (`scripts/social-preview.html`, rendered by `nix run .#screenshots`).

### Changed

- The page's statuses use the identity's colours: up to date in Zambian
  Green, outdated in Persian Orange, failed and vulnerable in Norwegian Pink.
  Dots use the brighter tint, text a darker one, which is easier to read than
  before on both themes. Can't update, marked broken and a failed or
  unfinished build have their own Indian Gold instead of sharing outdated's
  colour. "On master" is in nixkeeper's violet instead of GitHub's purple,
  and open update PRs in the identity's green.
- Links and key UI on the page (focus outlines, active filters) are in
  nixkeeper's violet, from the brand's colour tokens, which the page now
  loads (`docs/tokens.css`).
- The docs call the frequent checks "about hourly": GitHub runs scheduled
  workflows on a best-effort basis, so they can be a few hours apart.

### Fixed

- On narrow tables, a package's status dot could end up on a line of its
  own, above the name; it now stays beside the name, and only the platform
  tags wrap.

## [0.5.0] - 2026-09-30

### Added

- Update checks for unstable versions (`github` + `branch` in
  `package-lists/update-checks.nix`): for a package whose nixpkgs version is
  `…-unstable-YYYY-MM-DD`, the commits since then on the branch it follows.
  Repology can't tell: it only tracks releases, and marks unstable versions
  "untrusted". The package counts as outdated once one of those commits has
  waited 90 days; `outdatedAfter = { days = …; commits = …; }` changes that
  per package (whichever comes first; `null` turns one off). Until then, the
  details list the newer commits as not counted yet. First one: stepmania
  (its `5_1-new` branch).
- Ignore rules for update attempts (`package-lists/ignored-updates.nix`): a
  version nixpkgs-update tried and failed that shouldn't count, such as one
  upstream never really released. Its failure shows as superseded, with the
  rule's reason; a failure at any other version still counts. The sync notes
  when a rule no longer matches the bot's latest attempt. First one: xskat's
  4.0-9.
- The build panel says which version last built on a failing platform, with
  a link to that build, next to the version that fails ("failed at 1.2.4 ·
  last succeeded at 1.2.3"). When both are the same, the version didn't break
  it; something else did (a dependency, the toolchain). Platforms that didn't
  build because of a dependency, or didn't finish, now show when they last
  succeeded too.
- The page links to nixkeeper's repository ("source and how it works") and
  to what its statuses and badges mean in its footer, and a copy of nixkeeper
  on GitHub Pages also links to its own package lists.
- The page has a description, for search engines and link previews.
- The README explains how to set up a dashboard of your own ("Track your own
  packages"), with screenshots of the page. How the code is laid out, the
  commands, and how changes and releases happen moved to
  `CONTRIBUTING.md`.
- The README explains how nixkeeper works (with a diagram) and how to read
  the page: every dot, badge and column state. `DATA.md` describes the data
  files, field by field, and `CONTRIBUTING.md` maps the code.
- Issue forms: "Track a package" and "Something looks wrong".
- A security policy (`SECURITY.md`): report vulnerabilities privately
  through GitHub's private vulnerability reporting.
- Dependabot (`.github/dependabot.yml`) proposes updates to the actions the
  workflows use, weekly.

### Changed

- The page fits narrow screens without scrolling sideways. On phones and
  windows up to 940px wide, each package is a card: its name and platforms,
  then its version and badges, then only what needs attention (build or
  update failures, open PRs and issues). The panels wrap to fit. In the
  table, a long version wraps (before "→", never inside a version) and
  platform tags go under the name when space is short, instead of widening
  the table past the screen.
- An outdated unstable version shows only the new date as its target
  ("5.1.0-b2-unstable-2022-11-14 → 2026-08-22"); the full version is in its
  tooltip and the details.

### Fixed

- A nixpkgs-update attempt that found a newer version but had no way to
  update the package ("The diff was empty after rewrites", e.g. a package
  with several hashes and no updateScript) showed as "nothing to update". It
  now shows as an amber "can't update", with the bot's reasons from the log:
  not a failure, but a sign the update needs doing by hand. After an
  updateScript run (`0 -> 1`), an empty diff still means nothing to update.
- Opening a package's details no longer shifts the table's columns: the
  panel's long list of repositories made the table redistribute its width, so
  the rows above moved (by up to ~90px). On a phone, a repository chip with a
  long version that can't break (`5.1.0~20221114gitd55acb1`) no longer sticks
  out past the screen; its version wraps inside the chip.

### Security

- The workflows' actions are pinned to commits (`nix-installer-action` ran
  from its `main` branch), so a change upstream can't run with the workflows'
  write access unreviewed. CI only gets read access, and CI and the release
  workflow don't keep the token in the checkout.
- Links on the page from data (homepages, update-check pages, logs, PRs,
  sources) are shown only if they're web addresses (`https:` or `http:`): a
  `javascript:` link, which escaping doesn't stop, isn't linked.

## [0.4.0] - 2026-09-29

### Added

- "On master": when master has a newer version than the nixos-unstable
  channel (built by Hydra, or brought by an update PR merged into master, so
  before Hydra has built it), the row says so, and an outdated package whose
  update is merged shows as waiting for the channel: in GitHub's merged-PR
  purple (its status dot and age, an "on master" badge like GitHub's "Merged"
  label, linking to the merged PR, and a note in the details), sorted after
  the other outdated packages. It doesn't trigger "Newly outdated" in the
  status issue. PRs merged into staging don't count: they reach master weeks
  later.
- Update PRs: an open PR updating a package (title
  `<attribute>: <old> -> <new>`, aiming past nixpkgs' version) shows as a
  badge linking to it, in GitHub's open-PR green (grey while a draft). The
  status issue links it too.
- Hourly PR check (`nix run .#pr-check`): the update PRs of every outdated
  package, open and merged into master, so those badges show within the hour.
  One GitHub request; it commits only when a badge changes.
- Release workflow ("Release: publish from tag", `release.yml`): pushing a
  version tag publishes a GitHub Release with that version's changelog
  section as notes, after checking the tag against `pyproject.toml` and the
  changelog and running the flake checks.

### Changed

- Workflows are named for what they do: "CI: tests and lint" (`ci.yml`, was
  `check.yml`), "Data: daily sync" (`data-daily.yml`, was `sync.yml`) and
  "Data: hourly updates (frequent packages, update PRs)" (`data-hourly.yml`,
  was `quick-check.yml`).
- The hourly workflow runs the frequent update checks (`nix run
  .#frequent-check`, renamed from `quick-check`, which still works) and the PR
  check, with one commit. The frequent check no longer refreshes GitHub
  counts: those stay daily.

### Fixed

- An update failure clears as soon as nixpkgs has moved on from the version
  the bot tried to update (someone updated it another way), shown as
  "superseded". Before, it only cleared at the bot's next attempt, up to ~10
  days later, for packages with their own update script (`0 -> 1` in the
  log), such as wesnoth-devel.
- A failure also counts as superseded once master has moved on (the fix is
  merged, not yet in the channel), so a row waiting for the channel doesn't
  also show as failed.
- The update cell shows a superseded failure as a grey "superseded" instead of
  "none reported", so a bot attempt that broke stays visible.

## [0.3.0] - 2026-09-28

### Added

- Platforms where nixpkgs marks a package broken (`meta.broken`, evaluated per
  platform at the channel's commit, since the package index only reflects
  x86_64-linux). They show as "marked broken" (amber) with a link to the
  package source, don't count as failed, and are listed in the status issue
  without notifying.
- Update failures from nixpkgs-update (r-ryantm), read from its public logs:
  the latest attempt per package, recognised as failed, PR opened, PR already
  open, or nothing to update. A failure counts as failed and notifies; one at a
  version nixpkgs has since reached is shown as superseded. Clicking the update
  cell shows the attempt, the end of a failed log, and links to the logs.

- nixkeeper's own update checks (`package-lists/update-checks.nix`): for a
  listed package, the newest version matching a pattern, either among its
  GitHub repository's tags or anywhere on a web page (such as the vendor's
  release notes). If that's newer than nixpkgs', the package counts as
  outdated even while Repology says newest, and the page says the check found
  it. `nix flake check` validates the entries and their patterns. First
  checks: wesnoth-devel (GitHub tags, the 1.19 series) and bbedit (its
  updates page).

- Sources that couldn't be refreshed are shown, not just logged: when an
  update check (GitHub or web page), Hydra or the nixpkgs-update logs fail, the
  row keeps its last known result and says so, with the reason and since when
  ("check failing" badge, "not refreshed" tags, a note in the panels). The
  status issue lists them under "Not refreshed" and comments once per newly
  failing source; working again is listed quietly.

- Packages Repology flags as vulnerable link to its list of known CVEs, in
  the package details and in the status issue.

- Hourly quick check (`nix run .#quick-check`, `quick-check.yml`): update
  checks marked `frequent = true` also run every hour against the last
  published data, refreshing just those packages' Repology data. Writes,
  commits and notifies only when something changed. First ones: google-chrome
  (Google's version history API) and microsoft-edge (Microsoft's Debian
  repository), Linux stable.

- MIT license (`LICENSE`, also declared in `pyproject.toml` and the flake's
  package metadata). The README notes where the published data comes from.

- Runs outside GitHub too (groundwork for self-hosting): the data directory,
  the package lists (Nix folder or JSON), a token file, the notification
  method and the page URL are settings (see the README). The page finds its
  data next to itself, through a `<meta>` setting, or on GitHub as before.

- Filters for the package lists: `extraPackages` in `package-lists/default.nix`
  holds named lists (`extra`, `gaming-team`), and the page shows a filter for
  each next to `maintained` (packages found through `maintainers`). The counts
  follow it, and `?list=<name>` is a shareable page of one list. A plain list
  still works, as `extra`.

### Changed

- Described as what it has become: "Health dashboard for the nixpkgs packages
  you maintain", in the README (with what it checks), the page ("your nixpkgs
  packages, at a glance"), `flake.nix` and `pyproject.toml`.
- Notifications go through a choice of method (`NIXKEEPER_NOTIFY`); the status
  issue is `github-issue` (the old value `1` still works). It never posts with
  the local `gh` login.
- The daily sync and the quick check share a concurrency group, so they never
  push to the data branch at the same time.
- Hydra and the update logs share one retrying HTTP helper.
- "Outdated" means outdated per Repology or per an update check, everywhere:
  the page, "outdated since" and the status issue.

### Fixed

- The data directory was fixed when the code loaded, so functions defaulting
  to it ignored a later setting.

## [0.2.0] - 2026-09-28

### Added

- Build failures from Hydra (jobset `nixpkgs/unstable`, i.e. master) for each
  tracked package on x86_64-linux, aarch64-linux and aarch64-darwin, limited to
  the platforms it declares. Unfree packages, which Hydra doesn't build, are
  skipped.
- Build panel on the page: clicking a row's build cell shows each platform's
  result, with links to the build or its log and when a failing job last built
  successfully. It shares the space under the row with the package details.
- Status issue: one issue in this repository, rewritten on every sync, listing
  what's failed, outdated, flagged vulnerable or not refreshed. A comment (which
  is what notifies) is posted when something newly needs attention, including a
  package starting to fail on another platform; good news is only listed.
- Links to where nixpkgs defines each package, at the channel's exact commit
  and line.
- Workflow warnings when GitHub search counts look wrong (failed searches, or
  every PR count equal to its issue count).
- `nix flake check` validates the package lists (unknown attributes or
  maintainer handles, aliases such as `python3Packages`, duplicates) and runs
  formatting and lint checks (nixfmt, ruff, biome, deadnix, statix,
  actionlint). `nix fmt` formats everything.
- This changelog.

### Changed

- The page is split into `index.html`, `app.js` and `style.css`.
- The "failed" filter follows the platform filter: with macOS selected, a
  failure only on Linux doesn't count.
- A Repology domain that answers is tried first for the rest of the run, so an
  unreachable repology.org costs one failed connection instead of one per
  lookup.
- Workflows use `actions/checkout@v7`.
- The flake takes its version from `pyproject.toml`.

### Fixed

- PR counts in CI came back equal to issue counts: the sync workflow now has
  `pull-requests: read`.
- actionlint found no workflows in the Nix check (no `.git` there); they're
  passed explicitly.

## [0.1.0] - 2026-09-28

First versioned release, covering everything from the start of the project up
to its restructuring into a Python package.

### Added

- Daily sync (GitHub Actions) that compares tracked nixpkgs-unstable packages
  with Repology and publishes the results to the `data` branch.
- Static page (GitHub Pages) reading that data:
  - clickable counts for tracked, outdated, failed and flagged-vulnerable
    packages, following Repology's wording;
  - separate rows for stable and devel variants (wesnoth / wesnoth-devel),
    with a shaded "devel" badge;
  - how long each package has been outdated;
  - platform tags (Linux, macOS) that filter the list;
  - open nixpkgs PR and issue counts, from title-only GitHub searches by
    attribute name;
  - sorting by what needs attention (failed, then longest outdated) or A–Z;
  - filters, search and sort kept in the address;
  - a warning when the data is more than two days old;
  - placeholder columns for build and update failures.
- Package lists in `package-lists/`: every package maintained by the listed
  GitHub handles, plus extra packages by attribute (nested sets such as
  `haskellPackages.foo` included) or pname.
- Package metadata (maintainers, platforms, homepage) from the nixos-unstable
  channel's package index, without evaluating nixpkgs.
- Repology lookups by nixpkgs attribute, falling back to the project name.
- Retries, a fallback Repology domain, and reuse of the previous run's data
  (marked "not refreshed") when a lookup fails; the run aborts if most fail.
- GitHub searches batched through GraphQL.
- Unit tests, run on every build and in CI.
- `nix run .#sync` (alias `.#fetch`).

### Changed

- The data directory is rebuilt on every run and swapped in at the end, so
  packages removed from the lists don't leave files behind.
- The sync script is a Python package (`nixkeeper/`) with tests in `tests/`.

[unreleased]: https://github.com/nixkeeper/nixkeeper/compare/v0.21.0...HEAD
[0.21.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.20.0...v0.21.0
[0.20.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.19.0...v0.20.0
[0.19.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.18.0...v0.19.0
[0.18.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.17.0...v0.18.0
[0.17.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.16.0...v0.17.0
[0.16.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.15.0...v0.16.0
[0.15.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.14.1...v0.15.0
[0.14.1]: https://github.com/nixkeeper/nixkeeper/compare/v0.13.0...v0.14.1
[0.14.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/nixkeeper/nixkeeper/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/nixkeeper/nixkeeper/releases/tag/v0.1.0
