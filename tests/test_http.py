"""Slowing down when a server asks (Retry-After, GitHub's rate limits):
sources/http.py, and its use in Repology's and GitHub's requests."""

import gzip
import io
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from nixkeeper import config
from nixkeeper.sources import github, http, repology
from tests.helpers import response


class Case(unittest.TestCase):
    def slow_down(self, code=429, **headers):
        """A "slow down" answer (429 by default) with headers, closed after
        the test (an HTTPError is also an open response)."""
        err = urllib.error.HTTPError(
            "https://example.org", code, "err", headers, io.BytesIO()
        )
        self.addCleanup(err.close)
        return err


class AskedWait(Case):
    NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)

    def test_seconds(self):
        self.assertEqual(http.asked_wait(self.slow_down(**{"Retry-After": "7"})), 7)

    def test_a_date(self):
        err = self.slow_down(503, **{"Retry-After": "Fri, 02 Oct 2026 12:01:30 GMT"})
        self.assertEqual(http.asked_wait(err, now=self.NOW), 90)

    def test_only_when_asked_to_slow_down(self):
        self.assertIsNone(http.asked_wait(self.slow_down(429)))
        self.assertIsNone(http.asked_wait(self.slow_down(500, **{"Retry-After": "7"})))
        self.assertIsNone(http.asked_wait(urllib.error.URLError("down")))
        self.assertIsNone(http.asked_wait(self.slow_down(**{"Retry-After": "soon"})))


class Retries(Case):
    def setUp(self):
        for patcher in (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch.object(config, "RETRY_DELAYS", [5, 15]),
            mock.patch.object(repology, "_working", None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sleep = mock.patch("time.sleep").start()
        self.addCleanup(mock.patch.stopall)

    def test_waits_as_long_as_asked(self):
        answers = [self.slow_down(**{"Retry-After": "40"}), response("ok")]
        answers[1].read.return_value = b"ok"
        with mock.patch("urllib.request.urlopen", side_effect=answers):
            self.assertEqual(http.get("https://x/"), "ok")
        self.sleep.assert_called_once_with(40)

    def test_never_shorter_than_planned(self):
        answers = [self.slow_down(**{"Retry-After": "1"}), response("ok")]
        answers[1].read.return_value = b"ok"
        with mock.patch("urllib.request.urlopen", side_effect=answers):
            http.get("https://x/")
        self.sleep.assert_called_once_with(5)

    def test_gives_up_when_asked_to_wait_too_long(self):
        err = self.slow_down(**{"Retry-After": str(config.MAX_RETRY_AFTER + 1)})
        with (
            mock.patch("urllib.request.urlopen", side_effect=err) as urlopen,
            self.assertRaises(urllib.error.HTTPError),
        ):
            http.get("https://x/")
        self.assertEqual(urlopen.call_count, 1)  # no retry, no wait
        self.sleep.assert_not_called()

    def test_repology_too(self):
        answers = [self.slow_down(**{"Retry-After": "30"}), response(["ok"])]
        with (
            mock.patch.object(config, "REPOLOGY_URLS", ["https://a"]),
            mock.patch("urllib.request.urlopen", side_effect=answers),
        ):
            self.assertEqual(repology.get("/x")[0], ["ok"])
        self.sleep.assert_called_once_with(30)


class GitHubRateLimit(Case):
    def test_retry_after(self):
        self.assertEqual(
            github.rate_limit_wait(self.slow_down(403, **{"Retry-After": "60"})), 60
        )

    def test_until_the_reset(self):
        err = self.slow_down(
            403, **{"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1100"}
        )
        self.assertEqual(github.rate_limit_wait(err, now=1000), 100)

    def test_not_a_rate_limit(self):
        self.assertIsNone(github.rate_limit_wait(self.slow_down(403)))  # no permission
        self.assertIsNone(
            github.rate_limit_wait(self.slow_down(500, **{"Retry-After": "5"}))
        )

    def test_waits_and_tries_once_more(self):
        answers = [
            self.slow_down(429, **{"Retry-After": "20"}),
            response({"data": {"x": 1}}),
        ]
        with (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch("time.sleep") as sleep,
            mock.patch("urllib.request.urlopen", side_effect=answers),
        ):
            self.assertEqual(github.graphql("token", "query", {}), {"x": 1})
        sleep.assert_called_once_with(20)

    def test_gives_up_on_a_long_wait(self):
        err = self.slow_down(429, **{"Retry-After": str(config.MAX_RETRY_AFTER + 1)})
        with (
            mock.patch("time.sleep") as sleep,
            mock.patch("urllib.request.urlopen", side_effect=err),
            self.assertRaises(urllib.error.HTTPError),
        ):
            github.graphql("token", "query", {})
        sleep.assert_not_called()


class Compressed(unittest.TestCase):
    """compressed=True: a big page from a trusted source comes gzipped."""

    def fetch(self, body, encoding, **kwargs):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = body
        resp.headers = {"Content-Encoding": encoding} if encoding else {}
        with mock.patch("urllib.request.urlopen", return_value=resp) as urlopen:
            text = http.get("https://example.org/", **kwargs)
        return text, urlopen.call_args.args[0].headers

    def test_asks_for_gzip_and_unpacks_it(self):
        text, headers = self.fetch(gzip.compress(b"index"), "gzip", compressed=True)
        self.assertEqual(text, "index")
        self.assertEqual(headers.get("Accept-encoding"), "gzip")

    def test_a_plain_answer_too(self):
        text, _ = self.fetch(b"index", None, compressed=True)
        self.assertEqual(text, "index")

    def test_not_asked_otherwise(self):
        _, headers = self.fetch(b"index", None)
        self.assertNotIn("Accept-encoding", headers)


class GetPage(unittest.TestCase):
    """http.get_page: a page the server only sends if it changed."""

    def answer(self, status_or_body, headers=None):
        def urlopen(req, timeout):
            urlopen.sent = dict(req.header_items())
            if status_or_body == 304:
                e = urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)
                raise e
            resp = mock.MagicMock()
            resp.__enter__.return_value = resp
            resp.read.return_value = status_or_body
            resp.headers = headers or {}
            return resp

        return urlopen

    def test_reads_it_and_what_to_send_next_time(self):
        urlopen = self.answer(b"page", {"ETag": '"a"', "Last-Modified": "Fri"})
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            text, cached = http.get_page("https://example.org/")
        self.assertEqual(
            (text, cached), ("page", {"etag": '"a"', "lastModified": "Fri"})
        )
        self.assertNotIn("If-none-match", urlopen.sent)

    def test_unchanged(self):
        urlopen = self.answer(304)
        cached = {"etag": '"a"', "lastModified": "Fri"}
        with mock.patch("urllib.request.urlopen", side_effect=urlopen):
            text, again = http.get_page("https://example.org/", cached)
        self.assertIs(text, http.NOT_MODIFIED)
        self.assertEqual(again, cached)
        self.assertEqual(urlopen.sent["If-none-match"], '"a"')
        self.assertEqual(urlopen.sent["If-modified-since"], "Fri")

    def test_unchanged_in_safe_mode_too(self):
        urlopen = self.answer(304)
        with (
            mock.patch.object(http._safe_opener, "open", side_effect=urlopen),
            mock.patch.object(http, "check_public"),
        ):
            text, _ = http.get_page("https://example.org/", {"etag": '"a"'}, safe=True)
        self.assertIs(text, http.NOT_MODIFIED)

    def test_a_304_not_asked_for_is_an_error(self):
        urlopen = self.answer(304)
        with (
            mock.patch.object(config, "RETRY_DELAYS", []),
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch("urllib.request.urlopen", side_effect=urlopen),
            self.assertRaises(urllib.error.HTTPError),
        ):
            http.get("https://example.org/")


class SitePause(unittest.TestCase):
    """Update checks' pages: one request a second to the same site at most
    (http.pace); different sites don't wait for each other."""

    def setUp(self):
        self.now = 1000.0
        self.slept = []

        def sleep(seconds):
            self.slept.append(round(seconds, 3))
            self.now += seconds

        for patcher in (
            mock.patch.object(config, "SITE_PAUSE_SECONDS", 1),
            mock.patch.object(http, "_last_asked", {}),
            mock.patch("time.monotonic", side_effect=lambda: self.now),
            mock.patch("time.sleep", side_effect=sleep),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_the_same_site_waits(self):
        http.pace("https://pypi.org/pypi/a/json")
        self.now += 0.25
        http.pace("https://PyPI.org/pypi/b/json")  # the same site, any case
        self.assertEqual(self.slept, [0.75])

    def test_other_sites_dont(self):
        http.pace("https://pypi.org/pypi/a/json")
        http.pace("https://www.barebones.com/updates.html")
        self.assertEqual(self.slept, [])

    def test_after_a_while_no_wait(self):
        http.pace("https://pypi.org/pypi/a/json")
        self.now += 5
        http.pace("https://pypi.org/pypi/b/json")
        self.assertEqual(self.slept, [])

    def test_get_page_is_paced(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = b"page"
        resp.headers = {}
        with mock.patch("urllib.request.urlopen", return_value=resp):
            http.get_page("https://pypi.org/pypi/a/json")
            http.get_page("https://pypi.org/pypi/b/json")
        self.assertEqual(self.slept, [1.0])


class Deadline(unittest.TestCase):
    """A whole answer has FETCH_DEADLINE_SECONDS to arrive, however steadily
    it trickles in: a real server on this machine sending a byte at a time."""

    BODY = b"x" * 60

    def setUp(self):
        body = self.BODY

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    for i in range(len(body)):
                        self.wfile.write(body[i : i + 1])
                        self.wfile.flush()
                        if self.path == "/slow":
                            time.sleep(0.02)
                except OSError:
                    pass  # the client gave up

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_address[1]}"
        for patcher in (
            mock.patch("sys.stderr", io.StringIO()),
            mock.patch.object(config, "RETRY_DELAYS", []),
            mock.patch.object(config, "FETCH_DEADLINE_SECONDS", 0.3),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_trickle_is_given_up(self):
        # 60 bytes at 20 ms each: 1.2 s, against 0.3 s.
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            http.get(self.base + "/slow")
        self.assertLess(time.monotonic() - started, 1)

    def test_a_steady_answer_arrives(self):
        self.assertEqual(http.get(self.base + "/fast"), self.BODY.decode())

    def test_downloads_have_longer(self):
        with mock.patch.object(config, "DOWNLOAD_DEADLINE_SECONDS", 10):
            self.assertEqual(http.get_bytes(self.base + "/slow"), self.BODY)

    def test_at_most_the_limit(self):
        with urllib.request.urlopen(self.base + "/fast", timeout=5) as resp:
            body = http._read(resp, time.monotonic() + 5, limit=50)
        self.assertEqual(len(body), 51)  # one more: over the limit
