import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import config, history, lookup
from nixkeeper.sources import about, http, versions_digest

NOW = "2026-10-05T06:00:00+00:00"


def nix(attr, version, status="newest"):
    return {
        "repo": "nix_unstable",
        "srcname": attr,
        "version": version,
        "status": status,
    }


def line(project, entries, checked="2026-10-05"):
    return json.dumps({"project": project, "checked": checked, "entries": entries})


TRACY = [
    nix("tracy", "0.13.1", "outdated"),
    nix("tracy_0_11", "0.11.1", "legacy"),
    {"repo": "arch", "srcname": "tracy", "version": "0.14.1", "status": "newest"},
]
LINES = [line("heroic-games-launcher", [nix("heroic", "2.22.3")]), line("tracy", TRACY)]


class ProjectsOf(unittest.TestCase):
    def test_keeps_only_the_tracked_attrs_projects(self):
        found = versions_digest.projects_of(LINES, {"tracy_0_11", "gone"})
        self.assertEqual(found, {"tracy_0_11": ("tracy", TRACY, "2026-10-05")})


class Answer(unittest.TestCase):
    DIGEST = versions_digest.projects_of(LINES, {"tracy", "tracy_0_11", "heroic"})

    def answer(self, attrs, versions):
        nixpkgs = {a: {"version": v} for a, v in versions.items()}
        return versions_digest.answer(self.DIGEST, attrs, nixpkgs)

    def test_the_channels_version(self):
        self.assertEqual(
            self.answer(["tracy", "tracy_0_13"], {"tracy": "0.13.1"})[:2],
            ("tracy", TRACY),
        )

    def test_another_version_asks_repology(self):
        # nixpkgs moved on since the digest read it.
        self.assertIsNone(self.answer(["tracy"], {"tracy": "0.14.1"}))

    def test_not_in_the_digest(self):
        self.assertIsNone(self.answer(["new-package"], {"new-package": "1.0"}))


class Load(unittest.TestCase):
    def setUp(self):
        self.noted = self.enterContext(about.collecting())

    def load(self, meta, lines=LINES):
        body = gzip.compress("".join(f"{x}\n" for x in lines).encode())
        out = io.StringIO()
        with (
            mock.patch.object(config, "VERSIONS_DIGEST_URL", "https://digest/"),
            mock.patch.object(http, "get", return_value=json.dumps(meta)),
            mock.patch.object(http, "get_bytes", return_value=body),
            mock.patch("sys.stderr", out),
        ):
            return versions_digest.load(["heroic", "tracy"], NOW), out.getvalue()

    def meta(self, read="2026-10-05T04:20:00+00:00"):
        return {"format": 1, "outdatedAt": read, "projects": 119028}

    def test_current(self):
        found, out = self.load(self.meta())
        self.assertEqual(sorted(found), ["heroic", "tracy"])
        self.assertIn("Versions digest: 119,028 projects", out)
        self.assertIn("2 of 2 tracked attributes in it", out)
        self.assertEqual(
            self.noted["versions"],
            {"used": True, "at": "2026-10-05T04:20:00+00:00", "projects": 119028},
        )

    def test_too_old_or_unreadable(self):
        # Too old: kept, for where Repology can't be reached (lookup.py).
        found, out = self.load(self.meta("2026-10-03T04:20:00+00:00"))
        self.assertEqual(sorted(found), ["heroic", "tracy"])
        self.assertTrue(found.stale)
        self.assertIn("the digest only where that fails", out)
        self.assertIn("used only where Repology", self.noted["versions"]["why"])
        found, out = self.load({"format": 2, "outdatedAt": NOW, "projects": 1})
        self.assertIsNone(found)
        self.assertIn("couldn't use it", out)
        noted = self.noted["versions"]
        self.assertFalse(noted["used"])
        self.assertTrue(noted["why"].startswith("couldn't be read (no digest"))
        with mock.patch.object(config, "VERSIONS_DIGEST_URL", ""):
            self.assertIsNone(versions_digest.load(["tracy"], NOW))


class CollectProjects(unittest.TestCase):
    def test_digest_first_repology_for_the_rest(self):
        digest = versions_digest.projects_of(LINES, {"tracy", "heroic", "fresh"})
        nixpkgs = {
            "tracy": {"version": "0.13.1"},
            "heroic": {"version": "2.23.0"},  # updated since: looked up
            "fresh": {"version": "1.0"},  # new in nixpkgs: looked up
        }
        asked = []

        def resolve(fallback, attrs, known=None):
            asked.append(fallback)
            return fallback, [nix(attrs[0], nixpkgs[attrs[0]]["version"])]

        wanted = {
            "tracy": (["tracy"], "tracy"),
            "heroic": (["heroic"], "heroic"),
            "fresh": (["fresh"], "fresh"),
        }
        with mock.patch("sys.stderr", io.StringIO()):
            projects = lookup.collect_projects(
                wanted,
                history.PreviousRun({"packages": []}),
                resolve=resolve,
                nixpkgs=nixpkgs,
                now=NOW,
                digest=digest,
            )
        self.assertEqual(sorted(asked), ["fresh", "heroic"])
        self.assertEqual(projects["tracy"]["checkedAt"], "2026-10-05T00:00:00+00:00")
        self.assertEqual(projects["tracy"]["entries"], TRACY)
