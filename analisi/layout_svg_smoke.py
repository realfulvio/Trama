"""Desktop smoke check for native layouts exported as vector SVG and PDF.

``tramastat.py --smoke`` calls :func:`check_layout_svg` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=layout-svg python tramastat.py --smoke DIR``.

Synthetic data only. The exported SVGs stay in ``DIR/layout-svg`` for a look in an SVG viewer.
"""
from io import BytesIO
import re
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pandas as pd

from .correlation_matrix import CORRELATION_MATRIX
from .figure_export_dialog import FigureExportDialog

SVG = "{http://www.w3.org/2000/svg}"
XLINK = "{http://www.w3.org/1999/xlink}href"
TABLE = "Prova città"
TITLE = "Figura 1 – città & <sintesi> (A)"
MIXED = "Pannello misto (raster)"


def inspect(path, width_mm, height_mm):
    """Parsed SVG with its links checked; returns (root, ids, refs)."""
    root = ET.parse(path).getroot()
    assert root.tag == SVG + "svg", root.tag
    for name, want in (("width", width_mm), ("height", height_mm)):
        value = root.get(name)
        assert value.endswith("mm") and abs(float(value[:-2]) - want) < .02, (name, value, want)
    ids = [item.get("id") for item in root.iter() if item.get("id") is not None]
    assert len(ids) == len(set(ids)), "duplicate ids"
    refs = []
    for item in root.iter():
        for key, value in item.attrib.items():
            if key in {"href", XLINK} and value.startswith("#"):
                refs.append(value[1:])
            refs.extend(re.findall(r"url\(#([^)]+)\)", value))
    assert refs and set(refs) <= set(ids), set(refs) - set(ids)
    return root, ids, refs


def texts(element):
    return ["".join(node.itertext()) for node in element.iter(SVG + "text")]


def source_images(figure):
    with BytesIO() as buffer:
        figure.savefig(buffer, format="svg")
        return len(ET.fromstring(buffer.getvalue()).findall(".//" + SVG + "image"))


def extracted_title_present(text):
    """PDF text extraction may insert CR/LF between words without changing the title."""
    return " ".join(TITLE.split()) in " ".join(text.split())


def check_layout_svg(kit):
    """``kit``: app, root, directory, capture, pick_method, select_columns, drive_dialog(type, action),
    wait_for_calculation, filedialog, LayoutDialog, AnalysisDialog."""
    app, root, capture, wait = kit.app, kit.root, kit.capture, kit.wait_for_calculation
    out = kit.directory / "layout-svg"
    out.mkdir(exist_ok=True)
    log, problems = [], []

    def shot(window, name):
        capture(window, name)
        if (kit.directory / name).exists():
            (kit.directory / name).replace(out / name)

    # A fresh project with synthetic XY data: one XY graph and one graph with error bars.
    app.new_project()
    root.update()
    app._add_tables({TABLE: pd.DataFrame({"Dose": [1., 2, 3, 4, 5, 6], "Risposta": [1.1, 2.3, 2.9, 4.2, 4.8, 6.1],
                                          "Media": [2., 3.5, 3.1, 4.4, 5.2, 5.9],
                                          "DS": [.3, .5, .4, .6, .35, .5]})})
    root.update()

    def graph(setup):
        app.show("data", TABLE)
        kit.drive_dialog(kit.AnalysisDialog, setup)
        app.choose_analysis()
        wait()
        return len(app.runs) - 1

    def xy(dialog):
        kit.pick_method(dialog, "XY series")
        dialog.controls["X"][1].set("Dose")
        kit.select_columns(dialog, "Y columns", {"Risposta"})

    def errors(dialog):
        kit.pick_method(dialog, "XY error bars")
        for name, value in {"X": "Dose", "Y": "Media", "Y lower error": "DS"}.items():
            dialog.controls[name][1].set(value)

    def heatmap(dialog):
        kit.pick_method(dialog, CORRELATION_MATRIX)
        kit.select_columns(dialog, "Variables", {"Dose", "Risposta", "Media", "DS"})

    first, second = graph(xy), graph(errors)
    assert app.runs[second].result.figure.axes[0].containers[0].has_yerr

    def compose(name, panels):
        def choose(dialog):
            dialog.name.set(name)
            dialog.columns.set("2")
            dialog.list.selection_clear(0, "end")
            for index, run in enumerate(dialog.runs):
                if app.runs.index(run) in panels:
                    dialog.list.selection_set(index)
            dialog.add_selected()
        kit.drive_dialog(kit.LayoutDialog, choose)
        app.new_layout()
        root.update()
        return len(app.layouts) - 1

    layout = compose(TITLE, {first, second})
    assert app.layouts[layout].columns == 2 and len(app.layouts[layout].panels) == 2

    # Save, reopen and recalculate the panels from the layout page.
    app.path = kit.directory / "layout-svg.alab"
    assert app.save()
    app.import_file(app.path)
    root.update()
    layout = next(i for i, item in enumerate(app.layouts) if item.name == TITLE)
    assert all(run.result is None for run in app.layout_runs(app.layouts[layout]))
    app.show("layout", layout)
    app.recalculate_layout(layout)
    wait()
    app.show("layout", layout)
    root.update()
    assert app.layout_figure is not None and all(axes.images for axes in app.layout_figure.axes)
    shot(root, "window-layout-svg-page.png")

    def export(target, configure, name):
        def act(dialog):
            configure(dialog)
            dialog.update()
            shot(dialog, name)
        kit.drive_dialog(FigureExportDialog, act)
        with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(target)), \
                patch.object(app, "error") as error:
            app.export_with_options()
        assert not error.called, error.call_args
        assert target.exists(), target

    def setting(fmt, width, text="Text", transparent=False):
        def configure(dialog):
            dialog.format.set(fmt)
            dialog.width.set(width)
            dialog.svg_text.set(text)
            dialog.transparent.set(transparent)
            dialog.update()
            note = dialog.note.cget("text")
            if fmt in {"SVG", "PDF"}:
                assert "vector graphics" in note, note
                assert dialog.summary.cget("text") == "Final size: 150.0 × 64.3 mm", dialog.summary.cget("text")
            else:
                assert "raster image" in note and "Choose SVG or PDF" in note, note
            log.append(f"{fmt} note: {note}")
        return configure

    panels = [run.result.figure for run in app.layout_runs(app.layouts[layout])]
    before = [(tuple(f.get_size_inches()), f.dpi, f.canvas, [(a.get_xlim(), a.get_ylim()) for a in f.axes])
              for f in panels]
    page = app.layout_figure
    dirty = app.dirty

    # Vector SVG with a custom width: text, markers (<use>) and clip paths of both panels.
    width = 150
    height = width * 3.6 / 8.4
    target = out / "layout-vector-text.svg"
    export(target, setting("SVG", "150"), "window-layout-svg-dialog.png")
    svg, ids, refs = inspect(target, width, height)
    words = texts(svg)
    assert TITLE in words and "A" in words and "B" in words, words
    assert not svg.findall(".//" + SVG + "image")
    for index in (1, 2):
        group = svg.find(f".//{SVG}g[@id='panel{index}']")
        assert group is not None and texts(group), index
        assert group.findall(f".//{SVG}use"), f"panel {index} markers"
        assert any(ref.startswith(f"panel{index}-") and ref != f"panel{index}-viewport" for ref in refs), index
    assert svg.findall(".//" + SVG + "clipPath")
    log.append(f"{target.name}: {target.stat().st_size} bytes, {len(ids)} ids, {len(refs)} links, "
               f"{len(svg.findall('.//' + SVG + 'text'))} text, 0 images")

    # Paths: no text element anywhere, still vector.
    target = out / "layout-vector-paths.svg"
    export(target, setting("SVG", "150", "Paths", True), "window-layout-svg-paths.png")
    svg, ids, refs = inspect(target, width, height)
    assert not svg.findall(".//" + SVG + "text") and svg.findall(".//" + SVG + "path")
    log.append(f"{target.name}: {target.stat().st_size} bytes, {len(ids)} ids, no text")

    # The same layout in PDF keeps panel text and paths at the dimensions shown in the dialog.
    from .pdf_bundle_smoke import read_pdf

    target = out / "layout-vector.pdf"
    export(target, setting("PDF", "150"), "window-layout-vector-pdf-dialog.png")
    [(size, text, image_count)] = read_pdf(target)
    assert image_count == 0 and extracted_title_present(text) and len(text) > len(TITLE) + 25, (image_count, text)
    assert all(abs(pt * 25.4 / 72 - mm) < .02 for pt, mm in zip(size, (width, height))), size
    log.append(f"{target.name}: {size} pt, no raster panels")

    quick_pdf = out / "layout-quick.pdf"
    with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(quick_pdf)):
        app.export()
    [(size, text, image_count)] = read_pdf(quick_pdf)
    assert size == (604.8, 259.2) and extracted_title_present(text) and image_count == 0, (size, text, image_count)

    after = [(tuple(f.get_size_inches()), f.dpi, f.canvas, [(a.get_xlim(), a.get_ylim()) for a in f.axes])
             for f in panels]
    assert after == before and app.layout_figure is page and app.dirty == dirty

    # A mixed layout: the heatmap keeps its image, everything else stays vector.
    heat = graph(heatmap)
    images = source_images(app.runs[heat].result.figure)
    assert images >= 1, images
    mixed = compose(MIXED, {first, heat})
    app.show("layout", mixed)
    root.update()
    shot(root, "window-layout-svg-mixed-page.png")
    target = out / "layout-mixed.svg"
    export(target, setting("SVG", "150"), "window-layout-svg-mixed-dialog.png")
    order = [app.runs.index(run) for run in app.layout_runs(app.layouts[mixed])]
    svg, ids, refs = inspect(target, width, height)
    assert len(svg.findall(".//" + SVG + "image")) == images
    raster = order.index(heat) + 1
    vector = 3 - raster
    group = svg.find(f".//{SVG}g[@id='panel{raster}']")
    assert len(group.findall(f".//{SVG}image")) == images and texts(group) and group.findall(f".//{SVG}path")
    assert not svg.find(f".//{SVG}g[@id='panel{vector}']").findall(f".//{SVG}image")
    log.append(f"{target.name}: {target.stat().st_size} bytes, {images} image(s) in panel {raster}, "
               f"panel {vector} without images")
    target = out / "layout-mixed.pdf"
    export(target, setting("PDF", "150", transparent=True), "window-layout-mixed-pdf-dialog.png")
    [(size, text, image_count)] = read_pdf(target)
    assert image_count == images and MIXED in text, (image_count, text)
    log.append(f"{target.name}: {size} pt, {image_count} embedded image(s)")
    original = list(app.layouts[mixed].panels)

    def page_setup(dialog):
        assert dialog.panel_list.size() == 2
        dialog.panel_list.selection_set(1)
        dialog.move_selected(-1)
        dialog.list.selection_clear(0, "end")
        dialog.list.selection_set(0)
        dialog.add_selected()
        assert dialog.panel_list.size() == 3
        dialog.remove_selected()
        dialog.paper.set("A4 landscape")
        dialog.background.set("#dce8f2")
        shot(dialog, "window-layout-page-setup.png")

    kit.drive_dialog(kit.LayoutDialog, page_setup)
    app.new_layout(edit=True)
    arranged = app.layouts[mixed]
    assert arranged.panels == original[::-1] and arranged.paper == "A4 landscape"
    assert arranged.background == "#dce8f2"

    def print_layout(dialog):
        dialog.format.set("PDF")
        dialog.width.set("")
        dialog.transparent.set(False)
        assert dialog.summary.cget("text") == "Final size: 297.0 × 210.0 mm", dialog.summary.cget("text")

    target = out / "layout-a4.pdf"
    export(target, print_layout, "window-layout-a4-export.png")
    [(size, text, image_count)] = read_pdf(target)
    assert all(abs(pt * 25.4 / 72 - mm) < .02 for pt, mm in zip(size, (297, 210))), size
    assert MIXED in text and image_count == images
    assert app.save()
    app.import_file(app.path)
    assert app.layouts[mixed] == arranged
    log.append(f"{target.name}: A4 landscape {size} pt, reordered panels and background retained after reopening")
    shot(root, "window-layout-svg-done.png")
    (out / "layout-svg.log").write_text("\n".join(log) + "\n", encoding="utf-8")
    assert not problems, problems
