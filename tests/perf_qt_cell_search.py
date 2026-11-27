"""Find/Replace in Cells on a 50 000 × 20 worksheet: scan, preview, apply and Undo times.

Run: QT_QPA_PLATFORM=offscreen python tests/perf_qt_cell_search.py
1 000 text cells contain «Dose» and are replaced; the search «1» also finds numbers (more than 1 000 matches).
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QApplication, QDialog
from unittest.mock import patch

from analisi.i18n import set_language
from trama_qt import cell_search
from trama_qt.window import MainWindow

ROWS, COLUMNS = 50_000, 20


def table():
    rng = np.random.default_rng(7)
    data = {}
    for column in range(COLUMNS):
        if column % 2:
            data[f"T{column}"] = pd.array([f"campione {row % 997}" for row in range(ROWS)], dtype="string")
        else:
            data[f"N{column}"] = rng.normal(size=ROWS).round(6)
    frame = pd.DataFrame(data)
    rows = rng.choice(ROWS, size=1_000, replace=False)
    for position, row in enumerate(rows):  # 1 000 text cells to replace, spread over the sheet.
        frame.iat[int(row), 1 + 2 * (position % (COLUMNS // 2))] = f"Dose {position}"
    return frame


def main():
    set_language("en")
    app = QApplication.instance() or QApplication(["perf-cell-search"])
    window = MainWindow()
    window.resize(1024, 768)
    window.show()
    window.error = lambda error: print("ERROR", error)
    title = window.project.add_tables({"Grande": table()})[0]
    window.refresh()
    window.open_sheet(("data", title))
    app.processEvents()
    window.open_cell_search(replace=True)
    panel = window.cell_search
    panel.query.setText("dose")

    started = time.perf_counter()
    panel.find()
    ticks = 0
    longest = 0.0
    while panel.scan is not None:
        tick = time.perf_counter()
        panel._scan_step()
        longest = max(longest, time.perf_counter() - tick)
        ticks += 1
        app.processEvents()
    scan = time.perf_counter() - started
    print(f"scan «dose» {ROWS}×{COLUMNS}: {scan:.2f} s in {ticks} steps, longest step {longest * 1000:.0f} ms, "
          f"{len(panel.matches)} matches · {panel.position.text()!r}")

    panel.query.setText("1")  # Many matches, numbers included: count only.
    started = time.perf_counter()
    panel.find()
    panel.run_scan_now()
    print(f"scan «1» (numbers too): {time.perf_counter() - started:.2f} s, {len(panel.matches)} matches")

    panel.query.setText("dose")
    panel.replacement.setText("serie")
    timings = {}

    def accept(dialog):
        timings["preview"] = time.perf_counter() - timings.pop("start")
        timings["changes"] = len(dialog.plan.changes)
        timings["listed"] = dialog.table.rowCount()
        timings["apply_start"] = time.perf_counter()
        return QDialog.DialogCode.Accepted

    with patch.object(cell_search.ReplacePreviewDialog, "exec", accept):
        timings["start"] = time.perf_counter()
        panel.replace_all()
        panel.run_scan_now()
    apply = time.perf_counter() - timings["apply_start"]
    print(f"scan + preview: {timings['preview']:.2f} s ({timings['changes']} changes, {timings['listed']} listed); "
          f"apply: {apply:.2f} s")
    raw = window.project.tables[title].raw
    replaced = int(raw.select_dtypes(exclude="number").apply(lambda c: c.str.startswith("serie").sum()).sum())
    started = time.perf_counter()
    window.undo()
    undo = time.perf_counter() - started
    raw = window.project.tables[title].raw
    back = int(raw.select_dtypes(exclude="number").apply(lambda c: c.str.startswith("Dose").sum()).sum())
    print(f"replaced cells: {replaced}; undo: {undo:.2f} s, «Dose» cells after undo: {back}")
    window.project.dirty = False
    panel.close()
    window.close()


if __name__ == "__main__":
    main()
