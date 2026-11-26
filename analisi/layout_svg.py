"""Native layouts as one vector SVG: every panel keeps the SVG primitives Matplotlib draws for it.

The screen preview and PNG and TIFF exports of a layout use ``presentation.compose_layout``,
which pastes a PNG of each graph. ``export_layout_svg`` writes the same page geometry
(4.2 × columns by 3.2 × rows + 0.4 inches, panels in row order with A, B, C markers) but
renders each source figure to SVG in memory and nests its elements in the page, so lines, text,
axes, legends and annotations stay editable. Images that are part of a graph stay images.

Panel IDs are made unique with a per-panel prefix and every ``href``, ``xlink:href`` and
``url(#…)`` reference is rewritten to match. Only documents Matplotlib produced during the call
are parsed. The engine does not import Tk.
"""
from io import BytesIO
import os
from pathlib import Path
import re
import tempfile
from xml.etree import ElementTree as ET

import matplotlib as mpl
from matplotlib.figure import Figure

from .figure_export import DEFAULT_DPI, MM, check_destination, plan_export
from .layout_arrangement import BORDER_DASHES, PanelArrangement
from .layout_geometry import AUTO_PAPER, PT, WHITE, layout_frame, page_size
from .layout_panels import EMPTY_PANEL, layout_labels, plan_panels, rotation_bounds
from .linked_tables import overlay_figure
from .presentation import Layout

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
SVG = "{%s}" % SVG_NS
XLINK_HREF = "{%s}href" % XLINK_NS
URL = re.compile(r"""url\(\s*(["']?)#([^)"'\s]+)\1\s*\)""")


def _render_svg(figure, plan, rc):
    """SVG bytes of ``figure`` at its own size; size, DPI and canvas are restored afterwards."""
    original = tuple(figure.get_size_inches())
    original_dpi, original_canvas = figure.dpi, figure.canvas
    try:
        with mpl.rc_context(rc), BytesIO() as buffer:
            dpi = min(DEFAULT_DPI, 4096 / max(original)) if hasattr(figure, "_trama_layout_picture_pdf") else DEFAULT_DPI
            figure.savefig(buffer, format="svg", dpi=dpi, transparent=plan["transparent"])
            return buffer.getvalue()
    finally:
        figure.set_size_inches(original, forward=False)
        figure.dpi = original_dpi
        figure.canvas = original_canvas


def _prefix_ids(root, prefix):
    """Give every id in ``root`` a prefix and update internal references to them."""
    mapping = {}
    for element in root.iter():
        old = element.get("id")
        if old is not None:
            mapping[old] = prefix + old
            element.set("id", prefix + old)

    def link(match):
        target = mapping.get(match.group(2))
        return match.group(0) if target is None else f"url(#{target})"

    for element in root.iter():
        for key, value in element.attrib.items():
            if key in {"href", XLINK_HREF} and value.startswith("#") and value[1:] in mapping:
                element.set(key, "#" + mapping[value[1:]])
            elif "url(" in value:
                element.set(key, URL.sub(link, value))


def _children(document):
    """Drawing children of a Matplotlib SVG document, without its metadata."""
    root = ET.fromstring(document)
    if root.tag != SVG + "svg":
        raise ValueError("Matplotlib did not produce an SVG document.")
    return root, [child for child in root if child.tag != SVG + "metadata"]


def _size_attr(mm):
    return f"{mm:.4f}".rstrip("0").rstrip(".") + "mm"


def _verify(path, plan, images):
    root = ET.parse(path).getroot()
    if root.tag != SVG + "svg":
        raise ValueError("The written file is not an SVG document.")
    for name, want in (("width", plan["width_mm"]), ("height", plan["height_mm"])):
        got = root.get(name, "")
        if not got.endswith("mm") or abs(float(got[:-2]) - want) > .01:
            raise ValueError(f"The SVG {name} is {got}, not {want:.2f} mm.")
    ids = [element.get("id") for element in root.iter() if element.get("id") is not None]
    if len(ids) != len(set(ids)):
        raise ValueError("The SVG has duplicate element IDs.")
    known = set(ids)
    for element in root.iter():
        for key, value in element.attrib.items():
            targets = [value[1:]] if key in {"href", XLINK_HREF} and value.startswith("#") else []
            targets += [match.group(2) for match in URL.finditer(value)]
            missing = [target for target in targets if target not in known]
            if missing:
                raise ValueError(f"The SVG refers to a missing element #{missing[0]}.")
    if len(root.findall(".//" + SVG + "image")) != images:
        raise ValueError("The SVG lost or gained embedded images.")


def export_layout_svg(title, columns, figures, path, settings, *, paper=AUTO_PAPER, background=WHITE,
                      panel_size="original", axis_alignment="none", tables=(), arrangement=PanelArrangement()):
    """Write the layout ``title`` with ``figures`` (panel order) to ``path`` as a vector SVG.

    ``settings`` are those of File → Export with options… with format ``svg``: ``width_mm``
    (None keeps the native page size), ``svg_text`` (``text`` or ``paths``) and ``transparent``.
    Every panel is rendered before anything is written; the SVG is written to a temporary file in
    the destination folder, checked, and only then replaces ``path``. Returns the export plan.
    ``tables`` (``linked_tables.TableSpec``) are the tables of the page itself: one group above the panels.
    """
    try:
        figures = list(figures)
    except TypeError:
        raise ValueError("Pass the layout panels as a sequence of figures.") from None
    Layout(title, columns, [("panel", index) for index in range(len(figures))], paper, background,
           panel_size, axis_alignment)
    for index, figure in enumerate(figures):
        if figure is not EMPTY_PANEL and not isinstance(figure, Figure):
            raise ValueError(f"Panel {chr(ord('A') + index)} has no figure to export.")
    if settings.get("format", "svg") != "svg":
        raise ValueError("The vector layout export writes SVG only.")
    width_in, height_in = page_size(columns, len(figures), paper)
    plan = plan_export((width_in, height_in), {**settings, "format": "svg"})
    path = Path(path)
    check_destination(path, "svg")
    rc = {"svg.fonttype": "none" if plan["svg_text"] == "text" else "path", "svg.image_inline": True}

    # Every panel is rendered first: a failure leaves the destination untouched.
    placements = plan_panels(columns, figures, paper, panel_size=panel_size, axis_alignment=axis_alignment,
                             arrangement=arrangement)
    panels = []
    for placement in placements:
        if placement.figure is None:
            panels.append(None)
        else:
            with placement.render() as figure:
                panels.append(_render_svg(figure, plan, rc))

    # The page itself (background, title and panel letters) comes from Matplotlib too, so the
    # Text/Paths choice and the fonts are the same as in the panels.
    order = arrangement.paint_order(len(placements))
    labels = layout_labels(placements, order)
    boxes = [placement.box if slot in labels else None for slot, placement in enumerate(placements)]
    frame = layout_frame(title, (width_in, height_in), boxes,
                         background=WHITE if plan["transparent"] else background)
    page, page_children = _children(_render_svg(frame, plan, rc))
    _prefix_ids(page, "layout-")
    table_children = []
    if tables:
        overlay, table_children = _children(_render_svg(overlay_figure((width_in, height_in), tables), plan, rc))
        _prefix_ids(overlay, "tables-")

    ET.register_namespace("", SVG_NS)
    ET.register_namespace("xlink", XLINK_NS)
    for child in list(page):
        if child.tag == SVG + "metadata":
            page.remove(child)
    page.set("width", _size_attr(plan["width_mm"]))
    page.set("height", _size_attr(plan["height_mm"]))
    page.set("viewBox", f"0 0 {width_in * PT:.4f} {height_in * PT:.4f}")
    images = 0
    defs = ET.SubElement(page, SVG + "defs")
    for slot in order:
        index = slot + 1
        document, placement = panels[slot], placements[slot]
        if document is None:
            continue
        w, h = placement.cropped_size
        x, y, scale = placement.box
        panel, children = _children(document)
        _prefix_ids(panel, f"panel{index}-")
        images += len(panel.findall(".//" + SVG + "image"))
        # The panel is clipped to its own figure, like the source SVG viewport.
        clip = ET.SubElement(defs, SVG + "clipPath", id=f"panel{index}-viewport")
        ET.SubElement(clip, SVG + "rect", x="0", y="0", width=f"{w * PT:.4f}", height=f"{h * PT:.4f}")
        left, top, *_ = rotation_bounds(w, h, placement.angle)
        turn = f" translate({-left * PT:.4f} {-top * PT:.4f}) rotate({placement.angle})" if placement.angle else ""
        group = ET.SubElement(page, SVG + "g", {
            "id": f"panel{index}",
            "transform": f"translate({x * PT:.4f} {y * PT:.4f}) scale({scale:.6f}){turn}",
        })
        inner = ET.SubElement(group, SVG + "g", {"clip-path": f"url(#panel{index}-viewport)"})
        if any(placement.crop):
            source_w, source_h = placement.size
            left, top, _, _ = placement.crop_bounds
            clip = ET.SubElement(defs, SVG + "clipPath", id=f"panel{index}-source")
            ET.SubElement(clip, SVG + "rect", x="0", y="0",
                          width=f"{source_w * PT:.4f}", height=f"{source_h * PT:.4f}")
            inner = ET.SubElement(inner, SVG + "g", {
                "transform": f"translate({-left * PT:.4f} {-top * PT:.4f})",
                "clip-path": f"url(#panel{index}-source)",
            })
        inner.extend(children)
        if placement.border:
            width, color, style = placement.border
            w, h = placement.oriented_size
            border = ET.SubElement(page, SVG + "rect", {
                "id": f"panel{index}-border", "fill": "none", "stroke": color, "stroke-width": str(width),
                "x": f"{x * PT:.4f}", "y": f"{y * PT:.4f}",
                "width": f"{w * scale * PT:.4f}", "height": f"{h * scale * PT:.4f}",
            })
            if dashes := BORDER_DASHES[style]:
                border.set("stroke-dasharray", " ".join(f"{length * width:.6g}" for length in dashes))
    if table_children:
        ET.SubElement(page, SVG + "g", {"id": "layout-tables"}).extend(table_children)
    data = ET.tostring(page, encoding="utf-8", xml_declaration=True)

    handle, name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=path.suffix, dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        _verify(temp, plan, images)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return plan
