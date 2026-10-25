"""nixkeeper.config: where the data folder is."""

import json
import os
import tempfile
import unittest
from unittest import mock

from nixkeeper import config, datastore


class DataDir(unittest.TestCase):
    def test_a_given_folder_first(self):
        with mock.patch.object(config, "OUT_DIR", "configured"):
            self.assertEqual(config.data_dir("given"), "given")

    def test_the_setting_as_it_is_when_called(self):
        # --data-dir sets OUT_DIR after the modules are imported.
        with mock.patch.object(config, "OUT_DIR", "set later"):
            self.assertEqual(config.data_dir(), "set later")
            self.assertEqual(config.data_dir(None), "set later")

    def test_a_reader_follows_the_setting(self):
        with tempfile.TemporaryDirectory() as folder:
            with open(os.path.join(folder, "history.json"), "w") as f:
                json.dump({"points": [{"day": "2026-10-25"}]}, f)
            with mock.patch.object(config, "OUT_DIR", folder):
                self.assertEqual(datastore.read_history(), [{"day": "2026-10-25"}])


if __name__ == "__main__":
    unittest.main()
