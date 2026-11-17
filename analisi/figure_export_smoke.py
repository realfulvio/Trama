"""Desktop smoke check for File → Export with options… (0.57).

``tramastat.py --smoke`` calls :func:`check_figure_export` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=figure-export python tramastat.py --smoke DIR``.
"""
from unittest.mock import patch

import pandas as pd
from PIL import Image

from . import figure_export as fe
from .data import Dataset, save_project
from .figure_export_dialog import FigureExportDialog
from .presentation import Layout

TITLE = "Export data"
METHOD = "Scatter / confidence ellipse"


def check_figure_export(root, app, directory, tools):
    """``tools`` carries the smoke helpers: capture, drive_dialog, wait_for_calculation, messagebox, filedialog."""
    wait, capture, drive = tools.wait_for_calculation, tools.capture, tools.drive_dialog
    out = directory / "figure-export"
    out.mkdir(exist_ok=True)
    data = Dataset(pd.DataFrame({"X": [1., 2, 3, 4, 5, 6], "Y": [1.2, 1.9, 3.2, 3.8, 5.1, 6.3],
                                "Group": ["A", "A", "A", "B", "B", "B"]}))
    data.analyses.append((METHOD, {"X": "X", "Y": "Y", "Group": "Group"}))
    path = directory / "figure-export.alab"
    save_project(path, {TITLE: data})
    app.import_file(path)
    run = next(i for i, r in enumerate(app.runs) if r.method == METHOD)
    app.open_sheet(("graph", run))
    wait()
    figure = app.runs[run].result.figure
    assert figure.axes and figure.axes[0].get_legend() is not None
    before = (tuple(figure.get_size_inches()), figure.dpi, figure.axes[0].get_xlim(), figure.axes[0].get_ylim())
    options_before = dict(app.runs[run].options)
    dirty = app.dirty
    log, problems = [], []

    def export(action, target, *, cancel=False, shot=None):
        def act(dialog):
            action(dialog)
            dialog.update()
            if shot:
                capture(dialog, shot)

        def leave():
            def find(parent):
                for child in parent.winfo_children():
                    if isinstance(child, FigureExportDialog):
                        return child
                    found = find(child)
                    if found is not None:
                        return found

            dialog = find(root)
            try:
                act(dialog)
            except Exception as exception:
                problems.append(exception)
            finally:
                dialog.cancel()

        if cancel:
            root.after(200, leave)
        else:
            drive(FigureExportDialog, act)
        with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(target)) as ask, \
                patch.object(app, "error") as error:
            app.export_with_options()
        assert not problems, problems
        return ask, error

    def settle(label):
        assert (tuple(figure.get_size_inches()), figure.dpi, figure.axes[0].get_xlim(),
                figure.axes[0].get_ylim()) == before, label
        assert app.runs[run].options == options_before and app.dirty == dirty, label

    # The dialog starts on the Screen preset and shows size and pixels; a changed field becomes Custom.
    def screen(dialog):
        assert dialog.preset.get() == "Screen" and dialog.format.get() == "PNG"
        assert dialog.plan["pixels"] == [605, 378] or dialog.plan["pixels"][0] == 605, dialog.plan
        assert "px" in dialog.summary.cget("text")
        dialog.dpi.set("150")
        assert dialog.preset.get() == "Custom"
        dialog.dpi.set("96")
        dialog.preset.set("Screen")
        dialog.update()
    target = out / "screen.png"
    export(screen, target, shot="window-export-options-dialog.png")
    with Image.open(target) as image:
        assert image.size[0] == 605 and abs(image.info["dpi"][0] - 96) < .1, (image.size, image.info)
        assert image.convert("RGBA").getpixel((0, 0))[3] == 0, "transparent corner expected"
    log.append(f"screen.png {image.size}")
    settle("screen")

    # Invalid numbers keep the dialog open and nothing is written.
    def invalid(dialog):
        dialog.preset.set("Custom")
        dialog.width.set("abc")
        dialog.update()
        assert dialog.validate() is False and str(dialog.summary.cget("foreground")) == "#b00020"
        capture(dialog, "window-export-options-error.png")
        dialog.width.set("5000")
        assert dialog.validate() is False and "between" in dialog.summary.cget("text")
        dialog.width.set("400")
        dialog.dpi.set("1200")
        dialog.update()
        assert dialog.validate() is False and "limit" in dialog.summary.cget("text"), dialog.summary.cget("text")
        dialog.dpi.set("300,5")
        assert dialog.validate() is False
    skipped = out / "never.png"
    ask, _ = export(invalid, skipped, cancel=True)
    assert not ask.called and not skipped.exists()
    settle("invalid")

    # Cancel leaves no file.
    ask, _ = export(lambda dialog: dialog.width.set("100"), skipped, cancel=True)
    assert not ask.called and not skipped.exists()

    # Print preset: opaque LZW TIFF at 300 DPI; the extension .tiff is accepted.
    target = out / "print.tiff"
    export(lambda dialog: dialog.preset.set("Print"), target)
    with Image.open(target) as image:
        assert image.mode == "RGB" and image.tag_v2[259] == 5 and abs(image.info["dpi"][0] - 300) < .1
        expected = fe.plan_export(figure.get_size_inches(), {"format": "tiff", "width_mm": 85, "dpi": 300})
        assert list(image.size) == expected["pixels"], (image.size, expected)
    log.append(f"print.tiff {image.size}")
    settle("print")

    # A wrong extension is refused before writing and keeps the previous file.
    target = out / "wrong.pdf"
    ask, error = export(lambda dialog: dialog.preset.set("Screen"), target)
    assert error.called, 'no error shown'
    assert not target.exists(), 'file written'
    assert not [p for p in out.iterdir() if p.name.startswith(".")], list(out.iterdir())
    settle("extension")

    # Vector presets: PDF page and SVG size match the requested millimetres, Text vs Paths.
    target = out / "vector.pdf"
    export(lambda dialog: dialog.preset.set("Vector"), target)
    import pypdfium2 as pdfium

    with pdfium.PdfDocument(target) as document:
        size = document[0].get_size()
    plan = fe.plan_export(figure.get_size_inches(), {"format": "pdf", "width_mm": 85})
    assert abs(size[0] - 85 * 72 / 25.4) < .01 and abs(size[1] - plan["height_mm"] * 72 / 25.4) < .01, size
    log.append(f"vector.pdf {size[0]:.2f} x {size[1]:.2f} pt")

    def svg(mode):
        def action(dialog):
            dialog.format.set("SVG")
            dialog.width.set("120")
            dialog.svg_text.set(mode)
            dialog.update()
        return action
    for mode in ("Text", "Paths"):
        target = out / f"vector-{mode.lower()}.svg"
        export(svg(mode), target)
        content = target.read_text(encoding="utf-8")
        assert ("<text" in content) == (mode == "Text"), mode
        assert 'width="' in content and "pt" in content
        log.append(f"vector-{mode.lower()}.svg {len(content)} bytes")
    settle("vector")

    # A native layout can export either the composed PNG or a vector PDF.
    app.layouts.append(Layout("Export layout", 1, [app.runs[run].reference]))
    app.refresh_navigator()
    app.show("layout", len(app.layouts) - 1)
    root.update()

    def layout_dialog(dialog):
        dialog.format.set("PNG")
        assert "raster image" in dialog.note.cget("text"), dialog.note.cget("text")
        dialog.format.set("PDF")
        dialog.update()
        assert "PDF preserves vector graphics" in dialog.note.cget("text"), dialog.note.cget("text")
        capture(dialog, "window-export-options-layout.png")
    target = out / "layout.pdf"
    _, error = export(layout_dialog, target)
    assert not error.called, error.call_args
    from .pdf_bundle_smoke import read_pdf

    [(_, text, images)] = read_pdf(target)
    assert "Export layout" in text and images == 0, (text, images)
    quick = out / "quick.png"
    with patch.object(tools.filedialog, "asksaveasfilename", return_value=str(quick)):
        app.export()
    assert quick.stat().st_size > 1000
    app.dirty = dirty
    capture(root, "window-export-options-opened.png")
    (out / "export-sizes.log").write_text("\n".join(log) + "\n", encoding="utf-8")
