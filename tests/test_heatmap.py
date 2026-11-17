"""Worksheet and long-format heat maps, color mapping, and selection limits."""
from io import BytesIO
import unittest

import numpy as np
import pandas as pd

from analisi.heatmap import CENTER, MAXIMUM, MINIMUM, OUTSIDE, HEAT_MAP, heat_map
from analisi.processing import FieldError
from analisi.workbench import analyse


class HeatMapTests(unittest.TestCase):
    def setUp(self):
        self.grouped = pd.DataFrame({"Row title": ["North", "South", "Empty", None],
                                     "A [1]": [2., 4., None, None], "A [2]": [4., None, None, None],
                                     "B [1]": [5., 9., None, None], "B [2]": [9., 9., None, None]})
        self.grouped.attrs["table_format"] = "grouped"
        self.variables = list(self.grouped.columns[1:])

    def test_grouped_summary_mask_and_order(self):
        output = analyse(HEAT_MAP, self.grouped, {"Variables": self.variables, "Mark missing cells": True,
                                                  "Show cell values": True})
        table = output.tables["Heat map data"]
        self.assertEqual(table.index.tolist(), ["North", "South", "Empty"])
        self.assertEqual(table.columns.tolist(), ["A", "B"])
        np.testing.assert_allclose(table, [[3, 7], [4, 9], [np.nan, np.nan]])
        ax = output.figure.axes[0]
        mesh, = ax.collections
        np.testing.assert_array_equal(mesh.get_array().mask, [[False, False], [False, False], [True, True]])
        self.assertEqual([label.get_text() for label in ax.texts], ["3", "7", "4", "9", "×", "×"])
        output.figure.canvas.draw()

    def test_summary_choices_and_orientation(self):
        expected = {"Median": [3., 7.], "Geometric mean": [np.sqrt(8), np.sqrt(45)],
                    "SD": [np.sqrt(2), np.sqrt(8)], "SEM": [1., 2.],
                    "CV (%)": [100 * np.sqrt(2) / 3, 100 * np.sqrt(8) / 7]}
        for measure, values in expected.items():
            with self.subTest(measure=measure):
                result = heat_map(self.grouped, {"Variables": self.variables, "Cell value": measure,
                                                 "Transpose": True, "Reverse rows": True, "Reverse columns": True})
                table = result.tables["Heat map data"]
                self.assertEqual(table.index.tolist(), ["B", "A"])
                self.assertEqual(table.columns.tolist(), ["Empty", "South", "North"])
                np.testing.assert_allclose(table["North"], values[::-1])
                if measure in {"SD", "SEM", "CV (%)"}:
                    self.assertTrue(pd.isna(table.loc["A", "South"]))

    def test_long_numeric_duplicate_observations_and_custom_scale(self):
        frame = pd.DataFrame({"X": ["Day 2", "Day 1", "Day 2", "Day 2", None],
                              "Y": ["A", "A", "B", "A", "A"], "Metric": [1, -2, 7, 3, 2]})
        result = heat_map(frame, {"Input format": "Long numeric", "X categories": "X", "Y categories": "Y",
                                  "Values": "Metric", "Palette": "Blue–red", "Color scale": "Diverging",
                                  MINIMUM: "-1", CENTER: "0", MAXIMUM: "5", OUTSIDE: "#803040"})
        table = result.tables["Heat map data"]
        self.assertEqual(table.columns.tolist(), ["Day 2", "Day 1"])
        np.testing.assert_allclose(table, [[2, -2], [7, np.nan]])
        mesh, = result.figure.axes[0].collections
        np.testing.assert_allclose(mesh.norm([-1, 0, 5]), [0, .5, 1])
        self.assertEqual(mesh.colorbar.extend, "both")
        data = BytesIO()
        result.figure.savefig(data, format="svg")
        self.assertIn(b"<path", data.getvalue())

    def test_long_category_first_occurrence_and_stable_legend(self):
        frame = pd.DataFrame({"X": ["day 1", "day 1", "day 2", "day 1", "day 1"],
                              "Y": ["A", "A", "A", "B", "B"], "Metric": ["On", "Off", "Off", None, "On"]})
        opts = {"Input format": "Long categories", "X categories": "X", "Y categories": "Y", "Values": "Metric"}
        original = heat_map(frame, opts)
        reversed_map = heat_map(frame, {**opts, "Reverse columns": True})
        table = original.tables["Heat map data"]
        self.assertEqual(table.iloc[0].tolist(), ["On", "Off"])
        self.assertTrue(table.iloc[1].isna().all())
        for result in (original, reversed_map):
            legend = result.figure.axes[0].get_legend()
            self.assertEqual([text.get_text() for text in legend.get_texts()], ["On", "Off"])

    def test_literal_labels_and_thin_matrix_legend(self):
        frame = pd.DataFrame({r"$\unknown$": np.ones(100)})
        result = heat_map(frame, {"Variables": list(frame), MINIMUM: " ", MAXIMUM: " "})
        result.figure.set_size_inches(4.8, 3.2)
        target = BytesIO()
        result.figure.savefig(target, format="svg")
        self.assertGreater(result.figure.axes[1].get_position().width, .01)

    def test_validation_is_field_specific(self):
        frame = pd.DataFrame({"x": [1., 2.], "y": [0., -1.]})
        for options, field in (
                ({"Cell value": "Geometric mean"}, "Cell value"),
                ({"Color scale": "Diverging", CENTER: "20"}, CENTER),
                ({MINIMUM: "2", MAXIMUM: "1"}, MAXIMUM),
                ({"Missing color": "invalid color"}, "Missing color")):
            with self.subTest(options=options), self.assertRaises(FieldError) as error:
                heat_map(frame, {"Variables": ["x", "y"], **options})
            self.assertEqual(error.exception.field, field)


if __name__ == "__main__":
    unittest.main()
