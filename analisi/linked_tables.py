"""Tables linked to a worksheet or to an analysis result, drawn on a graph or on a layout page.

A table object is one record in the style of a graph (key ``linked_tables``) or in a layout (``tables``). It
holds how the table looks (position, headers, orientation, font, grid) and where its numbers come from:

* **Linked** (``mode`` ``linked``): ``source`` names a worksheet range by the title of the sheet, the identity of
  each row (the worksheet row identities that survive inserted and deleted rows) and the names of the columns, or a
  result range by the identity of the analysis (its recipe, not its number in the list), the key of the result
  table and the row and column keys. The values are read when the figure is drawn; nothing is stored but the
  reference. Tables that cannot be read are drawn as an explicit state (missing, ambiguous, empty, changed, error or
  not calculated yet): a linked table never moves to another sheet, result or range, and never runs an analysis.
* **Copy** (``mode`` ``copy``): the text of the cells at the moment of insertion is the table (``values``). The
  source is only a label (``origin``).

Data (the record), cache (the values read from the project for one drawing, ``Resolved``) and error state
(``Resolved.state``) are three different things: the record is saved, the other two are never stored.

The drawing is vector: one container artist holds the text, fill and line artists, so PDF and SVG keep the text
as text and the rules as paths. Sizes are in points and the position is the top left corner as a fraction of
the page, which keeps the table the same size when a layout reflows the panel; a table that would stick out of the
page is moved back onto it, never cut. The engine does not import Tk or Qt.
"""
from dataclasses import dataclass, field
from math import isfinite
import json
import re
import uuid

from matplotlib.artist import Artist
from matplotlib.figure import Figure
from matplotlib.font_manager import FontProperties
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from matplotlib.text import Text
from matplotlib.textpath import TextToPath
from matplotlib.transforms import Affine2D, ScaledTranslation

from .i18n import tr
from .worksheet_row_identity import current_spans, valid_token

TABLES = "linked_tables"
MODES = ("linked", "copy")
SOURCE_KINDS = ("sheet", "result")
HEADERS = ("both", "row", "column", "none")
ORIENTATIONS = ("normal", "transposed")
ROW_BY = ("keys", "position")
FONT_FAMILIES = ("sans-serif", "serif", "monospace")
STATES = ("ok", "missing", "ambiguous", "empty", "changed", "error", "pending")
MAX_TABLES = 12
MAX_ROWS, MAX_COLUMNS, MAX_CELLS = 60, 16, 600
MAX_TEXT = 160
MAX_SHOWN = 40
SIZE_RANGE = (5.0, 24.0)
DEFAULT_SIZE = 9.0
GID = "tramastat-table-"

TABLE_KEYS = {"id", "mode", "position", "size", "headers", "orientation", "grid"}
OPTIONAL_KEYS = {"source", "values", "origin", "font"}
SOURCE_KEYS = {"kind", "sheet", "analysis", "table", "rows", "columns", "by", "rows_total", "retired"}

SIZE_MESSAGE = ("Choose up to {rows} rows and {columns} columns ({cells} cells in all); "
                "the range has {have_rows} × {have_columns}.")

INK, MUTED, RULE, WHITE = "#1b2733", "#5c6b7a", "#6b7785", "#ffffff"
HEADER_FILL, PROBLEM_INK, PROBLEM_FILL = "#eef2f7", "#8c2a22", "#fdf3f1"
PADDING, ROW_HEIGHT = .5, 1.6
_NUMBER = re.compile(r"[-−+]?(?:\d+[.,]?\d*|[.,]\d+)(?:[eE][-−+]?\d+)?%?")


# -- records -----------------------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def _number(value):
    return type(value) in (int, float) and isfinite(value)


def _canonical_uuid(value):
    if not isinstance(value, str):
        return False
    try:
        return str(uuid.UUID(value)) == value
    except (ValueError, AttributeError, TypeError):
        return False


def _text(value, *, limit=MAX_TEXT):
    return isinstance(value, str) and 0 < len(value) <= limit and value == value.strip()


def check_size(rows, columns):
    """Refuse a range that is empty or too large *before* any cell is read or any artist is created."""
    if type(rows) is not int or type(columns) is not int or rows < 1 or columns < 1:
        raise ValueError("The range of a linked table is empty.")
    if rows > MAX_ROWS or columns > MAX_COLUMNS or rows * columns > MAX_CELLS:
        raise ValueError(SIZE_MESSAGE.format(rows=MAX_ROWS, columns=MAX_COLUMNS, cells=MAX_CELLS,
                                             have_rows=rows, have_columns=columns))


def _keys(values, kind, *, integers=False):
    if not isinstance(values, list):
        raise ValueError("Invalid linked table source.")
    if integers:
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("Invalid linked table source.")
    elif kind == "token":
        if any(not valid_token(value) for value in values):
            raise ValueError("Invalid linked table source.")
    elif any(not isinstance(value, str) or not value or len(value) > MAX_TEXT for value in values):
        raise ValueError("Invalid linked table source.")
    if len(set(values)) != len(values):
        raise ValueError("A linked table source repeats a row or a column.")
    return list(values)


def validate_source(source):
    """A canonical copy of one source reference; the size of the range is checked first."""
    if not isinstance(source, dict) or source.keys() - SOURCE_KEYS or source.get("kind") not in SOURCE_KINDS:
        raise ValueError("Invalid linked table source.")
    rows, columns = source.get("rows"), source.get("columns")
    if not isinstance(rows, list) or not isinstance(columns, list):
        raise ValueError("Invalid linked table source.")
    check_size(len(rows), len(columns))
    kind = source["kind"]
    clean = {"kind": kind}
    if kind == "sheet":
        if (source.keys() - {"kind", "sheet", "rows", "columns", "retired"}
                or not _text(source.get("sheet")) or ("retired" in source and source["retired"] is not True)):
            raise ValueError("Invalid linked table source.")
        clean["sheet"] = source["sheet"]
        clean["rows"] = _keys(rows, "token")
        if source.get("retired"):
            clean["retired"] = True
    else:
        if (source.keys() - {"kind", "analysis", "table", "rows", "columns", "by", "rows_total"}
                or not _text(source.get("analysis"), limit=64) or not _text(source.get("table"))
                or source.get("by", "keys") not in ROW_BY):
            raise ValueError("Invalid linked table source.")
        by = source.get("by", "keys")
        clean["analysis"], clean["table"], clean["by"] = source["analysis"], source["table"], by
        clean["rows"] = _keys(rows, "label", integers=by == "position")
        if by == "position":
            total = source.get("rows_total")
            if type(total) is not int or total < 1 or total > 10 ** 9:
                raise ValueError("Invalid linked table source.")
            clean["rows_total"] = total
        elif "rows_total" in source:
            raise ValueError("Invalid linked table source.")
    clean["columns"] = _keys(columns, "label")
    return clean


def validate_values(values):
    """The frozen cells of a copy: labels and the text of every cell."""
    if not isinstance(values, dict) or values.keys() - {"rows", "columns", "cells"}:
        raise ValueError("Invalid linked table values.")
    rows, columns, cells = values.get("rows"), values.get("columns"), values.get("cells")
    if not all(isinstance(item, list) for item in (rows, columns, cells)):
        raise ValueError("Invalid linked table values.")
    check_size(len(rows), len(columns))
    if len(cells) != len(rows) or any(not isinstance(line, list) or len(line) != len(columns) for line in cells):
        raise ValueError("Invalid linked table values.")
    for text in (*rows, *columns, *(cell for line in cells for cell in line)):
        if not isinstance(text, str) or len(text) > MAX_TEXT:
            raise ValueError("Invalid linked table values.")
    return {"rows": list(rows), "columns": list(columns), "cells": [list(line) for line in cells]}


def validate_table(record):
    """One table record as a canonical, independent copy; the range is measured before anything is read."""
    if (not isinstance(record, dict) or not TABLE_KEYS.issubset(record)
            or record.keys() - TABLE_KEYS - OPTIONAL_KEYS):
        raise ValueError("Invalid linked table record.")
    if not _canonical_uuid(record["id"]):
        raise ValueError("Each linked table requires a canonical lowercase UUID.")
    mode = record["mode"]
    if mode not in MODES:
        raise ValueError("Choose linked or copy for the table mode.")
    position = record["position"]
    if (not isinstance(position, (list, tuple)) or len(position) != 2 or not all(map(_number, position))
            or not all(0 <= value <= 1 for value in position)):
        raise ValueError("Enter table positions between 0 and 1.")
    size = record["size"]
    if not _number(size) or not SIZE_RANGE[0] <= size <= SIZE_RANGE[1]:
        raise ValueError("Enter a table font size between 5 and 24 points.")
    if record["headers"] not in HEADERS or record["orientation"] not in ORIENTATIONS:
        raise ValueError("Choose the table headers and orientation from the list.")
    if type(record["grid"]) is not bool:
        raise ValueError("Invalid table grid setting.")
    if "font" in record and record["font"] not in FONT_FAMILIES:
        raise ValueError("Choose a valid table font family.")
    if "origin" in record and not _text(record["origin"], limit=200):
        raise ValueError("Invalid linked table origin.")
    clean = {"id": record["id"], "mode": mode, "position": [float(position[0]), float(position[1])],
             "size": float(size), "headers": record["headers"], "orientation": record["orientation"],
             "grid": record["grid"]}
    if mode == "linked":
        if "source" not in record or "values" in record:
            raise ValueError("A linked table needs a source and no stored values.")
        clean["source"] = validate_source(record["source"])
    else:
        if "values" not in record or "source" in record:
            raise ValueError("A table copy needs stored values and no source.")
        clean["values"] = validate_values(record["values"])
    for key in ("origin", "font"):
        if key in record:
            clean[key] = record[key]
    return clean


def validate_tables(records, *, limit=MAX_TABLES):
    if not isinstance(records, (list, tuple)):
        raise ValueError("Invalid linked tables.")
    if len(records) > limit:
        raise ValueError(f"Add up to {limit} linked tables per graph or layout.")
    clean, seen = [], set()
    for record in records:
        item = validate_table(record)
        if item["id"] in seen:
            raise ValueError("Duplicate linked table ID.")
        seen.add(item["id"])
        clean.append(item)
    return clean


def source_analyses(records):
    """The identities of the analyses whose results these linked tables read."""
    return {record["source"]["analysis"] for record in records
            if record.get("mode") == "linked" and record.get("source", {}).get("kind") == "result"}


def remap_sources(records, analyses=None, sheets=None):
    """``records`` with the analyses and sheets they read named by ``analyses`` and ``sheets`` (old → new).

    A family copy uses it so that a table copied with its graph reads the copies of the sheets and analyses
    that were copied with it. A source that is not in the maps is left exactly as it was: it keeps reading
    the original, or shows a missing source where the original does not exist. The same list when nothing moves."""
    analyses, sheets = analyses or {}, sheets or {}
    moved = []
    for record in records:
        source = record.get("source")
        if source is not None:
            if source["kind"] == "result" and source["analysis"] in analyses:
                source = {**source, "analysis": analyses[source["analysis"]]}
            elif source["kind"] == "sheet" and not source.get("retired") and source["sheet"] in sheets:
                new_sheet = sheets[source["sheet"]]
                source = {**source, "retired": True} if new_sheet is None else {**source, "sheet": new_sheet}
            if source is not record["source"]:
                record = {**record, "source": source}
        moved.append(record)
    return records if all(new is old for new, old in zip(moved, records, strict=True)) else moved


def rename_sheet(records, old, new):
    """Rename worksheet sources, or retire them when their worksheet is deleted."""
    return remap_sources(records, sheets={old: new})


# -- reading the project ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class FrameSource:
    """What the project hands over for one source: the values, how a cell reads, and the row identities."""

    frame: object
    text: object                 # (row position, column position) -> the text the grid shows
    spans: tuple | None = None   # worksheet row identities (sheets)
    row_label: object = None     # row position -> label (results)
    labelled: bool = False       # results: the rows have labels, not just numbers


@dataclass(frozen=True)
class Problem:
    state: str
    detail: str = ""


@dataclass(frozen=True)
class Resolved:
    """The values of one table for one drawing, or why they are not available."""

    state: str = "ok"
    detail: str = ""
    row_labels: tuple = ()
    column_labels: tuple = ()
    cells: tuple = ()

    @property
    def ok(self):
        return self.state == "ok"


def _token_rows(spans, tokens):
    """Current row of every token (a ``base:7`` style row identity), or None for a row that no longer exists."""
    wanted = {}
    for token in tokens:
        origin, _, number = token.rpartition(":")
        wanted.setdefault(origin, []).append((int(number), token))
    rows, offset = {}, 0
    for origin, first, count in spans or ():
        for number, token in wanted.get(origin, ()):
            if first <= number < first + count:
                rows[token] = offset + number - first
        offset += count
    return [rows.get(token) for token in tokens]


def row_tokens(frame, positions):
    """The row identities of the worksheet rows ``positions``."""
    spans, offset, result = current_spans(frame) or (), 0, {}
    wanted = set(positions)
    for origin, first, count in spans:
        for position in wanted:
            if offset <= position < offset + count:
                result[position] = f"{origin}:{first + position - offset}"
        offset += count
    return [result[position] for position in positions]


def _column_positions(frame, names):
    labels = [str(name) for name in frame.columns]
    found = []
    for name in names:
        hits = [index for index, label in enumerate(labels) if label == name]
        if not hits:
            return None, Problem("missing", tr("linked_table.detail.column", name=name))
        if len(hits) > 1:
            return None, Problem("ambiguous", tr("linked_table.detail.column_repeated", name=name))
        found.append(hits[0])
    return found, None


def _frozen(record):
    values = record["values"]
    return Resolved("ok", "", tuple(values["rows"]), tuple(values["columns"]),
                    tuple(tuple(line) for line in values["cells"]))


def resolve(record, lookup):
    """The values of ``record`` read through ``lookup`` (``sheet(title)`` and ``result(analysis, table)``).

    A copy needs no lookup. A linked table whose source cannot be read exactly as it was referenced is not
    resolved: a missing or repeated key never falls back to another row, column, sheet or result.
    """
    if record["mode"] == "copy":
        return _frozen(record)
    source = record["source"]
    if source.get("retired"):
        return Resolved("missing", tr("linked_table.detail.sheet", name=source["sheet"]))
    found = (lookup.sheet(source["sheet"]) if source["kind"] == "sheet"
             else lookup.result(source["analysis"], source["table"]))
    if isinstance(found, Problem):
        return Resolved(found.state, found.detail)
    frame = found.frame
    if not len(frame) or not len(frame.columns):
        return Resolved("empty", tr("linked_table.detail.empty"))
    columns, problem = _column_positions(frame, source["columns"])
    if problem:
        return Resolved(problem.state, problem.detail)
    if source["kind"] == "sheet":
        rows = _token_rows(found.spans, source["rows"])
        if None in rows:
            return Resolved("missing", tr("linked_table.detail.row_removed"))
        labels = tuple(str(row + 1) for row in rows)
    elif source.get("by") == "position":
        if len(frame) != source["rows_total"]:
            return Resolved("changed", tr("linked_table.detail.rows_changed", before=source["rows_total"],
                                          now=len(frame)))
        rows = list(source["rows"])
        if any(row >= len(frame) for row in rows):
            return Resolved("changed", tr("linked_table.detail.rows_changed", before=source["rows_total"],
                                          now=len(frame)))
        labels = tuple(str(row + 1) for row in rows)
    else:
        names = [found.row_label(position) for position in range(len(frame))]
        rows, labels = [], []
        for key in source["rows"]:
            hits = [position for position, name in enumerate(names) if name == key]
            if not hits:
                return Resolved("missing", tr("linked_table.detail.row", name=key))
            if len(hits) > 1:
                return Resolved("ambiguous", tr("linked_table.detail.row_repeated", name=key))
            rows.append(hits[0])
            labels.append(key)
        labels = tuple(labels)
    cells = tuple(tuple(found.text(row, column) for column in columns) for row in rows)
    return Resolved("ok", "", labels, tuple(source["columns"]), cells)


# -- drawing -------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TableSpec:
    """A record and the values it shows now."""

    record: dict
    resolved: Resolved = field(default_factory=Resolved)

    @property
    def signature(self):
        return json.dumps([self.record, [self.resolved.state, self.resolved.detail, self.resolved.row_labels,
                                         self.resolved.column_labels, self.resolved.cells]],
                          sort_keys=True, ensure_ascii=False)


_PATHS = TextToPath()


def _width(text, font):
    return _PATHS.get_text_width_height_descent(text, font, False)[0] if text else 0.


def _shown(text):
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_SHOWN else text[:MAX_SHOWN - 1] + "…"


def _is_number(text):
    return _NUMBER.fullmatch(text.strip()) is not None


def _lines(spec):
    """The text grid to draw: ``(kind, text)`` rows for a table, or the lines of an explicit state."""
    record, resolved = spec.record, spec.resolved
    if not resolved.ok:
        origin = record.get("origin") or tr("linked_table.unknown_source")
        return None, [tr(f"linked_table.state.{resolved.state}"), _shown(origin), *wrapped(resolved.detail)]
    rows, columns, cells = resolved.row_labels, resolved.column_labels, resolved.cells
    if record["orientation"] == "transposed":
        rows, columns = columns, rows
        cells = tuple(zip(*cells, strict=True))
    headers = record["headers"]
    grid = []
    if headers in ("column", "both"):
        grid.append([("corner", "")] * (headers == "both") + [("column", _shown(label)) for label in columns])
    for label, line in zip(rows, cells, strict=True):
        grid.append([("row", _shown(label))] * (headers in ("row", "both"))
                    + [("number" if _is_number(text) else "text", _shown(text)) for text in line])
    return grid, None


def wrapped(text, width=58):
    words, lines, line = str(text).split(), [], ""
    for word in words:
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return [*lines, line] if line else lines


def _font(record, scale, weight="normal"):
    return FontProperties(family=record.get("font", "sans-serif"), size=record["size"] * scale, weight=weight)


class LinkedTableArtist(Artist):
    """One table: every text, fill and rule it is made of is drawn in the table's own point coordinates."""

    def __init__(self, figure, spec, scale=1.):
        super().__init__()
        self.set_figure(figure)
        self.set_zorder(40)
        self.set_gid(GID + spec.record["id"])
        self.spec = spec
        self.scale = scale
        self.extent, self._children = (0., 0.), ()
        self._build(figure)

    # Table coordinates: points, the origin at the top left corner, y growing downward, then the page.
    def _local(self, figure):
        """Where the table sits: its top left corner at the recorded position, moved back onto the page when it
        would stick out (a table is never cut by the edge of the figure or of the layout page)."""
        x, y = self.spec.record["position"]
        width, height = (float(value) for value in figure.get_size_inches())
        table_width, table_height = self.extent[0] / 72, self.extent[1] / 72
        left = min(x * width, max(width - table_width, 0.))
        top = min(y * height, max(height - table_height, 0.))
        return (Affine2D().scale(1 / 72, -1 / 72) + figure.dpi_scale_trans
                + ScaledTranslation(left, height - top, figure.dpi_scale_trans))

    def _place(self, figure):
        transform = self._local(figure)
        for child in self._children:
            child.set_transform(transform)

    def _build(self, figure):
        record = self.spec.record
        scale = self.scale
        size, pad = record["size"] * scale, PADDING * record["size"] * scale
        height = ROW_HEIGHT * size
        grid, problem = _lines(self.spec)
        children = []

        def add(artist):
            artist.set_figure(figure)
            artist.set_clip_on(False)
            children.append(artist)

        def text(x, y, string, font, color, align):
            add(Text(x, y, string, fontproperties=font, color=color, ha=align, va="center_baseline",
                     parse_math=False))

        def rule(xs, ys, color, width):
            add(Line2D(xs, ys, color=color, linewidth=width * scale, solid_capstyle="butt"))

        if problem is not None:
            fonts = [_font(record, scale, "bold"), *[_font(record, scale)] * (len(problem) - 1)]
            width = max(_width(line, font) for line, font in zip(problem, fonts, strict=True)) + 2 * pad
            total = height * len(problem) + pad
            add(Rectangle((0, 0), width, total, facecolor=PROBLEM_FILL, edgecolor=PROBLEM_INK,
                          linewidth=.8 * scale))
            for index, (line, font) in enumerate(zip(problem, fonts, strict=True)):
                text(pad, pad / 2 + height * (index + .5), line, font, PROBLEM_INK if index == 0 else MUTED, "left")
            self.extent, self._children = (width, total), tuple(children)
            self._place(figure)
            return
        body, bold = _font(record, scale), _font(record, scale, "bold")
        widths = [max(_width(line[column][1], bold if line[column][0] in ("column", "row") else body)
                      for line in grid) + 2 * pad for column in range(len(grid[0]))]
        total_width, total_height = sum(widths), height * len(grid)
        add(Rectangle((0, 0), total_width, total_height, facecolor=WHITE, edgecolor="none"))
        column_header = grid[0][0][0] in ("corner", "column")
        row_header = any(line[0][0] in ("row", "corner") for line in grid)
        if column_header:
            add(Rectangle((0, 0), total_width, height, facecolor=HEADER_FILL, edgecolor="none"))
        if row_header:
            add(Rectangle((0, 0), widths[0], total_height, facecolor=HEADER_FILL, edgecolor="none"))
        # A column of numbers is right aligned, its heading with it; everything else starts at the left.
        right_aligned = [all(line[column][0] == "number" for line in grid if line[column][0] in ("number", "text"))
                         and any(line[column][0] == "number" for line in grid) for column in range(len(widths))]
        edges = [0.]
        for width in widths:
            edges.append(edges[-1] + width)
        for row, line in enumerate(grid):
            for column, (kind, string) in enumerate(line):
                if not string:
                    continue
                right = right_aligned[column] and kind in ("number", "column")
                x = edges[column + 1] - pad if right else edges[column] + pad
                text(x, height * (row + .5), string, bold if kind in ("column", "row") else body, INK,
                     "right" if right else "left")
        if record["grid"]:
            for row in range(len(grid) + 1):
                rule([0, total_width], [height * row] * 2, RULE, .6)
            for edge in edges:
                rule([edge] * 2, [0, total_height], RULE, .6)
        self.extent, self._children = (total_width, total_height), tuple(children)
        self._place(figure)

    @property
    def size_points(self):
        return self.extent

    def draw(self, renderer):
        if not self.get_visible():
            return
        renderer.open_group("linked_table", self.get_gid())
        for child in self._children:
            child.draw(renderer)
        renderer.close_group("linked_table")
        self.stale = False


def table_size(spec, scale=1.):
    """The width and height of a table in inches, as drawn."""
    figure = Figure(figsize=(1, 1))
    return tuple(value / 72 for value in LinkedTableArtist(figure, spec, scale).extent)


def remove_tables(figure):
    """Take every table off ``figure``; returns how many there were."""
    found = [artist for artist in figure.artists if isinstance(artist, LinkedTableArtist)]
    for artist in found:
        artist.remove()
    return len(found)


def draw_tables(figure, specs, *, scale=1.):
    """Add one container artist per table spec to ``figure``; tables never change the axes or their limits."""
    artists = []
    for spec in specs:
        artist = LinkedTableArtist(figure, spec, scale)
        figure.add_artist(artist, clip=False)
        artists.append(artist)
    return artists


def sync_tables(figure, specs, *, scale=1.):
    """Make the tables on ``figure`` exactly ``specs``. Returns True when the figure had to change.

    Nothing is drawn again when the records and the values are the same as the last drawing.
    """
    page = [round(float(value), 4) for value in figure.get_size_inches()]
    signature = json.dumps([spec.signature for spec in specs] + [scale, page]) if specs else ""
    present = any(isinstance(artist, LinkedTableArtist) for artist in figure.artists)
    if signature == getattr(figure, "_tramastat_tables_signature", "") and present == bool(specs):
        return False
    remove_tables(figure)
    draw_tables(figure, specs, scale=scale)
    figure._tramastat_tables_signature = signature
    return True


def overlay_figure(size, specs, *, scale=1.):
    """A transparent page the size of a layout holding only its tables, drawn above the panels."""
    figure = Figure(figsize=size, facecolor="none")
    figure.patch.set_alpha(0)
    draw_tables(figure, specs, scale=scale)
    return figure


__all__ = ["FrameSource", "LinkedTableArtist", "Problem", "Resolved", "TABLES", "TableSpec", "check_size",
           "draw_tables", "new_id", "overlay_figure", "remap_sources", "remove_tables", "rename_sheet", "resolve", "row_tokens",
           "source_analyses", "sync_tables", "table_size", "validate_table", "validate_tables"]
