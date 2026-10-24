"""nixkeeper.shape: what data/ must look like, checked before it's written."""

import re
import unittest
import zlib
from pathlib import Path

from nixkeeper import shape
from nixkeeper.datastore import slug


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


class Rows(unittest.TestCase):
    def test_well_formed(self):
        self.assertEqual(shape.problems(files([row("a"), row("b")], count=2), slug), {})

    def test_a_field_misspelt_missing_or_of_the_wrong_type(self):
        found = shape.problems(
            files([row("a", markedBroke=True), {"name": "b"}, row("c", openPRs=True)]),
            slug,
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
        found = shape.problems(data, slug)["rows"]
        self.assertIn("a: appears twice", found)
        self.assertIn(f"a: in {other}, not in its own shard", found)


class Manifest(unittest.TestCase):
    def test_counts_against_the_rows(self):
        data = files([row("a")])
        data["index.json"]["packageCount"] = 2
        data["index.json"]["shardCount"] = 2
        self.assertEqual(
            shape.problems(data, slug)["manifest"],
            ["shardCount 2, but 1 shards", "packageCount 2, rows 1"],
        )

    def test_views_lengths_and_their_rows(self):
        data = files([row("a")], views={"attention": [{"name": "a"}, {"name": "gone"}]})
        data["index.json"]["views"]["attention"] = 1
        found = shape.problems(data, slug)
        self.assertEqual(found["views"], ["views/attention.json: 'gone' isn't a row"])
        self.assertEqual(
            found["manifest"], ["views.attention is 1, but its view has 2"]
        )

    def test_a_teams_count_against_its_view(self):
        data = files([row("a")], views={})
        data["index.json"]["views"]["teams"] = {"Security review": 2}
        data["views/team/security-review.json"] = {"packages": [{"name": "a"}]}
        self.assertEqual(
            shape.problems(data, slug)["manifest"],
            ["views.teams.Security review is 2, but its view has 1"],
        )

    def test_an_empty_view_not_written(self):
        data = files([row("a")], views={})
        data["index.json"]["views"]["backport"] = 0
        self.assertEqual(shape.problems(data, slug), {})
        data["index.json"]["views"]["backport"] = 1
        self.assertEqual(
            shape.problems(data, slug)["manifest"],
            ["views.backport is 1, but its view has 0"],
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
        self.assertEqual(
            shape.problems(files([one], {"attention": [one]}, counts), slug), {}
        )

    def test_build_failures_as_the_page_counts_them(self):
        rows = [FAILING_DARWIN, FAILING_LINUX]
        good = {"buildFailures": 2, "buildFailuresOn": {"darwin": 0, "linux": 1}}
        self.assertEqual(
            shape.problems(files(rows, {"attention": rows}, good), slug), {}
        )
        # mygui fails on aarch64-darwin, where nixpkgs doesn't list it: not
        # Darwin's (nixkeeper-mcp counted it, 2026-10-24).
        bad = {"buildFailures": 2, "buildFailuresOn": {"darwin": 1, "linux": 1}}
        self.assertEqual(
            shape.problems(files(rows, {"attention": rows}, bad), slug)["manifest"],
            ["counts.buildFailuresOn.darwin is 1, but the attention view has 0"],
        )


class Malformed(unittest.TestCase):
    """Bad data is what the check looks for: it's reported, never raised."""

    def test_a_row_without_a_name(self):
        data = files([row("a")])
        data["rows/0.json"]["packages"].append({"attrs": []})
        self.assertEqual(
            shape.problems(data, slug)["rows"], ["rows/0.json, row 1: no name"]
        )

    def test_a_manifest_missing_or_without_its_counts(self):
        self.assertEqual(
            shape.problems({}, slug),
            {"manifest": ["index.json is missing or isn't an object"]},
        )
        found = shape.problems({"index.json": {}}, slug)["manifest"]
        self.assertIn("shardCount is None, not a number of shards", found)
        self.assertIn("packageCount None, rows 0", found)

    def test_views_and_builds_without_what_they_should_have(self):
        data = files([row("a")], views={"attention": [{}, "not an entry"]})
        data["views/attention.json"]["packages"].append(
            {"name": "a", "builds": [{}, {"status": "failed"}, "a build"]}
        )
        data["index.json"]["counts"] = {
            "buildFailures": 0,
            "buildFailuresOn": {"darwin": 0},
        }
        found = shape.problems(data, slug)
        self.assertIn("views/attention.json: None isn't a row", found["views"])
        # The failed build without a system counts as a failure, on no
        # platform in particular.
        self.assertIn(
            "counts.buildFailures is 0, but the attention view has 1", found["manifest"]
        )

    def test_a_file_in_rows_that_isnt_a_shard(self):
        data = files([row("a")])
        data["rows/notes.txt"] = "not JSON"
        self.assertIn(
            "rows/notes.txt isn't a shard of rows", shape.problems(data, slug)["rows"]
        )

    def test_a_write_goes_on_if_the_check_itself_fails(self):
        import contextlib
        import io
        import tempfile
        from unittest import mock

        from nixkeeper import datastore

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
        self.assertIn(
            "Data shape: the check itself failed: RuntimeError('a bug in the check')",
            log.getvalue(),
        )


class Documented(unittest.TestCase):
    def test_every_field_in_data_md(self):
        docs = (Path(__file__).parent.parent / "docs" / "data.md").read_text()
        named = set(re.findall(r"`([A-Za-z]+)`", docs))
        self.assertEqual(sorted(shape.ROW.keys() - named), [])


class Report(unittest.TestCase):
    def test_how_many_and_the_first_few(self):
        import io

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
