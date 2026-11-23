"""Change → Number format…: the helper, the saved form and the history, without a window."""
import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.i18n import active_language, set_language
from analisi.worksheet_history import WorksheetHistory, WorksheetState
from analisi.worksheet_number_format import (AUTOMATIC, CODES, COUNTS, METHOD, ROW_TITLES, TEXT, FormatDraft, Renderer,
                                             assign_formats, edit_text, format_number, format_target, result_columns,
                                             validated_spec, worksheet_columns)

# The cases delivered with the request (fixtures/cases.json), inline so the suite needs no extra file.
CASES = [
    (1.25, "fixed", 3, ".", "1.250"),
    (2.125, "fixed", 2, ".", "2.12"),
    (2.375, "fixed", 2, ".", "2.38"),
    (-0.004, "fixed", 2, ",", "0,00"),
    (0.000125, "scientific", 3, ",", "1,250e-04"),
    (1000, "scientific", 0, ".", "1e+03"),
    (-0.0, "scientific", 2, ".", "0.00e+00"),
    (12345.6789, "significant", 4, ".", "1.235e+04"),
    (0.00123456, "significant", 3, ".", "0.00123"),
    (9007199254740993, "fixed", 0, ".", "9007199254740993"),
    (1.23456789012345, "automatic", None, ".", None),
    ("1.25", "fixed", 2, ".", None),
    (True, "fixed", 2, ".", None),
    (None, "fixed", 2, ".", None),
]


def spec(mode, digits=None):
    return {"mode": mode} if digits is None else {"mode": mode, "digits": digits}


class LanguageCase(unittest.TestCase):
    def use(self, language):
        self.addCleanup(set_language, active_language())
        set_language(language)


class FormatNumberTests(unittest.TestCase):
    def test_delivered_cases(self):
        for value, mode, digits, mark, expected in CASES:
            with self.subTest(value=value, mode=mode, digits=digits):
                self.assertEqual(format_number(value, spec(mode, digits), decimal_mark=mark), expected)

    def test_numpy_values_and_missing_or_infinite_values(self):
        fixed = spec("fixed", 2)
        self.assertEqual(format_number(np.float64(3.14159), fixed), "3.14")
        self.assertEqual(format_number(np.int64(7), fixed), "7.00")
        self.assertEqual(format_number(np.float32(0.5), spec("significant", 1)), "0.5")
        for value in (math.nan, np.nan, math.inf, -math.inf, pd.NA, pd.NaT, np.bool_(True), "x"):
            with self.subTest(value=value):
                self.assertIsNone(format_number(value, fixed))

    def test_ties_round_half_to_even_and_negative_zero_is_plain_zero(self):
        self.assertEqual(format_number(0.5, spec("fixed", 0)), "0")
        self.assertEqual(format_number(1.5, spec("fixed", 0)), "2")
        self.assertEqual(format_number(2.5, spec("fixed", 0)), "2")
        self.assertEqual(format_number(-0.0, spec("fixed", 3)), "0.000")
        self.assertEqual(format_number(-0.0001, spec("fixed", 2)), "0.00")
        self.assertEqual(format_number(-0.0, spec("significant", 3)), "0")
        self.assertEqual(format_number(-0.006, spec("fixed", 2)), "-0.01")

    def test_exponent_has_a_sign_and_at_least_two_digits(self):
        self.assertEqual(format_number(1.5e-300, spec("scientific", 1)), "1.5e-300")
        self.assertEqual(format_number(123.0, spec("scientific", 2)), "1.23e+02")
        self.assertEqual(format_number(-123.0, spec("scientific", 2), decimal_mark=","), "-1,23e+02")

    def test_huge_integers_in_scientific_and_significant(self):
        self.assertEqual(format_number(10 ** 400, spec("fixed", 1)), "1" + "0" * 400 + ".0")
        self.assertIsNone(format_number(10 ** 400, spec("scientific", 2)))  # Beyond float: the plain renderer.
        self.assertEqual(format_number(123456789, spec("significant", 3)), "1.23e+08")

    def test_inconsistent_specs_raise(self):
        bad = [None, {}, {"mode": "fixed"}, {"mode": "fixed", "digits": 13}, {"mode": "fixed", "digits": -1},
               {"mode": "significant", "digits": 0}, {"mode": "significant", "digits": 16},
               {"mode": "scientific", "digits": 13}, {"mode": "fixed", "digits": True},
               {"mode": "fixed", "digits": 2.0}, {"mode": "automatic", "digits": 2}, {"mode": "percent", "digits": 2},
               {"mode": "fixed", "digits": 2, "extra": 1}, ["fixed", 2]]
        for item in bad:
            with self.subTest(spec=item), self.assertRaises(ValueError):
                format_number(1.0, item)
        with self.assertRaises(ValueError):
            format_number(1.0, spec("fixed", 2), decimal_mark=";")
        self.assertEqual(validated_spec({"mode": "significant", "digits": 15}), spec("significant", 15))
        self.assertEqual(validated_spec({"mode": "fixed", "digits": 0}), spec("fixed", 0))

    def test_renderer_follows_the_display_language(self):
        renderer = Renderer({1: spec("fixed", 2)})
        self.assertEqual(renderer.text(1, 2.5), "2.50")
        self.assertIsNone(renderer.text(0, 2.5))
        self.assertFalse(Renderer({}))
        set_language("it")
        try:
            self.assertEqual(renderer.text(1, 2.5), "2,50")
        finally:
            set_language("en")
        self.assertEqual(renderer.text(1, 2.5), "2.50")

    def test_edit_text_keeps_every_stored_digit(self):
        self.assertEqual(edit_text(1.23456789012345), "1.23456789012345")
        self.assertEqual(edit_text(9007199254740993), "9007199254740993")
        self.assertEqual(edit_text(math.nan), "")
        self.assertEqual(edit_text(None), "")


class DraftTests(LanguageCase):
    def test_modes_keep_the_digits_in_range(self):
        draft = FormatDraft(spec(AUTOMATIC))
        self.assertEqual(draft.spec(), spec(AUTOMATIC))
        draft.set_mode("significant")
        self.assertEqual(draft.spec(), spec("significant", 4))
        draft.set_digits(15)
        draft.set_mode("fixed")
        self.assertEqual(draft.spec(), spec("fixed", 12))
        draft.set_digits(0)
        draft.set_mode("significant")
        self.assertEqual(draft.spec(), spec("significant", 1))
        with self.assertRaises(ValueError):
            draft.set_digits(16)
        with self.assertRaises(ValueError):
            draft.set_mode("percent")
        draft.set_mode(AUTOMATIC)
        self.assertEqual(draft.spec(), spec(AUTOMATIC))

    def test_preview_uses_the_language_and_automatic_shows_the_classic_text(self):
        self.use("it")
        draft = FormatDraft(spec("fixed", 3))
        self.assertEqual(draft.preview(0.000125), "0,000")
        self.assertEqual(draft.digits_label(), "Cifre decimali (0–12)")
        draft.set_mode(AUTOMATIC)
        self.assertEqual(draft.preview(1.23456789012345), "1.23456789")


class ColumnTests(LanguageCase):
    def test_worksheet_columns_say_why_a_column_keeps_its_style(self):
        data = Dataset(pd.DataFrame({"Name": ["a", "b"], "Dose": [0.5, 1.5], "Flag": [True, False],
                                     "Count": [1, 2], "Mixed": ["n/a", 2.5]}))
        data.set_formula("Twice", "=2*Dose")
        columns = worksheet_columns(data, data.frame())
        self.assertEqual([(column.name, column.reason) for column in columns],
                         [("Name", TEXT), ("Dose", None), ("Flag", TEXT), ("Count", None), ("Mixed", None),
                          ("Twice", None)])

    def test_contingency_and_survival_tables(self):
        counts = Dataset(pd.DataFrame({"Outcome": ["Yes", "No"], "A": [3, 4], "B": [5, 6]}),
                         table_format="Contingency")
        reasons = {column.reason for column in worksheet_columns(counts, counts.frame())}
        self.assertTrue(reasons <= {ROW_TITLES, COUNTS, TEXT})
        self.use("en")
        with self.assertRaisesRegex(ValueError, "Contingency"):
            format_target(worksheet_columns(counts, counts.frame()), (0, 0, 1, 2), {})
        survival = Dataset(pd.DataFrame({"Time": [1.5, 2.25], "Event": [1, 0]}), table_format="Survival")
        reasons = [column.reason for column in worksheet_columns(survival, survival.frame())]
        self.assertEqual(reasons[-1], CODES)
        self.assertIsNone(reasons[0])

    def test_result_columns_keep_row_titles_and_method_formats(self):
        frame = pd.DataFrame({"Threshold": [math.inf, 0.5], "Sensitivity": [0.0, 0.9], "Label": ["x", "y"]})
        columns = result_columns(frame, "Row", {"Threshold"})
        self.assertEqual([column.reason for column in columns], [ROW_TITLES, METHOD, None, TEXT])

    def test_target_lists_changes_and_picks_a_real_preview_value(self):
        self.use("it")
        frame = pd.DataFrame({"Name": ["a", "b", "c"], "Dose": [math.nan, 0.25, 3.0], "Count": [1, 2, 3]})
        data = Dataset(frame)
        columns = worksheet_columns(data, data.frame())
        value_at = lambda row, position: frame.iat[row, position]
        target = format_target(columns, (0, 0, 2, 2), {2: spec("fixed", 1)}, active=(0, 0), value_at=value_at,
                               rows=3)
        self.assertEqual(target.keys, [1, 2])
        self.assertEqual(target.changing_text(), "Colonne che cambiano: Dose, Count")
        self.assertIn("Name", target.unchanged_text())
        self.assertEqual((target.value, target.sample, target.spec, target.has_format), (0.25, False, spec("fixed", 1),
                                                                                         True))
        active = format_target(columns, (0, 1, 2, 2), {}, active=(2, 2), value_at=value_at, rows=3)
        self.assertEqual((active.value, active.spec, active.has_format), (3, spec(AUTOMATIC), False))
        empty = format_target(columns, (0, 1, 0, 1), {}, active=(0, 1), value_at=value_at, rows=3)
        self.assertTrue(empty.sample)
        with self.assertRaisesRegex(ValueError, "selezion"):
            format_target(columns, (0, 0, 2, 0), {}, value_at=value_at, rows=3)
        text_only = Dataset(pd.DataFrame({"Name": ["a"]}))
        with self.assertRaises(ValueError):
            format_target(worksheet_columns(text_only, text_only.frame()), (0, 0, 0, 0), {})

    def test_many_columns_are_summarised(self):
        frame = pd.DataFrame({f"C{index}": [1.0] for index in range(12)})
        data = Dataset(frame)
        target = format_target(worksheet_columns(data, data.frame()), (0, 0, 0, 11), {})
        self.assertIn("C0", target.changing_text())
        self.assertNotIn("C11", target.changing_text())


class PersistenceTests(unittest.TestCase):
    def table(self):
        data = Dataset(pd.DataFrame({"Dose": [0.125, 1.5], "Response": [2.0, 3.25], "Label": ["a", "b"]}),
                       analyses=[("Linear regression", {"X": "Dose", "Y": "Response"})])
        data.set_number_format(["Dose", "Response"], spec("fixed", 3))
        data.set_number_format(["Response"], spec("scientific", 2))
        data.set_result_number_format(0, "Regression", [1], spec("significant", 3))
        data.set_result_number_format(0, "Data", [1, 2], spec("fixed", 1))
        return data

    def test_formats_round_trip_and_leave_the_numbers_alone(self):
        data = self.table()
        before = data.raw.copy()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "formats.alab"
            save_project(path, {"Example": data})
            reopened = load_project(path)["Example"]
        self.assertEqual(reopened.number_formats, {"Dose": spec("fixed", 3), "Response": spec("scientific", 2)})
        self.assertEqual(reopened.result_number_formats, {0: {"Regression": {1: spec("significant", 3)},
                                                              "Data": {1: spec("fixed", 1), 2: spec("fixed", 1)}}})
        pd.testing.assert_frame_equal(reopened.raw, before, check_dtype=False)
        self.assertEqual(reopened.displayed_number_formats, {0: spec("fixed", 3), 1: spec("scientific", 2)})

    def test_automatic_removes_the_entry_and_unchanged_returns_false(self):
        data = self.table()
        formats = data.number_formats
        self.assertIs(assign_formats(formats, ["Dose"], spec("fixed", 3)), formats)
        data.set_number_format(["Dose"], spec(AUTOMATIC))
        self.assertEqual(data.number_formats, {"Response": spec("scientific", 2)})
        data.set_result_number_format(0, "Regression", [1], None)
        data.set_result_number_format(0, "Data", [1, 2], None)
        self.assertEqual(data.result_number_formats, {})
        with self.assertRaises(ValueError):
            data.set_number_format(["Missing"], spec("fixed", 1))

    def test_formats_follow_column_order(self):
        data = self.table()
        data.set_formula("Twice", "=2*Dose")
        data.set_number_format(["Twice"], spec("fixed", 0))
        data.column_order = ("Dose", "Twice", "Response", "Label")
        self.assertEqual(data.displayed_number_formats, {0: spec("fixed", 3), 1: spec("fixed", 0),
                                                         2: spec("scientific", 2)})
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "reordered.alab"
            save_project(path, {"Example": data})
            reopened = load_project(path)["Example"]
        self.assertEqual(reopened.displayed_number_formats, {0: spec("fixed", 3), 1: spec("fixed", 0),
                                                             2: spec("scientific", 2)})

    def test_old_files_without_formats_still_open(self):
        data = Dataset(pd.DataFrame({"Dose": [1.0, 2.0]}), analyses=[("Descriptive statistics",
                                                                      {"Variables": ["Dose"]})])
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "old.alab"
            save_project(path, {"Old": data})
            reopened = load_project(path)["Old"]
        self.assertEqual((reopened.number_formats, reopened.result_number_formats), ({}, {}))

    def test_invalid_saved_formats_are_refused(self):
        from analisi.data import load_workspace, project_document
        good = project_document({"Example": self.table()})
        self.assertEqual(good["tables"][0]["number_formats"],
                         {"Dose": spec("fixed", 3), "Response": spec("scientific", 2)})
        broken = [
            ("number_formats", {"Nope": spec("fixed", 2)}),
            ("number_formats", {"Dose": spec("fixed", 99)}),
            ("number_formats", ["Dose"]),
            ("result_number_formats", {"0": {"Data": [[0, spec("fixed", 1)]]}}),
            ("result_number_formats", {"0": {"Data": [[1, spec("fixed", 1)], [1, spec("fixed", 2)]]}}),
            ("result_number_formats", {"0": {"Data": [["1", spec("fixed", 1)]]}}),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            for number, (key, value) in enumerate(broken):
                with self.subTest(key=key, value=value):
                    document = json.loads(json.dumps(good))
                    document["tables"][0][key] = value
                    path = Path(temporary) / f"broken{number}.alab"
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        load_workspace(path)

    def test_history_undoes_a_format_change_in_one_step(self):
        data = self.table()
        history = WorksheetHistory()
        before = WorksheetState.capture(data)
        data.set_number_format(["Dose"], spec("significant", 2))
        after = WorksheetState.capture(data)
        self.assertTrue(history.record("Example", "Number format", before, after))
        self.assertFalse(before.data_changed(after))
        self.assertEqual(history.apply({"Example": data}).label, "Number format")
        self.assertEqual(data.number_formats["Dose"], spec("fixed", 3))
        history.apply({"Example": data}, redo=True)
        self.assertEqual(data.number_formats["Dose"], spec("significant", 2))


class ProjectTests(unittest.TestCase):
    def test_rename_delete_and_undo_keep_formats_with_their_column(self):
        from trama_qt.project import Project
        project = Project()
        project.add_tables({"Example": pd.DataFrame({"Dose": [0.125, 1.5], "Response": [2.0, 3.25]})})
        data = project.tables["Example"]
        self.assertTrue(project.set_table_number_format("Example", ["Dose"], spec("fixed", 2)))
        self.assertFalse(project.set_table_number_format("Example", ["Dose"], spec("fixed", 2)))
        project.rename_column("Example", 0, "Concentration")
        self.assertEqual(data.number_formats, {"Concentration": spec("fixed", 2)})
        project.delete_columns("Example", [0])
        self.assertEqual(data.number_formats, {})
        project.undo()
        self.assertTrue(project.undo_changed_data)
        self.assertEqual(data.number_formats, {"Concentration": spec("fixed", 2)})
        project.undo()
        self.assertEqual(data.number_formats, {"Dose": spec("fixed", 2)})
        project.undo()
        self.assertFalse(project.undo_changed_data)
        self.assertEqual(data.number_formats, {})
        pd.testing.assert_frame_equal(data.raw, pd.DataFrame({"Dose": [0.125, 1.5], "Response": [2.0, 3.25]}),
                                      check_dtype=False)

    def test_recovery_snapshot_and_family_copy_keep_formats(self):
        from analisi.data import project_document
        from analisi.family_workflow import duplicate_family
        from trama_qt.project import Project
        project = Project()
        project.add_tables({"Example": pd.DataFrame({"Dose": [1.0, 2.0, 3.0], "Response": [2.0, 4.5, 5.5]})})
        project.tables["Example"].analyses = [("Linear regression", {"X": "Dose", "Y": "Response"})]
        project.set_table_number_format("Example", ["Response"], spec("significant", 3))
        project.set_result_number_format("Example", 0, "Regression", [1], spec("fixed", 4))
        snapshot = project.snapshot()
        record = project_document(snapshot.tables)["tables"][0]
        self.assertEqual(record["number_formats"], {"Response": spec("significant", 3)})
        self.assertEqual(record["result_number_formats"], {0: {"Regression": [[1, spec("fixed", 4)]]}})
        copy = duplicate_family(project.tables, [], [], ("data", "Example"), name="Copy")
        twin = copy.tables["Copy"]
        self.assertEqual(twin.number_formats, {"Response": spec("significant", 3)})
        self.assertEqual(twin.result_number_formats, {0: {"Regression": {1: spec("fixed", 4)}}})
        twin.set_number_format(["Response"], spec("fixed", 1))
        self.assertEqual(project.tables["Example"].number_formats, {"Response": spec("significant", 3)})


if __name__ == "__main__":
    unittest.main()
