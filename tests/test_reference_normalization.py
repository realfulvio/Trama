"""Contract tests for normalization to observed references."""
import copy
import json
import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analisi.field_error import FieldError
from analisi.presentation import graph_series
from analisi.reference_normalization import (EACH, NORMALIZED, REFERENCES, ROW_MEANS, SOURCE_ROWS, SETTINGS,
                                            normalize_to_references)
from analisi.workbench import analyse


ROOT = Path(__file__).resolve().parent / "data" / "reference_normalization"
SHEETS = [NORMALIZED, REFERENCES, SOURCE_ROWS, SETTINGS]


def equal(actual, expected):
    if expected is None:
        assert actual is None or (isinstance(actual, float) and math.isnan(actual)), (actual, expected)
    elif isinstance(expected, dict):
        assert set(actual) == set(expected), (set(actual), set(expected))
        for key in expected:
            equal(actual[key], expected[key])
    elif isinstance(expected, list):
        assert len(actual) == len(expected), (len(actual), len(expected))
        for left, right in zip(actual, expected, strict=True):
            equal(left, right)
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        assert math.isclose(actual, expected, rel_tol=2e-10, abs_tol=1e-10), (actual, expected)
    else:
        assert actual == expected, (actual, expected)


class ReferenceNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads((ROOT / "cases.json").read_text(encoding="utf-8"))
        cls.gold = json.loads((ROOT / "expected" / "results.json").read_text(encoding="utf-8"))
        cls.legacy = json.loads((ROOT / "expected" / "legacy.json").read_text(encoding="utf-8"))

    def test_goldens_match_the_dispatcher_contract(self):
        for case in self.cases:
            with self.subTest(case=case["name"]):
                frame = pd.DataFrame(case["data"], index=case.get("index"))
                frame.attrs["packet_marker"] = {"untouched": [1, 2]}
                frame.attrs.update(copy.deepcopy(case.get("attrs", {})))
                before = frame.copy(deep=True)
                attrs = copy.deepcopy(frame.attrs)
                options = copy.deepcopy(case["options"])
                result = analyse("Normalize to references", frame, options)
                pd.testing.assert_frame_equal(frame, before)
                self.assertEqual(frame.attrs, attrs)
                self.assertEqual(options, case["options"])
                self.assertEqual(list(result.tables), SHEETS)
                expected = self.gold[case["name"]]
                table = result.tables[NORMALIZED]
                self.assertEqual(list(table.columns), list(expected["normalized"]))
                equal(table.index.tolist(), expected["source_index"])
                equal({key: table[key].tolist() for key in table}, expected["normalized"])
                refs = result.tables[REFERENCES]
                keys = list(expected["references"][0])
                equal(refs[keys].to_dict("records"), expected["references"])
                source = result.tables[SOURCE_ROWS]
                equal(source["Source row"].tolist(), expected["source_rows"])
                equal(source["Source index"].tolist(), expected["source_index"])
                self.assertIsNone(result.figure)
                self.assertNotIn("packet_marker", table.attrs)

    def test_legacy_normalizers_stay_on_their_golden(self):
        frame = pd.DataFrame({"A": [10, 20, None, 40], "B": [4, 8, 12, 16]})
        for mode, saved in self.legacy.items():
            with self.subTest(mode=mode):
                table = analyse("Normalize", frame, {"Variables": ["A", "B"], "Method": mode}).tables["Normalized"]
                equal(json.loads(table.to_json(orient="split", double_precision=12)), json.loads(saved))

    def test_row_means_do_not_pool_every_cell(self):
        frame = pd.DataFrame({"A [1]": [0, 10, 20], "A [2]": [100, None, 20]})
        result = normalize_to_references(frame, {
            "Variables": ["A [1]", "A [2]"], "Replicates": ROW_MEANS, "Units": "Fractions", "Graph results": False})
        # Row means are 50, 10 and 20, so the anchors are 10 and 50, not the pooled 0 and 100.
        equal(result.tables[NORMALIZED]["A"].tolist(), [1, 0, 0.25])
        self.assertEqual(result.tables[NORMALIZED].attrs["worksheet_roles"]["y"], [["A"]])

    def test_explicit_roles_beat_column_titles(self):
        frame = pd.DataFrame({"p": [10, 20, 30], "q": [14, None, 34], "r": [4, 8, 12], "s": [6, 10, 14]})
        frame.attrs["worksheet_roles"] = {"x": [], "y": [["p", "q"], ["r", "s"]]}
        result = normalize_to_references(frame, {
            "Variables": ["p", "q", "r", "s"], "Replicates": EACH, "Units": "Fractions", "Graph results": False})
        roles = result.tables[NORMALIZED].attrs["worksheet_roles"]
        self.assertEqual(roles["y"], [["p", "q"], ["r", "s"]])
        self.assertEqual(list(result.tables[REFERENCES]["Series"]), ["p", "r"])
        # Common anchors come from the row means: p/q are 12, 20, 32.
        equal(result.tables[REFERENCES].iloc[0]["Zero reference"], 12)
        equal(result.tables[REFERENCES].iloc[0]["One reference"], 32)

    def test_inactive_invalid_fields_are_ignored(self):
        frame = pd.DataFrame({"A": [1.0, 2.0, 4.0], "Mean": [1.0, 2.0, 4.0]})
        raw = {"Variables": ["A"], "Zero value": "inf", "One rows": "0", "Error lower": "missing",
               "Error upper": "missing", "N": "missing", "Graph results": False}
        normalize_to_references(frame, raw)
        summary = {"Input": "Summary values", "Mean": "Mean", "Variables": ["missing"], "Replicates": "nope",
                   "Zero rows": "0", "Graph results": False}
        normalize_to_references(frame, summary)

    def test_duplicate_index_and_reserved_column_names_are_kept(self):
        frame = pd.DataFrame({"Source row": [10.0, 20.0, 30.0], "Series": [1.0, 1.0, 1.0]}, index=[7, 7, 42])
        result = normalize_to_references(frame, {"Variables": ["Source row"], "Row titles": "Series", "Graph results": False})
        table = result.tables[NORMALIZED]
        self.assertEqual(list(table.columns), ["Series", "Source row"])
        self.assertEqual(table.index.tolist(), [7, 7, 42])
        self.assertEqual(len(result.tables[SOURCE_ROWS]), 3)

    def test_failures_leave_the_frame_and_report_the_field(self):
        frame = pd.DataFrame({"A": [1.0, 2.0, 3.0], "B": [4.0, 5.0, 6.0]})
        frame.attrs["packet_marker"] = {"untouched": [1, 2]}
        before = frame.copy(deep=True)
        attrs = copy.deepcopy(frame.attrs)
        checks = [
            ({"Variables": ["A"], "Zero reference": "Constant", "One reference": "Constant", "Zero value": 2,
              "One value": 2, "Graph results": False}, "One reference"),
            ({"Variables": ["A", "A"], "Graph results": False}, "Variables"),
            ({"Variables": ["A"], "X": "A", "Graph results": False}, "X"),
            ({"Variables": ["A"], "Zero reference": "Selected rows mean", "Zero rows": "0", "Graph results": False},
             "Zero rows"),
            ({"Variables": ["A"], "One reference": "Sum", "Reference values in output": "Blank reference values",
              "Graph results": False}, "Reference values in output"),
            ({"Input": "Summary values", "Mean": "A", "Error format": "SD", "Error lower": "B",
              "Graph results": False}, "Error lower"),
        ]
        # The SD case needs a negative error. Rebuild it below; the tuple above uses B which is positive.
        checks[-1] = ({"Input": "Summary values", "Mean": "A", "Error format": "SD", "Error lower": "B",
                       "Graph results": False}, "Error lower")
        negative = frame.copy()
        negative["B"] = [-1.0, 2.0, 3.0]
        with self.assertRaises(FieldError) as caught:
            normalize_to_references(negative, checks[-1][0])
        self.assertEqual(caught.exception.field, "Error lower")
        for options, field in checks[:-1]:
            with self.subTest(field=field):
                with self.assertRaises(FieldError) as caught:
                    normalize_to_references(frame, options)
                self.assertEqual(caught.exception.field, field)
        pd.testing.assert_frame_equal(frame, before)
        self.assertEqual(frame.attrs, attrs)

    def test_limits_distances_and_sample_size_fields(self):
        frame = pd.DataFrame({"Mean": [10.0, 20.0, 30.0], "Low": [11.0, 21.0, 31.0], "High": [12.0, 24.0, 36.0],
                              "N": [4, 1.5, 8]})
        with self.assertRaises(FieldError) as caught:
            normalize_to_references(frame, {"Input": "Summary values", "Mean": "Mean", "Error format": "Limits",
                                            "Error lower": "Low", "Error upper": "High", "Graph results": False})
        self.assertEqual(caught.exception.field, "Error lower")
        frame.loc[0, "Low"] = 9
        with self.assertRaises(FieldError) as caught:
            normalize_to_references(frame, {"Input": "Summary values", "Mean": "Mean", "Error format": "Distances",
                                            "Error lower": "Low", "Error upper": "High", "N": "N", "Graph results": False})
        self.assertEqual(caught.exception.field, "N")

    def test_row_grammar_and_series_limit(self):
        frame = pd.DataFrame({"A": [1.0, 2.0, 4.0]})
        with self.assertRaises(FieldError) as caught:
            normalize_to_references(frame, {"Variables": ["A"], "Zero reference": "Selected rows mean",
                                            "Zero rows": "1, 3-1", "Graph results": False})
        self.assertEqual(caught.exception.field, "Zero rows")
        wide = pd.DataFrame({f"C{i}": [1.0, 2.0] for i in range(25)})
        with self.assertRaises(FieldError) as caught:
            normalize_to_references(wide, {"Variables": list(wide.columns), "Graph results": False})
        self.assertEqual(caught.exception.field, "Variables")
        self.assertIn("24", str(caught.exception))
        tall = pd.DataFrame({"A": np.arange(100_001, dtype=float)})
        with self.assertRaises(FieldError) as caught:
            normalize_to_references(tall, {"Variables": ["A"], "One reference": "Selected rows mean",
                                           "One rows": "1-100001", "Graph results": False})
        self.assertEqual(caught.exception.field, "One rows")
        self.assertIn("100000", str(caught.exception))

    def test_graph_uses_table_values_and_hides_guides(self):
        frame = pd.DataFrame({"X": [10, 0, 5], "A": [1.0, 2.0, 4.0], "Title": ["b", "a", "c"]})
        result = normalize_to_references(frame, {"Variables": ["A"], "X": "X", "Row titles": "Title", "Graph results": True})
        axes = result.figure.axes[0]
        self.assertEqual(tuple(axes._tramastat_numeric_axes), ("x", "y"))
        guides = [line for line in axes.lines if str(line.get_gid() or "").startswith("tramastat-shape-")]
        self.assertEqual({line.get_gid() for line in guides},
                         {"tramastat-shape-reference-0", "tramastat-shape-reference-m"})
        data = [line for line in axes.lines if line not in guides]
        self.assertTrue(np.allclose(data[0].get_ydata(), result.tables[NORMALIZED]["A"].to_numpy(dtype=float), equal_nan=True))
        self.assertTrue(np.array_equal(data[0].get_xdata(), [10, 0, 5]))
        self.assertTrue(all(not str(series.artist.get_gid() or "").startswith("tramastat-shape-")
                            for series in graph_series(axes)))
        flags = pd.DataFrame({"X": [True, False, True], "A": [1.0, 3.0, 5.0]})
        positioned = normalize_to_references(flags, {"Variables": ["A"], "X": "X", "Graph results": True})
        line = next(item for item in positioned.figure.axes[0].lines
                    if not str(item.get_gid() or "").startswith("tramastat-shape-"))
        self.assertTrue(np.array_equal(line.get_xdata(), [1, 2, 3]))

    def test_summary_error_bars_follow_the_normalized_mean(self):
        frame = pd.DataFrame({"Mean": [10.0, 20.0, 30.0], "SD": [1.0, None, 3.0]})
        result = normalize_to_references(frame, {"Input": "Summary values", "Mean": "Mean", "Error format": "SD",
                                                 "Error lower": "SD", "Graph results": True})
        axes = result.figure.axes[0]
        series = graph_series(axes)
        self.assertEqual([item.kind for item in series], ["errorbar"])
        center = series[0].artist.lines[0]
        self.assertTrue(np.allclose(center.get_ydata(), result.tables[NORMALIZED]["Mean"].to_numpy(dtype=float),
                                    equal_nan=True))
        # SD is scaled by the same factor as the mean and is not divided by N.
        equal(result.tables[NORMALIZED]["SD"].tolist(), [5, None, 15])

    def test_boolean_option_must_be_boolean(self):
        frame = pd.DataFrame({"A": [1.0, 2.0]})
        with self.assertRaises(FieldError) as caught:
            normalize_to_references(frame, {"Variables": ["A"], "Graph results": "yes"})
        self.assertEqual(caught.exception.field, "Graph results")


if __name__ == "__main__":
    unittest.main()
