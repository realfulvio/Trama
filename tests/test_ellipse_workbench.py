"""Regression tests for scatter overlay geometry and appearance."""

import math
import unittest

import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

from analisi.ellipse_workbench import draw_confidence_overlays, ellipse_visibility


SQUARE = pd.DataFrame({"x": [-1, 1, 1, -1], "y": [-1, -1, 1, 1]})
BASE = {"X": "x", "Y": "y", "Ellipse": "Data ellipse"}


class ConfidenceOverlayTests(unittest.TestCase):
    def setUp(self):
        self.axes = Figure().add_subplot()

    def test_legacy_option_uses_point_group_colors_and_data_ellipse_scale(self):
        frame = pd.concat([SQUARE.assign(points="A"), SQUARE.assign(x=SQUARE.x + 8, points="B")])
        point_colors = {"A": np.array([.1, .2, .3, 1]), "B": "#d37136"}
        summary = draw_confidence_overlays(self.axes, frame, {**BASE, "Group": "points"}, point_colors)

        self.assertEqual(summary["Group"].tolist(), ["A", "B"])
        self.assertEqual(summary["N"].tolist(), [4, 4])
        self.assertEqual(len(self.axes.lines), 2)
        self.assertEqual(len(self.axes.patches), 0)
        for artist, group, center in zip(self.axes.lines, ("A", "B"), ((0, 0), (8, 0)), strict=True):
            self.assertIsInstance(artist, Line2D)
            self.assertEqual(to_rgba(artist.get_color()), to_rgba(point_colors[group]))
            self.assertEqual(artist.get_linestyle(), "-")
            points = artist.get_xydata()
            np.testing.assert_allclose(points[0], points[-1], atol=1e-12)
            # Sample covariance of these four corners is 4/3 times the identity.
            expected_radius = math.sqrt((4 / 3) * (-2 * math.log(.05)))
            np.testing.assert_allclose(np.linalg.norm(points - center, axis=1), expected_radius)

    def test_pooled_contour_uses_all_xy_pairs_even_when_point_group_is_missing(self):
        frame = SQUARE.assign(points=["left", "right", None, None])
        summary = draw_confidence_overlays(
            self.axes, frame, {**BASE, "Group": "points", "Ellipse grouping": "All XY data"}, {},
        )
        self.assertEqual(summary.loc[0, "N"], 4)
        self.assertEqual(summary.loc[0, "Center X"], 0)
        self.assertEqual(len(self.axes.lines), 1)

    def test_separate_categories_have_stable_colors_and_report_unavailable_groups(self):
        frame = pd.concat([
            SQUARE.assign(cohort="A"),
            SQUARE.assign(y=SQUARE.y + 10, cohort="B"),
            pd.DataFrame({"x": [0, 1, 2], "y": [2, 3, 4], "cohort": ["C"] * 3}),
            pd.DataFrame({"x": [4], "y": [None], "cohort": ["D"]}),
        ]).assign(points="A")
        frame["cohort"] = pd.Categorical(frame["cohort"], categories=["unused", "B", "A", "C", "D"])
        options = {**BASE, "Group": "points", "Ellipse grouping": "Separate categorical variable",
                   "Ellipse group": "cohort", "Fill": "By group", "Fill opacity (%)": 35,
                   "Border opacity (%)": 65, "Border width": 2.25, "Border style": "Dash-dot"}
        summary = draw_confidence_overlays(self.axes, frame, options, {"A": "#000000"})

        self.assertEqual(summary["Group"].tolist(), ["A", "B", "C", "D"])
        self.assertEqual(summary["N"].tolist(), [4, 4, 3, 0])
        self.assertEqual(summary["Status"].tolist()[:2], ["Drawn", "Drawn"])
        self.assertIn("collinear", summary.loc[2, "Status"])
        self.assertIn("three finite XY pairs", summary.loc[3, "Status"])
        self.assertEqual(len(self.axes.patches), 2)
        self.assertEqual(len(self.axes.lines), 2)
        for patch, border in zip(self.axes.patches, self.axes.lines, strict=True):
            self.assertIsInstance(patch, Polygon)
            self.assertEqual(patch.get_facecolor()[3], .35)
            self.assertEqual(patch.get_facecolor()[:3], to_rgba(border.get_color())[:3])
            self.assertNotEqual(to_rgba(border.get_color())[:3], (0, 0, 0))
            self.assertEqual(border.get_alpha(), .65)
            self.assertEqual(border.get_linewidth(), 2.25)
            self.assertEqual(border.get_linestyle(), "-.")
        self.assertNotEqual(self.axes.patches[0].get_facecolor(), self.axes.patches[1].get_facecolor())

    def test_mean_region_uses_requested_level_and_single_border_color(self):
        draw_confidence_overlays(
            self.axes, SQUARE, {**BASE, "Ellipse": "Confidence region of mean", "Level (%)": 90,
                                "Border": "Single color", "Border color": "#13a679"}, {"All": "black"},
        )
        artist, = self.axes.lines
        self.assertEqual(to_rgba(artist.get_color()), to_rgba("#13a679"))
        # With n=4 the 90% quantile of F(2,2) is 9, giving a radius of 3.
        np.testing.assert_allclose(np.linalg.norm(artist.get_xydata(), axis=1), 3)

    def test_single_color_fill_and_center_marker_without_border(self):
        frame = SQUARE.assign(x=SQUARE.x + 5, y=SQUARE.y + 7)
        draw_confidence_overlays(
            self.axes, frame, {**BASE, "Fill": "Single color", "Fill color": "#884466",
                               "Border": "None", "Center marker": "Diamond", "Center size": 8}, {},
        )
        self.assertEqual(len(self.axes.patches), 1)
        self.assertEqual(self.axes.patches[0].get_facecolor(), to_rgba("#884466", alpha=.2))
        marker, = self.axes.lines
        self.assertEqual(marker.get_marker(), "D")
        self.assertEqual(marker.get_markersize(), 8)
        self.assertEqual(marker.get_linestyle(), "None")
        np.testing.assert_array_equal(marker.get_xydata(), [(5, 7)])

    def test_legacy_hull_is_closed_and_ignores_confidence_level(self):
        frame = pd.concat([SQUARE, pd.DataFrame({"x": [0], "y": [0]})])
        summary = draw_confidence_overlays(
            self.axes, frame, {**BASE, "Ellipse": "Convex hull", "Level (%)": 999}, {},
        )
        points = self.axes.lines[0].get_xydata()
        self.assertEqual({tuple(point) for point in points[:-1]}, {tuple(row) for row in SQUARE.to_numpy()})
        np.testing.assert_array_equal(points[0], points[-1])
        self.assertTrue(pd.isna(summary.loc[0, "Level (%)"]))

    def test_invalid_settings_leave_axes_unmodified(self):
        for options, message in [
            ({"Level (%)": 100}, "between 0 and 100"),
            ({"Level (%)": float("nan")}, "finite"),
            ({"Border width": 0}, "between 0.1 and 72 points"),
            ({"Fill": "Single color", "Fill color": "not-a-color"}, "Fill color"),
            ({"Border": "None"}, "visible fill or border"),
            ({"Ellipse grouping": "Separate categorical variable"}, "categorical column"),
            ({"Ellipse grouping": "Separate categorical variable", "Ellipse group": "x"}, "distinct"),
        ]:
            with self.subTest(options=options):
                with self.assertRaisesRegex(ValueError, message):
                    draw_confidence_overlays(self.axes, SQUARE, {**BASE, **options}, {})
                self.assertEqual(len(self.axes.lines) + len(self.axes.patches), 0)

    def test_raises_when_no_group_can_produce_a_contour(self):
        with self.assertRaisesRegex(ValueError, "No confidence overlay could be drawn.*three"):
            draw_confidence_overlays(self.axes, SQUARE.iloc[:2], BASE, {})

    def test_inactive_fields_are_hidden_and_have_no_effect(self):
        options = {**BASE, "Ellipse": "None", "Border width": "not a number"}
        self.assertTrue(draw_confidence_overlays(self.axes, SQUARE, options, {}).empty)
        self.assertFalse(any(ellipse_visibility(options).values()))
        visible = ellipse_visibility({**BASE, "Ellipse grouping": "Separate categorical variable",
                                      "Fill": "By group", "Center marker": "Cross"})
        self.assertTrue(visible["Ellipse group"])
        self.assertTrue(visible["Fill opacity (%)"])
        self.assertFalse(visible["Fill color"])
        self.assertTrue(visible["Center size"])


if __name__ == "__main__":
    unittest.main()
