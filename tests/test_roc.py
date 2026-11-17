import itertools
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from analisi.exploration import roc
from analisi.processing import FieldError
from analisi.roc import ROC_INTERVALS, binomial_interval, compare_paired_roc, roc_analysis
from analisi.workbench import analyse

HIGHER, LOWER = "Higher in patients", "Lower in patients"
CP, WILSON, WB = ROC_INTERVALS
A = pd.DataFrame({"Control": [1, 2, np.nan, 2, 4, 5], "Patient": [2, 3, 4, 4, 6, 7]})


def table(controls, patients, direction=HIGHER, **options):
    frame = pd.DataFrame({"C": pd.Series(controls, dtype=float), "P": pd.Series(patients, dtype=float)})
    return roc_analysis(frame, "C", "P", direction, **options)


def apply_rule(row, direction, controls, patients):
    """Re-apply a published threshold and operator to the raw data."""
    compare = np.greater_equal if direction == HIGHER else np.less_equal
    value = row["Threshold"]
    return (int(compare(np.asarray(patients, float), value).sum()), int(compare(np.asarray(controls, float), value).sum()))


class ThresholdTableTests(unittest.TestCase):
    def test_fixture_a_sequence_and_counts(self):
        report, curve, rows = roc_analysis(A, "Control", "Patient", HIGHER)
        self.assertEqual(rows["Threshold"].tolist(), [np.inf, 6.5, 5.5, 4.5, 3.5, 2.5, 1.5, -np.inf])
        self.assertEqual(rows["TP"].tolist(), [0, 1, 2, 2, 4, 5, 6, 6])
        self.assertEqual(rows["FP"].tolist(), [0, 0, 0, 1, 2, 2, 4, 5])
        self.assertEqual(rows["TN"].tolist(), [5, 5, 5, 4, 3, 3, 1, 0])
        self.assertEqual(rows["FN"].tolist(), [6, 5, 4, 4, 2, 1, 0, 0])
        self.assertEqual(rows["Threshold type"].tolist(), ["Endpoint"] + ["Midpoint"] * 6 + ["Endpoint"])
        np.testing.assert_allclose(rows["Youden J"], [0, 1 / 6, 1 / 3, 2 / 15, 4 / 15, 13 / 30, 1 / 5, 0], atol=1e-15)
        self.assertEqual(rows["Youden candidate"].tolist(), [""] * 5 + ["Yes"] + [""] * 2)
        self.assertEqual(rows.loc[5, "Sensitivity"], 5 / 6)
        self.assertEqual(rows.loc[5, "Specificity"], 3 / 5)
        self.assertEqual(rows.loc[4, "Sensitivity"], 4 / 6)
        self.assertEqual(rows.loc[0, "Rule"], "score >= +∞")
        self.assertEqual(rows.loc[7, "Rule"], "score >= −∞")
        self.assertEqual(rows.loc[5, "Rule"], "score >= 2.5")
        self.assertEqual((report["Control N"], report["Patient N"]), (5, 6))

    def test_curve_matches_table_and_integrates_to_auc(self):
        report, curve, rows = roc_analysis(A, "Control", "Patient", HIGHER)
        self.assertEqual(len(curve), 8)
        self.assertEqual(curve["Threshold"].tolist(), [np.inf, 7, 6, 5, 4, 3, 2, 1])
        np.testing.assert_allclose(curve["False positive rate"], rows["FP"] / 5)
        np.testing.assert_allclose(curve["True positive rate"], rows["TP"] / 6)
        self.assertAlmostEqual(np.trapezoid(curve["True positive rate"], curve["False positive rate"]), 11 / 15)
        self.assertTrue((np.diff(curve["False positive rate"]) >= 0).all())
        self.assertTrue((np.diff(curve["True positive rate"]) >= 0).all())
        self.assertTrue(((rows["TP"] + rows["FN"]) == 6).all() and ((rows["TN"] + rows["FP"]) == 5).all())

    def test_two_column_contract_is_preserved(self):
        result = roc(A, "Control", "Patient", "Higher in patients")
        self.assertEqual(len(result), 2)
        self.assertEqual(list(result[1].columns), ["Threshold", "False positive rate", "True positive rate"])
        self.assertIn("CI 95% low", result[0])

    def test_lower_direction_and_automatic(self):
        report, curve, rows = roc_analysis(A, "Control", "Patient", LOWER)
        self.assertAlmostEqual(report["AUC"], 4 / 15)
        self.assertEqual(rows["Threshold"].iloc[0], -np.inf)
        self.assertEqual(rows["Threshold"].iloc[-1], np.inf)
        self.assertEqual(curve["Threshold"].iloc[0], -np.inf)
        self.assertEqual(rows["Rule"].iloc[1].split()[1], "<=")
        automatic = roc(A, "Control", "Patient", "Automatic")[0]
        self.assertEqual(automatic["Direction"], HIGHER)
        negated = -A
        self.assertEqual(roc(negated, "Control", "Patient", "Automatic")[0]["Direction"], LOWER)
        equal = pd.DataFrame({"C": [1., 3.], "P": [2., 2.]})
        self.assertEqual(roc(equal, "C", "P", "Automatic")[0]["Direction"], HIGHER)

    def test_automatic_direction_does_not_overflow(self):
        big = 1.7e308
        frame = pd.DataFrame({"C": [big, big], "P": [big, -big]})
        self.assertEqual(roc(frame, "C", "P", "Automatic")[0]["Direction"], LOWER)
        frame = pd.DataFrame({"C": [-big, -big], "P": [big, big]})
        self.assertEqual(roc(frame, "C", "P", "Automatic")[0]["Direction"], HIGHER)

    def test_published_rules_reproduce_counts(self):
        cases = [(A["Control"].dropna(), A["Patient"]), ([1., 3.], [2., 4.]), ([4., 4., 4.], [4., 4.]),
                 ([1., 2.], [3., 4., 5.]), ([-1e308, 1e308, 0.], [1e308, -1e308]),
                 ([1., 1.], [np.nextafter(1., 2.)] * 2), ([-0.0, 1.], [0.0, 2.]),
                 ([1e308, 1.7e308], [-1.7e308, -1e308])]
        for direction, (controls, patients) in itertools.product((HIGHER, LOWER), cases):
            _, _, rows = table(controls, patients, direction)
            finite = rows["Threshold"][np.isfinite(rows["Threshold"])]
            self.assertTrue(np.isfinite(finite).all())
            for _, row in rows.iterrows():
                tp, fp = apply_rule(row, direction, controls, patients)
                self.assertEqual((tp, fp), (row["TP"], row["FP"]), (direction, row.to_dict()))

    def test_all_equal_scores_have_two_endpoints(self):
        report, curve, rows = table([4, 4, 4], [4, 4])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows["Threshold type"].tolist(), ["Endpoint", "Endpoint"])
        self.assertEqual(report["AUC"], .5)
        self.assertEqual((report["SE (DeLong)"], report["CI 95% low"], report["CI 95% high"]), (0, .5, .5))
        self.assertTrue(np.isnan(report["p (normal approximation)"]))
        self.assertIn("p note", report)
        self.assertNotIn("Yes", rows["Youden candidate"].tolist())
        self.assertIn("None", report["Youden candidates"])

    def test_ties_among_maximum_j_are_all_highlighted(self):
        _, _, rows = table([1, 3], [2, 4])
        self.assertEqual(rows.loc[rows["Youden candidate"] == "Yes", "Threshold"].tolist(), [3.5, 1.5])

    def test_perfect_separation(self):
        for direction, auc in ((HIGHER, 1.), (LOWER, 0.)):
            report, _, rows = table([1, 2], [3, 4, 5], direction)
            self.assertEqual(report["AUC"], auc)
            self.assertEqual(report["SE (DeLong)"], 0)
            self.assertTrue(np.isnan(report["p (normal approximation)"]))
        _, _, rows = table([1, 2], [3, 4, 5])
        self.assertEqual(rows.loc[rows["Youden J"] == 1, "Threshold"].tolist(), [2.5])
        self.assertEqual(rows.loc[rows["Youden candidate"] == "Yes", "Threshold"].tolist(), [2.5])

    def test_no_candidate_when_interior_j_is_not_positive(self):
        _, _, rows = table([3, 4], [1, 2])          # patients lower, forced Higher: AUC 0
        self.assertNotIn("Yes", rows["Youden candidate"].tolist())

    def test_adjacent_floats_use_observed_boundary(self):
        upper = np.nextafter(1., 2.)
        _, _, rows = table([1., 1.], [upper, upper], HIGHER)
        self.assertEqual(rows["Threshold"].tolist()[1], upper)
        self.assertEqual(rows["Threshold type"].tolist()[1], "Observed boundary")
        rule = rows["Rule"].iat[1]
        operator, shown = rule.split()[1:]
        self.assertEqual(operator, ">=")
        self.assertEqual(float(shown), upper)
        self.assertFalse(1. >= float(shown))
        _, _, rows = table([1., 1.], [upper, upper], LOWER)
        self.assertEqual(rows["Threshold"].tolist()[1], 1.)
        self.assertEqual(rows["Rule"].tolist()[1].split()[1], "<=")

    def test_extreme_opposite_signs_keep_finite_midpoints(self):
        _, _, rows = table([-1.7e308, -1.7e308], [1.7e308, 1.7e308])
        self.assertEqual(rows["Threshold"].tolist()[1], 0.0)

    def test_signed_zeros_are_one_block(self):
        _, curve, rows = table([-0.0, -0.0], [0.0, 0.0])
        self.assertEqual(len(rows), 2)
        self.assertEqual(len(curve), 2)

    def test_independent_permutations_are_invariant(self):
        base = roc_analysis(A, "Control", "Patient", HIGHER)
        shuffled = pd.DataFrame({"Control": A["Control"].sample(frac=1, random_state=1).to_numpy(),
                                 "Patient": A["Patient"].sample(frac=1, random_state=2).to_numpy()})
        other = roc_analysis(shuffled, "Control", "Patient", HIGHER)
        pd.testing.assert_frame_equal(base[2], other[2])
        self.assertEqual(base[0]["AUC"], other[0]["AUC"])

    def test_brute_force_oracle_matches_random_data(self):
        rng = np.random.default_rng(7)
        for _ in range(20):
            controls, patients = rng.integers(0, 6, 7).astype(float), rng.integers(0, 8, 9).astype(float)
            report, curve, rows = table(controls, patients)
            phi = (patients[:, None] > controls[None, :]) + .5 * (patients[:, None] == controls[None, :])
            self.assertAlmostEqual(report["AUC"], phi.mean())
            v_pos, v_neg = phi.mean(1), phi.mean(0)
            expected = v_pos.var(ddof=1) / 9 + v_neg.var(ddof=1) / 7
            self.assertAlmostEqual(report["Variance (DeLong)"], expected)
            self.assertAlmostEqual(np.trapezoid(curve["True positive rate"], curve["False positive rate"]), phi.mean())


class ErrorTests(unittest.TestCase):
    def test_validation(self):
        frame = A.assign(Text=["a", "b", "c", "d", "e", "f"], Same=1.)
        with self.assertRaises(FieldError):
            roc_analysis(frame, "Control", "Control", HIGHER)
        with self.assertRaisesRegex(ValueError, "Choose a column for Patient"):
            roc_analysis(frame, "Control", "Missing", HIGHER)
        with self.assertRaisesRegex(ValueError, "contains text"):
            roc_analysis(frame, "Control", "Text", HIGHER)
        with self.assertRaisesRegex(ValueError, "infinite"):
            roc_analysis(A.assign(Patient=[1, 2, np.inf, 4, 5, 6]), "Control", "Patient", HIGHER)
        with self.assertRaisesRegex(ValueError, "at least two"):
            roc_analysis(pd.DataFrame({"C": [1., np.nan, np.nan], "P": [1., 2., 3.]}), "C", "P", HIGHER)
        with self.assertRaises(FieldError):
            roc_analysis(A, "Control", "Patient", "Sideways")
        for level in (0, 100, float("nan"), float("inf"), -1, "x"):
            with self.assertRaises(FieldError, msg=repr(level)):
                roc_analysis(A, "Control", "Patient", HIGHER, level)
        with self.assertRaises(FieldError):
            roc_analysis(A, "Control", "Patient", HIGHER, 95., "Wald")

    def test_large_integer_scores_cannot_be_rounded_into_ties(self):
        frame = pd.DataFrame({"Control": [2**53, 2**53], "Patient": [2**53 + 1, 2**53 + 1]})
        with self.assertRaisesRegex(FieldError, "supported precision"):
            roc_analysis(frame, "Control", "Patient", HIGHER)

    def test_blank_cells_are_filtered_per_column(self):
        report = roc(A, "Control", "Patient", HIGHER)[0]
        self.assertEqual((report["Control N"], report["Patient N"]), (5, 6))


class IntervalTests(unittest.TestCase):
    TABLE = [
        (0, 6, 95, [0, 0.459258126440], [0, 0.390334287902], [0, 0.390334287902]),
        (6, 6, 95, [0.540741873560, 1], [0.609665712098, 1], [0.609665712098, 1]),
        (2, 6, 95, [0.043271868293, 0.777221904496], [0.096771411106, 0.700006684862], [0.059226918450, 0.700006684862]),
        (3, 5, 95, [0.146632799635, 0.947255049474], [0.230724281276, 0.882379225767], [0.230724281276, 0.928927697860]),
        (2, 6, 90, [0.062849891708, 0.728661627480], [0.117276094102, 0.652985233000], [0.088635268065, 0.652985233000]),
    ]

    def test_reference_intervals(self):
        for k, n, level, *expected in self.TABLE:
            for method, want in zip(ROC_INTERVALS, expected):
                low, high = binomial_interval(method, [k], [n], level)
                np.testing.assert_allclose([low[0], high[0]], want, atol=1e-9, err_msg=f"{method} {k}/{n}")

    def test_wilson_brown_switch_points(self):
        low, _ = binomial_interval(WB, [3], [50], 95)
        self.assertAlmostEqual(low[0], 0.020614970349, places=9)
        low, _ = binomial_interval(WB, [3], [51], 95)
        self.assertAlmostEqual(low[0], 0.016033165631, places=9)
        _, high = binomial_interval(WB, [48], [51], 95)
        self.assertAlmostEqual(high[0], 0.983966834369, places=9)

    def test_table_uses_tp_over_patients_and_tn_over_controls(self):
        _, _, rows = roc_analysis(A, "Control", "Patient", HIGHER, 90., WB, "Percentages")
        row = rows[rows["Threshold"] == 5.5].iloc[0]
        self.assertAlmostEqual(row["Sensitivity (%)"], 100 * 2 / 6)
        self.assertAlmostEqual(row["Sensitivity CI 90% low (%)"], 8.863526806494, places=8)
        self.assertAlmostEqual(row["Sensitivity CI 90% high (%)"], 65.298523299968, places=8)
        self.assertEqual(row["Specificity (%)"], 100.)
        self.assertEqual(row["TP"], 2)
        self.assertLessEqual(row["Youden J"], 1)          # J keeps its own scale
        _, curve, _ = roc_analysis(A, "Control", "Patient", HIGHER, 90., WB, "Percentages")
        self.assertLessEqual(curve["True positive rate"].max(), 1)


class AucInferenceTests(unittest.TestCase):
    def test_fixture_a_oracle(self):
        report = roc(A, "Control", "Patient", HIGHER)[0]
        self.assertAlmostEqual(report["AUC"], 11 / 15)
        self.assertAlmostEqual(report["Variance (DeLong)"], 107 / 4000)
        self.assertAlmostEqual(report["SE (DeLong)"], 0.163554272337961, places=12)
        self.assertAlmostEqual(report["CI 95% low"], 0.412772850033274, places=12)
        self.assertEqual(report["CI 95% high"], 1)
        self.assertAlmostEqual(report["p (normal approximation)"], 0.153683218842248, places=12)
        report90 = roc(A, "Control", "Patient", HIGHER, 90.)[0]
        self.assertAlmostEqual(report90["CI 90% low"], 0.464310495274829, places=12)
        self.assertNotIn("CI 95% low", report90)
        lower = roc(A, "Control", "Patient", LOWER)[0]
        self.assertAlmostEqual(lower["AUC"], 4 / 15)
        self.assertAlmostEqual(lower["p (normal approximation)"], 0.153683218842248, places=12)
        self.assertEqual(lower["CI 95% low"], 0)
        self.assertAlmostEqual(lower["CI 95% high"], 0.587227149966726, places=12)

    def test_edit_a_patient(self):
        frame = A.assign(Patient=[2, 3, 4, 4, 6, 0])
        report = roc(frame, "Control", "Patient", HIGHER, 90.)[0]
        self.assertAlmostEqual(report["AUC"], 17 / 30)
        self.assertAlmostEqual(report["Variance (DeLong)"], 147 / 4000)
        self.assertAlmostEqual(report["CI 90% low"], 0.251343464320238, places=12)
        self.assertAlmostEqual(report["CI 90% high"], 0.881989869013095, places=12)

    def test_excluded_cell(self):
        frame = A.copy()
        frame.loc[0, "Patient"] = np.nan
        report = roc(frame, "Control", "Patient", HIGHER)[0]
        self.assertEqual((report["Control N"], report["Patient N"]), (5, 5))
        self.assertAlmostEqual(report["AUC"], .8)


class WorkbenchTests(unittest.TestCase):
    LEGACY = {"Control": "Control", "Patient": "Patient", "Direction": "Automatic"}

    def test_legacy_recipe_and_sheet_order(self):
        result = analyse("ROC curve", A, self.LEGACY)
        self.assertEqual(list(result.tables), ["ROC summary", "Curve points", "Diagnostic thresholds"])
        self.assertIsNotNone(result.figure)
        summary = result.tables["ROC summary"]["Value"]
        self.assertAlmostEqual(summary["AUC"], 11 / 15)
        self.assertIn("CI 95% low", summary.index)
        thresholds = result.tables["Diagnostic thresholds"]
        self.assertIn("Sensitivity CI 95% low", thresholds)
        self.assertTrue(all(pd.api.types.is_numeric_dtype(thresholds[c]) for c in ("Threshold", "TP", "Youden J")))
        self.assertEqual(len(result.figure.axes[0].get_lines()), 2)

    def test_percentage_labels_and_ticks(self):
        options = {**self.LEGACY, "Confidence level (%)": 90., "Confidence interval": WB, "Show as": "Percentages"}
        result = analyse("ROC curve", A, options)
        thresholds = result.tables["Diagnostic thresholds"]
        self.assertIn("Sensitivity CI 90% low (%)", thresholds)
        axes = result.figure.axes[0]
        self.assertEqual(axes.get_xlabel(), "False positive rate (%)")
        result.figure.canvas.draw()
        self.assertIn("100%", [t.get_text() for t in axes.get_xticklabels()])
        curve = result.tables["Curve points"]
        self.assertLessEqual(curve["False positive rate"].max(), 1)

    def test_project_roundtrip_with_recipe_and_infinities(self):
        from analisi.data import Dataset, load_workspace, save_project

        options = {**self.LEGACY, "Direction": HIGHER, "Confidence level (%)": 90.,
                   "Confidence interval": WB, "Show as": "Percentages"}
        data = Dataset(A.copy())
        data.analyses.append(("ROC curve", options))
        thresholds = analyse("ROC curve", A, options).tables["Diagnostic thresholds"]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "roc.alab"
            save_project(path, {"Data": data, "Thresholds": Dataset(thresholds)})
            tables, _ = load_workspace(path)
        method, recipe = tables["Data"].analyses[0]
        self.assertEqual((method, recipe), ("ROC curve", options))
        result = analyse(method, tables["Data"].frame(mask_excluded=True), recipe)
        row = result.tables["Diagnostic thresholds"].query("Threshold == 5.5").iloc[0]
        self.assertAlmostEqual(row["Sensitivity (%)"], 100 * 2 / 6)
        self.assertAlmostEqual(row["Sensitivity CI 90% low (%)"], 8.863526806494, places=8)
        self.assertAlmostEqual(row["Sensitivity CI 90% high (%)"], 65.298523299968, places=8)
        saved = tables["Thresholds"].raw
        self.assertEqual(saved["Threshold"].iloc[0], np.inf)
        self.assertEqual(saved["Threshold"].iloc[-1], -np.inf)
        self.assertEqual(saved["Rule"].iloc[0], "score >= +∞")


B = pd.DataFrame({"Control A": [1, 2, 2, 4, 5, np.nan], "Control B": [2, 4, 1, 3, 5, np.nan],
                  "Patient A": [2, 3, 4, 4, 6, 7], "Patient B": [1, 5, 2, 6, 7, 5]})
NAMES = ("Control A", "Control B", "Patient A", "Patient B")


class PairedRocTests(unittest.TestCase):
    def compare(self, frame=B, **options):
        return compare_paired_roc(frame, *NAMES, **options)

    def test_fixture_b(self):
        report, curve_a, curve_b = self.compare()
        self.assertAlmostEqual(report["AUC A"], 11 / 15)
        self.assertAlmostEqual(report["AUC B"], 7 / 10)
        self.assertAlmostEqual(report["Variance A"], 107 / 4000)
        self.assertAlmostEqual(report["Variance B"], 367 / 12000)
        self.assertAlmostEqual(report["Covariance (A, B)"], 1229 / 72000)
        self.assertAlmostEqual(report["Difference (A − B)"], 1 / 30)
        self.assertAlmostEqual(report["Variance of difference"], 0.0231944444444444, places=12)
        self.assertAlmostEqual(report["SE (difference)"], 0.152297224020809, places=12)
        self.assertAlmostEqual(report["Z"], 0.218870262065833, places=12)
        self.assertAlmostEqual(report["p (normal approximation)"], 0.826751112261351, places=12)
        self.assertAlmostEqual(report["CI 95% low (difference)"], -0.265163740692881, places=12)
        self.assertAlmostEqual(report["CI 95% high (difference)"], 0.331830407359547, places=12)
        self.assertEqual((report["Control pairs used"], report["Patient pairs used"]), (5, 6))
        self.assertEqual((report["Incomplete control pairs discarded"], report["Incomplete patient pairs discarded"]), (0, 0))
        self.assertAlmostEqual(np.trapezoid(curve_a["True positive rate"], curve_a["False positive rate"]), 11 / 15)
        self.assertAlmostEqual(np.trapezoid(curve_b["True positive rate"], curve_b["False positive rate"]), 7 / 10)

    def test_constant_nonzero_placement_difference_has_zero_variance(self):
        frame = pd.DataFrame(dict(zip(NAMES, ([0, 0, 2], [0, 0, 2], [1, 1, 3], [0, 0, 1]))))
        report = self.compare(frame)[0]
        self.assertEqual(report["Difference (A − B)"], 1 / 3)
        self.assertEqual(report["Variance of difference"], 0.)
        self.assertTrue(np.isnan(report["p (normal approximation)"]))

    def test_covariance_identity(self):
        report = self.compare()[0]
        self.assertAlmostEqual(report["Variance of difference"], report["Variance A"] + report["Variance B"]
                               - 2 * report["Covariance (A, B)"])

    def test_incomplete_rows_per_block(self):
        frame = B.copy()
        frame.loc[2, "Control B"] = np.nan
        frame.loc[3, "Patient B"] = np.nan
        report = self.compare(frame)[0]
        self.assertEqual((report["Control pairs used"], report["Patient pairs used"]), (4, 5))
        self.assertEqual((report["Incomplete control pairs discarded"], report["Incomplete patient pairs discarded"]), (1, 1))
        self.assertAlmostEqual(report["AUC A"], .7)
        self.assertAlmostEqual(report["AUC B"], .575)
        self.assertAlmostEqual(report["Difference (A − B)"], .125)
        self.assertAlmostEqual(report["Covariance (A, B)"], 169 / 6400)
        self.assertAlmostEqual(report["SE (difference)"], 0.184560288252918, places=12)
        self.assertAlmostEqual(report["p (normal approximation)"], 0.498224853418339, places=12)

    def test_swap_markers_flips_sign_keeps_p(self):
        report = self.compare()[0]
        swapped = compare_paired_roc(B, "Control B", "Control A", "Patient B", "Patient A")[0]
        self.assertAlmostEqual(swapped["Difference (A − B)"], -report["Difference (A − B)"])
        self.assertAlmostEqual(swapped["Z"], -report["Z"])
        self.assertAlmostEqual(swapped["p (normal approximation)"], report["p (normal approximation)"])

    def test_joint_permutation_within_class_is_invariant(self):
        controls = B.iloc[:5][["Control A", "Control B"]].iloc[[3, 0, 4, 2, 1]].reset_index(drop=True)
        patients = B[["Patient A", "Patient B"]].iloc[[5, 2, 0, 4, 1, 3]].reset_index(drop=True)
        shuffled = pd.concat([controls, patients], axis=1)
        a, b = self.compare()[0], self.compare(shuffled)[0]
        for key in ("Difference (A − B)", "Variance of difference", "Covariance (A, B)", "p (normal approximation)"):
            self.assertAlmostEqual(a[key], b[key])

    def test_breaking_the_pairing_changes_the_result(self):
        broken = B.copy()
        broken["Patient B"] = B["Patient B"].iloc[[1, 0, 2, 3, 4, 5]].to_numpy()
        self.assertNotAlmostEqual(self.compare()[0]["Covariance (A, B)"], self.compare(broken)[0]["Covariance (A, B)"])

    def test_identical_markers_have_zero_variance(self):
        frame = pd.DataFrame({"Control A": B["Control A"], "Control B": B["Control A"],
                              "Patient A": B["Patient A"], "Patient B": B["Patient A"]})
        report = self.compare(frame)[0]
        self.assertEqual((report["Difference (A − B)"], report["SE (difference)"]), (0, 0))
        self.assertTrue(np.isnan(report["Z"]) and np.isnan(report["p (normal approximation)"]))
        self.assertIn("Note", report)

    def test_directions_and_errors(self):
        flipped = self.compare(direction_b="Lower in patients")[0]
        self.assertAlmostEqual(flipped["AUC B"], 1 - 7 / 10)
        with self.assertRaises(FieldError):
            self.compare(direction_a="Automatic")
        with self.assertRaises(FieldError):
            compare_paired_roc(B, "Control A", "Control A", "Patient A", "Patient B")
        with self.assertRaises(FieldError):
            self.compare(level=100)
        with self.assertRaisesRegex(ValueError, "two valid pairs"):
            compare_paired_roc(B.assign(**{"Control B": [1, np.nan, np.nan, np.nan, np.nan, np.nan]}), *NAMES)
        with self.assertRaisesRegex(ValueError, "contains text"):
            compare_paired_roc(B.assign(**{"Control B": list("abcdef")}), *NAMES)

    def test_workbench_graph_and_recalculation(self):
        options = dict(zip(NAMES, NAMES)) | {"Direction A": HIGHER, "Direction B": HIGHER}
        result = analyse("Compare paired ROC curves", B, options)
        self.assertEqual(list(result.tables), ["Paired ROC comparison", "Curve points A", "Curve points B"])
        self.assertEqual(len(result.figure.axes[0].get_lines()), 3)
        self.assertEqual(len(result.figure.axes[0].get_legend().get_texts()), 2)
        edited = analyse("Compare paired ROC curves", B.assign(**{"Patient B": [1, 5, 2, 6, 7, 0]}), options)
        self.assertNotEqual(edited.tables["Paired ROC comparison"].loc["AUC B", "Value"], .7)


if __name__ == "__main__":
    unittest.main()
