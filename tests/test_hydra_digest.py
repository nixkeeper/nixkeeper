import gzip
import io
import json
import unittest
import urllib.error
from unittest import mock

from nixkeeper import config, sync
from nixkeeper.sources import about, http, hydra, hydra_digest
from nixkeeper.sources import nixpkgs as nixpkgs_source

NOW = "2026-10-04T15:00:00+00:00"
EVALS = '<a href="https://hydra.nixos.org/eval/1829817">'
COLUMNS = (
    "attr,system,build,status,finished,name,lastSuccessBuild,lastSuccessAt,"
    "lastSuccessName"
)


def row(attr, status, build, system="x86_64-linux", last=("", "", ""), name=None):
    return {
        "attr": attr,
        "system": system,
        "build": build,
        "status": status,
        "finished": "" if status == "queued" else "2026-10-03T01:00:00+00:00",
        "name": name if name is not None else f"{attr}-1.0",
        "lastSuccessBuild": last[0],
        "lastSuccessAt": last[1],
        "lastSuccessName": last[2],
    }


class Answer(unittest.TestCase):
    def test_ok(self):
        self.assertEqual(
            hydra_digest.answer(row("wesnoth", "ok", "10"), False, None),
            {
                "attr": "wesnoth",
                "system": "x86_64-linux",
                "status": "ok",
                "build": 10,
                "name": "wesnoth-1.0",
            },
        )

    def test_failing_with_its_last_success(self):
        last = ("5", "2026-09-01T00:00:00+00:00", "x-0.9")
        result = hydra_digest.answer(row("x", "failed", "10", last=last), False, None)
        self.assertEqual(
            (
                result["lastSuccess"],
                result["lastSuccessBuild"],
                result["lastSuccessName"],
            ),
            ("2026-09-01T00:00:00+00:00", 5, "x-0.9"),
        )

    def test_which_dependency_failed(self):
        last = ("5", "2026-09-01T00:00:00+00:00", "mealie-1.0")
        blocked = {
            **row("mealie", "dependency", "10", last=last),
            "blockedBy": "python314Packages.python-ldap source",
        }
        result = hydra_digest.answer(blocked, False, None)
        self.assertEqual(
            result["blockedBy"], ["python314Packages.python-ldap", "source"]
        )
        # Not read yet (empty), or a digest from before the column: nothing.
        self.assertNotIn(
            "blockedBy", hydra_digest.answer({**blocked, "blockedBy": ""}, False, None)
        )
        self.assertNotIn(
            "blockedBy",
            hydra_digest.answer(row("x", "dependency", "10", last=last), False, None),
        )

    def test_why_it_failed(self):
        """nixkeeper-hydra's reason and lines for a failed build, from its
        log: in the digest's answer, every package's bulk one, and Hydra's
        own for the same build."""
        failed = {
            **row(
                "aerogramme",
                "failed",
                "10",
                last=("9", "2026-09-01T00:00:00+00:00", "a"),
            ),
            "failedBecause": "compile",
            "failedExcerpt": "error: could not compile `rustix`",
        }
        result = hydra_digest.answer(failed, False, None)
        self.assertEqual(
            (result["failedBecause"], result["failedExcerpt"]),
            ("compile", "error: could not compile `rustix`"),
        )
        # Not read yet: nothing said.
        unread = {**failed, "failedBecause": "", "failedExcerpt": ""}
        self.assertNotIn("failedBecause", hydra_digest.answer(unread, False, None))
        job = ("aerogramme", "x86_64-linux")
        hydra_says = {"attr": "aerogramme", "status": "failed", "build": 10}
        self.assertEqual(
            hydra_digest.with_blockers({job: dict(hydra_says)}, {job: failed})[job][
                "failedBecause"
            ],
            "compile",
        )
        newer = {job: {**hydra_says, "build": 11}}
        self.assertNotIn(
            "failedBecause", hydra_digest.with_blockers(newer, {job: failed})[job]
        )

    def test_which_dependency_failed_without_a_last_success(self):
        # Never built: Hydra is asked (answer None), but every package's
        # bulk answer keeps which dependency failed, and so do Hydra's
        # answers for the same build (sync.ask_hydra).
        blocked = {**row("mealie", "dependency", "10"), "blockedBy": "pypdf"}
        self.assertIsNone(hydra_digest.answer(blocked, False, None))
        job = ("mealie", "x86_64-linux")
        found = hydra_digest.bulk_answers({job: blocked}, [job], {}, {})
        self.assertEqual(
            (found[job]["status"], found[job]["blockedBy"]), ("dependency", ["pypdf"])
        )
        hydra_says = {"attr": "mealie", "status": "dependency", "build": 10}
        self.assertEqual(
            hydra_digest.with_blockers({job: dict(hydra_says)}, {job: blocked})[job][
                "blockedBy"
            ],
            ["pypdf"],
        )
        # Another build than the digest's (Hydra's is newer): not its blockers.
        newer = {job: {**hydra_says, "build": 11}}
        self.assertNotIn(
            "blockedBy", hydra_digest.with_blockers(newer, {job: blocked})[job]
        )
        self.assertEqual(hydra_digest.with_blockers(newer, None), newer)

    def test_failing_without_one_is_asked(self):
        self.assertIsNone(
            hydra_digest.answer(row("x", "dependency", "10"), False, None)
        )

    def test_failing_keeps_last_syncs_last_success_for_the_same_build(self):
        before = {"build": 10, "status": "failed", "lastSuccess": None}
        result = hydra_digest.answer(row("x", "failed", "10"), False, before)
        self.assertIsNone(result["lastSuccess"])  # never, as Hydra said
        self.assertNotIn("lastSuccessBuild", result)
        # Another build since: Hydra is asked again.
        self.assertIsNone(hydra_digest.answer(row("x", "failed", "11"), False, before))

    def test_never_succeeded_isnt_asked(self):
        # nixkeeper-hydra asked Hydra already: lastSuccessAt "never".
        result = hydra_digest.answer(
            row("x", "failed", "10", last=("", "never", "")), False, None
        )
        self.assertIsNone(result["lastSuccess"])  # never, as Hydra said
        self.assertNotIn("lastSuccessBuild", result)
        self.assertEqual(result["status"], "failed")

    def test_queued_is_asked(self):
        self.assertIsNone(hydra_digest.answer(row("x", "queued", "10"), False, None))

    def test_broken(self):
        built = hydra_digest.answer(row("x", "ok", "10"), True, None)
        self.assertEqual(
            (built["status"], built["lastSuccessBuild"], built["lastSuccess"]),
            ("broken", 10, "2026-10-03T01:00:00+00:00"),
        )
        # Failing, its last success unknown: asked, as any failing build.
        self.assertIsNone(hydra_digest.answer(row("x", "failed", "10"), True, None))

    def test_answers(self):
        digest = {
            ("a", "x86_64-linux"): row("a", "ok", "1"),
            ("b", "x86_64-linux"): row("b", "queued", "2"),
            ("c", "x86_64-linux"): row("c", "unfinished", "3", last=("1", "t", "c-0")),
        }
        wanted = [("a", "x86_64-linux"), ("b", "x86_64-linux"), ("c", "x86_64-linux")]
        wanted.append(("gone", "x86_64-linux"))  # not in the digest: neither
        found, ask = hydra_digest.answers(digest, wanted, {}, {})
        self.assertEqual(sorted(found), [("a", "x86_64-linux"), ("c", "x86_64-linux")])
        self.assertEqual(ask, [("b", "x86_64-linux")])


class Load(unittest.TestCase):
    def serve(self, meta, rows=(), evals=EVALS):
        """A fake http.get / get_bytes: the digest at config's URL, and
        Hydra's list of evaluations (evals: its page, or an error)."""
        text = COLUMNS + "\n" + "".join(",".join(r.values()) + "\n" for r in rows)
        files = {
            "meta.json": json.dumps(meta),
            "builds.csv.gz": gzip.compress(text.encode()),
        }

        def get(url, *args, **kwargs):
            if url.endswith("/evals"):
                if isinstance(evals, Exception):
                    raise evals
                return evals
            return files.get(url.rsplit("/", 1)[1])

        return get, lambda url: files.get(url.rsplit("/", 1)[1])

    def load(self, meta, rows=(), evals=EVALS):
        get, get_bytes = self.serve(meta, rows, evals)
        out = io.StringIO()
        with (
            mock.patch.object(config, "HYDRA_DIGEST_URL", "https://digest/"),
            mock.patch.object(http, "get", side_effect=get),
            mock.patch.object(http, "get_bytes", side_effect=get_bytes),
            mock.patch("sys.stderr", out),
        ):
            return hydra_digest.load(NOW), out.getvalue()

    def meta(self, eval_id=1829817, fetched="2026-10-04T14:00:00+00:00"):
        return {"format": 1, "eval": eval_id, "fetchedAt": fetched}

    def test_the_newest_evaluation(self):
        rows, out = self.load(self.meta(), [row("a", "ok", "1")])
        self.assertEqual(list(rows), [("a", "x86_64-linux")])
        self.assertIn("Hydra digest: 1 jobs, evaluation 1829817, Hydra's newest", out)
        self.assertEqual(
            about.taken()["hydra"],
            {"used": True, "at": "2026-10-04T14:00:00+00:00", "eval": 1829817},
        )

    def test_behind_but_recent(self):
        rows, out = self.load(self.meta(1829803), [row("a", "ok", "1")])
        self.assertIsNotNone(rows)
        self.assertIn(
            "evaluation 1829803; Hydra's newest is 1829817, but read 1 h ago", out
        )
        # Hydra's list unknown: the age decides.
        rows, _ = self.load(self.meta(1829803), [row("a", "ok", "1")], OSError("down"))
        self.assertIsNotNone(rows)

    def test_behind_and_old_is_not_used(self):
        old = self.meta(1829803, "2026-10-03T15:00:00+00:00")
        rows, out = self.load(old)
        self.assertIsNone(rows)
        self.assertIn("warning: Hydra digest: not used", out)
        self.assertEqual(
            about.taken()["hydra"],
            {
                "used": False,
                "why": "too old",
                "at": "2026-10-03T15:00:00+00:00",
                "eval": 1829803,
            },
        )

    def test_unreadable_or_off(self):
        rows, out = self.load({"format": 2, "eval": 1, "fetchedAt": NOW})
        self.assertIsNone(rows)
        self.assertIn("couldn't use it (no digest in a format", out)
        with mock.patch.object(config, "HYDRA_DIGEST_URL", ""):
            self.assertIsNone(hydra_digest.load(NOW))

    def test_unreachable(self):
        out = io.StringIO()
        with (
            mock.patch.object(config, "HYDRA_DIGEST_URL", "https://digest/"),
            mock.patch.object(http, "get", side_effect=urllib.error.URLError("down")),
            mock.patch("sys.stderr", out),
        ):
            self.assertIsNone(hydra_digest.load(NOW))
        self.assertIn("asking Hydra about each job", out.getvalue())


class AskHydra(unittest.TestCase):
    NIXPKGS = {
        "a": {"pname": "a", "version": "1.0", "meta": {"platforms": ["x86_64-linux"]}},
        "b": {"pname": "b", "version": "1.0", "meta": {"platforms": ["x86_64-linux"]}},
        "c": {"pname": "c", "version": "1.0", "meta": {"platforms": ["x86_64-linux"]}},
    }

    def ask(self, digest):
        with (
            mock.patch.object(nixpkgs_source, "broken", return_value={}),
            mock.patch.object(hydra_digest, "load", return_value=digest),
            mock.patch.object(hydra, "fetch", return_value={}) as fetch,
            mock.patch("sys.stderr", io.StringIO()),
        ):
            _, fetched = sync.ask_hydra(
                ["a", "b", "c"], self.NIXPKGS, "rev", {"packages": []}, NOW
            )
        return fetched, fetch.call_args.args[0]

    def test_digest_first_hydra_for_the_rest(self):
        digest = {
            ("a", "x86_64-linux"): row("a", "ok", "1"),
            ("b", "x86_64-linux"): row("b", "queued", "2"),
        }
        fetched, asked = self.ask(digest)
        self.assertEqual(fetched[("a", "x86_64-linux")]["build"], 1)
        # b is queued in the digest, c isn't in it (and new): Hydra for both.
        self.assertEqual(sorted(asked), [("b", "x86_64-linux"), ("c", "x86_64-linux")])

    def test_hydras_answer_gets_the_digests_blockers(self):
        digest = {
            ("a", "x86_64-linux"): {**row("a", "dependency", "7"), "blockedBy": "b"},
        }
        hydra_says = {
            ("a", "x86_64-linux"): {"attr": "a", "status": "dependency", "build": 7}
        }
        with (
            mock.patch.object(nixpkgs_source, "broken", return_value={}),
            mock.patch.object(hydra_digest, "load", return_value=digest),
            mock.patch.object(hydra, "fetch", return_value=hydra_says),
            mock.patch("sys.stderr", io.StringIO()),
        ):
            _, fetched = sync.ask_hydra(
                ["a"], self.NIXPKGS, "rev", {"packages": []}, NOW
            )
        self.assertEqual(fetched[("a", "x86_64-linux")]["blockedBy"], ["b"])

    def test_without_a_digest_as_before(self):
        _, asked = self.ask(None)
        self.assertEqual(len(asked), 3)
