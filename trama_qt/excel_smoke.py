"""Smoke of File → Import/Export Excel workbook (scenario ``qt-excel-workbook``).

Run alone with ``python -m trama_qt --smoke FOLDER --scenario qt-excel-workbook`` (preferences kept in
FOLDER, theme from ``TRAMA_THEME``) or as part of the full ``--smoke``. Everything it reads is synthetic and
written into the smoke folder first; nothing of the user's is opened.

Per language: the import dialog on the multi-sheet workbook (Appunti left out, Vuoto not importable, header
row 2 for Controlli, an error on a header past the last row), the imported values, Cancel, a broken XLSX and an
incompatible selection on a modified project (nothing added), an analysis with several tables, an export of two
data sheets and two result tables in a chosen order, an independent read of the file (zip + XML, no openpyxl),
the overwrite question, a blocked destination and a Cancel during preparation (bytes and temporary files
recorded), and a reopen in Trama. Once per run: times on 50 000 × 20 cells in two sheets.
Screenshots ``<lang>-excel-*.png``; ``excel-<lang>/`` holds the files and ``excel-timings.txt``.
"""
from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import shutil
import sys
import time
from unittest import mock
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
from PySide6.QtWidgets import QDialog

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def fixture(folder):
    """The multi-sheet workbook of the acceptance packet, written here: a formula with a stored result (G2 = 5)
    and one without (G3), literal text, a hidden sheet and an empty one."""
    import datetime as dt
    from openpyxl import Workbook

    book = Workbook()
    sheet = book.active
    sheet.title = "Campioni α"
    for row in (["ID", "Dose", "Dose", None, "Attivo", "Data", "Calcolo", "Nota"],
                ["0007", 2, 3, 0, True, dt.datetime(2026, 4, 6, 12, 30), "=SUM(B2:C2)", None],
                ["0042", 4, 6, None, False, None, "=SUM(B3:C3)", "@codice"], [],
                ["0009", -1, 0, 1, None, None, None, "Fine $"]):
        sheet.append(row)
    sheet["H2"].value = "=letterale"
    sheet["H2"].data_type = "s"
    controls = book.create_sheet("Controlli")
    for row in (["Titolo della scheda"], ["ID esterno", "Risposta"], ["001", 0], ["002", 13.5]):
        controls.append(row)
    notes = book.create_sheet("Appunti")
    notes.append(["Internal"])
    notes.append(["HIDDEN_FIXTURE"])
    notes.sheet_state = "hidden"
    book.create_sheet("Vuoto")
    raw = folder / "raw.xlsx"
    book.save(raw)
    path = folder / "quaderno-multifoglio.xlsx"
    with ZipFile(raw) as source, ZipFile(path, "w") as target:
        for item in source.infolist():
            data = source.read(item)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(b'<c r="G2"><f>SUM(B2:C2)</f><v /></c>',
                                    b'<c r="G2"><f>SUM(B2:C2)</f><v>5</v></c>')
            target.writestr(item, data)
    raw.unlink()
    (folder / "rotto.xlsx").write_text("This fixture is intentionally not an XLSX archive.\n", encoding="utf-8")
    return path


def digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()[:16] if Path(path).exists() else "missing"


def peak_memory_mb():
    """Peak resident memory of this process, in MB (Windows: peak working set)."""
    try:
        if sys.platform.startswith("win"):
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t),
                            ("PeakPagefileUsage", ctypes.c_size_t)]
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.windll.kernel32.GetCurrentProcess(),
                                                     ctypes.byref(counters), counters.cb)
            return counters.PeakWorkingSetSize / 1e6
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / 1e6 if sys.platform == "darwin" else peak / 1e3
    except Exception:  # noqa: BLE001 - a measure, never a failure.
        return float("nan")


def independent_read(path):
    """Sheet names, formulas found and cells by coordinate (type, text), straight from the OOXML parts."""
    with ZipFile(path) as archive:
        book = ET.fromstring(archive.read("xl/workbook.xml"))
        names = [node.get("name") for node in book.iter(f"{NS}sheet")]
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {node.get("Id"): node.get("Target") for node in rels}
        relation = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        members = ["xl/" + targets[node.get(relation)].lstrip("/").removeprefix("xl/")
                   for node in book.iter(f"{NS}sheet")]
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ["".join(text.text or "" for text in item.iter(f"{NS}t"))
                      for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).iter(f"{NS}si")]
        sheets, formulas = {}, 0
        for name, member in zip(names, members):
            cells = {}
            for cell in ET.fromstring(archive.read(member)).iter(f"{NS}c"):
                formulas += cell.find(f"{NS}f") is not None
                kind = cell.get("t", "n")
                if kind == "inlineStr":
                    value = "".join(text.text or "" for text in cell.iter(f"{NS}t"))
                elif kind == "s":
                    value = shared[int(cell.findtext(f"{NS}v"))]
                else:
                    value = cell.findtext(f"{NS}v")
                cells[cell.get("r")] = (kind, value)
            sheets[name] = cells
    return names, formulas, sheets


def fresh(window):
    """One empty project tab, whatever the earlier steps left (their changes are discarded)."""
    for session in window.sessions:
        session.project.dirty = False
    while len(window.sessions) > 1:
        window.switch_project(window.sessions[len(window.sessions) - 1])
        window.close_project()
    window.close_project()


@contextmanager
def driven(smoke, configure, prefix):
    """QDialog.exec replaced: the dialog is shown, recorded through ``configure`` and accepted or cancelled."""
    original = QDialog.exec

    def run(dialog):
        dialog.show()
        smoke.app.processEvents()
        accepted = configure(dialog)
        smoke.app.processEvents()
        if accepted:
            dialog.accept()
            return QDialog.DialogCode.Accepted if dialog.result is not None else QDialog.DialogCode.Rejected
        dialog.reject()
        return QDialog.DialogCode.Rejected

    QDialog.exec = run
    try:
        yield
    finally:
        QDialog.exec = original


@contextmanager
def expected_errors(window):
    """Errors the scenario provokes on purpose are collected, not reported as problems."""
    shown, original = [], window.error
    window.error = lambda error: shown.append(str(error))
    try:
        yield shown
    finally:
        window.error = original


def run(smoke, window, *, timings=True):
    """Raises nothing for a deviation: each one becomes a problem in the smoke report."""
    from . import excel_workbook as excel
    folder = smoke.folder / f"excel-{smoke.language}"
    if folder.exists():  # Ours: an earlier run of the smoke. Start from nothing.
        for item in folder.rglob("*"):
            if item.is_dir():
                os.chmod(item, 0o700)
        shutil.rmtree(folder)
    folder.mkdir()

    def unexpected(parent, title, text):  # A question nobody planned would wait for a click forever.
        smoke.problem(f"excel: unexpected question: {text}")
        return False

    with mock.patch.object(excel, "confirm", unexpected), mock.patch.object(excel, "inform", lambda *args: None):
        return _scenario(smoke, window, folder, timings, excel)


def _scenario(smoke, window, folder, timings, excel):
    log = []

    def check(ok, text):
        if not ok:
            smoke.problem(f"excel: {text}")

    fresh(window)
    workbook = fixture(folder)

    # -- import: dialog, header rows, an error with its field visible --------------------------------
    def configure(dialog):
        check(dialog.checked() == ["Campioni α", "Controlli"], f"preselected {dialog.checked()}")
        check(not dialog.list.item(3, 0).flags() & excel.Qt.ItemFlag.ItemIsUserCheckable, "Vuoto can be chosen")
        smoke.shot(dialog, "excel-import")
        dialog.set_header("Controlli", 9)
        check(not dialog.import_button.isEnabled() and dialog.notes.isVisible(), "header past the end accepted")
        dialog.header.setFocus()
        smoke.shot(dialog, "excel-import-error")
        dialog.set_header("Controlli", 2)
        check(dialog.names.text().endswith("ID esterno, Risposta"), f"names {dialog.names.text()}")
        smoke.shot(dialog, "excel-import-header-2")
        dialog.select("Campioni α")
        check(dialog.grid.item(1, 0).text() == "0007" and dialog.grid.item(1, 7).text() == "=letterale",
              "preview values")
        check("G3" in dialog.notes.text(), "no note about G3")
        return True

    notices = []
    with driven(smoke, configure, "import"), mock.patch.object(excel, "inform",
                                                              lambda parent, title, text: notices.append(text)):
        window.import_excel_workbook(workbook)
        smoke.wait()
    tables = window.project.tables
    check(list(tables) == ["Campioni α", "Controlli"], f"imported {list(tables)}")
    if list(tables) == ["Campioni α", "Controlli"]:
        sample = tables["Campioni α"].raw
        check(sample.loc[0, "ID"] == "0007" and sample.loc[0, "Data"] == "2026-04-06T12:30:00"
              and sample.loc[0, "Nota"] == "=letterale" and sample.loc[0, "Calcolo"] == 5
              and pd.isna(sample.loc[1, "Calcolo"]) and sample.iloc[2].isna().all(), "imported values")
        check(tables["Controlli"].raw.to_dict("list") == {"ID esterno": ["001", "002"], "Risposta": [0, 13.5]},
              "Controlli with header row 2")
    check(notices and "G3" in notices[0], "no notice about G3 after the import")
    smoke.shot(window, "excel-imported")
    log.append(f"Import: {list(tables)}; notice: {notices[0] if notices else '-'}")

    # -- Cancel, broken file, incompatible selection: nothing changes -------------------------------
    window.project.dirty = True
    before = list(window.project.tables)
    with driven(smoke, lambda dialog: False, "import-cancel"):
        window.import_excel_workbook(workbook)
    check(list(window.project.tables) == before, "Cancel added sheets")
    with expected_errors(window) as shown:
        window.import_excel_workbook(folder / "rotto.xlsx")
    check(len(shown) == 1 and list(window.project.tables) == before and window.project.dirty,
          f"broken workbook: {shown}")
    log.append(f"Broken XLSX: {shown[0] if shown else '-'}")

    def incompatible(dialog):
        dialog.set_header("Controlli", 2)
        dialog.headers["Controlli"] = 50  # The sheet changes between preview and import.
        dialog.errors.clear()
        return True

    with expected_errors(window) as shown, driven(smoke, incompatible, "import-incompatible"):
        window.import_excel_workbook(workbook)
        smoke.wait()
    check(len(shown) == 1 and list(window.project.tables) == before, f"incompatible selection: {shown}")
    log.append(f"Incompatible selection: {shown[0] if shown else '-'}")

    # -- an analysis with several result tables ---------------------------------------------------
    from .analysis_dialog import AnalysisDialog
    groups = pd.DataFrame({"Group": list("aaabbbccc"), "Y": [1, 2, 3, 4, 5, 6, 7, 8, 9.5]})
    title = window.project.add_tables({"Gruppi": groups})[0]
    dialog = AnalysisDialog(window, groups, current=("One-way ANOVA", {}))
    options = dialog.options()
    dialog.deleteLater()
    options.update({"Response": "Y", "Group": "Group", "Post-hoc": "Tukey", "Brown–Forsythe variance test": True})
    window.calculate_candidate(window.project.candidate(title, "One-way ANOVA", options),
                               window.project.tables[title].frame(), None)
    smoke.wait()
    run_index = len(window.project.runs) - 1
    result = window.project.runs[run_index].result
    names = list(result.tables) if result is not None else []
    check(len(names) >= 2, f"the analysis gave {len(names)} tables")
    window.open_sheet(("result", run_index))
    smoke.wait()

    # -- export: two data sheets and two result tables, in order --------------------------------------
    path = folder / "esportazione.xlsx"
    chosen = {}

    def export_configure(dialog, shot=True):
        dialog.set_checked(("data", "Campioni α"))
        dialog.set_checked(("data", "Controlli"))
        if len(names) >= 2:
            dialog.set_checked(("result", run_index, names[1]))
        dialog.move_key(("data", "Controlli"), 0)
        dialog.move_key(("data", "Campioni α"), 1)
        chosen.update(dialog.excel_names())
        if shot:
            smoke.shot(dialog, "excel-export")
        return True

    with driven(smoke, export_configure, "export"):
        window.export_excel_workbook(path)
        smoke.wait()
    check(path.exists(), "no workbook written")
    if path.exists():
        sheets, formulas, cells = independent_read(path)
        check(sheets == list(chosen.values()), f"sheets {sheets} != {list(chosen.values())}")
        check(formulas == 0, f"{formulas} formulas in the export")
        sample = cells.get(sheets[1], {}) if len(sheets) > 1 else {}
        check(sample.get("A2") == ("inlineStr", "0007") and sample.get("H2") == ("inlineStr", "=letterale"),
              f"literal text {sample.get('A2')} {sample.get('H2')}")
        check(sample.get("B2") == ("n", "2") and sample.get("E2") == ("b", "1"), "numbers and booleans")
        anova = cells.get(sheets[2], {}) if len(sheets) > 2 else {}
        index_name = result.tables[names[0]].index.name if names else None
        check(anova.get("A1", (None, None))[1] == (index_name or "Row"), f"index header {anova.get('A1')}")
        log.append(f"Export: {sheets}; formulas {formulas}; {path.stat().st_size} bytes; sha {digest(path)}")

    # -- reopen the export in Trama ------------------------------------------------------------------
    count = len(window.project.tables)
    with driven(smoke, lambda dialog: True, "reopen"), mock.patch.object(excel, "inform", lambda *args: None):
        window.import_excel_workbook(path)
        smoke.wait()
    added = list(window.project.tables)[count:]
    check(len(added) == len(chosen), f"reopened {added}")
    if len(added) >= 2:
        again = window.project.tables[added[1]].raw
        check(again.loc[0, "ID"] == "0007" and again.loc[0, "Nota"] == "=letterale", "reopened values")
    smoke.shot(window, "excel-reopened")
    log.append(f"Reopen: {added}")
    # -- the same file again: No keeps it, a blocked destination keeps it, Cancel keeps it, Yes replaces it
    original = digest(path)
    with driven(smoke, lambda dialog: True, "export-no"), mock.patch.object(excel, "confirm", return_value=False):
        window.export_excel_workbook(path)
        smoke.wait()
    check(digest(path) == original, "No to the overwrite question changed the file")
    log.append(f"Overwrite No: {original} → {digest(path)}")
    with expected_errors(window) as shown, driven(smoke, lambda dialog: True, "export-locked"), \
            mock.patch.object(excel, "confirm", return_value=True), \
            mock.patch("analisi.xlsx_exchange.os.replace", side_effect=PermissionError("The file is in use.")):
        window.export_excel_workbook(path)
        smoke.wait()
    check(len(shown) == 1 and digest(path) == original, f"locked destination: {shown}")
    log.append(f"Locked destination: {original} → {digest(path)}; {shown[0] if shown else '-'}")
    locked_folder = folder / "bloccata"
    locked_folder.mkdir(exist_ok=True)
    real_block = not sys.platform.startswith("win") and os.geteuid() != 0  # root, Windows: folders do not block.
    if real_block:
        os.chmod(locked_folder, 0o500)
        blocked = mock.patch.object(sys, "dont_write_bytecode", sys.dont_write_bytecode)  # Nothing to replace.
    else:
        blocked = mock.patch("analisi.xlsx_exchange.tempfile.mkstemp",
                             side_effect=PermissionError(13, "Access is denied", str(locked_folder)))
    try:
        with expected_errors(window) as shown, driven(smoke, lambda dialog: True, "export-folder"), blocked:
            window.export_excel_workbook(locked_folder / "x.xlsx")
            smoke.wait()
    finally:
        if real_block:
            os.chmod(locked_folder, 0o700)
    check(len(shown) == 1 and not list(locked_folder.iterdir()), f"blocked folder: {shown}")
    log.append(f"Blocked folder ({'chmod 500' if real_block else 'no permission to create files, simulated'}): "
               f"{shown[0] if shown else '-'}; files in it: {len(list(locked_folder.iterdir()))}")

    real_prepare = excel.prepare_workbook

    def cancelling(target, entries, **options):
        cancel = options["cancel"]
        report = options["progress"]

        def progress(done, total):  # Cancel pressed once writing has started.
            report(done, total)
            cancel.set()
        options["progress"] = progress
        big = entries + [("Grande", pd.DataFrame({"X": np.arange(20000.0)}))]
        return real_prepare(target, big, **options)

    with driven(smoke, lambda dialog: True, "export-cancel"), mock.patch.object(excel, "confirm", return_value=True), \
            mock.patch.object(excel, "prepare_workbook", cancelling):
        window.export_excel_workbook(path)
        smoke.wait()
    check(digest(path) == original, "Cancel during preparation changed the file")
    leftovers = sorted(item.name for item in folder.iterdir() if item.name.startswith(".~trama-"))
    check(not leftovers, f"temporary files left: {leftovers}")
    log.append(f"Cancel during preparation: {original} → {digest(path)}; status '{window.message.text()}'; "
               f"temporary files {leftovers or 'none'}")
    with driven(smoke, lambda dialog: export_configure(dialog, shot=False), "export-yes"), \
            mock.patch.object(excel, "confirm", return_value=True):
        window.export_excel_workbook(path)
        smoke.wait()
    check(path.exists() and not [item for item in folder.iterdir() if item.name.startswith(".~trama-")],
          "replace left temporary files")
    log.append(f"Overwrite Yes: {original} → {digest(path)}")

    window.project.dirty = False

    if timings:
        log += measure(smoke, window, folder)
    (folder / "excel-report.txt").write_text("\n".join(log) + "\n", encoding="utf-8")
    window.project.dirty = False
    return log


def measure(smoke, window, folder):
    """Preview, import, export and Cancel response on 50 000 × 20 cells in two sheets."""
    import platform
    from analisi.xlsx_exchange import WorkbookReader
    from . import excel_workbook as excel
    fresh(window)

    def frame(seed):
        r = np.random.default_rng(seed)
        data = {f"N{index}": r.normal(size=50000) for index in range(14)}
        data.update({f"I{index}": pd.array(r.integers(0, 1000, 50000), dtype="Int64") for index in range(3)})
        data.update({f"T{index}": pd.array([f"id{value:06d}" for value in r.integers(0, 10 ** 6, 50000)],
                                           dtype="string") for index in range(3)})
        return pd.DataFrame(data)

    window.project.add_tables({"Grande A": frame(1), "Grande B": frame(2)})
    lines = [f"Measures on 2 sheets × 50 000 rows × 20 columns · {platform.platform()} · "
             f"{platform.processor() or platform.machine()} · {os.cpu_count()} logical CPUs"]
    path = folder / "grande.xlsx"

    def export(name):
        started = time.perf_counter()
        with driven(smoke, lambda dialog: [dialog.set_checked(("data", "Grande A")),
                                           dialog.set_checked(("data", "Grande B"))] and True, "measure-export"):
            window.export_excel_workbook(path)
            smoke.wait(600)
        lines.append(f"{name}: {time.perf_counter() - started:.2f} s, {path.stat().st_size / 1e6:.1f} MB")

    export("Export (cold)")
    with mock.patch.object(excel, "confirm", return_value=True):
        export("Export (warm, replace)")
    for name in ("cold", "warm"):
        started = time.perf_counter()
        with WorkbookReader(path) as reader:
            reader.sheets()
            reader.preview("Grande A", 1)
        lines.append(f"Open + preview ({name}): {time.perf_counter() - started:.2f} s")
    for name in ("cold", "warm"):
        started = time.perf_counter()
        with driven(smoke, lambda dialog: True, "measure-import"), mock.patch.object(excel, "inform",
                                                                                     lambda *args: None):
            window.import_excel_workbook(path)
            smoke.wait(600)
        lines.append(f"Import of both sheets ({name}): {time.perf_counter() - started:.2f} s")
    timings = {}

    def cancel_after(delay, command):
        started = time.perf_counter()
        command()
        while time.perf_counter() - started < delay and window.job is not None:
            smoke.app.processEvents()
            time.sleep(0.01)
        pressed = time.perf_counter()
        window.cancel_calculation()
        smoke.wait(600)
        return time.perf_counter() - pressed

    with driven(smoke, lambda dialog: True, "measure-cancel-import"):
        timings["import"] = cancel_after(1.0, lambda: window.import_excel_workbook(path))
    before = digest(path)
    with driven(smoke, lambda dialog: [dialog.set_checked(("data", "Grande A"))] and True, "measure-cancel-export"), \
            mock.patch.object(excel, "confirm", return_value=True):
        timings["export"] = cancel_after(1.0, lambda: window.export_excel_workbook(path))
    lines.append(f"Cancel response: import {timings['import']:.3f} s, export {timings['export']:.3f} s "
                 f"(file unchanged: {digest(path) == before})")
    lines.append(f"Peak memory of the process: {peak_memory_mb():.0f} MB")
    window.project.dirty = False
    (smoke.folder / "excel-timings.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines
