// A package panel's sections, from the package alone (no page state):
// its vulnerabilities, builds and what's on GitHub. Pure: a package in, HTML
// out (tests/js/panel.test.mjs).
import {
  compareVersions,
  cvePieces,
  onMaster,
  shortAge,
  targetVersion,
  VULN_COUNTED,
  vulnFixes,
} from './logic.js';
import { html, raw, safeUrl } from './markup.js';
import { BUILD_FAILED, fmt, GH_ICONS, icon, longDate, shortDay } from './ui.js';

// What each verdict on a CVE or advisory says (nixkeeper-vulnerabilities,
// sources/vulnerabilities_digest.py); those in VULN_COUNTED count. Each:
// [a word or two for the line, the sentence its hover says].
export const VERDICTS = {
  affected: ['affected', "Affected: nixpkgs' version is in the CVE's range"],
  byVersion: ['affected', "Affected: nixpkgs' version is in the CVE's range"], // data from before
  tracker: ['affected', "Affected, says the security tracker (the CVE's versions can't be read)"],
  wontFix: ["won't fix", "The security team won't fix it"],
  osv: ['OSV advisory', "An OSV advisory that lists nixpkgs' version"],
  unconfirmed: ['unconfirmed', "Unconfirmed: the CVE's versions can't be read"],
  fixed: ['fixed', "Fixed in nixpkgs' version"],
  patched: ['patched', 'Fixed by a patch in nixpkgs, named after it'],
  dismissed: ['dismissed', 'Dismissed by the security team'],
};

// The panel's CVEs and advisories (the row's "vulnerabilities"), counted
// ones first, worst first; the others folded. What the counted ones share
// is said once, above them: how many of each severity, the verdict and the
// release branches still affected (a fix to backport), when the same for
// all. Then they're grouped by the tracker's issue (its nixpkgs issue
// linked once), a line each: the id, its severity and its summary (cut
// short, whole on hover), and what it doesn't share. The worst VULNS_SHOWN,
// then "Show all": zitadel's 24 took 48 lines, most of them repeating
// (2026-10-23).
export const VULNS_SHOWN = 5;

export function vulnSection(pkg) {
  const all = pkg.vulnerabilities || [];
  if (!all.length) return '';
  const link = (id) =>
    id.startsWith('CVE-')
      ? `https://nvd.nist.gov/vuln/detail/${encodeURIComponent(id)}`
      : `https://osv.dev/vulnerability/${encodeURIComponent(id)}`;
  const stillAffected = (v) =>
    Object.entries(v.releases || {})
      .filter(([, status]) => status === 'affected')
      .map(([branch]) => branch.replace(/^release-/, ''))
      .join(', ');
  const verdict = (v) =>
    VERDICTS[v.verdict]
      ? html`<span class="vl-verdict" title="${VERDICTS[v.verdict][1]}">${VERDICTS[v.verdict][0]}<span class="sr-only">: ${VERDICTS[v.verdict][1]}</span></span>`
      : html`<span class="vl-verdict">${v.verdict}</span>`;
  const issueLink = (v) =>
    html`<a class="files-link mono" href="https://tracker.security.nixos.org/issues/${encodeURIComponent(v.issue)}" target="_blank" rel="noopener">${v.issue}</a>${v.github && safeUrl(v.github) ? html` (<a class="files-link" href="${safeUrl(v.github)}" target="_blank" rel="noopener">its nixpkgs issue</a>)` : ''}`;
  // Open PRs patching it (prs_digest.add_cve_prs): "patched by #563607".
  const patches = (prs, all = false) =>
    html`${all ? 'all ' : ''}patched by ${prs.map(
      (p, i) =>
        html`${i ? ', ' : ''}<a class="files-link gh-item pr" href="https://github.com/NixOS/nixpkgs/pull/${p.number}" target="_blank" rel="noopener" title="${p.title}">${GH_ICONS.pr}<span class="sr-only">PR </span>#${p.number} ↗</a>${
          p.base || p.draft
            ? html` (${[p.base && html`into <span class="mono">${p.base}</span>`, p.draft && 'a draft'].filter(Boolean).map((x, k) => html`${k ? ', ' : ''}${x}`)})`
            : ''
        }`,
    )}`;
  const prKey = (v) => (v.prs || []).map((p) => p.number).join(',');
  const sharedPRs = (vs) => vs.length > 1 && new Set(vs.map(prKey)).size === 1 && vs[0].prs;
  // One line: its id, severity and summary; and, when they aren't said
  // above (own: false), its verdict, its issue and the branches still affected.
  const line = (
    v,
    {
      sharedVerdict = false,
      sharedReleases = false,
      sharedFix = false,
      sharedPR = false,
      own = true,
    } = {},
    hidden = false,
  ) => {
    const releases = stillAffected(v);
    return html`<li class="vl"${hidden ? raw(' hidden') : ''}><a class="files-link mono" href="${link(v.id)}" target="_blank" rel="noopener">${v.id}</a>${
      v.severity ? html` <span class="sev sev-${v.severity}">${v.severity}</span>` : ''
    }${sharedVerdict ? '' : html` ${verdict(v)}`}${v.summary ? html` <span class="vl-summary" title="${v.summary}">${v.summary}</span>` : ''}${
      own && v.issue ? html`<span>· ${issueLink(v)}</span>` : ''
    }${!sharedReleases && releases ? html`<span>· <span class="vl-backport">still affected on ${releases}</span></span>` : ''}${
      !sharedFix && v.fixedIn
        ? html`<span>· fixed in <span class="mono">${v.fixedIn}</span></span>`
        : ''
    }${!sharedPR && v.prs ? html`<span>· ${patches(v.prs)}</span>` : ''}</li>`;
  };
  const counted = all.filter((v) => VULN_COUNTED.includes(v.verdict));
  const rest = all.filter((v) => !VULN_COUNTED.includes(v.verdict));
  // What they all share, said once.
  const verdicts = new Set(counted.map((v) => v.verdict));
  const sharedVerdict = counted.length > 1 && verdicts.size === 1;
  const releaseSets = new Set(counted.map(stillAffected));
  const sharedReleases = counted.length > 1 && releaseSets.size === 1;
  const fixSet = new Set(counted.map((v) => v.fixedIn));
  const sharedFix = counted.length > 1 && fixSet.size === 1 && [...fixSet][0];
  const sharedPR = sharedPRs(counted);
  const restPR = sharedPRs(rest);
  const word = counted.every((v) => v.id.startsWith('CVE-')) ? 'CVE' : 'advisory';
  const severities = ['critical', 'high', 'medium', 'low']
    .map((sev) => [sev, counted.filter((v) => v.severity === sev).length])
    .filter(([, n]) => n);
  const head =
    counted.length > 1
      ? html`<p class="vl-head">${fmt(counted.length)} ${word === 'CVE' ? 'CVEs' : 'advisories'}${
          severities.length
            ? html`: ${severities.map(([sev, n], i) => html`${i ? ', ' : ''}${fmt(n)} <span class="sev sev-${sev}">${sev}</span>`)}`
            : ''
        }${sharedVerdict ? html` · all ${verdict(counted[0])}` : ''}${
          sharedReleases && [...releaseSets][0]
            ? html` · <span class="vl-backport">still affected on ${[...releaseSets][0]}</span>`
            : ''
        }${sharedFix ? html` · all fixed in <span class="mono">${sharedFix}</span>` : ''}${
          sharedPR ? html` · ${patches(sharedPR, true)}` : ''
        }</p>`
      : '';
  // Grouped by the tracker's issue, in the order of their worst.
  const groups = new Map();
  for (const v of counted) groups.set(v.issue || '', [...(groups.get(v.issue || '') || []), v]);
  let shownSoFar = 0;
  const grouped = [...groups.values()].map((vs) => {
    const first = shownSoFar;
    shownSoFar += vs.length;
    const hideGroup = first >= VULNS_SHOWN;
    const opts = {
      sharedVerdict,
      sharedReleases,
      sharedFix,
      sharedPR,
      own: !vs[0].issue || vs.length === 1,
    };
    return html`<div class="vl-group"${hideGroup ? raw(' hidden') : ''}>${
      vs[0].issue && vs.length > 1
        ? html`<p class="vl-issue">${issueLink(vs[0])} · ${fmt(vs.length)} ${word === 'CVE' ? 'CVEs' : 'advisories'}</p>`
        : ''
    }<ul class="vl-list">${vs.map((v, i) => line(v, opts, first + i >= VULNS_SHOWN))}</ul></div>`;
  });
  const more =
    counted.length > VULNS_SHOWN
      ? html`<button type="button" class="more-btn vl-more" aria-expanded="false" data-all="${counted.length}">Show all ${fmt(counted.length)}</button>`
      : '';
  // What fixes them, from the versions their ranges say do: master, its
  // open update PR (here rather than as a pill under On GitHub) and the
  // newest release. Without those, whether the PR's version fixes them is
  // for a person to check.
  const pr = pkg.openPR?.facts?.vulnerable && counted.length ? pkg.openPR : null;
  const fixes = vulnFixes(pkg, counted);
  const prItem = pr
    ? html`<a class="files-link gh-item pr" href="${safeUrl(pr.url)}" target="_blank" rel="noopener">${GH_ICONS.pr}<span class="sr-only">PR </span>#${pr.number} ↗</a>`
    : '';
  const them = counted.length === 1 ? 'it' : 'them';
  // Of those whose ranges name a version that fixes them: "fixes them",
  // "fixes 3 of 5", with the version all of them need when it falls short.
  const unnamed = fixes ? counted.length - fixes.named : 0;
  const does = (k) => {
    const of = !unnamed
      ? ''
      : fixes.named === 1
        ? ' the one that names a fixed version'
        : ` the ${fmt(fixes.named)} that name a fixed version`;
    if (k >= fixes.named) return unnamed ? `fixes${of}` : `fixes ${them}`;
    return k
      ? `fixes ${fmt(k)} of${of || ` ${fmt(counted.length)}`}`
      : `doesn't fix${of || ` ${them}`}`;
  };
  // A fix only in a newer series than nixpkgs' (mariadb 11.4 against
  // 12.2.2): its own series may have it backported, which ranges miss.
  const major = (v) => (v || '').split(/[.\-_+~]/)[0];
  const backport =
    fixes && major(fixes.need) !== major(pkg.nixVersion)
      ? html` (a newer series: check whether nixpkgs' ${major(pkg.nixVersion)}.x has the fix backported)`
      : '';
  const need = (k) =>
    k < fixes.named
      ? html`: ${fixes.named > 1 ? 'all ' : ''}fixed in <span class="mono">${fixes.need}</span>${backport}`
      : '';
  const newest = targetVersion(pkg);
  const fixLines = [];
  if (fixes?.master)
    fixLines.push(
      html`Master has <span class="mono">${onMaster(pkg)}</span>, which ${does(fixes.master)}: it reaches the channel in a few days`,
    );
  if (pr)
    fixLines.push(
      fixes
        ? html`${prItem} updates it to <span class="mono">${pr.to}</span>, which ${does(fixes.pr)}${need(fixes.pr)}; review it first`
        : html`${prItem} updates it to <span class="mono">${pr.to}</span>: check whether that fixes ${them}, and review it first`,
    );
  if (fixes && fixes.master < fixes.named && (!pr || (fixes.pr < fixes.named && newest !== pr.to)))
    fixLines.push(
      newest && compareVersions(newest, pkg.nixVersion) > 0
        ? html`${fixes.newest < fixes.named ? 'Even the' : 'The'} newest release, <span class="mono">${newest}</span>, ${does(fixes.newest)}${need(fixes.newest)}`
        : html`${fixes.named > 1 ? 'All fixed' : 'Fixed'} in <span class="mono">${fixes.need}</span>, newer than any release nixkeeper knows of${backport}`,
    );
  return html`<section class="pd-sec vl-sec"><h4 class="other-label">Vulnerabilities</h4>${
    counted.length ? html`${head}${grouped}${more}` : html`<p class="pd-text">None counted.</p>`
  }${counted.length ? fixLines.map((l) => html`<p class="pd-text vl-pr">${l}</p>`) : ''}${
    rest.length
      ? html`<details class="vl-rest"><summary>${rest.length} not counted (fixed, unconfirmed or dismissed)${
          restPR ? html` · ${patches(restPR, true)}` : ''
        }</summary><ul class="vl-list">${rest.map((v) => line(v, { sharedPR: Boolean(restPR) }))}</ul></details>`
      : ''
  }</section>`;
}

// CVEs fixed on master but still affected on the newest release branch
// ("backport", from the sync): a fix to backport.
export function backportNote(pkg) {
  if (!pkg.backport?.length) return '';
  const entry = (id) => (pkg.vulnerabilities || []).find((v) => v.id === id) || {};
  const releases = [
    ...new Set(
      pkg.backport.flatMap((id) =>
        Object.entries(entry(id).releases || {})
          .filter(([, status]) => status === 'affected')
          .map(([branch]) => branch.replace(/^release-/, '')),
      ),
    ),
  ];
  return html`<div class="master-note">A fix to backport: ${pkg.backport.map(
    (id, i) => html`${i ? ', ' : ''}<span class="mono">${id}</span>`,
  )} ${pkg.backport.length === 1 ? 'is' : 'are'} fixed on nixpkgs master, still affected on ${releases.join(', ') || 'the newest release'}.</div>`;
}

// nixpkgs marks it insecure (meta.knownVulnerabilities): its reasons, with
// their CVE ids linked to NVD.
export function insecureNote(pkg) {
  if (!pkg.markedInsecure?.length) return '';
  const reason = (text) =>
    cvePieces(text).map((p) =>
      p.cve
        ? html`<a class="files-link mono" href="https://nvd.nist.gov/vuln/detail/${p.cve}" target="_blank" rel="noopener">${p.cve}</a>`
        : p.text,
    );
  return html`<div class="vuln-note">⚠ nixpkgs marks it insecure: it won't build unless allowed (<span class="mono">permittedInsecurePackages</span>).<ul class="vuln-reasons">${pkg.markedInsecure.map((r) => html`<li>${reason(r)}</li>`)}</ul></div>`;
}

export const HYDRA = 'https://hydra.nixos.org';

export const BUILD_STATUS = {
  ok: { dot: 'ok', text: 'built OK', short: 'built' },
  failed: { dot: 'missing', text: 'failed', short: 'failed' },
  broken: { dot: 'caution', text: 'marked broken in nixpkgs', short: 'marked broken' },
  dependency: {
    dot: 'caution',
    text: "didn't build: a dependency failed",
    short: 'dependency failed',
  },
  unfinished: {
    dot: 'caution',
    text: "didn't finish (timed out or aborted)",
    short: "didn't finish",
  },
  notBuilt: { dot: 'neutral', text: 'not built by Hydra on this platform', short: 'not built' },
  unknown: { dot: 'neutral', text: "couldn't check Hydra on the last run", short: 'unknown' },
};

// Which dependency stopped a build (nixkeeper-hydra's blockedBy): its
// package, opening it where the page has every package (pkgHref: its
// address, or null), or the name Hydra gave it.
export function blockedByHtml(blockers, pkgHref = () => null) {
  return html`blocked by ${blockers.map(
    ({ name, row }, i) =>
      html`${i ? ', ' : ''}${
        row && pkgHref(name)
          ? html`<a class="files-link mono" href="${pkgHref(name)}" data-scope-pkg="${name}">${name}</a>`
          : html`<span class="mono">${name}</span>`
      }`,
  )} (its build failed)`;
}

// One system's build in the builds panel: where, its status, when it last
// built, and what to open (the log, the job, the build, the source).
// alike: how many builds fail as this one does, and whether this line shows
// their log's lines (the last of them: groupedBuilds); the others have their
// Log link instead. pkgHref: a package's address, for a blocking one
// (blockedByHtml).
export function buildLine(pkg, b, alike = { n: 1, shows: true }, pkgHref = () => null) {
  const s = BUILD_STATUS[b.status] || BUILD_STATUS.unknown;
  const multi = (pkg.attrs || []).length > 1;
  // The versions only when they differ: the same version means something else
  // broke it (a dependency, the toolchain), not the update.
  const versionsDiffer = b.version && b.lastSuccessVersion && b.version !== b.lastSuccessVersion;
  // Failing at another version than it last built at: since that update.
  // Its PR when nixkeeper knows it (prs_digest.build_fix_prs), else a
  // search for it.
  const cause = pkg.buildCausePR;
  const updatePR =
    cause && cause.title.endsWith(b.version)
      ? html` (<a class="files-link gh-item merged" href="${safeUrl(cause.url)}" target="_blank" rel="noopener" title="${cause.title}">${GH_ICONS.merged}<span class="sr-only">PR </span>#${cause.number} ↗</a>)`
      : html` (<a class="files-link" href="https://github.com/NixOS/nixpkgs/pulls?q=${encodeURIComponent(`is:pr is:merged in:title "${(b.attr || pkg.name).split('.').pop()}" "${b.version}"`)}" target="_blank" rel="noopener" title="Search nixpkgs' merged PRs for this update">its PR ↗</a>)`;
  const at =
    versionsDiffer && b.status === 'failed'
      ? html` at <span class="mono">${b.version}</span>, since its update${updatePR}`
      : '';
  let lastGood = '';
  if (versionsDiffer) {
    const v = b.lastSuccessVersion;
    lastGood = b.lastSuccessBuild
      ? html` at <a class="files-link mono" href="${HYDRA}/build/${b.lastSuccessBuild}" target="_blank" rel="noopener">${v}</a>`
      : html` at <span class="mono">${v}</span>`;
  }
  const since =
    'lastSuccess' in b
      ? b.lastSuccess
        ? html`last built${lastGood} <span title="${longDate(b.lastSuccess)}">${shortAge(b.lastSuccess)} ago</span>`
        : 'never built successfully'
      : '';
  // Why it failed, from its log (nixkeeper-hydra), and the lines that say so:
  // in the status badge itself ("failed: missing file", as the list's cell
  // says it), not beside it.
  const why = b.status === 'failed' && BUILD_FAILED[b.failedBecause];
  const what =
    b.status === 'dependency' && b.blockedBy?.length
      ? html`${blockedByHtml(b.blockedBy, pkgHref)}${since ? html` · ${since}` : ''}`
      : html`${at}${at && since ? ' · ' : ''}${since}`;
  const act = (href, name, label, title) =>
    html`<a class="pd-link" href="${href}" target="_blank" rel="noopener"${title ? html` title="${title}"` : ''}>${icon(name)}${label}</a>`;
  const excerpt = why && b.failedExcerpt && alike.shows;
  const acts = [
    // With the log's lines shown, their own link ("full log") instead.
    b.status === 'failed' && !excerpt && act(`${HYDRA}/build/${b.build}/log`, 'file-text', 'Log'),
    // A failed build's page too: every step, when the failure is in a
    // derivation built for it rather than the package's own step.
    ['failed', 'dependency', 'unfinished'].includes(b.status) &&
      b.build &&
      act(`${HYDRA}/build/${b.build}`, 'hammer', 'Build', `Hydra build ${b.build}`),
    b.status === 'broken' &&
      safeUrl(pkg.source) &&
      act(safeUrl(pkg.source), 'file-code', 'Source', 'Where nixpkgs marks it broken'),
    b.status !== 'notBuilt' &&
      act(
        `${HYDRA}/job/nixpkgs/unstable/${encodeURIComponent(`${b.attr}.${b.system}`)}`,
        'external-link',
        'Job',
        `Hydra job ${b.attr}.${b.system}: every build of it`,
      ),
  ].filter(Boolean);
  return html`<div class="br${alike.n > 1 && !alike.shows ? ' alike' : ''}">
    <span class="br-sys"><span class="mono">${b.system}</span>${multi ? html`<span class="mono br-attr">${b.attr}</span>` : ''}</span>
    <span class="br-st ${s.dot}" title="${why ? `${s.text}: ${why.text}` : s.text}">${why ? html`<span class="sr-only">${s.short}: </span>${why.short}` : s.short}</span>
    <span class="br-what">${what}</span>
    <span class="br-acts">${acts}</span>
    ${excerpt ? html`<div class="br-log-wrap"><pre class="br-log" title="From the build's log on Hydra">${b.failedExcerpt}</pre><span class="br-log-foot"><a class="files-link br-full-log" href="${HYDRA}/build/${b.build}/log" target="_blank" rel="noopener">full log ↗</a>${alike.n > 1 ? ` · the same on ${alike.n === 2 ? 'both' : `all ${alike.n}`}` : ''}</span></div>` : ''}
  </div>`;
}

// A failure's log lines as compared between builds: without what changes
// from one run to the next (pytest's timings, its "=" padding around them).
export const sameFailure = (b) =>
  `${b.failedBecause}\n${(b.failedExcerpt || '')
    .replace(/ in [\d.]+s( \(\d+:\d\d:\d\d\))?/g, '')
    .replace(/=+/g, '=')
    .replace(/\s+/g, ' ')}`;

// The builds in their order, those failing alike (same reason, same log
// lines: python313Packages and python314Packages, on two platforms) brought
// together where the first of them is, each with its alike for buildLine:
// their lines shown once, under the last.
export function groupedBuilds(builds) {
  const key = (b) => (b.status === 'failed' && b.failedExcerpt ? sameFailure(b) : null);
  const groups = new Map();
  for (const b of builds) if (key(b)) groups.set(key(b), [...(groups.get(key(b)) || []), b]);
  const out = [];
  for (const b of builds) {
    const k = key(b);
    if (!k) out.push([b, { n: 1, shows: true }]);
    else if (groups.get(k)[0] === b) {
      const all = groups.get(k);
      all.forEach((x, i) => {
        out.push([x, { n: all.length, shows: i === all.length - 1 }]);
      });
    }
  }
  return out;
}

// ", by @author, merged by @merger", each a link (either may be missing).
export const whoDid = (author, mergedBy) => {
  const at = (who) =>
    html`<a class="files-link" href="https://github.com/${encodeURIComponent(who)}" target="_blank" rel="noopener">@${who}</a>`;
  return html`${author ? html`, by ${at(author)}` : ''}${mergedBy ? html`, merged by ${at(mergedBy)}` : ''}`;
};

// What nixkeeper-prs found of a package's PRs and issues (the daily sync's
// facts, nixkeeper/sources/prs_digest.py): its update PR's merge-bot
// eligibility, state, bot blocking and duplicates; open PRs touching it
// while its build fails on Hydra; and its issues checked against Hydra and
// nixpkgs now. Nothing when there's none.
// Each: [the pill's few words, the sentence its hover says].
export const PR_STATES = {
  superseded: (now) => [`superseded (${now})`, `Superseded: nixpkgs has ${now} already`],
  overtaken: (now) => [
    `needs a rebase (${now})`,
    `Overtaken: nixpkgs moved to ${now}, a rebase is needed`,
  ],
  downgrade: () => ['a downgrade', 'It would downgrade the package'],
  snapshotToRelease: () => ['back to a release', 'From a snapshot back to a release'],
  preRelease: () => ['a pre-release', 'To a pre-release, by its version suffix'],
};

export function githubSection(pkg) {
  // Each PR and issue with GitHub's icon for it: open, draft, merged, issue.
  const link = (item, kind = item.draft ? 'draft' : 'pr', who = '') =>
    html`<a class="files-link gh-item ${kind}" href="${safeUrl(item.url)}" target="_blank" rel="noopener"${who ? html` title="${who[0].toUpperCase()}${who.slice(1)}"` : ''}>${GH_ICONS[kind]}<span class="sr-only">${kind === 'issue' ? 'issue' : kind === 'merged' ? 'merged PR' : kind === 'draft' ? 'draft PR' : 'PR'} </span>#${item.number} ↗</a>`;
  // A pill of a few words; the sentence behind them on hover, and for
  // screen readers (they were whole sentences, in the pill, 2026-10-23).
  const fact = (kind, text, title) =>
    html`<span class="gh-fact ${kind}"${title ? html` title="${title}"` : ''}>${text}${title ? html`<span class="sr-only">: ${title}</span>` : ''}</span>`;
  const lines = [];
  // Marked broken with open PRs: one may fix it, or be moot now.
  if (pkg.markedBroken && pkg.openPRs > 0)
    lines.push(
      html`<li>${fact('warn', `broken · ${fmt(pkg.openPRs)} open PR${pkg.openPRs === 1 ? '' : 's'}`, `Marked broken, and ${pkg.openPRs === 1 ? 'an open PR touches' : `${fmt(pkg.openPRs)} open PRs touch`} it: one may fix it, or be moot while it stays broken; worth a look before reviewing it`)}</li>`,
    );
  const pr = pkg.openPR;
  const f = pr?.facts;
  if (f) {
    const said = [
      f.fixesBuild &&
        fact(
          '',
          'may fix the build',
          'It changes the package while its build fails on Hydra: maybe its fix',
        ),
      f.mergeBot === 'ready' &&
        fact(
          'ok',
          'merge-bot ready',
          'Ready for the merge bot: CI green, no conflict; a maintainer of the package can merge it by commenting @NixOS/nixpkgs-merge-bot merge',
        ),
      f.mergeBot === 'eligible' &&
        fact(
          '',
          'merge-bot eligible',
          'The merge bot could merge it once CI is green and any conflict is sorted out',
        ),
      f.state && fact('warn', ...(PR_STATES[f.state] || (() => [f.state]))(f.now || '?')),
      f.behind &&
        fact(
          'warn',
          `behind (${f.behind})`,
          `Behind: upstream has ${f.behind}. Merged as it is, the package would still be outdated: worth updating the PR first`,
        ),
      f.blocksBot &&
        fact(
          'warn',
          'blocks the bot',
          `Blocks the update bot${typeof f.blocksBot === 'string' ? ` (its next try ~${shortDay(f.blocksBot)})` : ''}: it has the very title nixpkgs-update would use, so the bot skips this update while it is open`,
        ),
      f.duplicates?.length &&
        html`<span class="gh-fact">also open: ${f.duplicates.map((n, i) => html`${i ? ' ' : ''}<a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${n}" target="_blank" rel="noopener">#${n}</a>`)}</span>`,
    ].filter(Boolean);
    if (said.length)
      lines.push(html`<li>Update PR ${link(pr)} <span class="mono">${pr.to}</span>: ${said}</li>`);
  }
  // Open update PRs nixpkgs is already past (prs_digest.mark_superseded).
  // And init PRs for it, added another way while they waited.
  for (const sp of pkg.supersededPRs || [])
    lines.push(
      html`<li>${link({ ...sp, url: `https://github.com/NixOS/nixpkgs/pull/${sp.number}` })} ${sp.title} ${
        sp.init
          ? fact(
              'warn',
              'can be closed (in nixpkgs)',
              `nixpkgs has it now (${sp.now}), added another way while this PR waited: the PR can be closed`,
            )
          : fact(
              'warn',
              `can be closed (${sp.now})`,
              `nixpkgs has ${sp.now}, this version or a newer one: the PR can be closed, or updated to the newest`,
            )
      }</li>`,
    );
  // Its other open PRs, a removal first (prs_digest.add_facts).
  const KIND = {
    drop: (other) => {
      const attr = /^([\w.+-]+):/.exec(other.title)?.[1];
      const what = attr && attr.toLowerCase() !== pkg.name.toLowerCase() ? attr : 'it';
      // Only proposed (changes requested, or no activity for months): said
      // quietly, no "being removed" badge in the list.
      return other.proposed
        ? fact(
            '',
            'removal proposed',
            `This PR would remove ${what} from nixpkgs (${other.proposed}), but it doesn't look likely to be merged as it is`,
          )
        : fact('warn', 'removes it', `It removes ${what} from nixpkgs`);
    },
    init: () => fact('', 'adds it'),
    update: () => fact('', 'an update'),
  };
  const closing = new Set((pkg.supersededPRs || []).map((sp) => sp.number));
  for (const other of (pkg.otherPRs || []).filter((o) => !closing.has(o.number)))
    lines.push(
      html`<li>${link({ ...other, url: `https://github.com/NixOS/nixpkgs/pull/${other.number}` })} ${other.title} ${other.kind ? KIND[other.kind]?.(other) || '' : ''}${
        other.mergeBot === 'ready'
          ? fact('ok', 'merge-bot ready', 'Ready for the merge bot: CI green, no conflict')
          : other.mergeBot === 'eligible'
            ? fact('', 'merge-bot eligible')
            : ''
      }</li>`,
    );
  // The update its build began failing with (prs_digest.build_fix_prs).
  const bc = pkg.buildCausePR;
  if (bc)
    lines.push(
      html`<li>${link(bc, 'merged', [bc.author && `by @${bc.author}`, bc.mergedBy && `merged by @${bc.mergedBy}`].filter(Boolean).join(', '))} ${bc.title} ${fact('warn', 'likely broke the build', 'Its build has failed since this update, at the version it updated to: likely what broke it')}</li>`,
    );
  // A PR merged since its build began failing that touched it: likely the
  // fix, once Hydra builds it (prs_digest.build_fix_prs).
  const bf = pkg.buildFixPR;
  if (bf)
    lines.push(
      // Who wrote and merged it on the link's hover, not the line: the icon
      // says merged, and no other line here names people.
      html`<li>${link(bf, 'merged', [bf.author && `by @${bf.author}`, bf.mergedBy && `merged by @${bf.mergedBy}`].filter(Boolean).join(', '))} ${bf.title} ${fact('ok', 'likely fix', "Merged since its build began failing: likely its fix, which Hydra hasn't built yet (or the failure was elsewhere)")}</li>`,
    );
  for (const fix of pkg.fixPRs || [])
    lines.push(
      html`<li>${link(fix)} ${fix.title} ${fact('', 'may fix the build', 'It touches the package while its build fails on Hydra: maybe its fix')}</li>`,
    );
  const ISSUE = {
    builds: (c) =>
      c.condition
        ? fact(
            'warn',
            'builds now · check it',
            'It builds on Hydra now, but the title adds a condition to check',
          )
        : fact('ok', 'builds now · can close', 'It builds on Hydra now: a candidate to close'),
    failing: () => fact('', 'still failing', 'Still failing on Hydra'),
    done: (c) =>
      fact(
        'ok',
        `done${c.now ? ` (${c.now})` : ''} · can close`,
        `nixpkgs has ${c.now || 'it'}: a candidate to close`,
      ),
    partly: (c) =>
      fact(
        'warn',
        `partly done${c.now ? ` (${c.now})` : ''}`,
        `nixpkgs moved to ${c.now || 'a newer version'}, not to the one asked`,
      ),
    cveFixed: (c) =>
      fact(
        'ok',
        `CVE${c.cves?.length > 1 ? 's' : ''} fixed · can close`,
        `${(c.cves || []).join(', ')}: ${c.cves?.length > 1 ? "none affect nixpkgs' version" : "it doesn't affect nixpkgs' version"}, as nixkeeper reads the security tracker and OSV: a candidate to close. Check before closing`,
      ),
  };
  for (const c of pkg.issueChecks || [])
    lines.push(
      html`<li>${link(c, 'issue')} ${c.title} ${(ISSUE[c.verdict] || (() => c.verdict))(c)}</li>`,
    );
  return lines.length
    ? html`<section class="pd-sec"><h4 class="other-label">On GitHub</h4><ul class="gh-checks">${lines}</ul></section>`
    : '';
}
