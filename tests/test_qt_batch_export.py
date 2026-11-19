"""File → Export multiple figures… on Qt: file names and safe writing (the engine needs only Matplotlib)."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg", force=False)
from matplotlib.figure import Figure  # noqa: E402

from trama_qt import batch_export as bx  # noqa: E402

# The same cases as the oracle of the work package (fixture/filename-cases.json).
CASES = [
    {"titles": ["Assay: A/B", "assay: A/B", "CON", "… Δ", "..", "R²"], "format": "svg",
     "occupied": ["ASSAY_ A_B.svg", "_CON.svg"],
     "expected": ["Assay_ A_B (2).svg", "assay_ A_B (3).svg", "_CON (2).svg", "… Δ.svg", "Figure.svg", "R².svg"]},
    {"titles": ["Café", "Café", "LPT9.tmp"], "format": "pdf", "occupied": ["café.pdf"],
     "expected": ["Café (2).pdf", "Café (3).pdf", "_LPT9.tmp.pdf"]},
    {"titles": ["", ".", "con", "AUX", "Dose", "Dose (2)", "Dose"], "format": "png", "occupied": [],
     "expected": ["Figure.png", "Figure (2).png", "_con.png", "_AUX.png", "Dose.png", "Dose (2).png",
                  "Dose (3).png"]},
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def figure(title="F"):
    result = Figure(figsize=(4, 3))
    axes = result.add_subplot()
    axes.plot([1, 2, 3], [2, 1, 3])
    axes.set_title(title)
    return result


def writer(fig, fmt):
    from analisi.figure_export import export_figure
    settings = {"format": fmt, "dpi": 100} if fmt == "png" else {"format": fmt}
    return lambda path: export_figure(fig, path, settings)


class FileNameTests(unittest.TestCase):
    def test_oracle_cases(self):
        for case in CASES:
            with self.subTest(case=case["titles"]):
                self.assertEqual(bx.plan_filenames(case["titles"], case["format"], case["occupied"]), case["expected"])

    def test_formats_and_inputs(self):
        for fmt in ("", "exe", "../png", "PNG", "tiff", None):
            with self.assertRaises(ValueError):
                bx.plan_filenames(["Dose"], fmt)
        self.assertEqual(bx.plan_filenames([], "png"), [])

    def test_characters_reserved_names_and_length(self):
        plan = bx.plan_filenames
        self.assertEqual(plan(["a\x00\x01b", 'x<>:"|?*y', "../../evil", "a\\b/c", " . Dose . "], "png"),
                         ["a_b.png", "x_y.png", "_.._evil.png", "a_b_c.png", "Dose.png"])
        # NFC: a decomposed é is the same name as the composed one; Unicode spaces and dots stay literal.
        self.assertEqual(plan(["Cafe\u0301", "Café"], "pdf"), ["Café.pdf", "Café (2).pdf"])
        self.assertEqual(plan(["a\u3000b\u2024c"], "svg"), ["a\u3000b\u2024c.svg"])
        self.assertEqual(plan(["COM1.data", "com¹", "CONSOLE", "NUL .x", "PRN"], "png"),
                         ["_COM1.data.png", "_com¹.png", "CONSOLE.png", "_NUL .x.png", "_PRN.png"])
        long = "x" * 200
        first, second = plan([long, long], "png")
        self.assertEqual(first, "x" * 96 + ".png")
        self.assertEqual(second, "x" * 92 + " (2).png")
        self.assertEqual(len(Path(second).stem), 96)
        self.assertEqual(plan(["a" * 95 + " .tail"], "png"), ["a" * 95 + ".png"])
        # Folders count as occupied names too, and the comparison ignores case.
        self.assertEqual(plan(["Results"], "png", ["results.PNG"]), ["Results (2).png"])
        for name in plan(["../x", "/etc/passwd", "C:\\Windows", "\\\\server\\share"], "pdf"):
            self.assertNotIn("/", name)
            self.assertNotIn("\\", name)
            self.assertFalse(name.startswith("."))


class BatchWriterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.folder = self.root / "out"
        self.folder.mkdir()

    def items(self, titles, fmt, fail=()):
        names = bx.plan_filenames(titles, fmt, bx.folder_names(self.folder))
        items = []
        for title, name in zip(titles, names):
            if title in fail:
                def render(path, title=title):
                    Path(path).write_bytes(b"partial")
                    raise RuntimeError(f"renderer failed on {title}")
            else:
                render = writer(figure(title), fmt)
            items.append(bx.BatchItem(title, name, render))
        return items

    def listing(self):
        return sorted(path.name for path in self.folder.iterdir())

    def test_three_files_then_suffixed_rerun(self):
        import pypdfium2 as pdfium
        from PIL import Image
        for fmt in ("png", "svg", "pdf"):
            shutil.rmtree(self.folder)
            self.folder.mkdir()
            batch = bx.BatchExport(self.folder, fmt, self.items(["A", "B", "C"], fmt))
            outcomes = batch.run()
            self.assertEqual([o.status for o in outcomes], ["done"] * 3, outcomes)
            self.assertEqual(self.listing(), [f"{t}.{fmt}" for t in "ABC"])
            for name in self.listing():
                path = self.folder / name
                if fmt == "png":
                    with Image.open(path) as image:
                        self.assertEqual(image.size, (400, 300))
                elif fmt == "svg":
                    self.assertTrue(ET.parse(path).getroot().tag.endswith("svg"))
                else:
                    self.assertEqual(len(pdfium.PdfDocument(str(path))), 1)
            before = {name: digest(self.folder / name) for name in self.listing()}
            again = bx.BatchExport(self.folder, fmt, self.items(["A", "B", "C"], fmt)).run()
            self.assertEqual([o.filename for o in again], [f"{t} (2).{fmt}" for t in "ABC"])
            self.assertEqual({name: digest(self.folder / name) for name in before}, before)
            self.assertEqual(len(self.listing()), 6)
            self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["out"])  # Nothing outside the folder.

    def test_renderer_error_continues_and_leaves_no_temporary(self):
        batch = bx.BatchExport(self.folder, "png", self.items(["A", "B", "C"], "png", fail={"B"}))
        outcomes = batch.run()
        self.assertEqual([o.status for o in outcomes], ["done", "error", "done"])
        self.assertIn("renderer failed on B", outcomes[1].reason)
        self.assertEqual(self.listing(), ["A.png", "C.png"])
        self.assertEqual(batch.counts(), {"done": 2, "skipped": 0, "error": 1, "cancelled": 0})

    def test_name_taken_after_the_preview_is_never_overwritten(self):
        items = self.items(["A", "B", "C"], "png")
        (self.folder / "b.PNG").write_bytes(b"someone else")  # Case-insensitive clash with B.png.
        (self.folder / "C.png").mkdir()  # A folder with the same name.
        outcomes = bx.BatchExport(self.folder, "png", items).run()
        self.assertEqual([(o.status, o.reason) for o in outcomes], [("done", ""), ("skipped", "conflict"),
                                                                    ("skipped", "conflict")])
        self.assertEqual((self.folder / "b.PNG").read_bytes(), b"someone else")
        self.assertTrue((self.folder / "C.png").is_dir())
        self.assertEqual(self.listing(), ["A.png", "C.png", "b.PNG"])

    def test_exclusive_create_without_hard_links(self):
        items = self.items(["A", "B"], "svg")
        real_open = open

        def racing_open(path, mode="r", *args, **kwargs):  # B appears between the listing and the create.
            if mode == "xb" and Path(path).name == "B.svg":
                Path(path).write_bytes(b"raced")
            return real_open(path, mode, *args, **kwargs)

        with mock.patch("os.link", side_effect=PermissionError(1, "Operation not permitted")), \
                mock.patch("builtins.open", racing_open):
            outcomes = bx.BatchExport(self.folder, "svg", items).run()
        self.assertEqual([o.status for o in outcomes], ["done", "skipped"])
        self.assertTrue(ET.parse(self.folder / "A.svg").getroot().tag.endswith("svg"))
        self.assertEqual((self.folder / "B.svg").read_bytes(), b"raced")

    def test_partial_copy_is_removed(self):
        items = self.items(["A"], "png")
        with mock.patch("os.link", side_effect=OSError(18, "Invalid cross-device link")), \
                mock.patch("shutil.copyfileobj", side_effect=OSError(28, "No space left on device")):
            outcomes = bx.BatchExport(self.folder, "png", items).run()
        self.assertEqual(outcomes[0].status, "error")
        self.assertEqual(self.listing(), [])

    def test_invalid_output_is_an_error(self):
        items = [bx.BatchItem("A", "A.pdf", lambda path: Path(path).write_text("not a pdf")),
                 bx.BatchItem("B", "B.pdf", writer(figure(), "pdf"))]
        outcomes = bx.BatchExport(self.folder, "pdf", items).run()
        self.assertEqual([o.status for o in outcomes], ["error", "done"])
        self.assertEqual(self.listing(), ["B.pdf"])

    def test_cancel_while_two_files_wait(self):
        batch = bx.BatchExport(self.folder, "png", self.items(["A", "B", "C"], "png"))
        batch.start()
        self.assertTrue(batch.step())
        batch.cancel()
        self.assertFalse(batch.step())
        self.assertEqual([o.status for o in batch.outcomes], ["done", "cancelled", "cancelled"])
        self.assertEqual(self.listing(), ["A.png"])

    def test_unwritable_folder_stops_the_batch(self):
        with mock.patch("tempfile.mkdtemp", side_effect=PermissionError(13, "Permission denied")):
            outcomes = bx.BatchExport(self.folder, "png", self.items(["A", "B"], "png")).run()
        self.assertEqual([(o.status, o.reason) for o in outcomes], [("skipped", "folder")] * 2)
        missing = bx.BatchExport(self.root / "gone", "png", [bx.BatchItem("A", "A.png", writer(figure(), "png"))])
        self.assertEqual(missing.run()[0].reason, "folder")
        self.assertFalse((self.root / "gone").exists())

    def test_folder_lost_during_the_batch(self):
        items = self.items(["A", "B", "C"], "png")
        original = items[1].render

        def vanish(path):
            shutil.rmtree(self.folder)
            original(path)

        items[1].render = vanish
        outcomes = bx.BatchExport(self.folder, "png", items).run()
        self.assertEqual([o.status for o in outcomes], ["done", "error", "skipped"])
        self.assertEqual(outcomes[2].reason, "folder")

    @unittest.skipIf(os.name == "nt" or not hasattr(os, "geteuid") or os.geteuid() == 0,
                     "permissions are not enforced for root or on Windows")
    def test_read_only_folder(self):
        os.chmod(self.folder, 0o500)
        self.addCleanup(os.chmod, self.folder, 0o700)
        outcomes = bx.BatchExport(self.folder, "png", self.items(["A"], "png")).run()
        self.assertEqual(outcomes[0].reason, "folder")


if __name__ == "__main__":
    unittest.main()
