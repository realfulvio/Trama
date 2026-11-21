"""Exercise a real Qt window and its recalculation worker in a fresh interpreter."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest


def exercise():
    import gc
    import threading
    import time
    import weakref

    from PySide6.QtCore import QEvent, QObject
    from PySide6.QtWidgets import QApplication
    from trama_qt.window import MainWindow

    app = QApplication([])
    gc.enable()
    first = MainWindow()
    second = MainWindow()
    first.close()
    assert not gc.isenabled(), "Closing one of two windows released the collector"
    gc.collect()
    finalized = []
    obj = QObject()
    obj.cycle = obj
    ref = weakref.ref(obj, lambda _: finalized.append(threading.get_ident()))
    del obj

    def allocate():
        return [dict() for _ in range(5 * gc.get_threshold()[0] + 1000)]

    batch = second.worker.submit(allocate).result(timeout=10)
    assert not finalized, "The worker finalized a GUI-owned object"
    deadline = time.monotonic() + 5
    while not finalized and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert batch and ref() is None and finalized == [threading.get_ident()]
    second.close()
    assert gc.isenabled(), "Last window did not restore automatic collection"

    deleted = MainWindow()
    deleted.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert gc.isenabled(), "Deleting a window without a close event must release its registration"
    gc.disable()
    third = MainWindow()
    third.close()
    assert not gc.isenabled(), "The caller had already disabled automatic collection"


class GuiCollectionTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("PySide6"), "PySide6 unavailable")
    def test_worker_cannot_collect_gui_objects_and_windows_restore_the_prior_mode(self):
        result = subprocess.run([sys.executable, "-m", "tests.test_qt_gui_gc", "--probe"],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                env={**os.environ, "QT_QPA_PLATFORM": "offscreen"}, timeout=45)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))


if __name__ == "__main__" and "--probe" in sys.argv:
    exercise()
