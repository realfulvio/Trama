"""Desktop acceptance of worksheets linked to a CSV or TSV file (File → Update from file…), with screenshots.

    python -m trama_qt.source_link_smoke OUT [--lang en|it] [--theme light|dark] [--size 1024x768]

Run it on a real screen or on a virtual one (``xvfb-run -a -s '-screen 0 1600x1000x24' ...``) and, for 150 %, with
``QT_SCALE_FACTOR=1.5`` on a screen of 1536×1152 pixels, which Qt sees as 1024×768 logical pixels. The scale is
emulated, not a native DPI setting; the report says so.

It uses a temporary preferences folder and the synthetic files of ``tests/data/source_link``. Every dialog runs with
its real ``exec`` and is driven like a person would: the import with “Link to the source file” and the key ``ID``,
a linear regression (slope 2), the file replaced by ``aggiornato.csv``, the preview (one row moved, B modified, D
added) confirmed with Enter, the slope 2.2, Undo (2) and Redo (2.2), a style and an exclusion on B that follow the
key, ``duplicato.csv`` refused with Apply off, a conflict that needs a decision, the four conflicts of
``per_riga`` decided row by row with the keyboard (Alt+N or Alt+S, Alt+P, Alt+F, Enter) to give ``atteso.csv``,
the Source link dialog, save, close and reopen with the file moved next to the project. ``OUT`` receives PNG
screenshots, ``casi-dati-collegati.alab`` with its ``dati.csv`` and ``dati-per-riga.csv`` (reopenable: the links
are relative), ``report.txt`` and ``status.txt`` (PASS/FAIL).
"""
import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data" / "source_link"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="en")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--size", default="1024x768")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    width, height = (int(value) for value in args.size.lower().split("x"))
    prefs = Path(tempfile.mkdtemp(prefix="trama-source-link-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    from PySide6 import __version__ as pyside
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

    from analisi.i18n import set_language
    set_language(args.lang)
    app = QApplication.instance() or QApplication(["trama-source-link-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.source_link import SourceLinkDialog, UpdatePreviewDialog
    from trama_qt.source_link import t as link_text
    from trama_qt.text_import import TextImportDialog
    from trama_qt.window import MainWindow

    problems, shots, timings = [], [], {}
    tag = f"{args.lang}-{args.theme}-{width}x{height}"
    italian = args.lang == "it"

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

    def when_modal(kind, act):
        """Act on the next modal dialog of class ``kind`` while its real exec() runs."""
        timer = QTimer()
        timer.setInterval(30)

        def poll():
            widget = app.activeModalWidget()
            if isinstance(widget, kind):
                timer.stop()
                try:
                    act(widget)
                except Exception:  # noqa: BLE001 - recorded, then the dialog is closed so the smoke goes on.
                    problems.append(f"{kind.__name__}:\n{traceback.format_exc()}")
                if widget.isVisible():  # A refused Apply keeps the dialog open: say why and close it.
                    banner = getattr(widget, "blocked", None)
                    problems.append(f"{kind.__name__} stayed open"
                                    + (f": {banner.text()}" if banner is not None else ""))
                    widget.reject()

        timer.timeout.connect(poll)
        timer.start()
        return timer

    work = out / f"{tag}-files"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()
    data = work / "dati.csv"
    shutil.copyfile(DATA / "iniziale.csv", data)

    window = MainWindow()
    errors = []
    window.error = lambda error: errors.append(str(error))
    window._ask = lambda *a, error=None, **k: errors.append(f"calculation failed: {error}")
    available = (window.screen() or app.primaryScreen()).availableGeometry()
    window.resize(min(width, available.width()), min(height, available.height()))
    window.show()
    app.processEvents()
    theme.keep_on_screen(window)

    def wait():
        end = time.monotonic() + 120
        while window.job is not None and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        settle()

    def slope():
        return float(window.project.runs[0].result.tables["Regression"].loc["Slope"].iloc[0])

    def ids():
        return window.project.tables[title].raw["ID"].tolist()

    def preview(act):
        seen = {}

        def look(dialog):
            seen["summary"] = dialog.summary.text()
            seen["enabled"] = dialog.apply_button.isEnabled()
            seen["rows"] = dialog.table.rowCount()
            act(dialog, seen)

        timer = when_modal(UpdatePreviewDialog, look)
        started = time.perf_counter()
        window.actions["refresh_source"].trigger()
        wait()
        timer.stop()
        seen["seconds"] = time.perf_counter() - started
        return seen

    title = None
    try:
        # -- import with the link ------------------------------------------------------------------------------------
        def import_linked(dialog):
            dialog.link.setChecked(True)
            dialog.key.setCurrentIndex(dialog.key.findData("ID"))
            settle()
            check(dialog.link.text() == ("Collega al file sorgente" if italian else "Link to the source file"),
                  f"link checkbox text {dialog.link.text()!r}")
            shot(dialog, "import-linked")
            dialog.accept()

        timer = when_modal(TextImportDialog, import_linked)
        window.open_path(data, import_data=True)
        wait()
        timer.stop()
        title = window._active_table()
        check(window.project.tables[title].source_link is not None, "the import did not link the worksheet")
        check(window.actions["refresh_source"].isEnabled(), "Update from file… is off on a linked worksheet")
        candidate = window.project.candidate(title, "Linear regression", {"X": "X", "Y": "Y"})
        window.calculate_candidate(candidate, window.project.tables[title].frame(), None)
        wait()
        check(abs(slope() - 2.0) < 1e-12, f"initial slope {slope()}")
        window.show_sheet("data", title)
        window.project.set_table_background(title, (1, 0, 1, 2), "#ffcc00")  # The row of B.
        window.project.toggle_exclusion(title, [(1, 0)])  # The key cell of B: the regression still uses every row.
        window.reshow()
        shot(window, "linked-worksheet")

        # -- the package case: preview, Enter applies, Undo, Redo ------------------------------------------------------
        shutil.copyfile(DATA / "aggiornato.csv", data)
        source_bytes = data.read_bytes()

        def enter(dialog, seen):
            shot(dialog, "preview")
            QTest.keyClick(dialog.table, Qt.Key.Key_Return)  # Enter: the default button is Apply.

        seen = preview(enter)
        timings["preview and apply (4 rows)"] = seen["seconds"]
        expected = ("4 righe nel file · 1 aggiunte · 1 modificate · 0 rimosse · 1 spostate · 2 invariate" if italian
                    else "4 rows in the file · 1 added · 1 modified · 0 removed · 1 moved · 2 unchanged")
        check(seen.get("summary") == expected, f"preview summary {seen.get('summary')!r}")
        check(seen.get("rows") == 3 and seen.get("enabled"), f"preview rows {seen.get('rows')}, Apply on "
                                                             f"{seen.get('enabled')}")
        check(ids() == ["C", "A", "B", "D"], f"order after Apply {ids()}")
        check(abs(slope() - 2.2) < 1e-12, f"slope after Apply {slope()}")
        check({row for row, _ in window.project.tables[title].cell_backgrounds} == {2},
              "the background of B did not follow its key")
        check(window.project.tables[title].excluded == {(2, 0)}, "the exclusion of B did not follow its key")
        check(data.read_bytes() == source_bytes, "the source file was written")
        shot(window, "updated")
        window.actions["undo"].trigger()
        wait()
        check(ids() == ["A", "B", "C"] and abs(slope() - 2.0) < 1e-12, f"Undo: {ids()} slope {slope()}")
        window.actions["redo"].trigger()
        wait()
        check(ids() == ["C", "A", "B", "D"] and abs(slope() - 2.2) < 1e-12, f"Redo: {ids()} slope {slope()}")

        # -- duplicated keys: Apply off, nothing changes ---------------------------------------------------------------
        shutil.copyfile(DATA / "duplicato.csv", data)
        raw = window.project.tables[title].raw

        def blocked(dialog, seen):
            seen["blocked"] = dialog.blocked.text()
            shot(dialog, "preview-duplicate-keys")
            QTest.keyClick(dialog.table, Qt.Key.Key_Return)  # Enter on a blocked preview applies nothing.
            settle()
            dialog.reject()

        seen = preview(blocked)
        check(not seen.get("enabled"), "Apply is on with duplicated keys")
        check(("ripete B" if italian else "repeats B") in seen.get("blocked", ""), f"blocked {seen.get('blocked')!r}")
        check(window.project.tables[title].raw is raw, "duplicated keys changed the worksheet")

        # -- a conflict: no default, a choice turns Apply on -----------------------------------------------------------
        shutil.copyfile(DATA / "aggiornato.csv", data)
        data.write_text(data.read_text(encoding="utf-8").replace("B,2,9", "B,2,10"), encoding="utf-8")
        window.project.edit_cell(title, 2, 2, "8")  # B in the project.
        window.reshow()

        def conflict(dialog, seen):
            seen["before"] = dialog.apply_button.isEnabled()
            dialog.conflicts.all_project.click()
            seen["after"] = dialog.apply_button.isEnabled()
            shot(dialog, "preview-conflict")
            dialog.accept()

        seen = preview(conflict)
        check(seen.get("before") is False and seen.get("after") is True, f"conflict decision {seen}")
        values = dict(zip(ids(), window.project.tables[title].raw["Y"].tolist()))
        check(values.get("B") == 8, f"Keep the project for all gave B = {values.get('B')}")

        # -- conflicts decided row by row, with the keyboard: the package case of per_riga ---------------------------
        rows_file = work / "dati-per-riga.csv"
        shutil.copyfile(DATA / "per_riga" / "iniziale.csv", rows_file)
        def import_rows(dialog):
            dialog.link.setChecked(True)
            dialog.key.setCurrentIndex(dialog.key.findData("ID"))
            dialog.accept()

        timer = when_modal(TextImportDialog, import_rows)
        window.open_path(rows_file, import_data=True)
        wait()
        timer.stop()
        rows_title = window._active_table()
        keys = window.project.tables[rows_title].raw["ID"].tolist()
        for key, value in (("B", "21"), ("C", "31"), ("D", "41")):
            window.project.edit_cell(rows_title, keys.index(key), 1, value)
        window.project.delete_rows(rows_title, [keys.index("E")])
        window.reshow()
        shutil.copyfile(DATA / "per_riga" / "aggiornato.csv", rows_file)
        choose = {"B": Qt.Key.Key_P, "D": Qt.Key.Key_P, "C": Qt.Key.Key_F, "E": Qt.Key.Key_F}

        def row_by_row(dialog, seen):
            panel = dialog.conflicts
            seen["open"] = panel.state.text()
            panel.table.setFocus()
            shot(dialog, "preview-conflicts-open")
            for _ in range(len(choose)):  # Alt+N (Alt+S) finds the next row to decide, Alt+P / Alt+F decide it.
                QTest.keyClick(app.focusWidget(), Qt.Key.Key_S if italian else Qt.Key.Key_N,
                               Qt.KeyboardModifier.AltModifier)
                QTest.qWait(250)
                key = panel.table.item(panel.selected_lines()[0], 0).text()
                if key == "B":
                    seen["half"] = [panel.state.text(), dialog.apply_button.isEnabled()]
                QTest.keyClick(app.focusWidget(), choose[key], Qt.KeyboardModifier.AltModifier)
                QTest.qWait(250)
            seen["done"] = [panel.state.text(), dialog.apply_button.isEnabled(), dialog.apply_button.isDefault()]
            shot(dialog, "preview-conflicts-decided")
            QTest.keyClick(app.focusWidget(), Qt.Key.Key_Return)  # Enter: Apply.

        seen = preview(row_by_row)
        timings["preview and apply (4 conflicts row by row)"] = seen["seconds"]
        check(seen.get("open") == ("4 di 4 ancora da decidere" if italian else "4 of 4 still to decide"),
              f"conflicts open {seen.get('open')!r}")
        check(seen.get("done") == [("Tutte le 4 decise." if italian else "All 4 decided."), True, True],
              f"conflicts decided {seen.get('done')}")
        expected_rows = [line.split(",") for line in
                         (DATA / "per_riga" / "atteso.csv").read_text(encoding="utf-8").split()[1:]]
        rows = [[key, str(value)] for key, value in window.project.tables[rows_title].raw[["ID", "Y"]].values]
        check(rows == expected_rows, f"row by row gave {rows}, expected {expected_rows}")
        shot(window, "updated-row-by-row")
        window.actions["undo"].trigger()
        wait()
        undone = window.project.tables[rows_title].raw["ID"].tolist()
        check(undone == ["A", "B", "C", "D", "G"], f"Undo of row by row: {undone}")
        window.actions["redo"].trigger()
        wait()
        window.show_sheet("data", title)
        settle()

        # -- the Source link dialog ------------------------------------------------------------------------------------
        def look_link(dialog):
            buttons = [button for button in dialog.findChildren(QPushButton)
                       if button.objectName().startswith("sourceLink_")]
            check(len(buttons) == 3 and not any(button.autoDefault() for button in buttons),
                  "Source link buttons must not be auto-default")
            shot(dialog, "source-link")
            dialog.reject()

        timer = when_modal(SourceLinkDialog, look_link)
        window.actions["source_link"].trigger()
        settle()
        timer.stop()

        # -- save, move project and file together, reopen --------------------------------------------------------------
        saved = work / "casi-dati-collegati.alab"
        window.project.save(saved)
        shutil.copyfile(saved, out / "casi-dati-collegati.alab")
        shutil.copyfile(data, out / "dati.csv")
        shutil.copyfile(rows_file, out / "dati-per-riga.csv")
        window.project.dirty = False
        moved = out / f"{tag}-moved"
        shutil.rmtree(moved, ignore_errors=True)
        shutil.copytree(work, moved)
        shutil.rmtree(work)
        window.open_path(moved / "casi-dati-collegati.alab")
        wait()
        title = next(name for name, dataset in window.project.tables.items() if dataset.source_link is not None)
        window.show_sheet("data", title)
        settle()
        check(ids() == ["C", "A", "B", "D"], f"reopened order {ids()}")
        (moved / "dati.csv").write_text("ID,X,Y\nC,3,7\nA,1,3\nB,2,10\nD,4,11\nE,5,13\n", encoding="utf-8")

        def relative(dialog, seen):
            seen["before"] = dialog.apply_button.isEnabled()
            dialog.use_file.setChecked(True)
            seen["after"] = dialog.apply_button.isEnabled()
            shot(dialog, "preview-moved-project")
            dialog.accept()

        seen = preview(relative)
        check(seen.get("before") is False and seen.get("after") is True, f"moved project {seen}")
        values = dict(zip(ids(), window.project.tables[title].raw["Y"].tolist()))
        check(ids() == ["C", "A", "B", "D", "E"] and values.get("B") == 8,  # B keeps the project edit.
              f"after the moved update {values}")
        check(errors == [], f"errors shown: {errors}")
        window.project.dirty = False
        # -- unlink: the question, then one Undo step ------------------------------------------------------------------
        timer = when_modal(QMessageBox, lambda box: box.button(QMessageBox.StandardButton.Yes).click())
        from trama_qt.source_link import unlink
        unlink(window, title)
        timer.stop()
        check(window.project.tables[title].source_link is None, "Unlink kept the link")
        window.actions["undo"].trigger()
        wait()
        check(window.project.tables[title].source_link is not None, "Undo did not link again")
        check(link_text("Update from file…") == ("Aggiorna da file…" if italian else "Update from file…"),
              "menu text")
    except Exception:  # noqa: BLE001 - the report says what broke.
        problems.append("stopped:\n" + traceback.format_exc())
    finally:
        for session in window.sessions:
            session.project.dirty = False
        window.close()
        app.processEvents()

    screen = app.primaryScreen()
    geometry = screen.availableGeometry()
    lines = [f"Source link smoke · {tag} · PySide6 {pyside} · platform {app.platformName()} · {sys.platform}",
             f"Screen {screen.name()}: available {geometry.width()}×{geometry.height()}, device pixel ratio "
             f"{screen.devicePixelRatio()}, logical DPI {screen.logicalDotsPerInch()}"
             + (f" (QT_SCALE_FACTOR={os.environ['QT_SCALE_FACTOR']}; scale override)"
                if "QT_SCALE_FACTOR" in os.environ else " (system scale)"),
             f"Window {window.width()}×{window.height()}", f"Screenshots: {len(shots)}",
             *(f"{name}: {seconds:.3f} s" for name, seconds in timings.items()), ""] + (problems or
                                                                                      ["No problems found."])
    (out / f"{tag}-report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = "FAIL" if problems else "PASS"
    (out / f"{tag}-status.txt").write_text(status + "\n", encoding="utf-8")
    print(f"Source link smoke {tag}: {status} ({out})")
    for problem in problems:
        print("  -", problem)
    return 0 if status == "PASS" else 1


def run_dedicated(folder, sizes=((1024, 768), (1600, 1000))):
    folder = Path(folder)
    failures = [main([str(folder / f"{language}-{mode}"), "--lang", language, "--theme", mode,
                      "--size", f"{width}x{height}"])
                for language in ("en", "it") for mode in ("light", "dark") for width, height in sizes]
    status = "FAIL" if any(failures) else "PASS"
    (folder / "status.txt").write_text(status + "\n", encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
