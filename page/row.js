// A row of the list and its cells, as HTML: the name, version, builds,
// update and GitHub cells, the badges, and the dot's title. Imports nothing
// that touches the page, so tests load it without a browser.

import { daysText, daysUntil, shortAge } from './dates.js';
import { familyLabel } from './facets.js';
import { PLATFORMS } from './filters.js';
import { html, raw, safeUrl } from './markup.js';
import { isHidden } from './prefs.js';
import { buildsWith, failedBuilds, hasFailure, listView, scopeHref, state } from './state.js';
import {
  buildFailedBecause,
  communityCheck,
  computeStatus,
  midway,
  neverBuiltOn,
  nothingCompared,
  olderVersionKept,
  onBranch,
  onMaster,
  onPlatform,
  targetVersion,
  unbuiltOn,
  unbuiltWhere,
  updateTitle,
  waitingForChannel,
} from './status.js';
import {
  archivedText,
  BUILD_FAILED,
  bulkShort,
  bulkText,
  FAILED_BECAUSE,
  failingSince,
  fmt,
  GH_ICONS,
  hydraBuildsIt,
  hydraBuildUrl,
  LOOKUP_FAILED,
  longDate,
  notRefreshed,
  ONLY_NIXPKGS_TEXT,
  stagingWait,
  staleText,
  UNSUPPORTED_TEXT,
  UNVERSIONED_TITLE,
  upstreamRepoLabel,
  upstreamRepoText,
} from './ui.js';
import { compareVersions, versionDiff } from './versions.js';
import { isVulnerable, vulnSources, vulnSummary } from './vulns.js';

// The systems of a family nixpkgs builds (SYSTEMS in nixkeeper/sources/nixpkgs.py).
const LINUX_SYSTEMS = ['x86_64-linux', 'aarch64-linux'];

// Where the package's update stands on GitHub, in GitHub's own colors:
// "on master" (merged, purple) while waiting for the channel, else an open
// update PR (green; grey while a draft). A link to the PR when it's known.
const badge = (cls, text, title, pr) =>
  pr
    ? html` <a class="badge ${cls}" href="${safeUrl(pr.url)}" target="_blank" rel="noopener" title="${title}">${text}</a>`
    : html` <span class="badge ${cls}" title="${title}">${text}</span>`;

// The update's badge: on master when that's all it waits for, else merged
// into staging or staging-next on its way there, else its PR, else the
// branch that has it (haskell-updates), waiting for its merge.
function prBadge(pkg) {
  if (waitingForChannel(pkg)) return masterBadge(pkg);
  if (pkg.stagingPR) return stagingBadge(pkg);
  if (pkg.openPR) return openPrBadge(pkg);
  return onBranch(pkg) ? branchBadge(pkg) : '';
}

function branchBadge(pkg) {
  const b = pkg.branch;
  return badge(
    'onmaster',
    `on ${b.name}`,
    `${b.name} already has ${b.version}: waiting for its merge into master (about every two weeks)`,
    b.build ? { url: hydraBuildUrl(b.build) } : null,
  );
}

function stagingBadge(pkg) {
  const pr = pkg.stagingPR;
  return badge(
    'onmaster',
    `on ${pr.on}`,
    `${pr.on} has ${pr.to}: merged in #${pr.number} (${pr.title}); it ${stagingWait(pr)}. A mass rebuild's way: weeks, not days`,
    pr,
  );
}

function masterBadge(pkg) {
  const pr = pkg.masterPR;
  return badge(
    'onmaster',
    'on master',
    `master already has ${onMaster(pkg)}: merged${pr ? ` in #${pr.number} (${pr.title})` : ''}, waiting for nixos-unstable to catch up (usually a few days)`,
    pr,
  );
}

function openPrBadge(pkg) {
  const pr = pkg.openPR;
  if (!pr) return '';
  const behind =
    targetVersion(pkg) && compareVersions(pr.to, targetVersion(pkg)) < 0
      ? ` (the newest is ${targetVersion(pkg)})`
      : '';
  return badge(
    pr.draft ? 'prdraft' : 'propen',
    `PR #${pr.number}`,
    `${pr.draft ? 'Draft update PR' : 'Update PR waiting for review'}: ${pr.title}${behind}`,
    pr,
  );
}

// The versions nixpkgs-update's queue would update a package to: a list
// entry's (summary), or a full row's candidates (one package alone).
const queuedTo = (pkg) =>
  pkg.queued?.to || [...new Set((pkg.queued?.candidates || []).map(([to]) => to))];

// A robot's head (nixpkgs-update, the bot), in the text's colour.
const BOT_ICON = raw(
  '<svg class="bot-icon" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M8 2.6v2"/><circle cx="8" cy="1.8" r="0.9" fill="currentColor" stroke="none"/><rect x="2.75" y="4.6" width="10.5" height="8.4" rx="2.2"/><circle cx="6" cy="8.6" r="1.05" fill="currentColor" stroke="none"/><circle cx="10" cy="8.6" r="1.05" fill="currentColor" stroke="none"/><path d="M1 7.8v2.2M15 7.8v2.2"/></svg>',
);

// A hard hat (Hydra's builders), in the text's colour: a failing build's
// mark in the build cell, as the robot is a failed update's.
const HAT_ICON = raw(
  '<svg class="bot-icon" viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3.2 11V9.6a4.8 4.8 0 0 1 9.6 0V11"/><path d="M6.6 5.1v3M9.4 5.1v3"/><rect x="1.5" y="11" width="13" height="2.4" rx="1.2"/></svg>',
);

// The robot in place of a cell's dot (updateCell): red, or "queued" amber
// and "match" green, the queue's colours (queuedState).
const botMark = (colour) =>
  html`<span class="bot-mark${colour ? ` ${colour}` : ''}" aria-hidden="true">${BOT_ICON}</span>`;

// Whether nixpkgs-update is set to try the package (the update cell's robot):
// { match: to the newest version, its last attempt fine, so its PR should
// follow; title }, or null.
function queuedState(pkg) {
  const st = computeStatus(pkg);
  const to = queuedTo(pkg);
  if (pkg.openPR || pkg.stagingPR || waitingForChannel(pkg)) return null;
  const target = st === 'warn' ? targetVersion(pkg) : null;
  let match = false;
  let title;
  if (to.length) {
    const newest = Boolean(target && to.includes(target));
    // Its last attempt went wrong: the next may as well.
    const doubtful = pkg.updateFailure || ['cantUpdate', 'skipped'].includes(pkg.update?.outcome);
    // Its last attempt made the PR, or found one or its branch already.
    const made = ['prOpened', 'prExists', 'branchExists'].includes(pkg.update?.outcome);
    match = newest && !doubtful;
    title = `nixpkgs-update is set to update it to ${newest ? `${target}, the newest` : `${to.join(' or ')}${target ? `, not the newest (${target})` : ''}`}${
      doubtful
        ? ", but its last attempt didn't work: the next may not either"
        : made
          ? ': its last attempt already made a PR, or found one (the update panel links it)'
          : newest
            ? ': its PR should follow'
            : ''
    }. When: the update panel`;
  } else if (pkg.queued?.script && st === 'warn') {
    title =
      "nixpkgs-update will run its updateScript, which decides the version: whether it's the newest, its PR will tell. When: the update panel";
  } else {
    return null;
  }
  return { match, title };
}

// "auto update in 4 days": when nixpkgs-update is set to update the package
// to the newest version (the green robot) and the queue says when, the
// update cell's text instead of "—" (nothing reported). Days from its
// expected day (queued.by), as the update panel's "Next attempt" counts.
function botDueText(pkg) {
  const by = pkg.queued?.by;
  if (!by || !queuedState(pkg)?.match) return null;
  const days = daysUntil(by);
  return days < 1
    ? 'auto update within a day'
    : `auto update in ${days === 1 ? 'a day' : `${days} days`}`;
}

// The version column: the versions on the left, badges on the right (so
// they line up from row to row). Up to date: nixpkgs' version, and what's
// said about it (devel, vulnerable, ...) at the right. Outdated, two lines:
// nixpkgs' version, and under it the newest, in full, with the start they
// share faded so the part that changes stands out ("→" hangs to its left).
// At the right, each line's badges: what's said about nixpkgs' version
// (devel, vulnerable, ...) beside it; the update's (its PR, on master, a
// failing check) beside the newest. Screen readers get the two versions in a
// sentence instead. Both versions are one button: it copies the update's
// title as nixpkgs writes it ("unciv: 4.22.1 -> 4.22.6").
// Whether a line's version and its badges won't fit side by side in the
// version column (its narrowest, about 28 characters of the version's
// font): then the badges go under the versions instead (.vcell.long), or
// they squeezed a long version into a line per few characters
// (linuxKernel.packages.linux_6_6.tbs's 7.2.11-unstable-2025-12-15, beside
// devel and on master, took 8 lines). Badges stack within their column, so
// the widest counts: about 0.95 of a character each, with 1.5 for the
// padding ("only in nixpkgs", 113px, fits beside 2020-01-31 at 1,081px).
const VERSION_LINE = 28;

function tooWide(version, badges) {
  const widest = Math.max(
    0,
    ...[...String(badges).matchAll(/class="badge[^"]*"[^>]*>([^<]*)</g)].map(
      (m) => m[1].length * 0.95 + 1.5,
    ),
  );
  return widest > 0 && String(version || '').length + 2 + widest > VERSION_LINE;
}

export function versionCell(pkg, st) {
  if (st === 'missing') return html`<span class="badge missing">not packaged</span>`;
  const now = pkg.nixVersion;
  const stale = notRefreshed(pkg, 'upstream');
  const failing = stale
    ? html`<span class="badge neutral" title="${staleText(stale, "nixkeeper's update check failing")}. ${communityCheck(pkg) ? "It's a community rule: report it to nixkeeper, or give the package a rule of your own." : 'Fix it in package-lists/update-checks.nix.'}">check failing</span>`
    : '';
  const about = html`${pkg.set ? bulkBadge(pkg.set) : ''}${olderVersionKept(pkg) ? html`<span class="badge neutral" title="${keptText(pkg)}">older version</span>` : pkg.unversioned && st === 'neutral' ? html`<span class="badge neutral" title="${UNVERSIONED_TITLE}">not versioned</span>` : st === 'neutral' ? html`<span class="badge neutral"${pkg.nixStatus === 'unsupported' ? html` title="${UNSUPPORTED_TEXT}"` : nothingCompared(pkg) ? html` title="${ONLY_NIXPKGS_TEXT}"` : ''}>${statusLabel(pkg.nixStatus)}</span>` : ''}${pkg.archived ? html`<span class="badge warn" title="${archivedText(pkg)}">archived</span>` : ''}${pkg.upstreamRepo ? html`<span class="badge ${pkg.upstreamRepo.movedTo && !pkg.upstreamRepo.archived ? 'neutral' : 'warn'}" title="${upstreamRepoText(pkg.upstreamRepo)}">${upstreamRepoLabel(pkg.upstreamRepo)}</span>` : ''}${pkg.dropPR && !pkg.dropPR.proposed ? html`<span class="badge warn" title="An open PR removes it from nixpkgs: #${pkg.dropPR.number} (${pkg.dropPR.title})">being removed</span>` : ''}${pkg.feed?.heldBack && st === 'ok' ? html`<span class="badge neutral" title="nixpkgs pins it to ${pkg.feed.name}: Hackage has ${pkg.feed.heldBack}, which Stackage holds back until its next series">Stackage LTS</span>` : ''}${pkg.devel ? html`<span class="badge devel ${st}">devel</span>` : ''}${vulnBadge(pkg)}${pkg.staleSince ? html`<span class="badge neutral" title="Repology lookup failed on the last run; this is data from ${new Date(pkg.staleSince).toLocaleString()}">not refreshed</span>` : pkg.lookupFailed ? html`<span class="badge neutral" title="${LOOKUP_FAILED}">not looked up</span>` : ''}`;
  if (st !== 'warn')
    return html`<div class="vcell${tooWide(now, html`${about}${failing}`) ? ' long' : ''}"><span class="v-now"><span class="v">${now}</span></span><span class="v-tags top">${about}${failing}</span></div>`;
  const target = targetVersion(pkg);
  const merged = waitingForChannel(pkg);
  const title = updateTitle(pkg);
  // A newer version under the one before it: the start they share faded,
  // the rest in colour, "→" hanging to its left.
  const step = (cls, from, to, colour) => {
    const d = versionDiff(from, to);
    // Outdated, but no newer version known (Repology says outdated without
    // one): say so, rather than a bare "?".
    if (!to)
      return html`<span class="${cls}" aria-hidden="true"><span class="arrow">→</span><span class="unknown">newer version unknown</span></span>`;
    return html`<span class="${cls}" aria-hidden="true" title="${to}"><span class="arrow">→</span><span class="same">${d.same}</span><span class="ref${colour}">${d.to}</span></span>`;
  };
  // Master partway there: its own line, with its badge, between the two.
  const mid = midway(pkg);
  const steps = mid
    ? html`${step('v-mid', pkg.nixVersion, mid, ' merged')}${step('v-next', mid, target, '')}`
    : step('v-next', pkg.nixVersion, target, merged ? ' merged' : '');
  // The update's badge alone (no other badge, master not partway): between
  // the two versions, level with the row's GitHub counts.
  const update = mid ? openPrBadge(pkg) : prBadge(pkg);
  const solo = !mid && String(update) && !String(about) && !String(failing);
  const said = mid
    ? `${now}, on master ${mid}, newest ${target || 'unknown'}`
    : `${now}, newest ${target || 'unknown'}`;
  const long =
    tooWide(now, about) ||
    (mid && tooWide(mid, masterBadge(pkg))) ||
    tooWide(target, html`${update}${failing}`);
  return html`<div class="vcell${mid ? ' three' : ''}${long ? ' long' : ''}">
    <button type="button" class="vcopy" data-copy="${title || ''}" title="Copy “${title || ''}”">
    <span class="v-now"><span class="v" aria-hidden="true">${now}</span><span class="sr-only">${said}</span></span>
    ${steps}
    </button>
    <span class="v-tags top">${about}</span>${mid ? html`<span class="v-tags mid">${masterBadge(pkg)}</span>` : ''}
    <span class="v-tags bottom${solo ? ' solo' : ''}">${update}${failing}</span>
  </div>`;
}

// Where a row's failing builds (on the platform picked, if any) never
// succeeded on Hydra: linux (both its systems), x86_64-linux or
// aarch64-linux, darwin; "" when nowhere.
function neverWhere(pkg) {
  if (!failedBuilds(pkg).length) return '';
  const systems = neverBuiltOn(pkg, state.platformFilter);
  const linux = systems.filter((s) => s.endsWith('-linux'));
  const shownSystems = linux.length === LINUX_SYSTEMS.length ? ['linux'] : linux;
  if (systems.some((s) => s.endsWith('-darwin'))) shownSystems.push('darwin');
  return shownSystems.join(', ');
}

function ageTag(pkg, st) {
  // Failing first: how long it's been broken, in the failure's colour. A
  // failing build that never succeeded has no date: "n/a" when nothing
  // else is dated (the build column says where).
  const never = neverWhere(pkg);
  const failing = hasFailure(pkg) && failingSince(pkg);
  if (failing)
    return html`<span class="age failing" title="Failing since ${longDate(failing)}${never ? `; never built on ${never}` : ''}">${shortAge(failing)}</span>`;
  if (never)
    return html`<span class="age failing" title="No date: never built on ${never}">n/a</span>`;
  if (st !== 'warn' || !pkg.outdatedSince) return '';
  return html`<span class="age${waitingForChannel(pkg) ? ' merged' : ''}" title="Outdated since ${longDate(pkg.outdatedSince)}">${shortAge(pkg.outdatedSince)}</span>`;
}

// The row's dot, on hover (the legend popover lists them all).
// Repology's statuses as the page says them, where the code isn't clear
// ("unlisted": with every package, one Repology doesn't know).
const STATUS_LABEL = { unlisted: 'not on Repology', unique: 'only in nixpkgs' };

// An older version kept beside a newer one (olderVersionKept): which.
const keptText = (pkg) =>
  pkg.keptBeside
    ? `An older version nixpkgs keeps on purpose: it also has ${pkg.keptBeside.attr} ${pkg.keptBeside.version}`
    : 'An older version nixpkgs keeps on purpose, beside a newer one';

const statusLabel = (status) => STATUS_LABEL[status] || status;

export const bulkBadge = (set) =>
  html`<span class="badge neutral" title="${bulkText(set)} (${set}): counted on its set's line on the overview">${bulkShort(set)}</span>`;

export const DOT_TITLE = {
  ok: 'Up to date: nixpkgs has the newest version',
  warn: 'Outdated: a newer release is out',
  merged: 'On master: the update is merged, waiting for nixos-unstable',
  missing: 'Not packaged: not in nixpkgs unstable',
  neutral:
    "Can't compare (a rolling or unusual version scheme), or an older version kept on purpose",
};

// A fold's lead: how many more it stands for, a button showing or folding
// them.
function foldButton(pkg) {
  const fold = listView.folds.get(pkg.name);
  if (!fold) return '';
  const more = fold.members.length - 1;
  const label = familyLabel(fold.members.map((m) => m.name)) || `${pkg.name} and the like`;
  return html`<button type="button" class="fold-btn" data-fold="${fold.key}" aria-expanded="${fold.open}" title="${fmt(more + 1)} packages one update moves together (${label}): ${fold.open ? 'fold them into one row' : 'show them all'}">${fold.open ? `fold ${fmt(more)}` : `+${fmt(more)} like it`}</button>`;
}

const CHEVRON = raw(
  '<svg class="icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg>',
);

// What a row's dot means, in words: its colour's, or why it's grey when
// only nixpkgs packages it.
const dotTitle = (pkg, st) =>
  waitingForChannel(pkg)
    ? DOT_TITLE.merged
    : nothingCompared(pkg)
      ? `Not compared: ${ONLY_NIXPKGS_TEXT.charAt(0).toLowerCase()}${ONLY_NIXPKGS_TEXT.slice(1)}`
      : DOT_TITLE[st];

export function rowHtml(pkg, i) {
  const st = computeStatus(pkg);
  return html`<tr class="row${isHidden(pkg) ? ' is-hidden' : ''}${listView.inOpenFold.has(pkg.name) ? ' fold-member' : ''}" tabindex="0" data-i="${i}">
      <td class="c-name"><div class="pkg-name"><span class="who"><span class="status-dot ${waitingForChannel(pkg) ? 'merged' : st}" role="img" aria-label="${dotTitle(pkg, st)}" title="${dotTitle(pkg, st)}"></span><a class="n pkg-link" href="${scopeHref({ pkg: pkg.name })}" tabindex="-1">${breakableName(pkg.name)} ${ageTag(pkg, st)}</a></span>${platformTags(pkg)}${foldButton(pkg)}</div></td>
      <td class="c-ver ver mono">${versionCell(pkg, st)}</td>
      <td class="c-gh${pkg.openPRs || pkg.openIssues ? '' : ' quiet'}">${githubLinks(pkg)}</td>
      <td class="c-build">${buildCell(pkg)}</td>
      <td class="c-update">${updateCell(pkg)}</td>
      <td class="c-chev"><span class="chev" aria-hidden="true">${CHEVRON}</span></td>
    </tr>`;
}

// The vulnerable badge: "insecure" when nixpkgs' mark is all there is, else
// "vulnerable", coloured by the worst severity known, who says so on hover.
function vulnBadge(pkg) {
  if (!isVulnerable(pkg)) return '';
  const saidBy = vulnSources(pkg);
  const insecureOnly = saidBy.length === 1 && pkg.markedInsecure?.length;
  const found = vulnSummary(pkg);
  const severity = found?.severity;
  const n = found?.n;
  const title = insecureOnly
    ? `nixpkgs marks it insecure: ${pkg.markedInsecure.join(' · ')}`
    : `Vulnerable, says ${saidBy.join(', ')}${n ? `: ${n} ${n === 1 ? 'CVE or advisory' : 'CVEs or advisories'}` : ''}${severity ? ` (worst: ${severity})` : ''}`;
  return html`<span class="badge vuln${severity ? ` sev-${severity}` : ''}" title="${title}">${insecureOnly ? 'insecure' : 'vulnerable'}</span>`;
}

// quiet: nothing that needs attention, so it's drawn muted, without a dot
// ("none reported" as a dash), and the phone layout leaves it out. Only
// what needs a look keeps its colour.
// mark: in place of the dot (a build's hard hat, the bot's robot), when
// given; marked: what it says that the text doesn't, for screen readers
// ("queued for an update").
function failureButton(
  kind,
  dot,
  text,
  title,
  stale = null,
  quiet = false,
  mark = null,
  marked = '',
) {
  const calm = quiet && !stale;
  const shown = calm && text === 'none reported' ? html`<span aria-hidden="true">—</span>` : text;
  return html`<button class="failure-btn${dot === 'missing' ? ' failing' : ''}${calm ? ' calm' : ''}" type="button" data-kind="${kind}"${calm ? html` data-quiet aria-label="${kind}: ${text}${marked ? `, ${marked}` : ''}"` : ''} aria-expanded="false" title="${title}">
    ${mark || html`<span class="status-dot ${dot}" aria-hidden="true"></span>`}<span class="cell-label">${kind}:</span>${shown}${marked && !calm ? html`<span class="sr-only">, ${marked}</span>` : ''}${
      stale
        ? html` <span class="stale-tag" title="${staleText(stale, 'Not refreshed')}">not refreshed</span>`
        : ''
    }</button>`;
}

export function buildCell(pkg) {
  if (!pkg.builds) return html`<span class="failure-na" title="Not in nixpkgs">—</span>`;
  const button = (dot, text, quiet = false) =>
    failureButton('build', dot, text, 'Show Hydra builds', notRefreshed(pkg, 'builds'), quiet);
  // Failing, blocked or marked broken: the hard hat in place of the dot, in
  // its colour, as the update column has the robot.
  const hat = (dot, text) =>
    failureButton(
      'build',
      dot,
      text,
      'Show Hydra builds',
      notRefreshed(pkg, 'builds'),
      false,
      html`<span class="bot-mark${dot === 'caution' ? ' queued' : ''}" aria-hidden="true">${HAT_ICON}</span>`,
    );
  // A failed build that never succeeded on Hydra: where, instead (the
  // panel lists the others).
  const never = neverWhere(pkg);
  if (never) return hat('missing', `never: ${never}`);
  if (failedBuilds(pkg).length) {
    // One reason for all of them (their logs, nixkeeper-hydra): only it, as
    // the update column says its own; the column says the rest.
    const [why, ...more] = buildFailedBecause(pkg, state.platformFilter);
    const known = !more.length && why !== 'unread' && BUILD_FAILED[why];
    return hat(
      'missing',
      html`<span class="sr-only">failed: </span>${known ? known.short : 'failure'}`,
    );
  }
  // Known failures: shown, but not counted as failed.
  // Hydra's builds say where; a broken package often has no Hydra job at
  // all, and then only meta.broken does (markedBroken).
  if (buildsWith(pkg, 'broken').length || pkg.markedBroken) return hat('caution', 'marked broken');
  // A dependency's failure stopped it: not its own, so not counted as failed.
  if (buildsWith(pkg, 'dependency').length) return hat('caution', 'blocked');
  if (!hydraBuildsIt(pkg)) return button('neutral', 'not built by Hydra', true);
  return button('ok', 'none reported', true);
}

// nixpkgs-update's latest attempt. `update` is null when the bot never tried
// and missing for packages not in nixpkgs. When the bot is set to update it
// (its queue), the robot is in front, in place of the dot: green when to
// the newest version and its last attempt didn't fail, so its PR should
// follow; amber when it will try but it's unsure (queuedState); its hover
// says which, and the update panel when. Without the queue, a failure's robot is red and "can't
// update"'s gold; the rest have no mark.
function updateCell(pkg) {
  // A set's, the bot never tried: its set's tooling updates it.
  if (pkg.set && !pkg.update)
    return queuedOrDash(pkg, `${bulkText(pkg.set)}: nixpkgs-update hasn't tried it`);
  if (pkg.update === undefined)
    return html`<span class="failure-na" title="Not in nixpkgs">—</span>`;
  if (pkg.update === null && pkg.unversioned && !pkg.unread?.includes('update'))
    return queuedOrDash(pkg, `${UNVERSIONED_TITLE}: nothing for nixpkgs-update to update`);
  const q = queuedState(pkg);
  const robot = botMark;
  const button = (dot, text, quiet = false, unqueued = null) =>
    failureButton(
      'update',
      dot,
      text,
      `Show the latest nixpkgs-update attempt${q ? `. ${q.title.replace(/\. When: the update panel$/, '')}` : ''}`,
      notRefreshed(pkg, 'update'),
      quiet,
      q ? robot(q.match ? 'match' : 'queued') : unqueued,
      q ? 'queued for an update' : '',
    );
  // Failed: only why ("patch"), the column saying the rest.
  if (pkg.updateFailure) {
    const because = FAILED_BECAUSE[pkg.update?.failedBecause];
    return button(
      'missing',
      html`<span class="sr-only">failed: </span>${because ? because.short : 'failure'}`,
      false,
      robot(''),
    );
  }
  // The bot's last attempt failed, but nixpkgs has moved on since: not a
  // failure anymore, though the next attempt may well break the same way.
  if (pkg.update?.outcome === 'superseded') return button('neutral', 'superseded', true);
  // A newer version the bot has no way to update to: not a failure, but it
  // needs a manual update (or an updateScript).
  if (pkg.update?.outcome === 'cantUpdate')
    return button('caution', "can't update", false, robot('queued'));
  // The bot passes it over on purpose (opted out, GNOME's release cycle, too
  // many rebuilds, ...): not a failure, but it won't update it either.
  if (pkg.update?.outcome === 'skipped') return button('neutral', 'skipped', true);
  // With every package, only the lists' packages' logs are read (with no
  // attempt read before).
  if (pkg.unread?.includes('update') && !pkg.update) return button('neutral', 'not read', true);
  // Nothing reported, and the bot is set to update it: when, in green.
  const due = botDueText(pkg);
  if (due)
    return failureButton(
      'update',
      'ok',
      html`<span class="bot-due">${due}</span>`,
      `${q.title.replace(/\. When: the update panel$/, '')}, expected by ${pkg.queued.by}`,
      notRefreshed(pkg, 'update'),
      false,
      robot('match'),
    );
  if (pkg.update === null) return button('neutral', 'not attempted', true);
  return button('ok', 'none reported', true);
}

// A "—" with nothing to open, saying why on hover; unless the bot is set
// to update it anyway: then the robot and "—", one button opening the
// update panel, as the other cells.
function queuedOrDash(pkg, why) {
  const q = queuedState(pkg);
  if (!q) return html`<span class="failure-na" title="${why}">—</span>`;
  return failureButton(
    'update',
    'neutral',
    'none reported',
    `${why}. ${q.title.replace(/\. When: the update panel$/, '')}`,
    notRefreshed(pkg, 'update'),
    true,
    botMark(q.match ? 'match' : 'queued'),
    'queued for an update',
  );
}

// From nixpkgs meta.platforms; null means nixpkgs doesn't restrict it.
// Linux and Darwin, and the one Linux system when it's on only one ("Linux
// x86_64": the exception named, the rule not).
function platformTags(pkg) {
  const pl = pkg.platforms;
  if (pl === undefined) return '';
  // No restriction: "any platform", unless Hydra doesn't build it
  // somewhere, which the chips then say as for a listed platform (fzssh:
  // Linux, not Darwin; 334 such on 2026-10-19).
  const any = pl === null;
  if (any && !unbuiltWhere(pkg).length)
    return html`<span class="plats"><span class="plat any" title="nixpkgs doesn't restrict its platforms">any platform</span></span>`;
  const listed = pl || { linux: true, darwin: true };
  const linux = LINUX_SYSTEMS.filter((s) => onPlatform(pkg, s));
  // Each chip: its platform, and whether Hydra builds it there
  // (unbuiltOn: listed, not built). On both Linux systems with one not
  // built, they split: "Linux x86_64 · aarch64", the latter struck.
  const chips = [];
  if (listed.linux) {
    const built = linux.filter((s) => !unbuiltOn(pkg, s));
    if (linux.length === 2 && built.length === 1) {
      const missing = linux.find((s) => s !== built[0]);
      chips.push([built[0], false], [missing, true, missing.split('-')[0]]);
    } else {
      const key = linux.length === 1 ? linux[0] : 'linux';
      chips.push([key, unbuiltOn(pkg, key)]);
    }
  }
  if (listed.darwin) chips.push(['darwin', unbuiltOn(pkg, 'darwin')]);
  const tags = chips.map(([key, unbuilt, short]) => {
    const p = PLATFORMS[key];
    const where = any
      ? "nixpkgs doesn't restrict its platforms"
      : `Listed for ${p.label} in nixpkgs`;
    const said = unbuilt
      ? `${where}, but Hydra doesn't build it on ${p.label}: no build exists there, usually because a dependency isn't available on ${p.label}`
      : any
        ? `${p.title} (nixpkgs doesn't restrict its platforms)`
        : p.title;
    return html`<button class="plat${unbuilt ? ' unbuilt' : ''}" type="button" data-platform="${key}" aria-pressed="${state.platformFilter === key}"
      title="${said}. ${state.platformFilter === key ? 'Show all platforms' : `Click to show only packages available on ${p.label}`}">${short || p.label}${unbuilt ? html`<span class="sr-only"> (not built by Hydra)</span>` : ''}</button>`;
  });
  // Together, so they wrap as one.
  return tags.length ? html`<span class="plats">${tags}</span>` : '';
}

// Open nixpkgs PRs / issues with the package's attribute name in the title:
// a link to GitHub's search for each kind that has some, with its count.
// None of either: a faint "—", as the other columns say nothing to report
// (two thirds of the attention list had "PRs 0 issues 0", two links to an
// empty search, 2026-10-23). Not counted (an instance whose sync doesn't
// ask GitHub): both, as plain links.
export function githubLinks(pkg) {
  const term = pkg.searchTerm || pkg.name;
  // Packages with none open are counted every few days, not daily
  // (nixkeeper/sources/github.py): when, if it wasn't today.
  const age = pkg.countedAt && daysText(pkg.countedAt);
  const counted = age && age !== 'today' ? ` (counted ${age} ago)` : '';
  // GitHub's icon and the count ("2 open PRs" said); without a count, the
  // word instead.
  // The count is of titles about the package (nixkeeper/sources/
  // github_bulk.py); GitHub's search, linked, matches words, and for a name
  // that's a word (pkg, linux) shows more: the hover says so.
  const link = (kind, path, label, count) => {
    if (count === 0) return '';
    const q = encodeURIComponent(`is:${kind} state:open in:title "${term}"`);
    const more = pkg.searchShowsMore?.includes(kind)
      ? `. GitHub's search shows more: titles with the word ${term} in them, not only its name`
      : '';
    return html`<a class="gh-btn" href="https://github.com/NixOS/nixpkgs/${path}?q=${q}" target="_blank" rel="noopener"
      title="Open nixpkgs ${label} naming ${term} in their title${counted}${more}"${count != null ? html` aria-label="${count} open ${label}"` : ''}>${GH_ICONS[kind]}${count != null ? html`<b>${count}</b>` : label}</a>`;
  };
  if (pkg.openPRs === 0 && pkg.openIssues === 0)
    return html`<span class="failure-na" title="No open nixpkgs PRs or issues naming ${term} in their title${counted}${pkg.searchShowsMore ? `. GitHub's search shows some with the word ${term} in them` : ''}">—</span>`;
  return html`<span class="gh-links">${link('pr', 'pulls', 'PRs', pkg.openPRs)}${link('issue', 'issues', 'issues', pkg.openIssues)}</span>`;
}

// A package's name, able to wrap after each dot (python313Packages. /
// requests) and at its hyphens, as a long one would otherwise widen the
// table past the screen for every row.
function breakableName(name) {
  return name.split('.').map((part, i) => (i ? html`.<wbr>${part}` : part));
}
