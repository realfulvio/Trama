"""Timing of linked tables on a large sheet: ``python -m tests.bench_linked_tables [rows] [columns]``.

Builds a ``rows × columns`` worksheet (default 50 000 × 20), puts a 12-table graph on a regression of it and
times: the dialog's preview of the source (the first 200 × 40 cells), the record of a 60 × 10 range, the refusal of
a whole-column range (it must fail before any cell is read), an edit that moves the linked cells, an edit that does
not (nothing is redrawn), and the export of the page. It also counts the artists: one container per table and a
bounded number of children, never one per cell of the sheet.
"""
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main(rows=50_000, columns=20):
    from analisi import linked_tables as lt
    from analisi.presentation import Layout
    from trama_qt.project import Project, compute

    random = np.random.default_rng(1)
    frame = pd.DataFrame({f"V{index + 1}": random.normal(size=rows) for index in range(columns)})
    frame["X"] = np.arange(rows, dtype=float)
    project = Project()
    title, = project.add_tables({"Grande": frame})
    run = project.candidate(title, "Linear regression", {"X": "X", "Y": "V1"})
    index, _ = project.add_result(run, compute(run, project.tables[title].frame(mask_excluded=True)))
    run = project.runs[index]
    project.put_layout(Layout("Pagina", 1, [(title, index)]))

    def timed(label, function):
        start = time.perf_counter()
        value = function()
        print(f"{label:<58}{(time.perf_counter() - start) * 1000:9.1f} ms")
        return value

    sheet = next(c for c in project.table_source_choices() if c["kind"] == "sheet")
    timed("preview of the source (200 × 40 cells)", lambda: project.table_source_preview(sheet, 200, 40))

    def whole_column():
        try:
            project.table_record(sheet, (0, 0, rows - 1, 0))
        except ValueError as error:
            return error

    refused = timed(f"refuse a whole column ({rows} rows) before reading it", whole_column)
    assert isinstance(refused, ValueError), "a whole column was accepted"
    records = [timed(f"record of range {number + 1} (60 × 10 cells, linked)",
                     lambda number=number: project.table_record(sheet, (number, 0, number + 59, 9), mode="linked",
                                                                position=((number % 4) * .24, (number // 4) * .3),
                                                                size=6))
               for number in range(lt.MAX_TABLES)]
    style = dict(run.style or {})
    style[lt.TABLES] = records
    timed("apply 12 tables to the graph (draw + resolve)", lambda: project.apply_format(run, style))
    figure = run.result.figure
    artists = [a for a in figure.artists if isinstance(a, lt.LinkedTableArtist)]
    children = sum(len(a._children) for a in artists)
    print(f"artists: {len(artists)} tables, {children} children in all ({children / max(len(artists), 1):.0f} each; "
          f"the sheet has {rows * (columns + 1)} cells)")
    bound = 3 + lt.MAX_CELLS + lt.MAX_ROWS + lt.MAX_COLUMNS + 2 * 70   # cells, titles, fills, rules
    assert len(artists) == lt.MAX_TABLES and children <= lt.MAX_TABLES * bound, "too many artists"
    timed("edit a cell inside the tables (resolve + redraw)", lambda: project.edit_cell(title, 5, 1, "9.5"))
    timed("edit a cell outside the tables (nothing redrawn)", lambda: project.edit_cell(title, rows - 1, 3, "1.5"))
    timed("update_linked_tables with nothing changed", project.update_linked_tables)
    out = Path(tempfile.mkdtemp(prefix="trama-table-bench-"))
    project.put_layout(Layout("Pagina", 1, [(title, index)], tables=records[:4]), 0)
    layout = project.layouts[0]
    timed("export the layout page as PDF", lambda: project.export_layout(layout, out / "p.pdf", {"format": "pdf"}))
    timed("export the layout page as SVG", lambda: project.export_layout(layout, out / "p.svg", {"format": "svg"}))
    timed("export the layout page as PNG (150 dpi)",
          lambda: project.export_layout(layout, out / "p.png", {"format": "png", "dpi": 150}))


if __name__ == "__main__":
    main(*(int(value) for value in sys.argv[1:3]))
