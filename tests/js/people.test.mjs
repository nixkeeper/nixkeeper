// Maintainers and teams (page/people.js). Run: node --test tests/js/
// (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import {
  maintainerMatches,
  maintainersKeep,
  maintainersParam,
  maintainsDirectly,
  matchesSearch,
  nameMatches,
  parseMaintainers,
  parseTeams,
  searchHandle,
  teamsKeep,
  teamsParam,
} from '../../page/people.js';
import { pkg } from './helpers.mjs';

describe('matchesSearch', () => {
  const heroic = pkg({
    name: 'heroic',
    attrs: ['heroic', 'heroic-unwrapped'],
    maintainers: ['TomaSajt', 'iedame'],
  });
  test('names, projects and attributes contain the text', () => {
    assert.equal(matchesSearch(heroic, ' Unwrapped '), true);
    assert.equal(matchesSearch(heroic, ''), true);
    assert.equal(matchesSearch(heroic, 'tomas'), false); // handles only with @
  });
  test('@handle: the whole handle, in any case', () => {
    assert.equal(matchesSearch(heroic, '@tomasajt'), true);
    assert.equal(matchesSearch(heroic, '@TomaS'), false);
    assert.equal(matchesSearch(heroic, '@'), true); // still typing
    assert.equal(matchesSearch(pkg(), '@iedame'), false); // not synced yet
  });
  test('@none: no maintainer, not unknown', () => {
    assert.equal(matchesSearch(pkg({ maintainers: [] }), '@none'), true);
    assert.equal(matchesSearch(heroic, '@none'), false);
    assert.equal(matchesSearch(pkg(), '@none'), false);
  });
});

describe('maintainerMatches', () => {
  const list = [
    ['Fgaz', 81, 23, 7],
    ['fgazbot', 2, 0, 0],
    ['afgazer', 1, 0, 0],
    ['iedame', 27, 4, 0],
  ];
  test('the handle, then those starting with it, then by handle; any case, @ or not', () => {
    assert.deepEqual(
      maintainerMatches(list, '@fgaz').found.map(([h]) => h),
      ['Fgaz', 'fgazbot', 'afgazer'],
    );
    assert.equal(maintainerMatches(list, 'FGAZ').total, 3);
  });
  test('at most limit, and how many there are', () => {
    assert.deepEqual(maintainerMatches(list, 'a', 2), {
      found: [list[2], list[0]],
      total: 4,
    });
    assert.deepEqual(maintainerMatches(list, '@'), { found: [], total: 0 });
  });
});

describe('searchHandle and maintainsDirectly', () => {
  test('the maintainer a search names', () => {
    assert.equal(searchHandle(' @L0b0 '), 'l0b0');
    assert.equal(searchHandle('@'), null);
    assert.equal(searchHandle('@none'), null);
    assert.equal(searchHandle('gdal'), null);
  });
  test('listed directly, not only as a team member', () => {
    const gdal = { maintainers: ['tviti', 'l0b0'], nonTeamMaintainers: ['tviti'] };
    assert.equal(maintainsDirectly(gdal, 'tviti'), true);
    assert.equal(maintainsDirectly(gdal, 'l0b0'), false);
    // No nonTeamMaintainers: every maintainer is a direct one.
    assert.equal(maintainsDirectly({ maintainers: ['L0b0'] }, 'l0b0'), true);
  });
});

describe('?team=: one team, teams left out, none', () => {
  test('read and written back', () => {
    const t = parseTeams('Gaming, -Geospatial,-Steam,none,-Geospatial');
    assert.deepEqual(t, { include: 'Gaming', leftOut: ['Geospatial', 'Steam'], none: true });
    assert.equal(teamsParam(t), 'Gaming,-Geospatial,-Steam,none');
    assert.deepEqual(parseTeams(null), { include: null, leftOut: [], none: false });
    assert.equal(teamsParam(parseTeams('')), '');
    assert.deepEqual(parseTeams('-').leftOut, []); // a lone "-" names nothing
  });
  const gdal = {
    teams: ['Geospatial'],
    maintainers: ['tviti', 'l0b0'],
    nonTeamMaintainers: ['tviti'],
  };
  const game = { teams: ['Gaming'], maintainers: ['l0b0'] };
  const own = { maintainers: ['l0b0'] };
  const keep = (value, handle = null) =>
    [gdal, game, own].filter((p) => teamsKeep(p, parseTeams(value), handle)).length;
  test('a team left out, any case', () => {
    assert.equal(keep('-geospatial'), 2);
    assert.equal(keep('-Geospatial,-Gaming'), 1);
  });
  test("none: a maintainer's own packages, or packages without a team", () => {
    assert.equal(keep('none', 'l0b0'), 2); // game (direct) and own
    assert.equal(keep('none', 'tviti'), 1); // gdal
    assert.equal(keep('none'), 1); // own: no team
  });
  test('one team, as before', () => {
    assert.equal(keep('Gaming'), 1);
    assert.equal(keep(''), 3);
  });
});

describe('?maintainer=: one page, maintainers left out', () => {
  test('read and written back', () => {
    const m = parseMaintainers('l0b0,-iedame, -@Someone,-iedame');
    assert.deepEqual(m, { handle: 'l0b0', leftOut: ['iedame', 'someone'] });
    assert.equal(maintainersParam(m), 'l0b0,-iedame,-someone');
    assert.deepEqual(parseMaintainers('-iedame'), { handle: null, leftOut: ['iedame'] });
    assert.deepEqual(parseMaintainers('@l0b0'), { handle: 'l0b0', leftOut: [] });
    assert.equal(maintainersParam(parseMaintainers(null)), '');
  });
  test('their packages left out, directly or through a team', () => {
    const freedink = { maintainers: ['iedame', 'l0b0'], nonTeamMaintainers: ['iedame'] };
    assert.equal(maintainersKeep(freedink, ['iedame']), false);
    assert.equal(maintainersKeep(freedink, ['l0b0']), false); // via Gaming: still theirs
    assert.equal(maintainersKeep(freedink, ['someone']), true);
    assert.equal(maintainersKeep({}, ['iedame']), true);
    assert.equal(maintainersKeep(freedink, []), true);
  });
});

describe('searching by the name nixpkgs titles use', () => {
  test('python3Packages. finds python313Packages.', () => {
    const pkg = { name: 'python313Packages.requests', searchTerm: 'python3Packages.requests' };
    assert.equal(matchesSearch(pkg, 'python3Packages.'), true);
    assert.equal(matchesSearch(pkg, 'python313Packages.req'), true);
    const names = [
      ['python313Packages.requests', 'u'],
      ['requests-oauthlib', 'u'],
    ];
    const { found } = nameMatches(names, 'python3Packages.req', new Set());
    assert.deepEqual(
      found.map(([n]) => n),
      ['python313Packages.requests'],
    );
  });
});
