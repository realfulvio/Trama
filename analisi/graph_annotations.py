"""Literal text and optional arrows stored with a native graph's presentation."""
from math import isfinite
from sys import float_info

from matplotlib.colors import is_color_like

from .probability_scale import PROBABILITY_SCALES

ANNOTATIONS = "annotations"
UNITS = ("axes", "data")
ALIGNMENTS = ("left", "center", "right")


def _number(value):
    return type(value) in (int, float) and abs(value) <= float_info.max and isfinite(value)


def validate_annotation(record):
    required = {"text", "position", "units", "align", "size", "color"}
    if not isinstance(record, dict) or required - record.keys() or record.keys() - (required | {"target"}):
        raise ValueError("Invalid graph annotation.")
    text = record["text"]
    if (not isinstance(text, str) or not text.strip() or len(text) > 500
            or any((ord(c) < 32 and c not in "\r\n\t") or 0xd800 <= ord(c) <= 0xdfff for c in text)):
        raise ValueError("Enter annotation text between 1 and 500 characters.")
    if record["units"] not in UNITS or record["align"] not in ALIGNMENTS:
        raise ValueError("Choose annotation coordinates and alignment.")
    for field in ("position", "target"):
        if field not in record:
            continue
        coordinates = record[field]
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2 or not all(map(_number, coordinates)):
            raise ValueError("Enter finite X and Y coordinates.")
        if record["units"] == "axes" and not all(0 <= value <= 1 for value in coordinates):
            raise ValueError("Plot fractions must be between 0 and 1.")
    if not _number(record["size"]) or not 4 <= record["size"] <= 72:
        raise ValueError("Enter a text size between 4 and 72 points.")
    color = record["color"]
    if not isinstance(color, str) or len(color) > 40 or not is_color_like(color):
        raise ValueError("Enter a valid text color.")
    return record


def validate_annotations(records):
    if not isinstance(records, list):
        raise ValueError("Invalid graph annotations.")
    for record in records:
        validate_annotation(record)


def on_axis_domain(axes, record):
    if record["units"] == "axes":
        return True
    points = (record["position"], record.get("target", record["position"]))
    for index, scale in enumerate((axes.get_xscale(), axes.get_yscale())):
        coordinates = [point[index] for point in points]
        if scale == "log" and any(value <= 0 for value in coordinates):
            return False
        if scale in PROBABILITY_SCALES and any(not 0 < value < PROBABILITY_SCALES[scale] for value in coordinates):
            return False
    return True


def draw_annotations(axes, records):
    artists = []
    for record in records:
        if not on_axis_domain(axes, record):
            continue
        units = "axes fraction" if record["units"] == "axes" else "data"
        position, target = record["position"], record.get("target")
        color = record["color"]
        arrow = {"arrowstyle": "->", "color": color, "linewidth": 1.15} if target is not None else None
        artist = axes.annotate(record["text"], xy=target or position, xycoords=units,
                               xytext=position, textcoords=units, arrowprops=arrow, annotation_clip=True,
                               fontsize=record["size"], color=color, ha=record["align"], va="center",
                               parse_math=False, clip_on=True, zorder=9)
        artist.set_clip_path(axes.patch)
        if artist.arrow_patch is not None:
            artist.arrow_patch.set_clip_path(axes.patch)
        artists.append(artist)
    return artists
