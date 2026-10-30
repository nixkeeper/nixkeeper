// The "where the data is from" popover.

import { timeAgo } from './dates.js';
import { html } from './markup.js';
import { store } from './store.js';

// Where the data is from: the daily sync's sources as it noted them
// (nixkeeper/sources/about.py), each with when its data is from, or why the
// sync didn't use it (it then asked per package instead). Those read from
// one of nixkeeper's digests are grouped under it (DIGESTS), in this order.
const DIGESTS = {
  hydra: 'https://github.com/nixkeeper/digest-builds',
  versions: 'https://github.com/nixkeeper/digest-versions',
  updates: 'https://github.com/nixkeeper/digest-update-bot',
  vulnerabilities: 'https://github.com/nixkeeper/digest-vulnerabilities',
  prs: 'https://github.com/nixkeeper/digest-prs',
};

const hydraEval = (s) =>
  html`evaluation <a class="files-link" href="https://hydra.nixos.org/eval/${s.eval}" target="_blank" rel="noopener">${s.eval}</a>, read ${timeAgo(s.at)}`;

const SOURCES = [
  {
    key: 'nixpkgs',
    label: 'nixpkgs',
    from: 'https://github.com/NixOS/nixpkgs',
    says: (s) =>
      html`channel at <a class="files-link mono" href="https://github.com/NixOS/nixpkgs/commit/${s.revision}" target="_blank" rel="noopener">${s.revision.slice(0, 7)}</a>`,
  },
  { key: 'github', label: 'GitHub PRs', says: () => 'listed during the sync' },
  {
    // Only noted when lookups failed (Repology down, most likely).
    key: 'repology',
    label: 'Repology lookups',
    says: () => '',
    instead: 'the rest of the sync went on',
  },
  {
    // Hydra's nixpkgs/trunk jobset: master, which the channels follow.
    key: 'hydra',
    digest: 'hydra',
    label: 'master',
    from: 'https://hydra.nixos.org/jobset/nixpkgs/trunk',
    says: hydraEval,
  },
  {
    // Only the jobs that differ from master's (nixkeeper/sources/branches.py),
    // and only while its cycle isn't merged yet.
    key: 'branch:staging-next',
    digest: 'hydra',
    label: 'staging-next',
    from: 'https://hydra.nixos.org/jobset/nixpkgs/staging-next',
    says: (s) => html`${hydraEval(s)}, ${s.jobs?.toLocaleString()} jobs differing from master`,
    instead: 'not shown until its next evaluation',
  },
  {
    key: 'branch:haskell-updates',
    digest: 'hydra',
    label: 'haskell-updates',
    from: 'https://hydra.nixos.org/jobset/nixpkgs/haskell-updates',
    says: hydraEval,
    instead: 'not shown',
  },
  {
    // nixkeeper's own update checks (upstream.py, inferred.py): not a digest
    // nor noted by the sync, but run in it, so from the daily sync's time.
    key: 'nixkeeper',
    digest: 'versions',
    label: 'nixkeeper',
    title: "nixkeeper's own update checks: GitHub tags, release pages, a branch's commits",
    says: (s) => `read ${timeAgo(s.at)}`,
  },
  {
    key: 'versions',
    digest: 'versions',
    label: 'Repology',
    says: (s) => `read ${timeAgo(s.at)}`,
  },
  {
    key: 'releases',
    digest: 'versions',
    label: 'GitHub releases',
    says: (s) => `read ${timeAgo(s.at)}, ${s.packages?.toLocaleString()} packages`,
    instead: 'checked for the lists only',
  },
  {
    key: 'typst',
    digest: 'versions',
    label: 'Typst Universe',
    says: (s) => `read ${timeAgo(s.at)}, ${s.packages?.toLocaleString()} packages`,
    instead: "Repology's versions used",
  },
  {
    key: 'sets',
    digest: 'versions',
    label: "Generated sets' indexes",
    says: (s) =>
      `read ${timeAgo(s.at)}: CHICKEN 5 ${s.chickenPackages_5?.toLocaleString()}, CHICKEN 6 ${s.chickenPackages_6?.toLocaleString()}, Akku ${s.akkuPackages?.toLocaleString()}, GNOME ${s.gnomeExtensions?.toLocaleString()}, Azure CLI ${s['azure-cli-extensions']?.toLocaleString()} packages`,
    instead: "Repology's versions used",
  },
  {
    key: 'emacs',
    digest: 'versions',
    label: 'Emacs archives',
    says: (s) =>
      `read ${timeAgo(s.at)}: MELPA ${s.melpa?.toLocaleString()}, MELPA Stable ${s.melpaStable?.toLocaleString()}, NonGNU ${s.nongnu?.toLocaleString()}, GNU ${s.gnu?.toLocaleString()} packages`,
    instead: "Repology's versions used",
  },
  {
    key: 'stackage',
    digest: 'versions',
    label: 'Stackage LTS',
    says: (s) =>
      `nixpkgs follows ${s.nixpkgs}, ${s.snapshot} is the newest (${s.packages?.toLocaleString()} packages), read ${timeAgo(s.at)}`,
    instead: "Repology's versions used",
  },
  {
    key: 'cran',
    digest: 'versions',
    label: 'CRAN, Bioconductor',
    says: (s) =>
      `read ${timeAgo(s.at)}: CRAN ${s.cran?.toLocaleString()}, Bioconductor ${s.biocVersion} ${((s.bioc || 0) + (s.annotation || 0) + (s.experiment || 0)).toLocaleString()} packages`,
    instead: "Repology's versions used",
  },
  {
    key: 'updates',
    digest: 'updates',
    label: 'Update attempts',
    says: (s) =>
      `made ${timeAgo(s.at)}${s.pending ? ` · ${s.pending.toLocaleString()} attempts still to read` : ''}`,
  },
  {
    key: 'queue',
    digest: 'updates',
    label: 'Queue',
    says: (s) => `from ${timeAgo(s.at)}, going round every ${s.cycleDays} days`,
  },
  {
    key: 'tracker',
    digest: 'vulnerabilities',
    label: 'NixOS security tracker',
    from: 'https://tracker.security.nixos.org',
    says: (s) =>
      `read ${timeAgo(s.at)}: ${s.suggestions?.toLocaleString()} CVEs, on ${s.packages?.toLocaleString()} packages`,
    instead: "Repology's flag used",
  },
  {
    key: 'osv',
    digest: 'vulnerabilities',
    label: 'OSV',
    from: 'https://osv.dev',
    says: (s) =>
      `read ${timeAgo(s.at)}: ${s.advisories?.toLocaleString()} advisories, on ${s.packages?.toLocaleString()} packages`,
  },
  {
    key: 'prs',
    digest: 'prs',
    label: 'PRs and issues',
    says: (s) =>
      [
        `made ${timeAgo(s.at)}`,
        s.prs != null && `${s.prs.toLocaleString()} open PRs, ${s.issues?.toLocaleString()} issues`,
        s.merged != null && `${s.merged.toLocaleString()} merged since the channel`,
        s.staging != null && `${s.staging.toLocaleString()} merged into staging or staging-next`,
        s.partly && `${s.partly}: listed during the sync`,
      ]
        .filter(Boolean)
        .join(' · '),
    instead: 'listed during the sync',
  },
];

export function sourcesHtml() {
  const when = (iso) =>
    new Date(iso).toLocaleString(undefined, {
      day: 'numeric',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
    });
  const noted = (key) =>
    key === 'nixkeeper'
      ? store.sources?.versions && store.checkedAt && { used: true, at: store.checkedAt }
      : store.sources?.[key];
  const row = ({ key, label, from, title, says, instead, digest }) => {
    const s = noted(key);
    const name = from
      ? html`<a class="files-link" href="${from}" target="_blank" rel="noopener">${label}</a>`
      : label;
    return html`<li class="${[s.used ? '' : 'unused', digest ? 'in-digest' : ''].filter(Boolean).join(' ')}"><b${title ? html` title="${title}"` : ''}>${name}</b><span class="src-what"${s.at ? html` title="${when(s.at)}"` : ''}>${
      s.used
        ? says(s)
        : `not used: ${s.why || 'unknown'}${s.at ? `, from ${timeAgo(s.at)}` : ''}, ${instead || 'asked per package instead'}`
    }</span></li>`;
  };
  const shown = SOURCES.filter(({ key }) => noted(key));
  const own = shown.filter((src) => !src.digest).map(row);
  const digests = Object.entries(DIGESTS).map(([digest, url]) => {
    const mine = shown.filter((src) => src.digest === digest);
    return mine.length
      ? html`<li class="src-digest"><a class="files-link" href="${url}" target="_blank" rel="noopener">${url.split('/').pop()}</a></li>${mine.map(row)}`
      : '';
  });
  // nixkeeper.com: every source, and whether each is on time, is the status
  // page's (it was a screenful here, too long for a phone). Elsewhere (an
  // instance of its own, a preview), the list as before: the status page
  // isn't about its runs.
  if (location.hostname === 'nixkeeper.com') {
    const nix = noted('nixpkgs');
    return html`<p class="pop-title">Where the data is from</p>
    <ul>
      <li><b>Last sync</b><span title="${store.checkedAt ? when(store.checkedAt) : ''}">${store.checkedAt ? `${timeAgo(store.checkedAt)}, ${when(store.checkedAt)}` : 'not yet'}</span></li>
      ${nix?.used ? html`<li><b>nixpkgs</b><span>${SOURCES[0].says(nix)}</span></li>` : ''}
    </ul>
    <a class="files-link" href="https://status.nixkeeper.com/" target="_blank" rel="noopener">Every source, and how fresh it is ↗</a>
    <a class="files-link" href="https://github.com/nixkeeper/nixkeeper/blob/main/docs/how-it-works.md" target="_blank" rel="noopener">How nixkeeper gathers it ↗</a>`;
  }
  return html`<p class="pop-title">Where the data is from</p>
    <ul>
      <li><b>Last sync</b><span title="${store.checkedAt ? when(store.checkedAt) : ''}">${store.checkedAt ? `${timeAgo(store.checkedAt)}, ${when(store.checkedAt)}` : 'not yet'}</span></li>
      <li><b>Hourly checks</b><span>frequent update checks and update PRs, between syncs</span></li>
      ${own}
      ${digests}
    </ul>
    <a class="files-link" href="https://github.com/nixkeeper/nixkeeper/blob/main/docs/how-it-works.md" target="_blank" rel="noopener">How nixkeeper gathers it ↗</a>`;
}
