"""Formatting of single observations in XY series and scatter plots.

A style for one point never changes the series, the data or the result of the analysis. It lives in the
shared presentation style under ``"points"`` as a list of records::

    {"series": "scatter:1:C",
     "source": {"row": 2, "rows": 5, "x": 1.0, "y": 2.0, "copy": 2, "copies": 2, "recipe": ["X", "Y", "Group"]},
     "color": "#ac4320", "marker": "s", "marker_size": 9}

``color``, ``marker`` and ``marker_size`` are optional: a missing one is inherited from the series.

Identity. The builders of the graph record, for every artist, which worksheet row each point comes from
(``attach_points``): rows are 1-based positions in the worksheet, before missing cells and exclusions remove
points. A record stores that row, the length of the worksheet, the coordinates, the position among the points
of the series that share exactly those coordinates (``copy`` of ``copies``) and the columns the graph reads.
A project worksheet also supplies a stable row token, which changes when that row is replaced.
When there is no token, ``resolve`` uses the recorded row and coordinates:

- the graph reads other columns than when the point was styled: the style is suspended;
- the worksheet keeps its length: the row position is trusted. A row that is excluded or has a missing value
  is simply not drawn (the style waits for it); a row whose values were edited keeps its style, unless the old
  values sit elsewhere in the series, which is a reordering and is followed only when the values are unique;
- rows were inserted or deleted: positions cannot be trusted, so the values decide. They must be found as
  many times as when the point was styled, and then the same ``copy`` is taken; fewer or more copies (a
  duplicate row was added or removed) make the association uncertain and the style is suspended.

A suspended or waiting style is never applied to another row. Resetting a point is always possible because the
records stay in the style whatever their state.

Drawing. The series keeps its artist, its data, its limits, its legend entry and its stroke. The styled points
are taken out of the series artist (a scatter collection puts NaN in the offsets of those vertices, an XY line
hides their markers with ``markevery``) and drawn again by one extra marker line per distinct look
(``trama-point-style:``), which sits in the axes but out of the series list, the limits and the legend. The
series therefore keeps its fast uniform drawing: a graph of ten thousand points redraws as quickly as before.
``restore_point_styles`` returns every artist to the series look before a style is applied again.
"""
from contextlib import contextmanager
from dataclasses import dataclass, field
from math import isfinite
import re

import numpy as np
from matplotlib import rcParams
from matplotlib.collections import PathCollection
from matplotlib.colors import is_color_like, to_hex, to_rgba
from matplotlib.legend import Legend
from matplotlib.legend_handler import HandlerLine2D
from matplotlib.lines import Line2D
from matplotlib.markers import MarkerStyle
import matplotlib.patheffects as path_effects

from .worksheet_row_identity import row_of, token_at, valid_token

POINTS = "points"
MAX_POINT_STYLES = 256
POINT_FIELDS = ("color", "marker", "marker_size")
SOURCE_KEYS = {"row", "rows", "x", "y", "copy", "copies", "recipe"}
RECORD_KEYS = {"series", "source", *POINT_FIELDS}
# The symbols of ``analisi.presentation.MARKERS`` that draw something.
MARKER_CODES = ("o", "s", "D", "^", "v", "+", "x", "*")
SERIES_KEY = re.compile(r"(scatter|xy):[1-9][0-9]*:.*", re.DOTALL)
GID_PREFIX = "trama-point-style:"
INDICATOR_GID = "trama-point-indicator"
INDICATOR_COLOR = "#e2411c"
MAX_SHEET_ROWS = 10 ** 9

POINT_MAP_ATTR = "_tramastat_points"
BASE_ATTR = "_tramastat_point_base"
STATE_ATTR = "_tramastat_point_state"
STATUS_ATTR = "_tramastat_point_status"
INDICATOR_ATTR = "_tramastat_point_indicator"

# A point style that is not drawn is either ``hidden`` (its row is excluded or has no value: the style waits for
# it) or ``suspended`` (the association is uncertain or the series cannot show it: the user decides). The reasons
# are ``not_drawn``, ``no_series``, ``no_rows``, ``no_symbols``, ``breaks``, ``recipe``, ``not_found``, ``ambiguous``.


# -- the correspondence with the worksheet ---------------------------------------------------------------
@dataclass(frozen=True, eq=False)
class PointMap:
    """What each vertex of an artist is: the worksheet row it comes from and the coordinates it was given.

    ``rows`` are 1-based worksheet positions. ``drawn`` is False for a vertex that draws nothing (a Y that is
    missing, excluded or not positive on a logarithmic axis): an XY line keeps one vertex per worksheet row.
    """
    rows: np.ndarray
    x: np.ndarray
    y: np.ndarray
    drawn: np.ndarray
    recipe: tuple
    sheet_rows: int
    row_spans: tuple | None = None
    data: object | None = None  # the worksheet frame the graph was drawn from (the labels of the observations read it)

    def __post_init__(self):
        if not (len(self.rows) == len(self.x) == len(self.y) == len(self.drawn)):
            raise ValueError("A point map needs one entry per vertex.")

    def __len__(self):
        return len(self.rows)


def attach_points(artist, positions, x, y, recipe, sheet_rows, drawn=None, *, row_spans=None, data=None):
    """Record the source rows of ``artist``'s vertices. ``positions`` are 1-based worksheet positions.

    ``data`` is the worksheet frame (all its columns, in the rows of ``positions``): the labels of the observations
    read their text from it. Nothing is copied or scanned here.
    """
    positions = np.asarray(positions, dtype=np.int64)
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    shown = np.ones(len(positions), dtype=bool) if drawn is None else np.asarray(drawn, dtype=bool)
    setattr(artist, POINT_MAP_ATTR, PointMap(positions, x, y, shown, tuple(str(name) for name in recipe),
                                             int(sheet_rows), row_spans, data))


def positions_of(frame, index):
    """1-based worksheet positions of the rows labelled ``index``, or None when the labels are not unique."""
    if not frame.index.is_unique:
        return None
    found = frame.index.get_indexer(index)
    return None if (found < 0).any() else found + 1


def point_map(artist):
    return getattr(artist, POINT_MAP_ATTR, None)


def source_record(pmap, index):
    """The identity record of the drawn vertex ``index``."""
    same = np.flatnonzero(pmap.drawn & (pmap.x == pmap.x[index]) & (pmap.y == pmap.y[index]))
    source = {"row": int(pmap.rows[index]), "rows": int(pmap.sheet_rows), "x": float(pmap.x[index]),
              "y": float(pmap.y[index]), "copy": int(np.searchsorted(same, index)) + 1,
              "copies": int(len(same)), "recipe": list(pmap.recipe)}
    if pmap.row_spans is not None and (token := token_at(pmap.row_spans, source["row"])):
        source["row_token"] = token
    return source


@dataclass(frozen=True)
class PointStatus:
    """Where one record stands on the current graph."""
    state: str  # "ok", "hidden" or "suspended"
    index: int | None = None
    reason: str | None = None
    row: int | None = None

    @property
    def ok(self):
        return self.state == "ok"


OK = "ok"


def resolve(source, pmap):
    """Find the vertex a record styled, or say why it cannot be found. Never guesses between candidates."""
    if list(pmap.recipe) != list(source["recipe"]):
        return PointStatus("suspended", None, "recipe", source["row"])
    same = np.flatnonzero(pmap.drawn & (pmap.x == source["x"]) & (pmap.y == source["y"]))
    if "row_token" in source:
        row = row_of(pmap.row_spans, source["row_token"]) if pmap.row_spans is not None else None
        if row is None:
            return PointStatus("suspended", None, "not_found", source["row"])
        here = np.flatnonzero((pmap.rows == row) & pmap.drawn)
        if not len(here):
            return PointStatus("hidden", None, "not_drawn", source["row"])
        # Changing the number of identical plotted observations after a row edit
        # can suspend a style. Never choose a different observation in its place.
        if (pmap.sheet_rows != source["rows"] and len(same) != source["copies"]
                and min(len(same), source["copies"]) > 0 and max(len(same), source["copies"]) > 1):
            return PointStatus("suspended", None, "ambiguous", source["row"])
        return PointStatus(OK, int(here[0]), None, source["row"])
    here = np.flatnonzero(pmap.rows == source["row"])
    at = int(here[0]) if len(here) else None
    if pmap.sheet_rows == source["rows"]:
        # The worksheet kept its length: row positions still mean the same rows.
        if at is None or not pmap.drawn[at]:
            return PointStatus("hidden", None, "not_drawn", source["row"])
        if pmap.x[at] == source["x"] and pmap.y[at] == source["y"]:
            return PointStatus(OK, at, None, source["row"])
        if len(same) >= source["copies"]:
            # The old values are still there as often as before: rows were moved, not edited.
            if source["copies"] == 1 and len(same) == 1:
                return PointStatus(OK, int(same[0]), None, source["row"])
            return PointStatus("suspended", None, "ambiguous", source["row"])
        return PointStatus(OK, at, None, source["row"])  # the row itself was edited
    if len(same) == 0:
        return PointStatus("suspended", None, "not_found", source["row"])
    if len(same) == source["copies"]:
        return PointStatus(OK, int(same[source["copy"] - 1]), None, source["row"])
    return PointStatus("suspended", None, "ambiguous", source["row"])


# -- validation ------------------------------------------------------------------------------------------
def _number(value):
    return type(value) in (int, float) and isfinite(value)


def _whole(value, low=1):
    return type(value) is int and low <= value <= MAX_SHEET_ROWS


def _check_source(source):
    if (not isinstance(source, dict) or source.keys() - {"row_token"} != SOURCE_KEYS
            or ("row_token" in source and not valid_token(source["row_token"]))):
        raise ValueError("Invalid point reference.")
    if not (_whole(source["row"]) and _whole(source["rows"]) and source["row"] <= source["rows"]
            and _whole(source["copy"]) and _whole(source["copies"]) and source["copy"] <= source["copies"]):
        raise ValueError("Invalid point reference.")
    if not (_number(source["x"]) and _number(source["y"])):
        raise ValueError("Invalid point reference.")
    recipe = source["recipe"]
    if (not isinstance(recipe, list) or not 2 <= len(recipe) <= 3
            or any(not isinstance(name, str) or len(name) > 1024 for name in recipe)):
        raise ValueError("Invalid point reference.")


def validate_points(records):
    """Raise ValueError for a malformed list. What the figure shows is never checked here: see ``resolve``."""
    if not isinstance(records, list) or len(records) > MAX_POINT_STYLES:
        raise ValueError(f"Format up to {MAX_POINT_STYLES} individual points.")
    seen = set()
    for record in records:
        if not isinstance(record, dict) or record.keys() - RECORD_KEYS or {"series", "source"} - record.keys():
            raise ValueError("Invalid point style.")
        key = record["series"]
        if not isinstance(key, str) or len(key) > 1024 or SERIES_KEY.fullmatch(key) is None:
            raise ValueError("Points can be formatted in XY series and scatter plots only.")
        _check_source(record["source"])
        if not any(name in record for name in POINT_FIELDS):
            raise ValueError("Choose a color, a symbol or a size for the point.")
        color = record.get("color")
        if "color" in record and not (isinstance(color, str) and len(color) <= 40 and is_color_like(color)):
            raise ValueError("Enter a valid color, for example #2866ae.")
        if "marker" in record and record["marker"] not in MARKER_CODES:
            raise ValueError("Choose a valid symbol.")
        if "marker_size" in record and not (_number(record["marker_size"]) and 0.1 <= record["marker_size"] <= 72):
            raise ValueError("Enter line widths and symbol sizes between 0.1 and 72 points.")
        source = record["source"]
        identity = ((key, source["row_token"]) if "row_token" in source
                    else (key, source["row"], source["x"], source["y"], source["copy"]))
        if identity in seen:
            raise ValueError("A point is formatted twice.")
        seen.add(identity)
    return records


# -- records: the editing operations of the Inspector ---------------------------------------------------
def find_record(records, statuses, series_key, index):
    """The position in ``records`` of the record that styles vertex ``index`` of the series, or None."""
    for position, (record, status) in enumerate(zip(records, statuses, strict=False)):
        if record["series"] == series_key and status.ok and status.index == index:
            return position
    return None


def with_point(records, statuses, series_key, pmap, index, **fields):
    """A copy of ``records`` where the point has ``fields`` (None removes one; none left removes the record).

    An existing record keeps its place and takes the identity of the point as it is now, so a row whose
    values were edited keeps being found.
    """
    updated = [dict(record, source=dict(record["source"])) for record in records]
    position = find_record(updated, statuses, series_key, index)
    if position is None:
        record = {"series": series_key, "source": source_record(pmap, index)}
        updated.append(record)
        position = len(updated) - 1
    else:
        record = updated[position]
        record["source"] = source_record(pmap, index)
    for name, value in fields.items():
        if value is None:
            record.pop(name, None)
        else:
            record[name] = value
    if not any(name in record for name in POINT_FIELDS):
        del updated[position]
    return updated


def without_record(records, position):
    return [record for number, record in enumerate(records) if number != position]


def translate_point_error(error):
    """An engine message of this module in the active language (anything else is returned unchanged)."""
    from .i18n import translate_message

    return translate_message(error, "point.error.")


def points_of_style(style):
    return list((style or {}).get(POINTS) or [])


def strip_points(style):
    """``style`` without point records, for a graph built on other rows (another worksheet, another family)."""
    if not isinstance(style, dict) or POINTS not in style:
        return style
    return {key: value for key, value in style.items() if key != POINTS}


# -- support ---------------------------------------------------------------------------------------------
def _is_marker(value):
    return value not in (None, "None", "none", "", " ")


def support_reason(series, figure=None):
    """Why this series cannot show point styles (a reason code), or None. Does not look at the style."""
    from .axis_breaks import segment_axes

    if series is None or series.kind not in {"scatter", "xy"}:
        return "no_rows"
    artist = series.artist
    pmap = point_map(artist)
    if pmap is None:
        return "no_rows"
    if isinstance(artist, Line2D) and (not _is_marker(artist.get_marker()) or str(artist.get_drawstyle()).startswith("steps")):
        return "no_symbols"
    if isinstance(artist, PathCollection) and not _uniform(artist):
        return "mixed"
    if figure is not None and segment_axes(figure):
        return "breaks"
    return None


# -- legend ----------------------------------------------------------------------------------------------
def _snapshot(artist):
    if isinstance(artist, PathCollection):
        return {"offsets": np.array(artist.get_offsets(), dtype=float)}
    return {"markevery": artist.get_markevery()}


def _install(artist, state):
    if isinstance(artist, PathCollection):
        artist.set_offsets(state["offsets"])
    else:
        artist.set_markevery(state["markevery"])


@contextmanager
def series_look(artist):
    """The artist as the series draws it, without the formatting of single points (for legends and clones).

    A scatter collection keeps its own colors, sizes and shapes whatever is formatted, so only an XY line, whose
    ``markevery`` would reach a legend handle, is put back for the time of the call.
    """
    base = getattr(artist, BASE_ATTR, None)
    if base is None or isinstance(artist, PathCollection):
        yield artist
        return
    styled = _snapshot(artist)
    _install(artist, base)
    try:
        yield artist
    finally:
        _install(artist, styled)


class _SeriesLine(HandlerLine2D):
    def create_artists(self, legend, orig_handle, *args, **kwargs):
        with series_look(orig_handle):
            return super().create_artists(legend, orig_handle, *args, **kwargs)


# A legend entry shows the series, never the one point that was formatted.
Legend.update_default_handler_map({Line2D: _SeriesLine()})


# -- drawing ---------------------------------------------------------------------------------------------
@dataclass
class _State:
    artists: list = field(default_factory=list)
    overlays: list = field(default_factory=list)


def restore_point_styles(figure):
    """Put every artist back to the series look and remove the extra markers."""
    if not figure.axes:
        return
    axes = figure.axes[0]
    state = getattr(axes, STATE_ATTR, None)
    setattr(axes, STATUS_ATTR, [])
    if state is None:
        return
    for artist in state.artists:
        base = getattr(artist, BASE_ATTR, None)
        if base is not None:
            _install(artist, base)
            delattr(artist, BASE_ATTR)
    for overlay in state.overlays:
        try:
            overlay.remove()
        except (ValueError, NotImplementedError):
            pass
    setattr(axes, STATE_ATTR, None)


def _marker_path(code, cache=None):
    marker = MarkerStyle(code)
    return marker.get_path().transformed(marker.get_transform())


def _marker_code(path):
    """The code of the marker a scatter path was drawn with (``"o"`` when it is none of ours)."""
    for code in MARKER_CODES:
        known = _marker_path(code)
        if known.vertices.shape == path.vertices.shape and np.allclose(known.vertices, path.vertices):
            return code
    return "o"


def _uniform(artist):
    """A scatter collection with one color, one size and one shape for all its points."""
    return len(artist.get_paths()) <= 1 and len(artist.get_facecolor()) <= 1 and len(artist.get_sizes()) <= 1


def _overlays(artist, key, x, y, looks, state):
    """One marker line for every distinct look, in the data coordinates of the series."""
    for number, ((face, edge, marker, size), indexes) in enumerate(looks.items()):
        overlay = Line2D(x[indexes], y[indexes], linestyle="None", marker=marker, markersize=size,
                         markerfacecolor=face, markeredgecolor=edge, markeredgewidth=_edge_width(artist),
                         alpha=artist.get_alpha(), zorder=artist.get_zorder() + 0.01, label="_nolegend_",
                         gid=f"{GID_PREFIX}{key}:{number + 1}", visible=artist.get_visible())
        overlay.set_transform(_data_transform(artist))
        artist.axes.add_artist(overlay)
        state.overlays.append(overlay)


def _data_transform(artist):
    """The transform that places the vertices of ``artist`` (a scatter collection keeps it as its offset transform)."""
    return artist.get_offset_transform() if isinstance(artist, PathCollection) else artist.get_transform()


def _edge_width(artist):
    if isinstance(artist, Line2D):
        return artist.get_markeredgewidth()
    widths = artist.get_linewidths()
    return float(widths[0]) if len(widths) else float(rcParams["lines.linewidth"])


def _style_collection(artist, key, entries, state):
    pmap = point_map(artist)
    offsets = np.array(artist.get_offsets(), dtype=float)
    if len(offsets) != len(pmap) or not _uniform(artist):
        return
    setattr(artist, BASE_ATTR, _snapshot(artist))
    state.artists.append(artist)
    faces = artist.get_facecolor()
    face = to_hex(faces[0] if len(faces) else to_rgba("#2866ae"), keep_alpha=True)
    follows = isinstance(artist._edgecolors, str) and artist._edgecolors == "face"
    edges = artist.get_edgecolor()
    edge = face if follows or not len(edges) else to_hex(edges[0], keep_alpha=True)
    sizes = artist.get_sizes()
    size = float(np.sqrt(sizes[0])) if len(sizes) else float(rcParams["lines.markersize"])
    paths = artist.get_paths()
    marker = _marker_code(paths[0]) if len(paths) else "o"
    looks = {}
    for index, record in entries:
        look = (record.get("color") or face, record.get("color") or edge, record.get("marker") or marker,
                float(record.get("marker_size") or size))
        looks.setdefault(look, []).append(index)
    hidden = offsets.copy()
    hidden[[index for index, _ in entries]] = np.nan  # the vertex keeps its place; the series draws nothing there
    artist.set_offsets(hidden)
    _overlays(artist, key, offsets[:, 0], offsets[:, 1], looks, state)


def _style_line(artist, key, entries, state):
    pmap = point_map(artist)
    if len(artist.get_xdata()) != len(pmap) or artist.get_markevery() is not None:
        return
    setattr(artist, BASE_ATTR, _snapshot(artist))
    state.artists.append(artist)
    keep = np.ones(len(pmap), dtype=bool)
    looks = {}
    series_color = artist.get_color()
    for index, record in entries:
        keep[index] = False
        face = record.get("color") or (series_color if artist.get_markerfacecolor() in ("auto", None)
                                       else artist.get_markerfacecolor())
        edge = record.get("color") or (series_color if artist.get_markeredgecolor() in ("auto", None)
                                       else artist.get_markeredgecolor())
        look = (to_hex(face, keep_alpha=True), to_hex(edge, keep_alpha=True),
                record.get("marker") or artist.get_marker(),
                float(record.get("marker_size") or artist.get_markersize()))
        looks.setdefault(look, []).append(index)
    artist.set_markevery(keep)
    _overlays(artist, key, pmap.x, pmap.y, looks, state)


def apply_point_styles(figure, series, records, *, breaks=False):
    """Draw the point styles of ``records`` on ``figure`` and return one ``PointStatus`` per record."""
    restore_point_styles(figure)
    if not figure.axes:
        return []
    axes = figure.axes[0]
    by_key = {item.key: item for item in series}
    statuses, planned = [], {}
    for record in records:
        source = record["source"]
        item = by_key.get(record["series"])
        if item is None:
            status = PointStatus("suspended", None, "no_series", source["row"])
        else:
            reason = "breaks" if breaks else support_reason(item)
            if reason:
                status = PointStatus("suspended", None, reason, source["row"])
            else:
                status = resolve(source, point_map(item.artist))
        statuses.append(status)
        if status.ok:
            planned.setdefault(id(item.artist), (item.artist, item.key, {}))[2][status.index] = record
    state = _State()
    for artist, key, entries in planned.values():
        ordered = sorted(entries.items())
        if isinstance(artist, PathCollection):
            _style_collection(artist, key, ordered, state)
        else:
            _style_line(artist, key, ordered, state)
    setattr(axes, STATE_ATTR, state if state.artists else None)
    setattr(axes, STATUS_ATTR, statuses)
    return statuses


def point_statuses(figure):
    """The statuses of the last ``apply_point_styles`` on ``figure``, one per record."""
    return list(getattr(figure.axes[0], STATUS_ATTR, None) or []) if figure.axes else []


def point_styles_status(figure, records):
    """One line about the records that are not drawn, for the graph warning; None when all is well."""
    from .i18n import tr

    statuses = point_statuses(figure)
    held = [(record, status) for record, status in zip(records or [], statuses, strict=False)
            if status.state == "suspended"]
    if not held:
        return None
    return tr("point.status.suspended", count=len(held), reason=reason_text(held[0][1], held[0][0]))


def reason_text(status, record=None):
    from .i18n import tr

    series = record["series"] if record else ""
    return tr("point.reason." + status.reason, row=status.row, series=series) if status.reason else ""


# -- picking and describing points ---------------------------------------------------------------------
def drawn_vertices(artist):
    """Indexes of the vertices of ``artist`` that draw a point."""
    pmap = point_map(artist)
    if pmap is None:
        return np.zeros(0, dtype=int)
    return np.flatnonzero(pmap.drawn)


def display_positions(artist):
    """Display coordinates of every vertex of ``artist`` (NaN for the vertices that draw nothing)."""
    pmap = point_map(artist)
    points = np.column_stack([pmap.x, pmap.y])
    points[~pmap.drawn] = np.nan
    return artist.axes.transData.transform(points) if artist.axes is not None else points


def nearest_points(series, x, y, tolerance=9.0):
    """``[(index, distance)]`` of the drawn points of ``series`` within ``tolerance`` display pixels of (x, y).

    Nearest first; a click on overlapping points returns each of them.
    """
    artist = series.artist
    if point_map(artist) is None or not artist.get_visible():
        return []
    with np.errstate(invalid="ignore"):
        positions = display_positions(artist)
        distance = np.hypot(positions[:, 0] - x, positions[:, 1] - y)
    near = np.flatnonzero(distance <= tolerance)
    order = near[np.argsort(distance[near], kind="stable")]
    return [(int(index), float(distance[index])) for index in order]


def overlapping(series, index):
    """Every drawn vertex of ``series`` that lies on the same pixel as ``index``, in worksheet order."""
    artist = series.artist
    positions = display_positions(artist)
    with np.errstate(invalid="ignore"):
        distance = np.hypot(positions[:, 0] - positions[index, 0], positions[:, 1] - positions[index, 1])
    return [int(number) for number in np.flatnonzero(distance < 1.0)]


def describe_point(pmap, index):
    from .i18n import tr

    return tr("point.item", row=int(pmap.rows[index]), x=f"{pmap.x[index]:.6g}", y=f"{pmap.y[index]:.6g}")


def series_defaults(series, style=None):
    """The color, symbol code and size the series gives its points now (before single-point formatting)."""
    artist = series.artist
    with series_look(artist):
        if isinstance(artist, PathCollection):
            faces = artist.get_facecolor()
            color = to_hex(faces[0]) if len(faces) else "#2866ae"
            sizes = artist.get_sizes()
            size = float(np.sqrt(sizes[0])) if len(sizes) else float(rcParams["lines.markersize"])
            marker = ((style or {}).get("series", {}).get(series.key, {}).get("marker") or "o")
        else:
            face = artist.get_markerfacecolor()
            color = to_hex(artist.get_color() if face in ("auto", None) else face)
            size = float(artist.get_markersize())
            marker = artist.get_marker()
    return color, marker, size


# -- the temporary selection indicator ------------------------------------------------------------------
class _Indicator(Line2D):
    """A ring around the selected point. It is drawn on screen only: an export, a layout or a thumbnail
    renders through ``savefig``, where ``is_saving()`` is true, and never sees it."""

    def draw(self, renderer):
        figure = self.get_figure(root=True)
        canvas = figure.canvas if figure is not None else None
        if canvas is not None and canvas.is_saving():
            return
        super().draw(renderer)


def clear_indicator(figure):
    if not figure.axes:
        return
    axes = figure.axes[0]
    ring = getattr(axes, INDICATOR_ATTR, None)
    if ring is not None:
        try:
            ring.remove()
        except (ValueError, NotImplementedError):
            pass
        setattr(axes, INDICATOR_ATTR, None)


def show_indicator(series, index, extent=None):
    """Mark vertex ``index`` of ``series`` with a ring; ``extent`` is the symbol size in points."""
    artist = series.artist
    pmap = point_map(artist)
    figure = artist.get_figure(root=True)
    clear_indicator(figure)
    if pmap is None or not 0 <= index < len(pmap) or not pmap.drawn[index]:
        return None
    size = (extent if extent is not None else series_defaults(series)[2]) + 9
    ring = _Indicator([pmap.x[index]], [pmap.y[index]], marker="o", markersize=size, markerfacecolor="none",
                      markeredgecolor=INDICATOR_COLOR, markeredgewidth=2.2, linestyle="None", zorder=1000,
                      gid=INDICATOR_GID, label="_nolegend_")
    ring.set_path_effects([path_effects.withStroke(linewidth=4.4, foreground="white")])
    ring.set_transform(_data_transform(artist))
    artist.axes.add_artist(ring)
    ring.set_clip_on(False)
    ring.set_in_layout(False)  # Never moves the axes: the ring is not part of a layout or a tight box.
    setattr(figure.axes[0], INDICATOR_ATTR, ring)
    return ring
