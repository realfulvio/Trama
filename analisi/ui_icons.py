"""Shared Classica vector icons, rasterised with Pillow at the requested size.

The 16 px grid uses rounded strokes and a teal accent to emphasise the action or data. Each
icon is a list of ``(kind, geometry,
classes)`` items: ``P`` is an SVG path (M L H V C A Z, absolute and relative), ``C`` a circle
(cx, cy, r). Classes: ``a`` accent stroke, ``af`` translucent accent fill, ``f`` ink fill, ``k`` knock-out
fill in the background colour.
"""
from math import atan2, cos, pi, radians, sin, sqrt
import re

from PIL import Image, ImageDraw

ICONS = {
    "new": [('P', 'M9 14H4a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 4 2h5l3 3v2M9 2v3h3', ''),
            ('P', 'M11.5 8.5v6M8.5 11.5h6', 'a')],
    "open": [('P', 'M2 12.5V4a1 1 0 0 1 1-1h3l1.5 2H12a1 1 0 0 1 1 1v1', ''),
             ('P', 'M2 12.5 4 7h10.5l-2 6H2z', 'af')],
    "save": [('P', 'M3.5 2h7L14 5.5v7a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12.5v-9A1.5 1.5 0 0 1 3.5 2zM5 2v3.5h5V2', ''),
             ('P', 'M5 14V9h6v5', 'a')],
    "saveas": [('P', 'M14 7V5.5L10.5 2h-7A1.5 1.5 0 0 0 2 3.5v9A1.5 1.5 0 0 0 3.5 14H7M5 2v3.5h5V2M5 14v-4h3', ''),
               ('P', 'M9.5 14.5l.5-2.5 3.8-3.8 1.5 1.5-3.8 3.8z', 'a')],
    "addrow": [('P', 'M2 2.5h12v6H2zM2 5.5h12M8 2.5v6', ''), ('P', 'M8 10v5M5.5 12.5h5', 'a')],
    "addcol": [('P', 'M2.5 2v12h6V2zM5.5 2v12M2.5 8h6', ''), ('P', 'M10 8h5M12.5 5.5v5', 'a')],
    "info": [('C', (8.0, 8.0, 5.7), ''), ('P', 'M8 7.4v3.6', ''), ('C', (8.0, 5.1, 0.8), 'f')],
    "exclude": [('C', (8.0, 8.0, 5.7), ''), ('P', 'M4 12l8-8', 'a')],
    "formula": [('P', 'M9.6 2.9c-1.5-.5-2.5.2-2.8 1.8L5.6 11c-.3 1.6-1.2 2.3-2.6 1.9M4.4 6.5h4.2', ''), ('P', 'M10.4 9.2l3.6 4M14 9.2l-3.6 4', 'a')],
    "undo": [('P', 'M2.5 6h7a3.5 3.5 0 0 1 0 7H7', ''), ('P', 'M6 2.5 2.5 6 6 9.5', '')],
    "redo": [('P', 'M13.5 6h-7a3.5 3.5 0 0 0 0 7H9', ''), ('P', 'M10 2.5 13.5 6 10 9.5', '')],
    "cut": [('C', (4.6, 11.8, 1.9), ''), ('C', (11.4, 11.8, 1.9), ''), ('P', 'M5.8 10.3L12 2.2M10.2 10.3L4 2.2', '')],
    "copy": [('P', 'M2 10V3.5A1.5 1.5 0 0 1 3.5 2H10', ''),
             ('P', 'M6.5 5H13a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H6.5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z', '')],
    "paste": [('P', 'M5.5 3.5H4A1.5 1.5 0 0 0 2.5 5v8A1.5 1.5 0 0 0 4 14.5h8A1.5 1.5 0 0 0 13.5 13V5A1.5 1.5 0 0 0 12 3.5h-1.5M5.5 2h5v3h-5z', ''),
              ('P', 'M5.5 8.5h5M5.5 11h4', 'a')],
    "pastespecial": [('P', 'M5 3.5H3.5A1.5 1.5 0 0 0 2 5v8A1.5 1.5 0 0 0 3.5 14.5H7M10 3.5h1.5A1.5 1.5 0 0 1 13 5v2M5 2h5v3H5z', ''),
                     ('P', 'M12 8.5v6M9 11.5h6M10.2 9.7l3.6 3.6M13.8 9.7l-3.6 3.6', 'a')],
    "pastetable": [('P', 'M5 3.5H3.5A1.5 1.5 0 0 0 2 5v8A1.5 1.5 0 0 0 3.5 14.5h2M10 3.5h1.5A1.5 1.5 0 0 1 13 5v1M5 2h5v3H5z', ''),
                   ('P', 'M8.5 8.5h6v6h-6zM8.5 11.5h6M11.5 8.5v6', 'a')],
    "linreg": [('P', 'M2 2v12h12', ''), ('P', 'M5 11.5l9-8', 'a'),
               ('C', (6.0, 8.0, 0.9), 'f'), ('C', (9.5, 9.7, 0.9), 'f'), ('C', (11.5, 3.5, 0.9), 'f')],
    "curve": [('P', 'M2 2v12h12', ''), ('P', 'M4.5 11.5C9.5 11.5 7.5 4.5 14 4.5', 'a')],
    "bars": [('P', 'M2 14h12M5 11.5V9M8 11.5v-7M11 11.5v-4', ''),
             ('P', 'M8 6V3.5', 'a')],
    "analyze": [('P', 'M12.5 3H4l4.5 5L4 13h8.5', '')],
    "heatmap": [('P', 'M2.5 2.5h3.700v3.700h-3.700zM6.200 6.200h3.600v3.600h-3.600zM9.800 9.800h3.700v3.700h-3.700z', 'af'), ('P', 'M2.5 2.5h11v11h-11zM6.200 2.5v11M9.800 2.5v11M2.5 6.200h11M2.5 9.800h11', '')],
    "params": [('P', 'M2.5 5h11M2.5 11h11', ''), ('C', (6.0, 5.0, 1.8), 'k'), ('C', (10.5, 11.0, 1.8), 'k')],
    "format": [('P', 'M2 2v12h12', ''), ('P', 'M5.5 10.5l.6-2.6 5.5-5.5 2 2-5.5 5.5zM10 4l2 2', 'a')],
    "import": [('P', 'M2 10v2.5A1.5 1.5 0 0 0 3.5 14h9a1.5 1.5 0 0 0 1.5-1.5V10', ''),
               ('P', 'M8 2v8M4.5 6.5 8 10l3.5-3.5', 'a')],
    "export": [('P', 'M2 10v2.5A1.5 1.5 0 0 0 3.5 14h9a1.5 1.5 0 0 0 1.5-1.5V10', ''),
               ('P', 'M8 10V2M4.5 5.5 8 2l3.5 3.5', 'a')],
    "exportopts": [('P', 'M2.5 9.500v2h6', ''), ('P', 'M6 9.200v-6.700M3.300 5l2.700-2.700 2.700 2.700', 'a'), ('P', 'M10 9.500h4.500M10 12h4.500M10 14.500h4.500', '')],
    "graph": [('P', 'M2 2v12h12', ''), ('P', 'M4.5 10.5 7.5 7.5 10 9l4-5', 'a'),
              ('C', (14.0, 4.0, 0.9), 'f')],
    "layout": [('P', 'M3.5 2h9A1.5 1.5 0 0 1 14 3.5v9a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12.5v-9A1.5 1.5 0 0 1 3.5 2zM8 2v12M8 8h6', '')],
    "pairwise": [('P', 'M3.500 13.500v-6.500h9v6.500', ''), ('P', 'M8 1.500v3.400M6.500 2.350l3 1.700M9.500 2.350l-3 1.700', 'a')],
    "navigator": [('P', 'M2.5 3.500h11v9h-11z', ''), ('P', 'M6.200 3.500v9', ''), ('P', 'M3.800 6h1M3.800 8h1', '')],
    "gallery": [('P', 'M2.5 3.500h11v9h-11zM2.5 8h11M8 3.500v9', '')],
    "prev": [('P', 'M9.700 3.500L5.200 8l4.500 4.500', '')],
    "next": [('P', 'M6.300 3.500L10.800 8l-4.500 4.500', '')],
    "link": [('P', 'M6.800 9.200a2.400 2.400 0 0 0 3.400 0l2.300-2.300a2.400 2.400 0 0 0-3.400-3.400l-.9.9', ''), ('P', 'M9.200 6.800a2.400 2.400 0 0 0-3.400 0l-2.300 2.300a2.400 2.400 0 0 0 3.400 3.400l.9-.9', '')],
    "data": [('P', 'M2.5 3.500h11v9h-11zM2.5 6.500h11M2.5 9.500h11M6.500 3.500v9', '')],
    "result": [('P', 'M3.500 1.500h6l3 3v10h-9z', ''), ('P', 'M9.500 1.500v3h3', ''), ('P', 'M5.500 8h5M5.500 10.500h5', '')],
    "search": [('C', (7.0, 7.0, 4.2), ''), ('P', 'M10.200 10.200l3.300 3.300', '')],
    "plus": [('P', 'M8 3.500v9M3.500 8h9', '')],
    "close": [('P', 'M4.200 4.200l7.600 7.600M11.800 4.200l-7.600 7.600', '')],
    "chevdown": [('P', 'M4.500 6.500L8 10l3.500-3.500', '')],
    "caretr": [('P', 'M6 4.300L10.200 8 6 11.700z', 'f')],
    "caretd": [('P', 'M4.300 6h7.400L8 10.200z', 'f')],
    "warning": [('P', 'M8 2.300l6.200 11h-12.400z', ''), ('P', 'M8 6.600v3.200', ''), ('C', (8.0, 11.5, 0.7), 'f')],
    "home": [('P', 'M2.500 8L8 2.800 13.500 8', ''), ('P', 'M4 7v6.500h8V7', '')],
    "back": [('P', 'M13 8H3.500M7 4.500L3.500 8 7 11.500', '')],
    "forward": [('P', 'M3 8h9.500M9 4.500L12.500 8 9 11.500', '')],
    "pan": [('P', 'M8 2v12M2 8h12M6.200 3.800L8 2l1.800 1.800M6.200 12.200L8 14l1.800-1.800M3.800 6.200L2 8l1.800 1.800M12.200 6.200L14 8l-1.800 1.800', '')],
    "zoom": [('C', (7.0, 7.0, 4.2), ''), ('P', 'M10.200 10.200l3.300 3.300M5.200 7h3.600M7 5.200v3.600', '')],
    "annotation": [('P', 'M3.500 5v-1.500h9V5M8 3.500v9M6.300 12.500h3.400', '')],
    "shapes": [('P', 'M2.500 6.500h7v7h-7z', ''), ('C', (10.7, 5.3, 3.0), 'a k')],
    "inspector": [('P', 'M2.500 3.500h11v9h-11z', ''), ('P', 'M9.800 3.500v9', ''), ('P', 'M11.200 6h1M11.200 8h1', '')],
    "check": [('P', 'M3.500 8.500l3 3 6-7', '')],
    "dots": [('C', (3.5, 8.0, 1.1), 'f'), ('C', (8.0, 8.0, 1.1), 'f'), ('C', (12.5, 8.0, 1.1), 'f')],
}

_TOKEN = re.compile(r"[MmLlHhVvCcAaZz]|-?(?:\d+\.?\d*|\.\d+)")


def _arc(start, rx, ry, rotation, large, sweep, end):
    """Points along an SVG elliptical arc from ``start`` to ``end``."""
    (x1, y1), (x2, y2) = start, end
    if rx == 0 or ry == 0 or start == end:
        return [end]
    phi = radians(rotation)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cos(phi) * dx + sin(phi) * dy, -sin(phi) * dx + cos(phi) * dy
    rx, ry = abs(rx), abs(ry)
    lam = x1p ** 2 / rx ** 2 + y1p ** 2 / ry ** 2
    if lam > 1:
        rx, ry = rx * sqrt(lam), ry * sqrt(lam)
    numerator = rx ** 2 * ry ** 2 - rx ** 2 * y1p ** 2 - ry ** 2 * x1p ** 2
    denominator = rx ** 2 * y1p ** 2 + ry ** 2 * x1p ** 2
    factor = sqrt(max(0.0, numerator / denominator)) * (-1 if bool(large) == bool(sweep) else 1)
    cxp, cyp = factor * rx * y1p / ry, -factor * ry * x1p / rx
    cx = cos(phi) * cxp - sin(phi) * cyp + (x1 + x2) / 2
    cy = sin(phi) * cxp + cos(phi) * cyp + (y1 + y2) / 2
    start_angle = atan2((y1p - cyp) / ry, (x1p - cxp) / rx)
    delta = atan2((-y1p - cyp) / ry, (-x1p - cxp) / rx) - start_angle
    if sweep and delta < 0:
        delta += 2 * pi
    elif not sweep and delta > 0:
        delta -= 2 * pi
    steps = max(6, int(abs(delta) / (pi / 12)) + 1)
    points = []
    for step in range(1, steps + 1):
        angle = start_angle + delta * step / steps
        px, py = rx * cos(angle), ry * sin(angle)
        points.append((cos(phi) * px - sin(phi) * py + cx, sin(phi) * px + cos(phi) * py + cy))
    return points


def _cubic(p0, p1, p2, p3, steps=14):
    points = []
    for step in range(1, steps + 1):
        t = step / steps
        u = 1 - t
        points.append((u ** 3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t ** 3 * p3[0],
                       u ** 3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t ** 3 * p3[1]))
    return points


def subpaths(data):
    """Flatten an SVG path string into ``[(points, closed), ...]`` on the 16 px grid."""
    tokens = _TOKEN.findall(data)
    result, points, closed = [], [], False
    x = y = start_x = start_y = 0.0
    command, index = "", 0

    def number():
        nonlocal index
        value = float(tokens[index])
        index += 1
        return value

    while index < len(tokens):
        if tokens[index].isalpha():
            command = tokens[index]
            index += 1
            if command in "Zz":
                if points:
                    result.append((points, True))
                points, x, y = [], start_x, start_y
                continue
        relative = command.islower()
        kind = command.upper()
        if kind == "M":
            if points:
                result.append((points, False))
            nx, ny = number(), number()
            x, y = (x + nx, y + ny) if relative else (nx, ny)
            start_x, start_y = x, y
            points = [(x, y)]
            command = "l" if relative else "L"
            continue
        if not points:
            points = [(x, y)]
        if kind == "L":
            nx, ny = number(), number()
            x, y = (x + nx, y + ny) if relative else (nx, ny)
            points.append((x, y))
        elif kind == "H":
            nx = number()
            x = x + nx if relative else nx
            points.append((x, y))
        elif kind == "V":
            ny = number()
            y = y + ny if relative else ny
            points.append((x, y))
        elif kind == "C":
            values = [number() for _ in range(6)]
            if relative:
                values = [value + (x if i % 2 == 0 else y) for i, value in enumerate(values)]
            points.extend(_cubic((x, y), tuple(values[0:2]), tuple(values[2:4]), tuple(values[4:6])))
            x, y = values[4], values[5]
        elif kind == "A":
            rx, ry, rotation, large, sweep, nx, ny = (number() for _ in range(7))
            end = (x + nx, y + ny) if relative else (nx, ny)
            points.extend(_arc((x, y), rx, ry, rotation, large, sweep, end))
            x, y = end
    if points:
        result.append((points, closed))
    return result


def _hex(color, alpha=255):
    color = color.lstrip("#")
    return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16), alpha)


def render(name, size, *, ink, accent, knockout="#ffffff", stroke=1.4, supersample=4):
    """Draw one icon as an RGBA image of ``size`` px (transparent background)."""
    factor = size * supersample / 16
    image = Image.new("RGBA", (size * supersample, size * supersample))
    draw = ImageDraw.Draw(image)
    width = max(1, round(stroke * factor))

    def scaled(points):
        return [(px * factor, py * factor) for px, py in points]

    def stroke_line(points, color):
        if len(points) == 1:
            return
        draw.line(points, fill=color, width=width, joint="curve")
        radius = width / 2
        for px, py in (points[0], points[-1]):
            draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color)

    for kind, geometry, classes in ICONS[name]:
        names = classes.split()
        color = _hex(accent if "a" in names else ink)
        if kind == "C":
            cx, cy, radius = geometry
            box = ((cx - radius) * factor, (cy - radius) * factor, (cx + radius) * factor, (cy + radius) * factor)
            if "f" in names:
                draw.ellipse(box, fill=_hex(ink))
            elif "k" in names:
                draw.ellipse(box, fill=_hex(knockout))
                draw.ellipse(box, outline=color, width=width)
            else:
                draw.ellipse(box, outline=color, width=width)
            continue
        for points, closed in subpaths(geometry):
            points = scaled(points)
            if "af" in names:
                draw.polygon(points, fill=_hex(accent, 128))
            elif "f" in names:
                draw.polygon(points, fill=_hex(ink))
                continue
            stroke_line(points + [points[0]] if closed else points, color)
    return image.resize((size, size), Image.Resampling.LANCZOS)
