"""What the sync's sources were (sources/about.py), for the manifest."""

import threading
import unittest

from nixkeeper.sources import about


class About(unittest.TestCase):
    def test_noted_inside_the_block_sorted_by_source(self):
        with about.collecting() as noted:
            about.note("updates", True, at="2026-10-05T15:00:00+00:00", pending=None)
            about.note("hydra", False, "too old", eval=1829803)
        self.assertEqual(
            noted,
            {
                "hydra": {"used": False, "why": "too old", "eval": 1829803},
                "updates": {"used": True, "at": "2026-10-05T15:00:00+00:00"},
            },
        )
        self.assertEqual(list(noted), ["hydra", "updates"])

    def test_nothing_kept_outside_a_block(self):
        about.note("updates", True)
        with about.collecting() as noted:
            pass
        about.note("hydra", True)
        self.assertEqual(noted, {})

    def test_from_another_thread_too(self):
        # Hydra's source notes itself from the sync's background thread.
        with about.collecting() as noted:
            thread = threading.Thread(target=about.note, args=("hydra", True))
            thread.start()
            thread.join()
        self.assertEqual(noted, {"hydra": {"used": True}})

    def test_the_innermost_block_collects(self):
        with about.collecting() as outer:
            with about.collecting() as inner:
                about.note("prs", True)
            about.note("hydra", True)
        self.assertEqual((list(outer), list(inner)), (["hydra"], ["prs"]))

    def test_a_long_reason_is_cut(self):
        with about.collecting() as noted:
            about.note("versions", False, "x" * 500)
        why = noted["versions"]["why"]
        self.assertEqual(len(why), about.WHY_LENGTH)
        self.assertTrue(why.endswith("…"))
