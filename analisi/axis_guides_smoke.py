"""Desktop smoke check for axis guides (ticks, labels, reference lines) and shaded ranges.

``tramastat.py --smoke`` calls :func:`check_axis_guides` with its own helpers.
Alone: ``TRAMASTAT_SMOKE_ONLY=axis-guides python tramastat.py --smoke DIR``.

Synthetic data only. Artifacts and the project stay in ``DIR/axis-guides``; screenshots in ``DIR``.
"""
from copy import deepcopy
from unittest.mock import patch
from xml.etree import ElementTree as ET

import pandas as pd
import pypdfium2 as pdfium
from pypdfium2 import raw as pdfraw

from . import i18n, ui_theme
from .axis_guides import AXIS_BANDS, AXIS_GUIDES
from .axis_guides_dialog import AxisBandsDialog, AxisGuidesDialog, BandEditorDialog, GuideEditorDialog
from .data import Dataset, save_project
from .figure_export_dialog import FigureExportDialog
from .graph_dialog import GraphFormatDialog
from .graph_language_smoke import drive_mapped_dialog


TITLE = "Dose study"


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
        assert button.winfo_rooty() + button.winfo_height() <= bottom + 1, button


def check_axis_guides(kit):
    """Run the end-to-end axis guides & bands smoke test inside the real Trama application."""
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
    out = kit.directory / "axis-guides"
    out.mkdir(exist_ok=True)
    alab = out / "axis-guides.alab"

    frame = pd.DataFrame({
        "Time": [0.0, 1.0, 2.0, 3.0, 4.0],
        "Control": [1.0, 2.1, 3.0, 2.2, 1.2],
        "Treated": [10.0, 22.0, 35.0, 28.0, 18.0],
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
    dataset.analyses.append(("Column graph", {"Variables": ["Control", "Treated"]}))
    save_project(alab, {TITLE: dataset})

    # --- Part 1: English + Standard theme + Format Graph -------------------------
    i18n.set_language("en")
    ui_theme.configure(root, "standard")
    app.import_file(alab)
    app.open_sheet(("graph", 0))
    wait()
    run = app.runs[0]

    def drive_format(dlg):
        dlg.notebook.select(3)
        _fits(dlg, (dlg.guides_button, dlg.bands_button), root)

        # Open Additional ticks and grids…
        def drive_guides(gdlg):
            _fits(gdlg, (gdlg.apply_button, gdlg.cancel_button), root)

            def drive_add_guide(ed):
                _fits(ed, (ed.preview_button, ed.ok_button, ed.cancel_button), root)
                ed.fields["axis"].set("x")
                ed.fields["value"].set("2.5")
                ed.fields["tick"].set(True)
                ed.fields["line"].set(True)
                ed.fields["label"].set("$literal$, A")
                ed.fields["color"].set("#008577")
                ed.fields["width"].set("1.5")
                assert ed.preview()
                # Trigger invalid width after valid preview -> stays open, focuses width, then recovers
                ed.fields["width"].set("99")
                assert not ed.preview()
                assert ed.winfo_exists() and ed.error_widget is ed.widgets["width"]
                ed.fields["width"].set("1.5")
                ed.ok()

            drive_mapped_dialog(gdlg, GuideEditorDialog, drive_add_guide, errors)
            gdlg.add()
            assert not errors, errors
            assert len(gdlg.records) == 1

            # Add an opposite Y guide too
            def drive_add_opp(ed):
                ed.fields["axis"].set("y")
                ed.fields["value"].set("2.0")
                ed.fields["tick"].set(True)
                ed.fields["line"].set(True)
                ed.fields["label"].set("Cut Y")
                ed.fields["side"].set("opposite")
                ed.fields["color"].set("#aa3355")
                ed.ok()

            drive_mapped_dialog(gdlg, GuideEditorDialog, drive_add_opp, errors)
            gdlg.add()
            assert not errors, errors
            gdlg.preview()
            gdlg.update()
            capture(gdlg, "window-axis-guides-dialog-en.png")
            gdlg.ok()

        drive_mapped_dialog(dlg, AxisGuidesDialog, drive_guides, errors)
        dlg.guides_button.invoke()
        assert not errors, errors

        # Open Shaded ranges…
        def drive_bands(bdlg):
            _fits(bdlg, (bdlg.apply_button, bdlg.cancel_button), root)

            def drive_add_band(ed):
                _fits(ed, (ed.preview_button, ed.ok_button, ed.cancel_button), root)
                ed.fields["axis"].set("x")
                ed.fields["lower"].set("1.0")
                ed.fields["upper"].set("3.0")
                ed.fields["color"].set("#ccddee")
                ed.fields["alpha"].set("0.22")
                ed.fields["hatch"].set("/")
                ed.ok()

            drive_mapped_dialog(bdlg, BandEditorDialog, drive_add_band, errors)
            bdlg.add()
            assert not errors, errors
            bdlg.ok()

        drive_mapped_dialog(dlg, AxisBandsDialog, drive_bands, errors)
        dlg.bands_button.invoke()
        assert not errors, errors
        dlg.ok()

    drive_mapped_dialog(root, GraphFormatDialog, drive_format, errors)
    app.format_graph()
    assert not errors, errors
    assert len(run.style.get(AXIS_GUIDES, [])) == 2
    assert len(run.style.get(AXIS_BANDS, [])) == 1
    # Verify twin right axis was NOT touched
    left_ax, right_ax = run.result.figure.axes
    assert "$literal$, A" in [t.get_text() for t in left_ax.get_xticklabels()]
    assert not any(str(a.get_gid()).startswith(("trama-axis-guide:", "trama-axis-band:"))
                   for a in right_ax.get_children())
    root.update()
    capture(root, "window-axis-guides-en.png")

    # --- Part 2: Inspector transaction (child preview+Cancel, parent Cancel, Apply) ---
    app.toggle_inspector()
    inspector = app.inspector
    assert inspector is not None
    root.update()

    # Child preview + Cancel keeps parent draft untouched
    inspector.vars["title"].set("Draft XY Title")
    inspector._now("title")

    def drive_inspector_child_cancel(gdlg):
        gdlg.tree.selection_set("0")
        gdlg.duplicate()
        gdlg.records[1]["value"] = 3.5
        gdlg.records[1]["label"] = "Extra"
        gdlg.preview()
        assert "Extra" in [t.get_text() for t in left_ax.get_xticklabels()]
        gdlg.cancel()

    drive_mapped_dialog(inspector, AxisGuidesDialog, drive_inspector_child_cancel, errors)
    inspector.axis_guides_button.invoke()
    assert not errors, errors
    assert len(inspector.draft[AXIS_GUIDES]) == 2
    assert "Extra" not in [t.get_text() for t in left_ax.get_xticklabels()]
    assert left_ax.get_title() == "Draft XY Title"

    # Parent Inspector Cancel restores confirmed style
    inspector.cancel_button.invoke()
    root.update()
    assert app.inspector is None
    assert left_ax.get_title() != "Draft XY Title"

    # --- Part 3: Italian + Save/Reopen + Source Edit & Exclusion + Exports ---
    i18n.set_language("it")
    app.toggle_inspector()
    inspector = app.inspector
    assert inspector is not None

    def drive_it_guide_edit(gdlg):
        def drive_edit(ed):
            ed.fields["value"].set("2,25")
            ed.ok()

        drive_mapped_dialog(gdlg, GuideEditorDialog, drive_edit, errors)
        gdlg.tree.selection_set("0")
        gdlg.edit()
        assert not errors, errors
        gdlg.ok()

    drive_mapped_dialog(inspector, AxisGuidesDialog, drive_it_guide_edit, errors)
    inspector.axis_guides_button.invoke()
    assert not errors, errors
    assert inspector.apply()
    root.update()
    capture(root, "window-axis-guides-it.png")
    inspector.cancel_button.invoke()
    root.update()

    assert run.style[AXIS_GUIDES][0]["value"] == 2.25
    assert app.tables[TITLE].graph_styles[0][AXIS_GUIDES][0]["value"] == 2.25

    # Save .alab and reopen -> canonical recipe/styles preserved
    app.path = alab
    assert app.save()
    app.import_file(alab)
    app.open_sheet(("graph", 0))
    wait()
    reopened = app.runs[0]
    assert reopened.style[AXIS_GUIDES][0]["value"] == 2.25
    assert reopened.style[AXIS_GUIDES][0]["label"] == "$literal$, A"
    assert len(reopened.style[AXIS_BANDS]) == 1

    # Modify and exclude a source cell -> recalculation keeps guides & bands
    app.show("data", TITLE)
    app.edit_cell(0, 1, "1.5")
    wait()
    app.current_grid.active_cell = (4, 1)
    app.toggle_exclusion()
    wait()
    updated_run = app.runs[0]
    assert "$literal$, A" in [t.get_text() for t in updated_run.result.figure.axes[0].get_xticklabels()]

    # Export CSV, PNG, SVG (vector!), PDF (vector!)
    app.show("data", TITLE)
    csv_path = out / "source.csv"
    with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(csv_path)):
        app.export()
    assert csv_path.exists() and csv_path.stat().st_size > 0

    app.show("graph", 0)
    for fmt, ext, extra in (
        ("PNG", "png", {}),
        ("SVG", "svg", {"svg_text": "Text"}),
        ("PDF", "pdf", {}),
    ):
        target = out / f"xy-guides.{ext}"

        def drive_export(edlg, fmt=fmt, extra=extra):
            edlg.format.set(fmt)
            if "svg_text" in extra:
                edlg.svg_text.set(extra["svg_text"])

        with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(target)):
            kit.drive_dialog(FigureExportDialog, drive_export)
            app.export_with_options()
        assert not errors, errors
        assert target.exists() and target.stat().st_size > 0

    svg_text = (out / "xy-guides.svg").read_text(encoding="utf-8")
    assert "<image" not in svg_text
    assert "$literal$, A" in svg_text
    assert "trama-axis-band:" in svg_text
    ET.fromstring(svg_text)

    pdf_text, pdf_paths, pdf_images = _pdf_objects(out / "xy-guides.pdf")
    assert "$literal$, A" in pdf_text
    assert pdf_paths > 0 and pdf_images == 0

    # Two-panel layout with Column graph on panel 2 (also checks Modern theme screenshot)
    app.open_sheet(("graph", 1))
    wait()
    col_run = app.runs[1]
    assert col_run.result is not None

    def choose_layout(ldlg):
        ldlg.name.set("Layout Axis Guides")
        ldlg.list.selection_set(0, 1)
        ldlg.add_selected()

    kit.drive_dialog(kit.LayoutDialog, choose_layout)
    app.new_layout()
    layout_svg = out / "layout-guides.svg"
    layout_pdf = out / "layout-guides.pdf"
    with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(layout_svg)):
        app.export()
    with patch.object(kit.filedialog, "asksaveasfilename", return_value=str(layout_pdf)):
        app.export()
    assert "<image" not in layout_svg.read_text(encoding="utf-8")
    assert layout_pdf.read_bytes().startswith(b"%PDF")

    # Modern theme screenshot with ModernWorksheet Inspector visible
    ui_theme.configure(root, "modern")
    app.show("data", TITLE)
    root.update()
    ws = app.modern_workspace
    assert ws is not None and ws.inspector is not None
    ws.choice.current(0)
    ws._chosen()
    if not ws.sidebar_wanted.get():
        ws.show_format()
    root.update()
    assert hasattr(ws.inspector, "axis_guides_button")
    capture(root, "window-axis-guides-modern.png")
    ui_theme.configure(root, "standard")
