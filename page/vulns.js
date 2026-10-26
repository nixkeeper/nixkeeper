// Vulnerabilities: whether a package counts as vulnerable, its CVEs'
// severities and sources, and a CVE id's parts.

// Whether a package counts as vulnerable: Repology flags nixpkgs' version
// (nixVulnerable), or nixpkgs itself marks it insecure (markedInsecure, its
// meta.knownVulnerabilities).
export const isVulnerable = (pkg) => {
  const found = vulnSummary(pkg);
  return found !== undefined
    ? Boolean(found) // the sync's verdict, from nixkeeper-vulnerabilities
    : Boolean(pkg.nixVulnerable || pkg.markedInsecure?.length);
};

// The verdicts of a row's "vulnerabilities" that count (changes.py's
// COUNTED_VULNERABILITIES), and severities worst first.
export const VULN_COUNTED = ['affected', 'byVersion', 'tracker', 'wontFix', 'osv'];
const SEVERITIES = ['critical', 'high', 'medium', 'moderate', 'low'];

// A package's vulnerability verdict as the list's entries have it ("vuln":
// {n, severity?, by}, or null when nothing says so), worked out from the
// full row's "vulnerabilities" (a package's own page, or a panel) as
// vulnerabilities_digest.summary does; undefined when there are neither:
// Repology's flag and nixpkgs' mark decide.
export function vulnSummary(pkg) {
  if (pkg.vuln !== undefined) return pkg.vuln;
  if (!pkg.vulnerabilities) return undefined;
  const counted = pkg.vulnerabilities.filter((v) => VULN_COUNTED.includes(v.verdict));
  const by = [...new Set(counted.map((v) => v.source))].sort();
  if (pkg.markedInsecure?.length) by.push('nixpkgs');
  if (pkg.nixVulnerable) by.push('repology');
  if (!by.length) return null;
  const known = counted.map((v) => v.severity).filter((s) => SEVERITIES.includes(s));
  known.sort((a, b) => SEVERITIES.indexOf(a) - SEVERITIES.indexOf(b));
  return { n: counted.length, ...(known.length ? { severity: known[0] } : {}), by };
}

// A vulnerable package's worst severity, as a rank (0 worst); the last
// for one with none known: the vulnerable list's order.
export const severityRank = (pkg) => {
  const i = SEVERITIES.indexOf(vulnSummary(pkg)?.severity);
  return i < 0 ? SEVERITIES.length : i;
};

// Who says a package is vulnerable (its summary's "vuln.by", else from
// Repology's flag and nixpkgs' mark), in words for the badge's title.
const SOURCE_WORDS = {
  tracker: 'the NixOS security tracker',
  osv: 'OSV',
  nixpkgs: 'nixpkgs (marked insecure)',
  repology: 'Repology',
};
export function vulnSources(pkg) {
  const by =
    vulnSummary(pkg)?.by ||
    [pkg.markedInsecure?.length && 'nixpkgs', pkg.nixVulnerable && 'repology'].filter(Boolean);
  return by.map((s) => SOURCE_WORDS[s] || s);
}

// A reason nixpkgs gives for marking a package insecure, in pieces: plain
// text, and the CVE ids in it (CVE-2020-25031), to link.
const CVE_ID = /CVE-\d{4}-\d{4,}/g;
export function cvePieces(text) {
  const pieces = [];
  let at = 0;
  for (const m of text.matchAll(CVE_ID)) {
    if (m.index > at) pieces.push({ text: text.slice(at, m.index) });
    pieces.push({ cve: m[0] });
    at = m.index + m[0].length;
  }
  if (at < text.length) pieces.push({ text: text.slice(at) });
  return pieces;
}
