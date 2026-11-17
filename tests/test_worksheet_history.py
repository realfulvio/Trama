import unittest

import pandas as pd
from pandas.testing import assert_frame_equal

from analisi.data import Dataset
from analisi.grid_data import paste_block
from analisi.worksheet_history import WorksheetHistory, WorksheetState


class WorksheetHistoryTests(unittest.TestCase):
    def test_edit_growth_undo_redo_and_divergent_edit(self):
        data = Dataset(pd.DataFrame({"Exact": [2**53 + 3, 8]}), excluded={(1, 0)})
        history = WorksheetHistory()
        before = WorksheetState.capture(data)
        paste_block(data, 1, 0, [["9", "001"], ["12", "002"]])
        after = WorksheetState.capture(data)
        history.record("Data", "Paste", before, after)
        tables = {"Data": data}

        self.assertEqual(history.apply(tables).label, "Paste")
        assert_frame_equal(data.raw, before.raw)
        self.assertEqual(data.excluded, {(1, 0)})
        self.assertEqual(history.apply(tables, redo=True).label, "Paste")
        assert_frame_equal(data.raw, after.raw)
        self.assertEqual(data.raw.iat[0, 0], 2**53 + 3)

        history.apply(tables)
        paste_block(data, 1, 0, [["7"]])
        history.record("Data", "Edit", before, WorksheetState.capture(data))
        self.assertFalse(history.can_apply(redo=True))
        self.assertEqual(data.raw.iat[1, 0], 7)

    def test_invalid_formula_context_leaves_revision_and_dataset_unchanged(self):
        data = Dataset(pd.DataFrame({"X": [1, 2]}), info={"scale": "2"})
        data.set_formula("Scaled", '=X * INFO("Scale")')
        before = WorksheetState.capture(data)
        data.formulas = {}
        history = WorksheetHistory()
        history.record("Data", "Formula", before, WorksheetState.capture(data))
        data.info = {}
        with self.assertRaisesRegex(ValueError, "Scale"):
            history.apply({"Data": data})
        self.assertFalse(data.formulas)
        self.assertTrue(history.can_apply())
        data.info = {"scale": "3"}
        history.apply({"Data": data})
        self.assertEqual(data.frame()["Scaled"].tolist(), [3, 6])

    def test_history_trims_to_budget_and_can_be_cleared(self):
        data = Dataset(pd.DataFrame({"X": [1]}))
        history = WorksheetHistory(memory_budget=1)
        for value in ("2", "3"):
            before = WorksheetState.capture(data)
            paste_block(data, 0, 0, [[value]])
            history.record("Data", "Edit", before, WorksheetState.capture(data))
        history.apply({"Data": data})
        self.assertEqual(data.raw.iat[0, 0], 2)
        self.assertFalse(history.can_apply())
        self.assertTrue(history.can_apply(redo=True))
        history.clear()
        self.assertFalse(history.can_apply(redo=True))
