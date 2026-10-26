"""Read and write data/, the page's data folder, through one set of names.

Everything that reads the last run's data (history, schedules,
notifications, the hourly checks) or writes a new run's goes through here.
The work is in five modules: shards (the rows' shards and the summary),
facts (what each row says), trends (the history, fixed and events records),
view_files (the views the overview reads, with every package) and folder
(writing, swapping and reading data/, in the format it describes).
"""

from .facts import highlights, nothing_compared, numbers, status, unbuilt_where
from .folder import (
    MERGE_VIEW,
    SYNC_ONLY,
    check_kept,
    entries,
    files,
    load,
    restore_interrupted_swap,
    saved_entries,
    swap_in,
    update,
    write,
)
from .shards import (
    PANEL_ONLY,
    data_file,
    kept_entries,
    newest_repos,
    shard_count,
    summary_entry,
)
from .trends import (
    fixed_summary,
    read_events,
    read_fixed,
    read_history,
    with_events,
    with_fixed,
    with_split,
)
from .view_files import views

__all__ = [
    "check_kept",
    "data_file",
    "entries",
    "files",
    "fixed_summary",
    "highlights",
    "kept_entries",
    "load",
    "MERGE_VIEW",
    "newest_repos",
    "nothing_compared",
    "numbers",
    "PANEL_ONLY",
    "read_events",
    "read_fixed",
    "read_history",
    "restore_interrupted_swap",
    "saved_entries",
    "shard_count",
    "status",
    "summary_entry",
    "swap_in",
    "SYNC_ONLY",
    "unbuilt_where",
    "update",
    "views",
    "with_events",
    "with_fixed",
    "with_split",
    "write",
]
