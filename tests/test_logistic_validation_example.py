"""The synthetic example project of the logistic validation guide opens, calculates and keeps its linked analysis."""
from pathlib import Path
import unittest

from analisi import logistic_validation as lv
from analisi.analysis_chain import result_frame
from analisi.data import load_project
from analisi.workbench import analyse

EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "examples" / "Validazione-Logistica.alab"
TITLE = "studio logistico $ sintetico"


class ExampleProject(unittest.TestCase):
    def test_the_recipes_calculate_as_the_guide_describes(self):
        tables = load_project(EXAMPLE)
        self.assertEqual(list(tables), [TITLE])
        dataset = tables[TITLE]
        (method, options), (linked, linked_options) = dataset.analyses
        self.assertEqual(method, lv.METHOD)
        self.assertEqual((options["Folds"], options["Seed"], options["Threshold"], options["Calibration bins"],
                          options["Validation fold"]), (5, 2026, .4, 8, None))
        result = analyse(method, dataset.frame(mask_excluded=True), options)
        summary = result.tables[lv.VALIDATION].iloc[0]
        self.assertEqual((summary["N"], summary["Events"]), (156, 82))  # 160 rows, four of them incomplete
        rows = result.tables[lv.PREDICTIONS]
        self.assertEqual(rows.loc[rows["Status"] == lv.INCOMPLETE, "Source row"].tolist(), [5, 40, 70, 100])
        # The linked analysis reads the Predictions sheet: logistic recalibration of Observed on Logit.
        self.assertEqual(linked, "Multiple regression")
        self.assertEqual(dataset.analysis_sources[1].table, lv.PREDICTIONS)
        recalibration = analyse(linked, result_frame(result, lv.PREDICTIONS), linked_options)
        self.assertEqual(int(recalibration.tables["Model"].loc["N", "Value"]), 156)


if __name__ == "__main__":
    unittest.main()
