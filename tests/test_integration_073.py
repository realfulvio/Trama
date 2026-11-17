"""Regression checks from the joint review of PRs 89, 90 and 91."""
import unittest
from types import MethodType, SimpleNamespace

import numpy as np
import pandas as pd

from analisi.field_error import FieldError
from analisi.workbench import analyse
from tests import test_robust_curve


class IntegrationNumericsTests(unittest.TestCase):
    def test_verifier_accepts_elementwise_absolute_tolerances_without_a_wrapper(self):
        verifier = test_robust_curve.ContractTests.load_verifier()
        verifier.close([1., 1e-9], [1., 1e-9], atol=np.array([1e-8, 1e-15]))

    def test_verifier_retains_the_stricter_tolerance_for_a_tiny_coefficient(self):
        verifier = test_robust_curve.ContractTests.load_verifier()
        with self.assertRaises(AssertionError):
            verifier.close([1., 0.], [1., 1e-9], rtol=1e-5, atol=np.array([1e-8, 1e-15]))

    def test_nonzero_residuals_at_a_large_offset_are_not_an_exact_pilot(self):
        frame = pd.DataFrame({"X": np.arange(7), "Y": 1e15 + np.array([-.25, .25, -.125, .125, -.25, .25, 0.])})
        result = analyse("Robust curve fit", frame, {
            "X": "X", "Y columns": ["Y"], "Model": "Horizontal line", "Scale method": "Pilot MAD",
            "Initial parameters": {"Mean": 1e15}})
        fit = result.tables["Robust fit"].iloc[0]
        self.assertNotEqual(fit["Status"], "Exact pilot")
        self.assertGreater(fit["Residual scale"], 0)
        self.assertGreater(fit["Robust objective"], 0)
        self.assertTrue(result.tables["Robust residuals"]["Residual"].ne(0).any())

    def test_an_unrepresentable_aggregate_reference_names_the_reference_field(self):
        frame = pd.DataFrame({"A": [1e308, 1e308]})
        with self.assertRaises(FieldError) as raised:
            analyse("Normalize to references", frame, {
                "Variables": ["A"], "Zero reference": "Constant", "Zero value": 0.,
                "One reference": "Sum", "Units": "Fractions", "Graph results": False})
        self.assertEqual(raised.exception.field, "One reference")

    def test_normalized_summary_error_bars_fit_inside_the_visible_axis(self):
        frame = pd.DataFrame({"Mean": [10., 20.], "SD": [100., 200.]})
        result = analyse("Normalize to references", frame, {
            "Input": "Summary values", "Mean": "Mean", "Error format": "SD", "Error lower": "SD",
            "Zero reference": "Constant", "Zero value": 0., "One reference": "Constant", "One value": 40.,
            "Graph results": True})
        values = result.tables["Normalized"]
        lower, upper = result.figure.axes[0].get_ylim()
        self.assertLessEqual(lower, (values["Mean"] - values["SD"]).min())
        self.assertGreaterEqual(upper, (values["Mean"] + values["SD"]).max())


class StaleResultTests(unittest.TestCase):
    def state(self, kind):
        from tramastat import App, Run
        run = Run("Normalize to references", "Synthetic", {})
        run.calculation_error = "The zero and one references are equal."
        state = SimpleNamespace(selected=(kind, 0), runs=[run], errors=[])
        state.error = state.errors.append
        state.stale_calculation_note = MethodType(App.stale_calculation_note, state)
        state.require_current_calculation = MethodType(App.require_current_calculation, state)
        return state

    def test_saved_result_has_a_persistent_warning_until_a_successful_refresh(self):
        state = self.state("result")
        self.assertIn("equal", state.stale_calculation_note())
        state.runs[0].calculation_error = None
        self.assertIsNone(state.stale_calculation_note())

    def test_stale_results_cannot_be_exported_as_current_csv_or_images(self):
        from tramastat import App
        for kind in ("result", "graph"):
            with self.subTest(kind=kind):
                state = self.state(kind)
                App.export(state)
                self.assertEqual(len(state.errors), 1)

    def test_stale_graph_cannot_be_exported_with_options(self):
        from tramastat import App
        state = self.state("graph")
        App.export_with_options(state)
        self.assertEqual(len(state.errors), 1)

    def test_stale_result_cannot_be_used_as_fresh_data(self):
        from tramastat import App
        state = self.state("result")
        App.use_result_as_data(state)
        self.assertEqual(len(state.errors), 1)

    def test_retained_layout_panels_can_still_be_previewed(self):
        from matplotlib.figure import Figure
        from analisi.reporting import Result
        from tramastat import App
        state = self.state("layout")
        state.runs[0].result = Result({}, Figure())
        state.layout_runs = lambda layout: state.runs
        self.assertEqual(App.layout_panel_figures(state, object()), (state.runs[0].result.figure,))

    def test_stale_layout_vector_export_is_rejected_at_the_export_boundary(self):
        from tramastat import App
        state = self.state("layout")
        state.layout_runs = lambda layout: state.runs
        with self.assertRaises(ValueError):
            App.export_vector_layout(state, object(), "unused.svg", {"format": "svg"})


if __name__ == "__main__":
    unittest.main()
