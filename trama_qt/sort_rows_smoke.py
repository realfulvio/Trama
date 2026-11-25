"""Desktop acceptance smoke for Edit -> Sort rows and quick sort actions (IT/EN, 1024x768 and 150%).

    python -m trama_qt.sort_rows_smoke OUT [--lang en|it] [--theme light|dark] [--fixture PATH]
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent


def _fallback_fixture_bytes() -> bytes:
    return json.dumps({
        "version": 2,
        "tables": [{
            "title": "Ordine delle osservazioni",
            "columns": ["Row title", "X", "Y", "Campione"],
            "kinds": ["text", "numeric", "numeric", "text"],
            "rows": [
                ["Zeta", 3, 7, "Z-1"],
                ["alpha", 1, 2, "A-1"],
                ["Beta $", 2, 4, "B-1"],
                ["ALPHA", 1, 2, "A-2"],
                [None, None, 5, "VUOTO"],
                ["delta", 0, 9, "D"],
                ["beta $", 2, 10, "B-2"],
            ],
            "formulas": [],
            "analyses": [["XY series", {"X": "X", "Y columns": ["Y"]}]],
            "excluded": [[3, 2]],
            "table_format": "multivariable",
            "graph_styles": {},
            "row_heights": [[3, 40]],
            "cell_backgrounds": [[3, "Y", "#d4e4f6"]],
            "text_styles": [["Y", 3, 4, {"size": 14, "color": "#245b9a", "bold": True}]],
        }],
        "layouts": [],
    }).encode("utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="it")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    parser.add_argument("--fixture", type=Path, default=None)
    args = parser.parse_args(argv)

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefs = Path(tempfile.mkdtemp(prefix="trama-sort-rows-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    from PySide6 import __version__ as pyside
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from analisi.i18n import set_language
    set_language(args.lang)

    app = QApplication.instance() or QApplication(["trama-sort-rows-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.project import Project, compute
    from trama_qt.sort_rows_dialog import SortRowsDialog
    from trama_qt.window import MainWindow

    problems, shots = [], []
    tag = f"{args.lang}-{args.theme}"
    window = None

    def check(condition, text):
        if not condition:
            problems.append(text)

    def settle():
        for _ in range(100):
            app.processEvents()
            if window is None or getattr(window, "job", None) is None:
                break
            time.sleep(0.02)
        for _ in range(4):
            app.processEvents()
            time.sleep(0.01)

    def shot(widget, name):
        settle()
        frame = widget.frameGeometry()
        available = (widget.screen() or app.primaryScreen()).availableGeometry()
        check(
            frame.width() <= available.width() and frame.height() <= available.height(),
            f"{name}: {frame.width()}x{frame.height()} exceeds {available.width()}x{available.height()}",
        )
        file_path = out / f"{tag}-{name}.png"
        widget.grab().save(str(file_path))
        shots.append(str(file_path))

    work_dir = Path(tempfile.mkdtemp(prefix="trama-sort-rows-work-"))
    fixture_path = args.fixture if args.fixture is not None else (work_dir / "ordine-righe.alab")
    if args.fixture is None:
        fixture_path.write_bytes(_fallback_fixture_bytes())

    window = MainWindow()
    window.resize(1024, 720)
    window.show()
    settle()

    try:
        window.open_path(fixture_path)
        settle()
        project = window.project
        title = next(iter(project.tables))
        ds = project.tables[title]
        window.show_sheet("data", title)
        settle()

        # Select tracked row "A-2" (0-based row 3, col 3) before sorting.
        window.sheet.select_block(3, 3, 3, 3, current_row=3, current_col=3)
        shot(window, "01-initial")

        # Open Sort rows dialog cleanly, shoot it, accept X Ascending.
        dialog = SortRowsDialog(window, project, title, ds, initial_column=1)
        shot_taken = []

        def _capture_and_accept():
            if not shot_taken:
                shot_taken.append(1)
                shot(dialog, "02-sort-dialog")
                dialog.accept()

        QTimer.singleShot(40, _capture_and_accept)
        dialog.exec()
        plan = dialog.plan
        dialog.deleteLater()
        check(plan is not None, "dialog produced no sort plan")
        window._apply_row_sort(title, plan=plan)
        settle()

        check(ds.raw["Campione"].tolist() == ["D", "A-1", "A-2", "B-1", "B-2", "Z-1", "VUOTO"],
              f"unexpected X ascending order: {ds.raw['Campione'].tolist()}")
        check(window.sheet.currentIndex().row() == 2 and window.sheet.currentIndex().column() == 3,
              f"cursor did not follow A-2: {(window.sheet.currentIndex().row(), window.sheet.currentIndex().column())}")
        shot(window, "03-sorted-x-ascending")

        # Quick sort by row title ascending (casefold).
        window.sort_by_row_title()
        settle()
        check(ds.raw["Campione"].tolist() == ["A-1", "A-2", "B-1", "B-2", "D", "Z-1", "VUOTO"],
              f"unexpected row title order: {ds.raw['Campione'].tolist()}")
        shot(window, "04-sorted-row-title")

        # Undo twice back to initial order and verify metadata restored, then redo once for reopenable .alab.
        window.undo()
        settle()
        window.undo()
        settle()
        check(ds.raw["Campione"].tolist() == ["Z-1", "A-1", "B-1", "A-2", "VUOTO", "D", "B-2"],
              "undo did not restore initial order")
        shot(window, "05-after-undo")

        window.undo(redo=True)
        settle()
        saved_alab = out / "ordine-righe-collaudo.alab"
        project.save(saved_alab)
        reopened = Project()
        reopened.load(saved_alab)
        check(reopened.tables[title].raw["Campione"].tolist() == ["D", "A-1", "A-2", "B-1", "B-2", "Z-1", "VUOTO"],
              "saved .alab did not preserve sorted order")
    except Exception:
        problems.append(traceback.format_exc())
    finally:
        window.project.dirty = False
        window.close()

    report = {
        "lang": args.lang,
        "theme": args.theme,
        "pyside6": pyside,
        "screen": f"{app.primaryScreen().geometry().width()}x{app.primaryScreen().geometry().height()}",
        "scale_factor": os.environ.get("QT_SCALE_FACTOR", "1"),
        "shots": shots,
        "problems": problems,
    }
    (out / f"{tag}-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
