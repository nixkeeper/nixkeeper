"""One run at a time on a data folder.

The sync and the frequent checks all write the data folder, and
`nixkeeper page` copies it. Each holds a lock file next to the folder
(<data dir>.lock) while it runs, and a second run waits for the first.
Holding the lock is also when a swap a run didn't finish is tidied up
(datastore.restore_interrupted_swap): nothing else can be writing then.
"""

import contextlib
import fcntl
import os
import sys

from . import config, datastore


def path(out_dir=None):
    return os.path.abspath(out_dir or config.OUT_DIR) + ".lock"


@contextlib.contextmanager
def held(out_dir=None):
    """Hold the data folder's lock for the block, waiting while another run has it.

    The wait is said in the log. Once the lock is held, a swap a run didn't
    finish is tidied up first. The lock is released when the block ends,
    or when the process does.

    Args:
        out_dir: The data folder (the configured one by default).
    """
    lock = path(out_dir)
    os.makedirs(os.path.dirname(lock), exist_ok=True)
    with open(lock, "a") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(
                f"Waiting for another nixkeeper run on {out_dir or config.OUT_DIR}...",
                file=sys.stderr,
            )
            fcntl.flock(f, fcntl.LOCK_EX)
        datastore.restore_interrupted_swap(out_dir)
        yield
