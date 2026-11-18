"""Negative binomial (NB2) regression: numbers, field errors, missing cells, row mapping and limits.

The references are independent of analisi.nb2_regression: the frozen closed-form oracle of the 0.93 package
(tests/data/nb2_regression/expected.json, two saturated groups), statsmodels (GLM with known alpha and the
discrete NB2 model with joint ML) and scipy.stats.nbinom for the log likelihood.
"""
import json
import warnings
from io import BytesIO
from math import log
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy.stats import nbinom

from analisi import nb2_regression as nb
from analisi.field_error import FieldError
from analisi.workbench import GROUPS, METHODS, analyse

DATA = Path(__file__).resolve().parent / "data" / "nb2_regression"
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))
NB2 = "Negative binomial regression"
BASE = {"Response": "Count", "Predictors": ["Treatment"], "Categorical predictors": [], "Exposure": "Exposure",
        "Dispersion mode": "Fixed", "Dispersion alpha": 0.5, "Confidence level (%)": 95.0, "Residual plot": False}


def counts():
    return pd.read_csv(DATA / "counts.csv", keep_default_na=False).replace("", np.nan)


def batches():
    return pd.read_csv(DATA / "batches.csv")


def run(frame=None, **changes):
    return analyse(NB2, counts() if frame is None else frame, BASE | changes)


def close(actual, expected, **tolerance):
    np.testing.assert_allclose(np.asarray(actual, dtype=float), np.asarray(expected, dtype=float),
                               **({"rtol": 2e-9, "atol": 2e-10} | tolerance))


class RegistryTests(unittest.TestCase):
    def test_method_sits_beside_multiple_regression_with_canonical_defaults(self):
        group = GROUPS["Regression and Curves"]
        self.assertEqual(group.index(NB2), group.index("Multiple regression") + 1)
        self.assertEqual(METHODS[NB2], {"Response": None, "Predictors": "Multiple",
                                        "Categorical predictors": "Multiple (optional)", "Exposure": "Optional",
                                        "Dispersion mode": ("Estimated ML", "Fixed"), "Dispersion alpha": 0.5,
                                        "Confidence level (%)": 95.0, "Residual plot": False})

    def test_sheets_and_columns_are_canonical(self):
        result = run(counts(), Predictors=["Treatment", "Batch"], **{"Categorical predictors": ["Batch"]})
        self.assertEqual(list(result.tables), ["Coefficients", "Model fit", "Fitted values", "Reference levels"])
        self.assertEqual(list(result.tables["Coefficients"].columns),
                         ["Estimate", "SE", "p", "Lower", "Upper", "IRR", "IRR lower", "IRR upper"])
        self.assertEqual(list(result.tables["Model fit"].columns),
                         ["N", "Incomplete rows", "Dispersion mode", "Alpha", "Parameters", "Log likelihood", "AIC",
                          "Covariance"])
        self.assertEqual(len(result.tables["Model fit"]), 1)
        self.assertEqual(list(result.tables["Fitted values"].columns),
                         ["Source row", "Observed", "Exposure", "Fitted count", "Fitted rate", "Variance",
                          "Pearson residual"])
        self.assertEqual(result.tables["Reference levels"].to_dict(), {"Reference": {"Batch": "A"}})
        self.assertIsNone(result.figure)

    def test_reference_levels_and_terms_match_multiple_regression(self):
        frame = batches()
        roles = {"Response": "Count", "Predictors": ["Dose", "Batch"], "Categorical predictors": ["Batch"],
                 "Exposure": "Exposure"}
        poisson = analyse("Multiple regression", frame, roles | {"Family": "Poisson"})
        result = analyse(NB2, frame, roles | {"Dispersion mode": "Fixed", "Dispersion alpha": 0.8})
        self.assertEqual(list(result.tables["Coefficients"].index), list(poisson.tables["Coefficients"].index))
        self.assertEqual(list(result.tables["Coefficients"].index), ["Intercept", "Dose", "Batch [B]", "Batch [C]"])
        pd.testing.assert_frame_equal(result.tables["Reference levels"], poisson.tables["Reference levels"])


class OracleTests(unittest.TestCase):
    """Two saturated groups of eight, exposures 2 and 4: means 3 and 9, rate ratio 1.5 (closed form)."""

    def check(self, mode, option, **tolerance):
        result = run(**{"Dispersion mode": option})
        expected = EXPECTED[mode]
        coefficients = result.tables["Coefficients"].loc[["Intercept", "Treatment"]]
        for column, key in (("Estimate", "beta"), ("SE", "se"), ("IRR", "irr"), ("IRR lower", "lower"),
                            ("IRR upper", "upper"), ("p", "p")):
            close(coefficients[column], expected[key], **tolerance)
        close(coefficients["Lower"], np.log(expected["lower"]), **tolerance)
        close(coefficients["Upper"], np.log(expected["upper"]), **tolerance)
        fit = result.tables["Model fit"].iloc[0]
        for column, key in (("Alpha", "alpha"), ("Log likelihood", "ll"), ("AIC", "aic")):
            close(fit[column], expected[key], **tolerance)
        rows = result.tables["Fitted values"]
        for column, key in (("Fitted count", "mean"), ("Variance", "variance"), ("Pearson residual", "pearson")):
            close(rows[column], expected[key], **tolerance)
        close(rows["Fitted rate"], np.array(expected["mean"]) / np.repeat([2.0, 4.0], 8), **tolerance)
        self.assertEqual(rows["Source row"].tolist(), list(range(1, 17)))
        self.assertEqual((fit["N"], fit["Incomplete rows"], fit["Dispersion mode"]), (16, 0, option))
        return fit

    def test_fixed_alpha_uses_the_fisher_information(self):
        fit = self.check("fixed", "Fixed")
        self.assertEqual((fit["Parameters"], fit["Covariance"]), (2, nb.FISHER))

    def test_estimated_ml_solves_the_size_score_and_uses_the_observed_information(self):
        fit = self.check("estimated", "Estimated ML", rtol=2e-8, atol=2e-9)
        self.assertEqual((fit["Parameters"], fit["Covariance"]), (3, nb.OBSERVED))

    def test_the_confidence_level_changes_only_the_limits(self):
        wide, narrow = run(), run(**{"Confidence level (%)": 80.0})
        a, b = wide.tables["Coefficients"], narrow.tables["Coefficients"]
        close(a["Estimate"], b["Estimate"])
        close(a["SE"], b["SE"])
        close(b["Upper"] - b["Estimate"], 1.2815515655446004 * b["SE"])
        close(b["IRR lower"], np.exp(b["Estimate"] - 1.2815515655446004 * b["SE"]))


class ReferenceTests(unittest.TestCase):
    """Varying exposure and a categorical predictor against statsmodels."""

    def design(self, frame):
        import statsmodels.api as sm
        dummies = pd.get_dummies(frame[["Dose", "Batch"]], columns=["Batch"], drop_first=True, dtype=float)
        return sm.add_constant(dummies)

    def test_fixed_alpha_matches_the_glm_with_known_dispersion(self):
        import statsmodels.api as sm
        frame = batches()
        glm = sm.GLM(frame["Count"], self.design(frame), family=sm.families.NegativeBinomial(alpha=0.8),
                     offset=np.log(frame["Exposure"])).fit(tol=1e-14, maxiter=200)
        result = analyse(NB2, frame, {"Response": "Count", "Predictors": ["Dose", "Batch"],
                                      "Categorical predictors": ["Batch"], "Exposure": "Exposure",
                                      "Dispersion mode": "Fixed", "Dispersion alpha": 0.8})
        coefficients = result.tables["Coefficients"]
        close(coefficients["Estimate"], glm.params, rtol=1e-7, atol=1e-8)
        close(coefficients["SE"], glm.bse, rtol=1e-7)
        close(coefficients["p"], glm.pvalues, rtol=1e-6, atol=1e-12)
        close(result.tables["Fitted values"]["Fitted count"], glm.fittedvalues, rtol=1e-7)
        close(result.tables["Model fit"]["Log likelihood"].iloc[0], glm.llf, rtol=1e-11)
        close(result.tables["Fitted values"]["Pearson residual"], glm.resid_pearson, rtol=1e-6, atol=1e-8)

    def test_estimated_ml_matches_the_discrete_nb2_model(self):
        from statsmodels.discrete.discrete_model import NegativeBinomial
        frame = batches()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            model = NegativeBinomial(frame["Count"], self.design(frame), loglike_method="nb2",
                                     exposure=frame["Exposure"]).fit(method="newton", maxiter=300, tol=1e-14,
                                                                     disp=0)
        result = analyse(NB2, frame, {"Response": "Count", "Predictors": ["Dose", "Batch"],
                                      "Categorical predictors": ["Batch"], "Exposure": "Exposure",
                                      "Dispersion mode": "Estimated ML"})
        coefficients, fit = result.tables["Coefficients"], result.tables["Model fit"].iloc[0]
        close(coefficients["Estimate"], model.params.iloc[:-1], rtol=1e-8, atol=1e-9)
        close(fit["Alpha"], model.params.iloc[-1], rtol=1e-8)
        # statsmodels inverts the observed Hessian of (beta, alpha): the same covariance block.
        close(coefficients["SE"], model.bse.iloc[:-1], rtol=1e-7)
        close(fit["Log likelihood"], model.llf, rtol=1e-12)
        close(fit["AIC"], model.aic, rtol=1e-12)
        self.assertEqual(fit["Parameters"], 5)

    def test_the_log_likelihood_keeps_every_constant(self):
        result = analyse(NB2, batches(), {"Response": "Count", "Predictors": ["Dose"], "Exposure": "Exposure",
                                          "Dispersion mode": "Fixed", "Dispersion alpha": 2.5})
        rows, fit = result.tables["Fitted values"], result.tables["Model fit"].iloc[0]
        mu = rows["Fitted count"].to_numpy()
        expected = nbinom.logpmf(rows["Observed"].to_numpy(), 1 / 2.5, 1 / (1 + 2.5 * mu)).sum()
        close(fit["Log likelihood"], expected, rtol=1e-13)
        close(fit["AIC"], -2 * expected + 2 * 2, rtol=1e-13)
        close(rows["Variance"], mu + 2.5 * mu ** 2, rtol=1e-14)
        close(rows["Pearson residual"], (rows["Observed"] - mu) / np.sqrt(mu + 2.5 * mu ** 2), rtol=1e-13)


class ExposureTests(unittest.TestCase):
    def test_multiplying_every_exposure_moves_only_the_intercept(self):
        for mode in ("Fixed", "Estimated ML"):
            frame = batches()
            options = {"Response": "Count", "Predictors": ["Dose", "Batch"], "Categorical predictors": ["Batch"],
                       "Exposure": "Exposure", "Dispersion mode": mode}
            before = analyse(NB2, frame, options)
            frame["Exposure"] *= 3
            after = analyse(NB2, frame, options)
            shift = after.tables["Coefficients"]["Estimate"] - before.tables["Coefficients"]["Estimate"]
            close(shift, [-log(3), 0, 0, 0], rtol=0, atol=1e-9)
            close(after.tables["Coefficients"]["SE"], before.tables["Coefficients"]["SE"], rtol=1e-8)
            close(after.tables["Fitted values"]["Fitted count"], before.tables["Fitted values"]["Fitted count"],
                  rtol=1e-9)
            close(after.tables["Fitted values"]["Fitted rate"] * 3, before.tables["Fitted values"]["Fitted rate"],
                  rtol=1e-9)
            close(after.tables["Model fit"]["Alpha"], before.tables["Model fit"]["Alpha"], rtol=1e-9)

    def test_without_exposure_the_offset_is_zero_and_the_exposure_column_is_one(self):
        frame = counts()
        with_unit = frame.assign(Exposure=1.0)
        a = run(frame, Exposure=None)
        b = run(with_unit)
        pd.testing.assert_frame_equal(a.tables["Coefficients"], b.tables["Coefficients"], rtol=1e-12)
        self.assertTrue((a.tables["Fitted values"]["Exposure"] == 1.0).all())
        close(a.tables["Fitted values"]["Fitted rate"], a.tables["Fitted values"]["Fitted count"], rtol=0)

    def test_an_empty_exposure_is_an_incomplete_row_and_an_infinite_one_an_error(self):
        frame = counts().astype({"Exposure": float})
        frame.loc[3, "Exposure"] = np.nan
        result = run(frame)
        self.assertEqual(result.tables["Fitted values"]["Source row"].tolist(), [1, 2, 3, *range(5, 17)])
        self.assertEqual(result.tables["Model fit"]["Incomplete rows"].iloc[0], 1)
        for bad in (0.0, -2.0, np.inf, -np.inf, "abc", "nan"):
            frame = counts().astype({"Exposure": object})
            frame.loc[5, "Exposure"] = bad
            with self.assertRaises(FieldError) as raised:
                run(frame)
            self.assertEqual(raised.exception.field, "Exposure", bad)
            self.assertIn("row 6", str(raised.exception))


class RowTests(unittest.TestCase):
    def test_source_rows_are_physical_positions_with_a_duplicated_index(self):
        frame = counts().astype({"Count": float})
        frame.index = [37] * len(frame)
        frame.iloc[2, 0] = np.nan
        frame.iloc[9, 1] = np.nan
        result = run(frame)
        rows = result.tables["Fitted values"]
        self.assertEqual(rows["Source row"].tolist(), [1, 2, *range(4, 10), *range(11, 17)])
        self.assertEqual(rows["Observed"].tolist(), frame["Count"].iloc[rows["Source row"] - 1].tolist())
        self.assertEqual(rows["Exposure"].tolist(), frame["Exposure"].iloc[rows["Source row"] - 1].tolist())
        self.assertEqual(result.tables["Model fit"]["Incomplete rows"].iloc[0], 2)
        self.assertTrue(rows.index.equals(pd.RangeIndex(len(rows))))

    def test_a_zero_count_is_a_value_and_an_empty_cell_is_missing(self):
        frame = counts().astype({"Count": object})
        frame.loc[0, "Count"] = "  "
        result = run(frame)
        rows = result.tables["Fitted values"]
        self.assertEqual(rows["Source row"].tolist(), list(range(2, 17)))
        self.assertIn(0.0, rows["Observed"].tolist())
        self.assertEqual(result.tables["Model fit"]["N"].iloc[0], 15)

    def test_the_worksheet_is_not_modified(self):
        frame = counts()
        before = frame.copy()
        run(frame, Predictors=["Treatment", "Batch"], **{"Categorical predictors": ["Batch"]})
        pd.testing.assert_frame_equal(frame, before)


class FieldErrorTests(unittest.TestCase):
    def raises(self, field, call, contains=None):
        with self.assertRaises(FieldError) as raised:
            call()
        self.assertEqual(raised.exception.field, field, str(raised.exception))
        if contains:
            self.assertIn(contains, str(raised.exception))
        return str(raised.exception)

    def bad_cell(self, column, value, field, row=1):
        frame = counts().astype({column: object})
        frame.loc[row, column] = value
        return self.raises(field, lambda: run(frame), f"row {row + 1}")

    def test_cells_that_do_not_suit_their_role(self):
        for value in (1.25, -1, np.inf, "abc", "nan", True + 0.5):
            self.bad_cell("Count", value, "Response")
        for value in ("abc", np.inf, "1,5"):
            self.bad_cell("Treatment", value, "Predictors")
        self.assertIn('"Count"', self.bad_cell("Count", 2.5, "Response"))

    def test_data_errors(self):
        self.raises("Response", lambda: run(counts().assign(Count=0)), "at least one observed event")
        self.raises("Response", lambda: run(counts().assign(Count=np.nan)), "No row")
        doubled = counts().assign(Double=lambda f: 2 * f["Treatment"])
        self.raises("Predictors", lambda: run(doubled, Predictors=["Treatment", "Double"]), "rank deficient")
        self.raises("Categorical predictors",
                    lambda: run(counts().assign(Batch="A"), Predictors=["Treatment", "Batch"],
                                **{"Categorical predictors": ["Batch"]}), "2 to 100 levels")
        self.raises("Predictors", lambda: run(counts().iloc[:2]), "coefficients for 2 complete rows")

    def test_budgets_are_checked_before_the_design_is_built(self):
        big = pd.DataFrame({"Count": np.ones(50_001), "X": np.arange(50_001.0)})
        with patch.object(nb, "_design", side_effect=AssertionError("built")):
            self.raises("Response", lambda: analyse(NB2, big, {"Response": "Count", "Predictors": ["X"]}),
                        "50,001 complete rows")
            wide = pd.DataFrame({"Count": np.arange(200) % 7, "X": np.arange(200.0),
                                 "Site": [f"S{i % 40}" for i in range(200)]})
            self.raises("Categorical predictors", lambda: analyse(NB2, wide, {
                "Response": "Count", "Predictors": ["X", "Site"], "Categorical predictors": ["Site"]}),
                "41 coefficients; the limit is 32")
            many = wide.assign(Site=[f"S{i}" for i in range(200)])
            self.raises("Categorical predictors", lambda: analyse(NB2, many, {
                "Response": "Count", "Predictors": ["X", "Site"], "Categorical predictors": ["Site"]}),
                "2 to 100 levels")

    def test_option_errors(self):
        frame = counts()
        cases = [
            ("Response", {"Response": None}), ("Response", {"Response": "Missing"}),
            ("Predictors", {"Predictors": []}), ("Predictors", {"Predictors": "Treatment"}),
            ("Predictors", {"Predictors": ["Treatment", "Treatment"]}),
            ("Predictors", {"Predictors": ["Treatment", "Count"]}),
            ("Predictors", {"Predictors": [f"P{i}" for i in range(9)]}),
            ("Categorical predictors", {"Categorical predictors": ["Batch"]}),
            ("Exposure", {"Exposure": "Count"}), ("Exposure", {"Exposure": "Treatment"}),
            ("Exposure", {"Exposure": "Missing"}),
            ("Dispersion mode", {"Dispersion mode": "Wrong"}), ("Dispersion mode", {"Dispersion mode": None}),
            ("Dispersion alpha", {"Dispersion alpha": 0}), ("Dispersion alpha", {"Dispersion alpha": 1001}),
            ("Dispersion alpha", {"Dispersion alpha": 9e-7}), ("Dispersion alpha", {"Dispersion alpha": np.nan}),
            ("Dispersion alpha", {"Dispersion alpha": True}), ("Dispersion alpha", {"Dispersion alpha": "0.5"}),
            ("Confidence level (%)", {"Confidence level (%)": 0}),
            ("Confidence level (%)", {"Confidence level (%)": 100}),
            ("Confidence level (%)", {"Confidence level (%)": np.inf}),
            ("Confidence level (%)", {"Confidence level (%)": False}),
            ("Residual plot", {"Residual plot": "yes"}),
        ]
        wide = frame.assign(**{f"P{i}": float(i) for i in range(9)})
        for field, change in cases:
            self.raises(field, lambda: run(wide, **change))
        # The limits of the alpha domain are accepted.
        for alpha in (1e-6, 1000):
            self.assertEqual(run(**{"Dispersion alpha": alpha}).tables["Model fit"]["Alpha"].iloc[0], alpha)

    def test_alpha_is_not_read_by_estimated_ml(self):
        a = run(**{"Dispersion mode": "Estimated ML", "Dispersion alpha": "garbage"})
        b = analyse(NB2, counts(), {k: v for k, v in BASE.items() if k != "Dispersion alpha"}
                    | {"Dispersion mode": "Estimated ML"})
        pd.testing.assert_frame_equal(a.tables["Coefficients"], b.tables["Coefficients"])

    def test_the_poisson_boundary_and_the_upper_limit_have_no_ml_estimate(self):
        boundary = pd.read_csv(DATA / "poisson-boundary.csv")
        message = self.raises("Dispersion mode", lambda: run(boundary, **{"Dispersion mode": "Estimated ML"}),
                              "Poisson boundary")
        self.assertIn("alpha = 0", message)
        # Fixed remains available on the same data and stays close to Poisson for a small alpha.
        fixed = run(boundary, **{"Dispersion alpha": 1e-6})
        poisson = analyse("Multiple regression", boundary, {"Response": "Count", "Predictors": ["Treatment"],
                                                            "Categorical predictors": [], "Family": "Poisson",
                                                            "Exposure": "Exposure"})
        close(fixed.tables["Coefficients"]["Estimate"], poisson.tables["Coefficients"]["Estimate"], rtol=1e-6)
        y = np.zeros(1000)
        y[0] = y[-1] = 10_000
        heavy = pd.DataFrame({"Count": y, "Treatment": np.r_[np.zeros(500), np.ones(500)]})
        self.raises("Dispersion mode", lambda: run(heavy, Exposure=None, **{"Dispersion mode": "Estimated ML"}),
                    "beyond alpha = 1000")

    def test_separation_does_not_return_an_estimate(self):
        frame = counts()
        frame.loc[frame["Treatment"] == 1, "Count"] = 0
        self.raises("Predictors", lambda: run(frame), "did not converge")
        self.raises("Dispersion mode", lambda: run(frame, **{"Dispersion mode": "Estimated ML"}), "did not converge")

    def test_a_maximum_on_a_grid_edge_is_never_reported(self):
        with patch.object(nb, "_GRID", nb._GRID[:6]):
            frame = batches()
            self.raises("Dispersion mode", lambda: analyse(NB2, frame, {
                "Response": "Count", "Predictors": ["Dose"], "Exposure": "Exposure",
                "Dispersion mode": "Estimated ML"}), "beyond alpha")

    def test_an_unusable_hessian_names_dispersion_mode(self):
        with patch.object(nb, "_alpha_curvature", return_value=1.0):
            self.raises("Dispersion mode", lambda: run(**{"Dispersion mode": "Estimated ML"}),
                        "not positive definite")


class NumericTests(unittest.TestCase):
    def test_alpha_score_and_curvature_match_differences_of_the_log_likelihood(self):
        rng = np.random.default_rng(13)
        y = rng.integers(0, 40, 30).astype(float)
        mu = rng.uniform(0.2, 30, 30)
        for alpha in (1e-4, 0.03, 0.7, 8.0, 400.0):
            h = alpha * 1e-3

            def ll(a):
                return nb.loglik_rows(y, mu, a).sum()

            def derivative(f):  # fourth-order central difference: truncation and rounding both well below 1e-6
                return (f(alpha - 2 * h) - 8 * f(alpha - h) + 8 * f(alpha + h) - f(alpha + 2 * h)) / (12 * h)

            close(nb.alpha_score(y, mu, alpha), derivative(ll), rtol=1e-6, atol=1e-6)
            close(nb._alpha_curvature(y, mu, alpha), derivative(lambda a: nb.alpha_score(y, mu, a)),
                  rtol=1e-6, atol=1e-6)

    def test_the_score_reaches_the_overdispersion_statistic_at_the_poisson_limit(self):
        rng = np.random.default_rng(5)
        y = rng.integers(0, 25, 50).astype(float)
        mu = rng.uniform(1, 20, 50)
        close(nb.alpha_score(y, mu, 1e-10), 0.5 * np.sum((y - mu) ** 2 - y), rtol=1e-7)

    def test_large_counts_use_the_digamma_form_with_the_same_value(self):
        rng = np.random.default_rng(8)
        y = rng.integers(0, 80, 25).astype(float)
        mu = rng.uniform(1, 60, 25)
        for alpha in (1e-3, 0.4, 6.0):
            exact = nb.alpha_score(y, mu, alpha), nb._alpha_curvature(y, mu, alpha)
            with patch.object(nb, "_TABLE_LIMIT", 3):
                close((nb.alpha_score(y, mu, alpha), nb._alpha_curvature(y, mu, alpha)), exact, rtol=1e-10)

    def test_the_log_likelihood_matches_scipy_over_the_alpha_range(self):
        y = np.array([0, 1, 4, 13, 250.0])
        mu = np.array([0.4, 2.5, 3.0, 9.0, 180.0])
        for alpha in (1e-6, 0.01, 1.0, 1000.0):
            close(nb.loglik_rows(y, mu, alpha), nbinom.logpmf(y, 1 / alpha, 1 / (1 + alpha * mu)), rtol=1e-9)


class OutputTests(unittest.TestCase):
    def test_the_residual_plot_draws_the_fitted_sheet(self):
        result = run(**{"Residual plot": True})
        axes, = result.figure.axes
        rows = result.tables["Fitted values"]
        offsets = axes.collections[0].get_offsets()
        close(offsets[:, 0], rows["Fitted count"], rtol=0)
        close(offsets[:, 1], rows["Pearson residual"], rtol=0)
        self.assertEqual([tuple(line.get_ydata()) for line in axes.lines], [(0, 0)])
        self.assertEqual((axes.get_title(), axes.get_xlabel(), axes.get_ylabel()),
                         ("Negative binomial residuals", "Fitted count", "Pearson residual"))
        for extension, magic in (("svg", b"<svg"), ("pdf", b"%PDF"), ("png", b"\x89PNG")):
            buffer = BytesIO()
            result.figure.savefig(buffer, format=extension)
            self.assertIn(magic, buffer.getvalue()[:300])

    def test_one_fit_per_calculation(self):
        with patch.object(nb, "fit", wraps=nb.fit) as fitted, patch.object(nb, "fit_beta", wraps=nb.fit_beta) as beta:
            run(**{"Residual plot": True})
        self.assertEqual(fitted.call_count, 1)
        self.assertEqual(beta.call_count, 1)

    def test_check_options_never_fits(self):
        with patch.object(nb, "fit_beta", side_effect=AssertionError("fitted")):
            nb.check_options(counts(), BASE | {"Dispersion mode": "Estimated ML"})
            boundary = pd.read_csv(DATA / "poisson-boundary.csv")
            nb.check_options(boundary, BASE | {"Dispersion mode": "Estimated ML"})

    def test_the_visibility_of_alpha_follows_the_mode(self):
        self.assertEqual(nb.visibility("Fixed"), {"Dispersion alpha": True})
        self.assertEqual(nb.visibility("Estimated ML"), {"Dispersion alpha": False})

    def test_poisson_recipes_of_multiple_regression_ignore_the_new_keys(self):
        options = {"Response": "Count", "Predictors": ["Treatment"], "Categorical predictors": [],
                   "Family": "Poisson", "Exposure": "Exposure"}
        baseline = analyse("Multiple regression", counts(), options)
        extra = analyse("Multiple regression", counts(), options | {"Dispersion mode": "Wrong",
                                                                    "Dispersion alpha": -1})
        self.assertEqual(list(extra.tables), list(baseline.tables))
        for name in baseline.tables:
            pd.testing.assert_frame_equal(extra.tables[name], baseline.tables[name], check_exact=True)
        close(baseline.tables["Coefficients"]["Estimate"], EXPECTED["fixed"]["beta"])


if __name__ == "__main__":
    unittest.main()
