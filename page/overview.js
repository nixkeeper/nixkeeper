// The overview (the page with every package, before a view is picked): the
// counts' cards and their trends, the newest and longest-standing of each
// kind, what blocks the most, why things fail, the sets updated in bulk,
// what was fixed, nixpkgs in numbers. HTML from the store and the state;
// app.js draws it (renderScope) and handles its buttons.

import { readJson } from './data.js';
import { dayPosition, NAME_DOTS, shortAge, trendChange } from './logic.js';
import { html, raw } from './markup.js';
import { scopeHref } from './state.js';
import { store } from './store.js';
import {
  ARCHIVED_TITLE,
  bulkShort,
  bulkText,
  FAILED_BECAUSE,
  fmt,
  longDate,
  profileOf,
  shortDay,
  teamPicker,
} from './ui.js';

// The overview's build failures by where they fail (the manifest's
// buildFailuresOn): Linux and Darwin, each Hydra system on hover. Not with
// data from before.
export function platformSplit(on) {
  if (!on || on.linux == null) return '';
  const systems = Object.entries(on)
    .filter(([k]) => k.includes('-'))
    .map(([k, n]) => `${k} ${fmt(n)}`)
    .join(', ');
  return html`<span class="card-sub" title="Packages whose own build fails there: ${systems}. A package failing on both Linux systems counts once for Linux; on Linux and Darwin (macOS), once for each. Narrow the list by platform under its tiles.">Linux ${fmt(on.linux)} · Darwin ${fmt(on.darwin || 0)}</span>`;
}

// The overview's cards: the manifest's count, which list they open
// (?view=, ?filter=), and history.json's key.
export const CARDS = [
  { key: 'outdated', label: 'Outdated', view: 'attention', filter: 'warn', color: 'var(--warn)' },
  {
    key: 'buildFailures',
    label: 'Build failures',
    view: 'attention',
    filter: 'builds',
    color: 'var(--danger)',
  },
  {
    key: 'updateFailures',
    label: 'Update failures',
    view: 'attention',
    filter: 'updates',
    color: 'var(--caution)',
  },
  {
    key: 'vulnerable',
    label: 'Vulnerable',
    view: 'attention',
    filter: 'vuln',
    color: 'var(--danger)',
  },
  { key: 'broken', label: 'Marked broken', view: 'broken', filter: null, color: 'var(--caution)' },
];

// A package that moves with others (one package file, one version: the
// sync's family, datastore.grouped) is one line in the overview's lists:
// what they're called together and how many (huaweicloudsdk* ·187),
// opening a search for them; without a shared start, its name and +N,
// opening it.
export const familyName = (name, family) =>
  family
    ? html`<span class="hl-name mono" title="${fmt(family.more + 1)} packages, one update: ${family.label || name} and the like">${family.label || name}</span><span class="hl-family">${family.label ? fmt(family.more + 1) : `+${fmt(family.more)}`}</span>`
    : html`<span class="hl-name mono">${name}</span>`;

export const familyLink = (name, family) =>
  family?.label
    ? html`href="?q=${encodeURIComponent(family.label.replace(/\*$/, ''))}"`
    : html`href="${scopeHref({ pkg: name })}" data-scope-pkg="${name}"`;

// The overview's lists of the newest and longest-standing (the manifest's
// highlights), and which of the two each shows.
export const HIGHLIGHTS = [
  { key: 'failing', label: 'Build failures', filter: 'builds', color: 'var(--danger)' },
  { key: 'outdated', label: 'Outdated', filter: 'warn', color: 'var(--warn)' },
  { key: 'updateFailing', label: 'Update failures', filter: 'updates', color: 'var(--caution)' },
];

export const highlightShown = {
  failing: 'newest',
  outdated: 'newest',
  updateFailing: 'newest',
  blockers: 'master',
};

export function highlightsHtml() {
  const found = store.manifest.highlights;
  if (!found) return '';
  const columns = HIGHLIGHTS.map(({ key, label, filter, color }) => {
    const h = found[key] || { count: 0, newest: [], oldest: [] };
    const mode = highlightShown[key];
    const items = h[mode] || [];
    const toggle = (m, text) =>
      html`<button type="button" class="hl-mode" data-hl="${key}" data-mode="${m}" aria-pressed="${mode === m}">${text}</button>`;
    return html`<section class="hl-card" style="--hl:${color}" aria-label="${label}">
      <div class="hl-head">
        <h3 class="hl-title"><span class="hl-label">${label}</span><span class="hl-n">${fmt(h.count)}</span></h3>
        <div class="hl-modes" role="group" aria-label="${label}: show">${toggle('newest', 'Newest')}${toggle('oldest', 'Oldest')}</div>
      </div>
      ${
        items.length
          ? html`<ol class="hl-list">${items.map(
              ([name, since, letter, family]) =>
                html`<li><a class="hl-row" ${familyLink(name, family)}><span class="status-dot ${NAME_DOTS[letter[0]] || 'neutral'}" aria-hidden="true"></span>${familyName(name, family)}<span class="hl-age" title="Since ${longDate(since)}">${shortAge(since)}</span></a></li>`,
            )}</ol>`
          : html`<p class="hl-none">None right now.</p>`
      }
      ${h.count ? html`<a class="hl-all" href="${scopeHref({ view: 'attention', filter })}" data-card-view="attention" data-card-filter="${filter}">Show all ${fmt(h.count)} <span aria-hidden="true">→</span></a>` : ''}
    </section>`;
  });
  return html`<h2 class="scope-label">Newest and longest-standing · fully checked</h2>
    <div class="hl-cols">${columns}${blockersHtml()}</div>`;
}

// Why things fail, across packages (the manifest's causes, nixkeeper's
// causes.py): failed builds grouped by the same error (a friendly title
// where the pattern is known, else the error line), each opening its
// packages; and the update bot's failures by cause, each opening the list
// of them (?updateFailed=). Not with data from before.
// The update bot's own problems, not the package's (FAILED_BECAUSE: bot,
// request), with how the card says them; and how many of the package's
// causes it shows as bars.
export const BOT_OWN = new Map([
  ['bot', "the bot's own outage"],
  ['request', 'its request failed'],
]);

export const BOT_SHOWN = 8;

export const botCause = (key) =>
  key === 'noLog' ? 'build, no log' : FAILED_BECAUSE[key]?.short || key;

export function causesHtml() {
  const c = store.manifest.causes;
  if (!c?.builds?.length && !Object.keys(c?.bot || {}).length) return '';
  const groups = c.builds.length
    ? html`<section class="hl-card" style="--hl:var(--danger)" aria-label="Same error, many packages">
    <div class="hl-head">
      <h3 class="hl-title" title="Failed builds grouped by the line of their log that says why (paths, numbers and names left out): one cause, one fix pattern"><span class="hl-label">Same error, many packages</span><span class="hl-n">${fmt(c.packages)}</span></h3>
      <span class="hl-unit">in ${fmt(c.groups)} groups</span>
    </div>
    <ol class="hl-list">${(store.allCauses || c.builds).map(
      (g) =>
        html`<li><a class="hl-row" href="${scopeHref({ cause: g.key })}" data-scope-cause="${g.key}" title="${g.line}"><span class="status-dot missing" aria-hidden="true"></span><span class="hl-name${g.title ? '' : ' mono'}">${g.title || g.signature}</span>${g.about ? html`<span class="fixed-by">${g.about}</span>` : ''}<span class="hl-age">${fmt(g.count)}</span></a></li>`,
    )}</ol>
    ${
      c.groups > c.builds.length
        ? html`<button type="button" class="hl-all cause-more" aria-expanded="${!!store.allCauses}">${store.allCauses ? 'Show the biggest only' : html`Show all ${fmt(c.groups)} groups`} <span aria-hidden="true">${store.allCauses ? '↑' : '↓'}</span></button>`
        : ''
    }
  </section>`
    : '';
  // The commonest first (the data's keys are written sorted by name).
  const all = Object.entries(c.bot || {}).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const total = all.reduce((n, [, v]) => n + v, 0);
  // The bot's own problems (its outage, its request failing): not the
  // package's, said apart however few; the package's causes as bars.
  const own = all.filter(([key]) => BOT_OWN.has(key));
  const bot = all.filter(([key]) => !BOT_OWN.has(key));
  const most = Math.max(1, ...bot.map(([, v]) => v));
  const failedHref = (key) =>
    `${scopeHref({ view: 'attention', filter: 'updates' })}&updateFailed=${encodeURIComponent(key)}`;
  const more = bot.slice(BOT_SHOWN);
  const reasons = bot.length
    ? html`<section class="hl-card" style="--hl:var(--warn-dot)" aria-label="Why the update bot fails">
    <div class="hl-head">
      <h3 class="hl-title" title="nixpkgs-update's last attempt at each package, by why it failed (its log)"><span class="hl-label">Why the update bot fails</span><span class="hl-n">${fmt(total)}</span></h3>
      <span class="hl-unit">packages, by cause</span>
    </div>
    <ol class="hl-list cause-bars">${bot
      .slice(0, BOT_SHOWN)
      .map(
        ([key, n]) =>
          html`<li><a class="hl-row" href="${failedHref(key)}"><span class="hl-name">${botCause(key)}</span><span class="cause-bar" aria-hidden="true"><span style="width:${Math.round((100 * n) / most)}%"></span></span><span class="hl-age">${fmt(n)}</span></a></li>`,
      )}</ol>
    ${
      own.length
        ? html`<p class="cause-own" title="Failures that aren't the package's: the update bot's own outage, or its request to the builders failing">Not the package's: ${own.map(([key, n], i) => html`${i ? ' · ' : ''}<a class="files-link" href="${failedHref(key)}">${BOT_OWN.get(key)} ${fmt(n)}</a>`)}</p>`
        : ''
    }
    ${more.length ? html`<a class="hl-all" href="${scopeHref({ view: 'attention', filter: 'updates' })}">and ${more.length} more ${more.length === 1 ? 'cause' : 'causes'} (${more.map(([key]) => botCause(key)).join(', ')}) <span aria-hidden="true">→</span></a>` : ''}
  </section>`
    : '';
  return html`<h2 class="scope-label">Why things fail · fully checked</h2>
    <div class="hl-cols">${groups}${reasons}</div>`;
}

// "Blocking the most": the failing dependencies stopping the most packages'
// builds (nixkeeper-hydra's blockedBy: fix one, and they all build again;
// of all of nixpkgs, as zh.fail counts them; not with data from before, or
// before the digest has read any), on master (the manifest's blockers) or,
// while Hydra has evaluated
// the current cycle, on staging-next before its merge (blockers.stagingNext,
// branches.apply_staging_next_blocked), switched in its header as the other
// lists switch newest and oldest: one list, one height, the cards aligned.
export function blockersHtml() {
  const b = store.manifest.blockers;
  const sn = b?.stagingNext?.top?.length ? b.stagingNext : null;
  if (!b?.count && !sn) return '';
  const onNext = sn && highlightShown.blockers === 'stagingNext';
  const shown = onNext ? sn : b;
  const toggle = (m, text, title) =>
    html`<button type="button" class="hl-mode" data-hl="blockers" data-mode="${m}" aria-pressed="${(onNext ? 'stagingNext' : 'master') === m}" title="${title}">${text}</button>`;
  const when = sn?.evaluatedAt
    ? ` (Hydra's evaluation of ${shortDay(sn.evaluatedAt.slice(0, 10))})`
    : '';
  const title = onNext
    ? `On staging-next${when}, ${fmt(sn.count)} failing dependencies stop ${fmt(sn.packages)} packages that build on master: unless fixed there, they're stopped on master too when staging-next is merged`
    : `${fmt(b.count)} failing dependencies stop ${fmt(b.packages)} packages' builds, in all of nixpkgs`;
  return html`<section class="hl-card" style="--hl:var(--danger)" aria-label="Blocking the most">
    <div class="hl-head">
      <h3 class="hl-title" title="${title}"><span class="hl-label">Blocking the most</span><span class="hl-n">${fmt(shown.packages)}</span></h3>
      ${
        sn
          ? html`<div class="hl-modes" role="group" aria-label="Blocking the most: on">${toggle('master', 'Master', 'On master, now')}${toggle('stagingNext', 'Next', 'On staging-next, before its merge into master')}</div>`
          : html`<span class="hl-unit">packages stopped</span>`
      }
    </div>
    <ol class="hl-list">${shown.top.map(
      ([name, isRow, stopped, builds]) =>
        html`<li>${
          isRow
            ? html`<a class="hl-row" href="${scopeHref({ pkg: name })}" data-scope-pkg="${name}">`
            : raw('<span class="hl-row">')
        }<span class="status-dot missing" aria-hidden="true"></span><span class="hl-name mono">${name}</span><span class="hl-age" title="Stops ${fmt(stopped)} ${stopped === 1 ? 'package' : 'packages'} (${fmt(builds)} ${builds === 1 ? 'build' : 'builds'})${onNext ? ' on staging-next' : ''}">stops ${fmt(stopped)}</span>${raw(isRow ? '</a>' : '</span>')}</li>`,
    )}</ol>
    ${
      onNext
        ? html`<p class="hl-all hl-when" title="${title}">On staging-next${sn.evaluatedAt ? `, evaluated ${shortDay(sn.evaluatedAt.slice(0, 10))}` : ''}</p>`
        : html`<a class="hl-all" href="${scopeHref({ view: 'blocked' })}" data-card-view="blocked">Show all ${fmt(b.packages)} <span aria-hidden="true">→</span></a>`
    }
  </section>`;
}

// Days of history the cards draw, and how many points before they do.
export const TREND_DAYS = 30;

// How many days the trends shown span, the first and the last included (9
// while there are 9 days of history, then TREND_DAYS).
export const trendSpan = (points) =>
  Math.round((Date.parse(points.at(-1).day) - Date.parse(points[0].day)) / 864e5) + 1;

export const TREND_MIN_POINTS = 2;

// A card's trend: its count at each point, placed by date (dayPosition),
// with a thin mark on each day something explains a jump (TREND_EVENTS).
export function sparkline(points, key, color) {
  const values = points.map((p) => p[key] ?? 0);
  const lo = Math.min(...values);
  const span = Math.max(...values) - lo || 1;
  const xy = points.map(
    (p, i) =>
      `${dayPosition(points, p.day).toFixed(1)},${(20 - (18 * (values[i] - lo)) / span).toFixed(1)}`,
  );
  const marks = shownEvents(points)
    .filter((e) => MARKED.has(e.kind))
    .map(
      (e) =>
        `<line class="spark-mark ${e.kind}" x1="${e.x.toFixed(1)}" x2="${e.x.toFixed(1)}" y1="0" y2="22" vector-effect="non-scaling-stroke"/>`,
    )
    .join('');
  return raw(
    `<svg class="spark" viewBox="0 0 100 22" preserveAspectRatio="none" aria-hidden="true">${marks}<polyline points="${xy.join(' ')}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"/></svg>`,
  );
}

// Under the cards: what the marks on the trends are, one short entry per
// kind with its days ("counting changed Oct 6, Oct 7"), each day saying in
// full what happened when hovered (a staging-next one links its PR).
// nixkeeper's own releases aren't marked nor listed: the footer says the
// version, and a release that changes counting has its own mark.
export const MARK_LABELS = { counting: 'counting changed', 'staging-next': 'staging-next merged' };

export function marksHtml(points) {
  const marked = shownEvents(points).filter((e) => MARKED.has(e.kind));
  if (!marked.length) return '';
  const kinds = [...new Set(marked.map((e) => e.kind))];
  return html`<p class="spark-legend">${kinds.map((kind, i) => {
    // One date per day: two changes the same day share it, both said.
    const days = new Map();
    for (const e of marked.filter((m) => m.kind === kind))
      days.set(e.day, [...(days.get(e.day) || []), e]);
    const dates = [...days].map(([day, es]) => {
      const said = es.map((e) => TREND_EVENTS[kind](e)).join('; ');
      return kind === 'staging-next'
        ? html`<a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${es[0].pr}" target="_blank" rel="noopener" title="${said}">${shortDay(day)}</a>`
        : html`<span class="spark-day" title="${said}">${shortDay(day)}</span>`;
    });
    return html`${i ? ' · ' : ''}<span class="spark-key ${kind}" aria-hidden="true"></span>${MARK_LABELS[kind]} ${dates.flatMap((d, j) => (j ? [', ', d] : [d]))}`;
  })}</p>`;
}

// While nixkeeper-updates' digest is still reading the bot's past attempts
// (more than this many to go: a backfill, not a day's new ones), update
// failures keep turning up that were there all along: the Failing card
// says so, as its rise isn't packages breaking.
export const BACKFILL_PENDING = 1000;

// Under Vulnerable: the CVEs fixed on unstable (a new version, or a patch
// named after the CVE) that the newest release is still affected by (their
// tile in Vulnerable's list: Fixes to backport). Not part of Vulnerable's
// count: unstable has the fix. Not on data from before nixkeeper-vulnerabilities
// (no count).
export function backportCardNote() {
  const n = store.manifest.counts?.backport;
  if (n == null) return '';
  const release = store.manifest.sources?.tracker?.release;
  const to = release ? `to ${release}` : 'to the newest release';
  return html`<span class="card-sub" title="Fixed on nixpkgs unstable (a new version, or a patch named after the CVE), while the newest release is still affected: fixes to backport there, a tile in this card's list. Not counted above: unstable has the fix.">${n ? `${fmt(n)} fixed, to backport ${to}` : `none to backport ${to}`}</span>`;
}

export function backfillNote() {
  const updates = store.manifest.sources?.updates;
  if (!updates?.used || !(updates.pending > BACKFILL_PENDING)) return '';
  return html`<span class="card-sub card-note" title="nixkeeper-updates is still reading nixpkgs-update's past attempts: update failures that were there all along keep turning up, so this count rises until it's done">update failures still being read: ${fmt(updates.pending)} attempts to go</span>`;
}

// What marks the trends, in words: a staging-next merge (mass rebuilds:
// failing builds jump for days after), a change in how nixkeeper counts
// (it can step a count overnight), or nixkeeper updated (said under the
// cards, not marked: a release that changes counting has its own mark).
export const TREND_EVENTS = {
  'staging-next': (e) => `staging-next merged (#${e.pr})`,
  nixkeeper: (e) => `nixkeeper ${e.version}`,
  counting: (e) => e.text,
};

// The kinds drawn on the trends: grey for staging-next, amber for a counting
// change (style.css).
export const MARKED = new Set(['staging-next', 'counting']);

// The events on the days the trends show, with where they fall.
export function shownEvents(points) {
  return store.trendEvents
    .filter((e) => TREND_EVENTS[e.kind])
    .map((e) => ({ ...e, x: dayPosition(points, e.day) }))
    .filter((e) => e.x != null);
}

export function overviewHtml() {
  const c = store.manifest.counts || {};
  const views = store.manifest.views || {};
  const sets = Object.entries(views.sets || {}).map(([name, v]) => [
    name,
    typeof v === 'number' ? { packages: v, failed: 0, broken: 0 } : v,
  ]);
  // In sets updated in bulk ("pending" before 0.14.0).
  const inSets = c.inSets ?? c.pending ?? 0;
  const total = (c.tracked || 0) + inSets;
  const share = total ? (100 * (c.tracked || 0)) / total : 0;
  const points = (store.trendPoints || []).slice(-TREND_DAYS);
  const trends = points.length >= TREND_MIN_POINTS;
  // Build failures from before the count was kept apart: the newest and
  // longest-standing lists' count of them.
  const count = (key) =>
    key === 'buildFailures' && c[key] == null ? store.manifest.highlights?.failing?.count : c[key];
  const cards = CARDS.filter((card) => !card.optional || count(card.key) != null).map((card) => {
    // The days that have this count (the split ones are newer than the rest).
    const mine = points.filter((p) => p[card.key] != null);
    const drawn = mine.length >= TREND_MIN_POINTS;
    const trend = drawn ? trendChange(mine, card.key) : null;
    const change = trend?.change;
    const over = trend?.since ? `Since ${shortDay(trend.since)}` : 'Over the last 7 days';
    const said =
      change == null
        ? ''
        : change === 0
          ? html`<span class="card-change" title="${over}">no change<span class="sr-only">, ${over.toLowerCase()}</span></span>`
          : html`<span class="card-change ${change > 0 ? 'worse' : 'better'}" title="${over}"><span aria-hidden="true">${change > 0 ? '↑' : '↓'}</span><span class="sr-only">${change > 0 ? 'up' : 'down'}</span> ${fmt(Math.abs(change))}<span class="sr-only">, ${over.toLowerCase()}</span></span>`;
    return html`<a class="card" href="${scopeHref({ view: card.view, filter: card.filter })}" data-card-view="${card.view}" data-card-filter="${card.filter || ''}">
      <span class="card-label">${card.label}<span class="card-go" aria-hidden="true">›</span></span>
      <span class="card-row"><span class="card-n" style="color:${card.color}">${fmt(count(card.key))}</span>${said}</span>
      ${
        card.key === 'buildFailures' && c.failingBuilds
          ? html`<span class="card-sub" title="Every Hydra job that didn't build, on every platform, in all of nixpkgs: as zh.fail counts them, with a dependency's failure counted for each package it stops, and timeouts. A package counts here only when its own build failed.">${fmt(c.failingBuilds)} failing builds on Hydra</span>${platformSplit(c.buildFailuresOn)}`
          : card.key === 'updateFailures'
            ? backfillNote()
            : card.key === 'vulnerable'
              ? backportCardNote()
              : card.key === 'outdated'
                ? html`<span class="card-sub" title="Each package counted once, its other attributes left out, and the sets updated in bulk (Haskell, R and the others) left out: they count on their own lines below. With nixkeeper's own update checks, which can overrule a newer version listed elsewhere (a development series, a version upstream withdrew). Counts of every attribute in nixpkgs come out higher.">Unique, outside sets updated in bulk</span>`
                : ''
      }
      ${drawn ? sparkline(mine, card.key, card.color) : ''}
    </a>`;
  });
  return html`<h2 class="scope-head">
      <span class="scope-label">All of nixpkgs</span>
      <span class="scope-total">${fmt(total)} packages</span>
    </h2>
    <div class="scope-bar" aria-hidden="true"><span style="width:${share.toFixed(1)}%"></span></div>
    <div class="scope-split">
      <span><i class="swatch full"></i><b>${fmt(c.tracked)}</b> fully checked</span>
      <span title="Generated from CRAN, Hackage and the like and kept current in bulk by their own tooling, not one PR per package: each set counted on its own line below, not in the cards"><i class="swatch gen"></i><b>${fmt(inSets)}</b> in sets updated in bulk · counted per set</span>
    </div>
    <h2 class="scope-label">Fully checked${trends ? `, last ${trendSpan(points)} days` : ''} · each opens its list${trends ? '' : html` <span class="scope-hint">(trends from the second daily sync)</span>`}</h2>
    <div class="cards">${cards}</div>${trends ? marksHtml(points) : ''}

    <div class="find">${teamPicker('Browse a team…')}</div>
    <p class="find-more">or <a class="files-link" href="${scopeHref({ view: 'maintainers' })}" data-card-view="maintainers">browse every maintainer</a></p>
    <div class="overview-more">${highlightsHtml()}${causesHtml()}${fixedHtml()}${setsHtml(sets)}${numbersHtml()}</div>`;
}

// The overview's recently fixed (the manifest's "fixed", from history.json):
// builds that work again, packages updated, nixpkgs-update failures
// cleared, the last week's of each. Not with data from before it.
// What a fix ended, for its age's hover ("failing since Jun 2").
export const FIXED_SINCE = { build: 'failing', update: 'outdated', bot: 'the update bot failing' };

export const FIXED = [
  { key: 'build', label: 'Builds fixed' },
  { key: 'update', label: 'Updated' },
  { key: 'bot', label: 'Update failures cleared' },
];

// Who a fix is credited to (history.credit in nixkeeper): its PR, who
// opened it and who merged it; "likely" for a build fix (a PR merged since
// the build began failing that touched it). The name shown: the author,
// unless it's a bot (the update bot), then who merged it, unless that's a
// bot too (the merge bot, asked by someone the data doesn't say yet): then
// none, the PR still in the tooltip.
export const BOTS = new Set(['r-ryantm', 'nixpkgs-ci', 'nixpkgs-merge-bot', 'github-actions']);

export const creditName = (c) => [c.author, c.mergedBy].find((who) => who && !BOTS.has(who)) || '';

export const creditText = (c) =>
  `${c.likely ? 'Likely fixed by' : 'By'} #${c.pr}${c.author ? `, opened by @${c.author}` : ''}${c.mergedBy ? `, merged by @${c.mergedBy}` : ''}`;

export function fixedHtml() {
  const fixed = store.manifest.fixed;
  if (!fixed) return '';
  const cards = FIXED.map(({ key, label }) => {
    const f = fixed[key] || { count: 0, newest: [] };
    return html`<section class="hl-card" style="--hl:var(--ok-devel)" aria-label="${label}">
      <div class="hl-head">
        <h3 class="hl-title"><span class="hl-label">${label}</span><span class="hl-n">${fmt(f.count)}</span></h3>
      </div>
      ${
        f.newest.length
          ? html`<ol class="hl-list">${f.newest.map(
              ([name, at, from, to, credit, since, family]) =>
                html`<li><a class="hl-row" ${familyLink(name, family)}${credit ? html` title="${creditText(credit)}"` : ''}><span class="status-dot ok" aria-hidden="true"></span>${familyName(name, family)}${to ? html`<span class="fixed-to mono" title="${from} → ${to}">→ ${to}</span>` : ''}${credit && creditName(credit) ? html`<span class="fixed-by">@${creditName(credit)}</span>` : ''}${
                  since
                    ? html`<span class="hl-age" title="Fixed ${longDate(at)}, ${FIXED_SINCE[key]} since ${longDate(since)}">after ${shortAge(since, new Date(at).getTime())}</span>`
                    : html`<span class="hl-age" title="${longDate(at)}">${shortAge(at)}</span>`
                }</a></li>`,
            )}</ol>`
          : html`<p class="hl-none">None this week yet.</p>`
      }
    </section>`;
  });
  return html`<h2 class="scope-label" title="The fixes that took longest first: how long each had been failing or outdated when it was fixed">Recently fixed · last ${fixed.days} days · longest-standing first · fully checked</h2>
    <div class="hl-cols">${cards}</div>`;
}

export const SET_BAR_TITLE =
  'Outdated (orange), marked broken (yellow) and failing (red), each package once, at its worst: a failing package counts as failing only, a broken one as broken only. The counts below count each on its own, so a package can be in several.';

// The overview's sets updated in bulk: each one's size, what updates it,
// and how much of it is failing, marked broken or outdated (a bar, in
// their colours).
// The overview's last section, "nixpkgs in numbers": figures for the
// curious, out of the way of the lists above (the manifest's "numbers",
// datastore.numbers; "merge", prs_digest.merge_summary; the sources' PR and
// queue counts). Each says what it means, and opens its list when there is
// one. Only those the data has.
export function numbersHtml() {
  const n = store.manifest.numbers;
  if (!n) return '';
  const m = store.manifest.merge;
  const prs = store.sources?.prs;
  const queue = store.sources?.queue;
  const link = (href, text) => html` <a class="files-link" href="${href}">${text} →</a>`;
  const items = [
    prs?.prs != null && [
      fmt(prs.prs),
      'open PRs',
      `in nixpkgs, and ${fmt(prs.issues)} open issues`,
    ],
    m?.prs != null && [
      fmt(m.prs),
      'ready for the merge bot',
      html`PRs waiting for their own maintainers (${fmt(m.maintainers)} people could each merge one), ${fmt(m.over90)} for over three months. Yours: "You can merge these", on <a class="files-link" href="${scopeHref({ view: 'maintainers' })}" data-card-view="maintainers">your page</a>`,
    ],
    store.manifest.close?.prs != null && [
      fmt(store.manifest.close.prs),
      'update PRs nixpkgs is past',
      html`it already has their version or a newer one: they can be closed (${fmt(store.manifest.close.bot)} of them the update bot's)${store.manifest.close.init ? `, and ${fmt(store.manifest.close.init)} init PRs for a package it has now` : ''}. Yours: "Can be closed", on <a class="files-link" href="${scopeHref({ view: 'maintainers' })}" data-card-view="maintainers">your page</a>${link(scopeHref({ view: 'superseded' }), 'all of them')}`,
    ],
    [
      fmt(n.behind),
      'update PRs behind upstream',
      'upstream has moved on since they were opened: merged as they are, the package would still be outdated',
    ],
    queue?.cycleDays != null && [
      `${queue.cycleDays} days`,
      "the update bot's round",
      'how long nixpkgs-update takes to go through its whole queue, trying each package once',
    ],
    // The top card's failing builds (counts.failingBuilds), split by kind.
    [
      fmt(n.failing + (n.blocked || 0) + (n.unfinished || 0)),
      'builds not built on Hydra',
      `${fmt(n.failing)} failing themselves · ${fmt(n.blocked || 0)} blocked by a failing dependency · ${fmt(n.unfinished || 0)} unfinished (timed out or aborted) · of ${fmt(n.builds)} in master's evaluation, every platform, sets included`,
    ],
    store.manifest.views?.unbuilt != null && [
      fmt(store.manifest.views.unbuilt),
      'not built where listed',
      html`nixpkgs lists them for a platform Hydra doesn't build them on${link(scopeHref({ view: 'unbuilt' }), 'see them')}`,
    ],
    store.manifest.counts?.tracked > 0 && [
      `${Math.round((100 * (store.manifest.counts.tracked - store.manifest.counts.outdated)) / store.manifest.counts.tracked)}%`,
      'up to date',
      `of the ${fmt(store.manifest.counts.tracked)} packages outside the sets: nixpkgs has the newest version (${fmt(store.manifest.counts.outdated)} outdated)`,
    ],
    [
      fmt(n.unmaintained),
      'without a maintainer',
      html`packages outside the sets nobody maintains${link('?maintainer=none', 'see them')}`,
    ],
  ].filter(Boolean);
  return html`<h2 class="scope-label">nixpkgs in numbers</h2>
    <div class="numbers">${items.map(
      ([value, label, what]) =>
        html`<div class="number"><span class="number-v">${value}</span><span class="number-l">${label}</span><span class="number-what">${what}</span></div>`,
    )}</div>`;
}

export function setsHtml(sets) {
  if (!sets.length) return '';
  const pct = (n, of) => (of ? Math.min(100, (100 * n) / of) : 0).toFixed(1);
  const cards = sets.map(([s, v]) => {
    // Each package once, at its worst (from 0.14.0); before, broken and
    // failing as counted, overlapping.
    const worst = v.bar || { broken: v.broken, failed: v.failed };
    // In the order the text below says them.
    const bar = ['outdated', 'broken', 'failed'].filter((k) => worst[k]).map((k) => [k, worst[k]]);
    const problems = [
      v.outdated
        ? html`<span class="set-outdated">${fmt(v.outdated)} outdated</span>${v.onBranch ? html`, ${fmt(v.onBranch)} on ${profileOf(s)?.branch || 'its branch'}` : ''}`
        : '',
      v.archived
        ? html`<span class="set-broken" title="${ARCHIVED_TITLE}; nixpkgs marks most of them broken already">${fmt(v.archived)} archived${v.archivedUnmarked ? html` (${fmt(v.archivedUnmarked)} not marked broken)` : ''}</span>`
        : '',
      v.broken ? html`<span class="set-broken">${fmt(v.broken)} broken</span>` : '',
      v.failed ? html`<span class="set-failed">${fmt(v.failed)} failing</span>` : '',
    ].filter(Boolean);
    return html`<a class="set-card" href="${scopeHref({ set: s })}" data-scope-set="${s}">
      <span class="set-name mono">${s}</span>
      <span class="set-n">${fmt(v.packages)} <span class="set-unit">packages</span></span>
      <span class="set-by" title="${bulkText(s)}">by ${bulkShort(s)}</span>
      <span class="set-bar" aria-hidden="true" title="${SET_BAR_TITLE}">${bar.map(([kind, n]) => html`<span class="set-bar-${kind}" style="width:${pct(n, v.packages)}%"></span>`)}</span>
      <span class="set-meta">${problems.length ? problems.map((p, i) => html`${i ? ' · ' : ''}${p}`) : v.outdated == null ? 'None broken or failing' : 'None outdated, broken or failing'}</span>
    </a>`;
  });
  return html`<h2 class="scope-label">Sets updated in bulk <span class="scope-hint">each by its own tooling, not one PR per package: counted here, not in the cards above</span></h2>
    <div class="set-grid">${cards}</div>`;
}

// The overview's controls, once: its lists' newest or longest-standing, the
// groups card in full. page: what they need of the page (app.js's
// pageHooks).
export function wireOverview(page) {
  // The overview's lists: newest or longest-standing.
  document.getElementById('scope')?.addEventListener('click', (e) => {
    const mode = e.target.closest('button.hl-mode');
    if (mode) {
      highlightShown[mode.dataset.hl] = mode.dataset.mode;
      page.renderScope();
    }
  });

  // The groups card shown in full (or back to the biggest): every group,
  // loaded once from views/causes.json, then the overview drawn again.
  document.addEventListener('click', async (e) => {
    const button = e.target.closest('.cause-more');
    if (!button) return;
    if (store.allCauses) {
      store.allCauses = null;
    } else {
      try {
        store.allCauses = (await readJson('views/causes.json')).groups || [];
      } catch {
        return; // the biggest stay
      }
    }
    if (store.shownView === 'overview') page.renderScope();
  });
}
