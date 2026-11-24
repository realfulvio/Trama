"""Publication export of a figure: size in millimetres, DPI, transparency and SVG text handling.

`plan_export` validates the request and computes the final geometry without rendering.
`export_figure` renders it, checks the real file and replaces the destination only on success.
`export_pdf_bundle` writes several figures as the pages of one PDF with the same rules.
"""
from io import BytesIO
import math
import os
from pathlib import Path
import tempfile
from numbers import Real

import matplotlib as mpl

FORMATS = ("png", "tiff", "svg", "pdf")
SUFFIXES = {"png": {".png"}, "tiff": {".tif", ".tiff"}, "svg": {".svg"}, "pdf": {".pdf"}}
MM = 25.4
MIN_MM, MAX_MM = 20.0, 500.0
MIN_DPI, MAX_DPI = 72, 1200
MAX_SIDE_PIXELS, MAX_PIXELS = 12000, 50_000_000
DEFAULT_DPI = 300
PDF_FONT_TYPE = 42
PRESETS = {
    "Screen": {"format": "png", "dpi": 96, "width_mm": 160, "transparent": True},
    "Print": {"format": "tiff", "dpi": 300, "width_mm": 85, "transparent": False},
    "Vector": {"format": "pdf", "width_mm": 85, "transparent": False},
}


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number.")
    return float(value)


def _flag(value, name):
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be true or false.")
    return value


def plan_export(size_inches, settings):
    """Return the export plan for a figure of `size_inches`; raise ValueError for an invalid request."""
    try:
        width_in, height_in = (_number(v, "Figure size") for v in size_inches)
    except TypeError as error:
        raise ValueError("Figure size must be width and height.") from error
    if width_in <= 0 or height_in <= 0:
        raise ValueError("The figure has no size.")
    fmt = settings.get("format", "png")
    if fmt not in FORMATS:
        raise ValueError(f"Format must be one of {', '.join(FORMATS)}.")
    raster = fmt in {"png", "tiff"}
    requested = settings.get("width_mm")
    if requested is None or requested == "":
        width_mm, height_mm = width_in * MM, height_in * MM
    else:
        width_mm = _number(requested, "Width")
        height_mm = height_in / width_in * width_mm
    for name, value in (("Width", width_mm), ("Height", height_mm)):
        if not MIN_MM - 1e-9 <= value <= MAX_MM + 1e-9:
            raise ValueError(f"{name} must be between {MIN_MM:g} and {MAX_MM:g} mm (it is {value:.1f} mm).")
    dpi = pixels = None
    if raster:
        raw = settings.get("dpi", DEFAULT_DPI)
        if isinstance(raw, bool) or not isinstance(raw, Real) or not math.isfinite(raw) or raw != int(raw):
            raise ValueError("DPI must be a whole number.")
        dpi = int(raw)
        if not MIN_DPI <= dpi <= MAX_DPI:
            raise ValueError(f"DPI must be between {MIN_DPI} and {MAX_DPI}.")
        pixels = [math.floor(value * dpi / MM + .5) for value in (width_mm, height_mm)]
        if max(pixels) > MAX_SIDE_PIXELS:
            raise ValueError(f"The image would be {pixels[0]} × {pixels[1]} px; the limit is {MAX_SIDE_PIXELS} px per side.")
        if pixels[0] * pixels[1] > MAX_PIXELS:
            raise ValueError(f"The image would have {pixels[0] * pixels[1]:,} pixels; the limit is {MAX_PIXELS:,}.")
    transparent = False if fmt == "tiff" else _flag(settings.get("transparent", False), "Transparent")
    svg_text = None
    if fmt == "svg":
        svg_text = settings.get("svg_text", "text")
        if svg_text not in {"text", "paths"}:
            raise ValueError("SVG text must be Text or Paths.")
    return {"format": fmt, "width_mm": width_mm, "height_mm": height_mm, "dpi": dpi, "pixels": pixels,
            "transparent": transparent, "svg_text": svg_text}


def check_destination(path, fmt):
    if Path(path).suffix.lower() not in SUFFIXES[fmt]:
        wanted = " or ".join(sorted(SUFFIXES[fmt]))
        raise ValueError(f"The file name must end with {wanted} for the {fmt.upper()} format.")


def _render(figure, plan, target):
    fmt = plan["format"]
    if fmt == "pdf" and (pdf := getattr(figure, "_trama_frozen_pdf", None)):
        from .layout_pdf import write_frozen_pdf

        write_frozen_pdf(pdf, target, plan)
        return
    if plan["pixels"] is not None:
        # Agg truncates the pixel size: aim just above the integer so the file has exactly the planned pixels.
        size = [(p + 1e-6) / plan["dpi"] for p in plan["pixels"]]
    else:
        size = [plan["width_mm"] / MM, plan["height_mm"] / MM]
    original = tuple(figure.get_size_inches())
    original_dpi, original_canvas = figure.dpi, figure.canvas
    rc = {"svg.fonttype": "none" if plan["svg_text"] == "text" else "path", "pdf.fonttype": PDF_FONT_TYPE}
    try:
        with mpl.rc_context(rc):
            figure.set_size_inches(size, forward=False)
            dpi = plan["dpi"] or DEFAULT_DPI
            if fmt == "tiff":
                from PIL import Image

                with BytesIO() as buffer:
                    figure.savefig(buffer, format="png", dpi=dpi, transparent=False)
                    buffer.seek(0)
                    with Image.open(buffer) as image:
                        image.convert("RGB").save(target, format="TIFF", compression="tiff_lzw", dpi=(dpi, dpi))
            else:
                kwargs = {"pil_kwargs": {"dpi": (dpi, dpi)}} if fmt == "png" else {}
                figure.savefig(target, format=fmt, dpi=dpi, transparent=plan["transparent"], **kwargs)
    finally:
        figure.set_size_inches(original, forward=False)
        figure.dpi = original_dpi
        figure.canvas = original_canvas


def _verify(path, plan):
    if plan["pixels"] is not None:
        from PIL import Image

        with Image.open(path) as image:
            if list(image.size) != plan["pixels"]:
                raise ValueError(f"The rendered image is {image.size[0]} × {image.size[1]} px, not {plan['pixels'][0]} × {plan['pixels'][1]}.")


def export_figure(figure, path, settings, *, size_inches=None):
    """Write `figure` to `path`; the destination is replaced only after a verified render."""
    plan = plan_export(figure.get_size_inches() if size_inches is None else size_inches, settings)
    path = Path(path)
    check_destination(path, plan["format"])
    handle, name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=path.suffix, dir=path.parent)
    os.close(handle)
    temp = Path(name)
    try:
        _render(figure, plan, temp)
        _verify(temp, plan)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return plan


MAX_BUNDLE_PAGES = 64


def plan_pdf_bundle(sizes, settings, names=None):
    """Return one PDF plan per page size (inches); raise ValueError naming the first page that cannot be exported."""
    sizes = list(sizes)
    if not 1 <= len(sizes) <= MAX_BUNDLE_PAGES:
        raise ValueError(f"Select between 1 and {MAX_BUNDLE_PAGES} graphs or layouts (there are {len(sizes)}).")
    fmt = settings.get("format", "pdf")
    if fmt != "pdf":
        raise ValueError("A multi-page export is always a PDF.")
    settings = {key: value for key, value in settings.items() if key in {"width_mm", "transparent"}}
    settings["format"] = "pdf"
    plans = []
    for index, size in enumerate(sizes):
        try:
            plans.append(plan_export(size, settings))
        except ValueError as error:
            label = f"“{names[index]}”" if names is not None else f"{index + 1}"
            raise ValueError(f"Page {index + 1} ({label}): {error}" if names is not None
                             else f"Page {label}: {error}") from None
    return plans


def export_pdf_bundle(figures, path, settings, names=None):
    """Write figures and native layout pages in order as one PDF. Return the per-page plans.

    Every page is validated before writing; each keeps its own aspect ratio and is drawn by the
    Matplotlib PDF backend, so native vector content stays vector. The PDF is written to a temporary
    file in the destination folder, its page count is checked with PDFium and only then it replaces
    `path`. Figures keep their size, DPI and canvas even when a page fails.
    """
    from matplotlib.backends.backend_pdf import PdfPages
    from matplotlib.figure import Figure

    from .layout_pdf import PdfLayoutPage, add_layout_panels

    try:
        figures = list(figures)
    except TypeError:
        raise ValueError("Pass the figures to export as a sequence.") from None
    if not 1 <= len(figures) <= MAX_BUNDLE_PAGES:
        raise ValueError(f"Select between 1 and {MAX_BUNDLE_PAGES} graphs or layouts (there are {len(figures)}).")
    for index, figure in enumerate(figures):
        if not isinstance(figure, (Figure, PdfLayoutPage)):
            raise ValueError(f"Page {index + 1} has no figure to export.")
    plans = plan_pdf_bundle([figure.size if isinstance(figure, PdfLayoutPage) else figure.get_size_inches()
                             for figure in figures], settings, names)
    layouts = [(index, figure, plan) for index, (figure, plan) in enumerate(zip(figures, plans))
               if isinstance(figure, PdfLayoutPage)]
    frozen = [(index, payload, plan) for index, (figure, plan) in enumerate(zip(figures, plans))
              if (payload := getattr(figure, "_trama_frozen_pdf", None))]
    for index, layout, plan in layouts:
        figures[index] = layout.frame(plan)
    for index, _, _ in frozen:
        figures[index] = Figure(figsize=figures[index].get_size_inches())

    def render_pages(target):
        # PdfPages embeds fonts when it closes, after the per-figure render has returned.
        with mpl.rc_context({"pdf.fonttype": PDF_FONT_TYPE}), PdfPages(target, metadata={"Creator": "Trama"}) as document:
            for figure, plan in zip(figures, plans):
                _render(figure, plan, document)

    path = Path(path)
    check_destination(path, "pdf")
    handle, name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=path.suffix, dir=path.parent)
    os.close(handle)
    temp = Path(name)
    try:
        if layouts or frozen:
            with tempfile.TemporaryFile() as base:
                render_pages(base)
                add_layout_panels(base, temp, layouts, frozen=frozen)
        else:
            render_pages(temp)
        _verify_pdf(temp, plans)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return plans


def _verify_pdf(path, plans):
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(path))
    try:
        if len(document) != len(plans):
            raise ValueError(f"The PDF has {len(document)} pages instead of {len(plans)}.")
        for index, plan in enumerate(plans):
            page = document[index]
            try:
                width, height = page.get_size()
            finally:
                page.close()
            want = plan["width_mm"] / MM * 72, plan["height_mm"] / MM * 72
            if abs(width - want[0]) > .05 or abs(height - want[1]) > .05:
                raise ValueError(f"Page {index + 1} is {width:.1f} × {height:.1f} pt, not {want[0]:.1f} × {want[1]:.1f}.")
    finally:
        document.close()
