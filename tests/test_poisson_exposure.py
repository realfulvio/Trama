"""Poisson regression with an optional exposure column and diagnostics."""
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.genmod.families import Poisson
from statsmodels.genmod.generalized_linear_model import GLM

from analisi import models
from analisi.additional import regression_visibility
from analisi.processing import FieldError
from analisi.workbench import analyse

FIXTURE = Path(__file__).parent / "data" / "poisson-exposure.csv"
LEGACY_COLUMNS = ["Observed", "Fitted", "Residual"]
DIAGNOSTIC_COLUMNS = [*LEGACY_COLUMNS, "Source row", "Exposure", "Fitted rate", "Pearson residual", "Deviance residual"]


def fixture():
    return pd.read_csv(FIXTURE)


def fit(frame, exposure="Exposure", diagnostics=True, predictors=("Group",), categories=("Group",)):
    return models.regression(frame, "Count", list(predictors), list(categories), "Poisson",
                             exposure=exposure, diagnostics=diagnostics)


def options(**extra):
    return {"Response": "Count", "Predictors": ["Group"], "Categorical predictors": ["Group"], "Family": "Poisson",
            **extra}


class AnalyticFixtureTests(unittest.TestCase):
    """Values derived by hand for rates 1 and 3 in the synthetic fixture."""

    def test_rates_coefficients_and_fitted_counts(self):
        tables = fit(fixture())
        coeff = tables["Coefficients"]
        self.assertEqual(list(coeff.index), ["Intercept", "Group [1]"])
        np.testing.assert_allclose(coeff["Estimate"], [0, np.log(3)], atol=1e-9)
        np.testing.assert_allclose(coeff.loc["Group [1]", "Exp(estimate)"], 3, rtol=1e-9)
        self.assertEqual(tables["Reference levels"].loc["Group", "Reference"], "0")
        fitted = tables["Fitted values"]
        self.assertEqual(list(fitted.columns), DIAGNOSTIC_COLUMNS)
        np.testing.assert_allclose(fitted["Fitted"], [1, 2, 3, 3, 3, 3], rtol=1e-9)
        np.testing.assert_allclose(fitted["Fitted rate"], [1, 1, 1, 3, 3, 3], rtol=1e-9)
        np.testing.assert_array_equal(fitted["Exposure"], [1, 2, 3, 1, 1, 1])
        np.testing.assert_array_equal(fitted["Source row"], range(6))

    def test_deviance_pearson_and_ratios(self):
        tables = fit(fixture())
        report = tables[models.POISSON_DIAGNOSTICS]["Value"]
        self.assertAlmostEqual(report["Deviance"], 10.6192227463, places=9)
        self.assertAlmostEqual(report["Pearson χ²"], 7.3333333333, places=8)  # IRLS convergence tolerance
        self.assertEqual(report["Residual df"], 4)
        self.assertAlmostEqual(report["Deviance / df"], 10.6192227463 / 4, places=9)
        self.assertAlmostEqual(report["Pearson χ² / df"], 7.3333333333 / 4, places=9)
        fitted = tables["Fitted values"]
        self.assertAlmostEqual(fitted["Pearson residual"].iat[0], -1, places=9)
        self.assertAlmostEqual(fitted["Deviance residual"].iat[0], -np.sqrt(2), places=9)

    def test_diagnostics_follow_the_written_formulas(self):
        frame = fixture()
        fitted = fit(frame)["Fitted values"]
        y, mu = frame["Count"].to_numpy(float), fitted["Fitted"].to_numpy()
        pearson = (y - mu) / np.sqrt(mu)
        with np.errstate(divide="ignore", invalid="ignore"):
            first = np.where(y > 0, y * np.log(y / mu), 0.0)
        unit = 2 * (first - (y - mu))
        np.testing.assert_allclose(fitted["Pearson residual"], pearson, atol=1e-9)
        # Roundoff can make the theoretically zero contribution slightly negative when y ≈ mu.
        self.assertTrue((unit >= -1e-12).all())
        residual = np.sign(y - mu) * np.sqrt(np.maximum(unit, 0.0))
        np.testing.assert_allclose(fitted["Deviance residual"], residual, atol=1e-7)
        self.assertAlmostEqual(unit.sum(), 10.6192227463, places=9)
        self.assertAlmostEqual((pearson ** 2).sum(), 7.3333333333, places=8)  # IRLS convergence tolerance

    def test_doubling_exposure_moves_only_the_intercept(self):
        frame = fixture()
        doubled = frame.assign(Exposure=frame["Exposure"] * 2)
        base, scaled = fit(frame), fit(doubled)
        delta = base["Coefficients"]["Estimate"] - scaled["Coefficients"]["Estimate"]
        self.assertAlmostEqual(delta["Intercept"], np.log(2), places=9)
        self.assertAlmostEqual(delta["Group [1]"], 0, places=9)
        np.testing.assert_allclose(scaled["Fitted values"]["Fitted"], base["Fitted values"]["Fitted"], rtol=1e-9)
        np.testing.assert_allclose(scaled["Fitted values"]["Fitted rate"], base["Fitted values"]["Fitted rate"] / 2,
                                   rtol=1e-9)

    def test_explicit_unit_exposure_matches_none(self):
        frame = fixture().assign(One=1.0)
        explicit, implicit = fit(frame, exposure="One"), fit(frame, exposure=None)
        for name in ("Coefficients", "Model", models.POISSON_DIAGNOSTICS):
            pd.testing.assert_frame_equal(explicit[name], implicit[name])
        pd.testing.assert_frame_equal(explicit["Fitted values"], implicit["Fitted values"])

    def test_text_groups_keep_names_and_reference(self):
        frame = fixture().assign(Group=lambda f: f["Group"].map({0: "Low", 1: "High"}))
        tables = fit(frame)
        self.assertEqual(list(tables["Coefficients"].index), ["Intercept", "Group [Low]"])
        self.assertEqual(tables["Reference levels"].loc["Group", "Reference"], "High")
        self.assertAlmostEqual(tables["Coefficients"].loc["Group [Low]", "Estimate"], -np.log(3), places=9)
        np.testing.assert_allclose(tables["Fitted values"]["Fitted"], [1, 2, 3, 3, 3, 3], rtol=1e-9)


class ExposureValidationTests(unittest.TestCase):
    def assert_field(self, field, frame, **kwargs):
        with self.assertRaises(FieldError) as raised:
            fit(frame, **kwargs)
        self.assertEqual(raised.exception.field, field)
        return str(raised.exception)

    def test_invalid_exposure_values_name_the_field(self):
        for bad in (0, -1, np.inf, -np.inf, "abc"):
            with self.subTest(bad=bad):
                frame = fixture().astype({"Exposure": object})
                frame.loc[2, "Exposure"] = bad
                message = self.assert_field("Exposure", frame)
                self.assertIn("row 3", message)

    def test_invalid_exposure_wins_over_missing_cells_in_the_same_row(self):
        frame = fixture().astype({"Exposure": object, "Count": float})
        frame.loc[1, ["Count", "Exposure"]] = [np.nan, 0]
        self.assert_field("Exposure", frame)
        frame.loc[1, ["Count", "Exposure"]] = [2, -3]
        frame.loc[1, "Group"] = None
        self.assert_field("Exposure", frame)

    def test_exposure_must_be_a_separate_column(self):
        self.assert_field("Exposure", fixture(), exposure="Count")
        self.assert_field("Exposure", fixture(), exposure="Group")
        self.assert_field("Exposure", fixture(), exposure="Missing")

    def test_counts_must_be_nonnegative_integers_with_an_event(self):
        frame = fixture().astype({"Count": float})
        frame.loc[0, "Count"] = 0.5
        self.assertIn("integer", self.assert_field("Response", frame))
        frame.loc[0, "Count"] = -1
        self.assert_field("Response", frame)
        self.assertIn("event", self.assert_field("Response", fixture().assign(Count=0)))
        self.assertIn("event", self.assert_field("Response", fixture().assign(Count=0), exposure=None))

    def test_missing_or_excluded_exposure_drops_the_row(self):
        frame = fixture().astype({"Exposure": "Float64"})
        frame.loc[1, "Exposure"] = pd.NA  # A masked (excluded) cell arrives as NA.
        frame.loc[4, "Count"] = np.nan
        tables = fit(frame)
        fitted = tables["Fitted values"]
        np.testing.assert_array_equal(fitted["Source row"], [0, 2, 3, 5])
        self.assertEqual(tables["Model"].loc["Incomplete rows", "Value"], 2)
        self.assertEqual(tables[models.POISSON_DIAGNOSTICS].loc["Residual df", "Value"], 2)
        # Group 0 keeps counts 0 and 4 over exposures 1 and 3: rate 1.
        np.testing.assert_allclose(fitted["Fitted rate"], [1, 1, 3, 3], rtol=1e-9)

    def test_exposure_is_rejected_outside_poisson(self):
        for family in ("Linear", "Logistic"):
            with self.subTest(family=family), self.assertRaises(ValueError):
                models.regression(fixture(), "Count", ["Group"], ["Group"], family, exposure="Exposure")


class RecipeTests(unittest.TestCase):
    def test_old_recipe_keeps_three_fitted_columns(self):
        result = analyse("Multiple regression", fixture(), options())
        self.assertEqual(list(result.tables), ["Coefficients", "Model", "Reference levels", "Fitted values"])
        self.assertEqual(list(result.tables["Fitted values"].columns), LEGACY_COLUMNS)
        self.assertIsNone(result.figure)
        np.testing.assert_allclose(result.tables["Fitted values"]["Fitted"], [2, 2, 2, 3, 3, 3], rtol=1e-9)

    def test_blank_exposure_is_unit_exposure(self):
        old = analyse("Multiple regression", fixture(), options())
        blank = analyse("Multiple regression", fixture(), options(Exposure=None, Diagnostics=False))
        pd.testing.assert_frame_equal(old.tables["Coefficients"], blank.tables["Coefficients"])

    def test_exposure_and_diagnostics_from_options(self):
        result = analyse("Multiple regression", fixture(),
                         options(Exposure="Exposure", Diagnostics=True, **{"Residual plot": False}))
        self.assertEqual(list(result.tables)[-1], models.POISSON_DIAGNOSTICS)
        self.assertIsNone(result.figure)

    def test_residual_plot_uses_fitted_counts_and_pearson_residuals(self):
        result = analyse("Multiple regression", fixture(),
                         options(Exposure="Exposure", Diagnostics=True, **{"Residual plot": True}))
        axis = result.figure.axes[0]
        points = axis.collections[0].get_offsets()
        fitted = result.tables["Fitted values"]
        np.testing.assert_allclose(points[:, 0], fitted["Fitted"])
        np.testing.assert_allclose(points[:, 1], fitted["Pearson residual"])
        self.assertEqual(list(axis.lines[0].get_ydata()), [0, 0])
        self.assertEqual((axis.get_xlabel(), axis.get_ylabel()), ("Fitted count", "Pearson residual"))

    def test_residual_plot_needs_diagnostics(self):
        result = analyse("Multiple regression", fixture(), options(Exposure="Exposure", **{"Residual plot": True}))
        self.assertIsNone(result.figure)
        self.assertNotIn(models.POISSON_DIAGNOSTICS, result.tables)

    def test_other_families_ignore_poisson_options(self):
        frame = fixture()
        plain = analyse("Multiple regression", frame, {**options(), "Family": "Linear"})
        extra = analyse("Multiple regression", frame,
                        {**options(), "Family": "Linear", "Exposure": "Exposure", "Diagnostics": True})
        pd.testing.assert_frame_equal(plain.tables["Coefficients"], extra.tables["Coefficients"])
        self.assertEqual(list(extra.tables["Fitted values"].columns), LEGACY_COLUMNS)

    def test_visibility(self):
        linear = {"Linear diagnostics": True, "Linear residual plot": True, "Linear profiles": True,
                  "Linear CI (%)": True}
        hidden = {"Linear diagnostics": False, "Linear residual plot": False, "Linear profiles": False,
                  "Linear CI (%)": False}
        logistic_hidden = {"Logistic diagnostics": False, "Logistic cutoff": False, "Logistic profiles": False,
                           "Logistic confidence (%)": False}
        # The Gaussian weighting is a linear-only choice: unweighted shows only the choice itself.
        gaussian = {"Gaussian weighting": True, "Weight exponent K": False, "Gaussian SD column": False,
                    "Gaussian weight column": False, "Weighted prediction intervals": False}
        gaussian_hidden = dict.fromkeys(gaussian, False)
        self.assertEqual(regression_visibility("Linear", True),
                         {"Exposure": False, "Diagnostics": False, "Residual plot": False, **linear,
                          **gaussian, **logistic_hidden})
        self.assertEqual(regression_visibility("Poisson", False),
                         {"Exposure": True, "Diagnostics": True, "Residual plot": False, **hidden,
                          **gaussian_hidden, **logistic_hidden})
        self.assertTrue(regression_visibility("Poisson", True)["Residual plot"])
        shown = regression_visibility("Logistic", False, logistic_diagnostics_on=True, logistic_profiles=True)
        self.assertFalse(shown["Linear profiles"])
        self.assertTrue(shown["Logistic diagnostics"] and shown["Logistic cutoff"] and shown["Logistic profiles"])
        self.assertTrue(shown["Logistic confidence (%)"])
        self.assertFalse(regression_visibility("Logistic", False)["Logistic cutoff"])


class StatsmodelsComparisonTests(unittest.TestCase):
    """Independent fits through statsmodels with an explicit log offset."""

    @staticmethod
    def frame():
        rng = np.random.default_rng(47)
        n = 120
        dose = rng.uniform(0, 2, n)
        site = rng.choice(["North", "South", "West"], n)
        exposure = rng.uniform(.5, 4, n)
        effect = pd.Series(site).map({"North": 0, "South": .4, "West": -.3}).to_numpy()
        counts = rng.poisson(exposure * np.exp(.2 + .5 * dose + effect))
        return pd.DataFrame({"Count": counts, "Dose": dose, "Site": site, "Exposure": exposure})

    def test_matches_glm_with_log_offset(self):
        frame = self.frame()
        tables = fit(frame, predictors=("Dose", "Site"), categories=("Site",))
        design = pd.DataFrame({"Intercept": 1.0, "Dose": frame["Dose"],
                               "Site [South]": (frame["Site"] == "South") * 1.0,
                               "Site [West]": (frame["Site"] == "West") * 1.0})
        reference = GLM(frame["Count"], design, family=Poisson(), offset=np.log(frame["Exposure"])).fit()
        coeff = tables["Coefficients"]
        np.testing.assert_allclose(coeff["Estimate"], reference.params, rtol=1e-7)
        np.testing.assert_allclose(coeff["SE"], reference.bse, rtol=1e-7)
        np.testing.assert_allclose(coeff["p"], reference.pvalues, rtol=1e-6)
        self.assertAlmostEqual(tables["Model"].loc["Log likelihood", "Value"], reference.llf, places=7)
        report = tables[models.POISSON_DIAGNOSTICS]["Value"]
        self.assertAlmostEqual(report["Deviance"], reference.deviance, places=7)
        self.assertAlmostEqual(report["Pearson χ²"], reference.pearson_chi2, places=7)
        self.assertEqual(report["Residual df"], reference.df_resid)
        fitted = tables["Fitted values"]
        np.testing.assert_allclose(fitted["Fitted"], reference.fittedvalues, rtol=1e-7)
        np.testing.assert_allclose(fitted["Pearson residual"], reference.resid_pearson, rtol=1e-6, atol=1e-9)
        np.testing.assert_allclose(fitted["Deviance residual"], reference.resid_deviance, rtol=1e-6, atol=1e-9)

    def test_diagnostics_do_not_change_standard_errors(self):
        frame = self.frame()
        on = fit(frame, predictors=("Dose", "Site"), categories=("Site",))
        off = fit(frame, diagnostics=False, predictors=("Dose", "Site"), categories=("Site",))
        pd.testing.assert_frame_equal(on["Coefficients"], off["Coefficients"])
        self.assertEqual(list(off["Fitted values"].columns), LEGACY_COLUMNS)


if __name__ == "__main__":
    unittest.main()
