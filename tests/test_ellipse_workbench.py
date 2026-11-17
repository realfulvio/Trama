"""Regression tests for scatter overlay geometry and appearance."""

import math
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

from analisi import ui_theme
from analisi.data import Dataset, load_project, save_project
from analisi.ellipse_workbench import GROUP_STYLES, draw_confidence_overlays, ellipse_visibility
from analisi.workbench import analyse
from tests.test_graph_i18n import TkCase


SQUARE = pd.DataFrame({"x": [-1, 1, 1, -1], "y": [-1, -1, 1, 1]})
BASE = {"X": "x", "Y": "y", "Ellipse": "Data ellipse"}


class ConfidenceOverlayTests(unittest.TestCase):
    def setUp(self):
        self.axes = Figure().add_subplot()

    def test_ellipse_group_style_controls_each_contour_independently(self):
        frame = pd.concat([SQUARE.assign(cohort=1), SQUARE.assign(x=SQUARE.x + 4, cohort="1")])
        options = {**BASE, "Group": "cohort", "Fill": "By group", "Border": "By group",
                   "Ellipse group styles": {"cohort": {
                       "int:1": {"Fill color": "#0060a0", "Fill opacity (%)": 30,
                                 "Border color": "#804020", "Border style": "Dotted",
                                 "Border width": 2.5, "Border opacity (%)": 55},
                       "str:1": {"Fill opacity (%)": 0, "Border color": "#00aa40"},
                   }}}
        summary = draw_confidence_overlays(self.axes, frame, options, {1: "blue", "1": "red"})
        polygon, = self.axes.patches
        first, second = self.axes.lines
        self.assertEqual(polygon.get_facecolor(), to_rgba("#0060a0", .3))
        self.assertEqual(to_rgba(first.get_color()), to_rgba("#804020"))
        self.assertEqual(first.get_alpha(), .55)
        self.assertEqual(first.get_linewidth(), 2.5)
        self.assertEqual(first.get_linestyle(), ":")
        self.assertEqual(to_rgba(second.get_color()), to_rgba("#00aa40"))
        np.testing.assert_allclose(summary["Center X"], [0, 4])

        axes = Figure().add_subplot()
        draw_confidence_overlays(axes, frame, {**options, "Fill": "None", "Border": "Single color",
                                             "Border color": "#202020"}, {})
        self.assertEqual(len(axes.patches), 0)
        self.assertEqual([to_rgba(line.get_color()) for line in axes.lines], [to_rgba("#202020")] * 2)

    def test_invalid_group_style_is_rejected_before_drawing(self):
        cohort = SQUARE.assign(cohort="A")
        options = {**BASE, "Group": "cohort", "Border": "By group", "Ellipse group styles": {
            "cohort": {"str:A": {"Border width": 0}},
        }}
        with self.assertRaisesRegex(ValueError, "Border width"):
            draw_confidence_overlays(self.axes, cohort, options, {})
        self.assertEqual(len(self.axes.lines) + len(self.axes.patches), 0)

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


class EllipseGroupDialogTests(TkCase):
    def test_group_styles_save_cancel_and_roundtrip_from_the_analysis_dialog(self):
        from analisi.ellipse_style_dialog import EllipseStyleDialog
        from tramastat import AnalysisDialog

        method = "Scatter / confidence ellipse"
        frame = pd.concat([SQUARE.assign(cohort=1), SQUARE.assign(x=SQUARE.x + 4, cohort="1")], ignore_index=True)
        options = {**BASE, "Group": "cohort", "Fill": "By group", "Border": "By group"}
        self.use("it")
        ui_theme.configure(self.root)
        failures = []
        self.root.deiconify()

        def child(action):
            dialog = next(item for item in parent.winfo_children() if isinstance(item, EllipseStyleDialog))
            try:
                action(dialog)
            except Exception as error:
                failures.append(error)
                dialog.cancel()

        def change(dialog):
            self.assertEqual(dialog.title(), "Stili delle ellissi per gruppo")
            self.assertEqual(tuple(dialog.groups["values"]), ("1 (Numero)", "1 (Testo)"))
            dialog.variables["Border width"].set("0")
            with patch("analisi.ellipse_style_dialog.messagebox.showerror") as error:
                self.assertFalse(dialog.validate())
                self.assertIn("0,1", error.call_args.args[1])
            dialog.variables["Border width"].set("2,5")
            dialog.variables["Fill color"].set("#005050")
            dialog.groups.current(1)
            dialog._select_group()
            dialog.variables["Border style"].set("Dotted")
            dialog.variables["Border color"].set("#804020")
            dialog.ok()

        def cancel(dialog):
            dialog.variables["Fill color"].set("#ff0000")
            dialog.cancel()

        def drive():
            nonlocal parent
            parent = next(item for item in self.root.winfo_children() if isinstance(item, AnalysisDialog))
            try:
                button = parent.field_rows[GROUP_STYLES][1]
                parent.fields.select(button.master)
                self.root.after(80, lambda: child(change))
                button.invoke()
                self.root.after(80, lambda: child(cancel))
                button.invoke()
                parent.ok()
            except Exception as error:
                failures.append(error)
                parent.cancel()

        parent = None
        self.root.after(100, drive)
        dialog = AnalysisDialog(self.root, frame, current=(method, options), only=method)
        if failures:
            raise failures[0]
        styles = dialog.result[1][GROUP_STYLES]["cohort"]
        self.assertEqual(styles["int:1"], {"Fill color": "#005050", "Border width": 2.5})
        self.assertEqual(styles["str:1"], {"Border color": "#804020", "Border style": "Dotted"})
        with TemporaryDirectory() as directory:
            path = Path(directory) / "groups.alab"
            save_project(path, {"Example": Dataset(frame, analyses=[dialog.result])})
            reopened = load_project(path)["Example"]
        self.assertEqual(reopened.analyses[0], dialog.result)
        reopened.raw.loc[0, "y"] = -2
        result = analyse(method, reopened.frame(), reopened.analyses[0][1])
        self.assertEqual(result.tables["Confidence overlays"]["Center Y"].tolist(), [-.25, 0.])
        first, second = result.figure.axes[0].lines
        self.assertEqual(first.get_linewidth(), 2.5)
        self.assertEqual(second.get_linestyle(), ":")


if __name__ == "__main__":
    unittest.main()
