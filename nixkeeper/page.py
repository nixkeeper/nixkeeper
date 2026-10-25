"""Write or serve the page (page/), which ships with nixkeeper.

`nixkeeper page <dir>` writes the page with a copy of the data into a
folder, ready for any static host; `nixkeeper serve` shows it on this
computer. Either way the page finds its data by itself, as data/ next to
it.
"""

import functools
import http.server
import os
import shutil
import sys
import urllib.parse
from importlib import resources

from . import config, datastore

# Where the package carries the page (copied in from page/ when it's built),
# and where a checkout has it.
_PACKAGED = resources.files("nixkeeper") / "page"
_CHECKOUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "page")


def page_dir():
    """Return the page's folder: the package's copy, or a checkout's page/.

    Raises:
        SystemExit: There's neither: this copy of nixkeeper was built
            without the page.
    """
    if _PACKAGED.is_dir():
        return str(_PACKAGED)
    if os.path.exists(os.path.join(_CHECKOUT, "index.html")):
        return os.path.normpath(_CHECKOUT)
    sys.exit(
        "nixkeeper's page isn't here: this copy of nixkeeper was built without it."
    )


def _data_dir_or_exit():
    """Return the data folder, or exit when no sync has written data there.

    Raises:
        SystemExit: The data folder has no index.json yet.
    """
    data = config.data_dir()
    if not os.path.exists(os.path.join(data, "index.json")):
        sys.exit(f"No data in {data} yet: run `nixkeeper sync` first.")
    return data


def _is_page(folder):
    """Return whether folder is empty, or a page this command wrote.

    Those are the only folders `nixkeeper page` writes into, as it replaces
    their data/.
    """
    if not os.listdir(folder):
        return True
    try:
        with open(os.path.join(folder, "index.html")) as f:
            return "<title>nixkeeper" in f.read()
    except OSError:
        return False


def write(folder):
    """Write the page and a copy of the data into folder.

    The folder is created if needed. Only an empty folder or an earlier
    page is written into, never anything else.

    Returns:
        The folder, as an absolute path.

    Raises:
        SystemExit: There's no data yet, folder is neither empty nor an
            earlier page, or this nixkeeper was built without the page.
    """
    data = _data_dir_or_exit()
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
    # The data is copied aside, then swapped in as the sync swaps its own
    # (datastore.swap_in): a host never serves half of it, and finds none
    # only between two renames. A write cut short between them is tidied
    # first: only this command writes this copy, under the data folder's
    # lock (cli.py), so no other write can be under way.
    target = os.path.join(folder, "data")
    datastore.restore_interrupted_swap(target)
    staged = target + ".tmp"
    shutil.rmtree(staged, ignore_errors=True)
    shutil.copytree(data, staged)
    datastore.swap_in(staged, target)
    return folder


class _Handler(http.server.SimpleHTTPRequestHandler):
    """Serve the page's files, and /data/ from the data folder.

    Both are read where they are, so a sync shows on the next reload.
    """

    def __init__(self, *args, page, data, **kwargs):
        self.page, self.data = page, data
        super().__init__(*args, directory=page, **kwargs)

    def translate_path(self, path):
        """Map /data/... to the data folder, and every other path to the page."""
        clean = urllib.parse.urlsplit(path).path
        if clean == "/data" or clean.startswith("/data/"):
            self.directory = self.data
            path = path[len("/data") :] or "/"
        else:
            self.directory = self.page
        return super().translate_path(path)


def server(port, bind, page=None, data=None):
    """Make an HTTP server for the page and its data, not yet serving.

    Args:
        port: The port to listen on (0 for any free one).
        bind: The address to listen on.
        page: The page's folder (page_dir by default).
        data: The data folder (the configured one by default).
    """
    handler = functools.partial(
        _Handler, page=page or page_dir(), data=os.path.abspath(config.data_dir(data))
    )
    return http.server.ThreadingHTTPServer((bind, port), handler)


def serve(port, bind):
    """Serve the page until stopped.

    Without data yet, the page says it can't find any until a sync writes
    it, so the server can be started before the first sync.
    """
    data = config.data_dir()
    if not os.path.exists(os.path.join(data, "index.json")):
        print(
            f"No data in {data} yet: the page shows it once `nixkeeper sync` has run.",
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
