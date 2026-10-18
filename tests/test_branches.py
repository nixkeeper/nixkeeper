import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import changes, config
from nixkeeper.sources import about, branches

NOW = "2026-10-08T06:00:00+00:00"
# Trimmed from nixkeeper-hydra's haskell-updates.json.gz (evaluation 1829685).
DIGEST = {
    "format": 1,
    "jobset": "nixpkgs/haskell-updates",
    "eval": 1829685,
    "fetchedAt": "2026-10-07T12:17:00+00:00",
    "columns": ["attr", "system", "build", "status", "name"],
    "jobs": [
        ["haskellPackages.Agda", "x86_64-linux", "347795412", "failed", "Agda-2.8.0.2"],
        [
            "haskellPackages.Cabal-hooks",
            "x86_64-linux",
            "347795500",
            "ok",
            "Cabal-hooks-3.18",
        ],
        [
            "haskellPackages.amazonka-lookoutequipment",
            "x86_64-linux",
            "347796162",
            "ok",
            "amazonka-lookoutequipment-2.0-unstable-2026-06-10",
        ],
        ["haskellPackages.other", "aarch64-linux", "1", "ok", "other-1.0"],
    ],
}


class Load(unittest.TestCase):
    def setUp(self):
        about.taken()
        for patcher in (
            mock.patch("sys.stderr", io.StringIO()),
            # The tests turn the digests off (tests/__init__.py): on, here.
            mock.patch.object(config, "HYDRA_DIGEST_URL", "https://example.org/data/"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def serve(self, body):
        data = None if body is None else gzip.compress(json.dumps(body).encode())
        return mock.patch.object(branches.http, "get_bytes", return_value=data)

    def test_its_jobs_and_versions(self):
        with self.serve(DIGEST):
            jobs = branches.load("haskell-updates", NOW)
        self.assertEqual(
            jobs["haskellPackages.Agda"],
            {"version": "2.8.0.2", "status": "failed", "build": "347795412"},
        )
        self.assertEqual(jobs["haskellPackages.Cabal-hooks"]["version"], "3.18")
        self.assertNotIn("haskellPackages.other", jobs)  # not x86_64-linux
        noted = about.taken()["branch:haskell-updates"]
        self.assertEqual(
            (noted["used"], noted["eval"], noted["jobs"]), (True, 1829685, 3)
        )

    def test_old_or_missing(self):
        with self.serve({**DIGEST, "fetchedAt": "2026-10-05T00:00:00+00:00"}):
            self.assertIsNone(branches.load("haskell-updates", NOW))
        self.assertEqual(about.taken()["branch:haskell-updates"]["why"], "too old")
        with self.serve(None):
            self.assertIsNone(branches.load("haskell-updates", NOW))

    def test_only_when_tracked(self):
        self.assertEqual(
            branches.wanted(["haskellPackages.Agda", "zlib"]), ["haskell-updates"]
        )
        self.assertEqual(branches.wanted(["zlib"]), [])


class Apply(unittest.TestCase):
    def test_rows_get_what_the_branch_has(self):
        rows = [
            {"name": "haskellPackages.Agda", "attrs": ["haskellPackages.Agda"]},
            {"name": "zlib", "attrs": ["zlib"]},
        ]
        jobs = {
            "haskellPackages.Agda": {
                "version": "2.8.0.2",
                "status": "failed",
                "build": "1",
            }
        }
        branches.apply(rows, "haskell-updates", jobs)
        self.assertEqual(
            rows[0]["branch"],
            {
                "name": "haskell-updates",
                "version": "2.8.0.2",
                "status": "failed",
                "build": "1",
            },
        )
        self.assertNotIn("branch", rows[1])


class OnBranch(unittest.TestCase):
    def row(self, version, **extra):
        return {
            "nixStatus": "outdated",
            "nixVersion": "3.16",
            "refVersion": "3.18",
            "branch": {"name": "haskell-updates", "version": version},
            **extra,
        }

    def test_waiting_for_the_branchs_merge(self):
        self.assertTrue(changes.on_branch(self.row("3.18")))
        self.assertTrue(changes.on_branch(self.row("3.19")))  # newer still
        self.assertFalse(changes.on_branch(self.row("3.17")))  # not there yet
        self.assertFalse(changes.on_branch(self.row("3.18", nixStatus="newest")))
        self.assertFalse(
            changes.on_branch({"nixStatus": "outdated", "refVersion": "1"})
        )


if __name__ == "__main__":
    unittest.main()


class StagingNext(unittest.TestCase):
    """staging-next's builds, for the updates on their way there."""

    DIGEST = {
        "format": 1,
        "jobset": "nixpkgs/staging-next",
        "eval": 1830302,
        "evaluatedAt": "2026-10-16T01:08:22Z",
        "fetchedAt": "2026-10-16T02:15:00+00:00",
        "columns": ["attr", "system", "build", "status", "name"],
        "jobs": [
            ["coreutils", "aarch64-darwin", "3", "ok", "coreutils-9.12"],
            ["coreutils", "x86_64-linux", "1", "ok", "coreutils-9.12"],
            ["harfbuzz", "x86_64-linux", "7", "ok", "harfbuzz-14.5.1"],
            ["hatchling", "x86_64-linux", "8", "ok", "hatchling-1.31.0"],
            ["imagemagick", "x86_64-linux", "4", "ok", "imagemagick-7.1.2-33"],
            ["openssh", "aarch64-darwin", "6", "failed", "openssh-10.6p1"],
            ["openssh", "x86_64-linux", "5", "ok", "openssh-10.6p1"],
        ],
    }
    NOW = "2026-10-16T03:00:00+00:00"

    def setUp(self):
        about.taken()
        for patcher in (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch.object(config, "HYDRA_DIGEST_URL", "https://example.org/data/"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def load(self, body):
        data = gzip.compress(json.dumps(body).encode())
        with mock.patch.object(branches.http, "get_bytes", return_value=data):
            return branches.load_staging_next(self.NOW)

    def row(self, name, to):
        return {
            "name": name,
            "attrs": [name],
            "stagingPR": {"number": 1, "to": to, "on": "staging-next"},
        }

    def test_how_the_updates_build_there(self):
        found = self.load(self.DIGEST)
        rows = [
            self.row("coreutils", "9.12"),
            self.row("openssh", "10.6p1"),
            self.row("imagemagick", "7.1.2-34"),  # merged after the evaluation
            {
                "name": "curl",
                "attrs": ["curl"],
                "stagingPR": {"number": 2, "to": "8.23.0", "on": "staging"},
            },  # not there yet
        ]
        branches.apply_staging_next(rows, found)
        coreutils, openssh, imagemagick, curl = (r["stagingPR"] for r in rows)
        self.assertEqual(
            [(b["system"], b["status"]) for b in coreutils["builds"]],
            [("aarch64-darwin", "ok"), ("x86_64-linux", "ok")],
        )
        self.assertEqual(
            coreutils["eval"], {"eval": 1830302, "evaluatedAt": "2026-10-16T01:08:22Z"}
        )
        self.assertEqual([b["status"] for b in openssh["builds"]], ["failed", "ok"])
        self.assertEqual((imagemagick["inEval"], imagemagick["builds"]), (False, []))
        self.assertNotIn("builds", curl)
        self.assertEqual(about.taken()["branch:staging-next"]["eval"], 1830302)

    def test_newer_than_the_pr_there(self):
        # harfbuzz, 2026-10-16: the PR to 14.5.0; staging-next has 14.5.1.
        found = self.load(self.DIGEST)
        rows = [self.row("harfbuzz", "14.5.0"), self.row("hatchling", "1.32.0")]
        branches.apply_staging_next(rows, found)
        harfbuzz, hatchling = (r["stagingPR"] for r in rows)
        self.assertEqual(
            (
                harfbuzz["inEval"],
                harfbuzz["evalVersion"],
                harfbuzz["builds"][0]["build"],
            ),
            (True, "14.5.1", "7"),
        )
        # Older there (1.31.0): not in it yet.
        self.assertEqual((hatchling["inEval"], hatchling["builds"]), (False, []))
        self.assertNotIn("evalVersion", hatchling)

    def test_too_old_unused(self):
        old = {**self.DIGEST, "fetchedAt": "2026-10-13T00:00:00+00:00"}
        self.assertIsNone(self.load(old))


class StagingNextBreaks(unittest.TestCase):
    """What staging-next breaks: packages that build on master, failing
    their own build there at the same version."""

    INFO = {"eval": 1830302, "evaluatedAt": "2026-10-16T01:08:22Z"}

    def master(self, attr, system, status, name):
        return {"attr": attr, "system": system, "status": status, "name": name}

    def job(self, status, name, build="9"):
        return {"name": name, "status": status, "build": build}

    def test_only_its_own_failure_at_masters_version(self):
        jobs = {
            ("afew", "x86_64-linux"): self.job("failed", "afew-4.0.2", "1"),
            ("afew", "aarch64-darwin"): self.job("failed", "afew-4.0.2", "2"),
            # A dependency's failure: not this package's.
            ("dep", "x86_64-linux"): self.job("dependency", "dep-1.0"),
            # Another version there: an update in progress (Part A's).
            ("upd", "x86_64-linux"): self.job("failed", "upd-2.0"),
            # Failing on master too: not staging-next's doing.
            ("old", "x86_64-linux"): self.job("failed", "old-1.0"),
        }
        rows = [
            {
                "name": "afew",
                "builds": [
                    self.master("afew", "x86_64-linux", "ok", "afew-4.0.2"),
                    self.master("afew", "aarch64-darwin", "ok", "afew-4.0.2"),
                    self.master("afew", "aarch64-linux", "ok", "afew-4.0.2"),
                ],
            },
            {
                "name": "dep",
                "builds": [self.master("dep", "x86_64-linux", "ok", "dep-1.0")],
            },
            {
                "name": "upd",
                "builds": [self.master("upd", "x86_64-linux", "ok", "upd-1.0")],
            },
            {
                "name": "old",
                "builds": [self.master("old", "x86_64-linux", "failed", "old-1.0")],
            },
        ]
        cycle = {"n": 571813, "cut": "2026-10-08T00:00:00Z", "open": True}
        branches.apply_staging_next_breaks(rows, (jobs, self.INFO), cycle)
        afew = rows[0]["stagingNextBreaks"]
        self.assertEqual(
            [(b["system"], b["build"]) for b in afew["builds"]],
            [("aarch64-darwin", "2"), ("x86_64-linux", "1")],
        )
        self.assertEqual(
            (afew["eval"], afew["cycle"]),
            (1830302, {"n": 571813, "cut": "2026-10-08T00:00:00Z"}),
        )
        self.assertEqual(
            [r["name"] for r in rows if "stagingNextBreaks" in r], ["afew"]
        )

    def test_without_the_file_none(self):
        row = {"name": "afew", "builds": [], "stagingNextBreaks": {"eval": 1}}
        branches.apply_staging_next_breaks([row], None)
        self.assertNotIn("stagingNextBreaks", row)


class StagingNextBlocked(unittest.TestCase):
    """Who stops whom on staging-next: its failing dependencies."""

    INFO = {"eval": 1830302, "evaluatedAt": "2026-10-16T01:08:22Z"}

    def build(self, attr, status, name, system="x86_64-linux"):
        return {"attr": attr, "system": system, "status": status, "name": name}

    def job(self, status, name, blocked_by=(), build="9"):
        return {
            "name": name,
            "status": status,
            "build": build,
            "blockedBy": list(blocked_by),
        }

    def test_who_stops_whom(self):
        jobs = {
            ("blender", "x86_64-linux"): self.job(
                "dependency", "blender-5.0.1", ["rocmPackages.clang"], "11"
            ),
            ("hipblas", "x86_64-linux"): self.job(
                "dependency", "hipblas-7.0", ["rocmPackages.clang"], "12"
            ),
            # Its blocker no row: named as it is.
            ("azure-functions-core-tools", "x86_64-linux"): self.job(
                "dependency", "aft-4.0", ["Grpc.Tools-2.55.1"], "13"
            ),
            # Stopped on master too: not staging-next's doing.
            ("krita", "x86_64-linux"): self.job(
                "dependency", "krita-6.0", ["qt"], "14"
            ),
        }
        rows = [
            {
                "name": "blender",
                "attrs": ["blender"],
                "builds": [self.build("blender", "ok", "blender-5.0.1")],
            },
            {
                "name": "hipblas",
                "attrs": ["hipblas"],
                "builds": [self.build("hipblas", "ok", "hipblas-7.0")],
            },
            {
                "name": "azure-functions-core-tools",
                "attrs": ["azure-functions-core-tools"],
                "builds": [self.build("azure-functions-core-tools", "ok", "aft-4.0")],
            },
            {
                "name": "krita",
                "attrs": ["krita"],
                "builds": [self.build("krita", "dependency", "krita-6.0")],
            },
            {"name": "clang-rocm", "attrs": ["rocmPackages.clang"], "builds": []},
        ]
        branches.apply_staging_next_blocked(rows, (jobs, self.INFO))
        by = {r["name"]: r for r in rows}
        self.assertEqual(
            by["blender"]["stagingNextBlockedBy"]["builds"],
            [
                {
                    "system": "x86_64-linux",
                    "build": "11",
                    "by": [{"name": "clang-rocm", "row": True}],
                }
            ],
        )
        self.assertEqual(
            by["azure-functions-core-tools"]["stagingNextBlockedBy"]["builds"][0]["by"],
            [{"name": "Grpc.Tools-2.55.1"}],
        )
        self.assertNotIn("stagingNextBlockedBy", by["krita"])
        self.assertEqual(
            by["clang-rocm"]["stagingNextBlocks"],
            {**self.INFO, "packages": 2, "builds": 2},
        )
        # Without the file: none.
        branches.apply_staging_next_blocked(rows, None)
        self.assertFalse(
            any("stagingNextBlocks" in r or "stagingNextBlockedBy" in r for r in rows)
        )


class CurrentStagingNext(unittest.TestCase):
    """A staging-next evaluation made before its cycle's merge into master
    isn't used: that cycle is master's now."""

    FOUND = ({}, {"eval": 1830329, "evaluatedAt": "2026-10-16T17:14:44Z"})

    def setUp(self):
        about.taken()
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_before_the_merge_not_used(self):
        # 2026-10-16: #571813 merged at 19:04, two hours after it.
        merged = {"n": 571813, "merged": "2026-10-16T19:04:23Z"}
        self.assertIsNone(branches.current_staging_next(self.FOUND, merged))
        self.assertFalse(about.taken()["branch:staging-next"]["used"])

    def test_after_the_merge_or_unknown_used(self):
        # Of the next cycle, or with nothing merged since: used.
        earlier = {"n": 566094, "merged": "2026-09-28T17:40:27Z"}
        self.assertIs(branches.current_staging_next(self.FOUND, earlier), self.FOUND)
        self.assertIs(branches.current_staging_next(self.FOUND, None), self.FOUND)
        self.assertIsNone(branches.current_staging_next(None, earlier))
