"""Confidence overlays in the two-dimensional observation coordinate system."""
import math
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi import exploration, pca_graphs
from analisi.processing import FieldError
from analisi.workbench import analyse


class PcaOverlayTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({
            "A": [-3, -2, -2, -1, 2, 2.4, 3, 4, 4.5, np.nan],
            "B": [1, -1, 2, 3, 1, 2.5, 0, 4, 2, 8],
            "Treatment": pd.Series([1] * 4 + ["1"] * 4 + [None, True], dtype=object),
        })
        self.options = {"Variables": ["A", "B"], "Standardize": True,
                        "Color groups by": "Treatment", "PCA overlay": "Confidence region of mean",
                        "PCA overlay grouping": "By point group", "PCA overlay level (%)": 95.0}

    def result(self, **choices):
        return analyse("Principal component analysis", self.frame, {**self.options, **choices})

    def test_typed_groups_and_mean_contours_use_one_existing_fit(self):
        with patch.object(exploration, "pca", wraps=exploration.pca) as fit:
            result = self.result()
        self.assertEqual(fit.call_count, 1)
        report = result.tables["Confidence overlays"]
        self.assertEqual(report["N"].tolist(), [4, 4, 1])
        self.assertEqual(len(set(report["Group"])), 3)
        axes = result.figure.axes[0]
        self.assertEqual(len(axes.get_legend().get_texts()), 3)
        self.assertEqual(len(axes.patches), 2)
        self.assertEqual(report["Status"].tolist()[:2], ["Drawn", "Drawn"])
        self.assertTrue(report["Status"].iloc[2].startswith("Unavailable:"))
        for patch_, points in zip(axes.patches, axes.collections):
            coordinates = np.asarray(points.get_offsets())
            center = coordinates.mean(axis=0)
            offsets = patch_.get_xy() - center
            covariance = np.cov(coordinates.T)
            distances = (offsets @ np.linalg.inv(covariance) * offsets).sum(axis=1)
            # F(2, 2) at 95% is 19. With four observations, T² / n is 14.25.
            np.testing.assert_allclose(distances, 14.25, atol=1e-10)
            np.testing.assert_allclose(patch_.get_facecolor()[:3], points.get_facecolor()[0][:3])

    def test_pooled_biplot_data_ellipse_uses_the_displayed_points(self):
        result = self.result(**{"Graph display": "Biplot", "PCA overlay": "Data ellipse",
                                "PCA overlay grouping": "All plotted points", "PCA overlay level (%)": 90.0})
        axes = result.figure.axes[0]
        table = result.tables["PC graph coordinates"]
        xy = table.loc[table.Kind == "Row", ["Horizontal", "Vertical"]].to_numpy(dtype=float)
        offsets = axes.patches[0].get_xy() - xy.mean(axis=0)
        distances = (offsets @ np.linalg.inv(np.cov(xy.T)) * offsets).sum(axis=1)
        np.testing.assert_allclose(distances, -2 * math.log(.1), atol=1e-10)
        self.assertEqual(result.tables["Confidence overlays"]["N"].tolist(), [len(xy)])

    def test_state_and_field_errors(self):
        with self.assertRaises(FieldError) as error:
            self.result(**{"PCA overlay level (%)": 100.0})
        self.assertEqual(error.exception.field, "PCA overlay level (%)")
        with self.assertRaises(FieldError) as error:
            self.result(**{"Color groups by": None})
        self.assertEqual(error.exception.field, "PCA overlay grouping")
        flat = self.result(**{"Graph display": "Scree", "PCA overlay level (%)": "bad"})
        self.assertNotIn("Confidence overlays", flat.tables)
        self.assertFalse(flat.figure.axes[0].patches)
        disabled = self.result(**{"PCA overlay": "None"})
        self.assertNotIn("Confidence overlays", disabled.tables)

    def test_hull_views_and_sparse_groups(self):
        options = {"PCA overlay": "Convex hull", "PCA overlay level (%)": None}
        result = self.result(**options)
        axes = result.figure.axes[0]
        self.assertEqual(len(axes.patches), 2)
        for polygon, points in zip(axes.patches, axes.collections):
            self.assertLessEqual(set(map(tuple, polygon.get_xy())), set(map(tuple, points.get_offsets())))
        self.frame["Treatment"] = [str(n) for n in range(len(self.frame))]
        result = self.result(**options)
        self.assertFalse(result.figure.axes[0].patches)
        self.assertTrue(all(s.startswith("Unavailable:") for s in result.tables["Confidence overlays"]["Status"]))
