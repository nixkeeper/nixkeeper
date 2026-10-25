"""nixkeeper.sources.digests: fetching and checking the digests' files."""

import gzip
import io
import json
import unittest
from unittest import mock

from nixkeeper.sources import about, digests, http


class ReadMeta(unittest.TestCase):
    def test_in_this_format(self):
        with mock.patch.object(http, "get", return_value='{"format": 1, "at": "x"}'):
            self.assertEqual(digests.read_meta("https://d/", 1)["at"], "x")

    def test_missing_or_another_format(self):
        for answer in (None, '{"format": 2}'):
            with (
                mock.patch.object(http, "get", return_value=answer),
                self.assertRaisesRegex(
                    ValueError, r"no digest in a format .*https://d/"
                ),
            ):
                digests.read_meta("https://d/", 1)


class Download(unittest.TestCase):
    def test_missing(self):
        with (
            mock.patch.object(http, "get_bytes", return_value=None),
            self.assertRaisesRegex(ValueError, "its builds.csv.gz is missing"),
        ):
            digests.download("https://d/", "builds.csv.gz")


class ReadJsonGz(unittest.TestCase):
    def serve(self, data):
        return mock.patch.object(http, "get_bytes", return_value=data)

    def test_in_this_format(self):
        body = gzip.compress(json.dumps({"format": 1, "jobs": []}).encode())
        with self.serve(body):
            self.assertEqual(
                digests.read_json_gz("https://d/", "f.json.gz", 1)["jobs"], []
            )

    def test_not_there_yet(self):
        with self.serve(None), self.assertRaisesRegex(ValueError, "no f.json.gz yet"):
            digests.read_json_gz("https://d/", "f.json.gz", 1)

    def test_another_format(self):
        body = gzip.compress(json.dumps({"format": 2}).encode())
        with (
            self.serve(body),
            self.assertRaisesRegex(
                ValueError, r"not in a format .*https://d/f.json.gz"
            ),
        ):
            digests.read_json_gz("https://d/", "f.json.gz", 1)


class HoursSince(unittest.TestCase):
    def test_hours(self):
        self.assertEqual(
            digests.hours_since(
                "2026-10-25T00:00:00+00:00", "2026-10-25T06:30:00+00:00"
            ),
            6.5,
        )


class GiveUp(unittest.TestCase):
    def test_noted_and_warned(self):
        about.taken()  # start from no notes
        out = io.StringIO()
        with mock.patch("sys.stderr", out):
            digests.give_up(
                "hydra", "Hydra digest", ValueError("gone"), "; asking Hydra"
            )
        self.assertEqual(
            out.getvalue(),
            "::warning::Hydra digest: couldn't use it (gone); asking Hydra\n",
        )
        self.assertEqual(
            about.taken(), {"hydra": {"used": False, "why": "couldn't be read (gone)"}}
        )


if __name__ == "__main__":
    unittest.main()
