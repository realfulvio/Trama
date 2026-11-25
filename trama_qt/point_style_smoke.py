"""Desktop acceptance of the formatting of single points in the Graph Inspector, with screenshots.

    python -m trama_qt.point_style_smoke OUT [--lang en|it] [--theme light|dark]

Run it on a real screen or on a virtual one (``xvfb-run -a -s '-screen 0 1024x768x24' ...``) and, for 150 %,
with ``QT_SCALE_FACTOR=1.5`` on a screen of 1536×1152 pixels (``-screen 0 1536x1152x24``), which Qt sees as 1024×768
logical pixels. The scale is emulated, not a native DPI setting; the report says so.

It uses a temporary preferences folder and the synthetic table in ``tests/data/point_style`` (rows 1 and 2 are
identical). On the real window it opens the Graph Inspector on a scatter plot with groups, picks the overlapping
points with a real mouse click and chooses the second one, formats it, checks the preview, Apply (one commit),
Cancel, reset, saves and reopens the project, exports PNG/SVG/PDF of the figure and of a layout, inserts an identical
row before the point (the style must be suspended with a message, never given to another row), and shows a graph
that cannot be formatted. Every step is checked. ``OUT`` receives PNG screenshots, the exports, the reproducible
``casi-punti-formattati.alab`` (row 2 formatted) and ``casi-inserimento-ambiguo.alab`` (an identical row inserted
before it, the style suspended), ``report.txt`` (platform, screen, scale, problems) and ``status.txt`` (PASS/FAIL).
"""
import argparse
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import time
import traceback

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "tests" / "data" / "point_style" / "casi.csv"
COLOR = "#ac4320"
KEY = "scatter:1:C"
SCATTER = "Scatter / confidence ellipse"
RECIPE = {"X": "X", "Y": "Y", "Group": "Group"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="en")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefs = Path(tempfile.mkdtemp(prefix="trama-point-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    import matplotlib
    import matplotlib.pyplot as plt
    from PySide6 import __version__ as pyside
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QScrollArea
    import numpy as np

    from analisi import point_style as ps
    from analisi.i18n import set_language
    from analisi.presentation import Layout
    set_language(args.lang)
    app = QApplication.instance() or QApplication(["trama-point-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.project import Project, compute
    from trama_qt.window import MainWindow, export_graph

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

    def overlays(figure):
        return [child for child in figure.axes[0].get_children() if str(child.get_gid() or "").startswith(ps.GID_PREFIX)]

    def hex_colors(figure):
        return [matplotlib.colors.to_hex(line.get_markerfacecolor()) for line in overlays(figure)]

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

    def show_section(inspector):
        for scroll in inspector.findChildren(QScrollArea):
            scroll.ensureWidgetVisible(inspector.points.reset_selected_button)
            scroll.ensureWidgetVisible(inspector.points.view)
        settle()

    commits = []
    try:
        work = Path(tempfile.mkdtemp(prefix="trama-point-work-"))
        # -- the project: a scatter with groups, an XY series with points, a histogram ----------------------
        project = Project()
        title = project.load(DATA)[0]
        for method, recipe in ((SCATTER, RECIPE),
                               ("XY series", {"X": "X", "Y columns": ["Y"], "Series style": {"Y": "Line and points"}}),
                               ("Histogram", {"Response": "Y", "Bins": 3})):
            run = project.candidate(title, method, dict(recipe))
            result = compute(run, project.tables[title].frame(mask_excluded=True))
            project.add_result(run, result)
        base = work / "casi.alab"
        project.save(base)
        open_project(base)
        window.project.dirty = False
        original = window.project.commit_style

        def counting(run, style, **kwargs):
            commits.append(deepcopy(style))
            return original(run, style, **kwargs)

        window.project.commit_style = counting

        window.open_sheet(("graph", 0))
        wait()
        run = window.project.runs[0]
        figure = run.result.figure
        before_limits = (figure.axes[0].get_xlim(), figure.axes[0].get_ylim())
        shot(window, "graph")
        inspector = open_inspector()
        check(inspector is not None, "the Inspector did not open")
        points = inspector.points
        canvas = window.page.canvases[0]
        show_section(inspector)
        check(points.model.rowCount() == 3 and points.series.key == KEY, "list of observations")
        check(not points.color.row.isEnabled(), "fields enabled before any selection")
        shot(window, "inspector-section")

        # -- a real click on the overlapping rows 1 and 2 -------------------------------------------------
        canvas_click(canvas, 1, 2)
        check(len(points.candidates) == 2 and points.near.count() == 2, "the click did not offer both rows")
        check(not points.near.isHidden(), "overlap chooser hidden")
        check("row 1" in points.info.text() or "riga 1" in points.info.text(), points.info.text())
        ring = getattr(figure.axes[0], ps.INDICATOR_ATTR, None)
        check(ring is not None, "no selection ring")
        shot(window, "click-overlap")
        points.near.setCurrentIndex(1)
        check("2" in points.info.text(), "second row not selected")

        # -- format, preview, apply ---------------------------------------------------------------------------
        points.color.setText(COLOR)
        points.color.editingFinished.emit()
        points.marker.set("Square")
        points.size.setText("9")
        points.size.editingFinished.emit()
        settle()
        check(commits == [] and run.style is None, "a preview was saved")
        check(hex_colors(figure) == [COLOR], f"preview colors {hex_colors(figure)}")
        check([text.get_text() for text in figure.axes[0].get_legend().get_texts()] == ["C", "T"], "legend changed")
        check((figure.axes[0].get_xlim(), figure.axes[0].get_ylim()) == before_limits, "limits changed")
        check(points.styled.count() == 1, "formatted list")
        shot(window, "preview")
        close_inspector()
        check(window.inspector is None and overlays(window.project.runs[0].result.figure) == []
              and window.project.runs[0].style is None, "Cancel did not restore the graph")
        shot(window, "cancelled")

        inspector = open_inspector()
        points = inspector.points
        figure = window.project.runs[0].result.figure
        canvas = window.page.canvases[0]
        canvas_click(canvas, 1, 2)
        points.near.setCurrentIndex(1)
        points.color.setText(COLOR)
        points.color.editingFinished.emit()
        points.marker.set("Square")
        points.size.setText("9")
        points.size.editingFinished.emit()
        inspector.apply_button.click()
        settle()
        run = window.project.runs[0]
        check(len(commits) == 1 and run.style and len(run.style[ps.POINTS]) == 1, "Apply did not save once")
        check(window.project.dirty, "the project is not marked as changed")
        shot(window, "applied")

        # -- save, reopen --------------------------------------------------------------------------------------
        saved = work / "styled.alab"
        window.project.save(saved)
        open_project(saved)
        window.open_sheet(("graph", 0))
        wait()
        run = window.project.runs[0]
        check(run.style and run.style[ps.POINTS][0]["source"]["row"] == 2, "reopened style")
        figure = run.result.figure
        check(hex_colors(figure) == [COLOR], "reopened graph does not show the point")
        check([item.state for item in ps.point_statuses(figure)] == ["ok"], "reopened status")
        shot(window, "reopened")

        # -- exports: figure and layout ------------------------------------------------------------------------
        inspector = open_inspector()
        inspector.points.view.setCurrentIndex(inspector.points.model.index(1))
        check(getattr(figure.axes[0], ps.INDICATOR_ATTR, None) is not None, "ring not shown for the export test")
        for suffix in ("png", "svg", "pdf"):
            export_graph(figure, out / f"{tag}-figure.{suffix}")
        svg = (out / f"{tag}-figure.svg").read_text(encoding="utf-8")
        check(COLOR in svg.lower() and ps.INDICATOR_COLOR not in svg.lower(), "figure SVG color or ring")
        layout = Layout("Pagina", 1, [(run.title, run.slot)])
        window.project.layouts.append(layout)
        for suffix in ("png", "svg", "pdf"):
            window.project.export_layout(layout, out / f"{tag}-layout.{suffix}")
        layout_svg = (out / f"{tag}-layout.svg").read_text(encoding="utf-8")
        check(COLOR in layout_svg.lower() and ps.INDICATOR_COLOR not in layout_svg.lower(), "layout SVG color or ring")
        check((out / f"{tag}-figure.pdf").read_bytes().startswith(b"%PDF")
              and (out / f"{tag}-layout.pdf").read_bytes().startswith(b"%PDF"), "PDF not written")
        pixels = plt.imread(str(out / f"{tag}-figure.png"))
        wanted = np.array(matplotlib.colors.to_rgb(COLOR))
        check(int(np.sum(np.all(np.abs(pixels[..., :3] - wanted) < 0.02, axis=-1))) > 20, "figure PNG without the color")
        ring = np.array(matplotlib.colors.to_rgb(ps.INDICATOR_COLOR))
        check(int(np.sum(np.all(np.abs(pixels[..., :3] - ring) < 0.02, axis=-1))) == 0, "the ring is in the PNG export")
        window.project.layouts.remove(layout)
        close_inspector()

        # -- reset ---------------------------------------------------------------------------------------------
        inspector = open_inspector()
        points = inspector.points
        points.styled.setCurrentRow(0)
        check(points.reset_selected_button.isEnabled(), "reset disabled for a formatted point")
        points.reset_selected_button.click()
        settle()
        check(ps.POINTS not in inspector.draft and overlays(inspector.figure) == [], "reset did not clear the point")
        shot(window, "reset")
        close_inspector()
        check(hex_colors(window.project.runs[0].result.figure) == [COLOR], "Cancel after reset lost the point")

        # -- an identical row inserted before the point ----------------------------------------------------------
        window.open_sheet(("data", title))
        settle()
        window.sheet.setCurrentIndex(window.sheet.model().index(0, 0))
        window.insert_row()
        wait()
        for column, text in enumerate(("1", "2", "C")):
            window.edit_cell(title, 0, column, text)
            wait()
        window.open_sheet(("graph", 0))
        wait()
        run = window.project.runs[0]
        statuses = ps.point_statuses(run.result.figure)
        check([(item.state, item.reason) for item in statuses] == [("suspended", "ambiguous")], f"statuses {statuses}")
        check(overlays(run.result.figure) == [], "a row took the style of another one")
        check(bool(run.result.style_warning), "no message for the suspended style")
        check(run.style and run.style.get(ps.POINTS), "the record was lost")
        shot(window, "ambiguous-message")
        window.project.save(out / "casi-inserimento-ambiguo.alab")
        inspector = open_inspector()
        points = inspector.points
        show_section(inspector)
        check(points.styled.count() == 1 and not points.styled.item(0).icon().isNull(), "suspended record not listed")
        points.styled.setCurrentRow(0)
        check(points.reset_selected_button.isEnabled(), "a suspended point cannot be reset")
        shot(window, "ambiguous-inspector")
        close_inspector()

        # Replacing the original styled row can leave the values and count unchanged.
        window.open_sheet(("data", title))
        wait()
        window.sheet.setCurrentIndex(window.sheet.model().index(2, 0))
        window.delete_rows()
        wait()
        window.open_sheet(("graph", 0))
        wait()
        run = window.project.runs[0]
        check(not overlays(run.result.figure) and ps.point_statuses(run.result.figure)[0].state == "suspended",
              "the replacement row received the style")
        shot(window, "replaced-row")
        window.project.save(out / "casi-riga-sostituita.alab")

        # -- a graph that cannot be formatted ---------------------------------------------------------------
        window.open_sheet(("graph", 2))
        wait()
        inspector = open_inspector()
        points = inspector.points
        show_section(inspector)
        check(not points.reason.isHidden() and points.reason.text(), "no reason for an unsupported graph")
        check(not points.view.isEnabled(), "list enabled on an unsupported graph")
        shot(window, "unsupported")
        close_inspector()

        # -- XY series ----------------------------------------------------------------------------------------
        window.open_sheet(("graph", 1))
        wait()
        inspector = open_inspector()
        points = inspector.points
        canvas = window.page.canvases[0]
        check(points.series.key == "xy:1:Y", "XY series not selected")
        canvas_click(canvas, 2, 4)
        points.color.setText(COLOR)
        points.color.editingFinished.emit()
        check(len(overlays(inspector.figure)) == 1, "XY point not drawn")
        show_section(inspector)
        shot(window, "xy-series")
        close_inspector()
        check(errors == [], f"errors shown: {errors}")
        (out / "casi-punti-formattati.alab").write_bytes(saved.read_bytes())
    except Exception:  # noqa: BLE001 - the report says what broke.
        problems.append("stopped:\n" + traceback.format_exc())
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()

    screen = app.primaryScreen()
    geometry = screen.availableGeometry()
    lines = [f"Single point smoke · {tag} · PySide6 {pyside} · platform {app.platformName()} · {sys.platform}",
             f"Screen {screen.name()}: available {geometry.width()}×{geometry.height()}, device pixel ratio "
             f"{screen.devicePixelRatio()}, logical DPI {screen.logicalDotsPerInch()}"
             + (f" (QT_SCALE_FACTOR={os.environ['QT_SCALE_FACTOR']}; scale override)"
                if "QT_SCALE_FACTOR" in os.environ else " (system scale)"),
             f"Window {window.width()}×{window.height()}", f"Commits made by Apply: {len(commits)}",
             f"Screenshots: {len(shots)}", ""] + (problems or ["No problems found."])
    (out / f"{tag}-report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = "FAIL" if problems else "PASS"
    (out / f"{tag}-status.txt").write_text(status + "\n", encoding="utf-8")
    print(f"Single point smoke {tag}: {status} ({out})")
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
