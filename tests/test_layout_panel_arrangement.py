from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from matplotlib.figure import Figure

from analisi.layout_panels import plan_panels
from analisi.layout_svg import SVG, export_layout_svg


def figures():
    result = []
    sizes = ((8, 4), (3, 6), (7, 5), (4, 4))
    axes = ((.12, .10, .80, .75), (.25, .20, .66, .72), (.24, .12, .68, .68), (.15, .16, .79, .58))
    for size, rect in zip(sizes, axes, strict=True):
        figure = Figure(figsize=size)
        axis = figure.add_axes(rect)
        axis.plot([0, 1, 2], [1, 3, 5])
        for edge in ("left", "bottom"):
            axis.spines[edge].set_gid(f"axis-{edge}")
        result.append(figure)
    return result


def figure_state(figure):
    return (tuple(figure.get_size_inches()), figure.dpi, figure.canvas, figure.get_layout_engine(),
            tuple((axis.get_position(original=True).bounds, axis.get_position().bounds, axis.get_in_layout(),
                   tuple(axis.get_xlim()), tuple(axis.get_ylim())) for axis in figure.axes))


class LayoutArrangementTests(unittest.TestCase):
    def test_equalizes_width_height_or_both(self):
        graphs = figures()
        for option in ("original", "width", "height", "both"):
            with self.subTest(option=option):
                panels = plan_panels(2, graphs, "A4 portrait", panel_size=option)
                widths = {round(panel.size[0] * panel.box[2], 8) for panel in panels}
                heights = {round(panel.size[1] * panel.box[2], 8) for panel in panels}
                self.assertEqual(len(widths) == 1, option in ("width", "both"))
                self.assertEqual(len(heights) == 1, option in ("height", "both"))
                if option != "both":
                    self.assertEqual([panel.size for panel in panels],
                                     [tuple(graph.get_size_inches()) for graph in graphs])

    def test_aligns_actual_axis_edges_in_svg_and_keeps_source_geometry(self):
        graphs = figures()
        original = [figure_state(graph) for graph in graphs]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "panel-layout.svg"
            export_layout_svg("Layout", 2, graphs, target, {"format": "svg"},
                              panel_size="both", axis_alignment="both")
            root = ET.parse(target).getroot()
        lefts, bottoms = [], []
        for i in range(1, 5):
            panel = root.find(f".//{SVG}g[@id='panel{i}']")
            x, y, scale = map(float, re.fullmatch(r"translate\((\S+) (\S+)\) scale\((\S+)\)",
                                                 panel.get("transform")).groups())
            left_path = panel.find(f".//{SVG}g[@id='panel{i}-axis-left']/{SVG}path")
            bottom_path = panel.find(f".//{SVG}g[@id='panel{i}-axis-bottom']/{SVG}path")
            _, left, *_ = left_path.get("d").split()
            _, _, bottom, *_ = bottom_path.get("d").split()
            lefts.append(x + scale * float(left))
            bottoms.append(y + scale * float(bottom))
        self.assertAlmostEqual(lefts[0], lefts[2], places=3)
        self.assertAlmostEqual(lefts[1], lefts[3], places=3)
        self.assertAlmostEqual(bottoms[0], bottoms[1], places=3)
        self.assertAlmostEqual(bottoms[2], bottoms[3], places=3)
        self.assertEqual([figure_state(graph) for graph in graphs], original)
        self.assertFalse(root.findall(f".//{SVG}image"))

    def test_multiple_subplots_and_fixed_aspect_keep_their_positions(self):
        graphs = figures()
        graphs[0].add_axes((.1, .1, .2, .2))
        graphs[1].axes[0].set_aspect("equal")
        panels = plan_panels(2, graphs, axis_alignment="both")
        self.assertIsNone(panels[0].bounds)
        self.assertIsNone(panels[1].bounds)
        self.assertIsNotNone(panels[2].bounds)
        self.assertIsNotNone(panels[3].bounds)

    def test_render_error_restores_figure_geometry(self):
        graphs = figures()
        graphs[0].set_layout_engine("tight")
        # A subplot gives the tight layout engine real geometry to recalculate.
        graphs[0].axes[0].remove()
        graphs[0].add_subplot(111).set_xlabel("An axis with a long label")
        original = [figure_state(graph) for graph in graphs]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "panel-layout.svg"
            with patch.object(graphs[1], "savefig", side_effect=OSError("test render failure")):
                with self.assertRaisesRegex(OSError, "test render failure"):
                    export_layout_svg("Layout", 2, graphs, target, {"format": "svg"},
                                      panel_size="both", axis_alignment="both")
            self.assertFalse(target.exists())
        self.assertEqual([figure_state(graph) for graph in graphs], original)
