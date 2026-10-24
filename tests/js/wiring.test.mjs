// The views' controls (wireOverview, wireMaintainerView): each button
// changes its view's state and draws the page again, through the page's
// hooks. On stand-in elements: a click is a target with what it's inside.
// Run: node --test tests/js/ (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { beforeEach, describe, test } from 'node:test';

// The page's elements by id, and the document: each keeps its listeners.
const listening = () => {
  const handlers = {};
  return {
    handlers,
    addEventListener: (type, fn) => {
      handlers[type] = [...(handlers[type] || []), fn];
    },
  };
};
const elements = {};
globalThis.document = Object.assign(listening(), {
  getElementById: (id) => {
    if (!elements[id]) elements[id] = listening();
    return elements[id];
  },
});
globalThis.location = { pathname: '/', search: '', href: 'https://nixkeeper.test/' };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { highlightShown, wireOverview } = await import('../../page/overview.js');
const { maintainerView, wireMaintainerView } = await import('../../page/maintainer-view.js');

// A click on a button matching selector (and its data), in the scope.
const click = async (selector, dataset = {}) => {
  const target = { dataset, closest: (s) => (s.split(', ').includes(selector) ? target : null) };
  for (const fn of elements.scope.handlers.click || []) await fn({ target });
};

const drawn = [];
const page = { renderScope: () => drawn.push('scope'), copyTitle: () => {}, setPrHidden: () => {} };
wireOverview(page);
wireMaintainerView(page);
beforeEach(() => {
  drawn.length = 0;
});

describe('the overview', () => {
  test('a list switched to its longest-standing, and drawn again', async () => {
    await click('button.hl-mode', { hl: 'failing', mode: 'oldest' });
    assert.equal(highlightShown.failing, 'oldest');
    assert.deepEqual(drawn, ['scope']);
  });
});

describe("a maintainer's page", () => {
  test('every PR shown, then the first few again', async () => {
    await click('button.merge-more');
    assert.equal(maintainerView.mergeAll, true);
    await click('button.merge-more');
    assert.equal(maintainerView.mergeAll, false);
    assert.deepEqual(drawn, ['scope', 'scope']);
  });
  test("Can be closed's every one, and the hidden ones shown", async () => {
    await click('button[data-close-more]');
    await click('button.merge-hidden-toggle');
    assert.equal(maintainerView.closeAll, true);
    assert.equal(maintainerView.showHiddenPrs, true);
  });
  test("another view's button changes nothing here", async () => {
    await click('button.tile', { filter: 'warn' });
    assert.deepEqual(drawn, []);
  });
});
