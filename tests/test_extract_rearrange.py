"""Extract and Rearrange fixture and layout oracles."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.extract_rearrange import EXTRACT_TABLE, extract_rearrange
from analisi.processing import FieldError


def extract(frame, output, *, complete=True, prefix=False, **fields):
    return extract_rearrange(frame, {"Output table": output,
                                     "Only include complete rows": complete,
                                     "Include variable name prefixes": prefix, **fields})


def values(table, *columns):
    return table[list(columns)].to_numpy(dtype=float, na_value=np.nan)


GROUPED = {"Response variable": "Y", "Row factor variable": "Age", "Column factor variable": "Training"}
COLUMN = {"Response variable": "Y", "Grouping variable": "Arm"}
XY = {**COLUMN, "Independent (X) variable": "Time"}
CONTINGENCY = {"Row (treatment) variable": "Treatment", "Column (outcome) variable": "Outcome"}
SUBJECT = "Subject/replicate variable"
NAN = np.nan


class ExtractRearrangeTests(unittest.TestCase):
    def test_official_grouped_reference_all_36_measurements(self):
        # Source table B3D31937 and Extract result ED57A9CE, in their stored orders.
        source = pd.DataFrame({
            "Age": ["Young"] * 12 + ["Middle"] * 12 + ["Senior"] * 12,
            "Training": (["None"] * 4 + ["Moderate"] * 4 + ["Intense"] * 4) * 3,
            "Y": [42.1, 44.5, 45.7, 41.8, 48.9, 46, 43.4, 52.9, 57.5, 56, 64.2, 55.5,
                  38.8, 31.2, 29.5, 26.5, 34.6, 40.3, 33, 42, 50.1, 47.6, 44, 50.4,
                  24.8, 25.2, 20.8, 25.3, 28.9, 24.1, 34.7, 26.7, 31.3, 35.4, 36.2, 30.2],
        })
        before = source.copy(deep=True)
        result = extract(source, "Grouped", complete=False, **GROUPED).tables[EXTRACT_TABLE]
        expected_headers = [f"{training} [{i}]" for training in ("Intense", "Moderate", "None") for i in range(1, 5)]
        self.assertEqual(result.columns.tolist(), ["Row title", *expected_headers])
        self.assertEqual(result["Row title"].tolist(), ["Middle", "Senior", "Young"])
        np.testing.assert_array_equal(values(result, *expected_headers), [
            [50.1, 47.6, 44, 50.4, 34.6, 40.3, 33, 42, 38.8, 31.2, 29.5, 26.5],
            [31.3, 35.4, 36.2, 30.2, 28.9, 24.1, 34.7, 26.7, 24.8, 25.2, 20.8, 25.3],
            [57.5, 56, 64.2, 55.5, 48.9, 46, 43.4, 52.9, 42.1, 44.5, 45.7, 41.8],
        ])
        self.assertEqual(Dataset(result).table_format, "grouped")
        self.assertEqual(result.attrs["worksheet_roles"], {"x": [], "y": [expected_headers[:4],
                                                                            expected_headers[4:8],
                                                                            expected_headers[8:]]})
        pd.testing.assert_frame_equal(source, before)

    def test_grouped_sparse_keeps_sequential_missing_slots(self):
        source = pd.DataFrame({"Age": [2, 1, 2, 2, 2], "Training": ["A", "A", "A", "A", "B"],
                               "Y": [5, NAN, NAN, 7, 9]})
        sparse = extract(source, "Grouped", complete=False, prefix=True, **GROUPED).tables[EXTRACT_TABLE]
        self.assertEqual(sparse["Row title"].tolist(), ["Age = 1", "Age = 2"])
        a = [f'Training = "A" [{i}]' for i in range(1, 4)]
        np.testing.assert_array_equal(values(sparse, *a, 'Training = "B" [1]'),
                                      [[NAN, NAN, NAN, NAN], [5, NAN, 7, 9]])
        compact = extract(source, "Grouped", **GROUPED).tables[EXTRACT_TABLE]
        self.assertEqual(compact["Row title"].tolist(), ["2"])
        np.testing.assert_array_equal(values(compact, "A [1]", "A [2]", "B [1]", "B [2]"), [[5, 7, 9, NAN]])

    def test_grouped_subjects_align_across_cells_and_duplicates_are_reported(self):
        source = pd.DataFrame({"Age": [2, 2, 1, 1], "Training": ["A", "A", "A", "B"],
                               "Patient": ["p2", "p1", "p2", "p1"], "Y": [20, 10, 21, 11]})
        fields = {**GROUPED, SUBJECT: "Patient"}
        table = extract(source, "Grouped", **fields).tables[EXTRACT_TABLE]
        np.testing.assert_array_equal(values(table, "A [1]", "A [2]", "B [1]", "B [2]"),
                                      [[NAN, 21, 11, NAN], [10, 20, NAN, NAN]])
        self.assertEqual(table.attrs["replicate_labels"], ["p1", "p2"])
        duplicate = pd.concat([source, source.iloc[[0]]], ignore_index=True)
        with self.assertRaises(FieldError) as failure:
            extract(duplicate, "Grouped", **fields)
        self.assertEqual(failure.exception.field, SUBJECT)
        self.assertIn("row 5", str(failure.exception))

    def test_weighted_contingency_counts_only_nonnegative_whole_weights(self):
        source = pd.DataFrame({
            "Treatment": ["B", "A", "B", "A", "B", "A", None, "Unused", "B", "B"],
            "Outcome": ["Yes", "Yes", "Yes", "No", "No", "Yes", "No", "Yes", "Yes", None],
            "Weight": [2, 4, "7", 0, -1, 1.5, 99, "invalid", None, 99],
        })
        result = extract(source, "Contingency", prefix=True, **CONTINGENCY, **{"Count variable": "Weight"})
        table = result.tables[EXTRACT_TABLE]
        self.assertEqual(table.attrs["table_format"], "contingency")
        self.assertEqual(table["Row title"].tolist(), ['Treatment = "A"', 'Treatment = "B"'])
        self.assertEqual(table[['Outcome = "No"', 'Outcome = "Yes"']].values.tolist(), [[0, 4], [0, 9]])
        self.assertEqual(result.tables["Notes"].loc["Invalid counts skipped", "Value"], 3)
        unweighted = extract(source.iloc[:6], "Contingency", **CONTINGENCY).tables[EXTRACT_TABLE]
        self.assertEqual(unweighted[["No", "Yes"]].values.tolist(), [[1, 2], [1, 2]])

    def test_contingency_preserves_exact_weight_and_detects_overflow(self):
        source = pd.DataFrame({"Treatment": ["A", "A"], "Outcome": ["Yes", "Yes"],
                               "Weight": ["9007199254740993", "2"]})
        fields = {**CONTINGENCY, "Count variable": "Weight"}
        result = extract(source, "Contingency", **fields).tables[EXTRACT_TABLE]
        self.assertEqual(int(result.loc[0, "Yes"]), 9007199254740995)
        source.loc[0, "Weight"] = str(2**64 - 1)
        with self.assertRaises(FieldError) as failure:
            extract(source, "Contingency", **fields)
        self.assertEqual(failure.exception.field, "Count variable")

    def test_contingency_uses_exact_integer_value_of_float_weights(self):
        source = pd.DataFrame({"Treatment": ["A"], "Outcome": ["Yes"], "Weight": [float(2**63)]})
        table = extract(source, "Contingency", **CONTINGENCY, **{"Count variable": "Weight"}).tables[EXTRACT_TABLE]
        self.assertEqual(int(table.loc[0, "Yes"]), 2**63)

    def test_column_sparse_retains_positions_and_compact_packs_each_group(self):
        source = Dataset(pd.DataFrame({"Arm": ["B", "A", "B", "A", "B"], "Y": [4, 2, 6, 8, 10]},
                                      index=[5, 5, 1, 3, 2]), excluded={(2, 1)}).frame(mask_excluded=True)
        sparse = extract(source, "Column", complete=False, **COLUMN).tables[EXTRACT_TABLE]
        self.assertEqual(sparse.attrs["table_format"], "column")
        np.testing.assert_array_equal(values(sparse, "A", "B"), [[NAN, 4], [2, NAN], [NAN, NAN],
                                                                  [8, NAN], [NAN, 10]])
        compact = extract(source, "Column", **COLUMN).tables[EXTRACT_TABLE]
        np.testing.assert_array_equal(values(compact, "A", "B"), [[2, 4], [8, 10]])

    def test_column_titles_align_and_subject_matching_keeps_labels(self):
        source = pd.DataFrame({"Arm": ["B", "A", "A", "B"], "Y": [4, 2, 8, 10],
                               "Label": ["day 1", "day 2", "day 1", "day 2"], "ID": [1, 2, 1, 2]})
        result = extract(source, "Column", **COLUMN, **{"Row titles": "Label"}).tables[EXTRACT_TABLE]
        self.assertEqual(result["Row title"].tolist(), ["day 1", "day 2"])
        np.testing.assert_array_equal(values(result, "A", "B"), [[8, 4], [2, 10]])
        result = extract(source, "Column", complete=False, **COLUMN, **{SUBJECT: "ID"}).tables[EXTRACT_TABLE]
        self.assertEqual(result["Row title"].tolist()[:2], ["1", "2"])
        np.testing.assert_array_equal(values(result, "A", "B"), [[8, 4], [2, 10], [NAN, NAN], [NAN, NAN]])
        source.loc[2, "Label"] = "other"
        with self.assertRaises(FieldError) as failure:
            extract(source, "Column", **COLUMN, **{SUBJECT: "ID", "Row titles": "Label"})
        self.assertEqual(failure.exception.field, "Row titles")

    def test_xy_sparse_retains_order_and_compact_merges_occurrences_at_same_x(self):
        source = pd.DataFrame({"Time": [2, 1, 2, 2, 2, 3, NAN],
                               "Arm": ["B", "A", "A", "B", "A", "B", "A"],
                               "Y": [22, 11, 21, 24, 23, NAN, 99]})
        sparse = extract(source, "XY", complete=False, **XY).tables[EXTRACT_TABLE]
        self.assertEqual(sparse.attrs["worksheet_roles"], {"x": ["Time"], "y": [["A"], ["B"]]})
        np.testing.assert_array_equal(values(sparse, "Time", "A", "B"), [
            [2, NAN, 22], [1, 11, NAN], [2, 21, NAN], [2, NAN, 24], [2, 23, NAN], [3, NAN, NAN], [NAN, NAN, NAN],
        ])
        compact = extract(source, "XY", **XY).tables[EXTRACT_TABLE]
        np.testing.assert_array_equal(values(compact, "Time", "A", "B"), [[2, 21, 22], [1, 11, NAN], [2, 23, 24]])

    def test_xy_replicates_keep_distinct_subjects_and_reject_same_destination(self):
        source = pd.DataFrame({"Time": [10, 10, 10, 20, 20], "Arm": ["A", "A", "B", "A", "B"],
                               "Patient": ["P2", "P1", "P1", "P1", "P2"], "Y": [2, 1, 3, 4, 5]})
        fields = {**XY, SUBJECT: "Patient"}
        table = extract(source, "XY", **fields).tables[EXTRACT_TABLE]
        self.assertEqual(table.attrs["table_format"], "XY with replicates")
        self.assertEqual(table.attrs["replicate_labels"], ["P1", "P2"])
        np.testing.assert_array_equal(values(table, "Time", "A [1]", "A [2]", "B [1]", "B [2]"),
                                      [[10, 1, 2, 3, NAN], [20, 4, NAN, NAN, 5]])
        with self.assertRaises(FieldError) as failure:
            extract(pd.concat([source, source.iloc[[0]]]), "XY", **fields)
        self.assertEqual(failure.exception.field, SUBJECT)

    def test_xy_without_group_preserves_exact_numeric_integer_coordinates(self):
        source = pd.DataFrame({"Time": [2**53 + 1, 2**53 + 2], "Y": [1, 2]})
        table = extract(source, "XY", **{"Independent (X) variable": "Time", "Response variable": "Y"}).tables[EXTRACT_TABLE]
        self.assertEqual(table.columns.tolist(), ["Time", "Y"])
        self.assertEqual(table["Time"].tolist(), [2**53 + 1, 2**53 + 2])

    def test_xy_preserves_object_integer_coordinates_with_missing_values(self):
        source = pd.DataFrame({"Time": pd.Series([2**53 + 1, None, 2**53 + 2], dtype=object), "Y": [1, 2, 3]})
        table = extract(source, "XY", complete=False,
                        **{"Independent (X) variable": "Time", "Response variable": "Y"}).tables[EXTRACT_TABLE]
        self.assertEqual(table["Time"].tolist(), [2**53 + 1, pd.NA, 2**53 + 2])

    def test_header_collisions_and_whitespace_survive_project_round_trip(self):
        source = pd.DataFrame({"Time": [1, 2, 3, 4], "Arm": ["Time", " Drug ", "Drug", "Row title"],
                               "Y": [2, 3, 4, 5], "Label": ["a", "b", "c", "d"]})
        result = extract(source, "XY", complete=False, **XY, **{"Row titles": "Label"}).tables[EXTRACT_TABLE]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "workspace.json"
            save_project(path, {"Rearranged": Dataset(result)})
            restored = load_project(path)["Rearranged"]
        self.assertEqual(restored.table_format, "xy")
        self.assertEqual(restored.raw.attrs["worksheet_roles"], result.attrs["worksheet_roles"])
        self.assertEqual(restored.raw.columns.tolist(), ["Row title", "Time", "Drug", "Drug (2)",
                                                        "Row title (2)", "Time (2)"])
        self.assertEqual(restored.raw["Time (2)"].iloc[0], 2)

    def test_size_limits_include_replicate_subcolumns_and_blank_rows(self):
        source = pd.DataFrame({"Age": [1, 1, 2], "Training": ["A", "A", "B"], "Y": [1, 2, 3]})
        with patch("analisi.extract_rearrange.MAX_COLUMNS", 4), self.assertRaises(FieldError) as failure:
            extract(source, "Grouped", **GROUPED)
        self.assertEqual(failure.exception.field, "Output table")
        with patch("analisi.extract_rearrange.MAX_CELLS", 10), self.assertRaises(FieldError) as failure:
            extract(pd.DataFrame({"Age": range(4), "Training": list("ABCD"), "Y": range(4)}), "Grouped", **GROUPED)
        self.assertEqual(failure.exception.field, "Output table")

    def test_invalid_numeric_factor_and_missing_fields_are_explicit(self):
        with self.assertRaises(FieldError) as failure:
            extract(pd.DataFrame({"Arm": [0.5], "Y": [2]}), "Column", **COLUMN)
        self.assertEqual(failure.exception.field, "Grouping variable")
        with self.assertRaises(FieldError) as failure:
            extract(pd.DataFrame({"Arm": [1], "Y": [None]}), "Column", **COLUMN)
        self.assertEqual(failure.exception.field, "Response variable")
        with self.assertRaises(FieldError) as failure:
            extract(pd.DataFrame({"Y": [2]}), "Grouped", **GROUPED)
        self.assertEqual(failure.exception.field, "Row factor variable")


if __name__ == "__main__":
    unittest.main()
