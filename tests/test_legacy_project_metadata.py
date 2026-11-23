"""Versioned import metadata preserves earlier recipes and user-owned text."""

from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.legacy_project_metadata import LEGACY_METADATA_VERSION, saved_analysis
from analisi.legacy_restore import LEGACY_TITLE, SAVED_XY


class LegacyProjectMetadataTests(unittest.TestCase):
    def test_import_metadata_uses_its_own_workspace_version(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "workspace.alab"
            source = Dataset(pd.DataFrame({"Run A": [1.0, 3.0]}))
            save_project(path, {"Measurements": source})
            self.assertEqual(json.loads(path.read_text())["version"], 2)

            source.analyses = [(SAVED_XY, {LEGACY_TITLE: "Preserve the title as entered"})]
            save_project(path, {"Measurements": source})
            self.assertEqual(json.loads(path.read_text())["version"], LEGACY_METADATA_VERSION)
            restored = load_project(path)["Measurements"]
            self.assertEqual(restored.analyses, source.analyses)
            pd.testing.assert_frame_equal(restored.raw, source.raw, check_dtype=False)

    def test_known_retired_name_is_translated_at_the_recipe_boundary(self):
        old_title_key = "Retired title"
        old_method = "Retired XY graph"
        aliases = {sha256(old.encode()).hexdigest(): new for old, new in
                   ((old_title_key, LEGACY_TITLE), (old_method, SAVED_XY))}
        with patch.dict("analisi.legacy_project_metadata._RETIRED_NAMES", aliases):
            method, options = saved_analysis(old_method, {old_title_key: old_method})
            self.assertEqual((method, options), (SAVED_XY, {LEGACY_TITLE: old_method}))
            with self.assertRaisesRegex(ValueError, "Duplicate versioned analysis option"):
                saved_analysis(old_method, {old_title_key: "old", LEGACY_TITLE: "new"})


if __name__ == "__main__":
    unittest.main()
