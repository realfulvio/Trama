"""Reuse saved K-means partitions and Gap results while their input still matches."""

from hashlib import sha256
import json
import math

import numpy as np
import pandas as pd

from . import kmeans_options as selection
from .kmeans_reports import CENTROIDS
from .stats import Clusters, _cluster_data

ARCHIVE = "Imported K-means partitions"


def _signature(frame, options, data):
    columns = options["Variables"]
    values = data.to_numpy(dtype="<f8", copy=True)
    if len(data) != len(frame) or not 2 <= len(data) <= 3000 or not np.isfinite(values).all():
        return None
    # The reference data and fits are independent of the plotted reports and the
    # vote shown in the selection sheet.
    values[values == 0] = 0.0
    fit = selection.fit_options(selection.SELECTION, frame, options)
    settings = (columns, values.shape, selection.scale(options), options.get("Minimum k", 1),
                options["Maximum k"], options["Seed"], options.get("Gap simulations", 20),
                options.get(selection.GAP_REFERENCE, selection.GAP_VARIABLE_RANGES), sorted(fit.items()))
    digest = sha256(json.dumps(settings, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    digest.update(values.tobytes(order="C"))
    return digest.hexdigest()


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _iterations(value):
    return value if type(value) is int and 0 <= value <= 1000 else None


def _identical_rows(data):
    _, keys = np.unique(data.to_numpy(dtype=float), axis=0, return_inverse=True)
    ordered = np.argsort(keys)
    repeated = np.diff(keys[ordered]) == 0
    return ordered[:-1][repeated], ordered[1:][repeated]


def _fit(data, values, count, groups, repeated):
    if not isinstance(groups, list) or len(groups) != len(data):
        return None
    if any(type(group) is not int or not 1 <= group <= count for group in groups):
        return None
    labels = np.asarray(groups)
    # Identical selected measurements are indistinguishable after a row reorder.
    if len(set(groups)) != count or np.any(labels[repeated[0]] != labels[repeated[1]]):
        return None
    centers = np.vstack([values[labels == group].mean(axis=0) for group in range(1, count + 1)])
    distances = np.linalg.norm(values - centers[labels - 1], axis=1)
    fit = Clusters(data, pd.Series(labels, index=data.index),
                   centers=pd.DataFrame(centers, columns=data.columns),
                   inertia=float(distances @ distances))
    return fit, distances


def _consistent(fit, saved_wss, gap, se, observed, expected):
    return (all(_number(item) for item in (saved_wss, gap, se, observed, expected)) and saved_wss > 0 and se >= 0
            and math.isclose(fit.inertia, saved_wss, rel_tol=1e-10)
            and math.isclose(math.log(saved_wss), observed, rel_tol=1e-10, abs_tol=1e-10)
            and math.isclose(expected - observed, gap, rel_tol=1e-10, abs_tol=1e-10))


def _archived_row(model, data, values, count, repeated):
    clusters = model.get("clusters")
    if model.get("status") != "VALID" or not isinstance(clusters, list) or len(clusters) != count:
        return None
    memberships, saved_distances = [0] * len(data), [0.0] * len(data)
    for group, cluster in enumerate(clusters, 1):
        points = cluster.get("points")
        if not isinstance(points, list) or not 1 <= len(points) <= len(data):
            return None
        for point in points:
            row, distance = point.get("id"), point.get("distance")
            if (type(row) is not int or not 0 <= row < len(data) or memberships[row]
                    or not _number(distance) or distance < 0):
                return None
            memberships[row], saved_distances[row] = group, distance
    found = _fit(data, values, count, memberships, repeated)
    if found is None:
        return None
    fit, distances = found
    gap = model["gap"]
    values_to_keep = [model.get("wcss"), gap.get("statistic"), gap.get("sd"),
                      gap.get("logWObserved"), gap.get("logWExpected")]
    if (not _consistent(fit, *values_to_keep)
            or not np.allclose(distances, saved_distances, rtol=1e-10, atol=1e-12)):
        return None
    record = {"groups": memberships, "metrics": values_to_keep}
    if (iterations := _iterations(model.get("iterationCount"))) is not None:
        record["iterations"] = iterations
    return record


def restore(frame, options, results):
    """Follow the record's row IDs only when the complete-case data and distances agree."""
    if options.get(CENTROIDS):
        return None
    try:
        content = results["content"]
        summary = content["dataSummary"]
        columns = options["Variables"]
        if (content["status"]["error"] != "VALID" or summary["rowsTotal"] != len(frame)
                or summary["rowsSkipped"] != 0 or summary["rowsAnalyzed"] != len(frame)
                or summary["variablesCount"] != len(columns) or frame.attrs.get("excluded")):
            return None
        models = content["models"]
        low, high = options.get("Minimum k", 1), options["Maximum k"]
        if set(models) != {str(count) for count in range(low, high + 1)}:
            return None
        data, values = _cluster_data(frame, columns, 1, selection.scale(options))
        source = _signature(frame, options, data)
        if source is None:
            return None
        repeated = _identical_rows(data)
        rows = [_archived_row(models[str(count)], data, values, count, repeated)
                for count in range(low, high + 1)]
        return {"source": source, "models": rows} if all(row is not None for row in rows) else None
    except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
        return None


def matching(frame, options, data, values, candidates, retain_initial):
    """Return live result tables when the saved records bind to the exact worksheet."""
    saved = options.get(ARCHIVE)
    if not isinstance(saved, dict) or retain_initial:
        return None
    models = saved.get("models")
    if not isinstance(models, list) or len(models) != len(candidates):
        return None
    source = _signature(frame, options, data)
    if source is None or source != saved.get("source"):
        return None
    repeated = _identical_rows(data)
    fits, gaps = {}, {}
    for count, model in zip(candidates, models, strict=True):
        if not isinstance(model, dict):
            return None
        found = _fit(data, values, count, model.get("groups"), repeated)
        metrics = model.get("metrics")
        if found is None or not isinstance(metrics, list) or len(metrics) != 5:
            return None
        fit, _ = found
        if not _consistent(fit, *metrics):
            return None
        fit.iterations = _iterations(model.get("iterations"))
        fits[count] = fit
        gaps[count] = metrics[1:3]
    return fits, gaps
