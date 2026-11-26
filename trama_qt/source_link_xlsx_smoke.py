"""Desktop acceptance of worksheets linked to a sheet of an .xlsx workbook, with screenshots.

    python -m trama_qt.source_link_xlsx_smoke OUT [--lang en|it] [--theme light|dark] [--size 1024x768]

Run it on a real screen or on a virtual one (``xvfb-run -a -s '-screen 0 1600x1000x24' ...``) and, for 150 %, with
``QT_SCALE_FACTOR=1.5`` on a screen of 1536×1152 pixels (1024×768 logical pixels). The scale is emulated, not a
native DPI setting; the report says so.

It uses a temporary preferences folder and the synthetic workbooks of ``tests/data/source_link_xlsx``. Every dialog
runs with its real ``exec`` and is driven like a person would: File → Import data… on ``iniziale.xlsx`` with the
sheet ``Misure`` (``Riepilogo`` is a decoy with the same columns), Link to the source file and the key ``ID``,
confirmed with Enter; a linear regression (slope 2); File → Source link… showing the sheet; B edited to 50 and the
workbook replaced by ``aggiornato.xlsx``; the conflict of B decided with the keyboard (Alt+N, Alt+P, Enter) to give
``atteso-progetto.csv``; Undo and Redo; ``duplicato.xlsx`` and ``formula-senza-cache.xlsx`` refused with Apply off;
``rinominato.xlsx`` with the explicit choice of ``Misure 2027``; save, move project and workbook together, reopen;
F1. The workbook's SHA-256 and modification time are checked after every reading. ``OUT`` receives PNG
screenshots, ``casi-excel-collegato.alab`` with its ``misure.xlsx`` (reopenable: the link is relative),
``report.txt`` and ``status.txt`` (PASS/FAIL).
"""
import argparse
import csv
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data" / "source_link_xlsx"


def _expected(name):
    with (DATA / name).open(encoding="utf-8", newline="") as handle:
        return [[row[0], int(row[1]), int(row[2])] for row in list(csv.reader(handle))[1:]]


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
    prefs = Path(tempfile.mkdtemp(prefix="trama-xlsx-link-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    from PySide6 import __version__ as pyside
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from analisi.i18n import set_language
    set_language(args.lang)
    app = QApplication.instance() or QApplication(["trama-xlsx-link-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.shortcuts_dialog import ShortcutsDialog
    from trama_qt.source_link import SourceLinkDialog, UpdatePreviewDialog
    from trama_qt.workbook_link import WorkbookImportDialog
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
                if widget.isVisible():
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
    book = work / "misure.xlsx"
    shutil.copyfile(DATA / "iniziale.xlsx", book)

    def fingerprint():
        return hashlib.sha256(book.read_bytes()).hexdigest(), book.stat().st_mtime_ns

    def use(fixture):
        shutil.copyfile(DATA / fixture, book)
        return fingerprint()

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

    def rows():
        raw = window.project.tables[title].raw
        return [[key, int(dose), int(response)] for key, dose, response in
                zip(raw["ID"], raw["Dose"], raw["Response"])]

    def preview(act, *, count=1):
        seen = {}
        timers = []

        def look(dialog):
            seen.setdefault("summary", dialog.summary.text())
            seen["enabled"] = dialog.apply_button.isEnabled()
            act(dialog, seen)
            if len(timers) < count:  # Another preview follows (another sheet chosen here).
                timers.append(when_modal(UpdatePreviewDialog, look))

        timers.append(when_modal(UpdatePreviewDialog, look))
        started = time.perf_counter()
        window.actions["refresh_source"].trigger()
        wait()
        wait()
        for timer in timers:
            timer.stop()
        seen["seconds"] = time.perf_counter() - started
        return seen

    title = None
    try:
        # -- File → Import data… on a workbook: the sheet by name, the link and the key ------------------------------
        def import_linked(dialog):
            def wait_for_preview():
                until = time.monotonic() + 20
                while dialog.loading and time.monotonic() < until:
                    app.processEvents()
                    time.sleep(.01)
                if dialog.loading:
                    raise TimeoutError("The selected Excel sheet is still being read.")

            wait_for_preview()
            sheets = [dialog.sheet_box.itemText(index) for index in range(dialog.sheet_box.count())]
            check(sheets == ["Riepilogo", "Misure"], f"sheets in workbook order {sheets}")
            dialog.set_choice("Misure", 1)
            wait_for_preview()
            dialog.link.setChecked(True)
            dialog.set_key("ID")
            dialog.sheet_box.setFocus()
            settle()
            check(dialog.import_button.isDefault() and dialog.import_button.isEnabled(), "Import is not default")
            shot(dialog, "import-sheet")
            QTest.keyClick(dialog.sheet_box, Qt.Key.Key_Tab)  # Tab moves on; Enter still imports.
            QTest.keyClick(app.focusWidget(), Qt.Key.Key_Return)

        timer = when_modal(WorkbookImportDialog, import_linked)
        window.open_path(book, import_data=True)
        wait()
        timer.stop()
        title = window._active_table()
        link = window.project.tables[title].source_link if title else None
        check(link is not None and link.sheet == "Misure", "the import did not link the sheet Misure")
        candidate = window.project.candidate(title, "Linear regression", {"X": "Dose", "Y": "Response"})
        window.calculate_candidate(candidate, window.project.tables[title].frame(), None)
        wait()
        check(abs(slope() - 2.0) < 1e-12, f"initial slope {slope()}")
        window.show_sheet("data", title)
        shot(window, "linked-worksheet")

        # -- File → Source link…: the sheet is readable ---------------------------------------------------------------
        def look_link(dialog):
            from PySide6.QtWidgets import QLabel
            labels = [label.text() for label in dialog.findChildren(QLabel)]
            check("Foglio Excel" in labels if italian else "Excel sheet" in labels, "no Excel sheet row")
            check("Misure" in labels, "the sheet name is not shown")
            shot(dialog, "source-link")
            dialog.reject()

        timer = when_modal(SourceLinkDialog, look_link)
        window.actions["source_link"].trigger()
        settle()
        timer.stop()

        # -- the package case: B edited here and in the file, decided with the keyboard --------------------------------
        window.project.edit_cell(title, 1, 2, "50")
        window.reshow()
        before = use("aggiornato.xlsx")

        def decide(dialog, seen):
            panel = dialog.conflicts
            seen["open"] = dialog.apply_button.isEnabled()
            panel.table.setFocus()
            shot(dialog, "preview-conflict")
            QTest.keyClick(app.focusWidget(), Qt.Key.Key_S if italian else Qt.Key.Key_N,
                           Qt.KeyboardModifier.AltModifier)
            QTest.qWait(200)
            QTest.keyClick(app.focusWidget(), Qt.Key.Key_P, Qt.KeyboardModifier.AltModifier)
            QTest.qWait(200)
            seen["decided"] = [dialog.apply_button.isEnabled(), dialog.apply_button.isDefault()]
            shot(dialog, "preview-decided")
            QTest.keyClick(app.focusWidget(), Qt.Key.Key_Return)

        seen = preview(decide)
        timings["preview and apply (package case)"] = seen["seconds"]
        check(seen.get("open") is False and seen.get("decided") == [True, True], f"conflict decision {seen}")
        check(rows() == _expected("atteso-progetto.csv"), f"Keep the project gave {rows()}")
        check(fingerprint() == before, "the workbook changed")
        shot(window, "updated")
        window.actions["undo"].trigger()
        wait()
        check([row[0] for row in rows()] == ["A", "B", "C", "D"], f"Undo: {rows()}")
        window.actions["redo"].trigger()
        wait()
        check(rows() == _expected("atteso-progetto.csv"), f"Redo: {rows()}")

        # -- refused workbooks: Apply off, Enter applies nothing -------------------------------------------------------
        for fixture, expected, name in (("duplicato.xlsx", "ripete B" if italian else "repeats B", "duplicate"),
                                        ("formula-senza-cache.xlsx", "C2", "formula")):
            before = use(fixture)
            raw = window.project.tables[title].raw

            def blocked(dialog, seen, name=name):
                seen["blocked"] = dialog.blocked.text()
                shot(dialog, f"preview-{name}")
                QTest.keyClick(dialog, Qt.Key.Key_Return)
                settle()
                dialog.reject()

            seen = preview(blocked)
            check(not seen.get("enabled"), f"{fixture}: Apply is on")
            check(expected in seen.get("blocked", ""), f"{fixture}: blocked {seen.get('blocked')!r}")
            check(window.project.tables[title].raw is raw, f"{fixture} changed the worksheet")
            check(fingerprint() == before, f"{fixture}: the workbook changed")

        # -- renamed sheet: the explicit choice of another one ---------------------------------------------------------
        before = use("rinominato.xlsx")

        def choose_sheet(dialog, seen):
            if dialog.sheet_choice is not None:
                seen["missing"] = dialog.blocked.text()
                dialog.sheet_choice.setCurrentIndex(dialog.sheet_choice.findData("Misure 2027"))
                shot(dialog, "preview-renamed-sheet")
                dialog.read_sheet.click()
            else:
                seen["second"] = dialog.apply_button.isEnabled()
                shot(dialog, "preview-other-sheet")
                QTest.keyClick(dialog, Qt.Key.Key_Return)

        seen = preview(choose_sheet, count=2)
        check(("non ha più il foglio Misure" if italian else "no longer has the sheet Misure") in seen.get("missing", ""),
              f"renamed: {seen.get('missing')!r}")
        check(seen.get("second") is True, "the chosen sheet could not be applied")
        check(window.project.tables[title].source_link.sheet == "Misure 2027",
              f"sheet after the choice {window.project.tables[title].source_link.sheet}")
        check(fingerprint() == before, "rinominato: the workbook changed")

        # -- save, move project and workbook together, reopen ---------------------------------------------------------
        saved = work / "casi-excel-collegato.alab"
        window.project.save(saved)
        shutil.copyfile(saved, out / "casi-excel-collegato.alab")
        shutil.copyfile(book, out / "misure.xlsx")
        window.project.dirty = False
        moved = out / f"{tag}-moved"
        shutil.rmtree(moved, ignore_errors=True)
        shutil.copytree(work, moved)
        shutil.rmtree(work)
        book = moved / "misure.xlsx"
        window.open_path(moved / "casi-excel-collegato.alab")
        wait()
        title = next(name for name, dataset in window.project.tables.items() if dataset.source_link is not None)
        check(window.project.tables[title].source_link.sheet == "Misure 2027", "sheet name after reopening")
        check(rows() == _expected("atteso-progetto.csv"), f"reopened rows {rows()}")

        def relative(dialog, seen):
            seen["before"] = dialog.apply_button.isEnabled()
            dialog.use_file.setChecked(True)
            seen["after"] = dialog.apply_button.isEnabled()
            shot(dialog, "preview-moved-project")
            dialog.accept()

        seen = preview(relative)
        check(seen.get("before") is False and seen.get("after") is True, f"moved project {seen}")
        check(errors == [], f"errors shown: {errors}")
        window.project.dirty = False

        shortcuts_opened = []

        def close_shortcuts(dialog):
            shortcuts_opened.append(dialog.windowTitle())
            dialog.reject()

        window.activateWindow()
        window.sheet.setFocus()
        settle()
        timer = when_modal(ShortcutsDialog, close_shortcuts)
        QTest.keyClick(window.sheet, Qt.Key.Key_F1)
        settle()
        timer.stop()
        check(bool(shortcuts_opened), "F1 did not open the shortcuts dialog")
    except Exception:  # noqa: BLE001 - the report says what broke.
        problems.append("stopped:\n" + traceback.format_exc())
    finally:
        for session in window.sessions:
            session.project.dirty = False
        window.close()
        app.processEvents()

    screen = app.primaryScreen()
    geometry = screen.availableGeometry()
    lines = [f"Excel source link smoke · {tag} · PySide6 {pyside} · platform {app.platformName()} · {sys.platform}",
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
    print(f"Excel source link smoke {tag}: {status} ({out})")
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
