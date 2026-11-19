"""Restore positioned pages whose graph links resolve to a shared XY worksheet."""

from math import hypot
from struct import error as StructError, unpack_from

from matplotlib.colors import is_color_like
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon

from .prism_binary import _records
from .prism_binary_editable import _one, _require, _subgroups
from .prism_binary_layouts import _placement_references
from .prism_import import _identifier
from .prism_zip_xy import render_sparse_xy


ZIP_LAYOUT = "Prism ZIP layout"
_MAX_BYTES = 2 * 1024 * 1024
_MAX_OBJECTS = 32
_ARROW_ENDS = {1: [1], 2: [0], 3: [0, 1]}


def _positioned_records(data, fen_id):
    records, identifiers, factors = [], [], []
    for tag, path, payload in _records(data):
        if path == (1,) and tag == 0x8035:
            _require(len(payload) == 2)
            identifiers.append(unpack_from("<H", payload)[0])
        elif path == (1,) and tag == 0xA1:
            _require(len(payload) == 104)
            factors.append(unpack_from("<i", payload)[0])
        elif path[:2] == (1, 53):
            records.append((tag, path[2:], payload))
    _require(identifiers == [fen_id] and len(factors) == 1 and 0 < factors[0] <= 2400)
    return records, factors[0]


def _connector(records):
    style = _one(records, 0x23)
    _require(len(style) == 26 and style[7] == 0)
    thickness, = unpack_from("<f", style, 22)
    (path_header, points), = list(_subgroups(records, 0x80D8))
    _require(len(path_header) == 32 and unpack_from("<I", path_header)[0] == 2)
    points = [payload for tag, path, payload in points if tag == 0xD9 and not path]
    _require(len(points) == 2 and 0 < thickness <= 200)
    ends = []
    for point in points:
        _require(len(point) == 20 and unpack_from("<I", point)[0] == 2 and not any(point[12:]))
        ends.append(list(unpack_from("<2i", point, 4)))
    _require(ends[0] != ends[1])
    connector = {"ends": ends, "color": "#" + bytes(style[4:7]).hex(), "thickness": thickness}
    direction, profile, size = unpack_from("<3H", style, 8)
    if direction in _ARROW_ENDS and (profile, size) == (1, 0):
        connector["arrow_ends"] = _ARROW_ENDS[direction].copy()
    return connector


def _linked_objects(records, graphs):
    _require(_placement_references(_one(records, 0x37)) == graphs.keys())
    (header, scene), = list(_subgroups(records, 0x8018))
    _require(len(header) == 12)
    count, groups = unpack_from("<II", header, 4)
    objects = list(_subgroups(scene, 0x8020))
    _require(not groups and 0 < count == len(objects) <= _MAX_OBJECTS)
    panels, connectors, seen = [], [], set()
    for header, details in objects:
        _require(len(header) == 30)
        kind, = unpack_from("<H", header)
        if kind == 11:
            graph, = unpack_from("<H", _one(details, 0x2F))
            title, style = graphs[graph]
            bounds = list(unpack_from("<4h", header, 18))
            panel = {"title": title, "style": style, "bounds": bounds}
            original = [data for tag, path, data in details if tag == 0x30 and not path]
            if style.get("plot") and len(original) == 1 and len(original[0]) == 4:
                if list(unpack_from("<2H", original[0])) == style["plot"]["size"]:
                    panel["axes_box"] = style["plot"]["axes_box"]
            panels.append(panel)
            seen.add(graph)
        elif kind == 3:
            connectors.append(_connector(details))
        else:
            raise ValueError("Unrecognized object on the saved layout.")
    _require(seen == graphs.keys())
    return panels, connectors


def saved_positioned_layout(archive, uid, sheet, restored_graphs):
    """Return the worksheet and geometry when every layout link is understood."""
    if not isinstance(sheet.get("linkedGraphSheets"), list):
        return None
    try:
        linked = [_identifier(graph) for graph in sheet["linkedGraphSheets"]]
        _require(sheet.get("uid") == uid and type(sheet.get("fenID")) is int
                 and not sheet.get("mediaCollection") and 0 < len(linked) <= 16 and len(set(linked)) == len(linked))
        graph_data = [restored_graphs[link] for link in linked]
        frame = graph_data[0][0]
        _require(all(item[0] is frame for item in graph_data))
        graphs = {graph_id: (title, style) for _, graph_id, title, style in graph_data}
        _require(len(graphs) == len(linked))
        member = archive.getinfo(f"layouts/{uid}/data.bin")
        _require(0 < member.file_size <= _MAX_BYTES)
        records, units = _positioned_records(archive.read(member), sheet["fenID"])
        page = _one(records, 0xA)
        _require(len(page) == 300)
        paper = [value / 100 for value in unpack_from("<2i", page)]
        panels, connectors = _linked_objects(records, graphs)
        layout = {"paper": paper, "units_per_inch": units, "panels": panels, "connectors": connectors}
        _page_size(layout)
        return frame, layout
    except (KeyError, TypeError, ValueError, IndexError, StructError):
        return None


def _page_size(layout):
    width, height = layout["paper"]
    units = layout["units_per_inch"]
    _require(1 <= width <= 36 and 1 <= height <= 36 and 0 < units <= 2400)
    _require(0 < len(layout["panels"]) <= _MAX_OBJECTS and len(layout["connectors"]) <= _MAX_OBJECTS)
    w, h = width * units, height * units
    for panel in layout["panels"]:
        left, top, right, bottom = panel["bounds"]
        _require(0 <= left < right <= w and 0 <= top < bottom <= h)
        if "axes_box" in panel:
            x, y, width, height = panel["axes_box"]
            _require(0 <= x < x + width <= 1 and 0 <= y < y + height <= 1)
    for connector in layout["connectors"]:
        start, end = connector["ends"]
        arrow_ends = connector.get("arrow_ends", [])
        _require(start != end and all(0 <= x <= w and 0 <= y <= h for x, y in (start, end))
                 and 0 < connector["thickness"] <= 200 and is_color_like(connector["color"])
                 and arrow_ends in ([], [0], [1], [0, 1]) and all(type(end) is int for end in arrow_ends))
    return w, h


def _draw_connector(figure, connector, width, height, units):
    color = connector["color"]
    x = tuple(point[0] / width for point in connector["ends"])
    y = tuple(1 - point[1] / height for point in connector["ends"])
    line = Line2D(x, y, transform=figure.transFigure, color=color,
                  linewidth=72 * connector["thickness"] / units)
    figure.add_artist(line)
    for end in connector.get("arrow_ends", []):
        tip_x, tip_y = connector["ends"][end]
        other_x, other_y = connector["ends"][1 - end]
        dx, dy = other_x - tip_x, other_y - tip_y
        length = hypot(dx, dy)
        # The default filled cap measures 90 by 72 file units at 600 units/inch
        # in the reference drawings, independently of the stroke width.
        head = min(units * .15, length / 2) / length
        base_x, base_y = tip_x + dx * head, tip_y + dy * head
        side_x, side_y = -.4 * dy * head, .4 * dx * head
        vertices = ((tip_x / width, 1 - tip_y / height),
                    ((base_x + side_x) / width, 1 - (base_y + side_y) / height),
                    ((base_x - side_x) / width, 1 - (base_y - side_y) / height))
        figure.add_artist(Polygon(vertices, transform=figure.transFigure, facecolor=color, edgecolor="none"))


def render_positioned_layout(frame, layout):
    """Redraw the worksheet-linked panels in their saved page rectangles."""
    try:
        width, height = _page_size(layout)
        figure = Figure(figsize=layout["paper"])
        for panel in layout["panels"]:
            left, top, right, bottom = panel["bounds"]
            grid = GridSpec(3, 3, figure=figure, left=0, right=1, bottom=0, top=1, wspace=0, hspace=0,
                            width_ratios=(left, right - left, width - right),
                            height_ratios=(top, bottom - top, height - bottom))
            page = figure.add_subfigure(grid[1, 1])
            axes = page.add_axes(panel.get("axes_box", (.09, .18, .86, .67)))
            render_sparse_xy(frame, panel["style"], panel["title"], axes=axes)
            axes.title.set_fontsize(10)
            axes.tick_params(labelsize=8)
            if legend := axes.get_legend():
                handles, captions = axes.get_legend_handles_labels()
                legend.remove()
                legend = axes.legend(handles, captions, ncols=(len(handles) + 3) // 4, fontsize=7)
                for label in legend.get_texts():
                    label.set_parse_math(False)
        for connector in layout["connectors"]:
            _draw_connector(figure, connector, width, height, layout["units_per_inch"])
        return figure
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise ValueError("Invalid page geometry or source data for the saved layout.") from error
