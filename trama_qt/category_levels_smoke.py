"""Dedicated Qt smoke for category level renaming/merging (IT/EN, 1024x768 & 1600x1000, light & dark)."""

import argparse
import os
from pathlib import Path
import sys
import time
import traceback

os.environ.setdefault("MPLBACKEND", "QtAgg")

import pandas as pd  # noqa: E402
from PySide6 import __version__ as PYSIDE_VERSION  # noqa: E402
from PySide6.QtCore import Qt, qVersion  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QAbstractButton, QWidget  # noqa: E402

from analisi.category_levels import LevelEditDraft  # noqa: E402
from analisi.category_order import WORKSHEET_ORDERS, set_order  # noqa: E402
from analisi.i18n import set_language, tr  # noqa: E402


class CategoryLevelsSmoke:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.app = QApplication.instance()
        self.problems = []
        self.notes = []
        self.language = "en"

    def note(self, text):
        self.notes.append(f"[{self.language}] {text}")

    def expect(self, condition, text):
        if not condition:
            self.problems.append(f"[{self.language}] {text}")
        return bool(condition)

    def _pump(self, seconds=0.08):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.01)

    def _check_widget(self, widget, name, *, max_width=None, max_height=None):
        screen = widget.screen() or self.app.primaryScreen()
        avail = screen.availableGeometry()
        frame = widget.frameGeometry()
        client = QWidget.size(widget)
        chrome_w = max(0, frame.width() - client.width())
        chrome_h = max(0, frame.height() - client.height())
        limit_w = max_width + chrome_w if max_width is not None else avail.width()
        limit_h = max_height + chrome_h if max_height is not None else avail.height()
        desktop = self.app.platformName() != "offscreen"
        if desktop:
            limit_w, limit_h = min(limit_w, avail.width()), min(limit_h, avail.height())
        if max_width is not None or desktop:
            self.expect(
                frame.width() <= limit_w and frame.height() <= limit_h,
                f"{name}: {frame.width()}x{frame.height()} exceeds {limit_w}x{limit_h}",
            )
        for child in widget.findChildren(QWidget):
            if not child.isVisibleTo(widget) or QWidget.width(child) <= 0:
                continue
            if isinstance(child, QAbstractButton) and child.text():
                needed = child.minimumSizeHint().width()
            elif isinstance(child, QLabel) and child.text() and not child.wordWrap() and child.pixmap().isNull():
                needed = child.minimumSizeHint().width()
            else:
                continue
            self.expect(
                QWidget.width(child) + 1 >= needed,
                f"{name}: '{child.text()}' width {QWidget.width(child)} < needed {needed}",
            )

    def _dpi_info(self, widget):
        screen = widget.screen() or self.app.primaryScreen()
        handle = widget.windowHandle()
        win_dpr = handle.devicePixelRatio() if handle is not None else widget.devicePixelRatioF()
        return (
            f"logicalDpi=({screen.logicalDotsPerInchX():.1f}, {screen.logicalDotsPerInchY():.1f}) "
            f"physicalDpi=({screen.physicalDotsPerInchX():.1f}, {screen.physicalDotsPerInchY():.1f}) "
            f"screenDPR={screen.devicePixelRatio():.2f} windowDPR={win_dpr:.2f}"
        )

    def _shot(self, widget, name, *, max_width=None, max_height=None):
        self._pump(0.1)
        self._check_widget(widget, name, max_width=max_width, max_height=max_height)
        path = self.folder / f"{name}.png"
        ok = widget.grab().save(str(path))
        self.expect(ok and path.exists() and path.stat().st_size > 0, f"failed screenshot {path.name}")

    def run_pass(self, lang, width, height, *, dark):
        from . import theme
        from .category_order import CategoryOrderDialog
        from .window import MainWindow

        self.language = lang
        mode_tag = "dark" if dark else "light"
        tag = f"{lang}-{width}x{height}-{mode_tag}"
        set_language(lang)
        theme.STATE["mode"] = mode_tag
        theme.apply(self.app)

        window = MainWindow()
        try:
            window.resize(width, height)
            window.show()
            self._pump(0.1)
            if self.app.platformName() != "offscreen":
                theme.keep_on_screen(window)

            df = pd.DataFrame({
                "Gruppo": pd.Series(["A", "B", "A", None, "Controllo $", "Procès"], dtype="string"),
                "Valore": [10.0, 14.0, 12.0, 8.0, 9.0, 16.0],
            })
            title, = window.project.add_tables({"Studio": df})
            set_order(window.project.tables[title], "Gruppo", ["str:Controllo $", "str:B", "str:A", "str:Procès"])
            window.open_sheet(("data", title))
            window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
            self._pump(0.08)

            self.note(f"{tag}: {self._dpi_info(window)}")
            self.expect(window.actions["category_order"].isEnabled(), f"{tag}: category_order action disabled")

            draft = LevelEditDraft(window.project.tables[title], "Gruppo")
            dialog = CategoryOrderDialog(
                window,
                "Gruppo",
                draft,
                check_recipes=lambda plan: window.project.category_level_blockers(title, plan),
                confirm_merge=lambda merges: True,
            )
            dialog.show()
            self._pump(0.08)
            self.note(f"{tag}-dialog: {self._dpi_info(dialog)} size={dialog.width()}x{dialog.height()}")

            # Verify initial row order and counts
            self.expect(dialog.table.rowCount() == 4, f"{tag}: expected 4 rows, got {dialog.table.rowCount()}")
            self.expect(dialog.table.item(2, 1).text() == "2", f"{tag}: expected count 2 for A")

            # Filter and validate empty name -> must restore filter, show error banner, and select invalid field
            dialog.table.item(2, 2).setText("")
            dialog.search.setText("Procès")
            self._pump(0.05)
            dialog.accept()
            self._pump(0.05)
            self.expect(dialog.problem.isVisible(), f"{tag}: error banner not shown on empty name")
            self.expect(dialog.table.currentRow() == 2 and dialog.table.currentColumn() == 2,
                        f"{tag}: invalid field not selected ({dialog.table.currentRow()}, {dialog.table.currentColumn()})")
            self._shot(dialog, f"{tag}-validation-error", max_width=width, max_height=height)

            # Fix into merge (A, B -> Risposta) and apply
            dialog.table.item(1, 2).setText("Risposta")
            dialog.table.item(2, 2).setText("Risposta")
            dialog.accept()
            self.expect(dialog.plan is not None, f"{tag}: merge plan missing after confirm")
            if dialog.plan is not None:
                window._apply_edit(title, lambda: window.project.apply_category_levels(title, dialog.plan))
            self._pump(0.08)
            self._shot(window, f"{tag}-applied", max_width=width, max_height=height)

            ds = window.project.tables[title]
            self.expect(
                ds.raw.attrs[WORKSHEET_ORDERS]["Gruppo"] == ["str:Controllo $", "str:Risposta", "str:Procès"],
                f"{tag}: unexpected order {ds.raw.attrs.get(WORKSHEET_ORDERS)}",
            )
            dialog.deleteLater()
        finally:
            window.project.dirty = False
            window.close()
            self._pump(0.05)


def run_smoke(folder, *, sizes=((1024, 768), (1600, 1000))):
    app = QApplication.instance() or QApplication(sys.argv[:1])
    smoke = CategoryLevelsSmoke(folder)
    smoke.note(f"Qt={qVersion()} PySide6={PYSIDE_VERSION} platform={app.platformName()}")
    try:
        for lang in ("en", "it"):
            for dark in (False, True):
                for width, height in sizes:
                    smoke.run_pass(lang, width, height, dark=dark)
    except Exception:
        smoke.problems.append(traceback.format_exc())
    status = "PASS" if not smoke.problems else "FAIL"
    report_lines = [*smoke.notes, "", f"STATUS: {status}", *smoke.problems]
    (Path(folder) / "report.txt").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    (Path(folder) / "status.txt").write_text(status + "\n", encoding="utf-8")
    print("\n".join(report_lines))
    return 0 if status == "PASS" else 1


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("folder")
    args = parser.parse_args(argv)
    return run_smoke(args.folder)


if __name__ == "__main__":
    raise SystemExit(main())
