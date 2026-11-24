"""Plot a function: grids, values, derivatives, integral and field errors."""
import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from analisi import plot_function as pf
from analisi.curve_models import MODELS
from analisi.data import Dataset, load_project, save_project
from analisi.processing import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

DATA = Path(__file__).parent / "data" / "plot_function"
CASES = json.loads((DATA / "cases.json").read_text(encoding="utf-8"))
EXPECTED = json.loads((DATA / "expected.json").read_text(encoding="utf-8"))


def curve(name, **parameters):
    return {"name": name, "parameters": parameters}


def options(model="Straight line", curves=None, **fields):
    return {pf.MODEL: model, pf.CURVES: curves or [curve("Line", Intercept=5, Slope=2)], pf.X_SOURCE: pf.LINEAR,
            pf.X_MIN: -2, pf.X_MAX: 2, pf.SEGMENTS: 8, **fields}


def cells(table):
    values = table.astype(object)
    return values.where(values.notna(), None).to_numpy().tolist()


class PlotFunctionTests(unittest.TestCase):
    def rejects(self, field, o, frame=None):
        with self.assertRaises(FieldError) as caught:
            analyse(pf.PLOT_FUNCTION, pd.DataFrame() if frame is None else frame, o)
        self.assertEqual(caught.exception.field, field, str(caught.exception))
        return str(caught.exception)

    def assert_cells(self, actual, expected):
        self.assertEqual(len(actual), len(expected))
        for row, wanted in zip(actual, expected):
            self.assertEqual(len(row), len(wanted))
            for value, target in zip(row, wanted):
                if target is None or isinstance(target, str):
                    self.assertEqual(value, target)
                else:
                    self.assertTrue(math.isclose(value, target, rel_tol=1e-9, abs_tol=1e-9), (value, target))

    def test_fixture_cases_match_the_reference(self):
        frame = pd.read_csv(DATA / "worksheet.csv")
        for name, case in CASES.items():
            with self.subTest(name):
                result = analyse(pf.PLOT_FUNCTION, frame if case[pf.X_SOURCE] == pf.WORKSHEET else pd.DataFrame(),
                                 case)
                self.assertEqual(set(result.tables), {pf.SETTINGS, *EXPECTED[name]})
                for sheet, wanted in EXPECTED[name].items():
                    self.assert_cells(cells(result.tables[sheet]), wanted)

    def test_geometric_grid_and_second_derivative(self):
        result = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), CASES["quadratic-geometric"])
        x = result.tables[pf.VALUES]["X"].to_numpy()
        np.testing.assert_allclose(x, [1, 2, 4, 8, 16])
        self.assertEqual((x[0], x[-1]), (1., 16.))
        np.testing.assert_allclose(result.tables[pf.SECOND]["Quadratic"], 6., rtol=1e-12)

    def test_registered_in_regression_and_graphs(self):
        self.assertIn(pf.PLOT_FUNCTION, GROUPS["Regression and Curves"])
        self.assertIn(pf.PLOT_FUNCTION, GRAPH_METHODS)
        self.assertIs(METHODS[pf.PLOT_FUNCTION], pf.OPTIONS)
        self.assertEqual(pf.PLOTTABLE[0], pf.DEFAULT_MODEL)
        self.assertEqual(set(pf.PLOTTABLE), {name for name, spec in MODELS.items() if not spec.required_shared})
        self.assertNotIn("Two intersecting lines", pf.PLOTTABLE)

    def test_hidden_fields_follow_the_x_source(self):
        self.assertEqual(pf.visibility(pf.WORKSHEET),
                         {pf.X_MIN: False, pf.X_MAX: False, pf.SEGMENTS: False, pf.X_COLUMN: True})
        self.assertEqual(pf.visibility(pf.GEOMETRIC),
                         {pf.X_MIN: True, pf.X_MAX: True, pf.SEGMENTS: True, pf.X_COLUMN: False})
        # Stale worksheet keys do not matter on a generated grid, and stale limits do not matter on a worksheet.
        generated = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), options(**{pf.X_COLUMN: 42}))
        self.assertEqual(len(generated.tables[pf.VALUES]), 9)
        frame = pd.DataFrame({"Dose": [1., 2., 3.]})
        stale = options(**{pf.X_SOURCE: pf.WORKSHEET, pf.X_COLUMN: "Dose", pf.X_MIN: float("nan"),
                           pf.X_MAX: None, pf.SEGMENTS: 1.5})
        self.assertEqual(analyse(pf.PLOT_FUNCTION, frame, stale).tables[pf.VALUES]["X"].tolist(), [1., 2., 3.])

    def test_budget_near_the_limit(self):
        twelve = [curve(f"C{i}", Intercept=i, Slope=1) for i in range(12)]
        # 12 curves × 10,000 points is exactly the budget.
        result = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), options(curves=twelve, **{pf.SEGMENTS: 9999}))
        self.assertEqual(result.tables[pf.VALUES].shape, (10_000, 13))
        message = self.rejects(pf.SEGMENTS, options(curves=twelve, **{pf.SEGMENTS: 10_000}))
        self.assertIn("120,000", message)
        frame = pd.DataFrame({"Dose": np.arange(10_001.)})
        self.assertEqual(len(analyse(pf.PLOT_FUNCTION, frame.iloc[:10_000], options(
            curves=twelve, **{pf.X_SOURCE: pf.WORKSHEET, pf.X_COLUMN: "Dose"})).tables[pf.VALUES]), 10_000)
        self.rejects(pf.X_COLUMN, options(curves=twelve, **{pf.X_SOURCE: pf.WORKSHEET, pf.X_COLUMN: "Dose"}), frame)
        self.rejects(pf.SEGMENTS, options(**{pf.SEGMENTS: 10_001}))
        self.rejects(pf.SEGMENTS, options(**{pf.SEGMENTS: 1}))
        self.rejects(pf.CURVES, options(curves=twelve + [curve("D", Intercept=0, Slope=0)]))

    def test_names_ignore_case_but_keep_spelling(self):
        result = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), options(curves=[
            curve("  Alpha ", Intercept=0, Slope=1), curve("alphA 2", Intercept=1, Slope=1)]))
        self.assertEqual(list(result.tables[pf.VALUES].columns), ["X", "Alpha", "alphA 2"])
        self.assertEqual(result.tables[pf.PARAMETERS]["Curve"].tolist(), ["Alpha", "alphA 2"])
        self.rejects(pf.CURVES, options(curves=[curve("Alpha", Intercept=0, Slope=1),
                                                curve("ALPHA", Intercept=1, Slope=1)]))
        for reserved in ("x", " X "):
            self.rejects(pf.CURVES, options(curves=[curve(reserved, Intercept=0, Slope=1)]))
        self.rejects(pf.CURVES, options(curves=[curve("   ", Intercept=0, Slope=1)]))

    def test_unrepresentable_values_stay_empty(self):
        # 10^(300 + x) overflows for x > 8: those cells stay empty, the others keep their values.
        result = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), options(
            "Semilog line (log Y)", [curve("Large", Intercept=300, Slope=1)], **{
                pf.X_MIN: 0, pf.X_MAX: 10, pf.SEGMENTS: 10, pf.FIRST: True, pf.SECOND: True, pf.INTEGRAL: True}))
        values = result.tables[pf.VALUES]["Large"]
        self.assertTrue(values.iloc[:9].notna().all())
        self.assertTrue(values.iloc[9:].isna().all())
        for sheet in (pf.FIRST, pf.SECOND, pf.INTEGRAL):
            table = result.tables[sheet]["Large"].to_numpy(dtype=float)
            self.assertFalse(np.isinf(table).any(), sheet)
        settings = result.tables[pf.SETTINGS]["Value"]
        self.assertEqual(settings["Non-finite values · Large"], 2)
        integral = result.tables[pf.INTEGRAL]["Large"]
        self.assertTrue(integral.iloc[:9].notna().all() and integral.iloc[9:].isna().all())
        # Overflowing trapezoid sums stop the cumulative integral rather than store infinity.
        near = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), options(
            "Semilog line (log Y)", [curve("Near", Intercept=308, Slope=.01)], **{
                pf.X_MIN: 0, pf.X_MAX: 10, pf.SEGMENTS: 10, pf.INTEGRAL: True}))
        self.assertTrue(near.tables[pf.VALUES]["Near"].notna().all())
        integral = near.tables[pf.INTEGRAL]["Near"].to_numpy(dtype=float)
        self.assertEqual(integral[0], 0.)
        self.assertTrue(np.isnan(integral[-1]) and not np.isinf(integral).any())

    def test_entirely_nonfinite_curve_names_the_curve(self):
        message = self.rejects(pf.CURVES, options("Semilog line (log Y)", [
            curve("Fine", Intercept=0, Slope=1), curve("Overflow", Intercept=400, Slope=1)]))
        self.assertIn("Overflow", message)

    def test_parameter_and_field_errors(self):
        self.rejects(pf.CURVES, options(curves=[curve("A", Intercept=float("inf"), Slope=1)]))
        self.rejects(pf.CURVES, options(curves=[curve("A", Intercept="2", Slope=1)]))
        self.rejects(pf.CURVES, options() | {pf.CURVES: []})
        self.rejects(pf.CURVES, options(curves="A"))
        self.rejects(pf.CURVES, options("Line through point", [curve("A", Slope=1, X0=0)]))
        # Inclusive limits: Percent fast may be 0 or 100 but not beyond.
        model = "Two-phase decay"
        base = dict(zip(MODELS[model].parameters, (10., 1., 0., 1., .1)))
        analyse(pf.PLOT_FUNCTION, pd.DataFrame(), options(model, [curve("A", **base)], **{pf.X_MIN: 0}))
        analyse(pf.PLOT_FUNCTION, pd.DataFrame(), options(model, [curve("A", **base | {"Percent fast": 100.})],
                                                          **{pf.X_MIN: 0}))
        self.rejects(pf.CURVES, options(model, [curve("A", **base | {"Percent fast": 100.5})], **{pf.X_MIN: 0}))
        self.rejects(pf.X_MIN, options(model, [curve("A", **base)]))
        self.rejects(pf.X_MAX, options(**{pf.X_MAX: -2}))
        self.rejects(pf.X_MIN, options(**{pf.X_MIN: "low"}))
        self.rejects(pf.X_MAX, options(**{pf.X_MAX: float("inf")}))
        self.rejects(pf.X_MAX, options(**{pf.X_SOURCE: pf.GEOMETRIC, pf.X_MIN: 1, pf.X_MAX: -1}))
        self.rejects(pf.X_MIN, options(**{pf.X_SOURCE: pf.GEOMETRIC, pf.X_MIN: -2}))
        self.rejects(pf.SEGMENTS, options(**{pf.X_MIN: 0, pf.X_MAX: 1e-321, pf.SEGMENTS: 1000}))
        self.rejects(pf.SEGMENTS, options(**{pf.SEGMENTS: True}))
        self.rejects(pf.X_SOURCE, options(**{pf.X_SOURCE: "Random"}))
        self.rejects(pf.MODEL, options("No such model"))
        worksheet = options(**{pf.X_SOURCE: pf.WORKSHEET, pf.X_COLUMN: "Dose"})
        self.rejects(pf.X_COLUMN, options(**{pf.X_SOURCE: pf.WORKSHEET}), pd.DataFrame({"Dose": [1., 2., 3.]}))
        self.rejects(pf.X_COLUMN, worksheet, pd.DataFrame({"Dose": [1., 2., None]}))
        self.rejects(pf.X_COLUMN, worksheet, pd.DataFrame({"Dose": [1., 2., 2., 3.]}))
        self.rejects(pf.X_COLUMN, worksheet, pd.DataFrame({"Dose": [1., 2., float("inf")]}))
        self.rejects(pf.X_COLUMN, worksheet, pd.DataFrame({"Dose": [1., True, 3.]}, dtype=object))
        self.rejects(pf.X_COLUMN, options("Semilog line (log X)", **{pf.X_SOURCE: pf.WORKSHEET,
                                                                       pf.X_COLUMN: "Dose"}),
                     pd.DataFrame({"Dose": [-1., 1., 2.]}))

    def test_wide_range_keeps_finite_x(self):
        result = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), options(**{
            pf.X_MIN: -1.7e308, pf.X_MAX: 1.7e308, pf.SEGMENTS: 4}))
        x = result.tables[pf.VALUES]["X"].to_numpy()
        self.assertTrue(np.isfinite(x).all() and (np.diff(x) > 0).all())

    def test_worksheet_skips_blank_and_excluded_cells_in_order(self):
        frame = pd.DataFrame({"Dose": [-1., np.nan, " ", 0.5, None, 4.]}, dtype=object)
        result = analyse(pf.PLOT_FUNCTION, frame, options(**{pf.X_SOURCE: pf.WORKSHEET, pf.X_COLUMN: "Dose"}))
        self.assertEqual(result.tables[pf.VALUES]["X"].tolist(), [-1., .5, 4.])

    def test_lognormal_plot_includes_limit_at_zero_but_rejects_negative_x(self):
        coefficients = {"A": 1., "Geometric mean": 2., "Geometric SD": 2.}
        settings = options("Lognormal", [curve("Density", **coefficients)],
                           **{pf.X_MIN: 0., pf.X_MAX: 4., pf.SEGMENTS: 4})
        result = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), settings)
        values = result.tables[pf.VALUES]["Density"].to_numpy()
        self.assertEqual(values[0], 0.)
        x = np.arange(1., 5.)
        np.testing.assert_allclose(values[1:], np.exp(-.5 * (np.log2(x / 2.))**2) / x)
        self.rejects(pf.X_MIN, settings | {pf.X_MIN: -1.})

    def test_power_series_is_checked_point_by_point(self):
        result = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), options(
            "Power series", [curve("Root", A=1, B=.5, C=0, D=1)], **{pf.X_MIN: -2, pf.X_MAX: 2, pf.SEGMENTS: 4}))
        values = result.tables[pf.VALUES]["Root"]
        self.assertTrue(values.iloc[:2].isna().all())
        self.assertEqual(values.iloc[2:].tolist(), [0., 1., math.sqrt(2)])

    def test_graph_draws_one_named_line_per_curve(self):
        result = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), CASES["internal-gap"])
        axes = result.figure.axes[0]
        self.assertEqual([line.get_label() for line in axes.lines], ["Reciprocal", "Finite"])
        self.assertEqual([text.get_text() for text in axes.get_legend().get_texts()], ["Reciprocal", "Finite"])
        self.assertTrue(np.isnan(axes.lines[0].get_ydata()[3]))

    def test_recipe_round_trip_repeats_values(self):
        recipe = options(curves=[curve("A", Intercept=2., Slope=3.), curve("B", Intercept=2., Slope=3.)],
                         **{pf.FIRST: True, pf.INTEGRAL: True})
        json.dumps(recipe)
        first = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), recipe)
        data = Dataset(pd.DataFrame({"A": []}))
        data.analyses.append((pf.PLOT_FUNCTION, recipe))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "function.alab"
            save_project(path, {"Function": data})
            method, saved = load_project(path)["Function"].analyses[0]
        self.assertEqual((method, saved), (pf.PLOT_FUNCTION, recipe))
        again = analyse(pf.PLOT_FUNCTION, pd.DataFrame(), saved)
        for sheet, table in first.tables.items():
            pd.testing.assert_frame_equal(again.tables[sheet], table)
        values = again.tables[pf.VALUES]
        np.testing.assert_array_equal(values["A"], values["B"])

    def test_simulate_data_and_fitting_recipes_are_unchanged(self):
        simulated = analyse("Simulate data", pd.DataFrame(), {
            "Distribution": "XY with normal noise", "N": 3, "Seed": 42, "Mean": 0., "SD": 0.,
            "X minimum": -1., "X maximum": 1., "Intercept": 2., "Slope": 3.,
            "Success probability A": .5, "Success probability B": .5})
        self.assertEqual(list(simulated.tables), ["Simulated data"])
        self.assertEqual(simulated.tables["Simulated data"].to_numpy().tolist(), [[-1, -1], [0, 2], [1, 5]])
        x = np.arange(1., 11.)
        frame = pd.DataFrame({"x": x, "y": 1 + 5 * np.exp(-.3 * x) + .01 * np.sin(x)})
        fit = analyse("Nonlinear regression", frame, {"X": "x", "Y": "y", "Model": "One-phase decay"})
        self.assertTrue(fit.tables)
        self.assertIn("Two intersecting lines", MODELS)
        self.assertNotIn(pf.PLOT_FUNCTION, MODELS)


if __name__ == "__main__":
    unittest.main()
