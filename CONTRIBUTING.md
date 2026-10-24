# Contributing to nixkeeper

How the code is laid out, how to work on it, and how changes and releases
happen. For what nixkeeper does and how to set up your own, see the
[README](README.md) and the [documentation](docs/README.md).

## Layout

- `nixkeeper/`: the sync and the hourly checks, as a Python package (see
  [The code](#the-code))
- `tests/`: offline tests, one file per module (nothing reaches the network:
  sources are faked). `tests/js/` tests the page's rules (`page/logic.js`),
  a package panel's sections (`page/panel.js`), how it reads its data
  (`page/data.js`, with `fetch` stood in for), its address
  (`page/state.js`), a package's panel (`page/package-view.js`, the parts
  that are HTML), the overview (`page/overview.js`), a maintainer's page
  (`page/maintainer-view.js`), what the list keeps (`page/filters.js`), the
  list's rows and cells (`page/list.js`), the views' controls (wired onto
  stand-in elements) and the search box's query (`page/search.js`) with
  Node's own test runner
- `nix/package.nix`: nixkeeper's package, in nixpkgs' by-name style (the
  flake builds it from the checkout; see [Releasing](#releasing))
- `nix/module.nix`: the NixOS module (`nixosModules.default`).
  `nix flake check` evaluates it in a NixOS configuration on any system,
  and on Linux boots it in a VM (`nix/module-test.nix`; CI runs it)
- `nix/darwin-module.nix`: the nix-darwin module (`darwinModules.default`),
  evaluated in a nix-darwin configuration by `nix flake check` (nix-darwin
  is a flake input for that only). `nix/module-common.nix` holds what both
  modules share: the options for the lists, the token and notifications
- `nix/package-lists.nix`: `nix flake check` validates the package lists
  against nixpkgs (typos, aliases like `python3Packages`, unknown maintainer
  handles, duplicates, malformed update checks, ignore and up-to-date rules)
- `package-lists/`: what this instance tracks (see
  [how it works](docs/how-it-works.md#what-gets-tracked))
- `community/update-checks.nix`: the community update checks, rules anyone
  can add by PR; `community/ignored-updates.nix`, the community ignore
  rules; and `community/up-to-date.nix`, the community up-to-date rules
  ([docs/community.md](docs/community.md))
- `docs/`: the documentation, one page per topic ([docs/README.md](docs/README.md)
  lists them); `README.md`, `CONTRIBUTING.md`, `SECURITY.md`,
  `CHANGELOG.md` and `LICENSE` stay at the root, where GitHub looks for them
- `page/`: the page (`index.html`, `app.js`, `style.css`), reading `data/`
  from the `data` branch. `logic.js` holds its rules (statuses, versions,
  ages, safe links, the tab icon's signals) without the page, so they can be
  tested; `overview.js` the overview (the cards, trends, causes, sets,
  fixes, nixpkgs in numbers); `maintainer-view.js` a maintainer's or team's
  page (You can merge these, Can be closed) and the maintainers page;
  `package-view.js` a package's panel (Details, Updates, Builds), given what
  it needs of the page (`panelPage` in `app.js`: a package's address, hiding
  it, drawing again); `panel.js` its sections (vulnerabilities, builds, On
  GitHub), from the package alone, tested too; `ui.js` the small pieces of
  HTML and text they and the list share (numbers, dates, icons, why a build
  failed); `data.js` where the data is and how it's read (its files as JSON,
  the shards' rows once each); `state.js` the filters, sort and paging in
  one object (`state`), read from the address and written back (`readState`,
  `writeState`), and a view's address (`scopeHref`, with the tables `app.js`
  gives it in `known`); `list.js` the list (its header with the tiles,
  refines and facets, Your packages and Your team, each row and its cells,
  where the data is from); `filters.js` what the list keeps (the tiles'
  filters, refines, sorts, platforms, and the list worked out with them);
  `search.js` the search box as a query (`is:builds on:darwin`: parseQuery,
  writeQuery, needsList: the words that open a list from the overview,
  matchNote: what status: and ofteam: wait for) and
  its menu (suggest, wireSearchMenu; the values and counts
  from list.js's searchValues); `prefs.js` what this browser keeps (localStorage, the rows
  hidden here); `store.js` what's loaded of the data, in one object
  (`store`); `app.js` imports them, changes the state, fills the store and
  draws the page. Each view wires its own controls (`wireList`,
  `wireOverview`, `wireMaintainerView`), given what they need of the page
  (`pageHooks` in `app.js`); `app.js` keeps the search box's listeners, the
  links between views, the theme menu and the keyboard. Native ES modules,
  no build step: `index.html` preloads each (`modulepreload`), so a new
  module goes there too. `favicon*.svg` (the mark, and the live status icons
  the page switches between), `nixkeeper-lockup-tight*.svg` (the header) and
  `tokens.css` are copies from `assets/brand/`, written by `nix run .#brand`
- `assets/`:
  - `brand/`: nixkeeper's identity: the guide (`BRAND.md`), the mark and
    its variants, status versions and lockups as SVGs, the colour tokens
    (`tokens.css`, `tokens.json`) and the identity sheet (`identity.html`),
    all generated by `scripts/brand/` (see [Brand](#brand)), and
    `explorations/`, the pages the wordmark was chosen from. The page's own
    copy of the favicon is `page/favicon.svg`, since only `page/` is
    published.
  - `screenshots/`: the page, for the README (light and dark, desktop and
    phone, in the Classic and Catppuccin palettes) and the repository's
    social preview, taken by
    `scripts/screenshots.sh` (see [Screenshots](#screenshots))
- `.github/workflows/`:
  - `ci.yml`, **CI: tests and lint**: checks nixkeeper's own code on every
    push and PR
  - `data-daily.yml`, **Data: sync** (the file keeps its old name): updates
    all package data
  - `community-checks.yml`, **Community: update checks still work**: runs
    every community rule for real weekly, keeping the "Community rules
    status" issue up to date (`nixkeeper community-check
    --report-issue`), and on PRs that change `community/`, the rules they add
    or change (`--changed-from`), failing if one finds nothing (see
    [docs/community.md](docs/community.md))
  - `pages.yml`, **Pages: publish the page**: publishes `page/` to GitHub
    Pages whenever it changes on `main` (Pages' source is "GitHub Actions")
  - `data-hourly.yml`, **Data: hourly updates (frequent packages, update PRs)**:
    the frequent update checks and outdated packages' update PRs. Scheduled
    hourly, but GitHub may delay or skip scheduled runs under load, so gaps of
    a few hours between runs are normal
  - `release.yml`, **Release: publish from tag**: a GitHub Release for each
    version tag (see [Releasing](#releasing))

## The code

`nixkeeper/cli.py` is the `nixkeeper` command: it reads the flags and runs
the subcommand's module. `nixkeeper/sync.py` runs one sync, top to bottom:

| Step | Module |
|---|---|
| read the package lists, the channel's package index and its revision | `sources/nixpkgs.py` |
| work out which packages to track, and which lists each is on | `tracking.py` |
| check the lists for mistakes (a handle no package lists, ...) | `listcheck.py` |
| load the previous run's data, for lookups that fail | `history.py` |
| look each one up on Repology (falling back to the last run) | `lookup.py`, `sources/repology.py` |
| turn Repology's projects into the page's rows, and link nixpkgs' source | `rows.py` |
| run nixkeeper's own update checks | `sources/upstream.py` |
| carry "outdated since" over from the previous run | `history.py` |
| where nixpkgs marks them broken, and Hydra's builds | `sources/nixpkgs.py`, `sources/hydra.py` |
| the nixpkgs-update bot's latest attempts | `sources/nixpkgs_update.py` |
| open PR and issue counts, and update PRs | `sources/github.py` |
| check `data/` against its shape, then write it | `shape.py`, `datastore.py` |
| rewrite the status issue, commenting on what's newly wrong | `notify.py`, `changes.py` |

Around that:

- `config.py`: settings (the command's flags set them, over their
  environment variables, over the defaults: the user's XDG folders), and the
  addresses of every source
- `init.py` and `templates/package-lists/`: `nixkeeper init`'s starter lists
  (`nix flake check` validates them like the real ones)
- `community.py`: the community update checks (`community/update-checks.nix`,
  shipped in the package like the page): opting in, merging with the lists'
  own, and the limits community rules are held to (with `sources/http.py`'s
  safe mode)
- `lock.py`: one run at a time on a data folder (`<data dir>.lock`), for
  every command that writes or copies the data
- `shape.py`: what `data/` must look like, checked before each write (the
  sync's and the hourly checks'): a row's fields and their types (`ROW`:
  a field added to the rows is added there and to `docs/data.md`, which a
  test holds to it), and the manifest's counts against the views they
  count. For now its problems are reported in the log (`Data shape: ...`)
- `page.py`: `nixkeeper page` and `nixkeeper serve`. The package carries the
  page: its build copies `page/` into `nixkeeper/page/` (and links it as
  `share/nixkeeper/www/`); from a checkout, `page/` itself
- `versions.py`: comparing version strings
- `sources/http.py`: GET with retries, for the sources that need no more
- `frequent.py`, `prcheck.py`: the hourly checks, which start from the last
  published data and publish through `partial.py` only when a row changed

Each source that can fail keeps the row's previous result and records it as
not refreshed (`history.not_refreshed`), so one unreachable service never
blanks the page.

## Commands

```bash
nix run .#sync            # nixkeeper sync, into data/ (alias: nix run .#fetch)
nix run .#frequent-check  # only the frequent update checks, against data/ (hourly in CI)
nix run .#pr-check        # outdated packages' update PRs, against data/ (hourly in CI)
nix run .#sync -- --help  # the command's flags (each app passes its arguments on)
nix run . -- paths        # the command as installed: your own folders, not the checkout's
nix fmt                   # format everything (Nix, Python, the page), and sort the lists
nix flake check           # tests, formatting, linters, package-list checks
nix develop -c python3 -m unittest discover -s tests -t .   # tests, quickly
nix develop -c node --test 'tests/js/*.test.mjs'            # the page's tests
nix run .#community-check -- <attribute>   # try a community update check for real
nix eval --json -f package-lists                             # what the lists evaluate to
nix run .#screenshots -- --browser google-chrome   # retake the screenshots in assets/screenshots/
nix run .#brand           # regenerate assets/brand/ and the page's favicon
```

New files must be `git add`ed before Nix sees them.

The package lists and the community rules (update checks, ignore and
up-to-date rules) are kept sorted by `nix fmt` (keep-sorted), so a
package's rule is easy to find: add an entry anywhere between the
`keep-sorted` comments, and `nix fmt` moves it into place; `nix flake check`
fails on a list out of order.

## Changes

`main` only changes through pull requests: squash-merged, once CI
(`tests-and-lint`) passes, so each PR is one commit on `main`, titled after
the PR. Direct and force pushes to `main` are blocked (repository rulesets).
Changes that users would notice go in `CHANGELOG.md` under `## [Unreleased]`,
in the same PR, and so do the docs that describe them:
`docs/reading-the-page.md` for a new or changed status, badge or column,
`docs/data.md` for a field, and the [screenshots](#screenshots) when the page looks noticeably
different. The PR template has this as a checklist.

Security problems go through the [security policy](SECURITY.md), not a
public issue.

## Screenshots

The screenshots in `assets/screenshots/` are of the page's current code (`page/`) with
live data, taken in a headless browser:

```bash
nix run .#screenshots -- --browser google-chrome
```

In this repository that takes both sets: the overview's (`overview-*.png`)
from the community instance, nixkeeper.com, and the list's from the demo,
demo.nixkeeper.com (a fork tracking a maintainer's packages and the gaming
team's). In a copy of the repository it takes the set its own data makes
(its `data` branch on GitHub). Each set is ten files, compressed, five in each of the page's palettes:
`desktop-{dark,light}.png` (1280px wide, at 2x, with a panel open),
`mobile-{dark,light}.png` (390px, at 2x) and `social-preview.png` (a
1280×640 card at 2x: the lockup, what nixkeeper watches, and the dark
desktop shot; its layout is `scripts/social-preview.html`). Those are
Classic; Catppuccin's (Latte when light, Mocha when dark) end in
`-catppuccin`, e.g. `desktop-dark-catppuccin.png`. The overview's are the
same, starting with `overview-` (its desktop shot taller, 1280×1180, with
no panel). The social preview is then uploaded by hand: Settings → General
→ Social preview.

| Option | What it sets |
|---|---|
| `--browser <name or path>` | required: a Chromium-based browser, either a nixpkgs package (`google-chrome`, `chromium`, `ungoogled-chromium`, `brave`, `microsoft-edge`, `vivaldi`), fetched only when used, or the path to one's executable (e.g. `/Applications/Chromium.app/Contents/MacOS/Chromium`). Not every package exists on every system: `chromium` and `ungoogled-chromium` are Linux-only. Firefox can't be used: its headless screenshots come before the page has loaded its data. |
| `--open <row>:<panel>` | the panel open in the list's desktop shots. The row: a package's name as the page shows it, or a position in the page's order (`1` is the first row; past the last, the last). The panel: `info` (its details), `build`, `update`, or `auto` (update if it has something to show, else build likewise, else info). `none` for no panel. Default: `4:auto`: a few rows of the table above the panel, the whole panel in the shot |
| `--data <url or folder>` | that data alone: the folder with `index.json`, a URL or a local folder. A list-based instance's makes the list's set, every package's the overview's |
| `--overview-data`, `--list-data <url or folder, or none>` | each set's data; `none` leaves that set's files as they are. Defaults, in this repository: the community instance's `data` branch (`https://raw.githubusercontent.com/nixkeeper/nixkeeper/data/data/`), and the data demo.nixkeeper.com's page names; in a copy, its own `data` branch. Your own list's shots beside the community overview, say: `--list-data https://raw.githubusercontent.com/<you>/<repo>/data/data/` |
| `--port <port>` | the port of the local server that shows the page to the browser. Default: 8799 |

`--open`, `--data`, `--overview-data`, `--list-data` and `--port` can also
be set in the environment (`OPEN`, `DATA`, `OVERVIEW_DATA`, `LIST_DATA`,
`PORT`); the argument wins. `--help` lists them all. The script
checks the data and the panel before starting, and uses a throwaway browser
profile.

## Brand

nixkeeper's identity is in `assets/brand/`: `BRAND.md` says what it is and
how to use it, `identity.html` shows it all on one page. Everything there is
generated, so edit the scripts in `scripts/brand/`, not the files:

| Script | Writes |
|---|---|
| `geometry.py` | (shared) the mark's geometry and the brand colours |
| `generate.py` | the mark, its variants, status versions and lockups, as SVGs |
| `wordmark.py` | (used by `generate.py`) the wordmark as outlines, from the Oxanium font file the app fetches |
| `tokens.py` | `tokens.css` and `tokens.json`: the palette and the page's colour roles |
| `identity.py` | `identity.html`, from the tokens and the SVGs |

```bash
nix run .#brand
```

runs all three in order (fetching the wordmark's font first) and copies the
favicons, the header's lockups and the tokens to `page/`, for the page.
Commit the regenerated files with the change to the scripts.

The page's own colours (`page/style.css`) are variables that point at the
tokens' roles, e.g. `--accent: var(--nk-link-text)`, so a change to the
palette reaches the page through `nix run .#brand`.

## Releasing

1. In a PR titled `chore: release x.y.z`: set the new `version` in
   `pyproject.toml` (the flake reads it from there), and turn
   `## [Unreleased]` in `CHANGELOG.md` into `## [x.y.z] - date` (with a fresh
   `## [Unreleased]` above it, and its compare link below), and move the
   pinning example in `docs/command.md` ("Pinning a version") to the new
   tag.
2. Once merged, tag the merge commit on `main` and push the tag:
   `git switch main && git pull`, `git tag vx.y.z`, `git push origin vx.y.z`.

The release workflow checks that the tag matches `pyproject.toml` and has a
changelog section, runs the flake checks, and publishes the GitHub Release
with that section as its notes. If a check fails, nothing is published.

`nix/package.nix` is ready for nixpkgs, for when nixkeeper has users beyond
its author (nixpkgs prefers packages proposed and merged by others): as
`pkgs/by-name/ni/nixkeeper/package.nix`, it's the same file with `src` and
`version` replaced by the release (its header comment shows how). Until then,
the flake is how nixkeeper is installed. Once it's in nixpkgs, the
nixpkgs-update bot proposes each new release there by itself; changes to
`nix/package.nix` itself (a new dependency, say) go to nixpkgs by hand, with
that release's update.

Version tags can't be moved or deleted (a tag ruleset), so a published
version never changes. If a release fails, fix it in a PR and release the next
patch version (x.y.z+1) instead of reusing the tag; a tag whose release
failed stays unreleased.
