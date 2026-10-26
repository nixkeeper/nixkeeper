// Days, ages and trends (page/dates.js). Run: node --test tests/js/
// (part of `nix flake check`, as checks.page).

import assert from 'node:assert/strict';
import { describe, test } from 'node:test';

import { onHost } from '../../page/address.js';
import {
  dayPosition,
  daysText,
  daysUntil,
  shortAge,
  timeAgo,
  trendChange,
  weekChange,
} from '../../page/dates.js';
import { daysAgo, NOW } from './helpers.mjs';

describe('ages', () => {
  test('shortAge: one unit, rounded down', () => {
    assert.equal(shortAge(daysAgo(0.5), NOW), '<1 d');
    assert.equal(shortAge(daysAgo(1), NOW), '1 d');
    assert.equal(shortAge(daysAgo(6), NOW), '6 d');
    assert.equal(shortAge(daysAgo(7), NOW), '1 w');
    assert.equal(shortAge(daysAgo(29), NOW), '4 w');
    assert.equal(shortAge(daysAgo(30), NOW), '1 m');
    assert.equal(shortAge(daysAgo(364), NOW), '11 m');
    assert.equal(shortAge(daysAgo(365), NOW), '1 y');
    assert.equal(shortAge(daysAgo(800), NOW), '2 y');
  });
  test('daysText', () => {
    assert.equal(daysText(daysAgo(0.2), NOW), 'today');
    assert.equal(daysText(daysAgo(1), NOW), '1 day');
    assert.equal(daysText(daysAgo(12), NOW), '12 days');
  });
  test('daysUntil', () => {
    // NOW is 2026-10-01 at noon UTC.
    assert.equal(daysUntil('2026-10-01', NOW), 0);
    assert.equal(daysUntil('2026-10-02', NOW), 1);
    assert.equal(daysUntil('2026-10-12', NOW), 11);
    assert.equal(daysUntil('2026-09-28', NOW), 0); // past: due now
  });
  test('onHost', () => {
    assert.equal(onHost('https://github.com/yairm210/Unciv/releases', 'github.com'), true);
    assert.equal(onHost('https://API.GitHub.com/repos/x', 'github.com'), true);
    // The name elsewhere in the address isn't the host.
    assert.equal(onHost('https://example.org/?github.com', 'github.com'), false);
    assert.equal(onHost('https://github.com.example.org/', 'github.com'), false);
    assert.equal(onHost('https://notgithub.com/', 'github.com'), false);
    assert.equal(onHost('not a url', 'github.com'), false);
    assert.equal(onHost('', 'repology.org'), false);
  });
  test('timeAgo', () => {
    assert.equal(timeAgo(null, NOW), 'never');
    assert.equal(timeAgo(new Date(NOW - 30e3).toISOString(), NOW), 'just now');
    assert.equal(timeAgo(new Date(NOW - 5 * 60e3).toISOString(), NOW), '5m ago');
    assert.equal(timeAgo(new Date(NOW - 4 * 3600e3).toISOString(), NOW), '4h ago');
    assert.equal(timeAgo(daysAgo(3), NOW), '3d ago');
  });
});

describe('weekChange', () => {
  const day = (d, failed) => ({ day: d, failed });
  test('against the newest point a week or more before', () => {
    const points = [day('2026-09-25', 100), day('2026-09-28', 110), day('2026-10-05', 150)];
    assert.equal(weekChange(points, 'failed'), 40);
  });
  test('null without a week of points', () => {
    assert.equal(weekChange([day('2026-10-01', 1), day('2026-10-05', 2)], 'failed'), null);
    assert.equal(weekChange([], 'failed'), null);
  });
});

describe('trendChange and dayPosition', () => {
  const day = (d, failed) => ({ day: d, failed });
  test('a week once there is one, else since the first point', () => {
    const week = [day('2026-09-25', 100), day('2026-10-05', 150)];
    assert.deepEqual(trendChange(week, 'failed'), { change: 50, since: null });
    const two = [day('2026-10-05', 2127), day('2026-10-06', 2195)];
    assert.deepEqual(trendChange(two, 'failed'), { change: 68, since: '2026-10-05' });
    assert.equal(trendChange([day('2026-10-06', 1)], 'failed'), null);
  });
  test('by date, missing days keeping their room; null outside', () => {
    const points = [day('2026-10-01', 0), day('2026-10-02', 0), day('2026-10-05', 0)];
    assert.equal(dayPosition(points, '2026-10-01'), 0);
    assert.equal(dayPosition(points, '2026-10-02'), 25);
    assert.equal(dayPosition(points, '2026-10-05'), 100);
    assert.equal(dayPosition(points, '2026-09-28'), null);
    assert.equal(dayPosition([day('2026-10-01', 0)], '2026-10-01'), null);
  });
});
