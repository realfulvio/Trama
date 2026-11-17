"""Per-slice color, explode and visibility for composition charts."""
from pathlib import Path
import tempfile
import unittest

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba
from matplotlib.patches import Wedge

from analisi.data import Dataset, load_workspace, save_project
from analisi.figure_export import export_figure
from analisi.parts_of_whole import APPLY_SEGMENT_STYLES, PARTS_GRAPH, SEGMENT_STYLES, parts_graph, slice_color_defaults
from analisi.processing import FieldError
from analisi.workbench import analyse


def composition():
    return pd.DataFrame({"Category": ["A", "A", "Zero", "B", "Blank"], "Value": [1, 1, 0, 2, None]})


STYLES = {
    "row:1": {"color": "#d62728", "explode": 0.12, "visible": True},
    "row:2": {"color": "#2ca02c", "visible": False},
    "row:3": {"color": "#000000"},
    "row:4": {"color": "#1f77b4"},
}


def styled(**extra):
    options = {"Values": "Value", "Row titles": "Category", "Graph style": "Donut",
               "Legend": "Category and percent", "Segment styles": STYLES, "Slice labels": "Percent",
               "Border color": "#394c60", "Border width": 2, **extra}
    return options


def wedges(result):
    return [patch for patch in result.figure.axes[0].patches if isinstance(patch, Wedge)]


class SegmentStyleTests(unittest.TestCase):
    def tearDown(self):
        plt.close("all")

    def test_editor_defaults_match_wedges_after_zero_rows(self):
        frame = composition()
        for reverse, rows in ((False, [1, 2, 4]), (True, [4, 2, 1])):
            with self.subTest(reverse=reverse):
                options = {"Values": "Value", "Graph style": "Donut", "Reverse order": reverse}
                defaults = slice_color_defaults(frame, options)
                result = parts_graph(frame, options)
                np.testing.assert_allclose([to_rgba(defaults[row]) for row in rows],
                                           [wedge.get_facecolor() for wedge in wedges(result)])

    def test_slice_identity_survives_reverse_and_hiding(self):
        frame = composition()
        legacy = parts_graph(frame, {"Values": "Value", "Row titles": "Category", "Graph style": "Donut",
                                     "Legend": "Category and percent"})
        result = parts_graph(frame, styled())
        for name in ("Composition", "Total"):
            pd.testing.assert_frame_equal(legacy.tables[name], result.tables[name])
        drawn = wedges(result)
        self.assertEqual([item.get_visible() for item in drawn], [True, False, True])
        np.testing.assert_allclose([abs(item.theta2 - item.theta1) for item in drawn], [90, 90, 180], atol=1e-4)
        np.testing.assert_allclose(drawn[0].center, np.array([np.cos(np.pi / 4), np.sin(np.pi / 4)]) * 0.12, atol=1e-7)
        np.testing.assert_allclose(drawn[0].get_facecolor(), to_rgba("#d62728"))
        np.testing.assert_allclose(drawn[2].get_facecolor(), to_rgba("#1f77b4"))
        np.testing.assert_allclose(drawn[0].get_edgecolor(), to_rgba("#394c60"))
        self.assertEqual(drawn[0].get_linewidth(), 2)
        self.assertEqual([text.get_text() for text in result.figure.axes[0].get_legend().get_texts()],
                         ["A · 25.0%", "B · 50.0%"])
        self.assertEqual([text.get_text() for text in result.figure.axes[0].texts].count("25.0%"), 1)
        self.assertEqual(result.figure.axes[0].texts[-1].get_text().split("\n")[0], "Total")

        reversed_wedges = wedges(parts_graph(frame, styled(**{"Reverse order": True})))
        np.testing.assert_allclose(reversed_wedges[-1].get_facecolor(), to_rgba("#d62728"))
        self.assertFalse(reversed_wedges[1].get_visible())
        counterclockwise = wedges(parts_graph(frame, styled(**{"Clockwise": False})))
        np.testing.assert_allclose(counterclockwise[0].center, [-drawn[0].center[0], drawn[0].center[1]], atol=1e-7)

        hidden = parts_graph(frame, styled(**{"Segment styles": {f"row:{row}": {"visible": False} for row in (1, 2, 4)}}))
        self.assertTrue(wedges(hidden))
        self.assertFalse(any(item.get_visible() for item in wedges(hidden)))
        pd.testing.assert_frame_equal(hidden.tables["Composition"], legacy.tables["Composition"])
        self.assertIsNone(hidden.figure.axes[0].get_legend())

    def test_invalid_style_names_the_row_and_other_graphs_ignore_it(self):
        frame = composition()
        with self.assertRaises(FieldError) as caught:
            parts_graph(frame, styled(**{"Segment styles": {"row:1": {"explode": 0.7}}}))
        self.assertEqual(caught.exception.field, "Segment styles")
        self.assertIn("Row 1", str(caught.exception))
        self.assertIn("explode", str(caught.exception))
        with self.assertRaises(FieldError) as unknown:
            parts_graph(frame, styled(**{"Segment styles": {"row:2": {"glow": 1}}}))
        self.assertIn("Row 2", str(unknown.exception))
        self.assertIn("glow", str(unknown.exception))
        with self.assertRaises(FieldError) as width:
            parts_graph(frame, styled(**{"Border width": 7}))
        self.assertEqual(width.exception.field, "Border width")
        for style in ("Horizontal slices", "Vertical slices", "Dot plot"):
            with self.subTest(style=style):
                result = parts_graph(frame, {"Values": "Value", "Row titles": "Category", "Graph style": style,
                                             "Segment styles": {"row:1": {"explode": 0.7}}})
                self.assertIn("Composition", result.tables)

    def test_styles_follow_sheet_position_not_the_index_label(self):
        frame = composition()
        frame.index = [10, 11, 14, 19, 20]
        result = analyse(PARTS_GRAPH, frame, styled(**{"Start angle": 450}))
        drawn = wedges(result)
        same = wedges(analyse(PARTS_GRAPH, frame, styled()))
        self.assertEqual([item.theta1 for item in drawn], [item.theta1 for item in same])
        np.testing.assert_allclose(drawn[0].get_facecolor(), to_rgba("#d62728"))

    def test_defaults_match_a_recipe_without_the_new_keys(self):
        frame = pd.DataFrame({"Row title": ["A", "Zero", "B"], "Count": [3., 0., 1.]})
        legacy = parts_graph(frame, {"Values": "Count", "Donut hole (%)": 60.})
        same = parts_graph(frame, {"Values": "Count", "Donut hole (%)": 60., "Start angle": 90,
                                   "Clockwise": True, "Slice labels": "None", "Border color": "white",
                                   "Border width": 1.3, "Segment styles": {}})
        pd.testing.assert_frame_equal(legacy.tables["Composition"], same.tables["Composition"])
        self.assertEqual([item.width for item in same.figure.axes[0].patches], [.4, .4])
        self.assertEqual(same.figure.axes[0].texts[-1].get_text(), legacy.figure.axes[0].texts[-1].get_text())
        np.testing.assert_allclose(same.figure.axes[0].patches[0].get_facecolor(),
                                   legacy.figure.axes[0].patches[0].get_facecolor())

    def test_bars_and_dots_apply_segment_styles_while_preserving_geometry(self):
        frame = pd.DataFrame({
            "Part": ["Alpha", "", "Beta", "Alpha", "Zero", "Gamma"],
            "Count": [25, None, 35, 15, 0, 25],
        })
        styles = {
            "row:1": {"color": "#c0392b", "visible": True},
            "row:3": {"color": "#1f7a8c", "visible": False},
            "row:4": {"color": "#e67e22", "visible": True},
            "row:5": {"color": "#000000", "visible": False},
            "row:6": {"color": "#2e8b57", "visible": True},
        }
        for reverse, order, expected_legend in (
            (False, [1, 3, 4, 6], ["Alpha · 25.0%", "Alpha · 15.0%", "Gamma · 25.0%"]),
            (True, [6, 4, 3, 1], ["Gamma · 25.0%", "Alpha · 15.0%", "Alpha · 25.0%"]),
        ):
            for graph_style in ("Horizontal slices", "Vertical slices"):
                with self.subTest(graph_style=graph_style, reverse=reverse):
                    base = parts_graph(frame, {"Values": "Count", "Row titles": "Part",
                                               "Graph style": graph_style, "Reverse order": reverse})
                    styled_bar = parts_graph(frame, {"Values": "Count", "Row titles": "Part",
                                                     "Graph style": graph_style, "Reverse order": reverse,
                                                     "Apply segment styles": True, "Segment styles": styles})
                    for name in ("Composition", "Total"):
                        pd.testing.assert_frame_equal(base.tables[name], styled_bar.tables[name])
                    base_patches = base.figure.axes[0].patches
                    patches = styled_bar.figure.axes[0].patches
                    self.assertEqual(len(patches), 4)
                    for left, right in zip(base_patches, patches, strict=True):
                        if graph_style == "Horizontal slices":
                            self.assertAlmostEqual(left.get_x(), right.get_x(), places=9)
                            self.assertAlmostEqual(left.get_width(), right.get_width(), places=9)
                        else:
                            self.assertAlmostEqual(left.get_y(), right.get_y(), places=9)
                            self.assertAlmostEqual(left.get_height(), right.get_height(), places=9)
                    self.assertEqual([patch.get_visible() for patch in patches],
                                     [styles[f"row:{row}"]["visible"] for row in order])
                    for patch, row in zip(patches, order, strict=True):
                        np.testing.assert_allclose(patch.get_facecolor(), to_rgba(styles[f"row:{row}"]["color"]))
                    self.assertEqual([t.get_text() for t in styled_bar.figure.axes[0].get_legend().get_texts()],
                                     expected_legend)

            with self.subTest(graph_style="Dot plot", reverse=reverse):
                base_dots = parts_graph(frame, {"Values": "Count", "Row titles": "Part",
                                                "Graph style": "Dot plot", "Number of dots": 20,
                                                "Reverse order": reverse})
                styled_dots = parts_graph(frame, {"Values": "Count", "Row titles": "Part",
                                                  "Graph style": "Dot plot", "Number of dots": 20,
                                                  "Reverse order": reverse,
                                                  "Apply segment styles": True, "Segment styles": styles})
                for name in ("Composition", "Total"):
                    pd.testing.assert_frame_equal(base_dots.tables[name], styled_dots.tables[name])
                base_cols = base_dots.figure.axes[0].collections
                cols = styled_dots.figure.axes[0].collections
                self.assertEqual(len(cols), 4)
                for left, right in zip(base_cols, cols, strict=True):
                    np.testing.assert_allclose(left.get_offsets(), right.get_offsets())
                self.assertEqual([col.get_visible() for col in cols],
                                 [styles[f"row:{row}"]["visible"] for row in order])
                for col, row in zip(cols, order, strict=True):
                    np.testing.assert_allclose(col.get_facecolor()[0], to_rgba(styles[f"row:{row}"]["color"]))
                self.assertEqual([t.get_text() for t in styled_dots.figure.axes[0].get_legend().get_texts()],
                                 expected_legend)

    def test_bars_and_dots_ignore_explode_and_respect_apply_flag(self):
        frame = composition()
        for style in ("Horizontal slices", "Vertical slices", "Dot plot"):
            with self.subTest(style=style):
                ignored = parts_graph(frame, {"Values": "Value", "Row titles": "Category", "Graph style": style,
                                              "Segment styles": {"row:1": {"color": "not-a-color", "visible": False}}})
                self.assertIsNotNone(ignored.figure.axes[0].get_legend())
                with self.assertRaises(FieldError) as bad_color:
                    parts_graph(frame, {"Values": "Value", "Row titles": "Category", "Graph style": style,
                                        "Apply segment styles": True,
                                        "Segment styles": {"row:1": {"color": "not-a-color"}}})
                self.assertEqual(bad_color.exception.field, "Segment styles")
                stale_explode = parts_graph(frame, {"Values": "Value", "Row titles": "Category", "Graph style": style,
                                                    "Apply segment styles": True,
                                                    "Segment styles": {"row:1": {"color": "#112233", "explode": 99}}})
                artist = (stale_explode.figure.axes[0].collections[0]
                          if style == "Dot plot" else stale_explode.figure.axes[0].patches[0])
                face = artist.get_facecolor()[0] if style == "Dot plot" else artist.get_facecolor()
                np.testing.assert_allclose(face, to_rgba("#112233"))
                all_hidden = parts_graph(frame, {"Values": "Value", "Row titles": "Category", "Graph style": style,
                                                 "Apply segment styles": True,
                                                 "Segment styles": {f"row:{r}": {"visible": False} for r in (1, 2, 4)}})
                self.assertIsNone(all_hidden.figure.axes[0].get_legend())
                self.assertEqual(all_hidden.figure.axes[0].texts[-1].get_text().split("\n")[0], "Total")

    def test_project_persistence_recalculation_use_as_data_and_export(self):
        frame = composition()
        options = {
            "Values": "Value", "Row titles": "Category", "Graph style": "Horizontal slices",
            "Legend": "Category and percent", APPLY_SEGMENT_STYLES: True, SEGMENT_STYLES: STYLES,
        }
        dataset = Dataset(frame.copy(), analyses=[(PARTS_GRAPH, options)])
        with tempfile.TemporaryDirectory() as tmp:
            project_path = Path(tmp) / "composition-segments.alab"
            save_project(project_path, {"Composition": dataset})
            loaded_sheets, _ = load_workspace(project_path)
            restored = loaded_sheets["Composition"]
            self.assertEqual(len(restored.analyses), 1)
            reopened_method, reopened_options = restored.analyses[0]
            self.assertEqual(reopened_method, PARTS_GRAPH)
            self.assertIs(reopened_options[APPLY_SEGMENT_STYLES], True)
            self.assertEqual(reopened_options[SEGMENT_STYLES]["row:1"]["explode"], 0.12)
            reopened_res = analyse(reopened_method, restored.frame(mask_excluded=True), reopened_options)
            patches = reopened_res.figure.axes[0].patches
            self.assertEqual([patch.get_visible() for patch in patches], [True, False, True])
            np.testing.assert_allclose(patches[0].get_facecolor(), to_rgba("#d62728"))
            np.testing.assert_allclose(patches[2].get_facecolor(), to_rgba("#1f77b4"))

            # Round-trip pie -> bar -> pie preserves explode in Segment styles
            pie_options = {**reopened_options, "Graph style": "Donut"}
            pie_res = analyse(PARTS_GRAPH, restored.frame(mask_excluded=True), pie_options)
            drawn_wedges = wedges(pie_res)
            np.testing.assert_allclose(
                drawn_wedges[0].center, np.array([np.cos(np.pi / 4), np.sin(np.pi / 4)]) * 0.12, atol=1e-7
            )

            # Cell edit recalculates proportions while preserving segment styles
            restored.raw.iat[0, 1] = 5
            recalc = analyse(PARTS_GRAPH, restored.frame(mask_excluded=True), reopened_options)
            self.assertAlmostEqual(recalc.tables["Composition"]["Percent"].iloc[0], 62.5)
            np.testing.assert_allclose(recalc.figure.axes[0].patches[0].get_facecolor(), to_rgba("#d62728"))
            self.assertFalse(recalc.figure.axes[0].patches[1].get_visible())

            # Cell exclusion recalculates remaining rows while keeping row-keyed styles on active sheet rows
            restored.excluded.add((0, 1))
            after_excl = analyse(PARTS_GRAPH, restored.frame(mask_excluded=True), reopened_options)
            self.assertEqual(len(after_excl.figure.axes[0].patches), 2)
            self.assertEqual([p.get_visible() for p in after_excl.figure.axes[0].patches], [False, True])
            np.testing.assert_allclose(after_excl.figure.axes[0].patches[1].get_facecolor(), to_rgba("#1f77b4"))

            # Use Result as Data produces a valid Dataset from the Composition result table
            derived = Dataset(reopened_res.tables["Composition"].rename(columns=str).reset_index(drop=True))
            self.assertEqual(list(derived.frame().columns), ["Category", "Value", "Fraction", "Percent"])
            self.assertEqual(len(derived.frame()), 4)

            # Export SVG and PNG
            svg_path = Path(tmp) / "bars.svg"
            png_path = Path(tmp) / "bars.png"
            export_figure(reopened_res.figure, svg_path, {"format": "svg", "svg_text": "text"})
            export_figure(reopened_res.figure, png_path, {"format": "png", "dpi": 150})
            self.assertIn("<svg", svg_path.read_text(encoding="utf-8"))
            self.assertGreater(png_path.stat().st_size, 1000)
