"""Desktop acceptance of the data labels of the observations in the Graph Inspector, with screenshots.

    python -m trama_qt.observation_labels_smoke OUT [--lang en|it] [--theme light|dark]

Run it on a real screen or on a virtual one (``xvfb-run -a -s '-screen 0 1024x768x24' ...``) and, for 150 %,
with ``QT_SCALE_FACTOR=1.5`` on a screen of 1536×1152 pixels (``-screen 0 1536x1152x24``), which Qt sees as 1024×768
logical pixels. The scale is emulated, not a native DPI setting; the report says so.

It uses a temporary preferences folder and ``tests/data/observation_labels/etichette-osservazioni.alab`` (rows 1 and
2 are two points at the same coordinates, row 4 has no Y, row 5 has no label and the label of row 6 is excluded). On
the real window it opens the Graph Inspector on the scatter plot, chooses the column of the labels, checks the preview
and Cancel, picks the overlapping points with a real mouse click and hides the label of the second one, applies (one
commit), saves and reopens the project, exports PNG/SVG/PDF of the figure and of a layout (the selection ring must
not be in them), excludes the label of a row, moves the hidden row, deletes it and inserts an identical one (the
setting must be suspended with a message, never given to the new row), deletes the label column and creates another
one with the same name (the source stays missing until it is chosen again) and shows the graphs that cannot be
labelled. Every step is checked. ``OUT`` receives PNG screenshots, the exports, the reproducible
``casi-etichette-applicate.alab`` (labels applied, the second identical point hidden), ``casi-riga-sostituita.alab``
and ``casi-colonna-mancante.alab``, ``report.txt`` (platform, screen, scale, problems) and ``status.txt``
(PASS/FAIL).
"""
import argparse
from copy import deepcopy
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data" / "observation_labels" / "etichette-osservazioni.alab"
COLOR = "#aa2288"
CONTROL, XY = "scatter:1:Controllo", "xy:1:Y"
VISIBLE = ["Campione $1", "Campione $2", "Caffè"]
LABEL_COLUMN = 4


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="en")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefs = Path(tempfile.mkdtemp(prefix="trama-label-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    import matplotlib
    import matplotlib.pyplot as plt
    from PySide6 import __version__ as pyside
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QScrollArea
    import numpy as np

    from analisi import observation_labels as ol
    from analisi import point_style as ps
    from analisi.i18n import set_language
    from analisi.presentation import Layout
    set_language(args.lang)
    app = QApplication.instance() or QApplication(["trama-label-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.project import Project, compute
    from trama_qt.window import MainWindow, export_graph

    problems, shots = [], []
    tag = f"{args.lang}-{args.theme}"
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

    window = MainWindow()
    errors = []
    window.error = lambda error: errors.append(str(error))
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

    def open_project(path):
        window.open_path(path)
        settle()
        wait()

    def figure_of(slot=0):
        return window.project.runs[slot].result.figure

    def texts(slot=0, key=None):
        return [text for series, text in ol.label_texts(figure_of(slot)) if key in (None, series)]

    def pixels_of(path, color, tolerance=0.15):
        image = plt.imread(str(path))
        target = np.array(matplotlib.colors.to_rgb(color))
        return int(np.sum(np.all(np.abs(image[..., :3] - target) < tolerance, axis=-1)))

    def canvas_click(canvas, x, y):
        """A real mouse click at data coordinates (x, y) of the first axes."""
        px, py = canvas.figure.axes[0].transData.transform((x, y))
        ratio = getattr(canvas, "device_pixel_ratio", 1) or 1
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(round(px / ratio), round((canvas.figure.bbox.height - py) / ratio)))
        settle()

    def open_inspector():
        """The Inspector stays wanted between pages: open it only when it is not open."""
        if window.inspector is None:
            window.toggle_inspector()
        settle()
        return window.inspector

    def close_inspector():
        if window.inspector is not None:
            window.inspector.cancel_button.click()
        settle()

    def show_section(inspector, widget=None):
        widget = widget or inspector.labels.reset_selected_button
        for scroll in inspector.findChildren(QScrollArea):
            scroll.ensureWidgetVisible(widget)
            scroll.ensureWidgetVisible(inspector.labels.source)
        settle()

    def choose(inspector, caption):
        combo = inspector.labels.source
        for number in range(combo.count()):
            if combo.itemText(number) == caption:
                combo.setCurrentIndex(number)
                settle()
                return True
        problems.append(f"no source {caption!r} in {[combo.itemText(n) for n in range(combo.count())]}")
        return False

    def goto_graph(slot=0):
        window.open_sheet(("graph", slot))
        wait()

    def goto_data():
        window.open_sheet(("data", title))
        wait()
        settle()

    commits, copies = [], []

    def watch(project):
        """Count the styles that Apply stores in ``project``."""
        project.dirty = False
        original = project.commit_style

        def counting(run, style, **kwargs):
            commits.append(deepcopy(style))
            return original(run, style, **kwargs)

        project.commit_style = counting

    def reopen(path):
        """Open the saved file as a new project. (A path that is already open only shows its tab: open a copy.)"""
        copy = work / f"reopened-{len(copies) + 1}" / Path(path).name
        copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, copy)
        copies.append(copy)
        before = window.project
        open_project(copy)
        check(window.project is not before, "the file was not opened as a new project")
        watch(window.project)

    try:
        work = Path(tempfile.mkdtemp(prefix="trama-label-work-"))
        # -- the project of the package, with a histogram added -----------------------------------------------
        project = Project()
        title = project.load(DATA)[0]
        run = project.candidate(title, "Histogram", {"Response": "Y", "Bins": 3})
        project.add_result(run, compute(run, project.tables[title].frame(mask_excluded=True)))
        for run in project.runs:
            if run.result is None:
                run.result = compute(run, project.tables[title].frame(mask_excluded=True))
        base = work / "casi.alab"
        project.save(base)
        open_project(base)
        watch(window.project)

        goto_graph(0)
        run = window.project.runs[0]
        figure = run.result.figure
        axes = figure.axes[0]
        before_limits = (axes.get_xlim(), axes.get_ylim())
        shot(window, "graph")
        inspector = open_inspector()
        check(inspector is not None, "the Inspector did not open")
        labels = inspector.labels
        show_section(inspector)
        captions = [labels.source.itemText(number) for number in range(labels.source.count())]
        check(captions[1:] == (["Titoli delle righe"] if italian else ["Row titles"]) + ["X", "Y", "Gruppo", "Etichetta"],
              f"sources {captions}")
        check(not labels.color.row.isEnabled() and not labels.mode.isEnabled(), "fields enabled without a source")
        shot(window, "inspector-section")

        # -- the column of the labels: preview, then Cancel ---------------------------------------------------
        check(choose(inspector, "Etichetta"), "source not chosen")
        check(texts() == VISIBLE, f"preview texts {texts()}")
        check(texts(key="scatter:1:Trattamento") == [], "labels for the group without text")
        check(commits == [] and run.style is None, "a preview was saved")
        check([text.get_text() for text in axes.get_legend().get_texts()] == ["Controllo", "Trattamento"],
              "legend changed")
        check((axes.get_xlim(), axes.get_ylim()) == before_limits, "limits changed")
        shot(window, "preview")
        close_inspector()
        check(window.inspector is None and texts() == [] and window.project.runs[0].style is None,
              "Cancel did not restore the graph")
        shot(window, "cancelled")

        # -- the duplicate point: a real click, hide the label of the second one -----------------------------------
        inspector = open_inspector()
        labels, points = inspector.labels, inspector.points
        canvas = window.page.canvases[0]
        choose(inspector, "Etichetta")
        labels.color.setText(COLOR)
        labels.color.editingFinished.emit()
        settle()
        check(texts() == VISIBLE, "both labels of the identical points are expected before hiding one")
        canvas_click(canvas, 1, 2)
        check(len(points.candidates) == 2 and points.near.count() == 2, "the click did not offer both rows")
        points.near.setCurrentIndex(1)
        check(labels.mode.isEnabled() and ("2" in labels.point_info.text()), labels.point_info.text())
        show_section(inspector, labels.mode)
        shot(window, "duplicate-selected")
        labels.mode.set("hide")
        settle()
        check(texts() == ["Campione $1", "Caffè"], f"hiding one of the identical points: {texts()}")
        check(labels.listing.count() == 1, "list of observations")
        check(commits == [] and window.project.runs[0].style is None, "the draft was saved")
        shot(window, "duplicate-hidden")

        inspector.apply_button.click()
        settle()
        run = window.project.runs[0]
        check(len(commits) == 1 and run.style and len(run.style[ol.LABELS]) == 1, "Apply did not save once")
        check(window.project.dirty, "the project is not marked as changed")
        check(run.style[ol.LABELS][0]["observations"][0]["show"] is False, "the override is not in the style")
        shot(window, "applied")

        # -- save, reopen -------------------------------------------------------------------------------------------
        saved = work / "etichette-applicate.alab"
        window.project.save(saved)
        reopen(saved)
        goto_graph(0)
        run = window.project.runs[0]
        check(run.style and run.style[ol.LABELS][0]["from"]["name"] == "Etichetta", "reopened style")
        check(texts() == ["Campione $1", "Caffè"], f"reopened texts {texts()}")
        check([item.state for item in ol.label_statuses(figure_of())] == ["ok"], "reopened status")
        shot(window, "reopened")

        # -- exports: figure and layout, no selection ring ---------------------------------------------------------
        inspector = open_inspector()
        inspector.points.view.setCurrentIndex(inspector.points.model.index(1))
        figure = figure_of()
        check(getattr(figure.axes[0], ps.INDICATOR_ATTR, None) is not None, "ring not shown for the export test")
        for suffix in ("png", "svg", "pdf"):
            export_graph(figure, out / f"{tag}-figure.{suffix}")
        svg = (out / f"{tag}-figure.svg").read_text(encoding="utf-8")
        check(COLOR in svg.lower() and ps.INDICATOR_COLOR not in svg.lower(), "figure SVG label color or ring")
        check("Campione" in svg and "Caff" in svg, "figure SVG has no label text")
        layout = Layout("Pagina", 1, [(run.title, run.slot)])
        window.project.layouts.append(layout)
        for suffix in ("png", "svg", "pdf"):
            window.project.export_layout(layout, out / f"{tag}-layout.{suffix}")
        layout_svg = (out / f"{tag}-layout.svg").read_text(encoding="utf-8")
        check(COLOR in layout_svg.lower() and ps.INDICATOR_COLOR not in layout_svg.lower(), "layout SVG color or ring")
        check((out / f"{tag}-figure.pdf").read_bytes().startswith(b"%PDF")
              and (out / f"{tag}-layout.pdf").read_bytes().startswith(b"%PDF"), "PDF not written")
        check(pixels_of(out / f"{tag}-figure.png", COLOR) > 40, "figure PNG without the labels")
        check(pixels_of(out / f"{tag}-layout.png", COLOR) > 20, "layout PNG without the labels")
        check(pixels_of(out / f"{tag}-figure.png", ps.INDICATOR_COLOR, 0.02) == 0, "the ring is in the PNG export")
        window.project.layouts.remove(layout)
        close_inspector()

        # -- an excluded label cell ---------------------------------------------------------------------------------
        goto_data()
        window.sheet.select_block(2, LABEL_COLUMN, 2, LABEL_COLUMN, current_row=2, current_col=LABEL_COLUMN)
        window.toggle_exclusion()
        wait()
        goto_graph(0)
        check(texts() == ["Campione $1"], f"excluded label cell: {texts()}")
        shot(window, "excluded")
        goto_data()
        window.sheet.select_block(2, LABEL_COLUMN, 2, LABEL_COLUMN, current_row=2, current_col=LABEL_COLUMN)
        window.toggle_exclusion()
        wait()
        goto_graph(0)
        check(texts() == ["Campione $1", "Caffè"], f"label cell included again: {texts()}")

        # -- rows reordered: the hidden label stays on its row -----------------------------------------------------
        goto_data()
        window.sheet.select_block(1, 0, 1, 0, current_row=1, current_col=0)
        window.move_rows(1, 2, 6)  # Campione $2 goes to the end
        wait()
        goto_graph(0)
        run = window.project.runs[0]
        check(texts() == ["Campione $1", "Caffè"], f"after the reorder: {texts()}")
        check([item.state for item in ol.label_statuses(figure_of())[0].observations] == ["ok"], "override after the reorder")
        check(not run.result.style_warning, "a warning after the reorder")
        shot(window, "reordered")

        # -- delete that row and insert an identical one ------------------------------------------------------------
        goto_data()
        window.sheet.select_block(5, 0, 5, 0, current_row=5, current_col=0)
        window.delete_rows()
        wait()
        goto_data()
        window.sheet.setCurrentIndex(window.sheet.model().index(1, 0))
        window.insert_row()
        wait()
        for column, text in enumerate(("Riga $α", "1", "2", "Controllo", "Campione $2")):
            window.edit_cell(title, 1, column, text)
            wait()
        goto_graph(0)
        run = window.project.runs[0]
        status = ol.label_statuses(figure_of())[0]
        check([(item.state, item.reason) for item in status.observations] == [("suspended", "not_found")],
              f"override of a deleted row: {status}")
        check(texts() == VISIBLE, f"the new identical row must not inherit the override: {texts()}")
        check(bool(run.result.style_warning), "no message for the suspended setting")
        check(run.style and run.style[ol.LABELS][0].get("observations"), "the setting was lost")
        shot(window, "replaced-row")
        window.project.save(out / "casi-riga-sostituita.alab")
        inspector = open_inspector()
        labels = inspector.labels
        show_section(inspector)
        check(labels.listing.count() == 1 and not labels.listing.item(0).icon().isNull(), "suspended setting not listed")
        labels.listing.setCurrentRow(0)
        check(labels.reset_selected_button.isEnabled(), "a suspended setting cannot be reset")
        shot(window, "replaced-row-inspector")
        close_inspector()

        # -- delete the label column and create another one with the same name ----------------------------------
        goto_data()
        window.sheet.select_block(0, LABEL_COLUMN, 5, LABEL_COLUMN, current_row=0, current_col=LABEL_COLUMN)
        window.delete_columns()
        wait()
        goto_graph(0)
        status = ol.label_statuses(figure_of())[0]
        check((status.state, status.reason) == ("suspended", "missing"), f"deleted column: {status}")
        check(texts() == [] and bool(window.project.runs[0].result.style_warning), "labels of a deleted column")
        shot(window, "column-deleted")
        window._apply_edit(title, lambda: window.project.insert_column(title, LABEL_COLUMN, "Etichetta"))
        wait()
        for row, text in enumerate(("Nuovo $1", "Nuovo $2", "Nuovo", "-", "Quinto", "Sesto", "Settimo")):
            if row < len(window.project.tables[title].raw):
                window.project.edit_cell(title, row, LABEL_COLUMN, text)
        window.project.save(out / "casi-colonna-mancante.alab")
        reopen(out / "casi-colonna-mancante.alab")
        goto_graph(0)
        check(ol.label_statuses(figure_of())[0].reason == "missing", "the column was reconnected by its name")
        check(texts() == [], "labels drawn from a column that only has the same name")
        inspector = open_inspector()
        labels = inspector.labels
        show_section(inspector)
        check("Etichetta" in labels.source.currentText() and labels.source.currentIndex() > 0
              and labels.source.currentData() == -1, f"missing source shown as {labels.source.currentText()!r}")
        shot(window, "column-missing-inspector")
        check(choose(inspector, "Etichetta"), "no explicit choice offered")
        check(texts() == ["Nuovo $1", "Nuovo $2", "Nuovo"], f"explicit choice: {texts()}")
        shot(window, "column-chosen-again")
        close_inspector()

        # -- graphs that cannot be labelled ---------------------------------------------------------------------
        goto_graph(2)
        inspector = open_inspector()
        labels = inspector.labels
        show_section(inspector)
        check(not labels.reason.isHidden() and labels.reason.text(), "no reason for an unsupported graph")
        check(not labels.source.isEnabled(), "source enabled on an unsupported graph")
        shot(window, "unsupported")
        close_inspector()

        # -- XY series ----------------------------------------------------------------------------------------------
        goto_graph(1)
        inspector = open_inspector()
        labels = inspector.labels
        check(inspector.points.series.key == XY, "XY series not selected")
        choose(inspector, "Titoli delle righe" if italian else "Row titles")
        check(texts(1, XY)[:3] == ["Riga $α", "Riga $α", "Terza"], f"XY labels {texts(1, XY)}")
        show_section(inspector)
        shot(window, "xy-series")
        close_inspector()
        check(errors == [], f"errors shown: {errors}")
        (out / "casi-etichette-applicate.alab").write_bytes(saved.read_bytes())
    except Exception:  # noqa: BLE001 - the report says what broke.
        problems.append("stopped:\n" + traceback.format_exc())
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()

    screen = app.primaryScreen()
    geometry = screen.availableGeometry()
    lines = [f"Observation labels smoke · {tag} · PySide6 {pyside} · platform {app.platformName()} · {sys.platform}",
             f"Screen {screen.name()}: available {geometry.width()}×{geometry.height()}, device pixel ratio "
             f"{screen.devicePixelRatio()}, logical DPI {screen.logicalDotsPerInch()}"
             + (f" (QT_SCALE_FACTOR={os.environ['QT_SCALE_FACTOR']}; scale override)"
                if "QT_SCALE_FACTOR" in os.environ else " (system scale)"),
             f"Window {window.width()}×{window.height()}", f"Commits made by Apply: {len(commits)}",
             f"Screenshots: {len(shots)}", ""] + (problems or ["No problems found."])
    (out / f"{tag}-report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = "FAIL" if problems else "PASS"
    (out / f"{tag}-status.txt").write_text(status + "\n", encoding="utf-8")
    print(f"Observation labels smoke {tag}: {status} ({out})")
    for problem in problems:
        print("  -", problem)
    return 0 if status == "PASS" else 1


def run_dedicated(folder):
    folder = Path(folder)
    failures = [main([str(folder / f"{language}-{mode}"), "--lang", language, "--theme", mode])
                for language in ("en", "it") for mode in ("light", "dark")]
    status = "FAIL" if any(failures) else "PASS"
    (folder / "status.txt").write_text(status + "\n", encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
