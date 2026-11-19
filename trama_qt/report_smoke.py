"""Smoke of File → Export analysis report…, run by ``python -m trama_qt --smoke FOLDER`` after the project tabs.

A synthetic calibration (Dose, Risposta) gets a linear regression, a second regression with the same name, a
failed one and a layout, all through the window. The real dialog is shown, its field error recorded, sections
reordered and renamed, the replace confirmation answered No then Yes, and the report written as a job. The ZIP
is checked with ``verify_bundle`` and on its own (members, offline index, no Info note), then extracted to
``report-<lang>/estratto``. Screenshots ``<lang>-report-*.png`` go to the smoke folder.
"""
from copy import deepcopy
import json
from pathlib import Path
from unittest import mock
import zipfile

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QMessageBox

TITLE = "Control $ <A> & β"
NOTE = "Confronto <script>test</script> tra curve"


def run(smoke, window):
    """Raises nothing for a deviation: each one becomes a problem in the smoke report."""
    from analisi.presentation import Layout
    from analisi.report_bundle import verify_bundle
    from . import report_dialog, theme
    from .project import compute

    folder = smoke.folder / f"report-{smoke.language}"
    folder.mkdir(exist_ok=True)

    def check(ok, text):
        if not ok:
            smoke.problem(f"report: {text}")

    for session in window.sessions:
        session.project.dirty = False
    if window.sessions.full():
        window.close_project()
    window.new_project()
    csv = folder / "Calibrazione.csv"
    pd.DataFrame({"Dose": [0, 1, 2, 3, 4], "Risposta": [1, 3, 4, 8, 9]}).to_csv(csv, index=False)
    window.open_path(csv)
    smoke.wait()
    project = window.project
    title = next(iter(project.tables))
    frame = project.tables[title].frame(mask_excluded=True)
    first = project.candidate(title, "Linear regression", {"X": "Dose", "Y": "Risposta"})
    project.add_result(first, compute(first, frame))
    second = project.candidate(title, "Linear regression", {"X": "Risposta", "Y": "Dose"})
    second.label = first.name
    project.add_result(second, compute(second, frame))
    failed = project.candidate(title, "Linear regression", {"X": "Dose", "Y": "Risposta"})
    failed.label = "Regressione non aggiornata"
    project.add_result(failed, compute(failed, frame))
    failed.calculation_error = "Synthetic failure for the smoke"
    project.put_layout(Layout("Pannello β", 2, [first.reference, second.reference]))
    window.refresh()
    window.show_sheet("graph", 0)
    smoke.app.processEvents()
    project.dirty = False
    selected = window.selected
    target = folder / "report.zip"
    target.write_bytes(b"previous report")
    answers = []

    def drive(dialog):
        dialog.show()
        smoke.app.processEvents()
        smoke.shot(dialog, "report-dialog")
        rows = dialog.rows()
        reason = [row for row in rows if "Synthetic failure" in row.text()]
        check(len(reason) == 2 and not any(row.flags() & Qt.ItemFlag.ItemIsUserCheckable for row in reason),
              "the failed analysis is not marked with its reason")
        dialog.check_all(False)
        smoke.shot(dialog, "report-error")
        check(dialog.summary.objectName() == "errorBanner", "an empty selection is not a field error")
        dialog.check_all(True)
        dialog.title.setText(TITLE)
        dialog.note.setPlainText(NOTE)
        dialog.list.setCurrentRow(len(rows) - 1)  # The layout goes first.
        for _ in range(len(rows) - 1):
            dialog.move(-1)
        dialog.list.item(1).setText("Tabella $ <B>")
        smoke.shot(dialog, "report-ordered")
        theme.apply(smoke.app, dark=True)
        smoke.shot(dialog, "report-dark")
        theme.apply(smoke.app, dark=False)
        dialog.accept()
        return QDialog.DialogCode.Accepted if dialog.result else QDialog.DialogCode.Rejected

    def question(*args, **_kwargs):
        answers.append(args[2])
        return QMessageBox.StandardButton.No if len(answers) == 1 else QMessageBox.StandardButton.Yes

    errors = []
    with mock.patch.object(report_dialog.ReportDialog, "exec", drive), \
            mock.patch.object(report_dialog.QFileDialog, "getSaveFileName", return_value=(str(target), "")), \
            mock.patch.object(report_dialog.QMessageBox, "question", side_effect=question), \
            mock.patch.object(window, "error", lambda error: errors.append(str(error))):
        window.actions["export_report"].trigger()  # Answers No: nothing is written.
        smoke.wait()
        check(target.read_bytes() == b"previous report", "No to the replace question changed the file")
        window.actions["export_report"].trigger()
        smoke.wait()
    check(not errors, f"errors shown: {errors}")
    check(len(answers) == 2, "the replace question was not asked each time")
    try:
        manifest = verify_bundle(target)
    except ValueError as error:
        check(False, f"the report does not verify: {error}")
        return
    with zipfile.ZipFile(target) as bundle:
        names = sorted(bundle.namelist())
        blob = b"".join(bundle.read(name) for name in names)
        index = bundle.read("index.html").decode("utf-8")
        bundle.extractall(folder / "estratto")
    check(names == ["figures/001.svg", "figures/003.svg", "figures/005.svg", "index.html", "manifest.json",
                    "tables/002.csv", "tables/004.csv"], f"unexpected members {names}")
    check([s["label"] for s in manifest["sections"]][:2] == ["Pannello β", "Tabella $ <B>"],
          "order or names were not kept")
    check(manifest["project_title"] == TITLE and "&lt;script&gt;" in index, "title or note not literal")
    check("http://" not in index.replace('xmlns="http://www.w3.org', "") and "https://" not in index,
          "the index refers to the network")
    check(str(folder).encode() not in blob, "the report contains a local path")
    check(not project.dirty and window.selected == selected, "exporting changed the project or the selection")
    check(str(target) in window.message.text(), "the status does not show the report path")
    smoke.shot(window, "report-done")
    (folder / "manifest-letto.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
    project.dirty = False
    window.new_project()
