"""Desktop acceptance of the pointer drawing tools: open → draw → edit → copy/paste → undo/redo → save → reopen → export.

Called by ``trama_qt.smoke`` for each language. It builds a small synthetic project with one stored rectangle,
then drives the real graph canvas with ``QTest`` mouse and key events (sent to the widget, not through the
operating system pointer) and checks the confirmed model, the drawn artists, the three export formats and the
saved file. It writes ``canvas-<language>-*.png`` (light and dark palette) and the exports next to the report.

Problems go to ``Smoke.problem``; the first failed step of a language stops that language's canvas run.
"""
import json
from pathlib import Path
import re
from unittest import mock

import numpy as np
import pandas as pd
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog

from analisi.axis_breaks import AXIS_BREAKS, segment_axes
from analisi.data import Dataset, save_project
from analisi.graph_shapes import SHAPES
from analisi.i18n import tr

from . import theme

HANDLE = (0x17, 0x66, 0x76)  # Edge colour of the selection handles drawn by the controller.
STORED = {"id": "00000000-0000-0000-0000-000000000067", "kind": "rectangle", "units": "axes",
          "points": [[.14, .15], [.40, .32]], "stroke": "#315A84", "width": 1.8, "line_style": "solid",
          "fill": "#ABCDEF", "alpha": .8, "layer": "above", "hatch": "diagonal", "hatch_color": "#213443"}
BREAKS = {"axis": "y", "gap": .03, "segments": [{"low": 1, "high": 5, "share": 50}, {"low": 6, "high": 10, "share": 50}]}


class Step(Exception):
    """A failed expectation: the rest of the cycle would only repeat the same problem."""


class CanvasSmoke:
    def __init__(self, smoke):
        self.smoke, self.window, self.app = smoke, smoke.window, smoke.app
        self.folder = smoke.folder / f"canvas-{smoke.language}"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "project.alab"
        self.log = []

    # -- helpers ---------------------------------------------------------------------------------------
    def expect(self, condition, text):
        if not condition:
            self.smoke.problem(f"canvas: {text}")
            raise Step(text)

    @property
    def run(self):
        return self.window.project.runs[0]

    @property
    def canvas(self):
        canvas, = self.window.page.canvases
        return canvas

    @property
    def shapes(self):
        return [dict(s) for s in (self.run.style or {}).get(SHAPES, [])]

    def drawn(self):
        axes = self.run.result.figure.axes[0]
        return [str(a.get_gid()).removeprefix("tramastat-shape-") for a in getattr(axes, "_tramastat_shapes", ())]

    def point(self, fraction):
        x, y = self.run.result.figure.axes[0].transAxes.transform(fraction)
        ratio = self.canvas.device_pixel_ratio
        return QPoint(round(x / ratio), self.canvas.height() - round(y / ratio))

    def drag(self, start, end, modifier=Qt.KeyboardModifier.NoModifier):
        QTest.mousePress(self.canvas, Qt.MouseButton.LeftButton, modifier, self.point(start))
        QTest.mouseMove(self.canvas, self.point(end), 30)
        QTest.mouseRelease(self.canvas, Qt.MouseButton.LeftButton, modifier, self.point(end))
        self.app.processEvents()

    def tool(self, name):
        self.window.actions[f"draw_{name}"].trigger()
        self.app.processEvents()

    def undo(self, redo=False):
        self.window.actions["redo" if redo else "undo"].trigger()
        self.app.processEvents()

    def shot(self, name, *, dark=False, widget=None):
        """The window (or ``widget``) in the light palette and, when ``dark``, also in the dark one."""
        target = widget or self.window
        self.smoke.shot(target, f"canvas-{name}-light")
        if dark:
            theme.apply(self.app, dark=True)
            try:
                self.app.processEvents()
                self.smoke.shot(target, f"canvas-{name}-dark")
            finally:
                theme.apply(self.app)
                self.app.processEvents()

    def handle_pixels(self):
        self.canvas.draw()
        image = self.canvas.grab().toImage()
        pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)
        bgr = pixels[:, :image.width(), :3].astype(int)
        target = np.array(HANDLE[::-1])
        return int((np.abs(bgr - target).max(axis=2) < 8).sum())

    def export(self, name):
        path = self.folder / name
        chosen = {".png": "PNG (*.png)", ".svg": "SVG (*.svg)", ".pdf": "PDF (*.pdf)"}[path.suffix]
        with mock.patch.object(QFileDialog, "getSaveFileName", return_value=(str(path), chosen)):
            self.window.export()
        self.app.processEvents()
        self.expect(path.exists() and path.stat().st_size > 0, f"{name} was not written")
        return path

    # -- the cycle -------------------------------------------------------------------------------------
    def build(self):
        frame = pd.DataFrame({"Time": [1, 2, 3, 4, 5], "Response": [3, 7, 6, 11, 13], "Control": [2, 4, 7, 8, 9]})
        dataset = Dataset(frame, analyses=[("XY series", {"X": "Time", "Y columns": ["Response"]}),
                                           ("XY series", {"X": "Time", "Y columns": ["Control"]})])
        dataset.graph_styles[0] = {SHAPES: [dict(STORED)]}
        save_project(self.path, {"Measurements": dataset})

    def open_project(self):
        self.window.project.dirty = False
        if self.window.sessions.find(self.path) is self.window.sessions.active:
            self.window.close_project()
        self.window.open_path(self.path)
        self.window.open_sheet(("graph", 0))
        self.smoke.wait()
        self.window.project.dirty = False
        window = self.window
        available = self.smoke.screen_rect(window).size()
        frame = window.frameGeometry().size() - window.size()  # The title bar and borders count against the screen.
        window.resize(available - frame)
        self.app.processEvents()

    def run_all(self):
        self.build()
        self.open_project()
        stored = self.shapes
        self.expect(stored == [STORED], f"the stored recipe was changed on opening: {stored}")
        self.expect(self.drawn() == [STORED["id"]], "the stored rectangle is not drawn")
        for name in ("select", "line", "arrow", "rectangle", "ellipse"):
            self.expect(self.window.actions[f"draw_{name}"].isEnabled(), f"draw_{name} is disabled on a native graph")
        self.shot("1-open", dark=True)

        # Draw.
        self.tool("rectangle")
        self.drag((.55, .52), (.83, .79))
        shapes = self.shapes
        self.expect(len(shapes) == 2 and shapes[0] == STORED, f"drawing a rectangle gave {shapes}")
        new = shapes[1]
        self.expect(new["id"] != STORED["id"] and new["kind"] == "rectangle" and new["units"] == "axes",
                    f"the new shape is wrong: {new}")
        self.expect(np.allclose(new["points"], [(.55, .52), (.83, .79)], atol=.035), f"drawn at {new['points']}")
        self.expect(self.window.project.dirty, "the project is not marked as changed")
        self.expect(self.handle_pixels() > 8, "the selection handles are not drawn on screen")
        self.shot("2-drawn", dark=True)

        # Move and resize keep identity, unit and style.
        self.drag((.55, .655), (.48, .60))  # From the left border: a hollow rectangle is picked by its outline.
        moved = self.shapes[1]
        self.expect(moved["id"] == new["id"] and moved["points"] != new["points"] and
                    {k: v for k, v in moved.items() if k != "points"} == {k: v for k, v in new.items() if k != "points"},
                    f"moving changed more than the points: {moved}")
        self.drag(tuple(moved["points"][1]), (.80, .85))
        resized = self.shapes[1]
        self.expect(resized["points"][0] == moved["points"][0] and resized["points"][1] != moved["points"][1],
                    f"resizing moved the wrong corner: {resized['points']}")
        self.shot("3-edited")

        # Use the same buttons as the Classic worksheet toolbar.
        buttons = self.window.toolbar.buttons
        self.expect(buttons["copy"].isEnabled() and buttons["paste"].isEnabled(),
                    "the toolbar clipboard buttons are disabled on a native graph")
        buttons["copy"].click()
        buttons["paste"].click()
        self.app.processEvents()
        pasted = self.shapes
        self.expect(len(pasted) == 3 and pasted[2]["id"] not in {s["id"] for s in pasted[:2]},
                    f"paste did not add a new shape: {[s['id'] for s in pasted]}")
        self.shot("4-pasted")

        # Context menu and the numeric editor.
        menu = self.window.drawing.context_menu(pasted[2]["id"])
        menu.popup(self.canvas.mapToGlobal(QPoint(40, 40)))
        self.app.processEvents()
        self.shot("5-context-menu", dark=True, widget=menu)
        menu.close()
        menu.deleteLater()
        self.tool("select") if not self.window.actions["draw_select"].isChecked() else None
        with self.smoke.dialogs("canvas-editor") as seen:
            self.window.drawing.edit(STORED["id"])
        self.expect(seen == ["canvas-editor-ShapeEditor"], f"the numeric editor did not open: {seen}")

        # Undo and redo: four steps (draw, move, resize, paste), only for this graph.
        final = self.shapes
        for _ in range(4):
            self.undo()
        self.expect(self.shapes == [STORED] and self.drawn() == [STORED["id"]], f"undo left {self.shapes}")
        self.expect(not self.window.actions["undo"].isEnabled(), "undo is still enabled after the last step")
        for _ in range(4):
            self.undo(redo=True)
        self.expect(self.shapes == final, "redo did not restore the shapes")
        self.expect(self.drawn() == [s["id"] for s in final], "the drawn artists do not match the model")

        # Save, reopen, export. Selection handles must not reach any file.
        self.tool("select") if not self.window.actions["draw_select"].isChecked() else None
        self.expect(self.window.save(), "saving failed")
        self.open_project()
        self.expect(self.shapes == final, f"the reopened shapes differ: {self.shapes}")
        self.expect(self.drawn() == [s["id"] for s in final], "the reopened drawing differs from the model")
        self.tool("select")
        self.drag((.27, .23), (.27, .23))
        self.expect(self.window.drawing.controller.selected == STORED["id"], "the stored rectangle cannot be selected")
        self.expect(self.handle_pixels() > 8, "the handles are not on screen before the export")
        svg = self.export("canvas.svg")
        text = svg.read_text(encoding="utf-8").lower()
        self.expect("#176676" not in text, "selection handles leaked into the SVG")
        ids = re.findall(r'id="tramastat-shape-([0-9a-f-]+)"', text)
        self.expect(sorted(ids) == sorted(s["id"] for s in final), f"the SVG draws {ids}")
        png = self.export("canvas.png")
        pdf = self.export("canvas.pdf")
        from PIL import Image
        with Image.open(png) as image:
            leaked = int((np.abs(np.asarray(image.convert("RGB")).astype(int) - HANDLE).max(axis=2) < 6).sum())
        self.expect(leaked == 0, f"{leaked} handle pixels leaked into the PNG")
        self.expect(pdf.read_bytes().startswith(b"%PDF"), "the PDF is not a PDF")
        self.expect(b"176676" not in pdf.read_bytes().lower(), "selection handles leaked into the PDF")
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.expect(SHAPES in saved["tables"][0]["graph_styles"]["0"] and
                    "176676" not in self.path.read_text(encoding="utf-8").lower(),
                    "the saved project carries a selection handle")
        self.expect(self.handle_pixels() > 8, "exporting removed the on-screen handles")

        # Axis breaks: the tools stay off with the reason, the numeric editor stays available.
        self.window.open_sheet(("graph", 1))
        self.smoke.wait()
        run = self.window.project.runs[1]
        style = dict(run.style or {})
        style[AXIS_BREAKS] = BREAKS
        self.window.project.apply_format(run, style)
        self.window.open_sheet(("graph", 1))
        self.smoke.wait()
        self.expect(segment_axes(run.result.figure), "the axis breaks were not applied")
        self.expect(self.window.drawing.controller is None, "the tools are on over broken axes")
        self.expect(not self.window.actions["draw_rectangle"].isEnabled(), "draw_rectangle is enabled on broken axes")
        self.expect(tr("axis_breaks.canvas_note") in self.window.actions["draw_rectangle"].toolTip(),
                    "the reason is not in the tool tip")
        self.expect(self.window.actions["shapes"].isEnabled(), "the numeric editor is off on broken axes")
        self.shot("6-axis-breaks", dark=True)

        # A layout page has no tools either.
        self.window.open_sheet(("data", "Measurements"))
        self.expect(not self.window.actions["draw_select"].isEnabled(), "the tools are on over the worksheet")
        self.log.append(f"cycle OK: toolbar copy/paste, {len(final)} shapes, exports {svg.name}, {png.name}, {pdf.name}")


def check_canvas(smoke):
    """Run the cycle for the smoke's current language; the palette is restored whatever happens."""
    canvas = CanvasSmoke(smoke)
    try:
        canvas.run_all()
    except Step:
        pass
    except Exception as error:  # noqa: BLE001 - the report must say what broke.
        import traceback
        smoke.problem("canvas: stopped:\n" + traceback.format_exc())
        del error
    finally:
        theme.apply(smoke.app)
    return canvas.log
