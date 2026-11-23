"""Smoke of Analysis → Repeat analysis on other sheets… (scenario ``qt-repeat-analysis``).

Run alone with ``python -m trama_qt --smoke FOLDER --scenario qt-repeat-analysis`` or as part of the full
``--smoke``. Everything it reads is synthetic and written into the smoke folder first.

Per language, on a project with Original (X, Y: Transform → Linear regression on Transformed), Lot B (Tempo,
Segnale), Lot C (Concentrazione, Risposta) and Short (two rows):

- the three steps of the assistant through their real widgets: the recipe with its downstream step, the sheets
  (Original refused with its reason), the columns chosen by hand, a duplicate choice that
  blocks Next, the preview; screenshots of each;
- Cancel during the calculation and a project changed during the calculation: nothing is added;
- a copy that cannot be calculated (Short): nothing is added and the same assistant opens again with the reason;
- the two copies: slopes 2 and 5, children linked to the new producer, Change input recognises them, the source
  untouched; editing an option of a copy leaves the source intact; save and reopen keep everything.
Screenshots ``<lang>-repeat-*.png``; the project is saved as ``repeat-<lang>.alab``.
"""
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

PARENT_ID = "664dd2e3-7bc3-4648-86c7-29493b5e3d62"
CHILD_ID = "a875096c-bd16-4f69-be97-937175df241d"
MAPPINGS = {"Lot B": {"X": "Tempo", "Y": "Segnale"}, "Lot C": {"X": "Concentrazione", "Y": "Risposta"},
            "Short": {"X": "A", "Y": "B"}}


def fixture(folder):
    """The project of the acceptance packet, plus a sheet too short for a regression."""
    from analisi.analysis_chain import ResultSource
    from analisi.data import Dataset, save_project

    original = Dataset(pd.DataFrame({"X": [0., 1., 4.], "Y": [1., 2., 5.]}), analyses=[
        ("Transform", {"Variables": ["X", "Y"], "Operation": "Absolute value"}),
        ("Linear regression", {"X": "X", "Y": "Y"}),
    ], analysis_ids={0: PARENT_ID, 1: CHILD_ID}, analysis_sources={1: ResultSource(PARENT_ID, "Transformed")})
    tables = {"Original": original,
              "Lot B": Dataset(pd.DataFrame({"Tempo": [0., 1., 4.], "Segnale": [1., 3., 9.]})),
              "Lot C": Dataset(pd.DataFrame({"Concentrazione": [0., 1., 4.], "Risposta": [4., 9., 24.]})),
              "Short": Dataset(pd.DataFrame({"A": [1., 2.], "B": [3., 5.]}))}
    path = Path(folder) / "repeat-fixture.alab"
    save_project(path, tables)
    return path


def slope(run):
    return float(run.result.tables["Regression"].at["Slope", "Value"])


def run(smoke, window):
    from analisi.data import project_bytes
    from analisi.repeat_analysis_text import t
    from . import repeat_analysis as module

    language = smoke.language
    errors = []

    def expect(condition, text):
        if not condition:
            smoke.problem(f"repeat analysis: {text}")

    window.error = lambda error: errors.append(str(error))
    window.open_path(fixture(smoke.folder))
    smoke.wait()
    project = window.project
    window.refresh_runs(list(project.runs))  # Results are calculated when shown: calculate them all here.
    smoke.wait()
    runs = project.runs
    source = next(index for index, item in enumerate(runs) if item.title == "Original" and item.slot == 0)
    child = next(item for item in runs if item.title == "Original" and item.slot == 1)
    expect(abs(slope(child) - 1.) < 1e-9, "the source regression is not 1")
    window.open_sheet(("result", source))
    smoke.wait()
    expect(window.actions["repeat_analysis"].isEnabled(), "Repeat analysis is disabled on a result")
    original_source = project_bytes({"Original": project.tables["Original"]})

    def drive(dialog, targets, name=None, accept=True):
        """Recipe (with the downstream step), sheets and columns by hand, preview."""
        expect(dialog.follow.isEnabled() and dialog.follow.isChecked(),
                     "the downstream step is not offered")
        expect("Linear regression" in dialog.summary.toPlainText() or
                     "Regressione lineare" in dialog.summary.toPlainText(), "the summary misses the child step")
        if name:
            smoke.shot(dialog, f"{name}-recipe")
        dialog.next.click()
        items = {dialog.sheet_list.item(row).data(Qt.ItemDataRole.UserRole): dialog.sheet_list.item(row)
                 for row in range(dialog.sheet_list.count())}
        expect(not items["Original"].flags() & Qt.ItemFlag.ItemIsEnabled, "the source sheet is selectable")
        for title in targets:
            items[title].setCheckState(Qt.CheckState.Checked)
            expect(not dialog.next.isEnabled(), f"Next is enabled before choosing the columns of {title}")
            for row in range(dialog.table.rowCount()):
                column = dialog.table.item(row, 0).text()
                box = dialog.table.cellWidget(row, 1)
                box.setCurrentIndex(box.findData(MAPPINGS[title][column]))
            if name and title == "Lot B":  # A duplicate choice blocks Next and says why.
                box = dialog.table.cellWidget(1, 1)
                box.setCurrentIndex(box.findData(MAPPINGS[title][dialog.table.item(0, 0).text()]))
                expect(not dialog.next.isEnabled(), "a duplicate column choice did not block Next")
                expect(dialog.sheet_status.text() != t("ready"), "a duplicate choice shows no reason")
                smoke.shot(dialog, f"{name}-duplicate")
                box.setCurrentIndex(box.findData(MAPPINGS[title][dialog.table.item(1, 0).text()]))
        expect(dialog.next.isEnabled(), "Next stays disabled with every column chosen")
        if name:
            smoke.shot(dialog, f"{name}-sheets")
        dialog.next.click()
        expect(dialog.pages.currentIndex() == 2 and dialog.plan is not None, "the preview did not open")
        if name:
            smoke.shot(dialog, f"{name}-preview")
        if not accept:
            dialog.reject()
            return QDialog.DialogCode.Rejected
        dialog.apply.click()
        return dialog.result()

    def repeat(targets, *, name=None, during=None, reopened=None):
        """Open the command on the source, drive the assistant, optionally act while the copies calculate."""
        seen = []

        def exec_(dialog):
            seen.append(dialog)
            if len(seen) > 1:  # The same assistant reopened after a failure.
                if reopened is not None:
                    reopened(dialog)
                dialog.reject()
                return QDialog.DialogCode.Rejected
            return drive(dialog, targets, name)

        original = module.RepeatDialog.exec
        module.RepeatDialog.exec = exec_
        try:
            window.open_sheet(("result", source))
            window.repeat_analysis()
            if during is not None and window.job is not None:
                during()
            smoke.wait()
            for _ in range(5):  # A reopened assistant arrives through a zero timer.
                smoke.app.processEvents()
        finally:
            module.RepeatDialog.exec = original
        return seen

    # Cancel during the calculation: nothing added.
    before = project_bytes(project.tables)
    count = len(project.runs)
    repeat(["Lot B", "Lot C"], during=window.cancel_calculation)
    expect(project_bytes(project.tables) == before and len(project.runs) == count,
                 "Cancel during the calculation changed the project")
    # A project changed during the calculation: nothing added, the user is told.
    errors.clear()

    def change():
        project.tables["Lot C"].raw.iat[0, 1] = 4.0
        project.dirty = True

    repeat(["Lot B", "Lot C"], during=change)
    expect(errors == [t("changed")], f"the changed project was not reported: {errors}")
    expect(len(project.runs) == count and all(not project.tables[name].analyses
                                                    for name in ("Lot B", "Lot C")),
                 "copies were added to a project changed during the calculation")
    errors.clear()
    # A copy that cannot be calculated: nothing added, the same assistant again with the reason.
    before = project_bytes(project.tables)
    notices = []

    def reopened(dialog):
        notices.append(dialog.banner.text())
        expect(dialog.pages.currentIndex() == 1 and "Short" in dialog.assistant.selected,
                     "the assistant did not reopen on the same choices")
        smoke.shot(dialog, "repeat-failed")

    seen = repeat(["Lot B", "Short"], reopened=reopened)
    expect(len(seen) == 2 and seen[0].assistant is seen[1].assistant, "the assistant did not reopen")
    expect(bool(notices) and "Short" in notices[0], f"the failure does not name the sheet: {notices}")
    expect(project_bytes(project.tables) == before and len(project.runs) == count,
                 "a failed copy changed the project")
    # The two copies.
    repeat(["Lot B", "Lot C"], name="repeat")
    expect(not errors, f"errors during the repetition: {errors}")
    added = {item.title: item for item in project.runs if item.title in ("Lot B", "Lot C")}
    expect(len(project.runs) == count + 4, f"{len(project.runs) - count} analyses added, 4 expected")
    for title, expected in (("Lot B", 2.), ("Lot C", 5.)):
        copies = [item for item in project.runs if item.title == title]
        parent = next((item for item in copies if item.slot == 0), None)
        regression = next((item for item in copies if item.method == "Linear regression"), None)
        if parent is None or regression is None:
            smoke.problem(f"{title}: the copies are missing")
            continue
        expect(abs(slope(regression) - expected) < 1e-8, f"{title}: slope {slope(regression)}, not {expected}")
        expect(regression.source is not None and regression.source.analysis_id == parent.uid and
                     parent.uid not in (PARENT_ID, CHILD_ID), f"{title}: the child is not linked to the new copy")
    expect(project_bytes({"Original": project.tables["Original"]}) == original_source,
                 "the source sheet changed")
    smoke.shot(window, "repeat-added")
    regression = next(item for item in project.runs if item.title == "Lot B" and item.method == "Linear regression")
    window.open_sheet(("result", project.runs.index(regression)))
    smoke.wait()
    smoke.shot(window, "repeat-copy-result")
    with smoke.dialogs("repeat-change-input"):
        window.change_input_result()
    # Editing an option of a copy leaves the source intact.
    copy = project.tables["Lot B"]
    method, options = copy.analyses[1]
    copy.analyses[1] = (method, {**options, "Confidence level": 0.9})
    expect(project.tables["Original"].analyses[1][1].get("Confidence level") != 0.9,
                 "editing the copy changed the source")
    copy.analyses[1] = (method, options)
    # Save and reopen.
    path = smoke.folder / f"repeat-{language}.alab"
    project.save(path)
    window.new_project()
    window.open_path(path)
    smoke.wait()
    window.refresh_runs(list(window.project.runs))
    smoke.wait()
    reopened = {item.title: item for item in window.project.runs if item.method == "Linear regression"}
    for title, expected in (("Original", 1.), ("Lot B", 2.), ("Lot C", 5.)):
        item = reopened.get(title)
        expect(item is not None and item.result is not None and abs(slope(item) - expected) < 1e-8,
                     f"{title}: the reopened regression is not {expected}")
    expect(not errors, f"errors after reopening: {errors}")
    window.project.dirty = False
    smoke.notes.append(f"[{language}] repeat analysis: cancel, changed project, failed copy, slopes 2 and 5, "
                       f"save/reopen OK")
