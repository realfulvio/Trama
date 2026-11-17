"""Global fit custom equation: joint algebra, scales, constraints and recipe handling.

Expected numbers come from a design matrix written here, not from the solver under test and not
from the packet oracles.
"""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import curve_models
from analisi import global_custom_fit as engine
from analisi.custom_fit import CUSTOM_EQUATION
from analisi.data import Dataset, load_project, save_project
from analisi.field_error import FieldError
from analisi.global_custom_fit import GLOBAL_CUSTOM_EQUATION, check_options, global_custom_fit, series_in
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "global_custom"
SHARED = pd.read_csv(DATA / "shared-linear.csv").set_index("source_row")


def coefficient(name, start=1.0, lower=None, upper=None, *, fixed=False, shared=False):
    return {"name": name, "start": start, "lower": lower, "upper": upper, "fixed": fixed, "shared": shared}


def recipe(**extra):
    options = {
        "X": "X", "Y": "Y", "Group": "Group", "Equation": "A + B*X",
        "Parameters": [coefficient("A", shared=False), coefficient("B", shared=True)],
        "Series constraints": [], "Weighting": "Unweighted", "SD column": None,
        "Confidence level (%)": 95.0, "Curve points": 21,
    }
    options.update(extra)
    return options


def fit(frame=SHARED, **extra):
    return global_custom_fit(frame, recipe(**extra))


def rejected(test, field, frame=SHARED, **extra):
    with test.assertRaises(FieldError) as caught:
        fit(frame, **extra)
    test.assertEqual(caught.exception.field, field, str(caught.exception))
    return str(caught.exception)


def _group(value):
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return value


def by_key(frame):
    found = {}
    for record in frame.to_dict("records"):
        found[(record["Scope"], _group(record["Group"]), record["Parameter"])] = record
    return found


def design_wls(frame, sd_column=None):
    """Joint straight line: one intercept column per series and one shared slope. Independent of the engine."""
    rows = frame.loc[frame["Group"].notna() & frame["X"].notna() & frame["Y"].notna()]
    labels = list(dict.fromkeys(str(value) for value in rows["Group"]))
    groups = np.array([str(value) for value in rows["Group"]])
    x = rows["X"].to_numpy(dtype=float)
    y = rows["Y"].to_numpy(dtype=float)
    scale = np.ones(len(rows)) if sd_column is None else rows[sd_column].to_numpy(dtype=float)
    design = np.zeros((len(rows), len(labels) + 1))
    for index, label in enumerate(labels):
        design[groups == label, index] = 1.0
    design[:, -1] = x
    weighted = design / scale[:, None]
    beta = np.linalg.lstsq(weighted, y / scale, rcond=None)[0]
    residual = y / scale - weighted @ beta
    df = len(rows) - design.shape[1]
    covariance = np.linalg.inv(weighted.T @ weighted) * float(residual @ residual) / df
    return labels, beta, covariance, float(np.sum(((y - design @ beta) / scale) ** 2)), rows


class JointAlgebraTests(unittest.TestCase):
    def test_empty_text_group_does_not_duplicate_an_estimated_coefficient_as_fixed(self):
        frame = SHARED.assign(Group=SHARED["Group"].replace({"A": ""}))
        parameters = fit(frame).tables["Parameters"]
        self.assertEqual(len(parameters), 3)
        self.assertEqual(parameters["Scope"].tolist(), ["Shared", "Local", "Local"])
        self.assertEqual(parameters.loc[parameters["Scope"] == "Local", "Group"].tolist(), ["", "B"])

    def test_series_limits_must_also_contain_a_common_fixed_coefficient(self):
        options = recipe(**{
            "Parameters": [coefficient("A", 1., fixed=True), coefficient("B", shared=True)],
            "Series constraints": [{"series": "A", "parameters": {"A": {"lower": 2., "upper": 5.}}}],
        })
        for run in (check_options, global_custom_fit):
            with self.subTest(stage=run.__name__):
                with self.assertRaises(FieldError) as caught:
                    run(SHARED, options)
                self.assertEqual(caught.exception.field, "Series constraints")

    def test_common_fixed_value_on_the_series_limit_is_valid(self):
        result = fit(**{
            "Parameters": [coefficient("A", 1., fixed=True), coefficient("B", shared=True)],
            "Series constraints": [{"series": "A", "parameters": {"A": {"lower": 1., "upper": 5.}}}],
        })
        self.assertEqual(by_key(result.tables["Parameters"])[("Fixed", None, "A")]["Estimate"], 1.)

    def test_shared_slope_matches_the_design_matrix_and_crosses_series(self):
        labels, beta, covariance, wsse, rows = design_wls(SHARED)
        result = fit()
        table = by_key(result.tables["Parameters"])
        intercept = [beta[labels.index(label)] for label in ("A", "B")]
        np.testing.assert_allclose(table[("Shared", None, "B")]["Estimate"], beta[-1], rtol=1e-8)
        np.testing.assert_allclose([table[("Local", label, "A")]["Estimate"] for label in ("A", "B")], intercept, rtol=1e-8)
        matrix = result.tables["Covariance"]
        # Free coordinates: shared slope, then each series intercept. Cross-series covariance stays.
        arranged = covariance[np.ix_([-1, *range(len(labels))], [-1, *range(len(labels))])]
        np.testing.assert_allclose(matrix.to_numpy(), arranged, rtol=1e-6, atol=1e-10)
        cross = float(matrix.to_numpy()[1, 2])
        self.assertGreater(abs(cross), 1e-6)
        self.assertAlmostEqual(cross, float(arranged[1, 2]), places=8)
        self.assertAlmostEqual(float(result.tables["Global fit"].loc["Weighted residual SS", "Value"]), wsse, places=8)
        self.assertEqual(result.tables["Residuals"]["Source row"].tolist(), [int(value) for value in rows.index])
        self.assertEqual(int(result.tables["Global fit"].loc["Observations", "Value"]), len(rows))

    def test_a_common_sd_factor_and_a_tiny_response_keep_the_normalised_answer(self):
        _labels, _beta, covariance, wsse, _rows = design_wls(SHARED, "SD")
        arranged = covariance[np.ix_([-1, 0, 1], [-1, 0, 1])]
        weighted = {"Weighting": "Inverse variance (column)", "SD column": "SD"}
        for factor in (1.0, 1e100, 1e-100):
            scaled = SHARED.assign(SD=SHARED["SD"] * factor)
            result = fit(scaled, **weighted)
            np.testing.assert_allclose(result.tables["Covariance"].to_numpy(), arranged, rtol=1e-5, atol=1e-12)
            got = float(result.tables["Global fit"].loc["Weighted residual SS", "Value"])
            self.assertAlmostEqual(got * factor ** 2, wsse, places=5)
        unweighted = fit()
        tiny = SHARED.assign(Y=SHARED["Y"] * 1e-12)
        options = recipe()
        options["Parameters"] = [coefficient("A", 1e-12), coefficient("B", 1e-12, shared=True)]
        result = global_custom_fit(tiny, options)
        np.testing.assert_allclose(result.tables["Parameters"]["Estimate"],
                                   unweighted.tables["Parameters"]["Estimate"].to_numpy() * 1e-12,
                                   rtol=1e-6, atol=1e-18)
        np.testing.assert_allclose(result.tables["Covariance"].to_numpy(),
                                   unweighted.tables["Covariance"].to_numpy() * 1e-24, rtol=1e-5, atol=1e-30)

    def test_source_index_is_kept_when_it_is_duplicated(self):
        frame = pd.DataFrame({"X": [0., 1, 0, 1], "Y": [1., 3, 2, 4], "Group": ["A", "A", "B", "B"]})
        frame.index = [5, 5, 7, 8]
        rows = fit(frame).tables["Residuals"]["Source row"].tolist()
        self.assertEqual(rows, [5, 5, 7, 8])

    def test_input_frame_and_options_stay_unchanged(self):
        frame = SHARED.copy(deep=True)
        options = recipe()
        snapshot = copy.deepcopy(options)
        fit(frame)
        pd.testing.assert_frame_equal(frame, SHARED)
        self.assertEqual(options, snapshot)

    def test_unweighted_fit_does_not_read_a_text_sd_column(self):
        frame = SHARED.assign(Note="not a number")
        result = fit(frame, **{"SD column": "Note"})
        self.assertEqual(result.tables["Residuals"]["SD"].tolist(), [1.0] * len(result.tables["Residuals"]))

    def test_constraints_rank_and_bounds_name_their_field(self):
        rejected(self, "Series constraints", **{"Series constraints": [
            {"series": "missing", "parameters": {"A": {"fixed": 1.0}}}]})
        rejected(self, "Series constraints", **{"Series constraints": [
            {"series": "A", "parameters": {"B": {"lower": 3.0}}},
            {"series": "B", "parameters": {"B": {"upper": 2.0}}}]})
        rejected(self, "Parameters", Equation="A + B + C*X", Parameters=[
            coefficient("A"), coefficient("B"), coefficient("C", shared=True)])
        rejected(self, "Parameters", Parameters=[coefficient("B", fixed=True, shared=True), coefficient("A")])
        bound = fit(**{"Series constraints": [
            {"series": "A", "parameters": {"B": {"upper": 1.7}}},
            {"series": "B", "parameters": {"B": {"upper": 1.5}}}]})
        slope = bound.tables["Parameters"].set_index(["Scope", "Group", "Parameter"]).loc[("Shared", None, "B")]
        self.assertEqual(float(slope["Estimate"]), 1.5)
        self.assertEqual(slope["Status"], "At bound")
        self.assertTrue(bound.tables["Covariance"].isna().all().all())
        locals_ = bound.tables["Parameters"]
        self.assertEqual(locals_.loc[locals_["Scope"] == "Local", "Status"].tolist(), ["Estimated", "Estimated"])
        self.assertTrue(locals_.loc[locals_["Scope"] == "Local", "SE"].isna().all())

    def test_all_fixed_keeps_a_real_residual_and_an_empty_covariance(self):
        result = fit(Parameters=[coefficient("A", 1.0, fixed=True), coefficient("B", 2.0, fixed=True)])
        summary = result.tables["Global fit"]["Value"]
        self.assertEqual(int(summary["Free parameters"]), 0)
        self.assertGreater(float(summary["Residual SS"]), 1.0)
        self.assertEqual(result.tables["Covariance"].shape, (0, 0))
        self.assertTrue(result.tables["Parameters"]["SE"].isna().all())

    def test_check_options_does_not_call_the_solver(self):
        with patch.object(engine, "_solve", side_effect=AssertionError("solver started")):
            check_options(SHARED, recipe())
        with patch.object(engine, "_solve", side_effect=FieldError("Parameters", "Injected worker failure")):
            with self.assertRaises(FieldError) as caught:
                fit()
        self.assertEqual(caught.exception.field, "Parameters")
        self.assertIn("Injected worker failure", str(caught.exception))

    def test_series_in_follows_first_appearance_and_survives_a_partial_recipe(self):
        self.assertEqual(series_in(SHARED, recipe()), ["A", "B"])
        self.assertEqual(series_in(SHARED, recipe(Group=None)), [])

    def test_legacy_custom_equation_recipe_has_no_shared_flag(self):
        frame = pd.DataFrame({"X": [0., 1, 2], "Y": [1., 3, 5]})
        options = {"X": "X", "Y": "Y", "Group": None, "Equation": "A + B*X",
                   "Parameters": [{"name": "A", "start": 1.0, "lower": None, "upper": None, "fixed": False},
                                  {"name": "B", "start": 1.0, "lower": None, "upper": None, "fixed": False}],
                   "Weighting": "Unweighted", "SD column": None, "Confidence level (%)": 95.0, "Curve points": 20}
        result = analyse(CUSTOM_EQUATION, frame, options)
        np.testing.assert_allclose(result.tables["Parameters: All"]["Estimate"], [1.0, 2.0], rtol=1e-6)
        rejected(self, "Parameters", Parameters=[{"name": "A", "start": 1.0, "lower": None, "upper": None, "fixed": False},
                                                 {"name": "B", "start": 1.0, "lower": None, "upper": None, "fixed": False}])


class RecipeTests(unittest.TestCase):
    def test_method_is_listed_once_and_draws_a_graph(self):
        self.assertEqual(GROUPS["Regression and Curves"].count(GLOBAL_CUSTOM_EQUATION), 1)
        self.assertIn(GLOBAL_CUSTOM_EQUATION, METHODS)
        self.assertIn(GLOBAL_CUSTOM_EQUATION, GRAPH_METHODS)
        self.assertIsNotNone(fit().figure)

    def test_catalog_of_named_models_is_not_modified(self):
        before = dict(curve_models.MODELS)
        fit()
        self.assertEqual(before, curve_models.MODELS)

    def test_recipe_round_trips_with_booleans_and_series_constraints(self):
        options = recipe(**{"Series constraints": [{"series": "A", "parameters": {"A": {"fixed": 1.0}}}]})
        dataset = Dataset(SHARED.reset_index(drop=True))
        dataset.analyses.append((GLOBAL_CUSTOM_EQUATION, options))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "global.alab"
            save_project(path, {"T": dataset})
            loaded = load_project(path)
        method, restored = list(loaded.values())[0].analyses[0]
        self.assertEqual(method, GLOBAL_CUSTOM_EQUATION)
        self.assertIs(restored["Parameters"][1]["shared"], True)
        self.assertIs(restored["Parameters"][0]["fixed"], False)
        self.assertEqual(restored["Series constraints"], options["Series constraints"])


if __name__ == "__main__":
    unittest.main()
