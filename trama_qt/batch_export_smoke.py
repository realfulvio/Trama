"""Acceptance of File → Export multiple figures…: ``python -m trama_qt.batch_export_smoke FOLDER``.

Opens the two-table fixture of the work package (``sessione.alab``, or ``--fixture PATH``), calculates
both XY graphs, builds a two-panel layout and exports the three figures as PNG, SVG and PDF into a
temporary folder, twice (the second run must suffix every name and leave the first files identical).
Runs in English and Italian, light and dark theme, and writes into FOLDER:

- ``<lang>-<theme>-batch-setup.png`` / ``-batch-summary.png`` / ``-batch-rerun.png``: the dialog;
- ``results.json``: per run the outcomes, the files and their measured size;
- ``report.txt`` and ``status.txt`` (``PASS`` or ``FAIL``), as ``python -m trama_qt --smoke``.

``check_in_smoke`` is the short pass that ``trama_qt.smoke`` runs on its own project.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

FIXTURE = {"version": 2, "tables": [
    {"title": title, "columns": ["Dose", "Response"], "kinds": ["numeric", "numeric"],
     "rows": [[1, a], [2, b], [4, c], [8, d], [16, e]], "formulas": [],
     "analyses": [["XY series", {"X": "Dose", "Y columns": ["Response"], "Drawing": "Line and points"}]],
     "excluded": [], "table_format": "xy", "graph_styles": {}}
    for title, (a, b, c, d, e) in (("Calibrazione $ A", (2.1, 3.2, 5.9, 8.2, 9.3)),
                                   ("Calibrazione B", (1.8, 3.1, 5.2, 7.7, 8.8)))], "layouts": []}


def check_in_smoke(smoke, window):
    """Inside ``python -m trama_qt --smoke``: the dialog opens on the smoke project, fits and is not clipped."""
    with smoke.dialogs("export-batch"):
        window.export_batch()


def measure(path):
    """Width and height in mm (vector) or pixels (PNG), read back with Pillow, ElementTree or PDFium."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".png":
        from PIL import Image
        with Image.open(path) as image:
            return {"pixels": list(image.size)}
    if suffix == ".svg":
        from xml.etree import ElementTree
        root = ElementTree.parse(path).getroot()
        values = []
        for key in ("width", "height"):
            raw = root.get(key, "")
            number = float(raw.rstrip("ptmx") or 0)
            values.append(round(number / 72 * 25.4 if raw.endswith("pt") else number, 2))
        return {"mm": values}
    import pypdfium2 as pdfium
    document = pdfium.PdfDocument(str(path))
    try:
        page = document[0]
        size = [round(value / 72 * 25.4, 2) for value in page.get_size()]
        page.close()
        return {"mm": size, "pages": len(document)}
    finally:
        document.close()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class BatchSmoke:
    def __init__(self, folder, fixture=None):
        from .smoke import Smoke
        self.base = Smoke(folder)  # Screenshots, fit and clipping checks, report.
        self.folder = Path(folder)
        self.fixture = fixture
        self.results = []

    @property
    def app(self):
        return self.base.app

    def wait(self, window, timeout=120):
        end = time.monotonic() + timeout
        while window.job is not None and time.monotonic() < end:
            self.app.processEvents()
            time.sleep(0.02)
        self.app.processEvents()
        if window.job is not None:
            raise RuntimeError("calculation still running")

    def open_project(self, window, scratch, language):
        from analisi.layout_geometry import AUTO_PAPER, WHITE
        from analisi.presentation import Layout
        path = scratch / "sessione.alab"
        if self.fixture:
            path.write_bytes(Path(self.fixture).read_bytes())
        else:
            path.write_text(json.dumps(FIXTURE), encoding="utf-8")
        window.open_path(path)
        self.wait(window)
        for index in range(len(window.project.runs)):
            window.open_sheet(("graph", index))
            self.wait(window)
        project = window.project
        if any(run.result is None or run.calculation_error for run in project.runs):
            raise RuntimeError("the fixture graphs were not calculated")
        project.put_layout(Layout("Figura 1" if language == "it" else "Figure 1", 2,
                                  [run.reference for run in project.runs], AUTO_PAPER, WHITE))
        project.dirty = False
        window.refresh()
        window.open_sheet(("data", next(iter(project.tables))))
        return project

    def run_dialog(self, window, out, fmt, shots):
        """Drive one export through the real dialog; ``shots`` names the screenshots (setup, summary)."""
        from .batch_export_dialog import BatchExportDialog
        seen = {}

        def drive(dialog):
            seen["dialog"] = dialog
            dialog.show()
            self.app.processEvents()
            dialog.format.setCurrentText(fmt.upper())
            dialog.width.setText("120")
            dialog.dpi.setText("150")
            dialog.folder.setText(str(out))
            dialog.refresh()
            if shots[0]:
                self.base.shot(dialog, shots[0])
            dialog.start_export()
            end = time.monotonic() + 180
            while dialog.running and time.monotonic() < end:
                self.app.processEvents()
                time.sleep(0.005)
            if dialog.running:
                raise RuntimeError("batch still running")
            self.base.shot(dialog, shots[1])
            dialog.accept()
            return 0

        original = BatchExportDialog.exec
        BatchExportDialog.exec = drive
        try:
            window.export_batch()
        finally:
            BatchExportDialog.exec = original
        dialog = seen.get("dialog")
        if dialog is None or dialog.outcomes is None:
            raise RuntimeError(f"{fmt}: the batch did not run")
        return dialog

    def run_language(self, language, dark):
        from analisi.i18n import set_language
        from . import export_options, theme
        from .window import MainWindow
        self.base.language = f"{language}-{'dark' if dark else 'light'}"
        set_language(language)
        theme.install_qt_translations(self.app, language)
        theme.apply(self.app, dark=dark)
        session = dict(export_options.SESSION)
        window = MainWindow()
        window.error = lambda error: self.base.problem(f"error shown: {error}")
        available = self.base.screen_rect(window)
        window.resize(min(1280, available.width()), min(800, available.height()))
        window.show()
        theme.keep_on_screen(window)
        self.app.processEvents()
        with tempfile.TemporaryDirectory(prefix="trama-batch-smoke-") as name:
            scratch = Path(name)
            try:
                project = self.open_project(window, scratch, language)
                before = (project.dirty, window.selected, project.history.can_apply())
                for fmt in ("png", "svg", "pdf"):
                    out = scratch / fmt
                    out.mkdir()
                    first = self.run_dialog(window, out, fmt, ("batch-setup" if fmt == "pdf" else None,
                                                               f"batch-summary-{fmt}" if fmt != "pdf"
                                                               else "batch-summary"))
                    files = {o.filename: digest(out / o.filename) for o in first.outcomes if o.status == "done"}
                    second = self.run_dialog(window, out, fmt, (None, "batch-rerun" if fmt == "pdf" else
                                                                f"batch-rerun-{fmt}"))
                    record = {"language": language, "theme": "dark" if dark else "light", "format": fmt,
                              "first": [[o.filename, o.status, o.reason] for o in first.outcomes],
                              "second": [[o.filename, o.status, o.reason] for o in second.outcomes],
                              "sizes": {o.filename: measure(out / o.filename) for o in first.outcomes
                                        if o.status == "done"},
                              "unchanged": all(digest(out / name) == value for name, value in files.items()),
                              "leftovers": sorted(p.name for p in out.iterdir() if p.name.startswith("."))}
                    self.results.append(record)
                    self.expect(record)
                after = (project.dirty, window.selected, project.history.can_apply())
                if after != before:
                    self.base.problem(f"project state changed by the export: {before} → {after}")
                # No configuration is left behind: a new project starts without the folder or a dirty flag.
                window.project.dirty = False
                window.new_project()
                self.app.processEvents()
                from .batch_export_dialog import BatchExportDialog
                fresh = BatchExportDialog(window, window.project, [], "")
                if fresh.folder.text():
                    self.base.problem("the next project inherited the export folder")
                fresh.deleteLater()
                if window.project.dirty or window.project.layouts:
                    self.base.problem("the next project is not empty")
                if export_options.SESSION != session:
                    self.base.problem("the batch changed the Export with options session settings")
            except Exception:  # noqa: BLE001 - the report must say what broke, then the next run goes on.
                self.base.problem("stopped:\n" + traceback.format_exc())
            finally:
                window.project.dirty = False
                window.close()
                window.deleteLater()
                self.app.processEvents()
                theme.apply(self.app, dark=False)

    def expect(self, record):
        fmt = record["format"]
        names = [row[0] for row in record["first"]]
        if [row[1] for row in record["first"]] != ["done"] * 3:
            self.base.problem(f"{fmt}: first run {record['first']}")
        if [row[1] for row in record["second"]] != ["done"] * 3 or not all(
                Path(row[0]).stem.endswith(" (2)") for row in record["second"]):
            self.base.problem(f"{fmt}: second run {record['second']}")
        if not record["unchanged"]:
            self.base.problem(f"{fmt}: a file of the first run changed")
        if record["leftovers"]:
            self.base.problem(f"{fmt}: temporary files left {record['leftovers']}")
        for name in names:
            size = record["sizes"].get(name, {})
            if fmt == "png":
                wanted = round(120 * 150 / 25.4)
                if size.get("pixels", [0])[0] != wanted:
                    self.base.problem(f"{fmt}: {name} is {size} instead of {wanted} px wide")
            elif abs(size.get("mm", [0])[0] - 120) > 0.5:
                self.base.problem(f"{fmt}: {name} is {size} instead of 120 mm wide")
            if fmt == "pdf" and size.get("pages") != 1:
                self.base.problem(f"{fmt}: {name} has {size.get('pages')} pages")

    def finish(self):
        (self.folder / "results.json").write_text(json.dumps(self.results, indent=1, ensure_ascii=False) + "\n",
                                                  encoding="utf-8")
        return self.base.report()


def run(folder, languages=("en", "it"), themes=(False, True), fixture=None):
    from analisi.i18n import active_language, set_language
    smoke = BatchSmoke(folder, fixture)
    previous = active_language()
    try:
        for language in languages:
            for dark in themes:
                smoke.run_language(language, dark)
    finally:
        set_language(previous)
        from . import theme
        theme.install_qt_translations(smoke.app, previous)
    return smoke.finish()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("folder", type=Path)
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--languages", default="en,it")
    parser.add_argument("--themes", default="light,dark")
    args = parser.parse_args(argv)
    os.environ.setdefault("MPLBACKEND", "QtAgg")
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from . import theme
    theme.load_fonts()
    theme.apply(app)
    status = run(args.folder, tuple(args.languages.split(",")),
                 tuple(name == "dark" for name in args.themes.split(",")), args.fixture)
    print(f"Batch export smoke: {status} ({args.folder})")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
