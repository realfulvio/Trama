"""Timing of the Text group on a large sheet: ``python -m tests.bench_text_style [rows] [columns]``.

Selects every cell of a ``rows × columns`` worksheet (default 50 000 × 20), reads the Text state, applies bold, a
colour and a size, undoes and redoes, and counts how many times the worksheet or an analysis was recalculated
(the answer must be zero). The same steps with the cell background colour are timed as a reference for the
per-cell approach: the text style stores a few ranges per column, so its cost follows the ranges, not the cells.
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from PySide6.QtCore import QItemSelection, QItemSelectionModel  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


def main(rows=50_000, columns=20):
    app = QApplication.instance() or QApplication(["bench", "-platform", "offscreen"])
    from analisi import data as data_module
    from trama_qt import theme
    from trama_qt.window import MainWindow
    theme.load_fonts()
    theme.apply(app)
    window = MainWindow()
    window.project.dirty = False
    window.resize(1280, 800)
    window.show()
    random = np.random.default_rng(1)
    frame = pd.DataFrame({f"V{index + 1}": random.normal(size=rows) for index in range(columns)})
    title, = window.project.add_tables({"Grande": frame})
    window.show_sheet("data", title)
    app.processEvents()
    view, model = window.sheet, window.sheet.model()

    frames = []
    original = data_module.Dataset.frame

    def counting(self, *args, **kwargs):
        frames.append(1)
        return original(self, *args, **kwargs)
    data_module.Dataset.frame = counting
    reloads = []
    original_reload = type(model).reload
    type(model).reload = lambda self, *args, **kwargs: (reloads.append(1), original_reload(self, *args, **kwargs))[1]

    def timed(label, function):
        start = time.perf_counter()
        function()
        app.processEvents()
        elapsed = (time.perf_counter() - start) * 1000
        print(f"{label:<46}{elapsed:9.1f} ms")
        return elapsed

    def select_all():
        view.setCurrentIndex(model.index(0, 0))
        view.selectionModel().select(QItemSelection(model.index(0, 0), model.index(rows - 1, columns - 1)),
                                     QItemSelectionModel.SelectionFlag.ClearAndSelect)

    print(f"worksheet {rows:,} rows × {columns} columns = {rows * columns:,} cells")
    results = {}
    results["select"] = timed("select all (selection change + Text state)", select_all)
    frames.clear(), reloads.clear()
    results["state"] = timed("read inherited / uniform / mixed state", lambda: window.text_format.states())
    results["bold"] = timed("apply bold to the whole selection", lambda: window.text_format.apply({"bold": True}))
    results["color"] = timed("apply colour + size on top", lambda: window.text_format.apply({"color": "#aa0000", "size": 12}))
    results["undo"] = timed("undo", window.undo)
    results["redo"] = timed("redo", lambda: window.undo(redo=True))
    results["restore"] = timed("restore text", lambda: window.text_format.apply(None, restore=True))
    results["partial"] = timed("apply to half the rows of two columns", lambda: (
        view.setCurrentIndex(model.index(0, 2)),
        view.selectionModel().select(QItemSelection(model.index(rows // 4, 2), model.index(3 * rows // 4, 3)),
                                     QItemSelectionModel.SelectionFlag.ClearAndSelect),
        window.text_format.apply({"italic": True})))
    dataset = window.project.tables[title]
    print(f"runs stored: {dataset.text_styles.run_count()}; worksheet recalculations: {len(frames)}; "
          f"model reloads: {len(reloads)}")

    # Reference: the per-cell background colour on the same selection.
    window.undo()
    window.undo()
    select_all()
    start = time.perf_counter()
    window.project.set_table_background(title, (0, 0, rows - 1, columns - 1), "#ffd966")
    reference = (time.perf_counter() - start) * 1000
    print(f"{'reference: background colour on all cells':<46}{reference:9.1f} ms "
          f"({len(dataset.cell_backgrounds):,} entries)")
    data_module.Dataset.frame = original
    type(model).reload = original_reload
    window.project.dirty = False
    window.close()
    return results, len(frames), len(reloads)


if __name__ == "__main__":
    arguments = [int(value) for value in sys.argv[1:3]]
    main(*arguments)
