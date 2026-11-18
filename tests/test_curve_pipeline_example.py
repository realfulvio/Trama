"""The synthetic example project of the Curve pipeline guide opens and every stored recipe still calculates."""
from pathlib import Path
import unittest

import numpy as np

from analisi import curve_pipeline as cp
from analisi.data import load_project
from analisi.workbench import analyse

EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "examples" / "Curve-pipeline.alab"
# The rows of the worked example in docs/curve-pipeline.md: X, Value, First source row, Last source row.
GUIDE = {
    ("Irregular", cp.FIRST): [(0.5, 3, 1, 3), (2, 6, 3, 0), (4.5, 11, 0, 4), (8, 18, 4, 2)],
    ("Irregular", cp.SECOND): [(1.25, 2, 1, 0), (3.25, 2, 3, 4), (6.25, 2, 0, 2)],
    ("Irregular", cp.CUMULATIVE): [(0, 2, 1, 1), (1, 3.5, 1, 3), (3, 21.5, 1, 0), (6, 116, 1, 4), (10, 452, 1, 2)],
    ("Gaps", cp.FIRST): [(.5, 2, 0, 1), (4, 2, 3, 4), (5.5, 2, 4, 5)],
}


class ExampleProject(unittest.TestCase):
    def test_every_recipe_calculates_and_the_worked_example_matches_the_guide(self):
        tables = load_project(EXAMPLE)
        self.assertEqual(set(tables), {"Uniform", "Irregular", "Gaps", "Shifted", "Blocks"})
        seen = 0
        for title, dataset in tables.items():
            for method, options in dataset.analyses:
                result = analyse(method, dataset.frame(mask_excluded=True), options)
                self.assertEqual(list(result.tables), [cp.CURVE, cp.SETTINGS])
                seen += 1
                rows = GUIDE.get((title, options.get(cp.OPERATION)))
                if rows and options.get("Y", "Y") == "Y":
                    table = result.tables[cp.CURVE]
                    np.testing.assert_allclose(table[["X", "Value", "First source row", "Last source row"]].to_numpy(float),
                                               np.array(rows, dtype=float), rtol=1e-12)
        self.assertEqual(seen, 10)

    def test_the_smoothed_recipes_of_the_uniform_table(self):
        tables = load_project(EXAMPLE)
        uniform = tables["Uniform"]
        clean, impulse = (analyse(method, uniform.frame(), options).tables[cp.CURVE] for method, options in uniform.analyses)
        np.testing.assert_allclose(clean[["X", "Value"]].to_numpy(), [[2.5, 7], [3.5, 9], [4.5, 11], [5.5, 13]])
        np.testing.assert_allclose(impulse["Value"].iloc[:2], [15.8, 24.8], rtol=1e-12)


if __name__ == "__main__":
    unittest.main()
