"""Verify sample layout, signs and confidence levels through the t-test workbench."""

import unittest

import numpy as np
import pandas as pd
from scipy.stats import t, ttest_ind

from analisi import ttest_options as tt
from analisi.field_error import FieldError
from analisi.paired_graphs import TTEST_ESTIMATION
from analisi.legacy_recipes import restore_recipe
from analisi.variance_ratio import SHEET as VARIANCE, SHOW as VARIANCE_SHOW
from analisi.workbench import analyse
from tests.test_legacy_recipes import source, var


BEFORE = [43., 48., 64., None, 54., 70.]
AFTER = [39., 37., 55., 48., 51., None]
WIDE = pd.DataFrame({"ID": list("abcdef"), "Before": BEFORE, "After": AFTER})
COLUMNS = {tt.INPUT: tt.COLUMNS, tt.FIRST: "Before", tt.SECOND: "After", "Subject": "ID"}


def summary(frame, options):
    return analyse("t-test", frame, options).tables["t-test"]["Value"]


class TTestInputs(unittest.TestCase):
    def test_paired_columns_and_grouping_use_the_same_complete_pairs(self):
        opts = {"Design": "Paired", tt.LEVEL: 92.5, tt.DETAILS: True, TTEST_ESTIMATION: True}
        wide = analyse("t-test", WIDE, {**opts, **COLUMNS})
        long = WIDE.melt(id_vars="ID", var_name="Visit", value_name="Value")
        grouped = analyse("t-test", long, {**opts, "Response": "Value", "Group": "Visit", "Subject": "ID"})
        pd.testing.assert_frame_equal(wide.tables["t-test"], grouped.tables["t-test"])
        result = wide.tables["t-test"]["Value"]
        differences = np.array([4., 11., 9., 3.])
        center = differences.mean()
        error = differences.std(ddof=1) / 2
        margin = t.isf(.0375, 3) * error
        self.assertAlmostEqual(result["Difference"], center)
        self.assertAlmostEqual(result["SE of differences"], error)
        self.assertAlmostEqual(result["Hedges' g"], center / differences.std(ddof=1) * (1 - 3/11))
        interval, = [artist for artist in wide.figure.axes[1].collections
                     if artist.get_gid() == "paired-mean-confidence-interval"]
        np.testing.assert_allclose(interval.get_segments()[0][:, 1], [center - margin, center + margin])
        duplicate = pd.concat([WIDE, WIDE.iloc[:1]], ignore_index=True)
        with self.assertRaisesRegex(FieldError, "more than one complete pair") as error:
            summary(duplicate, {**opts, **COLUMNS})
        self.assertEqual(error.exception.field, "Subject")

    def test_independent_columns_ignore_missing_values_separately_and_keep_variance_orientation(self):
        for design in ("Welch", "Student"):
            with self.subTest(design=design):
                settings = {**COLUMNS, "Design": design, tt.LEVEL: 97., tt.ALTERNATIVE: tt.GREATER,
                            VARIANCE_SHOW: True}
                original = analyse("t-test", WIDE, settings)
                inverted = analyse("t-test", WIDE, {**settings, tt.REVERSE: True})
                first, second = WIDE.Before.dropna(), WIDE.After.dropna()
                fit = ttest_ind(first, second, equal_var=design == "Student")
                table = original.tables["t-test"]["Value"]
                reverse = inverted.tables["t-test"]["Value"]
                self.assertEqual((table["N first"], table["N second"]), (5, 5))
                self.assertAlmostEqual(table["p"], t.sf(fit.statistic, fit.df))
                self.assertAlmostEqual(table["p"] + reverse["p"], 1.)
                self.assertAlmostEqual(table["CI 97% low"], -reverse["CI 97% high"])
                self.assertAlmostEqual(original.tables[VARIANCE].loc["Variance ratio", "Value"],
                                       first.var() / second.var())
                self.assertAlmostEqual(inverted.tables[VARIANCE].loc["Variance ratio", "Value"],
                                       second.var() / first.var())

    def test_directed_group_recipe_preserves_orientation_when_rows_move(self):
        data = pd.DataFrame({"Group": list("ABABAB"), "Y": [11., 1., 6., 3., 9., 2.]})
        options = {"Design": "Welch", "Group": "Group", "Response": "Y", tt.ALTERNATIVE: tt.GREATER}
        tt.preserve_direction(options, data)
        self.assertEqual(options["Group order"], ["A", "B"])
        self.assertAlmostEqual(summary(data, options)["p"], summary(data.iloc[::-1], options)["p"])

    def test_one_sample_uses_an_explicit_tail_and_two_sided_interval(self):
        opts = {"Design": "One-sample", "Response": "Before", "Null mean": 38., tt.LEVEL: 80.}
        left = summary(WIDE, {**opts, tt.ALTERNATIVE: tt.LESS})
        right = summary(WIDE, {**opts, tt.ALTERNATIVE: tt.GREATER})
        self.assertAlmostEqual(left["p"] + right["p"], 1.)
        self.assertAlmostEqual(left["CI 80% low"], right["CI 80% low"])
        for invalid in (False, 0., 100., np.nan, np.inf):
            with self.subTest(invalid=invalid), self.assertRaises(FieldError) as error:
                summary(WIDE, {**opts, tt.LEVEL: invalid})
            self.assertEqual(error.exception.field, tt.LEVEL)

    def test_import_of_two_paired_columns_preserves_order_and_confidence(self):
        a, b = var("a", 1), var("b", 2)
        content = {"variableDesign": {"responseList": [a, b], "factorList": [], "subject": var("s")},
                   "experimentalDesign": "PAIRED_T_TEST", "graph": {"confidenceInterval": True},
                   "options": {"swapDirection": True, "significanceLevel": .10,
                               "pValueTailType": "P_VALUE_TWO_TAILED"}}
        args = source("T_TESTS_AND_NONPARAMETRIC", "0.0.1", content, WIDE.copy(),
                      {"a": ["Before"], "b": ["After"], "s": ["ID"]})
        saved = {"content": {"descriptiveStatistics": {
            f"sample{index}": {"id": {"var": {"response": column["col"], "factorList": []}}}
            for index, column in enumerate((b, a), start=1)}}}
        _, _, options = restore_recipe(*args, saved)
        self.assertEqual((options[tt.INPUT], options[tt.FIRST], options[tt.SECOND], options[tt.LEVEL]),
                         (tt.COLUMNS, "After", "Before", 90.))
        result = summary(WIDE, options)
        self.assertEqual(result["Difference"], -6.75)
        self.assertIn("CI 90% high", result.index)
