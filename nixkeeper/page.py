"""The page (page/), shipped with nixkeeper: `nixkeeper page <dir>` writes it
with the data into a folder ready for any static host, `nixkeeper serve`
shows it on this computer. The page finds the data by itself as data/ next to
it."""

import functools
import http.server
import os
import shutil
import sys
import urllib.parse
from importlib import resources

from . import config

# Where the package carries the page (copied in from page/ when it's built),
# and where a checkout has it.
_PACKAGED = resources.files("nixkeeper") / "page"
_CHECKOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "page")


def page_dir():
    """The page's folder: the package's copy, or a checkout's page/."""
    if _PACKAGED.is_dir():
        return str(_PACKAGED)
    if os.path.exists(os.path.join(_CHECKOUT, "index.html")):
        return os.path.normpath(_CHECKOUT)
    sys.exit(
        "nixkeeper's page isn't here: this copy of nixkeeper was built without it."
    )


def _data_dir():
    data = config.OUT_DIR
    if not os.path.exists(os.path.join(data, "index.json")):
        sys.exit(f"No data in {data} yet: run `nixkeeper sync` first.")
    return data


def _is_page(folder):
    """Whether folder is empty, or a page this command wrote: the only
    folders it will write into (it replaces their data/)."""
    if not os.listdir(folder):
        return True
    try:
        with open(os.path.join(folder, "index.html")) as f:
            return "<title>nixkeeper" in f.read()
    except OSError:
        return False


def write(folder):
    """The page and a copy of the data in folder, created if needed. Only
    into an empty folder or an earlier page: never over anything else."""
    data = _data_dir()
    folder = os.path.abspath(folder)
    if os.path.exists(folder) and not (os.path.isdir(folder) and _is_page(folder)):
        sys.exit(
            f"{folder} isn't empty and isn't a nixkeeper page: give `page` a new "
            "or empty folder."
        )
    os.makedirs(folder, exist_ok=True)
    source = page_dir()
    for name in os.listdir(source):
        target = os.path.join(folder, name)
        shutil.copyfile(os.path.join(source, name), target)
        os.chmod(target, 0o644)  # read-only when copied from the Nix store
    # The data swapped in whole, so a host never serves half of it.
    staged = os.path.join(folder, "data.tmp")
    shutil.rmtree(staged, ignore_errors=True)
    shutil.copytree(data, staged)
    shutil.rmtree(os.path.join(folder, "data"), ignore_errors=True)
    os.rename(staged, os.path.join(folder, "data"))
    return folder


class _Handler(http.server.SimpleHTTPRequestHandler):
    """The page's files, and /data/ from the data folder, read where they are
    (so a sync shows on the next reload)."""

    def __init__(self, *args, page, data, **kwargs):
        self.page, self.data = page, data
        super().__init__(*args, directory=page, **kwargs)

    def translate_path(self, path):
        clean = urllib.parse.urlsplit(path).path
        if clean == "/data" or clean.startswith("/data/"):
            self.directory = self.data
            path = path[len("/data") :] or "/"
        else:
            self.directory = self.page
        return super().translate_path(path)


def server(port, bind, page=None, data=None):
    """An HTTP server for the page and data (not yet serving)."""
    handler = functools.partial(
        _Handler, page=page or page_dir(), data=os.path.abspath(config.data_dir(data))
    )
    return http.server.ThreadingHTTPServer((bind, port), handler)


def serve(port, bind):
    """Serve until stopped. Without data yet, the page says it can't find
    any until a sync writes it (so it can be started before the first one)."""
    if not os.path.exists(os.path.join(config.OUT_DIR, "index.json")):
        print(
            f"No data in {config.OUT_DIR} yet: the page shows it once "
            "`nixkeeper sync` has run.",
            file=sys.stderr,
        )
    httpd = server(port, bind)
    host, port = httpd.server_address[:2]
    print(f"nixkeeper's page: http://{host}:{port}/  (Ctrl+C to stop)", file=sys.stderr)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
