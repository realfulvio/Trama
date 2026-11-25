"""Read verified Info records from legacy PCFFGRA4 projects."""

from struct import unpack_from

from .i18n import tr
from .info import InfoSheet, MAX_INFO_FIELDS, MAX_INFO_NAME, MAX_INFO_SHEETS, MAX_INFO_VALUE
from .legacy_binary import _records


def _text(payload, limit, encoding):
    if not 1 <= len(payload) <= limit + 1:
        raise ValueError("Invalid legacy Info text size.")
    raw = bytes(payload)
    if not raw.endswith(b"\0") or b"\0" in raw[:-1]:
        raise ValueError("Invalid legacy Info text.")
    return raw[:-1].decode(encoding).replace("\r\n", "\n").replace("\r", "\n")


def _notes(records, encoding):
    if not records:
        return ""
    if (len(records) > 2 or records[0][0] != 0x802B or len(records[0][1]) != 18
            or bytes(records[0][1][:2]) != b"\xff\xff"):
        raise ValueError("Invalid legacy Info notes header.")
    # The unnumbered Info text object stores a byte count at offset 6.
    # The 0x2C child is text without a NUL terminator. Style and font
    # records are separate from the editable text.
    size, = unpack_from("<H", records[0][1], 6)
    if len(records) == 1 and not size:
        return ""
    if len(records) != 2 or records[1][0] != 0x2C or len(records[1][1]) != size:
        raise ValueError("Invalid legacy Info notes length.")
    value = bytes(records[1][1]).decode(encoding)
    if any(not char.isprintable() and char not in "\r\n\t\u00a0\u00ad" for char in value):
        raise ValueError("Unsupported characters in legacy Info notes.")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _sheet(records, title, encoding, notes):
    headers = [payload for tag, payload in records if tag == 0x6D]
    if len(headers) != 1 or len(headers[0]) != 20:
        raise ValueError("Invalid legacy Info header.")
    count, = unpack_from("<I", headers[0], 4)
    fields = [(tag, payload) for tag, payload in records if tag in (0x6E, 0x6F)]
    if count > MAX_INFO_FIELDS or [tag for tag, _ in fields] != [0x6E, 0x6F] * count:
        raise ValueError("Invalid legacy Info field pairs.")
    rows = tuple((_text(name, MAX_INFO_NAME, encoding), _text(value, MAX_INFO_VALUE, encoding))
                 for (_, name), (_, value) in zip(fields[::2], fields[1::2], strict=True))
    # The first header integer references an internal constants table. It is
    # not the optional link to a user worksheet.
    return InfoSheet(title, rows, notes)


def read_binary_info(data, target, skipped):
    order, groups, note_records, current = (), {}, {}, None
    for tag, parents, payload in _records(data):
        if parents == (1,) and tag == 0x8002:
            # The final 500-slot index orders the Info section.
            count, = unpack_from("<I", payload, 56)
            if count > MAX_INFO_SHEETS:
                skipped.append("Imported Info section")
                return
            order = unpack_from(f"<{count}i", payload, 8060)
            if len(set(order)) != count or any(not 0 <= uid <= 65535 for uid in order):
                skipped.append("Imported Info section")
                return
            codepage = unpack_from("<I", payload, 10064)[0] if len(payload) == 10068 else 1252
            encoding = f"cp{codepage}" if codepage in (1251, 1252) else "ascii"
            groups = dict.fromkeys(order)
            note_records = {uid: [] for uid in order}
        elif parents == (1,) and tag == 0x8038:
            current = None
            if len(payload) == 2:
                uid, = unpack_from("<H", payload)
                if uid in groups:
                    current = [] if groups[uid] is None else False
                    groups[uid] = current
        elif parents == (1, 56) and isinstance(current, list) and tag in (9, 0x6D, 0x6E, 0x6F):
            if len(current) >= 2 + 2 * MAX_INFO_FIELDS:
                groups[uid] = current = False
            else:
                current.append((tag, payload))
        elif isinstance(current, list) and (
                (parents == (1, 56) and tag == 0x802B) or (parents == (1, 56, 43) and tag == 0x2C)):
            notes = note_records[uid]
            if len(notes) < 3:
                notes.append((tag, payload))
    for uid in order:
        title = f"Info sheet {uid + 1}"
        try:
            records = groups[uid]
            if not records:
                raise ValueError("Missing legacy Info sheet.")
            names = [payload for tag, payload in records if tag == 9]
            if len(names) != 1:
                raise ValueError("Invalid legacy Info sheet title.")
            title = _text(names[0], MAX_INFO_NAME, encoding) or title
            try:
                notes = _notes(note_records[uid], encoding)
            except ValueError:
                skipped.append(tr("import.skipped_info_note", name=title))
                notes = ""
            target.append(_sheet(records, title, encoding, notes))
        except ValueError:
            skipped.append(title)
