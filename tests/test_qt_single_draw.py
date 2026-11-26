"""A graph sheet is rendered once when it opens, at the size of its canvas.

A full render costs 0.05 s for an ordinary graph and more than a second for a million points. Opening a sheet
used to render twice: once before the canvas had been laid out (thrown away) and once when it was shown.
"""
from pathlib import Path
import shutil
import tempfile
import time
import unittest

try:
    from PySide6.QtCore import QEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
except ImportError:  # PySide6 missing, or libEGL/libGL missing on a headless machine.
    QApplication = None

import numpy as np

FIXTURE = Path(__file__).resolve().parent / "data" / "qt_canvas" / "grafico.alab"


def _app():
    app = QApplication.instance() or QApplication(["trama-qt-single-draw-tests", "-platform", "offscreen"])
    from trama_qt import theme
    theme.load_fonts()
    theme.apply(app)
    return app


@unittest.skipIf(QApplication is None, "PySide6 is not available")
class SingleDrawTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = _app()

    def setUp(self):
        from analisi.i18n import set_language
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        from trama_qt.window import MainWindow

        set_language("en")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / "grafico.alab"
        shutil.copy(FIXTURE, path)
        self.window = MainWindow()
        self.window.error = lambda error: self.fail(str(error))
        self.window.resize(1000, 700)
        self.window.show()
        self.addCleanup(self._close)
        self.window.open_path(path)
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.window.project.dirty = False
        # Count every full render from here on, with the size of the canvas that asked for it.
        self.renders = []
        real = FigureCanvasAgg.draw

        def counted(canvas, *positional, **named):
            if canvas in self.window.page.canvases:  # not a preview or an export drawn on a canvas of its own
                self.renders.append((canvas.width(), canvas.height()))
            return real(canvas, *positional, **named)

        FigureCanvasAgg.draw = counted
        self.addCleanup(setattr, FigureCanvasAgg, "draw", real)

    def _close(self):
        for session in self.window.sessions:
            session.project.dirty = False
        self.window.close()
        self.window.deleteLater()
        self.app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        self.app.processEvents()

    def wait(self, timeout=60):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            QTest.qWait(30)
            if self.window.job is None:
                QTest.qWait(30)
                if self.window.job is None:
                    return
        self.fail("calculation still running")

    @property
    def canvas(self):
        canvas, = self.window.page.canvases
        return canvas

    def assert_shown(self):
        """The canvas holds a rendered picture of its own size, with more than the background on it."""
        canvas = self.canvas
        pixels = np.asarray(canvas.buffer_rgba())
        ratio = canvas.device_pixel_ratio
        self.assertEqual(pixels.shape[:2], (round(canvas.height() * ratio), round(canvas.width() * ratio)))
        self.assertGreater(len(np.unique(pixels.reshape(-1, 4), axis=0)), 2)

    def test_opening_a_graph_sheet_renders_it_once(self):
        self.window.open_sheet(("data", next(iter(self.window.project.tables))))
        self.wait()
        self.renders.clear()
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.assertEqual(self.renders, [(self.canvas.width(), self.canvas.height())])
        self.assert_shown()

    def test_coming_back_from_the_result_sheet_renders_it_once(self):
        self.window.open_sheet(("result", 0))
        self.wait()
        self.renders.clear()
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.assertEqual(len(self.renders), 1)
        self.assert_shown()

    def test_a_sheet_opened_with_the_inspector_renders_once(self):
        self.window.toggle_inspector()  # the inspector asks for a redraw while the page is being built
        self.wait()
        self.assertIsNotNone(self.window.inspector)
        self.assert_shown()
        self.window.open_sheet(("result", 0))
        self.wait()
        self.renders.clear()
        self.window.open_sheet(("graph", 0))
        self.wait()
        self.assertIsNotNone(self.window.inspector)
        self.assertEqual(self.renders, [(self.canvas.width(), self.canvas.height())])
        self.assert_shown()

    def test_a_request_after_the_page_is_shown_still_renders(self):
        self.renders.clear()
        self.canvas.draw_idle()
        self.wait()
        self.assertEqual(len(self.renders), 1)

    def test_a_resize_still_renders(self):
        self.renders.clear()
        self.window.resize(900, 640)
        self.wait()
        self.assertEqual(self.renders, [(self.canvas.width(), self.canvas.height())])
        self.assert_shown()


if __name__ == "__main__":
    unittest.main()
