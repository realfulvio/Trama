"""Drawing order for native XY series, separate from the recipe and legend."""

from itertools import chain

from matplotlib.container import BarContainer

from .data import XY_SERIES_ORDER
from .point_style import POINT_DEPTH_OFFSET
from .xy_series import X_ERROR_ARTISTS

MAX_ORDERED_SERIES = 256
_ORIGINAL_DEPTH = "_tramastat_series_original_depth"


def validate_xy_order(order):
    if (not isinstance(order, list) or len(order) > MAX_ORDERED_SERIES
            or any(not isinstance(key, str) or not key.startswith("xy:1:") or not 5 < len(key) <= 1024
                   for key in order)
            or len(set(order)) != len(order)):
        raise ValueError("Invalid XY series drawing order.")


def _parts(artist):
    data = artist.patches if isinstance(artist, BarContainer) else (artist,)
    return chain(data, getattr(artist, X_ERROR_ARTISTS, ()))


def xy_layer_groups(figure, series, order=()):
    """Return each axes' independently drawable series from back to front."""
    ranks = {key: rank for rank, key in enumerate(order)}
    by_axes = {}
    for item in series:
        if item.kind != "xy" or (artist := next(_parts(item.artist), None)) is None:
            continue
        by_axes.setdefault(artist.axes, []).append((item, artist))
    groups = []
    for axes in figure.axes:
        if not (items := by_axes.get(axes)):
            continue
        items.sort(key=lambda pair: (ranks.get(pair[0].key, len(ranks)),
                                     getattr(pair[1], _ORIGINAL_DEPTH, pair[1].get_zorder())))
        groups.append((axes, tuple(item for item, _ in items)))
    return groups


def _layers_keys(groups):
    return [item.key for _, group in groups for item in group]


def xy_order_record(figure, series, previous, requested):
    """Keep earlier locations for temporarily absent series when editing the available ones."""
    current = _layers_keys(xy_layer_groups(figure, series, previous))
    if requested == current:
        return list(previous)
    if requested == _layers_keys(xy_layer_groups(figure, series)) and set(previous) <= set(current):
        return []
    shown = set(current)
    next_key = iter(requested)
    return [next(next_key) if key in shown else key for key in previous] + list(next_key)


def apply_xy_layers(figure, series, order):
    for item in series:
        if item.kind != "xy":
            continue
        if hasattr(item.artist, POINT_DEPTH_OFFSET):
            delattr(item.artist, POINT_DEPTH_OFFSET)
        for artist in _parts(item.artist):
            if hasattr(artist, _ORIGINAL_DEPTH):
                artist.set_zorder(getattr(artist, _ORIGINAL_DEPTH))
                delattr(artist, _ORIGINAL_DEPTH)
    if not order:
        return
    defaults = dict(xy_layer_groups(figure, series))
    for axes, group in xy_layer_groups(figure, series, order):
        if group == defaults[axes]:
            continue
        # Keep the data band between drawings below the series and reference lines above them.
        step = 0.7 / len(group)
        for index, item in enumerate(group):
            for artist in _parts(item.artist):
                setattr(artist, _ORIGINAL_DEPTH, artist.get_zorder())
                artist.set_zorder(1.2 + step * index)
            setattr(item.artist, POINT_DEPTH_OFFSET, step / 2)
