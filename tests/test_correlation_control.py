"""Correlate against control: pairwise and listwise rows, adjustments and the figure."""
import math
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from analisi.correlation_details import CORRELATE_CONTROL, adjust_p_values, correlation_statistics
from analisi.field_error import FieldError
from analisi.workbench import METHODS, analyse

DATA = Path(__file__).parent / "data" / "correlation_details"


def control(frame, **options):
    base = {"X": "X", "Variables": ["A", "B", "Constant"], "Method": "Pearson", "Alternative": "Two-sided",
            "Confidence level (%)": 95, "Missing values": "Pairwise complete", "P adjustment": "None",
            "Show intervals": True}
    base.update(options)
    return analyse(CORRELATE_CONTROL, frame, base)


class Adjustment(unittest.TestCase):
    def test_holm_and_benjamini_hochberg_follow_the_finite_order(self):
        values = [0.04, 0.01, 0.20]
        holm = adjust_p_values(values, "Holm")
        bh = adjust_p_values(values, "Benjamini–Hochberg")
        self.assertEqual(adjust_p_values(values, "None"), values)
        # Sorted p are 0.01, 0.04, 0.20. Holm: 0.03, 0.08, 0.20 then unsort to the original positions.
        self.assertEqual(holm, [0.08, 0.03, 0.20])
        # BH from the large end: 0.20, then 0.06, then 0.03, then unsort.
        self.assertTrue(all(math.isclose(left, right) for left, right in zip(bh, [0.06, 0.03, 0.20], strict=True)))


class CorrelateAgainstControl(unittest.TestCase):
    def setUp(self):
        self.frame = pd.read_csv(DATA / "control.csv")

    def test_method_is_in_the_correlation_group(self):
        self.assertEqual(METHODS[CORRELATE_CONTROL]["Variables"], "Multiple")
        self.assertEqual(METHODS[CORRELATE_CONTROL]["Show intervals"], True)
        self.assertNotIn("Kendall", METHODS[CORRELATE_CONTROL]["Method"])

    def test_pairwise_keeps_the_constant_and_does_not_adjust_intervals(self):
        before = self.frame.copy(deep=True)
        result = control(self.frame, **{"P adjustment": "Holm"})
        pd.testing.assert_frame_equal(self.frame, before)
        table = result.tables["Correlations"]
        self.assertEqual(table["Variable"].tolist(), ["A", "B", "Constant"])
        self.assertEqual(table["Status"].tolist(), ["Available", "Available", "Unavailable"])
        self.assertEqual(table["N"].tolist(), [7, 7, 8])
        self.assertTrue(pd.isna(table.loc[2, "p"]))
        self.assertTrue(table.loc[2, "Reason"])
        finite = table.loc[table["Status"] == "Available", "p"].tolist()
        self.assertEqual(table.loc[table["Status"] == "Available", "p adjusted"].tolist(),
                         adjust_p_values(finite, "Holm"))
        paired = result.tables["Pairs"]
        for name in ("A", "B"):
            row = table.set_index("Variable").loc[name]
            used = paired[paired["Variable"] == name]
            direct = correlation_statistics(used["X"], used["Y"])
            self.assertEqual(int(row["N"]), direct["N"])
            self.assertTrue(np.isclose(row["Coefficient"], direct["Coefficient"]))
            self.assertTrue(np.isclose(row["Lower"], direct["Lower"]))
            self.assertTrue(np.isclose(row["p"], direct["p"]))
        settings = " ".join(map(str, result.tables["Settings"]["Value"].tolist()))
        self.assertRegex(settings, r"pointwise|simultaneous")
        labels = [tick.get_text() for tick in result.figure.axes[0].get_yticklabels()]
        self.assertEqual(labels, ["A", "B"])
        self.assertTrue(_gids(result.figure.axes[0]) & {"corr:intervals"})

    def test_listwise_changes_n_and_benjamini_hochberg_changes_only_adjusted_p(self):
        pairwise = control(self.frame, **{"P adjustment": "Holm"}).tables["Correlations"]
        listwise = control(self.frame, **{"Missing values": "Listwise complete", "P adjustment": "Holm"})
        table = listwise.tables["Correlations"]
        self.assertEqual(table["N"].tolist(), [6, 6, 6])
        self.assertNotEqual(table["N"].tolist(), pairwise["N"].tolist())
        bh = control(self.frame, **{"Missing values": "Listwise complete",
                                    "P adjustment": "Benjamini–Hochberg"}).tables["Correlations"]
        for column in ("Coefficient", "p", "Lower", "Upper", "R²", "N"):
            pd.testing.assert_series_equal(table[column], bh[column], check_names=False)
        self.assertEqual(bh.loc[bh["Status"] == "Available", "p adjusted"].tolist(),
                         adjust_p_values(bh.loc[bh["Status"] == "Available", "p"].tolist(), "Benjamini–Hochberg"))
        # Two moderate p values: Holm and BH are not the same correction.
        separated = pd.DataFrame({"X": [1, 2, 3, 4, 5, 6, 7, 8],
                                 "Near": [1, 2, 3, 4, 7, 8, 6, 5], "Mild": [1, 2, 3, 4, 8, 6, 7, 5]})
        holm_rows = control(separated, Variables=["Near", "Mild"], **{"P adjustment": "Holm"}).tables["Correlations"]
        bh_rows = control(separated, Variables=["Near", "Mild"],
                          **{"P adjustment": "Benjamini–Hochberg"}).tables["Correlations"]
        for column in ("Coefficient", "p", "Lower", "Upper"):
            pd.testing.assert_series_equal(holm_rows[column], bh_rows[column], check_names=False)
        self.assertFalse(all(math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-15)
                             for left, right in zip(holm_rows["p adjusted"], bh_rows["p adjusted"], strict=True)))

    def test_hidden_intervals_keep_the_points_and_the_table(self):
        shown = control(self.frame)
        hidden = control(self.frame, **{"Show intervals": False})
        pd.testing.assert_frame_equal(shown.tables["Correlations"], hidden.tables["Correlations"])
        axes = hidden.figure.axes[0]
        self.assertIn("corr:coefficients", _gids(axes))
        self.assertNotIn("corr:intervals", _gids(axes))

    def test_literal_dollar_name(self):
        frame = self.frame.copy()
        frame["$x$"] = [1, 3, 2, 4, 6, 5, 8, 7]
        result = control(frame, Variables=["$x$", "Constant"])
        ticks = result.figure.axes[0].get_yticklabels()
        self.assertEqual([tick.get_text() for tick in ticks], ["$x$"])
        self.assertFalse(any(tick.get_parse_math() for tick in ticks))
        self.assertFalse(result.figure.axes[0].title.get_parse_math())

    def test_exact_outside_the_budget_names_the_option(self):
        wide = pd.read_csv(DATA / "spearman-11.csv")
        wide["Other"] = wide["Y"] + 1
        with self.assertRaises(FieldError) as caught:
            analyse(CORRELATE_CONTROL, wide, {"X": "X", "Variables": ["Y", "Other"], "Method": "Spearman",
                                              "Spearman p values": "Exact", "Missing values": "Pairwise complete",
                                              "P adjustment": "None", "Show intervals": True})
        self.assertEqual(caught.exception.field, "Spearman p values")

    def test_nothing_calculable_and_bad_roles(self):
        frame = pd.DataFrame({"X": [1, 2, 3], "A": [1, 1, 1]})
        with self.assertRaises(FieldError) as caught:
            control(frame, Variables=["A"])
        self.assertEqual(caught.exception.field, "Variables")
        with self.assertRaises(FieldError) as caught:
            control(self.frame, Variables=["A", "A"])
        self.assertEqual(caught.exception.field, "Variables")
        text = self.frame.copy()
        text["A"] = text["A"].astype(object)
        text.loc[0, "A"] = "text"
        with self.assertRaises(FieldError) as caught:
            control(text)
        self.assertEqual(caught.exception.field, "Variables")

    def test_twenty_four_responses_keep_one_row_each(self):
        frame = pd.read_csv(DATA / "stress-control-24.csv")
        names = [f"Y{i:02d}" for i in range(1, 25)]
        result = control(frame, Variables=names, **{"P adjustment": "Benjamini–Hochberg"})
        table = result.tables["Correlations"]
        self.assertEqual(table["Variable"].tolist(), names)
        self.assertIn("Available", table["Status"].tolist())
        finite = table.loc[table["Status"] == "Available", "p"]
        self.assertEqual(table.loc[table["Status"] == "Available", "p adjusted"].tolist(),
                         adjust_p_values(finite.tolist(), "Benjamini–Hochberg"))


def _gids(axes):
    return {artist.get_gid() for artist in (*axes.lines, *axes.collections) if artist.get_gid()}


if __name__ == "__main__":
    unittest.main()
