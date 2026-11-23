import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd
from pandas.testing import assert_frame_equal

from analisi.data import EDITABLE_LEGACY_XY, MAX_COLUMNS, Dataset, load_workspace, save_project
from analisi.grid_data import clear_block, clipboard_rows, copy_block, filter_clipboard_rows, paste_block
from analisi.grid_widget import _heading_bands


class GridDataTests(unittest.TestCase):
    def test_freeze_formula_keeps_position_exclusions_and_dependent_values(self):
        data = Dataset(pd.DataFrame({"Dose": [2, 4], "Result": [None, None], "Other": [7, 9]}),
                       excluded={(1, 0), (0, 2)})
        data.set_worksheet_formula(1, "=Dose * 2")
        data.set_formula("Adjusted", '=COL("Result") + 1')
        before = data.frame()
        data.freeze_worksheet_formula(1)
        self.assertEqual(list(data.raw), ["Dose", "Result", "Other"])
        self.assertEqual(data.source_indices, (0, 1, 2, None))
        self.assertEqual(data.excluded, {(1, 0), (0, 2)})
        self.assertEqual(set(data.formulas), {"Adjusted"})
        assert_frame_equal(data.frame(), before)
        paste_block(data, 0, 0, [["12"]])
        self.assertEqual(data.frame().loc[0, ["Result", "Adjusted"]].tolist(), [4, 5])
        paste_block(data, 0, 1, [["6"]])
        self.assertEqual(data.frame().loc[0, ["Result", "Adjusted"]].tolist(), [6, 7])
        self.assertTrue(pd.isna(data.frame().loc[1, "Result"]))
        with TemporaryDirectory() as folder:
            path = Path(folder) / "frozen.alab"
            save_project(path, {"Study": data})
            saved, _ = load_workspace(path)
        assert_frame_equal(saved["Study"].frame(), data.frame(), check_dtype=False)
        self.assertEqual(saved["Study"].excluded, data.excluded)

    def test_freeze_formula_rejects_a_source_column_and_oversize_without_changes(self):
        from unittest.mock import patch

        data = Dataset(pd.DataFrame({"Dose": [2, 4]}))
        data.set_formula("Derived", "=Dose * 2")
        raw, formulas = data.raw, data.formulas
        with self.assertRaisesRegex(ValueError, "calculated column"):
            data.freeze_worksheet_formula(0)
        with patch("analisi.data.MAX_CELLS", 3), self.assertRaisesRegex(ValueError, "size limit"):
            data.freeze_worksheet_formula(1)
        self.assertIs(data.raw, raw)
        self.assertIs(data.formulas, formulas)

    def test_formula_conversion_confirms_values_and_remaps_only_the_selected_source(self):
        frame = pd.DataFrame({"Dose": [2, 4], "Label": ["a", "b"], "Retained": [7, 9]})
        frame.attrs["worksheet_roles"] = {"x": [], "y": [["Dose"], ["Label"], ["Retained"]]}
        data = Dataset(frame, excluded={(0, 1), (1, 2)})
        original = data.raw
        with self.assertRaisesRegex(ValueError, "Confirm replacement"):
            data.set_worksheet_formula(1, "=A * 2")
        with self.assertRaisesRegex(ValueError, "cannot depend on itself"):
            data.set_worksheet_formula(1, "=B + 1", replace_values=True)
        self.assertIs(data.raw, original)
        self.assertEqual(data.excluded, {(0, 1), (1, 2)})
        data.set_worksheet_formula(1, '=CONCATENATE("A", A)', replace_values=True)
        self.assertEqual(list(data.frame()), ["Dose", "Label", "Retained"])
        self.assertEqual(data.frame()["Label"].tolist(), ["A2", "A4"])
        self.assertEqual(data.excluded, {(1, 1)})
        self.assertEqual(data.worksheet_excluded, {(1, 2)})
        self.assertIn("Dose", data.formulas["Label"])
        self.assertEqual(frame.attrs["worksheet_roles"]["y"], [["Dose"], ["Label"], ["Retained"]])
        with TemporaryDirectory() as folder:
            path = Path(folder) / "converted.alab"
            save_project(path, {"Study": data})
            saved, _ = load_workspace(path)
        self.assertEqual(saved["Study"].raw.attrs["worksheet_roles"]["y"], [["Dose"], ["Retained"]])
        assert_frame_equal(saved["Study"].frame(), data.frame(), check_dtype=False)

    def test_paste_keeps_expression_like_text_as_data_in_empty_columns(self):
        data = Dataset(pd.DataFrame({"Dose": [2., 4.], "Notes": pd.array([None, None], dtype="Float64")}))
        paste_block(data, 0, 1, [["=A * 2"]])
        self.assertEqual(data.raw["Notes"].iloc[0], "=A * 2")
        self.assertEqual(data.formulas, {})

    def test_paste_filter_keeps_first_then_skips_rows_before_writing(self):
        source = clipboard_rows('one\t0\r\ntwo\t1,25\r\n"three\ncontinued"\t2\r\nfour\t\r\nfive\t4\r\n')
        selected = filter_clipboard_rows(source, first=2, last=4, skip=1)
        self.assertEqual(selected, [["two", "1,25"], ["four", ""]])
        data = Dataset(pd.DataFrame({"Title": ["a", "b", "c", "d"], "Y": [1., 2., 3., 4.]}))
        paste_block(data, 1, 0, selected)
        self.assertEqual(data.raw["Title"].tolist(), ["a", "two", "four", "d"])
        self.assertEqual(data.raw.iat[1, 1], 1.25)
        self.assertTrue(pd.isna(data.raw.iat[2, 1]))
        for settings in ({"first": 0}, {"last": 6}, {"first": 3, "last": 2}, {"skip": -1}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                filter_clipboard_rows(source, **settings)

    def test_transpose_preserves_blank_positions_and_uses_destination_width(self):
        text = "1,25\t\t-3,75\r\n\t4,125\t\r\n"
        rows = clipboard_rows(text, max_columns=2, transpose=True)
        self.assertEqual(rows, [["1,25", ""], ["", "4,125"], ["-3,75", ""]])
        with self.assertRaisesRegex(ValueError, "size limit"):
            clipboard_rows(text, max_columns=1, transpose=True)
        data = Dataset(pd.DataFrame({"Dose": [1, 2, 3, 4], "A": [4.] * 4, "B": [5.] * 4}))
        paste_block(data, 1, 1, rows)
        self.assertEqual(data.raw.iat[1, 1], 1.25)
        self.assertEqual(data.raw.iat[2, 2], 4.125)
        self.assertEqual(data.raw.iat[3, 1], -3.75)
        self.assertTrue(pd.isna(data.raw.iat[1, 2]) and pd.isna(data.raw.iat[2, 1]))

    def test_clear_blanks_existing_cells_and_removes_only_their_exclusion_flags(self):
        data = Dataset(pd.DataFrame({
            "Count": pd.Series([2**63 + 5, 8], dtype="uint64"),
            "Flag": [True, False],
        }), excluded={(0, 0), (1, 0), (1, 1)})
        clear_block(data, (1, 0, 4, 1))
        self.assertEqual(data.raw.shape, (2, 2))
        self.assertEqual(data.raw.iat[0, 0], 2**63 + 5)
        self.assertTrue(data.raw.iat[0, 1])
        self.assertTrue(data.raw.iloc[1].isna().all())
        self.assertEqual(data.excluded, {(0, 0)})
        previous = data.raw
        clear_block(data, (1, 0, 4, 1))
        self.assertIs(data.raw, previous)

    def test_clear_rejects_calculated_columns_without_partial_mutation(self):
        data = Dataset(pd.DataFrame({"x": [2, 4]}), excluded={(1, 0)})
        data.set_formula("Twice", "=x*2")
        original = data.raw
        with self.assertRaisesRegex(ValueError, "Calculated"):
            clear_block(data, (0, 0, 1, 1))
        self.assertIs(data.raw, original)
        self.assertEqual(data.excluded, {(1, 0)})

    def test_excel_block_preserves_position_blanks_and_decimal_commas(self):
        data = Dataset(pd.DataFrame({"Dose": [1, 2, 3], "A": [4., 5., 6.], "B": [7., 8., 9.]}))
        rows = clipboard_rows("10,5\t\r\n\t12,25\r\n")
        paste_block(data, 1, 1, rows)
        self.assertEqual(data.raw.iloc[0].tolist(), [1, 4., 7.])
        self.assertEqual(data.raw.iat[1, 1], 10.5)
        self.assertTrue(pd.isna(data.raw.iat[1, 2]))
        self.assertTrue(pd.isna(data.raw.iat[2, 1]))
        self.assertEqual(data.raw.iat[2, 2], 12.25)

    def test_copy_preserves_full_precision_and_quotes_text(self):
        data = pd.DataFrame({"ID": ["001", "x\ty\nz"], "Count": [2**53 + 3, 8]})
        text = copy_block(data, (0, 0, 1, 1), {(1, 1)})
        self.assertEqual(clipboard_rows(text), [["001", str(2**53 + 3)], ["x\ty\nz", ""]])

    def test_grows_plain_table_and_infers_new_column_without_losing_ids(self):
        data = Dataset(pd.DataFrame({"Dose": [1, 2**53 + 3]}))
        paste_block(data, 1, 0, clipboard_rows("3\t001\r\n4\t002\r\n"))
        self.assertEqual(list(data.raw), ["Dose", "Column 2"])
        self.assertEqual(data.raw["Dose"].tolist(), [1, 3, 4])
        self.assertEqual(data.raw["Column 2"].iloc[1:].tolist(), ["001", "002"])

    def test_bad_value_or_formula_target_leaves_entire_block_untouched(self):
        data = Dataset(pd.DataFrame({"x": [2, 4], "y": [1., 2.]}))
        data.set_formula("twice", "=x*2")
        original = data.raw.copy()
        with self.assertRaisesRegex(ValueError, "requires a number"):
            paste_block(data, 0, 0, [["8", "text"]])
        with self.assertRaisesRegex(ValueError, "Calculated"):
            paste_block(data, 0, 1, [["8", "9"]])
        assert_frame_equal(original, data.raw)
        paste_block(data, 1, 0, [["6"]])
        self.assertEqual(data.frame()["twice"].tolist(), [4, 12])

    def test_decimal_paste_refuses_to_round_existing_large_integer(self):
        data = Dataset(pd.DataFrame({"ID": [2**53 + 3, 2]}))
        with self.assertRaisesRegex(ValueError, "precision"):
            paste_block(data, 1, 0, [["2.5"]])
        self.assertEqual(data.raw.iat[0, 0], 2**53 + 3)

    def test_quoted_values_and_ragged_rows_parse_as_a_rectangle(self):
        self.assertEqual(clipboard_rows('"A\tB"\tC\r\n"D\r\nE"\r\n'),
                         [["A\tB", "C"], ["D\r\nE", ""]])
        with self.assertRaisesRegex(ValueError, "clipboard"):
            clipboard_rows('"unclosed')

    def test_empty_numeric_column_refuses_lossy_inference(self):
        data = Dataset(pd.DataFrame({"X": [float("nan"), float("nan")]}))
        for values in ([["9007199254740995"], ["1.5"]], [["1e-999"], ["2.5"]]):
            with self.assertRaisesRegex(ValueError, "precision|range"):
                paste_block(data, 0, 0, values)
            self.assertTrue(data.raw["X"].isna().all())

    def test_boolean_clipboard_preserves_type(self):
        data = Dataset(pd.DataFrame({"Included": [True, False, True]}))
        paste_block(data, 1, 0, clipboard_rows("TRUE\r\n\r\n"))
        self.assertEqual(data.raw["Included"].dtype, "boolean")
        self.assertTrue(data.raw.iat[1, 0])
        self.assertTrue(pd.isna(data.raw.iat[2, 0]))

    def test_copy_includes_virtual_blank_rows_without_changing_precision(self):
        data = pd.DataFrame({"ID": [2**53 + 3]})
        text = copy_block(data, (0, 0, 1, 0), set())
        self.assertEqual(clipboard_rows(text), [[str(2**53 + 3)], [""]])

    def test_round_trip_for_existing_wide_projects(self):
        width = MAX_COLUMNS + 1
        data = Dataset(pd.DataFrame([list(range(width))]))
        text = copy_block(data.raw, (0, 0, 0, width - 1), set())
        with self.assertRaisesRegex(ValueError, "size"):
            clipboard_rows(text)
        paste_block(data, 0, 0, clipboard_rows(text, max_columns=width))
        self.assertEqual(data.raw.iloc[0].tolist(), list(range(width)))

    def test_copy_uses_decimal_mark_for_numeric_values_only(self):
        data = pd.DataFrame({"Value": [4.125, -1.25, 1.2e-20], "Label": ["4.125", "A.1", ""]})
        text = copy_block(data, (0, 0, 3, 1), set(), decimal_mark=",")
        self.assertEqual(clipboard_rows(text),
                         [["4,125", "4.125"], ["-1,25", "A.1"], ["1,2e-20", ""], ["", ""]])

    def test_legacy_graph_points_keep_series_identity_and_existing_rows(self):
        data = Dataset(pd.DataFrame({"X": [0, 1], "Y": [2, 3], "Series": ["Group A"] * 2, "Dataset": [1, 1]}))
        data.table_format = EDITABLE_LEGACY_XY
        with self.assertRaisesRegex(ValueError, "Use Format"):
            paste_block(data, 0, 1, [["8", "Another series"]])
        self.assertEqual(data.raw.iloc[0].tolist(), [0, 2, "Group A", 1])
        with self.assertRaisesRegex(ValueError, "existing X/Y"):
            paste_block(data, 2, 0, [["4"]])
        paste_block(data, 0, 1, [["8"]])
        self.assertEqual(data.raw.iloc[0].tolist(), [0, 8, "Group A", 1])


    def test_saved_xy_worksheet_preserves_known_implicit_x(self):
        frame = pd.DataFrame({"Control": [1], "Treatment": [2]})
        frame.attrs.update(table_format="xy", legacy_x=None, legacy_y=["a", "b"],
                           legacy_columns={"a": ["Control"], "b": ["Treatment"]})
        with TemporaryDirectory() as directory:
            path = Path(directory) / "project.alab"
            save_project(path, {"XY": Dataset(frame)})
            reopened = load_workspace(path)[0]["XY"]
        _, roles = _heading_bands(reopened.frame(), list(frame.columns), 2, reopened.table_format)
        self.assertEqual(roles, ["Y", "Y"])
