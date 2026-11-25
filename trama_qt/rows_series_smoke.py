"""Desktop acceptance smoke for worksheet row move/resize and Create numeric series (IT/EN, 1024x768 and 150%).

    python -m trama_qt.rows_series_smoke OUT [--lang en|it] [--theme light|dark] [--fixture PATH]
"""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_FIXTURE = {
    "version": 2,
    "tables": [{
        "title": "Serie XY",
        "columns": ["Row title", "X", "Segnale", "Controllo"],
        "kinds": ["text", "numeric", "numeric", "numeric"],
        "rows": [
            ["Campione A", 1, 3, 2],
            ["Campione B", 2, 6, 4],
            ["Campione B", 2, 6, 4],
            ["Campione C", 4, 12, 8],
            ["Campione D", 8, 24, 16],
        ],
        "formulas": [],
        "analyses": [["XY series", {"X": "X", "Y columns": ["Segnale", "Controllo"]}]],
        "excluded": [[2, 3]],
        "table_format": "xy",
        "graph_styles": {},
        "cell_backgrounds": [[2, "Segnale", "#bee3da"]],
    }],
    "layouts": [],
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="it")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--fixture", type=Path, default=None)
    args = parser.parse_args(argv)

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefs = Path(tempfile.mkdtemp(prefix="trama-rows-series-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    from PySide6 import __version__ as pyside
    from PySide6.QtCore import QPoint, QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QMenu

    from analisi import point_style as ps
    from analisi.i18n import set_language
    from analisi.numeric_series import GEOMETRIC
    set_language(args.lang)

    app = QApplication.instance() or QApplication(["trama-rows-series-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.numeric_series_dialog import NumericSeriesDialog
    from trama_qt.project import Project
    from trama_qt.window import MainWindow

    problems, shots = [], []
    tag = f"{args.lang}-{args.theme}"

    def check(condition, text):
        if not condition:
            problems.append(text)

    def settle():
        for _ in range(6):
            app.processEvents()
            time.sleep(0.02)

    def shot(widget, name):
        settle()
        frame = widget.frameGeometry()
        available = (widget.screen() or app.primaryScreen()).availableGeometry()
        check(frame.width() <= available.width() and frame.height() <= available.height(),
              f"{name}: {frame.width()}x{frame.height()} exceeds {available.width()}x{available.height()}")
        path = out / f"{tag}-{len(shots) + 1:02d}-{name}.png"
        check(widget.grab().save(str(path)), f"{name}: screenshot not written")
        shots.append(path.name)

    window = MainWindow()
    errors = []
    window.error = lambda err: errors.append(str(err))
    window._ask = lambda *a, error=None, **k: errors.append(f"calculation failed: {error}")
    available = (window.screen() or app.primaryScreen()).availableGeometry()
    window.resize(min(1024, available.width()), min(768, available.height()))
    window.show()
    app.processEvents()
    theme.keep_on_screen(window)

    def wait():
        end = time.monotonic() + 120
        while window.job is not None and time.monotonic() < end:
            app.processEvents()
            time.sleep(0.02)
        app.processEvents()

    try:
        work = Path(tempfile.mkdtemp(prefix="trama-rows-series-work-"))
        fixture_path = work / "fixture.alab"
        if args.fixture is not None:
            fixture_path.write_bytes(args.fixture.read_bytes())
        else:
            fixture_path.write_text(json.dumps(DEFAULT_FIXTURE), encoding="utf-8")

        window.open_path(fixture_path)
        settle()
        wait()
        title = "Serie XY"

        # 1. identita-riga: style row 3 of Segnale via Inspector observation list, then drag row 3 -> before row 1
        window.open_sheet(("graph", 0))
        wait()
        inspector = window.toggle_inspector() or window.inspector
        settle()
        points = inspector.points
        for i in range(inspector.selector.count()):
            if "Segnale" in inspector.selector.itemText(i):
                inspector.selector.setCurrentIndex(i)
                break
        settle()
        model = points.model
        row3_idx = next(
            i for i in range(model.rowCount())
            if "Row 3 " in model.data(model.index(i)) or "Riga 3 " in model.data(model.index(i))
        )
        points.view.setCurrentIndex(model.index(row3_idx))
        points.color.setText("#ac4320")
        points.color.editingFinished.emit()
        points.marker.set("Square")
        points.size.setText("9")
        points.size.editingFinished.emit()
        inspector.apply()
        settle()
        token_before = window.project.runs[0].style[ps.POINTS][0]["source"]["row_token"]
        inspector.cancel_button.click()
        settle()

        window.open_sheet(("data", title))
        settle()
        view = window.sheet
        header = view.verticalHeader()
        shot(window, "sheet-initial")

        # Drag row 3 (index 2) before row 1 (index 0), capturing insertion indicator mid-drag
        y_from = header.sectionViewportPosition(2) + header.sectionSize(2) // 2
        y_to = header.sectionViewportPosition(0) + 2
        QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_from))
        QTest.mouseMove(header.viewport(), QPoint(12, y_to))
        settle()
        check(header._mode == "move" and header._drop_row == 0, f"drop indicator expected 0, got {header._drop_row}")
        shot(window, "row-drag-indicator")
        QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_to))
        settle()
        wait()

        ds = window.project.tables[title]
        check(ds.raw["Row title"].tolist() == ["Campione B", "Campione A", "Campione B", "Campione C", "Campione D"],
              "identita-riga order mismatch")
        check(ds.excluded == {(0, 3)}, f"excluded expected D1 (0,3), got {ds.excluded}")
        check(ds.cell_backgrounds == {(0, "Segnale"): "#bee3da"}, f"bg expected C1, got {ds.cell_backgrounds}")
        check(ps.point_statuses(window.project.runs[0].result.figure)[0].state == "ok", "point style not ok after move")
        check(window.project.runs[0].style[ps.POINTS][0]["source"]["row_token"] == token_before, "token changed")
        shot(window, "row-moved")

        # Undo, Redo, Save and Reopen
        window.undo()
        wait()
        check(ds.excluded == {(2, 3)}, "undo did not restore D3")
        window.undo(redo=True)
        wait()
        check(ds.excluded == {(0, 3)}, "redo did not restore D1")

        # 2. altezza: resize row 1 (original row 3) at 100% zoom -> 0 recalcs, switch sheet, reopen, reset
        recalcs = []
        orig_refresh = window.refresh_runs

        def track_refresh(runs, **kw):
            recalcs.append(len(runs))
            return orig_refresh(runs, **kw)

        window.refresh_runs = track_refresh
        y_border = header.sectionViewportPosition(0) + header.sectionSize(0)
        QTest.mousePress(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_border))
        QTest.mouseMove(header.viewport(), QPoint(12, y_border + 22))
        QTest.mouseRelease(header.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_border + 22))
        settle()
        check(not recalcs, f"row resize triggered recalcs: {recalcs}")
        saved_h = ds.row_heights.get(0)
        check(saved_h is not None and saved_h >= 40, f"row height not stored: {ds.row_heights}")
        shot(window, "row-resized")

        window.open_sheet(("graph", 0))
        wait()
        shot(window, "graph-after-row-move")
        saved_alab = out / f"{tag}-risultato.alab"
        window.project.save(saved_alab)

        # Reopen saved .alab and verify height & point style persist
        window.open_path(saved_alab)
        wait()
        window.open_sheet(("data", title))
        settle()
        check(window.project.tables[title].row_heights.get(0) == saved_h, "height lost on reopen")
        check(window.sheet.verticalHeader().sectionSize(0) == saved_h, "visual height lost on reopen")

        # Reset height via vertical header context menu action
        window.refresh_runs = track_refresh
        window.sheet.selectRow(0)
        settle()
        window.actions["reset_row_height"].trigger()
        settle()
        check(not recalcs, "reset height triggered recalc")
        check(window.project.tables[title].row_heights == {}, "height not reset")
        window.refresh_runs = orig_refresh

        # 3. blocco: move rows 2-3 (indices 1..2) after row 5 -> [1,4,5,2,3] (relative to current)
        window.sheet.select_block(1, 0, 2, window.sheet.model().columnCount() - 1)
        settle()
        y_b_from = window.sheet.verticalHeader().sectionViewportPosition(1) + window.sheet.verticalHeader().sectionSize(1) // 2
        y_b_to = window.sheet.verticalHeader().sectionViewportPosition(4) + window.sheet.verticalHeader().sectionSize(4) - 2
        QTest.mousePress(window.sheet.verticalHeader().viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_b_from))
        QTest.mouseMove(window.sheet.verticalHeader().viewport(), QPoint(12, y_b_to))
        QTest.mouseRelease(window.sheet.verticalHeader().viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(12, y_b_to))
        settle()
        wait()

        # 4. aritmetica: on B2 (row 1, col 1), 5 values from 1 step -0,25 (or -0.25), capture dialog & cancel, then confirm
        step_arith = "-0,25" if args.lang == "it" else "-0.25"
        step_geo = "0,5" if args.lang == "it" else "0.5"
        window.sheet.select_block(1, 1, 1, 1)
        settle()
        before_x = list(window.project.tables[title].raw["X"])

        def drive_cancel():
            dlg = next(w for w in window.findChildren(NumericSeriesDialog) if w.isVisible())
            dlg.first.setText("1")
            dlg.count.setValue(5)
            dlg.step.setText(step_arith)
            settle()
            check(not dlg.ok_button.isEnabled(), "replace confirmation should be required")
            shot(dlg, "series-dialog-confirm")
            dlg.reject()

        QTimer.singleShot(50, drive_cancel)
        window.create_numeric_series()
        settle()
        check(list(window.project.tables[title].raw["X"]) == before_x, "cancel modified X")

        def drive_arith():
            dlg = next(w for w in window.findChildren(NumericSeriesDialog) if w.isVisible())
            dlg.first.setText("1")
            dlg.count.setValue(5)
            dlg.step.setText(step_arith)
            dlg.confirm_replace.setChecked(True)
            settle()
            check(dlg.ok_button.isEnabled(), "ok button still disabled after confirm")
            dlg.ok_button.click()

        QTimer.singleShot(50, drive_arith)
        window.create_numeric_series()
        wait()
        check(window.project.tables[title].raw["X"].tolist() == [window.project.tables[title].raw["X"].iloc[0], 1.0, 0.75, 0.5, 0.25, 0.0],
              f"arithmetic mismatch: {window.project.tables[title].raw['X'].tolist()}")

        # 5. geometrica: on B6 (row 5, col 1), 4 values from 16 ratio 0,5
        window.sheet.select_block(5, 1, 5, 1)
        settle()

        def drive_geo():
            dlg = next(w for w in window.findChildren(NumericSeriesDialog) if w.isVisible())
            dlg.mode.setCurrentIndex(dlg.mode.findData(GEOMETRIC))
            dlg.first.setText("16")
            dlg.count.setValue(4)
            dlg.step.setText(step_geo)
            dlg.confirm_replace.setChecked(True)
            settle()
            shot(dlg, "series-dialog-geometric")
            dlg.ok_button.click()

        QTimer.singleShot(50, drive_geo)
        window.create_numeric_series()
        wait()
        check(window.project.tables[title].raw["X"].tolist()[5:9] == [16.0, 8.0, 4.0, 2.0],
              f"geometric mismatch: {window.project.tables[title].raw['X'].tolist()}")
        shot(window, "sheet-after-series")

        # Save final re-openable .alab
        final_alab = out / f"{tag}-finale.alab"
        window.project.save(final_alab)
        reopened = Project()
        reopened.load(final_alab)
        check(reopened.tables[title].raw["X"].tolist()[5:9] == [16.0, 8.0, 4.0, 2.0], "final alab reopen failed")
        check(not errors, f"unexpected window errors: {errors}")

    except Exception as exc:
        problems.append(f"exception: {exc}\n{traceback.format_exc()}")
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()

    screen = app.primaryScreen()
    geo = screen.geometry()
    report = [
        f"platform: {sys.platform}",
        f"pyside6: {pyside}",
        f"lang: {args.lang}",
        f"theme: {args.theme}",
        f"screen_px: {geo.width()}x{geo.height()}",
        f"device_pixel_ratio: {screen.devicePixelRatio()}",
        f"qt_scale_factor: {os.environ.get('QT_SCALE_FACTOR', '1')}",
        f"shots: {shots}",
        f"problems: {problems}",
    ]
    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")
    status = "PASS" if not problems else "FAIL"
    (out / "status.txt").write_text(status + "\n", encoding="utf-8")
    print("\n".join(report))
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
