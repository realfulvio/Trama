"""Scale invariance regression for PR #49. Copy into the repository's tests."""
import unittest

import numpy as np
import pandas as pd

from analisi.pca_graphs import _dead, pca_result


class PCAUnitsRegressionTests(unittest.TestCase):
    def test_component_detection_is_relative_to_the_spectrum(self):
        for scale in (1e-18, 1e-12, 1.0, 1e12):
            with self.subTest(scale=scale):
                np.testing.assert_array_equal(_dead(np.array([1.6, .4])*scale), [False, False])
                np.testing.assert_array_equal(_dead(np.array([1.0, 1e-14])*scale), [False, True])
        np.testing.assert_array_equal(_dead(np.array([0., 0.])), [True, True])

    def test_unstandardized_biplot_reconstructs_after_change_of_units(self):
        frame = pd.DataFrame({
            "A": [np.sqrt(2), -np.sqrt(2), np.sqrt(.5), -np.sqrt(.5), 0, 0],
            "B": [np.sqrt(2), -np.sqrt(2), -np.sqrt(.5), np.sqrt(.5), 0, 0],
        })
        centered = frame.to_numpy() - frame.to_numpy().mean(axis=0)
        for scale in (1e-9, 1e-6, 1.0, 1e6):
            with self.subTest(scale=scale):
                result = pca_result(frame * scale, {
                    "Variables": ["A", "B"], "Standardize": False,
                    "Graph display": "Biplot", "Horizontal PC": 1, "Vertical PC": 2,
                })
                coordinates = result.tables["PC graph coordinates"]
                rows = coordinates.loc[coordinates.Kind == "Row", ["Horizontal", "Vertical"]].to_numpy()
                variables = coordinates.loc[coordinates.Kind == "Variable", ["Horizontal", "Vertical"]].to_numpy()
                np.testing.assert_allclose((rows @ variables.T) / scale, centered, rtol=1e-10, atol=1e-12)


if __name__ == "__main__":
    unittest.main()

