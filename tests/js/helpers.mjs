// What the page modules' tests share: a fixed now, and packages as
// index.json has them.

export const NOW = Date.parse('2026-10-01T12:00:00Z');
export const daysAgo = (n) => new Date(NOW - n * 86400e3).toISOString();

// A package as index.json has it, up to date unless overridden.
export const pkg = (fields = {}) => ({ name: 'p', nixStatus: 'newest', ...fields });
export const outdated = (fields = {}) =>
  pkg({ nixStatus: 'outdated', nixVersion: '1.0', refVersion: '1.1', ...fields });
