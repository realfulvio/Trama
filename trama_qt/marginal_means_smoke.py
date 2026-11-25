"""Estimated marginal means of Multifactor ANOVA in the desktop smoke.

``exercise`` runs inside ``python -m trama_qt --smoke FOLDER`` after planned contrasts. On its own,
``python -m trama_qt.marginal_means_smoke FOLDER [--languages en,it] [--themes light,dark]`` runs only this
step, once per language and theme.

The table is the unbalanced 2 × 2 of ``tests/data/marginal_means/oracolo.json``. The dialog asks for the
four cells and the overall mean, refuses a confidence of 0, then accepts 95%. The sheet and its CSV are
checked against the oracle. A cancelled edit keeps the recipe. Save, reopen, a cell edit and an excluded
observation recalculate the same sheet the engine builds from the masked worksheet.
"""
from contextlib import contextmanager
from copy import deepcopy
import json
import math
from pathlib import Path
import os
import platform
import sys

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from analisi import anova_marginal_means as means

METHOD = "Multifactor ANOVA"
TITLE = "Oracle 2 × 2"
ORACLE = json.loads((Path(__file__).resolve().parents[1] / "tests" / "data" / "marginal_means" / "oracolo.json")
                    .read_text(encoding="utf-8"))
DATA = pd.DataFrame(ORACLE["data"])
CELLS = (("A0 B0", "A0", "B0"), ("A0 B1", "A0", "B1"), ("A1 B0", "A1", "B0"), ("A1 B1", "A1", "B1"))


def _project(path):
    from analisi.data import Dataset, save_project
    save_project(path, {TITLE: Dataset(DATA.copy())})


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
            smoke.problem(f"means: unexpected dialog: {dialog.banner.text()}")
            dialog.reject()
            return QDialog.DialogCode.Rejected
        accepted = queue.pop(0)(dialog)
        return QDialog.DialogCode.Accepted if accepted and dialog.result else QDialog.DialogCode.Rejected

    with mock.patch.object(AnalysisDialog, "exec", run):
        yield
    if queue:
        smoke.problem("means: a dialog step did not run")


def _tick(dialog, names):
    box = dialog.controls["Factors"][1]
    for row in range(box.count()):
        item = box.item(row)
        item.setCheckState(Qt.CheckState.Checked if item.text() in names else Qt.CheckState.Unchecked)


def _tick_means(panel, names):
    panel.enabled.setChecked(True)
    for name in names:
        for row in range(panel.factor_list.count()):
            item = panel.factor_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == name:
                item.setCheckState(Qt.CheckState.Checked)


def _close_enough(sheet, smoke, what):
    if sheet is None or means.SHEET not in getattr(sheet, "tables", {}):
        return None
    frame = sheet.tables[means.SHEET]
    if list(frame.columns[:3]) != ["Mean", "A", "B"]:
        smoke.problem(f"means: {what} columns {list(frame.columns[:3])}")
        return frame
    for key, level_a, level_b in CELLS:
        rows = frame[(frame["A"] == level_a) & (frame["B"] == level_b)]
        if len(rows) != 1:
            smoke.problem(f"means: {what} has no cell {level_a} {level_b}")
            continue
        _numbers(smoke, rows.iloc[0], ORACLE["expected"][key], f"{what} {key}")
    overall = frame[frame["Mean"] == means.OVERALL_ROW]
    if len(overall) != 1:
        smoke.problem(f"means: {what} has no overall mean")
    else:
        _numbers(smoke, overall.iloc[0], ORACLE["expected"]["Globale"], f"{what} overall")
    if not (frame["Weighting"] == means.WEIGHTING_TEXT).all() or not (frame["Status"] == "OK").all():
        smoke.problem(f"means: {what} weighting or status changed")
    return frame


def _numbers(smoke, row, expected, what):
    for field, key in (("Estimate", "mean"), ("SE", "se"), ("df", "df"), ("CI low", "low"), ("CI high", "high")):
        if not math.isclose(float(row[field]), float(expected[key]), rel_tol=0, abs_tol=1e-10):
            smoke.problem(f"means: {what} {field} is {row[field]}, expected {expected[key]}")


def _panel_usable(smoke, panel, name):
    for child in panel.findChildren(QWidget):
        if child.isVisibleTo(panel) and child.width() <= 0:
            smoke.problem(f"{name}: {child.objectName() or type(child).__name__} has no width")
    if panel.factor_list.width() < 80 or panel.confidence.width() < 40:
        smoke.problem(f"{name}: the factor list or the confidence field collapsed "
                      f"({panel.factor_list.width()}×{panel.confidence.width()})")


def exercise(smoke, window):
    from analisi.i18n import active_language
    from analisi.workbench import analyse
    from . import theme
    from .window import safe_csv
    app = QApplication.instance()
    language = active_language()
    english = smoke.folder / "means-en.alab"
    path = smoke.folder / f"means-{language}-start.alab"
    _project(path)
    window.open_path(path)
    smoke.wait()
    window.open_sheet(("data", TITLE))
    app.processEvents()

    def build(dialog):
        _tick(dialog, ["A", "B"])
        dialog.controls["Interaction order"][1].setText("2")
        combo = dialog.controls["Compare marginal means by"][1]
        none = combo.findData("")
        combo.setCurrentIndex(none if none >= 0 else 0)
        dialog.tabs.setCurrentIndex(1)
        panel = dialog.controls[means.ENABLED][1]
        dialog.tabs.widget(1).ensureWidgetVisible(panel)
        _tick_means(panel, ["A", "B"])
        panel.overall.setChecked(True)
        panel.confidence.setText("0")
        app.processEvents()
        dialog.accept()
        if dialog.result is not None or "0" not in panel.confidence.text():
            smoke.problem(f"means: a confidence of 0 was accepted ({dialog.banner.text()})")
        sentence = "minore di 100" if language == "it" else "less than 100"
        if sentence not in dialog.banner.text() or panel.confidence.selectedText() != "0":
            smoke.problem(f"means: the confidence error did not select its field ({dialog.banner.text()!r}, "
                          f"selected {panel.confidence.selectedText()!r})")
        smoke.shot(dialog, "means-confidence-error")
        panel.confidence.setText("95")
        dialog.banner.hide()
        narrow = dialog.size()
        dialog.resize(min(640, smoke.screen_rect(dialog).width()), min(700, smoke.screen_rect(dialog).height()))
        app.processEvents()
        theme.keep_on_screen(dialog)
        app.processEvents()
        _panel_usable(smoke, panel, "means narrow")
        smoke.shot(dialog, "means-options-narrow")
        dialog.resize(narrow)
        app.processEvents()
        smoke.shot(dialog, "means-options")
        if panel.title.text() != ("Medie marginali stimate" if language == "it" else "Estimated marginal means"):
            smoke.problem(f"means: caption {panel.title.text()!r}")
        dialog.accept()
        return dialog.result is not None

    def cancel(dialog):
        panel = dialog.controls[means.ENABLED][1]
        panel.enabled.setChecked(False)
        if means.KEYS[0] in dialog.options():
            smoke.problem("means: turning the option off left its keys in the draft")
        dialog.reject()
        return False

    with _driven(smoke, [build]):
        window.analyze(method=METHOD)
    smoke.wait()
    if not window.project.runs:
        smoke.problem("means: the analysis did not run")
        return
    run = window.project.runs[-1]
    if run.calculation_error:
        smoke.problem(f"means: calculation failed: {run.calculation_error}")
    sheet = _close_enough(run.result, smoke, "first run")
    if "Multiple comparisons" in (run.result.tables if run.result is not None else {}):
        smoke.problem("means: comparisons were added while the comparison factor was empty")
    index = window.project.runs.index(run)
    window.open_sheet(("result", index))
    smoke.wait()
    if window.result_tabs is not None and run.result is not None and means.SHEET in run.result.tables:
        window.result_tabs.setCurrentIndex(list(run.result.tables).index(means.SHEET))
    smoke.shot(window, "means-result")
    if sheet is not None:
        csv_path = smoke.folder / f"{language}-means.csv"
        safe_csv(csv_path, sheet)
        loaded = pd.read_csv(csv_path)
        exported = sheet.reset_index(drop=True).astype(object)
        exported = exported.mask(exported.map(lambda value: value == ""), float("nan"))
        try:
            pd.testing.assert_frame_equal(loaded, exported, check_dtype=False)
        except AssertionError as error:
            smoke.problem(f"means: CSV differs from the sheet: {error}")
    confirmed = deepcopy(run.options)
    with _driven(smoke, [cancel]):
        window.change_parameters()
    smoke.wait()
    if run.options != confirmed:
        smoke.problem("means: Cancel changed the confirmed analysis")

    saved = smoke.folder / f"means-{language}.alab"
    window.project.save(saved)
    source = english if language != "en" and english.exists() else saved
    window.close_project()
    window.open_path(source)
    smoke.wait()
    index = next((i for i, item in enumerate(window.project.runs) if item.method == METHOD), None)
    if index is None:
        smoke.problem(f"means: {source.name} has no Multifactor ANOVA")
        return
    window.open_sheet(("result", index))
    smoke.wait()
    reopened = window.project.runs[index]
    if {key: reopened.options.get(key) for key in means.KEYS} != {key: confirmed.get(key) for key in means.KEYS}:
        smoke.problem(f"means: {source.name} reopened with another recipe")
    _close_enough(reopened.result, smoke, f"reopened {source.name}")
    smoke.shot(window, "means-reopened")

    window.open_sheet(("data", TITLE))
    model = window.sheet.model()
    if not model.setData(model.index(0, 2), "2"):  # A0 B0: 1 → 2
        smoke.problem("means: the cell edit was refused")
    app.processEvents()
    smoke.wait()
    window.sheet.setCurrentIndex(model.index(2, 2))  # one A0 B1 response
    window.toggle_exclusion()
    app.processEvents()
    smoke.wait()
    after = window.project.runs[index]
    if after.calculation_error or after.result is None or means.SHEET not in after.result.tables:
        smoke.problem(f"means: recalculation failed: {after.calculation_error}")
    else:
        title = next(iter(window.project.tables))
        fresh = analyse(METHOD, window.project.tables[title].frame(mask_excluded=True), after.options)
        try:
            pd.testing.assert_frame_equal(after.result.tables[means.SHEET], fresh.tables[means.SHEET])
        except AssertionError as error:
            smoke.problem(f"means: the edited sheet differs from the engine: {error}")
        if after.result.tables[means.SHEET]["Estimate"].iloc[0] == sheet["Estimate"].iloc[0] if sheet is not None else False:
            smoke.problem("means: the edit left the first estimate unchanged")
    window.open_sheet(("result", index))
    smoke.wait()
    smoke.shot(window, "means-recalculated")
    for session in window.sessions:
        session.project.dirty = False


def main(argv=None):
    """Only this step: ``python -m trama_qt.marginal_means_smoke FOLDER [--languages en,it] [--themes light,dark]``."""
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
    print(f"Marginal means smoke: {status} ({folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
