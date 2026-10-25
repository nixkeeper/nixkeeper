import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.sources import about, http, stackage_digest

NOW = "2026-10-08T06:00:00+00:00"
# Trimmed from nixkeeper-versions' stackage.json.gz (2026-10-07).
FOUND = {
    "format": 1,
    "fetchedAt": "2026-10-08T04:10:00+00:00",
    "series": "lts-24",
    "nixpkgs": "lts-24.38",
    "snapshot": "lts-24.62",
    "versions": {"aeson": "2.2.5.1", "zot": "0.0.3"},
}


def row(attr, version, ref, status="outdated"):
    return {
        "name": attr,
        "attrs": [attr],
        "nixVersion": version,
        "refVersion": ref,
        "nixStatus": status,
    }


class Apply(unittest.TestCase):
    def test_pinned_packages_against_their_series(self):
        rows = [
            # Behind the series' newest snapshot: outdated, against it (not
            # Hackage's 2.3.0.0, which Stackage holds back).
            row("haskellPackages.aeson", "2.2.4.1", "2.3.0.0"),
            # At it: newest, whatever Hackage has.
            row("haskellPackages.zot", "0.0.3", "0.1.0"),
            # Not pinned: Hackage's newest, as Repology says.
            row("haskellPackages.pandoc", "3.7", "3.8"),
            # A versioned attribute nixpkgs keeps (extra-packages): left alone.
            row("haskellPackages.aeson_1_5_6_0", "1.5.6.0", "2.3.0.0", "legacy"),
        ]
        stackage_digest.apply(rows, {}, FOUND)
        aeson, zot, pandoc, kept = rows
        self.assertEqual(
            (aeson["nixStatus"], aeson["refVersion"]), ("outdated", "2.2.5.1")
        )
        self.assertEqual(
            aeson["feed"],
            {
                "name": "Stackage LTS 24",
                "version": "2.2.5.1",
                "url": "https://www.stackage.org/lts-24.62/package/aeson",
                "snapshot": "lts-24.62",
                "followed": "lts-24.38",
                "heldBack": "2.3.0.0",
            },
        )
        self.assertEqual(
            (zot["nixStatus"], zot["feed"]["heldBack"]), ("newest", "0.1.0")
        )
        self.assertEqual(
            (pandoc["nixStatus"], pandoc["refVersion"]), ("outdated", "3.8")
        )
        self.assertNotIn("feed", pandoc)
        self.assertEqual(kept["nixStatus"], "legacy")
        self.assertNotIn("feed", kept)

    def test_not_held_back(self):
        rows = [row("haskellPackages.zot", "0.0.3", "0.0.3", "newest")]
        stackage_digest.apply(rows, {}, FOUND)
        self.assertNotIn("heldBack", rows[0]["feed"])


class Load(unittest.TestCase):
    def setUp(self):
        about.taken()
        for patcher in (
            mock.patch("sys.stderr", io.StringIO()),
            # The tests turn the digests off (tests/__init__.py): on, here.
            mock.patch.object(
                config, "VERSIONS_DIGEST_URL", "https://example.org/data/"
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_current(self):
        data = gzip.compress(json.dumps(FOUND).encode())
        with mock.patch.object(http, "get_bytes", return_value=data):
            self.assertEqual(stackage_digest.load(NOW)["snapshot"], "lts-24.62")
        noted = about.taken()["stackage"]
        self.assertEqual(
            (noted["used"], noted["snapshot"], noted["nixpkgs"], noted["packages"]),
            (True, "lts-24.62", "lts-24.38", 2),
        )


if __name__ == "__main__":
    unittest.main()
