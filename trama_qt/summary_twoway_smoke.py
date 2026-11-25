"""Two-way ANOVA from cell summaries in the desktop smoke.

``python -m trama_qt.summary_twoway_smoke FOLDER [--languages en,it] [--themes light,dark]`` opens the
grouped fixture, refuses a column group that has no N, then runs the balanced grid. It saves and reopens
the project, edits one mean, exports the ANOVA sheet, and checks Undo, Redo and a locked sheet. A second
step maps the long CSV without reshaping it.

Screenshots use the language and theme prefix of ``Smoke``. The report records the real device pixel ratio.
"""
from contextlib import contextmanager
import math
from pathlib import Path
import os
import platform
import shutil
import sys
import time

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from analisi.summary_twoway import (
    ANOVA_SHEET, COLUMN_FACTOR, COLUMN_NAME, DISPERSION, DISPERSION_TYPE, INPUT, MEAN, METHOD, RESIDUAL,
    ROW_FACTOR, ROW_NAME, ROWS, SAMPLE_SIZE, SD, SUBCOLUMNS, SUMMARY_SHEET, VARIABLES,
)

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "data" / "summary-twoway"
TITLE = "Bilanciato"
EXPECTED = {"A": 48.0, "B": 108.0, "A:B": 12.0}
EDITED = {"A": 75.0, "B": 147.0, "A:B": 27.0}


def _project_copy(folder):
    source = FIXTURE / "anova-riassunti.alab"
    path = folder / "anova-riassunti.alab"
    shutil.copyfile(source, path)
    return path


@contextmanager
def _driven(smoke, steps):
    """Analysis dialogs run the queued steps instead of waiting for a click."""
    from unittest import mock
    from .analysis_dialog import AnalysisDialog
    app = QApplication.instance()
    queue = list(steps)

    def run(dialog):
        dialog.show()
        app.processEvents()
        if not queue:
            smoke.problem(f"summary twoway: unexpected dialog: {dialog.heading.text()}")
            dialog.reject()
            return QDialog.DialogCode.Rejected
        accepted = queue.pop(0)(dialog)
        return QDialog.DialogCode.Accepted if accepted and dialog.result else QDialog.DialogCode.Rejected

    with mock.patch.object(AnalysisDialog, "exec", run):
        yield
    if queue:
        smoke.problem("summary twoway: a dialog step did not run")


def _choose(smoke, dialog, label, value):
    combo = dialog.controls[label][1]
    position = combo.findData(value)
    if position < 0:
        smoke.problem(f"summary twoway: {label} has no choice {value!r}")
        return
    combo.setCurrentIndex(position)


def _tick(box, selected):
    for row in range(box.count()):
        item = box.item(row)
        item.setCheckState(Qt.CheckState.Checked if item.text() in selected else Qt.CheckState.Unchecked)


def _close(smoke, table, expected, what):
    if table is None or ANOVA_SHEET not in getattr(table, "tables", {}):
        smoke.problem(f"summary twoway: {what} has no ANOVA sheet")
        return None
    frame = table.tables[ANOVA_SHEET]
    for term, value in expected.items():
        if term not in frame.index or not math.isclose(float(frame.loc[term, "F"]), value, rel_tol=1e-8, abs_tol=1e-10):
            smoke.problem(f"summary twoway: {what} F for {term} is "
                          f"{None if term not in frame.index else frame.loc[term, 'F']}, expected {value}")
    if not math.isclose(float(frame.loc[RESIDUAL, "SS"]), 8.0, rel_tol=0, abs_tol=1e-10):
        smoke.problem(f"summary twoway: {what} residual SS is {frame.loc[RESIDUAL, 'SS']}")
    return frame


def _run(smoke, window, title):
    if not window.project.runs or window.project.runs[-1].method != METHOD:
        smoke.problem(f"summary twoway: {title} did not run")
        return None
    run = window.project.runs[-1]
    if run.calculation_error:
        smoke.problem(f"summary twoway: {title} failed: {run.calculation_error}")
    return run


def exercise(smoke, window):
    from analisi.i18n import active_language, ui
    from analisi.workbench import analyse
    from . import theme
    from .window import safe_csv
    app = QApplication.instance()
    language = active_language()
    folder = smoke.folder
    path = _project_copy(folder)
    window.open_path(path)
    smoke.wait()
    if TITLE not in window.project.tables:
        smoke.problem(f"summary twoway: {path.name} did not open {TITLE}")
        return
    window.open_sheet(("data", TITLE))
    app.processEvents()
    if not window.actions["analyze"].isEnabled():
        smoke.problem("summary twoway: Analyze is disabled on the grouped sheet")
        return
    started = time.perf_counter()

    def build(dialog):
        app.processEvents()
        heading = "ANOVA a due fattori da riepiloghi" if language == "it" else METHOD
        if dialog.heading.text() != heading:
            smoke.problem(f"summary twoway: heading {dialog.heading.text()!r}")
        if dialog.controls[INPUT][1].currentData() != SUBCOLUMNS:
            smoke.problem("summary twoway: a grouped sheet did not open on summary subcolumns")
        box = dialog.controls[VARIABLES][1]
        kept = [box.item(row).text() for row in range(box.count())
                if not box.item(row).text().endswith("[N]")]
        _tick(box, [name for name in kept if "[Mean]" in name or "[SD]" in name])
        dialog.controls[ROW_NAME][1].setText("A")
        dialog.controls[COLUMN_NAME][1].setText("B")
        _choose(smoke, dialog, DISPERSION_TYPE, SD)
        dialog.accept()
        sentence = "richiede Mean" if language == "it" else "needs Mean"
        if sentence not in dialog.banner.text() or not dialog.banner.isVisible():
            smoke.problem(f"summary twoway: dropping N did not show the field error ({dialog.banner.text()!r})")
        smoke.shot(dialog, "summary-twoway-field-error")
        _tick(box, [box.item(row).text() for row in range(box.count()) if box.item(row).text() != "Row title"])
        dialog.banner.hide()
        dialog.resize(min(940, smoke.screen_rect(dialog).width()), min(640, smoke.screen_rect(dialog).height()))
        theme.keep_on_screen(dialog)
        app.processEvents()
        smoke.shot(dialog, "summary-twoway-options")
        dialog.tabs.setCurrentIndex(1)
        app.processEvents()
        smoke.shot(dialog, "summary-twoway-names")
        dialog.accept()
        return dialog.result is not None

    with _driven(smoke, [build]):
        window.analyze(method=METHOD)
    smoke.wait()
    run = _run(smoke, window, TITLE)
    if run is None:
        return
    sheet = _close(smoke, run.result, EXPECTED, "balanced")
    index = window.project.runs.index(run)
    window.open_sheet(("result", index))
    smoke.wait()
    if window.result_tabs is not None and run.result is not None and ANOVA_SHEET in run.result.tables:
        window.result_tabs.setCurrentIndex(list(run.result.tables).index(ANOVA_SHEET))
    smoke.shot(window, "summary-twoway-result")
    saved = folder / f"summary-twoway-{language}.alab"
    window.project.save(saved)
    window.close_project()
    window.open_path(saved)
    smoke.wait()
    reopened = next((item for item in window.project.runs if item.method == METHOD), None)
    if reopened is None:
        smoke.problem(f"summary twoway: {saved.name} has no saved analysis")
        return
    index = window.project.runs.index(reopened)
    window.open_sheet(("result", index))
    smoke.wait()
    reopened = window.project.runs[index]
    _close(smoke, reopened.result, EXPECTED, f"reopened {saved.name}")
    if reopened.options.get(ROW_NAME) != "A" or reopened.options.get(COLUMN_NAME) != "B":
        smoke.problem(f"summary twoway: reopened names {reopened.options.get(ROW_NAME)!r}, "
                      f"{reopened.options.get(COLUMN_NAME)!r}")

    window.open_sheet(("data", TITLE))
    app.processEvents()
    model = window.sheet.model()
    column = list(model.frame.columns).index("B1 [Mean]")
    if model.frame.iat[1, 0] != "A1":
        smoke.problem(f"summary twoway: row 2 is {model.frame.iat[1, 0]!r}, expected A1")
    if not model.setData(model.index(1, column), "14"):
        smoke.problem("summary twoway: the mean edit was refused")
    app.processEvents()
    smoke.wait()
    edited = window.project.runs[window.project.runs.index(reopened)]
    edited_sheet = _close(smoke, edited.result, EDITED, "edited mean")
    if edited_sheet is not None:
        fresh = analyse(METHOD, window.project.tables[TITLE].frame(mask_excluded=True), edited.options)
        try:
            pd.testing.assert_frame_equal(edited.result.tables[ANOVA_SHEET], fresh.tables[ANOVA_SHEET])
        except AssertionError as error:
            smoke.problem(f"summary twoway: the edited sheet differs from the engine: {error}")
        csv_path = folder / f"{language}-summary-twoway-anova.csv"
        safe_csv(csv_path, edited_sheet, index=True)
        loaded = pd.read_csv(csv_path, index_col=0)
        for term in EXPECTED:
            if term not in loaded.index or not math.isclose(float(loaded.loc[term, "F"]), EDITED[term],
                                                            rel_tol=1e-6, abs_tol=1e-8):
                smoke.problem(f"summary twoway: exported F for {term} is "
                              f"{None if term not in loaded.index else loaded.loc[term, 'F']}")
    window.open_sheet(("result", window.project.runs.index(edited)))
    smoke.wait()
    smoke.shot(window, "summary-twoway-edited")

    window.undo()
    smoke.wait()
    restored = window.project.runs[window.project.runs.index(edited)]
    _close(smoke, restored.result, EXPECTED, "undo")
    window.undo(redo=True)
    smoke.wait()
    redone = window.project.runs[window.project.runs.index(edited)]
    _close(smoke, redone.result, EDITED, "redo")
    window.undo()
    smoke.wait()
    window.open_sheet(("data", TITLE))
    app.processEvents()
    window._worksheet_command(("data", TITLE), "freeze")
    app.processEvents()
    smoke.wait()
    locked_model = window.sheet.model()
    before = window.project.tables[TITLE].raw.copy()
    if locked_model.setData(locked_model.index(1, column), "14"):
        smoke.problem("summary twoway: a locked sheet accepted an edit")
    app.processEvents()
    try:
        pd.testing.assert_frame_equal(window.project.tables[TITLE].raw, before)
    except AssertionError as error:
        smoke.problem(f"summary twoway: the locked sheet changed: {error}")
    if not window.actions["analyze"].isEnabled():
        smoke.problem("summary twoway: Analyze is disabled on a locked sheet")
    held = window.project.runs[window.project.runs.index(edited)]
    _close(smoke, held.result, EXPECTED, "locked sheet")
    smoke.shot(window, "summary-twoway-locked")

    rows = folder / "bilanciato.csv"
    shutil.copyfile(FIXTURE / "bilanciato.csv", rows)
    window.project.dirty = False
    window.open_path(rows)
    smoke.wait()
    imported = next((name for name in window.project.tables if name != TITLE and name != "Sbilanciato"), None)
    if imported is None:
        smoke.problem("summary twoway: the long CSV was not imported")
    else:
        window.open_sheet(("data", imported))
        app.processEvents()

        def map_rows(dialog):
            if dialog.controls[INPUT][1].currentData() != ROWS:
                smoke.problem("summary twoway: a long CSV did not open on groups in rows")
            for label, value in ((ROW_FACTOR, "A"), (COLUMN_FACTOR, "B"), (MEAN, "Mean"),
                                 (DISPERSION, "SD"), (SAMPLE_SIZE, "N")):
                _choose(smoke, dialog, label, value)
            _choose(smoke, dialog, DISPERSION_TYPE, SD)
            dialog.controls[ROW_NAME][1].setText("A")
            dialog.controls[COLUMN_NAME][1].setText("B")
            dialog.resize(min(940, smoke.screen_rect(dialog).width()), min(640, smoke.screen_rect(dialog).height()))
            theme.keep_on_screen(dialog)
            app.processEvents()
            smoke.shot(dialog, "summary-twoway-rows")
            dialog.accept()
            return dialog.result is not None

        with _driven(smoke, [map_rows]):
            window.analyze(method=METHOD)
        smoke.wait()
        mapped = _run(smoke, window, imported)
        if mapped is not None:
            _close(smoke, mapped.result, EXPECTED, "long CSV")
    unbalanced = FIXTURE / "sbilanciato.csv"
    if imported is not None:
        wide = folder / "sbilanciato.csv"
        shutil.copyfile(unbalanced, wide)
        window.project.dirty = False
        window.open_path(wide)
        smoke.wait()
        unbalanced_title = next((name for name in window.project.tables
                                 if name not in {TITLE, "Sbilanciato", imported}), None)
        if unbalanced_title is None:
            smoke.problem("summary twoway: the unbalanced CSV was not imported")
        else:
            window.open_sheet(("data", unbalanced_title))

            def map_unbalanced(dialog):
                for label, value in ((ROW_FACTOR, "A"), (COLUMN_FACTOR, "B"), (MEAN, "Mean"),
                                     (DISPERSION, "SD"), (SAMPLE_SIZE, "N")):
                    _choose(smoke, dialog, label, value)
                _choose(smoke, dialog, DISPERSION_TYPE, SD)
                dialog.accept()
                return dialog.result is not None

            with _driven(smoke, [map_unbalanced]):
                window.analyze(method=METHOD)
            smoke.wait()
            mapped = _run(smoke, window, unbalanced_title)
            if mapped is not None and mapped.result is not None:
                labels = mapped.result.tables[SUMMARY_SHEET].iloc[:, 0].astype(str).tolist()
                if "Dose $" not in labels:
                    smoke.problem(f"summary twoway: the level Dose $ was not kept ({labels})")
    elapsed = time.perf_counter() - started
    screen = app.primaryScreen()
    ratio = screen.devicePixelRatio() if screen else "?"
    smoke.notes.append(
        f"[{smoke.language}] two-way summary ANOVA {elapsed:.2f}s, "
        f"device pixel ratio {ratio}, QT_SCALE_FACTOR {os.environ.get('QT_SCALE_FACTOR', '1')}, "
        f"command {ui(METHOD)!r}"
    )
    for session in window.sessions:
        session.project.dirty = False


def main(argv=None):
    """Only this step: ``python -m trama_qt.summary_twoway_smoke FOLDER [--languages en,it] [--themes light,dark]``."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(main.__doc__)
        return 2

    def option(name, default):
        if name in argv:
            position = argv.index(name)
            value = argv[position + 1]
            del argv[position:position + 2]
            return value.split(",")
        return default

    languages = option("--languages", ["en", "it"])
    themes = option("--themes", ["light", "dark"])
    folder = Path(argv[0])
    from analisi.i18n import set_language
    os.environ.setdefault("MPLBACKEND", "QtAgg")
    app = QApplication.instance() or QApplication([sys.argv[0]])
    from . import theme
    import matplotlib
    matplotlib.use("QtAgg")
    theme.load_fonts()
    from .smoke import Smoke
    from .window import MainWindow
    smoke = Smoke(folder)
    smoke.notes.append(f"OS {platform.system()} {platform.release()} — {platform.platform()}")
    for mode in themes:
        theme.set_mode(mode, app, remember=False)
        for language in languages:
            smoke.language = f"{language}-{mode}"
            set_language(language)
            theme.install_qt_translations(app, language)
            window = smoke.window = MainWindow()
            window.error = lambda error: smoke.problem(f"error shown: {error}")
            available = smoke.screen_rect(window)
            window.resize(min(1280, available.width()), min(800, available.height()))
            window.show()
            theme.keep_on_screen(window)
            app.processEvents()
            try:
                exercise(smoke, window)
            except Exception:  # noqa: BLE001 - the report says what broke, then the next run goes on.
                import traceback
                smoke.problem("stopped:\n" + traceback.format_exc())
            finally:
                for session in window.sessions:
                    session.project.dirty = False
                window.close()
                window.deleteLater()
                app.processEvents()
    status = smoke.report()
    print(f"Two-way summary ANOVA smoke: {status} ({folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
