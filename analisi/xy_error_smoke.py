"""Desktop smoke check for XY error bars (symmetric/asymmetric X and Y, directions, styling, EN/IT, exports).

``tramastat.py --smoke`` calls :func:`check_xy_errors` with its helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=xy-errors python tramastat.py --smoke DIR``.
"""
from copy import deepcopy
from unittest.mock import patch
import xml.etree.ElementTree as ET

from matplotlib.colors import to_hex
import numpy as np
import pandas as pd
from PIL import Image
import pypdfium2 as pdfium

from .figure_export import export_figure, export_pdf_bundle
from .graph_annotations import ANNOTATIONS
from .i18n import set_language
from .layout_pdf import PdfLayoutPage
from .layout_svg import export_layout_svg
from .presentation import apply_style

SCREEN = (1024, 768)
FIXTURE_CSV = """row_id,X,Y,Group,LegacyX,XL,XU,XLo,XHi,YL,YU,YLo,YHi
41,10.0,100.0,B,1.0,1.5,2.5,8.5,12.5,10.0,15.0,90.0,115.0
7,4.0,50.0,A,0.5,0.25,1.75,3.75,5.75,5.0,8.0,45.0,58.0
90,20.0,200.0,B,2.0,0.0,3.0,20.0,23.0,12.0,0.0,188.0,200.0
13,8.0,80.0,A,1.25,1.0,0.5,7.0,8.5,4.0,6.0,76.0,86.0
55,15.0,150.0,B,1.5,,2.0,,17.0,9.0,11.0,141.0,161.0
88,12.0,,A,1.0,1.0,1.0,11.0,13.0,3.0,3.0,,
"""


def check_xy_errors(root, app, directory, tools):
    """Drive AnalysisDialog, GraphInspector, persistence, and exports for XY error bars."""
    errors = tools.errors
    geometry = root.geometry()
    root.geometry(f"{SCREEN[0]}x{SCREEN[1]}+0+0")
    root.update()
    try:
        _run_xy_errors_smoke(root, app, directory, tools, errors)
    finally:
        set_language("en")
        root.geometry(geometry)
        root.update()


def _drive_cancel(dialog_type, action, root, errors):
    def find(widget):
        for child in widget.winfo_children():
            if isinstance(child, dialog_type):
                return child
            nested = find(child)
            if nested is not None:
                return nested
        return None

    def step():
        dialog = find(root)
        if dialog is None:
            errors.append(f"{dialog_type.__name__} did not open")
            return
        try:
            action(dialog)
            if dialog.winfo_exists():
                dialog.cancel()
        except Exception as exc:
            errors.append(f"{dialog_type.__name__}: {exc!r}")
            if dialog.winfo_exists():
                dialog.cancel()

    root.after(180, step)


def _run_xy_errors_smoke(root, app, directory, tools, errors):
    csv_path = directory / "xy_errors.csv"
    csv_path.write_text(FIXTURE_CSV, encoding="utf-8")
    app.import_file(csv_path)
    table_name = "xy_errors"
    assert table_name in app.tables

    # 1. Verify Italian dialog labels, dependent visibility, 1024x768 layout, and Cancel behavior.
    set_language("it")

    def inspect_italian_dialog(dialog):
        tools.pick_method(dialog, "XY error bars")
        dialog.update_idletasks()
        width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        assert width <= SCREEN[0] and height <= SCREEN[1], ("Dialog exceeds 1024x768 in IT", width, height)
        tabs = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
        assert tabs == ["Errori X", "Errori Y", "Aspetto degli errori"], tabs
        assert dialog.field_rows["X error distance"][0].cget("text") == "Distanza X simmetrica"
        assert dialog.field_rows["X lower error"][0].cget("text") == "Errore X inferiore"
        assert dialog.field_rows["X upper error"][0].cget("text") == "Errore X superiore"
        assert dialog.field_rows["Error cap size"][0].cget("text") == "Dimensione cappucci (pt)"
        assert dialog.field_rows["Error width"][0].cget("text") == "Spessore errori (pt)"
        assert dialog.field_rows["Error color"][0].cget("text") == "Colore errori"

        dialog.controls["X"][1].set("X")
        dialog.controls["X lower error"][1].set("XLo")
        dialog.controls["X upper error"][1].set("XHi")
        dialog.controls["X error values"][1].set("Endpoints")
        dialog.controls["X error direction"][1].set("Negative only")
        dialog.update_idletasks()
        assert dialog.field_rows["X error values"][1].get() == "Estremi"
        assert dialog.field_rows["X error direction"][1].get() == "Solo negativa"
        tools.capture(dialog, "window-xy-errors-dialog-it.png")

    runs_before = len(app.runs)
    _drive_cancel(tools.AnalysisDialog, inspect_italian_dialog, root, errors)
    app.choose_analysis()
    assert not errors, errors
    assert len(app.runs) == runs_before

    # 2. Switch to English, verify dependent visibility, decimal comma input, and confirm calculation.
    set_language("en")

    def configure_english_dialog(dialog):
        tools.pick_method(dialog, "XY error bars")
        dialog.update_idletasks()
        width, height = dialog.winfo_reqwidth(), dialog.winfo_reqheight()
        assert width <= SCREEN[0] and height <= SCREEN[1], ("Dialog exceeds 1024x768 in EN", width, height)
        tabs = [dialog.fields.tab(i, "text") for i in range(dialog.fields.index("end"))]
        assert tabs == ["X errors", "Y errors", "Error appearance"], tabs

        # Initially no X error column selected -> X error values & X error direction hidden
        assert dialog.field_rows["X error values"][1].grid_info() == {}
        assert dialog.field_rows["X error direction"][1].grid_info() == {}

        # Selecting only legacy X error distance shows X error direction, keeps X error values hidden
        dialog.controls["X error distance"][1].set("LegacyX")
        dialog.update_idletasks()
        assert dialog.field_rows["X error values"][1].grid_info() == {}
        assert dialog.field_rows["X error direction"][1].grid_info() != {}

        # Switch to asymmetric X endpoints
        dialog.controls["X error distance"][1].set("")
        dialog.controls["X"][1].set("X")
        dialog.controls["Group"][1].set("Group")
        dialog.controls["X lower error"][1].set("XLo")
        dialog.controls["X upper error"][1].set("XHi")
        dialog.controls["X error values"][1].set("Endpoints")
        dialog.controls["X error direction"][1].set("Negative only")
        dialog.update_idletasks()
        assert dialog.field_rows["X error values"][1].grid_info() != {}
        assert dialog.field_rows["X error direction"][1].grid_info() != {}

        # Y errors tab
        dialog.fields.select(1)
        dialog.controls["Y"][1].set("Y")
        dialog.controls["Y lower error"][1].set("YLo")
        dialog.controls["Y upper error"][1].set("YHi")
        dialog.controls["Y error values"][1].set("Endpoints")
        dialog.controls["Y error direction"][1].set("Positive only")

        # Error appearance tab with decimal comma on Error width
        dialog.fields.select(2)
        dialog.controls["Error cap size"][1].set("7")
        dialog.controls["Error width"][1].set("2,25")
        dialog.controls["Error color"][1].set("#b12435")
        dialog.controls["Error line style"][1].set("dashed")
        dialog.update_idletasks()
        tools.capture(dialog, "window-xy-errors-dialog-en.png")

    tools.drive_dialog(tools.AnalysisDialog, configure_english_dialog)
    app.choose_analysis()
    tools.wait_for_calculation()
    run_index = len(app.runs) - 1
    run = app.runs[run_index]

    assert run.options["Error cap size"] == 7.0 and isinstance(run.options["Error cap size"], float)
    assert run.options["Error width"] == 2.25 and isinstance(run.options["Error width"], float)
    assert run.options["X error values"] == "Endpoints"
    assert run.options["Y error values"] == "Endpoints"
    assert run.options["X error direction"] == "Negative only"
    assert run.options["Y error direction"] == "Positive only"
    assert run.options["Error color"] == "#b12435"
    assert run.options["Error line style"] == "dashed"

    # 3. Show graph and verify GraphInspector Apply, Cancel, and Reset.
    app.show("graph", run_index)
    root.update()
    ax = run.result.figure.axes[0]
    assert len(ax.containers) == 2
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["B", "A"]

    app.toggle_inspector()
    inspector = app.inspector
    assert inspector is not None
    root.update()
    window_bottom = root.winfo_rooty() + root.winfo_height()
    for button in (inspector.apply_button, inspector.cancel_button):
        assert button.winfo_ismapped()
        assert button.winfo_rooty() + button.winfo_height() <= window_bottom + 1

    # Preview color change in Inspector then Cancel -> reverts to #b12435
    inspector.select_group("errorbar:0")
    inspector.vars["element:color"].set("#1f77b4")
    inspector._now("element:color")
    assert to_hex(ax.containers[0].lines[0].get_color()) == "#1f77b4"
    inspector.cancel_button.invoke()
    root.update()
    assert app.inspector is None
    assert to_hex(ax.containers[0].lines[1][0].get_color()) == "#b12435"

    # Reopen Inspector, Apply override on group B, verify group A stays #b12435, then Reset section
    app.toggle_inspector()
    inspector = app.inspector
    inspector.select_group("errorbar:0")
    inspector.vars["element:color"].set("#2ca02c")
    inspector._now("element:color")
    assert inspector.apply()
    assert to_hex(ax.containers[0].lines[0].get_color()) == "#2ca02c"
    assert to_hex(ax.containers[1].lines[1][0].get_color()) == "#b12435"
    inspector.reset_section("data")
    assert inspector.apply()
    inspector.cancel_button.invoke()
    root.update()
    assert to_hex(ax.containers[0].lines[1][0].get_color()) == "#b12435"

    # 4. Reopen parameters (Change Parameters…), change to Both, trigger FieldError, verify focus, fix & confirm.
    def edit_and_validate_errors(dialog):
        dialog.controls["X error direction"][1].set("Both")
        dialog.controls["Y error direction"][1].set("Both")

        # Ambiguous legacy X + new X -> FieldError on X error distance, dialog stays open with focus
        dialog.controls["X error distance"][1].set("LegacyX")
        dialog.update()

        def press_ok_expecting(field):
            # The real OK path (ok -> validate); the dialog must stay open with the field focused.
            with patch.object(tools.messagebox, "showerror") as shown:
                dialog.ok()
                assert shown.called, field
            assert dialog.winfo_exists() and dialog.result is None, field
            dialog.update()
            assert str(dialog.fields.select()) == str(dialog.field_rows[field][1].master), field
            assert dialog.focus_get() is dialog.field_rows[field][1], (field, dialog.focus_get())

        press_ok_expecting("X error distance")
        tools.capture(dialog, "window-xy-errors-field-error.png")

        # Clear legacy X, set invalid X lower endpoint (Y=100 > X=10) -> FieldError on X lower error
        dialog.controls["X error distance"][1].set("")
        dialog.controls["X lower error"][1].set("Y")
        press_ok_expecting("X lower error")

        # Negative cap size -> FieldError on the cap size field of the appearance tab
        dialog.controls["X lower error"][1].set("XLo")
        dialog.controls["Error cap size"][1].set("-1")
        press_ok_expecting("Error cap size")

        # Restore valid values (decimal comma on the numeric cap size field) and confirm
        dialog.controls["Error cap size"][1].set("6,5")
        dialog.update_idletasks()

    tools.drive_dialog(tools.AnalysisDialog, edit_and_validate_errors)
    app.edit_analysis()
    tools.wait_for_calculation()

    run = app.runs[run_index]
    assert run.options["X error direction"] == "Both"
    assert run.options["Y error direction"] == "Both"
    assert run.options["Error cap size"] == 6.5 and isinstance(run.options["Error cap size"], float)
    app.show("graph", run_index)
    root.update()
    tools.capture(root, "window-xy-errors-graph.png")

    # 5. Add text annotation for export verification, save .alab, reopen, and check consistency.
    run.style[ANNOTATIONS] = [{
        "text": "Asymmetric XY error check",
        "position": [0.18, 0.86],
        "units": "axes",
        "align": "left",
        "size": 10,
        "color": "#1d3348",
    }]
    apply_style(run.result.figure, run.style)

    obs_before = run.result.tables["Observations"].copy()
    assert list(obs_before.columns) == ["X", "Y", "XLo", "XHi", "YLo", "YHi", "Group"]
    assert len(obs_before) == 4

    alab_path = directory / "xy-errors-roundtrip.alab"
    app.path = alab_path
    assert app.save()
    app.import_file(alab_path)
    # Other feature smoke checks may have saved their own analyses in this project.
    # Find this recipe by identity instead of assuming it is the first analysis.
    reopened_indexes = [i for i, candidate in enumerate(app.runs)
                        if candidate.title == table_name and candidate.method == "XY error bars"]
    assert len(reopened_indexes) == 1, reopened_indexes
    reopened_index = reopened_indexes[0]
    app.open_sheet(("graph", reopened_index))
    tools.wait_for_calculation()
    reopened = app.runs[reopened_index]
    pd.testing.assert_frame_equal(reopened.result.tables["Observations"], obs_before)
    assert reopened.options["Error width"] == 2.25
    assert reopened.options["Error cap size"] == 6.5

    # 6. Physical exports: CSV, SVG (101.6 mm = 288 pt), PNG (100 dpi = 400x250 px), PDF, and layout SVG/PDF.
    fig = reopened.result.figure
    fig.set_size_inches(8.0, 5.0)
    csv_out = directory / "xy-errors-observations.csv"
    reopened.result.tables["Observations"].to_csv(csv_out, index=True)
    reloaded_csv = pd.read_csv(csv_out, index_col=0)
    assert list(reloaded_csv.columns) == ["X", "Y", "XLo", "XHi", "YLo", "YHi", "Group"]
    assert len(reloaded_csv) == 4

    svg_out = directory / "xy-errors-export.svg"
    png_out = directory / "xy-errors-export.png"
    pdf_out = directory / "xy-errors-export.pdf"
    layout_svg_out = directory / "xy-errors-layout.svg"
    layout_pdf_out = directory / "xy-errors-layout.pdf"

    export_figure(fig, svg_out, {"format": "svg", "width_mm": 101.6, "svg_text": "text"})
    export_figure(fig, png_out, {"format": "png", "width_mm": 101.6, "dpi": 100})
    export_figure(fig, pdf_out, {"format": "pdf", "width_mm": 101.6})
    export_layout_svg("XY Error Layout", 1, [fig], layout_svg_out, {"svg_text": "text"})
    export_pdf_bundle([PdfLayoutPage("XY Error Layout", 1, (fig,))], layout_pdf_out, {})

    svg_root = ET.parse(svg_out).getroot()
    assert abs(float(svg_root.get("width").removesuffix("pt")) - 288.0) < 1e-4
    assert abs(float(svg_root.get("height").removesuffix("pt")) - 180.0) < 1e-4
    assert not any(elem.tag.endswith("}image") for elem in svg_root.iter())
    assert "Asymmetric XY error check" in svg_out.read_text(encoding="utf-8")
    assert "Asymmetric XY error check" in layout_svg_out.read_text(encoding="utf-8")

    with Image.open(png_out) as img:
        assert list(img.size) == [400, 250], img.size

    for pdf_file in (pdf_out, layout_pdf_out):
        doc = pdfium.PdfDocument(str(pdf_file))
        try:
            page = doc[0]
            try:
                tp = page.get_textpage()
                try:
                    assert "Asymmetric XY error check" in tp.get_text_bounded()
                finally:
                    tp.close()
            finally:
                page.close()
        finally:
            doc.close()

    # 7. Use Result as Data, then edit a cell and exclude a row on the source table and verify recalculation.
    app.show("result", reopened_index)
    root.update()
    tables_before = len(app.tables)
    app.use_result_as_data()
    assert len(app.tables) == tables_before + 1

    app.show("data", table_name)
    root.update()
    app.edit_cell(0, 1, "10.5")  # X at row 0 becomes 10.5 (still between XLo=8.5 and XHi=12.5)
    tools.wait_for_calculation()
    assert float(app.runs[reopened_index].result.tables["Observations"]["X"].iloc[0]) == 10.5

    app.current_grid.active_cell = (1, 1)  # exclude row 1 (row_id 7)
    app.toggle_exclusion()
    tools.wait_for_calculation()
    assert len(app.runs[reopened_index].result.tables["Observations"]) == 3
