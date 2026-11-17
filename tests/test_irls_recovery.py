"""Targeting rules for reopening the analysis dialog after an IRLS field error on the worker."""
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from analisi.processing import FieldError
from tramastat import AnalysisRecovery, App, Run


def fake_app(project="p1", runs=(), tables=("Data",)):
    app = SimpleNamespace(active_project=project, runs=list(runs), tables=dict.fromkeys(tables),
                          status=MagicMock(), root=MagicMock())
    app.weighting_recovery = lambda *args, **kwargs: App.weighting_recovery(app, *args, **kwargs)
    return app


class RecoveryTests(unittest.TestCase):
    def test_only_fitted_weightings_carry_a_recovery_context(self):
        app = fake_app()
        for method in ("Global nonlinear regression", "Nonlinear regression"):
            for weighting in ("1/abs(Yfit)", "1/Yfit²"):
                self.assertIsInstance(app.weighting_recovery(method, {"Weighting": weighting}, None),
                                      AnalysisRecovery)
            for weighting in ("Unweighted", "Inverse variance (column)", "1/abs(Y)", "1/Y²", None):
                self.assertIsNone(app.weighting_recovery(method, {"Weighting": weighting}, None))
        self.assertIsNone(app.weighting_recovery("Compare nonlinear models", {"Weighting": "1/Yfit²"}, None))

    def test_an_edit_records_the_confirmed_run_and_the_project(self):
        confirmed = Run("Global nonlinear regression", "Data", {"Weighting": "Unweighted"})
        app = fake_app(runs=[confirmed])
        recovery = app.weighting_recovery("Global nonlinear regression", {"Weighting": "1/Yfit²"}, 0, "only")
        self.assertEqual((recovery.project, recovery.index, recovery.only), ("p1", 0, "only"))
        self.assertIs(recovery.confirmed, confirmed)

    def test_the_dialog_reopens_only_for_its_own_project_table_and_analysis(self):
        confirmed = Run("Global nonlinear regression", "Data", {"Weighting": "Unweighted"})
        candidate = Run("Global nonlinear regression", "Data", {"Weighting": "1/Yfit²"})
        error = FieldError("Weighting", "zero")
        recovery = AnalysisRecovery("p1", 0, confirmed)
        self.assertTrue(App.recover_analysis(fake_app(runs=[confirmed]), candidate, error, recovery))
        self.assertFalse(App.recover_analysis(fake_app(project="p2", runs=[confirmed]), candidate, error, recovery))
        self.assertFalse(App.recover_analysis(fake_app(runs=[confirmed], tables=()), candidate, error, recovery))
        replaced = Run("Global nonlinear regression", "Data", {})
        self.assertFalse(App.recover_analysis(fake_app(runs=[replaced]), candidate, error, recovery))
        self.assertFalse(App.recover_analysis(fake_app(runs=[]), candidate, error, recovery))
        self.assertFalse(App.recover_analysis(fake_app(runs=[confirmed]), candidate, ValueError("plain"), recovery))
        new = AnalysisRecovery("p1", None, None)
        app = fake_app()
        self.assertTrue(App.recover_analysis(app, candidate, error, new))
        self.assertIn("No analysis was added", app.status.set.call_args.args[0])
        app.root.after_idle.assert_called_once()


if __name__ == "__main__":
    unittest.main()
