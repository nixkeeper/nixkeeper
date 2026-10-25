"""nixpkgs side: the package lists (Nix files), the channel's package index and
revision, where nixpkgs marks packages broken, and where their sources come
from."""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

import brotli

from .. import config


def read_lists(path=None):
    """The package lists: {"maintainers": [...], "extraPackages": [...],
    "updateChecks": {...}, "ignoredUpdates": {...}, "upToDate": {...}, ...}.
    From a JSON file as is, or from the Nix folder (package-lists/) by
    evaluating it."""
    path = path or config.LISTS
    if not os.path.exists(path):
        sys.exit(
            f"No package lists at {path}. Start some with `nixkeeper init "
            "--maintainer <your GitHub handle>`, or point --lists (or "
            "NIXKEEPER_LISTS) at yours."
        )
    if path.endswith(".json"):
        with open(path) as f:
            return json.load(f)
    try:
        result = subprocess.run(
            [
                "nix",
                "eval",
                "--extra-experimental-features",
                "nix-command flakes",
                "--json",
                "-f",
                path,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError:
        sys.exit(
            "nixkeeper needs nix on the PATH to read the package lists (or give "
            "it a JSON file of them with --lists)."
        )
    except subprocess.CalledProcessError as e:
        sys.exit(f"The package lists at {path} didn't evaluate:\n{e.stderr.strip()}")
    return json.loads(result.stdout)


def channel_revision():
    """The nixpkgs commit the channel (and so the index) was built from, or the
    branch name if it can't be fetched: links then still work, their line
    numbers just may have drifted."""
    req = urllib.request.Request(
        config.NIXPKGS_REVISION_URL, headers={"User-Agent": config.user_agent()}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            revision = resp.read().decode().strip()
    except (urllib.error.URLError, OSError) as e:
        print(f"  couldn't fetch the channel revision ({e})", file=sys.stderr)
        return config.NIXPKGS_BRANCH
    return revision or config.NIXPKGS_BRANCH


# meta.broken of each attribute (null if it doesn't evaluate), on the
# platform of the legacyPackages it's applied to.
BROKEN_EXPR = """pkgs: map (attr:
  let
    pkg = pkgs.lib.attrByPath (pkgs.lib.splitString "." attr) { } pkgs;
    r = builtins.tryEval (pkg.meta.broken or false);
  in if r.success then r.value else null) {attrs}"""


# What evaluate answered, kept between syncs (data/evaluations.json) while
# nixpkgs' commit hasn't moved: the channel moves once or twice a day, so a
# sync every few hours would otherwise fetch and evaluate the same commit
# again for the same answers. Only once the sync turns it on (keep_answers):
# {"answers": {"<revision> <system> <expression's hash>": {attr: answer}},
# "used": the keys asked this run}.
EVALUATIONS = "evaluations.json"
_kept = None
_kept_lock = threading.Lock()


def keep_answers(out_dir=None):
    """From now on, keep evaluate's answers, starting from those the last
    sync wrote (EVALUATIONS in out_dir). Returns how many it had."""
    global _kept
    found = {}
    try:
        with open(os.path.join(config.data_dir(out_dir), EVALUATIONS)) as f:
            found = json.load(f).get("answers") or {}
    except (OSError, ValueError, AttributeError):
        pass
    _kept = {"answers": found, "used": set()}
    return sum(len(v) for v in found.values())


def kept_answers():
    """The answers this run used, to write as EVALUATIONS (those of commits
    no longer asked about are dropped), or None when they aren't kept."""
    if _kept is None:
        return None
    with _kept_lock:
        return {
            "answers": {
                key: _kept["answers"][key]
                for key in sorted(_kept["used"])
                if key in _kept["answers"]
            }
        }


def stop_keeping():
    """Stop keeping evaluate's answers (once the sync has written them)."""
    global _kept
    _kept = None


def evaluate(revision, system, expr, attrs):
    """expr (a function of legacyPackages, with {attrs} where the list of
    attributes goes) evaluated at the channel's revision for system: its
    JSON answer, one value per attribute. The attributes are read from a
    file, not put on nix's command line: Linux limits one argument to 128
    KB, a few thousand attribute names (reading a file outside the store
    takes --impure; what's evaluated is still that revision). Raises with
    nix's last line of output if that fails. While answers are kept
    (keep_answers), only the attributes not answered at that revision yet
    are evaluated (none, most syncs between channel moves); not for a
    branch name, which moves."""
    if _kept is None or revision == config.NIXPKGS_BRANCH:
        return _evaluate(revision, system, expr, attrs)
    key = f"{revision} {system} {hashlib.sha256(expr.encode()).hexdigest()[:12]}"
    with _kept_lock:
        _kept["used"].add(key)
        known = _kept["answers"].setdefault(key, {})
        missing = [a for a in dict.fromkeys(attrs) if a not in known]
    if missing:
        values = _evaluate(revision, system, expr, missing)
        with _kept_lock:
            known.update(zip(missing, values, strict=True))
    return [known[a] for a in attrs]


def _evaluate(revision, system, expr, attrs):
    """evaluate's answer from nix itself."""
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "attrs.json")
        with open(path, "w") as f:
            json.dump(attrs, f)
        listed = f"(builtins.fromJSON (builtins.readFile {json.dumps(path)}))"
        return _nix_eval(revision, system, expr.replace("{attrs}", listed))


def _nix_eval(revision, system, apply):
    """legacyPackages.system at revision, with apply applied: its JSON
    answer. Raises EvalError with nix's last line of output."""
    try:
        out = subprocess.run(
            [
                "nix",
                "eval",
                "--extra-experimental-features",
                "nix-command flakes",
                "--impure",
                "--json",
                f"github:NixOS/nixpkgs/{revision}#legacyPackages.{system}",
                "--apply",
                apply,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(out.stdout)
    except (subprocess.CalledProcessError, OSError, ValueError) as e:
        # nix's last line of output says what went wrong.
        lines = (getattr(e, "stderr", None) or "").strip().splitlines()
        raise EvalError(lines[-1] if lines else str(e)) from e


class EvalError(Exception):
    """nixpkgs didn't evaluate (evaluate): the reason, from nix."""


def broken(attrs, revision):
    """{attr: [systems where nixpkgs marks it broken]} at the channel's
    revision. The index can't say: it's evaluated for x86_64-linux only, and
    `broken = stdenv.hostPlatform.isDarwin;` is false there. Evaluates nixpkgs
    per platform instead (evaluation only, so darwin works from Linux). Empty
    if that fails: this is extra information, not worth failing the sync."""
    attrs = sorted(attrs)
    result = {}
    for system in config.HYDRA_SYSTEMS:
        try:
            values = evaluate(revision, system, BROKEN_EXPR, attrs)
        except EvalError as e:
            print(
                f"::warning::Couldn't evaluate meta.broken on {system}: {e}",
                file=sys.stderr,
            )
            return {}
        for attr, is_broken in zip(attrs, values, strict=True):
            if is_broken:
                result.setdefault(attr, []).append(system)
    return result


# Where each attribute's source comes from: its version, and its src's
# repository (fetchFromGitHub and the like), tag, rev and first URL; null for
# a field it doesn't have, and for an attribute that doesn't evaluate.
SOURCES_EXPR = """pkgs: map (attr:
  let
    lib = pkgs.lib;
    pkg = lib.attrByPath (lib.splitString "." attr) { } pkgs;
    text = s: f: let r = builtins.tryEval (s.${f} or null);
      in if r.success && builtins.isString r.value then r.value else null;
    srcTry = builtins.tryEval (pkg.src or null);
    src = if srcTry.success && builtins.isAttrs srcTry.value then srcTry.value else { };
    urls = builtins.tryEval (src.urls or [ ]);
    found = {
      version = text pkg "version";
      gitRepoUrl = text src "gitRepoUrl";
      tag = text src "tag";
      rev = text src "rev";
      url = if urls.success && builtins.isList urls.value && urls.value != [ ]
        then builtins.head urls.value else text src "url";
    };
    r = builtins.tryEval (builtins.deepSeq found found);
  in if r.success then r.value else null) {attrs}"""


def sources(attrs, revision):
    """{attr: {"version", "gitRepoUrl", "tag", "rev", "url"}} at the channel's
    revision, for x86_64-linux (where sources come from doesn't depend on the
    platform, as a rule); attributes that don't evaluate are left out. Raises
    EvalError if nixpkgs doesn't evaluate."""
    attrs = sorted(attrs)
    values = evaluate(revision, "x86_64-linux", SOURCES_EXPR, attrs)
    return {a: v for a, v in zip(attrs, values, strict=True) if v}


# Each attribute's patches, as text a CVE id can be found in: a patch
# file's name, a fetched patch's name and URLs; null for an attribute that
# doesn't evaluate. nixpkgs names a CVE's fix after it more often than not
# (CVE-2026-56391.patch, a fetchpatch of upstream's commit).
PATCHES_EXPR = """pkgs: map (attr:
  let
    lib = pkgs.lib;
    pkg = lib.attrByPath (lib.splitString "." attr) { } pkgs;
    listed = builtins.tryEval (pkg.patches or [ ]);
    patches =
      if listed.success && builtins.isList listed.value then listed.value else [ ];
    urls = p:
      let u = builtins.tryEval (p.urls or (lib.optional (p ? url) p.url));
      in if u.success && builtins.isList u.value
        then lib.filter builtins.isString u.value else [ ];
    names = p:
      let
        r = builtins.tryEval (
          if builtins.isPath p || builtins.isString p
          then [ (baseNameOf (toString p)) ]
          else if builtins.isAttrs p
          then lib.optional (p ? name && builtins.isString p.name) p.name ++ urls p
          else [ ]
        );
      in if r.success then r.value else [ ];
    found = lib.concatMap names patches;
    r = builtins.tryEval (builtins.deepSeq found found);
  in if r.success then r.value else null) {attrs}"""


def patches(attrs, revision):
    """{attr: [patch names and URLs]} at revision (x86_64-linux), for the
    attrs that have any. Raises EvalError if nixpkgs doesn't evaluate."""
    attrs = sorted(attrs)
    if not attrs:
        return {}
    values = evaluate(revision, "x86_64-linux", PATCHES_EXPR, attrs)
    return {a: v for a, v in zip(attrs, values, strict=True) if v}


def load_index(url=None):
    """attribute -> package (pname, version, meta) for all of nixos-unstable
    (or the channel whose index url is)."""
    print("Downloading nixpkgs package index...", file=sys.stderr)
    req = urllib.request.Request(
        url or config.NIXPKGS_INDEX_URL, headers={"User-Agent": config.user_agent()}
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        # Includes nested sets (haskellPackages.foo), but not aliases such as
        # python3Packages: those need their versioned name (python313Packages).
        return json.loads(brotli.decompress(resp.read()))["packages"]


# The systems nixpkgs builds for (Hydra), by family: what a row's platforms
# say it's available on, and the page's per-system filter.
SYSTEMS = {
    "linux": ("x86_64-linux", "aarch64-linux"),
    "darwin": ("aarch64-darwin",),
}


def platforms(pkgs):
    """Where any of pkgs is available, from meta.platforms less
    meta.badPlatforms: Linux and Darwin (any system of each), and "systems"
    (of SYSTEMS) when those don't already say which: a package on
    x86_64-linux only, not aarch64-linux (about 1,900 attributes of 151,000
    on 2026-10-07). None when none of them declares platforms: nixpkgs then
    doesn't restrict it."""

    def strings(field, p):
        return {s for s in p["meta"].get(field) or [] if isinstance(s, str)}

    declared = [p for p in pkgs if p["meta"].get("platforms")]
    if not declared:
        return None
    available = set().union(
        *(strings("platforms", p) - strings("badPlatforms", p) for p in declared)
    )
    found = {
        family: any(s.endswith(f"-{family}") for s in available) for family in SYSTEMS
    }
    # What the families imply, against what's there.
    implied = {s for family, ok in found.items() if ok for s in SYSTEMS[family]}
    known = {s for systems in SYSTEMS.values() for s in systems}
    if (available & known) != implied:
        found["systems"] = sorted(available & known)
    return found


def available_on(platforms, system):
    """Whether a row whose platforms() are platforms is available on system
    (x86_64-linux), as the page's platform filter has it."""
    if platforms is None:
        return True
    if not platforms.get(system.rsplit("-", 1)[-1]):
        return False
    systems = platforms.get("systems")
    return systems is None or system in systems
