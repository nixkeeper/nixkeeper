// The search box as a query (page/search.js): read into the state's
// fields, written back, both ways. Run: node --test tests/js/ (part of `nix
// flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

globalThis.document = { getElementById: () => ({ value: '' }) };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { KNOWN } = await import('../../page/filters.js');
const { parseQuery, queryFields, writeQuery } = await import('../../page/search.js');
const { readState } = await import('../../page/state.js');

// A query's state: what it sets, the rest as when it says nothing.
const stateOf = (query) => queryFields(parseQuery(query, KNOWN).fields);

describe('parseQuery', () => {
  test('a tile, refines, an age, a platform, beside a name', () => {
    const { fields, text, problems } = parseQuery(
      'is:builds -is:broken has:pr age:1y on:macos wine',
      KNOWN,
    );
    assert.equal(text, 'wine');
    assert.deepEqual(problems, []);
    assert.equal(fields.activeFilter, 'builds');
    assert.deepEqual([...fields.refines], ['notbroken', 'withpr']);
    assert.equal(fields.ageFilter, '1y');
    assert.equal(fields.platformFilter, 'darwin'); // on:macos, its other name
  });
  test("people: a team, teams and maintainers left out, the list's own maintainer", () => {
    const { fields, text } = parseQuery(
      '@GaetanLepage -maintainer:natsukium team:gaming -team:"Security review" by:@Alice',
      KNOWN,
    );
    assert.equal(text, '@GaetanLepage');
    assert.equal(fields.teamFilter, 'gaming');
    assert.deepEqual(fields.teamsLeftOut, ['Security review']);
    assert.deepEqual(fields.maintainersLeftOut, ['natsukium']);
    assert.equal(fields.byFilter, 'alice');
  });
  test('the search across nixpkgs: status and ofteam, apart from is and team', () => {
    const { fields } = parseQuery('python3 status:outdated ofteam:"Security review"', KNOWN);
    assert.equal(fields.statusFilter, 'outdated');
    assert.equal(fields.matchTeam, 'Security review');
    assert.equal(fields.activeFilter, undefined);
  });
  test('problems shown, with what was likely meant, not guessed', () => {
    const { fields, problems } = parseQuery('is:biulds on:darwn colour:red sort:oldest', KNOWN);
    assert.deepEqual(
      problems.map((p) => [p.token, p.suggestion]),
      [
        ['is:biulds', 'is:builds'],
        ['on:darwn', 'darwin'],
        ['colour:red', undefined],
      ],
    );
    assert.equal(fields.activeFilter, undefined);
    assert.equal(fields.sortMode, 'oldest');
  });
});

describe('writeQuery', () => {
  test('a query written back as it was read', () => {
    for (const query of [
      '',
      'wine',
      'is:builds on:darwin',
      'is:outdated -is:broken has:pr has:newer age:1y on:x86_64-linux in:python313Packages',
      'team:gaming -team:"Security review" -maintainer:bob @alice',
      'is:updates update:patch build:compile by:carol sort:oldest order:reverse',
      'status:vulnerable ofteam:Python python3',
    ])
      assert.equal(writeQuery(stateOf(query), parseQuery(query, KNOWN).text, KNOWN), query);
  });
  test("an address's filters as a query, and that query as the same filters", () => {
    const address =
      '?filter=builds&platform=darwin&refine=withpr,notbroken&age=1y&team=gaming,-geospatial&sort=oldest&order=reverse&q=wine';
    const { state: read, query: text } = readState(new URLSearchParams(address), KNOWN);
    const query = writeQuery(read, text, KNOWN);
    assert.equal(
      query,
      'is:builds -is:broken has:pr age:1y on:darwin team:gaming -team:geospatial sort:oldest order:reverse wine',
    );
    const again = stateOf(query);
    for (const field of [
      'activeFilter',
      'platformFilter',
      'ageFilter',
      'teamFilter',
      'sortMode',
      'sortReverse',
    ])
      assert.deepEqual(again[field], read[field], field);
    assert.deepEqual([...again.refines].sort(), [...read.refines].sort());
    assert.deepEqual(again.teamsLeftOut, read.teamsLeftOut);
  });
  test('a query saying nothing of a field leaves it as when nothing is picked', () => {
    const st = stateOf('wine');
    assert.equal(st.activeFilter, 'all');
    assert.equal(st.refines.size, 0);
    assert.equal(st.sortMode, 'pressing');
  });
});
