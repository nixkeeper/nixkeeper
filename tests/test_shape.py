"""nixkeeper.shape: what data/ must look like, checked before it's written."""

import contextlib
import copy
import io
import random
import re
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from nixkeeper import datastore, shape


def row(name, **fields):
    return {
        "name": name,
        "attrs": [name],
        "searchTerm": name,
        "lists": [],
        "nixStatus": "newest",
        **fields,
    }


def files(rows, views=None, counts=None, count=1):
    """data/ as datastore.files hands it over: rows in their shards, and
    with views (every package), the manifest's views and counts."""
    shards = {f"rows/{n}.json": {"packages": []} for n in range(count)}
    for r in rows:
        shards[f"rows/{zlib.crc32(r['name'].encode()) % count}.json"][
            "packages"
        ].append(r)
    manifest = {"packageCount": len(rows), "shardCount": count}
    out = {**shards, "index.json": manifest}
    if views is not None:
        manifest["views"] = {k: len(v) for k, v in views.items()}
        manifest["counts"] = counts or {}
        for k, v in views.items():
            out[f"views/{k}.json"] = {"packages": v}
    return out


FAILING_DARWIN = row(
    "mygui",
    platforms={"linux": True, "darwin": False},
    builds=[{"system": "aarch64-darwin", "status": "failed"}],
)
FAILING_LINUX = row(
    "openttd",
    platforms={"linux": True, "darwin": True},
    builds=[{"system": "x86_64-linux", "status": "failed"}],
)


# What reach finds where a value has no such key or index.
MISSING = object()


def places(value, path=()):
    """Every place in value, as the path of keys and indexes leading there."""
    yield path
    if isinstance(value, dict):
        children = value.items()
    elif isinstance(value, list):
        children = enumerate(value)
    else:
        children = ()
    for key, child in children:
        yield from places(child, (*path, key))


def reach(value, key):
    """value's child at key, or MISSING when it has none there."""
    if isinstance(value, dict):
        return value.get(key, MISSING)
    if isinstance(value, list) and isinstance(key, int) and key < len(value):
        return value[key]
    return MISSING


class Rows(unittest.TestCase):
    def test_well_formed(self):
        self.assertEqual(shape.problems(files([row("a"), row("b")], count=2)), {})

    def test_a_field_misspelt_missing_or_of_the_wrong_type(self):
        found = shape.problems(
            files([row("a", markedBroke=True), {"name": "b"}, row("c", openPRs=True)])
        )["row fields"]
        self.assertIn("a: unknown field markedBroke", found)
        self.assertIn("b: missing attrs", found)
        # true isn't a count, though Python says bool is an int.
        self.assertIn("c: openPRs is bool, not int", found)

    def test_null_where_allowed_only(self):
        self.assertEqual(shape.row_problems(row("a", platforms=None)), [])
        self.assertEqual(
            shape.row_problems(row("a", homepage=1)),
            ["homepage is int, not str or null"],
        )

    def test_a_list_entry_nixpkgs_no_longer_has(self):
        # space-station-14-launcher, renamed ss14-launcher (2026-10-24's sync).
        missing = row("a", attrs=[], nixStatus="missing", nixVersion=None)
        self.assertEqual(shape.row_problems(missing), [])

    def test_twice_or_in_another_shard(self):
        data = files([row("a")], count=2)
        other = next(
            p for p in data if p.startswith("rows/") and not data[p]["packages"]
        )
        data[other]["packages"].append(row("a"))
        found = shape.problems(data)["rows"]
        self.assertIn("a: appears twice", found)
        own = datastore.shard_of("a", 2)
        self.assertIn(f"a: in {other}, but its shard is rows/{own}.json", found)


class Manifest(unittest.TestCase):
    def test_counts_against_the_rows(self):
        data = files([row("a")])
        data["index.json"]["packageCount"] = 2
        data["index.json"]["shardCount"] = 2
        self.assertEqual(
            shape.problems(data)["manifest"],
            [
                "shardCount is 2, but rows/ has 1",
                "packageCount is 2, but the shards hold 1 rows",
            ],
        )

    def test_views_lengths_and_their_rows(self):
        data = files([row("a")], views={"attention": [{"name": "a"}, {"name": "gone"}]})
        data["index.json"]["views"]["attention"] = 1
        found = shape.problems(data)
        self.assertEqual(found["views"], ["views/attention.json: 'gone' isn't a row"])
        self.assertEqual(
            found["manifest"],
            ["views.attention is 1; counted from views/attention.json: 2"],
        )

    def test_a_teams_count_against_its_view(self):
        data = files([row("a")], views={})
        data["index.json"]["views"]["teams"] = {"Security review": 2}
        data["views/team/security-review.json"] = {"packages": [{"name": "a"}]}
        self.assertEqual(
            shape.problems(data)["manifest"],
            [
                "views.teams.Security review is 2; "
                "counted from views/team/security-review.json: 1"
            ],
        )

    def test_an_empty_view_not_written(self):
        data = files([row("a")], views={})
        data["index.json"]["views"]["backport"] = 0
        self.assertEqual(shape.problems(data), {})
        data["index.json"]["views"]["backport"] = 1
        self.assertEqual(
            shape.problems(data)["manifest"],
            ["views.backport is 1; counted from views/backport.json: 0"],
        )

    def test_only_the_systems_nixpkgs_lists(self):
        # Listed for x86_64-linux only, failing on aarch64-linux too.
        one = row(
            "one",
            platforms={"linux": True, "darwin": False, "systems": ["x86_64-linux"]},
            builds=[
                {"system": "x86_64-linux", "status": "failed"},
                {"system": "aarch64-linux", "status": "failed"},
            ],
        )
        counts = {
            "buildFailures": 1,
            "buildFailuresOn": {"linux": 1, "x86_64-linux": 1, "aarch64-linux": 0},
        }
        self.assertEqual(shape.problems(files([one], {"attention": [one]}, counts)), {})

    def test_build_failures_as_the_page_counts_them(self):
        rows = [FAILING_DARWIN, FAILING_LINUX]
        good = {"buildFailures": 2, "buildFailuresOn": {"darwin": 0, "linux": 1}}
        self.assertEqual(shape.problems(files(rows, {"attention": rows}, good)), {})
        # mygui fails on aarch64-darwin, where nixpkgs doesn't list it: not
        # Darwin's (nixkeeper-mcp counted it, 2026-10-24).
        bad = {"buildFailures": 2, "buildFailuresOn": {"darwin": 1, "linux": 1}}
        self.assertEqual(
            shape.problems(files(rows, {"attention": rows}, bad))["manifest"],
            [
                "counts.buildFailuresOn.darwin is 1; "
                "counted from views/attention.json: 0"
            ],
        )


class Malformed(unittest.TestCase):
    """Bad data is what the check looks for: it's reported, never raised."""

    def test_a_row_without_a_name(self):
        data = files([row("a")])
        data["rows/0.json"]["packages"].append({"attrs": []})
        self.assertEqual(shape.problems(data)["rows"], ["rows/0.json, row 1: no name"])

    def test_a_manifest_missing_or_without_its_counts(self):
        self.assertEqual(
            shape.problems({}),
            {"manifest": ["index.json is missing or isn't an object"]},
        )
        found = shape.problems({"index.json": {}})["manifest"]
        self.assertIn("shardCount is None, not a number of shards", found)
        self.assertIn("packageCount is None, but the shards hold 0 rows", found)

    def test_views_and_builds_without_what_they_should_have(self):
        data = files([row("a")], views={"attention": [{}, "not an entry"]})
        data["views/attention.json"]["packages"].append(
            {"name": "a", "builds": [{}, {"status": "failed"}, "a build"]}
        )
        data["index.json"]["counts"] = {
            "buildFailures": 0,
            "buildFailuresOn": {"darwin": 0},
        }
        found = shape.problems(data)
        self.assertIn("views/attention.json: None isn't a row", found["views"])
        # The failed build without a system counts as a failure, on no
        # platform in particular.
        self.assertIn(
            "counts.buildFailures is 0; counted from views/attention.json: 1",
            found["manifest"],
        )

    def test_a_file_in_rows_that_isnt_a_shard(self):
        # Said once: it isn't counted as a shard as well.
        data = files([row("a")])
        data["rows/notes.txt"] = "not JSON"
        self.assertEqual(
            shape.problems(data), {"rows": ["rows/notes.txt isn't a shard of rows"]}
        )

    def test_fields_of_the_wrong_kind(self):
        # From the review of #334: each crashed the check before.
        rows = [row("a")]

        def views(**manifest):
            data = files(rows, views={})
            data["index.json"].update(manifest)
            return data

        attention = files(rows, views={"attention": [{"name": ["a"]}]})
        systems = files(
            rows,
            views={
                "attention": [
                    {
                        "name": "a",
                        "platforms": {"darwin": True, "systems": 5},
                        "builds": [{"status": "failed", "system": "aarch64-darwin"}],
                    }
                ]
            },
            counts={"buildFailures": 1, "buildFailuresOn": {"darwin": 0}},
        )
        cases = {
            "views.teams a list": (
                views(views={"teams": ["Gaming"]}),
                {"manifest": ["views.teams is a list, not an object"]},
            ),
            "counts.buildFailuresOn a list": (
                views(counts={"buildFailuresOn": ["darwin"]}),
                {"manifest": ["counts.buildFailuresOn is a list, not an object"]},
            ),
            "a view entry named with a list": (
                attention,
                {"views": ["views/attention.json: ['a'] isn't a row"]},
            ),
            # Counted as not listed there: the Darwin count, 0, agrees.
            "platforms.systems a number": (systems, {}),
            "a team named with a number": (
                views(views={"teams": {1: 2}}),
                {"manifest": ["views.teams: 1 isn't a name"]},
            ),
        }
        for case, (data, expected) in cases.items():
            with self.subTest(case):
                self.assertEqual(shape.problems(data), expected)

    def test_random_damage_is_reported_never_raised(self):
        # The cases above are picked by hand; this keeps the promise as the
        # check grows: values at every depth replaced by others of any kind.
        failing = row(
            "a",
            platforms={"linux": True, "darwin": True, "systems": ["x86_64-linux"]},
            builds=[{"system": "x86_64-linux", "status": "failed"}],
        )
        valid = files(
            [failing, row("b", set="haskellPackages")],
            views={"attention": [failing]},
            counts={"buildFailures": 1, "buildFailuresOn": {"linux": 1}, "broken": 0},
        )
        valid["index.json"]["views"].update(
            {
                "teams": {"Gaming": 1},
                "sets": {"haskellPackages": {"packages": 1}},
                "broken": 0,
            }
        )
        valid["views/team/gaming.json"] = {"packages": [failing]}
        valid["views/set/haskellPackages.json"] = {"packages": [row("b")]}
        kinds = (None, 0, 7, "x", [], ["x", 1], {}, {"name": 1}, True)
        rng = random.Random(334)

        every = list(places(valid))
        for attempt in range(500):
            data = copy.deepcopy(valid)
            for path in rng.sample(every, rng.randint(1, 4)):
                if not path:
                    continue
                # An earlier change may have replaced a value on the way.
                parent = data
                for key in path[:-1]:
                    parent = reach(parent, key)
                if reach(parent, path[-1]) is not MISSING:
                    parent[path[-1]] = rng.choice(kinds)
            with self.subTest(attempt=attempt):
                self.assertIsInstance(shape.problems(data), dict)

    def test_the_guard_names_the_line_in_shape_py(self):
        # Raised beneath shape.py, from a function it calls: the log names
        # the line in shape.py that called it, not the function's own file.
        def broken(*args):
            return {}["x"]

        index = {"checkedAt": "2026-10-24T00:00:00+00:00", "packages": [row("a")]}
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(shape, "_check_rows", broken),
        ):
            log = io.StringIO()
            with contextlib.redirect_stderr(log):
                datastore.write(index, {}, out_dir=f"{d}/data")
        self.assertRegex(
            log.getvalue(), r"the check itself failed at shape\.py:\d+: KeyError\('x'\)"
        )

    def test_a_write_goes_on_if_the_check_itself_fails(self):
        index = {"checkedAt": "2026-10-24T00:00:00+00:00", "packages": [row("a")]}
        with (
            tempfile.TemporaryDirectory() as d,
            mock.patch.object(
                shape, "problems", side_effect=RuntimeError("a bug in the check")
            ),
        ):
            log = io.StringIO()
            with contextlib.redirect_stderr(log):
                datastore.write(index, {}, out_dir=f"{d}/data")
            self.assertTrue(Path(f"{d}/data/index.json").exists())
        self.assertRegex(
            log.getvalue(),
            r"Data shape: the check itself failed at \S+:\d+: "
            r"RuntimeError\('a bug in the check'\)",
        )


class Documented(unittest.TestCase):
    def test_every_field_in_data_md(self):
        docs = (Path(__file__).parent.parent / "docs" / "data.md").read_text()
        named = set(re.findall(r"`([A-Za-z]+)`", docs))
        self.assertEqual(sorted(shape.ROW.keys() - named), [])


class Typed(unittest.TestCase):
    """ROW, as made from the Row type."""

    def test_required_fields_are_row_fields(self):
        self.assertLessEqual(shape.REQUIRED, shape.Row.__annotations__.keys())
        self.assertEqual(
            {name for name, field in shape.ROW.items() if field.required},
            shape.REQUIRED,
        )

    def test_a_union_is_each_of_its_types(self):
        self.assertEqual(shape.ROW["nixVersion"].types, (str, type(None)))
        self.assertEqual(shape.ROW["notRefreshed"].types, (dict, list))
        self.assertEqual(shape.ROW["name"], shape.Field((str,), required=True))


class Report(unittest.TestCase):
    def test_how_many_and_the_first_few(self):
        out = io.StringIO()
        shape.report({"rows": [f"r{n}: twice" for n in range(7)]}, out)
        self.assertEqual(
            out.getvalue().splitlines(),
            [
                "Data shape: 7 rows problems",
                "  r0: twice",
                "  r1: twice",
                "  r2: twice",
                "  r3: twice",
                "  r4: twice",
                "  ... and 2 more",
            ],
        )
