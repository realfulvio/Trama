"""Embedded, fixed artwork captured from a layout graph."""

from base64 import b64decode, b64encode
from functools import lru_cache
from io import BytesIO

from matplotlib.figure import Figure

from .legacy_pdf_preview import pdf_dimensions, render_pdf
from .layout_panels import panel_background

MAX_PICTURE_TEXT = 16 * 1024 * 1024


@lru_cache(maxsize=12)
def source_size(payload):
    """Validate the one-page drawing and return its native dimensions in inches."""
    pdf = b64decode(payload, validate=True)
    return tuple(value / 72 for value in pdf_dimensions(pdf))


def validate_picture(width, height, payload):
    if (any(type(side) not in (int, float) or not 1 / 72 <= side <= 200 for side in (width, height))
            or not isinstance(payload, str) or not 0 < len(payload) <= MAX_PICTURE_TEXT):
        raise ValueError("Invalid layout picture.")
    source_size(payload)


def capture_picture(figure, *, clear_background=False):
    """Snapshot the currently confirmed drawing, with no reference to data or analysis state."""
    size = tuple(map(float, figure.get_size_inches()))
    pdf = getattr(figure, "_trama_frozen_pdf", None)
    if pdf is None:
        original_canvas = figure.canvas
        try:
            with panel_background(figure, clear_background), BytesIO() as output:
                figure.savefig(output, format="pdf", metadata={"CreationDate": None})
                pdf = output.getvalue()
        finally:
            figure.set_canvas(original_canvas)
    payload = b64encode(pdf).decode("ascii")
    validate_picture(*size, payload)
    return *size, payload


@lru_cache(maxsize=4)
def _preview(payload, transparent):
    return render_pdf(b64decode(payload, validate=True), 2200, transparent=transparent)


def picture_figure(picture, *, transparent=False):
    width, height, payload = picture
    figure = Figure(figsize=(width, height))
    axes = figure.add_axes((0, 0, 1, 1))
    axes.imshow(_preview(payload, transparent), aspect="auto")
    axes.set_axis_off()
    figure._trama_layout_picture_pdf = b64decode(payload, validate=True)
    figure._trama_layout_picture_size = source_size(payload)
    return figure
