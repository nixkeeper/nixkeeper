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


class ReadJson(unittest.TestCase):
    def test_in_this_format(self):
        answer = '{"format": 1, "prs": [1]}'
        with mock.patch.object(http, "get", return_value=answer) as get:
            self.assertEqual(digests.read_json("https://d/", "prs.json", 1)["prs"], [1])
        get.assert_called_once_with("https://d/prs.json", compressed=True)

    def test_empty_or_another_format(self):
        for answer in (None, '{"format": 2}'):
            with (
                mock.patch.object(http, "get", return_value=answer),
                self.assertRaisesRegex(ValueError, "no prs.json in a format"),
            ):
                digests.read_json("https://d/", "prs.json", 1)


class DownloadMissingOk(unittest.TestCase):
    def test_none_rather_than_raise(self):
        with mock.patch.object(http, "get_bytes", return_value=None):
            self.assertIsNone(digests.download("https://d/", "q.gz", missing_ok=True))


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


class TooOld(unittest.TestCase):
    def test_noted_and_warned(self):
        about.taken()
        out = io.StringIO()
        with mock.patch("sys.stderr", out):
            digests.too_old(
                "hydra", "Hydra digest", "2026-10-25", " (evaluation 7)", eval=7
            )
        self.assertEqual(
            out.getvalue(),
            "::warning::Hydra digest: not used, read 2026-10-25 (evaluation 7)\n",
        )
        self.assertEqual(
            about.taken(),
            {"hydra": {"used": False, "why": "too old", "at": "2026-10-25", "eval": 7}},
        )


if __name__ == "__main__":
    unittest.main()
