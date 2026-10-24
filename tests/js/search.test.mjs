// The search box as a query (page/search.js): read into the state's
// fields, written back, both ways. Run: node --test tests/js/ (part of `nix
// flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

globalThis.document = { getElementById: () => ({ value: '' }) };
globalThis.localStorage = { getItem: () => null, setItem() {}, removeItem() {} };

const { KNOWN } = await import('../../page/filters.js');
const { matchNote, needsList, parseQuery, queryFields, suggest, writeQuery } = await import(
  '../../page/search.js'
);
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

describe('ofteam:', () => {
  const teams = { ...KNOWN, TEAMS: ['Python', 'Security review'] };
  test('a team as the data writes it, whatever the case', () => {
    assert.equal(parseQuery('ofteam:python', teams).fields.matchTeam, 'Python');
    assert.equal(parseQuery('ofteam:"security review"', teams).fields.matchTeam, 'Security review');
  });
  test('one the data has no team for, said with the closest', () => {
    const { fields, problems } = parseQuery('ofteam:pyton', teams);
    assert.equal(fields.matchTeam, undefined);
    assert.deepEqual(problems, [
      { token: 'ofteam:pyton', message: 'no ofteam:pyton', suggestion: 'ofteam:Python' },
    ]);
  });
  test('before the data says its teams, as typed', () => {
    assert.equal(parseQuery('ofteam:python').fields.matchTeam, 'python');
  });
});

describe('matchNote', () => {
  const st = (q) => queryFields(parseQuery(q).fields);
  test('status: or ofteam: with no name', () => {
    assert.equal(
      matchNote(st('ofteam:Python'), ''),
      'ofteam: narrows the matches in all of nixpkgs: add a name',
    );
    assert.equal(
      matchNote(st('status:outdated ofteam:Python'), '@fabaff'),
      'status: and ofteam: narrow the matches in all of nixpkgs: add a name',
    );
  });
  test('nothing with a name, or with neither word', () => {
    assert.equal(matchNote(st('ofteam:Python'), 'firefox'), null);
    assert.equal(matchNote(st('is:builds'), ''), null);
  });
});

describe('needsList', () => {
  const of = (q) => needsList(queryFields(parseQuery(q).fields));
  test('a word only a list reads', () => {
    for (const q of [
      'is:builds',
      '-has:maintainer',
      'age:1y',
      'build:compile',
      '-team:Gaming',
      'sort:oldest',
      'order:reverse',
    ])
      assert.equal(of(q), true, q);
  });
  test('a name, or words the matches read too', () => {
    for (const q of [
      '',
      'firefox',
      'status:outdated ofteam:Python',
      'on:darwin in:python313Packages',
      'by:fabaff',
      'team:Gaming',
    ])
      assert.equal(of(q), false, q);
  });
});

describe('suggest', () => {
  const values = {
    is: [
      { value: 'outdated', label: 'outdated', count: 120 },
      { value: 'builds', label: 'build failures', count: 33 },
      { value: 'broken', label: 'marked broken', count: 4 },
    ],
    team: [
      { value: 'Security review', count: 12 },
      { value: 'gaming', count: 40 },
    ],
  };
  const texts = (found) => found?.items.map((i) => i.text);
  test("a word's start: the qualifiers it begins", () => {
    assert.deepEqual(texts(suggest('wine o', 6, values)), ['on:', 'ofteam:', 'order:']);
    assert.equal(suggest('wine o', 6, values).start, 5);
    assert.deepEqual(texts(suggest('-t', 2, values)), ['-team:']);
  });
  test('after a qualifier: its values, by what they begin with or are called', () => {
    assert.deepEqual(texts(suggest('is:b', 4, values)), ['is:builds', 'is:broken']);
    assert.deepEqual(texts(suggest('is:fail', 7, values)), ['is:builds']); // "build failures"
    const found = suggest('is:', 3, values);
    assert.equal(found.items[0].count, 120);
    assert.equal(found.items[0].done, true);
  });
  test('a value with spaces, quoted', () => {
    assert.deepEqual(texts(suggest('team:sec', 8, values)), ['team:"Security review"']);
  });
  test('nothing for a name, an @handle, or a word typed whole', () => {
    assert.equal(suggest('python3', 7, values), null);
    assert.equal(suggest('@alice', 6, values), null);
    assert.equal(suggest('is:builds', 9, values), null);
  });
  test('the word at the caret, not the last one', () => {
    const found = suggest('is:b wine', 4, values);
    assert.deepEqual([found.start, found.end], [0, 4]);
  });
});
