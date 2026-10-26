"""Writing, swapping and reading data/.

A full sync builds a new folder and swaps it in (write, swap_in); the
hourly checks rewrite only the files that changed (update). load,
saved_entries and entries read the last run's data back.

The data is in format 2, described in docs/data.md:

- index.json: a small manifest (the format, the counts, ...).
- summary.json: a short entry per row, what the page's list needs. With
  every package there's no summary; views/ and names.json take its place
  (views()).
- rows/<n>.json: the full rows, split into shards by a hash of the
  package's name. Each row carries its Repology entries in "repology".

Format 1 (0.11.0 and before; written beside format 2 until 0.13.0) is still
read, so the first sync after upgrading keeps the last run's data. In
format 1, index.json held every row in full in "packages", and each
Repology project's entries were in a file of their own, named by the row's
"dataFile".
"""

import contextlib
import copy
import functools
import json
import os
import shutil
import traceback

from .. import config, log, shape
from ..naming import shard_of
from . import shards, trends, view_files


def files(index, entries, history=None, fixed=None, events=None):
    """Build every file of the data folder.

    The rows go into the shards, each with its Repology entries. With every
    package, the page starts from views (views()) rather than a summary of
    every row, and history.json gets this run's counts; otherwise
    summary.json lists every row.

    Args:
        index: The manifest, with every row in "packages".
        entries: Repology's entries, by the rows' "dataFile".
        history: With every package, the last run's history.json points
            (read_history), to which this run's counts are added. None
            leaves history.json out, for a partial run: the file on disk
            stays, and the manifest keeps the "fixed" it already has.
        fixed: The fixes to keep (read_fixed's, with this run's added by
            with_fixed).
        events: What marks the trends (with_events).

    Returns:
        {path in the data folder: data}.
    """
    run = index.get("checkedAt")
    rows = sorted(
        (shards.elided(row, run) for row in index["packages"]),
        key=lambda row: row["name"],
    )
    count = shards.shard_count(len(rows))
    by_shard = [[] for _ in range(count)]
    for row in rows:
        full = dict(row)
        if found := entries.get(row.get("dataFile")):
            full["repology"] = found
        by_shard[shard_of(row["name"], count)].append(full)
    manifest = {
        **index,
        "format": shards.FORMAT,
        "packageCount": len(rows),
        "shardCount": count,
    }
    del manifest["packages"]  # the rows are in the shards
    out = {}
    if index.get("allPackages"):
        # With every package, a summary of them all would be too big to
        # load: the page starts from the views, the name index and the
        # counts instead (views()).
        manifest.update(view_files.views(rows, out))
        if history is not None:
            out["history.json"] = {
                "points": trends.with_point(history, run, manifest["counts"]),
                "fixed": fixed or [],
                "events": events or [],
            }
            manifest["fixed"] = trends.fixed_summary(fixed or [], run)
    else:
        out["summary.json"] = {"packages": [shards.summary_entry(row) for row in rows]}
    out["index.json"] = manifest
    for n, shard in enumerate(by_shard):
        out[f"rows/{n}.json"] = {"packages": shard}
    return out


def _write_file(path, text):
    """Write text to path, through a temporary file.

    The file is replaced in one step, so a failed write never leaves it
    half-written.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write(text)
    os.replace(path + ".tmp", path)


def _check_shape(written):
    """Report what in the data doesn't match its description (shape.py).

    The check only reports for now, so it must never stop a write: should
    the check itself fail, that failure is logged too, and the write goes on.

    Args:
        written: The data about to be written, as files builds it.
    """
    try:
        shape.report(shape.problems(written))
    except Exception as e:  # reporting only: never stop a write
        # Where in shape.py it broke, to find the bug without running it
        # again: the innermost frame may be in a library it called.
        frames = traceback.extract_tb(e.__traceback__)
        frame = next(
            (f for f in reversed(frames) if os.path.basename(f.filename) == "shape.py"),
            frames[-1],
        )
        where = f"{os.path.basename(frame.filename)}:{frame.lineno}"
        log.warn(f"Data shape: the check itself failed at {where}: {e!r}")


def write(
    index, entries, out_dir=None, history=None, fixed=None, events=None, kept=None
):
    """Write the whole data folder for a sync, replacing the last one.

    The new data is built in a folder of its own and only then swapped in,
    so packages removed since the last sync disappear, and a run that
    fails before the swap leaves the last data as it was.

    Args:
        index: The manifest, with every row in "packages".
        entries: Repology's entries, by the rows' "dataFile".
        out_dir: The data folder (the configured one by default).
        history: The counts' history so far (read_history), with every
            package; None leaves history.json out.
        fixed: The fixes to keep (with_fixed).
        events: What marks the trends (with_events).
        kept: Files written as they are, {path: data}, what the sync keeps
            for its next run (nixpkgs' evaluations, views/merge.json); None
            for a file leaves it out.

    Raises:
        ValueError: A kept file is under rows/ or views/ but not in
            SYNC_ONLY, before anything is written.
    """
    check_kept(kept)
    out_dir = config.data_dir(out_dir)
    tmp_dir = out_dir + ".tmp"
    # Also done by lock.held; repeated here for callers, such as tests,
    # that write without the lock.
    restore_interrupted_swap(out_dir)
    shutil.rmtree(tmp_dir, ignore_errors=True)  # leftover from a failed run
    os.makedirs(tmp_dir)
    written = files(index, entries, history, fixed, events)
    _check_shape(written)
    for name, data in written.items():
        _write_file(os.path.join(tmp_dir, name), shards.dumps(data))
    for name, data in (kept or {}).items():
        if data is not None:
            _write_file(os.path.join(tmp_dir, name), shards.dumps(data))
    swap_in(tmp_dir, out_dir)


def swap_in(new_dir, out_dir):
    """Replace a data folder with a new one.

    The old folder is moved aside before the new one is moved in, rather
    than deleted first: the data is then missing only between two renames,
    not while a whole folder is deleted, and a run that dies between them
    leaves the old data in <out_dir>.old, which restore_interrupted_swap
    puts back.

    Args:
        new_dir: The new data folder, complete.
        out_dir: The data folder it replaces.
    """
    old_dir = out_dir + ".old"
    shutil.rmtree(old_dir, ignore_errors=True)
    if os.path.exists(out_dir):
        os.rename(out_dir, old_dir)
    os.rename(new_dir, out_dir)
    shutil.rmtree(old_dir, ignore_errors=True)


def restore_interrupted_swap(out_dir=None):
    """Tidy up after a swap that a run didn't finish.

    Only to be called when nothing else can be writing the folder: for the
    data folder, with its lock held (lock.held calls it). It moves folders,
    and another run in the middle of swap_in would see them change under
    it.

    A run that died between swap_in's two renames leaves no data folder
    and the last data in <out_dir>.old: that data is moved back, so the run
    that follows reads it as the previous run's. A run that died after
    both renames leaves the data folder and a stale <out_dir>.old: the old
    folder is removed.

    Args:
        out_dir: The folder swap_in replaces (the configured data folder by
            default).
    """
    out_dir = config.data_dir(out_dir)
    old_dir = out_dir + ".old"
    if not os.path.isdir(old_dir):
        return
    if os.path.exists(out_dir):
        shutil.rmtree(old_dir, ignore_errors=True)
    else:
        os.rename(old_dir, out_dir)


def update(index, entries, out_dir=None):
    """Rewrite the data folder in place, for a partial run.

    The hourly checks change a few rows: only the files whose content
    changed are written, each written aside first so a failure never leaves
    one half-written. The shards and views this run no longer writes, left
    from a run with more rows or a view that has emptied since, are
    removed, so the folder holds what a full write would leave.

    Args:
        index: The manifest, with every row in "packages".
        entries: Repology's entries, by the rows' "dataFile".
        out_dir: The data folder (the configured one by default).
    """
    out_dir = config.data_dir(out_dir)
    # Also done by lock.held; repeated here for callers, such as tests,
    # that write without the lock.
    restore_interrupted_swap(out_dir)
    written = files(index, entries)
    _check_shape(written)
    for name, data in written.items():
        path = os.path.join(out_dir, name)
        text = shards.dumps(data)
        try:
            with open(path) as f:
                if f.read() == text:
                    continue
        except OSError:
            pass
        _write_file(path, text)
    _remove_files_no_longer_written(out_dir, written)


# The view of the PRs maintainers can merge. Only the daily sync writes it,
# as one of write's kept files, so a partial run leaves it in place.
MERGE_VIEW = "views/merge.json"
# Every file the daily sync keeps under rows/ or views/ (write's kept
# files): the only files there that a partial run leaves although it doesn't
# write them. check_kept refuses a kept file there that isn't listed, so a
# new one can't be deleted by every hourly check without anyone noticing.
SYNC_ONLY = frozenset({MERGE_VIEW})
# The folders a partial run tidies: everything in them is written by
# files().
GENERATED_FOLDERS = ("rows", "views")


def check_kept(kept):
    """Refuse a kept file in the generated folders that SYNC_ONLY doesn't list.

    This raises, unlike the shape check (shape.py), which only reports: an
    unlisted kept file is a mistake in nixkeeper's code, caught before any
    data is lost, not a problem in the data.

    Args:
        kept: write's kept files, {path: data}.

    Raises:
        ValueError: A kept file under rows/ or views/ isn't in SYNC_ONLY:
            the next partial run would delete it.
    """
    for path in kept or {}:
        if path.split("/")[0] in GENERATED_FOLDERS and path not in SYNC_ONLY:
            raise ValueError(
                f"{path} is kept by the sync but isn't in datastore.SYNC_ONLY: "
                "the hourly checks would delete it. Add it there."
            )


def _remove_files_no_longer_written(out_dir, written):
    """Remove the files under rows/ and views/ a partial run no longer writes.

    A view with no rows isn't written, so a view that has emptied since the
    last sync would otherwise keep its old rows on disk while the manifest
    says 0; and a shard past the shard count would stay when there are
    fewer rows. A leftover <file>.tmp, from a write that died, goes too.
    The files in SYNC_ONLY, which only the daily sync writes, are kept, and
    so is everything outside those folders (evaluations.json, history.json).
    Folders left empty are removed, except rows/ and views/ themselves, as
    a full write wouldn't make them.

    Args:
        out_dir: The data folder.
        written: The files this run wrote, as files builds them.
    """
    for folder in GENERATED_FOLDERS:
        top = os.path.join(out_dir, folder)
        # Bottom up, so a folder is seen after its files are removed.
        for root, _, names in os.walk(top, topdown=False):
            for name in names:
                path = os.path.relpath(os.path.join(root, name), out_dir)
                if path not in written and path not in SYNC_ONLY:
                    os.remove(os.path.join(root, name))
            if root != top and not os.listdir(root):
                os.rmdir(root)


@functools.lru_cache(maxsize=64)
def _cached(path, changed):
    """Read a data file's JSON, once while the file is unchanged.

    entries() reads a row's shard for each row it's asked about, so without
    the cache a shard would be read again for each of its rows.

    Args:
        path: The file.
        changed: Its modification time, part of the cache's key, so a file
            that was written again is read again.
    """
    return shards.load_json(path)


def _shared(path):
    """Read a data file's JSON through the cache.

    The result is shared with every other caller, so it must not be
    changed.
    """
    return _cached(path, os.stat(path).st_mtime_ns)


def load(out_dir=None):
    """Read the last run's index, with every row in "packages".

    The rows come without their Repology entries (entries() reads those).
    Both formats are read.

    Returns:
        The index, or {"packages": []} when there's none or it can't be
        read.
    """
    out_dir = config.data_dir(out_dir)
    try:
        index = shards.load_json(os.path.join(out_dir, "index.json"))
    except (OSError, ValueError):
        return {"packages": []}
    if index.get("format") == shards.FORMAT:
        # The rows come from the shards. If one can't be read, the rows in
        # index.json are kept (data from 0.12.0 has them, written beside
        # format 1), else there are none.
        with contextlib.suppress(OSError, ValueError, KeyError, TypeError):
            index["packages"] = sorted(
                (
                    {k: v for k, v in row.items() if k != "repology"}
                    for n in range(index["shardCount"])
                    for row in shards.load_json(
                        os.path.join(out_dir, f"rows/{n}.json")
                    )["packages"]
                ),
                key=lambda row: row["name"],
            )
    index.setdefault("packages", [])
    for row in index["packages"]:
        shards.restored(row, index.get("checkedAt"))
    return index


def saved_entries(out_dir=None):
    """Read every row's Repology entries from the last run, each shard once.

    This is for the hourly checks, which write every shard again: calling
    entries() for each row would read a shard per row, about 126,000 shard
    reads with every package.

    Returns:
        {name: entries}, or {} for format 1 or when a file can't be read
        (entries() then reads each row's own file).
    """
    out_dir = config.data_dir(out_dir)
    try:
        index = shards.load_json(os.path.join(out_dir, "index.json"))
        if index.get("format") != shards.FORMAT:
            return {}
        return {
            full["name"]: full.get("repology") or []
            for n in range(index["shardCount"])
            for full in shards.load_json(os.path.join(out_dir, f"rows/{n}.json"))[
                "packages"
            ]
        }
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def entries(row, out_dir=None):
    """Read row's Repology entries from the last run.

    They're read from the row's shard (format 2), else from its own data
    file (format 1, 0.11.0 and before).

    Raises:
        OSError, ValueError: Neither can be read.
    """
    out_dir = config.data_dir(out_dir)
    try:
        index = _shared(os.path.join(out_dir, "index.json"))
        if index.get("format") == shards.FORMAT:
            n = shard_of(row["name"], index["shardCount"])
            for full in _shared(os.path.join(out_dir, f"rows/{n}.json"))["packages"]:
                if full["name"] == row["name"]:
                    return copy.deepcopy(full.get("repology") or [])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    path = os.path.join(out_dir, row.get("dataFile") or f"{row['project']}.json")
    with open(path) as f:
        return json.load(f)
