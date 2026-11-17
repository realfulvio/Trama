import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch

from matplotlib.figure import Figure
from PIL import Image
import pypdfium2 as pdfium

from analisi.figure_export import check_destination, export_figure, plan_export

CASES = json.loads((Path(__file__).parent / "data" / "figure_export" / "plans.json").read_text(encoding="utf-8"))
KEYS = ("width_mm", "height_mm", "dpi", "pixels", "transparent", "svg_text")


def sample():
    figure = Figure(figsize=(8, 5), dpi=113, layout="constrained")
    axes = figure.subplots()
    axes.plot([0, 1, 2], [1, 0, 4], label="Series A")
    axes.set_title("Publication sample")
    axes.legend()
    return figure


class PlanTests(unittest.TestCase):
    def test_fixture_plans(self):
        for name, (size, settings, expected) in CASES.items():
            plan = plan_export(size, settings)
            for key, want in zip(KEYS, expected, strict=True):
                if isinstance(want, float):
                    self.assertAlmostEqual(plan[key], want, msg=(name, key))
                else:
                    self.assertEqual(plan[key], want, (name, key))

    def test_invalid_requests(self):
        for settings in ({"format": "exe"}, {"format": "png", "dpi": True}, {"format": "png", "dpi": 300.5},
                         {"format": "png", "dpi": 71}, {"format": "png", "dpi": 1201},
                         {"format": "png", "dpi": 1200, "width_mm": 400}, {"format": "pdf", "width_mm": 501},
                         {"format": "pdf", "width_mm": 19}, {"format": "png", "width_mm": float("nan")},
                         {"format": "png", "width_mm": True}, {"format": "svg", "svg_text": "invalid"},
                         {"format": "png", "transparent": 1}):
            with self.assertRaises(ValueError, msg=settings):
                plan_export([8, 5], settings)

    def test_height_limit_uses_the_aspect_ratio(self):
        with self.assertRaises(ValueError):
            plan_export([10, 1], {"format": "pdf", "width_mm": 100})

    def test_pixel_limits(self):
        with self.assertRaisesRegex(ValueError, "per side"):
            plan_export([1, 1], {"format": "png", "width_mm": 500, "dpi": 1200})
        with self.assertRaisesRegex(ValueError, "pixels"):
            plan_export([1, 1], {"format": "tiff", "width_mm": 254, "dpi": 1200})

    def test_hidden_fields_are_ignored(self):
        plan = plan_export([8, 5], {"format": "pdf", "dpi": "hidden", "svg_text": "invalid", "transparent": True})
        self.assertIsNone(plan["dpi"])
        self.assertIsNone(plan["svg_text"])
        self.assertTrue(plan["transparent"])
        self.assertFalse(plan_export([8, 5], {"format": "tiff", "transparent": True})["transparent"])

    def test_extensions(self):
        check_destination("a.tif", "tiff")
        check_destination("a.TIFF", "tiff")
        with self.assertRaises(ValueError):
            check_destination("a.png", "pdf")


class FileTests(unittest.TestCase):
    def test_files_have_the_planned_geometry_and_leave_the_figure_alone(self):
        figure = sample()
        state = (tuple(figure.get_size_inches()), figure.dpi, figure.canvas)
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            export_figure(figure, directory / "a.png", CASES["screen"][1])
            with Image.open(directory / "a.png") as image:
                self.assertEqual(image.size, (605, 378))
                self.assertEqual(image.convert("RGBA").getpixel((0, 0))[3], 0)
            export_figure(figure, directory / "b.tif", CASES["print"][1])
            with Image.open(directory / "b.tif") as image:
                self.assertEqual((image.mode, image.size, image.tag_v2[259]), ("RGB", (1004, 627), 5))
            export_figure(figure, directory / "c.pdf", CASES["pdf"][1])
            with pdfium.PdfDocument(directory / "c.pdf") as document:
                self.assertAlmostEqual(document[0].get_size()[0], 85 * 72 / 25.4, places=1)
            for mode, present in (("text", True), ("paths", False)):
                export_figure(figure, directory / f"{mode}.svg", {"format": "svg", "svg_text": mode})
                root = ET.parse(directory / f"{mode}.svg").getroot()
                words = " ".join("".join(e.itertext()) for e in root.iter() if e.tag.endswith("}text"))
                self.assertEqual("Publication sample" in words, present)
            self.assertEqual(sorted(p.name for p in directory.iterdir()),
                             ["a.png", "b.tif", "c.pdf", "paths.svg", "text.svg"])
        self.assertEqual((tuple(figure.get_size_inches()), figure.dpi, figure.canvas), state)

    def test_failed_write_keeps_the_previous_file_and_leaves_no_temporary(self):
        figure = sample()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "keep.png"
            path.write_bytes(b"original")

            def fail(target, *args, **kwargs):
                Path(target).write_bytes(b"partial")
                raise OSError("simulated")

            with patch.object(figure, "savefig", side_effect=fail), self.assertRaises(OSError):
                export_figure(figure, path, {"format": "png"})
            self.assertEqual(path.read_bytes(), b"original")
            self.assertEqual([p.name for p in Path(temp).iterdir()], ["keep.png"])
            with self.assertRaises(ValueError):
                export_figure(figure, Path(temp) / "wrong.pdf", {"format": "png"})
            self.assertEqual([p.name for p in Path(temp).iterdir()], ["keep.png"])
        self.assertEqual(tuple(figure.get_size_inches()), (8, 5))


if __name__ == "__main__":
    unittest.main()
