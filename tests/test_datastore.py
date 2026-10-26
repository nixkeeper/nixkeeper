import json
import os
import tempfile
import unittest
import unittest.mock

from nixkeeper import datastore, lock
from nixkeeper.datastore import data_file, write
from nixkeeper.naming import shard_of

ENTRIES = [{"repo": "nix_unstable", "version": "1.18.5"}]


def full_row(name, **extra):
    """A row as the sync writes it, with fields only the panels use."""
    return {
        "name": name,
        "project": name,
        "dataFile": f"{name}.json",
        "homepage": "https://example.org",
        "source": "https://github.com/NixOS/nixpkgs/blob/x/package.nix#L1",
        "repoCount": 12,
        "repologyCheckedAt": "2026-10-05T00:00:00+00:00",
        "nixVersion": "1.18.5",
        "builds": [
            {
                "attr": name,
                "build": 1,
                "checkedAt": "2026-10-05T06:00:00+00:00",
                "name": f"{name}-1.18.5",
                "status": "failed",
                "system": "x86_64-linux",
                "version": "1.18.5",
            }
        ],
        "update": {
            "outcome": "failed",
            "failedBecause": "tests",
            "log": "https://example.org/log",
            "to": "2",
        },
        "upstream": {
            "version": "1.19",
            "newer": True,
            "repo": "wesnoth/wesnoth",
            "checkedAt": "2026-10-05T06:00:00+00:00",
        },
        **extra,
    }


class Output(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.out = os.path.join(self.dir.name, "data")

    def read(self, name):
        with open(os.path.join(self.out, name)) as f:
            return f.read()

    def test_data_file_is_safe(self):
        self.assertEqual(data_file("python:requests"), "python_requests.json")
        self.assertEqual(data_file("wesnoth"), "wesnoth.json")
        self.assertEqual(data_file("a/b c"), "a_b_c.json")

    def test_write_replaces_the_whole_folder(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "removed-package.json"), "w") as f:
            f.write("[]")
        os.makedirs(self.out + ".tmp")  # leftover from a failed run
        write(
            {"checkedAt": "now", "packages": [full_row("wesnoth")]},
            {"wesnoth.json": [{"repo": "x"}]},
            self.out,
        )
        # No per-project files (format 1) since 0.13.0: the entries are in
        # the shards.
        self.assertEqual(
            sorted(os.listdir(self.out)), ["index.json", "rows", "summary.json"]
        )
        self.assertEqual(os.listdir(os.path.join(self.out, "rows")), ["0.json"])
        self.assertFalse(os.path.exists(self.out + ".tmp"))

    def test_written_compact_with_sorted_keys(self):
        write({"packages": [{"name": "a"}], "checkedAt": "now"}, {}, self.out)
        self.assertEqual(self.read("summary.json"), '{"packages":[{"name":"a"}]}')
        self.assertTrue(self.read("index.json").startswith('{"checkedAt":"now",'))

    def test_manifest_without_rows(self):
        rows = [full_row("wesnoth"), full_row("unciv")]
        write({"checkedAt": "now", "version": "0.13.0", "packages": rows}, {}, self.out)
        index = json.loads(self.read("index.json"))
        self.assertEqual(index["format"], 2)
        self.assertEqual(index["packageCount"], 2)
        self.assertEqual(index["shardCount"], 1)
        self.assertEqual(index["version"], "0.13.0")
        self.assertNotIn("packages", index)  # format 1's, until 0.13.0

    def test_summary_leaves_out_what_only_panels_use(self):
        write({"packages": [full_row("wesnoth", openPRs=2)]}, {}, self.out)
        (entry,) = json.loads(self.read("summary.json"))["packages"]
        for key in datastore.PANEL_ONLY:
            self.assertNotIn(key, entry)
        self.assertEqual(
            entry["builds"], [{"status": "failed", "system": "x86_64-linux"}]
        )
        # Why it failed: the list says.
        self.assertEqual(
            entry["update"], {"outcome": "failed", "failedBecause": "tests"}
        )
        self.assertEqual(entry["upstream"], {"version": "1.19", "newer": True})
        self.assertEqual(entry["openPRs"], 2)
        self.assertEqual(entry["nixVersion"], "1.18.5")

    def test_summary_keeps_the_queues_versions_and_day(self):
        github = "https://github.com/yairm210/Unciv/releases"
        repology = "https://repology.org/project/unciv/versions"
        queued = {
            "by": "2026-10-11",
            "candidates": [["4.22.7", github], ["4.22.7", repology]],
        }
        write(
            {
                "packages": [
                    full_row("unciv", queued=queued),
                    full_row("wesnoth", queued={"by": "2026-10-15", "script": True}),
                    full_row("zzz", queued={"by": "2026-10-15"}),
                ]
            },
            {},
            self.out,
        )
        unciv, wesnoth, zzz = json.loads(self.read("summary.json"))["packages"]
        # Each version once, and when (the list's "auto update in 4 days").
        self.assertEqual(unciv["queued"], {"to": ["4.22.7"], "by": "2026-10-11"})
        # Its updateScript's turn: no version, the script decides.
        self.assertEqual(wesnoth["queued"], {"script": True, "by": "2026-10-15"})
        self.assertNotIn("queued", zzz)  # neither: nothing to show
        # The row has it all, for the panel.
        rows = json.loads(self.read("rows/0.json"))["packages"]
        self.assertEqual(rows[0]["queued"], queued)

    def test_summary_keeps_null_and_missing_update_apart(self):
        never = {"name": "a", "update": None}  # the bot never tried
        absent = {"name": "b"}  # not in nixpkgs
        write({"packages": [never, absent]}, {}, self.out)
        a, b = json.loads(self.read("summary.json"))["packages"]
        self.assertIsNone(a["update"])
        self.assertNotIn("update", b)

    def test_shards_hold_full_rows_with_their_entries(self):
        write(
            {"packages": [full_row("wesnoth"), full_row("unciv")]},
            {"wesnoth.json": ENTRIES, "unciv.json": []},
            self.out,
        )
        rows = json.loads(self.read("rows/0.json"))["packages"]
        self.assertEqual([row["name"] for row in rows], ["unciv", "wesnoth"])
        self.assertNotIn("repology", rows[0])  # no entries: left out
        self.assertEqual(rows[1]["repology"], ENTRIES)
        self.assertEqual(rows[1]["builds"][0]["build"], 1)  # in full

    def test_shard_count(self):
        self.assertEqual(datastore.shard_count(0), 1)
        self.assertEqual(datastore.shard_count(241), 1)
        self.assertEqual(datastore.shard_count(501), 2)
        self.assertEqual(datastore.shard_count(1500), 4)
        self.assertEqual(datastore.shard_count(150_000), 512)

    def test_shards_by_name_hash(self):
        rows = [{"name": f"pkg{i}"} for i in range(1200)]
        write({"packages": rows}, {}, self.out)
        index = json.loads(self.read("index.json"))
        self.assertEqual(index["shardCount"], 4)
        seen = []
        for n in range(4):
            shard = json.loads(self.read(f"rows/{n}.json"))["packages"]
            self.assertTrue(shard)  # spread out
            for row in shard:
                self.assertEqual(shard_of(row["name"], 4), n)
            seen += [row["name"] for row in shard]
        self.assertEqual(sorted(seen), sorted(row["name"] for row in rows))

    def test_load_reads_format_2_shards(self):
        rows = [full_row("wesnoth"), full_row("unciv")]
        write(
            {"checkedAt": "now", "packages": rows}, {"wesnoth.json": ENTRIES}, self.out
        )
        loaded = datastore.load(self.out)
        self.assertEqual(loaded["checkedAt"], "now")
        self.assertEqual(
            loaded["packages"], sorted(rows, key=lambda row: row["name"])
        )  # without their entries

    def test_load_falls_back_on_0_12_0s_rows(self):
        # 0.12.0 wrote format 1's rows beside the shards: when a shard can't
        # be read, they're the last run's.
        write({"checkedAt": "now", "packages": [full_row("a")]}, {}, self.out)
        index = json.loads(self.read("index.json"))
        index["packages"] = [{"name": "a"}]
        with open(os.path.join(self.out, "index.json"), "w") as f:
            json.dump(index, f)
        os.remove(os.path.join(self.out, "rows/0.json"))
        self.assertEqual(datastore.load(self.out)["packages"], [{"name": "a"}])
        del index["packages"]  # and since 0.13.0: none
        with open(os.path.join(self.out, "index.json"), "w") as f:
            json.dump(index, f)
        self.assertEqual(datastore.load(self.out)["packages"], [])

    def test_load_reads_format_1(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "index.json"), "w") as f:
            json.dump({"checkedAt": "then", "packages": [{"name": "a"}]}, f, indent=2)
        self.assertEqual(
            datastore.load(self.out), {"checkedAt": "then", "packages": [{"name": "a"}]}
        )

    def test_load_without_data(self):
        self.assertEqual(datastore.load(self.out), {"packages": []})

    def test_entries_from_the_shard_then_the_data_file(self):
        row = full_row("wesnoth")
        write({"packages": [row]}, {"wesnoth.json": ENTRIES}, self.out)
        self.assertEqual(datastore.entries(row, self.out), ENTRIES)
        # Format 1 (from 0.11.0 and before): the data file.
        os.makedirs(os.path.join(self.dir.name, "old"))
        old = os.path.join(self.dir.name, "old")
        with open(os.path.join(old, "index.json"), "w") as f:
            json.dump({"packages": [row]}, f)
        with open(os.path.join(old, "wesnoth.json"), "w") as f:
            json.dump(ENTRIES, f)
        self.assertEqual(datastore.entries(row, old), ENTRIES)
        with self.assertRaises(OSError):
            datastore.entries(full_row("unciv"), old)

    def test_saved_entries_read_each_shard_once(self):
        rows = [full_row(f"pkg{i}") for i in range(1200)]
        write({"packages": rows}, {r["dataFile"]: ENTRIES for r in rows}, self.out)
        reads = []
        load = datastore.shards.load_json

        def counting(path):
            reads.append(path)
            return load(path)

        with unittest.mock.patch.object(datastore.shards, "load_json", counting):
            saved = datastore.saved_entries(self.out)
        self.assertEqual(saved["pkg7"], ENTRIES)
        self.assertEqual(len(saved), 1200)
        shards = json.loads(self.read("index.json"))["shardCount"]
        self.assertEqual(len(reads), 1 + shards)  # the index, each shard once

    def test_no_saved_entries_in_format_1(self):
        os.makedirs(self.out)
        with open(os.path.join(self.out, "index.json"), "w") as f:
            json.dump({"packages": [full_row("wesnoth")]}, f)
        self.assertEqual(datastore.saved_entries(self.out), {})
        self.assertEqual(datastore.saved_entries(os.path.join(self.dir.name, "x")), {})

    def cut_short(self):
        """A swap that dies between moving the old data aside and moving
        the new data in: the last data waits in data.old."""
        write({"packages": [{"name": "last"}]}, {}, self.out)
        real_rename = os.rename

        def dies_on_moving_the_new_data_in(src, dst):
            if src.endswith(".tmp"):
                raise OSError("the run died")
            real_rename(src, dst)

        with (
            unittest.mock.patch("os.rename", dies_on_moving_the_new_data_in),
            self.assertRaises(OSError),
        ):
            write({"packages": [{"name": "new"}]}, {}, self.out)
        self.assertFalse(os.path.exists(self.out))
        self.assertTrue(os.path.isdir(self.out + ".old"))

    def test_a_swap_cut_short_is_undone_under_the_lock(self):
        self.cut_short()
        with lock.held(self.out):
            rows = datastore.load(self.out)["packages"]
        self.assertEqual([row["name"] for row in rows], ["last"])
        self.assertFalse(os.path.exists(self.out + ".old"))

    def test_load_reads_only(self):
        # Without the lock, a swap may be under way: load changes nothing.
        self.cut_short()
        self.assertEqual(datastore.load(self.out), {"packages": []})
        self.assertFalse(os.path.exists(self.out))
        self.assertTrue(os.path.isdir(self.out + ".old"))

    def test_a_stale_old_folder_is_removed(self):
        # A run that died after both renames, before removing data.old.
        write({"packages": [{"name": "new"}]}, {}, self.out)
        os.makedirs(self.out + ".old")
        with lock.held(self.out):
            pass
        self.assertFalse(os.path.exists(self.out + ".old"))
        self.assertEqual(datastore.load(self.out)["packages"][0]["name"], "new")

    def test_update_removes_shards_past_the_new_count(self):
        write({"packages": [{"name": f"pkg{i}"} for i in range(1200)]}, {}, self.out)
        self.assertEqual(
            sorted(os.listdir(os.path.join(self.out, "rows"))),
            [f"{n}.json" for n in range(4)],
        )
        datastore.update({"packages": [{"name": "pkg0"}]}, {}, self.out)
        self.assertEqual(os.listdir(os.path.join(self.out, "rows")), ["0.json"])
        self.assertEqual(len(datastore.load(self.out)["packages"]), 1)

    def test_update_rewrites_only_what_changed(self):
        rows = [{"name": f"pkg{i}"} for i in range(1200)]
        write({"packages": rows}, {}, self.out)
        before = {
            n: os.stat(os.path.join(self.out, f"rows/{n}.json")).st_mtime_ns
            for n in range(4)
        }
        changed = [dict(row) for row in rows]
        changed[0]["nixVersion"] = "2"
        datastore.update({"packages": changed}, {}, self.out)
        shard = shard_of("pkg0", 4)
        for n in range(4):
            after = os.stat(os.path.join(self.out, f"rows/{n}.json")).st_mtime_ns
            self.assertEqual(after != before[n], n == shard, n)
        self.assertEqual(datastore.load(self.out)["packages"][0]["nixVersion"], "2")


RUN = "2026-10-05T06:00:00+00:00"
EARLIER = "2026-10-03T06:00:00+00:00"


def stamped(name, when=RUN):
    """A row with this run's stamps (or when's): a build, an update check,
    counts."""
    return {
        "name": name,
        "builds": [
            {"status": "ok", "system": "x86_64-linux", "checkedAt": when},
            {"status": "ok", "system": "aarch64-linux", "checkedAt": EARLIER},
        ],
        "upstream": {"version": "2", "checkedAt": when},
        "openPRs": 0,
        "openIssues": 0,
        "countedAt": when,
    }


class RunStamps(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.out = os.path.join(self.dir.name, "data")

    def written(self, rows, run=RUN):
        write({"checkedAt": run, "packages": rows}, {}, self.out)
        with open(os.path.join(self.out, "rows/0.json")) as f:
            return json.load(f)["packages"]

    def test_this_runs_stamps_left_out(self):
        (row,) = self.written([stamped("a")])
        self.assertNotIn("countedAt", row)
        self.assertNotIn("checkedAt", row["upstream"])
        self.assertNotIn("checkedAt", row["builds"][0])
        self.assertEqual(row["builds"][1]["checkedAt"], EARLIER)  # older: kept

    def test_older_stamps_kept(self):
        (row,) = self.written([stamped("a", EARLIER)])
        self.assertEqual(row["countedAt"], EARLIER)
        self.assertEqual(row["upstream"]["checkedAt"], EARLIER)

    def test_everywhere_written(self):
        self.written([stamped("a")])
        with open(os.path.join(self.out, "summary.json")) as f:
            self.assertNotIn(RUN, json.load(f)["packages"][0].values())

    def test_load_puts_them_back(self):
        rows = [stamped("a"), stamped("b", EARLIER)]
        self.written(rows)
        self.assertEqual(datastore.load(self.out)["packages"], rows)

    def test_nothing_added_where_nothing_was(self):
        bare = {"name": "a", "nixVersion": "1"}  # no builds, check or counts
        self.written([bare])
        self.assertEqual(datastore.load(self.out)["packages"], [bare])

    def test_unchanged_rows_keep_their_bytes(self):
        first = self.written([stamped("a")])
        second = self.written(
            [stamped("a", "2026-10-06T06:00:00+00:00")], run="2026-10-06T06:00:00+00:00"
        )
        self.assertEqual(first, second)


class Unbuilt(unittest.TestCase):
    """Listed for a platform Hydra doesn't build it on (the page's
    unbuiltWhere: tests/js/status.test.mjs has the same cases)."""

    def row(self, platforms, *builds):
        return {
            "name": "p",
            "platforms": platforms,
            "builds": [{"system": s, "status": st} for s, st in builds],
        }

    def test_cases(self):
        both = {"linux": True, "darwin": True}
        juce = self.row(
            both,
            ("x86_64-linux", "ok"),
            ("aarch64-linux", "ok"),
            ("aarch64-darwin", "notBuilt"),
        )
        self.assertEqual(datastore.unbuilt_where(juce), ["darwin"])
        arm = self.row(
            {"linux": True, "darwin": False},
            ("x86_64-linux", "ok"),
            ("aarch64-linux", "notBuilt"),
        )
        self.assertEqual(datastore.unbuilt_where(arm), ["aarch64-linux"])
        nowhere = self.row(
            both,
            ("x86_64-linux", "notBuilt"),
            ("aarch64-linux", "notBuilt"),
            ("aarch64-darwin", "notBuilt"),
        )
        self.assertEqual(datastore.unbuilt_where(nowhere), [])
        not_listed = self.row(
            {"linux": True, "darwin": False},
            ("x86_64-linux", "ok"),
            ("aarch64-darwin", "notBuilt"),
        )
        self.assertEqual(datastore.unbuilt_where(not_listed), [])
        # No restriction: listed everywhere (fzssh).
        anywhere = self.row(
            None, ("x86_64-linux", "ok"), ("aarch64-darwin", "notBuilt")
        )
        self.assertEqual(datastore.unbuilt_where(anywhere), ["darwin"])


class Numbers(unittest.TestCase):
    def test_counts(self):
        rows = [
            {
                "name": "a",
                "maintainers": [],
                "builds": [
                    {"system": "x86_64-linux", "status": "failed"},
                    {"system": "aarch64-linux", "status": "dependency"},
                    {"system": "aarch64-darwin", "status": "notBuilt"},
                ],
                "openPR": {"facts": {"behind": "2.0"}},
            },
            {
                "name": "b",
                "maintainers": ["x"],
                "builds": [
                    {"system": "x86_64-linux", "status": "ok"},
                    {"system": "aarch64-linux", "status": "unfinished"},
                ],
            },
            # A set's: its builds count, its maintainers don't.
            {
                "name": "haskellPackages.c",
                "set": "haskellPackages",
                "maintainers": [],
                "builds": [{"system": "x86_64-linux", "status": "failed"}],
            },
        ]
        self.assertEqual(
            datastore.numbers(rows),
            {
                "builds": 5,
                "failing": 2,
                "blocked": 1,
                "unfinished": 1,
                "behind": 1,
                "unmaintained": 1,
            },
        )


def build(status, system="x86_64-linux", **more):
    """A Hydra build of a row, as the collectors read it."""
    return {"attr": "a", "system": system, "status": status, **more}


class Collectors(unittest.TestCase):
    """views()' collectors on their own: what each counts, sets included or not."""

    FAILING = {"name": "f", "builds": [build("failed")], "maintainers": ["Ann"]}
    IN_SET = {**FAILING, "name": "s", "set": "rPackages"}

    def test_each_collector_under_its_own_name(self):
        # views() reads each by name: a name holding another collector would
        # only show as wrong output.
        collectors = datastore.view_files._Collectors.new()
        expected = {
            "view_files": datastore.view_files._Views,
            "counts": datastore.view_files._Counts,
            "names": datastore.view_files._Names,
            "facets": datastore.view_files._Facets,
            "maintainers": datastore.view_files._Maintainers,
            "ages": datastore.view_files._Ages,
            "blockers": datastore.view_files._Blockers,
            "staging": datastore.view_files._StagingNextBlockers,
            "sets": datastore.view_files._Sets,
        }
        self.assertEqual(
            {name: type(c) for name, c in collectors._asdict().items()}, expected
        )

    def test_views_leave_a_sets_rows_out_of_most(self):
        views = datastore.view_files._Views()
        for row in (self.FAILING, self.IN_SET):
            views.add(row, "f")
        files, sizes = views.result()
        self.assertEqual(sizes["attention"], 1)
        self.assertEqual(
            [p["name"] for p in files["views/maintainer/ann.json"]["packages"]],
            ["f", "s"],
        )
        self.assertEqual(
            [p["name"] for p in files["views/set/rPackages.json"]["packages"]], ["s"]
        )

    def test_counts_count_a_sets_rows_apart(self):
        counts = datastore.view_files._Counts()
        for row in (self.FAILING, self.IN_SET):
            counts.add(row, "f")
        found = counts.result()
        self.assertEqual(
            (found["tracked"], found["failed"], found["inSets"]), (1, 1, 1)
        )
        self.assertEqual(found["failingBuilds"], 2)  # sets included, as zh.fail
        self.assertEqual(found["buildFailuresOn"], {"linux": 1, "x86_64-linux": 1})

    def test_maintainers_count_a_sets_rows_as_packages_only(self):
        maintainers = datastore.view_files._Maintainers()
        for row in (self.FAILING, self.IN_SET):
            maintainers.add(row, "f")
        self.assertEqual(maintainers.result(), {"maintainers": [["Ann", 2, 0, 1]]})

    def test_blockers_count_a_stopped_package_with_its_blockers_unknown(self):
        blockers = datastore.view_files._Blockers()
        blocker = {"name": "zlib", "row": True}
        blockers.add(
            {"name": "a", "builds": [build("dependency", blockedBy=[blocker])]}, "n"
        )
        blockers.add({"name": "b", "builds": [build("dependency")]}, "n")
        self.assertEqual(
            blockers.result(),
            {"count": 1, "packages": 2, "top": [["zlib", True, 1, 1]]},
        )

    def test_staging_next_blockers_say_which_evaluation(self):
        staging = datastore.view_files._StagingNextBlockers()
        found = {
            "eval": 7,
            "evaluatedAt": "2026-10-25",
            "builds": [{"by": [{"name": "glib"}]}],
        }
        staging.add({"name": "a", "stagingNextBlockedBy": found}, "u")
        staging.add({"name": "b"}, "u")
        self.assertEqual(
            staging.result(),
            {
                "eval": 7,
                "evaluatedAt": "2026-10-25",
                "count": 1,
                "packages": 1,
                "top": [["glib", False, 1, 1]],
            },
        )

    def test_a_sets_bar_counts_each_package_at_its_worst(self):
        sets = datastore.view_files._Sets()
        sets.add({**self.IN_SET, "markedBroken": True}, "f")  # failing and broken
        sets.add({"name": "t", "set": "rPackages", "markedBroken": True}, "u")
        sets.add(self.FAILING, "f")  # not in a set: not counted
        found = sets.result()["rPackages"]
        self.assertEqual(
            (found["packages"], found["failed"], found["broken"]), (2, 1, 2)
        )
        self.assertEqual(found["bar"], {"failed": 1, "broken": 1, "outdated": 0})
