import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from matplotlib.figure import Figure
import pandas as pd
from PIL import Image
import pypdfium2 as pdfium

from analisi.data import Dataset, load_workspace, save_project
from analisi.figure_export import export_figure, export_pdf_bundle
from analisi.layout_pdf import PdfLayoutPage
from analisi.layout_svg import export_layout_svg
from analisi.presentation import Layout, compose_layout


class LayoutPageTests(unittest.TestCase):
    def test_page_settings_roundtrip_and_legacy_defaults(self):
        source = Dataset(pd.DataFrame({"X": [1, 2], "Y": [2, 3]}))
        source.analyses.append(("Linear regression", {"X": "X", "Y": "Y"}))
        refs = [("Data", 0), ("Data", 0)]
        page = Layout("Results", 2, refs, "A4 landscape", "#dce8f2")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "pages.alab"
            save_project(path, {"Data": source}, layouts=[page])
            self.assertEqual(load_workspace(path)[1], [page])
            document = json.loads(path.read_text(encoding="utf-8"))
            for field in ("paper", "background"):
                del document["layouts"][0][field]
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertEqual(load_workspace(path)[1], [Layout("Results", 2, refs)])

        default = Layout("Legacy", 1, refs)
        self.assertEqual(default.paper, "Automatic")
        self.assertEqual(default.background, "#ffffff")
        for options in (("Custom", "#ffffff"), ("Automatic", "#xyzxyz"), ("Automatic", "transparent")):
            with self.assertRaises(ValueError):
                Layout("Invalid", 1, refs, *options)

    def test_paper_size_and_background_reach_all_formats(self):
        figure = Figure(figsize=(3, 2))
        axes = figure.add_subplot()
        axes.plot([0, 1], [0, 1], label="series")
        axes.set_title("Panel A text")
        figures = (figure, figure)
        page = {"paper": "A4 landscape", "background": "#dce8f2"}
        native = compose_layout("Page title", 2, figures, **page)
        self.assertAlmostEqual(native.get_figwidth() * 25.4, 297)
        self.assertAlmostEqual(native.get_figheight() * 25.4, 210)
        with TemporaryDirectory() as directory:
            path = Path(directory)
            for fmt, extension in (("png", "png"), ("tiff", "tif")):
                target = path / f"layout.{extension}"
                export_figure(native, target, {"format": fmt, "width_mm": 148.5, "dpi": 96})
                with Image.open(target) as image:
                    self.assertEqual(image.size, (561, 397))
                    self.assertEqual(image.convert("RGB").getpixel((1, 1)), (220, 232, 242))
            svg = path / "layout.svg"
            export_layout_svg("Page title", 2, figures, svg, {}, **page)
            xml = svg.read_text(encoding="utf-8")
            for token in ('width="297mm"', 'height="210mm"', '#dce8f2'):
                self.assertIn(token, xml)
            pdf = path / "layout.pdf"
            layout = PdfLayoutPage("Page title", 2, figures, **page)
            export_pdf_bundle([layout], pdf, {})
            with pdfium.PdfDocument(pdf) as document:
                pdf_page = document[0]
                self.assertAlmostEqual(pdf_page.get_width() * 25.4 / 72, 297, places=3)
                self.assertAlmostEqual(pdf_page.get_height() * 25.4 / 72, 210, places=3)
                text = pdf_page.get_textpage()
                try:
                    self.assertIn("Page title", text.get_text_range())
                finally:
                    text.close()
                bitmap = pdf_page.render()
                try:
                    self.assertEqual(bitmap.to_pil().convert("RGB").getpixel((2, 2)), (220, 232, 242))
                finally:
                    bitmap.close()
                    pdf_page.close()
