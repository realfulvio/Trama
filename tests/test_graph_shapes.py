"""Unit and integration tests for native graph shapes (lines, rectangles, ellipses)."""
import copy
from pathlib import Path
import tempfile
import unittest
import warnings
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_hex
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, Rectangle
import pandas as pd
from PIL import Image
import pypdfium2 as pdfium
from pypdfium2 import raw as pdfraw

from analisi.data import Dataset, load_project, save_project
from analisi.figure_export import export_figure, export_pdf_bundle
from analisi.grid_data import paste_block
from analisi.graph_shapes import SHAPES, draw_shapes, on_axis_domain, validate_shapes
from analisi.layout_pdf import PdfLayoutPage
from analisi.layout_svg import export_layout_svg
from analisi.presentation import apply_style, graph_series, validated_style
from analisi.workbench import analyse

RAW_SHAPES = [
    {
        "id": "00000000-0000-4000-8000-000000000001",
        "kind": "line",
        "units": "axes",
        "points": [[0.1, 0.2], [0.8, 0.7]],
        "stroke": "#c62b37",
        "width": 2.0,
        "line_style": "solid",
        "fill": None,
        "alpha": 1.0,
        "layer": "above",
    },
    {
        "id": "00000000-0000-4000-8000-000000000002",
        "kind": "rectangle",
        "units": "axes",
        "points": [[0.7, 0.8], [0.2, 0.3]],
        "stroke": "#216a94",
        "width": 1.5,
        "line_style": "dashed",
        "fill": "#dce8f5",
        "alpha": 0.6,
        "layer": "below",
    },
    {
        "id": "00000000-0000-4000-8000-000000000003",
        "kind": "ellipse",
        "units": "data",
        "points": [[2.0, 3.0], [6.0, 7.0]],
        "stroke": "#207a4b",
        "width": 2.5,
        "line_style": "dotted",
        "fill": None,
        "alpha": 0.8,
        "layer": "above",
    },
]

CANONICAL_SHAPES = [
    {
        "id": "00000000-0000-4000-8000-000000000001",
        "kind": "line",
        "units": "axes",
        "points": [[0.1, 0.2], [0.8, 0.7]],
        "stroke": "#c62b37",
        "width": 2.0,
        "line_style": "solid",
        "fill": None,
        "alpha": 1.0,
        "layer": "above",
    },
    {
        "id": "00000000-0000-4000-8000-000000000002",
        "kind": "rectangle",
        "units": "axes",
        "points": [[0.2, 0.3], [0.7, 0.8]],
        "stroke": "#216a94",
        "width": 1.5,
        "line_style": "dashed",
        "fill": "#dce8f5",
        "alpha": 0.6,
        "layer": "below",
    },
    {
        "id": "00000000-0000-4000-8000-000000000003",
        "kind": "ellipse",
        "units": "data",
        "points": [[2.0, 3.0], [6.0, 7.0]],
        "stroke": "#207a4b",
        "width": 2.5,
        "line_style": "dotted",
        "fill": None,
        "alpha": 0.8,
        "layer": "above",
    },
]

ANNOTATION = {
    "text": "Shape proof < 5 – città $literal$",
    "units": "axes",
    "position": [0.15, 0.9],
    "target": [0.5, 0.6],
    "color": "#174e78",
    "size": 10,
    "align": "left",
}


class GraphShapesTests(unittest.TestCase):
    def _make_figure(self, y=(2, 4, 7, 8)):
        fig = Figure(figsize=(4, 3), dpi=100)
        FigureCanvasAgg(fig)
        ax = fig.add_axes([0.2, 0.2, 0.6, 0.6])
        ax.plot([1, 2, 4, 6], list(y), label="Data", color="#111111")
        ax.set_xlim([0, 10])
        ax.set_ylim([0, 10])
        return fig, ax

    def test_validation_normalization_and_limits(self):
        self.assertEqual(SHAPES, "shapes")
        source = copy.deepcopy(RAW_SHAPES)
        normalized = validate_shapes(source)
        self.assertEqual(normalized, CANONICAL_SHAPES)
        self.assertEqual(source, RAW_SHAPES)
        normalized[0]["points"][0][0] = 0.45
        self.assertEqual(source, RAW_SHAPES)

        # Alpha 0 and 1 are valid
        zero_alpha = copy.deepcopy(CANONICAL_SHAPES[:1])
        zero_alpha[0]["alpha"] = 0.0
        self.assertEqual(validate_shapes(zero_alpha)[0]["alpha"], 0.0)

        for field, value in [
            ("kind", "polygon"),
            ("units", "figure"),
            ("stroke", "not-a-color"),
            ("stroke", "none"),
            ("width", True),
            ("width", 0.0),
            ("width", 12.5),
            ("width", float("nan")),
            ("alpha", False),
            ("alpha", -0.01),
            ("alpha", 1.01),
            ("alpha", float("inf")),
            ("line_style", "dashdot"),
            ("layer", "middle"),
            ("id", "not-a-uuid"),
            ("id", "00000000-0000-4000-8000-00000000000A"),
            ("fill", "#ff00ff"),  # line cannot have fill
        ]:
            bad = copy.deepcopy(CANONICAL_SHAPES)
            bad[0][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                validate_shapes(bad)

        bad_cases = [
            [dict(CANONICAL_SHAPES[0], points=[[0.2, 0.2], [0.2, 0.2]])],
            [dict(CANONICAL_SHAPES[0], points=[[True, 0.2], [0.8, 0.7]])],
            [dict(CANONICAL_SHAPES[0], points=[[float("inf"), 0.2], [0.8, 0.7]])],
            [dict(CANONICAL_SHAPES[0], points=[[-0.1, 0.2], [0.8, 0.7]])],
            [dict(CANONICAL_SHAPES[1], kind="rectangle", points=[[0.2, 0.3], [0.2, 0.8]])],
            [dict(CANONICAL_SHAPES[1], kind="ellipse", points=[[0.2, 0.3], [0.7, 0.3]])],
            [CANONICAL_SHAPES[0], CANONICAL_SHAPES[0]],
            {"shape": CANONICAL_SHAPES[0]},
            [dict(CANONICAL_SHAPES[0], extra_field=1)],
        ]
        for bad_records in bad_cases:
            with self.subTest(records=bad_records), self.assertRaises(ValueError):
                validate_shapes(copy.deepcopy(bad_records))

        hundred = [
            dict(copy.deepcopy(CANONICAL_SHAPES[0]), id=f"00000000-0000-4000-8000-{i:012d}")
            for i in range(100)
        ]
        self.assertEqual(len(validate_shapes(hundred)), 100)
        with self.assertRaises(ValueError):
            validate_shapes(hundred + [dict(copy.deepcopy(CANONICAL_SHAPES[0]), id="00000000-0000-4000-8000-999999999999")])

    def test_rendering_pixel_geometry_idempotence_and_twin_axis(self):
        fig, ax = self._make_figure()
        data_line = ax.lines[0]
        before = (
            ax.get_xlim(),
            ax.get_ylim(),
            tuple(ax.dataLim.bounds),
            ax.get_autoscalex_on(),
            ax.get_autoscaley_on(),
        )
        style = {"shapes": copy.deepcopy(CANONICAL_SHAPES), "annotations": [copy.deepcopy(ANNOTATION)]}
        for _ in range(20):
            apply_style(fig, copy.deepcopy(style))
            self.assertEqual(len(ax._tramastat_shapes), 3)
            self.assertEqual(len(ax.lines), 2)
            self.assertEqual(len(ax.patches), 2)
            self.assertEqual(len(ax.texts), 1)
        fig.canvas.draw()
        artists = ax._tramastat_shapes
        self.assertIsInstance(artists[0], Line2D)
        self.assertIsInstance(artists[1], Rectangle)
        self.assertIsInstance(artists[2], Ellipse)

        expected_bounds = [
            [104.0, 96.0, 272.0, 186.0],
            [128.0, 114.0, 248.0, 204.0],
            [128.0, 114.0, 224.0, 186.0],
        ]
        expected_zorders = [5.0, 1.001, 5.002]
        for i, (artist, record) in enumerate(zip(artists, CANONICAL_SHAPES)):
            self.assertEqual(artist.get_gid(), "tramastat-shape-" + record["id"])
            self.assertTrue(artist.get_clip_on())
            self.assertAlmostEqual(artist.get_linewidth(), record["width"])
            self.assertAlmostEqual(artist.get_alpha(), record["alpha"])
            self.assertAlmostEqual(artist.get_zorder(), expected_zorders[i])
            if isinstance(artist, Line2D):
                self.assertEqual(to_hex(artist.get_color()), record["stroke"])
                bounds = list(artist.get_transform().transform(artist.get_xydata()).ravel())
            else:
                self.assertEqual(to_hex(artist.get_edgecolor()), record["stroke"])
                bounds = list(artist.get_window_extent(fig.canvas.get_renderer()).extents)
            for got, want in zip(bounds, expected_bounds[i]):
                self.assertAlmostEqual(got, want, places=6)

        after = (
            ax.get_xlim(),
            ax.get_ylim(),
            tuple(ax.dataLim.bounds),
            ax.get_autoscalex_on(),
            ax.get_autoscaley_on(),
        )
        self.assertEqual(before, after)
        self.assertIs(ax.lines[0], data_line)
        self.assertEqual([s.key for s in graph_series(ax)], ["line:1:Data"])

        # Secondary axis: shapes stay on primary axes only
        right_ax = ax.twinx()
        right_ax.plot([1, 2, 4, 6], [10, 20, 30, 40], color="#444444")
        apply_style(fig, copy.deepcopy(style))
        self.assertEqual(len(ax._tramastat_shapes), 3)
        self.assertFalse(hasattr(right_ax, "_tramastat_shapes"))

        # Atomic rejection on invalid candidate
        previous = tuple(ax._tramastat_shapes)
        bad = copy.deepcopy(style)
        bad["shapes"][0]["width"] = -2
        with self.assertRaises(ValueError):
            apply_style(fig, bad)
        self.assertEqual(tuple(ax._tramastat_shapes), previous)

        # Removing shapes leaves data line and annotations intact
        apply_style(fig, {"annotations": [copy.deepcopy(ANNOTATION)]})
        self.assertEqual(len(ax._tramastat_shapes), 0)
        self.assertEqual(len(ax.patches), 0)
        self.assertEqual(len(ax.lines), 1)
        self.assertEqual(len(ax.texts), 1)

    def test_domains_warnings_and_persistence_and_exports(self):
        # The probability scales only accept data inside their range, so those figures plot valid fractions.
        for settings, points, y in [
            ({"xscale": "log"}, [[-1, 3], [6, 7]], (2, 4, 7, 8)),
            ({"yscale": "log"}, [[2, 0], [6, 7]], (2, 4, 7, 8)),
            ({"yscale": "probability"}, [[2, 0], [6, 0.8]], (.2, .4, .7, .8)),
            ({"yscale": "probability %"}, [[2, 20], [6, 100]], (20, 40, 70, 80)),
        ]:
            fig, ax = self._make_figure(y)
            selected = copy.deepcopy(CANONICAL_SHAPES)
            selected[2]["points"] = points
            style = {**settings, "shapes": selected}
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter("always")
                apply_style(fig, style)
            self.assertEqual(len(ax._tramastat_shapes), 2)
            self.assertTrue(
                any(issubclass(w.category, RuntimeWarning) and selected[2]["id"] in str(w.message) for w in caught)
            )
            self.assertFalse(on_axis_domain(ax, selected[2]))
            apply_style(fig, {"shapes": selected})
            self.assertEqual(len(ax._tramastat_shapes), 3)

        # Persistence & exports
        source = pd.DataFrame({"X": [1, 2, 4, 6], "Y": [2, 4, 7, 8], "Group": ["Control"] * 4})
        dataset = Dataset(source)
        dataset.analyses.append(("Scatter / confidence ellipse", {"X": "X", "Y": "Y", "Group": "Group"}))
        style = {"shapes": copy.deepcopy(CANONICAL_SHAPES), "annotations": [copy.deepcopy(ANNOTATION)]}
        dataset.graph_styles[0] = copy.deepcopy(style)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            alab = folder / "shapes.alab"
            save_project(alab, {"Synthetic": dataset})
            restored = load_project(alab)["Synthetic"]
            self.assertEqual(restored.graph_styles[0], style)
            # Edit the cell through the grid path of the app: reopened integer columns are Int64.
            paste_block(restored, 0, list(restored.raw.columns).index("Y"), [["2.25"]])
            self.assertEqual(float(restored.raw.loc[0, "Y"]), 2.25)
            recalc = analyse(*restored.analyses[0][:1], restored.raw, restored.analyses[0][1])
            apply_style(recalc.figure, restored.graph_styles[0])
            self.assertEqual(len(recalc.figure.axes[0]._tramastat_shapes), 3)

            fig, ax = self._make_figure()
            apply_style(fig, copy.deepcopy(style))
            svg_path = folder / "graph.svg"
            pdf_path = folder / "graph.pdf"
            png_path = folder / "graph.png"
            layout_svg = folder / "layout.svg"
            layout_pdf = folder / "layout.pdf"

            export_figure(fig, svg_path, {"format": "svg", "width_mm": 101.6, "svg_text": "text"})
            export_figure(fig, pdf_path, {"format": "pdf", "width_mm": 101.6})
            export_figure(fig, png_path, {"format": "png", "width_mm": 101.6, "dpi": 100})
            export_layout_svg("Shape layout", 2, [fig, fig], layout_svg, {"format": "svg", "width_mm": 160, "svg_text": "text"})
            export_pdf_bundle([PdfLayoutPage("Shape layout", 2, (fig, fig))], layout_pdf, {"format": "pdf", "width_mm": 160})

            with Image.open(png_path) as img:
                self.assertEqual(list(img.size), [400, 300])

            for s_path in (svg_path, layout_svg):
                root = ET.parse(s_path).getroot()
                self.assertFalse(any(e.tag.endswith("}image") for e in root.iter()))
                for record in CANONICAL_SHAPES:
                    gid = "tramastat-shape-" + record["id"]
                    self.assertTrue(any(gid in e.get("id", "") for e in root.iter()))

            for p_path in (pdf_path, layout_pdf):
                doc = pdfium.PdfDocument(str(p_path))
                try:
                    page = doc[0]
                    try:
                        tp = page.get_textpage()
                        try:
                            txt = " ".join(tp.get_text_range().split())
                            self.assertIn("Shape proof < 5", txt)
                            self.assertIn("$literal$", txt)
                        finally:
                            tp.close()
                        types = [obj.type for obj in page.get_objects(max_depth=15)]
                        self.assertNotIn(pdfraw.FPDF_PAGEOBJ_IMAGE, types)
                        self.assertGreaterEqual(types.count(pdfraw.FPDF_PAGEOBJ_PATH), 3)
                    finally:
                        page.close()
                finally:
                    doc.close()


if __name__ == "__main__":
    unittest.main()
