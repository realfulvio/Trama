"""Place graphs on a PDF layout as forms, preserving their paths, text and embedded images."""
from contextlib import contextmanager
from ctypes import c_float
from dataclasses import dataclass
from io import BytesIO
from math import isfinite

from matplotlib.figure import Figure

from .figure_export import MM, _render
from .layout_arrangement import BORDER_DASHES, PanelArrangement
from .layout_geometry import AUTO_PAPER, PT, WHITE, layout_frame, page_size
from .layout_panels import EMPTY_PANEL, layout_labels, plan_panels, rotation_bounds
from .linked_tables import overlay_figure
from .presentation import Layout


@dataclass(frozen=True)
class PdfLayoutPage:
    """A native layout and the calculated figures in its panel order."""

    title: str
    columns: int
    panels: tuple  # Calculated figures and EMPTY_PANEL slots
    paper: str = AUTO_PAPER
    background: str = WHITE
    panel_size: str = "original"
    axis_alignment: str = "none"
    tables: tuple = ()      # ``linked_tables.TableSpec`` objects drawn on the page itself, above the panels
    arrangement: PanelArrangement = PanelArrangement()

    def __post_init__(self):
        Layout(self.title, self.columns, [("panel", index) for index in range(len(self.panels))],
               self.paper, self.background, self.panel_size, self.axis_alignment)
        for index, figure in enumerate(self.panels):
            if figure is EMPTY_PANEL:
                continue
            if not isinstance(figure, Figure):
                raise ValueError(f"Panel {chr(ord('A') + index)} has no figure to export.")
            if not all(isfinite(value) and value > 0 for value in figure.get_size_inches()):
                raise ValueError(f"Panel {chr(ord('A') + index)} has no usable size.")

    @property
    def size(self):
        return page_size(self.columns, len(self.panels), self.paper)

    @property
    def placements(self):
        return plan_panels(self.columns, self.panels, self.paper, panel_size=self.panel_size,
                           axis_alignment=self.axis_alignment, arrangement=self.arrangement)

    def frame(self, plan):
        scale = plan["width_mm"] / MM / self.size[0]
        placements = self.placements
        labels = layout_labels(placements, self.arrangement.paint_order(len(placements)))
        boxes = [panel.box if index in labels else None for index, panel in enumerate(placements)]
        return layout_frame(self.title, self.size, boxes, scale, background=WHITE if plan["transparent"] else self.background)


def _place_form(document, page, source, matrix):
    from pypdfium2 import raw

    template = raw.FPDF_NewXObjectFromPage(document, source, 0)
    if not template:
        raise ValueError("Could not copy the PDF panel.")
    try:
        form = raw.FPDF_NewFormObjectFromXObject(template)
        if not form:
            raise ValueError("Could not create the PDF panel.")
    finally:
        raw.FPDF_CloseXObject(template)
    if not raw.FPDFPageObj_TransformF(form, matrix):
        raw.FPDFPageObj_Destroy(form)
        raise ValueError("Could not position the PDF panel.")
    # PDFium takes ownership even if insertion fails.
    if not raw.FPDFPage_InsertObject(page, form):
        raise ValueError("Could not insert the PDF panel.")


def _add_tables(document, page, layout, plan):
    """The tables of the layout page: one transparent PDF page drawn above every panel, text and rules as vectors."""
    import pypdfium2 as pdfium
    from pypdfium2 import raw

    width, height = layout.size
    page_scale = plan["width_mm"] / MM / width
    overlay = overlay_figure((width, height), layout.tables)
    with BytesIO() as buffer:
        _render(overlay, {**plan, "width_mm": width * MM, "height_mm": height * MM, "transparent": True}, buffer)
        buffer.seek(0)
        with pdfium.PdfDocument(buffer) as source:
            _place_form(document, page, source, raw.FS_MATRIX(page_scale, 0, 0, page_scale, 0, 0))
    if not raw.FPDFPage_GenerateContent(page):
        raise ValueError("Could not write the PDF layout tables.")


def _add_border(page, panel, height, page_scale):
    from pypdfium2 import raw

    x, y, fit = panel.box
    w, h = panel.oriented_size
    unit = PT * page_scale
    width, color, style = panel.border
    stroke = width * page_scale
    rgb = bytes.fromhex(color[1:])
    rect = raw.FPDFPageObj_CreateNewRect(x * unit, (height - y - h * fit) * unit, w * fit * unit, h * fit * unit)
    if not rect:
        raise ValueError("Could not create the PDF panel border.")
    try:
        if not (raw.FPDFPageObj_SetStrokeWidth(rect, stroke) and raw.FPDFPageObj_SetStrokeColor(rect, *rgb, 255)
                and raw.FPDFPath_SetDrawMode(rect, raw.FPDF_FILLMODE_NONE, 1)):
            raise ValueError("Could not set the PDF panel border.")
        if dashes := BORDER_DASHES[style]:
            lengths = (c_float * len(dashes))(*(length * stroke for length in dashes))
            if not raw.FPDFPageObj_SetDashArray(rect, lengths, len(dashes), 0):
                raise ValueError("Could not set the PDF panel border style.")
    except BaseException:
        raw.FPDFPageObj_Destroy(rect)
        raise
    if not raw.FPDFPage_InsertObject(page, rect):
        raise ValueError("Could not insert the PDF panel border.")


@contextmanager
def _panel_view(source, panel):
    if not any(panel.crop):
        yield source
        return

    from pypdfium2 import PdfDocument, raw

    width, height = panel.cropped_size
    left, _, _, bottom = panel.crop_bounds
    with PdfDocument.new() as cropped:
        page = cropped.new_page(width * PT, height * PT)
        try:
            # Limit the locally translated source form to the new page while keeping its native vectors.
            _place_form(cropped, page, source, raw.FS_MATRIX(1, 0, 0, 1, -left * PT, (bottom - panel.size[1]) * PT))
            if not raw.FPDFPage_GenerateContent(page):
                raise ValueError("Could not crop the PDF panel.")
        finally:
            page.close()
        yield cropped


@contextmanager
def _panel_pdf(panel, plan):
    from pypdfium2 import PdfDocument, raw

    width, height = (value * PT for value in panel.size)
    if pdf := getattr(panel.figure, "_trama_layout_picture_pdf", None):
        with PdfDocument(pdf) as original:
            original_w, original_h = original.get_page_size(0)
            if abs(width - original_w) < 1e-6 and abs(height - original_h) < 1e-6:
                yield original
                return
            with PdfDocument.new() as scaled:
                page = scaled.new_page(width, height)
                try:
                    matrix = raw.FS_MATRIX(width / original_w, 0, 0, height / original_h, 0, 0)
                    _place_form(scaled, page, original, matrix)
                    if not raw.FPDFPage_GenerateContent(page):
                        raise ValueError("Could not resize the layout picture.")
                finally:
                    page.close()
                yield scaled
    else:
        with panel.render() as figure, BytesIO() as buffer:
            source_w, source_h = panel.size
            _render(figure, {**plan, "width_mm": source_w * MM, "height_mm": source_h * MM}, buffer)
            buffer.seek(0)
            with PdfDocument(buffer) as source:
                yield source


def _add_panels(document, page, layout, plan):
    from pypdfium2 import raw

    width, height = layout.size
    page_scale = plan["width_mm"] / MM / width
    placements = layout.placements
    for index in layout.arrangement.paint_order(len(placements)):
        panel = placements[index]
        if panel.figure is None:
            continue
        w, h = panel.cropped_size
        left, top, _, _, c, s = rotation_bounds(w, h, panel.angle)
        x, y, fit = panel.box
        # PDF uses points with the origin at the bottom left. The form's bounding box clips the panel.
        scale = page_scale * fit
        unit = PT * page_scale
        matrix = raw.FS_MATRIX(c * scale, -s * scale, s * scale, c * scale,
                               (x - (s * h + left) * fit) * unit, (height - y + (top - c * h) * fit) * unit)
        with _panel_pdf(panel, plan) as source, _panel_view(source, panel) as viewport:
            _place_form(document, page, viewport, matrix)
        if panel.border:
            _add_border(page, panel, height, page_scale)
    if not raw.FPDFPage_GenerateContent(page):
        raise ValueError("Could not write the PDF layout page.")
    if layout.tables:
        _add_tables(document, page, layout, plan)


def _fill_snapshot(document, page, pdf, plan):
    from pypdfium2 import PdfDocument, raw

    with PdfDocument(pdf) as source:
        original = source[0]
        try:
            width, height = original.get_size()
        finally:
            original.close()
        target_width, target_height = (plan[key] * PT / MM for key in ("width_mm", "height_mm"))
        scale = min(target_width / width, target_height / height)
        matrix = raw.FS_MATRIX(scale, 0, 0, scale, (target_width - width * scale) / 2,
                               (target_height - height * scale) / 2)
        _place_form(document, page, source, matrix)
    if not raw.FPDFPage_GenerateContent(page):
        raise ValueError("Could not write the frozen PDF.")


def write_frozen_pdf(pdf, target, plan):
    from pypdfium2 import PdfDocument, PdfiumError

    try:
        with PdfDocument.new() as document:
            page = document.new_page(plan["width_mm"] * PT / MM, plan["height_mm"] * PT / MM)
            try:
                _fill_snapshot(document, page, pdf, plan)
            finally:
                page.close()
            document.save(target)
    except PdfiumError as error:
        raise ValueError(f"Could not write the frozen PDF: {error}") from error


def add_layout_panels(base, target, layouts, *, frozen=()):
    """Insert panels into the corresponding pages of a PDF containing the layout frames."""
    import pypdfium2 as pdfium

    try:
        base.seek(0)
        with pdfium.PdfDocument(base) as document:
            for index, layout, plan in layouts:
                page = document[index]
                try:
                    _add_panels(document, page, layout, plan)
                finally:
                    page.close()
            for index, pdf, plan in frozen:
                page = document[index]
                try:
                    _fill_snapshot(document, page, pdf, plan)
                finally:
                    page.close()
            document.save(target)
    except pdfium.PdfiumError as error:
        raise ValueError(f"Could not write the PDF layout: {error}") from error
