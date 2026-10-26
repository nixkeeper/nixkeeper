// HTML from data, escaped, and how the page writes it (page/markup.js). Run: node --test tests/js/
// (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  appendHtml,
  capitalized,
  escapeHtml,
  html,
  raw,
  safeUrl,
  setHtml,
  withoutLeadingJoiner,
} from '../../page/markup.js';

describe('links and markup from data', () => {
  test('escapeHtml', () => {
    assert.equal(
      escapeHtml(`<a href="x">'&'</a>`),
      '&lt;a href=&quot;x&quot;&gt;&#39;&amp;&#39;&lt;/a&gt;',
    );
    assert.equal(escapeHtml(null), '');
    assert.equal(escapeHtml(42), '42');
  });
  test('only web addresses are links', () => {
    assert.equal(
      safeUrl('https://github.com/NixOS/nixpkgs/pull/1'),
      'https://github.com/NixOS/nixpkgs/pull/1',
    );
    assert.equal(safeUrl('http://example.org/'), 'http://example.org/');
    assert.equal(safeUrl('javascript:alert(1)'), '');
    assert.equal(safeUrl('JavaScript:alert(1)'), '');
    assert.equal(safeUrl('data:text/html,<script>'), '');
    assert.equal(safeUrl('not a url'), '');
    assert.equal(safeUrl(undefined), '');
  });
  test('html escapes everything put in it', () => {
    const title = `<img src=x onerror="alert(1)">'&'`;
    assert.equal(
      String(html`<b title="${title}">${title}</b>`),
      '<b title="&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&#39;&amp;&#39;">' +
        '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;&#39;&amp;&#39;</b>',
    );
    // Links: safeUrl, then escaped like the rest.
    assert.equal(
      String(html`<a href="${safeUrl('https://example.org/?a="b"&c')}">`),
      '<a href="https://example.org/?a=&quot;b&quot;&amp;c">',
    );
  });
  test('html keeps markup made with html or raw', () => {
    const name = '<i>x</i>';
    const inner = html`<i>${name}</i>`;
    assert.equal(String(html`<b>${inner}</b>`), '<b><i>&lt;i&gt;x&lt;/i&gt;</i></b>');
    assert.equal(String(html`${raw('<br>')}`), '<br>');
  });
  test('html joins arrays, and leaves out null and undefined only', () => {
    assert.equal(String(html`${['<a>', html`<b>`]}`), '&lt;a&gt;<b>');
    assert.equal(String(html`${null}${undefined}|${0}|${false}`), '|0|false');
  });
  test('capitalized escapes text, and keeps markup made with html', () => {
    // A plain string from the data is escaped, whatever it holds.
    assert.equal(String(capitalized('failed: <img src=x>')), 'Failed: &lt;img src=x&gt;');
    assert.equal(String(html`<p>${capitalized('<b>x</b>')}</p>`), '<p>&lt;b&gt;x&lt;/b&gt;</p>');
    // Markup's own tags are passed over: no "&lt;span" (the old display bug).
    assert.equal(
      String(capitalized(html`<span class="mono">failed</span> trying`)),
      '<span class="mono">Failed</span> trying',
    );
    assert.equal(String(capitalized(html`opened ${'<x>'}`)), 'Opened &lt;x&gt;');
    // Nothing to capitalize: as it was.
    assert.equal(String(capitalized('1.2 is out')), '1.2 is out');
    assert.equal(String(capitalized('Already')), 'Already');
    assert.equal(String(capitalized(null)), '');
  });
  test('capitalized passes over quoted ">", knows any letter, and leaves what it must', () => {
    // A tag whose attribute holds a ">": the letter after the tag.
    assert.equal(
      String(capitalized(html`<span title="${'a>b'}">x</span>`)),
      '<span title="a&gt;b">X</span>',
    );
    assert.equal(
      String(capitalized(raw('<span title="a>b">x</span>'))),
      '<span title="a>b">X</span>',
    );
    // Text starting with a space is a sentence's tail: left as it is.
    assert.equal(String(capitalized(' then failed')), ' then failed');
    // The project's name stays lowercase, as its brand guide says.
    assert.equal(String(capitalized('nixkeeper found it')), 'nixkeeper found it');
    assert.equal(String(capitalized(html`<b>nixkeeper</b> found`)), '<b>nixkeeper</b> found');
    // Letters beyond a to z.
    assert.equal(String(capitalized('über')), 'Über');
  });
  test('withoutLeadingJoiner takes the joining punctuation off, still escaped', () => {
    assert.equal(String(withoutLeadingJoiner(' — <b>x</b>')), '&lt;b&gt;x&lt;/b&gt;');
    assert.equal(String(withoutLeadingJoiner(html`, but <i>${'<y>'}</i>`)), 'but <i>&lt;y&gt;</i>');
    assert.equal(String(withoutLeadingJoiner('no joiner')), 'no joiner');
  });
  test('capitalized leaves the lowercase names, as whole words only', () => {
    assert.equal(String(capitalized('nixkeeper found it')), 'nixkeeper found it');
    assert.equal(String(capitalized('nixkeeperish')), 'Nixkeeperish');
    // nixpkgs' names too, as the page's own sentences write them.
    assert.equal(String(capitalized("nixpkgs won't build it")), 'nixpkgs won&#39;t build it');
    assert.equal(String(capitalized('nixpkgs-update tried')), 'nixpkgs-update tried');
    assert.equal(String(capitalized('r-ryantm opened it')), 'r-ryantm opened it');
    assert.equal(String(capitalized('nixpkgsfoo')), 'Nixpkgsfoo');
  });
});

describe('setHtml and appendHtml', () => {
  // No DOM in Node: an element as far as they use one.
  const element = () => ({
    innerHTML: '',
    insertAdjacentHTML(where, text) {
      assert.equal(where, 'beforeend');
      this.innerHTML += text;
    },
  });

  test('only markup html`` or raw() made', () => {
    const el = element();
    assert.throws(() => setHtml(el, '<b>bold</b>'), TypeError);
    assert.throws(() => appendHtml(el, '<b>bold</b>'), TypeError);
    assert.equal(el.innerHTML, '');
  });

  test('what html escaped, as it escaped it', () => {
    const el = element();
    setHtml(el, html`<b>${'<script>alert(1)</script>'}</b>`);
    assert.equal(el.innerHTML, '<b>&lt;script&gt;alert(1)&lt;/script&gt;</b>');
    appendHtml(el, raw('<i>more</i>'));
    assert.equal(el.innerHTML, '<b>&lt;script&gt;alert(1)&lt;/script&gt;</b><i>more</i>');
    setHtml(el, html``);
    assert.equal(el.innerHTML, '');
  });
});
