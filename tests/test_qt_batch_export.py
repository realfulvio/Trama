"""File → Export multiple figures… on Qt: file names, safe writing and the dialog on the active project.

The engine tests need only Matplotlib; the window tests run offscreen and are skipped without PySide6.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

import matplotlib

matplotlib.use("Agg", force=False)
from matplotlib.figure import Figure  # noqa: E402

from trama_qt import batch_export as bx  # noqa: E402

try:
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:  # PySide6 missing, or the Qt platform libraries missing on a headless machine.
    QApplication = None

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
FIXTURE = json.dumps({"version": 2, "tables": [
    {"title": title, "columns": ["Dose", "Response"], "kinds": ["numeric", "numeric"],
     "rows": [[1, a], [2, b], [4, c], [8, d], [16, e]], "formulas": [],
     "analyses": [["XY series", {"X": "Dose", "Y columns": ["Response"], "Drawing": "Line and points"}]],
     "excluded": [], "table_format": "xy", "graph_styles": {}}
    for title, (a, b, c, d, e) in (("Calibrazione $ A", (2.1, 3.2, 5.9, 8.2, 9.3)),
                                   ("Calibrazione B", (1.8, 3.1, 5.2, 7.7, 8.8)))], "layouts": []})


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


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class BatchExportWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from trama_qt import export_options
        from trama_qt.window import MainWindow
        saved = dict(export_options.SESSION)
        self.addCleanup(lambda: (export_options.SESSION.clear(), export_options.SESSION.update(saved)))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.out = self.root / "figures"
        self.out.mkdir()
        self.window = MainWindow()
        self.window._ask = lambda *args, error=None, **kwargs: self.fail(f"calculation failed: {error}")
        self.errors = []
        self.window.error = self.errors.append
        self.window.show()
        self.addCleanup(self._close)
        self.app.processEvents()

    def _close(self):
        self.window.project.dirty = False
        self.window.dispose_inspector()
        self.window.close()
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while self.window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        self.assertIsNone(self.window.job)

    def open_fixture(self, *, layout=True):
        """``sessione.alab`` of the work package, both graphs calculated and a two-panel layout."""
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        path = self.root / "sessione.alab"
        path.write_text(FIXTURE, encoding="utf-8")
        window = self.window
        window.open_path(path)
        self.wait()
        for index in range(len(window.project.runs)):
            window.open_sheet(("graph", index))
            self.wait()
        self.assertTrue(all(run.result is not None and not run.calculation_error for run in window.project.runs))
        if layout:
            window.project.put_layout(Layout("Figura 1", 2, [run.reference for run in window.project.runs],
                                             AUTO_PAPER, WHITE))
            window.project.dirty = False
            window.refresh()
        window.open_sheet(("data", "Calibrazione $ A"))
        return window

    def state(self):
        project = self.window.project
        return (project.dirty, self.window.selected, project.history.can_apply(),
                project.history.can_apply(redo=True), [run.name for run in project.runs],
                [layout.name for layout in project.layouts], [title for title in project.tables])

    def drive(self, script):
        """Replace the modal ``exec`` with ``script(dialog)``; the dialog runs its batch through the event loop."""
        from trama_qt.batch_export_dialog import BatchExportDialog
        seen = {}

        def run(dialog):
            seen["dialog"] = dialog
            dialog.show()
            self.app.processEvents()
            script(dialog)
            end = time.monotonic() + 120
            while dialog.running and time.monotonic() < end:
                self.app.processEvents()
                time.sleep(0.005)
            self.assertFalse(dialog.running)
            return 0

        with mock.patch.object(BatchExportDialog, "exec", run):
            self.window.export_batch()
        return seen.get("dialog")

    def start(self, folder, fmt="PDF", width="120"):
        def script(dialog):
            dialog.format.setCurrentText(fmt)
            dialog.width.setText(width)
            dialog.folder.setText(str(folder))
            dialog.refresh()
            dialog.start_export()
        return script

    def test_three_figures_in_each_format_then_suffixed(self):
        import pypdfium2 as pdfium
        from PIL import Image
        window = self.open_fixture()
        before = self.state()
        self.assertTrue(window.actions["export_batch"].isEnabled())
        dialog = self.drive(lambda d: None)
        self.assertEqual([row.label for row in dialog.rows],
                         ["Graph · XY series of Calibrazione $ A", "Graph · XY series of Calibrazione B", "Layout · Figura 1"])
        self.assertTrue(all(row.ready for row in dialog.rows))
        self.assertIsNone(dialog.outcomes)
        for fmt in ("PDF", "SVG", "PNG"):
            folder = self.out / fmt
            folder.mkdir()
            dialog = self.drive(self.start(folder, fmt, "120"))
            ext = fmt.lower()
            names = [f"XY series of Calibrazione $ A.{ext}", f"XY series of Calibrazione B.{ext}", f"Figura 1.{ext}"]
            self.assertEqual([o.filename for o in dialog.outcomes], names)
            self.assertEqual([o.status for o in dialog.outcomes], ["done"] * 3, dialog.outcomes)
            self.assertEqual(sorted(p.name for p in folder.iterdir()), sorted(names))
            for name in names:
                path = folder / name
                if ext == "pdf":
                    document = pdfium.PdfDocument(str(path))
                    self.assertEqual(len(document), 1)
                    self.assertAlmostEqual(document[0].get_width() / 72 * 25.4, 120, delta=0.5)
                elif ext == "svg":
                    root = ET.parse(path).getroot()
                    width = root.get("width")
                    value = float(width.rstrip("ptmx"))
                    millimetres = value / 72 * 25.4 if width.endswith("pt") else value
                    self.assertAlmostEqual(millimetres, 120, delta=0.5, msg=f"{name}: {width}")
                else:
                    dpi = dialog.settings()["dpi"]
                    with Image.open(path) as image:
                        self.assertEqual(image.size[0], round(120 * dpi / 25.4))
            # The layout stays vector in SVG and PDF.
            if ext == "svg":
                self.assertIn("<path", (folder / f"Figura 1.{ext}").read_text(encoding="utf-8"))
            digests = {name: digest(folder / name) for name in names}
            dialog = self.drive(self.start(folder, fmt, "120"))
            self.assertEqual([o.filename for o in dialog.outcomes],
                             [f"XY series of Calibrazione $ A (2).{ext}", f"XY series of Calibrazione B (2).{ext}", f"Figura 1 (2).{ext}"])
            self.assertEqual({name: digest(folder / name) for name in names}, digests)
            self.assertFalse([p for p in folder.iterdir() if p.name.startswith(".")])
            self.assertIn("3", window.message.text())
        self.assertEqual(self.state(), before)
        self.assertEqual(self.errors, [])

    def test_unavailable_figures_are_listed_with_a_reason(self):
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        window = self.open_fixture(layout=False)
        window.project.put_layout(Layout("Figura 1", 2, [run.reference for run in window.project.runs],
                                         AUTO_PAPER, WHITE))
        window.project.runs[1].calculation_error = "Y must be numeric"
        window.refresh()
        dialog = self.drive(lambda d: None)
        self.assertEqual([(row.ready, bool(row.reason)) for row in dialog.rows],
                         [(True, False), (False, True), (False, True)])
        self.assertIn("Y must be numeric", dialog.rows[1].reason)
        item = dialog.tree.topLevelItem(1)
        self.assertFalse(item.flags() & item.flags().ItemIsEnabled)
        dialog.check_all(False)
        self.assertFalse(dialog.export_button.isEnabled())
        dialog.check_all(True)
        self.assertEqual([row.label for row in dialog.chosen()], ["Graph · XY series of Calibrazione $ A"])
        # Not calculated at all: no ready figure, so the command says why instead of opening.
        window.project.runs[0].result = None
        window.refresh()
        self.errors.clear()
        with mock.patch("trama_qt.batch_export_dialog.BatchExportDialog.exec") as opened:
            window.export_batch()
        opened.assert_not_called()
        self.assertTrue(self.errors)

    def test_duplicate_titles_get_distinct_rows_and_names(self):
        window = self.open_fixture(layout=False)
        window.project.runs[0].label = window.project.runs[1].label = "Dose: risposta"
        window.refresh()
        dialog = self.drive(self.start(self.out, "PNG", ""))
        self.assertEqual([row.label for row in dialog.rows],
                         ["Graph · Dose: risposta", "Graph · Dose: risposta (2)"])
        self.assertEqual([o.filename for o in dialog.outcomes], ["Dose_ risposta.png", "Dose_ risposta (2).png"])
        self.assertEqual([run.name for run in window.project.runs], ["Dose: risposta"] * 2)  # Titles unchanged.

    def test_inspector_draft_is_settled_first(self):
        window = self.open_fixture()
        window.open_sheet(("graph", 0))
        self.wait()
        window.toggle_inspector()
        axes = window.project.runs[0].result.figure.axes[0]
        confirmed = axes.get_title()
        window.inspector.widgets["title"].setText("Bozza")
        window.inspector._now("title")
        self.assertTrue(window.inspector.has_draft)
        with mock.patch("trama_qt.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel), \
                mock.patch("trama_qt.batch_export_dialog.BatchExportDialog.exec") as opened:
            window.export_batch()
        opened.assert_not_called()
        self.assertTrue(window.inspector.has_draft)  # Cancel keeps the user on the graph with the draft.
        with mock.patch("trama_qt.window.QMessageBox.question", return_value=QMessageBox.StandardButton.Discard):
            dialog = self.drive(self.start(self.out, "SVG", ""))
        self.assertEqual([o.status for o in dialog.outcomes], ["done"] * 3)
        self.assertEqual(axes.get_title(), confirmed)
        self.assertNotIn("Bozza", (self.out / "XY series of Calibrazione $ A.svg").read_text(encoding="utf-8"))

    def test_cancelled_folder_choice_writes_nothing(self):
        self.open_fixture()
        before = self.state()

        def script(dialog):
            self.assertEqual(dialog.folder.text(), str(self.root))  # The project folder is the default.
            dialog.format.setCurrentText("PDF")
            dialog.folder.setText("")
            dialog.refresh()
            self.assertTrue(dialog.export_button.isEnabled())
            with mock.patch("trama_qt.batch_export_dialog.QFileDialog.getExistingDirectory", return_value=""):
                dialog.start_export()
            self.assertIsNone(dialog.batch)
            with mock.patch("trama_qt.batch_export_dialog.QFileDialog.getExistingDirectory",
                            return_value=str(self.out)):
                dialog.start_export()  # Picks the folder and shows the names again; nothing is written yet.
            self.assertIsNone(dialog.batch)
            self.assertEqual(dialog.tree.topLevelItem(0).text(1), "XY series of Calibrazione $ A.pdf")
            dialog.reject()

        listing = sorted(p.name for p in self.root.iterdir())
        dialog = self.drive(script)
        self.assertIsNone(dialog.outcomes)
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), listing)
        self.assertEqual(list(self.out.iterdir()), [])
        self.assertEqual(self.state(), before)

    def test_preview_shows_existing_names_and_invalid_settings(self):
        self.open_fixture()
        (self.out / "XY SERIES OF CALIBRAZIONE B.png").write_bytes(b"x")

        def script(dialog):
            dialog.format.setCurrentText("PNG")
            dialog.folder.setText(str(self.out))
            dialog.width.setText("abc")
            self.assertFalse(dialog.export_button.isEnabled())
            self.assertIn("millimetres", dialog.summary.text())
            dialog.width.setText("5000")
            self.assertFalse(dialog.export_button.isEnabled())
            self.assertIn("Calibrazione", dialog.summary.text())
            dialog.width.setText("")
            dialog.dpi.setText("2.5")
            self.assertFalse(dialog.export_button.isEnabled())
            dialog.dpi.setText("150")
            self.assertTrue(dialog.export_button.isEnabled())
            self.assertEqual([dialog.tree.topLevelItem(i).text(1) for i in range(3)],
                             ["XY series of Calibrazione $ A.png", "XY series of Calibrazione B (2).png", "Figura 1.png"])
            self.assertFalse(dialog.dpi.isHidden())
            dialog.format.setCurrentText("SVG")
            self.assertTrue(dialog.dpi.isHidden())
            self.assertFalse(dialog.svg_text.isHidden())
            dialog.reject()

        self.drive(script)

    def test_renderer_error_and_cancel_in_the_dialog(self):
        from analisi import figure_export
        self.open_fixture()
        real = figure_export.export_figure
        calls = []

        def flaky(fig, path, settings):
            calls.append(path)
            if len(calls) == 1:
                raise RuntimeError("renderer exploded")
            return real(fig, path, settings)

        with mock.patch("trama_qt.batch_export_dialog.fe.export_figure", flaky):
            dialog = self.drive(self.start(self.out / "", "PNG", ""))
        self.assertEqual([o.status for o in dialog.outcomes], ["error", "done", "done"])
        self.assertIn("renderer exploded", dialog.results.topLevelItem(0).text(2))
        self.assertIn("1", dialog.totals.text())

        folder = self.out / "cancel"
        folder.mkdir()

        def cancel_after_first(dialog):
            self.start(folder, "PNG", "")(dialog)
            self.app.processEvents()  # The first figure is written by the event loop…
            while dialog.batch.position < 1:
                self.app.processEvents()
            dialog.reject()  # …then Cancel (or Esc) stops before the two that wait.
            self.assertTrue(dialog.isVisible())

        dialog = self.drive(cancel_after_first)
        self.assertEqual([o.status for o in dialog.outcomes], ["done", "cancelled", "cancelled"])
        self.assertEqual([p.name for p in folder.iterdir()], ["XY series of Calibrazione $ A.png"])
        self.assertEqual(dialog.close_button.text(), "Close")

    def test_italian_labels(self):
        from analisi.i18n import active_language, set_language
        previous = active_language()
        set_language("it")
        self.addCleanup(set_language, previous)
        from trama_qt.batch_export_dialog import BatchExportDialog, batch_rows, text
        self.open_fixture()
        self.assertEqual(text("command"), "Esporta più figure…")
        rows = batch_rows(self.window.project, ())
        self.assertEqual(rows[0].label, "Grafico · XY series of Calibrazione $ A")
        dialog = BatchExportDialog(self.window, self.window.project, rows)
        self.assertEqual(dialog.windowTitle(), "Esporta più figure")
        self.assertEqual(dialog.export_button.text(), "Esporta")
        dialog.deleteLater()


if __name__ == "__main__":
    unittest.main()
