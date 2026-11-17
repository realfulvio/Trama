"""Unit and Matplotlib integration tests for axis guides and shaded bands."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree as ET

import numpy as np
import pandas as pd
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FixedLocator

from analisi.axis_guides import (
    AXIS_BANDS,
    AXIS_GUIDES,
    BAND_HATCHES,
    MAX_BANDS,
    MAX_GUIDES_PER_AXIS,
    merge_ticks,
    normalise_bands,
    normalise_guides,
    ulp_close,
)
from analisi.category_graphs import category_graph
from analisi.figure_export import export_figure, export_pdf_bundle
from analisi.forest_plot import forest_plot
from analisi.layout_pdf import PdfLayoutPage
from analisi.layout_svg import export_layout_svg
from analisi.presentation import apply_style, capture_defaults, graph_series, validate_graph_style, validated_style
from analisi.probability_scale import FRACTION_SCALE
from analisi.workbench import _preview_figure
from analisi.xy_series import xy_series


UUIDS = [f"a0000000-0000-4000-8000-{i:012d}" for i in range(1, 80)]


def _guide(index=0, **overrides):
    base = {
        "id": UUIDS[index],
        "axis": "x",
        "value": float(index + 1),
    }
    base.update(overrides)
    return base


def _band(index=0, **overrides):
    base = {
        "id": UUIDS[index],
        "axis": "x",
        "lower": float(index + 1),
        "upper": float(index + 2),
        "color": "#aabbcc",
    }
    base.update(overrides)
    return base


class NormaliseGuidesTests(unittest.TestCase):
    def test_defaults_and_non_mutation(self):
        raw = [_guide(0, value=2)]
        snapshot = deepcopy(raw)
        out = normalise_guides(raw)
        self.assertEqual(raw, snapshot)
        self.assertIsNot(out, raw)
        self.assertEqual(
            out[0],
            {
                "id": UUIDS[0],
                "axis": "x",
                "value": 2.0,
                "tick": False,
                "line": True,
                "label": "",
                "color": "#657486",
                "width": 1.0,
                "style": "--",
                "visible": True,
            },
        )

    def test_optional_fields_and_boundaries(self):
        g = _guide(
            0,
            value=1e-100,
            tick=True,
            line=False,
            label="$literal$, \\frac{1}{2} (a)",
            color="teal",
            width=0.2,
            style="-.",
            visible=True,
            label_color="#112233",
            font_size=72,
            side="opposite",
        )
        out = normalise_guides([g])[0]
        self.assertEqual(out["width"], 0.2)
        self.assertEqual(out["font_size"], 72.0)
        self.assertEqual(out["side"], "opposite")
        self.assertEqual(out["label_color"], "#112233")
        out_max_w = normalise_guides([_guide(1, width=8, font_size=4)])[0]
        self.assertEqual((out_max_w["width"], out_max_w["font_size"]), (8.0, 4.0))

    def test_invalid_guides_rejected(self):
        bad_cases = [
            "not-a-list",
            [_guide(0, unknown=1)],
            [{"axis": "x", "value": 1.0}],
            [_guide(0, id="not-a-uuid")],
            [_guide(0, id=UUIDS[0].upper())],
            [_guide(0, id=UUIDS[0]), _guide(0, id=UUIDS[0], value=2.0)],
            [_guide(0, axis="z")],
            [_guide(0, value=True)],
            [_guide(0, value=float("nan"))],
            [_guide(0, value=float("inf"))],
            [_guide(0, value=float("-inf"), visible=False)],
            [_guide(0, tick="yes")],
            [_guide(0, line=1)],
            [_guide(0, visible="true")],
            [_guide(0, tick=False, line=False, visible=True)],
            [_guide(0, label="a\nb")],
            [_guide(0, label="a\rb")],
            [_guide(0, label="x" * 161)],
            [_guide(0, color="not-a-color")],
            [_guide(0, color="none")],
            [_guide(0, label_color="bad")],
            [_guide(0, width=0.19)],
            [_guide(0, width=8.01)],
            [_guide(0, width=True)],
            [_guide(0, style="solid")],
            [_guide(0, font_size=3.99)],
            [_guide(0, font_size=72.01)],
            [_guide(0, side="right")],
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises((ValueError, TypeError)):
                    normalise_guides(case)

    def test_hidden_guide_without_tick_or_line_allowed(self):
        out = normalise_guides([_guide(0, tick=False, line=False, visible=False)])
        self.assertFalse(out[0]["visible"])

    def test_tick_collision_ulp_and_budget(self):
        # Two visible ticks at same / 8-ULP coordinate collide
        with self.assertRaises(ValueError):
            normalise_guides([
                _guide(0, axis="x", value=1e-100, tick=True),
                _guide(1, axis="x", value=1.0000000000000001e-100, tick=True),
            ])
        # Allowed if one is hidden, or one has tick=False, or different axes
        ok = normalise_guides([
            _guide(0, axis="x", value=2.0, tick=True, line=True),
            _guide(1, axis="x", value=2.0, tick=False, line=True),
            _guide(2, axis="x", value=2.0, tick=True, visible=False),
            _guide(3, axis="y", value=2.0, tick=True),
        ])
        self.assertEqual(len(ok), 4)

        # Budget: 30 per axis (including hidden), 60 total
        x_30 = [_guide(i, axis="x", value=float(i), visible=(i % 2 == 0)) for i in range(MAX_GUIDES_PER_AXIS)]
        y_30 = [_guide(30 + i, axis="y", value=float(i)) for i in range(MAX_GUIDES_PER_AXIS)]
        self.assertEqual(len(normalise_guides(x_30 + y_30)), 60)
        with self.assertRaises(ValueError):
            normalise_guides(x_30 + [_guide(60, axis="x", value=99.0, visible=False)])


class NormaliseBandsTests(unittest.TestCase):
    def test_valid_hatches_and_defaults(self):
        for idx, hatch in enumerate(BAND_HATCHES):
            band = normalise_bands([_band(idx, hatch=hatch)])[0]
            self.assertEqual(band["hatch"], hatch)
            self.assertEqual(band["alpha"], 0.15)
            self.assertTrue(band["visible"])

    def test_invalid_bands_and_budget(self):
        bad_cases = [
            "bad",
            [_band(0, extra=1)],
            [_band(0, id="bad")],
            [_band(0), _band(0, lower=5.0, upper=6.0)],
            [_band(0, axis="z")],
            [_band(0, lower=3.0, upper=3.0)],
            [_band(0, lower=4.0, upper=2.0)],
            [_band(0, lower=-1e308, upper=1e308)],  # non-representable span
            [_band(0, lower=True)],
            [_band(0, upper=float("nan"))],
            [_band(0, color="nope")],
            [_band(0, alpha=-0.01)],
            [_band(0, alpha=1.01)],
            [_band(0, alpha=True)],
            [_band(0, hatch="xx")],
            [_band(0, visible=0)],
        ]
        for case in bad_cases:
            with self.subTest(case=case):
                with self.assertRaises((ValueError, TypeError)):
                    normalise_bands(case)

        twelve = [_band(i) for i in range(MAX_BANDS)]
        self.assertEqual(len(normalise_bands(twelve)), MAX_BANDS)
        with self.assertRaises(ValueError):
            normalise_bands(twelve + [_band(MAX_BANDS)])


class MergeTicksTests(unittest.TestCase):
    def test_tiny_ulp_scientific_and_log_domain(self):
        self.assertTrue(ulp_close(1e-100, 1.0000000000000001e-100))
        # Empty label on existing tick keeps regular label; empty label on new tick formats with .12g
        locs, labels = merge_ticks(
            [1.0, 2.0, 3.0],
            ["1e+00", "2e+00", "3e+00"],
            [
                {"id": "a", "value": 2.0, "tick": True, "label": ""},
                {"id": "b", "value": 2.5, "tick": True, "label": ""},
                {"id": "c", "value": 3.0, "tick": True, "label": "$raw$, (x)"},
            ],
            0.0,
            4.0,
            "linear",
        )
        self.assertEqual(locs, [1.0, 2.0, 2.5, 3.0])
        self.assertEqual(labels, ["1e+00", "2e+00", "2.5", "$raw$, (x)"])

        # Visible tick <= 0 on log fails; hidden tick <= 0 allowed
        with self.assertRaises(ValueError):
            merge_ticks([1.0, 10.0], ["1", "10"], [{"id": "a", "value": 0.0, "tick": True}], 0.1, 100.0, "log")
        locs, labels = merge_ticks(
            [1.0, 10.0],
            ["1", "10"],
            [{"id": "a", "value": -1.0, "tick": True, "visible": False}],
            0.1,
            100.0,
            "log",
        )
        self.assertEqual((locs, labels), ([1.0, 10.0], ["1", "10"]))


class RenderingAndIntegrationTests(unittest.TestCase):
    @staticmethod
    def _xy_figure():
        fig = Figure()
        FigureCanvasAgg(fig)
        ax = fig.add_subplot()
        ax.plot([0.0, 1.0, 2.0, 3.0, 4.0], [1.0, 2.0, 4.0, 2.0, 1.0], label="Series")
        ax.set_xlim(0.0, 4.0)
        ax.set_ylim(0.0, 5.0)
        ax.legend()
        return fig, ax

    def test_domain_errors_do_not_mutate_figure(self):
        fig, ax = self._xy_figure()
        ax.set_xlim(1.0, 100.0)
        ax.set_ylim(1.0, 100.0)
        ax.set_yscale("log")
        capture_defaults(fig)
        valid = {
            AXIS_GUIDES: [_guide(0, axis="y", value=10.0, tick=True, line=True, label="Ten")],
            AXIS_BANDS: [_band(0, axis="y", lower=2.0, upper=20.0)],
        }
        apply_style(fig, valid)
        before_children = list(ax.get_children())
        before_ylim = ax.get_ylim()
        before_locator = ax.yaxis.get_major_locator()

        # Visible guide at 0 on log must fail BEFORE changing anything
        bad = {AXIS_GUIDES: [_guide(0, axis="y", value=0.0, tick=False, line=True)]}
        with self.assertRaises(ValueError):
            apply_style(fig, bad)
        self.assertEqual(list(ax.get_children()), before_children)
        self.assertEqual(ax.get_ylim(), before_ylim)
        self.assertIs(ax.yaxis.get_major_locator(), before_locator)

        # Visible band with lower <= 0 on log must also fail before mutation
        bad_band = {AXIS_BANDS: [_band(0, axis="y", lower=-1.0, upper=5.0)]}
        with self.assertRaises(ValueError):
            apply_style(fig, bad_band)
        self.assertEqual(list(ax.get_children()), before_children)

        # Hidden guide with value=0 on log is allowed
        hidden_log = {AXIS_GUIDES: [_guide(0, axis="y", value=0.0, tick=True, line=False, visible=False)]}
        apply_style(fig, hidden_log)

    def test_rejected_axis_kinds_and_allowed_numeric_axes(self):
        # Probability axis rejected
        fig, ax = self._xy_figure()
        ax.plot([0.1, 0.5, 0.9], [0.2, 0.5, 0.8])
        ax.set_yscale(FRACTION_SCALE)
        with self.assertRaises(ValueError):
            validate_graph_style(ax, {AXIS_GUIDES: [_guide(0, axis="y", value=0.5)]})
        with self.assertRaises(ValueError):
            validate_graph_style(ax, {AXIS_BANDS: [_band(0, axis="y", lower=0.2, upper=0.8)]})

        # Column graph: X categorical rejected, Y numeric allowed
        col_df = pd.DataFrame({"Ctrl": [1.0, 2.0, 3.0], "Drug": [2.0, 4.0, 5.0]})
        col_res = category_graph(col_df, {"Variables": ["Ctrl", "Drug"]})
        col_ax = col_res.figure.axes[0]
        with self.assertRaises(ValueError):
            validate_graph_style(col_ax, {AXIS_GUIDES: [_guide(0, axis="x", value=0.0)]})
        apply_style(col_res.figure, {
            AXIS_GUIDES: [_guide(0, axis="y", value=3.0, tick=True, label="Threshold")],
            AXIS_BANDS: [_band(0, axis="y", lower=1.5, upper=3.5)],
        })

        # Forest plot: X numeric (FuncFormatter + LogLocator) allowed, Y categorical rejected
        forest_df = pd.DataFrame({
            "Study": ["A", "B"],
            "Estimate": [1.2, 2.0],
            "Lower": [0.8, 1.3],
            "Upper": [1.8, 3.1],
        })
        forest_res = forest_plot(forest_df, {
            "Input": "One study per row",
            "Study": "Study",
            "Estimate": "Estimate",
            "Lower limit": "Lower",
            "Upper limit": "Upper",
            "Scale": "Log10",
        })
        forest_ax = forest_res.figure.axes[0]
        with self.assertRaises(ValueError):
            validate_graph_style(forest_ax, {AXIS_GUIDES: [_guide(0, axis="y", value=0.5)]})
        apply_style(forest_res.figure, {AXIS_GUIDES: [_guide(0, axis="x", value=1.5, tick=True, label="Mid")]})

        # Non-native preview image rejected
        from PIL import Image
        preview_fig = _preview_figure(Image.new("RGB", (100, 100), "white"))
        with self.assertRaises(ValueError):
            validate_graph_style(preview_fig.axes[0], {AXIS_GUIDES: [_guide(0, axis="x", value=0.5)]})

    def test_numeric_fixed_locator_not_confused_as_categorical(self):
        fig, ax = self._xy_figure()
        ax.xaxis.set_major_locator(FixedLocator([0.0, 2.0, 4.0]))
        apply_style(fig, {AXIS_GUIDES: [_guide(0, axis="x", value=2.5, tick=True, label="Mid")]})
        self.assertEqual([t.get_text() for t in ax.get_xticklabels()], ["0", "2", "Mid", "4"])

    def test_xy_two_y_axes_leaves_right_axis_untouched(self):
        frame = pd.DataFrame({"X": [0.0, 1.0, 2.0, 3.0], "Left": [1.0, 2.0, 3.0, 4.0], "Right": [100.0, 200.0, 300.0, 400.0]})
        res = xy_series(frame, {
            "X": "X",
            "Y columns": ["Left", "Right"],
            "Series side": {"Left": "Left", "Right": "Right"},
        })
        left_ax, right_ax = res.figure.axes
        right_before = (right_ax.get_ylim(), list(right_ax.get_yticks()), len(right_ax.get_children()))
        apply_style(res.figure, {
            AXIS_GUIDES: [
                _guide(0, axis="y", value=2.5, tick=True, line=True, label="Opp", side="opposite"),
                _guide(1, axis="x", value=1.5, tick=True, line=True, label="Mid"),
            ],
        })
        self.assertEqual(right_ax.get_ylim(), right_before[0])
        self.assertEqual(list(right_ax.get_yticks()), right_before[1])
        self.assertEqual(len(right_ax.get_children()), right_before[2])
        gids = [a.get_gid() or "" for a in left_ax.get_children()]
        self.assertIn(f"trama-axis-guide:{UUIDS[0]}:tick", gids)
        self.assertIn(f"trama-axis-guide:{UUIDS[0]}:label", gids)

    def test_dynamic_locator_zoom_scientific_and_literal_labels(self):
        fig = Figure()
        FigureCanvasAgg(fig)
        ax = fig.add_subplot()
        ax.plot([0.0, 1e6, 2e6], [1.0, 2.0, 3.0])
        style = {
            AXIS_GUIDES: [
                _guide(0, axis="x", value=5e5, tick=True, line=True, label="$literal$"),
                _guide(1, axis="x", value=1.8e6, tick=True, line=False, label="Far"),
            ]
        }
        apply_style(fig, style)
        fig.canvas.draw()
        self.assertEqual(ax.xaxis.get_offset_text().get_text(), "1e6")
        labels_full = [t.get_text() for t in ax.get_xticklabels()]
        self.assertIn("$literal$", labels_full)
        self.assertIn("Far", labels_full)
        literal_tick = next(t for t in ax.xaxis.majorTicks if t.label1.get_text() == "$literal$")
        self.assertFalse(literal_tick.label1.get_parse_math())

        # Zoom in: regular ticks update dynamically and out-of-view custom tick (1.8e6) disappears
        ax.set_xlim(0.0, 1e6)
        fig.canvas.draw()
        zoomed_locs = list(ax.get_xticks())
        self.assertTrue(all(0.0 <= v <= 1e6 for v in zoomed_locs))
        self.assertIn(5e5, zoomed_locs)
        self.assertNotIn(1.8e6, zoomed_locs)

    def test_idempotence_restore_and_series_unaffected(self):
        fig, ax = self._xy_figure()
        style = {
            AXIS_GUIDES: [
                _guide(0, axis="x", value=2.5, tick=True, line=True, label="Cut"),
                _guide(1, axis="y", value=3.0, tick=False, line=True, label="Ref"),
            ],
            AXIS_BANDS: [_band(0, axis="x", lower=1.0, upper=3.0, hatch="/", alpha=0.2)],
        }
        orig_children_count = len(ax.get_children())
        orig_legend_labels = ax.get_legend_handles_labels()[1]
        for _ in range(10):
            apply_style(fig, style)
        fig.canvas.draw()
        # Line/label/band artists are constant and do not enter graph_series or legend
        count_after_10 = len(ax.get_children())
        apply_style(fig, style)
        self.assertEqual(len(ax.get_children()), count_after_10)
        self.assertEqual(len(graph_series(ax)), 1)
        self.assertEqual(ax.get_legend_handles_labels()[1], orig_legend_labels)

        # Reset to empty removes all guide/band artists and restores original locator/formatter/ticks
        apply_style(fig, {})
        fig.canvas.draw()
        self.assertEqual(len(ax.get_children()), orig_children_count)
        self.assertFalse(any(str(a.get_gid()).startswith(("trama-axis-guide:", "trama-axis-band:"))
                             for a in ax.get_children()))
        self.assertFalse(any(t.label1.get_gid() is not None for t in ax.xaxis.majorTicks))

    def test_vector_export_svg_pdf_and_two_panel_layout(self):
        fig1, _ = self._xy_figure()
        fig2, _ = self._xy_figure()
        style1 = {
            AXIS_GUIDES: [_guide(0, axis="x", value=2.5, tick=True, line=True, label="$literal$")],
            AXIS_BANDS: [_band(0, axis="x", lower=1.0, upper=3.0, hatch="/", alpha=0.2)],
        }
        style2 = {
            AXIS_GUIDES: [_guide(1, axis="y", value=2.5, tick=True, line=True, label="Target, B", side="opposite")],
            AXIS_BANDS: [_band(1, axis="y", lower=1.5, upper=3.5, hatch="o", alpha=0.25)],
        }
        apply_style(fig1, style1)
        apply_style(fig2, style2)

        with TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            svg_path = out_dir / "single.svg"
            pdf_path = out_dir / "single.pdf"
            png_path = out_dir / "single.png"
            layout_svg = out_dir / "layout.svg"
            layout_pdf = out_dir / "layout.pdf"

            export_figure(fig1, svg_path, {"format": "svg", "svg_text": "text"})
            export_figure(fig1, pdf_path, {"format": "pdf"})
            export_figure(fig1, png_path, {"format": "png", "dpi": 120})
            export_layout_svg("Two panels", 2, [fig1, fig2], layout_svg, {"format": "svg", "svg_text": "text"})
            export_pdf_bundle([PdfLayoutPage("Two panels", 2, (fig1, fig2))], layout_pdf, {"format": "pdf"})

            svg_text = svg_path.read_text(encoding="utf-8")
            self.assertNotIn("<image", svg_text)
            self.assertIn("$literal$", svg_text)
            self.assertIn(f"trama-axis-band:{UUIDS[0]}", svg_text)

            layout_text = layout_svg.read_text(encoding="utf-8")
            self.assertNotIn("<image", layout_text)
            self.assertIn(f"panel1-trama-axis-band:{UUIDS[0]}", layout_text)
            self.assertIn(f"panel2-trama-axis-band:{UUIDS[1]}", layout_text)
            ET.parse(layout_svg)  # valid XML
            self.assertTrue(pdf_path.read_bytes().startswith(b"%PDF"))
            self.assertTrue(layout_pdf.read_bytes().startswith(b"%PDF"))
            self.assertGreater(png_path.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
