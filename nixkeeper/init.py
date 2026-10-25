"""Write starter package lists, for `nixkeeper init`.

The lists come from the templates shipped with nixkeeper
(nixkeeper/templates/package-lists/), with the given maintainers filled in.
"""

import os
import re
import shutil
from importlib import resources

from .errors import Problem

# What GitHub allows in a handle: also keeps anything else out of the Nix file.
HANDLE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}$")
# The template's maintainers line, replaced with the given handles.
EMPTY = "maintainers = [ ];"


def write(folder, maintainers):
    """Write the starter lists to folder, listing maintainers.

    Args:
        folder: Where to write them; it mustn't exist yet.
        maintainers: The GitHub handles to list.

    Raises:
        Problem: folder is a JSON file's name or exists already, or one
            of maintainers isn't a GitHub handle.
    """
    if folder.endswith(".json"):
        raise Problem(f"{folder} is a JSON file: init writes a folder of Nix files.")
    if os.path.exists(folder):
        raise Problem(
            f"{folder} already exists: edit it, or give init another place "
            "with --lists."
        )
    bad = [m for m in maintainers if not HANDLE.match(m)]
    if bad:
        raise Problem(f"Not a GitHub handle: {', '.join(bad)}")
    templates = resources.files("nixkeeper") / "templates" / "package-lists"
    with resources.as_file(templates) as source:
        shutil.copytree(source, folder)
    for name in os.listdir(folder):  # read-only when copied from the Nix store
        os.chmod(os.path.join(folder, name), 0o644)
    os.chmod(folder, 0o755)
    if maintainers:
        path = os.path.join(folder, "default.nix")
        with open(path) as f:
            text = f.read()
        handles = "".join(f'    "{m}"\n' for m in maintainers)
        with open(path, "w") as f:
            f.write(text.replace(EMPTY, f"maintainers = [\n{handles}  ];", 1))
