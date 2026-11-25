"""Labels of the observations of XY series and scatter plots.

A label puts a text beside the point an observation draws: the title of its worksheet row or the value of one of
its columns. It is presentation only. Nothing about the worksheet, the series, the calculation, the legend or the
limits of the axes changes. The labels live in the shared presentation style under ``"observation_labels"``, a
list with one record for every series that has labels::

    {"series": "scatter:1:C",
     "from": {"kind": "column", "name": "Etichetta", "id": "base:5"},
     "show": true, "color": "#2866ae", "position": "above", "size": 8, "limit": 250,
     "observations": [{"source": {...identity of the point...}, "show": false}]}

``from`` is where the text comes from: ``{"kind": "row_title"}`` is the row title column of the worksheet (the
column named *Row title*), ``{"kind": "column", ...}`` any other column, numeric or text. A column is found by its
identity (``analisi.worksheet_column_identity``), not by its name: a rename follows the column, and a column that
is deleted leaves the label source *missing* until someone chooses a column again, even when another column takes
the old name. ``show``, ``color``, ``position`` (``above``, ``below``, ``left``, ``right``), ``size`` (points) and
``limit`` are optional. ``observations`` are the overrides of single observations (``show`` true or false). They
reuse the identity of ``analisi.point_style`` (the worksheet row, its stable token, the coordinates, the position
among identical points): the label follows its row when the rows are reordered, and an override whose row is gone
or whose identity became uncertain is *suspended* (never given to another row) and stays listed so it can be
removed.

The text is literal: ``$``, symbols and accents are drawn as they are, never as math. A cell that is empty,
missing or excluded, a number that is not finite, and a point that is not drawn make no label.

Rendering limit and priority. A series draws at most ``limit`` labels (250 unless the record says otherwise, up to
1000). When more observations have a label, the overrides that *show* come first, in worksheet order, and then the
other observations in worksheet order (the order of the drawn points); the rest is omitted, and the number omitted
is reported (``LabelStatus.omitted``, shown in the Inspector). An override that hides is never counted. A series
without a record is not looked at: no label is computed for it and nothing extra is drawn for it.

Drawing. The labels of a series are the texts of one artist (``_LabelLayer``) in the axes, outside the series
list, the limits and the legend. The layer draws the texts of the points that lie inside the axes at the time of
the drawing, so a zoom or a limit set later never leaves a label floating outside the plot; it never takes part in
the layout of the figure. Every text is an ordinary text of the renderer (text in PDF, ``<text>`` in SVG when the
export keeps text, glyph outlines otherwise), so a PNG, an SVG, a PDF and a layout that embeds the figure all
carry the labels. Styles are applied from a clean state (``restore_observation_labels``), so applying one again
never duplicates an artist.
"""
from dataclasses import dataclass, field
from math import isfinite
import re

import numpy as np
import pandas as pd
from matplotlib import rcParams
from matplotlib.artist import Artist
from matplotlib.colors import is_color_like
from matplotlib.text import Text
from matplotlib.transforms import ScaledTranslation

from .point_style import (PointStatus, SERIES_KEY, _check_source, _data_transform, point_map, resolve, series_defaults,
                          source_record, support_reason)
from .worksheet_column_identity import frame_ids, valid_reference

LABELS = "observation_labels"
DEFAULT_LIMIT = 250
MAX_LIMIT = 1000
MAX_LABEL_SERIES = 64
MAX_OVERRIDES = 256
POSITIONS = ("above", "below", "left", "right")
DEFAULT_POSITION = "above"
DEFAULT_SIZE = 8.0
MIN_SIZE, MAX_SIZE = 4, 72
MAX_TEXT = 200
GAP = 3.0  # points between the edge of the symbol and the label
GID_PREFIX = "trama-observation-labels:"
ROW_TITLE, COLUMN = "row_title", "column"
ROW_TITLE_NAMES = ("row title", "row titles")
RECORD_KEYS = {"series", "from", "show", "color", "position", "size", "limit", "observations"}
STATE_ATTR = "_tramastat_label_state"
STATUS_ATTR = "_tramastat_label_status"
SURROGATES = re.compile("[\ud800-\udfff]")
CONTROLS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Why a series or an override is not drawn (``LabelStatus.reason`` and ``PointStatus.reason``):
# ``no_series``, ``no_rows``, ``no_symbols``, ``mixed``, ``breaks`` (the series cannot show labels), ``no_data`` (the
# graph does not carry its worksheet), ``missing`` (the column is gone or was replaced), ``no_title`` (the worksheet
# has no row title column); for an override ``not_drawn`` (the point is excluded or has no value: it waits),
# ``recipe``, ``not_found`` and ``ambiguous`` (the identity of the point is uncertain).


# -- validation ------------------------------------------------------------------------------------------
def _number(value):
    return type(value) in (int, float) and isfinite(value)


def _check_origin(origin):
    if not isinstance(origin, dict) or origin.get("kind") not in (ROW_TITLE, COLUMN):
        raise ValueError("Invalid label source.")
    if origin["kind"] == ROW_TITLE:
        if origin.keys() != {"kind"}:
            raise ValueError("Invalid label source.")
        return
    name = origin.get("name")
    if (origin.keys() - {"kind", "name", "id"} or not isinstance(name, str) or not name or len(name) > 1024
            or ("id" in origin and not valid_reference(origin["id"]))):
        raise ValueError("Invalid label source.")


def validate_labels(records):
    """Raise ValueError for a malformed list. Whether the labels can be drawn is never checked here: see ``status``."""
    if not isinstance(records, list) or len(records) > MAX_LABEL_SERIES:
        raise ValueError(f"Label up to {MAX_LABEL_SERIES} series.")
    seen_series, overrides = set(), 0
    for record in records:
        if not isinstance(record, dict) or record.keys() - RECORD_KEYS or {"series", "from"} - record.keys():
            raise ValueError("Invalid label setting.")
        key = record["series"]
        if not isinstance(key, str) or len(key) > 1024 or SERIES_KEY.fullmatch(key) is None:
            raise ValueError("Labels are available in XY series and scatter plots only.")
        if key in seen_series:
            raise ValueError("A series has two label settings.")
        seen_series.add(key)
        _check_origin(record["from"])
        if "show" in record and type(record["show"]) is not bool:
            raise ValueError("Invalid label visibility.")
        if "color" in record and not (isinstance(record["color"], str) and len(record["color"]) <= 40
                                      and is_color_like(record["color"])):
            raise ValueError("Enter a valid label color, for example #2866ae.")
        if "position" in record and record["position"] not in POSITIONS:
            raise ValueError("Choose where the label goes: above, below, left or right.")
        if "size" in record and not (_number(record["size"]) and MIN_SIZE <= record["size"] <= MAX_SIZE):
            raise ValueError(f"Enter a label size between {MIN_SIZE} and {MAX_SIZE} points.")
        if "limit" in record and not (type(record["limit"]) is int and 1 <= record["limit"] <= MAX_LIMIT):
            raise ValueError(f"Enter a limit of 1 to {MAX_LIMIT} labels.")
        found = record.get("observations", [])
        if not isinstance(found, list):
            raise ValueError("Invalid label of an observation.")
        overrides += len(found)
        if overrides > MAX_OVERRIDES:
            raise ValueError(f"Set the labels of up to {MAX_OVERRIDES} individual observations.")
        seen = set()
        for item in found:
            if not isinstance(item, dict) or item.keys() != {"source", "show"} or type(item["show"]) is not bool:
                raise ValueError("Invalid label of an observation.")
            _check_source(item["source"])
            source = item["source"]
            identity = (source["row_token"] if "row_token" in source
                        else (source["row"], source["x"], source["y"], source["copy"]))
            if identity in seen:
                raise ValueError("An observation has two label settings.")
            seen.add(identity)
    return records


def translate_label_error(error):
    """An engine message of this module in the active language (anything else is returned unchanged)."""
    from .i18n import translate_message

    return translate_message(error, "label.error.")


def labels_of_style(style):
    return list((style or {}).get(LABELS) or [])


def strip_labels(style):
    """``style`` without label records, for a graph built on other rows or columns (another sheet)."""
    if not isinstance(style, dict) or LABELS not in style:
        return style
    return {key: value for key, value in style.items() if key != LABELS}


def remap_labels(records, columns):
    """The label records for a repetition on another sheet: the source columns and the series named after them
    follow ``columns`` (``{old: new}``); the identities of the old sheet and the single observations stay behind."""
    renamed = []
    for record in records or ():
        record = {key: value for key, value in record.items() if key != "observations"}
        origin = dict(record["from"])
        if origin["kind"] == COLUMN:
            origin = {"kind": COLUMN, "name": columns.get(origin["name"], origin["name"])}
        record["from"] = origin
        kind, _, rest = record["series"].partition(":")
        number, _, label = rest.partition(":")
        if label in columns:
            record["series"] = f"{kind}:{number}:{columns[label]}"
        renamed.append(record)
    return renamed


# -- the text of the cells ---------------------------------------------------------------------------------
def label_text(value):
    """The literal text a cell gives its label, or ``""`` when it has none (a missing cell, a number that is not
    finite, blanks). Only controls that cannot be drawn are removed and a very long text is cut."""
    if value is None or value is pd.NA or value is pd.NaT:
        return ""
    if isinstance(value, (bool, np.bool_)):
        return str(bool(value))
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        return format(float(value), ".12g") if isfinite(value) else ""
    text = SURROGATES.sub("", CONTROLS.sub("", str(value)))
    if not text.strip():
        return ""
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"


def _text_mask(values):
    """Which of the cells of ``values`` give a label (one vectorized pass, no text is built)."""
    if pd.api.types.is_numeric_dtype(values) and not pd.api.types.is_bool_dtype(values):
        numbers = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float, na_value=np.nan)
        return np.isfinite(numbers)
    mask = values.notna().to_numpy(dtype=bool, copy=True)
    if mask.any():
        strings = values.astype("string").str.strip().fillna("")
        mask &= (strings != "").to_numpy(dtype=bool, na_value=False)
    return mask


# -- where the text comes from -----------------------------------------------------------------------------
def row_title_name(frame):
    """The row title column of a worksheet frame: the first column named *Row title* (or the one a result names)."""
    named = frame.attrs.get("row_title_column")
    if named in frame.columns:
        return named
    for name in frame.columns:
        if isinstance(name, str) and name.strip().casefold() in ROW_TITLE_NAMES:
            return name
    return None


def column_origin(frame, name):
    """The label source that reads column ``name`` of ``frame`` and finds it again after a rename."""
    return {"kind": COLUMN, "name": str(name), "id": frame_ids(frame)[name]}


def source_choices(frame):
    """``[(origin, caption)]`` of the places a label can read: the row titles first, then every other column."""
    title = row_title_name(frame)
    choices = [({"kind": ROW_TITLE}, title)] if title is not None else []
    choices.extend((column_origin(frame, name), str(name)) for name in frame.columns if name != title)
    return choices


def resolve_origin(origin, frame):
    """``(column name, None)`` for the column ``origin`` reads in ``frame``, or ``(None, reason)``.

    A source with an identity is found by it alone: the same name on another column is *not* the source. A source
    without one (a copy made for another sheet) is found by name.
    """
    if origin["kind"] == ROW_TITLE:
        name = row_title_name(frame)
        return (name, None) if name is not None else (None, "no_title")
    if "id" in origin:
        for name, token in frame_ids(frame).items():
            if token == origin["id"]:
                return name, None
        return None, "missing"
    return (origin["name"], None) if origin["name"] in frame.columns else (None, "missing")


def origin_caption(origin, frame=None):
    """The name to show for a source: its live column name, else the name it had when it was chosen."""
    if frame is not None:
        name, _ = resolve_origin(origin, frame)
        if name is not None:
            return str(name)
    return origin.get("name", "") if origin["kind"] == COLUMN else ""


# -- the state of one series ---------------------------------------------------------------------------------
@dataclass(frozen=True)
class LabelStatus:
    """Where one record stands on the current graph."""
    state: str  # "ok" or "suspended"
    reason: str | None = None
    column: str | None = None  # the column read (its live name)
    candidates: int = 0  # observations that have a label to draw
    shown: int = 0
    omitted: int = 0
    limit: int = DEFAULT_LIMIT
    observations: tuple = ()  # one PointStatus per override of the record, in order

    @property
    def ok(self):
        return self.state == "ok"


def label_statuses(figure):
    """The statuses of the last ``apply_observation_labels`` on ``figure``, one per record."""
    return list(getattr(figure.axes[0], STATUS_ATTR, None) or []) if figure.axes else []


def label_layers(figure):
    """The artists that draw the labels of ``figure`` (one per labelled series)."""
    state = getattr(figure.axes[0], STATE_ATTR, None) if figure.axes else None
    return list(state.layers) if state else []


def label_texts(figure):
    """Every label text drawn on ``figure`` as ``(series key, text)``, in drawing order."""
    return [(layer.series_key, text.get_text()) for layer in label_layers(figure) for text in layer.texts]


@dataclass
class _State:
    layers: list = field(default_factory=list)


class _LabelLayer(Artist):
    """The texts of one series: drawn together, only for the points inside the axes, never part of the layout."""

    def __init__(self, series_key, texts, vertices, anchors, transform, zorder, artist):
        super().__init__()
        self.series_key, self.texts, self.vertices = series_key, texts, vertices
        self._anchors, self._data, self._series = anchors, transform, artist
        self.set_zorder(zorder)
        self.set_gid(f"{GID_PREFIX}{series_key}")
        self.set_label("_nolegend_")
        self.set_in_layout(False)

    def inside(self):
        """Which texts belong to a point that lies inside the axes now."""
        axes = self.axes
        pixels = self._data.transform(self._anchors)
        box = axes.bbox
        with np.errstate(invalid="ignore"):
            return ((pixels[:, 0] >= box.x0) & (pixels[:, 0] <= box.x1)
                    & (pixels[:, 1] >= box.y0) & (pixels[:, 1] <= box.y1))

    def draw(self, renderer):
        if not self.get_visible() or not self._series.get_visible() or not self.texts or self.axes is None:
            return
        renderer.open_group("observation-labels", self.get_gid())
        for text, show in zip(self.texts, self.inside(), strict=True):
            if show:
                text.draw(renderer)
        renderer.close_group("observation-labels")
        self.stale = False


def restore_observation_labels(figure):
    """Remove the labels a previous style drew."""
    if not figure.axes:
        return
    axes = figure.axes[0]
    state = getattr(axes, STATE_ATTR, None)
    setattr(axes, STATUS_ATTR, [])
    if state is None:
        return
    for layer in state.layers:
        try:
            layer.remove()
        except (ValueError, NotImplementedError):
            pass
    setattr(axes, STATE_ATTR, None)


# -- drawing -----------------------------------------------------------------------------------------------
def _alignment(position):
    return {"above": ("center", "bottom", 0, 1), "below": ("center", "top", 0, -1),
            "left": ("right", "center", -1, 0), "right": ("left", "center", 1, 0)}[position]


def _suspended(reason, record, *, row=None):
    overrides = tuple(PointStatus("suspended", None, reason, item["source"]["row"])
                      for item in record.get("observations", ()))
    return LabelStatus("suspended", reason, observations=overrides, limit=record.get("limit", DEFAULT_LIMIT))


def _plan(pmap, values, record):
    """The vertices that get a label, the override statuses and the counts, without building any text."""
    limit = record.get("limit", DEFAULT_LIMIT)
    forced, statuses = {}, []
    for item in record.get("observations", ()):
        status = resolve(item["source"], pmap)
        statuses.append(status)
        if status.ok:
            forced[status.index] = item["show"]
    eligible = pmap.drawn & _text_mask(values)
    explicit = np.array(sorted(index for index, show in forced.items() if show and eligible[index]), dtype=np.int64)
    blocked = [index for index, show in forced.items() if not show or index in explicit]
    others = eligible.copy()
    others[blocked] = False
    rest = np.flatnonzero(others) if record.get("show", True) else np.zeros(0, dtype=np.int64)
    ordered = np.concatenate([explicit, rest])
    chosen = np.sort(ordered[:limit])
    return chosen, statuses, len(ordered), limit


def _apply_record(figure, item, record, breaks, state, font_family):
    if item is None:
        return _suspended("no_series", record)
    reason = "breaks" if breaks else support_reason(item)
    if reason:
        return _suspended(reason, record)
    artist = item.artist
    pmap = point_map(artist)
    frame = pmap.data
    if frame is None or len(frame) != pmap.sheet_rows:
        return _suspended("no_data", record)
    column, reason = resolve_origin(record["from"], frame)
    if reason:
        return LabelStatus("suspended", reason, None, observations=tuple(
            resolve(entry["source"], pmap) for entry in record.get("observations", ())),
            limit=record.get("limit", DEFAULT_LIMIT))
    values = frame[column].iloc[pmap.rows - 1]
    chosen, statuses, candidates, limit = _plan(pmap, values, record)
    status = LabelStatus("ok", None, str(column), candidates, len(chosen), candidates - len(chosen), limit,
                         tuple(statuses))
    if not len(chosen):
        return status
    size = float(record.get("size", DEFAULT_SIZE))
    color = record.get("color") or rcParams["text.color"]
    ha, va, step_x, step_y = _alignment(record.get("position", DEFAULT_POSITION))
    gap = (series_defaults(item)[2] / 2 + GAP) / 72
    transform = _data_transform(artist) + ScaledTranslation(step_x * gap, step_y * gap, figure.dpi_scale_trans)
    texts = []
    for vertex in chosen:
        text = Text(float(pmap.x[vertex]), float(pmap.y[vertex]), label_text(values.iloc[vertex]), color=color,
                    fontsize=size, ha=ha, va=va, transform=transform, clip_on=False, parse_math=False, usetex=False,
                    **({"fontfamily": font_family} if font_family else {}))
        text.set_figure(figure)
        texts.append(text)
    anchors = np.column_stack([pmap.x[chosen], pmap.y[chosen]])
    layer = _LabelLayer(item.key, texts, chosen, anchors, _data_transform(artist), max(2.5, artist.get_zorder() + 0.5),
                        artist)
    artist.axes.add_artist(layer)
    state.layers.append(layer)
    return status


def apply_observation_labels(figure, series, records, *, breaks=False, font_family=None):
    """Draw the labels of ``records`` on ``figure`` and return one ``LabelStatus`` per record."""
    restore_observation_labels(figure)
    if not records or not figure.axes:
        return []
    axes = figure.axes[0]
    by_key = {item.key: item for item in series}
    state = _State()
    statuses = [_apply_record(figure, by_key.get(record["series"]), record, breaks, state, font_family)
                for record in records]
    setattr(axes, STATE_ATTR, state if state.layers else None)
    setattr(axes, STATUS_ATTR, statuses)
    return statuses


# -- records: the editing operations of the Inspector -------------------------------------------------------
def find_series_record(records, series_key):
    return next((number for number, record in enumerate(records) if record["series"] == series_key), None)


def with_series(records, series_key, **fields):
    """A copy of ``records`` where the series record has ``fields`` (None removes one). A record needs its source:
    without ``from`` the record is removed together with its overrides."""
    updated = [{**record, "observations": [dict(item, source=dict(item["source"]))
                                           for item in record.get("observations", ())]}
               if "observations" in record else dict(record) for record in records]
    position = find_series_record(updated, series_key)
    if position is None:
        if fields.get("from") is None:
            return updated
        updated.append({"series": series_key})
        position = len(updated) - 1
    record = updated[position]
    for name, value in fields.items():
        if value is None:
            record.pop(name, None)
        else:
            record[name] = value
    if "from" not in record:
        del updated[position]
    else:
        for name, default in (("show", True), ("position", DEFAULT_POSITION), ("limit", DEFAULT_LIMIT),
                              ("size", DEFAULT_SIZE)):
            if record.get(name) == default:
                del record[name]
    return updated


def find_override(record, statuses, pmap, vertex):
    """The position among ``record['observations']`` of the override of vertex ``vertex``, or None."""
    for position, status in enumerate(statuses):
        if status.ok and status.index == vertex:
            return position
    return None


def with_override(records, status, series_key, pmap, vertex, show):
    """A copy of ``records`` where observation ``vertex`` of the series is shown (True), hidden (False) or follows
    the series (None). An override takes the identity of the point as it is now, so an edited row stays found."""
    updated = with_series(records, series_key)
    position = find_series_record(updated, series_key)
    if position is None:
        return updated
    record = updated[position]
    found = record.setdefault("observations", [])
    current = find_override(record, status.observations if status else (), pmap, vertex)
    if current is not None:
        found.pop(current)
    if show is not None:
        entry = {"source": source_record(pmap, vertex), "show": show}
        if current is None:
            found.append(entry)
        else:
            found.insert(current, entry)
    if not found:
        del record["observations"]
    return updated


def without_override(records, series_key, position):
    updated = with_series(records, series_key)
    index = find_series_record(updated, series_key)
    if index is not None:
        record = updated[index]
        found = list(record.get("observations", ()))
        if 0 <= position < len(found):
            found.pop(position)
        if found:
            record["observations"] = found
        else:
            record.pop("observations", None)
    return updated


def override_of(record, status, vertex):
    """``True``/``False`` when observation ``vertex`` is shown/hidden on purpose, else None."""
    if status is None:
        return None
    for item, point in zip(record.get("observations", ()), status.observations, strict=False):
        if point.ok and point.index == vertex:
            return item["show"]
    return None


def text_at(series, record, vertex):
    """The label text observation ``vertex`` of ``series`` would carry under ``record``'s source ('' for none)."""
    pmap = point_map(series.artist)
    if pmap is None or pmap.data is None or len(pmap.data) != pmap.sheet_rows:
        return ""
    column, reason = resolve_origin(record["from"], pmap.data)
    if reason:
        return ""
    return label_text(pmap.data[column].iloc[int(pmap.rows[vertex]) - 1])


def label_status_line(figure, records):
    """One line about labels that are not drawn, for the graph warning; None when all is well."""
    from .i18n import tr

    statuses = label_statuses(figure)
    held = [(record, status) for record, status in zip(records or [], statuses, strict=False)
            if status.state == "suspended" or any(point.state == "suspended" for point in status.observations)]
    if not held:
        return None
    record, status = held[0]
    return tr("label.status.suspended", count=len(held), reason=reason_text(status, record))


def reason_text(status, record=None):
    """Why a series (``LabelStatus``) or one of its overrides (``PointStatus``) is not drawn."""
    from .i18n import tr

    series = record["series"] if record else ""
    if isinstance(status, LabelStatus) and status.state == "ok":
        return next((reason_text(point, record) for point in status.observations if point.state == "suspended"), "")
    name = ""
    if record is not None and record["from"]["kind"] == COLUMN:
        name = record["from"]["name"]
    return tr("label.reason." + status.reason, row=getattr(status, "row", None), series=series, column=name) \
        if status.reason else ""
