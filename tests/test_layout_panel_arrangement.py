from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from matplotlib.figure import Figure

from analisi.layout_panels import layout_shifts, panel_rectangle, plan_panels
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

    def test_distributing_three_selected_panels_keeps_the_outside_edges(self):
        graphs = figures()
        panels = plan_panels(4, graphs)
        initial = [panel_rectangle(panel) for panel in panels]
        objects = [(0,), (1,), (2,)]
        offsets = layout_shifts(panels, objects, "distribute_x")
        final = [(x + offsets[index][0], right + offsets[index][0])
                 for index, (x, _, right, _) in enumerate(initial[:3])]
        self.assertAlmostEqual(final[0][0], initial[0][0])
        self.assertAlmostEqual(final[2][1], initial[2][2])
        self.assertAlmostEqual(final[1][0] - final[0][1], final[2][0] - final[1][1])
        self.assertNotIn(3, offsets)
        self.assertEqual([panel_rectangle(panel) for panel in panels], initial)

    def test_scaled_stacking_order_is_drawn_in_raster_and_vector_pdf(self):
        import pypdfium2 as pdfium
        from matplotlib.backends.backend_agg import FigureCanvasAgg

        from analisi.figure_export import export_pdf_bundle
        from analisi.layout_arrangement import PanelArrangement
        from analisi.layout_pdf import PdfLayoutPage
        from analisi.presentation import compose_layout

        graphs = (Figure(figsize=(4, 3), facecolor="#e02020"), Figure(figsize=(4, 3), facecolor="#2040e0"))
        original_sizes = [tuple(graph.get_size_inches()) for graph in graphs]
        arrangement = PanelArrangement(offsets=((1, -.5, 0),), scales=((0, .5),), layers=(1, 0))
        page = PdfLayoutPage("Layers", 2, graphs, arrangement=arrangement)
        left, top, right, bottom = panel_rectangle(page.placements[0])
        x, y = left + .2 * (right - left), top + .2 * (bottom - top)
        outside = right + .2 * (right - left), y
        layout = compose_layout("Layers", 2, graphs, arrangement=arrangement)
        canvas = FigureCanvasAgg(layout)
        canvas.draw()
        raster = canvas.buffer_rgba()
        width, height = page.size

        def coordinates(px, py, point):
            return round(px * point[0] / width), round(py * point[1] / height)

        from PIL import Image
        preview = Image.frombuffer("RGBA", canvas.get_width_height(), raster).convert("RGB")
        expected = [(224, 32, 32), (32, 64, 224)]
        self.assertEqual([preview.getpixel(coordinates(*preview.size, point))
                          for point in ((x, y), outside)], expected)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "layers.pdf"
            export_pdf_bundle([page], target, {"format": "pdf"})
            with pdfium.PdfDocument(str(target)) as document:
                bitmap = document[0].render(scale=2).to_pil().convert("RGB")
                self.assertEqual([bitmap.getpixel(coordinates(*bitmap.size, point))
                                  for point in ((x, y), outside)], expected)
        self.assertEqual([tuple(graph.get_size_inches()) for graph in graphs], original_sizes)

    def test_rotated_graph_and_dashed_border_stay_vector_in_exports(self):
        import pypdfium2 as pdfium
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.patches import Rectangle
        from PIL import Image

        from analisi.figure_export import export_pdf_bundle
        from analisi.layout_arrangement import PanelArrangement
        from analisi.layout_pdf import PdfLayoutPage
        from analisi.presentation import compose_layout

        graph = Figure(figsize=(4, 2), facecolor="#e02020")
        graph.add_artist(Rectangle((0, .5), 1, .5, transform=graph.transFigure, color="#2040e0"))
        before = figure_state(graph)
        for angle, colors in ((90, [(224, 32, 32), (32, 64, 224)]),
                              (-90, [(32, 64, 224), (224, 32, 32)])):
            with self.subTest(angle=angle), tempfile.TemporaryDirectory() as folder:
                arrangement = PanelArrangement(scales=((0, .45),), rotations=((0, angle),),
                                               borders=((0, 3., "#008000", "dashed"),))
                page = PdfLayoutPage("Turned", 1, (graph,), arrangement=arrangement)
                left, top, right, bottom = panel_rectangle(page.placements[0])
                self.assertAlmostEqual(bottom - top, 2 * (right - left))
                points = [(left + fraction * (right - left), (top + bottom) / 2) for fraction in (.25, .75)]

                def drawing(image):
                    scale_x = image.width / page.size[0]
                    scale_y = image.height / page.size[1]
                    self.assertEqual([image.getpixel((round(x * scale_x), round(y * scale_y)))
                                      for x, y in points], colors)
                    edge = [image.getpixel((round(left * scale_x), y))
                            for y in range(round((top + .07) * scale_y), round((bottom - .07) * scale_y))]
                    self.assertIn((0, 128, 0), edge)
                    self.assertTrue(any(pixel[0] > 170 or pixel[2] > 170 for pixel in edge))

                layout = compose_layout("Turned", 1, (graph,), arrangement=arrangement)
                canvas = FigureCanvasAgg(layout)
                canvas.draw()
                drawing(Image.frombuffer("RGBA", canvas.get_width_height(), canvas.buffer_rgba()).convert("RGB"))

                pdf = Path(folder) / "rotated.pdf"
                export_pdf_bundle([page], pdf, {"format": "pdf"})
                with pdfium.PdfDocument(pdf) as document:
                    pdf_page = document[0]
                    drawing(pdf_page.render(scale=3).to_pil().convert("RGB"))
                    pdf_page.close()

                svg = Path(folder) / "rotated.svg"
                export_layout_svg("Turned", 1, (graph,), svg, {"format": "svg"}, arrangement=arrangement)
                root = ET.parse(svg).getroot()
                self.assertFalse(root.findall(f".//{SVG}image"))
                panel = root.find(f"{SVG}g[@id='panel1']")
                self.assertTrue(panel.get("transform").endswith(f"rotate({angle})"))
                border = root.find(f"{SVG}rect[@id='panel1-border']")
                self.assertEqual(border.get("stroke-dasharray"), "11.1 4.8")
                self.assertAlmostEqual(float(border.get("height")) / float(border.get("width")), 2, places=5)
        self.assertEqual(figure_state(graph), before)

    def test_signed_crop_clips_content_before_rotation_without_rasterizing_vectors(self):
        import pypdfium2 as pdfium
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from matplotlib.patches import Rectangle
        from PIL import Image

        from analisi.figure_export import export_pdf_bundle
        from analisi.layout_arrangement import PanelArrangement
        from analisi.layout_pdf import PdfLayoutPage
        from analisi.presentation import compose_layout

        graph = Figure(figsize=(4, 2), facecolor="#e02020")
        graph.add_artist(Rectangle((.5, 0), .5, 1, transform=graph.transFigure, color="#2040e0"))
        before = figure_state(graph)
        for angle in (0, 90, -90):
            with self.subTest(angle=angle), tempfile.TemporaryDirectory() as folder:
                arrangement = PanelArrangement(scales=((0, .45),), rotations=((0, angle),) if angle else (),
                                               crops=((0, .25, .25, -.25, 0.),))
                page = PdfLayoutPage("Cropped", 1, (graph,), background="#eaeadd", arrangement=arrangement)
                panel = page.placements[0]
                self.assertEqual(panel.cropped_size, (4., 1.5))
                left, top, right, bottom = panel_rectangle(panel)
                points = []
                for x in (.12, .48, .90):
                    u, v = (0.5, x) if angle == 90 else (0.5, 1-x) if angle == -90 else (x, .5)
                    points.append((left + u * (right-left), top + v * (bottom-top)))

                def drawing(image):
                    scale_x = image.width / page.size[0]
                    scale_y = image.height / page.size[1]
                    self.assertEqual([image.getpixel((round(x * scale_x), round(y * scale_y)))
                                      for x, y in points], [(224, 32, 32), (32, 64, 224), (234, 234, 221)])

                layout = compose_layout("Cropped", 1, (graph,), background=page.background, arrangement=arrangement)
                canvas = FigureCanvasAgg(layout)
                canvas.draw()
                drawing(Image.frombuffer("RGBA", canvas.get_width_height(), canvas.buffer_rgba()).convert("RGB"))

                pdf = Path(folder) / "crop.pdf"
                export_pdf_bundle([page], pdf, {"format": "pdf"})
                with pdfium.PdfDocument(pdf) as document:
                    pdf_page = document[0]
                    drawing(pdf_page.render(scale=3).to_pil().convert("RGB"))
                    pdf_page.close()

                svg = Path(folder) / "crop.svg"
                export_layout_svg("Cropped", 1, (graph,), svg, {"format": "svg"}, arrangement=arrangement)
                root = ET.parse(svg).getroot()
                self.assertFalse(root.findall(f".//{SVG}image"))
                crop = root.find(f".//{SVG}clipPath[@id='panel1-viewport']/{SVG}rect")
                self.assertEqual((float(crop.get("width")), float(crop.get("height"))), (288, 108))
                source = root.find(f".//{SVG}g[@clip-path='url(#panel1-source)']")
                self.assertEqual(source.get("transform"), "translate(-72.0000 -36.0000)")
        self.assertEqual(figure_state(graph), before)

    def test_replacing_a_wider_graph_scales_to_page_with_trim_unchanged(self):
        from analisi.layout_panels import LayoutPanel, replacement_geometry

        old = LayoutPanel(Figure(), (4., 2.), (3., 1., 1.), crop=(.15, 0., -.05, 0.))
        replacement = LayoutPanel(Figure(), (6., 3.), (0., 0., 1.))
        (x, y, scale), crop = replacement_geometry(old, replacement, (8., 4.))
        self.assertEqual((x, y), (3., 1.))
        self.assertAlmostEqual(scale, .9)
        self.assertAlmostEqual(crop[0] * replacement.size[0] * scale, .6)
        self.assertAlmostEqual(crop[2] * replacement.size[0] * scale, -.2)
        self.assertAlmostEqual(x + (1 - crop[0] - crop[2]) * replacement.size[0] * scale, 8.)
        with self.assertRaises(ValueError):
            replacement_geometry(old, LayoutPanel(Figure(), (.5, 1.), (0., 0., 1.)), (8., 4.))

    def test_coincident_corners_use_only_the_visible_panel_letter(self):
        from analisi.layout_arrangement import PanelArrangement
        from analisi.layout_panels import layout_labels

        graph = Figure(figsize=(4, 2))
        arrangement = PanelArrangement(offsets=((1, -.5, 0),))
        panels = plan_panels(2, (graph, graph), arrangement=arrangement)
        self.assertEqual(layout_labels(panels, (0, 1)), {1})
        self.assertEqual(layout_labels(panels, (1, 0)), {0})

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
