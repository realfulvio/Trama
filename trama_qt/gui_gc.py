"""Keep cyclic collection of GUI-owned PySide wrappers on their Qt thread."""
import gc
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from shiboken6 import isValid


class _GuiCollector(QTimer):
    def __init__(self, application):
        super().__init__(application)
        self.setInterval(1000)
        self.timeout.connect(self.collect)
        self.owners = set()
        self.young = 0
        self.middle = 0

    def collect(self):
        # Ordinary reference counting remains active. Only cycles need a sweep.
        if not gc.get_count()[0]:
            return
        _, middle_threshold, old_threshold = gc.get_threshold()
        if self.middle >= max(1, old_threshold):
            gc.collect(2)
            self.young = self.middle = 0
        elif self.young >= max(1, middle_threshold):
            gc.collect(1)
            self.young = 0
            self.middle += 1
        else:
            gc.collect(0)
            self.young += 1

    def release(self, token, *_):
        if token not in self.owners:
            return
        self.owners.remove(token)
        if not self.owners:
            gc.enable()
            if isValid(self):
                self.stop()


def attach(window):
    """The first window takes over automatic GC, the last restores the prior mode."""
    app = QApplication.instance()
    collector = getattr(app, "_trama_gc", None)
    if collector is None:
        collector = app._trama_gc = _GuiCollector(app)
    if not collector.owners:
        if not gc.isenabled():
            return None
        gc.disable()
        collector.start()
    token = object()
    collector.owners.add(token)
    release = partial(collector.release, token)
    window.destroyed.connect(release)
    return release
