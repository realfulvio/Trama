"""The synthetic example project of the K-means stability guide opens and its recipe matches the guide."""
from pathlib import Path
import unittest

from analisi import kmeans_stability as ks
from analisi.data import load_project
from analisi.workbench import analyse

EXAMPLE = Path(__file__).resolve().parents[1] / "docs" / "examples" / "Stabilita-KMeans.alab"


class ExampleProject(unittest.TestCase):
    def test_the_recipe_calculates_as_the_guide_describes(self):
        tables = load_project(EXAMPLE)
        self.assertEqual(list(tables), ["Tre gruppi $ sintetici"])
        dataset = tables["Tre gruppi $ sintetici"]
        [(method, options)] = dataset.analyses
        self.assertEqual(method, ks.METHOD)
        self.assertEqual((options["Minimum k"], options["Maximum k"], options["Resamples"], options["Report k"]),
                         (2, 4, 30, 3))
        result = analyse(method, dataset.frame(mask_excluded=True), options)
        summary = result.tables["Stability summary"]
        self.assertEqual(list(summary.index), [2, 3, 4])
        self.assertEqual(list(summary["N"]), [18, 18, 18])  # 20 rows, two of them incomplete
        median = summary["Median ARI"]
        self.assertEqual(median[3], 1.0)
        self.assertLess(median[2], 1.0)
        self.assertLess(median[4], 1.0)
        matrix = result.tables["Co-assignment"]
        self.assertEqual(matrix.shape, (18, 18))
        self.assertEqual(list(matrix.index), [row for row in range(1, 21) if row not in {6, 15}])


if __name__ == "__main__":
    unittest.main()
