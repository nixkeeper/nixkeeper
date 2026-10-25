import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.sources import about, http, typst_digest

NOW = "2026-10-08T06:00:00+00:00"
PACKAGES = {
    "cetz": {"version": "0.10.0", "released": "2026-10-01"},
    "fletcher": {"version": "0.5.8"},
}


def pkg(pname, version):
    return {"pname": pname, "version": version, "meta": {}}


# nixpkgs' typstPackages: each version an attribute, the latest under the
# package's own name too (pkgs/by-name/ty/typst/typst-packages.nix).
NIXPKGS = {
    "typstPackages.cetz": pkg("cetz", "0.9.2"),
    "typstPackages.cetz_0_9_2": pkg("cetz", "0.9.2"),
    "typstPackages.cetz_0_3_0": pkg("cetz", "0.3.0"),
    "typstPackages.fletcher": pkg("fletcher", "0.5.8"),
    "typstPackages.fletcher_0_5_8": pkg("fletcher", "0.5.8"),
    "typstPackages.gone": pkg("gone", "1.0.0"),
    "cetz": pkg("cetz", "0.1.0"),  # not a Typst package
}


def row(attrs, version, status):
    return {
        "name": attrs[0],
        "attrs": attrs,
        "nixVersion": version,
        "nixStatus": status,
    }


class Apply(unittest.TestCase):
    def rows(self):
        return [
            # Repology: nixpkgs alone ("unique"), its kept versions "legacy".
            row(["typstPackages.cetz", "typstPackages.cetz_0_9_2"], "0.9.2", "unique"),
            {
                **row(["typstPackages.cetz_0_3_0"], "0.3.0", "legacy"),
                "keptBeside": {"attr": "typstPackages.cetz", "version": "0.9.2"},
            },
            # Not on Repology: each attribute a row of its own.
            row(["typstPackages.fletcher"], "0.5.8", "unlisted"),
            row(["typstPackages.fletcher_0_5_8"], "0.5.8", "unlisted"),
            row(["typstPackages.gone"], "1.0.0", "unique"),  # not on Universe
            row(["cetz"], "0.1.0", "outdated"),
        ]

    def test_compared_with_universe(self):
        rows = self.rows()
        typst_digest.apply(rows, NIXPKGS, PACKAGES)
        cetz, cetz_kept, fletcher, fletcher_same, gone, other = rows
        # The latest attribute: 0.10.0 is newer than 0.9.2, by number.
        self.assertEqual(
            (cetz["nixStatus"], cetz["refVersion"]), ("outdated", "0.10.0")
        )
        self.assertEqual(
            cetz["feed"],
            {
                "name": "Typst Universe",
                "version": "0.10.0",
                "url": "https://typst.app/universe/package/cetz",
                "released": "2026-10-01",
            },
        )
        # A versioned one: an older version kept beside it.
        self.assertEqual(cetz_kept["nixStatus"], config.KEPT)
        self.assertEqual(
            cetz_kept["keptBeside"], {"attr": "typstPackages.cetz", "version": "0.9.2"}
        )
        # Up to date, and the same version under its versioned name.
        self.assertEqual(fletcher["nixStatus"], "newest")
        self.assertEqual(fletcher_same["nixStatus"], "newest")
        self.assertNotIn("keptBeside", fletcher_same)
        # Not on Universe, or not a Typst package: as Repology has them.
        self.assertEqual(gone["nixStatus"], "unique")
        self.assertNotIn("feed", gone)
        self.assertEqual(other["nixStatus"], "outdated")
        self.assertNotIn("feed", other)

    def test_nothing_without_universe(self):
        rows = self.rows()
        typst_digest.apply(rows, NIXPKGS, None)
        self.assertEqual(rows, self.rows())


class Load(unittest.TestCase):
    def setUp(self):
        about.taken()  # start with nothing noted
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)
        # The tests turn the digests off (tests/__init__.py): on, here.
        patcher = mock.patch.object(
            config, "VERSIONS_DIGEST_URL", "https://example.org/data/"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def serve(self, body):
        data = None if body is None else gzip.compress(json.dumps(body).encode())
        return mock.patch.object(http, "get_bytes", return_value=data)

    def test_current(self):
        body = {
            "format": 1,
            "fetchedAt": "2026-10-08T04:10:00+00:00",
            "packages": PACKAGES,
        }
        with self.serve(body):
            self.assertEqual(typst_digest.load(NOW), PACKAGES)
        self.assertEqual(about.taken()["typst"]["used"], True)

    def test_old_missing_or_off(self):
        old = {
            "format": 1,
            "fetchedAt": "2026-10-05T04:10:00+00:00",
            "packages": PACKAGES,
        }
        with self.serve(old):
            self.assertIsNone(typst_digest.load(NOW))
        self.assertEqual(about.taken()["typst"]["why"], "too old")
        with self.serve(None):
            self.assertIsNone(typst_digest.load(NOW))
        self.assertIn("couldn't be read", about.taken()["typst"]["why"])
        with mock.patch.object(config, "VERSIONS_DIGEST_URL", ""):
            self.assertIsNone(typst_digest.load(NOW))


if __name__ == "__main__":
    unittest.main()
