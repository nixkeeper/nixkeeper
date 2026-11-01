import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper import config
from nixkeeper.changes import is_outdated
from nixkeeper.sources import about, http, registries_digest

NOW = "2026-10-31T12:00:00+00:00"
READ = "2026-10-31T04:10:00+00:00"

# As the digest's registries.json.gz has them (2026-10-31).
REGISTRIES = {
    "rubygems": {
        "fetchedAt": READ,
        "attrs": {
            "rubyPackages.rails": "rails",
            "rubyPackages_3_4.rails": "rails",
            "rubyPackages.rake": "rake",
            "gist": "gist",
        },
        "packages": {
            "rails": {"version": "8.1.4"},
            "rake": {"version": "13.3.1"},
            "gist": {"version": "6.1.0"},
        },
    },
    "crates.io": {
        "fetchedAt": READ,
        # The crate's name isn't the attribute's.
        "attrs": {"_0x": "ohx", "pijul": "pijul", "gone": "gone"},
        "packages": {
            "ohx": {"version": "0.1.0"},
            "pijul": {"version": "0.15.0", "preRelease": "1.0.0-beta.25"},
        },
    },
}


def row(attrs, version, status="unique"):
    return {
        "name": attrs[0],
        "attrs": attrs,
        "nixVersion": version,
        "nixStatus": status,
    }


class Newest(unittest.TestCase):
    def test_pre_release_only_for_a_pre_release(self):
        pijul = REGISTRIES["crates.io"]["packages"]["pijul"]
        self.assertEqual(
            registries_digest.newest_for(pijul, "1.0.0-beta.24"), "1.0.0-beta.25"
        )
        self.assertEqual(registries_digest.newest_for(pijul, "0.14.0"), "0.15.0")
        self.assertEqual(
            registries_digest.newest_for({"version": "1.0"}, "1.0-rc1"), "1.0"
        )


class Apply(unittest.TestCase):
    def test_compared_with_each_registry(self):
        rows = [
            row(["rubyPackages.rails", "rubyPackages_3_4.rails"], "7.2.3"),
            row(["rubyPackages.rake"], "13.3.1"),
            row(["gist"], "6.0.0", "outdated"),
            row(["_0x"], "0.1.0"),
            row(["pijul"], "1.0.0-beta.24"),
            row(["gone"], "1.0"),  # not answered: Repology's verdict stays
            row(["hello"], "2.12.2", "newest"),
        ]
        registries_digest.apply(rows, {}, REGISTRIES)
        by_name = {r["name"]: r for r in rows}
        expected = {
            "rubyPackages.rails": (True, "8.1.4", "RubyGems"),
            "rubyPackages.rake": (False, "13.3.1", "RubyGems"),
            "gist": (True, "6.1.0", "RubyGems"),
            "_0x": (False, "0.1.0", "crates.io"),
            "pijul": (True, "1.0.0-beta.25", "crates.io"),
        }
        for name, (outdated, version, source) in expected.items():
            found = by_name[name]
            self.assertEqual(is_outdated(found), outdated, name)
            self.assertEqual(found["feed"]["version"], version, name)
            self.assertEqual(found["feed"]["name"], source, name)
        self.assertEqual(by_name["_0x"]["feed"]["url"], "https://crates.io/crates/ohx")
        self.assertEqual(
            by_name["rubyPackages.rails"]["feed"]["url"],
            "https://rubygems.org/gems/rails",
        )
        self.assertNotIn("feed", by_name["gone"])
        self.assertNotIn("feed", by_name["hello"])

    def test_registry_not_read(self):
        rows = [row(["_0x"], "0.0.9")]
        registries_digest.apply(rows, {}, {"rubygems": REGISTRIES["rubygems"]})
        registries_digest.apply(rows, {}, None)
        self.assertNotIn("feed", rows[0])


class Load(unittest.TestCase):
    def setUp(self):
        self.noted = self.enterContext(about.collecting())

    def test_current_registries_only(self):
        stale = {**REGISTRIES["crates.io"], "fetchedAt": "2026-10-28T04:10:00+00:00"}
        body = gzip.compress(
            json.dumps(
                {
                    "format": 1,
                    "fetchedAt": READ,
                    "registries": {**REGISTRIES, "crates.io": stale, "pypi": {}},
                }
            ).encode()
        )
        with (
            mock.patch.object(config, "VERSIONS_DIGEST_URL", "https://example.org/d/"),
            mock.patch.object(http, "get_bytes", return_value=body),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            found = registries_digest.load(NOW)
        self.assertEqual(sorted(found), ["rubygems"])
        self.assertEqual(self.noted["registries"]["rubygems"], 3)
        self.assertNotIn("crates.io", self.noted["registries"])


if __name__ == "__main__":
    unittest.main()
