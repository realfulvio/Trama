"""Desktop smoke check for native legend formatting across Standard/Modern and EN/IT.

``tramastat.py --smoke`` calls :func:`check_legend_formatting` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=legend-formatting python tramastat.py --smoke DIR``.

Synthetic data only. Artifacts and the project stay in ``DIR/legend-formatting``; screenshots in ``DIR``.
"""
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pandas as pd
import pypdfium2 as pdfium
from pypdfium2 import raw as pdfraw

from . import i18n, ui_theme
from .data import Dataset, save_project
from .fdr_control import METHOD as FDR_METHOD
from .figure_export_dialog import FigureExportDialog
from .graph_dialog import GraphFormatDialog
from .graph_language_smoke import drive_mapped_dialog
from .graph_legend import LEGEND_OPTIONS_KEY
from .graph_legend_dialog import FRAME_SHOWN, LegendEditorDialog

TITLE = "Legend study"


def _pdf_objects(path):
    document = pdfium.PdfDocument(str(path))
    try:
        page = document[0]
        try:
            textpage = page.get_textpage()
            try:
                text = " ".join(textpage.get_text_range().split())
            finally:
                textpage.close()
            types = [item.type for item in page.get_objects(max_depth=15)]
        finally:
            page.close()
    finally:
        document.close()
    return text, types.count(pdfraw.FPDF_PAGEOBJ_PATH), types.count(pdfraw.FPDF_PAGEOBJ_IMAGE)


def _fits(dialog, buttons, root):
    dialog.update()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    assert dialog.winfo_width() <= sw and dialog.winfo_height() <= sh, (
        dialog.winfo_width(), dialog.winfo_height(), sw, sh
    )
    bottom = dialog.winfo_rooty() + dialog.winfo_height()
    for button in buttons:
        assert button.winfo_viewable(), button
        assert button.winfo_rooty() + button.winfo_height() <= bottom + 2, button


def check_legend_formatting(kit):
    """Run the end-to-end legend formatting smoke test inside the real Trama application."""
    original_lang = i18n.active_language()
    original_theme = ui_theme._state.get("theme", "standard")
    try:
        _run(kit)
    finally:
        i18n.set_language(original_lang)
        if ui_theme._state.get("theme", "standard") != original_theme:
            ui_theme.configure(kit.root, original_theme)
        kit.root.update()


def _run(kit):
    app, root, wait, capture = kit.app, kit.root, kit.wait_for_calculation, kit.capture
    errors = kit.errors
    out = kit.directory / "legend-formatting"
    out.mkdir(exist_ok=True)
    alab = out / "legend-formatting.alab"

    frame = pd.DataFrame({
        "Time": [0.0, 1.0, 2.0, 3.0, 4.0],
        "Control": [1.0, 2.2, 3.1, 2.4, 1.5],
        "Treated": [10.0, 24.0, 36.0, 27.0, 19.0],
        "Pvals": [0.001, 0.012, 0.045, 0.35, 0.80],
    })
    dataset = Dataset(frame)
    dataset.analyses.append((
        "XY series",
        {
            "X": "Time",
            "Y columns": ["Control", "Treated"],
            "Series style": {"Control": "Line and points", "Treated": "Line and points"},
            "Series side": {"Control": "Left", "Treated": "Right"},
        },
    ))
    dataset.analyses.append((
        FDR_METHOD,
        {
            "p columns": ["Pvals"],
            "FDR method": "Benjamini–Hochberg",
            "Desired FDR (%)": 5.0,
            "Family scope": "Each column separately",
            "Show diagnostic plot": True,
        },
    ))
    dataset.analyses.append(("Normality tests", {
        "Variables": ["Control"], "Distribution": "Both", "Q–Q plot": True,
        "Q–Q variable": "Control", "Q–Q reference line": True,
    }))
    save_project(alab, {TITLE: dataset})

    # --- Part 1: EN + Standard theme + Format Graph + shared LegendEditorDialog ---
    i18n.set_language("en")
    ui_theme.configure(root, "standard")
    app.import_file(alab)
    app.open_sheet(("graph", 0))
    wait()
    run = app.runs[0]

    def drive_format(fdlg):
        _fits(fdlg, (fdlg.legend_button,), root)

        def drive_legend(ldlg):
            _fits(ldlg, (ldlg.reset_button, ldlg.preview_button, ldlg.apply_button, ldlg.cancel_button), root)
            # Invalid column count stays open and focuses field
            ldlg.fields["columns"].set("0")
            assert not ldlg.preview()
            assert ldlg.winfo_exists() and ldlg.error_widget is ldlg.widgets["columns"]
            assert ldlg.error_labels["columns"].winfo_ismapped()

            # Valid preview 1 -> preview 2 -> reset restores default, then apply custom values
            ldlg.fields["columns"].set("2")
            ldlg.fields["title"].set("Temp Preview")
            assert ldlg.preview()
            ldlg.reset_fields()
            assert ldlg.fields["title"].get() == ""

            ldlg.fields["title"].set("Literal {A} $B$")
            ldlg.fields["columns"].set("2")
            ldlg.fields["frame"].set(FRAME_SHOWN)
            ldlg.fields["facecolor"].set("#eef4fa")
            ldlg.fields["edgecolor"].set("#204060")
            ldlg.fields["width"].set("2.0")
            ldlg.fields["alpha"].set("0.45")
            ldlg.fields["reverse"].set(True)
            ldlg.entry_vars["xy:1:Control"].set("Ctrl $1$")
            ldlg.entry_vars["xy:1:Treated"].set("Tx {µM}")
            assert ldlg.preview()
            ldlg.update()
            capture(ldlg, "window-legend-dialog-en.png")
            ldlg.ok()

        drive_mapped_dialog(fdlg, LegendEditorDialog, drive_legend, errors)
        fdlg.legend_button.invoke()
        assert not errors, errors
        fdlg.ok()

    drive_mapped_dialog(root, GraphFormatDialog, drive_format, errors)
    app.format_graph()
    assert not errors, errors

    fig0 = run.result.figure
    assert len(fig0.axes) == 2
    leg0 = fig0.axes[0].get_legend()
    assert leg0.get_title().get_text() == "Literal {A} $B$"
    assert [t.get_text() for t in leg0.get_texts()] == ["Tx {µM}", "Ctrl $1$"]
    assert leg0._ncols == 2 and leg0.get_frame_on()
    assert abs(leg0.get_frame().get_alpha() - 0.45) < 1e-12
    root.update()
    capture(root, "window-legend-formatting-en.png")

    # Inspector opens the same LegendEditorDialog; Preview + Cancel keeps confirmed style intact
    app.toggle_inspector()
    inspector = app.inspector
    assert inspector is not None and "legend_options" in inspector.widgets

    def drive_insp_cancel(ldlg):
        ldlg.fields["title"].set("Should Cancel")
        assert ldlg.preview()
        assert fig0.axes[0].get_legend().get_title().get_text() == "Should Cancel"
        ldlg.cancel()

    drive_mapped_dialog(inspector, LegendEditorDialog, drive_insp_cancel, errors)
    inspector.widgets["legend_options"].invoke()
    assert not errors, errors
    assert fig0.axes[0].get_legend().get_title().get_text() == "Literal {A} $B$"
    inspector.cancel_button.invoke()
    root.update()
    assert app.inspector is None

    # --- Part 2: FDR figure-level legend ---
    app.open_sheet(("graph", 1))
    wait()
    fdr_run = app.runs[1]
    assert len(fdr_run.result.figure.legends) == 1
    assert "Benjamini" in fdr_run.result.figure.legends[0].get_texts()[0].get_text()

    def drive_fdr_format(fdlg):
        def drive_fdr_legend(ldlg):
            ldlg.fields["title"].set("FDR Key")
            ldlg.fields["frame"].set(FRAME_SHOWN)
            ldlg.fields["reverse"].set(True)
            ldlg.ok()

        drive_mapped_dialog(fdlg, LegendEditorDialog, drive_fdr_legend, errors)
        fdlg.legend_button.invoke()
        assert not errors, errors
        fdlg.ok()

    drive_mapped_dialog(root, GraphFormatDialog, drive_fdr_format, errors)
    app.format_graph()
    assert not errors, errors
    assert fdr_run.result.figure.legends[0].get_title().get_text() == "FDR Key"

    # --- Part 3: IT + Modern theme + Inspector Apply + Save/Reopen Graph FIRST + Recalc + Exports ---
    i18n.set_language("it")
    ui_theme.configure(root, "modern")
    app.show("data", TITLE)
    root.update()
    ws = app.modern_workspace
    assert ws is not None
    ws.choice.current(0)
    ws._chosen()
    if not ws.sidebar_wanted.get():
        ws.show_format()
    root.update()
    assert ws.inspector is not None and "legend_options" in ws.inspector.widgets

    def drive_modern_it(ldlg):
        _fits(ldlg, (ldlg.reset_button, ldlg.preview_button, ldlg.apply_button, ldlg.cancel_button), root)
        ldlg.fields["title"].set("Legenda {IT} $α$")
        ldlg.fields["alpha"].set("0,6")
        assert ldlg.preview()
        # Private preview must not mutate confirmed source figure before Inspector Apply.
        assert run.result.figure.axes[0].get_legend().get_title().get_text() == "Literal {A} $B$"
        ldlg.update()
        capture(ldlg, "window-legend-dialog-it.png")
        ldlg.ok()

    drive_mapped_dialog(ws.inspector, LegendEditorDialog, drive_modern_it, errors)
    ws.inspector.widgets["legend_options"].invoke()
    assert not errors, errors
    assert ws.inspector.apply()
    root.update()
    capture(root, "window-legend-formatting-it.png")
    assert run.style[LEGEND_OPTIONS_KEY]["title"] == "Legenda {IT} $α$"
    assert abs(run.style[LEGEND_OPTIONS_KEY]["alpha"] - 0.6) < 1e-12

    ui_theme.configure(root, "standard")
    app.path = alab
    assert app.save()
    app.import_file(alab)
    # Open the graph FIRST after reopening the project!
    app.open_sheet(("graph", 0))
    wait()
    reopened = app.runs[0]
    r_leg = reopened.result.figure.axes[0].get_legend()
    assert r_leg.get_title().get_text() == "Legenda {IT} $α$"
    assert [t.get_text() for t in r_leg.get_texts()] == ["Tx {µM}", "Ctrl $1$"]
    assert r_leg._ncols == 2 and r_leg.get_frame_on()

    # Edit & exclude data -> recalculate keeps legend formatting
    app.show("data", TITLE)
    app.edit_cell(0, 1, "1.8")
    wait()
    app.current_grid.active_cell = (4, 1)
    app.toggle_exclusion()
    wait()
    updated = app.runs[0]
    u_leg = updated.result.figure.axes[0].get_legend()
    assert u_leg.get_title().get_text() == "Legenda {IT} $α$"
    assert [t.get_text() for t in u_leg.get_texts()] == ["Tx {µM}", "Ctrl $1$"]

    # Export CSV, PNG, SVG (vector), PDF (vector), and Layout
    app.show("data", TITLE)
    csv_path = out / "legend-data.csv"
    with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    assert csv_path.exists() and csv_path.stat().st_size > 0

    app.show("graph", 0)
    for fmt, ext, extra in (
        ("PNG", "png", {}),
        ("SVG", "svg", {"svg_text": "Text"}),
        ("PDF", "pdf", {}),
    ):
        target = out / f"legend-graph.{ext}"

        def drive_export(edlg, fmt=fmt, extra=extra):
            edlg.format.set(fmt)
            if "svg_text" in extra:
                edlg.svg_text.set(extra["svg_text"])

        with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(target)):
            kit.drive_dialog(FigureExportDialog, drive_export)
            app.export_with_options()
        assert not errors, errors
        assert target.exists() and target.stat().st_size > 0

    svg_text = (out / "legend-graph.svg").read_text(encoding="utf-8")
    assert "<image" not in svg_text
    assert "Legenda {IT} $α$" in svg_text
    assert "Tx {µM}" in svg_text
    ET.fromstring(svg_text)

    pdf_text, pdf_paths, pdf_images = _pdf_objects(out / "legend-graph.pdf")
    assert "Legenda {IT} $α$" in pdf_text
    assert "Tx {µM}" in pdf_text
    assert pdf_paths > 0 and pdf_images == 0

    def choose_layout(ldlg):
        ldlg.name.set("Layout Legend")
        ldlg.list.selection_set(0, 1)
        ldlg.add_selected()

    kit.drive_dialog(kit.LayoutDialog, choose_layout)
    app.new_layout()
    layout_png = out / "legend-layout.png"
    with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(layout_png)):
        app.export()
    assert layout_png.exists() and layout_png.stat().st_size > 0

    # Independent native panels must have separate editor widgets and saved labels.
    app.open_sheet(("graph", 2))
    wait()

    def drive_qq_format(fdlg):
        def drive_qq_legend(ldlg):
            assert len(ldlg.entry_vars) == len(ldlg.entries) == 4
            entry = next(e for e in ldlg.entries if e.scope == "qq:lognormal" and "reference" in e.label)
            ldlg.entry_vars[entry.key].set("Log model only")
            assert ldlg.preview()
            capture(ldlg, "window-legend-qq-dialog-it.png")
            ldlg.ok()

        drive_mapped_dialog(fdlg, LegendEditorDialog, drive_qq_legend, errors)
        fdlg.legend_button.invoke()
        assert not errors, errors
        fdlg.ok()

    drive_mapped_dialog(root, GraphFormatDialog, drive_qq_format, errors)
    app.format_graph()
    assert not errors, errors
    app.path = alab
    assert app.save()
    app.import_file(alab)
    app.open_sheet(("graph", 2))
    wait()
    fig = app.runs[2].result.figure
    labels = {ax._trama_qq_panel: [text.get_text() for text in ax.get_legend().get_texts()]
              for ax in fig.axes}
    assert "Log model only" in labels["lognormal"]
    assert "Log model only" not in labels["normal"]
    capture(root, "window-legend-qq-independent-it.png")
    svg = out / "legend-independent-panels.svg"
    fig.savefig(svg, format="svg")
    assert "Log model only" in svg.read_text(encoding="utf-8")
