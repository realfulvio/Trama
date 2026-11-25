"""Timing of File → Update from file… on a large linked file: ``python -m tests.bench_source_link [rows] [columns]``.

Writes a synthetic ``rows × columns`` CSV (default 50 000 × 20: a key ``ID`` and numeric columns), imports it as a
linked worksheet with a regression on it, and times: the import with the link (digests of every row), a preview of
the unchanged file, a preview of a file with 1 % of the rows modified, 1 % removed, 1 % added and the rows in reverse
order, the preview table (at most 1 000 rows are drawn), Apply (one worksheet edit), Undo and Redo, the save of the
project (16 bytes per row in the link), and how long Cancel takes to stop a read. Each preview must stay a few seconds
at most on a normal PC; the numbers are printed, not asserted.
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


def write_csv(path, keys, values):
    lines = ["ID," + ",".join(f"V{index + 1}" for index in range(values.shape[1]))]
    lines += [f"{key}," + ",".join(repr(float(value)) for value in row) for key, row in zip(keys, values)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(rows=50_000, columns=20):
    from PySide6.QtWidgets import QApplication
    from analisi import source_link as engine
    from analisi.text_import import ImportOptions, TextImport, read_text_bytes
    from trama_qt.project import Project, compute
    from trama_qt.source_link import UpdatePreviewDialog

    app = QApplication.instance() or QApplication(["bench-source-link", "-platform", "offscreen"])
    folder = Path(tempfile.mkdtemp(prefix="trama-bench-source-link-"))
    path = folder / "grande.csv"
    random = np.random.default_rng(7)
    keys = np.array([f"K{index:06d}" for index in range(rows)])
    values = random.normal(size=(rows, columns - 1))
    write_csv(path, keys, values)
    results = []

    def timed(label, function):
        start = time.perf_counter()
        value = function()
        results.append((label, time.perf_counter() - start))
        return value

    def import_linked():
        data, content = read_text_bytes(path)
        text = TextImport.parse(content, ".csv", "Automatic")
        options = ImportOptions()
        frame = text.table(options)
        sources = engine.column_sources(text, options, text.plan(options).columns)
        spec = engine.LinkSpec(path, len(data), hashlib.sha256(data).hexdigest(), text.delimiter, options, sources,
                               "ID")
        project = Project()
        title, = project.add_tables({"Grande": frame})
        project.attach_source(title, spec)
        return project, title

    project, title = timed(f"import {rows:,}×{columns} with the link", import_linked)
    run = project.candidate(title, "Linear regression", {"X": "V2", "Y": "V1"})
    project.add_result(run, compute(run, project.tables[title].frame(mask_excluded=True)))

    def plan():
        raw, excluded = project.source_sheet(title)
        return engine.plan_update(project.tables[title].source_link, raw, excluded, path)

    unchanged = timed("preview of the unchanged file", plan)
    assert unchanged.count(engine.UNCHANGED) == rows

    step = 100
    changed_values = values.copy()
    changed_values[::step, 0] += 1.0
    keep = np.ones(rows, dtype=bool)
    keep[step // 2::step] = False
    extra = rows // step
    new_keys = np.concatenate([keys[keep], [f"N{index:06d}" for index in range(extra)]])[::-1]
    new_values = np.concatenate([changed_values[keep], random.normal(size=(extra, columns - 1))])[::-1]
    write_csv(path, new_keys, new_values)
    changed = timed("preview: 1 % modified, removed, added, reversed", plan)
    dialog = timed("preview table (first 1 000 changes drawn)",
                   lambda: UpdatePreviewDialog(None, project, title, changed))
    shown = dialog.table.rowCount()
    dialog.deleteLater()
    timed("Apply (one worksheet edit)", lambda: project.update_from_source(title, changed))
    assert len(project.tables[title].raw) == rows
    timed("Undo", project.undo)
    timed("Redo", lambda: project.undo(redo=True))
    saved = folder / "grande.alab"
    timed("save the project", lambda: project.save(saved))

    stop = threading.Event()
    raw, excluded = project.source_sheet(title)
    link = project.tables[title].source_link
    finished = {}

    def worker():
        try:
            engine.plan_update(link, raw, excluded, path, cancel=stop.is_set)
            finished["outcome"] = "finished before Cancel"
        except engine.UpdateCancelled:
            finished["outcome"] = "cancelled"
        finished["at"] = time.perf_counter()

    thread = threading.Thread(target=worker)
    thread.start()
    time.sleep(0.05)
    pressed = time.perf_counter()
    stop.set()
    thread.join()
    app.processEvents()

    print(f"Source link bench · {rows:,} rows × {columns} columns · file {path.stat().st_size / 1e6:.1f} MB · "
          f"project {saved.stat().st_size / 1e6:.1f} MB")
    for label, seconds in results:
        print(f"  {label}: {seconds:.3f} s")
    print(f"  preview rows drawn: {shown:,} (changes {changed.count(engine.MODIFIED) + changed.count(engine.ADDED):,} "
          f"+ {len(changed.removed):,} removed + {len(changed.moved()):,} moved)")
    print(f"  Cancel during the read: {finished['outcome']} {1000 * (finished['at'] - pressed):.0f} ms after the "
          f"press")
    return 0


if __name__ == "__main__":
    arguments = [int(value) for value in sys.argv[1:3]]
    raise SystemExit(main(*arguments))
