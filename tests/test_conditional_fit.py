"""Conditional equations in Fit custom equation and Global fit custom equation (0.81).

Known thresholds only: the expected values come from the linear design of the hinge written here with
NumPy/SciPy, never from the engine under test.
"""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from matplotlib.collections import PolyCollection
from scipy import stats

from analisi import custom_fit, global_custom_fit
from analisi.custom_fit import CUSTOM_EQUATION
from analisi.field_error import FieldError
from analisi.global_custom_fit import GLOBAL_CUSTOM_EQUATION
from analisi.parameter_intervals import METHOD as INTERVAL_METHOD, PROFILE
from analisi.workbench import analyse

X = np.array([-3., -2, -1, 0, 1, 2, 3])
Y = np.array([-2.4, -1.2, .6, 2., 1.6, .8, .6])
G2 = np.array([-3.9, -2.2, .1, 2., 3.1, 3.8, 5.1])
HINGE = "if(X<T,A+B*X,A+C*X)"


def design(x, threshold=0.):
    return np.column_stack([np.ones(len(x)), np.where(x < threshold, x, 0.), np.where(x < threshold, 0., x)])


def ols(x, y, sd=None):
    sd = np.ones(len(x)) if sd is None else np.asarray(sd, float)
    m = design(x) / sd[:, None]
    beta = np.linalg.lstsq(m, y / sd, rcond=None)[0]
    resid = y / sd - m @ beta
    df = len(x) - 3
    cov = (resid @ resid / df) * np.linalg.inv(m.T @ m)
    return beta, np.sqrt(np.diag(cov)), float(resid @ resid), df


def parameters(*, threshold_fixed=True, shared=None, start_t=0.):
    rows = []
    for name, start in (("A", 1.8), ("B", 1.2), ("C", -.2), ("T", start_t)):
        row = dict(name=name, start=start, lower=None, upper=None, fixed=name == "T" and threshold_fixed)
        if shared is not None:
            row["shared"] = name in shared and not row["fixed"]
        rows.append(row)
    return rows


def single(**extra):
    options = {"X": "X", "Y": "Y", "Group": None, "Equation": HINGE, "Equation syntax": "Conditional",
               "Parameters": parameters(), "Weighting": "Unweighted", "Confidence level (%)": 95., "Curve points": 41}
    options.update(extra)
    return options


def global_options(**extra):
    options = {"X": "X", "Y": "Y", "Group": "Group", "Equation": HINGE, "Equation syntax": "Conditional",
               "Parameters": parameters(shared={"A"}), "Weighting": "Unweighted", "Confidence level (%)": 95.,
               "Curve points": 41}
    options.update(extra)
    return options


FRAME = pd.DataFrame({"X": X, "Y": Y, "SD": np.arange(1., 8.)})
GLOBAL = pd.concat([pd.DataFrame({"X": X, "Y": Y, "Group": "G1"}), pd.DataFrame({"X": X, "Y": G2, "Group": "G2"})],
                   ignore_index=True)


class SingleFitTests(unittest.TestCase):
    def test_known_threshold_matches_the_linear_design(self):
        result = analyse(CUSTOM_EQUATION, FRAME, single())
        beta, se, rss, df = ols(X, Y)
        table = result.tables["Parameters: All"]
        np.testing.assert_allclose(table.loc[["A", "B", "C"], "Estimate"], beta, rtol=1e-7, atol=1e-9)
        np.testing.assert_allclose(table.loc[["A", "B", "C"], "SE"], se, rtol=1e-6)
        half = stats.t.ppf(.975, df) * se
        np.testing.assert_allclose(table.loc[["A", "B", "C"], "CI lower"], beta - half, rtol=1e-6, atol=1e-8)
        self.assertEqual(table.loc["T", "Status"], "Fixed")
        self.assertTrue(np.isnan(table.loc["T", "SE"]))
        fit = result.tables["Fit: All"]["Value"]
        self.assertEqual((fit["Free parameters"], fit["df"]), (3, 4))
        self.assertAlmostEqual(float(fit["Residual SS"]), rss, places=10)
        self.assertEqual(fit["Equation syntax"], "Conditional")
        self.assertIn("T = 0", fit["Conditions"])

    def test_branch_column_and_drawn_line_without_bridge(self):
        result = analyse(CUSTOM_EQUATION, FRAME, single(**{"Curve points": 40}))
        curve = result.tables["Curve: All"]
        self.assertEqual(list(curve.columns), ["X", "Predicted", "Branch"])
        self.assertTrue(np.isfinite(curve["Predicted"]).all() and len(curve) == 40)
        codes = curve["Branch"].to_numpy()
        np.testing.assert_array_equal(codes[curve["X"] < 0] != codes[curve["X"] >= 0][0], True)
        line = result.figure.axes[0].lines[0]
        x, y = np.asarray(line.get_xdata(), float), np.asarray(line.get_ydata(), float)
        self.assertEqual(int(np.isnan(y).sum()), 1)
        np.testing.assert_array_equal(x[np.isfinite(x)], curve["X"])
        gap = int(np.flatnonzero(np.isnan(y))[0])
        self.assertLess(x[gap - 1], 0)
        self.assertGreaterEqual(x[gap + 1], 0)

    def test_arithmetic_recipe_gets_no_branch_and_no_separator(self):
        options = single(Equation="A+B*X+C*X^2+0*T")
        options.pop("Equation syntax")
        legacy = analyse(CUSTOM_EQUATION, FRAME, options)
        explicit = analyse(CUSTOM_EQUATION, FRAME, {**options, "Equation syntax": "Arithmetic"})
        self.assertNotIn("Branch", legacy.tables["Curve: All"])
        self.assertNotIn("Equation syntax", legacy.tables["Fit: All"].index)
        self.assertFalse(np.isnan(np.asarray(legacy.figure.axes[0].lines[0].get_ydata(), float)).any())
        for name, frame in legacy.tables.items():
            pd.testing.assert_frame_equal(frame, explicit.tables[name])

    def test_legacy_names_if_and_or_not_still_fit_in_arithmetic(self):
        records = [dict(name=n, start=1., lower=None, upper=None, fixed=False) for n in ("if", "and")]
        result = analyse(CUSTOM_EQUATION, FRAME, single(Equation="if + and*X", Parameters=records,
                                                        **{"Equation syntax": "Arithmetic"}))
        slope, intercept = np.polyfit(X, Y, 1)
        np.testing.assert_allclose(result.tables["Parameters: All"]["Estimate"], [intercept, slope], rtol=1e-6)
        with self.assertRaises(FieldError) as caught:
            analyse(CUSTOM_EQUATION, FRAME, single(Equation="if + and*X", Parameters=records))
        self.assertEqual(caught.exception.field, "Parameters")

    def test_free_threshold_is_refused_before_any_fit(self):
        options = single(Parameters=parameters(threshold_fixed=False))
        with patch.object(custom_fit, "_fit_group", side_effect=AssertionError("fit started")):
            for call in (lambda: custom_fit.check_options(FRAME, options), lambda: analyse(CUSTOM_EQUATION, FRAME, options)):
                with self.assertRaises(FieldError) as caught:
                    call()
                self.assertEqual(caught.exception.field, "Parameters")
                self.assertIn("T", str(caught.exception))
        # The recipe is not rewritten: T is still free and the equation unchanged.
        self.assertFalse(options["Parameters"][3]["fixed"])
        self.assertEqual(options["Equation"], HINGE)

    def test_relative_weights_scaled_by_a_common_factor(self):
        sd = np.arange(1., 8.)
        base = analyse(CUSTOM_EQUATION, FRAME, single(Weighting="Inverse variance (column)", **{"SD column": "SD"}))
        scaled_frame = FRAME.assign(SD=FRAME.SD * 1e3)
        scaled = analyse(CUSTOM_EQUATION, scaled_frame,
                         single(Weighting="Inverse variance (column)", **{"SD column": "SD"}))
        beta, se, wsse, _ = ols(X, Y, sd)
        for result, factor in ((base, 1.), (scaled, 1e3)):
            table = result.tables["Parameters: All"]
            np.testing.assert_allclose(table.loc[["A", "B", "C"], "Estimate"], beta, rtol=1e-7, atol=1e-9)
            np.testing.assert_allclose(table.loc[["A", "B", "C"], "SE"], se, rtol=1e-6)
            self.assertAlmostEqual(float(result.tables["Fit: All"]["Value"]["Weighted residual SS"]) * factor ** 2,
                                   wsse, places=9)

    def test_excluded_rows_and_a_branch_without_observations(self):
        keep = X != 2
        result = analyse(CUSTOM_EQUATION, FRAME.assign(Y=np.where(keep, Y, np.nan)), single())
        beta, _, rss, _ = ols(X[keep], Y[keep])
        np.testing.assert_allclose(result.tables["Parameters: All"].loc[["A", "B", "C"], "Estimate"], beta, rtol=1e-7)
        self.assertEqual(result.tables["Fit: All"]["Value"]["Skipped rows"], 1)
        # T below every X: B only multiplies an empty branch, so it is not identifiable and no estimate is made up.
        options = single(Parameters=[{**row, "start": -10.} if row["name"] == "T" else row for row in parameters()])
        with self.assertRaises(FieldError) as caught:
            analyse(CUSTOM_EQUATION, FRAME, options)
        self.assertEqual(caught.exception.field, "Parameters")
        self.assertIn("identifiable", str(caught.exception))

    def test_undefined_condition_names_the_source_row(self):
        frame = FRAME.assign(X=[-3., -2, -1, 0, 1, 2, 3])
        options = single(Equation="if(log(X+2)<T,A+B*X,A+C*X)", Parameters=parameters(start_t=1.))
        with self.assertRaises(FieldError) as caught:
            custom_fit.check_options(frame, options)
        self.assertEqual(caught.exception.field, "Equation")
        self.assertIn("source row 0", str(caught.exception))
        # The same condition on X values where it is defined fits (log(X+2) < 1 holds for X = -1 and 0).
        result = analyse(CUSTOM_EQUATION, frame.iloc[2:], options)
        self.assertIn("Branch", result.tables["Curve: All"])

    def test_profile_intervals_with_a_fixed_threshold(self):
        result = analyse(CUSTOM_EQUATION, FRAME, single(**{INTERVAL_METHOD: PROFILE}))
        table = result.tables["Parameters: All"]
        beta, se, _, _ = ols(X, Y)
        # A linear model in the free coefficients: the profile limits equal the Wald limits.
        half = stats.t.ppf(.975, 4) * se
        np.testing.assert_allclose(table.loc[["A", "B", "C"], "CI lower"], beta - half, rtol=1e-4, atol=1e-6)
        np.testing.assert_allclose(table.loc[["A", "B", "C"], "CI upper"], beta + half, rtol=1e-4, atol=1e-6)


class GlobalFitTests(unittest.TestCase):
    def joint(self):
        # A shared intercept, local slopes on each side of the fixed threshold 0.
        x = np.concatenate([X, X])
        m = np.zeros((14, 5))
        m[:, 0] = 1
        for series in range(2):
            rows = slice(7 * series, 7 * series + 7)
            m[rows, 1 + 2 * series] = np.where(X < 0, X, 0)
            m[rows, 2 + 2 * series] = np.where(X < 0, 0, X)
        y = np.concatenate([Y, G2])
        beta = np.linalg.lstsq(m, y, rcond=None)[0]
        resid = y - m @ beta
        return beta, float(resid @ resid), x

    def test_shared_local_fixed(self):
        result = analyse(GLOBAL_CUSTOM_EQUATION, GLOBAL, global_options())
        beta, rss, _ = self.joint()
        table = result.tables["Parameters"]
        np.testing.assert_allclose(table.loc[table.Parameter == "A", "Estimate"], beta[:1], rtol=1e-7)
        for series, (b, c) in enumerate(((beta[1], beta[2]), (beta[3], beta[4]))):
            group = f"G{series + 1}"
            np.testing.assert_allclose(table.loc[(table.Parameter == "B") & (table.Group == group), "Estimate"], [b],
                                       rtol=1e-7)
            np.testing.assert_allclose(table.loc[(table.Parameter == "C") & (table.Group == group), "Estimate"], [c],
                                       rtol=1e-7, atol=1e-9)
        summary = result.tables["Global fit"]["Value"]
        self.assertEqual((summary["Free parameters"], summary["DF residual"]), (5, 9))
        self.assertAlmostEqual(float(summary["Residual SS"]), rss, places=9)
        curve = result.tables["Curve"]
        self.assertEqual(list(curve.columns), ["Group", "X", "Predicted", "Branch"])
        for line in result.figure.axes[0].lines:
            self.assertEqual(int(np.isnan(np.asarray(line.get_ydata(), float)).sum()), 1)

    def test_bands_and_predictions_follow_the_branches(self):
        queries = pd.DataFrame({"QX": [-.5, .5, -1.], "QG": ["G1", "G2", "G2"]})
        frame = pd.concat([GLOBAL, queries], axis=1)
        options = global_options(**{"Curve band": "Confidence", "Predict responses": True, "Query X": "QX",
                                    "Query group": "QG", "Query interval": "Confidence"})
        result = analyse(GLOBAL_CUSTOM_EQUATION, frame, options)
        bands = result.tables["Curve bands"]
        self.assertIn("Branch", bands)
        pd.testing.assert_series_equal(bands["Branch"].reset_index(drop=True),
                                       result.tables["Curve"]["Branch"].reset_index(drop=True))
        polygons = [p for c in result.figure.axes[0].collections if isinstance(c, PolyCollection)
                    for p in c.get_paths()]
        self.assertEqual(len(polygons), 4)  # two series, two branches each
        for path in polygons:
            xs = path.vertices[:, 0]
            self.assertTrue((xs < 0).all() or (xs >= 0).all(), xs)
        predictions = result.tables["Predictions"]
        self.assertEqual(predictions["Status"].tolist(), ["OK"] * 3)
        beta, _, _ = self.joint()
        np.testing.assert_allclose(predictions["Predicted"], [beta[0] - .5 * beta[1], beta[0] + .5 * beta[4],
                                                              beta[0] - beta[3]], rtol=1e-7, atol=1e-9)

    def test_query_where_the_condition_is_undefined_gets_its_own_status(self):
        frame = pd.concat([GLOBAL, pd.DataFrame({"QX": [-1.5, .5], "QG": ["G1", "G1"]})], axis=1)
        options = global_options(Equation="if(log(X+5)<T,A+B*X,A+C*X)",
                                 Parameters=parameters(shared={"A"}, start_t=float(np.log(5))),
                                 **{"Predict responses": True, "Query X": "QX", "Query group": "QG",
                                    "Allow extrapolation": True})
        frame.loc[0, "QX"] = -6.
        result = analyse(GLOBAL_CUSTOM_EQUATION, frame, options)
        statuses = result.tables["Predictions"]["Status"].tolist()
        self.assertEqual(statuses, ["Undefined model", "OK"])
        self.assertIn("condition", result.tables["Predictions"]["Reason"].iloc[0])

    def test_threshold_must_be_fixed_or_fixed_per_series(self):
        shared = global_options(Parameters=parameters(threshold_fixed=False, shared={"A", "T"}))
        local = global_options(Parameters=parameters(threshold_fixed=False, shared={"A"}))
        for options, words in ((shared, "shared"), (local, "'G1'")):
            with patch.object(global_custom_fit, "_solve", side_effect=AssertionError("fit started")):
                with self.assertRaises(FieldError) as caught:
                    global_custom_fit.check_options(GLOBAL, options)
            self.assertEqual(caught.exception.field, "Parameters")
            self.assertIn(words, str(caught.exception))
        # Per-series known thresholds: a local T fixed for every series in Series constraints.
        per_series = dict(local, **{"Series constraints": [
            {"series": "G1", "parameters": {"T": {"fixed": 0.}}},
            {"series": "G2", "parameters": {"T": {"fixed": 0.}}}]})
        result = analyse(GLOBAL_CUSTOM_EQUATION, GLOBAL, per_series)
        beta, _, _ = self.joint()
        table = result.tables["Parameters"]
        np.testing.assert_allclose(table.loc[table.Parameter == "A", "Estimate"], beta[:1], rtol=1e-7)


if __name__ == "__main__":
    unittest.main()
