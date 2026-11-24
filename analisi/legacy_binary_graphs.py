"""Recover the saved graph previews in legacy PCFFGRA4 projects."""

from base64 import b64decode, b64encode
from binascii import Error
import os
from pathlib import Path
from struct import unpack_from
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory

from PIL import Image, ImageChops, ImageOps

from .legacy_pdf_preview import pdf_dimensions, render_pdf


MAX_BINARY_GRAPHS = 256
MAX_BINARY_GRAPH_TOTAL = 8 * 1024 * 1024
_MAX_PREVIEW_BYTES = 1024 * 1024
_MAX_BASE64_BYTES = 4 * ((_MAX_PREVIEW_BYTES + 2) // 3)
_PREVIEW_PREFIX_SIZE = 136

# Drawing records used by the saved drawing previews. In particular, escape,
# printer/OpenGL, profile and nested metafile records are outside this subset.
_EMF_FIXED = {
    9: 16, 10: 16, 11: 16, 17: 12, 18: 12, 19: 12, 20: 12, 21: 12, 22: 12,
    24: 12, 25: 12, 27: 16, 30: 24, 33: 8, 34: 12, 36: 36, 37: 12, 38: 28,
    40: 12, 43: 24, 48: 12, 54: 16, 58: 12, 59: 8, 60: 8, 61: 8,
    62: 24, 63: 24, 98: 12,
}
_EMF_PLUS_VERSIONS = (0xDBC01001, 0xDBC01002)
_EMF_PLUS_FIXED = {
    0x4001: 28, 0x4002: 12, 0x4004: 12, 0x4009: 16, 0x4014: 16, 0x4015: 16,
    0x401E: 12, 0x401F: 12, 0x4025: 16, 0x4026: 16, 0x402A: 36, 0x402D: 20,
    0x402E: 20, 0x4031: 12, 0x4032: 28, 0x4033: 12, 0x4034: 12,
}


def _padded(size):
    return (size + 3) & ~3


def _emf_plus_path(data, *, cap=False):
    if len(data) < 12:
        return False
    version, count, flags = unpack_from("<III", data)
    # The additional flag in the observed cap paths leaves the point layout
    # unchanged. Other path encodings, including relative points, are omitted.
    return (version in _EMF_PLUS_VERSIONS and count > 0
            and flags in ((0x2000, 0x6000) if cap else (0, 0x4000))
            and len(data) == _padded(12 + count * (5 if flags & 0x4000 else 9)))


def _emf_plus_cap(data, cap_flags):
    # A length-prefixed default cap with one length-prefixed path.
    if len(data) < 64:
        return False
    cap_size, version, cap_type, flags = unpack_from("<4I", data)
    path_size, = unpack_from("<I", data, 60)
    return (cap_size == len(data) - 4 and version in _EMF_PLUS_VERSIONS
            and cap_type == 0 and flags == cap_flags
            and path_size == len(data) - 64 and _emf_plus_path(data[64:], cap=True))


def _emf_plus_pen(record):
    size = len(record)
    pen_type, pen_flags = unpack_from("<II", record, 16)
    brush_version, brush_type = unpack_from("<II", record, size - 12)
    # The observed layouts all end in a solid brush.
    if pen_type or brush_version not in _EMF_PLUS_VERSIONS or brush_type != 0:
        return False
    if (size, pen_flags) in ((52, 80), (56, 208)):
        return True
    if (size, pen_flags) == (68, 464):
        # The style array follows the dash offset and ends at the brush.
        return unpack_from("<I", record, 44)[0] == (size - 12 - 48) // 4
    if size == 192 and pen_flags in (2258, 4308):
        return _emf_plus_cap(record[48:-12], 1)
    if (size, pen_flags) == (256, 6358):
        return _emf_plus_cap(record[52:148], 2) and _emf_plus_cap(record[148:-12], 2)
    return False


def _emf_plus_object(flags, record):
    kind, size = flags >> 8, len(record)
    if size < 16 or flags & 0xFF >= 64 or unpack_from("<I", record, 12)[0] not in _EMF_PLUS_VERSIONS:
        return False
    if kind == 2 and size >= 52:
        return _emf_plus_pen(record)
    if kind == 3:
        return _emf_plus_path(record[12:])
    if kind == 4:
        return size == 40 and unpack_from("<II", record, 16) == (0, 0x10000000)
    if kind == 6:
        return size >= 36 and size == _padded(36 + 2 * unpack_from("<I", record, 32)[0])
    # The observed StringFormat objects carry no tab stops or character ranges.
    return kind == 7 and size == 72 and unpack_from("<II", record, 64) == (0, 0)


def _valid_emf_plus_record(kind, flags, record):
    size = len(record)
    if kind in _EMF_PLUS_FIXED:
        return size == _EMF_PLUS_FIXED[kind]
    if kind == 0x4003:  # Private text annotations in the source drawing.
        return flags in (0, 1, 2, 3) and size in (24, 32, 36)
    if kind == 0x4008:
        return _emf_plus_object(flags, record)
    if kind in (0x400A, 0x400D):
        # The observed rectangle and line arrays use signed 16-bit coordinates.
        offset, stride = (16, 8) if kind == 0x400A else (12, 4)
        expected_flags = 0xC000 if kind == 0x400A else 0x4000
        return (flags & 0xFF00 == expected_flags and size >= offset + 4
                and size == offset + 4 + stride * unpack_from("<I", record, offset)[0])
    if kind == 0x401C:
        return size >= 40 and size == _padded(40 + 2 * unpack_from("<I", record, 20)[0])
    if kind == 0x4036 and size >= 28:
        options, transform, count = unpack_from("<III", record, 16)
        return options == 1 and transform == 1 and size == _padded(52 + count * 10)
    return False


def _valid_layout_plus_record(kind, flags, record, image_ids):
    size = len(record)
    if kind == 0x4008:
        image_ids.discard(flags & 0xFF)
        if flags >> 8 == 5:
            if (flags & 0xFF >= 64 or size <= 156
                    or unpack_from("<I", record, 12)[0] not in _EMF_PLUS_VERSIONS
                    or unpack_from("<3I", record, 16) != (2, 4, size - 28)):
                return False
            # Type 4 embeds a single EMF+ metafile. Apply the graph profile
            # inside it, which excludes further embedded images.
            _emf_dimensions(record[28:])
            image_ids.add(flags & 0xFF)
            return True
    if kind == 0x401A:  # DrawImage with a signed 16-bit destination rectangle.
        if (flags & 0xFF00 != 0x4000 or flags & 0xFF not in image_ids or size != 44
                or unpack_from("<II", record, 12) != (0xFFFFFFFF, 2)):
            return False
        x, y, width, height = unpack_from("<4f", record, 20)
        dest_width, dest_height = unpack_from("<2h", record, 40)
        return (0 <= x < x + width <= 1_000_000 and 0 <= y < y + height <= 1_000_000
                and dest_width > 0 and dest_height > 0)
    if kind == 0x401B:
        return (flags in image_ids and size == 64
                and unpack_from("<II", record, 12) == (0xFFFFFFFF, 2)
                and unpack_from("<I", record, 36)[0] == 3
                and all(abs(value) <= 1_000_000 for value in unpack_from("<4f", record, 20))
                and all(abs(value) <= 1_000_000 for value in unpack_from("<6f", record, 40)))
    if kind == 0x402C:
        return flags == 0 and size == 36 and _bounded_transform(record, 12)
    return _valid_emf_plus_record(kind, flags, record)


def _bounded_transform(record, offset):
    a, b, c, d, x, y = unpack_from("<6f", record, offset)
    return all(abs(value) <= 10_000 for value in (a, b, c, d)) and abs(x) <= 1_000_000 and abs(y) <= 1_000_000


def _emf_plus_comment(record, image_ids=None):
    if (len(record) < 28 or unpack_from("<I", record, 8)[0] != len(record) - 12
            or record[12:16] != b"EMF+"):
        raise ValueError("Unsupported EMF comment in legacy graph.")
    pos = 16
    while pos < len(record):
        if len(record) - pos < 12:
            raise ValueError("Truncated EMF+ record in legacy graph.")
        kind, flags, size, payload_size = unpack_from("<HHII", record, pos)
        if size != payload_size + 12 or size % 4 or size > len(record) - pos:
            raise ValueError("Unsupported EMF+ record in legacy graph.")
        part = record[pos:pos + size]
        if image_ids is None:
            valid = _valid_emf_plus_record(kind, flags, part)
        else:
            valid = _valid_layout_plus_record(kind, flags, part, image_ids)
        if not valid:
            raise ValueError("Unsupported EMF+ record in legacy graph.")
        pos += size


def _valid_emf_record(kind, record):
    size = len(record)
    if kind in _EMF_FIXED:
        return size == _EMF_FIXED[kind]
    if kind in (42, 64) and size == 24:  # EMR_ELLIPSE or EMR_STROKEPATH with bounded geometry.
        left, top, right, bottom = unpack_from("<4i", record, 8)
        return (-1_000_000 <= left < right <= 1_000_000 and -1_000_000 <= top < bottom <= 1_000_000
                and max(right - left, bottom - top) <= 100_000)
    if kind == 39 and size == 24:
        style, _, hatch = unpack_from("<III", record, 12)
        return (style in (0, 1) and hatch == 0) or (style == 2 and hatch <= 5)
    if kind == 70:
        _emf_plus_comment(record)
        return True
    if kind == 75:  # Reset the clip or select a single rectangular region.
        return ((size == 16 and unpack_from("<II", record, 8) == (0, 5))
                or (size == 64 and unpack_from("<6I", record, 8) == (48, 5, 32, 1, 1, 16)))
    if kind == 76:
        return size == 100 and not any(record[84:100])
    if kind == 82:  # The extended font has no design-vector axes.
        return size == 368 and unpack_from("<II", record, 360) == (0x08007664, 0)
    if kind == 84 and size >= 76:  # UTF-16 text and matching horizontal advances.
        count, start, options = unpack_from("<III", record, 44)
        advance, = unpack_from("<I", record, 72)
        return (options in (0, 2) and 76 <= start <= advance - 2 * count
                and advance % 4 == 0 and size == advance + 4 * count)
    if kind in (85, 86, 87, 88, 89):
        return size >= 32 and size == 28 + 4 * unpack_from("<I", record, 24)[0]
    if kind in (90, 91) and size >= 32:
        polygons, points = unpack_from("<II", record, 24)
        return (size == 32 + 4 * (polygons + points)
                and points == sum(unpack_from(f"<{polygons}I", record, 32)))
    if kind in (93, 94):
        # The 1bpp monochrome brush uses implicit colors. The DIB pattern
        # brush carries both RGB entries in its palette.
        usage, bmi_size = (2, 40) if kind == 93 else (0, 48)
        return (size == 68 + bmi_size
                and unpack_from("<5I", record, 12) == (usage, 36, bmi_size, 36 + bmi_size, 32)
                and unpack_from("<IiiHHI", record, 36) == (40, 8, 8, 1, 1, 0)
                and unpack_from("<I", record, 56)[0] in (0, 32)
                and unpack_from("<II", record, 68) in (
                    ((0, 0),) if kind == 93 else ((0, 0), (0, 1), (0, 2), (2, 0), (2, 1), (2, 2))))
    return (kind == 95 and size == 56 and unpack_from("<4I", record, 12) == (56, 0, 56, 0)
            and unpack_from("<I", record, 28)[0] & 0xF != 7  # PS_USERSTYLE
            and unpack_from("<I", record, 36)[0] == 0  # BS_SOLID
            and unpack_from("<II", record, 44) == (0, 0))


def _layout_group_delta(record):
    if (len(record) == 40 and unpack_from("<I", record, 8)[0] == 28
            and unpack_from("<I", record, 16)[0] == 2 and unpack_from("<I", record, 36)[0] == 0):
        return 1  # EMR_COMMENT_BEGINGROUP without a description.
    if len(record) == 20 and unpack_from("<I", record, 8)[0] == 8 and unpack_from("<I", record, 16)[0] == 3:
        return -1  # EMR_COMMENT_ENDGROUP.
    raise ValueError("Unsupported EMF group comment in legacy layout.")


def _valid_layout_emf_record(kind, record):
    size = len(record)
    if kind == 13:  # SetBrushOrgEx.
        return size == 16 and all(abs(value) <= 1_000_000 for value in unpack_from("<2i", record, 8))
    if kind == 28:  # SetMetaRgn.
        return size == 8
    if kind == 35:  # SetWorldTransform.
        return size == 32 and _bounded_transform(record, 8)
    if kind == 115:  # SetLayout, observed left-to-right.
        return size == 12 and unpack_from("<I", record, 8)[0] == 0
    return _valid_emf_record(kind, record)


def _emf_dimensions(data, *, layout=False):
    if not 128 < len(data) <= _MAX_PREVIEW_BYTES:
        raise ValueError("Invalid EMF size in legacy graph.")
    kind, header_size = unpack_from("<II", data)
    version, total, record_count = unpack_from("<III", data, 44)
    if (kind != 1 or header_size != 108 or data[40:44] != b" EMF"
            or version != 0x10000 or total != len(data)
            or not 3 <= record_count <= 50_000
            or any(data[60:72]) or any(data[88:100])):
        raise ValueError("Unsupported EMF header in legacy graph.")
    x0, y0, x1, y1, left, top, right, bottom = unpack_from("<8i", data, 8)
    width, height = right - left, bottom - top
    if (not 0 < x1 - x0 <= 100_000 or not 0 < y1 - y0 <= 100_000
            or not 0 < width <= 2_000_000 or not 0 < height <= 2_000_000
            or max(width, height) > 100 * min(width, height)):
        raise ValueError("Invalid EMF dimensions in legacy graph.")

    view = memoryview(data)
    pos = header_size
    group_depth = 0
    image_ids = set() if layout else None
    for index in range(1, record_count):
        if len(data) - pos < 8:
            break
        kind, size = unpack_from("<II", data, pos)
        if size < 8 or size % 4 or size > len(data) - pos:
            break
        if kind == 14:
            if (not group_depth and index == record_count - 1 and pos + size == len(data) and size == 20
                    and unpack_from("<III", data, pos + 8) in ((0, 0, 20), (0, 16, 20))):
                return width, height
            break
        record = view[pos:pos + size]
        if layout and kind == 70:
            if record[12:16] == b"GDIC":
                group_depth += _layout_group_delta(record)
                if not 0 <= group_depth <= 16:
                    raise ValueError("Invalid EMF group nesting in legacy layout.")
            else:
                _emf_plus_comment(record, image_ids)
        elif not (_valid_layout_emf_record(kind, record) if layout else _valid_emf_record(kind, record)):
            raise ValueError("Unsupported EMF drawing record in legacy graph.")
        pos += size
    raise ValueError("Incomplete EMF drawing records in legacy graph.")


def _decode_preview(preview, *, layout=False):
    encoded = preview.get("data") if isinstance(preview, dict) else None
    if (not isinstance(encoded, str) or not 0 < len(encoded) <= _MAX_BASE64_BYTES
            or preview.get("format") not in ("emf", "pdf")):
        raise ValueError("Invalid legacy graph preview.")
    try:
        data = b64decode(encoded, validate=True)
    except (Error, ValueError) as exc:
        raise ValueError("Invalid legacy graph preview encoding.") from exc
    dimensions = pdf_dimensions(data) if preview["format"] == "pdf" else _emf_dimensions(data, layout=layout)
    return data, dimensions


def validate_binary_graph(preview, *, layout=False):
    """Return the original vector bytes after validating the project preview."""
    return _decode_preview(preview, layout=layout)[0]


def export_binary_graph(path, preview, *, layout=False):
    """Write a validated saved drawing without replacing the destination on failure."""
    data = validate_binary_graph(preview, layout=layout)
    path = Path(path)
    suffix = f".{preview['format']}"
    if path.suffix.lower() != suffix:
        raise ValueError(f"Use a {suffix} file name for this drawing.")
    temp = None
    try:
        with NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp = Path(handle.name)
            handle.write(data)
        os.replace(temp, path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def _graph_index(payload):
    if len(payload) not in (10064, 10068):
        raise ValueError("Unsupported legacy binary graph index.")
    count, = unpack_from("<I", payload, 48)
    if count > MAX_BINARY_GRAPHS:
        raise ValueError("Legacy binary graph count exceeds the limit.")
    ids = unpack_from(f"<{count}i", payload, 4060)
    if len(set(ids)) != count or any(not 0 <= uid <= 65535 for uid in ids):
        raise ValueError("Invalid legacy binary graph identifiers.")
    codepage = unpack_from("<I", payload, 10064)[0] if len(payload) == 10068 else 1252
    return dict.fromkeys(ids), f"cp{codepage}" if codepage in (1251, 1252) else "ascii"


def _read_title(payload, encoding):
    raw = bytes(payload)
    if not 0 < len(raw) <= 4096 or not raw.endswith(b"\0") or b"\0" in raw[:-1]:
        raise ValueError("Invalid legacy graph title.")
    title = raw[:-1].decode(encoding)
    if any(ord(char) < 32 for char in title):
        raise ValueError("Invalid legacy graph title.")
    return title


def _stored_emf_preview(payload, remaining, *, layout=False):
    if payload is None or payload is False or len(payload) <= _PREVIEW_PREFIX_SIZE:
        raise ValueError("Missing legacy binary preview.")
    size, version = unpack_from("<II", payload)
    encoded_size = 4 * ((size + 2) // 3)
    if (version != 1 or size != len(payload) - _PREVIEW_PREFIX_SIZE
            or encoded_size > remaining):
        raise ValueError("Invalid legacy binary preview length.")
    emf = payload[_PREVIEW_PREFIX_SIZE:]
    _emf_dimensions(emf, layout=layout)
    return {"format": "emf", "data": b64encode(emf).decode("ascii")}


def _stored_pdf_preview(payload, remaining):
    if (not payload or len(payload) > _MAX_PREVIEW_BYTES
            or 4 * ((len(payload) + 2) // 3) > remaining):
        raise ValueError("Missing or oversized saved legacy PDF drawing.")
    pdf_dimensions(bytes(payload))
    return {"format": "pdf", "data": b64encode(payload).decode("ascii")}


def read_binary_graphs(data, *, include_without_preview=False):
    """Read indexed previews in navigator order, optionally including scenes without a preview."""
    from .legacy_binary import _records

    indexed, current = None, None
    encoding = "ascii"
    for tag, parents, payload in _records(data):
        if parents == (1,) and tag == 0x8002:
            if indexed is not None:
                raise ValueError("Duplicate legacy binary graph index.")
            indexed, encoding = _graph_index(payload)
        elif parents == (1,) and tag == 0x8012:
            current = None
            if indexed is None or len(payload) != 2:
                continue
            uid, = unpack_from("<H", payload)
            if uid in indexed:
                # Duplicate IDs are ambiguous even if their titles match.
                current = {} if indexed[uid] is None else False
                indexed[uid] = current
        elif parents == (1,) and tag == 0x4012:
            current = None
        elif parents == (1, 18) and isinstance(current, dict) and tag in (9, 0x5E, 0xF00):
            current[tag] = False if tag in current else payload

    if indexed is None:
        raise ValueError("Missing legacy binary graph index.")
    graphs, skipped, total = [], [], 0
    for uid, group in indexed.items():
        title = f"Graph {uid}"
        try:
            if not group or not group.get(9):
                raise ValueError("Missing legacy binary graph title.")
            title = _read_title(group[9], encoding) or title
            if include_without_preview and 0x5E not in group and 0xF00 not in group:
                graphs.append({"id": uid, "title": title})
                continue
            remaining = MAX_BINARY_GRAPH_TOTAL - total
            try:
                preview = _stored_emf_preview(group.get(0x5E), remaining)
            except ValueError:
                preview = _stored_pdf_preview(group.get(0xF00), remaining)
        except ValueError:
            skipped.append(title)
            continue
        graphs.append({"id": uid, "title": title, "preview": preview})
        total += len(preview["data"])
    return graphs, skipped


def _render_windows(path, dimensions, max_side):
    # GDI+ replays the EMF+ drawing commands in dual metafiles.
    import ctypes as c

    class StartupInput(c.Structure):
        _fields_ = [("version", c.c_uint32), ("debug", c.c_void_p),
                    ("suppress_background", c.c_int), ("suppress_codecs", c.c_int)]

    gdip = c.WinDLL("gdiplus.dll")

    def call(function, *args):
        status = getattr(gdip, function)(*args)
        if status != 0:
            raise ValueError(f"Windows could not render the legacy graph ({function}, status {status}).")

    width, height = dimensions
    width, height = (max(1, round(side * max_side / max(dimensions))) for side in dimensions)
    token = c.c_size_t()
    source, bitmap, graphics = c.c_void_p(), c.c_void_p(), c.c_void_p()
    pixel_data = (c.c_ubyte * (width * height * 4))()
    call("GdiplusStartup", c.byref(token), c.byref(StartupInput(1, None, 0, 1)), None)
    try:
        call("GdipLoadImageFromFile", c.c_wchar_p(str(path)), c.byref(source))
        call("GdipCreateBitmapFromScan0", width, height, width * 4, 0x26200A, pixel_data, c.byref(bitmap))
        call("GdipGetImageGraphicsContext", bitmap, c.byref(graphics))
        call("GdipGraphicsClear", graphics, c.c_uint32(0xFFFFFFFF))
        call("GdipDrawImageRectI", graphics, source, 0, 0, width, height)
        call("GdipFlush", graphics, 1)  # FlushIntentionSync.
        return Image.frombytes("RGBA", (width, height), bytes(pixel_data), "raw", "BGRA").convert("RGB")
    finally:
        if graphics:
            gdip.GdipDeleteGraphics(graphics)
        if bitmap:
            gdip.GdipDisposeImage(bitmap)
        if source:
            gdip.GdipDisposeImage(source)
        gdip.GdiplusShutdown(token)


def render_binary_graph(preview, *, layout=False, crop=True, max_side=1600):
    """Render the original drawing, with a bounded raster size for display."""
    data, dimensions = _decode_preview(preview, layout=layout)
    if preview["format"] == "pdf":
        image = render_pdf(data, max_side)
    else:
        if sys.platform != "win32":
            raise ValueError("Displaying the saved graph requires Windows.")
        with TemporaryDirectory(prefix="trama-legacy-graph-") as directory:
            path = Path(directory) / "graph.emf"
            path.write_bytes(data)
            image = _render_windows(path, dimensions, max_side)
    if all(low == high for low, high in image.getextrema()):
        raise ValueError("The saved graph rendered without visible content.")
    if not crop:
        return image
    bounds = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
    return ImageOps.expand(image.crop(bounds), border=12, fill="white")
