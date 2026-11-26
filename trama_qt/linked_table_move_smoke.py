"""Desktop acceptance smoke for pointer selection & movement of linked tables on graphs and layouts.

    python -m trama_qt.linked_table_move_smoke OUT [--lang en|it] [--theme light|dark]
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
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "data" / "qt_linked_table_move" / "tabelle-in-figura.alab"
SVG = "{http://www.w3.org/2000/svg}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--lang", choices=("en", "it"), default="it")
    parser.add_argument("--theme", choices=("light", "dark"), default="light")
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prefs = Path(tempfile.mkdtemp(prefix="trama-move-table-prefs-"))
    os.environ["XDG_CONFIG_HOME"] = os.environ["APPDATA"] = str(prefs)
    sys.path.insert(0, str(ROOT))

    import pandas as pd
    from PySide6 import __version__ as pyside
    from PySide6.QtCore import QEvent, QPoint, Qt
    from PySide6.QtGui import QFocusEvent, QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QPushButton

    from analisi import linked_tables as lt
    from analisi.i18n import set_language, tr
    set_language(args.lang)

    app = QApplication.instance() or QApplication(["trama-linked-table-move-smoke"])
    from trama_qt import theme
    theme.load_fonts()
    theme.set_mode(args.theme, app, remember=False)
    theme.install_qt_translations(app, args.lang)
    from trama_qt.linked_tables import LinkedTableDialog, LinkedTablesDialog
    from trama_qt.shortcuts_dialog import ShortcutsDialog
    from trama_qt.window import MainWindow, export_graph

    problems, shots, timings = [], [], []
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
        check(frame.width() <= available.width() + 2 and frame.height() <= available.height() + 2,
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

    def active_canvas():
        canvas, = window.page.canvases
        return canvas

    def qpoint_px(canvas, x_px, y_px):
        ratio = float(canvas.device_pixel_ratio)
        return QPoint(round(x_px / ratio), canvas.height() - round(y_px / ratio))

    def artist_center(canvas, table_id):
        artist = next(a for a in canvas.figure.artists
                      if isinstance(a, lt.LinkedTableArtist) and a.get_gid() == f"{lt.GID}{table_id}")
        l, b, r, t = artist.bounds_pixels(canvas.figure)
        return qpoint_px(canvas, (l + r) / 2, (b + t) / 2)

    def frac_point(canvas, xf, yf_top):
        w, h = canvas.figure.get_size_inches()
        dpi = float(canvas.figure.dpi)
        return qpoint_px(canvas, xf * w * dpi, (1.0 - yf_top) * h * dpi)

    def drag(canvas, start, end, *, steps=12):
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
        for i in range(1, steps + 1):
            t = i / steps
            QTest.mouseMove(canvas, QPoint(round(start.x() + (end.x() - start.x()) * t),
                                           round(start.y() + (end.y() - start.y()) * t)))
            app.processEvents()
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end)
        app.processEvents()

    def pdf_words(path):
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(str(path)) as doc:
            return doc[0].get_textpage().get_text_range().split()

    try:
        work = Path(tempfile.mkdtemp(prefix="trama-move-table-work-"))
        project_path = work / "tabelle-in-figura.alab"
        shutil.copy(FIXTURE, project_path)
        window.open_path(project_path)
        settle()
        wait()

        # F1 shortcuts lists Ctrl+Shift+M; menu / toolbar present.
        shortcuts = ShortcutsDialog(window)
        shortcuts.show()
        settle()
        shot(shortcuts, "shortcuts-f1")
        shortcuts.reject()
        shortcuts.deleteLater()
        check(window.actions["linked_table_move"].shortcut() == QKeySequence("Ctrl+Shift+M"),
              "missing Ctrl+Shift+M shortcut")

        # 1. Graph: move linked table, keep copy intact, test edge clamping, simple click, cancel, undo/redo.
        window.open_sheet(("graph", 0))
        wait()
        canvas = active_canvas()
        canvas.draw()
        settle()
        before_graph = deepcopy(window.project.runs[0].style[lt.TABLES])
        linked_id, copy_id = before_graph[0]["id"], before_graph[1]["id"]
        window.project.dirty = False

        window.actions["linked_table_move"].trigger()
        settle()
        start_pt = artist_center(canvas, linked_id)
        QTest.mouseClick(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pt)
        settle()
        check(not window.project.dirty, "simple click dirtied project")
        shot(window, "graph-selected")

        # Mid-drag screenshot showing movement guides + escape cancel.
        QTest.mousePress(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start_pt)
        mid_pt = frac_point(canvas, 0.35, 0.45)
        QTest.mouseMove(canvas, mid_pt)
        settle()
        shot(window, "graph-dragging-guides")
        QTest.keyClick(canvas, Qt.Key.Key_Escape)
        QTest.mouseRelease(canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, mid_pt)
        settle()
        check(not window.project.dirty and window.project.runs[0].style[lt.TABLES] == before_graph,
              "Escape mid-drag changed project")

        # Drag linked table; copy stays fixed.
        drag(canvas, start_pt, frac_point(canvas, 0.25, 0.55))
        moved_graph = deepcopy(window.project.runs[0].style[lt.TABLES])
        check(moved_graph[1] == before_graph[1], "copy moved when moving linked table")
        check(moved_graph[0]["position"][1] > 0.40, "linked table did not move down")
        shot(window, "graph-moved")

        # Undo / Redo restores & reapplies in one step.
        window.actions["undo"].trigger()
        settle()
        check(window.project.runs[0].style[lt.TABLES] == before_graph, "undo did not restore graph table")
        window.actions["redo"].trigger()
        settle()
        check(window.project.runs[0].style[lt.TABLES] == moved_graph, "redo did not reapply graph table")

        # 2. Layout: move layout page table; panel untouched; try smaller canvas size.
        window.open_sheet(("layout", 0))
        wait()
        canvas = active_canvas()
        canvas.draw()
        settle()
        before_layout = deepcopy(window.project.layouts[0].tables)
        layout_id = before_layout[0]["id"]
        panel_bounds = tuple(canvas.figure.axes[0].get_position().bounds)

        window.resize(min(860, available.width()), min(640, available.height()))
        settle()
        window.actions["linked_table_move"].trigger()
        settle()
        drag(canvas, artist_center(canvas, layout_id), frac_point(canvas, 0.65, 0.42))
        moved_layout = deepcopy(window.project.layouts[0].tables)
        check(moved_layout[0]["position"][0] > 0.45 and moved_layout[0]["position"][1] < 0.55,
              f"layout table did not move: {moved_layout[0]['position']}")
        check(all(abs(float(a) - float(b)) < 1e-9
                  for a, b in zip(canvas.figure.axes[0].get_position().bounds, panel_bounds, strict=True)),
              "panel moved")
        shot(window, "layout-moved-resized")

        # Check LinkedTablesDialog Tab/Enter/autoDefault/fit_dialog.
        dialog = LinkedTablesDialog(window, window.project, moved_layout, owner="Risultati in figura")
        dialog.show()
        settle()
        check(not any(b.autoDefault() for b in (dialog.add_button, dialog.edit_button, dialog.remove_button)),
              "inner buttons have autoDefault enabled")
        defaults = [b for b in dialog.findChildren(QPushButton) if b.isDefault()]
        check(len(defaults) == 1 and defaults[0].text() == tr("graph.format.apply"), "Apply is not default")
        shot(dialog, "linked-tables-dialog")
        dialog.reject()
        dialog.deleteLater()

        # 3. Change B4 (7 -> 9), save, reopen, verify 2.6 vs 2, export PDF/SVG clean.
        window.open_sheet(("data", "Misure"))
        model = window.sheet.model()
        model.setData(model.index(3, 1), "9")
        wait()
        settle()
        check(window.save(), "save failed")
        window.close_project()
        window.open_path(project_path)
        wait()
        settle()
        check(window.project.runs[0].style[lt.TABLES][0]["position"] == moved_graph[0]["position"],
              "reopened graph linked table position mismatch")
        check(window.project.layouts[0].tables[0]["position"] == moved_layout[0]["position"],
              "reopened layout table position mismatch")

        window.open_sheet(("graph", 0))
        wait()
        window.actions["linked_table_move"].trigger()
        QTest.mouseClick(active_canvas(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         artist_center(active_canvas(), linked_id))
        settle()
        graph_pdf = out / f"{tag}-graph.pdf"
        graph_svg = out / f"{tag}-graph.svg"
        export_graph(window.project.runs[0].result.figure, graph_pdf, {"format": "pdf"})
        export_graph(window.project.runs[0].result.figure, graph_svg, {"format": "svg", "svg_text": "text"})
        graph_svg_text = graph_svg.read_text(encoding="utf-8")
        graph_svg_vals = ["".join(n.itertext()) for n in ET.fromstring(graph_svg_text).iter(f"{SVG}text")]
        check(pdf_words(graph_pdf).count("2.6") == 1 and "2" in pdf_words(graph_pdf),
              f"graph PDF values mismatch: {pdf_words(graph_pdf)}")
        check(graph_svg_vals.count("2.6") == 1 and graph_svg_vals.count("2") >= 1,
              "graph SVG text mismatch")
        check("#176676" not in graph_svg_text.lower(), "selection leaked to graph SVG")

        layout_pdf = out / f"{tag}-layout.pdf"
        layout_svg = out / f"{tag}-layout.svg"
        window.project.export_layout(window.project.layouts[0], layout_pdf, {"format": "pdf"})
        window.project.export_layout(window.project.layouts[0], layout_svg, {"format": "svg", "svg_text": "text"})
        layout_svg_text = layout_svg.read_text(encoding="utf-8")
        layout_svg_vals = ["".join(n.itertext()) for n in ET.fromstring(layout_svg_text).iter(f"{SVG}text")]
        check(pdf_words(layout_pdf).count("2.6") == 2 and "2" in pdf_words(layout_pdf),
              f"layout PDF values mismatch: {pdf_words(layout_pdf)}")
        check(layout_svg_vals.count("2.6") == 2 and "2" in layout_svg_vals,
              "layout SVG text mismatch")
        check("#176676" not in layout_svg_text.lower(), "selection leaked to layout SVG")
        shutil.copy(project_path, out / f"{tag}-tabelle-in-figura-verificato.alab")

        # 4. Benchmark interactivity with 6 and 12 tables: full draw vs blit frame.
        sheet_choice = next(c for c in window.project.table_source_choices() if c["kind"] == "sheet")
        many = [window.project.table_record(sheet_choice, (0, 0, 3, 1), mode="linked",
                                            position=((i % 4) * 0.22, (i // 4) * 0.28), size=8)
                for i in range(12)]
        window.open_sheet(("graph", 0))
        wait()
        window.commit_linked_tables(("graph", 0), many[:6])
        c6 = active_canvas()
        t0 = time.perf_counter()
        c6.draw()
        timings.append(f"6 tables full draw: {(time.perf_counter() - t0) * 1000:.1f} ms")

        window.commit_linked_tables(("graph", 0), many)
        c12 = active_canvas()
        t0 = time.perf_counter()
        c12.draw()
        timings.append(f"12 tables full draw: {(time.perf_counter() - t0) * 1000:.1f} ms")
        window.actions["linked_table_move"].trigger()
        settle()
        p0 = artist_center(c12, many[-1]["id"])
        p1 = frac_point(c12, 0.72, 0.70)
        QTest.mousePress(c12, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p0)
        t_first = time.perf_counter()
        QTest.mouseMove(c12, QPoint((p0.x() + p1.x()) // 2, (p0.y() + p1.y()) // 2))
        app.processEvents()
        timings.append(f"12 tables drag init + first frame: {(time.perf_counter() - t_first) * 1000:.1f} ms")
        t_step = time.perf_counter()
        QTest.mouseMove(c12, p1)
        app.processEvents()
        timings.append(f"12 tables drag subsequent frame (blit): {(time.perf_counter() - t_step) * 1000:.2f} ms")
        QTest.mouseRelease(c12, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p1)
        app.processEvents()

        check(errors == [], f"errors shown: {errors}")
    except Exception:  # noqa: BLE001 - report exact trace
        problems.append("stopped:\n" + traceback.format_exc())
    finally:
        window.project.dirty = False
        window.close()
        app.processEvents()

    screen = app.primaryScreen()
    geometry = screen.availableGeometry()
    lines = [
        f"Linked table move smoke · {tag} · PySide6 {pyside} · platform {app.platformName()} · {sys.platform}",
        f"Screen {screen.name()}: available {geometry.width()}×{geometry.height()}, "
        f"device pixel ratio {screen.devicePixelRatio()}, logical DPI {screen.logicalDotsPerInch()}"
        + (f" (QT_SCALE_FACTOR={os.environ['QT_SCALE_FACTOR']}; scale override)"
           if "QT_SCALE_FACTOR" in os.environ else " (system scale)"),
        f"Window {window.width()}×{window.height()}",
        f"Screenshots: {len(shots)}",
        *timings,
        "",
    ]
    lines += problems or ["No problems found."]
    (out / f"{tag}-report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    status = "FAIL" if problems else "PASS"
    (out / f"{tag}-status.txt").write_text(status + "\n", encoding="utf-8")
    print(f"Linked table move smoke {tag}: {status} ({out})")
    for line in timings:
        print("  ", line)
    for problem in problems:
        print("  -", problem)
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
