"""Place graphs on a PDF layout as forms, preserving their paths, text and embedded images."""
from dataclasses import dataclass
from io import BytesIO
from math import isfinite

from matplotlib.figure import Figure

from .figure_export import MM, _render
from .layout_geometry import AUTO_PAPER, PT, WHITE, layout_frame, page_size
from .layout_panels import plan_panels
from .presentation import Layout


@dataclass(frozen=True)
class PdfLayoutPage:
    """A native layout and the calculated figures in its panel order."""

    title: str
    columns: int
    panels: tuple[Figure, ...]
    paper: str = AUTO_PAPER
    background: str = WHITE
    panel_size: str = "original"
    axis_alignment: str = "none"

    def __post_init__(self):
        Layout(self.title, self.columns, [("panel", index) for index in range(len(self.panels))],
               self.paper, self.background, self.panel_size, self.axis_alignment)
        for index, figure in enumerate(self.panels):
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
                           axis_alignment=self.axis_alignment)

    def frame(self, plan):
        scale = plan["width_mm"] / MM / self.size[0]
        return layout_frame(self.title, self.size, [panel.box for panel in self.placements],
                            scale, background=WHITE if plan["transparent"] else self.background)


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


def _add_panels(document, page, layout, plan):
    import pypdfium2 as pdfium
    from pypdfium2 import raw

    width, height = layout.size
    page_scale = plan["width_mm"] / MM / width
    for panel in layout.placements:
        w, h = panel.size
        x, y, fit = panel.box
        # PDF uses points with the origin at the bottom left. The form's bounding box clips the panel.
        scale = page_scale * fit
        matrix = raw.FS_MATRIX(scale, 0, 0, scale, x * PT * page_scale, (height - y - h * fit) * PT * page_scale)
        with panel.render() as figure, BytesIO() as buffer:
            _render(figure, {**plan, "width_mm": w * MM, "height_mm": h * MM}, buffer)
            buffer.seek(0)
            with pdfium.PdfDocument(buffer) as source:
                _place_form(document, page, source, matrix)
    if not raw.FPDFPage_GenerateContent(page):
        raise ValueError("Could not write the PDF layout page.")


def _fill_snapshot(document, page, pdf, plan):
    from pypdfium2 import PdfDocument, raw

    with PdfDocument(pdf) as source:
        original = source[0]
        try:
            width, height = original.get_size()
        finally:
            original.close()
        matrix = raw.FS_MATRIX(plan["width_mm"] * PT / MM / width, 0, 0,
                               plan["height_mm"] * PT / MM / height, 0, 0)
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
