"""Unit tests for Q–Q panel identity, validation, isolated styling, and project round-trip."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.markers import MarkerStyle
import numpy as np
import pandas as pd

from analisi.data import Dataset, load_workspace, save_project
from analisi.normality import NORMALITY, QQ_LINE, QQ_PLOT, QQ_VARIABLE
from analisi.presentation import AUTO_PAPER, WHITE, apply_style, compose_layout, validated_style
from analisi.qq_panels import PANEL_KEY, normalize_panel_styles, panel_axes
from analisi.workbench import analyse


class QQPanelsBackendTests(unittest.TestCase):
    def test_empty_axis_records_restore_automatic_limits_without_key_errors(self):
        result = self.run_normality()
        original = [ax.get_xlim() for ax in result.figure.axes]
        style = {PANEL_KEY:{name:{"axis":{"x":{},"y":{}}} for name in ("normal","lognormal")}}
        validated_style(style)
        apply_style(result.figure,style)
        for ax,bounds in zip(result.figure.axes,original):
            np.testing.assert_array_equal(ax.get_xlim(),bounds)

    def test_arbitrarily_large_integer_limit_is_a_validation_error(self):
        with self.assertRaises(ValueError):
            normalize_panel_styles({"normal":{"axis":{"x":{"min":0,"max":10**1000}}}})

    def test_dialog_retains_full_precision_limits_when_opened(self):
        from analisi.qq_panel_dialog import QQPanelsDialog
        dialog = object.__new__(QQPanelsDialog)
        dialog._default_legend_visible={"normal":True}
        low,high=1.234567891234567,2.345678912345678
        values=dialog._inputs_from_style({"axis":{"x":{"min":low,"max":high}}},"normal")
        self.assertEqual(float(values['xmin']),low)
        self.assertEqual(float(values['xmax']),high)

    def setUp(self):
        self.frame = pd.DataFrame({
            "A": [1.0, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0, 16.0],
            "B": [2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 13.0, 20.0],
        })

    def run_normality(self, mode="Both", *, show_line=True):
        return analyse(
            NORMALITY,
            self.frame,
            {"Variables": ["A"], "Distribution": mode, QQ_PLOT: True, QQ_VARIABLE: "A", QQ_LINE: show_line},
        )

    def test_panel_axes_identifies_modes_without_title_heuristics_and_ignores_non_qq(self):
        both = self.run_normality("Both")
        normal_only = self.run_normality("Normal")
        log_only = self.run_normality("Lognormal")

        self.assertEqual(set(panel_axes(both.figure)), {"normal", "lognormal"})
        self.assertEqual(set(panel_axes(normal_only.figure)), {"normal"})
        self.assertEqual(set(panel_axes(log_only.figure)), {"lognormal"})
        self.assertIs(panel_axes(log_only.figure)["lognormal"], log_only.figure.axes[0])

        # Identical or translated titles do not break canonical identity.
        for axis in both.figure.axes:
            axis.set_title("Titolo uguale")
        self.assertEqual(set(panel_axes(both.figure)), {"normal", "lognormal"})

        # Non-Q-Q figures never acquire Q-Q panel IDs even if titles mention Q-Q.
        lin = analyse("Linear regression", self.frame, {"X": "A", "Y": "B"})
        lin.figure.axes[0].set_title("Normal Q–Q plot")
        self.assertEqual(panel_axes(lin.figure), {})

        plain = Figure()
        ax = plain.add_subplot()
        ax.set_title("Lognormal Q–Q plot")
        self.assertEqual(panel_axes(plain), {})

    def test_normalize_panel_styles_validation_and_immutability(self):
        raw = {
            "normal": {"title": "Left $x$ {1}", "axis": {"x": {"min": -2.0, "max": 2.0}}},
            "lognormal": {"ylabel": "Log {A}", "legend_visible": False},
        }
        snapshot = deepcopy(raw)
        normalized = normalize_panel_styles(raw)
        self.assertEqual(normalized, raw)
        self.assertIsNot(normalized, raw)
        normalized["normal"]["axis"]["x"]["min"] = -99.0
        self.assertEqual(raw, snapshot)

        malformed_cases = [
            None,
            [],
            "normal",
            {"other": {}},
            {"normal": "bad"},
            {"normal": {"unknown": 1}},
            {"normal": {"title": "a" * 161}},
            {"normal": {"xlabel": 123}},
            {"normal": {"legend_visible": 1}},
            {"normal": {"axis": "x"}},
            {"normal": {"axis": {"z": {"min": 0.0, "max": 1.0}}}},
            {"normal": {"axis": {"x": {"min": 0.0}}}},
            {"normal": {"axis": {"x": {"max": 1.0}}}},
            {"normal": {"axis": {"x": {"min": True, "max": 1.0}}}},
            {"normal": {"axis": {"y": {"min": 0.0, "max": float("nan")}}}},
            {"normal": {"axis": {"y": {"min": float("-inf"), "max": 1.0}}}},
            {"normal": {"axis": {"x": {"min": 2.0, "max": 2.0}}}},
            {"normal": {"axis": {"x": {"min": 3.0, "max": 1.0}}}},
            {"normal": {"axis": {"x": {"min": 1.0, "max": 1.0 + 1e-16}}}},
        ]
        for bad in malformed_cases:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_panel_styles(bad)

    def test_right_and_left_panels_are_isolated_literal_linear_and_preserve_data(self):
        result = self.run_normality("Both")
        panels = panel_axes(result.figure)
        left, right = panels["normal"], panels["lognormal"]
        left_title = left.get_title()
        left_xlim = left.get_xlim()
        left_ylim = left.get_ylim()
        left_offsets = left.collections[0].get_offsets().copy()
        right_offsets = right.collections[0].get_offsets().copy()
        right_line = right.lines[0].get_xydata().copy()

        right_style = {
            PANEL_KEY: {
                "lognormal": {
                    "title": "Right $x$ {B} è",
                    "xlabel": "Q {z}$",
                    "ylabel": "ln({A})",
                    "axis": {"x": {"min": -2.5, "max": 2.5}, "y": {"min": -4.0, "max": 2.0}},
                    "legend_visible": False,
                }
            }
        }
        apply_style(result.figure, right_style)
        self.assertEqual(left.get_title(), left_title)
        self.assertEqual(left.get_xlim(), left_xlim)
        self.assertEqual(left.get_ylim(), left_ylim)
        self.assertTrue(left.get_legend().get_visible())
        self.assertEqual(right.get_title(), "Right $x$ {B} è")
        self.assertEqual(right.get_xlabel(), "Q {z}$")
        self.assertEqual(right.get_ylabel(), "ln({A})")
        self.assertFalse(right.title.get_parse_math())
        self.assertFalse(right.xaxis.label.get_parse_math())
        self.assertFalse(right.yaxis.label.get_parse_math())
        self.assertEqual(right.get_xscale(), "linear")
        self.assertEqual(right.get_yscale(), "linear")
        np.testing.assert_allclose(right.get_xlim(), (-2.5, 2.5))
        np.testing.assert_allclose(right.get_ylim(), (-4.0, 2.0))
        self.assertFalse(right.get_legend().get_visible())
        np.testing.assert_array_equal(left.collections[0].get_offsets(), left_offsets)
        np.testing.assert_array_equal(right.collections[0].get_offsets(), right_offsets)
        np.testing.assert_array_equal(right.lines[0].get_xydata(), right_line)

        # Global title affects the left panel, while panel override still takes precedence over global.
        apply_style(result.figure, {"title": "Global Left", PANEL_KEY: {"lognormal": {"title": "Right Only"}}})
        self.assertEqual(left.get_title(), "Global Left")
        self.assertEqual(right.get_title(), "Right Only")
        apply_style(result.figure, {
            "title": "Global Left",
            PANEL_KEY: {"normal": {"title": "Left Override"}, "lognormal": {"title": "Right Only"}},
        })
        self.assertEqual(left.get_title(), "Left Override")
        self.assertEqual(right.get_title(), "Right Only")
        # Resetting normal panel override restores global Left title.
        apply_style(result.figure, {"title": "Global Left", PANEL_KEY: {"lognormal": {"title": "Right Only"}}})
        self.assertEqual(left.get_title(), "Global Left")

    def test_legend_toggle_when_no_reference_line_exists_creates_and_restores_absence(self):
        result = self.run_normality("Both", show_line=False)
        panels = panel_axes(result.figure)
        self.assertIsNone(panels["normal"].get_legend())
        self.assertIsNone(panels["lognormal"].get_legend())

        apply_style(result.figure, {PANEL_KEY: {"lognormal": {"legend_visible": True}}})
        self.assertIsNone(panels["normal"].get_legend())
        leg = panels["lognormal"].get_legend()
        self.assertIsNotNone(leg)
        self.assertTrue(leg.get_visible())
        self.assertEqual([t.get_text() for t in leg.get_texts()], ["Observed values"])
        self.assertEqual(len(panels["lognormal"].lines), 0)

        # Resetting or clearing restores initial absence without inventing a reference line.
        apply_style(result.figure, {})
        self.assertIsNone(panels["lognormal"].get_legend())
        self.assertEqual(len(panels["lognormal"].lines), 0)

    def test_atomic_validation_preserves_prior_preview_and_repeated_apply_does_not_duplicate(self):
        result = self.run_normality("Both")
        panels = panel_axes(result.figure)
        apply_style(result.figure, {PANEL_KEY: {"normal": {"title": "Kept Left"}, "lognormal": {"title": "Kept Right"}}})
        with self.assertRaises(ValueError):
            apply_style(result.figure, {
                PANEL_KEY: {"normal": {"title": "Bad"}, "lognormal": {"axis": {"y": {"min": 5.0, "max": 1.0}}}}
            })
        self.assertEqual(panels["normal"].get_title(), "Kept Left")
        self.assertEqual(panels["lognormal"].get_title(), "Kept Right")

        for _ in range(3):
            apply_style(result.figure, {PANEL_KEY: {"lognormal": {"legend_visible": True, "title": "Repeat"}}})
        self.assertEqual(len(result.figure.axes), 2)
        self.assertEqual(len(panels["lognormal"].collections), 1)
        self.assertEqual(len(panels["lognormal"].lines), 1)

    def test_inactive_panel_survives_mode_transitions_and_exports_succeed(self):
        style = {
            "title": "Left Global",
            PANEL_KEY: {"lognormal": {"title": "Saved Right", "axis": {"x": {"min": -2.0, "max": 2.0}}}},
        }
        ds = Dataset(
            self.frame.copy(),
            analyses=[(NORMALITY, {"Variables": ["A"], "Distribution": "Both", QQ_PLOT: True, QQ_VARIABLE: "A"})],
            graph_styles={0: style},
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "qq.alab"
            save_project(path, {"D": ds})
            loaded, _ = load_workspace(path)
            self.assertEqual(loaded["D"].graph_styles[0], style)

        # Switching Both -> Normal keeps inactive lognormal style harmless; switching back restores it.
        norm = self.run_normality("Normal")
        norm_title = norm.figure.axes[0].get_title()
        apply_style(norm.figure, {PANEL_KEY: style[PANEL_KEY]})
        self.assertEqual(norm.figure.axes[0].get_title(), norm_title)

        both = self.run_normality("Both")
        apply_style(both.figure, style)
        self.assertEqual(panel_axes(both.figure)["lognormal"].get_title(), "Saved Right")
        FigureCanvasAgg(both.figure).draw()
        for fmt in ("png", "svg", "pdf"):
            buf = BytesIO()
            both.figure.savefig(buf, format=fmt)
            self.assertGreater(len(buf.getvalue()), 200)

    def test_points_and_reference_line_schema_normalization(self):
        raw = {
            "normal": {
                "points": {"visible": True, "marker": "s", "size": 7.0, "color": "#127a78", "alpha": 0.65},
                "reference_line": {"visible": True, "color": "#D1553A", "width": 2.0, "style": "--", "alpha": 0.8},
            },
            "lognormal": {
                "points": {"size": 0.5, "alpha": 0.0, "marker": "+", "color": "#aBcDeF"},
                "reference_line": {"visible": False, "width": 10.0, "style": ":"},
            },
        }
        snapshot = deepcopy(raw)
        out = normalize_panel_styles(raw)
        self.assertEqual(out, raw)
        self.assertEqual(out["normal"]["points"]["color"], "#127a78")
        self.assertEqual(out["normal"]["reference_line"]["color"], "#D1553A")
        self.assertEqual(out["lognormal"]["points"]["color"], "#aBcDeF")
        out["normal"]["points"]["size"] = 12.0
        self.assertEqual(raw, snapshot)
        self.assertEqual(
            normalize_panel_styles({"normal": {"points": {}, "reference_line": {}}}),
            {"normal": {"points": {}, "reference_line": {}}},
        )

        malformed = [
            {"normal": {"points": "bad"}},
            {"normal": {"points": {"unknown": 1}}},
            {"normal": {"points": {"visible": 1}}},
            {"normal": {"points": {"marker": "*"}}},
            {"normal": {"points": {"marker": "none"}}},
            {"normal": {"points": {"size": True}}},
            {"normal": {"points": {"size": 0.49}}},
            {"normal": {"points": {"size": 36.01}}},
            {"normal": {"points": {"size": 10**400}}},
            {"normal": {"points": {"size": float("nan")}}},
            {"normal": {"points": {"size": float("inf")}}},
            {"normal": {"points": {"alpha": False}}},
            {"normal": {"points": {"alpha": -0.01}}},
            {"normal": {"points": {"alpha": 1.01}}},
            {"normal": {"points": {"alpha": float("nan")}}},
            {"normal": {"points": {"color": "red"}}},
            {"normal": {"points": {"color": "#12345"}}},
            {"normal": {"points": {"color": "#1234567"}}},
            {"normal": {"points": {"color": "#123456ff"}}},
            {"normal": {"reference_line": []}},
            {"normal": {"reference_line": {"unknown": 1}}},
            {"normal": {"reference_line": {"visible": "yes"}}},
            {"normal": {"reference_line": {"color": "blue"}}},
            {"normal": {"reference_line": {"width": True}}},
            {"normal": {"reference_line": {"width": 0.09}}},
            {"normal": {"reference_line": {"width": 10.01}}},
            {"normal": {"reference_line": {"width": 10**400}}},
            {"normal": {"reference_line": {"width": float("inf")}}},
            {"normal": {"reference_line": {"style": "dashed"}}},
            {"normal": {"reference_line": {"alpha": -0.1}}},
            {"normal": {"reference_line": {"alpha": 1.5}}},
        ]
        for bad in malformed:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_panel_styles(bad)

    def test_artist_metadata_and_all_markers_linestyles_area_alpha_and_foreign(self):
        result = self.run_normality("Both")
        ident = id(result.figure)
        axes = panel_axes(result.figure)
        for ax in axes.values():
            ax.set_title("Same Title")
        self.assertEqual(set(panel_axes(result.figure)), {"normal", "lognormal"})

        # Foreign artists added before styling must not be chosen or modified.
        left = axes["normal"]
        foreign_before = left.scatter([0.0], [1.0], color="#00ff00", s=120)
        foreign_before_rgba = foreign_before.get_facecolors().copy()
        foreign_line_before = left.plot([-1.0, 1.0], [1.0, 2.0], color="#ff00ff", linewidth=3.5)[0]

        pts = getattr(left, "_trama_qq_points", None)
        ref = getattr(left, "_trama_qq_reference", None)
        self.assertIsNotNone(pts)
        self.assertIsNotNone(ref)
        self.assertIsNot(pts, foreign_before)
        self.assertIsNot(ref, foreign_line_before)
        orig_offsets = pts.get_offsets().copy()
        self.assertEqual(pts.get_sizes()[0], 26.0)

        # Partial color-only keeps default area 26.
        apply_style(result.figure, {PANEL_KEY: {"normal": {"points": {"color": "#112233"}}}})
        self.assertEqual(pts.get_sizes()[0], 26.0)

        # Check every valid marker and line style.
        for marker_code, ls in zip(("o", "s", "D", "^", "v", "+", "x"), ("-", "--", "-.", ":", "-", "--", "-.")):
            style = {
                PANEL_KEY: {
                    "normal": {
                        "points": {"marker": marker_code, "size": 7.0, "color": "#127A78", "alpha": 0.65},
                        "reference_line": {"color": "#D1553A", "width": 2.0, "style": ls, "alpha": 0.8},
                    }
                }
            }
            apply_style(result.figure, style)
            self.assertEqual(id(result.figure), ident)
            np.testing.assert_array_equal(pts.get_offsets(), orig_offsets)
            np.testing.assert_allclose(pts.get_sizes(), [49.0])
            np.testing.assert_allclose(pts.get_facecolors()[0], to_rgba("#127A78", 0.65))
            expected_path = MarkerStyle(marker_code).get_path().transformed(MarkerStyle(marker_code).get_transform())
            np.testing.assert_allclose(pts.get_paths()[0].vertices, expected_path.vertices)
            if marker_code in {"+", "x"}:
                np.testing.assert_allclose(pts.get_edgecolors()[0], to_rgba("#127A78", 0.65))
            self.assertEqual(ref.get_linestyle(), ls)
            self.assertEqual(ref.get_linewidth(), 2.0)
            self.assertEqual(ref.get_alpha(), 0.8)
            self.assertEqual(ref.get_color(), "#D1553A")

        foreign_after = left.scatter([0.5], [2.0], color="#abcdef", s=80)
        np.testing.assert_array_equal(foreign_before.get_facecolors(), foreign_before_rgba)
        np.testing.assert_array_equal(foreign_after.get_facecolors()[0], to_rgba("#abcdef", 1.0))
        self.assertEqual(foreign_line_before.get_linewidth(), 3.5)

        # Constant observations -> reference line unavailable (_trama_qq_reference is None) and never invented.
        const_df = self.frame.copy()
        const_df["A"] = 2.0
        const_res = analyse(
            NORMALITY, const_df,
            {"Variables": ["A"], "Distribution": "Normal", QQ_PLOT: True, QQ_VARIABLE: "A", QQ_LINE: True},
        )
        const_ax = panel_axes(const_res.figure)["normal"]
        self.assertIsNone(getattr(const_ax, "_trama_qq_reference"))
        lines_before = len(const_ax.lines)
        apply_style(const_res.figure, {PANEL_KEY: {"normal": {"reference_line": {"visible": True, "width": 3.0}}}})
        self.assertIsNone(getattr(const_ax, "_trama_qq_reference"))
        self.assertEqual(len(const_ax.lines), lines_before)

    def test_visibility_vs_zero_alpha_legend_coherence_reset_and_layout(self):
        result = self.run_normality("Both")
        ax = panel_axes(result.figure)["normal"]
        pts = getattr(ax, "_trama_qq_points")
        ref = getattr(ax, "_trama_qq_reference")
        orig_legend_texts = [t.get_text() for t in ax.get_legend().get_texts()]
        self.assertEqual(len(orig_legend_texts), 2)

        # Hidden points drop their legend item; alpha=0 keeps visible legend item.
        apply_style(result.figure, {PANEL_KEY: {"normal": {"points": {"visible": False}}}})
        self.assertFalse(pts.get_visible())
        self.assertTrue(ref.get_visible())
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], ["Fitted reference"])

        apply_style(result.figure, {PANEL_KEY: {"normal": {"points": {"alpha": 0.0}}}})
        self.assertTrue(pts.get_visible())
        np.testing.assert_allclose(pts.get_facecolors()[0], [0.15686275, 0.4, 0.68235294, 0.0], atol=1e-4)
        self.assertEqual([t.get_text() for t in ax.get_legend().get_texts()], orig_legend_texts)

        # Panel legend explicitly off stays off even when artists change.
        apply_style(result.figure, {PANEL_KEY: {"normal": {"legend_visible": False, "points": {"marker": "^"}}}})
        self.assertIsNotNone(ax.get_legend())
        self.assertFalse(ax.get_legend().get_visible())

        # Both hidden -> no visible non-empty legend.
        apply_style(
            result.figure,
            {PANEL_KEY: {"normal": {"points": {"visible": False}, "reference_line": {"visible": False}}}},
        )
        leg = ax.get_legend()
        self.assertTrue(leg is None or not leg.get_visible() or not leg.get_texts())

        # Full reset restores original 2 entries cleanly.
        apply_style(result.figure, {})
        self.assertTrue(pts.get_visible())
        self.assertTrue(ref.get_visible())
        self.assertEqual(pts.get_sizes()[0], 26.0)
        restored_leg = ax.get_legend()
        self.assertIsNotNone(restored_leg)
        self.assertTrue(restored_leg.get_visible())
        self.assertEqual([t.get_text() for t in restored_leg.get_texts()], orig_legend_texts)

        # Compose 2-panel layout with styled Q-Q figure & export SVG/PDF.
        styled = {
            PANEL_KEY: {
                "normal": {"points": {"marker": "D", "size": 8.0, "color": "#127A78", "alpha": 0.7}},
                "lognormal": {"reference_line": {"style": "-.", "width": 2.5, "color": "#D1553A"}},
            }
        }
        apply_style(result.figure, styled)
        lin = analyse("Linear regression", self.frame, {"X": "A", "Y": "B"})
        layout_fig = compose_layout("QQ Styled Layout", 2, [result.figure, lin.figure], paper=AUTO_PAPER, background=WHITE)
        FigureCanvasAgg(layout_fig).draw()
        svg_buf = BytesIO()
        layout_fig.savefig(svg_buf, format="svg")
        self.assertIn(b"<svg", svg_buf.getvalue())



if __name__ == "__main__":
    unittest.main()
