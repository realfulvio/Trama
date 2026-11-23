import tempfile
import unittest
from pathlib import Path

import pandas as pd

from analisi.data import Dataset, load_project, save_project
from trama_qt.project import Project


class WorksheetAppearanceTests(unittest.TestCase):
    def test_editing_highlights_leaves_data_intact_and_round_trips(self):
        original = pd.DataFrame({"Category": ["A", "B"], "Count": [22, 16]})
        table = Dataset(original.copy(), analyses=[("Linear regression", {})])
        table.set_background((0, 0, 1, 0), "#FFD966")
        table.set_result_background(0, "Weights", (0, 1, 0, 1), (2, 2), "#E4F3FF")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "appearance.alab"
            save_project(path, {"Example": table})
            reopened = load_project(path)["Example"]
        self.assertEqual(reopened.cell_backgrounds, {(0, "Category"): "#ffd966", (1, "Category"): "#ffd966"})
        self.assertEqual(reopened.result_backgrounds, {0: {"Weights": {(0, 1): "#e4f3ff"}}})
        pd.testing.assert_frame_equal(reopened.raw, original, check_dtype=False)

    def test_highlight_follows_source_edits_and_undo(self):
        project = Project()
        project.add_tables({"Example": pd.DataFrame({"Count": [22, 16]})})
        project.set_table_background("Example", (0, 0, 0, 0), "#ffd966")
        project.insert_rows("Example", 0)
        project.rename_column("Example", 0, "Value")
        data = project.tables["Example"]
        self.assertEqual(data.cell_backgrounds, {(1, "Value"): "#ffd966"})
        project.undo()
        project.undo()
        self.assertEqual(data.cell_backgrounds, {(0, "Count"): "#ffd966"})
        self.assertEqual(project.undo(), ("Example", []))
        self.assertEqual(data.cell_backgrounds, {})

    def test_font_is_shared_with_other_preferences_and_zoom_can_reset(self):
        from analisi.i18n import load_language, save_language
        from analisi.worksheet_appearance import font_preference, save_font_preference, zoom_step

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "preferences.json"
            save_language(path, "it")
            save_font_preference(path, "Segoe UI", 13)
            self.assertEqual(font_preference(path), ("Segoe UI", 13))
            self.assertEqual(load_language(path), "it")
            save_font_preference(path, "Segoe UI", None)
            self.assertEqual(font_preference(path), ("Segoe UI", None))
        self.assertEqual(zoom_step(100, 1), 110)
        self.assertEqual(zoom_step(200, 1), 200)
        self.assertEqual(zoom_step(175, 0), 100)
