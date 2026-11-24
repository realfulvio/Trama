"""Desktop smoke for imported variable types and selective family duplication."""
import json
from zipfile import ZipFile

import pandas as pd
from PySide6.QtWidgets import QDialog

from analisi.data import load_project
from analisi.variable_types import VARIABLE_TYPES

from .family import FamilyDialog
from .variables import VariablesDialog


def _fixture(folder):
    path = folder / "observations.pzt"
    table = {"uid": "table", "format": "multivariable", "dataFormat": "y_single", "dataSets": ["a", "b"]}
    with ZipFile(path, "w") as archive:
        archive.writestr("document.json", '{"sheets":{"data":["source"]}}')
        archive.writestr("data/sheets/source/sheet.json", json.dumps({"title": "Observations", "table": table}))
        for uid, name, kind in (("a", "Amplitude", "continuous"), ("b", "Batch", "categorical")):
            archive.writestr(f"data/sets/{uid}.json", json.dumps({"title": name, "dataType": kind}))
        archive.writestr("data/tables/table/data.csv", "1.5,001\n2,002\n")
    return path


def _apply_dialog(command, dialog_type, edit):
    original = dialog_type.exec

    def execute(dialog):
        dialog.show()
        edit(dialog)
        dialog.accept()
        if dialog.isHidden():
            return QDialog.DialogCode.Accepted
        dialog.reject()
        return QDialog.DialogCode.Rejected

    dialog_type.exec = execute
    try:
        command.trigger()
    finally:
        dialog_type.exec = original


def run(smoke, window):
    window.open_path(_fixture(smoke.folder))
    smoke.wait()
    dataset = window.project.tables["Observations"]
    expected = {"Amplitude": "numeric", "Batch": "categorical"}
    smoke.expect(dataset.raw.attrs.get(VARIABLE_TYPES) == expected, "source variable types were not kept")
    smoke.expect(dataset.raw["Batch"].tolist() == ["001", "002"], "category labels lost leading zeroes")

    def edit_variables(dialog):
        smoke.shot(dialog, "variable-properties")
        dialog.table.item(0, 0).setText("Signal")
        smoke.expect(dialog.types[0].currentData() == "numeric", "imported numeric type is missing")
        smoke.expect(dialog.types[1].currentData() == "categorical", "imported categorical type is missing")

    _apply_dialog(window.actions["variable_properties"], VariablesDialog, edit_variables)
    smoke.expect("Signal" in dataset.raw, "the variable was not renamed")
    window.actions["undo"].trigger()
    smoke.expect("Amplitude" in dataset.raw, "Undo did not restore the variable name")
    window.actions["redo"].trigger()

    frame = pd.DataFrame({"Row title": ["A", "B", "C"], "Dose": [1., 2., 4.], "Response": [4., 7., 8.]})
    frame.attrs["table_format"] = "xy"
    window.project.add_tables({"groups": frame})
    window.open_sheet(("data", "groups"))
    index = smoke.calculate("XY series", {"X": "Dose", "Y columns": ["Response"]})
    window.open_sheet(("graph", index))

    def edit_family(dialog):
        dialog.name.setText("Repeat ")
        for key in ("values", "row_titles", "graph_titles"):
            smoke.expect(dialog.blank_options[key].isEnabled(), f"the option to clear {key} is disabled")
            dialog.blank_options[key].setChecked(True)
        smoke.shot(dialog, "duplicate-family-options")

    _apply_dialog(window.actions["duplicate_family"], FamilyDialog, edit_family)
    smoke.wait()
    copied = window.project.tables["Repeat groups"]
    source = window.project.tables["groups"]
    smoke.expect(window.selected == ("data", "Repeat groups"), "the copy did not open on its input sheet")
    smoke.expect(copied.raw["Dose"].tolist() == [1, 2, 4], "X was cleared")
    smoke.expect(copied.raw[["Response", "Row title"]].isna().all().all(), "selected fields were not cleared")
    smoke.expect(copied.analyses == source.analyses and copied.graph_styles[0]["title"] == "",
                 "the copied recipe or graph title was changed incorrectly")
    workspace = smoke.folder / f"{smoke.language}-worksheet-properties.alab"
    window.project.save(workspace)
    reopened = load_project(workspace)
    smoke.expect(reopened["Observations"].raw.attrs[VARIABLE_TYPES] == {"Signal": "numeric", "Batch": "categorical"},
                 "the reopened worksheet lost its types")
    saved_copy = reopened["Repeat groups"]
    smoke.expect(tuple(saved_copy.raw) == tuple(copied.raw), "reopening changed the copied columns")
    smoke.expect(saved_copy.raw["Dose"].tolist() == [1, 2, 4], "reopening changed the X values")
    smoke.expect(saved_copy.raw[["Response", "Row title"]].isna().all().all(), "reopening restored cleared cells")
    smoke.expect(saved_copy.analyses == source.analyses and saved_copy.graph_styles[0]["title"] == "",
                 "reopening changed the copied recipe or graph title")
