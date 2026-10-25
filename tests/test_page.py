"""The page shipped with nixkeeper: `nixkeeper page` (a folder to host) and
`nixkeeper serve` (on this computer)."""

import io
import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest import mock

from nixkeeper import cli, config, page


class Page(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.data = os.path.join(self.dir.name, "data")
        os.mkdir(self.data)
        self.put("index.json", {"packages": [{"name": "unciv"}]})
        self.put("unciv.json", [])
        patcher = mock.patch.object(config, "OUT_DIR", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)
        out = mock.patch("sys.stdout", io.StringIO())
        out.start()
        self.addCleanup(out.stop)

    def put(self, name, value):
        with open(os.path.join(self.data, name), "w") as f:
            json.dump(value, f)

    def test_the_page_is_there(self):
        self.assertTrue(os.path.exists(os.path.join(page.page_dir(), "index.html")))
        self.assertTrue(os.path.exists(os.path.join(page.page_dir(), "logic.js")))

    def test_writes_the_page_and_the_data(self):
        site = os.path.join(self.dir.name, "site")
        cli.main(["page", site, "--data-dir", self.data])
        for name in ("index.html", "app.js", "style.css", "favicon.svg"):
            self.assertTrue(os.path.exists(os.path.join(site, name)), name)
        with open(os.path.join(site, "data", "index.json")) as f:
            self.assertEqual(json.load(f)["packages"][0]["name"], "unciv")

    def test_again_replaces_the_data(self):
        site = os.path.join(self.dir.name, "site")
        page.write(site)
        os.remove(os.path.join(self.data, "unciv.json"))
        self.put("index.json", {"packages": []})
        page.write(site)
        self.assertEqual(os.listdir(os.path.join(site, "data")), ["index.json"])
        self.assertFalse(os.path.exists(os.path.join(site, "data.tmp")))

    def test_the_data_is_never_deleted_from_under_a_host(self):
        # Swapped in as the sync's own is: after each folder deleted, the
        # data is still there.
        site = os.path.join(self.dir.name, "site")
        page.write(site)
        rmtree, missing = shutil.rmtree, []

        def watched(path, *args, **kwargs):
            rmtree(path, *args, **kwargs)
            if not os.path.isdir(os.path.join(site, "data")):
                missing.append(path)

        with mock.patch("shutil.rmtree", watched):
            page.write(site)
        self.assertEqual(missing, [])
        self.assertEqual(
            sorted(os.listdir(os.path.join(site, "data"))), ["index.json", "unciv.json"]
        )
        self.assertFalse(os.path.exists(os.path.join(site, "data.old")))

    def test_a_write_cut_short_is_tidied(self):
        # Died between the swap's two renames: no data/, the last in data.old.
        site = os.path.join(self.dir.name, "site")
        page.write(site)
        os.rename(os.path.join(site, "data"), os.path.join(site, "data.old"))
        page.write(site)
        self.assertTrue(os.path.exists(os.path.join(site, "data", "index.json")))
        self.assertFalse(os.path.exists(os.path.join(site, "data.old")))

    def test_into_an_empty_folder(self):
        site = os.path.join(self.dir.name, "empty")
        os.mkdir(site)
        page.write(site)
        self.assertTrue(os.path.exists(os.path.join(site, "index.html")))

    def test_never_over_something_else(self):
        site = os.path.join(self.dir.name, "home")
        os.makedirs(os.path.join(site, "data"))
        open(os.path.join(site, "data", "precious.txt"), "w").close()
        with self.assertRaises(SystemExit) as exit:
            page.write(site)
        self.assertIn("isn't a nixkeeper page", str(exit.exception.code))
        self.assertEqual(os.listdir(os.path.join(site, "data")), ["precious.txt"])
        a_file = os.path.join(self.dir.name, "file")
        open(a_file, "w").close()
        with self.assertRaises(SystemExit):
            page.write(a_file)

    def test_needs_a_sync_first(self):
        os.remove(os.path.join(self.data, "index.json"))
        with self.assertRaises(SystemExit) as exit:
            page.write(os.path.join(self.dir.name, "site"))
        self.assertIn("nixkeeper sync", str(exit.exception.code))


class Serve(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.data = os.path.join(self.dir.name, "state", "data")
        os.makedirs(self.data)
        with open(os.path.join(self.data, "index.json"), "w") as f:
            json.dump({"packages": []}, f)
        with open(os.path.join(self.dir.name, "state", "secret.txt"), "w") as f:
            f.write("not for the page")
        quiet = mock.patch.object(page._Handler, "log_message")
        quiet.start()
        self.addCleanup(quiet.stop)
        httpd = page.server(0, "127.0.0.1", data=self.data)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        self.base = f"http://127.0.0.1:{httpd.server_address[1]}"

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=5) as resp:
            return resp.headers.get_content_type(), resp.read().decode()

    def test_the_page(self):
        kind, body = self.get("/")
        self.assertEqual(kind, "text/html")
        self.assertIn("<title>nixkeeper", body)
        kind, _ = self.get("/app.js")
        self.assertEqual(kind, "text/javascript")  # a module script needs it

    def test_the_data_where_it_is(self):
        _, body = self.get("/data/index.json?cache=no")
        self.assertEqual(json.loads(body), {"packages": []})
        with open(os.path.join(self.data, "index.json"), "w") as f:
            json.dump({"packages": [{"name": "new"}]}, f)
        _, body = self.get("/data/index.json")
        self.assertEqual(json.loads(body)["packages"][0]["name"], "new")

    def test_before_the_first_sync(self):
        empty = os.path.join(self.dir.name, "no-data-yet")
        httpd = page.server(0, "127.0.0.1", data=empty)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        with urllib.request.urlopen(base + "/", timeout=5) as resp:
            self.assertIn("<title>nixkeeper", resp.read().decode())
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(base + "/data/index.json", timeout=5)
        self.assertEqual(e.exception.code, 404)

    def test_nothing_outside_the_page_and_the_data(self):
        for path in (
            "/data/../secret.txt",
            "/data/%2e%2e/secret.txt",
            "/../state/secret.txt",
        ):
            with (
                self.subTest(path=path),
                self.assertRaises(urllib.error.HTTPError) as e,
            ):
                self.get(path)
            self.assertEqual(e.exception.code, 404)


class Commands(unittest.TestCase):
    def test_page_and_serve(self):
        with (
            mock.patch("nixkeeper.lock.held"),
            mock.patch.multiple(config, LISTS=config.LISTS, OUT_DIR=config.OUT_DIR),
            mock.patch.object(page, "write", return_value="/x") as write,
            mock.patch.object(page, "serve") as serve,
            mock.patch("sys.stdout", io.StringIO()),
        ):
            cli.main(["page", "site"])
            cli.main(["serve", "--port", "9000"])
        write.assert_called_once_with("site")
        serve.assert_called_once_with(9000, "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
