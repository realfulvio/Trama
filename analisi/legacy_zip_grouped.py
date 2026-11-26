"""Recover a grouped bar chart from the worksheet and saved graph records."""

from math import isfinite
from struct import Struct, error as StructError, unpack_from

import pandas as pd

from .category_graphs import (
    BARS, INTERLEAVED, INTERVAL_DIRECTION, MAX_CATEGORIES, MAX_PLOT_CELLS, MAX_POINTS,
    RAW, SERIES_PLACEMENT, STACK_PREVIOUS, UPPER_INTERVAL, grouped_series_names,
)
from .legacy_binary_editable import _id_array, _one, _require, _subgroups
from .legacy_import import _identifier, _json_object
from .legacy_zip_xy import _MAX_GRAPH_BYTES, _MAX_TICKS, _graph_records, _saved_captions
from .presentation import validated_style


_LINK = Struct("<3i")


def _placement(records, datasets, rows):
    keys = _id_array(_one(records, 0x15))
    links = _one(records, 0x16)
    _require(len(keys) == len(datasets) == len(set(keys)) and len(links) == 2 + len(keys) * _LINK.size
             and unpack_from("<H", links)[0] == len(keys)
             and list(_LINK.iter_unpack(links[2:])) == [(dataset, 0, -2) for dataset in datasets])

    scene, = _subgroups(records, 0x8018)
    objects = list(_subgroups(scene[1], 0x8020))
    series, visible_axes = {}, set()
    for header, body in objects:
        _require(len(header) == 30)
        kind, = unpack_from("<H", header)
        flags, = unpack_from("<H", header, 28)
        if kind == 8 and not flags & 0x800:
            axis_id, = Struct("<H").unpack(_one(body, 0x2A))
            visible_axes.add(axis_id)
        if kind != 9:
            continue
        style = _one(body, 0x8028)
        key, family, dataset, enabled, center, mode, interval, sides = unpack_from("<8H", style)
        _require(len(style) == 144 and key not in series and not flags & 0x200
                 and (family, enabled, center, mode, interval, sides) == (1, 1, 0, 1, 2, 2)
                 and unpack_from("<H", style, 58)[0] == 14)
        detail, = [payload for tag, parent, payload in body if tag == 0x9C and parent == (40,)]
        _require(len(detail) == 321 and unpack_from("<2I", detail) == (27, 0xFFFFFFFF)
                 and unpack_from("<3I", detail, 293) == (1, 1, 0x20000)
                 and unpack_from("<I", detail, 313)[0] == dataset)
        left, _, right, _ = unpack_from("<4h", header, 2)
        relation, = unpack_from("<H", style, 104)
        _require(left < right)
        series[key] = dataset, relation, left, right

    _require(set(series) == set(keys) and [series[key][0] for key in keys] == datasets)
    relations = [series[key][1] for key in keys]
    _require(relations[0] == 0 and all(relation in (1, 2) for relation in relations[1:]) and 2 in relations)
    for previous, key in zip(keys, keys[1:]):
        _, relation, left, right = series[key]
        _, _, previous_left, previous_right = series[previous]
        if relation == 2:
            _require((left, right) == (previous_left, previous_right))
        else:
            _require(left > previous_left and right > previous_right)

    x, y, _ = [payload for tag, parent, payload in records if tag == 0x17 and not parent]
    _require(len(x) == len(y) == 60 and unpack_from("<2d", x, 16) == (1., float(rows)))
    x_id, y_id = [unpack_from("<H", axis, 54)[0] for axis in (x, y)]
    chart = _one(records, 0x13)
    left, top, right, bottom = unpack_from("<4h", chart)
    length, _, kind, title = unpack_from("<4H", y, 42)
    low, high = unpack_from("<2d", y, 16)
    _require(len(chart) == 48 and visible_axes == {x_id, y_id} and x_id != y_id
             and right - left == unpack_from("<H", x, 42)[0] > 0 and bottom - top == length > 0
             and kind == 0 and isfinite(low) and isfinite(high) and low < high)
    scale, = [header for header, _ in _subgroups(records, 0x8025) if unpack_from("<H", header)[0] == y_id]
    step, origin = unpack_from("<2d", scale, 54)
    _require(unpack_from("<2d", scale, 2) == (low, high) and unpack_from("<H", scale, 28)[0] == kind
             and isfinite(step) and step > 0 and isfinite(origin) and (high - low) / step <= _MAX_TICKS)
    captions = _saved_captions(records, objects, axis_titles=(unpack_from("<H", x, 48)[0], title))
    style = {"yscale": "linear", "axis": {"y": {"min": low, "max": high, "step": step, "start": origin}},
             **{name: value for name, value in captions.items() if len(value) <= 160}}
    return relations, validated_style(style)


def saved_grouped_bars(archive, graph, uid, sources):
    """Bind the supported grouped stacks with raw replicates and upper SEM."""
    try:
        selected = graph.get("inputDataSets")
        _require(graph.get("uid") == uid and type(graph.get("fenID")) is int
                 and isinstance(selected, list) and 2 <= len(selected) <= MAX_CATEGORIES)
        ids = [_identifier(value) for value in selected]
        _require(len(set(ids)) == len(ids))
        (sheet_uid, frame), = [(name, frame) for name, frame in sources.items()
                               if frame.attrs.get("table_format") == "grouped"
                               and frame.attrs.get("legacy_y") == ids]
        _require(frame.attrs["legacy_y_format"] == "y_replicates" and frame.attrs["legacy_x"] is None
                 and 0 < len(frame) <= MAX_CATEGORIES and len(frame) * len(ids) <= MAX_PLOT_CELLS)
        columns_by_id = frame.attrs["legacy_columns"]
        columns = [column for dataset in ids for column in columns_by_id[dataset]]
        _require(len(frame) * len(columns) <= MAX_POINTS and len(set(columns)) == len(columns)
                 and all(pd.api.types.is_numeric_dtype(frame[column]) for column in columns)
                 and frame[columns].notna().any(axis=1).all())
        sheet = _json_object(archive, f"data/sheets/{sheet_uid}/sheet.json")
        _require(sheet.get("uid") == sheet_uid and type(sheet.get("fenID")) is int)
        datasets = [_json_object(archive, f"data/sets/{dataset}.json")["fenID"] for dataset in ids]
        _require(all(type(number) is int and number >= 0 for number in datasets)
                 and len(set(datasets)) == len(datasets))

        member = archive.getinfo(f"graphs/{uid}/data.bin")
        _require(0 < member.file_size <= _MAX_GRAPH_BYTES)
        records = _graph_records(archive.read(member), graph["fenID"])
        _require(_id_array(_one(records, 0x14)) == [sheet["fenID"]])
        relations, style = _placement(records, datasets, len(frame))
        options = {"Variables": columns, "Input": RAW, "Graph style": BARS, "Placement of groups": INTERLEAVED,
                   "Center": "Mean", "Interval": "SEM", INTERVAL_DIRECTION: UPPER_INTERVAL}
        row_titles = sheet["table"].get("rowTitlesDataSet")
        if row_titles is not None:
            options["Row titles"], = columns_by_id[_identifier(row_titles)]
        names = grouped_series_names(frame, options)
        _require(len(names) == len(ids))
        options[SERIES_PLACEMENT] = {name: STACK_PREVIOUS for name, relation in zip(names, relations, strict=True)
                                     if relation == 2}
        return frame, options, style
    except (AttributeError, KeyError, TypeError, ValueError, StructError, OverflowError):
        return None
