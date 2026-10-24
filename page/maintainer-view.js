// A maintainer's or a team's page, above its list: the PRs they can merge
// now with nixpkgs' merge bot (You can merge these), those nixpkgs is past
// (Can be closed), each hideable in this browser until it changes; and the
// page of every maintainer. What they need of the page comes as arguments:
// the loader of the merge bot's PRs (app.js's loadMerge), the pager.

import { html, maintainerMatches, prPrint, raw } from './logic.js';
import { remember, stored } from './prefs.js';
import { searchText } from './search.js';
import { maintainerHref, scopeHref, state, teamName } from './state.js';
import { store } from './store.js';
import { fmt } from './ui.js';

// Its own state: every one shown in You can merge these (mergeAll) or Can
// be closed (closeAll), not their first few; the PRs hidden here shown too
// (showHiddenPrs). app.js's buttons switch them.
export const maintainerView = { mergeAll: false, closeAll: false, showHiddenPrs: false };

// "You can merge these"'s Hide, as the packages': in this browser only,
// each hidden PR by number with what it was then (prPrint), back as soon as
// that differs. Entries for PRs no longer in the list are dropped once it's
// in (loadMerge).
export const HIDDEN_PRS_KEY = 'nixkeeper-hidden-prs';

export const hiddenPrPrints = (() => {
  try {
    return JSON.parse(stored(HIDDEN_PRS_KEY) || '{}') || {};
  } catch {
    return {};
  }
})();

export const isPrHidden = (pr) => hiddenPrPrints[pr.number] === prPrint(pr);

export function saveHiddenPrs() {
  remember(
    HIDDEN_PRS_KEY,
    Object.keys(hiddenPrPrints).length ? JSON.stringify(hiddenPrPrints) : '',
  );
}

// views/merge.json: the PRs maintainers can merge now with the merge bot
// (nixkeeper/sources/prs_digest.py: mergeable), for "You can merge these" in
// a maintainer's or team's view. Loaded once, when one is first shown.
export const MERGE_SHOWN = 5;

export const MERGE_COMMAND = '@NixOS/nixpkgs-merge-bot merge';

// "You can merge these": in @handle's view, the PRs they can merge (their
// own first); in a team's, those touching the packages nixpkgs lists under
// the team (meta.teams: its members are their maintainers, so the merge bot
// counts them), not those a list of the same name adds (teamsByList: their
// own maintainers merge those), with who can. Nothing when there are none,
// or before views/merge.json is in.
export function mergeHtml(path, handle, loadMerge) {
  const mine = path.startsWith('views/maintainer/') && handle && handle !== 'none';
  const team = path.startsWith('views/team/');
  if (!mine && !team) return '';
  if (!store.mergeList) {
    loadMerge();
    return '';
  }
  const who = handle.toLowerCase();
  const theirs = team && teamName();
  const mergers = team
    ? new Set(store.packages.filter((p) => !p.teamsByList?.includes(theirs)).map((p) => p.name))
    : null;
  const own = (p) => mine && p.author.toLowerCase() === who;
  // Their own first, then those for a vulnerable package, then the
  // longest waiting (the list's own order).
  const prs = store.mergeList
    .filter((p) =>
      mine ? p.who.some((w) => w.toLowerCase() === who) : p.packages.some((n) => mergers.has(n)),
    )
    .sort((a, b) => own(b) - own(a) || Boolean(b.vulnerable) - Boolean(a.vulnerable));
  if (!prs.length) return '';
  // Those hidden here (Hide), left out unless shown again, greyed.
  const hiddenN = prs.filter(isPrHidden).length;
  const listed = maintainerView.showHiddenPrs ? prs : prs.filter((p) => !isPrHidden(p));
  const hiddenToggle = hiddenN
    ? html`<button type="button" class="merge-hidden-toggle" aria-pressed="${maintainerView.showHiddenPrs}" title="PRs you hid here, in this browser, until they change (a newer version, or a CVE)">${fmt(hiddenN)} hidden · ${maintainerView.showHiddenPrs ? 'hide them' : 'show them'}</button>`
    : '';
  if (!listed.length)
    return html`<section class="merge-block merge-all-hidden"><p class="merge-how">You've hidden ${hiddenN === 1 ? 'the PR' : html`the ${fmt(hiddenN)} PRs`} ready to merge here. ${hiddenToggle}</p></section>`;
  const shown = maintainerView.mergeAll ? listed : listed.slice(0, MERGE_SHOWN);
  const days = (iso) => Math.max(0, Math.floor((Date.now() - new Date(iso)) / 86400000));
  const waited = (iso) => {
    const d = days(iso);
    return d < 1 ? 'opened today' : `waiting ${d} day${d === 1 ? '' : 's'}`;
  };
  const people = (list) => list.map((h) => `@${h}`).join(', ');
  const line = (p) => {
    const facts = [
      own(p) ? html`<b>your own PR</b>` : `by @${p.author}`,
      html`<span title="Opened ${new Date(p.created).toLocaleDateString()}">${waited(p.created)}</span>`,
      p.base !== 'master' && html`into <span class="mono">${p.base}</span>`,
      p.approvedBy?.length && `approved by ${people(p.approvedBy)}`,
      p.vulnerable &&
        html`<span class="merge-warn" title="The package counts as vulnerable: worth reviewing this first">for a vulnerable package</span>`,
      p.behind &&
        html`<span class="merge-warn" title="Merged as it is, the package would still be outdated: worth updating the PR first">behind: upstream has ${p.behind}</span>`,
      team && `${people(p.who)} can merge it`,
    ].filter(Boolean);
    const hidden = isPrHidden(p);
    return html`<li${hidden ? raw(' class="is-hidden"') : ''}><a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${p.number}" target="_blank" rel="noopener">${p.title}</a> <span class="merge-n">#${p.number}</span><button type="button" class="merge-hide" data-pr="${p.number}" title="${hidden ? 'Shown again here' : 'Leave it out of this list, in this browser only, until it changes: a newer version in its title, or a CVE'}">${hidden ? 'Show it again' : 'Hide'}</button><span class="merge-facts">${facts.map((f, i) => html`${i ? ' · ' : ''}${f}`)}</span></li>`;
  };
  const n = listed.length;
  const what = mine
    ? html`You can merge ${n === 1 ? 'this PR' : html`these ${fmt(n)} PRs`}`
    : html`${fmt(n)} PR${n === 1 ? '' : 's'} on the team's packages, ready to merge`;
  // The merge bot also asks that whoever comments be in
  // @NixOS/nixpkgs-maintainers (nixpkgs' ci/README.md): not public, so said.
  const why = mine
    ? 'CI passed, and you maintain every package it touches: if you’re in @NixOS/nixpkgs-maintainers, the merge bot merges it for you'
    : 'CI passed, and the people named under each maintain every package it touches: the merge bot merges it for any of them in @NixOS/nixpkgs-maintainers';
  const more =
    listed.length > MERGE_SHOWN
      ? html`<button type="button" class="merge-more">${maintainerView.mergeAll ? 'Show fewer' : `Show all ${fmt(listed.length)}`}</button>`
      : '';
  return html`<section class="merge-block" aria-labelledby="mergeHead">
    <h3 id="mergeHead">${what} <span class="scope-hint">${why}</span> ${hiddenToggle}</h3>
    <ul class="merge-list">${shown.map(line)}</ul>
    ${more}
    <p class="merge-how">Review it, then comment on the PR: <code>${MERGE_COMMAND}</code>
      <button type="button" class="merge-copy" data-copy="${MERGE_COMMAND}" title="Copy the comment">Copy</button>
      <a class="files-link" href="https://github.com/NixOS/nixpkgs/blob/master/ci/README.md" target="_blank" rel="noopener">how the merge bot works ↗</a></p>
  </section>`;
}

// On a maintainer's or a team's page: the open update PRs nixpkgs is
// already past, on its packages (the rows' supersededPRs): "Can be closed".
// Hide as for "You can merge these" (in this browser, until it changes).
export const CLOSE_SHOWN = 5;

export function closeHtml(path, handle) {
  const mine = path.startsWith('views/maintainer/') && handle && handle !== 'none';
  const team = path.startsWith('views/team/');
  if (!mine && !team) return '';
  const who = (handle || '').toLowerCase();
  const theirs = team && teamName();
  const seen = new Set();
  const prs = store.packages
    .filter((p) => !team || !p.teamsByList?.includes(theirs))
    .flatMap((p) => (p.supersededPRs || []).map((pr) => ({ ...pr, pkg: p.name })))
    .filter((pr) => !seen.has(pr.number) && seen.add(pr.number))
    .sort((a, b) => (a.created < b.created ? -1 : a.created > b.created ? 1 : 0));
  if (!prs.length) return '';
  const hiddenN = prs.filter(isPrHidden).length;
  const listed = maintainerView.showHiddenPrs ? prs : prs.filter((p) => !isPrHidden(p));
  if (!listed.length) return '';
  const shown = maintainerView.closeAll ? listed : listed.slice(0, CLOSE_SHOWN);
  const days = (iso) => Math.max(0, Math.floor((Date.now() - new Date(iso)) / 86400000));
  const line = (p) => {
    const own = mine && p.author.toLowerCase() === who;
    const facts = [
      own ? html`<b>your own PR</b>` : `by @${p.author}`,
      html`<span title="Opened ${new Date(p.created).toLocaleDateString()}">open ${fmt(days(p.created))} days</span>`,
      p.init
        ? html`nixpkgs has it now (<span class="mono">${p.now}</span>), added another way`
        : html`nixpkgs has <span class="mono">${p.now}</span>`,
      p.draft && 'a draft',
    ].filter(Boolean);
    const hidden = isPrHidden(p);
    return html`<li${hidden ? raw(' class="is-hidden"') : ''}><a class="files-link" href="https://github.com/NixOS/nixpkgs/pull/${p.number}" target="_blank" rel="noopener">${p.title}</a> <span class="merge-n">#${p.number}</span><button type="button" class="merge-hide" data-pr="${p.number}" title="${hidden ? 'Shown again here' : 'Leave it out of this list, in this browser only, until it changes'}">${hidden ? 'Show it again' : 'Hide'}</button><span class="merge-facts">${facts.map((f, i) => html`${i ? ' · ' : ''}${f}`)}</span></li>`;
  };
  const n = listed.length;
  // Init PRs for a package nixpkgs has now among them (prs_digest.mark_superseded).
  const inits = listed.filter((p) => p.init).length;
  const kind = !inits ? 'update PR' : inits === n ? 'init PR' : 'PR';
  const why = !inits
    ? 'nixpkgs already has their version or a newer one'
    : inits === n
      ? 'nixpkgs has the package they add now'
      : 'nixpkgs already has their version or a newer one, or the package they add';
  const more =
    listed.length > CLOSE_SHOWN
      ? html`<button type="button" class="merge-more" data-close-more>${maintainerView.closeAll ? 'Show fewer' : `Show all ${fmt(listed.length)}`}</button>`
      : '';
  return html`<section class="merge-block close-block" aria-labelledby="closeHead">
    <h3 id="closeHead">${n === 1 ? `This ${kind} can` : html`These ${fmt(n)} ${kind}s can`} be closed <span class="scope-hint">${why}${hiddenN && !maintainerView.showHiddenPrs ? html` · ${fmt(hiddenN)} hidden` : ''}</span></h3>
    <ul class="merge-list">${shown.map(line)}</ul>
    ${more}
    <p class="merge-how">${
      !inits
        ? 'Close it with a word on why (nixpkgs has a newer version), or update it to the newest.'
        : inits === n
          ? "Close it with a word on why (nixpkgs has the package now), or turn it into an update of nixpkgs' package."
          : 'Close it with a word on why (nixpkgs has a newer version, or has the package now), or update it to the newest.'
    }${
      store.community && store.manifest.views?.superseded
        ? html` <a class="files-link" href="${scopeHref({ view: 'superseded' })}" data-card-view="superseded">All ${fmt(store.manifest.views.superseded)} packages with one, in all of nixpkgs →</a>`
        : ''
    }</p>
  </section>`;
}

// One maintainer: their handle (opening their packages) and counts.
export function maintainerItem([handle, count, outdated, failing]) {
  return html`<li><a class="files-link" href="${maintainerHref(handle)}" data-maintainer="${handle}">@${handle}</a><span class="maint-n">${fmt(count)} ${count === 1 ? 'package' : 'packages'}${outdated ? html` · <span class="warn-text">${fmt(outdated)} outdated</span>` : ''}${failing ? html` · <span class="danger-text">${fmt(failing)} failing</span>` : ''}</span></li>`;
}

// ?view=maintainers: every maintainer, by handle, a page at a time; the
// search narrows them (an @ in front or not).
export function maintainersHtml(pagerHtml) {
  if (!store.maintainersList) return html`<div class="empty">Loading the maintainers…</div>`;
  const query = searchText().trim();
  const list = query
    ? maintainerMatches(store.maintainersList, query, Infinity).found
    : store.maintainersList;
  if (!list.length) return html`<div class="empty">No maintainer matches “${query}”.</div>`;
  const pages = Math.max(1, Math.ceil(list.length / state.pageSize));
  state.pageNum = Math.min(state.pageNum, pages);
  const page = list.slice((state.pageNum - 1) * state.pageSize, state.pageNum * state.pageSize);
  return html`<ul class="maint-list maint-page">${page.map(maintainerItem)}</ul>${pagerHtml(list.length, pages)}`;
}

// Its controls, once. page: what they need of the page (app.js's
// pageHooks).
export function wireMaintainerView(page) {
  // You can merge these and Can be closed: the merge bot's command copied, a
  // PR hidden or shown again, the hidden ones shown, every one shown.
  document.getElementById('scope')?.addEventListener('click', (e) => {
    const copy = e.target.closest('button.merge-copy');
    if (copy) {
      page.copyTitle(copy);
      return;
    }
    const hidePr = e.target.closest('button.merge-hide');
    if (hidePr) {
      const number = Number(hidePr.dataset.pr);
      const pr = (store.mergeList || []).find((p) => p.number === number);
      if (pr) page.setPrHidden(number, !isPrHidden(pr));
      return;
    }
    if (e.target.closest('button.merge-hidden-toggle')) {
      maintainerView.showHiddenPrs = !maintainerView.showHiddenPrs;
      page.renderScope();
      return;
    }
    if (e.target.closest('button[data-close-more]')) {
      maintainerView.closeAll = !maintainerView.closeAll;
      page.renderScope();
      return;
    }
    if (e.target.closest('button.merge-more')) {
      maintainerView.mergeAll = !maintainerView.mergeAll;
      page.renderScope();
      return;
    }
  });
}
