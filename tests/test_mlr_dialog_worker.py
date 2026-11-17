"""Weighted fit work belongs to the application worker, not dialog validation."""
from copy import deepcopy
from unittest.mock import patch
from tests.test_graph_i18n import TkCase
from tests.test_mlr_weighting import fixture, options


class WeightedDialogWorkerTests(TkCase):
    def test_validate_checks_fields_without_running_the_fit(self):
        from tramastat import AnalysisDialog
        seen = {}

        def drive():
            dialog = next(w for w in self.root.winfo_children() if isinstance(w, AnalysisDialog))
            try:
                with patch("tramastat.analyse", side_effect=AssertionError("fit ran on the UI thread")):
                    seen["valid"] = dialog.validate()
                seen["cached"] = dialog.processing_result
            except Exception as error:
                seen["error"] = str(error)
            finally:
                dialog.cancel()

        self.root.deiconify()
        self.root.after(80, drive)
        AnalysisDialog(self.root, fixture("numeric.csv"),
                       current=("Multiple regression", deepcopy(options())), only="Multiple regression")
        self.root.withdraw()
        self.assertNotIn("error", seen, seen)
        self.assertTrue(seen["valid"])
        self.assertIsNone(seen["cached"])
