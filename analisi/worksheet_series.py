"""Resolve selected worksheet columns into ordered series."""
from .category_graphs import _title
from .data import _worksheet_roles


def series_columns(frame, names, *, recognize_replicates):
    roles = _worksheet_roles(frame)
    if roles:
        chosen = set(names)
        groups = [[name for name in group if name in chosen] for group in roles["y"]]
        used = {name for group in groups for name in group}
        return [group for group in groups if group] + [[name] for name in names if name not in used]
    if not recognize_replicates:
        return [[name] for name in names]
    groups = {}
    for name in names:
        groups.setdefault(_title(name), []).append(name)
    return list(groups.values())


def series_labels(groups):
    labels = []
    for group in groups:
        candidate = _title(group[0]) if len(group) > 1 else group[0]
        if candidate in labels:
            candidate = group[0]
        while candidate in labels:
            candidate += " (series)"
        labels.append(candidate)
    return labels
