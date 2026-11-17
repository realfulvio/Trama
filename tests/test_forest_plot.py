from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_workspace, save_project
from analisi.forest_plot import (BY_COLUMN, DIFFERENCE, FOREST_PLOT, LINEAR, LOG10, ROLE_ROWS, defaults_for,
                                 guess_role_rows, row_choices, visibility)
from analisi.processing import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, analyse

DATA = Path(__file__).parent / "data"
LONG = {"Study": "Study", "Estimate": "Estimate", "Lower limit": "Lower", "Upper limit": "Upper"}


def long_frame():
    return pd.read_csv(DATA / "05-forest-long.csv")


def wide_frame():
    return pd.read_csv(DATA / "05-forest-wide.csv")


def run(frame, **options):
    return analyse(FOREST_PLOT, frame, options)


def drawn(result):
    """Interval segments, caps, points and reference line read back from the Matplotlib artists."""
    axes = result.figure.axes[0]
    parts = axes._tramastat_forest
    segments = [np.asarray(segment) for segment in parts["intervals"].get_segments()]
    caps = [np.asarray(line.get_xdata(), dtype=float) for line in parts["caps"]]
    points = np.asarray(parts["points"].get_offsets(), dtype=float)
    references = [line for line in axes.lines if line.get_linestyle() == "--"]
    return axes, segments, caps, points, references


class LongInput(unittest.TestCase):
    def test_fixture_values_order_and_omitted_triple(self):
        result = run(long_frame(), **LONG)
        values = result.tables["Forest values"]
        self.assertEqual(values["Study"].tolist(), ["A", "B", "C"])
        self.assertEqual(values["Source row"].tolist(), [1, 2, 3])
        self.assertEqual(values["Estimate"].tolist(), [.5, 2., 1.])
        self.assertEqual(values["Lower"].tolist(), [.25, 1., 1.])
        self.assertEqual(values["Upper"].tolist(), [1., 4., 1.])
        summary = result.tables["Summary"]["Value"]
        self.assertEqual(summary["Studies drawn"], 3)
        self.assertEqual(summary["Incomplete or excluded (omitted)"], 1)
        self.assertEqual(summary["Omitted studies"], "D")
        self.assertEqual(summary["Scale"], LOG10)

    def test_artists_use_the_entered_limits_on_a_log_axis(self):
        axes, segments, caps, points, references = drawn(run(long_frame(), **LONG))
        self.assertEqual(axes.get_xscale(), "log")
        # Row 0 is the first study and the y axis is inverted so it sits on top.
        self.assertGreater(axes.get_ylim()[0], axes.get_ylim()[1])
        self.assertEqual([label.get_text() for label in axes.get_yticklabels()], ["A", "B", "C"])
        np.testing.assert_array_equal([s[:, 0] for s in segments], [[.25, 1.], [1., 4.], [1., 1.]])
        np.testing.assert_array_equal([s[0, 1] for s in segments], [0., 1., 2.])
        np.testing.assert_array_equal(caps[0], [.25, 1., 1.])
        np.testing.assert_array_equal(caps[1], [1., 4., 1.])
        np.testing.assert_array_equal(points, [[.5, 0.], [2., 1.], [1., 2.]])
        self.assertEqual(len(references), 1)
        self.assertEqual(list(references[0].get_xdata()), [1., 1.])
        # A and B are symmetric around 1 in log units.
        self.assertAlmostEqual(np.log10(.5) - np.log10(.25), np.log10(1.) - np.log10(.5))
        self.assertAlmostEqual(np.log10(2.) + np.log10(.5), 0.)

    def test_degenerate_interval_keeps_its_point(self):
        _, segments, _, points, _ = drawn(run(long_frame(), **LONG))
        np.testing.assert_array_equal(segments[2][:, 0], [1., 1.])
        np.testing.assert_array_equal(points[2], [1., 2.])

    def test_study_fallback_uses_row_titles_then_row_index(self):
        frame = pd.DataFrame({"Row title": ["First", None], "E": [1., 2.], "L": [.5, 1.], "U": [2., 3.]})
        result = run(frame, **{"Estimate": "E", "Lower limit": "L", "Upper limit": "U"})
        self.assertEqual(result.tables["Forest values"]["Study"].tolist(), ["First", "Row 2"])

    def test_unicode_and_duplicate_labels_stay_separate_studies(self):
        frame = pd.DataFrame({"S": ["Ωmega $x$", "Ωmega $x$", "Bé"], "E": [1., 2., 3.], "L": [.5, 1., 2.],
                              "U": [2., 3., 4.]})
        result = run(frame, **{"Study": "S", "Estimate": "E", "Lower limit": "L", "Upper limit": "U"})
        values = result.tables["Forest values"]
        self.assertEqual(values["Study"].tolist(), ["Ωmega $x$", "Ωmega $x$", "Bé"])
        self.assertEqual(values["Source row"].tolist(), [1, 2, 3])
        labels = [label.get_text() for label in result.figure.axes[0].get_yticklabels()]
        self.assertEqual(labels, ["Ωmega $x$", "Ωmega $x$", "Bé"])

    def test_excluded_cell_is_omitted_and_counted(self):
        dataset = Dataset(long_frame(), excluded={(1, 2)})
        result = run(dataset.frame(mask_excluded=True), **LONG)
        self.assertEqual(result.tables["Forest values"]["Study"].tolist(), ["A", "C"])
        summary = result.tables["Summary"]["Value"]
        self.assertEqual(summary["Incomplete or excluded (omitted)"], 2)
        self.assertEqual(summary["Omitted studies"], "B, D")

    def test_edited_limit_is_drawn_as_entered(self):
        frame = long_frame()
        frame.loc[1, "Upper"] = 3.7
        result = run(frame, **LONG)
        self.assertEqual(result.tables["Forest values"]["Upper"].tolist(), [1., 3.7, 1.])
        _, segments, caps, _, _ = drawn(result)
        self.assertEqual(segments[1][1, 0], 3.7)
        self.assertEqual(caps[1][1], 3.7)

    def test_inverted_limits_name_study_and_field(self):
        frame = long_frame()
        frame.loc[0, ["Lower", "Upper"]] = [1., .25]
        with self.assertRaises(FieldError) as raised:
            run(frame, **LONG)
        self.assertEqual(raised.exception.field, "Lower limit")
        self.assertIn('"A"', str(raised.exception))
        frame = long_frame()
        frame.loc[1, "Upper"] = 1.5
        with self.assertRaises(FieldError) as raised:
            run(frame, **LONG)
        self.assertEqual(raised.exception.field, "Upper limit")
        self.assertIn('"B"', str(raised.exception))

    def test_malformed_value_names_study_and_field(self):
        frame = long_frame().astype({"Estimate": object})
        frame.loc[2, "Estimate"] = "one"
        with self.assertRaises(FieldError) as raised:
            run(frame, **LONG)
        self.assertEqual(raised.exception.field, "Estimate")
        self.assertIn('"C"', str(raised.exception))

    def test_columns_must_be_distinct(self):
        with self.assertRaises(FieldError) as raised:
            run(long_frame(), **{**LONG, "Upper limit": "Lower"})
        self.assertEqual(raised.exception.field, "Upper limit")

    def test_weight_changes_marker_area_only(self):
        frame = long_frame().assign(W=[1., 4., 2., 9.])
        plain = run(frame, **LONG)
        weighted = run(frame, **LONG, Weight="W")
        pd.testing.assert_frame_equal(weighted.tables["Forest values"].drop(columns="Weight"),
                                      plain.tables["Forest values"])
        sizes = drawn(weighted)[3]
        areas = weighted.figure.axes[0]._tramastat_forest["points"].get_sizes()
        np.testing.assert_allclose(areas / areas.max(), [.25, 1., .5])
        np.testing.assert_array_equal(sizes, drawn(plain)[3])
        self.assertEqual(len(set(plain.figure.axes[0]._tramastat_forest["points"].get_sizes())), 1)
        legend = [text.get_text() for text in weighted.figure.axes[0].get_legend().get_texts()]
        self.assertTrue(any("area ∝ W" in text for text in legend), legend)

    def test_nonpositive_weight_is_rejected(self):
        frame = long_frame().assign(W=[1., 0., 2., 3.])
        with self.assertRaises(FieldError) as raised:
            run(frame, **LONG, Weight="W")
        self.assertEqual(raised.exception.field, "Weight")


class WideInput(unittest.TestCase):
    def roles(self):
        return {"Estimate row": "2 · Estimate", "Lower row": "3 · Lower", "Upper row": "1 · Upper"}

    def test_roles_from_explicit_rows_match_long_input(self):
        result = run(wide_frame(), Input=BY_COLUMN, **{"Study columns": ["A", "B", "C"]}, **self.roles())
        values = result.tables["Forest values"]
        long = run(long_frame(), **LONG).tables["Forest values"]
        self.assertEqual(values["Source column"].tolist(), ["A", "B", "C"])
        for name in ("Study", "Estimate", "Lower", "Upper"):
            self.assertEqual(values[name].tolist(), long[name].tolist())

    def test_selection_order_is_plotting_order(self):
        result = run(wide_frame(), Input=BY_COLUMN, **{"Study columns": ["C", "A"]}, **self.roles())
        self.assertEqual(result.tables["Forest values"]["Study"].tolist(), ["C", "A"])
        labels = [label.get_text() for label in result.figure.axes[0].get_yticklabels()]
        self.assertEqual(labels, ["C", "A"])

    def test_role_guess_reads_titles_not_numbers(self):
        self.assertEqual(guess_role_rows(wide_frame(), {}), self.roles())
        self.assertEqual(row_choices(wide_frame(), {}), ["1 · Upper", "2 · Estimate", "3 · Lower"])
        # Plain row numbers are accepted and stay positions.
        result = run(wide_frame(), Input=BY_COLUMN, **{"Study columns": ["A"], "Estimate row": 2, "Lower row": "Row 3",
                                                      "Upper row": "1"})
        self.assertEqual(result.tables["Forest values"]["Estimate"].tolist(), [.5])

    def test_duplicate_roles_are_rejected(self):
        roles = {**self.roles(), "Lower row": "2 · Estimate"}
        with self.assertRaises(FieldError) as raised:
            run(wide_frame(), Input=BY_COLUMN, **{"Study columns": ["A", "B"]}, **roles)
        self.assertEqual(raised.exception.field, "Lower row")

    def test_reference_table_with_relative_risks(self):
        frame = pd.DataFrame({"Row title": ["lower limit", "relative risk", "upper limit"],
                              "Sohn 2007": [2.3, 4.5, 7.8], "Raine  2001": [.9, 2.2, 4.3], "Snow 2005": [3.4, 4.1, 5.6]})
        roles = guess_role_rows(frame, {})
        self.assertEqual(roles, {"Estimate row": "2 · relative risk", "Lower row": "1 · lower limit",
                                 "Upper row": "3 · upper limit"})
        result = run(frame, Input=BY_COLUMN, **{"Study columns": ["Sohn 2007", "Raine  2001", "Snow 2005"]}, **roles)
        values = result.tables["Forest values"]
        self.assertEqual(values["Study"].tolist(), ["Sohn 2007", "Raine  2001", "Snow 2005"])
        self.assertEqual(values["Estimate"].tolist(), [4.5, 2.2, 4.1])
        self.assertEqual(values["Lower"].tolist(), [2.3, .9, 3.4])
        self.assertEqual(values["Upper"].tolist(), [7.8, 4.3, 5.6])

    def test_incomplete_column_is_omitted(self):
        frame = wide_frame()
        frame.loc[2, "B"] = np.nan
        result = run(frame, Input=BY_COLUMN, **{"Study columns": ["A", "B", "C"]}, **self.roles())
        self.assertEqual(result.tables["Forest values"]["Study"].tolist(), ["A", "C"])
        self.assertEqual(result.tables["Summary"]["Value"]["Omitted studies"], "B")

    def test_inverted_column_error_names_role_row(self):
        frame = wide_frame().astype({"B": float})
        frame.loc[0, "B"] = 1.5
        with self.assertRaises(FieldError) as raised:
            run(frame, Input=BY_COLUMN, **{"Study columns": ["A", "B"]}, **self.roles())
        self.assertEqual(raised.exception.field, "Upper row")
        self.assertIn('"B"', str(raised.exception))


class Scales(unittest.TestCase):
    def difference(self):
        return pd.DataFrame({"S": ["minus", "zero", "plus"], "E": [-2., 0., 2.], "L": [-3., -1., -.5],
                             "U": [-1., 1., 4.]})

    def test_difference_defaults_to_linear_axis_and_zero_reference(self):
        self.assertEqual(defaults_for(DIFFERENCE), (LINEAR, 0.))
        options = {"Study": "S", "Estimate": "E", "Lower limit": "L", "Upper limit": "U", "Measure": DIFFERENCE}
        result = run(self.difference(), **options)
        axes, segments, _, points, references = drawn(result)
        self.assertEqual(axes.get_xscale(), "linear")
        self.assertEqual(list(references[0].get_xdata()), [0., 0.])
        np.testing.assert_array_equal([s[:, 0] for s in segments], [[-3., -1.], [-1., 1.], [-.5, 4.]])
        np.testing.assert_array_equal(points[:, 0], [-2., 0., 2.])

    def test_log_scale_rejects_nonpositive_values_on_the_field(self):
        options = {"Study": "S", "Estimate": "E", "Lower limit": "L", "Upper limit": "U", "Measure": DIFFERENCE,
                   "Scale": LOG10}
        with self.assertRaises(FieldError) as raised:
            run(self.difference(), **options)
        self.assertEqual(raised.exception.field, "Lower limit")
        self.assertIn('"minus"', str(raised.exception))

    def test_log_reference_must_be_positive_unless_hidden(self):
        with self.assertRaises(FieldError) as raised:
            run(long_frame(), **LONG, Reference=0.)
        self.assertEqual(raised.exception.field, "Reference")
        result = run(long_frame(), **LONG, Reference=0., **{"Show reference": False})
        self.assertEqual(drawn(result)[4], [])
        self.assertEqual(result.tables["Summary"]["Value"]["Reference line"], "Hidden")

    def test_svg_and_png_export(self):
        result = run(long_frame(), **LONG)
        with tempfile.TemporaryDirectory() as folder:
            svg, png = Path(folder) / "forest.svg", Path(folder) / "forest.png"
            result.figure.savefig(svg)
            result.figure.savefig(png, dpi=80)
            self.assertIn(b"<svg", svg.read_bytes())
            self.assertGreater(png.stat().st_size, 1000)


class Catalog(unittest.TestCase):
    def test_listed_under_graphing_with_fields_by_mode(self):
        self.assertIn(FOREST_PLOT, GROUPS["Graphing"])
        self.assertIn(FOREST_PLOT, GRAPH_METHODS)
        rows, columns = visibility("One study per row"), visibility(BY_COLUMN)
        self.assertTrue(rows["Estimate"] and not rows["Study columns"])
        self.assertTrue(columns["Study columns"] and all(columns[role] for role in ROLE_ROWS))
        self.assertFalse(columns["Weight"] or columns["Estimate"])

    def test_recipe_survives_save_and_reopen(self):
        recipe = {"Input": BY_COLUMN, "Study columns": ["B", "A"], "Estimate row": "2 · Estimate",
                  "Lower row": "3 · Lower", "Upper row": "1 · Upper", "Measure": "Ratio", "Scale": LOG10,
                  "Reference": 1., "Show reference": True}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "forest.alab"
            save_project(path, {"Wide": Dataset(wide_frame(), analyses=[(FOREST_PLOT, recipe)])})
            tables = load_workspace(path)[0]
            method, options = tables["Wide"].analyses[0]
        self.assertEqual((method, options), (FOREST_PLOT, recipe))
        result = run(tables["Wide"].frame(mask_excluded=True), **options)
        self.assertEqual(result.tables["Forest values"]["Study"].tolist(), ["B", "A"])


if __name__ == "__main__":
    unittest.main()
