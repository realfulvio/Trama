from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from matplotlib.figure import Figure
import pypdfium2 as pdfium

from analisi.figure_export import export_figure
from analisi.presentation import apply_style, validated_style


LABEL = {"text": "p < 0.05 – città\n$literal$", "units": "axes", "position": [.15, .8],
         "target": [.75, .45], "color": "#174e78", "size": 11, "align": "left"}


class GraphAnnotationTests(unittest.TestCase):
    def setUp(self):
        self.figure = Figure(figsize=(4, 3))
        self.axes = self.figure.add_subplot()
        self.axes.plot([1, 2, 3], [2, 4, 8])

    def test_text_and_arrow_export_and_removal(self):
        before = self.axes.get_xlim(), self.axes.get_ylim()
        style = {"annotations": [LABEL]}
        apply_style(self.figure, style)
        apply_style(self.figure, style)
        self.assertEqual(len(self.axes.texts), 1)
        artist = self.axes.texts[0]
        self.assertEqual(artist.get_text(), LABEL["text"])
        self.assertIsNotNone(artist.arrow_patch)
        self.assertEqual((self.axes.get_xlim(), self.axes.get_ylim()), before)
        with TemporaryDirectory() as directory:
            svg = Path(directory) / "chart.svg"
            export_figure(self.figure, svg, {"format": "svg", "svg_text": "text"})
            text = svg.read_text(encoding="utf-8")
            self.assertIn("p &lt; 0.05 – città", text)
            self.assertIn("$literal$", text)
            pdf = Path(directory) / "chart.pdf"
            export_figure(self.figure, pdf, {"format": "pdf"})
            with pdfium.PdfDocument(pdf) as document:
                page = document[0]
                try:
                    textpage = page.get_textpage()
                    try:
                        text = textpage.get_text_range()
                        self.assertIn("p < 0.05 – città", " ".join(text.split()))
                        self.assertIn("$literal$", text)
                    finally:
                        textpage.close()
                finally:
                    page.close()
        apply_style(self.figure, {})
        self.assertEqual(len(self.axes.texts), 0)
        self.assertEqual((self.axes.get_xlim(), self.axes.get_ylim()), before)

    def test_data_annotations_skip_out_of_domain_coordinates(self):
        style = {"annotations": [{**LABEL, "units": "data", "position": [1.5, 3], "target": [1.5, -1]}]}
        apply_style(self.figure, style)
        self.assertEqual(len(self.axes.texts), 1)
        apply_style(self.figure, {**style, "yscale": "log"})
        self.assertEqual(len(self.axes.texts), 0)
        apply_style(self.figure, style)
        self.assertEqual(len(self.axes.texts), 1)

    def test_invalid_annotation_records(self):
        for fields in ({"text": " "}, {"units": "window"}, {"position": [1.1, .5]}, {"target": [0, float("nan")]},
                       {"size": 100}, {"color": "no color"}, {"align": "middle"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                validated_style({"annotations": [{**LABEL, **fields}]})
        with self.assertRaises(ValueError):
            validated_style({"annotations": LABEL})
