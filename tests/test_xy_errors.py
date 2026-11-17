"""Unit and integration tests for XY error bars (symmetric/asymmetric X and Y, directions, and styling)."""
import copy
from io import StringIO
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

import matplotlib
matplotlib.use("Agg")
from matplotlib.collections import LineCollection
from matplotlib.colors import to_hex
from matplotlib.container import ErrorbarContainer
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from PIL import Image
import pypdfium2 as pdfium

from analisi.data import Dataset, load_workspace, save_project
from analisi.field_error import FieldError
from analisi.figure_export import export_figure, export_pdf_bundle
from analisi.graph_annotations import ANNOTATIONS
from analisi.i18n import set_language, tr
from analisi.layout_pdf import PdfLayoutPage
from analisi.layout_svg import export_layout_svg
from analisi.presentation import apply_style
from analisi.workbench import METHODS, analyse
from analisi.xy_errors import (
    DIRECTIONS,
    ERROR_LINE_STYLES,
    VALUE_MODES,
    XY_ERROR_CHOICE_KEYS,
    XY_ERROR_LABEL_KEYS,
    XY_ERROR_TAB_KEYS,
    XY_ERROR_TABS,
    prune_xy_error_options,
    xy_error_visibility,
)


FIXTURE_CSV = """row_id,X,Y,XL,XU,YL,YU,XLo,XHi,YLo,YHi,LegacyX,Group
41,4,10,1,2,2,3,3,6,8,13,0.5,B
7,1,4,0.25,0.75,1,0.5,0.75,1.75,3,4.5,0.2,A
90,3,8,0,1.5,0.5,0,3,4.5,7.5,8,0,B
13,2,6,0.5,0.25,2,1,1.5,2.25,4,7,0.3,A
55,5,9,,0.25,1,1,,5.25,8,10,0.4,B
99,6,,1,1,1,1,5,7,0,2,0.6,A
"""

ROWS = [
    {"id": 41, "group": "B", "point": [4.0, 10.0], "x_bounds": [3.0, 6.0], "y_bounds": [8.0, 13.0], "legacy_x": [3.5, 4.5]},
    {"id": 7, "group": "A", "point": [1.0, 4.0], "x_bounds": [0.75, 1.75], "y_bounds": [3.0, 4.5], "legacy_x": [0.8, 1.2]},
    {"id": 90, "group": "B", "point": [3.0, 8.0], "x_bounds": [3.0, 4.5], "y_bounds": [7.5, 8.0], "legacy_x": [3.0, 3.0]},
    {"id": 13, "group": "A", "point": [2.0, 6.0], "x_bounds": [1.5, 2.25], "y_bounds": [4.0, 7.0], "legacy_x": [1.7, 2.3]},
    {"id": 55, "group": "B", "point": [5.0, 9.0], "x_bounds": None, "y_bounds": [8.0, 10.0], "legacy_x": [4.6, 5.4]},
]


def load_fixture():
    return pd.read_csv(StringIO(FIXTURE_CSV)).set_index("row_id")


def canonical_segments(segments):
    return sorted(tuple(round(float(v), 10) for v in np.asarray(s).ravel()) for s in segments)


def actual_segments(res):
    return canonical_segments(
        s for c in res.figure.axes[0].collections if isinstance(c, LineCollection)
        for s in c.get_segments() if np.asarray(s).shape == (2, 2)
    )


def expected_segments(ids, xd="Both", yd="Both", old=False, x=True, y=True):
    segments = []
    for fixed in ROWS:
        if fixed["id"] not in ids:
            continue
        cx, cy = fixed["point"]
        xb = fixed["legacy_x"] if old else fixed["x_bounds"]
        if x:
            lo = cx if xd == "Positive only" else xb[0]
            hi = cx if xd == "Negative only" else xb[1]
            segments.append([[lo, cy], [hi, cy]])
        if y:
            lo = cy if yd == "Positive only" else fixed["y_bounds"][0]
            hi = cy if yd == "Negative only" else fixed["y_bounds"][1]
            segments.append([[cx, lo], [cx, hi]])
    return canonical_segments(segments)


class XYErrorBarsTests(unittest.TestCase):
    def setUp(self):
        self.frame = load_fixture()
        self.legacy = {
            "X": "X", "Y": "Y", "X error distance": "LegacyX",
            "Y lower error": "YL", "Y upper error": "YU",
            "Y error values": "Distances", "Group": "Group",
        }
        self.new = {
            "X": "X", "Y": "Y", "X lower error": "XL", "X upper error": "XU",
            "X error values": "Distances", "Y lower error": "YL", "Y upper error": "YU",
            "Y error values": "Distances", "Group": "Group",
        }
        self.endpoints = {
            **self.new,
            "X lower error": "XLo", "X upper error": "XHi", "X error values": "Endpoints",
            "Y lower error": "YLo", "Y upper error": "YHi", "Y error values": "Endpoints",
        }

    def tearDown(self):
        plt.close("all")

    def test_options_registered_and_legacy_snapshot_preserved(self):
        required = {
            "X lower error", "X upper error", "X error values", "X error direction",
            "Y error direction", "Error cap size", "Error width", "Error color", "Error line style",
        }
        self.assertTrue(required <= METHODS["XY error bars"].keys())
        original = self.frame.copy(deep=True)
        res = analyse("XY error bars", self.frame, copy.deepcopy(self.legacy))
        pd.testing.assert_frame_equal(self.frame, original)
        self.assertEqual(list(res.tables), ["Observations"])
        obs = res.tables["Observations"]
        self.assertEqual(obs.index.tolist(), [41, 7, 90, 13, 55])
        self.assertEqual(list(obs.columns), ["X", "Y", "LegacyX", "YL", "YU", "Group"])
        self.assertEqual(actual_segments(res), expected_segments([41, 7, 90, 13, 55], old=True))
        self.assertEqual([t.get_text() for t in res.figure.axes[0].get_legend().get_texts()], ["B", "A"])

    def test_asymmetric_distances_endpoints_and_all_direction_pairs(self):
        dist_res = analyse("XY error bars", self.frame, copy.deepcopy(self.new))
        end_res = analyse("XY error bars", self.frame, copy.deepcopy(self.endpoints))
        self.assertEqual(dist_res.tables["Observations"].index.tolist(), [41, 7, 90, 13])
        self.assertEqual(list(dist_res.tables["Observations"].columns), ["X", "Y", "XL", "XU", "YL", "YU", "Group"])
        self.assertEqual(list(end_res.tables["Observations"].columns), ["X", "Y", "XLo", "XHi", "YLo", "YHi", "Group"])
        self.assertEqual(actual_segments(dist_res), expected_segments([41, 7, 90, 13]))
        self.assertEqual(actual_segments(end_res), expected_segments([41, 7, 90, 13]))

        for xd in DIRECTIONS:
            for yd in DIRECTIONS:
                with self.subTest(xd=xd, yd=yd):
                    opts = {**self.new, "X error direction": xd, "Y error direction": yd}
                    res = analyse("XY error bars", self.frame, opts)
                    self.assertEqual(actual_segments(res), expected_segments([41, 7, 90, 13], xd=xd, yd=yd))
                    self.assertEqual(res.tables["Observations"].index.tolist(), [41, 7, 90, 13])

    def test_single_axis_single_side_symmetry_and_stale_inactive_options(self):
        # Single side X in Distances is symmetric
        sym_x = analyse("XY error bars", self.frame, {"X": "X", "Y": "Y", "X lower error": "XL"})
        self.assertEqual(sym_x.tables["Observations"].index.tolist(), [41, 7, 90, 13])
        for row, seg in zip(
            sorted([r for r in ROWS if r["id"] in [41, 7, 90, 13]], key=lambda r: (r["point"][0] - (r["point"][0] - r["x_bounds"][0]), r["point"][1])),
            actual_segments(sym_x),
        ):
            cx, cy = row["point"]
            dx = cx - row["x_bounds"][0]
            np.testing.assert_allclose(seg, (cx - dx, cy, cx + dx, cy), atol=1e-10)

        # Y-only ignores stale X error values / X error direction and retains row 55
        y_only = {
            "X": "X", "Y": "Y", "Y lower error": "YL", "Y upper error": "YU",
            "X error values": "invalid-stale", "X error direction": "invalid-stale",
        }
        res_y = analyse("XY error bars", self.frame, y_only)
        self.assertEqual(res_y.tables["Observations"].index.tolist(), [41, 7, 90, 13, 55])
        self.assertEqual(actual_segments(res_y), expected_segments([41, 7, 90, 13, 55], x=False, y=True))

        # X-only ignores stale Y error values / Y error direction
        x_only = {
            "X": "X", "Y": "Y", "X lower error": "XL", "X upper error": "XU",
            "Y error values": "invalid-stale", "Y error direction": "invalid-stale",
        }
        res_x = analyse("XY error bars", self.frame, x_only)
        self.assertEqual(res_x.tables["Observations"].index.tolist(), [41, 7, 90, 13])
        self.assertEqual(actual_segments(res_x), expected_segments([41, 7, 90, 13], x=True, y=False))

    def test_validation_errors_report_exact_field(self):
        cases = [
            ({**self.new, "X error distance": "LegacyX"}, "X error distance", None),
            ({"X": "X", "Y": "Y"}, "Y lower error", None),
            ({**self.endpoints, "X upper error": ""}, "X upper error", None),
            ({**self.endpoints, "X lower error": ""}, "X lower error", None),
            ({**self.endpoints, "Y upper error": ""}, "Y upper error", None),
            (self.new, "X lower error", self.frame.assign(XL=-0.1)),
            (self.new, "X upper error", self.frame.assign(XU=-0.1)),
            (self.endpoints, "X lower error", self.frame.assign(XLo=100)),
            (self.endpoints, "X upper error", self.frame.assign(XHi=-100)),
            (self.endpoints, "Y lower error", self.frame.assign(YLo=100)),
            (self.endpoints, "Y upper error", self.frame.assign(YHi=-100)),
            # Hidden side is still validated
            ({**self.new, "X error direction": "Positive only"}, "X lower error", self.frame.assign(XL=-1)),
            ({**self.new, "X error direction": "sideways"}, "X error direction", None),
            ({**self.new, "Y error direction": "sideways"}, "Y error direction", None),
            ({**self.new, "X error values": "Bogus"}, "X error values", None),
            ({**self.new, "Error cap size": -1}, "Error cap size", None),
            ({**self.new, "Error cap size": 25}, "Error cap size", None),
            ({**self.new, "Error width": 0}, "Error width", None),
            ({**self.new, "Error width": float("inf")}, "Error width", None),
            ({**self.new, "Error color": "no-such-color"}, "Error color", None),
            ({**self.new, "Error line style": "wavy"}, "Error line style", None),
            ({**self.new, "X lower error": "missing_col"}, "X lower error", None),
            ({**self.new, "X upper error": "XL"}, "X upper error", None),
            (self.new, "X lower error", self.frame.assign(XL=float("inf"))),
            (self.new, "X lower error", self.frame.assign(XL="bad-text")),
        ]
        for opts, expected_field, custom_frame in cases:
            with self.subTest(field=expected_field, opts=opts):
                with self.assertRaises(FieldError) as ctx:
                    analyse("XY error bars", self.frame if custom_frame is None else custom_frame, opts)
                self.assertEqual(ctx.exception.field, expected_field)

    def test_cap_styles_unilateral_caps_and_inspector_override_reset(self):
        for ls in ERROR_LINE_STYLES:
            res = analyse("XY error bars", self.frame, {
                **self.new, "Error cap size": "7,0", "Error width": "2,25",
                "Error color": "#b12435", "Error line style": ls,
            })
            axes = res.figure.axes[0]
            for coll in axes.collections:
                if isinstance(coll, LineCollection):
                    self.assertAlmostEqual(float(coll.get_linewidths()[0]), 2.25)
                    self.assertEqual(to_hex(coll.get_colors()[0]), "#b12435")
                    if ls == "solid":
                        self.assertIsNone(coll.get_linestyles()[0][1])
                    else:
                        self.assertIsNotNone(coll.get_linestyles()[0][1])
            caps = [cap for c in axes.containers if isinstance(c, ErrorbarContainer) for cap in c.lines[1]]
            self.assertTrue(caps)
            for cap in caps:
                self.assertAlmostEqual(cap.get_markersize(), 14.0)
                self.assertAlmostEqual(cap.get_markeredgewidth(), 2.25)
                self.assertEqual(to_hex(cap.get_color()), "#b12435")

            # Format Graph / Inspector override and reset
            apply_style(res.figure, {"series": {"errorbar:1:B": {"color": "#115577", "marker": "s", "label": "Group B"}}})
            b_container = next(c for c in axes.containers if isinstance(c, ErrorbarContainer))
            self.assertEqual(to_hex(b_container.lines[0].get_color()), "#115577")
            self.assertEqual(to_hex(b_container.lines[1][0].get_color()), "#115577")
            self.assertEqual(to_hex(b_container.lines[2][0].get_colors()[0]), "#115577")
            apply_style(res.figure, {})
            self.assertEqual(to_hex(b_container.lines[1][0].get_color()), "#b12435")
            self.assertEqual(to_hex(b_container.lines[2][0].get_colors()[0]), "#b12435")
            plt.close(res.figure)

    def test_visibility_pruning_persistence_recalculation_and_exports(self):
        vis = xy_error_visibility("LegacyX", "", "", "Distances", "YL", "", "Distances")
        self.assertEqual(vis, {
            "X error values": False, "X error direction": True,
            "Y error values": True, "Y error direction": True,
        })
        pruned = prune_xy_error_options({
            **self.legacy, "X lower error": None, "X upper error": None,
            "X error values": "Endpoints", "X error direction": "Both",
            "Y error direction": "Both", "Error cap size": 4.0,
            "Error width": "", "Error color": "", "Error line style": "solid",
        })
        self.assertEqual(pruned, self.legacy)

        styled_recipe = {
            **self.new, "X error direction": "Negative only", "Y error direction": "Positive only",
            "Error cap size": 6.0, "Error width": 1.8, "Error color": "#8e2c1f", "Error line style": "dashed",
        }
        res = analyse("XY error bars", self.frame, styled_recipe)
        apply_style(res.figure, {ANNOTATIONS: [{
            "text": "Cohort note", "position": [0.2, 0.85], "units": "axes",
            "align": "left", "size": 10, "color": "#1d3348",
        }]})

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            svg_path = folder / "xy_errors.svg"
            png_path = folder / "xy_errors.png"
            pdf_path = folder / "xy_errors.pdf"
            export_figure(res.figure, svg_path, {"format": "svg", "width_mm": 101.6, "svg_text": "text"})
            export_figure(res.figure, png_path, {"format": "png", "width_mm": 101.6, "dpi": 100})
            export_figure(res.figure, pdf_path, {"format": "pdf", "width_mm": 101.6})

            svg_root = ET.parse(svg_path).getroot()
            self.assertAlmostEqual(float(svg_root.get("width").removesuffix("pt")), 288.0, places=5)
            self.assertAlmostEqual(float(svg_root.get("height").removesuffix("pt")), 180.0, places=5)
            self.assertFalse(any(e.tag.endswith("}image") for e in svg_root.iter()))
            self.assertIn("Cohort note", svg_path.read_text(encoding="utf-8"))

            with Image.open(png_path) as img:
                self.assertEqual(list(img.size), [400, 250])

            doc = pdfium.PdfDocument(str(pdf_path))
            try:
                page = doc[0]
                try:
                    textpage = page.get_textpage()
                    try:
                        self.assertIn("Cohort note", textpage.get_text_bounded())
                    finally:
                        textpage.close()
                finally:
                    page.close()
            finally:
                doc.close()

            # Layout SVG and PDF export
            layout_svg = folder / "layout.svg"
            layout_pdf = folder / "layout.pdf"
            export_layout_svg("XY Error Layout", 1, [res.figure], layout_svg, {"svg_text": "text"})
            export_pdf_bundle([PdfLayoutPage("XY Error Layout", 1, (res.figure,))], layout_pdf, {})
            self.assertIn("Cohort note", layout_svg.read_text(encoding="utf-8"))
            ldoc = pdfium.PdfDocument(str(layout_pdf))
            try:
                lpage = ldoc[0]
                try:
                    ltext = lpage.get_textpage()
                    try:
                        self.assertIn("Cohort note", ltext.get_text_bounded())
                    finally:
                        ltext.close()
                finally:
                    lpage.close()
            finally:
                ldoc.close()

            # .alab persistence, cell edit and exclusion recalculation
            ds = Dataset(self.frame.reset_index(), analyses=[("XY error bars", styled_recipe)])
            alab_path = folder / "project.alab"
            save_project(alab_path, {"Data": ds})
            reopened, _ = load_workspace(alab_path)
            restored = reopened["Data"]
            self.assertEqual(restored.analyses[0], ("XY error bars", styled_recipe))
            restored.excluded.add((0, 1))  # exclude row 0 (row_id 41)
            recalc = analyse("XY error bars", restored.frame(mask_excluded=True), restored.analyses[0][1])
            self.assertEqual(len(recalc.tables["Observations"]), 3)
            plt.close(recalc.figure)
        plt.close(res.figure)

    def test_dialog_tabs_translations_and_decimal_comma(self):
        all_tab_fields = [field for group in XY_ERROR_TABS.values() for field in group]
        self.assertEqual(set(all_tab_fields), set(METHODS["XY error bars"].keys()))
        self.assertEqual(set(XY_ERROR_LABEL_KEYS.keys()), set(METHODS["XY error bars"].keys()))
        self.assertEqual(
            set(XY_ERROR_CHOICE_KEYS.keys()),
            set(VALUE_MODES) | set(DIRECTIONS) | set(ERROR_LINE_STYLES),
        )
        try:
            set_language("it")
            self.assertEqual(tr(XY_ERROR_TAB_KEYS["X errors"]), "Errori X")
            self.assertEqual(tr(XY_ERROR_TAB_KEYS["Y errors"]), "Errori Y")
            self.assertEqual(tr(XY_ERROR_TAB_KEYS["Error appearance"]), "Aspetto degli errori")
            self.assertEqual(tr(XY_ERROR_LABEL_KEYS["X error distance"]), "Distanza X simmetrica")
            self.assertEqual(tr(XY_ERROR_LABEL_KEYS["X lower error"]), "Errore X inferiore")
            self.assertEqual(tr(XY_ERROR_LABEL_KEYS["X upper error"]), "Errore X superiore")
            self.assertEqual(tr(XY_ERROR_LABEL_KEYS["Error cap size"]), "Dimensione cappucci (pt)")
            self.assertEqual(tr(XY_ERROR_LABEL_KEYS["Error width"]), "Spessore errori (pt)")
            self.assertEqual(tr(XY_ERROR_LABEL_KEYS["Error color"]), "Colore errori")
            self.assertEqual(tr(XY_ERROR_CHOICE_KEYS["Distances"]), "Distanze")
            self.assertEqual(tr(XY_ERROR_CHOICE_KEYS["Endpoints"]), "Estremi")
            self.assertEqual(tr(XY_ERROR_CHOICE_KEYS["Both"]), "Entrambe")
            self.assertEqual(tr(XY_ERROR_CHOICE_KEYS["Negative only"]), "Solo negativa")
            self.assertEqual(tr(XY_ERROR_CHOICE_KEYS["Positive only"]), "Solo positiva")
            set_language("en")
            self.assertEqual(tr(XY_ERROR_LABEL_KEYS["X error distance"]), "Symmetric X error distance")
        finally:
            set_language("en")

        pruned = prune_xy_error_options({
            **self.new,
            "Error cap size": "5,5",
            "Error width": "2,25",
            "Error color": " #b12435 ",
            "Error line style": "dashed",
        })
        self.assertIsInstance(pruned["Error cap size"], float)
        self.assertEqual(pruned["Error cap size"], 5.5)
        self.assertIsInstance(pruned["Error width"], float)
        self.assertEqual(pruned["Error width"], 2.25)
        self.assertEqual(pruned["Error color"], "#b12435")


if __name__ == "__main__":
    unittest.main()
