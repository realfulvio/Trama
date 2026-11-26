"""Read source grids from the legacy little-endian PCFFGRA4 project layout."""

from itertools import zip_longest
from math import isfinite
from struct import Struct, unpack_from

from .data import MAX_CELLS, MAX_COLUMNS, MAX_ENTRY, _table


MAGIC = b"PCFFGRA4"
_RECORD = Struct("<HI")
_DATASET = Struct("<15i")
_NUMERIC_CELL = (Struct("<IIf"), Struct("<IId"))
_FLOAT32 = Struct("<f")
_PLAIN = 10
_MEAN_SD = 21
_XY_LIMITS = 30
_LEGACY_LIMITS_LAYOUT = 34
_REPLICATES = 61
_ROW_TITLES = 256


class _UnsupportedSheet(ValueError):
    pass


def _records(data):
    """Yield (tag, parent tags, payload), including closing tags."""
    if data[:8] != MAGIC:
        raise ValueError("Unrecognized legacy binary header.")
    view = memoryview(data)
    parents = []
    pos = len(MAGIC)
    records = 0
    while pos < len(view):
        records += 1
        if records > 500_000 or len(parents) > 32:
            raise ValueError("Legacy binary project exceeds the record or nesting limit.")
        if len(view) - pos < 2:
            raise ValueError("Truncated legacy binary record.")
        tag, = unpack_from("<H", view, pos)
        flags, kind = tag & 0xC000, tag & 0x3FFF
        if flags == 0x4000:
            if not parents or parents.pop() != kind:
                raise ValueError("Mismatched legacy binary group.")
            pos += 2
            yield tag, tuple(parents), view[pos:pos]
            if not parents:
                if pos != len(view):
                    raise ValueError("Unexpected bytes after the legacy binary root.")
                return
            continue
        if not kind or flags == 0xC000 or len(view) - pos < _RECORD.size:
            raise ValueError("Invalid legacy binary record.")
        if not parents and tag != 0x8001:
            raise ValueError("Missing legacy binary root.")
        _, size = _RECORD.unpack_from(view, pos)
        start = pos + _RECORD.size
        pos = start + size
        if pos > len(view):
            raise ValueError("Truncated legacy binary record.")
        if tag == 0x8001 and (parents or size != 12):
            raise ValueError("Unsupported legacy binary root.")
        yield tag, tuple(parents), view[start:pos]
        # The root-level palette has a length field and no group terminator.
        if flags == 0x8000 and not (tag == 0x8003 and parents == [1]):
            parents.append(kind)
    raise ValueError("Unclosed legacy binary project.")


def _source_ids(payload):
    if len(payload) not in (10064, 10068):
        raise ValueError("Unsupported legacy binary sheet index.")
    count, = unpack_from("<i", payload, 40)
    if not 0 <= count <= 256:
        raise ValueError("Invalid legacy binary sheet count.")
    ids = unpack_from(f"<{count}i", payload, 60)
    if len(set(ids)) != count or any(not 0 <= uid <= 65535 for uid in ids):
        raise ValueError("Invalid legacy binary sheet identifiers.")
    return ids


def _title(payload):
    value = bytes(payload)
    if not value.endswith(b"\0") or b"\0" in value[:-1] or len(value) > 4096:
        raise _UnsupportedSheet("Unrecognized title storage")
    return value[:-1].decode("ascii")


def _formatted_label(payload, fonts):
    plain, separator, formatting = payload.partition(b"\0")
    if not separator:
        return plain.decode("ascii")
    if not formatting or len(formatting) % 3:
        raise _UnsupportedSheet("Unrecognized text formatting")
    parts = []
    offset = 0
    for length, style, font in Struct("<BBB").iter_unpack(formatting):
        part = plain[offset:offset + length]
        # Both display styles occur within one title. The font selects the glyph.
        if not length or len(part) != length or style not in (0x01, 0x41):
            raise _UnsupportedSheet("Unrecognized text formatting")
        if style == 0x41 and fonts.get(font - 1) not in (b"Arial", b"Symbol"):
            raise _UnsupportedSheet("Unrecognized font encoding")
        if font == 1 and fonts.get(0) not in (b"Symbol", b"Wingdings"):
            parts.append(part.decode("ascii"))
        elif fonts.get(font - 1) == b"Symbol" and part in (b"m", b"g"):
            parts.append("µ" if part == b"m" else "γ")
        else:
            raise _UnsupportedSheet("Unrecognized font encoding")
        offset += length
    if offset != len(plain):
        raise _UnsupportedSheet("Incomplete text formatting")
    return "".join(parts)


def _record_once(records, tag, required=True):
    matches = [payload for kind, payload in records if kind == tag]
    if len(matches) > 1 or (required and not matches):
        raise _UnsupportedSheet("Missing or duplicate table metadata")
    return matches[0] if matches else None


def _stored_cells(records, count, *, single_precision=False):
    payload = _record_once(records, 0x10)
    if len(payload) < 6:
        raise _UnsupportedSheet("Truncated cell storage")
    precision, stored_count = unpack_from("<HI", payload)
    if precision not in (0, 1) or (single_precision and precision != 0) or stored_count != count:
        raise _UnsupportedSheet("Unrecognized cell storage")
    layout = _NUMERIC_CELL[precision]
    if len(payload) != 6 + count * layout.size:
        raise _UnsupportedSheet("Inconsistent cell storage length")
    return layout.iter_unpack(payload[6:])


def _cell_storage(records, count, *, text=False):
    cells = _stored_cells(records, count)
    attributes = _record_once(records, 0xF3)
    if len(attributes) < 16:
        raise _UnsupportedSheet("Truncated cell attributes")
    version, header_size, stride, attribute_count = unpack_from("<4I", attributes)
    formats = {(1, 4), (2, 16), (3, 28)} if text else {(1, 4), (2, 16)}
    if ((version, stride) not in formats or header_size != 16
            or attribute_count != count or len(attributes) != 16 + count * stride):
        raise _UnsupportedSheet("Unrecognized cell attributes")
    return cells, attributes[16:], stride


def _numeric_values(records, count, *, grouped_integers=False, excluded_slots=None):
    cells, attributes, stride = _cell_storage(records, count)
    can_exclude = (excluded_slots is not None and stride == 4
                   and unpack_from("<H", _record_once(records, 0x10))[0] == 0)
    values = []
    for i, (status, width, value) in enumerate(cells):
        # Status 105 marks integers in the archived single-column-per-group profile.
        integer_status = grouped_integers and stride == 4 and status == 105 and width == 0 and value.is_integer()
        # Status zero can retain an earlier value after the cell was cleared.
        expected = (0, status, 0, 0) if stride == 16 else (0,)
        excluded = status == 3 and can_exclude
        if ((status not in (0, 1, 5) and not integer_status and not excluded)
                or unpack_from("<4I" if stride == 16 else "<I", attributes, i * stride) != expected
                or (status and not isfinite(value))):
            raise _UnsupportedSheet("Unrecognized numeric cell status")
        if excluded:
            excluded_slots.append(i)
        values.append(value if status else None)
    return values


def _legacy_values(records, count, x_id):
    column = x_id == -1
    field = _record_once(records, 0x8F)
    if (len(field) != 12 or unpack_from("<3i", field) != (2, -1, x_id)
            or _record_once(records, 0x90) != (b"\x01\x00" if column else b"\x00\x00")
            or _record_once(records, 0xF3, required=False) is not None
            or column and any(tag not in (9, 0x10, 0x8F, 0x90) for tag, _ in records)):
        raise _UnsupportedSheet("Unrecognized legacy cell attributes")
    values = []
    for status, width, value in _stored_cells(records, count, single_precision=True):
        if column:
            # FAQ 1646 shows status 105 on the plotted integer values in the
            # mice column, and status 1 on ordinary values in Cats and dogs.
            if width != 0 or not isfinite(value) or not (status == 1 or status == 105 and value.is_integer()):
                raise _UnsupportedSheet("Unrecognized legacy column cell status")
            values.append(value)
        elif status == 0 and width in (0, 4):
            values.append(None)
        # Widths observed in the saved XY worksheet include zero for uncached widths.
        elif status == 1 and width in (0, 11, 18, 25, 32, 39) and isfinite(value):
            values.append(value)
        else:
            raise _UnsupportedSheet("Unrecognized legacy XY cell status")
    return values


def _legacy_limit_values(records, count, x_id, role):
    owner = _record_once(records, 0x8F)
    if (len(owner) != 12 or unpack_from("<3i", owner) != (2, 0, x_id)
            or _record_once(records, 0x90) != b"\x01\x00"
            or _record_once(records, 0xF3, required=False) is not None):
        raise _UnsupportedSheet("Unrecognized legacy XY limit attributes")
    cells = _stored_cells(records, count, single_precision=True)
    if role == _ROW_TITLES:
        if count or any(_record_once(records, tag) != bytes(4) for tag in (0x11, 0xB6)):
            raise _UnsupportedSheet("Unrecognized legacy XY row titles")
        return []
    if role == 4:
        values = []
        for status, width, value in cells:
            if status != 1 or width or not isfinite(value):
                raise _UnsupportedSheet("Unrecognized legacy XY coordinate")
            values.append(value)
        return values

    values = []
    for center, plus, minus in zip(cells, cells, cells, strict=True):
        if (center, plus, minus) == ((0x100000, 0, 0), (0, 0, 0), (0, 0, 0)):
            values.extend((None, None, None))
            continue
        if any(status != 1 or width or not isfinite(value) for status, width, value in (center, plus, minus)):
            raise _UnsupportedSheet("Unrecognized legacy XY limit cells")
        # This profile stores signed distances. The original worksheet shows
        # single-precision endpoints, including limits that cross the center.
        mean = center[2]
        try:
            upper = _FLOAT32.unpack(_FLOAT32.pack(mean + plus[2]))[0]
            lower = _FLOAT32.unpack(_FLOAT32.pack(mean - minus[2]))[0]
        except OverflowError as error:
            raise _UnsupportedSheet("Legacy XY endpoint exceeds its numeric range") from error
        values.extend((mean, upper, lower))
    return values


def _indexed_row_titles(text, offsets, count, fonts, padding, *, packed_index=None):
    if (text is None or offsets is None or len(text) < 4 or len(offsets) < 4
            or unpack_from("<I", text)[0] != len(text) - 4):
        raise _UnsupportedSheet("Unrecognized row title storage")
    entries, = unpack_from("<I", offsets)
    if len(offsets) != 4 + 12 * entries + padding:
        raise _UnsupportedSheet("Inconsistent row title index")
    result = [None] * count
    referenced_bytes = 0
    for row, start, size in Struct("<III").iter_unpack(offsets[4:4 + 12 * entries]):
        referenced_bytes += size
        if (row >= count or not 0 < size <= 4096 or start + size > len(text) - 4
                or referenced_bytes > len(text) - 4 or result[row] is not None):
            raise _UnsupportedSheet("Invalid row title reference")
        if packed_index is not None and (start >= 1 << 16
                or unpack_from("<I", packed_index, 4 * row)[0] != ((size << 16) | start)):
            raise _UnsupportedSheet("Invalid legacy grouped row title reference")
        value = bytes(text[4 + start:4 + start + size])
        result[row] = _formatted_label(value, fonts)
    return result


def _row_titles(records, count, fonts):
    cells, attributes, stride = _cell_storage(records, count, text=True)
    text = _record_once(records, 0x11, required=False)
    offsets = _record_once(records, 0xB6, required=False)
    if count == 0 and text is None and (offsets is None or
            (len(offsets) in (4, 8) and unpack_from("<I", offsets)[0] == 0)):
        return []
    result = _indexed_row_titles(text, offsets, count, fonts, padding=4 if stride == 28 else 0)
    for row, ((status, _, _), label) in enumerate(zip(cells, result, strict=True)):
        if (status not in (0, 1) or bool(status) != (label is not None)
                or stride >= 16 and unpack_from("<2I", attributes, row * stride) != (0, status)):
            raise _UnsupportedSheet("Unrecognized row title status")
    return result


def _legacy_grouped_cells(records, count, role, name_payload, fonts):
    attributes = _record_once(records, 0x8F)
    if (len(attributes) != 24 or unpack_from("<4i", attributes) != (3, 0, -1, 1)
            or _record_once(records, 0x90) != b"\x01\x00"
            or _record_once(records, 0xF3, required=False) is not None):
        raise _UnsupportedSheet("Unrecognized legacy grouped attributes")
    text_size, title_size = unpack_from("<2i", attributes, 16)
    cells = _stored_cells(records, count, single_precision=True)
    if role == _ROW_TITLES:
        text = _record_once(records, 0x11)
        offsets = _record_once(records, 0xB6)
        index = _record_once(records, 0x92)
        if (text_size != len(text) - 4 or title_size != len(name_payload) - 1
                or len(index) != 4 + 4 * count or unpack_from("<I", index)[0] != count):
            raise _UnsupportedSheet("Unrecognized legacy grouped row titles")
        labels = _indexed_row_titles(text, offsets, count, fonts, padding=0, packed_index=index[4:])
        for (status, width, value), (packed,), label in zip(
                cells, Struct("<I").iter_unpack(index[4:]), labels, strict=True):
            if (width or status != int(label is not None) or (label is None and packed)
                    or value != _FLOAT32.unpack(_FLOAT32.pack(packed))[0]):
                raise _UnsupportedSheet("Invalid legacy grouped row title reference")
        return labels
    if text_size or title_size != len(name_payload) - 1:
        raise _UnsupportedSheet("Unexpected text in legacy grouped numeric cells")
    values = []
    for status, width, value in cells:
        stored_integer = status == 105 and value.is_integer()
        if width or (status not in (0, 1) and not stored_integer) or (status and not isfinite(value)):
            raise _UnsupportedSheet("Unrecognized legacy grouped numeric cell status")
        values.append(value if status else None)
    return values


def _sheet_frame(sheet_id, metadata, datasets, remaining_cells, fonts, *, analysis_id=-1):
    layout = _record_once(metadata, 0x8E)
    legacy_layout = unpack_from("<7i", layout) if analysis_id == -1 and len(layout) == 28 else ()
    legacy_source = bool(legacy_layout) and legacy_layout[0] == -1
    legacy_xy = legacy_source and legacy_layout[5:] == (0, 1)
    legacy_column = legacy_source and legacy_layout[4:] == (_PLAIN, 0, 2)
    legacy_limits = (bool(legacy_layout) and legacy_layout[0] >= 0
                     and legacy_layout[1:3] == (44, 3) and legacy_layout[4:] == (_LEGACY_LIMITS_LAYOUT, 0, 1))
    legacy_grouped = (analysis_id == -1 and len(layout) == 32
                      and unpack_from("<7i", layout, 4) == (107, 3, 3, _REPLICATES, 0, 3, 3))
    legacy = legacy_xy or legacy_column or legacy_limits
    modes = (_MEAN_SD, _REPLICATES) if legacy_xy else (_PLAIN, _MEAN_SD, _REPLICATES)
    if legacy_limits:
        mode = _XY_LIMITS
    elif legacy_grouped:
        mode = _REPLICATES
    elif len(layout) < (28 if legacy else 36) or (mode := unpack_from("<i", layout, 16)[0]) not in modes:
        raise _UnsupportedSheet("Unrecognized table layout")

    fields = {}
    linked_x_ids = set()
    for header, records in datasets:
        if len(header) != _DATASET.size:
            raise _UnsupportedSheet("Unrecognized data set header")
        uid, _, _, analysis, owner, storage, _, kind, role, form, repeats, linked_x, _, rows, count = _DATASET.unpack(header)
        if (uid < 0 or uid in fields or analysis != analysis_id or owner != sheet_id
                or storage != (101 if analysis_id == -1 else 102)):
            raise _UnsupportedSheet("Unexpected data set ownership")
        if not 0 < repeats <= MAX_COLUMNS or rows < 0 or count != rows * repeats:
            raise _UnsupportedSheet("Invalid data set dimensions")
        fields[uid] = role, kind, form, repeats, rows, count, records
        if legacy or legacy_grouped:
            linked_x_ids.add(linked_x)

    links = {}
    for tag, payload in metadata:
        if tag != 0x0D:
            continue
        if len(payload) < 12:
            raise _UnsupportedSheet("Truncated column link")
        position, uid, repeats = unpack_from("<III", payload)
        # The older link ends after the first word of the last repeat entry.
        link_size = 12 + 12 * repeats - (8 if legacy else 0)
        if (position >= MAX_COLUMNS or position in links or not 0 < repeats <= MAX_COLUMNS
                or len(payload) != link_size
                or (mode == _PLAIN and repeats != 1) or (mode == _MEAN_SD and repeats != 2)
                or (legacy_limits and (uid == 0xFFFFFFFF or repeats != 3))):
            raise _UnsupportedSheet("Unrecognized column link")
        if legacy_column and (uid == 0xFFFFFFFF or unpack_from("<I", payload, 12)[0] not in (0x7040, 0x7140)):
            raise _UnsupportedSheet("Unrecognized legacy column link")
        if uid != 0xFFFFFFFF and (uid not in fields or fields[uid][:4] != (8, 1, mode, repeats)):
            raise _UnsupportedSheet("Unrecognized column link")
        links[position] = uid
    if sorted(links) != list(range(len(links))):
        raise _UnsupportedSheet("Invalid column order")
    ys = {uid: index + 1 for index, uid in sorted(links.items()) if uid != 0xFFFFFFFF}
    xs = [uid for uid, field in fields.items() if field[:4] == (4, 1, _PLAIN, 1)]
    titles = [uid for uid, field in fields.items() if field[:4] == (_ROW_TITLES, 2, 12, 1)]
    if (len(xs) > 1 or len(titles) > 1 or len(fields) != len(xs) + len(titles) + len(ys)
            or len(ys) != sum(uid != 0xFFFFFFFF for uid in links.values())):
        raise _UnsupportedSheet("Unrecognized column role")
    if legacy_xy and (len(xs) != 1 or titles or linked_x_ids != set(xs)):
        raise _UnsupportedSheet("Unrecognized legacy XY column linkage")
    if legacy_column and (xs or titles or linked_x_ids != {-1}):
        raise _UnsupportedSheet("Unrecognized legacy column linkage")
    if legacy_limits and (len(xs) != 1 or linked_x_ids != set(xs) or titles != [legacy_layout[0]]
                          or len(ys) != legacy_layout[3]):
        raise _UnsupportedSheet("Unrecognized legacy XY limit linkage")
    if legacy_grouped and (xs or titles != [unpack_from("<i", layout)[0]] or linked_x_ids != set(titles)):
        raise _UnsupportedSheet("Unrecognized legacy grouped column linkage")
    if not ys:
        return None

    # The last layout words also occur on Column worksheets. Grouped worksheets
    # in this profile own a row-title dataset even when it has no populated labels.
    grouped = legacy_grouped or (not xs and bool(titles) and analysis_id == -1 and len(layout) == 36
                                 and unpack_from("<i", layout)[0] == titles[0]
                                 and unpack_from("<2i", layout, 20) == (39, 2))
    order = titles + xs + list(ys)
    width = sum(fields[uid][3] for uid in order)
    height = max(fields[uid][4] for uid in order)
    if width > MAX_COLUMNS or width * height > remaining_cells:
        raise ValueError("Legacy binary data tables exceed the size limit.")
    if not height:
        return None

    headers, kinds, columns = [], [], []
    excluded_cells = []
    for uid in order:
        role, _, form, repeats, _, count, records = fields[uid]
        name_payload = _record_once(records, 9)
        name = _title(name_payload)
        if role == _ROW_TITLES:
            if legacy_limits:
                labels = _legacy_limit_values(records, count, xs[0], role)
            elif legacy_grouped:
                labels = _legacy_grouped_cells(records, count, role, name_payload, fonts)
            else:
                labels = _row_titles(records, count, fonts)
            if labels:
                headers.append(name or "Row title")
                kinds.append("text")
                columns.append(labels)
            continue
        rich_title = _record_once(records, 0xD5, required=False)
        if rich_title is not None:
            rich_text = bytes(rich_title[4:])
            if (len(rich_title) < 4 or unpack_from("<I", rich_title)[0] != len(rich_text)
                    or rich_text.split(b"\0", 1)[0] != bytes(name_payload[:-1])):
                raise _UnsupportedSheet("Unrecognized formatted title")
            name = _formatted_label(rich_text, fonts)
        if legacy_limits:
            values = _legacy_limit_values(records, count, xs[0], role)
        elif legacy_grouped:
            values = _legacy_grouped_cells(records, count, role, name_payload, fonts)
        elif legacy:
            values = _legacy_values(records, count, xs[0] if legacy_xy else -1)
        else:
            slots = [] if analysis_id == -1 and role == 8 and form in (_PLAIN, _REPLICATES) else None
            values = _numeric_values(records, count, grouped_integers=grouped and form == _PLAIN and role == 8,
                                     excluded_slots=slots)
            if slots:
                start = len(columns)
                excluded_cells.extend((i // repeats, start + i % repeats) for i in slots)
        if role == 4:
            headers.append(name or "X")
        else:
            name = name.strip() or f"Y{ys[uid]}"
            if form == _MEAN_SD:
                headers.extend(f"{name} [{label}]" for label in ("Mean", "SD"))
            elif form == _XY_LIMITS:
                headers.extend(f"{name} [{label}]" for label in ("Center", "Upper", "Lower"))
            elif repeats == 1:
                headers.append(name)
            else:
                headers.extend(f"{name} [{index + 1}]" for index in range(repeats))
        kinds.extend([None] * repeats)
        columns.extend(values[index::repeats] for index in range(repeats))
    frame = _table(headers, [list(row) for row in zip_longest(*columns)], kinds)
    if excluded_cells:
        frame.attrs["excluded"] = sorted(excluded_cells)
    frame.attrs["table_format"] = "xy" if xs else "grouped" if grouped or mode != _PLAIN else "column"
    if xs or grouped:
        column = len(frame.columns) - sum(fields[uid][3] for uid in ys)
        x_names = [frame.columns[column - 1]] if xs else []
        groups = []
        for uid in ys:
            width = fields[uid][3]
            groups.append(frame.columns[column:column + width].tolist())
            column += width
        frame.attrs["worksheet_roles"] = {"x": x_names, "y": groups}
    if legacy_grouped:
        frame.attrs["legacy_binary_grouped_series"] = tuple(ys)
    return frame


def load_legacy_binary(path, *, restore=False, info_sheets=None, import_warnings=None):
    from .legacy_import import _finish, _store_table

    with path.open("rb") as stream:
        data = stream.read(MAX_ENTRY + 1)
    if len(data) > MAX_ENTRY:
        raise ValueError("Legacy input file exceeds 32 MiB.")
    ids = None
    sheets = {}
    fonts = {}
    current = None
    for tag, parents, payload in _records(data):
        if parents == (1,) and tag == 0x8002:
            if ids is not None:
                raise ValueError("Duplicate legacy binary sheet index.")
            ids = dict.fromkeys(_source_ids(payload))
        elif parents == (1, 2, 6) and tag == 7 and len(payload) == 66:
            font, = unpack_from("<I", payload)
            fonts[font] = bytes(payload[6:38]).split(b"\0", 1)[0]
        elif parents == (1,) and tag == 0x8008:
            if ids is None or len(payload) != 2:
                raise ValueError("Invalid legacy binary sheet header.")
            current, = unpack_from("<H", payload)
            if current not in ids:
                current = None
            elif current in sheets:
                raise ValueError("Duplicate legacy binary source sheet.")
            else:
                sheets[current] = ([], [])
        elif parents == (1,) and tag == 0x4008:
            current = None
        elif current is not None and parents == (1, 8):
            metadata, datasets = sheets[current]
            if tag == 0x800F:
                if len(datasets) > MAX_COLUMNS + 1:
                    raise ValueError("Legacy binary data table exceeds the column limit.")
                datasets.append((payload, []))
            elif tag in (9, 0x0D, 0x8E):
                metadata.append((tag, payload))
        elif current is not None and parents == (1, 8, 0xF):
            sheets[current][1][-1][1].append((tag, payload))

    if ids is None or sheets.keys() != ids.keys():
        raise ValueError("Legacy binary project has an incomplete source sheet index.")
    tables, skipped, cells = {}, [], 0
    sources = {}
    for uid in ids:
        metadata, datasets = sheets[uid]
        title = f"Data {uid + 1}"
        try:
            title = _title(_record_once(metadata, 9)) or title
            frame = _sheet_frame(uid, metadata, datasets, MAX_CELLS - cells, fonts)
        except (_UnsupportedSheet, UnicodeDecodeError):
            skipped.append(title)
            continue
        if frame is not None:
            _store_table(tables, title, frame)
            # Historical recipe matching compares raw grids. Preserve the saved views
            # until a matcher can independently verify a fit on masked observations.
            if not frame.attrs.get("excluded"):
                sources[uid] = frame
            cells += frame.size
    if restore:
        from .legacy_restore import restore_binary_views

        restore_binary_views(data, sources, tables, cells, fonts, path.stem)
    if info_sheets is not None:
        from .legacy_binary_info import read_binary_info

        read_binary_info(data, info_sheets, skipped)
    if not tables and not info_sheets:
        message = "The legacy binary project has no supported populated tables. Save a copy as a ZIP or XML project in the source application."
        if skipped:
            message += " Unsupported sheets: " + ", ".join(skipped)
        raise ValueError(message)
    return _finish(tables, skipped, info_sheets, import_warnings=import_warnings)
