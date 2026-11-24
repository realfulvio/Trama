"""Grouping and locking of drawings without changing their order or appearance."""
from collections import defaultdict
from copy import deepcopy
from uuid import uuid4

import numpy as np

from .graph_shapes import on_axis_domain, validate_shape, validate_shapes
from .i18n import tr


def object_key(record):
    group = record.get("group")
    return ("group", group) if group is not None else ("shape", record["id"])


def selected_objects(records, selected_ids):
    """Expand selected IDs to complete objects, in drawing order."""
    selected = set(selected_ids)
    keys = {object_key(record) for record in records if record["id"] in selected}
    objects = defaultdict(list)
    for record in records:
        key = object_key(record)
        if key in keys:
            objects[key].append(record)
    return list(objects.values())


def is_locked(records):
    return any(record.get("locked", False) for record in records)


def edit_objects(records, selected_ids, action):
    """Apply one metadata edit to complete objects."""
    candidate = validate_shapes(records)
    objects = selected_objects(candidate, selected_ids)
    selected = [record for obj in objects for record in obj]
    if action == "group" and len(objects) >= 2 and not is_locked(selected):
        group = str(uuid4())
        for record in selected:
            record["group"] = group
    elif action == "ungroup" and selected and not is_locked(selected):
        for record in selected:
            record.pop("group", None)
    elif action in ("lock", "unlock") and selected:
        for record in selected:
            if action == "lock":
                record["locked"] = True
            else:
                record.pop("locked", None)
    else:
        raise ValueError(tr("shape.objects.selection"))
    return candidate


def duplicate_object(records):
    """Copy one complete object with distinct shape and group IDs, initially unlocked."""
    copies = deepcopy(records)
    group = str(uuid4()) if len(copies) > 1 else None
    for copy in copies:
        copy["id"] = str(uuid4())
        copy.pop("locked", None)
        copy.pop("group", None)
        if group is not None:
            copy["group"] = group
    return copies

def shape_transform(axes, record):
    return axes.transAxes if record["units"] == "axes" else axes.transData


def translated_shape(axes, record, offset):
    """Move by display pixels, preserving units and untouched coordinates."""
    if not np.any(offset):
        return record
    transform = shape_transform(axes, record)
    with np.errstate(over="ignore", invalid="ignore"):
        moved = np.asarray(transform.inverted().transform(transform.transform(record["points"]) + offset))
    for axis, delta in enumerate(offset):
        if delta == 0:
            moved[:, axis] = np.asarray(record["points"])[:, axis]
    if record["units"] == "axes":
        moved = np.where((moved >= -1e-12) & (moved <= 1 + 1e-12), np.clip(moved, 0, 1), moved)
    candidate = validate_shape({**record, "points": moved.tolist()})
    if not on_axis_domain(axes, candidate):
        raise ValueError(tr("shape.error.axis_domain"))
    return candidate
