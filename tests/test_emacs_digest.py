import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.sources import about, emacs_digest, http

NOW = "2026-10-08T06:00:00+00:00"
# Trimmed from nixkeeper-versions' emacs.json.gz (2026-10-07).
ARCHIVES = {
    "melpa": {"magit": "20251005.508", "0x0": "20240101.100", "jabber": "20250101.1"},
    "melpaStable": {"rtags": "3.23", "magit": "4.4.2"},
    "nongnu": {"jabber": "0.15.0"},
    "gnu": {"auctex": "14.2.0", "jabber": "0.14.0", "agitate": "0.5.0"},
}


def pkg(position="pkgs/applications/editors/emacs/elisp-packages/x.nix:1"):
    return {"meta": {"position": position}}


def row(attr, version):
    return {
        "name": attr,
        "attrs": [attr],
        "nixVersion": version,
        "nixStatus": "untrusted",
    }


class Apply(unittest.TestCase):
    def apply(self, rows, nixpkgs=None):
        nixpkgs = nixpkgs or {r["attrs"][0]: pkg() for r in rows}
        emacs_digest.apply(rows, nixpkgs, ARCHIVES)
        return rows

    def test_a_melpa_version_against_melpa(self):
        (magit,) = self.apply([row("emacsPackages.magit", "20250820.1200")])
        self.assertEqual(
            (magit["nixStatus"], magit["refVersion"]), ("outdated", "20251005.508")
        )
        self.assertEqual(
            magit["feed"],
            {
                "name": "MELPA",
                "version": "20251005.508",
                "url": "https://melpa.org/#/magit",
                "dated": True,
            },
        )
        # A quoted attribute name: the package's own.
        (zero,) = self.apply([row('emacsPackages."0x0"', "20240101.100")])
        self.assertEqual(zero["nixStatus"], "newest")

    def test_a_release_against_the_first_archive_in_nixpkgs_order(self):
        rtags, jabber, auctex = self.apply(
            [
                row("emacsPackages.rtags", "2.46"),
                # On NonGNU and GNU: NonGNU comes later in nixpkgs, so first.
                row("emacsPackages.jabber", "0.15.0"),
                row("emacsPackages.auctex", "14.1.2"),
            ]
        )
        self.assertEqual(
            (rtags["nixStatus"], rtags["feed"]["name"]), ("outdated", "MELPA Stable")
        )
        self.assertEqual(
            (jabber["nixStatus"], jabber["feed"]["name"]), ("newest", "NonGNU ELPA")
        )
        self.assertEqual(
            jabber["feed"]["url"], "https://elpa.nongnu.org/nongnu/jabber.html"
        )
        self.assertEqual(
            (auctex["nixStatus"], auctex["refVersion"]), ("outdated", "14.2.0")
        )
        self.assertNotIn("dated", auctex["feed"])

    def test_left_to_repology(self):
        rows = [
            # A devel archive's version: not comparable with GNU ELPA's 0.5.0.
            row("emacsPackages.agitate", "0.0.20260424.102016"),
            # A hand-written package, whatever the archives have.
            row("emacsPackages.magit", "4.0.0"),
            # In no archive.
            row("emacsPackages.cask", "0.9.1"),
            # Not an Emacs package.
            row("magit", "20200101.1"),
        ]
        nixpkgs = {r["attrs"][0]: pkg() for r in rows}
        nixpkgs["emacsPackages.magit"] = pkg(
            "pkgs/applications/editors/emacs/elisp-packages/manual-packages/magit.nix:3"
        )
        self.apply(rows, nixpkgs)
        for r in rows:
            self.assertEqual(r["nixStatus"], "untrusted", r["name"])
            self.assertNotIn("feed", r)

    def test_nothing_without_the_archives(self):
        rows = [row("emacsPackages.magit", "20250820.1200")]
        emacs_digest.apply(rows, {}, None)
        self.assertNotIn("feed", rows[0])


class Load(unittest.TestCase):
    def setUp(self):
        about.taken()
        patcher = mock.patch("sys.stderr", io.StringIO())
        patcher.start()
        self.addCleanup(patcher.stop)
        # The tests turn the digests off (tests/__init__.py): on, here.
        patcher = mock.patch.object(
            config, "VERSIONS_DIGEST_URL", "https://example.org/data/"
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_current(self):
        body = {
            "format": 1,
            "fetchedAt": "2026-10-08T04:10:00+00:00",
            "archives": ARCHIVES,
        }
        data = gzip.compress(json.dumps(body).encode())
        with mock.patch.object(http, "get_bytes", return_value=data):
            self.assertEqual(emacs_digest.load(NOW), ARCHIVES)
        noted = about.taken()["emacs"]
        self.assertEqual((noted["used"], noted["melpa"], noted["gnu"]), (True, 3, 3))

    def test_missing(self):
        with mock.patch.object(http, "get_bytes", return_value=None):
            self.assertIsNone(emacs_digest.load(NOW))
        self.assertIn("no emacs.json.gz yet", about.taken()["emacs"]["why"])


if __name__ == "__main__":
    unittest.main()
