"""Literal text and optional arrows stored with a native graph's presentation.

An annotation keeps its text plain. Optional presentation fields change only how it is drawn: ``font`` (family),
``bold``, ``italic``, ``underline`` for the whole text and ``spans`` for subscript and superscript portions
(``analisi.text_markup``). The payload, the search and the copied text stay ``CO2`` and ``10-3``.
"""
from math import isfinite
from sys import float_info

from matplotlib.artist import Artist
from matplotlib.colors import is_color_like
from matplotlib.path import Path
from matplotlib.text import Text
from matplotlib.transforms import IdentityTransform

from .probability_scale import PROBABILITY_SCALES
from .text_markup import check_renders, displayed, validate_spans

ANNOTATIONS = "annotations"
UNITS = ("axes", "data")
ALIGNMENTS = ("left", "center", "right")
STYLE_FLAGS = ("bold", "italic", "underline")
MAX_FONT_NAME = 128


def _number(value):
    return type(value) in (int, float) and abs(value) <= float_info.max and isfinite(value)


def validate_annotation(record):
    required = {"text", "position", "units", "align", "size", "color"}
    optional = {"target", "font", *STYLE_FLAGS, "spans"}
    if not isinstance(record, dict) or required - record.keys() or record.keys() - (required | optional):
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
    font = record.get("font")
    if "font" in record and (not isinstance(font, str) or not font.strip() or len(font) > MAX_FONT_NAME
                             or any(ord(c) < 32 or 0xd800 <= ord(c) <= 0xdfff for c in font)):
        raise ValueError("Enter a valid text font.")
    if any(flag in record and type(record[flag]) is not bool for flag in STYLE_FLAGS):
        raise ValueError("Invalid text formatting.")
    if "spans" in record:
        spans = validate_spans(text, record["spans"])
        check_renders(text, spans, bold=record.get("bold", False), italic=record.get("italic", False))
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


class TextUnderline(Artist):
    """A line under each line of a text, drawn with it so PDF and SVG keep it a vector."""

    def __init__(self, text, color):
        super().__init__()
        self.text, self.color = text, color
        self.set_zorder(text.get_zorder())

    def _lines(self, renderer):
        """Per text line ``(left, right, y)`` in display pixels, just below its baseline."""
        text = self.text
        try:
            layout, info, _ = text._get_layout(renderer)
            window = Text.get_window_extent(text, renderer)
            dx, dy = window.x0 - layout.x0, window.y0 - layout.y0
            return [(x + dx, x + dx + width, y + dy) for _line, (width, _height, _descent), (x, y) in info]
        except (AttributeError, TypeError, ValueError):
            box = Text.get_window_extent(text, renderer)
            return [(box.x0, box.x1, box.y0)]

    def draw(self, renderer):
        if not self.get_visible() or not self.text.get_visible() or not self.text.get_text():
            return
        pixels = self.text.get_fontsize() * self.figure.dpi / 72
        gc = renderer.new_gc()
        gc.set_foreground(self.color)
        gc.set_linewidth(max(0.5, self.text.get_fontsize() / 16))
        self._set_gc_clip(gc)
        for left, right, baseline in self._lines(renderer):
            renderer.draw_path(gc, Path([(left, baseline - pixels * 0.12), (right, baseline - pixels * 0.12)]),
                               IdentityTransform())
        gc.restore()


def draw_annotations(axes, records):
    artists = []
    for record in records:
        if not on_axis_domain(axes, record):
            continue
        units = "axes fraction" if record["units"] == "axes" else "data"
        position, target = record["position"], record.get("target")
        color = record["color"]
        arrow = {"arrowstyle": "->", "color": color, "linewidth": 1.15} if target is not None else None
        bold, italic = record.get("bold", False), record.get("italic", False)
        spans = validate_spans(record["text"], record["spans"]) if record.get("spans") else []
        style = {}
        if "font" in record:
            style["fontfamily"] = record["font"]
        if bold:
            style["fontweight"] = "bold"
        if italic:
            style["fontstyle"] = "italic"
        artist = axes.annotate(displayed(record["text"], spans, bold=bold, italic=italic), xy=target or position,
                               xycoords=units, xytext=position, textcoords=units, arrowprops=arrow,
                               annotation_clip=True, fontsize=record["size"], color=color, ha=record["align"],
                               va="center", parse_math=bool(spans), clip_on=True, zorder=9, **style)
        artist.set_clip_path(axes.patch)
        if artist.arrow_patch is not None:
            artist.arrow_patch.set_clip_path(axes.patch)
        artists.append(artist)
        if record.get("underline"):
            line = TextUnderline(artist, color)
            axes.add_artist(line)
            line.set_clip_path(axes.patch)
            artists.append(line)
    return artists
