"""Portable snapshots of confirmed analysis tables and their figure."""
from base64 import b64decode, b64encode
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from io import BytesIO
import json
from math import isfinite

import numpy as np
import pandas as pd
from matplotlib.figure import Figure

from analisi.legacy_pdf_preview import pdf_dimensions, render_pdf
from analisi.reporting import Result


MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
_TYPE = "$type"
MAX_ELEMENTS = 2_000_000
_NUMPY_DTYPES = {"bool", "float32", "float64", *(f"{prefix}int{bits}" for prefix in ("", "u")
                                               for bits in (8, 16, 32, 64))}
_SERIES_DTYPES = _NUMPY_DTYPES | {"object", "string", "str", "boolean", "Float32", "Float64", "category",
                                  *(f"{prefix}Int{bits}" for prefix in ("", "U") for bits in (8, 16, 32, 64)),
                                  "datetime64[ns]", "datetime64[us]", "timedelta64[ns]", "timedelta64[us]"}


def _context_types():
    from analisi.hierarchical_workbench import AssignmentCoordinates, _HierarchyView, _Tree
    from analisi.kmeans_reports import ModelPlotData
    from analisi.survival_plot import SurvivalGraphData

    return {cls.__name__: cls for cls in (AssignmentCoordinates, _HierarchyView, _Tree,
                                         ModelPlotData, SurvivalGraphData)}


def _encode(value, contexts):
    if value is pd.NA or value is pd.NaT:
        return {_TYPE: "missing"}
    if isinstance(value, np.generic):
        return _encode(value.item(), contexts)
    if isinstance(value, pd.DataFrame):
        if value.size > MAX_ELEMENTS:
            raise ValueError("A frozen table can hold up to two million cells.")
        return {_TYPE: "frame", "index": _encode(value.index, contexts),
                "columns": _encode(value.columns, contexts), "dtypes": [str(dtype) for dtype in value.dtypes],
                "rows": [[_encode(cell, contexts) for cell in row]
                         for row in value.itertuples(index=False, name=None)]}
    if isinstance(value, pd.Series):
        return {_TYPE: "series", "index": _encode(value.index, contexts), "name": _encode(value.name, contexts),
                "dtype": str(value.dtype), "values": _encode(value.tolist(), contexts)}
    if isinstance(value, pd.RangeIndex):
        return {_TYPE: "range", "values": [value.start, value.stop, value.step, _encode(value.name, contexts)]}
    if isinstance(value, pd.MultiIndex):
        return {_TYPE: "multi_index", "names": _encode(list(value.names), contexts),
                "values": _encode(value.tolist(), contexts)}
    if isinstance(value, pd.Index):
        return {_TYPE: "index", "name": _encode(value.name, contexts), "values": _encode(value.tolist(), contexts)}
    if isinstance(value, (pd.Timestamp, datetime)):
        return {_TYPE: "timestamp", "value": value.isoformat()}
    if isinstance(value, date):
        return {_TYPE: "date", "value": value.isoformat()}
    if isinstance(value, pd.Timedelta):
        return {_TYPE: "timedelta", "value": str(value)}
    if isinstance(value, np.ndarray):
        return {_TYPE: "array", "shape": list(value.shape), "dtype": str(value.dtype),
                "values": _encode(value.ravel().tolist(), contexts)}
    if type(value) is float and not isfinite(value):
        return {_TYPE: "float", "value": str(value)}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, tuple):
        return {_TYPE: "tuple", "values": [_encode(item, contexts) for item in value]}
    if isinstance(value, list):
        return [_encode(item, contexts) for item in value]
    if isinstance(value, dict):
        return {_TYPE: "mapping", "values": [[_encode(key, contexts), _encode(item, contexts)]
                                               for key, item in value.items()]}
    if is_dataclass(value) and type(value) in contexts.values():
        return {_TYPE: "context", "name": type(value).__name__,
                "values": {field.name: _encode(getattr(value, field.name), contexts) for field in fields(value)}}
    raise ValueError(f"Cannot freeze a result containing {type(value).__name__}.")


def _series(values, dtype, **kwargs):
    # Keep integer, float, nullable and text columns without coercing mixed object columns.
    if dtype not in _SERIES_DTYPES or len(values) != len(kwargs["index"]):
        dtype = object
    return pd.Series(values, dtype=dtype, **kwargs)


def _decode(record, contexts):
    if isinstance(record, list):
        return [_decode(item, contexts) for item in record]
    if not isinstance(record, dict):
        return record
    kind = record[_TYPE]
    def field(name):
        return _decode(record[name], contexts)
    if kind == "missing":
        return pd.NA
    if kind == "float":
        return float(record["value"])
    if kind == "timestamp":
        return pd.Timestamp(record["value"])
    if kind == "date":
        return date.fromisoformat(record["value"])
    if kind == "timedelta":
        return pd.Timedelta(record["value"])
    if kind == "tuple":
        return tuple(field("values"))
    if kind == "mapping":
        return {_decode(key, contexts): _decode(value, contexts) for key, value in record["values"]}
    if kind == "range":
        start, stop, step, name = field("values")
        index = pd.RangeIndex(start, stop, step, name=name)
        if len(index) > MAX_ELEMENTS:
            raise ValueError("A frozen table can hold up to two million rows.")
        return index
    if kind == "index":
        return pd.Index(field("values"), name=field("name"), tupleize_cols=False)
    if kind == "multi_index":
        return pd.MultiIndex.from_tuples(field("values"), names=field("names"))
    if kind == "array":
        dtype, shape = record["dtype"], record["shape"]
        values = field("values")
        if dtype not in _NUMPY_DTYPES or not isinstance(values, list) or len(values) > MAX_ELEMENTS:
            raise ValueError("Invalid frozen result array.")
        if not isinstance(shape, list) or not all(type(side) is int and 0 <= side <= MAX_ELEMENTS for side in shape):
            raise ValueError("Invalid frozen result array dimensions.")
        return np.asarray(values, dtype=dtype).reshape(shape)
    if kind == "series":
        return _series(field("values"), record["dtype"], index=field("index"), name=field("name"))
    if kind == "frame":
        index, columns, rows = field("index"), field("columns"), field("rows")
        if (len(rows) != len(index) or len(record["dtypes"]) != len(columns)
                or len(rows) * len(columns) > MAX_ELEMENTS):
            raise ValueError("Invalid frozen result table.")
        result = pd.DataFrame({position: _series([row[position] for row in rows], dtype, index=index)
                               for position, dtype in enumerate(record["dtypes"])}, index=index)
        result.columns = columns
        return result
    if kind == "context":
        return contexts[record["name"]](**{name: _decode(value, contexts)
                                            for name, value in record["values"].items()})
    raise ValueError("Invalid frozen analysis value.")


def capture(result):
    contexts = _context_types()
    snapshot = {"tables": _encode(result.tables, contexts), "contexts": _encode(result.table_contexts, contexts)}
    if result.figure is not None:
        buffer = BytesIO()
        result.figure.savefig(buffer, format="pdf")
        snapshot["pdf"] = b64encode(buffer.getbuffer()).decode("ascii")
    size = len(json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode("utf-8"))
    return snapshot, size


def restore(snapshot):
    try:
        contexts = _context_types()
        tables = _decode(snapshot["tables"], contexts)
        sources = _decode(snapshot["contexts"], contexts)
        if not isinstance(tables, dict) or not all(isinstance(frame, pd.DataFrame) for frame in tables.values()):
            raise ValueError("Invalid frozen result tables.")
        if not isinstance(sources, dict):
            raise ValueError("Invalid frozen result context.")
        figure = None
        if data := snapshot.get("pdf"):
            pdf = b64decode(data, validate=True)
            width, height = pdf_dimensions(pdf)
            image = render_pdf(pdf, 1800)
            figure = Figure(figsize=(width / 72, height / 72))
            axes = figure.add_axes((0, 0, 1, 1))
            axes.imshow(image)
            axes.set_axis_off()
            figure._trama_frozen_pdf = pdf
        return Result(tables, figure, table_contexts=sources)
    except (KeyError, TypeError, IndexError, OverflowError) as error:
        raise ValueError("Invalid saved frozen analysis.") from error
