// ?debug=timing: each redraw's parts in the console, as long as each took
// ("update 41 ms: view 0, browser 4, filter 27, browser 1, stats 2, header
// 5, rows 2"), to see where the time goes rather than guess. "browser":
// the page yielding to it between parts (it lays out and paints then).
// Off, a timer does nothing.

const on = new URLSearchParams(location.search).get('debug') === 'timing';
const OFF = { lap() {}, done() {} };

// A timer for one run of what: lap(name) ends the part called name (begun
// at the last lap), done() logs them all.
export function timer(what, { enabled = on, log = console.log } = {}) {
  if (!enabled) return OFF;
  const start = performance.now();
  let last = start;
  const laps = [];
  return {
    lap(name) {
      const now = performance.now();
      laps.push(`${name} ${Math.round(now - last)}`);
      last = now;
    },
    done() {
      log(`${what} ${Math.round(performance.now() - start)} ms: ${laps.join(', ')}`);
    },
  };
}
