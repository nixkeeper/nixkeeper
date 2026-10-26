// What this browser keeps for the page (localStorage: nothing is sent
// anywhere): read and written, quietly doing without when storage is
// blocked.
import { attentionPrint } from './status.js';
import { store } from './store.js';

export const stored = (key) => {
  try {
    return localStorage.getItem(key);
  } catch {
    return null; // storage blocked: nothing is remembered
  }
};

export const remember = (key, value) => {
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    // storage blocked: it lasts until the page is left
  }
};

// "Hide until it changes": in this browser only (localStorage), each hidden
// package by name with what it needed attention for then (attentionPrint).
// Back as soon as that differs; "Show hidden" shows them all, greyed.
export const HIDDEN_KEY = 'nixkeeper-hidden';

export const hiddenPrints = (() => {
  try {
    return JSON.parse(stored(HIDDEN_KEY) || '{}') || {};
  } catch {
    return {};
  }
})();

// Entries that no longer match (it changed, or left the data) dropped, once
// a view's packages are in: what's hidden only ever matches now.
export function pruneHidden(list) {
  let changed = false;
  for (const pkg of list) {
    if (pkg.name in hiddenPrints && !isHidden(pkg)) {
      delete hiddenPrints[pkg.name];
      changed = true;
    }
  }
  if (changed)
    remember(HIDDEN_KEY, Object.keys(hiddenPrints).length ? JSON.stringify(hiddenPrints) : '');
}

// Its print worked out only for one hidden here: the filters ask for every
// package, and working out each print took 55 ms over 13,913.
export const isHidden = (pkg) =>
  pkg.name in hiddenPrints && hiddenPrints[pkg.name] === attentionPrint(pkg, store.checkedAt);
