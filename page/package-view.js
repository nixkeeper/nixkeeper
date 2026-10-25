// A package's panel (its Details, Updates and Builds tabs), drawn into its
// element when it opens: the verdict, versions and where they come from,
// the update bot's attempts and queue, each platform's builds, and the
// sections from panel.js. What it needs of the page comes in `page`
// (app.js's panelPage): a package's address, and hiding it.

import {
  capitalized,
  communityCheck,
  comparedRepos,
  compareVersions,
  computeStatus,
  daysText,
  daysUntil,
  fromMaster,
  html,
  nixkeeperEntry,
  nothingCompared,
  olderVersionKept,
  onBranch,
  onHost,
  onMaster,
  raw,
  safeUrl,
  setHtml,
  shortAge,
  targetVersion,
  waitingForChannel,
  withoutLeadingJoiner,
} from './logic.js';
import {
  backportNote,
  buildLine,
  githubSection,
  groupedBuilds,
  insecureNote,
  VULNS_SHOWN,
  vulnSection,
  whoDid,
} from './panel.js';
import { writeQuery } from './search.js';
import { failedBuilds, state } from './state.js';
import { store } from './store.js';
import {
  archivedText,
  bulkText,
  FAILED_BECAUSE,
  fmt,
  hydraBuildsIt,
  hydraBuildUrl,
  icon,
  LOOKUP_FAILED,
  longDate,
  notRefreshed,
  ONLY_NIXPKGS_TEXT,
  profileOf,
  shortDay,
  stagingWait,
  staleText,
  UNSUPPORTED_TEXT,
  UNVERSIONED_TITLE,
} from './ui.js';

export const NIX_REPO = 'nix_unstable';

// What a branch updating its set before master (haskell-updates) has, in
// the panel: its version, how its build went, and what that means here.
export const BRANCH_BUILD = {
  ok: 'builds',
  failed: 'fails to build',
  dependency: "doesn't build: a dependency fails",
  unfinished: "didn't finish building",
  queued: "isn't built yet",
};

export function branchNote(pkg) {
  const b = pkg.branch;
  if (!b) return '';
  const failing = failedBuilds(pkg).length > 0;
  if (b.version === pkg.nixVersion && b.status === 'ok' && !failing) return '';
  const after = onBranch(pkg)
    ? b.status === 'ok'
      ? ': the update waits for its merge into master, about every two weeks.'
      : ', so the update may wait for a fix before the branch merges.'
    : failing && b.status === 'ok'
      ? ': fixed there, once the branch merges into master.'
      : failing
        ? ': failing there too.'
        : b.status === 'failed' || b.status === 'dependency'
          ? ': it breaks when the branch merges into master, unless fixed first.'
          : '.';
  return html`<div class="master-note"><span class="mono">${b.name}</span> has <span class="mono">${b.version}</span>, which ${BRANCH_BUILD[b.status] || b.status} there (<a class="files-link" href="${safeUrl(hydraBuildUrl(b.build))}" target="_blank" rel="noopener">build ↗</a>)${after}</div>`;
}

// How an update on staging-next builds there, from Hydra's newest
// evaluation of it (branches.apply_staging_next): built everywhere, failing
// where (each failure's build linked), not built yet, or not in that
// evaluation yet. Said with the evaluation's day: it's a day or two old.
export const STAGING_BUILD = {
  failed: 'fails to build',
  dependency: 'fails: a dependency fails',
};

export function stagingBuilds(pr) {
  if (!pr.eval) return '';
  const when = pr.eval.evaluatedAt ? ` of ${shortDay(pr.eval.evaluatedAt.slice(0, 10))}` : '';
  const evalLink = html`<a class="files-link" href="https://hydra.nixos.org/eval/${pr.eval.eval}" target="_blank" rel="noopener">Hydra's evaluation${when} ↗</a>`;
  if (!pr.inEval) return html` It isn't in ${evalLink} yet.`;
  const builds = pr.builds || [];
  // staging-next past this PR's version: what it builds is that one.
  const it = pr.evalVersion
    ? html`staging-next has a newer version, <span class="mono">${pr.evalVersion}</span>, which`
    : 'it';
  const failing = builds.filter((b) => STAGING_BUILD[b.status]);
  if (failing.length)
    return html` In ${evalLink}, ${it} ${failing.map(
      (b, i) =>
        html`${i ? (i === failing.length - 1 ? ' and ' : ', ') : ''}${STAGING_BUILD[b.status]} on ${b.system} (<a class="files-link" href="${safeUrl(hydraBuildUrl(b.build))}" target="_blank" rel="noopener">build ↗</a>)`,
    )}.`;
  const waiting = builds.filter((b) => b.status !== 'ok');
  if (waiting.length)
    return html` In ${evalLink}, ${it} isn't built yet on ${waiting.map((b) => b.system).join(', ')}.`;
  return html` In ${evalLink}, ${it} builds${builds.length > 1 ? ' on every platform' : ''}.`;
}

// What staging-next breaks: this package, building on master, fails its own
// build there (each platform's build linked), as of Hydra's newest
// evaluation of it.
export function stagingNextBreaksNote(pkg) {
  const b = pkg.stagingNextBreaks;
  if (!b) return '';
  const when = b.evaluatedAt ? ` of ${shortDay(b.evaluatedAt.slice(0, 10))}` : '';
  const evalLink = html`<a class="files-link" href="https://hydra.nixos.org/eval/${b.eval}" target="_blank" rel="noopener">Hydra's evaluation${when} ↗</a>`;
  const systems = [...new Set(b.builds.map((x) => x.system))];
  const builds = b.builds.map(
    (x, i) =>
      html`${i ? ', ' : ''}<a class="files-link" href="${safeUrl(hydraBuildUrl(x.build))}" target="_blank" rel="noopener">${b.builds.length > systems.length ? `${x.attr} on ` : ''}${x.system} ↗</a>`,
  );
  const merge = b.cycle
    ? html` (<a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${b.cycle.n}" target="_blank" rel="noopener">#${b.cycle.n} ↗</a>)`
    : '';
  return html`<div class="master-note">⚠ Breaks on <span class="mono">staging-next</span>: in ${evalLink}, it fails to build there (${builds}), at the same version master builds fine. Unless fixed, it fails on master when staging-next is merged into it${merge}; a fix may already be on staging.</div>`;
}

// On staging-next, this package stops others (a failing dependency there),
// or is stopped there by one, as of Hydra's newest evaluation of it.
export function stagingNextBlockedNote(pkg, pkgHref) {
  const notes = [];
  const evalOf = (x) =>
    html`<a class="files-link" href="https://hydra.nixos.org/eval/${x.eval}" target="_blank" rel="noopener">Hydra's evaluation${x.evaluatedAt ? ` of ${shortDay(x.evaluatedAt.slice(0, 10))}` : ''} ↗</a>`;
  const blocks = pkg.stagingNextBlocks;
  if (blocks)
    notes.push(
      html`<div class="master-note">⚠ On <span class="mono">staging-next</span>, its failure stops ${fmt(blocks.packages)} other ${blocks.packages === 1 ? "package's" : "packages'"} builds (${fmt(blocks.builds)} ${blocks.builds === 1 ? 'build' : 'builds'}, in ${evalOf(blocks)}) that build on master: fixing it there unblocks them before staging-next is merged.</div>`,
    );
  const blocked = pkg.stagingNextBlockedBy;
  if (blocked) {
    const by = [...new Map(blocked.builds.flatMap((b) => b.by).map((x) => [x.name, x])).values()];
    const blockers = by.map(
      (x, i) =>
        html`${i ? ', ' : ''}${x.row ? html`<a class="files-link mono" href="${pkgHref(x.name)}" data-scope-pkg="${x.name}">${x.name}</a>` : html`<span class="mono">${x.name}</span>`}`,
    );
    const systems = [...new Set(blocked.builds.map((b) => b.system))].join(', ');
    notes.push(
      html`<div class="master-note">On <span class="mono">staging-next</span>, its build (${systems}) is stopped by ${blockers}, failing there, in ${evalOf(blocked)}; it builds on master. Unless that's fixed, it's stopped on master too when staging-next is merged.</div>`,
    );
  }
  return notes;
}

export function stagingNote(pkg) {
  const pr = pkg.stagingPR;
  if (!pr) return '';
  return html`<div class="master-note"><span class="mono">${pr.on}</span> already has <span class="mono">${pr.to}</span> (merged in <a class="files-link" href="${safeUrl(pr.url)}" target="_blank" rel="noopener">#${pr.number} ↗</a>${pr.merged ? ` on ${longDate(pr.merged)}` : ''}): it ${stagingWait(pr)}.${stagingBuilds(pr)}</div>`;
}

// The same, as a line at the top of a panel.
export const staleNote = (info, what, after) =>
  info ? html`<div class="stale-note">⚠ ${staleText(info, what)}. ${after}</div>` : '';

// How recent a "bot" failure is worth reporting (its panel's note).
export const REPORT_DAYS = 3;

export const DAY_MS = 86400e3;

export const prLink = (n, text) =>
  html`<a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${n}" target="_blank" rel="noopener">${text}</a>`;

// Each outcome: its colour, its pill in the panel (`label`), and what it
// means (`text`).
export const UPDATE_OUTCOME = {
  failed: {
    dot: 'missing',
    label: (u) =>
      `Failed${FAILED_BECAUSE[u.failedBecause] ? `: ${FAILED_BECAUSE[u.failedBecause].short}` : ''}`,
    text: (u) => {
      const because = FAILED_BECAUSE[u.failedBecause];
      return because ? `failed: ${because.text}` : 'failed';
    },
  },
  // nixpkgs has moved on since the attempt (updated another way): in the
  // channel, or merged on master and not in the channel yet. Or a rule
  // ignores the version it tried: your own (package-lists/ignored-updates.nix)
  // or a community one (community/ignored-updates.nix).
  superseded: {
    dot: 'neutral',
    label: () => 'Superseded',
    text: (u, pkg) => {
      const what = u.supersededOutcome === 'cantUpdate' ? "couldn't update it" : 'failed';
      const version = u.to === '1' ? pkg.nixVersion : u.to;
      return u.supersededOn === 'ignored'
        ? html`failed trying <span class="mono">${version}</span>, a version ignored by ${u.community ? 'a community rule' : 'a manual rule'}: ${u.reason}`
        : u.supersededOn === 'master'
          ? html`${what}, but master already has <span class="mono">${onMaster(pkg)}</span> (merged, waiting for nixos-unstable)`
          : html`${what}, but nixpkgs has moved on to <span class="mono">${pkg.nixVersion}</span> since`;
    },
  },
  // Every way the bot has of updating a package declined (the excerpt says
  // why): the update needs doing by hand, or an updateScript.
  cantUpdate: {
    dot: 'caution',
    label: () => "Can't update",
    text: () =>
      "couldn't update it: none of the bot's ways of updating a package apply here. Update it by hand, or give the package an updateScript so the bot can next time",
  },
  prOpened: {
    dot: 'ok',
    label: () => 'PR opened',
    text: (u) => html`opened ${prLink(u.pr, `PR #${u.pr} ↗`)}`,
  },
  prExists: {
    dot: 'ok',
    label: () => 'PR open',
    text: (u) => html`a PR was already open${u.pr ? html` (${prLink(u.pr, `#${u.pr} ↗`)})` : ''}`,
  },
  // The update's already on its way: the bot pushed it to its branch, and
  // its PR is open or will be.
  branchExists: {
    dot: 'ok',
    label: () => 'On its way',
    text: () =>
      'already done: the bot pushed this update to its branch, and its PR is open or on its way',
  },
  noChange: { dot: 'ok', label: () => 'Nothing to update', text: () => 'nothing to update' },
  // Its skiplist or the package itself says not to: the excerpt says why.
  skipped: {
    dot: 'neutral',
    label: () => 'Skipped',
    text: () => 'skipped on purpose: the bot passes this package over, for the reason below',
  },
  other: {
    dot: 'neutral',
    label: () => 'Unclear',
    text: () => 'finished without a recognisable result',
  },
};

// When the bot will try the package again, from its queue (the row's
// "queued"), and what it would update it to: a version it found that
// nixpkgs doesn't have (from a GitHub release, say), which doesn't make the
// package outdated here, the bot's picking can be wrong. Not in the queue:
// it sees nothing to update to. Nothing without the queue.
export function queueHtml(pkg) {
  if (!store.sources?.queue?.used) return '';
  const q = pkg.queued;
  const queueLink = html`<a class="files-link" href="https://nixpkgs-update-logs.nixos.org/~supervisor/queue.html" target="_blank" rel="noopener">queue ↗</a>`;
  if (!q) {
    return html`<section class="pd-sec"><h4 class="other-label">Next attempt</h4><p class="pd-text">Not in nixpkgs-update's ${queueLink}: it sees nothing to update this package to right now.</p></section>`;
  }
  const days = daysUntil(q.by);
  // Each version once, with where the bot found it (GitHub's releases,
  // Repology, ...).
  const byVersion = new Map();
  for (const [to, url] of q.candidates || []) {
    byVersion.set(to, [...(byVersion.get(to) || []), url]);
  }
  const where = (url) =>
    onHost(url, 'github.com')
      ? 'GitHub release'
      : onHost(url, 'repology.org')
        ? 'Repology'
        : 'its source';
  const candidates = [...byVersion].map(
    ([to, urls], i) =>
      html`${i ? ', ' : ''}<span class="mono">${to}</span> (${urls.map(
        (url, j) =>
          html`${j ? ' · ' : ''}${url ? html`<a class="files-link" href="${safeUrl(url)}" target="_blank" rel="noopener">${where(url)} ↗</a>` : where(url)}`,
      )})`,
  );
  const facts = [
    [
      'expected',
      days < 1
        ? 'within a day'
        : html`${longDate(`${q.by}T12:00:00Z`)} <span class="pd-ago">(in ${days === 1 ? 'a day' : `${days} days`})</span>`,
    ],
    candidates.length && ['would update to', candidates],
    ['from', queueLink],
  ].filter(Boolean);
  return html`<section class="pd-sec"><h4 class="other-label">Next attempt</h4><dl class="pd-facts">${facts.map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl></section>`;
}

export function fillUpdate(pkg, el) {
  const u = pkg.update;
  const unread = pkg.unread?.includes('update')
    ? html`<div class="stale-note">Not read on the last sync: with every package, nixpkgs-update's attempts come from a digest of them, which hasn't read this package's yet.${u ? ' Showing the last attempt read.' : ''}</div>`
    : '';
  if (unread && !u) {
    setHtml(el, html`${unread}<div class="pd">${queueHtml(pkg)}</div>`);
    return;
  }
  const stale = html`${unread}${staleNote(
    notRefreshed(pkg, 'update'),
    'Not refreshed',
    'Showing the last known attempt.',
  )}`;
  if (!u) {
    setHtml(
      el,
      html`${stale}<div class="pd">
      <div class="pd-head"><span class="pd-verdict neutral">Not tried</span></div>
      <p class="pd-text">${
        pkg.set
          ? html`nixpkgs-update hasn't tried to update this package: ${bulkText(pkg.set).replace(/^K/, 'k')}.`
          : "nixpkgs-update hasn't tried to update this package (it may have no update source it understands)."
      }</p>
      ${queueHtml(pkg)}
    </div>`,
    );
    return;
  }
  const dir = u.log.slice(0, u.log.lastIndexOf('/') + 1); // every attempt's log
  // A plain day: read as midday UTC, so no time zone moves it to the day before.
  const day = `${u.date}T12:00:00Z`;
  // "0 -> 1" means the package's updateScript picks the version.
  const versions = u.from && u.to && !(u.from === '0' && u.to === '1');
  const o = UPDATE_OUTCOME[u.outcome] || UPDATE_OUTCOME.other;
  const tone = { missing: 'danger', caution: 'caution', ok: 'ok' }[o.dot] || 'neutral';
  const facts = [
    ['attempted', html`${longDate(day)} <span class="pd-ago">(${shortAge(day)} ago)</span>`],
    versions && ['tried', html`<span class="mono">${u.from} → ${u.to}</span>`],
    (pkg.attrs || []).length > 1 && ['attribute', html`<span class="mono">${u.attr}</span>`],
  ].filter(Boolean);
  // The pill says "Failed: patch"; the sentence then only why.
  const because = u.outcome === 'failed' && FAILED_BECAUSE[u.failedBecause];
  const text = because
    ? because.text
    : u.outcome === 'failed'
      ? `the log doesn't say why in a way nixkeeper recognises${u.excerpt?.length ? '; its last lines are below' : ''}`
      : o.text(u, pkg);
  setHtml(
    el,
    html`${stale}<div class="pd">
    <div class="pd-head">
      <span class="pd-verdict ${tone}">${o.label(u)}</span>
      <dl class="pd-facts">${facts.map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>
    </div>
    ${because?.restates ? '' : html`<p class="pd-text">${capitalized(text)}.</p>`}${
      because?.report
        ? Date.now() - new Date(day).getTime() <= REPORT_DAYS * DAY_MS
          ? html`<p class="pd-text">Worth telling <a class="files-link" href="https://github.com/NixOS/nixpkgs-update/issues" target="_blank" rel="noopener">nixpkgs-update's maintainers ↗</a>, if no one has yet.</p>`
          : html`<p class="pd-text">A past problem of the bot's (on ${longDate(day)}): it will try again on its next round.</p>`
        : ''
    }
    ${
      u.excerpt?.length
        ? html`<section class="pd-sec"><h4 class="other-label">From the log</h4><pre class="log-excerpt mono">${u.excerpt.join('\n')}</pre></section>`
        : ''
    }
    ${queueHtml(pkg)}
    <div class="pd-links">
      <a class="pd-link" href="${safeUrl(u.log)}" target="_blank" rel="noopener">${icon('file-text')}Log</a>
      <a class="pd-link" href="${safeUrl(dir)}" target="_blank" rel="noopener">${icon('history')}All attempts</a>
    </div>
  </div>`,
  );
}

// A blocking package's address, where the page has every package
// (panel.js's buildLine links it).
export const blockerHref = (page) => (name) => (store.community ? page.pkgHref(name) : null);

export function fillBuilds(pkg, el, page) {
  const stale = staleNote(
    notRefreshed(pkg, 'builds'),
    'Not refreshed',
    'Showing the last known results.',
  );
  // Why there's nothing to show: a verdict and a sentence, nothing more.
  const none = (label, text) =>
    html`<div class="pd"><div class="pd-head"><span class="pd-verdict neutral">${label}</span></div><p class="pd-text">${text}</p></div>`;
  if (pkg.unfree) {
    setHtml(
      el,
      html`${stale}${none('Not built', "Hydra doesn't build unfree packages, so there are no build results for this one.")}`,
    );
    return;
  }
  if (!hydraBuildsIt(pkg) && pkg.markedBroken) {
    setHtml(
      el,
      html`${stale}${none('Marked broken', html`nixpkgs marks this package broken (<span class="mono">meta.broken</span>), so Hydra doesn't build it.${safeUrl(pkg.source) ? html` <a class="files-link" href="${safeUrl(pkg.source)}" target="_blank" rel="noopener">Source ↗</a>` : ''}`)}`,
    );
    return;
  }
  if (!hydraBuildsIt(pkg)) {
    setHtml(
      el,
      html`${stale}${none('Not built', html`Hydra doesn't build this package (nixpkgs may exclude it with <span class="mono">hydraPlatforms</span>).`)}`,
    );
    return;
  }
  // Each platform's line says how it stands: no summary above them (a
  // count the lines show at a glance). Builds with nothing going on are
  // checked every few days, not daily (nixkeeper/sources/hydra.py): when
  // the oldest was, under them, if it isn't today.
  const checked = pkg.builds
    .map((b) => b.checkedAt)
    .filter(Boolean)
    .sort()[0];
  const age = checked && daysText(checked);
  setHtml(
    el,
    html`${stale}<div class="pd">
    <div class="br-list">${groupedBuilds(pkg.builds).map(([b, alike]) => buildLine(pkg, b, alike, blockerHref(page)))}</div>
    ${
      checked && age !== 'today'
        ? html`<p class="pd-foot" title="${new Date(checked).toLocaleString()}">Checked on Hydra ${age} ago.</p>`
        : ''
    }
  </div>`,
  );
}

// "…/pkgs/by-name/we/wesnoth/package.nix#L147" -> "package.nix"
export function sourceFileName(url) {
  return url.split('#')[0].split('/').pop();
}

// entries: the row's Repology entries, or null if they couldn't be loaded
// (its shard).
export function fillDetail(pkg, el, entries, page) {
  const loaded = Array.isArray(entries);

  const others = loaded ? comparedRepos(entries.filter((e) => e.repo !== NIX_REPO)) : [];
  // With every package, a row no list has keeps the newest repositories
  // only (nixkeeper/datastore.py, kept_entries): the rest are on Repology.
  const notKept =
    store.community && !pkg.lists?.length && pkg.repoCount > others.length
      ? pkg.repoCount - others.length
      : 0;
  const compared = others.length + notKept;
  // Repology is asked every few days for packages with nothing going on
  // (nixkeeper/lookup.py): how old its data is, if it isn't from today.
  const repologyDays = pkg.repologyCheckedAt && daysText(pkg.repologyCheckedAt);
  const repologyAge =
    repologyDays && repologyDays !== 'today'
      ? html` <span class="since" title="${new Date(pkg.repologyCheckedAt).toLocaleString()}">· ${repologyDays} ago</span>`
      : '';
  // Repology's page of the package, and how old its data is, in the
  // sentence: "compared with 14 other repositories (5 days ago)".
  const repologyUrl = pkg.project
    ? `https://repology.org/project/${encodeURIComponent(pkg.project)}/versions`
    : null;
  const repologyLink = (text) =>
    repologyUrl
      ? html`<a class="files-link" href="${repologyUrl}" target="_blank" rel="noopener">${text}</a>`
      : text;
  const repologyWhen =
    repologyDays && repologyDays !== 'today'
      ? html` <span title="${new Date(pkg.repologyCheckedAt).toLocaleString()}">(${repologyDays} ago)</span>`
      : '';
  // The sentence after the verdict, without "nixpkgs unstable has 1.3.5"
  // (the row says the version): what came after it, as a sentence of its own.
  const opening = (tail) => capitalized(withoutLeadingJoiner(tail));
  const homepage = safeUrl(pkg.homepage);

  const st = computeStatus(pkg);
  const up = pkg.upstream;
  // nixkeeper's update check, and whether it was worked out from nixpkgs.
  const ours = up?.inferred
    ? "nixkeeper's update check (worked out from nixpkgs' source)"
    : "nixkeeper's update check";
  // The repositories it's compared against, nixkeeper's update check first.
  const mine = nixkeeperEntry(pkg);
  const checkedDays = up?.checkedAt && daysText(up.checkedAt);
  const chips = [
    ...(mine
      ? [
          {
            ...mine,
            title: `${mine.kind}${mine.where ? `: ${mine.where}` : ''}${checkedDays && checkedDays !== 'today' ? `, checked ${checkedDays} ago` : ''}`,
          },
        ]
      : []),
    ...others.map((e) => ({
      repo: e.repo,
      version: e.version,
      // Repology's newest, when it's newer than nixpkgs' (not when one of its
      // rules makes an older one newest: google-chrome's, at times).
      ahead:
        e.status === 'newest' &&
        Boolean(pkg.nixVersion) &&
        compareVersions(e.version, pkg.nixVersion) > 0,
    })),
  ];
  // "in the wesnoth/wesnoth tags" or "on www.barebones.com".
  const upLabel = up ? up.label || (up.repo ? `${up.repo} tags` : 'its update check') : '';
  const upLink = up
    ? html`${up.repo ? 'in the' : 'on'} ${safeUrl(up.url) ? html`<a class="files-link" href="${safeUrl(up.url)}" target="_blank" rel="noopener">${upLabel} ↗</a>` : upLabel}`
    : '';
  const since = pkg.outdatedSince
    ? ` — outdated since ${longDate(pkg.outdatedSince)} (${daysText(pkg.outdatedSince)})`
    : '';
  // What Repology said, where the update check decided otherwise
  // (repologySaid, upstream.apply in nixkeeper).
  // Its update check decides too when only nixpkgs packages it: Repology
  // compared it with nothing (nothingCompared without the check).
  const said = pkg.repologySaid;
  const repologyOutdated = (said?.status ?? pkg.nixStatus) === 'outdated';
  // A branch check (unstable versions): how many commits nixpkgs is behind,
  // and what makes that count as outdated ("90 days or 50 commits").
  const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
  const behind = up?.behind ? `${plural(up.behind, 'newer commit')}` : '';
  const limits = up?.outdatedAfter
    ? [
        up.outdatedAfter.days != null && `one has waited ${plural(up.outdatedAfter.days, 'day')}`,
        up.outdatedAfter.commits != null && `there are ${up.outdatedAfter.commits}`,
      ]
        .filter(Boolean)
        .join(' or ')
    : '';
  // A package updated together with another (follows): which, and that its
  // newest version and update PRs are that package's.
  const follows = up?.follows
    ? html`updated together with <b>${up.follows}</b> (${communityCheck(pkg) ? 'a community rule' : 'your update checks'}): its newest version and update PRs count for this package too`
    : '';
  // When the update check is what makes it outdated, say where the newer
  // version came from, and how it compares with Repology.
  // Outdated by nixkeeper's update check (the head says what it found, its
  // badge links where): how Repology differs, or what it is when it follows
  // another package.
  // Only nixpkgs packages it: its update check is what decided (the source
  // badge), nothing else for it to agree with.
  const nothingElse = pkg.onlyNixpkgs && pkg.nixStatus === 'unique';
  const upstreamExtra = () =>
    follows
      ? html`It's ${follows}.`
      : pkg.refVersion && pkg.refVersion !== up.version
        ? targetVersion(pkg) && targetVersion(pkg) !== up.version
          ? html`The newest above is Repology's; ${ours} found <span class="mono">${up.version}</span>.`
          : html`Repology's newest is <span class="mono">${pkg.refVersion}</span>.`
        : repologyOutdated
          ? ''
          : up.commit
            ? `${behind ? `${behind.charAt(0).toUpperCase()}${behind.slice(1)}` : 'Newer commits'}: Repology only tracks releases, so it can't tell.`
            : "Repology doesn't count it as the newest yet.";
  // A check that can't refresh needs fixing in nixkeeper, so the details say
  // so plainly, with the last result it's still using.
  const failing = notRefreshed(pkg, 'upstream');
  const checkNote = failing
    ? html`<div class="stale-note">⚠ ${staleText(failing, "nixkeeper's update check has been failing")}.${
        up
          ? html` Still using its last result: <span class="mono">${up.version}</span>${up.checkedAt ? ` (${longDate(up.checkedAt)})` : ''}.`
          : ' It has no result yet.'
      } ${
        communityCheck(pkg)
          ? html`It's a community rule (<span class="mono">community/update-checks.nix</span> in nixkeeper): report it there, or give this package a rule of your own in your update checks.`
          : html`Fix it in <span class="mono">package-lists/update-checks.nix</span>.`
      }</div>`
    : '';
  // An up-to-date rule: Repology gets this version wrong, so it counts as
  // up to date. What Repology said, and why the rule says otherwise.
  const rule = pkg.upToDate;
  const ruleText = rule
    ? html` — up to date by ${rule.community ? 'a community rule' : 'a manual rule'}: ${rule.reason || ''} (Repology calls it <span class="mono">${rule.status || '?'}</span>${
        rule.newest
          ? html`, with <span class="mono">${rule.newest}</span> as the newest elsewhere`
          : ''
      }).`
    : '';
  // Compared with its own source instead of Repology (Typst Universe):
  // the row's "feed".
  const feed = pkg.feed;
  const feedLink = feed
    ? html`<a class="files-link" href="${safeUrl(feed.url)}" target="_blank" rel="noopener">${feed.name} ↗</a>`
    : '';
  // MELPA's versions are a build's date and time (20251005.508): said as days.
  const builtOn = (v) => {
    const d = /^(\d{4})(\d{2})(\d{2})\./.exec(v || '');
    return d ? longDate(`${d[1]}-${d[2]}-${d[3]}T12:00:00Z`) : null;
  };
  const feedDay = feed?.followed
    ? feed.followed !== feed.snapshot
      ? ` (nixpkgs follows ${feed.followed}; ${feed.snapshot} is out)`
      : ''
    : feed?.released
      ? ` (published ${longDate(`${feed.released}T12:00:00Z`)})`
      : feed?.dated && builtOn(feed.version)
        ? ` (a build from ${builtOn(feed.version)}${st === 'warn' && builtOn(pkg.nixVersion) ? `; nixpkgs' is from ${builtOn(pkg.nixVersion)}` : ''})`
        : '';
  // What the head (verdict, newest, since when, the linked source) doesn't
  // say already: how Repology differs from the check that decided, why a
  // version isn't compared, a rule's reason; nothing when the head says it
  // all (outdated by Repology: its newest and since when).
  const nixLine =
    up?.newer && !fromMaster(pkg)
      ? upstreamExtra()
      : st === 'missing'
        ? html`Not found in <span class="mono">nix_unstable</span>: nixpkgs doesn't currently package this.`
        : opening(
            html`${
              rule
                ? ruleText
                : feed && st === 'ok' && feed.heldBack
                  ? html` Hackage has <span class="mono">${feed.heldBack}</span>, which Stackage holds back until its next series.`
                  : st === 'warn'
                    ? pkg.refFromPR && !fromMaster(pkg)
                      ? ' — Repology names no newer version: the newest comes from an update PR.'
                      : pkg.keptBeside
                        ? html` — an older series nixpkgs keeps on purpose, beside <b class="mono">${pkg.keptBeside.attr}</b> <span class="mono">${pkg.keptBeside.version}</span>; behind in its own: the newest above is its series'.`
                        : ''
                    : olderVersionKept(pkg)
                      ? html` — an older version nixpkgs keeps on purpose${pkg.keptBeside ? html`, beside <b class="mono">${pkg.keptBeside.attr}</b> <span class="mono">${pkg.keptBeside.version}</span>` : ', beside a newer one'}: not outdated while nothing newer is out in its own series.`
                      : st === 'neutral'
                        ? nothingCompared(pkg)
                          ? ` — ${ONLY_NIXPKGS_TEXT}.`
                          : pkg.nixStatus === 'unsupported'
                            ? ` — ${UNSUPPORTED_TEXT}.`
                            : pkg.nixStatus === 'unlisted'
                              ? pkg.lookupFailed
                                ? ` — ${LOOKUP_FAILED}, so there's nothing to compare it with yet.`
                                : " — Repology doesn't list this package, so there's nothing to compare it with."
                              : html` — Repology classifies this version as <span class="mono">${pkg.nixStatus}</span>.`
                        : feed || (said && up && !failing)
                          ? ''
                          : loaded && compared
                            ? html` — compared with ${repologyLink(`${compared} other ${compared === 1 ? 'repository' : 'repositories'}`)}${repologyWhen}.`
                            : ''
            }${
              up && !up.newer && !failing
                ? follows
                  ? html` It's ${follows}.`
                  : up.behind
                    ? html` ${ours}: ${behind} ${upLink} (up to <span class="mono">${up.version}</span>), not counted as outdated until ${limits}.`
                    : said
                      ? html` Repology counts it <span class="mono">${said.status}</span>${said.newest ? html`, with <span class="mono">${said.newest}</span> as the newest elsewhere` : ''}: the update check decides, being this package's own source.`
                      : !feed && !rule && !fromMaster(pkg) && !nothingElse
                        ? html` ${ours} ${st === 'warn' ? 'found nothing newer' : 'agrees'}: the latest version ${upLink} is <span class="mono">${up.version}</span>.`
                        : ''
                : ''
            }`,
          );
  // Where master is: the PR that brought it, and whether Hydra built it:
  // master is Hydra's latest build's version, which can be a failure (tgrep
  // 1.2.4, failing on x86_64-linux).
  const masterBuilt = (p) => {
    if (!p.master) return 'not built by Hydra yet';
    const at = (p.builds || []).filter((b) => b.version === p.master);
    const failing = [...new Set(at.filter((b) => b.status === 'failed').map((b) => b.system))];
    if (!failing.length) return 'built by Hydra';
    return at.some((b) => b.status === 'ok')
      ? `built by Hydra, but failing on ${failing.join(', ')}`
      : `failing to build on Hydra on ${failing.join(', ')}`;
  };
  const masterSaid = [
    pkg.masterPR &&
      html`merged in <a class="files-link" href="${safeUrl(pkg.masterPR.url)}" target="_blank" rel="noopener">#${pkg.masterPR.number} ↗</a>${whoDid(pkg.masterPR.author, pkg.masterPR.mergedBy)}`,
    masterBuilt(pkg),
  ]
    .filter(Boolean)
    .flatMap((part, i) => (i ? [', ', part] : [part]));

  const unloaded = loaded
    ? ''
    : html`<div class="stale-note">⚠ Couldn't load Repology's details for this package, so the repositories it's compared with aren't shown. Close and reopen it to try again.</div>`;
  const profile = profileOf(pkg.set);
  const inBulk = pkg.set
    ? html`<div class="nix-line">In ${profile ? `the ${profile.name} set` : 'a set'} (<span class="mono">${pkg.set}</span>): ${bulkText(pkg.set).replace(/^K/, 'k')}${profile ? html` (<a class="files-link" href="${safeUrl(profile.link)}" target="_blank" rel="noopener">in nixpkgs ↗</a>)` : ''}. It counts on its set's line on the overview, not in the cards; GitHub's PR counts and nixkeeper's update checks aren't collected for it.</div>`
    : pkg.unversioned
      ? html`<div class="nix-line">${UNVERSIONED_TITLE}.</div>`
      : '';
  const archived = pkg.archived ? html`<div class="stale-note">${archivedText(pkg)}</div>` : '';
  // The verdict at a glance: what it is, the versions, since when, and
  // which source decided (the chain: a check, a version
  // source, an up-to-date rule, master, or Repology), as a badge: ours in
  // the accent's tint, Repology grey, so it shows when Repology isn't the
  // judge.
  const target = targetVersion(pkg);
  const verdict =
    st === 'missing'
      ? ['danger', 'Not in nixpkgs']
      : st === 'warn'
        ? waitingForChannel(pkg)
          ? ['merged', 'Waiting for the channel']
          : ['warn', 'Outdated']
        : st === 'ok'
          ? ['ok', 'Up to date']
          : olderVersionKept(pkg)
            ? ['neutral', 'Older version kept']
            : ['neutral', 'Not compared'];
  const checkKind = communityCheck(pkg)
    ? 'a community update check'
    : up?.inferred
      ? "nixkeeper's update check, worked out from nixpkgs' source"
      : 'your update check';
  const source =
    st === 'missing' || verdict[1] === 'Not compared'
      ? null
      : fromMaster(pkg)
        ? [
            'merged',
            'git-merge',
            'master',
            "master's version, built by Hydra or merged",
            safeUrl(pkg.masterPR?.url),
          ]
        : rule
          ? [
              'ours',
              'list-check',
              'up-to-date rule',
              `${rule.community ? 'A community' : 'Your'} up-to-date rule: ${rule.reason || ''}`,
              rule.community
                ? 'https://github.com/nixkeeper/nixkeeper/blob/main/community/up-to-date.nix'
                : null,
            ]
          : feed
            ? [
                'ours',
                'package',
                feed.name,
                `Compared with ${feed.name}, this package's own source`,
                safeUrl(feed.url),
              ]
            : (said || up?.newer) && up.follows
              ? [
                  'ours',
                  'git-merge',
                  `with ${up.follows}`,
                  `Updated together with ${up.follows} (${communityCheck(pkg) ? 'a community rule' : 'your update checks'}): its newest version counts for this package too`,
                ]
              : said || up?.newer || (up && pkg.onlyNixpkgs && pkg.nixStatus === 'unique')
                ? [
                    'ours',
                    up.commit ? 'git-branch' : up.repo ? 'tag' : 'world',
                    upLabel,
                    `${checkKind.replace(/^[ay]/, (c) => c.toUpperCase())}: ${upLabel}`,
                    safeUrl(up.url),
                  ]
                : [
                    'repology',
                    'chart-dots-3',
                    'Repology',
                    'Repology: the repositories it compares',
                    repologyUrl,
                  ];
  const facts = [
    st === 'warn' && target && ['newest', html`<span class="mono pd-newer">${target}</span>`],
    st === 'warn' &&
      pkg.outdatedSince && [
        'outdated since',
        html`${longDate(pkg.outdatedSince)} <span class="pd-ago">(${daysText(pkg.outdatedSince)})</span>`,
      ],
  ].filter(Boolean);
  // Notes that call for something first; then the rest, the context.
  const urgent = html`${unloaded}${archived}${checkNote}${insecureNote(pkg)}${backportNote(pkg)}${
    pkg.nixVulnerable
      ? html`<div class="vuln-note">⚠ Repology flags nixpkgs' version <span class="mono">${pkg.nixVersion}</span> as vulnerable.${
          pkg.project
            ? html` <a class="files-link" href="https://repology.org/project/${encodeURIComponent(pkg.project)}/cves" target="_blank" rel="noopener">Known CVEs ↗</a>`
            : ''
        }</div>`
      : ''
  }`;
  // Its fixes of the last month (history.add_recent_fixes in nixkeeper),
  // with who, when a PR is known.
  const fixesSaid = (pkg.recentFixes || []).map((f) => {
    const what =
      f.kind === 'update'
        ? html`Updated <span class="mono">${f.from || '?'}</span> → <span class="mono">${f.to || '?'}</span>`
        : f.kind === 'build'
          ? 'Build fixed'
          : "The update bot's failures cleared";
    const pr = f.pr
      ? html`, ${f.likely ? 'likely by' : 'in'} <a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${f.pr}" target="_blank" rel="noopener">#${f.pr} ↗</a>${whoDid(f.author, f.mergedBy)}`
      : '';
    const after = f.since ? ` (after ${shortAge(f.since, new Date(f.at).getTime())})` : '';
    return html`<div class="master-note">✓ ${what} on ${longDate(f.at)}${after}${pr}.</div>`;
  });
  const context = html`${fixesSaid}${inBulk}${
    onMaster(pkg)
      ? html`<div class="master-note">master already has <span class="mono">${onMaster(pkg)}</span> (${masterSaid})${
          waitingForChannel(pkg)
            ? ': the update is merged, and reaches nixos-unstable when the channel next advances, usually within a few days.'
            : ', not in nixos-unstable yet.'
        }</div>`
      : ''
  }${waitingForChannel(pkg) ? '' : stagingNote(pkg)}${stagingNextBreaksNote(pkg)}${stagingNextBlockedNote(pkg, page.pkgHref)}${branchNote(pkg)}`;
  const people = [
    Array.isArray(pkg.maintainers) &&
      html`<section class="pd-sec"><h4 class="other-label">Maintainers</h4><div class="pd-pills">${
        pkg.maintainers.length
          ? pkg.maintainers.map(
              (m) =>
                html`<span class="pd-pill maintainer"><button type="button" class="maint-btn" data-handle="${m}" title="Their packages here"><img class="avatar" src="https://github.com/${encodeURIComponent(m)}.png?size=40" alt="" width="18" height="18" loading="lazy" referrerpolicy="no-referrer">${m}</button><a class="pd-pill-go" href="https://github.com/${encodeURIComponent(m)}" target="_blank" rel="noopener" aria-label="${m} on GitHub" title="${m} on GitHub">↗</a></span>`,
            )
          : html`<span class="none-note">none in nixpkgs · <button type="button" class="maint-btn" data-handle="none" title="Every package with no maintainer">see all packages without one</button></span>`
      }</div></section>`,
    pkg.teams?.length &&
      html`<section class="pd-sec"><h4 class="other-label">Teams</h4><div class="pd-pills">${pkg.teams.map(
        (t) =>
          html`<button type="button" class="pd-pill maint-btn team-btn" data-team="${t}" title="${
            pkg.teamsByList?.includes(t)
              ? `On the list named after the team (package-lists), not under it in nixpkgs (meta.teams). The team's packages here`
              : "The team's packages here"
          }">${t}${pkg.teamsByList?.includes(t) ? html`<span class="pd-pill-note">list</span>` : ''}</button>`,
      )}</div></section>`,
  ].filter(Boolean);
  const links = [
    homepage &&
      html`<a class="pd-link" href="${homepage}" target="_blank" rel="noopener">${icon('home')}Homepage</a>`,
    safeUrl(pkg.source) &&
      html`<a class="pd-link" href="${safeUrl(pkg.source)}" target="_blank" rel="noopener" title="Where nixpkgs defines this package">${icon('file-code')}${sourceFileName(pkg.source)}</a>`,
  ].filter(Boolean);
  setHtml(
    el,
    html`<div class="pd">
    <div class="pd-head">
      <span class="pd-verdict ${verdict[0]}">${verdict[1]}</span>
      <dl class="pd-facts">${facts.map(([k, v]) => html`<div><dt>${k}</dt><dd>${v}</dd></div>`)}</dl>
      ${
        source
          ? source[4]
            ? html`<a class="pd-source ${source[0]}" href="${source[4]}" target="_blank" rel="noopener" title="${source[3]}">${icon(source[1])}<span class="pd-source-text">${source[2]}</span> <span aria-hidden="true">↗</span></a>`
            : html`<span class="pd-source ${source[0]}" title="${source[3]}">${icon(source[1])}<span class="pd-source-text">${source[2]}</span></span>`
          : ''
      }
    </div>
    ${String(urgent).trim() ? html`<div class="pd-notes">${urgent}</div>` : ''}
    ${vulnSection(pkg)}
    <div class="pd-why-body">
      ${String(nixLine).trim() ? html`<p class="pd-text">${nixLine}</p>` : ''}${
        up?.tagged
          ? html`<p class="pd-text" title="nixkeeper prefers a release, when the project makes them: a tag alone may not be published yet">Tagged <span class="mono">${up.tagged}</span> on GitHub, not released yet.</p>`
          : ''
      }
      ${String(context).trim() ? html`<div class="pd-notes">${context}</div>` : ''}
    </div>
    ${
      // Up to date, they'd all say the same version: the sentence's link
      // has them. Outdated or not compared, they show who has what. Not for
      // an older version kept on purpose, behind in its own series or not:
      // they're the newer series' (and its betas: firefox 159.0b5 beside
      // firefox-esr 153.5.1; glibmm 2.90.0 beside glibmm_2_4, outdated
      // against its 2.66.10).
      chips.length && st !== 'ok' && !olderVersionKept(pkg) && !pkg.keptBeside
        ? html`<section class="pd-sec"><h4 class="other-label">Compared against${repologyAge}</h4><div class="repo-chips">
      ${chips.map((e, i) => html`<span class="repo-chip ${e.ahead ? 'ahead' : ''}"${e.title ? html` title="${e.title}"` : ''}${i >= COMPARED_SHOWN ? raw(' hidden') : ''}>${e.repo} <span class="v mono">${e.version || '?'}</span></span>`)}${
        chips.length > COMPARED_SHOWN
          ? html`<button type="button" class="more-btn" aria-expanded="false">Show all ${chips.length}</button>`
          : ''
      }
    </div></section>`
        : ''
    }
    ${githubSection(pkg)}
    ${people.length ? html`<div class="pd-people">${people}</div>` : ''}
    <div class="pd-links">${links}<span class="pd-links-end">${hideButton(page.isHidden(pkg), page.needsAttention(pkg))}</span></div>
  </div>`,
  );
  el.querySelector('.pd-hide')?.addEventListener('click', () =>
    page.setHidden(pkg, !page.isHidden(pkg)),
  );
  // A maintainer's packages: searches for them (the search box, so the
  // address can be shared).
  // A team's packages: the team filter (?team=, shareable too).
  for (const btn of el.querySelectorAll('.team-btn')) {
    btn.addEventListener('click', () => {
      state.teamFilter = btn.dataset.team;
      page.update();
      document.getElementById('stats').scrollIntoView({ block: 'nearest' });
    });
  }
  for (const btn of el.querySelectorAll('.maint-btn:not(.team-btn)')) {
    btn.addEventListener('click', () => {
      const search = document.getElementById('search');
      search.value = writeQuery(state, `@${btn.dataset.handle}`);
      search.dispatchEvent(new Event('input'));
      search.scrollIntoView({ block: 'nearest' });
    });
  }
  // Vulnerabilities: the worst VULNS_SHOWN, or all of them.
  el.querySelector('.vl-more')?.addEventListener('click', (e) => {
    const btn = e.currentTarget;
    const open = btn.getAttribute('aria-expanded') !== 'true';
    const sec = btn.closest('.vl-sec');
    sec.querySelectorAll('.vl-group > .vl-list > .vl').forEach((li, i) => {
      li.hidden = !open && i >= VULNS_SHOWN;
    });
    sec.querySelectorAll('.vl-group').forEach((g) => {
      g.hidden = !g.querySelector('.vl:not([hidden])');
    });
    btn.setAttribute('aria-expanded', open);
    btn.textContent = open ? 'Show fewer' : `Show all ${btn.dataset.all}`;
  });
  el.querySelector('.more-btn:not(.vl-more)')?.addEventListener('click', (e) => {
    const btn = e.currentTarget;
    const open = btn.getAttribute('aria-expanded') !== 'true';
    el.querySelectorAll('.repo-chip').forEach((chip, i) => {
      chip.hidden = !open && i >= COMPARED_SHOWN;
    });
    btn.setAttribute('aria-expanded', open);
    btn.textContent = open ? 'Show fewer' : `Show all ${chips.length}`;
  });
}

// The panel's "Hide until it changes" (or "Show it again" while hidden):
// for something that needs attention, kept in this browser.
// hidden: whether it's hidden now; needs: whether there's something to
// hide (what the list's tiles count as needing attention).
export function hideButton(hidden, needs) {
  if (!hidden && !needs) return '';
  return html`<button type="button" class="pd-hide" title="${
    hidden
      ? 'Shown again in your lists'
      : 'Leave it out of your lists, in this browser only, until what it needs attention for changes (a newer version, another failing build, a new CVE). Wrong for everyone? Report it, or add a community rule'
  }">${hidden ? 'Show it again' : 'Hide until it changes'}</button>`;
}

// How many repositories a panel shows before "Show all".
export const COMPARED_SHOWN = 8;
