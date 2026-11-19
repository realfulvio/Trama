"""Planned contrasts of the Multifactor ANOVA in the desktop smoke (0.96).

``exercise`` runs inside ``python -m trama_qt --smoke FOLDER`` after the Multifactor ANOVA step. On its own,
``python -m trama_qt.planned_contrasts_smoke FOLDER [--languages en,it] [--themes light,dark]`` runs only this
step, once per language and theme, and writes the same ``report.txt`` and ``status.txt``.

From the synthetic 2 × 3 table of the 0.96 package (levels ``Control $`` and ``B |``) it goes through
Analyze → Multifactor ANOVA and the real **Planned contrasts…** editor: two contrasts in one run with post hoc
comparisons, an error on a weight with the cursor on its row and the fix, a duplicate and a reorder, Run on
the Qt worker, the two sheets and their CSV, a change cancelled on a confirmed recipe, save and reopen (in
the other language when the English run left its project), a cell edit and an excluded observation with
recalculation. Screenshots are named ``<lang>-contrasts-*.png``; problems go to the smoke report.
"""
from contextlib import contextmanager
from copy import deepcopy
import math
from pathlib import Path
import os
import sys

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

METHOD = "Multifactor ANOVA"
TITLE = "Campioni $ 2 × 3"
LEVELS = [("Control $", "A"), ("Control $", "B |"), ("Control $", "C"),
          ("Treated", "A"), ("Treated", "B |"), ("Treated", "C")]
SCORES = [[1, 2, 3], [3, 4, 5], [5, 6, 7], [2, 3, 4], [6, 7, 8], [10, 11, 12]]
DATA = pd.DataFrame([(*cell, value) for cell, values in zip(LEVELS, SCORES) for value in values],
                    columns=["Treatment", "Visit", "Score"])
FIRST, SECOND = "Treatment − Control $", "Difference of differences"


def _project(path):
    from analisi.data import Dataset, save_project
    save_project(path, {TITLE: Dataset(DATA.copy())})


@contextmanager
def _driven(smoke, analysis_steps, editor_steps):
    """Analysis dialogs and contrast editors run the queued steps instead of waiting for clicks."""
    from unittest import mock
    from .analysis_dialog import AnalysisDialog
    from .planned_contrasts import ContrastEditor
    app = QApplication.instance()

    def run_dialog(dialog):
        dialog.show()
        app.processEvents()
        if not analysis_steps:
            smoke.problem(f"contrasts: unexpected dialog: {dialog.banner.text()}")
            dialog.reject()
            return QDialog.DialogCode.Rejected
        accepted = analysis_steps.pop(0)(dialog)
        return QDialog.DialogCode.Accepted if accepted and dialog.result else QDialog.DialogCode.Rejected

    def run_editor(editor):
        editor.show()
        app.processEvents()
        if not editor_steps:
            smoke.problem("contrasts: unexpected contrast editor")
            editor.reject()
            return QDialog.DialogCode.Rejected
        if editor_steps.pop(0)(editor):
            editor.accept()
            return QDialog.DialogCode.Accepted if editor.result_state is not None else QDialog.DialogCode.Rejected
        editor.reject()
        return QDialog.DialogCode.Rejected

    with mock.patch.object(AnalysisDialog, "exec", run_dialog), mock.patch.object(ContrastEditor, "exec", run_editor):
        yield


def _fill(editor, row_cells):
    """Weights of the current contrast: ``[(treatment, visit, coefficient text), ...]``."""
    item = editor.contrast()
    while len(item["weights"]) < len(row_cells):
        editor.add_weight()
    for row, (treatment, visit, text) in enumerate(row_cells):
        editor.set_level(row, "Treatment", treatment)
        editor.set_level(row, "Visit", visit)
        editor.set_coefficient(row, text)


def _check_sheet(smoke, run, what):
    from analisi.anova_planned_contrasts import SHEET, WEIGHTS_SHEET
    if run is None or run.result is None or SHEET not in run.result.tables:
        smoke.problem(f"contrasts: {what}: no Planned contrasts sheet")
        return None
    sheet = run.result.tables[SHEET]
    if sheet["Contrast"].tolist() != [FIRST, SECOND] or sheet["Status"].tolist() != ["OK", "OK"]:
        smoke.problem(f"contrasts: {what}: rows {sheet['Contrast'].tolist()} {sheet['Status'].tolist()}")
    if WEIGHTS_SHEET not in run.result.tables:
        smoke.problem(f"contrasts: {what}: no weights sheet")
    return sheet


def exercise(smoke, window):
    from analisi import anova_planned_contrasts as planned
    from analisi.i18n import active_language
    from .window import safe_csv
    app = QApplication.instance()
    language = active_language()
    english = smoke.folder / "contrasts-en.alab"
    path = smoke.folder / f"contrasts-{language}-start.alab"
    _project(path)
    window.open_path(path)
    smoke.wait()
    window.open_sheet(("data", TITLE))
    seen = {}

    def build(editor):
        decimal = "0,5" if language == "it" else "0.5"
        editor.add_contrast()
        editor.name.setText(FIRST)
        editor._renamed(FIRST)
        _fill(editor, [("Treated", visit, "1/3") for visit in ("A", "B |", "C")]
              + [("Control $", visit, "-1/3") for visit in ("A", "B |", "C")])
        editor.add_contrast()
        editor.name.setText(SECOND)
        editor._renamed(SECOND)
        _fill(editor, [("Control $", "A", "1"), ("Control $", "C", "-1"), ("Treated", "A", "-1"),
                       ("Treated", "C", decimal)])  # 0.5: the sum is wrong on purpose
        editor.alpha.setText("0,05" if language == "it" else "0.05")
        app.processEvents()
        if editor.validate(show=True):
            smoke.problem("contrasts: a contrast whose coefficients do not add up to 0 was accepted")
        if not editor.weights_error.isVisible():
            smoke.problem("contrasts: the sum error is not shown beside the weights")
        smoke.shot(editor, "contrasts-editor-error")
        editor.set_coefficient(3, "abc")
        if editor.validate(show=True) or editor.table.currentRow() != 3:
            smoke.problem(f"contrasts: a text coefficient did not put the cursor on its row "
                          f"({editor.table.currentRow()})")
        editor.set_coefficient(3, "1")
        if not editor.validate(show=True):
            smoke.problem(f"contrasts: the corrected draft is refused: {editor.weights_error.text()}")
        editor.duplicate()
        editor.move(-1)
        names = [item["name"] for item in editor.items]
        if names[1] == SECOND or len(names) != 3:
            smoke.problem(f"contrasts: duplicate and move gave {names}")
        smoke.shot(editor, "contrasts-editor-duplicate")
        editor.remove()  # back to the two contrasts of the run
        editor.select(0)
        smoke.shot(editor, "contrasts-editor")
        return True

    def new_analysis(dialog):
        factors = dialog.controls["Factors"][1]
        for row in range(factors.count()):
            item = factors.item(row)
            item.setCheckState(Qt.CheckState.Checked if item.text() in ("Treatment", "Visit") else
                               Qt.CheckState.Unchecked)
        dialog.controls["Interaction order"][1].setText("2")
        combo = dialog.controls["Compare marginal means by"][1]
        combo.setCurrentIndex(combo.findData("Visit"))  # post hoc comparisons in the same run
        dialog.tabs.setCurrentIndex(1)
        panel = dialog.controls[planned.CONTRASTS][1]
        dialog.tabs.widget(1).ensureWidgetVisible(panel)
        smoke.shot(dialog, "contrasts-options-empty")
        panel.open_editor()
        dialog.tabs.widget(1).ensureWidgetVisible(panel)
        smoke.shot(dialog, "contrasts-options")
        dialog.accept()
        return dialog.result is not None

    def change_then_cancel(dialog):
        panel = dialog.controls[planned.CONTRASTS][1]

        def remove_all(editor):
            while editor.items:
                editor.remove()
            return True

        editors.append(remove_all)
        panel.open_editor()
        if planned.CONTRASTS in dialog.options():
            smoke.problem("contrasts: removing every contrast left the key in the draft")
        smoke.shot(dialog, "contrasts-cancelled-change")
        dialog.reject()
        return False

    dialogs, editors = [new_analysis], [build]
    with _driven(smoke, dialogs, editors):
        window.analyze(method=METHOD)
        smoke.wait()
        run = window.project.runs[-1]
        sheet = _check_sheet(smoke, run, "first run")
        if sheet is not None:
            for name, value in zip((FIRST, SECOND), (3.0, 4.0)):
                estimate = float(sheet.loc[sheet["Contrast"] == name, "Estimate"].iloc[0])
                if not math.isclose(estimate, value, rel_tol=1e-10):
                    smoke.problem(f"contrasts: {name} is {estimate}, expected {value}")
            if "Multiple comparisons" not in run.result.tables:
                smoke.problem("contrasts: the post hoc comparisons are missing from the same run")
        index = window.project.runs.index(run)
        window.open_sheet(("result", index))
        smoke.wait()
        names = list(run.result.tables)
        for tab, name in (("contrasts-result", planned.SHEET), ("contrasts-weights", planned.WEIGHTS_SHEET)):
            if window.result_tabs is not None and name in names:
                window.result_tabs.setCurrentIndex(names.index(name))
            smoke.shot(window, tab)
            safe_csv(smoke.folder / f"{language}-{tab}.csv", run.result.tables[name])
        confirmed, result = deepcopy(run.options), run.result
        dialogs.append(change_then_cancel)
        window.change_parameters()
        smoke.wait()
        if run.options != confirmed or window.project.runs[index].result is not result:
            smoke.problem("contrasts: Cancel changed the confirmed analysis")

    # Save; reopen the English project in the other language when there is one.
    saved = smoke.folder / f"contrasts-{language}.alab"
    window.project.save(saved)
    source = english if language != "en" and english.exists() else saved
    window.close_project()
    window.open_path(source)
    smoke.wait()
    index = next((i for i, item in enumerate(window.project.runs) if item.method == METHOD), None)
    if index is None:
        smoke.problem(f"contrasts: {source.name} has no Multifactor ANOVA")
        return
    window.open_sheet(("result", index))
    smoke.wait()
    reopened = window.project.runs[index]
    if {key: reopened.options.get(key) for key in planned.KEYS} != {key: confirmed.get(key) for key in planned.KEYS}:
        smoke.problem(f"contrasts: {source.name} reopened with another recipe")
    _check_sheet(smoke, reopened, f"reopened {source.name}")
    smoke.shot(window, "contrasts-reopened")

    # A cell edit and an excluded observation recalculate the contrasts.
    window.open_sheet(("data", TITLE))
    model = window.sheet.model()
    if not model.setData(model.index(9, 2), "5"):  # Treated, A: 2 → 5
        smoke.problem("contrasts: the cell edit was refused")
    app.processEvents()
    smoke.wait()
    window.sheet.setCurrentIndex(model.index(0, 2))
    window.toggle_exclusion()
    app.processEvents()
    smoke.wait()
    after = window.project.runs[index]
    sheet = _check_sheet(smoke, after, "after edit and exclusion")
    if sheet is not None:
        means = {"Control $": [2.5, 4, 6], "Treated": [4, 7, 11]}  # cell means after the edit and exclusion
        expected = (sum(means["Treated"]) - sum(means["Control $"])) / 3
        estimate = float(sheet["Estimate"].iloc[0])
        if not math.isclose(estimate, expected, rel_tol=1e-10) or int(sheet["df"].iloc[0]) != 11:
            smoke.problem(f"contrasts: after the edit {estimate} (df {sheet['df'].iloc[0]}), expected {expected}")
    window.open_sheet(("result", index))
    smoke.wait()
    smoke.shot(window, "contrasts-recalculated")
    for session in window.sessions:
        session.project.dirty = False


def main(argv=None):
    """Only this step: ``python -m trama_qt.planned_contrasts_smoke FOLDER [--languages en,it] [--themes light,dark]``."""
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
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([sys.argv[0]])
    from . import theme
    import matplotlib
    matplotlib.use("QtAgg")
    theme.load_fonts()
    from .smoke import Smoke
    from .window import MainWindow
    smoke = Smoke(folder)
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
    print(f"Planned contrasts smoke: {status} ({folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
