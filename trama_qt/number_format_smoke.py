"""Smoke of Change → Number format… (scenario ``qt-number-format``).

Run alone with ``python -m trama_qt --smoke FOLDER --scenario qt-number-format``. Per language: the real dialog on
the package fixture (Dose and Risposta selected, a highlighted active cell), the window at 1024×768 and 1600×1000,
the format confirmed, Copy of the stored number, Undo in place; two result tabs of one Deming fit with their own
formats. Once per run: open, scroll to the end and format change on 50 000 × 20 cells, counting the cells the
format renders (only the visible ones). Screenshots ``<lang>-number-format-*.png``; ``number-format-timings.txt``.
"""
import time
from unittest import mock

import numpy as np
import pandas as pd
from PySide6.QtCore import QItemSelection, QItemSelectionModel
from PySide6.QtGui import QGuiApplication

SIZES = ((1024, 768), (1600, 1000))
FIXTURE = pd.DataFrame({
    "Categoria": ["Controllo", "Prima", "Seconda", "Terza", "Quarta"],
    "Dose": [0.000125, 1.23456789012345, 12345.6789, 0.5, float("nan")],
    "Risposta": [2.125, -0.0004, -0.0, 1.2345e-14, 950.0],
    "Repliche": [4, 4, 12, 9999, 0],
})


def _expect(smoke, condition, text):
    if not condition:
        smoke.problem(f"number format: {text}")


def _select(view, top, left, bottom, right, current=None):
    model = view.model()
    view.setCurrentIndex(model.index(*(current or (top, left))))
    view.selectionModel().select(QItemSelection(model.index(top, left), model.index(bottom, right)),
                                 QItemSelectionModel.SelectionFlag.ClearAndSelect)


def _confirm(spec, smoke=None, name=None):
    def exec_(dialog):
        dialog.set_mode(spec["mode"])
        if "digits" in spec:
            dialog.digits.setValue(spec["digits"])
        if smoke is not None:
            dialog.show()
            smoke.shot(dialog, name)
        dialog.confirm()
        return dialog.DialogCode.Accepted
    return exec_


def run(smoke, window, *, timings=True):
    from .worksheet_number_format import NumberFormatDialog
    language = smoke.language
    mark = "," if language == "it" else "."
    title, = window.project.add_tables({"celle": FIXTURE.copy()})
    window.project.set_table_background(title, (1, 1, 1, 1), "#ffd966")
    window.show_sheet("data", title)
    data = window.project.tables[title]
    for number, (width, height) in enumerate(SIZES):
        window.resize(width, height)
        smoke.app.processEvents()
        _select(window.sheet, 0, 0, 4, 2, current=(1, 1))
        last = number == len(SIZES) - 1
        spec = {"mode": "fixed", "digits": 3}
        if last:
            with mock.patch.object(NumberFormatDialog, "exec", _confirm(spec, smoke, "number-format-dialog")):
                window.change_number_format()
        else:
            with smoke.dialogs(f"number-format-{width}x{height}"):
                window.change_number_format()
        smoke.app.processEvents()
        smoke.shot(window, f"number-format-{width}x{height}")
    model = window.sheet.model()
    shown = [model.data(model.index(row, 1)) for row in range(4)]
    _expect(smoke, shown == [f"0{mark}000", f"1{mark}235", f"12345{mark}679", f"0{mark}500"],
                 f"Dose shows {shown}")
    _expect(smoke, model.data(model.index(1, 1), 2) == "1.23456789012345", "the editor does not start from the stored "
                                                                         "number")
    _expect(smoke, data.cell_backgrounds.get((1, "Dose")) == "#ffd966", "the highlight was lost")
    _select(window.sheet, 1, 1, 1, 1)
    window.sheet.copy()
    _expect(smoke, QGuiApplication.clipboard().text().strip() in ("1.23456789012345", "1,23456789012345"),
                 "Copy wrote the formatted text")
    sheet = window.sheet
    window.undo()
    smoke.app.processEvents()
    _expect(smoke, window.sheet is sheet and not data.number_formats, "Undo did not remove the format in place")
    window.undo(redo=True)
    smoke.app.processEvents()

    frame = pd.DataFrame({"Dose": [0.5, 1, 2, 4, 8, 16, 32, 64],
                          "Response": [2.1, 3.9, 6.2, 8.1, 9.8, 12.3, 13.1, 13.5]})
    fit, = window.project.add_tables({"groups": frame})  # The table Smoke.calculate reads.
    window.show_sheet("data", fit)
    index = smoke.calculate("Deming regression", {"X": "Dose", "Y": "Response"})
    window.open_sheet(("result", index))
    smoke.wait()
    tabs = window.result_tabs
    names = [tabs.tabText(number) for number in range(tabs.count())]
    for name, column, spec in (("Data", 1, {"mode": "fixed", "digits": 1}),
                               ("Pairs", 2, {"mode": "scientific", "digits": 2})):
        tabs.setCurrentIndex(names.index(name))
        _select(tabs.currentWidget(), 0, column, 7, column)
        with mock.patch.object(NumberFormatDialog, "exec", _confirm(spec)):
            window.change_number_format()
        smoke.app.processEvents()
        smoke.shot(window, f"number-format-result-{name.lower()}")
    run_ = window.project.runs[index]
    stored = window.project.tables[fit].result_number_formats.get(run_.slot, {})
    _expect(smoke, set(stored) == {"Data", "Pairs"} and stored["Data"] != stored["Pairs"],
                 f"result tabs share or lost their formats: {stored}")
    if timings:
        _timings(smoke, window)
    window.project.dirty = False


def _timings(smoke, window):
    from analisi.worksheet_number_format import Renderer
    from .worksheet_number_format import NumberFormatDialog
    big = pd.DataFrame(np.random.default_rng(7).normal(size=(50_000, 20)) * 1000,
                       columns=[f"C{index + 1}" for index in range(20)])
    started = time.perf_counter()
    title, = window.project.add_tables({"big": big})
    window.show_sheet("data", title)
    smoke.app.processEvents()
    window.sheet.viewport().repaint()
    opened = time.perf_counter() - started
    started = time.perf_counter()
    bar = window.sheet.verticalScrollBar()
    bar.setValue(bar.maximum())
    window.sheet.viewport().repaint()
    scrolled = time.perf_counter() - started
    _select(window.sheet, 0, 0, 49_999, 19)
    bar.setValue(bar.maximum() // 2)  # The end shows the empty spare rows; the middle shows numbers.
    smoke.app.processEvents()
    calls = []
    original = Renderer.text

    def counted(self, position, value):
        calls.append(position)
        return original(self, position, value)

    started = time.perf_counter()
    with mock.patch.object(Renderer, "text", counted), \
            mock.patch.object(NumberFormatDialog, "exec", _confirm({"mode": "scientific", "digits": 2})):
        window.change_number_format()
        smoke.app.processEvents()  # The view paints the cells it shows.
    changed = time.perf_counter() - started
    _expect(smoke, len(window.project.tables[title].number_formats) == 20, "the big sheet did not take the format")
    _expect(smoke, 0 < len(calls) <= 20 * 400, f"the format change rendered {len(calls)} cells, not the visible ones")
    lines = [f"window {window.width()}×{window.height()} · {smoke.language}",
             f"open 50000×20: {opened:.3f} s", f"scroll to the end: {scrolled:.3f} s",
             f"format change on 20 columns: {changed:.3f} s ({len(calls)} cells rendered)"]
    (smoke.folder / "number-format-timings.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
