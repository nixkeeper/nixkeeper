"""With every package tracked (config.all_packages): the lists' packages read
as always, the rest of nixpkgs in bulk only."""

import io
import json
import os
import tempfile
import unittest
from unittest import mock

from nixkeeper import config, datastore, history, sync, tracking
from nixkeeper import rows as rows_module
from nixkeeper.lookup import collect_projects
from nixkeeper.rows import build_rows
from nixkeeper.sources import github, hydra_digest, nixpkgs_update
from tests.helpers import nix, other, pkg

NOW = "2026-10-05T06:00:00+00:00"


class Setting(unittest.TestCase):
    def test_off_unless_turned_on(self):
        for value, on in (("", False), ("0", False), ("1", True), ("true", True)):
            with (
                mock.patch.object(config, "ALL_PACKAGES", None),
                mock.patch.dict(os.environ, {"NIXKEEPER_ALL_PACKAGES": value}),
            ):
                self.assertEqual(config.all_packages(), on, value)

    def test_the_command_wins(self):
        with (
            mock.patch.object(config, "ALL_PACKAGES", True),
            mock.patch.dict(os.environ, {"NIXKEEPER_ALL_PACKAGES": ""}),
        ):
            self.assertTrue(config.all_packages())


class Tracking(unittest.TestCase):
    def test_every_package_the_lists_dont_cover(self):
        nixpkgs = {
            "heroic": pkg("heroic"),
            "heroic-unwrapped": pkg("heroic"),
            "zlib": pkg("zlib"),
            "haskellPackages.zlib": pkg("zlib"),
        }
        listed = {"heroic": (["heroic", "heroic-unwrapped"], "heroic")}
        self.assertEqual(
            tracking.every_package(nixpkgs, listed),
            {
                "zlib": (["zlib"], "zlib"),
                "haskellPackages.zlib": (["haskellPackages.zlib"], "zlib"),
            },
        )

    def test_sets_updated_in_bulk_unless_listed(self):
        rows = [
            {"name": "haskellPackages.a", "attrs": ["haskellPackages.a"], "lists": []},
            {
                "name": "haskellPackages.b",
                "attrs": ["haskellPackages.b"],
                "lists": ["x"],
            },
            {
                "name": "python3Packages.c",
                "attrs": ["python313Packages.c"],
                "lists": [],
            },
            {"name": "d", "attrs": ["d"], "lists": []},
            # Not versioned software, listed or not: its builds only.
            {"name": "darwin.e", "attrs": ["darwin.e"], "lists": ["x"]},
        ]
        tracking.add_sets(rows)
        self.assertEqual(
            [(r.get("set"), r.get("unversioned")) for r in rows],
            [
                ("haskellPackages", None),
                (None, None),
                (None, None),
                (None, None),
                (None, True),
            ],
        )
        self.assertNotIn("pending", rows[0])


class Repology(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def collect(self, wanted, digest, previous=None):
        def resolve(*args, **kwargs):
            raise AssertionError("bulk packages are never looked up")

        return collect_projects(
            wanted,
            previous or {"packages": []},
            resolve=resolve,
            out_dir=self.dir.name,
            nixpkgs={"a": {"version": "2"}, "b": {"version": "1"}},
            now=NOW,
            digest=digest,
            bulk=set(wanted),
        )

    def test_from_the_digest_even_behind_the_channel(self):
        entries = [nix("a", "1", "outdated"), other("arch", "2", "newest")]
        projects = self.collect(
            {"a": (["a"], "a")}, {"a": ("a", entries, "2026-10-04")}
        )
        self.assertEqual(projects["a"]["entries"], entries)
        self.assertEqual(projects["a"]["checkedAt"], "2026-10-04T00:00:00+00:00")

    def test_not_on_repology(self):
        nixpkgs = {"b": {"version": "1", "pname": "b", "meta": {}}}
        projects = self.collect({"b": (["b"], "b")}, {})
        self.assertTrue(projects["unlisted:b"]["unlisted"])
        (row,) = build_rows(projects, nixpkgs)
        self.assertEqual((row["nixVersion"], row["nixStatus"]), ("1", "unlisted"))

    def test_never_joined_to_a_project_of_the_same_name(self):
        entries = [nix("python313Packages.c", "2", "newest")]
        projects = self.collect(
            {"python313Packages.c": (["python313Packages.c"], "c"), "c": (["c"], "c")},
            {"python313Packages.c": ("c", entries, "2026-10-04")},
        )
        self.assertEqual(projects["c"]["attrs"], ["python313Packages.c"])
        self.assertEqual(projects["unlisted:c"]["attrs"], ["c"])


def digest_row(attr, system, status, build="7", last=""):
    return {
        "attr": attr,
        "system": system,
        "status": status,
        "build": build,
        "finished": "2026-10-04T00:00:00Z",
        "name": f"{attr}-1",
        "lastSuccessBuild": last,
        "lastSuccessAt": "",
        "lastSuccessName": "",
    }


class Hydra(unittest.TestCase):
    JOBS = [
        ("ok", "x86_64-linux"),
        ("failing", "x86_64-linux"),
        ("queued", "x86_64-linux"),
        ("new", "x86_64-linux"),
        ("gone", "x86_64-linux"),
    ]

    def test_bulk_answers_never_ask(self):
        digest = {
            ("ok", "x86_64-linux"): digest_row("ok", "x86_64-linux", "ok"),
            ("failing", "x86_64-linux"): digest_row(
                "failing", "x86_64-linux", "failed"
            ),
            ("queued", "x86_64-linux"): digest_row("queued", "x86_64-linux", "queued"),
            ("new", "x86_64-linux"): digest_row("new", "x86_64-linux", "queued"),
        }
        before = {
            ("queued", "x86_64-linux"): {
                "attr": "queued",
                "system": "x86_64-linux",
                "status": "ok",
                "build": 5,
                "checkedAt": NOW,
            }
        }
        found = hydra_digest.bulk_answers(
            digest, self.JOBS, {"gone": ["x86_64-linux"]}, before
        )
        status = {attr: r["status"] for (attr, _), r in found.items()}
        self.assertEqual(
            status,
            {
                "ok": "ok",
                "failing": "failed",  # without its last success: the digest can't say
                "queued": "ok",  # the last sync's
                "new": "unknown",
                "gone": "broken",  # not in the evaluation, marked broken
            },
        )
        self.assertNotIn("lastSuccess", found["failing", "x86_64-linux"])
        self.assertNotIn("checkedAt", found["queued", "x86_64-linux"])

    def test_without_a_digest_as_the_last_sync_had_them(self):
        before = {
            ("ok", "x86_64-linux"): {
                "attr": "ok",
                "system": "x86_64-linux",
                "status": "ok",
            }
        }
        found = hydra_digest.bulk_answers(None, self.JOBS[:2], {}, before)
        self.assertEqual(found["ok", "x86_64-linux"]["status"], "ok")
        self.assertEqual(found["failing", "x86_64-linux"]["status"], "unknown")


class UpdateLogs(unittest.TestCase):
    def test_turns_outdated_and_failing_first_within_the_budget(self):
        nixpkgs = {n: pkg(n) for n in ("quiet", "outdated", "failing", "in-set")}
        rows = [
            {"name": "quiet", "attrs": ["quiet"], "nixStatus": "newest"},
            {"name": "outdated", "attrs": ["outdated"], "nixStatus": "outdated"},
            {"name": "failing", "attrs": ["failing"], "nixStatus": "newest"},
            {"name": "in-set", "attrs": ["in-set"], "set": "rPackages"},
        ]
        before = {"failing": {"name": "failing", "updateFailure": True, "update": {}}}
        dates = {n: nixpkgs_update.datetime.now(nixpkgs_update.UTC) for n in nixpkgs}
        with mock.patch.object(config, "UPDATE_LOGS_BUDGET", 2):
            turns = nixpkgs_update.bulk_turns(
                rows, nixpkgs, before, dates, NOW, {r["name"] for r in rows}
            )
        self.assertEqual(turns, {"outdated", "failing"})

    def test_unread_last_time_still_waits_its_turn(self):
        nixpkgs = {"a": pkg("a")}
        rows = [{"name": "a", "attrs": ["a"], "nixStatus": "newest"}]
        long_ago = nixpkgs_update.datetime(2026, 1, 1, tzinfo=nixpkgs_update.UTC)
        unread = {"a": {"name": "a", "update": None, "unread": ["update"]}}
        read = {"a": {"name": "a", "update": None}}
        for before, turns in ((unread, {"a"}), (read, set())):
            with mock.patch.object(config, "UPDATE_LOGS_BUDGET", 1):
                self.assertEqual(
                    nixpkgs_update.bulk_turns(
                        rows, nixpkgs, before, {"a": long_ago}, NOW, {"a"}
                    ),
                    turns,
                )

    def test_none_read_beyond_the_lists_for_now(self):
        nixpkgs = {"a": pkg("a")}
        rows = [{"name": "a", "attrs": ["a"], "nixStatus": "outdated"}]
        dates = {"a": nixpkgs_update.datetime.now(nixpkgs_update.UTC)}
        self.assertEqual(
            nixpkgs_update.bulk_turns(rows, nixpkgs, {}, dates, NOW, {"a"}), set()
        )

    def test_no_turns_without_the_sites_index(self):
        rows = [{"name": "a", "attrs": ["a"]}]
        self.assertEqual(
            nixpkgs_update.bulk_turns(rows, {"a": pkg("a")}, {}, None, NOW, {"a"}),
            set(),
        )


def row(name, **extra):
    return {
        "name": name,
        "attrs": [name],
        "nixStatus": "newest",
        "nixVersion": "1",
        **extra,
    }


class Data(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.out = os.path.join(self.dir.name, "data")

    def read(self, name):
        with open(os.path.join(self.out, name)) as f:
            return json.load(f)

    def test_the_day_befores_split_from_the_last_manifest(self):
        points = [
            {"day": "2026-10-05", "failed": 1619},
            {"day": "2026-10-06", "failed": 3151},
        ]
        # A manifest from before the split: its highlights' failing builds.
        previous = {
            "checkedAt": "2026-10-06T12:50:07+00:00",
            "counts": {"failed": 3151, "updateFailures": 2164},
            "highlights": {"failing": {"count": 1096}},
        }
        self.assertEqual(
            datastore.with_split(points, previous),
            [
                {"day": "2026-10-05", "failed": 1619},  # no manifest for it
                {
                    "day": "2026-10-06",
                    "failed": 3151,
                    "buildFailures": 1096,
                    "updateFailures": 2164,
                },
            ],
        )
        # A point that has them keeps its own; no manifest, nothing to add.
        recorded = [{"day": "2026-10-06", "buildFailures": 7, "updateFailures": 8}]
        self.assertEqual(datastore.with_split(recorded, previous), recorded)
        self.assertEqual(datastore.with_split(points, {}), points)

    def test_status_letters(self):
        self.assertEqual(datastore.status(row("a")), "u")
        self.assertEqual(datastore.status(row("a", nixStatus="outdated")), "o")
        self.assertEqual(datastore.status(row("a", updateFailure=True)), "f")
        self.assertEqual(datastore.status(row("a", nixStatus="unlisted")), "n")
        self.assertEqual(datastore.status(row("a", nixVulnerable=True)), "uv")
        insecure = row("a", markedInsecure=["CVE-2020-25031"])
        self.assertEqual(datastore.status(insecure), "uv")  # nixpkgs' own say
        # Unique with nothing compared: not up to date (pbar2); with a check
        # of nixkeeper's own, it is.
        alone = row("a", nixStatus="unique", onlyNixpkgs=True)
        self.assertEqual(datastore.status(alone), "n")
        checked = row(
            "a", nixStatus="unique", onlyNixpkgs=True, upstream={"version": "1"}
        )
        self.assertEqual(datastore.status(checked), "u")
        self.assertEqual(datastore.status(row("a", nixStatus="unique")), "u")
        waiting = row("a", nixStatus="outdated", refVersion="2", master="2")
        self.assertEqual(datastore.status(waiting), "m")

    def test_slug(self):
        self.assertEqual(datastore.slug("Security review"), "security-review")
        self.assertEqual(datastore.slug("Qt-KDE"), "qt-kde")

    def test_views_names_and_counts(self):
        rows = [
            row(
                "a",
                maintainers=["Iedame"],
                lists=["gaming-team"],
                teams=["Gaming"],
                dataFile="a.json",
            ),
            row(
                "b",
                nixStatus="outdated",
                maintainers=[],
                platforms={"linux": True, "darwin": False, "systems": ["x86_64-linux"]},
            ),
            row("c", updateFailure=True, maintainers=["iedame"]),
            row(
                "haskellPackages.d",
                set="haskellPackages",
                maintainers=[],
                markedBroken=True,
            ),
            row("e", nixVulnerable=True, maintainers=["someone"]),  # up to date
        ]
        datastore.write(
            {"checkedAt": NOW, "allPackages": True, "packages": rows},
            {"a.json": [nix("a", "1", "newest")]},
            self.out,
        )
        files = {
            os.path.relpath(os.path.join(d, f), self.out)
            for d, _, fs in os.walk(self.out)
            for f in fs
        }
        self.assertEqual(
            files,
            {
                "facets.json",
                "index.json",
                "maintainers.json",
                "names.json",
                "rows/0.json",
                "views/attention.json",
                "views/list/gaming-team.json",
                "views/maintainer/iedame.json",
                "views/maintainer/none.json",
                "views/maintainer/someone.json",
                "views/set/haskellPackages.json",
                "views/team/gaming.json",
            },
        )  # no summary.json, no per-project files
        index = self.read("index.json")
        self.assertNotIn("packages", index)
        self.assertEqual(
            index["counts"],
            {
                "broken": 0,
                "failingBuilds": 0,
                "tracked": 4,
                "outdated": 1,
                "failed": 1,
                "vulnerable": 1,
                "backport": 0,
                "updateFailures": 1,
                "buildFailures": 0,
                "waiting": 0,
                "inSets": 1,
                "buildFailuresOn": {},
            },
        )
        self.assertEqual(
            index["views"],
            {
                "attention": 3,
                "broken": 0,
                "blocked": 0,
                "backport": 0,
                "superseded": 0,
                "unbuilt": 0,
                "teams": {"Gaming": 1},
                "lists": {"gaming-team": 1},
                "sets": {
                    "haskellPackages": {
                        "packages": 1,
                        "outdated": 0,
                        "failed": 0,
                        "broken": 1,
                        "bar": {"failed": 0, "broken": 1, "outdated": 0},
                    }
                },
            },
        )
        names = lambda path: [p["name"] for p in self.read(path)["packages"]]  # noqa: E731
        self.assertEqual(names("views/attention.json"), ["b", "c", "e"])
        self.assertEqual(names("views/maintainer/iedame.json"), ["a", "c"])
        self.assertEqual(names("views/maintainer/none.json"), ["b"])  # not in a set
        # Every maintainer once, as first written (any case): packages,
        # outdated, failing.
        self.assertEqual(
            self.read("maintainers.json")["maintainers"],
            [["Iedame", 2, 0, 1], ["someone", 1, 0, 0]],
        )
        self.assertEqual(
            self.read("names.json")["names"],
            [
                ["a", "u"],
                ["b", "o"],
                ["c", "f"],
                ["e", "uv"],
                ["haskellPackages.d", "u", "haskellPackages"],
            ],
        )
        # Beside them, in their order: platforms' bits (1 x86_64-linux, 2
        # aarch64-linux, 4 Darwin; 7 unrestricted), maintainers and teams by
        # their place in the lists.
        self.assertEqual(
            self.read("facets.json"),
            {
                "handles": ["Iedame", "iedame", "someone"],
                "teams": ["Gaming"],
                "rows": [[7, [0], [0]], 1, [7, [1]], [7, [2]], 7],
            },
        )
        # The rows in full, and loaded back as usual.
        self.assertEqual(
            [r["name"] for r in datastore.load(self.out)["packages"]],
            ["a", "b", "c", "e", "haskellPackages.d"],
        )
        self.assertEqual(
            datastore.entries(rows[0], self.out), [nix("a", "1", "newest")]
        )

    def test_a_fix_to_backport_needs_attention(self):
        """Up to date and not vulnerable on unstable, but a CVE fixed there is
        still to backport: in the attention list (its tile), and its own."""
        rows = [
            row("f", backport=["CVE-2026-1"], maintainers=["iedame"]),
            row("g", maintainers=["iedame"]),
        ]
        datastore.write(
            {"checkedAt": NOW, "allPackages": True, "packages": rows}, {}, self.out
        )
        names = lambda path: [p["name"] for p in self.read(path)["packages"]]  # noqa: E731
        self.assertEqual(names("views/attention.json"), ["f"])
        self.assertEqual(names("views/backport.json"), ["f"])
        counts = self.read("index.json")["counts"]
        self.assertEqual((counts["backport"], counts["vulnerable"]), (1, 0))

    def test_update_prs_to_close(self):
        """An open update PR nixpkgs is already past: its own view, up to date
        or not, in a set or not (?view=superseded)."""
        pr = {"number": 1, "title": "t: 0.5 -> 0.12", "now": "0.12"}
        rows = [
            row("t", supersededPRs=[pr]),
            row("rPackages.u", set="rPackages", supersededPRs=[pr]),
            row("v"),
        ]
        datastore.write(
            {"checkedAt": NOW, "allPackages": True, "packages": rows}, {}, self.out
        )
        names = [p["name"] for p in self.read("views/superseded.json")["packages"]]
        self.assertEqual(names, ["rPackages.u", "t"])
        self.assertEqual(self.read("index.json")["views"]["superseded"], 2)

    def test_a_partial_run_removes_a_view_it_no_longer_writes(self):
        """A view that empties between syncs (its last PR to close gone, in
        an hourly check) isn't written: its old file is removed, while the
        view only the daily sync writes (datastore.MERGE_VIEW) stays."""
        pr = {"number": 1, "title": "t: 0.5 -> 0.12", "now": "0.12"}
        datastore.write(
            {
                "checkedAt": NOW,
                "allPackages": True,
                "packages": [row("t", supersededPRs=[pr])],
            },
            {},
            self.out,
            kept={datastore.MERGE_VIEW: {"checkedAt": NOW, "prs": []}},
        )
        self.assertTrue(os.path.exists(os.path.join(self.out, "views/superseded.json")))
        datastore.update(
            {"checkedAt": NOW, "allPackages": True, "packages": [row("t")]},
            {},
            self.out,
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.out, "views/superseded.json"))
        )
        self.assertTrue(os.path.exists(os.path.join(self.out, datastore.MERGE_VIEW)))
        self.assertEqual(self.read("index.json")["views"]["superseded"], 0)

    def test_set_bar_each_package_at_its_worst(self):
        def r(name, **more):
            return row(f"rPackages.{name}", set="rPackages", **more)

        rows = [
            r("a", nixStatus="outdated", markedBroken=True, updateFailure=True),
            r("b", nixStatus="outdated", markedBroken=True),
            r("c", nixStatus="outdated"),
            r("d", markedBroken=True),
            r("e"),
        ]
        datastore.write(
            {"checkedAt": NOW, "allPackages": True, "packages": rows}, {}, self.out
        )
        found = self.read("index.json")["views"]["sets"]["rPackages"]
        # The counts overlap; the bar's parts don't.
        self.assertEqual(
            (found["outdated"], found["broken"], found["failed"]), (3, 3, 1)
        )
        self.assertEqual(found["bar"], {"failed": 1, "broken": 2, "outdated": 1})

    def test_history_a_point_a_day(self):
        rows = [row("a"), row("b", nixStatus="outdated", markedBroken=True)]
        before = [
            {
                "day": "2026-10-04",
                "tracked": 2,
                "outdated": 0,
                "failed": 0,
                "vulnerable": 0,
                "broken": 0,
            },
            {
                "day": "2026-10-05",
                "tracked": 9,
                "outdated": 9,
                "failed": 9,
                "vulnerable": 9,
                "broken": 9,
            },  # an earlier sync today: replaced
        ]
        datastore.write(
            {"checkedAt": NOW, "allPackages": True, "packages": rows},
            {},
            self.out,
            history=before,
        )
        self.assertEqual(
            self.read("history.json")["points"],
            [
                before[0],
                {
                    "day": "2026-10-05",
                    "tracked": 2,
                    "outdated": 1,
                    "failed": 0,
                    "buildFailures": 0,
                    "updateFailures": 0,
                    "vulnerable": 0,
                    "broken": 1,
                },
            ],
        )
        self.assertEqual(
            datastore.read_history(self.out), self.read("history.json")["points"]
        )
        self.assertEqual(datastore.read_history(self.dir.name), [])
        self.assertEqual(
            [p["name"] for p in self.read("views/broken.json")["packages"]], ["b"]
        )

    def test_unbuilt_view(self):
        def builds(**on):
            return [{"attr": "x", "system": s, "status": st} for s, st in on.items()]

        both = {"linux": True, "darwin": True}
        rows = [
            # Listed for Darwin, built on Linux only: in the view.
            row(
                "juce",
                platforms=both,
                builds=builds(**{"x86_64-linux": "ok", "aarch64-darwin": "notBuilt"}),
            ),
            # Built everywhere listed: not.
            row(
                "fine",
                platforms=both,
                builds=builds(**{"x86_64-linux": "ok", "aarch64-darwin": "ok"}),
            ),
            # A set's: not (its set's line counts it).
            row(
                "haskellPackages.x",
                set="haskellPackages",
                platforms=both,
                builds=builds(**{"x86_64-linux": "ok", "aarch64-darwin": "notBuilt"}),
            ),
        ]
        datastore.write(
            {"checkedAt": NOW, "allPackages": True, "packages": rows}, {}, self.out
        )
        self.assertEqual(
            [p["name"] for p in self.read("views/unbuilt.json")["packages"]], ["juce"]
        )
        self.assertEqual(self.read("index.json")["views"]["unbuilt"], 1)

    def test_failing_builds_every_job(self):
        def builds(*statuses):
            return [
                {"attr": "x", "status": st, "system": "x86_64-linux"} for st in statuses
            ]

        rows = [
            row("a", builds=builds("failed", "dependency", "ok")),
            row("b", builds=builds("unfinished", "broken")),
            row(
                "haskellPackages.c",
                set="haskellPackages",
                builds=builds("failed"),
            ),
        ]
        datastore.write(
            {"checkedAt": NOW, "allPackages": True, "packages": rows}, {}, self.out
        )
        counts = self.read("index.json")["counts"]
        self.assertEqual(counts["failingBuilds"], 4)  # in sets too
        self.assertEqual(counts["failed"], 1)  # packages: their own build failed

    def test_build_failures_by_platform(self):
        def failed(*systems):
            return [{"attr": "x", "status": "failed", "system": s} for s in systems]

        rows = [
            row("a", builds=failed("x86_64-linux", "aarch64-linux")),  # Linux once
            row("b", builds=failed("aarch64-darwin")),
            row("c", builds=failed("aarch64-linux", "aarch64-darwin")),
            row("d", builds=[{"attr": "d", "status": "ok", "system": "x86_64-linux"}]),
            # Fails on Darwin (another attribute's build), but Linux-only: the
            # page's Darwin filter leaves it out, and so does the count.
            row(
                "f",
                platforms={"linux": True, "darwin": False},
                builds=failed("aarch64-darwin"),
            ),
            # The same within Linux: on x86_64-linux only.
            row(
                "g",
                platforms={"linux": True, "darwin": False, "systems": ["x86_64-linux"]},
                builds=failed("aarch64-linux"),
            ),
            row(
                "haskellPackages.e",
                set="haskellPackages",
                builds=failed("x86_64-linux"),
            ),  # in a set: not counted
        ]
        datastore.write(
            {"checkedAt": NOW, "allPackages": True, "packages": rows}, {}, self.out
        )
        counts = self.read("index.json")["counts"]
        self.assertEqual(counts["buildFailures"], 5)  # f and g too: any system
        self.assertEqual(
            counts["buildFailuresOn"],
            {
                "aarch64-darwin": 2,
                "aarch64-linux": 2,
                "darwin": 2,
                "linux": 2,
                "x86_64-linux": 1,
            },
        )

    def test_newest_repos_kept(self):
        entries = [
            nix("a", "1", "outdated"),
            other("old", "1", "outdated"),
            other("arch", "3", "newest"),
            other("arch", "2", "outdated"),
            other("rolling", "9", "rolling"),
            other("debian", "2", "outdated"),
        ]
        kept = datastore.newest_repos(entries, 2)
        self.assertEqual(
            [(e["repo"], e["version"]) for e in kept],
            [("nix_unstable", "1"), ("arch", "3"), ("debian", "2")],
        )

    def test_entries_kept_in_full_for_the_lists(self):
        many = [nix("a", "1", "newest")] + [
            other(f"r{i}", "1", "newest") for i in range(20)
        ]
        projects = {
            "a": {"dataFile": "a.json", "entries": many},
            "b": {"dataFile": "b.json", "entries": many},
        }
        rows = [
            {"dataFile": "a.json", "lists": ["x"]},
            {"dataFile": "b.json", "lists": []},
        ]
        kept = datastore.kept_entries(projects, rows)
        self.assertEqual(len(kept["a.json"]), 21)
        self.assertEqual(len(kept["b.json"]), 1 + config.REPOLOGY_ENTRIES_KEPT)


class FailingSince(unittest.TestCase):
    def build(self, status, last=None):
        b = {"attr": "a", "system": "x86_64-linux", "status": status}
        if last is not None:
            b["lastSuccess"] = last
        return b

    def test_new_failures_start_from_what_is_known(self):
        rows = [
            {
                "name": "a",
                "builds": [
                    self.build("failed", "2026-07-07T09:45:16+00:00"),
                    self.build("failed", "2026-09-01T00:00:00+00:00"),
                ],
            },
            {"name": "b", "builds": [self.build("failed")]},  # not known yet
            {"name": "c", "updateFailure": True, "update": {"date": "2026-10-02"}},
            {"name": "d", "builds": [self.build("dependency")]},  # not its own
        ]
        history.add_failing_since(rows, {"packages": []}, NOW)
        self.assertEqual(rows[0]["failingSince"], "2026-07-07T09:45:16+00:00")
        self.assertEqual(rows[1]["failingSince"], NOW)
        self.assertEqual(rows[2]["updateFailingSince"], "2026-10-02T00:00:00+00:00")
        self.assertNotIn("failingSince", rows[3])

    def test_hydras_last_success_over_what_was_carried(self):
        # Dated when nixkeeper first saw it fail (the last success not known
        # then): Hydra's date replaces it, earlier or later.
        previous = {"packages": [{"name": "a", "failingSince": NOW}]}
        rows = [
            {"name": "a", "builds": [self.build("failed", "2023-05-01T00:00:00+00:00")]}
        ]
        history.add_failing_since(rows, previous, NOW)
        self.assertEqual(rows[0]["failingSince"], "2023-05-01T00:00:00+00:00")

    def test_never_built_where_and_no_date(self):
        def never(system):  # Hydra: this job never succeeded
            return {**self.build("failed"), "system": system, "lastSuccess": None}

        previous = {"packages": [{"name": "a", "failingSince": NOW}]}
        rows = [
            {"name": "a", "builds": [never("aarch64-darwin"), never("x86_64-linux")]}
        ]
        history.add_failing_since(rows, previous, NOW)
        self.assertEqual(rows[0]["neverBuiltOn"], ["aarch64-darwin", "x86_64-linux"])
        self.assertNotIn("failingSince", rows[0])  # none of them has a date
        # Never on Darwin, failing on Linux since a success: dated by it.
        dated = {**self.build("failed", "2024-01-01T00:00:00+00:00")}
        rows = [{"name": "a", "builds": [never("aarch64-darwin"), dated]}]
        history.add_failing_since(rows, previous, NOW)
        self.assertEqual(rows[0]["failingSince"], "2024-01-01T00:00:00+00:00")
        self.assertEqual(rows[0]["neverBuiltOn"], ["aarch64-darwin"])
        # Never on Darwin, Linux's not known yet: carried for Linux's.
        rows = [
            {"name": "a", "builds": [never("aarch64-darwin"), self.build("failed")]}
        ]
        history.add_failing_since(rows, previous, NOW)
        self.assertEqual(rows[0]["failingSince"], NOW)
        # Fixed: gone.
        fixed = [
            {
                "name": "a",
                "builds": [self.build("ok")],
                "neverBuiltOn": ["x86_64-linux"],
            }
        ]
        history.add_failing_since(fixed, previous, NOW)
        self.assertNotIn("neverBuiltOn", fixed[0])

    def test_carried_over_then_dropped(self):
        previous = {
            "packages": [
                {
                    "name": "a",
                    "failingSince": "2026-01-01T00:00:00+00:00",
                    "updateFailingSince": "2026-02-01T00:00:00+00:00",
                }
            ]
        }
        still = [{"name": "a", "builds": [self.build("failed")], "updateFailure": True}]
        history.add_failing_since(still, previous, NOW)
        self.assertEqual(still[0]["failingSince"], "2026-01-01T00:00:00+00:00")
        self.assertEqual(still[0]["updateFailingSince"], "2026-02-01T00:00:00+00:00")
        fixed = [{"name": "a", "builds": [self.build("ok")], "failingSince": "x"}]
        history.add_failing_since(fixed, previous, NOW)
        self.assertNotIn("failingSince", fixed[0])
        self.assertNotIn("updateFailingSince", fixed[0])


class Highlights(unittest.TestCase):
    def test_newest_and_oldest(self):
        found = [
            ("2026-10-01T00:00:00+00:00", "b", "f", None),
            ("2026-09-01T00:00:00+00:00", "a", "f", None),
            ("2026-10-01T00:00:00+00:00", "a2", "f", None),
        ]
        got = datastore.highlights(found)
        self.assertEqual(got["count"], 3)
        self.assertEqual([e[0] for e in got["newest"]], ["a2", "b", "a"])
        self.assertEqual([e[0] for e in got["oldest"]], ["a", "a2", "b"])

    def test_a_family_is_one_entry(self):
        day = "2026-10-01T00:00:00+00:00"
        found = [(day, f"python313Packages.sdk{i}", "o", "fam1") for i in range(5)]
        found += [("2026-09-01T00:00:00+00:00", "lone", "o", None)]
        found += [(day, name, "o", "fam2") for name in ("x-one", "y-two")]
        got = datastore.highlights(found)
        self.assertEqual(got["count"], 8)  # the card counts packages
        newest = got["newest"]
        self.assertEqual(
            [e[0] for e in newest], ["python313Packages.sdk0", "x-one", "lone"]
        )
        self.assertEqual(newest[0][3], {"more": 4, "label": "python313Packages.sdk*"})
        self.assertEqual(newest[1][3], {"more": 1})  # nothing shared to name them
        self.assertEqual(len(newest[2]), 3)

    def test_an_update_waiting_for_the_channel_left_out(self):
        since = "2026-10-01T00:00:00+00:00"
        rows = [
            row("todo", nixStatus="outdated", refVersion="2", outdatedSince=since),
            row(
                "merged",
                nixStatus="outdated",
                refVersion="2",
                outdatedSince=since,
                master="2",
            ),
        ]
        index = datastore.views(rows, {})
        outdated = index["highlights"]["outdated"]
        self.assertEqual([n for n, _, _ in outdated["newest"]], ["todo"])
        self.assertEqual(outdated["count"], index["counts"]["outdated"])

    def test_in_the_manifest_fully_checked_only(self):
        rows = [
            row("old", nixStatus="outdated", outdatedSince="2026-01-01T00:00:00+00:00"),
            row(
                "haskellPackages.x",
                set="haskellPackages",
                failingSince="2026-01-01T00:00:00+00:00",
            ),
        ]
        with tempfile.TemporaryDirectory() as d:
            datastore.write(
                {"checkedAt": NOW, "allPackages": True, "packages": rows}, {}, d
            )
            with open(os.path.join(d, "index.json")) as f:
                found = json.load(f)["highlights"]
        self.assertEqual(
            found["outdated"]["oldest"], [["old", "2026-01-01T00:00:00+00:00", "o"]]
        )
        self.assertEqual(found["failing"]["count"], 0)  # in a set: left out

    def test_only_what_counts_now(self):
        # Dates the daily sync set, before the hourly checks recounted (a
        # change in how nixkeeper counts, a failure cleared): not listed, so
        # the lists match the cards.
        since = "2026-01-01T00:00:00+00:00"
        failed = [{"attr": "x", "status": "failed", "system": "x86_64-linux"}]
        rows = [
            row("outdated", nixStatus="outdated", outdatedSince=since),
            row("caught-up", nixStatus="newest", outdatedSince=since),
            row("failing", builds=failed, failingSince=since),
            row("built", builds=[], failingSince=since),
            # Never built: counted, no date to list.
            row("never", builds=failed, neverBuiltOn=["x86_64-linux"]),
            row("bot-fails", updateFailure=True, updateFailingSince=since),
            row("bot-fixed", updateFailure=False, updateFailingSince=since),
            # Newly outdated, its date not set yet: counted, not listed.
            row("newly", nixStatus="outdated"),
        ]
        with tempfile.TemporaryDirectory() as d:
            datastore.write(
                {"checkedAt": NOW, "allPackages": True, "packages": rows}, {}, d
            )
            with open(os.path.join(d, "index.json")) as f:
                index = json.load(f)
        found, counts = index["highlights"], index["counts"]
        self.assertEqual(found["outdated"]["count"], counts["outdated"])
        self.assertEqual(counts["outdated"], 2)
        self.assertEqual([n for n, _, _ in found["outdated"]["newest"]], ["outdated"])
        self.assertEqual(found["failing"]["count"], counts["buildFailures"])
        self.assertEqual([n for n, _, _ in found["failing"]["newest"]], ["failing"])
        self.assertEqual(found["updateFailing"]["count"], counts["updateFailures"])
        self.assertEqual(
            [n for n, _, _ in found["updateFailing"]["newest"]], ["bot-fails"]
        )


class Fixed(unittest.TestCase):
    """What a sync counts as fixed (history.fixes): only with something to
    show it, so a late source or a change in how nixkeeper counts doesn't
    look like a wave of fixes."""

    OK = {"status": "ok", "system": "x86_64-linux"}
    FAILED = {"status": "failed", "system": "x86_64-linux"}

    def fixes(self, before, now):
        return [
            (f["name"], f["kind"])
            for f in history.fixes(now, {"packages": before}, NOW)
        ]

    def test_a_build_fixed(self):
        before = [row("a", failingSince="2026-09-01", builds=[self.FAILED])]
        self.assertEqual(
            self.fixes(before, [row("a", builds=[self.OK])]), [("a", "build")]
        )
        # No build says so (Hydra not read, or queued): not a fix.
        self.assertEqual(self.fixes(before, [row("a", builds=[])]), [])
        # Never built before, built now: fixed too.
        never = [row("a", neverBuiltOn=["x86_64-linux"], builds=[self.FAILED])]
        self.assertEqual(
            self.fixes(never, [row("a", builds=[self.OK])]), [("a", "build")]
        )

    def test_updated_only_with_a_new_version(self):
        before = [row("a", nixStatus="outdated", nixVersion="1")]
        [fix] = history.fixes([row("a", nixVersion="2")], {"packages": before}, NOW)
        self.assertEqual((fix["kind"], fix["from"], fix["to"]), ("update", "1", "2"))
        # The same version, no longer counted as outdated (Repology changed
        # its mind, or nixkeeper its rules): not an update.
        self.assertEqual(self.fixes(before, [row("a", nixVersion="1")]), [])
        # Repology not reached: its data is old, nothing to say.
        self.assertEqual(
            self.fixes(before, [row("a", nixVersion="2", staleSince=NOW)]), []
        )

    def test_the_bots_failure_cleared(self):
        failed = {"outcome": "failed", "date": "2026-09-20"}
        before = [row("a", updateFailure=True, update=failed)]
        newer = {"outcome": "prOpened", "date": "2026-10-04"}
        self.assertEqual(self.fixes(before, [row("a", update=newer)]), [("a", "bot")])
        superseded = {**failed, "supersededOn": "2026-10-04"}
        self.assertEqual(
            self.fixes(before, [row("a", update=superseded)]), [("a", "bot")]
        )
        # Not read this time: nothing known.
        self.assertEqual(
            self.fixes(before, [row("a", update=newer, unread=["update"])]), []
        )

    def test_credited_to_the_pr(self):
        master_pr = {"number": 7, "author": "alice", "mergedBy": "bob", "to": "2"}
        before = [row("a", nixStatus="outdated", nixVersion="1", masterPR=master_pr)]
        [fix] = history.fixes([row("a", nixVersion="2")], {"packages": before}, NOW)
        self.assertEqual(
            {k: fix[k] for k in ("pr", "author", "mergedBy")},
            {"pr": 7, "author": "alice", "mergedBy": "bob"},
        )
        self.assertNotIn("likely", fix)
        # A build fix: likely, to the PR merged since it began failing.
        build_pr = {"number": 8, "author": "carol", "mergedBy": "nixpkgs-ci"}
        failing = [
            row(
                "b",
                failingSince="2026-09-01",
                builds=[self.FAILED],
                buildFixPR=build_pr,
            )
        ]
        [fix] = history.fixes([row("b", builds=[self.OK])], {"packages": failing}, NOW)
        self.assertEqual((fix["pr"], fix["likely"]), (8, True))
        # No PR seen: no credit, never a wrong one.
        plain = [row("c", nixStatus="outdated", nixVersion="1")]
        [fix] = history.fixes([row("c", nixVersion="2")], {"packages": plain}, NOW)
        self.assertNotIn("pr", fix)
        # The overview's summary carries it.
        summary = datastore.fixed_summary(
            [
                {
                    "at": NOW,
                    "name": "a",
                    "kind": "update",
                    "from": "1",
                    "to": "2",
                    "pr": 7,
                    "author": "alice",
                    "mergedBy": "bob",
                }
            ],
            NOW,
        )
        self.assertEqual(
            summary["update"]["newest"][0][4],
            {"pr": 7, "author": "alice", "mergedBy": "bob"},
        )

    def test_a_familys_fixes_are_one_entry(self):
        before = [
            row(
                f"m-{i}",
                updateFailure=True,
                update={"date": "2026-09-20"},
                family="f1",
                updateFailingSince="2026-09-20T00:00:00+00:00",
            )
            for i in range(3)
        ]
        now = [row(f"m-{i}", update={"date": "2026-10-04"}) for i in range(3)]
        found = history.fixes(now, {"packages": before}, NOW)
        self.assertEqual({f["family"] for f in found}, {"f1"})
        [entry] = datastore.fixed_summary(found, NOW)["bot"]["newest"]
        self.assertEqual(entry[0], "m-0")
        self.assertEqual(entry[6], {"more": 2})  # "m-" is too short to name

    def test_kept_on_the_package_a_month(self):
        old = {"at": "2026-09-01T06:00:00+00:00", "kind": "build"}
        week = {"at": "2026-09-30T06:00:00+00:00", "kind": "build", "pr": 3}
        before = {"packages": [row("a", recentFixes=[week, old]), row("b")]}
        today = {"at": NOW, "name": "a", "kind": "update", "from": "1", "to": "2"}
        rows = [row("a"), row("b")]
        history.add_recent_fixes(rows, before, [today], NOW)
        # Newest first, the month-old one gone; without the name.
        self.assertEqual(
            rows[0]["recentFixes"],
            [{"at": NOW, "kind": "update", "from": "1", "to": "2"}, week],
        )
        self.assertNotIn("recentFixes", rows[1])

    def test_not_new_removed_or_in_a_set(self):
        failing = row("a", failingSince="2026-09-01", builds=[self.FAILED])
        self.assertEqual(self.fixes([], [row("a", builds=[self.OK])]), [])  # new
        self.assertEqual(self.fixes([failing], []), [])  # removed
        in_set = {**failing, "set": "rPackages"}
        self.assertEqual(
            self.fixes([in_set], [row("a", builds=[self.OK], set="rPackages")]), []
        )

    def test_kept_a_month_once_a_day_and_summed_up(self):
        old = {"at": "2026-09-01T06:00:00+00:00", "name": "x", "kind": "build"}
        week = {"at": "2026-09-30T06:00:00+00:00", "name": "y", "kind": "build"}
        today = {"at": NOW, "name": "z", "kind": "update", "from": "1", "to": "2"}
        kept = datastore.with_fixed([old, week], [today, today], NOW)
        self.assertEqual([f["name"] for f in kept], ["y", "z"])  # x: over a month
        summary = datastore.fixed_summary(kept, NOW)
        self.assertEqual(summary["days"], 7)
        self.assertEqual(summary["build"]["count"], 1)  # y, 5 days before
        self.assertEqual(summary["update"]["newest"], [["z", NOW, "1", "2"]])

    def test_the_longest_standing_first(self):
        before = [
            row("a", failingSince="2026-06-01", builds=[self.FAILED]),
            row("b", nixStatus="outdated", nixVersion="1", outdatedSince="2026-09-28"),
        ]
        found = history.fixes(
            [row("a", builds=[self.OK]), row("b", nixVersion="2")],
            {"packages": before},
            NOW,
        )
        self.assertEqual(
            {f["name"]: f["since"] for f in found},
            {"a": "2026-06-01", "b": "2026-09-28"},
        )

        def fixed(name, **more):
            return {"at": NOW, "name": name, "kind": "build", **more}

        summary = datastore.fixed_summary(
            [
                fixed("days", since="2026-10-01T00:00:00+00:00"),
                fixed("unknown"),
                fixed("months", since="2026-06-01", pr=3),
                fixed("weeks", since="2026-09-10"),
            ],
            NOW,
        )
        shown = summary["build"]["newest"]
        self.assertEqual([e[0] for e in shown], ["months", "weeks", "days", "unknown"])
        # Credit and since when, a null between only where needed.
        self.assertEqual(shown[0][4:], [{"pr": 3}, "2026-06-01"])
        self.assertEqual(shown[1][4:], [None, "2026-09-10"])
        self.assertEqual(len(shown[3]), 4)
        self.assertEqual(summary["bot"], {"count": 0, "newest": []})

    def test_written_with_the_history(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "data")
            fix = {"at": NOW, "name": "a", "kind": "build"}
            datastore.write(
                {"checkedAt": NOW, "allPackages": True, "packages": [row("a")]},
                {},
                out,
                history=[],
                fixed=[fix],
            )
            self.assertEqual(datastore.read_fixed(out), [fix])
            with open(os.path.join(out, "index.json")) as f:
                self.assertEqual(json.load(f)["fixed"]["build"]["count"], 1)


class TrendEvents(unittest.TestCase):
    """What marks the overview's trends: staging-next merged into master,
    and nixkeeper updated (sync.trend_events, datastore.with_events)."""

    MERGED = {
        "search": {
            "nodes": [
                {
                    "number": 566094,
                    "title": "staging-next 2026-09-23",
                    "mergedAt": "2026-09-28T17:40:27Z",
                },
                {},  # an issue, or a node GitHub couldn't fill
            ]
        }
    }

    def test_staging_next_merges(self):
        with mock.patch.object(github, "graphql", return_value=self.MERGED) as asked:
            found = github.staging_next_merges("token", "2026-09-05")
        self.assertEqual(
            found,
            [
                {
                    "day": "2026-09-28",
                    "kind": "staging-next",
                    "pr": 566094,
                    "title": "staging-next 2026-09-23",
                }
            ],
        )
        self.assertIn("merged:>=2026-09-05", asked.call_args.args[2]["q"])
        self.assertIsNone(github.staging_next_merges(None, "2026-09-05"))  # no token
        with (
            mock.patch.object(github, "graphql", side_effect=OSError("down")),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            self.assertIsNone(github.staging_next_merges("token", "2026-09-05"))

    def test_nixkeeper_updated_since_the_last_sync(self):
        with (
            mock.patch.object(github, "staging_next_merges", return_value=None),
            mock.patch.object(github, "token", return_value=None),
            mock.patch.object(sync, "version", return_value="0.12.0"),
            mock.patch.object(config, "COUNTING_CHANGES", []),
        ):
            self.assertEqual(
                sync.trend_events({"version": "0.11.0"}, NOW),
                [
                    {
                        "day": "2026-10-05",
                        "kind": "nixkeeper",
                        "version": "0.12.0",
                        "from": "0.11.0",
                    }
                ],
            )
            self.assertEqual(sync.trend_events({"version": "0.12.0"}, NOW), [])
            self.assertEqual(sync.trend_events({}, NOW), [])  # the first sync

    def test_a_counting_change_on_the_first_day_it_ran(self):
        change = {"merged": "2026-10-04T09:00:00+00:00", "text": "older versions"}
        quiet = (
            mock.patch.object(github, "staging_next_merges", return_value=None),
            mock.patch.object(github, "token", return_value=None),
            mock.patch.object(config, "COUNTING_CHANGES", [change]),
            mock.patch.object(datastore, "read_events", return_value=[]),
        )
        with quiet[0], quiet[1], quiet[2], quiet[3]:
            # The last sync came after it was merged: it ran with it (main).
            after = {"checkedAt": "2026-10-04T12:00:00+00:00"}
            self.assertEqual(
                sync.trend_events(after, NOW),
                [{"day": "2026-10-04", "kind": "counting", "text": "older versions"}],
            )
            # Before: this sync is the first with it.
            before = {"checkedAt": "2026-10-04T06:00:00+00:00"}
            self.assertEqual(sync.trend_events(before, NOW)[0]["day"], "2026-10-05")
        # Marked once: a later sync leaves it.
        with (
            quiet[0],
            quiet[1],
            quiet[2],
            mock.patch.object(
                datastore, "read_events", return_value=[{"text": "older versions"}]
            ),
        ):
            self.assertEqual(sync.trend_events(after, NOW), [])

    def test_kept_once_each_a_year(self):
        old = {"day": "2025-09-01", "kind": "staging-next", "pr": 1, "title": "old"}
        merge = {
            "day": "2026-09-28",
            "kind": "staging-next",
            "pr": 566094,
            "title": "x",
        }
        update = {
            "day": "2026-10-05",
            "kind": "nixkeeper",
            "version": "0.12.0",
            "from": "0.11.0",
        }
        kept = datastore.with_events([old, merge], [merge, update], NOW)
        self.assertEqual(kept, [merge, update])  # old: over a year; merge once
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "data")
            datastore.write(
                {"checkedAt": NOW, "allPackages": True, "packages": [row("a")]},
                {},
                out,
                history=[],
                events=kept,
            )
            self.assertEqual(datastore.read_events(out), kept)


class Blockers(unittest.TestCase):
    """Which dependency stopped a build (nixkeeper-hydra's blockedBy): named
    as the rows are, and counted for the overview's "Blocking the most"."""

    def test_named_as_the_rows_are(self):
        rows = [
            row(
                "python313Packages.python-ldap",
                attrs=[
                    "python313Packages.python-ldap",
                    "python314Packages.python-ldap",
                ],
            ),
            row(
                "mealie",
                builds=[
                    {
                        "status": "dependency",
                        "system": "x86_64-linux",
                        "blockedBy": ["python314Packages.python-ldap", "source"],
                    }
                ],
            ),
        ]
        rows_module.name_blockers(rows)
        self.assertEqual(
            rows[1]["builds"][0]["blockedBy"],
            [
                {"name": "python313Packages.python-ldap", "row": True},
                {"name": "source"},
            ],
        )
        rows_module.name_blockers(rows)  # a second time: unchanged
        self.assertEqual(rows[1]["builds"][0]["blockedBy"][1], {"name": "source"})

    def test_staging_next_counted_apart(self):
        # Stopped on staging-next only (branches.apply_staging_next_blocked):
        # their own count, not master's.
        def sn(*by):
            return {
                "eval": 1830302,
                "evaluatedAt": "2026-10-16T01:08:22Z",
                "builds": [{"system": "x86_64-linux", "build": "1", "by": list(by)}],
            }

        clang = {"name": "clang-rocm", "row": True}
        rows = [
            row("blender", stagingNextBlockedBy=sn(clang)),
            row("hipblas", stagingNextBlockedBy=sn(clang)),
            row("aft", stagingNextBlockedBy=sn({"name": "Grpc.Tools-2.55.1"})),
        ]
        found = datastore.views(rows, {})["blockers"]
        self.assertEqual(found["count"], 0)  # master's: none
        self.assertEqual(
            found["stagingNext"],
            {
                "eval": 1830302,
                "evaluatedAt": "2026-10-16T01:08:22Z",
                "count": 2,
                "packages": 3,
                "top": [["clang-rocm", True, 2, 2], ["Grpc.Tools-2.55.1", False, 1, 1]],
            },
        )
        # None stopped there: no stagingNext at all.
        self.assertNotIn("stagingNext", datastore.views([row("x")], {})["blockers"])

    def test_counted_and_kept_in_the_list(self):
        ldap = {"name": "python-ldap", "row": True}

        def blocked(*systems, by=ldap):
            return [
                {"status": "dependency", "system": s, "blockedBy": [by]}
                for s in systems
            ]

        rows = [
            row("mealie", builds=blocked("x86_64-linux", "aarch64-linux")),
            row("conpass", builds=blocked("x86_64-linux")),
            row(
                "haskellPackages.x",
                set="haskellPackages",
                builds=blocked("x86_64-linux", by={"name": "source"}),
            ),
            row(
                "python-ldap",
                builds=[
                    {
                        "attr": "python-ldap",
                        "status": "failed",
                        "system": "x86_64-linux",
                    }
                ],
            ),
        ]
        # Blocked, its blocker not read yet: stopped all the same.
        rows.append(
            row("unread", builds=[{"status": "dependency", "system": "x86_64-linux"}])
        )
        out = {}
        made = datastore.views(rows, out)
        found = made["blockers"]
        self.assertEqual(found["count"], 2)
        self.assertEqual(found["packages"], 4)  # in sets too
        # The packages stopped, each once, for the card's "Show all".
        self.assertEqual(
            [p["name"] for p in out["views/blocked.json"]["packages"]],
            ["mealie", "conpass", "haskellPackages.x", "unread"],
        )
        self.assertEqual(made["views"]["blocked"], 4)
        self.assertEqual(
            found["top"], [["python-ldap", True, 2, 3], ["source", False, 1, 1]]
        )
        self.assertEqual(
            datastore.summary_entry(rows[0])["builds"][0],
            {"status": "dependency", "system": "x86_64-linux", "blockedBy": [ldap]},
        )
        # A failed build: why, for the list's filter; its lines, the panel's.
        failed = row(
            "aerogramme",
            builds=[
                {
                    "status": "failed",
                    "system": "x86_64-linux",
                    "failedBecause": "compile",
                    "failedExcerpt": "error: could not compile `rustix`",
                }
            ],
        )
        self.assertEqual(
            datastore.summary_entry(failed)["builds"][0],
            {"status": "failed", "system": "x86_64-linux", "failedBecause": "compile"},
        )
        # nixkeeper-prs' findings: the panel's only.
        found = {
            **row("wine"),
            "openPR": {"number": 1, "facts": {"mergeBot": "ready"}},
            "fixPRs": [{"number": 3}],
            "issueChecks": [{"number": 7}],
            "otherPRs": [{"number": 5}],
            "dropPR": {"number": 5, "title": "wine: drop"},
        }
        entry = datastore.summary_entry(found)
        self.assertEqual(entry["openPR"], {"number": 1})
        self.assertNotIn("fixPRs", entry)
        self.assertNotIn("issueChecks", entry)
        self.assertNotIn("otherPRs", entry)
        # Being removed: the list's badge.
        self.assertEqual(entry["dropPR"], {"number": 5, "title": "wine: drop"})
