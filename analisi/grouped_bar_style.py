"""Sparse appearance overrides anchored to a worksheet row and a grouped series."""

from dataclasses import dataclass
from math import isfinite
import re

from .worksheet_column_identity import valid_token as column_token
from .worksheet_row_identity import valid_token as row_token


BAR_STYLES = "grouped_bar_styles"
PATTERNS = {"none": None, "diagonal": "/", "cross": "xx", "dots": ".."}
MAX_OVERRIDES = 1200
MAX_COLUMNS = 256
FIELDS = {"fill", "border", "width", "pattern"}
_HEX = re.compile(r"#[a-fA-F0-9]{6}")
_INVALID = "Invalid individual bar formatting."


@dataclass(frozen=True)
class Bar:
    row_token: str
    columns: tuple
    row: int
    category: str
    series: str
    patch: object

    @property
    def key(self):
        return self.row_token, self.columns

    def record(self, style):
        return {"row_token": self.row_token, "columns": list(self.columns), "style": style}


def valid_appearance(style):
    if not isinstance(style, dict) or not style or style.keys() - FIELDS:
        return False
    for field in ("fill", "border"):
        if field in style:
            color = style[field]
            if not isinstance(color, str) or (color != "none" and _HEX.fullmatch(color) is None):
                return False
    if "width" in style:
        value = style["width"]
        if type(value) not in (int, float) or not 0 <= value <= 72 or not isfinite(value):
            return False
    return "pattern" not in style or (isinstance(style["pattern"], str) and style["pattern"] in PATTERNS)


def style_key(record):
    return record["row_token"], tuple(record["columns"])


def validate_bar_styles(records):
    if not isinstance(records, list) or len(records) > MAX_OVERRIDES:
        raise ValueError(_INVALID)
    seen = set()
    for record in records:
        if not isinstance(record, dict) or record.keys() != {"row_token", "columns", "style"}:
            raise ValueError(_INVALID)
        columns = record["columns"]
        if (not row_token(record["row_token"]) or not isinstance(columns, list)
                or not 1 <= len(columns) <= MAX_COLUMNS or not all(column_token(token) for token in columns)
                or columns != sorted(set(columns)) or not valid_appearance(record["style"])):
            raise ValueError(_INVALID)
        key = style_key(record)
        if key in seen:
            raise ValueError(_INVALID)
        seen.add(key)


def grouped_bars(figure):
    return getattr(figure, "_tramastat_individual_bars", ())


def register_bars(figure, patches, rows, columns, categories, series):
    """Associate already-drawn rectangles with their original worksheet coordinates."""
    if not columns or not 1 <= len(columns) <= MAX_COLUMNS or not all(column_token(token) for token in columns):
        return
    entries = [Bar(token, columns, int(position), category, series, patch)
               for patch, (position, token), category in zip(patches, rows, categories, strict=True)
               if token is not None]
    if entries:
        figure._tramastat_individual_bars = (*grouped_bars(figure), *entries)


def restore_bar_styles(figure):
    for patch, fill, border, width, pattern in getattr(figure, "_tramastat_individual_bar_defaults", ()):
        patch.set(facecolor=fill, edgecolor=border, linewidth=width, hatch=pattern)
    figure._tramastat_individual_bar_defaults = ()


def apply_bar_styles(figure, records):
    restore_bar_styles(figure)
    if not records:
        return
    lookup = {bar.key: bar.patch for bar in grouped_bars(figure)}
    original = []
    for record in records:
        patch = lookup.get(style_key(record))
        if patch is None:
            continue
        original.append((patch, patch.get_facecolor(), patch.get_edgecolor(), patch.get_linewidth(), patch.get_hatch()))
        appearance = record["style"]
        for field, setter in (("fill", patch.set_facecolor), ("border", patch.set_edgecolor),
                              ("width", patch.set_linewidth)):
            if field in appearance:
                setter(appearance[field])
        if "pattern" in appearance:
            patch.set_hatch(PATTERNS[appearance["pattern"]])
    figure._tramastat_individual_bar_defaults = original


def unavailable_bar_styles(figure, records):
    if not records:
        return 0
    keys = {bar.key for bar in grouped_bars(figure)}
    return sum(style_key(record) not in keys for record in records)


def bars_at(event):
    """Find visible rectangles at the pointer, highest painted first, including the right axis."""
    if event.x is None or event.y is None:
        return ()
    point = event.x, event.y
    figure = event.canvas.figure
    axis_order = {axes: index for index, axes in enumerate(figure.axes)}
    found = [bar for bar in grouped_bars(figure)
             if bar.patch.get_visible() and bar.patch.axes.bbox.contains(*point)
             and bar.patch.get_height() and bar.patch.get_width()
             and bar.patch.contains_point(point)]
    return tuple(sorted(reversed(found),
                        key=lambda bar: (bar.patch.axes.get_zorder(), axis_order[bar.patch.axes], bar.patch.get_zorder()),
                        reverse=True))
