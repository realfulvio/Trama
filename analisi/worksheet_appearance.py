"""Presentation settings shared by the Tk and Qt worksheets."""
import re

from .i18n import load_preferences, save_preferences

ZOOM_LEVELS = (60, 75, 90, 100, 110, 125, 150, 175, 200)
MIN_FONT_SIZE = 8
MAX_FONT_SIZE = 24
MIN_ROW_HEIGHT = 18
MAX_ROW_HEIGHT = 480


def font_preference(path):
    value = load_preferences(path).get("worksheet_font")
    if isinstance(value, dict):
        family, size = value.get("family"), value.get("size")
        if isinstance(family, str) and len(family) <= 128 and (size is None or type(size) is int and MIN_FONT_SIZE <= size <= MAX_FONT_SIZE):
            return family, size
    return "", None


def save_font_preference(path, family, size):
    save_preferences(path, worksheet_font={"family": family, "size": size} if family or size is not None else None)


def zoom_step(current, step):
    if not step:
        return 100
    index = ZOOM_LEVELS.index(current)
    return ZOOM_LEVELS[max(0, min(len(ZOOM_LEVELS) - 1, index + step))]


def text_on_background(color):
    channels = [int(color[start:start + 2], 16) / 255 for start in (1, 3, 5)]
    linear = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in channels]
    luminance = sum(weight * value for weight, value in zip((.2126, .7152, .0722), linear))
    return "#ffffff" if luminance < .179 else "#000000"


def _color(value):
    if not isinstance(value, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("Invalid cell background color.")
    return value.lower()


def paint_cells(current, box, shape, color, names=None):
    if color is not None:
        color = _color(color)
    rows, columns = shape
    top, left, bottom, right = box
    new = current.copy()
    if color is None:
        positions = dict(zip(names, range(columns))) if names is not None else None
        for row, column in current:
            position = positions[column] if positions is not None else column
            if top <= row <= bottom and left <= position <= right:
                del new[row, column]
    else:
        for row in range(max(0, top), min(rows, bottom + 1)):
            for position in range(max(0, left), min(columns, right + 1)):
                new[row, names[position] if names is not None else position] = color
    return current if new == current else new


def background_records(backgrounds):
    return [[row, column, color] for (row, column), color in sorted(backgrounds.items())]


def read_backgrounds(records, row_limit, columns):
    if not isinstance(records, list) or len(records) > row_limit * len(columns):
        raise ValueError("Invalid saved cell backgrounds.")
    backgrounds = {}
    for entry in records:
        if not isinstance(entry, list) or len(entry) != 3:
            raise ValueError("Invalid saved cell background.")
        row, column, color = entry
        column_type = int if isinstance(columns, range) else str
        if type(row) is not int or not 0 <= row < row_limit or type(column) is not column_type or column not in columns:
            raise ValueError("Cell background references an unknown cell.")
        if (row, column) in backgrounds:
            raise ValueError("Duplicate saved cell background.")
        backgrounds[row, column] = _color(color)
    return backgrounds


def assign_row_heights(current, rows, height, row_limit):
    """Return a new {row: base_height_px} mapping with custom heights set or reset to automatic (None)."""
    if height is not None and (type(height) is not int or not MIN_ROW_HEIGHT <= height <= MAX_ROW_HEIGHT):
        raise ValueError(f"Row height must be an integer between {MIN_ROW_HEIGHT} and {MAX_ROW_HEIGHT}.")
    new = current.copy()
    for row in rows:
        if type(row) is not int or not 0 <= row < row_limit:
            raise ValueError("Row height references an unknown row.")
        if height is None:
            new.pop(row, None)
        else:
            new[row] = height
    return current if new == current else new


def row_height_records(heights):
    return [[row, height] for row, height in sorted(heights.items())]


def read_row_heights(records, row_limit):
    """Validate persisted [row, height] pairs against the table row count."""
    if not isinstance(records, list) or len(records) > row_limit:
        raise ValueError("Invalid saved row heights.")
    heights = {}
    for entry in records:
        if not isinstance(entry, list) or len(entry) != 2:
            raise ValueError("Invalid saved row height.")
        row, height = entry
        if type(row) is not int or not 0 <= row < row_limit:
            raise ValueError("Row height references an unknown row.")
        if type(height) is not int or not MIN_ROW_HEIGHT <= height <= MAX_ROW_HEIGHT:
            raise ValueError("Invalid saved row height.")
        if row in heights:
            raise ValueError("Duplicate saved row height.")
        heights[row] = height
    return heights
