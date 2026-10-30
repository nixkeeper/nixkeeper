import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.changes import is_outdated
from nixkeeper.sources import about, http, sets_digest

NOW = "2026-10-30T12:00:00+00:00"
READ = "2026-10-30T04:10:00+00:00"


def pkg(pname, version):
    return {"pname": pname, "version": version, "meta": {}}


NIXPKGS = {
    "chickenPackages_5.chickenEggs.miscmacros": pkg("chicken-miscmacros", "1.0"),
    "chickenPackages_6.chickenEggs.miscmacros": pkg("chicken-miscmacros", "1.3"),
    "akkuPackages.chibi-crypto-md5": pkg("akku-chibi-crypto-md5", "0.9.0"),
    "gnomeExtensions.applications-menu": pkg(
        "gnome-shell-extension-applications-menu", "79"
    ),
    "gnomeExtensions.color-picker": pkg("gnome-shell-extension-color-picker", "50"),
    "azure-cli-extensions.acat": pkg("acat", "1.0.0b1"),
    "gnome-shell": pkg("gnome-shell", "50.4"),
    "azure-cli": pkg("azure-cli", "2.91.0"),
}

# As the digest's sets.json.gz has them (2026-10-30).
SETS = {
    "chickenPackages_5": {
        "fetchedAt": READ,
        "packages": {"miscmacros": {"version": "1.0"}},
    },
    "chickenPackages_6": {
        "fetchedAt": READ,
        "packages": {"miscmacros": {"version": "1.4"}},
    },
    "akkuPackages": {
        "fetchedAt": READ,
        "packages": {"chibi-crypto-md5": {"version": "0.10.0"}},
    },
    "gnomeExtensions": {
        "fetchedAt": READ,
        "attrs": {
            # Its slug is another extension's too: the digest's attrs tell.
            "gnomeExtensions.applications-menu": "apps-menu@gcampax",
            "gnomeExtensions.color-picker": "color-picker@tuberry",
        },
        "packages": {
            "apps-menu@gcampax": {
                "slug": "applications-menu",
                "pk": 6,
                "shells": {"47": "77", "48": "79", "49": "81"},
            },
            "Applications_Menu@rmy": {"slug": "applications-menu", "shells": {}},
            "color-picker@tuberry": {
                "slug": "color-picker",
                "shells": {"46": "44", "48": "46", "50": "49", "51": "50"},
            },
        },
    },
    "azure-cli-extensions": {
        "fetchedAt": READ,
        "packages": {
            "acat": {
                "versions": [
                    ["1.0.0b1", "2.61.0"],
                    ["1.0.0b2", "2.70.0"],
                    ["1.1.0", "2.95.0"],  # needs a newer azure-cli
                ]
            }
        },
    },
}


def row(attr, version, status="unique"):
    return {
        "name": attr,
        "attrs": [attr],
        "nixVersion": version,
        "nixStatus": status,
    }


class Newest(unittest.TestCase):
    def test_gnome_shells_nixpkgs_merges(self):
        extension = SETS["gnomeExtensions"]["packages"]["color-picker@tuberry"]
        # 48 and up with GNOME 50, a newer shell's too: 50, not 49.
        self.assertEqual(sets_digest.gnome_newest(extension, "50.4"), "50")
        self.assertEqual(sets_digest.gnome_newest(extension, "46.1"), "50")
        self.assertIsNone(sets_digest.gnome_newest({"shells": {"45": "3"}}, "50.4"))
        self.assertIsNone(sets_digest.gnome_newest(extension, None))

    def test_azure_newest_nixpkgs_cli_runs(self):
        extension = SETS["azure-cli-extensions"]["packages"]["acat"]
        self.assertEqual(sets_digest.azure_newest(extension, "2.91.0"), "1.0.0b2")
        self.assertEqual(sets_digest.azure_newest(extension, "2.95.0"), "1.1.0")
        self.assertIsNone(sets_digest.azure_newest(extension, "2.50.0"))


class Apply(unittest.TestCase):
    def test_compared_with_each_index(self):
        rows = [
            row("chickenPackages_5.chickenEggs.miscmacros", "1.0"),
            row("chickenPackages_6.chickenEggs.miscmacros", "1.3"),
            row("akkuPackages.chibi-crypto-md5", "0.9.0"),
            row("gnomeExtensions.applications-menu", "79"),
            row("gnomeExtensions.color-picker", "50"),
            row("azure-cli-extensions.acat", "1.0.0b1"),
            row("gnome-shell", "50.4", "newest"),  # not in a set
        ]
        sets_digest.apply(rows, NIXPKGS, SETS)
        by_name = {r["name"]: r for r in rows}
        expected = {
            "chickenPackages_5.chickenEggs.miscmacros": (False, "1.0"),
            "chickenPackages_6.chickenEggs.miscmacros": (True, "1.4"),
            "akkuPackages.chibi-crypto-md5": (True, "0.10.0"),
            "gnomeExtensions.applications-menu": (True, "81"),
            "gnomeExtensions.color-picker": (False, "50"),
            "azure-cli-extensions.acat": (True, "1.0.0b2"),
        }
        for name, (outdated, version) in expected.items():
            found = by_name[name]
            self.assertEqual(is_outdated(found), outdated, name)
            self.assertEqual(found["feed"]["version"], version, name)
        self.assertEqual(
            by_name["gnomeExtensions.applications-menu"]["feed"]["url"],
            "https://extensions.gnome.org/extension/6/applications-menu/",
        )
        self.assertEqual(
            by_name["chickenPackages_6.chickenEggs.miscmacros"]["feed"]["name"],
            "CHICKEN 6 eggs",
        )
        self.assertNotIn("feed", by_name["gnome-shell"])

    def test_not_in_its_index_or_set_not_read(self):
        rows = [
            row("akkuPackages.gone", "1.0"),
            row("chickenPackages_5.chickenEggs.miscmacros", "0.9"),
        ]
        sets_digest.apply(rows, NIXPKGS, {"akkuPackages": SETS["akkuPackages"]})
        self.assertFalse(any("feed" in r for r in rows))
        sets_digest.apply(rows, NIXPKGS, None)
        self.assertFalse(any("feed" in r for r in rows))


class Load(unittest.TestCase):
    def setUp(self):
        self.noted = self.enterContext(about.collecting())

    def serve(self, sets):
        body = gzip.compress(
            json.dumps({"format": 1, "fetchedAt": READ, "sets": sets}).encode()
        )
        return (
            mock.patch.object(config, "VERSIONS_DIGEST_URL", "https://example.org/d/"),
            mock.patch.object(http, "get_bytes", return_value=body),
            mock.patch("sys.stderr", io.StringIO()),
        )

    def test_current_sets_only(self):
        stale = {**SETS["akkuPackages"], "fetchedAt": "2026-10-27T04:10:00+00:00"}
        a, b, c = self.serve({**SETS, "akkuPackages": stale, "unknownSet": {}})
        with a, b, c:
            found = sets_digest.load(NOW)
        self.assertEqual(
            sorted(found),
            [
                "azure-cli-extensions",
                "chickenPackages_5",
                "chickenPackages_6",
                "gnomeExtensions",
            ],
        )
        self.assertEqual(self.noted["sets"]["gnomeExtensions"], 3)
        self.assertNotIn("akkuPackages", self.noted["sets"])


if __name__ == "__main__":
    unittest.main()
