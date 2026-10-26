// Days, ages and changes over time, in the words the page uses ("3 d",
// "2 y"). Times take `now`, so tests can fix it.

export const DAY = 86400e3;

// A count's change over the last week, from history.json's points (oldest
// first, a point a day): the newest point's value less the value of the
// newest point at least 7 days older; null without one.
export function weekChange(points, key) {
  const last = points.at(-1);
  if (!last) return null;
  const week = new Date(Date.parse(`${last.day}T00:00:00Z`) - 7 * 86400e3)
    .toISOString()
    .slice(0, 10);
  const before = points.filter((p) => p.day <= week).at(-1);
  return before ? last[key] - before[key] : null;
}

// A count's change for its card: over the last week (weekChange) once
// there's a week of points, else since the oldest point there is (the
// first daily syncs). {change, since: that point's day}, or null with fewer
// than two points.
export function trendChange(points, key) {
  const week = weekChange(points, key);
  if (week != null) return { change: week, since: null };
  if (points.length < 2) return null;
  return { change: points.at(-1)[key] - points[0][key], since: points[0].day };
}

// Where a day (YYYY-MM-DD) falls on a trend of points (oldest first), from
// 0 (the first point's day) to 100 (the last's), by date, so missing days
// keep their room; null outside them.
export function dayPosition(points, day) {
  if (points.length < 2) return null;
  const at = (d) => Date.parse(`${d}T00:00:00Z`);
  const first = at(points[0].day);
  const span = at(points.at(-1).day) - first;
  const t = at(day);
  if (!span || Number.isNaN(t) || t < first || t > first + span) return null;
  return (100 * (t - first)) / span;
}

// "Older than" (?age=): how many days each choice means. ?age=never is
// the builds that never succeeded on Hydra instead (neverBuiltOn): no date.
export const AGE_DAYS = { '1m': 30, '6m': 182, '1y': 365, '2y': 730, '3y': 1095 };

// How long a package has been outdated, one letter per unit: <1 d, 3 d, 2 w,
// 5 m (months), 2 y.
export function shortAge(iso, now = Date.now()) {
  const days = Math.floor((now - new Date(iso).getTime()) / DAY);
  if (days < 1) return '<1 d';
  if (days < 7) return `${days} d`;
  if (days < 30) return `${Math.floor(days / 7)} w`;
  if (days < 365) return `${Math.min(11, Math.floor(days / 30))} m`; // 360-364 days: not "12 m" before "1 y"
  return `${Math.floor(days / 365)} y`;
}

export function daysText(iso, now = Date.now()) {
  const days = Math.floor((now - new Date(iso).getTime()) / DAY);
  return days < 1 ? 'today' : days === 1 ? '1 day' : `${days} days`;
}

// Whole days from now until a day to come (a plain day, read as its midday
// UTC): 0 for today or one past.
export function daysUntil(day, now = Date.now()) {
  return Math.max(0, Math.round((new Date(`${day}T12:00:00Z`).getTime() - now) / DAY));
}

export function timeAgo(iso, now = Date.now()) {
  if (!iso) return 'never';
  const diff = now - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
