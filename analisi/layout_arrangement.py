"""Saved layout positions, scale, stacking, groups and locks."""

from dataclasses import dataclass, replace
from math import isfinite


@dataclass(frozen=True)
class PanelArrangement:
    offsets: tuple[tuple[int, float, float], ...] = ()
    groups: tuple[tuple[int, ...], ...] = ()
    locked: tuple[int, ...] = ()
    scales: tuple[tuple[int, float], ...] = ()
    layers: tuple[int, ...] = ()  # Panel indices from the back to the front.

    def record(self):
        return {key: value for key, value in vars(self).items() if value}

    def paint_order(self, count):
        return self.layers or tuple(range(count))

    def objects(self, selected):
        selected = set(selected)
        groups = [group for group in self.groups if selected.intersection(group)]
        for group in groups:
            selected.difference_update(group)
        return sorted([*groups, *((index,) for index in selected)])

    def remap(self, indices):
        """Keep the geometry and grouping of surviving panels when their order changes."""
        mapping = {old: new for new, old in enumerate(indices) if old is not None}
        offsets = [(mapping[index], x, y) for index, x, y in self.offsets if index in mapping]
        groups = [tuple(sorted(mapping[index] for index in group if index in mapping)) for group in self.groups]
        locked = tuple(sorted(mapping[index] for index in self.locked if index in mapping))
        scales = tuple(sorted((mapping[index], scale) for index, scale in self.scales if index in mapping))
        layers = tuple(mapping[index] for index in self.layers if index in mapping)
        if self.layers:
            layers += tuple(index for index, old in enumerate(indices) if old is None)
        if layers == tuple(range(len(indices))):
            layers = ()
        return PanelArrangement(tuple(sorted(offsets)), tuple(sorted(group for group in groups if len(group) > 1)),
                                locked, scales, layers)


def validated_arrangement(value, count):
    if isinstance(value, PanelArrangement):
        value = value.record()
    if not isinstance(value, dict) or set(value) - {"offsets", "groups", "locked", "scales", "layers"}:
        raise ValueError("Invalid layout panel arrangement.")

    def sequence(raw, limit):
        if not isinstance(raw, (tuple, list)) or len(raw) > limit:
            raise ValueError("Invalid layout panel arrangement.")
        return raw

    def indices(raw):
        values = sequence(raw, count)
        if any(type(index) is not int or not 0 <= index < count for index in values):
            raise ValueError("Invalid layout panel index.")
        if len(set(values)) != len(values):
            raise ValueError("Repeated layout panel index.")
        return tuple(sorted(values))

    entries = [sequence(entry, 3) for entry in sequence(value.get("offsets", ()), count)]
    if any(len(entry) != 3 for entry in entries):
        raise ValueError("Invalid layout panel position.")
    indices([entry[0] for entry in entries])
    if any(type(delta) not in (int, float) or abs(delta) > 2 or not isfinite(delta)
           for _, x, y in entries for delta in (x, y)):
        raise ValueError("Invalid layout panel position.")
    offsets = tuple(sorted((index, float(x), float(y)) for index, x, y in entries if x or y))
    groups = tuple(sorted(indices(group) for group in sequence(value.get("groups", ()), count)))
    indices([index for group in groups for index in group])
    if any(len(group) < 2 for group in groups):
        raise ValueError("A layout group needs at least two panels.")
    entries = [sequence(entry, 2) for entry in sequence(value.get("scales", ()), count)]
    if any(len(entry) != 2 for entry in entries):
        raise ValueError("Invalid layout panel scale.")
    indices([entry[0] for entry in entries])
    if any(type(scale) not in (int, float) or not .01 <= scale <= 100 for _, scale in entries):
        raise ValueError("Invalid layout panel scale.")
    scales = tuple(sorted((index, float(scale)) for index, scale in entries if scale != 1))
    layers = tuple(sequence(value.get("layers", ()), count))
    if layers and indices(layers) != tuple(range(count)):
        raise ValueError("Invalid layout panel stacking order.")
    if layers == tuple(range(count)):
        layers = ()
    return PanelArrangement(offsets, groups, indices(value.get("locked", ())), scales, layers)


def change_objects(arrangement, objects, command):
    selected = {index for members in objects for index in members}
    remaining = tuple(group for group in arrangement.groups if not selected.intersection(group))
    if command == "group":
        return replace(arrangement, groups=tuple(sorted((*remaining, tuple(sorted(selected))))))
    if command == "ungroup":
        return replace(arrangement, groups=remaining)
    locked = set(arrangement.locked)
    if command == "lock":
        locked.update(selected)
    else:
        locked.difference_update(selected)
    return replace(arrangement, locked=tuple(sorted(locked)))


def translated(arrangement, shifts, page):
    """Apply inch translations to the saved positions, retaining precision through round trips."""
    width, height = page
    offsets = {index: (x, y) for index, x, y in arrangement.offsets}
    for index, (dx, dy) in shifts.items():
        x, y = offsets.get(index, (0., 0.))
        x, y = round(float(x + dx / width), 12), round(float(y + dy / height), 12)
        if x or y:
            offsets[index] = (x, y)
        else:
            offsets.pop(index, None)
    return replace(arrangement, offsets=tuple((index, *offsets[index]) for index in sorted(offsets)))


def layered(arrangement, selected, count, *, front):
    """Move the selection together while retaining relative order within both sets."""
    selected = set(selected)
    order = arrangement.paint_order(count)
    picked = tuple(index for index in order if index in selected)
    other = tuple(index for index in order if index not in selected)
    layers = other + picked if front else picked + other
    return replace(arrangement, layers=() if layers == tuple(range(count)) else layers)


def positioned(arrangement, panels, targets, page):
    """Set page coordinates and the actual drawing scale for the specified panels."""
    scales = dict(arrangement.scales)
    shifts = {}
    for index, (x, y, scale) in targets.items():
        old_x, old_y, old_scale = panels[index].box
        if not isfinite(scale) or scale <= 0:
            raise ValueError("Invalid layout panel scale.")
        shifts[index] = (x - old_x, y - old_y)
        factor = round(float(scales.get(index, 1.) * scale / old_scale), 12)
        if factor == 1:
            scales.pop(index, None)
        else:
            scales[index] = factor
    return replace(translated(arrangement, shifts, page), scales=tuple(sorted(scales.items())))
