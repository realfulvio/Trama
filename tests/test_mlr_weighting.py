"""Fixed Gaussian observation weights of Multiple regression: contract, extremes, errors, legacy and dialog logic."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import statsmodels.api as sm
from numpy.testing import assert_allclose
from scipy import stats
from statsmodels.stats.outliers_influence import OLSInfluence
from statsmodels.regression import linear_model

from analisi import additional, i18n, mlr_weighting as mw, models, ols_diagnostics
from analisi.processing import FieldError
from analisi.workbench import analyse, METHODS

DATA = Path(__file__).resolve().parent / "data" / "mlr_weighting"
EXPECTED = json.loads((DATA / "expected.json").read_text())
PROFILES = json.loads((DATA / "profiles.json").read_text())
METHOD = "Multiple regression"
RTOL, ATOL = 2e-9, 2e-10
MODES = ["Weight column", "Inverse variance (SD column)", "1/abs(Y)", "1/Y²"]


def fixture(name):
    return pd.read_csv(DATA / name, index_col="Source row")


def options(mode="Weight column", **extra):
    base = {"Family": "Linear", "Response": "Y", "Predictors": ["X1", "X2"], "Categorical predictors": [],
            "Gaussian weighting": mode, "Gaussian weight column": "W", "Gaussian SD column": "SD",
            "Linear diagnostics": True, "Linear profiles": PROFILES, "Weighted prediction intervals": True}
    base.update(extra)
    return base


def run(frame=None, **extra):
    mode = extra.pop("mode", "Weight column")
    return analyse(METHOD, fixture("numeric.csv") if frame is None else frame, options(mode, **extra))


def close(actual, expected, rtol=RTOL, atol=ATOL):
    assert_allclose(actual, expected, rtol=rtol, atol=atol, equal_nan=True)


def reference(frame, column, x=("X1", "X2")):
    """Independent weighted least squares on sqrt(weight)·(D, y), complete rows only."""
    rows = frame.dropna(subset=[*x, "Y"])
    if column == "SD":
        rows = rows.dropna(subset=["SD"])
        w = 1.0 / rows["SD"].to_numpy(float) ** 2
    else:
        rows = rows.dropna(subset=[column])
        w = rows[column].to_numpy(float)
    wn = w / w.max()
    d = np.column_stack([np.ones(len(rows)), *[rows[name].to_numpy(float) for name in x]])
    y = rows["Y"].to_numpy(float)
    root = np.sqrt(wn)
    beta = np.linalg.lstsq(root[:, None] * d, root * y, rcond=None)[0]
    r = y - d @ beta
    df = len(y) - d.shape[1]
    s2 = float((root * r) @ (root * r)) / df
    q, _ = np.linalg.qr(root[:, None] * d)
    return dict(beta=beta, s2=s2, df=df, wn=wn, h=(q * q).sum(axis=1), r=r, d=d, y=y, rows=rows.index.to_numpy(),
                cov=s2 * np.linalg.inv(d.T @ (wn[:, None] * d)))


class ContractTests(unittest.TestCase):
    def test_four_modes_match_the_frozen_references(self):
        for mode in MODES:
            with self.subTest(mode=mode):
                result, e = run(mode=mode), EXPECTED[mode]
                tables = result.tables
                close(tables["Coefficients"]["Estimate"], e["beta"])
                close(tables["Coefficients"]["SE"], np.sqrt(np.diag(e["covariance"])))
                weights = tables["Linear weights"]
                self.assertEqual(list(weights.columns), ["Source row", "Observed", "Weight", "Normalized weight",
                                                         "Log weight", "Relative log weight"])
                close(weights["Relative log weight"], np.log(e["normalized_weights"]))
                self.assertEqual(weights["Relative log weight"].max(), 0.0)
                self.assertEqual(weights["Source row"].tolist(), e["source_rows"])
                close(weights["Weight"], e["weights"])
                close(weights["Normalized weight"], e["normalized_weights"])
                close(weights["Log weight"], np.log(e["weights"]))
                self.assertAlmostEqual(weights["Normalized weight"].max(), 1.0, places=15)
                fitted = tables["Fitted values"]
                close(fitted["Fitted"], e["fitted"])
                close(fitted["Residual"], e["residual"])
                d = tables["Linear diagnostics"]
                close(d["Leverage"], e["leverage"])
                close(d["Internally studentized residual"], e["student"])
                close(d["Cook's distance"], e["cook"])
                close(d["PRESS residual"], e["press_residual"])
                summary = tables["Linear model diagnostics"]["Value"]
                close(summary["PRESS"], e["PRESS"])
                close(summary["Weighted PRESS"], e["weighted_PRESS"])
                close(summary["Residual variance"], e["variance"])
                self.assertEqual(summary["Residual df"], e["df"])
                pred = tables["Linear predictions"]
                close(pred[["Prediction", "Mean CI low", "Mean CI high", "Prediction interval low",
                            "Prediction interval high"]], e["profiles"])

    def test_sparse_index_and_the_incomplete_row(self):
        frame = fixture("numeric.csv")
        before = frame.copy()
        result = run(frame)
        self.assertNotIn(77, result.tables["Linear weights"]["Source row"].tolist())
        self.assertEqual(result.tables["Model"].loc["N", "Value"], 10)
        self.assertEqual(result.tables["Model"].loc["Incomplete rows", "Value"], 1)
        # The worksheet is neither mutated nor re-indexed.
        pd.testing.assert_frame_equal(frame, before)

    def test_signed_response_with_a_fractional_power(self):
        frame = fixture("signed.csv")
        w = np.abs(frame.Y.to_numpy(float)) ** -1.3
        d = np.column_stack([np.ones(len(frame)), frame.X1, frame.X2])
        ref = sm.WLS(frame.Y, d, weights=w).fit()
        result = run(frame, mode="1/abs(Y)^K", **{"Weight exponent K": 1.3})
        close(result.tables["Coefficients"]["Estimate"], ref.params)
        close(result.tables["Coefficients"]["SE"], ref.bse)
        close(result.tables["Coefficients"]["p"], ref.pvalues)
        close(result.tables["Linear weights"]["Weight"], w)
        close(result.tables["Linear weights"]["Log weight"], -1.3 * np.log(np.abs(frame.Y)))
        self.assertEqual(result.tables["Model"].loc["Weight exponent K", "Value"], 1.3)

    def test_powers_one_and_two_agree_with_their_named_modes(self):
        frame = fixture("numeric.csv")
        for k, mode in ((1.0, "1/abs(Y)"), (2.0, "1/Y²")):
            a = run(frame, mode="1/abs(Y)^K", **{"Weight exponent K": k}).tables
            b = run(frame, mode=mode).tables
            for name in ("Coefficients", "Linear weights", "Linear diagnostics", "Linear predictions"):
                pd.testing.assert_frame_equal(a[name], b[name], rtol=1e-12, atol=0)

    def test_statsmodels_agrees_with_raw_weights_and_categories(self):
        rng = np.random.default_rng(7)
        n = 40
        frame = pd.DataFrame({"X": rng.normal(size=n), "G": rng.choice(["a", "b", "c"], n),
                              "W": rng.uniform(.2, 9, n)})
        frame["Y"] = 2 + 3 * frame.X + (frame.G == "b") * 1.5 + rng.normal(size=n) / np.sqrt(frame.W)
        frame.index = np.arange(n) * 3 + 2
        opts = {"Family": "Linear", "Response": "Y", "Predictors": ["X", "G"], "Categorical predictors": ["G"],
                "Gaussian weighting": "Weight column", "Gaussian weight column": "W", "Linear diagnostics": True}
        tables = analyse(METHOD, frame, opts).tables
        d = pd.get_dummies(frame.G, drop_first=True).astype(float)
        design = np.column_stack([np.ones(n), frame.X, d])
        ref = sm.WLS(frame.Y, design, weights=frame.W).fit()
        close(tables["Coefficients"]["Estimate"], ref.params)
        close(tables["Coefficients"]["SE"], ref.bse)
        close(tables["Coefficients"][["CI 95% low", "CI 95% high"]], ref.conf_int())
        close(tables["Model"].loc["R²", "Value"], ref.rsquared)
        self.assertEqual(tables["Reference levels"].loc["G", "Reference"], "a")
        influence = OLSInfluence(sm.OLS(ref.model.wendog, ref.model.wexog).fit())   # OLS on sqrt(w)·(D, y)
        close(tables["Linear diagnostics"]["Leverage"], influence.hat_matrix_diag)
        close(tables["Linear diagnostics"]["Cook's distance"], influence.cooks_distance[0])
        close(tables["Linear diagnostics"]["Internally studentized residual"], influence.resid_studentized_internal)
        self.assertEqual(tables["Linear diagnostics"]["Source row"].tolist(), frame.index.tolist())

    def test_log_likelihood_and_aic_use_the_normalized_weights(self):
        frame = fixture("numeric.csv").dropna(subset=["X1"])
        tables = run(frame).tables
        e = reference(frame, "W")
        n = len(e["y"])
        rss = float(e["wn"] @ e["r"] ** 2)
        llf = -n / 2 * np.log(2 * np.pi) - n / 2 * np.log(rss / n) - n / 2 + .5 * np.log(e["wn"]).sum()
        close(tables["Model"].loc["Log likelihood", "Value"], llf)
        close(tables["Model"].loc["AIC", "Value"], 2 * 3 - 2 * llf)
        text = tables["Model"].loc["AIC basis", "Value"]
        self.assertIn("normalized to a maximum of 1", text)
        self.assertIn("Var(y) = sigma² / normalized weight", tables["Model"].loc["Variance units", "Value"])

    def test_sheet_order_and_unit_graph_labels(self):
        result = run(**{"Linear residual plot": "Residuals vs fitted"})
        self.assertEqual(list(result.tables), ["Coefficients", "Model", "Fitted values", "Linear weights",
                                               "Linear diagnostics", "Linear model diagnostics", "Linear predictions"])
        self.assertEqual(result.figure.axes[0].get_ylabel(), "Residual (raw units)")
        absolute = run(**{"Linear residual plot": "Absolute residuals vs fitted"})
        self.assertEqual(absolute.figure.axes[0].get_ylabel(), "Absolute residual (raw units)")


class InvarianceTests(unittest.TestCase):
    def assert_same_fit(self, a, b):
        for name in ("Coefficients", "Linear diagnostics", "Linear predictions"):
            pd.testing.assert_frame_equal(a.tables[name], b.tables[name], rtol=1e-9, atol=1e-12)
        pd.testing.assert_frame_equal(a.tables["Linear weights"][["Source row", "Normalized weight"]],
                                      b.tables["Linear weights"][["Source row", "Normalized weight"]],
                                      rtol=1e-12, atol=0)

    def test_a_common_factor_on_weights_or_sd_changes_nothing(self):
        base = run()
        for factor in (1e150, 1e-150, 1e100):
            frame = fixture("numeric.csv")
            frame["W"] *= factor
            profiles = [dict(p, weight=p["weight"] * factor) for p in PROFILES]
            with self.subTest(column="W", factor=factor):
                scaled = run(frame, **{"Linear profiles": profiles})
                self.assert_same_fit(base, scaled)
                close(scaled.tables["Linear weights"]["Weight"], base.tables["Linear weights"]["Weight"] * factor)
        base = run(mode="Inverse variance (SD column)")
        for factor in (1e150, 1e-150):
            frame = fixture("numeric.csv")
            frame["SD"] *= factor
            profiles = [dict(p, weight=p["weight"] / factor**2) for p in PROFILES]
            with self.subTest(column="SD", factor=factor):
                scaled = run(frame, mode="Inverse variance (SD column)", **{"Linear profiles": profiles})
                self.assert_same_fit(base, scaled)

    def test_unrepresentable_raw_weights_leave_a_blank_and_a_log(self):
        frame = fixture("numeric.csv")
        frame["SD"] = 1e-200 * np.array([1., 2, .5, 1.5, 3, 2, 1, .75, 1.2, 2, 1])
        result = run(frame, mode="Inverse variance (SD column)", **{"Linear profiles": []})
        weights = result.tables["Linear weights"]
        self.assertTrue(weights["Weight"].isna().all())
        self.assertIn("Note", weights.columns)
        self.assertTrue(np.isfinite(weights["Log weight"]).all() and np.isfinite(weights["Normalized weight"]).all())
        self.assertGreater(weights["Normalized weight"].min(), 0)
        self.assertEqual(weights["Normalized weight"].max(), 1.0)
        base = run(mode="Inverse variance (SD column)", **{"Linear profiles": []})
        close(result.tables["Coefficients"]["Estimate"], base.tables["Coefficients"]["Estimate"])
        close(result.tables["Coefficients"]["SE"], base.tables["Coefficients"]["SE"])
        # Raw weights 1/(1e-200)² overflow, but log(w) is 2·200·ln(10) − 2·ln(SD/1e-200).
        close(weights["Log weight"], 2 * 200 * np.log(10) - 2 * np.log(frame["SD"].iloc[:10] / 1e-200))

    def test_identical_tiny_sd_is_not_squared_before_the_log(self):
        frame = fixture("numeric.csv")
        frame["SD"] = 1e-200
        result = run(frame, mode="Inverse variance (SD column)", **{"Linear profiles": []})
        self.assertTrue((result.tables["Linear weights"]["Normalized weight"] == 1.0).all())
        ols = analyse(METHOD, frame, {"Family": "Linear", "Response": "Y", "Predictors": ["X1", "X2"],
                                      "Categorical predictors": []})
        close(result.tables["Coefficients"]["Estimate"], ols.tables["Coefficients"]["Estimate"])
        close(result.tables["Coefficients"]["SE"], ols.tables["Coefficients"]["SE"])

    def test_huge_sd_and_weights_are_also_stable(self):
        frame = fixture("numeric.csv")
        frame["SD"] = 1e160 * frame["SD"]
        result = run(frame, mode="Inverse variance (SD column)", **{"Linear profiles": []})
        base = run(mode="Inverse variance (SD column)", **{"Linear profiles": []})
        close(result.tables["Coefficients"]["Estimate"], base.tables["Coefficients"]["Estimate"])
        self.assertTrue(result.tables["Linear weights"]["Weight"].isna().all())

    def test_ratio_outside_the_double_range_is_refused(self):
        frame = fixture("numeric.csv")
        frame.loc[4, "W"] = 1e-200
        frame.loc[9, "W"] = 1e200
        with self.assertRaises(FieldError) as caught:
            run(frame)
        self.assertEqual(caught.exception.field, "Gaussian weight column")
        self.assertIn("ratio", str(caught.exception))
        # The same ratio stays usable when it is representable.
        frame.loc[4, "W"], frame.loc[9, "W"] = 1e-10, 1e10
        close(run(frame).tables["Coefficients"]["Estimate"], reference(frame, "W")["beta"], rtol=1e-8)
        # A ratio that is representable but leaves the weighted matrix numerically singular is refused as such.
        frame.loc[4, "W"], frame.loc[9, "W"] = 1e-100, 1e100
        with self.assertRaisesRegex(ValueError, "rank deficient after weighting"):
            run(frame)

    def test_change_of_units(self):
        base = run(mode="1/abs(Y)", **{"Linear profiles": []})
        frame = fixture("numeric.csv")
        frame["Y"] *= 1000
        scaled_y = run(frame, mode="1/abs(Y)", **{"Linear profiles": []})
        close(scaled_y.tables["Coefficients"]["Estimate"], base.tables["Coefficients"]["Estimate"] * 1000)
        close(scaled_y.tables["Coefficients"]["SE"], base.tables["Coefficients"]["SE"] * 1000)
        for name in ("Leverage", "Internally studentized residual", "Cook's distance"):
            close(scaled_y.tables["Linear diagnostics"][name], base.tables["Linear diagnostics"][name])
        frame = fixture("numeric.csv")
        frame["X1"] *= 0.001
        scaled_x = run(frame, mode="1/abs(Y)", **{"Linear profiles": []})
        close(scaled_x.tables["Coefficients"]["Estimate"].iloc[1], base.tables["Coefficients"]["Estimate"].iloc[1] * 1000)
        close(scaled_x.tables["Linear diagnostics"]["Cook's distance"], base.tables["Linear diagnostics"]["Cook's distance"])
        close(scaled_x.tables["Linear weights"]["Normalized weight"], base.tables["Linear weights"]["Normalized weight"])


class PrecisionColumnTests(unittest.TestCase):
    def test_invalid_values_name_the_column_and_the_source_row(self):
        for key, mode, column in (("Gaussian weight column", "Weight column", "W"),
                                  ("Gaussian SD column", "Inverse variance (SD column)", "SD")):
            for bad in (0, -1.5, np.inf, "text", "nan?"):
                with self.subTest(column=column, value=bad):
                    frame = fixture("numeric.csv")
                    frame[column] = frame[column].astype(object)
                    frame.loc[21, column] = bad
                    with self.assertRaises(FieldError) as caught:
                        run(frame, mode=mode)
                    self.assertEqual(caught.exception.field, key)
                    self.assertIn("source row 21", str(caught.exception))
                    self.assertIn(f'"{column}"', str(caught.exception))

    def test_a_bad_value_on_an_incomplete_row_is_ignored(self):
        frame = fixture("numeric.csv")          # row 77 already has X1 missing and a zero weight and SD
        for column, mode in (("W", "Weight column"), ("SD", "Inverse variance (SD column)")):
            frame.loc[77, column] = -1
            result = run(frame, mode=mode)
            self.assertEqual(result.tables["Linear weights"]["Source row"].tolist(), EXPECTED[mode]["source_rows"])
        frame["W"] = frame["W"].astype(object)
        frame.loc[77, "W"] = "text"
        frame.loc[77, "X1"] = 1.0
        frame.loc[77, "Y"] = np.nan
        run(frame)

    def test_a_missing_precision_excludes_its_row(self):
        for column, mode in (("W", "Weight column"), ("SD", "Inverse variance (SD column)")):
            frame = fixture("numeric.csv")
            frame.loc[28, column] = np.nan
            result = run(frame, mode=mode)
            self.assertNotIn(28, result.tables["Linear weights"]["Source row"].tolist())
            self.assertEqual(result.tables["Model"].loc["N", "Value"], 9)
            self.assertEqual(result.tables["Model"].loc["Incomplete rows", "Value"], 2)
            ref = reference(frame, column)
            close(result.tables["Coefficients"]["Estimate"], ref["beta"])
            close(result.tables["Linear weights"]["Normalized weight"], ref["wn"])
            self.assertEqual(result.tables["Fitted values"].index.tolist(), ref["rows"].tolist())

    def test_the_column_must_exist_and_differ_from_the_model_columns(self):
        for column, expected in ((None, "Choose a column"), ("", "Choose a column"), ("Nope", "existing column"),
                                 ("Y", "distinct"), ("X1", "distinct")):
            with self.subTest(column=column), self.assertRaises(FieldError) as caught:
                run(**{"Gaussian weight column": column})
            self.assertEqual(caught.exception.field, "Gaussian weight column")
            self.assertIn(expected, str(caught.exception))
        with self.assertRaises(FieldError) as caught:
            run(mode="Inverse variance (SD column)", **{"Gaussian SD column": "X2"})
        self.assertEqual(caught.exception.field, "Gaussian SD column")

    def test_only_the_column_of_the_chosen_mode_is_read(self):
        bad = {"Gaussian SD column": "does not exist", "Weight exponent K": "abc"}
        close(run(**bad).tables["Coefficients"]["Estimate"], EXPECTED["Weight column"]["beta"])
        close(run(mode="Inverse variance (SD column)", **{"Gaussian weight column": "missing",
                                                          "Weight exponent K": "abc"}).tables["Coefficients"]["Estimate"],
              EXPECTED["Inverse variance (SD column)"]["beta"])


class ObservedResponseTests(unittest.TestCase):
    def test_a_zero_response_names_the_weighting_field(self):
        for mode, extra in (("1/abs(Y)", {}), ("1/Y²", {}), ("1/abs(Y)^K", {"Weight exponent K": 0.5}),
                            ("1/abs(Y)^K", {"Weight exponent K": -2})):
            frame = fixture("numeric.csv")
            frame.loc[4, "Y"] = 0
            with self.subTest(mode=mode, extra=extra), self.assertRaises(FieldError) as caught:
                run(frame, mode=mode, **extra)
            self.assertEqual(caught.exception.field, "Gaussian weighting")
            self.assertIn("source row 4", str(caught.exception))

    def test_k_zero_gives_equal_weights_even_with_a_zero_response(self):
        frame = fixture("numeric.csv")
        frame.loc[4, "Y"] = 0
        result = run(frame, mode="1/abs(Y)^K", **{"Weight exponent K": 0, "Linear profiles": []})
        weights = result.tables["Linear weights"]
        self.assertTrue((weights["Weight"] == 1).all() and (weights["Normalized weight"] == 1).all())
        self.assertTrue((weights["Log weight"] == 0).all() and not np.signbit(weights["Log weight"]).any())
        ols = analyse(METHOD, frame, {"Family": "Linear", "Response": "Y", "Predictors": ["X1", "X2"],
                                      "Categorical predictors": []})
        close(result.tables["Coefficients"]["Estimate"], ols.tables["Coefficients"]["Estimate"])
        close(result.tables["Coefficients"]["SE"], ols.tables["Coefficients"]["SE"])

    def test_a_zero_response_on_an_incomplete_row_is_ignored(self):
        frame = fixture("numeric.csv")
        frame.loc[77, "Y"] = 0           # the row has no X1
        run(frame, mode="1/abs(Y)")

    def test_k_accepts_any_finite_number_and_rejects_the_rest(self):
        for k in (-3, -0.25, 0.1, 7, 25, 1e-6, "2.5", 3):
            with self.subTest(k=k):
                frame = fixture("signed.csv")
                run(frame, mode="1/abs(Y)^K", **{"Weight exponent K": k, "Linear profiles": []})
        for bad in ("abc", np.inf, -np.inf, np.nan, True, [1]):
            with self.subTest(bad=bad), self.assertRaises(FieldError) as caught:
                run(fixture("signed.csv"), mode="1/abs(Y)^K", **{"Weight exponent K": bad})
            self.assertEqual(caught.exception.field, "Weight exponent K")
        frame = fixture("signed.csv")
        default = run(frame, mode="1/abs(Y)^K", **{"Linear profiles": []})      # missing K means 1
        again = run(frame, mode="1/abs(Y)", **{"Linear profiles": []})
        close(default.tables["Coefficients"]["Estimate"], again.tables["Coefficients"]["Estimate"])

    def test_an_exponent_that_leaves_the_numeric_range_is_refused(self):
        with self.assertRaises(FieldError) as caught:
            run(fixture("signed.csv"), mode="1/abs(Y)^K", **{"Weight exponent K": 1e308})
        self.assertEqual(caught.exception.field, "Weight exponent K")


class ExtremeExponentTests(unittest.TestCase):
    def frame(self, y):
        return pd.DataFrame({"X1": [0., 1, 2, 3, 4, 5], "X2": [1., 0, 1, 0, 1, 1], "Y": y})

    def test_equal_weights_stay_equal_for_a_huge_k(self):
        # |Y| = 1e100 for every row: K·log|Y| overflows the double range, the differences of the logs do not.
        frame = self.frame([1e100, -1e100, 1e100, -1e100, 1e100, 1e100])
        for k in (1e308, -1e308):
            result = analyse(METHOD, frame, {"Family": "Linear", "Response": "Y", "Predictors": ["X1", "X2"],
                                              "Categorical predictors": [], "Gaussian weighting": "1/abs(Y)^K",
                                              "Weight exponent K": k})
            weights = result.tables["Linear weights"]
            self.assertTrue((weights["Normalized weight"] == 1).all(), k)
            self.assertTrue((weights["Relative log weight"] == 0).all() and not np.signbit(weights["Relative log weight"]).any())
            self.assertTrue(weights["Log weight"].isna().all() and weights["Weight"].isna().all(), k)
            self.assertIn("Relative log weight", weights["Note"].iloc[0])
            self.assertTrue(np.isfinite(result.tables["Coefficients"]["Estimate"]).all())

    def test_a_real_contrast_out_of_range_is_a_named_error_not_a_silent_cut(self):
        frame = self.frame([1., 2, 3, 4, 5, 6])
        with self.assertRaises(FieldError) as caught:
            analyse(METHOD, frame, {"Family": "Linear", "Response": "Y", "Predictors": ["X1", "X2"],
                                    "Categorical predictors": [], "Gaussian weighting": "1/abs(Y)^K",
                                    "Weight exponent K": 1e300})
        self.assertEqual(caught.exception.field, "Weight exponent K")

    def test_relative_logs_match_the_direct_formula_when_the_raw_log_exists(self):
        frame = fixture("signed.csv")
        weights = run(frame, mode="1/abs(Y)^K", **{"Weight exponent K": -0.7, "Linear profiles": []}
                      ).tables["Linear weights"]
        direct = 0.7 * np.log(np.abs(frame.Y))
        close(weights["Log weight"], direct)
        close(weights["Relative log weight"], direct - direct.max())
        close(weights["Normalized weight"], np.exp(direct - direct.max()))

    def test_observed_y_weights_carry_the_conditional_inference_note(self):
        for mode in ("1/abs(Y)", "1/Y²"):
            self.assertIn("conditional", run(mode=mode).tables["Model"].loc["Inference", "Value"])
        self.assertIn("conditional", run(fixture("signed.csv"), mode="1/abs(Y)^K").tables["Model"].loc[
            "Inference", "Value"])
        for mode in ("Weight column", "Inverse variance (SD column)"):
            self.assertNotIn("Inference", run(mode=mode).tables["Model"].index)


class ModeAndFamilyTests(unittest.TestCase):
    def test_an_unknown_mode_is_a_field_error(self):
        for bad in ("1/Y", 3, ["Weight column"]):
            with self.subTest(bad=bad), self.assertRaises(FieldError) as caught:
                run(**{"Gaussian weighting": bad})
            self.assertEqual(caught.exception.field, "Gaussian weighting")

    def test_unweighted_and_missing_keys_keep_the_historical_result(self):
        base = {"Family": "Linear", "Response": "Y", "Predictors": ["X1", "X2"], "Categorical predictors": [],
                "Linear diagnostics": True, "Linear profiles": [dict(p) for p in PROFILES], "Linear CI (%)": 90,
                "Linear residual plot": "Residuals vs fitted"}
        frame = fixture("numeric.csv")
        legacy = analyse(METHOD, frame, dict(base))
        stale = {"Gaussian SD column": "nope", "Gaussian weight column": "Y", "Weight exponent K": "x",
                 "Weighted prediction intervals": True}
        for extra in ({"Gaussian weighting": "Unweighted"}, {"Gaussian weighting": ""}, {"Gaussian weighting": None},
                      {"Gaussian weighting": "Unweighted", **stale}, stale):
            with self.subTest(extra=extra):
                other = analyse(METHOD, frame, {**base, **extra})
                self.assertEqual(list(legacy.tables), list(other.tables))
                self.assertNotIn("Linear weights", other.tables)
                for name in legacy.tables:
                    pd.testing.assert_frame_equal(legacy.tables[name], other.tables[name])
                self.assertEqual(other.figure.axes[0].get_ylabel(), "Residual")
        self.assertNotIn("Note", legacy.tables["Linear predictions"].columns)
        # Profiles of an unweighted fit never need a weight.
        self.assertTrue(legacy.tables["Linear predictions"]["Prediction interval low"].notna().all())

    def test_logistic_and_poisson_ignore_every_gaussian_key(self):
        frame = pd.DataFrame({"X": [0., 1, 2, 3, 4, 5, 6, 7], "Y": [0, 0, 1, 0, 1, 1, 0, 1]})
        counts = pd.DataFrame({"X": [0., 1, 2, 3, 4, 5], "Y": [0, 1, 1, 3, 4, 7]})
        garbage = {"Gaussian weighting": "nonsense", "Gaussian SD column": "Y", "Gaussian weight column": 5,
                   "Weight exponent K": "x", "Weighted prediction intervals": "maybe"}
        for family, data in (("Logistic", frame), ("Poisson", counts)):
            plain = {"Family": family, "Response": "Y", "Predictors": ["X"], "Categorical predictors": []}
            a, b = analyse(METHOD, data, plain), analyse(METHOD, data, {**plain, **garbage})
            self.assertEqual(list(a.tables), list(b.tables), family)
            for name in a.tables:
                pd.testing.assert_frame_equal(a.tables[name], b.tables[name])
            with patch.object(mw, "weighted_linear_fit") as weighted:
                analyse(METHOD, data, {**plain, **garbage})
            weighted.assert_not_called()

    def test_the_method_dispatch_keys_and_defaults(self):
        spec = METHODS[METHOD]
        self.assertEqual(spec["Gaussian weighting"], mw.MODES)
        self.assertEqual(spec["Gaussian weighting"][0], "Unweighted")
        self.assertEqual(spec["Weight exponent K"], 1.0)
        self.assertIs(spec["Weighted prediction intervals"], False)
        self.assertEqual(spec["Gaussian SD column"], "Optional")

    def test_visibility(self):
        def visible(family, mode="Unweighted", profiles=False):
            return additional.regression_visibility(family, False, gaussian_mode=mode, linear_profiles=profiles)

        keys = ("Gaussian weighting", "Weight exponent K", "Gaussian SD column", "Gaussian weight column",
                "Weighted prediction intervals")
        self.assertEqual([visible("Linear")[k] for k in keys], [True, False, False, False, False])
        self.assertEqual([visible("Linear", "1/abs(Y)^K")[k] for k in keys], [True, True, False, False, False])
        self.assertEqual([visible("Linear", "Inverse variance (SD column)")[k] for k in keys],
                         [True, False, True, False, False])
        self.assertEqual([visible("Linear", "Weight column", True)[k] for k in keys], [True, False, False, True, True])
        self.assertFalse(visible("Linear", "Unweighted", True)["Weighted prediction intervals"])
        self.assertFalse(visible("Linear", "1/abs(Y)", False)["Weighted prediction intervals"])
        for family in ("Logistic", "Poisson"):
            self.assertFalse(any(visible(family, "Weight column", True)[k] for k in keys), family)


class OneFitTests(unittest.TestCase):
    def test_one_weighted_fit_feeds_every_sheet(self):
        calls = {"weighted": 0, "ols": 0, "wls": 0}
        original_wls, original_ols = linear_model.WLS.fit, linear_model.OLS.fit

        def wls(self, *a, **k):
            calls["wls"] += 1
            return original_wls(self, *a, **k)

        def ols(self, *a, **k):
            calls["ols"] += 1
            return original_ols(self, *a, **k)

        real = mw.weighted_linear_fit

        def weighted(*a, **k):
            calls["weighted"] += 1
            return real(*a, **k)

        with patch.object(linear_model.WLS, "fit", wls), patch.object(linear_model.OLS, "fit", ols), \
                patch.object(mw, "weighted_linear_fit", weighted), \
                patch.object(models, "linear_fit", side_effect=AssertionError("OLS helper")):
            result = run(**{"Linear residual plot": "Residuals vs fitted"})
        self.assertEqual(calls, {"weighted": 1, "ols": 0, "wls": 1})
        self.assertEqual(len(result.tables), 7 and 7)

    def test_the_ols_path_is_untouched(self):
        with patch.object(mw, "weighted_linear_fit", side_effect=AssertionError("weighted")):
            analyse(METHOD, fixture("numeric.csv"), {"Family": "Linear", "Response": "Y", "Predictors": ["X1", "X2"],
                                                      "Categorical predictors": [], "Linear diagnostics": True})

    def test_errors_leave_no_partial_result_and_no_mutation(self):
        frame = fixture("numeric.csv")
        frame.loc[4, "Y"] = 0
        before, recipe = frame.copy(), options("1/abs(Y)")
        saved = json.dumps(recipe, sort_keys=True)
        with self.assertRaises(FieldError):
            analyse(METHOD, frame, recipe)
        pd.testing.assert_frame_equal(frame, before)
        self.assertEqual(json.dumps(recipe, sort_keys=True), saved)


class CategoryAndRankTests(unittest.TestCase):
    def categorical(self):
        return fixture("categorical.csv")

    def opts(self, **extra):
        return options(**{"Predictors": ["X1", "Batch"], "Categorical predictors": ["Batch"], "Linear profiles": [],
                          **extra})

    def test_levels_come_only_from_the_fitted_rows(self):
        frame = self.categorical()
        tables = analyse(METHOD, frame, self.opts()).tables
        self.assertEqual(tables["Reference levels"].loc["Batch", "Reference"], "A")
        self.assertEqual([c for c in tables["Coefficients"].index], ["Intercept", "X1", "Batch [B]", "Batch [C]"])
        self.assertNotIn("Batch [Z]", tables["Coefficients"].index)    # level Z sits on the incomplete row 77
        # A level present only on rows that leave for a missing weight is not learned either.
        frame.loc[[4, 12, 30, 60], "W"] = np.nan
        frame.loc[[4, 12, 30, 60], "Batch"] = "A"
        reduced = analyse(METHOD, frame, self.opts()).tables
        self.assertEqual(reduced["Reference levels"].loc["Batch", "Reference"], "B")
        self.assertEqual([c for c in reduced["Coefficients"].index], ["Intercept", "X1", "Batch [C]"])

    def test_profiles_with_a_new_or_invalid_category_are_rejected_on_the_profiles_field(self):
        frame = self.categorical()
        profiles = [{"name": "Ok", "values": {"X1": 0.5, "Batch": "B"}, "weight": 2}]
        tables = analyse(METHOD, frame, self.opts(**{"Linear profiles": profiles})).tables
        self.assertEqual(tables["Linear predictions"]["Profile"].tolist(), ["Ok"])
        cases = (({"X1": 0.5, "Batch": "Z"}, "not a category"), ({"X1": 0.5, "Batch": "Q"}, "not a category"),
                 ({"X1": "x", "Batch": "A"}, "finite number"), ({"X1": 1.0}, "needs a value"))
        for values, text in cases:
            with self.subTest(values=values), self.assertRaises(FieldError) as caught:
                analyse(METHOD, frame, self.opts(**{"Linear profiles": [{"name": "Bad", "values": values,
                                                                           "weight": 1}]}))
            self.assertEqual(caught.exception.field, "Linear profiles")
            self.assertIn(text, str(caught.exception))
            self.assertIn("Bad", str(caught.exception))

    def test_rank_is_checked_on_the_weighted_matrix(self):
        frame = pd.DataFrame({"X": [1., 2, 3, 4, 5, 6, 7, 8], "Z": [0., 0, 0, 0, 0, 0, 0, 1],
                              "Y": [2., 3, 5, 4, 6, 8, 7, 9], "W": [1.] * 7 + [1e-300]})
        o = {"Family": "Linear", "Response": "Y", "Predictors": ["X", "Z"], "Categorical predictors": [],
             "Gaussian weighting": "Weight column", "Gaussian weight column": "W"}
        with self.assertRaisesRegex(ValueError, "rank deficient after weighting"):
            analyse(METHOD, frame, o)
        # The same columns are estimable without that weight.
        analyse(METHOD, frame, {**o, "Gaussian weighting": "Unweighted"})
        frame["W"] = 1.0
        analyse(METHOD, frame, o)
        # A redundant column stays an error with the historical wording.
        frame["Z"] = 2 * frame["X"]
        with self.assertRaisesRegex(ValueError, "rank deficient"):
            analyse(METHOD, frame, o)

    def test_too_few_rows_after_weights_leave_the_fit(self):
        frame = fixture("numeric.csv")
        frame.loc[frame.index[2:], "W"] = np.nan
        with self.assertRaises(ValueError):
            run(frame)


class PredictionTests(unittest.TestCase):
    def test_future_precision_avoids_intermediate_overflow(self):
        y = np.array([1., 2.1, 2.8, 4.3, 4.9, 6.])
        x = np.arange(6.)
        reference_fit = sm.OLS(y, sm.add_constant(x)).fit()
        for scale, expected_sd_scale in [(1e-100, 1e100), (1., 1e200)]:
            frame = pd.DataFrame({"X": x, "Y": y*scale, "W": 1e300})
            result = analyse(METHOD, frame, {"Family": "Linear", "Response": "Y", "Predictors": ["X"],
                "Categorical predictors": [], "Gaussian weighting": "Weight column", "Gaussian weight column": "W",
                "Linear profiles": [{"name": "P", "values": {"X": 2.5}, "weight": 1e-100}],
                "Weighted prediction intervals": True})
            row = result.tables["Linear predictions"].iloc[0]
            half = stats.t.isf(.025, 4)*np.sqrt(reference_fit.mse_resid)*expected_sd_scale
            assert_allclose([row["Prediction interval low"], row["Prediction interval high"]],
                            [-half, half], rtol=3e-12, atol=0)

    def test_without_future_precision_the_prediction_limits_are_blank_and_explained(self):
        tables = run(**{"Weighted prediction intervals": False}).tables
        pred = tables["Linear predictions"]
        self.assertTrue(pred["Prediction interval low"].isna().all() and pred["Prediction interval high"].isna().all())
        self.assertIn("precision", pred["Note"].iloc[0])
        close(pred[["Prediction", "Mean CI low", "Mean CI high"]], np.array(EXPECTED["Weight column"]["profiles"])[:, :3])
        # Profiles do not need a weight then.
        bare = [{"name": p["name"], "values": p["values"]} for p in PROFILES]
        again = run(**{"Weighted prediction intervals": False, "Linear profiles": bare}).tables["Linear predictions"]
        pd.testing.assert_frame_equal(pred, again)

    def test_future_precision_must_be_a_finite_positive_number_on_every_profile(self):
        for bad in (None, 0, -1, "x", np.inf, np.nan, True):
            profiles = [dict(PROFILES[0]), dict(PROFILES[1], weight=bad)]
            if bad is None:
                del profiles[1]["weight"]
            with self.subTest(bad=bad), self.assertRaises(FieldError) as caught:
                run(**{"Linear profiles": profiles})
            self.assertEqual(caught.exception.field, "Linear profiles")
            self.assertIn("P2", str(caught.exception))

    def test_future_variance_is_sigma_squared_over_the_relative_weight(self):
        e = EXPECTED["Weight column"]
        pred = run().tables["Linear predictions"]
        low = pred["Prediction interval low"].to_numpy()
        high = pred["Prediction interval high"].to_numpy()
        critical = stats.t.ppf(.975, e["df"])
        for row, profile in enumerate(PROFILES):
            x = np.array([1., profile["values"]["X1"], profile["values"]["X2"]])
            variance = x @ np.array(e["covariance"]) @ x + e["variance"] / (profile["weight"] / 5.0)
            half = critical * np.sqrt(variance)
            close((high[row] - low[row]) / 2, half)
        # A more precise future observation gives a narrower interval.
        better = run(**{"Linear profiles": [dict(p, weight=p["weight"] * 10) for p in PROFILES]}).tables
        self.assertTrue((better["Linear predictions"]["Prediction interval high"].to_numpy() < high).all())
        close(better["Linear predictions"]["Mean CI low"], pred["Mean CI low"])

    def test_profile_weights_and_training_weights_scale_together(self):
        base = run().tables["Linear predictions"]
        frame = fixture("numeric.csv")
        frame["W"] *= 1e100
        scaled = run(frame, **{"Linear profiles": [dict(p, weight=p["weight"] * 1e100) for p in PROFILES]})
        pd.testing.assert_frame_equal(base, scaled.tables["Linear predictions"], rtol=1e-9, atol=1e-12)

    def test_the_unrepresentable_maximum_weight_still_works_for_profiles(self):
        frame = fixture("numeric.csv")
        frame["SD"] = 1e-200 * frame["SD"]
        profiles = [{"name": "P", "values": {"X1": 1.0, "X2": 0.5}, "weight": 1e-4}]  # units of 1/SD²: 1/(1e-200)²…
        # The variance ratio is not representable, but its square root and the interval are.
        table = run(frame, mode="Inverse variance (SD column)", **{"Linear profiles": profiles}).tables["Linear predictions"]
        e = reference(fixture("numeric.csv"), "SD")
        half = stats.t.isf(.025, e["df"])*np.sqrt(e["s2"])*2e202
        assert_allclose(table[["Prediction interval low", "Prediction interval high"]].iloc[0],
                        [-half, half], rtol=3e-12, atol=0)
        # An actually unrepresentable endpoint still gives the named field error.
        frame["SD"] = fixture("numeric.csv")["SD"]*1e-300
        profiles[0]["weight"] = 1e-100
        with self.assertRaises(FieldError) as caught:
            run(frame, mode="Inverse variance (SD column)", **{"Linear profiles": profiles})
        self.assertEqual(caught.exception.field, "Linear profiles")
        self.assertIn("outside the numeric range", str(caught.exception))

    def test_unweighted_fits_never_ask_for_a_weight(self):
        profiles = [{"name": "P", "values": {"X1": 1.0, "X2": 0.5}}]
        base = {"Family": "Linear", "Response": "Y", "Predictors": ["X1", "X2"], "Categorical predictors": [],
                "Linear profiles": profiles, "Weighted prediction intervals": True}
        table = analyse(METHOD, fixture("numeric.csv"), base).tables["Linear predictions"]
        self.assertTrue(table["Prediction interval low"].notna().all())


class DiagnosticRuleTests(unittest.TestCase):
    def test_low_precision_outliers_do_not_erase_the_weighted_residual_variance(self):
        frame = pd.DataFrame({"X": np.arange(6, dtype=float), "Y": [0., 1., 1e14, -1e14, 2e14, -2e14],
                              "W": [1., 1., 1e-40, 1e-40, 1e-40, 1e-40]})
        opts = {"Family": "Linear", "Response": "Y", "Predictors": ["X"], "Categorical predictors": [],
                "Gaussian weighting": "Weight column", "Gaussian weight column": "W", "Linear diagnostics": True}
        fit, weights = mw.weighted_linear_fit(frame, opts)
        model, design = fit[1:3]
        tables = ols_diagnostics.linear_result(opts, fit, weights).tables
        variance = float(model.mse_resid)
        assert_allclose(variance, 2.5e-12, rtol=1e-12, atol=0)
        assert_allclose(tables["Linear model diagnostics"].loc["Residual variance", "Value"], variance,
                        rtol=1e-12, atol=0)
        # Use this fit's covariance to obtain h, independently of the diagnostics' reduced QR.
        coded = design.to_numpy()
        leverage = weights.normalized * np.einsum("ij,ij->i", coded @ model.normalized_cov_params, coded)
        scaled = weights.root * np.asarray(model.resid)
        expected_student = scaled[2:] / np.sqrt(variance * (1 - leverage[2:]))
        expected_cook = scaled[2:]**2 * leverage[2:] / (design.shape[1] * variance * (1 - leverage[2:])**2)
        diagnostics = tables["Linear diagnostics"].iloc[2:]
        assert_allclose(diagnostics["Internally studentized residual"], expected_student, rtol=1e-12, atol=0)
        assert_allclose(diagnostics["Cook's distance"], expected_cook, rtol=1e-12, atol=0)

    def test_leverage_one_and_exact_fits_follow_the_historical_blanks(self):
        frame = pd.DataFrame({"X": [0., 0, 0, 1, 1, 1, 2], "G": ["a", "a", "a", "a", "a", "a", "b"],
                              "Y": [1., 2, 3, 2, 3, 4, 7], "W": [1., 2, 3, 1, 2, 3, 4]})
        o = {"Family": "Linear", "Response": "Y", "Predictors": ["X", "G"], "Categorical predictors": ["G"],
             "Gaussian weighting": "Weight column", "Gaussian weight column": "W", "Linear diagnostics": True}
        tables = analyse(METHOD, frame, o).tables
        d, summary = tables["Linear diagnostics"], tables["Linear model diagnostics"]
        self.assertAlmostEqual(d["Leverage"].iloc[-1], 1.0, places=9)
        self.assertTrue(np.isnan(d["Internally studentized residual"].iloc[-1]) and np.isnan(d["PRESS residual"].iloc[-1]))
        self.assertTrue(np.isnan(summary.loc["PRESS", "Value"]) and np.isnan(summary.loc["Weighted PRESS", "Value"]))
        self.assertIn("leverage is one", summary["Note"].iloc[0])
        exact = pd.DataFrame({"X": [0., 1, 2, 3, 4], "Y": [1., 3, 5, 7, 9], "W": [1., 2, 3, 4, 5]})
        tables = analyse(METHOD, exact, {"Family": "Linear", "Response": "Y", "Predictors": ["X"],
                                          "Categorical predictors": [], "Gaussian weighting": "Weight column",
                                          "Gaussian weight column": "W", "Linear diagnostics": True}).tables
        self.assertTrue(tables["Linear diagnostics"]["Cook's distance"].isna().all())
        self.assertEqual(tables["Linear model diagnostics"].loc["Residual variance", "Value"], 0.0)
        self.assertTrue(np.isfinite(tables["Linear model diagnostics"].loc["Weighted PRESS", "Value"]))

    def test_leverage_sums_to_the_number_of_terms(self):
        d = run().tables["Linear diagnostics"]
        self.assertAlmostEqual(d["Leverage"].sum(), 3.0, places=12)


class CatalogTests(unittest.TestCase):
    def test_both_catalogs_have_the_same_keys_and_placeholders(self):
        keys = [k for k in i18n._EN if k.startswith(("analysis.mlr.", "mlr.error."))]
        self.assertGreater(len(keys), 25)
        for key in keys:
            self.assertIn(key, i18n._IT, key)
            self.assertEqual(i18n.placeholders(i18n._EN[key]), i18n.placeholders(i18n._IT[key]), key)

    def test_every_engine_message_translates_into_italian(self):
        def message(call):
            with self.assertRaises((FieldError, ValueError)) as caught:
                call()
            return str(caught.exception)

        frame = fixture("numeric.csv")
        zero = fixture("numeric.csv")
        zero.loc[4, "Y"] = 0
        tiny = fixture("numeric.csv")
        tiny.loc[4, "W"], tiny.loc[9, "W"] = 1e-200, 1e200
        text = fixture("numeric.csv")
        text["W"] = text["W"].astype(object)
        text.loc[4, "W"] = "abc"
        sd = fixture("numeric.csv")
        sd.loc[4, "SD"] = -2
        collinear = pd.DataFrame({"X": [1., 2, 3, 4, 5, 6, 7, 8], "Z": [0.] * 7 + [1.],
                                  "Y": [2., 3, 5, 4, 6, 8, 7, 9], "W": [1.] * 7 + [1e-300]})
        profile = [{"name": "P", "values": {"X1": 1, "X2": 1}}]
        cases = [
            lambda: run(**{"Gaussian weighting": "x"}),
            lambda: run(mode="1/abs(Y)^K", **{"Weight exponent K": "q"}),
            lambda: run(**{"Weighted prediction intervals": "maybe"}),
            lambda: run(**{"Gaussian weight column": None}),
            lambda: run(**{"Gaussian weight column": "Nope"}),
            lambda: run(**{"Gaussian weight column": "Y"}),
            lambda: run(zero, mode="1/abs(Y)"),
            lambda: run(tiny),
            lambda: run(text),
            lambda: run(sd, mode="Inverse variance (SD column)"),
            lambda: run(**{"Linear profiles": profile}),
            lambda: analyse(METHOD, collinear, {"Family": "Linear", "Response": "Y", "Predictors": ["X", "Z"],
                                                "Categorical predictors": [], "Gaussian weighting": "Weight column",
                                                "Gaussian weight column": "W"}),
        ]
        english = [message(call) for call in cases]
        from analisi.i18n import translate_message
        i18n.set_language("it")
        try:
            for text_en in english:
                translated = translate_message(text_en, "mlr.error.")
                self.assertNotEqual(translated, text_en, text_en)
                self.assertNotRegex(translated, r"\{[a-z_]+\}")
        finally:
            i18n.set_language("en")


if __name__ == "__main__":
    unittest.main()
