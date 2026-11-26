"""Saved layout groups, locks and translations in fractions of the page."""

from dataclasses import dataclass, replace
from math import isfinite


@dataclass(frozen=True)
class PanelArrangement:
    offsets: tuple[tuple[int, float, float], ...] = ()
    groups: tuple[tuple[int, ...], ...] = ()
    locked: tuple[int, ...] = ()

    @property
    def empty(self):
        return not (self.offsets or self.groups or self.locked)

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
        return PanelArrangement(tuple(sorted(offsets)), tuple(sorted(group for group in groups if len(group) > 1)),
                                locked)


def validated_arrangement(value, count):
    if isinstance(value, PanelArrangement):
        value = {"offsets": value.offsets, "groups": value.groups, "locked": value.locked}
    if not isinstance(value, dict) or set(value) - {"offsets", "groups", "locked"}:
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
    return PanelArrangement(offsets, groups, indices(value.get("locked", ())))


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
