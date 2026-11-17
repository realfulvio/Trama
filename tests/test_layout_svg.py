from io import BytesIO
from pathlib import Path
import re
import tempfile
import tkinter as tk
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from matplotlib.figure import Figure
from PIL import Image
import pypdfium2 as pdfium

from analisi.figure_export import export_figure, export_pdf_bundle
from analisi.layout_geometry import CELL_H, CELL_W, LABEL_H, PAD, TITLE_H, page_size, panel_boxes
from analisi.layout_svg import export_layout_svg
from analisi.presentation import compose_layout

SVG = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"
SETTINGS = {"format": "svg", "width_mm": 127, "svg_text": "text", "transparent": True}


def graphs():
    figures = []
    for title, color, error in (("Alfa < A & B", "#28608f", None), ("Beta – città (n=3)", "#c0392b", [.3, .5, .2])):
        figure = Figure(figsize=(4, 3), dpi=100, layout="constrained")
        axes = figure.add_subplot()
        axes.set_title(title, parse_math=False)
        axes.errorbar([1, 2, 4], [2, 3, 5] if error is None else [4, 2, 3], yerr=error, marker="o", color=color,
                      label=title)
        axes.set_xlim(0, 5)
        axes.legend()
        figures.append(figure)
    return figures


def state(figures):
    return [(tuple(f.get_size_inches()), f.dpi, f.canvas, [(a.get_xlim(), a.get_ylim()) for a in f.axes])
            for f in figures]


def mm(value):
    number, unit = re.fullmatch(r"([0-9.]+)(mm|pt|in)", value).groups()
    return float(number) * {"mm": 1, "pt": 25.4 / 72, "in": 25.4}[unit]


def references(root):
    found = []
    for item in root.iter():
        for key, value in item.attrib.items():
            if key in {"href", XLINK} and value.startswith("#"):
                found.append(value[1:])
            found.extend(re.findall(r"url\(#([^)]+)\)", value))
    return found


class LayoutSvgTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.target = Path(self.folder.name) / "layout.svg"
        self.figures = graphs()

    def tearDown(self):
        self.folder.cleanup()

    def export(self, figures=None, title="Figura città", columns=2, **settings):
        plan = export_layout_svg(title, columns, self.figures if figures is None else figures, self.target,
                                 {**SETTINGS, **settings})
        return plan, ET.parse(self.target).getroot()

    def test_geometry_ids_and_links(self):
        before = state(self.figures)
        plan, root = self.export()
        self.assertEqual(plan["format"], "svg")
        self.assertAlmostEqual(plan["width_mm"], 127)
        self.assertAlmostEqual(plan["height_mm"], 127 * 3.6 / 8.4)
        self.assertAlmostEqual(mm(root.get("width")), 127, delta=.01)
        self.assertAlmostEqual(mm(root.get("height")), 127 * 3.6 / 8.4, delta=.01)
        for got, want in zip([float(v) for v in root.get("viewBox").split()], [0, 0, 8.4 * 72, 3.6 * 72], strict=True):
            self.assertAlmostEqual(got, want, places=3)
        ids = [item.get("id") for item in root.iter() if item.get("id") is not None]
        self.assertEqual(len(ids), len(set(ids)))
        refs = references(root)
        self.assertTrue(refs)
        self.assertLessEqual(set(refs), set(ids))
        # Markers and clip paths of both panels survive with their own IDs.
        self.assertTrue(any(ref.startswith("panel1-") for ref in refs))
        self.assertTrue(any(ref.startswith("panel2-") for ref in refs))
        self.assertTrue(root.findall(f".//{SVG}clipPath"))
        self.assertTrue(root.findall(f".//{SVG}use"))
        self.assertEqual(state(self.figures), before)

    def test_text_mode_keeps_escaped_titles_and_letters(self):
        _, root = self.export()
        texts = ["".join(node.itertext()) for node in root.iter(f"{SVG}text")]
        for wanted in ("Figura città", "Alfa < A & B", "Beta – città (n=3)", "A", "B"):
            self.assertIn(wanted, texts)
        self.assertFalse(root.findall(f".//{SVG}image"))
        raw = self.target.read_text(encoding="utf-8")
        self.assertIn("Alfa &lt; A &amp; B", raw)

    def test_paths_mode_has_no_text(self):
        _, root = self.export(svg_text="paths")
        self.assertFalse(root.findall(f".//{SVG}text"))
        self.assertTrue(root.findall(f".//{SVG}path"))
        ids = [item.get("id") for item in root.iter() if item.get("id") is not None]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertLessEqual(set(references(root)), set(ids))

    def test_mixed_panel_keeps_one_image_and_vector_rest(self):
        self.figures[1].axes[0].imshow([[0, 1], [2, 3]], extent=(1, 2, 1, 2))
        _, root = self.export()
        images = root.findall(f".//{SVG}image")
        self.assertEqual(len(images), 1)
        panel2 = root.find(f".//{SVG}g[@id='panel2']")
        self.assertIsNotNone(panel2.find(f".//{SVG}image"))
        self.assertTrue(panel2.findall(f".//{SVG}path"))
        self.assertIn("Beta – città (n=3)", ["".join(n.itertext()) for n in panel2.iter(f"{SVG}text")])
        self.assertIsNone(root.find(f".//{SVG}g[@id='panel1']").find(f".//{SVG}image"))

    def test_native_size_and_opaque_background(self):
        plan, root = self.export(width_mm=None, transparent=False)
        self.assertAlmostEqual(plan["width_mm"], 8.4 * 25.4)
        self.assertAlmostEqual(mm(root.get("height")), 3.6 * 25.4, delta=.01)
        background = root.find(f".//{SVG}g[@id='layout-patch_1']/{SVG}path")
        self.assertIn("#ffffff", background.get("style"))

    def test_panels_keep_aspect_and_stay_in_their_cell(self):
        sizes = [(4, 3), (8, 2), (2, 6), (4, 3), (6.4, 4.8)]
        boxes = panel_boxes(2, sizes)
        width, height = page_size(2, len(sizes))
        self.assertEqual((width, height), (8.4, 3.2 * 3 + .4))
        for index, ((w, h), (x, y, scale)) in enumerate(zip(sizes, boxes)):
            row, column = divmod(index, 2)
            left, top = column * CELL_W + PAD, TITLE_H + row * CELL_H + LABEL_H
            self.assertGreaterEqual(x, left - 1e-9)
            self.assertGreaterEqual(y, top - 1e-9)
            self.assertLessEqual(x + w * scale, (column + 1) * CELL_W - PAD + 1e-9)
            self.assertLessEqual(y + h * scale, TITLE_H + (row + 1) * CELL_H - PAD + 1e-9)
            # Centred along the free direction.
            free_x = (CELL_W - 2 * PAD) - w * scale
            free_y = (CELL_H - LABEL_H - PAD) - h * scale
            self.assertAlmostEqual(x - left, free_x / 2)
            self.assertAlmostEqual(y - top, free_y / 2)
            self.assertTrue(abs(free_x) < 1e-9 or abs(free_y) < 1e-9)

    def test_panel_groups_follow_row_order(self):
        figures = (graphs() * 3)[:5]
        _, root = self.export(figures=figures, columns=2)
        groups = [g for g in root if g.tag == f"{SVG}g" and re.fullmatch(r"panel\d+", g.get("id", ""))]
        self.assertEqual([g.get("id") for g in groups], [f"panel{i}" for i in range(1, 6)])
        offsets = [tuple(float(v) for v in re.match(r"translate\(([^ ]+) ([^)]+)\)", g.get("transform")).groups())
                   for g in groups]
        self.assertLess(offsets[0][0], offsets[1][0])
        self.assertAlmostEqual(offsets[0][1], offsets[1][1])
        self.assertGreater(offsets[2][1], offsets[0][1])
        self.assertAlmostEqual(offsets[2][0], offsets[0][0])

    def test_invalid_requests(self):
        for args in (("", 2, self.figures), ("T", 5, self.figures), ("T", 1, self.figures * 7), ("T", 1, []),
                     ("T", 1, [None])):
            with self.assertRaises(ValueError, msg=args[:2]):
                export_layout_svg(*args, self.target, SETTINGS)
        with self.assertRaises(ValueError):
            export_layout_svg("T", 2, self.figures, self.target, {**SETTINGS, "format": "png"})
        with self.assertRaises(ValueError):
            export_layout_svg("T", 2, self.figures, self.target.with_suffix(".pdf"), SETTINGS)
        with self.assertRaises(ValueError):
            export_layout_svg("T", 2, self.figures, self.target, {**SETTINGS, "svg_text": "outline"})
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_failure_keeps_previous_file_and_figures(self):
        self.export()
        saved = self.target.read_bytes()
        before = state(self.figures)
        with patch.object(self.figures[1], "savefig", side_effect=OSError("synthetic")):
            with self.assertRaises(OSError):
                self.export(title="Other")
        self.assertEqual(self.target.read_bytes(), saved)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [self.target])
        self.assertEqual(state(self.figures), before)
        with patch("analisi.layout_svg._verify", side_effect=ValueError("bad")):
            with self.assertRaises(ValueError):
                self.export(title="Other")
        self.assertEqual(self.target.read_bytes(), saved)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [self.target])


class RasterCompositionRegressionTests(unittest.TestCase):
    """The screen preview and direct rendering of its figure keep the image-based composition."""

    def test_screen_composition_is_unchanged(self):
        figures = graphs()
        composed = compose_layout("Panels", 2, figures)
        self.assertEqual(tuple(composed.get_size_inches()), (8.4, 3.6))
        self.assertEqual(len(composed.axes), 2)
        for letter, axes in zip("AB", composed.axes):
            self.assertEqual(len(axes.images), 1)
            self.assertFalse(axes.axison)
            self.assertEqual(axes.get_title(loc="left"), letter)
        self.assertEqual(composed.get_suptitle(), "Panels")

    def test_png_and_pdf_exports_of_a_layout_are_unchanged(self):
        composed = compose_layout("Panels", 2, graphs())
        with tempfile.TemporaryDirectory() as folder:
            png = Path(folder) / "layout.png"
            export_figure(composed, png, {"format": "png", "width_mm": 127, "dpi": 300})
            with Image.open(png) as image:
                self.assertEqual(image.size, (1500, round(1500 * 3.6 / 8.4)))
            pdf = Path(folder) / "layout.pdf"
            export_figure(composed, pdf, {"format": "pdf", "width_mm": 127})
            bundle = Path(folder) / "bundle.pdf"
            export_pdf_bundle([composed, compose_layout("Two", 1, graphs())], bundle, {"width_mm": 127})
            for path, pages in ((pdf, 1), (bundle, 2)):
                document = pdfium.PdfDocument(str(path))
                try:
                    self.assertEqual(len(document), pages)
                    page = document[0]
                    width, height = page.get_size()
                    page.close()
                finally:
                    document.close()
                self.assertAlmostEqual(width, 127 / 25.4 * 72, delta=.05)
                self.assertAlmostEqual(height, 127 * 3.6 / 8.4 / 25.4 * 72, delta=.05)
            # The raster PDF really embeds the panel images.
            self.assertIn(b"/Image", pdf.read_bytes())

    def test_svg_of_the_composed_figure_still_embeds_images(self):
        composed = compose_layout("Panels", 2, graphs())
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "raster.svg"
            export_figure(composed, target, {"format": "svg", "width_mm": 127})
            root = ET.parse(target).getroot()
        self.assertEqual(len(root.findall(f".//{SVG}image")), 2)


class DialogNoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
        except tk.TclError as error:
            raise unittest.SkipTest(f"Tk unavailable: {error}")
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def notes(self, **flags):
        from analisi import figure_export_dialog as fed

        seen = {}

        def drive():
            dialog = next(child for child in self.root.winfo_children() if isinstance(child, fed.FigureExportDialog))
            try:
                for name in ("SVG", "PDF", "PNG"):
                    dialog.format.set(name)
                    dialog.update()
                    seen[name] = dialog.note.cget("text")
            finally:
                dialog.cancel()

        saved = dict(fed.SESSION)
        try:
            self.root.after(100, drive)
            fed.FigureExportDialog(self.root, (8.4, 3.6), **flags)
        finally:
            fed.SESSION.clear()
            fed.SESSION.update(saved)
        return seen

    def test_native_layout_distinguishes_vector_formats_from_raster_formats(self):
        seen = self.notes(layout_size=page_size(2, 2))
        for name in ("SVG", "PDF"):
            self.assertIn(f"{name} preserves vector graphics", seen[name])
            self.assertNotIn("raster image", seen[name])
        self.assertIn("raster image", seen["PNG"])
        self.assertIn("Choose SVG or PDF", seen["PNG"])

    def test_imported_layout_keeps_its_raster_note(self):
        seen = self.notes(raster_panels=True)
        for name in ("SVG", "PDF"):
            self.assertIn("stay raster even in SVG and PDF", seen[name])


if __name__ == "__main__":
    unittest.main()
