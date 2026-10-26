// Vulnerabilities (page/vulns.js). Run: node --test tests/js/
// (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  cvePieces,
  isVulnerable,
  severityRank,
  vulnSources,
  vulnSummary,
} from '../../page/vulns.js';

describe('isVulnerable and cvePieces', () => {
  test("Repology's flag or nixpkgs' mark", () => {
    assert.equal(isVulnerable({ nixVulnerable: true }), true);
    assert.equal(isVulnerable({ markedInsecure: ['EOL'] }), true);
    assert.equal(isVulnerable({ markedInsecure: [] }), false);
    assert.equal(isVulnerable({}), false);
  });
  test('the CVE ids in a reason, apart to link', () => {
    assert.deepEqual(cvePieces('CVE-2018-19655'), [{ cve: 'CVE-2018-19655' }]);
    assert.deepEqual(cvePieces('CVE-2026-34400: SQL injection, fixed in 9.1.0'), [
      { cve: 'CVE-2026-34400' },
      { text: ': SQL injection, fixed in 9.1.0' },
    ]);
    assert.deepEqual(cvePieces('Uses Electron 39, EOL'), [{ text: 'Uses Electron 39, EOL' }]);
  });
});

describe("nixkeeper-vulnerabilities' verdict", () => {
  test("the sync's, when there is one", () => {
    // null: the digest had entries, none counted, nor Repology nor nixpkgs.
    assert.equal(isVulnerable({ vuln: null, nixVulnerable: false }), false);
    assert.equal(isVulnerable({ vuln: { n: 1, by: ['tracker'] } }), true);
    // No "vuln" (data from before, or nothing on it): as before.
    assert.equal(isVulnerable({ nixVulnerable: true }), true);
  });
  test("from a full row's vulnerabilities, as the sync's summary", () => {
    const row = {
      nixVulnerable: true,
      vulnerabilities: [
        { verdict: 'fixed', source: 'tracker', severity: 'critical' },
        { verdict: 'osv', source: 'osv', severity: 'moderate' },
        { verdict: 'affected', source: 'tracker', severity: 'high' },
      ],
    };
    assert.deepEqual(vulnSummary(row), {
      n: 2,
      severity: 'high',
      by: ['osv', 'tracker', 'repology'],
    });
    assert.equal(isVulnerable(row), true);
    const none = { vulnerabilities: [{ verdict: 'fixed', source: 'tracker' }] };
    assert.equal(vulnSummary(none), null);
    assert.equal(isVulnerable(none), false);
  });
  test('worst severity first, unknown last', () => {
    const order = [{}, { vuln: { severity: 'low' } }, { vuln: { severity: 'critical' } }].map((p) =>
      severityRank(p),
    );
    assert.deepEqual(order, [5, 4, 0]);
  });
  test('who says so', () => {
    assert.deepEqual(vulnSources({ vuln: { by: ['tracker', 'repology'] } }), [
      'the NixOS security tracker',
      'Repology',
    ]);
    assert.deepEqual(vulnSources({ nixVulnerable: true, markedInsecure: ['x'] }), [
      'nixpkgs (marked insecure)',
      'Repology',
    ]);
  });
});
