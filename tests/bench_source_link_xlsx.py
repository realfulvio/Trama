"""Timing of a worksheet linked to an .xlsx sheet: ``python -m tests.bench_source_link_xlsx [rows] [columns] [folder]``.

Writes a synthetic workbook (default 50 000 × 10: a key ``ID`` and numeric columns, with a decoy sheet before the
linked one) in ``folder`` (default: a temporary folder; give a network folder to time a shared disk), then times:
reading the sheet, the import with the link, a preview of the unchanged workbook, a preview with 1 % of the rows
modified, 1 % removed, 1 % added and the rows in reverse order, the preview dialog, Apply, Undo and Redo, the save
of the project, and how long Cancel takes to stop a read. It checks that the SHA-256 and the modification time of
the workbook are the same before and after. The numbers are printed, not asserted.
"""
import hashlib
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def write_book(path, keys, values):
    from openpyxl import Workbook
    book = Workbook(write_only=True)
    decoy = book.create_sheet("Riepilogo")
    decoy.append(["ID"] + [f"V{index + 1}" for index in range(values.shape[1])])
    decoy.append(["K000000"] + [0.0] * values.shape[1])
    sheet = book.create_sheet("Misure")
    sheet.append(["ID"] + [f"V{index + 1}" for index in range(values.shape[1])])
    for key, row in zip(keys, values.tolist()):
        sheet.append([key, *row])
    book.save(path)


def fingerprint(path):
    return hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns


def main(rows=50_000, columns=10, folder=None):
    from PySide6.QtWidgets import QApplication
    from analisi import source_link as engine, xlsx_source
    from analisi.xlsx_source import WorkbookOptions
    from trama_qt.project import Project, compute
    from trama_qt.source_link import UpdatePreviewDialog

    app = QApplication.instance() or QApplication(["bench-source-link-xlsx", "-platform", "offscreen"])
    folder = Path(folder) if folder else Path(tempfile.mkdtemp(prefix="trama-bench-xlsx-"))
    path = folder / "grande.xlsx"
    random = np.random.default_rng(7)
    keys = np.array([f"K{index:06d}" for index in range(rows)])
    values = random.normal(size=(rows, columns - 1))
    write_book(path, keys, values)
    results = []

    def timed(label, function):
        start = time.perf_counter()
        value = function()
        results.append((label, time.perf_counter() - start))
        return value

    options = WorkbookOptions("Misure", 1)
    data = path.read_bytes()
    timed("read the sheet (openpyxl, read-only)", lambda: xlsx_source.read_sheet(data, options))

    def import_linked():
        source = engine.read_file(path, text=False)
        table = xlsx_source.read_sheet(source.content, options)
        positions = list(range(table.width))
        sources = engine.header_sources(table.header, positions)
        spec = engine.LinkSpec(path, source.size, source.sha256, "", options, sources, "ID", kind="xlsx")
        project = Project()
        title, = project.add_tables({"Misure": table.table(positions)})
        project.attach_source(title, spec)
        return project, title

    project, title = timed(f"import {rows:,}×{columns} with the link", import_linked)
    run = project.candidate(title, "Linear regression", {"X": "V2", "Y": "V1"})
    project.add_result(run, compute(run, project.tables[title].frame(mask_excluded=True)))

    def plan():
        raw, excluded = project.source_sheet(title)
        return engine.plan_update(project.tables[title].source_link, raw, excluded, path)

    unchanged = timed("preview of the unchanged workbook", plan)
    assert unchanged.count(engine.UNCHANGED) == rows, unchanged.problems

    step = 100
    changed = values.copy()
    changed[::step, 0] += 1.0
    keep = np.ones(rows, dtype=bool)
    keep[1::step] = False
    new_keys = np.concatenate([keys[keep], np.array([f"N{index:06d}" for index in range(rows // step)])])
    new_values = np.concatenate([changed[keep], random.normal(size=(rows // step, columns - 1))])
    write_book(path, new_keys[::-1], new_values[::-1])
    before = fingerprint(path)
    plan_changed = timed("preview: 1 % modified, removed, added, reversed", plan)
    assert not plan_changed.problems, plan_changed.problems
    dialog = timed("preview dialog (at most 1 000 rows drawn)",
                   lambda: UpdatePreviewDialog(None, project, title, plan_changed))
    dialog.deleteLater()
    timed("Apply (one worksheet edit)", lambda: project.update_from_source(title, plan_changed))
    timed("Undo", project.undo)
    timed("Redo", lambda: project.undo(redo=True))
    timed("save the project", lambda: project.save(folder / "studio.alab"))
    after = fingerprint(path)

    control = threading.Event()

    def cancel_later():
        time.sleep(0.2)
        control.set()

    threading.Thread(target=cancel_later).start()
    start = time.perf_counter()
    try:
        raw, excluded = project.source_sheet(title)
        engine.plan_update(project.tables[title].source_link, raw, excluded, path, cancel=control.is_set)
        stopped = "not stopped (finished first)"
    except engine.UpdateCancelled:
        stopped = f"stopped {time.perf_counter() - start - 0.2:.3f} s after Cancel"
    app.processEvents()

    print(f"Workbook {path} · {path.stat().st_size:,} bytes · {rows:,} rows × {columns} columns")
    for label, seconds in results:
        print(f"{label:<52} {seconds:8.3f} s")
    print(f"{'Cancel while reading':<52} {stopped}")
    print(f"{'workbook digest and time unchanged':<52} {before == after}")
    return 0 if before == after else 1


if __name__ == "__main__":
    arguments = sys.argv[1:]
    sys.exit(main(*(int(value) for value in arguments[:2]), *arguments[2:3]))
