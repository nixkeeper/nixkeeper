"""How the data's files are named: shared by the writer and its checks.

Both datastore/, which writes the data, and shape.py, which checks it,
need the same rules. Keeping them here, in one place, means a change to
a rule reaches both.
"""

import re
import zlib


def slug(name):
    """Turn a team's or list's name into its view's file name.

    The page does the same in viewSlug (page/logic.js).

    Args:
        name: The name, such as "Security review".

    Returns:
        The file name without ".json", such as "security-review".
    """
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


# A shard's path in data/, its number captured: rows/<number>.json.
SHARD_FILE = re.compile(r"rows/(\d+)\.json")


def shard_of(name, count):
    """Find which shard a row is written in.

    The shard is a stable hash of the row's name, so adding or removing a
    package changes only its own shard's file.

    Args:
        name: The row's name.
        count: How many shards there are.

    Returns:
        The shard's number, from 0 to count - 1: the row is in
        rows/<number>.json.
    """
    return zlib.crc32(name.encode()) % count
