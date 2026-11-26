"""Inspect and render one-page PDF drawings embedded in saved external graphs."""
from contextlib import contextmanager
from math import isfinite
from threading import Lock

import pypdfium2 as pdfium


# PDFium calls are serialized even when a gallery and the analysis worker overlap.
_PDFIUM_LOCK = Lock()


@contextmanager
def _page(data):
    if not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF"):
        raise ValueError("Invalid saved legacy PDF drawing.")
    try:
        with _PDFIUM_LOCK, pdfium.PdfDocument(data) as document:
            if len(document) != 1:
                raise ValueError("A saved legacy PDF drawing must have one page.")
            page = document[0]
            try:
                width, height = page.get_size()
                if (not all(isfinite(side) and 1 <= side <= 14_400 for side in (width, height))
                        or max(width, height) > 100 * min(width, height)):
                    raise ValueError("Invalid saved legacy PDF drawing dimensions.")
                yield page, (width, height)
            finally:
                page.close()
    except pdfium.PdfiumError as exc:
        raise ValueError("Could not read the saved legacy PDF drawing.") from exc


def pdf_dimensions(data):
    with _page(data) as (_, dimensions):
        return dimensions


def _render_page(page, dimensions, max_side, *, transparent=False):
    fill = (0, 0, 0, 0) if transparent else (255, 255, 255, 255)
    bitmap = page.render(scale=max_side / max(dimensions), draw_annots=False, fill_color=fill)
    try:
        return bitmap.to_pil().convert("RGBA" if transparent else "RGB")
    finally:
        bitmap.close()


def render_pdf(data, max_side, *, transparent=False):
    with _page(data) as (page, dimensions):
        return _render_page(page, dimensions, max_side, transparent=transparent)
