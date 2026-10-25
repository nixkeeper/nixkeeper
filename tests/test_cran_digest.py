import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.sources import about, cran_digest, http

NOW = "2026-10-08T06:00:00+00:00"
# Trimmed from nixkeeper-versions' cran.json.gz (2026-10-07).
FOUND = {
    "format": 1,
    "fetchedAt": "2026-10-08T04:10:00+00:00",
    "biocVersion": "3.23",
    "cran": {"ggplot2": "4.0.3", "ABC.RAP": "0.9.0", "import": "1.3.2"},
    "bioc": {"AnVIL": "1.24.1"},
    "annotation": {"org.Hs.eg.db": "3.22.0"},
    "experiment": {},
}


def row(attr, version, status="newest"):
    return {"name": attr, "attrs": [attr], "nixVersion": version, "nixStatus": status}


class Apply(unittest.TestCase):
    def test_against_cran_or_bioconductor(self):
        rows = [
            row("rPackages.ggplot2", "4.0.1", "outdated"),
            row("rPackages.ABC_RAP", "0.9.0", "unique"),  # dots as underscores
            row("rPackages.r_import", "1.3.2"),  # a name nixpkgs can't use as is
            # Bioconductor's patch releases, which Repology doesn't flag.
            row("rPackages.AnVIL", "1.24.0"),
            row("rPackages.org_Hs_eg_db", "3.22.0"),
        ]
        cran_digest.apply(rows, {}, FOUND)
        ggplot2, abc, imp, anvil, org = rows
        self.assertEqual(
            (ggplot2["nixStatus"], ggplot2["refVersion"]), ("outdated", "4.0.3")
        )
        self.assertEqual(
            ggplot2["feed"],
            {
                "name": "CRAN",
                "version": "4.0.3",
                "url": "https://cran.r-project.org/package=ggplot2",
            },
        )
        self.assertEqual(abc["nixStatus"], "newest")  # Repology's "unique" before
        self.assertEqual(
            imp["feed"]["url"], "https://cran.r-project.org/package=import"
        )
        self.assertEqual(
            (anvil["nixStatus"], anvil["feed"]["name"]),
            ("outdated", "Bioconductor 3.23"),
        )
        self.assertEqual(
            anvil["feed"]["url"],
            "https://bioconductor.org/packages/3.23/bioc/html/AnVIL.html",
        )
        self.assertEqual(
            org["feed"]["url"],
            "https://bioconductor.org/packages/3.23/data/annotation/html/org.Hs.eg.db.html",
        )

    def test_archived(self):
        # On neither: archived, its status left as Repology had it.
        rows = [row("rPackages.A3", "1.0.0", "unique")]
        cran_digest.apply(rows, {}, FOUND)
        self.assertTrue(rows[0]["archived"])
        self.assertEqual(rows[0]["nixStatus"], "unique")
        self.assertNotIn("feed", rows[0])

    def test_only_r_packages(self):
        rows = [row("ggplot2", "1.0")]
        cran_digest.apply(rows, {}, FOUND)
        self.assertNotIn("feed", rows[0])
        self.assertNotIn("archived", rows[0])


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
            self.assertEqual(cran_digest.load(NOW)["biocVersion"], "3.23")
        noted = about.taken()["cran"]
        self.assertEqual(
            (noted["used"], noted["biocVersion"], noted["cran"]), (True, "3.23", 3)
        )


if __name__ == "__main__":
    unittest.main()
