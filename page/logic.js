// The page's rules, without the page: statuses, versions, ages, links and the
// tab icon's signals, from a package's data alone. app.js draws the page with
// them; tests/js/ tests them (node --test, in the flake checks).
//
// Where a rule depends on the selected platform, it takes it as an argument
// (null for all platforms, or 'linux', 'darwin'); times take `now` so tests
// can fix it.

import { computeStatus, hasFailure, waitingForChannel } from './status.js';
import { isVulnerable } from './vulns.js';

// The tab's icon among packages: each signal turns its own chevron of the
// mark (assets/brand/BRAND.md, "Status icon"): r, a new release nothing has
// been done about yet (not already on master); f, a failure; v, a
// vulnerability. "rfv" order, or "ok" with none: favicon-<key>.svg.
export function faviconKey(packages, platform = null) {
  const signals = {
    r: packages.some((p) => computeStatus(p) === 'warn' && !waitingForChannel(p)),
    f: packages.some((p) => hasFailure(p, platform)),
    v: packages.some(isVulnerable),
  };
  return ['r', 'f', 'v'].filter((s) => signals[s]).join('') || 'ok';
}

// The page's look: a palette and light or dark. The visitor's choice (the
// Theme menu, kept in their browser) wins, then the page's default (the
// lists' page.theme, from the data), then classic; light or dark follows the
// system ('auto') unless chosen. Unknown values count as not set.
export const PALETTES = ['classic', 'catppuccin'];
export const MODES = ['auto', 'light', 'dark'];

export function themeFor(chosen = {}, siteDefault = null) {
  const palette = [chosen.palette, siteDefault].find((p) => PALETTES.includes(p)) || 'classic';
  const mode = MODES.includes(chosen.mode) ? chosen.mode : 'auto';
  return { palette, mode };
}
