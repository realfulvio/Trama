"""Desktop acceptance of linked coefficients (Fit custom equation and Global fit custom equation), with screenshots.

    python -m trama_qt.coefficient_links_smoke OUT [--lang en|it] [--theme light|dark] [--size 1024x768]

Run it on a real screen or on a virtual one (``xvfb-run -a -s '-screen 0 1920x1080x24' ...``); for 150 % use
``QT_SCALE_FACTOR=1.5`` on a screen of 1536×1152 pixels, which Qt sees as 1024×768 logical pixels (an emulated
scale, not a native DPI setting: the report says which one was used).

On the real main window it opens ``tests/data/coefficient_links/curve.csv``, types C = 2*A + 1 into the
coefficient table of Fit custom equation (Group = serie) with real key presses, reads the resolved formula before
Run, walks the table with Tab, presses Enter in a cell (the dialog must not close on a half-typed value), shows a
cycle and Esc, then runs the fit on the Qt worker and checks the series Uno against ``atteso.json``. Then the same
for Global fit custom equation (A shared, B local, C linked shared): a per-series limit, an invalid shared link to a
local source, the run, save, reopen and recalculation. F1 must open the keyboard shortcuts. ``OUT`` receives the
PNG screenshots, ``collegati-<lang>.alab``, ``<tag>-report.txt`` and ``<tag>-status.txt`` (PASS/FAIL).
"""
import argparse
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data" / "coefficient_links"
EXPECTED = json.loads((DATA / "atteso.json").read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="en")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--size", default="1024x768")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefs = Path(tempfile.mkdtemp(prefix="trama-links-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    from PySide6 import __version__ as pyside
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog
    import pandas as pd

    from analisi.i18n import set_language
    set_language(args.lang)
    app = QApplication.instance() or QApplication(["trama-links-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.analysis_dialog import AnalysisDialog
    from trama_qt.window import MainWindow

    width, height = (int(v) for v in args.size.lower().split("x"))
    tag = f"{args.lang}-{args.theme}-{width}x{height}"
    problems, shots = [], []

    def check(condition, text):
        if not condition:
            problems.append(text)

    def settle():
        for _ in range(6):
            app.processEvents()
            time.sleep(0.02)

    def shot(widget, name):
        settle()
        frame, available = widget.frameGeometry(), (widget.screen() or app.primaryScreen()).availableGeometry()
        check(frame.width() <= available.width() and frame.height() <= available.height(),
              f"{name}: {frame.width()}×{frame.height()} does not fit {available.width()}×{available.height()}")
        path = out / f"{tag}-{len(shots) + 1:02d}-{name}.png"
        check(widget.grab().save(str(path)), f"{name}: screenshot not written")
        shots.append(path.name)

    window = MainWindow()
    errors = []
    window.error = lambda error: errors.append(str(error))
    available = (window.screen() or app.primaryScreen()).availableGeometry()
    window.resize(min(width, available.width()), min(height, available.height()))
    window.show()
    settle()

    def wait():
        end = time.monotonic() + 120
        while window.job is not None and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        settle()

    def type_cell(table, row, column, text):
        """Real keys: select the cell, open the editor with F2, type, commit with Return."""
        table.setFocus()
        table.setCurrentCell(row, column)
        QTest.keyClick(table, Qt.Key.Key_F2)
        editor = app.focusWidget()
        if editor is not None:
            QTest.keySequence(editor, "Ctrl+A")
        QTest.keyClicks(editor or table, text)
        QTest.keyClick(editor or table, Qt.Key.Key_Return)
        settle()

    def close_modal_later():
        def close():
            modal = app.activeModalWidget()
            if isinstance(modal, QDialog):
                shot(modal, "f1-shortcuts")
                modal.reject()
        QTimer.singleShot(400, close)

    def close(value, expected, what, tol=1e-6):
        check(value is not None and math.isfinite(value) and math.isclose(value, expected, rel_tol=tol, abs_tol=tol),
              f"{what}: {value} instead of {expected}")

    try:
        source = out / "curve.csv"
        shutil.copy(DATA / "curve.csv", source)
        window.open_path(source)
        wait()
        title = next(iter(window.project.tables))
        frame = window.project.tables[title].frame(mask_excluded=True)

        # F1: the keyboard shortcuts.
        window.activateWindow()
        settle()
        close_modal_later()
        QTest.keyClick(window.focusWidget() or window, Qt.Key.Key_F1)
        settle()
        check(any(name.endswith("f1-shortcuts.png") for name in shots), "F1 did not open the keyboard shortcuts")

        # -- Fit custom equation -------------------------------------------------------------------------
        recipe = {"X": "x", "Y": "y", "Group": "serie", "Equation": "B + A*X + C*X^2",
                  "Parameters": [{"name": "A", "start": 1.0, "lower": None, "upper": None, "fixed": False},
                                 {"name": "B", "start": 1.0, "lower": None, "upper": None, "fixed": False}]}
        dialog = AnalysisDialog(window, frame, current=("Fit custom equation", recipe), only="Fit custom equation")
        dialog.show()
        dialog.activateWindow()
        settle()
        editor = dialog.controls["Parameters"][1]
        dialog.focus_field("Parameters")
        type_cell(editor.table, 2, editor.NAME, "C")
        editor.set_link(2, "A", "2", "1")
        settle()
        summary, problem = editor.preview.texts()
        check("C = 2*A + 1" in summary and problem == "", f"single: preview {summary!r} {problem!r}")
        check(editor.cell(2, editor.START) == "3", f"single: linked start {editor.cell(2, editor.START)!r}")
        shot(dialog, "single-linked")
        # Tab walks the row; Return in a cell commits the cell and leaves the dialog open.
        editor.table.setFocus()
        editor.table.setCurrentCell(2, editor.FACTOR)
        QTest.keyClick(editor.table, Qt.Key.Key_Tab)
        check(editor.table.currentColumn() == editor.OFFSET, f"single: Tab went to column {editor.table.currentColumn()}")
        type_cell(editor.table, 2, editor.FACTOR, "2")
        check(dialog.isVisible() and dialog.result is None, "single: Return in a cell closed the dialog")
        # A cycle is shown before Run and keeps the dialog open.
        editor.set_link(0, "C", "0.5", "-0.5")
        settle()
        check("A → C → A" in editor.preview.texts()[1], f"single: cycle not shown {editor.preview.texts()}")
        dialog.accept()
        settle()
        check(dialog.result is None and dialog.banner.isVisible(), "single: a cycle was accepted")
        shot(dialog, "single-cycle")
        editor.set_link(0, "")
        settle()
        dialog.accept()
        settle()
        check(dialog.result is not None, f"single: not accepted: {dialog.banner.text()}")
        method, options = dialog.result
        dialog.deleteLater()
        window.calculate_candidate(window.project.candidate(title, method, options), frame, None)
        wait()
        run = window.project.runs[-1]
        check(run.result is not None and not run.calculation_error, f"single: not calculated {run.calculation_error}")
        if run.result is not None:
            table = run.result.tables["Parameters: Uno"]
            close(float(table.loc["C", "Estimate"]), EXPECTED["singolo"]["C"], "single C")
            close(float(table.loc["C", "SE"]), EXPECTED["singolo"]["se_C"], "single SE(C)", 1e-5)
            check(table.loc["C", "Status"] == "Linked", "single: C not Linked")
        window.open_sheet(("result", len(window.project.runs) - 1))
        wait()
        shot(window, "single-result")

        # -- Global fit custom equation ------------------------------------------------------------------
        method = "Global fit custom equation"
        recipe = {"X": "x", "Y": "y", "Group": "serie", "Equation": "B + A*X + C*X^2", "Series constraints": [],
                  "Parameters": [{"name": "A", "start": 1.0, "lower": None, "upper": None, "fixed": False,
                                  "shared": True},
                                 {"name": "B", "start": 1.0, "lower": None, "upper": None, "fixed": False,
                                  "shared": False},
                                 {"name": "C", "start": 3.0, "lower": None, "upper": None, "fixed": False,
                                  "shared": True}]}
        dialog = AnalysisDialog(window, frame, current=(method, recipe), only=method)
        dialog.show()
        dialog.activateWindow()
        settle()
        coefficients = dialog.controls["Parameters"][1]
        series = dialog.controls["Series constraints"][1]
        coefficients.set_cell(2, coefficients.SOURCE, "B")
        settle()
        dialog.accept()
        settle()
        check(dialog.result is None and "Uno" in dialog.banner.text(), f"global: shared→local {dialog.banner.text()!r}")
        shot(dialog, "global-invalid")
        coefficients.set_cell(2, coefficients.SOURCE, "A")
        coefficients.set_cell(2, coefficients.FACTOR, "2")
        coefficients.set_cell(2, coefficients.OFFSET, "1")
        settle()
        check("C = 2*A + 1" in coefficients.preview.texts()[0], f"global: preview {coefficients.preview.texts()}")
        check(not dialog.banner.isVisible(), "global: the corrected link still shows its old error")
        for index in range(dialog.tabs.count()):
            dialog.tabs.setCurrentIndex(index)
            shot(dialog, f"global-tab-{index + 1}")
        series.set_override("Uno", "C", "upper", "100")
        dialog.focus_field("Series constraints")
        shot(dialog, "global-series")
        dialog.accept()
        settle()
        check(dialog.result is not None, f"global: not accepted: {dialog.banner.text()}")
        method, options = dialog.result
        dialog.deleteLater()
        window.calculate_candidate(window.project.candidate(title, method, options), frame, None)
        wait()
        run = window.project.runs[-1]
        check(run.result is not None and not run.calculation_error, f"global: not calculated {run.calculation_error}")

        def verify(result, what):
            table = result.tables["Parameters"]
            row = table[table["Parameter"] == "C"].iloc[0]
            close(float(row["Estimate"]), EXPECTED["globale"]["C"], f"{what} C")
            close(float(row["SE"]), EXPECTED["globale"]["se_C"], f"{what} SE(C)", 1e-5)
            close(float(row["CI low"]), EXPECTED["globale"]["ci_C"][0], f"{what} CI(C) low", 1e-5)
            check(result.tables["Global fit"].loc["DF residual", "Value"] == 7, f"{what}: df")

        if run.result is not None:
            verify(run.result, "global")
        window.open_sheet(("result", len(window.project.runs) - 1))
        wait()
        shot(window, "global-result")
        window.open_sheet(("graph", len(window.project.runs) - 1))
        wait()
        shot(window, "global-graph")

        # Save, reopen, recalculate: the links come back in the editors.
        saved = out / f"collegati-{args.lang}.alab"
        confirmed = deepcopy(window.project.runs[-1].options)
        window.project.save(saved)
        window.open_path(saved)
        wait()
        reopened = [i for i, item in enumerate(window.project.runs) if item.method == method]
        check(bool(reopened) and window.project.runs[reopened[-1]].options == confirmed, "global: reopened recipe")
        if reopened:
            index = reopened[-1]
            window.open_sheet(("result", index))
            wait()
            result = window.project.runs[index].result
            check(result is not None, "global: not recalculated after reopening")
            if result is not None:
                verify(result, "reopened")
            dialog = AnalysisDialog(window, frame, current=(method, window.project.runs[index].options), only=method)
            dialog.show()
            settle()
            check(dialog.controls["Parameters"][1].rows()[2]["scope"] == "Linked shared", "reopened scope")
            shot(dialog, "global-reopened")
            QTest.keyClick(dialog, Qt.Key.Key_Escape)
            settle()
            check(not dialog.isVisible(), "Esc did not close the dialog")
            dialog.deleteLater()
        check(errors == [], f"errors shown: {errors}")
    except Exception:  # noqa: BLE001 - the report says what broke.
        problems.append("stopped:\n" + traceback.format_exc())
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()

    screen = app.primaryScreen()
    geometry = screen.availableGeometry()
    lines = [f"Linked coefficients smoke · {tag} · PySide6 {pyside} · platform {app.platformName()} · {sys.platform}",
             f"Screen {screen.name()}: available {geometry.width()}×{geometry.height()}, device pixel ratio "
             f"{screen.devicePixelRatio()}, logical DPI {screen.logicalDotsPerInch()}"
             + (f" (QT_SCALE_FACTOR={os.environ['QT_SCALE_FACTOR']}; emulated scale)"
                if "QT_SCALE_FACTOR" in os.environ else " (system scale)"),
             f"Window {window.width()}×{window.height()}", f"Screenshots: {len(shots)}", ""] + (
        problems or ["No problems found."])
    (out / f"{tag}-report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = "FAIL" if problems else "PASS"
    (out / f"{tag}-status.txt").write_text(status + "\n", encoding="utf-8")
    print(f"Linked coefficients smoke {tag}: {status} ({out})")
    for problem in problems:
        print("  -", problem)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
