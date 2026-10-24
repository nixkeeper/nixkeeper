// The page's shared pieces of HTML: numbers, dates, icons, why a build
// failed. Used by app.js and panel.js.
import { daysText, html, raw } from './logic.js';
import { state } from './state.js';
import { store } from './store.js';

// GitHub's own icons (Octicons, (c) GitHub, MIT licence), 14px, in the
// text's colour: an open PR, a draft, a merged one, an open issue. In the
// list's GitHub cell and before each PR and issue in a package's details.
export const octicon = (d) =>
  raw(
    `<svg class="gh-icon" viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">${d
      .map((p) => `<path d="${p}"/>`)
      .join('')}</svg>`,
  );

export const GH_ICONS = {
  pr: octicon([
    'M1.5 3.25a2.25 2.25 0 1 1 3 2.122v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.25 2.25 0 0 1 1.5 3.25Zm5.677-.177L9.573.677A.25.25 0 0 1 10 .854V2.5h1A2.5 2.5 0 0 1 13.5 5v5.628a2.251 2.251 0 1 1-1.5 0V5a1 1 0 0 0-1-1h-1v1.646a.25.25 0 0 1-.427.177L7.177 3.427a.25.25 0 0 1 0-.354ZM3.75 2.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm0 9.5a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm8.25.75a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0Z',
  ]),
  draft: octicon([
    'M3.25 1A2.25 2.25 0 0 1 4 5.372v5.256a2.251 2.251 0 1 1-1.5 0V5.372A2.251 2.251 0 0 1 3.25 1Zm9.5 14a2.25 2.25 0 1 1 0-4.5 2.25 2.25 0 0 1 0 4.5ZM2.5 3.25a.75.75 0 1 0 1.5 0 .75.75 0 0 0-1.5 0ZM3.25 12a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5Zm9.5 0a.75.75 0 1 0 0 1.5.75.75 0 0 0 0-1.5ZM14 7.5a1.25 1.25 0 1 1-2.5 0 1.25 1.25 0 0 1 2.5 0Zm0-4.25a1.25 1.25 0 1 1-2.5 0 1.25 1.25 0 0 1 2.5 0Z',
  ]),
  merged: octicon([
    'M5.45 5.154A4.25 4.25 0 0 0 9.25 7.5h1.378a2.251 2.251 0 1 1 0 1.5H9.25A5.734 5.734 0 0 1 5 7.123v3.505a2.25 2.25 0 1 1-1.5 0V5.372a2.25 2.25 0 1 1 1.95-.218ZM4.25 13.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm8.5-4.5a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5ZM5 3.25a.75.75 0 1 0 0 .005V3.25Z',
  ]),
  issue: octicon([
    'M8 9.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3Z',
    'M8 0a8 8 0 1 1 0 16A8 8 0 0 1 8 0ZM1.5 8a6.5 6.5 0 1 0 13 0 6.5 6.5 0 0 0-13 0Z',
  ]),
};

export function longDate(iso) {
  return new Date(iso).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  });
}

export const fmt = (x) => (x || 0).toLocaleString();

export const shortDay = (day) =>
  new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  });

// Why a build failed on Hydra (nixkeeper-hydra's reasons, from its log): a
// word for the filter, a sentence for the panel.
export const BUILD_FAILED = {
  compile: { short: 'compile error', text: 'the compiler stopped at an error in the source' },
  tests: { short: 'tests', text: 'it built, but its tests failed' },
  link: {
    short: 'link error',
    text: "linking failed: a symbol or library the linker couldn't find",
  },
  header: { short: 'missing header', text: "a header the compiler couldn't find" },
  cmake4: {
    short: 'CMake 4',
    text: 'CMake 4 refuses projects asking for CMake older than 3.5 (cmake_minimum_required)',
  },
  cmake: { short: 'CMake', text: 'CMake failed to configure it' },
  boost: { short: 'Boost 1.89', text: "CMake couldn't use Boost 1.89" },
  pythonImport: { short: 'Python import', text: "a Python module it imports isn't there" },
  pythonDeps: {
    short: 'Python dependencies',
    text: "a Python dependency is missing, or its version isn't one the package accepts",
  },
  pythonBuild: { short: 'Python build', text: 'the Python build backend or setup failed' },
  pythonMetadata: {
    short: 'Python metadata',
    text: "the package's metadata doesn't match nixpkgs' (its version or name)",
  },
  haskellDeps: {
    short: 'Haskell dependencies',
    text: 'a Haskell dependency is missing, or the wrong version',
  },
  npm: { short: 'npm', text: "npm couldn't install its dependencies" },
  lisp: { short: 'Lisp', text: 'the Lisp build (SBCL) failed' },
  home: {
    short: 'writes to $HOME',
    text: "it writes to the home directory, which builds don't have",
  },
  download: { short: 'download', text: "a source couldn't be downloaded from any mirror" },
  hash: {
    short: 'hash',
    text: "a download's hash isn't the one nixpkgs expects: the source changed",
  },
  patch: { short: 'patch', text: "one of nixpkgs' patches no longer applies" },
  substitute: {
    short: 'substitute',
    text: 'a text substitution in nixpkgs no longer finds what it replaces',
  },
  missingFile: { short: 'missing file', text: 'a file the build expects is missing' },
  symlinks: { short: 'broken symlinks', text: 'it installs symlinks that point nowhere' },
  patchelf: {
    short: 'missing libraries',
    text: "autoPatchelf couldn't find libraries the binaries need",
  },
  autotools: { short: 'autotools', text: 'aclocal failed: an autotools dependency is missing' },
  disk: {
    short: 'out of disk',
    text: "Hydra's builder ran out of disk space: not the package",
    infra: true,
  },
  other: { short: 'other', text: 'none of the known reasons' },
  noLog: { short: 'no log', text: 'Hydra has no log of it' },
  unread: { short: 'not read yet', text: "nixkeeper-hydra hasn't read its log yet" },
};

// Icons in the panels: Tabler Icons' outlines (MIT,
// https://tabler.io/icons, @tabler/icons 3.49.0), inline: no font to load.
export const ICONS = {
  'chart-dots-3':
    '<path d="M3 7a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M14 15a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M15 6a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"/><path d="M3 18a3 3 0 1 0 6 0a3 3 0 1 0 -6 0"/><path d="M9 17l5 -1.5"/><path d="M6.5 8.5l7.81 5.37"/><path d="M7 7l8 -1"/>',
  'chevron-down': '<path d="M6 9l6 6l6 -6"/>',
  'external-link':
    '<path d="M12 6h-6a2 2 0 0 0 -2 2v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-6"/><path d="M11 13l9 -9"/><path d="M15 4h5v5"/>',
  'file-text':
    '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2"/><path d="M9 9l1 0"/><path d="M9 13l6 0"/><path d="M9 17l6 0"/>',
  history: '<path d="M12 8l0 4l2 2"/><path d="M3.05 11a9 9 0 1 1 .5 4m-.5 5v-5h5"/>',
  hammer:
    '<path d="M11.414 10l-7.383 7.418a2.091 2.091 0 0 0 0 2.967a2.11 2.11 0 0 0 2.976 0l7.407 -7.385"/><path d="M18.121 15.293l2.586 -2.586a1 1 0 0 0 0 -1.414l-7.586 -7.586a1 1 0 0 0 -1.414 0l-2.586 2.586a1 1 0 0 0 0 1.414l7.586 7.586a1 1 0 0 0 1.414 0"/>',
  'file-code':
    '<path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2"/><path d="M10 13l-1 2l1 2"/><path d="M14 13l1 2l-1 2"/>',
  'git-branch':
    '<path d="M5 18a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M5 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M15 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M7 8l0 8"/><path d="M9 18h6a2 2 0 0 0 2 -2v-5"/><path d="M14 14l3 -3l3 3"/>',
  'git-merge':
    '<path d="M5 18a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M5 6a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M15 12a2 2 0 1 0 4 0a2 2 0 1 0 -4 0"/><path d="M7 8l0 8"/><path d="M7 8a4 4 0 0 0 4 4h4"/>',
  home: '<path d="M5 12l-2 0l9 -9l9 9l-2 0"/><path d="M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2 -2v-7"/><path d="M9 21v-6a2 2 0 0 1 2 -2h2a2 2 0 0 1 2 2v6"/>',
  'list-check':
    '<path d="M3.5 5.5l1.5 1.5l2.5 -2.5"/><path d="M3.5 11.5l1.5 1.5l2.5 -2.5"/><path d="M3.5 17.5l1.5 1.5l2.5 -2.5"/><path d="M11 6l9 0"/><path d="M11 12l9 0"/><path d="M11 18l9 0"/>',
  package:
    '<path d="M12 3l8 4.5l0 9l-8 4.5l-8 -4.5l0 -9l8 -4.5"/><path d="M12 12l8 -4.5"/><path d="M12 12l0 9"/><path d="M12 12l-8 -4.5"/><path d="M16 5.25l-8 4.5"/>',
  tag: '<path d="M6.5 7.5a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/><path d="M3 6v5.172a2 2 0 0 0 .586 1.414l7.71 7.71a2.41 2.41 0 0 0 3.408 0l5.592 -5.592a2.41 2.41 0 0 0 0 -3.408l-7.71 -7.71a2 2 0 0 0 -1.414 -.586h-5.172a3 3 0 0 0 -3 3"/>',
  world:
    '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 0 0 -18 0"/><path d="M3.6 9h16.8"/><path d="M3.6 15h16.8"/><path d="M11.5 3a17 17 0 0 0 0 18"/><path d="M12.5 3a17 17 0 0 1 0 18"/>',
};

export const icon = (name) =>
  raw(
    `<svg class="ic" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name]}</svg>`,
  );

export const hydraBuildUrl = (build) =>
  `https://hydra.nixos.org/build/${encodeURIComponent(build)}`;

// Where an update merged into staging or staging-next is, and what it waits
// for: staging-next's merge into master (about every two to three weeks),
// or before that, the next staging-next.
export function stagingWait(pr) {
  return pr.on === 'staging-next'
    ? `reaches master when staging-next is merged into it${pr.cycle ? ` (#${pr.cycle.n}, open since ${shortDay(pr.cycle.cut.slice(0, 10))})` : ''}`
    : 'goes to staging-next when the next one is cut from staging, then to master with it';
}

// Repology's unique with nothing to compare (nothingCompared).
export const ONLY_NIXPKGS_TEXT =
  "Only nixpkgs packages it, and nixkeeper has no update check for it: there's nothing to compare its version with";

// nixpkgs' 0-unsupported (rows.UNSUPPORTED): not built in its default
// configuration, so no version to compare.
export const UNSUPPORTED_TEXT =
  "nixpkgs doesn't build it in its default configuration (0-unsupported: for the CUDA it defaults to, say), so there's no version to compare";

// A set kept current in bulk by its own tooling (rPackages: the CRAN
// import), not one PR per package: what updates it, from index.json's
// "profiles" (config.SET_PROFILES). Data from before has none: said plainly.
export const profileOf = (set) => store.manifest?.profiles?.[set] || null;

export const bulkText = (set) =>
  `Kept current in bulk by ${profileOf(set)?.updatedBy || 'its own tooling'}, not one PR per package`;

// No longer on CRAN or in the Bioconductor release nixpkgs pins (the row's
// "archived", sources/cran_digest.py).
export const ARCHIVED_TITLE =
  "No longer on CRAN or in the Bioconductor release nixpkgs pins: CRAN archived it (it failed CRAN's checks and wasn't fixed, or its maintainer left), or Bioconductor dropped it";

export const archivedText = (pkg) =>
  `${ARCHIVED_TITLE}. ${pkg.markedBroken ? 'nixpkgs marks it broken.' : "nixpkgs doesn't mark it broken: likely broken anyway, or due for removal."}`;

export const LOOKUP_FAILED =
  "Repology couldn't be reached on the last sync, and there's no earlier data";

export const UNVERSIONED_TITLE =
  "Not software with releases to compare (a system component): its builds are what's checked";

// A source the last sync couldn't refresh ("builds", "update", "upstream"):
// what's shown is from before `since`. null if it refreshed fine.
export const notRefreshed = (pkg, source) => pkg.notRefreshed?.[source] || null;

export const staleText = (info, what) =>
  `${what} since ${longDate(info.since)} (${daysText(info.since)}): ${info.reason}`;

// Whether Hydra built this at all: not for unfree packages, nor ones nixpkgs
// keeps off Hydra (hydraPlatforms).
export function hydraBuildsIt(pkg) {
  return !pkg.unfree && pkg.builds.some((b) => b.status !== 'notBuilt');
}

// Why the bot's attempt failed ("failedBecause"), as the log says: short in
// the list, said in full in the panel. None recognised: "other".
export const FAILED_BECAUSE = {
  unavailable: {
    short: 'unavailable',
    text: "nixpkgs won't build it where the bot builds (x86_64-linux): it or a dependency is broken, insecure or not for that platform",
  },
  patch: {
    short: 'patch',
    text: "nixpkgs' changes to the source (patches, substitutions) don't apply to the new version",
  },
  dependency: {
    short: 'dependency',
    text: "the new version needs a dependency nixpkgs doesn't give it: missing, or too old",
  },
  hash: {
    short: 'hash',
    text: "the bot couldn't work out a hash: of vendored dependencies, mostly, which failed to fetch or build",
  },
  source: { short: 'source', text: "the new version's source couldn't be fetched" },
  // restates: its text only says the pill again ("Failed: updateScript"),
  // so the panel leaves it out (the log lines say the rest).
  updateScript: {
    short: 'updateScript',
    text: "the package's updateScript failed",
    restates: true,
  },
  tests: { short: 'tests', text: 'the new version built, but its tests failed' },
  noLog: { short: 'build', text: 'the build failed, and nix kept no log of why' },
  build: { short: 'build', text: 'the new version failed to build', restates: true },
  request: {
    short: 'request',
    text: "a request of the bot's failed (to GitHub, mostly), not the package",
  },
  // The bot's own machine (its build users, its nix daemon): not the
  // package. Worth telling nixpkgs-update's maintainers while it's recent
  // (REPORT_DAYS); an older one was a past outage, fixed since (2026-09-28:
  // four hours, 1,306 attempts), which the bot's next round clears.
  bot: {
    short: 'bot',
    text: "the bot's machine failed (its build users group, or its nix daemon), not the package",
    report: true,
  },
};

export const bulkShort = (set) => profileOf(set)?.short || 'updated in bulk';

export const teamPicker = (label) => {
  // By name, whatever its case (the data's keys sort capitals first).
  const teams = Object.entries(store.manifest.views?.teams || {}).sort(([a], [b]) =>
    a.localeCompare(b, undefined, { sensitivity: 'base' }),
  );
  return teams.length
    ? html`<label class="team-pick"><span class="team-pick-label">Team</span> <select id="teamPick"><option value="">${label}</option>${teams.map(([t, count]) => html`<option value="${t}"${state.teamFilter && t.toLowerCase() === state.teamFilter.toLowerCase() ? raw(' selected') : ''}>${t} (${fmt(count)})</option>`)}</select></label>`
    : '';
};
