"""Qt print output, preview, menu routing and Office insertion without a printer or Office."""
from contextlib import closing
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from matplotlib.figure import Figure
import pandas as pd
from PIL import Image
import pypdfium2 as pdfium

from analisi.i18n import active_language, set_language, tr
from analisi.info import InfoSheet, NOTE_BOLD
from analisi.presentation import Layout
from analisi.reporting import Result
from trama_qt import office

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QPageRanges
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter
    from PySide6.QtWidgets import QApplication, QMessageBox
except ImportError:
    QApplication = None


class ComError(Exception):
    strerror = "test COM error"


class OfficeTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(set_language, active_language())
        set_language("en")
        self.application = Mock()
        self.dispatch = Mock(return_value=self.application)
        self.com = SimpleNamespace(CoInitializeEx=Mock(return_value=1), CoUninitialize=Mock())
        self.enterContext(patch.object(office, "ON_WINDOWS", True))
        self.enterContext(patch.object(office.ctypes, "WinDLL", return_value=self.com, create=True))
        self.enterContext(patch.dict(sys.modules, {"pywintypes": SimpleNamespace(com_error=ComError),
                                                   "win32com.client.dynamic": SimpleNamespace(Dispatch=self.dispatch)}))
        self.path = Path("figure.png")

    def test_word_embeds_the_figure_in_a_new_document(self):
        document = self.application.Documents.Add.return_value
        document.PageSetup = SimpleNamespace(PageWidth=600, PageHeight=800, LeftMargin=50, RightMargin=50,
                                             TopMargin=50, BottomMargin=50)
        office.send_picture("Word", self.path, "Famiglia α", (600, 300))
        self.dispatch.assert_called_once_with("Word.Application")
        self.application.Documents.Add.assert_called_once_with()
        document.Range.assert_called_once_with(0, 0)
        document.InlineShapes.AddPicture.assert_called_once_with(str(self.path), False, True, document.Range.return_value)
        picture = document.InlineShapes.AddPicture.return_value
        self.assertEqual((picture.Width, picture.Height, picture.AlternativeText), (500, 250, "Famiglia α"))
        self.assertIs(self.application.Visible, True)
        document.Activate.assert_called_once_with()
        document.Close.assert_not_called()
        self.com.CoInitializeEx.assert_called_once_with(None, 2)
        self.com.CoUninitialize.assert_called_once_with()

    def test_powerpoint_embeds_and_centres_the_figure_on_a_new_blank_slide(self):
        presentation = self.application.Presentations.Add.return_value
        presentation.PageSetup = SimpleNamespace(SlideWidth=960, SlideHeight=540)
        office.send_picture("PowerPoint", self.path, "Figure β", (300, 600))
        self.dispatch.assert_called_once_with("PowerPoint.Application")
        self.application.Presentations.Add.assert_called_once_with(-1)
        presentation.Slides.Add.assert_called_once_with(1, 12)
        shapes = presentation.Slides.Add.return_value.Shapes
        shapes.AddPicture.assert_called_once()
        args = shapes.AddPicture.call_args.args
        self.assertEqual(args[:3], (str(self.path), 0, -1))
        for actual, expected in zip(args[3:], (357, 24, 246, 492), strict=True):
            self.assertAlmostEqual(actual, expected)
        self.assertEqual(shapes.AddPicture.return_value.AlternativeText, "Figure β")
        presentation.Close.assert_not_called()

    def test_an_existing_different_com_apartment_is_not_uninitialized(self):
        self.com.CoInitializeEx.return_value = -2147417850  # RPC_E_CHANGED_MODE
        with office._office_apartment():
            self.com.CoUninitialize.assert_not_called()
        self.com.CoUninitialize.assert_not_called()

    def test_other_com_initialization_failures_do_not_start_office(self):
        self.com.CoInitializeEx.return_value = -2147024882
        with self.assertRaisesRegex(office.OfficeError, "0x8007000E"):
            office.send_picture("Word", self.path, "Figure", (400, 200))
        self.com.CoUninitialize.assert_not_called()
        self.dispatch.assert_not_called()

    def test_missing_app_and_failed_insert_are_reported_separately(self):
        self.dispatch.side_effect = ComError()
        with self.assertRaisesRegex(office.OfficeError, "Check that the desktop application is installed"):
            office.send_picture("Word", self.path, "Figure", (400, 200))
        self.dispatch.side_effect = None
        presentation = self.application.Presentations.Add.return_value
        presentation.PageSetup = SimpleNamespace(SlideWidth=960, SlideHeight=540)
        presentation.Slides.Add.return_value.Shapes.AddPicture.side_effect = ComError()
        with self.assertRaisesRegex(office.OfficeError, "Could not insert the figure in PowerPoint"):
            office.send_picture("PowerPoint", self.path, "Figure", (400, 200))
        presentation.Close.assert_called_once_with()
        self.application.Quit.assert_not_called()
        self.assertEqual(self.com.CoUninitialize.call_count, 2)


@unittest.skipIf(QApplication is None, "Qt Print Support is unavailable")
class PrintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication(["trama-print-test", "-platform", "offscreen"])

    def setUp(self):
        self.addCleanup(set_language, active_language())
        set_language("en")
        self.folder = Path(self.enterContext(TemporaryDirectory()))

    def printer(self, file):
        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
        printer.setOutputFileName(str(file))
        return printer

    def read_pages(self, file):
        with pdfium.PdfDocument(file) as pdf:
            pages = []
            for page in pdf:
                with closing(page), closing(page.get_textpage()) as text:
                    pages.append(text.get_text_range())
        return pages

    def test_wide_table_paginates_and_selected_pages_are_printed(self):
        from trama_qt.models import FrameModel
        from trama_qt.printing import print_pages, table_sheet

        model = FrameModel(pd.DataFrame({f"Column {col}": [f"Cell{col}_{row}" for row in range(90)] for col in range(9)}))
        sheet = table_sheet("Results <checked>", model)
        output = self.folder / "whole.pdf"
        printer = self.printer(output)
        print_pages(printer, sheet)
        pages = self.read_pages(output)
        self.assertGreater(len(pages), 3)
        self.assertTrue(all("Row" in page for page in pages))
        self.assertIn("Results <checked>", pages[0])
        self.assertIn("Cell8_89", pages[-1])

        subset = self.folder / "range.pdf"
        printer.setOutputFileName(str(subset))
        printer.setPageRanges(QPageRanges.fromString("2"))
        print_pages(printer, sheet)
        self.assertEqual(self.read_pages(subset), [pages[1]])

    def window(self):
        from trama_qt.project import Run
        from trama_qt.window import MainWindow

        window = MainWindow()
        self.addCleanup(self.close_window, window)
        window.error = Mock()
        window._ask_save = lambda: QMessageBox.StandardButton.Discard
        dataset = pd.DataFrame({"Dose": [1, 2], "Signal": [2, 4]})
        info = InfoSheet("Sheet notes", (("Researcher", "A < B"),), "Lorem\nIpsum", table="Assay",
                         note_styles=((0, 5, NOTE_BOLD),))
        window.project.add_tables({"Assay": dataset}, [info])
        figure = Figure(figsize=(4, 3))
        axes = figure.add_subplot()
        axes.plot([1, 2], [2, 4], color="crimson", linewidth=5)
        run = Run("XY series", "Assay", {}, label="Dose response")
        window.project.add_result(run, Result({"Summary": dataset, "Details": pd.DataFrame({"Field": ["Last tab"]})},
                                              figure))
        window.project.put_layout(Layout("Composite page", 1, [run.reference]))
        window.project.dirty = False
        window.refresh()
        return window, info.uid

    def close_window(self, window):
        window.project.dirty = False
        window.close()
        window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_file_actions_and_native_preview_of_current_sheet(self):
        from trama_qt.printing import PrintPreview

        window, info_id = self.window()
        actions = window.actions
        file_actions = window.command_menus["File"].actions()
        for key in ("print", "print_preview", "page_setup", "send_word", "send_powerpoint"):
            self.assertIn(actions[key], file_actions)
        self.assertEqual(actions["print"].shortcut().toString(), "Ctrl+P")
        self.assertEqual(actions["change"].shortcut().toString(), "Ctrl+Shift+P")

        ref = ("info", info_id)
        window.open_sheet(ref)
        output = self.folder / "notes.pdf"
        window.printing._printer = self.printer(output)

        def preview_dialog(dialog):
            dialog.show()
            self.app.processEvents()
            self.assertIsNone(dialog.error)
            self.assertEqual(dialog.preview.pageCount(), 1)
            self.assertIn("Sheet notes", dialog.windowTitle())
            dialog.close()
            return dialog.DialogCode.Rejected

        with patch.object(PrintPreview, "exec", preview_dialog):
            actions["print_preview"].trigger()
        self.assertFalse(output.exists())

        with patch.object(office, "ON_WINDOWS", False), patch.object(QPrintDialog, "exec", return_value=1):
            actions["print"].trigger()
        notes = self.read_pages(output)[0]
        self.assertIn("Researcher · A < B", notes)
        self.assertIn("Ipsum", notes)
        window.error.assert_not_called()
        self.assertEqual(window.selected, ref)
        self.assertFalse(window.project.dirty)

    def test_prints_used_worksheet_and_the_active_result_table(self):
        window, _ = self.window()
        printer = window.printing._printer = self.printer(self.folder / "table.pdf")
        window.open_sheet(("data", "Assay"))
        with patch.object(office, "ON_WINDOWS", False), patch.object(QPrintDialog, "exec", return_value=1):
            window.actions["print"].trigger()
            text = self.read_pages(Path(printer.outputFileName()))
            self.assertEqual(len(text), 1)
            printed = "".join(text[0].split())
            for value in ("Assay", "Dose", "Signal"):
                self.assertIn(value, printed)
            self.assertNotIn("51", printed)  # The worksheet's spare editing rows.

            printer.setOutputFileName(str(self.folder / "result.pdf"))
            window.open_sheet(("result", 0))
            window.result_tabs.setCurrentIndex(1)
            window.actions["print"].trigger()
            printed = "".join(self.read_pages(Path(printer.outputFileName()))[0].split())
            for value in ("Details", "Lasttab"):
                self.assertIn(value, printed)
            self.assertNotIn("Signal", printed)
        window.error.assert_not_called()

    def test_graph_and_layout_print_and_office_share_the_figure_renderer(self):
        from trama_qt.printing import figure_sheet, print_pages

        window, _ = self.window()
        for kind in ("graph", "layout"):
            with self.subTest(kind=kind):
                ref = (kind, 0)
                window.open_sheet(ref)
                sheet = figure_sheet(window.project, ref)
                output = self.folder / f"{kind}.pdf"
                print_pages(self.printer(output), sheet)
                with pdfium.PdfDocument(output) as printed:
                    self.assertEqual(len(printed), 1)
                    with closing(printed[0]) as page, closing(page.render(scale=0.25)) as bmp:
                        image = bmp.to_pil().convert("RGB")
                        colours = image.getcolors(maxcolors=image.width * image.height)
                        self.assertTrue(any(r > 140 and g < 80 and b < 130 for _, (r, g, b) in colours))

                inserted = []

                def send(app, path, title, size):
                    self.assertEqual(app, "PowerPoint")
                    self.assertEqual((title, size), (sheet.title, sheet.size))
                    with Image.open(path) as image:
                        self.assertEqual(max(image.size), 4000)
                        self.assertAlmostEqual(image.info["dpi"][0], 300, places=0)
                    inserted.append(path)

                with patch.object(office, "ON_WINDOWS", True), patch.object(office, "send_picture", side_effect=send):
                    window.update_actions()
                    window.actions["send_powerpoint"].trigger()
                self.assertEqual(len(inserted), 1)
                self.assertFalse(inserted[0].exists())
                self.assertEqual(window.selected, ref)
                self.assertFalse(window.project.dirty)

        window.project.runs[0].calculation_error = "stale"
        with self.assertRaisesRegex(ValueError, tr("reference.stale_export")):
            figure_sheet(window.project, ("graph", 0))
