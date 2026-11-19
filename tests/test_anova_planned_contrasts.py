"""Planned contrasts of the Multifactor ANOVA (0.96): calculation, reuse of the fit, limits, legacy recipes."""
from fractions import Fraction
import math
import unittest
from unittest import mock

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from scipy import stats

from analisi import anova_planned_contrasts as planned
from analisi import stats as engine
from analisi.field_error import FieldError
from analisi.workbench import METHODS, analyse

METHOD = "Multifactor ANOVA"
LEVELS = [("Control $", "A"), ("Control $", "B |"), ("Control $", "C"),
          ("Treated", "A"), ("Treated", "B |"), ("Treated", "C")]
BALANCED = [[1, 2, 3], [3, 4, 5], [5, 6, 7], [2, 3, 4], [6, 7, 8], [10, 11, 12]]
UNBALANCED = [[1, 3], [2, 4, 6], [5, 5, 7, 7], [2, 3, 4], [5, 6, 7, 8, 9], [10, 12]]
THIRD = 1 / 3
CONTRASTS = [
    {"name": "Treatment − Control $", "weights": [
        {"levels": ["Control $", "A"], "coefficient": -THIRD}, {"levels": ["Control $", "B |"], "coefficient": -THIRD},
        {"levels": ["Control $", "C"], "coefficient": -THIRD}, {"levels": ["Treated", "A"], "coefficient": THIRD},
        {"levels": ["Treated", "B |"], "coefficient": THIRD}, {"levels": ["Treated", "C"], "coefficient": THIRD}]},
    {"name": "Difference of differences", "weights": [
        {"levels": ["Control $", "A"], "coefficient": 1}, {"levels": ["Control $", "C"], "coefficient": -1},
        {"levels": ["Treated", "A"], "coefficient": -1}, {"levels": ["Treated", "C"], "coefficient": 1}]},
    {"name": "Control curvature", "weights": [
        {"levels": ["Control $", "A"], "coefficient": 1}, {"levels": ["Control $", "B |"], "coefficient": -2},
        {"levels": ["Control $", "C"], "coefficient": 1}]},
]


def frame_of(responses, levels=LEVELS):
    return pd.DataFrame([(*cell, value) for cell, values in zip(levels, responses) for value in values],
                        columns=["Treatment", "Visit", "Score"])


def recipe(**extra):
    return {"Response": "Score", "Factors": ["Treatment", "Visit"], "Interaction order": 2,
            planned.FACTORS: ["Treatment", "Visit"], planned.CONTRASTS: CONTRASTS, **extra}


def cell_means_oracle(responses, contrasts, alpha=.05):
    """Saturated cell-means model with exact fractions: estimate and variance of each contrast."""
    means = [Fraction(sum(values), len(values)) for values in responses]
    df = sum(len(values) - 1 for values in responses)
    mse = sum((v - m) ** 2 for values, m in zip(responses, means) for v in values) / df
    index = {cell: i for i, cell in enumerate(LEVELS)}
    rows = []
    for contrast in contrasts:
        weights = [(index[tuple(w["levels"])], Fraction(w["coefficient"]).limit_denominator(1000))
                   for w in contrast["weights"]]
        estimate = sum(c * means[i] for i, c in weights)
        variance = mse * sum(c * c / len(responses[i]) for i, c in weights)
        se = math.sqrt(variance)
        t = float(estimate) / se
        half = stats.t.ppf(1 - alpha / 2, df) * se
        rows.append({"Estimate": float(estimate), "SE": se, "df": df, "t": t,
                     "p": 2 * stats.t.sf(abs(t), df), "CI low": float(estimate) - half,
                     "CI high": float(estimate) + half})
    return rows


class CalculationTests(unittest.TestCase):
    def check_against_oracle(self, responses):
        frame = frame_of(responses)
        sheet = analyse(METHOD, frame, recipe()).tables[planned.SHEET]
        self.assertEqual(sheet.columns.tolist(), list(planned.COLUMNS))
        self.assertEqual(sheet["Contrast"].tolist(), [c["name"] for c in CONTRASTS])
        for actual, wanted in zip(sheet.to_dict("records"), cell_means_oracle(responses, CONTRASTS)):
            self.assertEqual(actual["Status"], "OK")
            for field, value in wanted.items():
                self.assertAlmostEqual(actual[field], value, delta=1e-9 * max(1, abs(value)), msg=field)

    def test_balanced_cells_match_the_cell_means_oracle(self):
        self.check_against_oracle(BALANCED)

    def test_unbalanced_cells_use_unweighted_marginal_means(self):
        self.check_against_oracle(UNBALANCED)
        frame = frame_of(UNBALANCED)
        options = recipe(**{planned.FACTORS: ["Treatment"], planned.CONTRASTS: [
            {"name": "T − C", "weights": [{"levels": ["Treated"], "coefficient": 1},
                                          {"levels": ["Control $"], "coefficient": -1}]}]})
        row = analyse(METHOD, frame, options).tables[planned.SHEET].iloc[0]
        cell = frame.groupby(["Treatment", "Visit"])["Score"].mean()
        marginal = cell["Treated"].mean() - cell["Control $"].mean()
        weighted = (frame[frame.Treatment == "Treated"].Score.mean()
                    - frame[frame.Treatment == "Control $"].Score.mean())
        self.assertAlmostEqual(row["Estimate"], marginal, places=12)
        self.assertGreater(abs(row["Estimate"] - weighted), 0.05)

    def test_zero_estimate_with_positive_se_has_p_one(self):
        row = analyse(METHOD, frame_of(BALANCED), recipe()).tables[planned.SHEET].iloc[2]
        self.assertEqual(row["Status"], "OK")
        self.assertAlmostEqual(row["Estimate"], 0, places=12)
        self.assertGreater(row["SE"], 0)
        self.assertAlmostEqual(row["p"], 1, places=12)
        self.assertLess(row["CI low"], 0)
        self.assertGreater(row["CI high"], 0)

    def test_additive_model_predicts_an_empty_cell(self):
        rng = np.random.default_rng(4)
        levels = [cell for cell in LEVELS if cell != ("Treated", "C")]
        responses = [list(np.round(rng.normal(5 + i, 1, 4), 3)) for i in range(len(levels))]
        frame = frame_of(responses, levels)
        options = recipe(**{"Interaction order": 1, planned.CONTRASTS: [
            {"name": "Treated C − Treated A", "weights": [{"levels": ["Treated", "C"], "coefficient": 1},
                                                          {"levels": ["Treated", "A"], "coefficient": -1}]},
            CONTRASTS[1]]})
        sheet = analyse(METHOD, frame, options).tables[planned.SHEET]
        # Independent additive fit: treatment-coded least squares, then the two predictions.
        x = np.column_stack([np.ones(len(frame)), frame.Treatment == "Treated",
                             frame.Visit == "B |", frame.Visit == "C"]).astype(float)
        beta, *_ = np.linalg.lstsq(x, frame.Score.to_numpy(), rcond=None)
        self.assertAlmostEqual(sheet.iloc[0]["Estimate"], beta[3], places=10)
        self.assertEqual(sheet.iloc[0]["Status"], "OK")
        # The interaction contrast vanishes in an additive model: no inference, nothing invented.
        row = sheet.iloc[1]
        self.assertEqual(row["Status"], planned.NO_INFERENCE)
        self.assertEqual(row["Estimate"], 0.0)
        for field in ("SE", "df", "t", "p", "Adjusted p", "CI low", "CI high"):
            self.assertTrue(np.isnan(row[field]), field)
        self.assertFalse(np.isnan(sheet.iloc[0]["Adjusted p"]))
        self.assertEqual(sheet.iloc[0]["Adjusted p"], sheet.iloc[0]["p"])  # one finite p: Holm leaves it

    def test_selected_terms_average_over_the_factor_left_out(self):
        rng = np.random.default_rng(9)
        frame = frame_of(BALANCED).assign(Site=list("xyz") * 6)
        frame["Score"] = frame["Score"] + rng.normal(0, .3, len(frame))
        options = {"Response": "Score", "Factors": ["Treatment", "Visit", "Site"],
                   "Term selection": "Selected terms", "Model terms": [["Treatment"], ["Visit"]],
                   planned.FACTORS: ["Visit"], planned.CONTRASTS: [
                       {"name": "C − A", "weights": [{"levels": ["C"], "coefficient": 1},
                                                    {"levels": ["A"], "coefficient": -1}]}]}
        row = analyse(METHOD, frame, options).tables[planned.SHEET].iloc[0]
        x = np.column_stack([np.ones(len(frame)), frame.Treatment == "Treated",
                             frame.Visit == "B |", frame.Visit == "C"]).astype(float)
        beta, rss, *_ = np.linalg.lstsq(x, frame.Score.to_numpy(), rcond=None)
        self.assertAlmostEqual(row["Estimate"], beta[3], places=10)
        self.assertEqual(row["df"], len(frame) - 4)
        outside = {**options, planned.FACTORS: ["Site"], planned.CONTRASTS: [
            {"name": "x − y", "weights": [{"levels": ["x"], "coefficient": 1}, {"levels": ["y"], "coefficient": -1}]}]}
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, outside)
        self.assertEqual(raised.exception.field, planned.FACTORS)

    def test_the_three_sums_of_squares_share_the_contrasts(self):
        frame = frame_of(UNBALANCED)
        sheets = {kind: analyse(METHOD, frame, recipe(**{"Sums of squares": kind, planned.CORRECTION: "Bonferroni"}))
                  for kind in ("Type I", "Type II", "Type III")}
        for kind in ("Type I", "Type II"):
            assert_frame_equal(sheets[kind].tables[planned.SHEET], sheets["Type III"].tables[planned.SHEET])
            assert_frame_equal(sheets[kind].tables[planned.WEIGHTS_SHEET],
                               sheets["Type III"].tables[planned.WEIGHTS_SHEET])
        self.assertFalse(sheets["Type I"].tables["ANOVA (type I)"].equals(
            sheets["Type III"].tables["ANOVA (type III)"]))

    def test_corrections_and_alpha(self):
        frame = frame_of(UNBALANCED)
        raw = analyse(METHOD, frame, recipe(**{planned.CORRECTION: "None"})).tables[planned.SHEET]
        p = raw["p"].to_numpy()
        np.testing.assert_allclose(raw["Adjusted p"], p)
        bonferroni = analyse(METHOD, frame, recipe(**{planned.CORRECTION: "Bonferroni"})).tables[planned.SHEET]
        np.testing.assert_allclose(bonferroni["Adjusted p"], np.minimum(1, 3 * p))
        holm = analyse(METHOD, frame, recipe()).tables[planned.SHEET]
        order = np.argsort(p)
        expected = np.maximum.accumulate(np.minimum(1, (3 - np.arange(3)) * p[order]))
        np.testing.assert_allclose(holm["Adjusted p"].to_numpy()[order], expected)
        wide = analyse(METHOD, frame, recipe(**{planned.ALPHA: .2})).tables[planned.SHEET]
        np.testing.assert_allclose(wide["Estimate"], holm["Estimate"])
        self.assertTrue((wide["CI high"] - wide["CI low"] < holm["CI high"] - holm["CI low"]).all())

    def test_small_alpha_still_gives_finite_confidence_limits(self):
        result = analyse(METHOD, frame_of(UNBALANCED), recipe(**{planned.ALPHA: 1e-20}))
        sheet = result.tables[planned.SHEET]
        self.assertTrue(np.isfinite(sheet[["CI low", "CI high"]]).all().all())
        self.assertTrue((sheet["CI low"] < sheet["Estimate"]).all())
        self.assertTrue((sheet["Estimate"] < sheet["CI high"]).all())

    def test_scaled_weights_rescale_the_interval_and_preserve_the_test(self):
        x = np.array([[1, -1], [1, -1], [1, 1], [1, 1]])
        beta = np.array([3., 2.])
        scales = np.array([1., 1e200, 1e-200])
        rows = scales[:, None] * np.array([[0., 2.]])
        plain, *scaled = planned.inference(rows, x, beta, 2., 2, .05, 2 * scales)
        for factor, result in zip(scales[1:], scaled):
            self.assertEqual(result["Status"], "OK")
            for field in ("Estimate", "SE", "CI low", "CI high"):
                self.assertAlmostEqual(result[field] / factor, plain[field])
            for field in ("t", "p"):
                self.assertAlmostEqual(result[field], plain[field])

    def test_holm_keeps_recipe_order_with_ties(self):
        adjusted = planned.adjust([.02, .01, .02, np.nan, .04], "Holm")
        np.testing.assert_allclose(adjusted[:3], [.06, .04, .06])
        self.assertTrue(np.isnan(adjusted[3]))
        self.assertAlmostEqual(adjusted[4], .06)

    def test_not_estimable_rows_get_no_inference(self):
        x = np.array([[1, 1, 0], [1, 1, 0], [1, 0, 1], [1, 0, 1.]])  # column 0 = column 1 + column 2
        beta = np.array([1, 2, 3.])
        rows = np.array([[0, 1, 0.], [0, 1, -1.]])
        first, second = planned.inference(rows, x, beta, 2.0, 2, .05, [1.0, 2.0])  # MSE 1
        self.assertEqual(first["Status"], planned.NOT_ESTIMABLE)
        self.assertTrue(np.isnan(first["Estimate"]) and np.isnan(first["p"]))
        self.assertEqual(second["Status"], "OK")
        self.assertAlmostEqual(second["SE"], 1.0)

    def test_variance_is_stable_for_a_large_offset(self):
        frame = frame_of(BALANCED)
        shifted = frame.assign(Score=frame.Score + 1e9)
        a = analyse(METHOD, frame, recipe()).tables[planned.SHEET]
        b = analyse(METHOD, shifted, recipe()).tables[planned.SHEET]
        np.testing.assert_allclose(b["SE"], a["SE"], rtol=1e-6)
        np.testing.assert_allclose(b["Estimate"], a["Estimate"], atol=1e-5)


class LiteralTextTests(unittest.TestCase):
    def test_names_and_levels_stay_literal(self):
        frame = frame_of(BALANCED).rename(columns={"Treatment": "Contrast", "Visit": "Coefficient"})
        options = {"Response": "Score", "Factors": ["Contrast", "Coefficient"], "Interaction order": 2,
                   planned.FACTORS: ["Coefficient", "Contrast"], planned.CONTRASTS: [
                       {"name": "  <b>&amp; | : \" é  ", "weights": [
                           {"levels": ["B |", "Control $"], "coefficient": 2.5},
                           {"levels": ["A", "Treated"], "coefficient": -2.5}]}]}
        result = analyse(METHOD, frame, options).tables
        weights = result[planned.WEIGHTS_SHEET]
        self.assertEqual(weights.columns.tolist(), ["Contrast", "Coefficient (factor)", "Contrast (factor)",
                                                    "Coefficient"])
        self.assertEqual(list(weights.itertuples(index=False, name=None)),
                         [("  <b>&amp; | : \" é  ", "B |", "Control $", 2.5),
                          ("  <b>&amp; | : \" é  ", "A", "Treated", -2.5)])
        self.assertEqual(result[planned.SHEET]["Contrast"].tolist(), ["  <b>&amp; | : \" é  "])

    def test_colliding_categories_are_a_field_error_only_with_contrasts(self):
        frame = frame_of(BALANCED)
        frame["Visit"] = frame["Visit"].astype(object)
        frame.loc[frame.Visit == "A", "Visit"] = 1
        frame.loc[frame.index[3:6], "Visit"] = "1"
        legacy = {"Response": "Score", "Factors": ["Treatment", "Visit"], "Interaction order": 1}
        analyse(METHOD, frame, legacy)  # the legacy path keeps its behaviour
        options = {**legacy, planned.FACTORS: ["Treatment"], planned.CONTRASTS: [
            {"name": "T − C", "weights": [{"levels": ["Treated"], "coefficient": 1},
                                          {"levels": ["Control $"], "coefficient": -1}]}]}
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, options)
        self.assertEqual(raised.exception.field, planned.FACTORS)
        self.assertIn("“1”", str(raised.exception))

    def test_numeric_factor_levels_are_their_model_text(self):
        frame = frame_of(BALANCED)
        frame["Visit"] = frame["Visit"].map({"A": 1.0, "B |": 2.0, "C": 3.0})
        options = recipe(**{planned.FACTORS: ["Visit"], planned.CONTRASTS: [
            {"name": "3 − 1", "weights": [{"levels": ["3.0"], "coefficient": 1}, {"levels": ["1.0"], "coefficient": -1}]}]})
        self.assertEqual(analyse(METHOD, frame, options).tables[planned.SHEET].iloc[0]["Status"], "OK")


class ValidationTests(unittest.TestCase):
    def error(self, frame=None, **changes):
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame_of(BALANCED) if frame is None else frame, recipe(**changes))
        return raised.exception

    def contrasts(self, *weights, name="c"):
        return [{"name": name, "weights": [{"levels": list(cell), "coefficient": c} for cell, c in weights]}]

    def test_weight_problems_name_the_contrast_and_row(self):
        cases = [
            (self.contrasts((LEVELS[0], 1), (LEVELS[1], -1), (LEVELS[2], 1)), "sum", None),
            (self.contrasts((LEVELS[0], 1), (LEVELS[0], -1)), "levels", 1),
            (self.contrasts((LEVELS[0], 1), (LEVELS[1], float("nan"))), "coefficient", 1),
            (self.contrasts((LEVELS[0], 1), (LEVELS[1], float("inf"))), "coefficient", 1),
            (self.contrasts((LEVELS[0], 1), (LEVELS[1], 10**400)), "coefficient", 1),
            (self.contrasts((LEVELS[0], True), (LEVELS[1], -1)), "coefficient", 0),
            (self.contrasts((LEVELS[0], "1"), (LEVELS[1], -1)), "coefficient", 0),
            (self.contrasts((LEVELS[0], 1), (LEVELS[1], 0), (LEVELS[2], -1)), "coefficient", 1),
            (self.contrasts((LEVELS[0], 1e308), (LEVELS[1], 1e308), (LEVELS[2], -1e308), (LEVELS[3], -1e308)),
             "sum", None),
            (self.contrasts((LEVELS[0], 1), (("Control $",), -1)), "levels", 1),
            (self.contrasts((LEVELS[0], 1), (("Missing", "A"), -1)), "levels", 1),
            (self.contrasts((LEVELS[0], 1)), "weights", None),
        ]
        for contrasts, part, row in cases:
            with self.subTest(contrasts=contrasts):
                error = self.error(**{planned.CONTRASTS: contrasts})
                self.assertEqual(error.field, planned.CONTRASTS)
                self.assertEqual((error.contrast, error.weight, error.part), (0, row, part))

    def test_sum_tolerance_is_relative(self):
        tiny = 1e-13
        ok = self.contrasts((LEVELS[0], 1 + tiny), (LEVELS[1], -1))
        analyse(METHOD, frame_of(BALANCED), recipe(**{planned.CONTRASTS: ok}))
        bad = self.contrasts((LEVELS[0], 1 + 1e-9), (LEVELS[1], -1))
        self.assertEqual(self.error(**{planned.CONTRASTS: bad}).part, "sum")

    def test_list_limits(self):
        pair = [{"levels": list(LEVELS[0]), "coefficient": 1}, {"levels": list(LEVELS[1]), "coefficient": -1}]
        many = [{"name": f"c{i}", "weights": pair} for i in range(33)]
        self.assertEqual(self.error(**{planned.CONTRASTS: many}).field, planned.CONTRASTS)
        for name, part in (("", "name"), ("   ", "name"), ("x" * 121, "name"), (3, "name")):
            error = self.error(**{planned.CONTRASTS: [{"name": name, "weights": pair}]})
            self.assertEqual((error.field, error.part), (planned.CONTRASTS, part))
        twice = [{"name": "same", "weights": pair}, {"name": "same", "weights": pair}]
        self.assertEqual((self.error(**{planned.CONTRASTS: twice}).contrast), 1)
        analyse(METHOD, frame_of(BALANCED), recipe(**{planned.CONTRASTS: [{"name": "x" * 120, "weights": pair}]}))
        for value in ("text", {"name": "c"}, [["c"]]):
            self.assertEqual(self.error(**{planned.CONTRASTS: value}).field, planned.CONTRASTS)

    def test_more_than_256_weights(self):
        levels = [f"L{i:03d}" for i in range(260)]
        frame = pd.DataFrame({"Score": np.arange(520.) % 7, "Group": levels * 2})
        weights = [{"levels": [level], "coefficient": 1 if i % 2 else -1} for i, level in enumerate(levels[:258])]
        with self.assertRaises(FieldError) as raised:
            analyse(METHOD, frame, {"Response": "Score", "Factors": ["Group"], "Interaction order": 1,
                                    planned.FACTORS: ["Group"],
                                    planned.CONTRASTS: [{"name": "many", "weights": weights}]})
        self.assertEqual(raised.exception.part, "weights")

    def test_grid_budget_is_checked_before_the_grid(self):
        a = [f"a{i:02d}" for i in range(65)]
        rows = [(x, y) for x in a for y in a]
        frame = pd.DataFrame(rows + rows[:200], columns=["A", "B"]).assign(Score=lambda f: np.arange(len(f)) % 11)
        options = {"Response": "Score", "Factors": ["A", "B"], "Interaction order": 1, planned.FACTORS: ["A"],
                   planned.CONTRASTS: [{"name": "a", "weights": [{"levels": ["a00"], "coefficient": 1},
                                                                {"levels": ["a01"], "coefficient": -1}]}]}
        with mock.patch.object(planned, "marginal_rows", side_effect=AssertionError("grid allocated")):
            with self.assertRaises(FieldError) as raised:
                analyse(METHOD, frame, options)
        self.assertEqual(raised.exception.field, planned.FACTORS)
        self.assertIn("4225", str(raised.exception))

    def test_factor_correction_and_alpha_fields(self):
        for factors in (None, [], ["Treatment", "Treatment"], ["Nope"], "Treatment"):
            self.assertEqual(self.error(**{planned.FACTORS: factors}).field, planned.FACTORS)
        self.assertEqual(self.error(**{planned.CORRECTION: "Tukey"}).field, planned.CORRECTION)
        for value in (0, 1, -.1, float("nan"), float("inf"), 10**400, "0.05", True):
            self.assertEqual(self.error(**{planned.ALPHA: value}).field, planned.ALPHA)

    def test_level_absent_from_the_data_after_an_exclusion(self):
        frame = frame_of(BALANCED)
        frame = frame[frame.Visit != "C"]  # the level is gone, as after excluding its rows
        error = self.error(frame=frame)
        self.assertEqual((error.field, error.contrast, error.weight, error.part), (planned.CONTRASTS, 0, 2, "levels"))
        self.assertIn("“C”", str(error))


class CompatibilityTests(unittest.TestCase):
    def test_methods_declare_the_keys(self):
        fields = METHODS[METHOD]
        self.assertEqual(fields[planned.CORRECTION], ("Holm", "Bonferroni", "None"))
        self.assertEqual(fields[planned.ALPHA], .05)
        self.assertIn(planned.FACTORS, fields)
        self.assertIn(planned.CONTRASTS, fields)

    def test_absent_or_empty_contrasts_change_nothing(self):
        frame = frame_of(UNBALANCED)
        legacy = {"Response": "Score", "Factors": ["Treatment", "Visit"], "Interaction order": 2,
                  "Compare marginal means by": "Treatment", "Effect sizes": True,
                  "ANOVA residual diagnostics": True, "ANOVA diagnostic graph": "Residuals vs fitted"}
        base = analyse(METHOD, frame, legacy)
        for extra in ({planned.CONTRASTS: []}, {planned.CONTRASTS: None},
                      {planned.CONTRASTS: [], planned.FACTORS: ["Nope"], planned.CORRECTION: "x", planned.ALPHA: 7}):
            other = analyse(METHOD, frame, {**legacy, **extra})
            self.assertEqual(list(other.tables), list(base.tables))
            for name in base.tables:
                assert_frame_equal(other.tables[name], base.tables[name], check_exact=True)

    def test_one_fit_with_contrasts_and_diagnostics(self):
        frame = frame_of(UNBALANCED)
        options = recipe(**{"ANOVA residual diagnostics": True, "ANOVA diagnostic graph": "Residuals vs fitted", "Effect sizes": True})
        with mock.patch.object(engine, "_anova_model", wraps=engine._anova_model) as fit, \
                mock.patch.object(np.linalg, "lstsq", wraps=np.linalg.lstsq) as solve:
            result = analyse(METHOD, frame, options)
        self.assertEqual(fit.call_count, 1)
        self.assertEqual(solve.call_count, 1 + 3)  # the fit, then one reduced fit per Type III term
        self.assertIn(planned.SHEET, result.tables)
        self.assertIsNotNone(result.figure)

    def test_post_hoc_comparisons_stay_in_the_same_run(self):
        frame = frame_of(UNBALANCED)
        options = recipe(**{"Compare marginal means by": "Visit", "Correction": "Tukey"})
        result = analyse(METHOD, frame, options)
        self.assertIn("Multiple comparisons", result.tables)
        self.assertIn(planned.SHEET, result.tables)
        self.assertIn(planned.WEIGHTS_SHEET, result.tables)


if __name__ == "__main__":
    unittest.main()


class TranslationTests(unittest.TestCase):
    def test_every_error_has_its_english_and_italian_text(self):
        from analisi import i18n
        for key, text in planned.ERRORS.items():
            entry = f"anova.contrasts.error.{key}"
            self.assertEqual(i18n._EN.get(entry), text, key)
            self.assertTrue(i18n._IT.get(entry), key)
            self.assertNotEqual(i18n._IT[entry], text, key)

    def test_italian_message_uses_the_decimal_comma_for_the_sum(self):
        from analisi.i18n import active_language, set_language
        previous = active_language()
        try:
            set_language("it")
            with self.assertRaises(planned.ContrastError) as raised:
                planned.check_contrasts({planned.CONTRASTS: [
                    {"name": "c", "weights": [{"levels": ["a"], "coefficient": 1},
                                              {"levels": ["b"], "coefficient": -0.5}]}]}, ["F"])
            self.assertIn("0,5", planned.localized(raised.exception))
        finally:
            set_language(previous)
