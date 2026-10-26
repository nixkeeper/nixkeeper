// Palettes and the tab icon (page/palette.js). Run: node --test tests/js/
// (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { faviconKey, themeFor } from '../../page/palette.js';
import { outdated, pkg } from './helpers.mjs';

describe('faviconKey', () => {
  test('all good', () => {
    assert.equal(faviconKey([]), 'ok');
    assert.equal(faviconKey([pkg(), pkg({ nixStatus: 'rolling' })]), 'ok');
  });
  test('each signal lights its own chevron, in r, f, v order', () => {
    assert.equal(faviconKey([outdated()]), 'r');
    assert.equal(faviconKey([pkg({ updateFailure: {} })]), 'f');
    assert.equal(faviconKey([pkg({ nixVulnerable: true })]), 'v');
    assert.equal(
      faviconKey([pkg({ nixVulnerable: true }), pkg({ updateFailure: {} }), outdated()]),
      'rfv',
    );
    assert.equal(faviconKey([outdated({ nixVulnerable: true })]), 'rv');
  });
  test('marked insecure by nixpkgs lights the vulnerable one too', () => {
    assert.equal(faviconKey([pkg({ markedInsecure: ['CVE-2020-25031'] })]), 'v');
  });
  test("an update already on master isn't a new release to act on", () => {
    assert.equal(faviconKey([outdated({ master: '1.1' })]), 'ok');
  });
  test('failures follow the platform filter', () => {
    const failsOnLinux = pkg({ builds: [{ system: 'x86_64-linux', status: 'failed' }] });
    assert.equal(faviconKey([failsOnLinux]), 'f');
    assert.equal(faviconKey([failsOnLinux], 'darwin'), 'ok');
  });
});

describe('themeFor', () => {
  test('nothing chosen: classic, following the system', () => {
    assert.deepEqual(themeFor(), { palette: 'classic', mode: 'auto' });
    assert.deepEqual(themeFor({ palette: null, mode: null }, null), {
      palette: 'classic',
      mode: 'auto',
    });
  });
  test("the page's default, when the visitor hasn't chosen", () => {
    assert.deepEqual(themeFor({}, 'catppuccin'), { palette: 'catppuccin', mode: 'auto' });
  });
  test("the visitor's choice wins over the page's default", () => {
    assert.deepEqual(themeFor({ palette: 'classic', mode: 'dark' }, 'catppuccin'), {
      palette: 'classic',
      mode: 'dark',
    });
  });
  test('unknown values count as not set', () => {
    assert.deepEqual(themeFor({ palette: 'solarized', mode: 'dim' }, 'catppuccin'), {
      palette: 'catppuccin',
      mode: 'auto',
    });
    assert.deepEqual(themeFor({}, 'nord'), { palette: 'classic', mode: 'auto' });
  });
});
