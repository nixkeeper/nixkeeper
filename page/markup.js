// Markup from data, escaped: the html`` tag, raw() for the page's own
// markup, and setHtml and appendHtml, the only way the page writes markup
// into an element. Imports nothing: tests load it without a browser.

export function escapeHtml(s) {
  return (s || '')
    .toString()
    .replace(
      /[&<>"']/g,
      (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
    );
}

// A link from data, only if it's a web address: escaping stops markup, but
// not a javascript: link, which would run when clicked. '' otherwise.
export function safeUrl(url) {
  try {
    const { protocol } = new URL(url);
    return protocol === 'https:' || protocol === 'http:' ? url : '';
  } catch {
    return '';
  }
}

// Markup, built with the html`...` tag: every ${...} in it is escaped,
// unless it's markup itself (another html`...`, or raw() for markup the page
// writes itself), so text from the data can't add markup, even where an
// escape would have been forgotten. Arrays are joined; null and undefined
// give nothing (and the rest prints as in a template string: false as
// "false", for aria-pressed). It's written into an element through setHtml
// or appendHtml.
class Markup {
  constructor(text) {
    this.text = text;
  }
  toString() {
    return this.text;
  }
}
const piece = (v) =>
  v instanceof Markup
    ? v.text
    : Array.isArray(v)
      ? v.map(piece).join('')
      : v == null
        ? ''
        : escapeHtml(String(v));
export function html(strings, ...values) {
  return new Markup(strings.reduce((out, s, i) => out + piece(values[i - 1]) + s));
}
// Markup the page writes itself, as is. Never for text from the data.
export const raw = (text) => new Markup(String(text));
// No markup at all: what a part of the page that has nothing to show gives.
export const NO_MARKUP = raw('');

// The one way the page writes markup: only what html`` or raw() made, so
// text from the data is always escaped. A Biome plugin
// (biome-plugins/no-raw-html.grit) keeps innerHTML and its kin to this file.
export function setHtml(el, markup) {
  if (!(markup instanceof Markup)) throw new TypeError('setHtml needs html`` or raw()');
  el.innerHTML = markup.text;
}

// The same, appended after el's children (the list's rows past the first
// page).
export function appendHtml(el, markup) {
  if (!(markup instanceof Markup)) throw new TypeError('appendHtml needs html`` or raw()');
  el.insertAdjacentHTML('beforeend', markup.text);
}

// A value as markup: an html template's kept as it is, anything else
// escaped as html would.
const asMarkup = (value) => (value instanceof Markup ? value : html`${value}`);

// What capitalized passes over before the first letter: tags (a quoted
// attribute value may hold a ">"). Any lowercase letter, not only a to z.
// Whitespace isn't passed over: a text starting with a space is a tail of
// a sentence ("... nixkeeper's update check found"), not its start.
const BEFORE_FIRST_LETTER = /^((?:<(?:[^>"]|"[^"]*")*>)*)(\p{Ll})/u;
// Names that stay lowercase even at a sentence's start, as their projects
// write them: nixkeeper (assets/brand/BRAND.md), nixpkgs, and its update
// bot's. The page's own sentences already start "nixpkgs-update hasn't
// tried..." (package-view.js). Whole words only: \b keeps "nixpkgsfoo" out.
// nixpkgs-update is listed though "nixpkgs" would match it already ("-"
// ends a word), so the list says what it covers.
const LOWERCASE_NAMES = /^(nixkeeper|nixpkgs|nixpkgs-update|r-ryantm)\b/;

// Text with its first letter capitalized, as markup that's safe to show.
// Tags at the start are passed over, so "<span>failed</span>" becomes
// "<span>Failed</span>". A sentence starting with one of LOWERCASE_NAMES
// is left as it is.
export function capitalized(value) {
  const markup = asMarkup(value).text;
  return new Markup(
    markup.replace(BEFORE_FIRST_LETTER, (match, before, letter) =>
      LOWERCASE_NAMES.test(markup.slice(before.length)) ? match : before + letter.toUpperCase(),
    ),
  );
}

// The joining punctuation ("— ", ", ", "; ") a sentence's tail starts with.
const LEADING_JOINER = /^\s*(—|,|;)\s*/;

// A sentence's tail with its joining punctuation taken off, so it stands
// as a sentence of its own, as markup that's safe to show. The text is
// escaped first; only punctuation and spaces are taken off, never markup.
export function withoutLeadingJoiner(value) {
  return new Markup(asMarkup(value).text.replace(LEADING_JOINER, ''));
}
