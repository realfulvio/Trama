"""Meta-analysis of effect estimates: numbers, field errors, missing cells, edge cases, figure and catalog."""
from io import BytesIO
import json
from math import exp, log, sqrt
from pathlib import Path
import tempfile
import threading
import unittest

import numpy as np
import pandas as pd
from scipy import stats

from analisi import meta_analysis as meta
from analisi.data import Dataset, load_workspace, save_project
from analisi.field_error import FieldError
from analisi.i18n import CATALOGS, placeholders, translate
from analisi.monte_carlo import MonteCarloCancelled
from analisi.presentation import apply_style
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "meta_analysis"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
REFERENCE = json.loads((DATA / "pm-reference.json").read_text(encoding="utf-8"))["cases"]
METHOD = meta.META_ANALYSIS
RANDOM, COMMON = meta.RANDOM, meta.COMMON
BASE = {"Study": "Study", "Estimate": "Estimate", "Standard error": "SE", "Show graph": False}


def fixture(name):
    return pd.read_csv(DATA / name, keep_default_na=False).replace("", np.nan)


def run(frame, **options):
    return analyse(METHOD, frame, {**BASE, **options})


def close(actual, expected, rtol=1e-12, atol=1e-13):
    np.testing.assert_allclose(np.asarray(actual, dtype=float), np.asarray(expected, dtype=float),
                               rtol=rtol, atol=atol)


def pooled(result):
    return result.tables["Pooled"].iloc[0]


def heterogeneity(result):
    return result.tables["Heterogeneity"].iloc[0]


class CommonEffectTests(unittest.TestCase):
    def test_equal_weights_closed_form(self):
        result = run(fixture("differences.csv"))
        self.assertEqual(list(result.tables), ["Studies", "Pooled", "Heterogeneity"])
        self.assertIsNone(result.figure)
        row = pooled(result)
        # Four studies with SE 0.2: SE = 0.2/√4, mean 0.8, normal interval.
        close([row["Estimate"], row["SE"]], [0.8, 0.1])
        z = stats.norm.ppf(0.975)
        close([row["Lower"], row["Upper"]], [0.8 - z * 0.1, 0.8 + z * 0.1])
        self.assertEqual((row["Studies"], row["Omitted studies"]), (4, 0))
        self.assertEqual((row["Pooling model"], row["Interval method"]), (COMMON, "Normal"))
        self.assertEqual(row["Prediction status"], meta.PI_NOT_REQUESTED)
        self.assertTrue(np.isnan(row["Prediction lower"]) and np.isnan(row["Prediction upper"]))
        het = heterogeneity(result)
        # Q = Σ (y − 0.8)²/0.04 = 0.8/0.04 = 20 with 3 df; I² = 1 − 3/20.
        close([het["Q"], het["Q df"], het["Q p"], het["I² (%)"]], [20.0, 3, stats.chi2.sf(20, 3), 85.0])
        self.assertTrue(np.isnan(het["Tau²"]), "Tau² is not estimated by the common-effect model")
        close(result.tables["Studies"]["Weight (%)"], [25.0] * 4)

    def test_unequal_weights_follow_the_inverse_variance(self):
        frame = pd.DataFrame({"Study": list("abc"), "Estimate": [1.0, 2.0, 4.0], "SE": [1.0, 2.0, 0.5]})
        result = run(frame)
        weights = np.array([1.0, 0.25, 4.0])
        mean = (weights * [1.0, 2.0, 4.0]).sum() / weights.sum()
        close(pooled(result)["Estimate"], mean)
        close(pooled(result)["SE"], 1 / sqrt(weights.sum()))
        close(result.tables["Studies"]["Weight (%)"], 100 * weights / weights.sum())
        q = (weights * (np.array([1.0, 2.0, 4.0]) - mean) ** 2).sum()
        close(heterogeneity(result)["Q"], q)

    def test_study_intervals_are_normal_at_the_chosen_level(self):
        result = run(fixture("differences.csv"), **{"Confidence level (%)": 90.0})
        studies = result.tables["Studies"]
        z = stats.norm.ppf(0.95)
        close(studies["Lower"], studies["Estimate"] - z * 0.2)
        close(studies["Upper"], studies["Estimate"] + z * 0.2)
        self.assertEqual(pooled(result)["Confidence level (%)"], 90.0)

    def test_the_random_interval_option_is_ignored_by_the_common_model(self):
        frame = fixture("differences.csv")
        a = run(frame, **{"Random interval": "Normal"})
        b = run(frame, **{"Random interval": "Modified Knapp–Hartung"})
        pd.testing.assert_frame_equal(a.tables["Pooled"], b.tables["Pooled"])


class RandomEffectsTests(unittest.TestCase):
    def test_equal_variances_have_a_closed_form_tau(self):
        result = run(fixture("differences.csv"), **{"Pooling model": RANDOM, "Prediction interval": True})
        het, row = heterogeneity(result), pooled(result)
        # Equal vᵢ: Q(τ²) = S/(v + τ²) = k − 1 gives τ² = S/(k − 1) − v = 0.8/3 − 0.04.
        close(het["Tau²"], 0.8 / 3 - 0.04)
        se = sqrt((0.04 + 0.8 / 3 - 0.04) / 4)
        close(row["SE"], se)
        t = stats.t.ppf(0.975, 3)
        close([row["Lower"], row["Upper"]], [0.8 - t * se, 0.8 + t * se])
        width = stats.t.ppf(0.975, 2) * sqrt(0.8 / 3 - 0.04 + se ** 2)
        close([row["Prediction lower"], row["Prediction upper"]], [0.8 - width, 0.8 + width])
        self.assertEqual(row["Interval method"], "Modified Knapp–Hartung")
        self.assertEqual(row["Prediction status"], meta.PI_DONE)
        # I² and Q always come from τ² = 0.
        close([het["Q"], het["I² (%)"]], [20.0, 85.0])

    def test_paule_mandel_matches_an_independent_fifty_digit_reference(self):
        for case in REFERENCE:
            with self.subTest(case["name"]):
                frame = pd.DataFrame({"Estimate": case["y"], "SE": case["se"]})
                normal = analyse(METHOD, frame, {"Estimate": "Estimate", "Standard error": "SE",
                                                 "Pooling model": RANDOM, "Random interval": "Normal",
                                                 "Show graph": False})
                modified = analyse(METHOD, frame, {"Estimate": "Estimate", "Standard error": "SE",
                                                   "Pooling model": RANDOM, "Show graph": False})
                common = analyse(METHOD, frame, {"Estimate": "Estimate", "Standard error": "SE",
                                                 "Show graph": False})
                scale = max(abs(case["mean"]), case["se_normal"])
                close(heterogeneity(normal)["Tau²"], case["tau2"], rtol=1e-11, atol=1e-300)
                close(pooled(normal)["Estimate"], case["mean"], rtol=0, atol=1e-12 * scale)
                close(pooled(normal)["SE"], case["se_normal"], rtol=1e-11)
                close(pooled(modified)["SE"], case["se_mkh"], rtol=1e-11)
                close(normal.tables["Studies"]["Weight (%)"], case["weights"], rtol=1e-11)
                close(heterogeneity(normal)["Q"], case["Q0"], rtol=1e-12)
                close(pooled(common)["Estimate"], case["common_mean"], rtol=0, atol=1e-12 * scale)
                close(pooled(common)["SE"], case["common_se"], rtol=1e-12)

    def test_the_solution_satisfies_the_estimating_equation(self):
        rng = np.random.default_rng(5)
        for trial in range(40):
            k = int(rng.integers(3, 50))
            se = rng.uniform(0.02, 2.0, k)
            y = rng.normal(0, rng.uniform(0.1, 2), k) + rng.normal(0, se)
            result = analyse(METHOD, pd.DataFrame({"y": y, "se": se}),
                             {"Estimate": "y", "Standard error": "se", "Pooling model": RANDOM, "Show graph": False})
            tau = heterogeneity(result)["Tau²"]
            w = 1 / (se ** 2 + tau)
            m = (w * y).sum() / w.sum()
            q_tau = (w * (y - m) ** 2).sum()
            q0 = heterogeneity(result)["Q"]
            if q0 <= k - 1:
                self.assertEqual(tau, 0.0)
            else:
                self.assertGreater(tau, 0)
                self.assertAlmostEqual(q_tau, k - 1, delta=1e-9 * k)
            close(pooled(result)["Estimate"], m, rtol=1e-10, atol=1e-12)

    def test_normal_and_modified_intervals_differ_only_in_quantile_and_floor(self):
        frame = fixture("zero-tau.csv")
        options = {"Pooling model": RANDOM, "Measure": "Ratio"}
        modified, normal = run(frame, **options), run(frame, **options, **{"Random interval": "Normal"})
        # τ² = 0 and q⋆ = Q(0)/2 < 1: the modified SE is floored at 1/√Σw, the quantile is t(2).
        self.assertEqual(heterogeneity(modified)["Tau²"], 0.0)
        self.assertLess(heterogeneity(modified)["Q"] / 2, 1)
        close(pooled(modified)["SE"], pooled(normal)["SE"])
        expected = EXPECTED["zero_tau"]
        close(pooled(modified)["SE"], expected["SE"])
        log_mean = log(expected["Estimate"])
        se = expected["SE"]
        close(pooled(normal)["Lower"], exp(log_mean - stats.norm.ppf(0.975) * se))
        close(pooled(modified)["Lower"], exp(log_mean - stats.t.ppf(0.975, 2) * se))

    def test_modified_knapp_hartung_inflates_when_q_star_exceeds_one(self):
        # Q(τ²) = k − 1 at a positive Paule–Mandel root, so q⋆ = 1 there: inflation needs τ² = 0 with Q(0) > k − 1,
        # impossible for Paule–Mandel. The floor is therefore checked on the explicit formula with a common τ² = 0.
        frame = pd.DataFrame({"Estimate": [0.0, 1.0, 2.0], "SE": [0.5, 0.5, 0.5]})
        result = analyse(METHOD, frame, {"Estimate": "Estimate", "Standard error": "SE", "Pooling model": RANDOM,
                                         "Show graph": False})
        tau = heterogeneity(result)["Tau²"]
        w = 1 / (0.25 + tau)
        q_star = (w * ((np.array([0.0, 1.0, 2.0]) - 1.0) ** 2)).sum() / 2
        close(q_star, 1.0)
        close(pooled(result)["SE"], sqrt(max(1, q_star) / (3 * w)))

    def test_package_references(self):
        for mode, name, ratio, random in (("common", "differences.csv", False, False),
                                          ("random", "differences.csv", False, True),
                                          ("ratios", "ratios.csv", True, True),
                                          ("zero_tau", "zero-tau.csv", True, True)):
            with self.subTest(mode):
                result = run(fixture(name), **{"Measure": "Ratio" if ratio else "Difference",
                                               "Pooling model": RANDOM if random else COMMON,
                                               "Prediction interval": random})
                expected = EXPECTED[mode]
                row, het = pooled(result), heterogeneity(result)
                for column in ("Studies", "Estimate", "Lower", "Upper", "SE"):
                    close(row[column], expected[column], rtol=1e-10)
                for column in ("Q", "Q p", "I² (%)"):
                    close(het[column], expected[column], rtol=1e-10)
                close(result.tables["Studies"]["Weight (%)"], expected["Weight (%)"], rtol=1e-10)
                if random:
                    close(het["Tau²"], expected["Tau²"], rtol=1e-10, atol=1e-15)
                    close([row["Prediction lower"], row["Prediction upper"]],
                          [expected["Prediction lower"], expected["Prediction upper"]], rtol=1e-10)


class RatioTests(unittest.TestCase):
    def test_the_exponential_is_applied_once_and_se_stays_on_the_log_scale(self):
        frame = fixture("ratios.csv")
        result = run(frame, **{"Measure": "Ratio", "Pooling model": RANDOM, "Prediction interval": True})
        studies = result.tables["Studies"]
        close(studies["Estimate"], frame["Estimate"], rtol=0, atol=0)
        close(studies["Standard error"], frame["SE"], rtol=0, atol=0)
        close(studies[["Lower", "Upper"]].to_numpy(), EXPECTED["ratio_study_limits"])
        row = pooled(result)
        close(row["SE"], EXPECTED["ratios"]["SE"])
        # The SE belongs to ln(ratio): the limits are exp(ln m ± t·SE), never m ± t·SE.
        t = stats.t.ppf(0.975, 4)
        close(row["Lower"], row["Estimate"] * exp(-t * row["SE"]))
        close(row["Upper"], row["Estimate"] * exp(t * row["SE"]))
        self.assertGreater(row["Lower"], 0)

    def test_duplicate_and_dollar_labels_stay_literal_and_separate(self):
        result = run(fixture("ratios.csv"), Measure="Ratio")
        studies = result.tables["Studies"]
        self.assertEqual(list(studies["Study"]), ["Cohort $", "Cohort B", "Cohort C", "Cohort B", "Cohort D"])
        self.assertEqual(list(studies["Source row"]), [1, 2, 3, 4, 5])

    def test_a_ratio_must_be_positive_and_names_the_row(self):
        frame = fixture("ratios.csv")
        for bad in (0.0, -1.2):
            changed = frame.copy()
            changed.loc[2, "Estimate"] = bad
            with self.assertRaises(FieldError) as raised:
                run(changed, Measure="Ratio")
            self.assertEqual(raised.exception.field, "Estimate")
            self.assertIn("source row 3", str(raised.exception))
        # A difference may be zero or negative.
        changed = frame.copy()
        changed.loc[2, "Estimate"] = -1.2
        self.assertEqual(pooled(run(changed))["Studies"], 5)

    def test_swapping_the_unit_changes_the_answer(self):
        frame = fixture("ratios.csv")
        as_ratio = pooled(run(frame, Measure="Ratio"))
        as_difference = pooled(run(frame, Measure="Difference"))
        self.assertNotAlmostEqual(as_ratio["Estimate"], as_difference["Estimate"], places=3)
        logged = frame.assign(Estimate=np.log(frame["Estimate"]))
        close(np.log(as_ratio["Estimate"]), pooled(run(logged))["Estimate"])
        close(as_ratio["SE"], pooled(run(logged))["SE"])


class RowsAndFieldsTests(unittest.TestCase):
    def test_blank_and_excluded_cells_omit_the_row_and_are_counted(self):
        frame = fixture("ratios.csv")
        frame.loc[1, "SE"] = np.nan
        frame.loc[3, "Estimate"] = pd.NA
        frame.loc[4, "Study"] = np.nan
        result = run(frame.astype({"Estimate": object}), Measure="Ratio")
        studies = result.tables["Studies"]
        self.assertEqual(list(studies["Source row"]), [1, 3, 5])
        self.assertEqual(list(studies["Study"]), ["Cohort $", "Cohort C", "Row 5"])
        self.assertEqual((pooled(result)["Studies"], pooled(result)["Omitted studies"]), (3, 2))

    def test_the_source_row_is_the_physical_position_not_the_index(self):
        frame = fixture("differences.csv")
        frame.index = [7, 7, 3, 1]
        result = run(frame, **{"Leave one out": True})
        self.assertEqual(list(result.tables["Studies"]["Source row"]), [1, 2, 3, 4])
        self.assertEqual(list(result.tables["Leave one out"]["Omitted source row"]), [1, 2, 3, 4])

    def test_text_cells_and_numbers_with_a_decimal_comma(self):
        frame = fixture("differences.csv").astype({"Estimate": object, "SE": object})
        frame.loc[0, "Estimate"] = " 0,2 "
        frame.loc[1, "SE"] = "0.2"
        close(pooled(run(frame))["Estimate"], 0.8)
        frame.loc[2, "SE"] = "abc"
        with self.assertRaises(FieldError) as raised:
            run(frame)
        self.assertEqual(raised.exception.field, "Standard error")
        self.assertEqual(str(raised.exception), "Standard error: source row 3 is not a number (abc).")

    def test_invalid_cells_name_the_field_and_the_row(self):
        frame = fixture("differences.csv")
        cases = [("SE", 0.0, "Standard error", "Standard error: source row 2 must be greater than zero (0)."),
                 ("SE", -0.1, "Standard error", "Standard error: source row 2 must be greater than zero (-0.1)."),
                 ("SE", np.inf, "Standard error", "Standard error: source row 2 must be a finite number."),
                 ("Estimate", -np.inf, "Estimate", "Estimate: source row 2 must be a finite number."),
                 ("Estimate", True, "Estimate", "Estimate: source row 2 is not a number (True).")]
        for column, value, field, message in cases:
            with self.subTest(column=column, value=value):
                changed = frame.astype(object)
                changed.loc[1, column] = value
                with self.assertRaises(FieldError) as raised:
                    run(changed)
                self.assertEqual((raised.exception.field, str(raised.exception)), (field, message))

    def test_a_bad_cell_counts_even_when_the_other_value_is_missing(self):
        frame = fixture("differences.csv")
        frame.loc[1, "Estimate"] = np.nan
        frame.loc[1, "SE"] = 0.0
        with self.assertRaises(FieldError) as raised:
            run(frame)
        self.assertEqual(raised.exception.field, "Standard error")

    def test_columns_must_exist_and_be_distinct(self):
        frame = fixture("differences.csv")
        cases = [({"Standard error": "Estimate"}, "Standard error", "choose a column different from Estimate"),
                 ({"Study": "SE"}, "Study", "choose a column different from Standard error"),
                 ({"Study": "Estimate"}, "Study", "choose a column different from Estimate"),
                 ({"Estimate": None}, "Estimate", "Choose a column for Estimate."),
                 ({"Standard error": ""}, "Standard error", "Choose a column for Standard error."),
                 ({"Estimate": "Effect"}, "Estimate", 'Choose an existing column for Estimate: "Effect"')]
        for change, field, text in cases:
            with self.subTest(change):
                with self.assertRaises(FieldError) as raised:
                    run(frame, **change)
                self.assertEqual(raised.exception.field, field)
                self.assertIn(text, str(raised.exception))
        twin = frame.copy()
        twin.columns = ["Study", "Estimate", "Estimate"]
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, twin, {"Estimate": "Estimate", "Standard error": "Study"})
        self.assertEqual(raised.exception.field, "Estimate")

    def test_options_are_validated_on_their_fields(self):
        frame = fixture("differences.csv")
        cases = [({"Measure": "Odds"}, "Measure"), ({"Pooling model": "DerSimonian–Laird"}, "Pooling model"),
                 ({"Pooling model": RANDOM, "Random interval": "HKSJ"}, "Random interval"),
                 ({"Confidence level (%)": 0.0}, "Confidence level (%)"),
                 ({"Confidence level (%)": 100.0}, "Confidence level (%)"),
                 ({"Confidence level (%)": float("nan")}, "Confidence level (%)"),
                 ({"Confidence level (%)": True}, "Confidence level (%)"),
                 ({"Confidence level (%)": "95"}, "Confidence level (%)"),
                 ({"Leave one out": 1}, "Leave one out"), ({"Show graph": "yes"}, "Show graph"),
                 ({"Prediction interval": None}, "Prediction interval")]
        for change, field in cases:
            with self.subTest(change):
                with self.assertRaises(FieldError) as raised:
                    run(frame, **change)
                self.assertEqual(raised.exception.field, field)

    def test_two_to_two_hundred_studies(self):
        frame = fixture("differences.csv")
        with self.assertRaises(FieldError) as raised:
            run(frame.iloc[:1])
        self.assertEqual(raised.exception.field, "Estimate")
        self.assertIn("1 found", str(raised.exception))
        two = run(frame.iloc[:2], **{"Pooling model": RANDOM})
        self.assertEqual(pooled(two)["Studies"], 2)
        rng = np.random.default_rng(1)
        many = pd.DataFrame({"Estimate": rng.normal(size=201), "SE": rng.uniform(.1, 1, 201)})
        self.assertEqual(pooled(analyse(METHOD, many.iloc[:200], {"Estimate": "Estimate", "Standard error": "SE",
                                                                  "Show graph": False}))["Studies"], 200)
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, many, {"Estimate": "Estimate", "Standard error": "SE"})
        self.assertIn("201 found", str(raised.exception))
        # Blank rows do not count towards the limit, but they are reported as omitted.
        padded = pd.concat([many.iloc[:200], pd.DataFrame({"Estimate": [np.nan] * 5, "SE": [np.nan] * 5})])
        row = pooled(analyse(METHOD, padded, {"Estimate": "Estimate", "Standard error": "SE", "Show graph": False}))
        self.assertEqual((row["Studies"], row["Omitted studies"]), (200, 5))

    def test_the_dialog_check_runs_every_field_check_and_the_main_fit(self):
        frame = fixture("ratios.csv")
        chosen = meta.check_options(frame, {**BASE, "Measure": "Ratio", "Leave one out": True})
        self.assertEqual(chosen["measure"], "Ratio")
        with self.assertRaises(FieldError):
            meta.check_options(frame.assign(SE=0), BASE)


class EdgeCaseTests(unittest.TestCase):
    def test_two_studies_keep_the_estimate_and_explain_the_empty_prediction_and_omissions(self):
        frame = fixture("ratios.csv").iloc[:2]
        result = run(frame, **{"Measure": "Ratio", "Pooling model": RANDOM, "Prediction interval": True,
                               "Leave one out": True})
        row = pooled(result)
        self.assertTrue(np.isfinite([row["Estimate"], row["Lower"], row["Upper"]]).all())
        self.assertTrue(np.isnan(row["Prediction lower"]) and np.isnan(row["Prediction upper"]))
        self.assertEqual(row["Prediction status"], meta.PI_TWO)
        # t with 1 df for the modified Knapp–Hartung interval.
        close(np.log(row["Upper"] / row["Estimate"]), stats.t.ppf(0.975, 1) * row["SE"])
        loo = result.tables["Leave one out"]
        self.assertEqual(list(loo.columns), meta.LOO_COLUMNS)
        self.assertTrue(loo[["Estimate", "Lower", "Upper", "Tau²"]].isna().all().all())
        self.assertEqual(list(loo["Status"]), [meta.LOO_ONE] * 2)
        self.assertEqual(list(loo["Studies"]), [1, 1])

    def test_prediction_status_for_each_case(self):
        frame = fixture("differences.csv")
        self.assertEqual(pooled(run(frame, **{"Prediction interval": True}))["Prediction status"], meta.PI_COMMON)
        self.assertEqual(pooled(run(frame, **{"Pooling model": RANDOM}))["Prediction status"], meta.PI_NOT_REQUESTED)
        three = pooled(run(frame.iloc[:3], **{"Pooling model": RANDOM, "Prediction interval": True}))
        self.assertEqual(three["Prediction status"], meta.PI_DONE)
        self.assertTrue(np.isfinite(three["Prediction lower"]))

    def test_zero_tau_edge(self):
        result = run(fixture("zero-tau.csv"), **{"Measure": "Ratio", "Pooling model": RANDOM})
        het = heterogeneity(result)
        self.assertEqual(het["Tau²"], 0.0)
        self.assertEqual(het["I² (%)"], 0.0)
        identical = pd.DataFrame({"Estimate": [1.0, 1.0, 1.0], "SE": [0.1, 0.2, 0.3]})
        same = analyse(METHOD, identical, {"Estimate": "Estimate", "Standard error": "SE", "Pooling model": RANDOM,
                                           "Show graph": False})
        self.assertEqual((heterogeneity(same)["Q"], heterogeneity(same)["I² (%)"]), (0.0, 0.0))

    def test_units_from_tiny_to_huge_give_the_same_answer(self):
        frame = pd.DataFrame({"Estimate": [0.2, 0.6, 1.0, 1.4, 0.9], "SE": [0.2, 0.25, 0.2, 0.3, 0.1]})
        options = {"Estimate": "Estimate", "Standard error": "SE", "Pooling model": RANDOM, "Show graph": False,
                   "Prediction interval": True, "Leave one out": True}
        reference = analyse(METHOD, frame, options)
        for factor in (1e-150, 1e-20, 1e20, 1e150):
            with self.subTest(factor=factor):
                scaled = analyse(METHOD, frame * factor, options)
                close(pooled(scaled)["Estimate"] / factor, pooled(reference)["Estimate"], rtol=1e-13)
                close(pooled(scaled)["SE"] / factor, pooled(reference)["SE"], rtol=1e-13)
                close(heterogeneity(scaled)["Tau²"] / factor ** 2, heterogeneity(reference)["Tau²"], rtol=1e-12)
                close(heterogeneity(scaled)["Q"], heterogeneity(reference)["Q"], rtol=1e-13)
                close(scaled.tables["Leave one out"]["Estimate"] / factor,
                      reference.tables["Leave one out"]["Estimate"], rtol=1e-12)

    def test_values_beyond_the_representable_range_are_refused_on_a_field(self):
        frame = pd.DataFrame({"Estimate": [0.2, 0.6, 1.0, 1.4], "SE": [0.2, 0.25, 0.2, 0.3]})
        options = {"Estimate": "Estimate", "Standard error": "SE", "Pooling model": RANDOM}
        for factor, text in ((1e-300, "too small"), (1e300, "too large")):
            with self.assertRaises(FieldError) as raised:
                analyse(METHOD, frame * factor, options)
            self.assertEqual(raised.exception.field, "Standard error")
            self.assertIn(text, str(raised.exception))
        spread = pd.DataFrame({"Estimate": [1.0, 2.0], "SE": [1e-200, 1e200]})
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, spread, {"Estimate": "Estimate", "Standard error": "SE"})
        self.assertEqual(raised.exception.field, "Standard error")
        ratio = pd.DataFrame({"Estimate": [1.2, 1.4], "SE": [1.0, 400.0]})
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, ratio, {"Estimate": "Estimate", "Standard error": "SE", "Measure": "Ratio"})
        self.assertEqual(raised.exception.field, "Standard error")
        self.assertIn("source row 2", str(raised.exception))

    def test_a_large_common_offset_keeps_the_spread(self):
        frame = pd.DataFrame({"Estimate": [0.2, 0.6, 1.0, 1.4, 0.9], "SE": [0.2, 0.25, 0.2, 0.3, 0.1]})
        options = {"Estimate": "Estimate", "Standard error": "SE", "Pooling model": RANDOM, "Show graph": False}
        reference = analyse(METHOD, frame, options)
        shifted = analyse(METHOD, frame.assign(Estimate=frame["Estimate"] + 1e6), options)
        close(pooled(shifted)["Estimate"] - 1e6, pooled(reference)["Estimate"], rtol=0, atol=1e-9)
        close(heterogeneity(shifted)["Tau²"], heterogeneity(reference)["Tau²"], rtol=1e-6)


class LeaveOneOutTests(unittest.TestCase):
    def test_each_omission_is_a_separate_fit_in_sheet_order(self):
        frame = fixture("ratios.csv")
        options = {"Measure": "Ratio", "Pooling model": RANDOM, "Leave one out": True}
        result = run(frame, **options)
        loo = result.tables["Leave one out"]
        self.assertEqual(list(result.tables), ["Studies", "Pooled", "Heterogeneity", "Leave one out"])
        self.assertEqual(list(loo.columns), meta.LOO_COLUMNS)
        self.assertEqual(list(loo["Omitted source row"]), [1, 2, 3, 4, 5])
        self.assertEqual(list(loo["Omitted study"]), list(frame["Study"]))
        close(loo["Estimate"], EXPECTED["omissions"], rtol=1e-10)
        for position in range(5):
            alone = run(frame.drop(index=position), **{**options, "Leave one out": False})
            close(loo.loc[position, ["Estimate", "Lower", "Upper"]].to_numpy(float),
                  [pooled(alone)[name] for name in ("Estimate", "Lower", "Upper")], rtol=1e-13)
            close(loo.loc[position, "Tau²"], heterogeneity(alone)["Tau²"], rtol=1e-12, atol=1e-300)
        self.assertEqual(set(loo["Status"]), {meta.CALCULATED})
        self.assertEqual(set(loo["Studies"]), {4})

    def test_common_effect_omissions_have_no_tau(self):
        loo = run(fixture("differences.csv"), **{"Leave one out": True}).tables["Leave one out"]
        self.assertTrue(loo["Tau²"].isna().all())
        close(loo["Estimate"], [(3.2 - value) / 3 for value in (0.2, 0.6, 1.0, 1.4)])

    def test_cancel_stops_between_omissions(self):
        class CountingEvent:
            def __init__(self, after):
                self.after, self.calls = after, 0

            def is_set(self):
                self.calls += 1
                return self.calls > self.after

        frame = fixture("ratios.csv")
        options = {**BASE, "Measure": "Ratio", "Pooling model": RANDOM, "Leave one out": True}
        event = CountingEvent(3)
        with self.assertRaises(MonteCarloCancelled):
            analyse(METHOD, frame, options, cancel=event)
        self.assertEqual(event.calls, 4, "the check runs before every omission")
        stopped = threading.Event()
        stopped.set()
        with self.assertRaises(meta.MetaAnalysisCancelled):
            analyse(METHOD, frame, options, cancel=stopped)
        self.assertIsNotNone(analyse(METHOD, frame, options, cancel=threading.Event()).tables["Leave one out"])

    def test_only_leave_one_out_offers_cancel(self):
        self.assertTrue(meta.cancellable(METHOD, {"Leave one out": True}))
        self.assertFalse(meta.cancellable(METHOD, {"Leave one out": False}))
        self.assertFalse(meta.cancellable("Forest plot", {"Leave one out": True}))


class FigureTests(unittest.TestCase):
    def figure(self, **options):
        return run(fixture("ratios.csv"), **{"Measure": "Ratio", "Pooling model": RANDOM, "Show graph": True,
                                             "Prediction interval": True, **options})

    def test_native_forest_parts(self):
        result = self.figure()
        axes = result.figure.axes[0]
        parts = axes._tramastat_meta
        self.assertEqual(axes.get_xscale(), "log")
        diamond = parts["diamond"]
        self.assertEqual(diamond.get_gid(), meta.DIAMOND_GID)
        xs = np.asarray(diamond.get_xy())[:, 0]
        close([xs.min(), xs.max()], [EXPECTED["ratios"]["Lower"], EXPECTED["ratios"]["Upper"]], rtol=1e-10)
        close(np.median(xs), EXPECTED["ratios"]["Estimate"], rtol=1e-10)
        self.assertEqual(parts["reference"].get_gid(), meta.REFERENCE_GID)
        close(parts["reference"].get_xdata(), [1, 1])
        close(parts["prediction"].get_xdata(), [EXPECTED["ratios"]["Prediction lower"],
                                                EXPECTED["ratios"]["Prediction upper"]], rtol=1e-10)
        segments = [np.asarray(segment) for segment in parts["intervals"].get_segments()]
        close([segment[:, 0] for segment in segments], EXPECTED["ratio_study_limits"])
        points = np.asarray(parts["points"].get_offsets())
        close(points[:, 0], fixture("ratios.csv")["Estimate"])
        sizes = parts["points"].get_sizes()
        weights = np.asarray(EXPECTED["ratios"]["Weight (%)"])
        close(sizes / sizes.max(), weights / weights.max(), rtol=1e-10)
        labels = [label.get_text() for label in axes.get_yticklabels()]
        self.assertEqual(labels[:5], ["Cohort $", "Cohort B", "Cohort C", "Cohort B", "Cohort D"])
        self.assertEqual(labels[5:], ["Pooled · Random effects", "Prediction interval"])
        self.assertFalse(any(label.get_parse_math() for label in axes.get_yticklabels()))
        self.assertEqual(axes._tramastat_numeric_axes, ("x",))

    def test_difference_uses_a_linear_axis_and_zero_and_no_prediction_row_without_request(self):
        result = run(fixture("differences.csv"), **{"Show graph": True})
        axes = result.figure.axes[0]
        self.assertEqual(axes.get_xscale(), "linear")
        self.assertIsNone(axes._tramastat_meta["prediction"])
        close(axes._tramastat_meta["reference"].get_xdata(), [0, 0])
        self.assertEqual([label.get_text() for label in axes.get_yticklabels()][-1], "Pooled · Common effect")

    def test_vector_exports_keep_ids_and_literal_labels(self):
        figure = self.figure().figure
        buffer = BytesIO()
        figure.savefig(buffer, format="svg")
        svg = buffer.getvalue().decode("utf-8")
        for gid in (meta.DIAMOND_GID, meta.REFERENCE_GID, meta.PREDICTION_GID, meta.INTERVALS_GID, meta.POINTS_GID):
            self.assertIn(f'id="{gid}', svg)
        self.assertNotIn("<image", svg)
        self.assertIn("Cohort $", svg)
        for extension, magic in (("pdf", b"%PDF"), ("png", b"\x89PNG")):
            buffer = BytesIO()
            figure.savefig(buffer, format=extension)
            self.assertTrue(buffer.getvalue().startswith(magic))

    def test_native_style_changes_keep_the_geometry(self):
        result = self.figure()
        axes = result.figure.axes[0]
        before = np.asarray(axes._tramastat_meta["diamond"].get_xy()).copy()
        apply_style(result.figure, {"title": "Pooled $ratio$", "accent": "#9b4174", "grid": True})
        self.assertEqual(axes.get_title(), "Pooled $ratio$")
        close(np.asarray(axes._tramastat_meta["diamond"].get_xy()), before)
        self.assertFalse(any(label.get_parse_math() for label in axes.get_yticklabels()))
        buffer = BytesIO()
        result.figure.savefig(buffer, format="svg")
        self.assertIn(b"meta-pooled-diamond", buffer.getvalue())

    def test_two_hundred_studies_fit_on_a_readable_figure(self):
        rng = np.random.default_rng(3)
        frame = pd.DataFrame({"Estimate": rng.normal(size=200), "SE": rng.uniform(.1, 1, 200)})
        figure = analyse(METHOD, frame, {"Estimate": "Estimate", "Standard error": "SE"}).figure
        self.assertLessEqual(figure.get_size_inches()[1], 40)
        self.assertEqual(len(figure.axes[0].get_yticklabels()), 201)


class CatalogTests(unittest.TestCase):
    def test_method_is_listed_under_data_exploration_with_its_options(self):
        self.assertIn(METHOD, GROUPS["Data Exploration and Summary"])
        self.assertNotIn(METHOD, GROUPS["Graphing"])
        self.assertNotIn(METHOD, GRAPH_METHODS, "the Graphs entry follows Show graph")
        self.assertEqual(list(METHODS[METHOD]), ["Study", "Estimate", "Standard error", "Measure", "Pooling model",
                                                 "Random interval", "Confidence level (%)", "Prediction interval",
                                                 "Leave one out", "Show graph"])
        self.assertIn("Forest plot", GROUPS["Graphing"])

    def test_every_key_has_both_languages_and_matching_placeholders(self):
        keys = [key for key in CATALOGS["en"] if key.startswith("meta.")]
        self.assertGreater(len(keys), 40)
        for key in keys:
            self.assertTrue(CATALOGS["it"].get(key), key)
            if key.startswith("meta.error."):
                self.assertNotEqual(CATALOGS["it"][key], CATALOGS["en"][key], key)
            self.assertEqual(placeholders(CATALOGS["en"][key]), placeholders(CATALOGS["it"][key]), key)
        self.assertEqual(translate("it", "interface.Meta-analysis of effect estimates"), "Meta-analisi delle stime")

    def test_every_engine_message_has_a_catalog_template(self):
        import ast
        import re
        source = Path(meta.__file__).read_text(encoding="utf-8")
        patterns = []
        for key, text in CATALOGS["en"].items():
            if key.startswith(meta.ERROR_PREFIX):
                parts = re.split(r"\{[a-z_]+\}", text)
                patterns.append(re.compile(".+?".join(re.escape(part) for part in parts) + r"\Z", re.DOTALL))
        tree = ast.parse(source)
        messages = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "FieldError":
                message = node.args[1]
                text = "".join(value.value if isinstance(value, ast.Constant) else "X"
                               for value in (message.values if isinstance(message, ast.JoinedStr) else [message]))
                messages.append(text)
        self.assertGreater(len(messages), 15)
        for text in messages:
            sample = text.replace("{name}", "Estimate").replace("{field}", "Estimate")
            self.assertTrue(any(pattern.match(sample) for pattern in patterns), text)


class RecipeTests(unittest.TestCase):
    def test_a_saved_project_keeps_the_recipe_and_the_legacy_forest_plot(self):
        frame = fixture("ratios.csv")
        recipe = {"Study": "Study", "Estimate": "Estimate", "Standard error": "SE", "Measure": "Ratio",
                  "Pooling model": RANDOM, "Random interval": "Normal", "Confidence level (%)": 90.0,
                  "Prediction interval": True, "Leave one out": True, "Show graph": True}
        legacy = frame.assign(Lower=frame["Estimate"] * .8, Upper=frame["Estimate"] * 1.1)
        forest = {"Input": "One study per row", "Study": "Study", "Estimate": "Estimate", "Lower limit": "Lower",
                  "Upper limit": "Upper", "Measure": "Ratio", "Scale": "Log10", "Reference": 1.0}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "meta.alab"
            save_project(path, {"Ratios": Dataset(legacy, analyses=[(METHOD, recipe), ("Forest plot", forest)])})
            [(name, dataset)] = load_workspace(path)[0].items()
        self.assertEqual(name, "Ratios")
        self.assertEqual(dataset.analyses, [(METHOD, recipe), ("Forest plot", forest)])
        result = analyse(METHOD, dataset.frame(), recipe)
        self.assertEqual(list(result.tables), ["Studies", "Pooled", "Heterogeneity", "Leave one out"])
        old = analyse("Forest plot", dataset.frame(), forest)
        self.assertEqual(list(old.tables), ["Forest values", "Summary"])
        self.assertFalse(any(patch.get_gid() == meta.DIAMOND_GID for patch in old.figure.axes[0].patches))


if __name__ == "__main__":
    unittest.main()
