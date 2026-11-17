"""Bubble plot: area scaling, omitted rows, field errors, legends and saved styles."""
from pathlib import Path
import tempfile
import unittest

from matplotlib.collections import PathCollection
from matplotlib.legend import Legend
import numpy as np
import pandas as pd

from analisi.bubble import MAX_AREA, MAX_LABELS, NEUTRAL, SHEET
from analisi.data import Dataset, load_workspace, save_project
from analisi.presentation import apply_style, graph_series, validate_graph_style
from analisi.processing import FieldError
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse

METHOD = "Bubble plot"
FIXTURE = Path(__file__).with_name("data") / "bubble.csv"
ROLES = {"X": "X", "Y": "Y", "Size": "Size"}


def run(frame, **options):
    return analyse(METHOD, frame, {**ROLES, **options})


def bubbles(result):
    return [artist for artist in result.figure.axes[0].collections if isinstance(artist, PathCollection)]


def size_legend(result):
    return next((artist for artist in result.figure.axes[0].artists if isinstance(artist, Legend)), None)


class Fixture(unittest.TestCase):
    def setUp(self):
        self.frame = pd.read_csv(FIXTURE)

    def test_catalog_entry_is_separate_from_scatter_and_xy(self):
        self.assertIn(METHOD, GROUPS["Graphing"])
        self.assertIn(METHOD, GRAPH_METHODS)
        self.assertEqual(list(METHODS[METHOD])[:5], ["X", "Y", "Size", "Group", "Label"])
        self.assertEqual(METHODS[METHOD][MAX_AREA], 400.)
        self.assertNotIn("Size", METHODS["Scatter / confidence ellipse"])
        self.assertNotIn("Size", METHODS["XY series"])

    def test_areas_rows_and_group_order(self):
        result = run(self.frame, Group="Group", Label="Label")
        sheet = result.tables[SHEET]
        self.assertEqual(list(sheet.columns),
                         ["Source row", "X", "Y", "Size", "Marker area (pt²)", "Group", "Label"])
        self.assertEqual(sheet["Source row"].tolist(), [1, 2, 3])
        np.testing.assert_allclose(sheet["Marker area (pt²)"], [400 / 9, 1600 / 9, 400])
        self.assertEqual(sheet["Group"].tolist(), ["Alpha", "Beta", "Alpha"])
        self.assertTrue(pd.isna(sheet["Label"].iloc[2]))
        drawn = bubbles(result)
        self.assertEqual([artist.get_label() for artist in drawn], ["Alpha", "Beta"])
        np.testing.assert_allclose(drawn[0].get_sizes(), [400 / 9, 400])
        np.testing.assert_allclose(drawn[0].get_offsets(), [[1, 2], [3, 1]])
        np.testing.assert_allclose(drawn[1].get_sizes(), [1600 / 9])
        # Every sheet row has exactly one symbol.
        self.assertEqual(sum(len(artist.get_offsets()) for artist in drawn), len(sheet))
        # The row with an empty label keeps its point, without an annotation.
        self.assertEqual([text.get_text() for text in result.figure.axes[0].texts], ["A", "B"])
        settings = result.tables["Settings"]["Value"]
        self.assertEqual(settings["Rows omitted (size zero)"], 1)
        self.assertEqual(settings["Rows omitted (missing or excluded X, Y or Size)"], 2)

    def test_quadruple_size_doubles_the_diameter(self):
        areas = run(self.frame).tables[SHEET]["Marker area (pt²)"].to_numpy()
        self.assertAlmostEqual(np.sqrt(areas[1]) / np.sqrt(areas[0]), 2.)

    def test_maximum_area_and_rescale_after_exclusion(self):
        np.testing.assert_allclose(run(self.frame, **{MAX_AREA: 900.}).tables[SHEET]["Marker area (pt²)"],
                                   [100, 400, 900])
        excluded = self.frame.copy()
        excluded.loc[2, "Size"] = np.nan
        result = run(excluded, Group="Group", **{MAX_AREA: 900.})
        np.testing.assert_allclose(result.tables[SHEET]["Marker area (pt²)"], [225, 900])
        # The scale is shared: Alpha's 1 and Beta's 4 keep the 1:4 ratio across groups.
        np.testing.assert_allclose([artist.get_sizes()[0] for artist in bubbles(result)], [225, 900])
        self.assertEqual(result.tables["Settings"]["Value"]["Largest drawn size"], 4)

    def test_source_values_are_not_changed(self):
        before = self.frame.copy()
        run(self.frame, Group="Group", Label="Label")
        pd.testing.assert_frame_equal(self.frame, before)


class Inputs(unittest.TestCase):
    def test_duplicate_xy_both_drawn(self):
        frame = pd.DataFrame({"X": [1, 1, 2], "Y": [5, 5, 6], "Size": [2, 8, 4]})
        result = run(frame)
        np.testing.assert_allclose(bubbles(result)[0].get_offsets(), [[1, 5], [1, 5], [2, 6]])
        np.testing.assert_allclose(bubbles(result)[0].get_sizes(), [100, 400, 200])

    def test_field_errors(self):
        frame = pd.DataFrame({"X": [1, 2, 3], "Y": [1, 2, 3], "Size": [1, 2, 3], "T": ["a", "b", "c"]})
        cases = [
            ({"Size": "T"}, "Size"), ({"X": "T"}, "X"), ({"Y": "T"}, "Y"),
            ({"Y": "X"}, "Y"), ({"Size": "X"}, "Size"), ({"Group": "missing"}, "Group"),
            ({MAX_AREA: 0.}, MAX_AREA), ({MAX_AREA: float("nan")}, MAX_AREA), ({MAX_AREA: "big"}, MAX_AREA),
            ({MAX_AREA: 20_000.}, MAX_AREA), ({"Show labels": "yes"}, "Show labels"),
        ]
        for options, field in cases:
            with self.subTest(options=options), self.assertRaises(FieldError) as caught:
                run(frame, **options)
            self.assertEqual(caught.exception.field, field)

    def test_negative_and_infinite_sizes(self):
        for value in (-1., np.inf):
            frame = pd.DataFrame({"X": [1, 2], "Y": [1, 2], "Size": [1., value]})
            with self.subTest(value=value), self.assertRaises(FieldError) as caught:
                run(frame)
            self.assertEqual(caught.exception.field, "Size")
        # A negative size is rejected even in a row without X.
        frame = pd.DataFrame({"X": [1, None], "Y": [1, 2], "Size": [1., -2.]})
        with self.assertRaises(FieldError):
            run(frame)

    def test_text_in_x_points_at_x(self):
        frame = pd.DataFrame({"X": ["1", "two"], "Y": [1, 2], "Size": [1, 2]})
        with self.assertRaises(FieldError) as caught:
            run(frame)
        self.assertEqual(caught.exception.field, "X")

    def test_only_zero_sizes_is_explained(self):
        frame = pd.DataFrame({"X": [1, 2], "Y": [1, 2], "Size": [0, 0]})
        with self.assertRaises(FieldError) as caught:
            run(frame)
        self.assertEqual(caught.exception.field, "Size")
        self.assertIn("size of zero", str(caught.exception))
        empty = pd.DataFrame({"X": [1, None], "Y": [None, 2], "Size": [1, 2]})
        with self.assertRaisesRegex(FieldError, "No row has numeric"):
            run(empty)

    def test_blank_group_is_neutral_and_unicode_kept(self):
        frame = pd.DataFrame({"X": [1, 2, 3, 4], "Y": [1, 2, 3, 4], "Size": [1, 2, 3, 4],
                              "G": ["Ωmega", None, "Ωmega", "  "], "L": ["Città", "東京", None, "$x$"]})
        result = run(frame, Group="G", Label="L")
        drawn = bubbles(result)
        self.assertEqual([artist.get_label() for artist in drawn], ["Ωmega", NEUTRAL])
        self.assertEqual([len(artist.get_offsets()) for artist in drawn], [2, 2])
        texts = result.figure.axes[0].texts
        self.assertEqual([text.get_text() for text in texts], ["Città", "東京", "$x$"])
        self.assertFalse(any(text.get_parse_math() for text in texts))
        self.assertEqual(result.tables[SHEET]["Group"].tolist()[0], "Ωmega")

    def test_numeric_groups_keep_first_appearance(self):
        frame = pd.DataFrame({"X": [1, 2, 3], "Y": [1, 2, 3], "Size": [1, 2, 3], "G": [3, 1, 3]})
        self.assertEqual([artist.get_label() for artist in bubbles(run(frame, Group="G"))], ["3", "1"])


class Legends(unittest.TestCase):
    def test_color_and_size_legends_are_distinct(self):
        frame = pd.read_csv(FIXTURE)
        result = run(frame, Group="Group")
        axes = result.figure.axes[0]
        color = axes.get_legend()
        self.assertEqual([text.get_text() for text in color.get_texts()], ["Alpha", "Beta"])
        self.assertEqual(color.get_title().get_text(), "Group")
        sizes = size_legend(result)
        self.assertIsNot(sizes, color)
        self.assertEqual(sizes.get_title().get_text(), "Size")
        self.assertEqual([text.get_text() for text in sizes.get_texts()], ["9", "4", "1"])
        self.assertEqual([round(handle.get_markersize() ** 2, 6) for handle in sizes.legend_handles],
                         [400, round(1600 / 9, 6), round(400 / 9, 6)])

    def test_equal_sizes_show_one_reference(self):
        frame = pd.DataFrame({"X": [1, 2, 3], "Y": [1, 2, 3], "Size": [5, 5, 0]})
        result = run(frame)
        self.assertEqual([text.get_text() for text in size_legend(result).get_texts()], ["5"])
        self.assertIsNone(result.figure.axes[0].get_legend())

    def test_size_legend_can_be_hidden(self):
        result = run(pd.read_csv(FIXTURE), **{"Show size legend": False})
        self.assertIsNone(size_legend(result))

    def test_label_limit(self):
        n = MAX_LABELS + 1
        frame = pd.DataFrame({"X": np.arange(n), "Y": np.arange(n), "Size": np.ones(n),
                              "L": [f"p{i}" for i in range(n)]})
        result = run(frame, Label="L")
        self.assertFalse(result.figure.axes[0].texts)
        self.assertIn(f"limit of {MAX_LABELS}", result.tables["Settings"]["Value"]["Labels"])
        self.assertEqual(result.tables[SHEET]["Label"].tolist(), frame["L"].tolist())
        within = run(frame.iloc[:MAX_LABELS], Label="L")
        self.assertEqual(len(within.figure.axes[0].texts), MAX_LABELS)
        hidden = run(frame.iloc[:3], Label="L", **{"Show labels": False})
        self.assertFalse(hidden.figure.axes[0].texts)

    def test_svg_is_vector(self):
        result = run(pd.read_csv(FIXTURE), Group="Group", Label="Label")
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "bubble.svg"
            result.figure.savefig(target)
            text = target.read_text(encoding="utf-8")
        self.assertIn("<svg", text)
        self.assertNotIn("<image", text)


class Styles(unittest.TestCase):
    def test_group_styles_survive_recalculation(self):
        frame = pd.read_csv(FIXTURE)
        style = {"series": {"scatter:1:Beta": {"color": "#9b4174"}}}
        first = run(frame, Group="Group")
        apply_style(first.figure, style)
        # Removing every Alpha row changes the order but not the key of Beta.
        changed = frame[frame["Group"] == "Beta"]
        second = run(changed, Group="Group")
        axes = second.figure.axes[0]
        anchor = axes.get_legend().get_bbox_to_anchor()
        apply_style(second.figure, style)
        beta = bubbles(second)[0]
        self.assertEqual(beta.get_label(), "Beta")
        np.testing.assert_allclose(beta.get_facecolor()[0][:3], [0x9b / 255, 0x41 / 255, 0x74 / 255])
        # The color legend stays outside the axes after the restyle.
        np.testing.assert_allclose(axes.get_legend().get_bbox_to_anchor().bounds, anchor.bounds)

    def test_uniform_symbol_size_is_not_offered(self):
        result = run(pd.read_csv(FIXTURE), Group="Group")
        series = graph_series(result.figure.axes[0])
        self.assertTrue(series and all("marker_size" not in item.fields for item in series))
        with self.assertRaises(ValueError):
            validate_graph_style(result.figure.axes[0], {"series": {"scatter:1:Alpha": {"marker_size": 5.}}})


class Workspace(unittest.TestCase):
    def test_saved_recipe_and_style_reopen(self):
        frame = pd.read_csv(FIXTURE)
        options = {**ROLES, "Group": "Group", "Label": "Label", MAX_AREA: 900., "Show labels": True,
                   "Show size legend": True}
        style = {"series": {"scatter:1:Alpha": {"color": "#216a94", "label": "Alfa"}}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bubble.alab"
            save_project(path, {"Bubbles": Dataset(frame, analyses=[(METHOD, options)], graph_styles={0: style})})
            reopened, _ = load_workspace(path)
        dataset = reopened["Bubbles"]
        method, saved = dataset.analyses[0]
        self.assertEqual((method, saved), (METHOD, options))
        self.assertEqual(dataset.graph_styles[0], style)
        result = analyse(method, dataset.raw, saved)
        apply_style(result.figure, dataset.graph_styles[0])
        self.assertEqual([text.get_text() for text in result.figure.axes[0].get_legend().get_texts()],
                         ["Alfa", "Beta"])
        np.testing.assert_allclose(result.tables[SHEET]["Marker area (pt²)"], [100, 400, 900])


if __name__ == "__main__":
    unittest.main()
