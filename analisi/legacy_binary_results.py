"""Recover analysis-owned result grids and verified paired tests from legacy project files."""

from decimal import Decimal
from itertools import zip_longest
from math import isfinite
import re
from struct import Struct, pack, unpack_from

from scipy import stats

from .data import MAX_CELLS, MAX_COLUMNS, _table
from .legacy_binary import (
    _DATASET, _NUMERIC_CELL, _PLAIN, _REPLICATES, _UnsupportedSheet, _cell_storage, _formatted_label,
    _numeric_values, _record_once, _records, _sheet_frame, _source_ids,
)
from .legacy_import import _store_table
from .legacy_restore import LEGACY_NOTES, LEGACY_TITLE

_TEXT_MODE = 12
_RESULT_STORAGE = 102
_TEXT_ENTRY = Struct("<III")
_ANALYSIS_TAGS = {9, 0x3B, 0x3C, 0x3D, 0x3F, 0x46}
_SHEET_TAGS = {9, 0x0D, 0x8E}
_DATASET_TAGS = {9, 0x10, 0x11, 0x64, 0x90, 0xB6, 0xD5, 0xF3}
_EXPLICIT_NUMERIC = {(1, 1, 0x00100000), (1, 1, 0x28001800)}
_FORMATTED_SIMULATION_X = (1, 4, 0x20001002)
_GENERATED_X = {(1, 4, 0x20001000), _FORMATTED_SIMULATION_X, (1, 4, 0x20001800)}
_UNLINKED_GENERATED_X = (1, 4, 0x1802)
_CLASSIC_GENERATED_X = {(1, 4, 0x20001801), (1, 4, 0x20001001), (1, 4, 0x1801)}
_FRACTION_OF_TOTAL_VIEW = (1, 1, 0x00140400)
_DECIMAL = re.compile(r"[+-]?\d{1,24}(?:\.\d{1,24})?(?:[Ee][+-]?\d{1,3})?")


def _analysis_ids(header):
    # The project header reserves a 500-entry source array before the analysis list.
    count, = unpack_from("<I", header, 44)
    if count > 500:
        return None
    ids = unpack_from(f"<{count}i", header, 2060)
    if len(set(ids)) != count or any(not 0 <= uid <= 65535 for uid in ids):
        return None
    return ids


def _read_groups(data):
    analyses, sheets, companions = {}, {}, {}
    indexed = set()
    analysis_ids = None
    current = None
    for tag, parents, payload in _records(data):
        if parents == (1,) and tag == 0x8002:
            indexed = set(_source_ids(payload))
            analysis_ids = _analysis_ids(payload)
        elif parents == (1,) and tag in (0x8039, 0x80E1, 0x8008):
            current = None
            if len(payload) == 2:
                uid, = unpack_from("<H", payload)
                target = {0x8039: analyses, 0x80E1: companions, 0x8008: sheets}[tag]
                current = (uid, [], [])
                # A repeated identifier cannot be used to establish ownership.
                target[uid] = None if uid in target else current[1:]
        elif current is not None and parents in ((1, 0x39), (1, 0xE1)):
            if tag in _ANALYSIS_TAGS or (parents[-1] == 0xE1 and tag == 0x3A):
                current[1].append((tag, payload))
        elif current is not None and parents == (1, 8):
            if tag in _SHEET_TAGS:
                current[1].append((tag, payload))
            elif tag == 0x800F and current[0] not in indexed:
                current[2].append((payload, []))
        elif (current is not None and current[2] and parents == (1, 8, 0xF)
                and tag in _DATASET_TAGS):
            current[2][-1][1].append((tag, payload))
    return analyses, sheets, indexed, analysis_ids, companions


def _title(payload):
    value = bytes(payload)
    if not value.endswith(b"\0") or b"\0" in value[:-1] or len(value) > 4096:
        raise _UnsupportedSheet("Unrecognized saved-result title")
    return value[:-1].decode("cp1252")


def _result_text(payload, fonts):
    plain, separator, formats = payload.partition(b"\0")
    if separator:
        # The observed display runs use one-byte lengths and the Arial font.
        if (not formats or len(formats) % 3 or sum(formats[::3]) != len(plain)
                or any(length == 0 or style != 1 or fonts.get(font - 1) != b"Arial"
                       for length, style, font in Struct("<BBB").iter_unpack(formats))):
            raise _UnsupportedSheet("Unrecognized saved-result text formatting")
    return plain.decode("cp1252")


def _text_values(records, count, fonts):
    cells, attributes, stride = _cell_storage(records, count, text=True)
    index = _record_once(records, 0xB6)
    pool = _record_once(records, 0x11, required=False)
    if len(index) < 4:
        raise _UnsupportedSheet("Truncated saved-result text index")
    entries, = unpack_from("<I", index)
    tail = 4 if stride == 28 else 0
    if len(index) != 4 + _TEXT_ENTRY.size * entries + tail or entries > count:
        raise _UnsupportedSheet("Invalid saved-result text index")
    if pool is None and not entries:
        pool = memoryview(bytes(4))
    if pool is None or len(pool) < 4 or unpack_from("<I", pool)[0] != len(pool) - 4:
        raise _UnsupportedSheet("Invalid saved-result text pool")

    result = [None] * count
    previous_end = 0
    for row, start, size in _TEXT_ENTRY.iter_unpack(index[4:len(index) - tail]):
        end = start + size
        # Stored spans increase monotonically. Disjoint spans bound text allocations by pool size.
        if (row >= count or not 0 < size <= 4096 or start < previous_end
                or end > len(pool) - 4 or result[row] is not None):
            raise _UnsupportedSheet("Invalid saved-result text reference")
        result[row] = _result_text(bytes(pool[4 + start:4 + end]), fonts)
        previous_end = end
    for row, (status, _, _) in enumerate(cells):
        # 0x800001 is observed on visible section headings in saved result grids.
        if (status not in (0, 1, 0x800001) or bool(status) != (result[row] is not None)
                or stride >= 16 and unpack_from("<I", attributes, row * stride + 4)[0] != status):
            raise _UnsupportedSheet("Unrecognized saved-result cell status")
    return result


def _column_ids(records, remaining=MAX_COLUMNS):
    links = {}
    for tag, payload in records:
        if tag != 0x0D:
            continue
        if len(payload) != 24:
            raise _UnsupportedSheet("Unrecognized saved-result column link")
        position, uid, repeats = unpack_from("<III", payload)
        if position in links or position >= remaining or repeats != 1 or uid == 0xFFFFFFFF:
            raise _UnsupportedSheet("Invalid saved-result column link")
        links[position] = uid
    if sorted(links) != list(range(len(links))) or len(set(links.values())) != len(links):
        raise _UnsupportedSheet("Invalid saved-result column order")
    return tuple(links[position] for position in range(len(links)))


def _text_snapshot(sheet_id, analysis_id, metadata, datasets, layout, remaining_cells, fonts):
    if len(datasets) > MAX_COLUMNS:
        raise _UnsupportedSheet("Saved-result table exceeds the column limit")
    title_uid, = unpack_from("<i", layout)
    columns = (title_uid, *_column_ids(metadata, MAX_COLUMNS - 1))
    fields = {}
    for header, records in datasets:
        if len(header) != _DATASET.size:
            raise _UnsupportedSheet("Invalid saved-result data set header")
        uid, _, _, analysis, owner, storage, _, kind, role, form, repeats, _, _, rows, count = _DATASET.unpack(header)
        if (uid < 0 or uid in fields or analysis != analysis_id or owner != sheet_id or storage != _RESULT_STORAGE
                or kind != 2 or role not in ((4, 256) if uid == title_uid else (8,))
                or form != _TEXT_MODE or repeats != 1 or count != rows or rows < 0):
            raise _UnsupportedSheet("Unrecognized saved-result data set")
        fields[uid] = count, records
    if not columns[1:] or len(fields) != len(columns) or set(fields) != set(columns):
        raise _UnsupportedSheet("Saved-result data sets do not match the table links")
    if len(columns) * max(count for count, _ in fields.values()) > remaining_cells:
        raise _UnsupportedSheet("Saved-result table exceeds the size limit")

    headers, values = [], []
    for uid in columns:
        count, records = fields[uid]
        headers.append(_title(_record_once(records, 9)))
        values.append(_text_values(records, count, fonts))
    if not any(value is not None for column in values for value in column):
        return None
    return _table(headers, [list(row) for row in zip_longest(*values)], ["text"] * len(headers))


def _view_kind(records, slot):
    kinds = []
    for tag, payload in records:
        if tag == 0x3F and len(payload) in (28, 32):
            _, active, view_type, flags, position = unpack_from("<5i", payload)
            if position == slot:
                kinds.append((active, view_type, flags))
    return kinds[0] if len(kinds) == 1 else None


def _x_sequence(records, rows, *, source_free=False, formatted_curve=False):
    # Sequence records use two single- or double-precision slots for origin and step.
    # The latter has a zero status in this layout even when its step is active.
    contents = _record_once(records, 0x10)
    attributes = _record_once(records, 0xF3)
    if len(contents) < 6:
        raise _UnsupportedSheet("Truncated saved X sequence")
    precision, count = unpack_from("<HI", contents)
    attributes_short = Struct("<6I").pack(1, 16, 4, 2, 0, 0)
    attributes_long = Struct("<12I").pack(2, 16, 16, 2, 0, 1, 0, 0, 0, 0, 0, 0)
    if (precision not in (0, 1) or count != 2 or len(contents) != 6 + 2 * _NUMERIC_CELL[precision].size
            or _record_once(records, 0x90) != (b"\1\0" if source_free else b"\0\0")):
        raise _UnsupportedSheet("Unrecognized saved X sequence")
    title_runs = _record_once(records, 0x64, required=False)
    if title_runs is not None:
        rich = _record_once(records, 0xD5)
        _, _, formatting = bytes(rich[4:]).partition(b"\0")
        if not formatting or title_runs != formatting + b"\0":
            raise _UnsupportedSheet("Unrecognized saved X title formatting")
    (first, first_style, start), (second, second_style, step) = _NUMERIC_CELL[precision].iter_unpack(contents[6:])
    standard = ((first, first_style, second, second_style) == (1, 0, 0, 0)
                and (attributes == attributes_long or precision == 0 and attributes == attributes_short))
    formatted_step = second in (1, first) or (first, second, second_style) == (1, 0, 0)
    formatted = (formatted_curve and precision == 1 and first in (1, 5) and first_style == 0
                 and formatted_step and second_style <= 255
                 and attributes == Struct("<12I").pack(2, 16, 16, 2, 0, first, 0xFFFFFFFF, 0x7FFFFFFF,
                                                        0, second, 0xFFFFFFFF, 0x7FFFFFFF))
    if (not (standard or formatted) or not isfinite(start) or not isfinite(step)
            or step <= 0 or not isfinite(start + (rows - 1) * step)):
        raise _UnsupportedSheet("Invalid saved X sequence")
    return [start + index * step for index in range(rows)]


def _formatted_simulation_values(records, rows):
    cells, attributes, stride = _cell_storage(records, rows)
    if stride != 16:
        raise _UnsupportedSheet("Unrecognized simulation result attributes")
    values = []
    for index, (status, width, value) in enumerate(cells):
        if (status != 1 or width > 255 or not isfinite(value)
                or unpack_from("<4I", attributes, index * stride) != (0, 1, 0xFFFFFFFF, 0x7FFFFFFF)):
            raise _UnsupportedSheet("Unrecognized formatted simulation value")
        values.append(value)
    return values


def _sequence_snapshot(sheet_id, analysis_id, metadata, datasets, layout, remaining_cells, fonts,
                       *, source_free=False, formatted_curve=False, formatted_simulation=False):
    row_title_id, = unpack_from("<i", layout)
    if len(datasets) > MAX_COLUMNS or (row_title_id != -1 and not formatted_curve):
        return None
    x_uid = None
    title_x = None
    fields = {}
    for header, records in datasets:
        if len(header) != _DATASET.size:
            raise _UnsupportedSheet("Invalid curve data set header")
        uid, _, _, analysis, owner, storage, _, kind, role, form, repeats, linked_x, _, rows, count = (
            _DATASET.unpack(header)
        )
        if (uid < 0 or uid in fields or analysis != analysis_id or owner != sheet_id
                or storage != _RESULT_STORAGE or repeats != 1 or count != rows or rows < 0):
            raise _UnsupportedSheet("Invalid curve data set ownership or dimensions")
        if uid == row_title_id:
            if (title_x is not None or (kind, role, form, rows) != (2, 256, _TEXT_MODE, 0)
                    or _record_once(records, 9) != b"\0" or _record_once(records, 0x10) != bytes(6)
                    or _record_once(records, 0xB6) != pack("<2I", 0, uid)
                    or any(tag not in (9, 0x10, 0x90, 0xB6, 0xF3) for tag, _ in records)):
                raise _UnsupportedSheet("Unrecognized empty curve row-title field")
            title_x = linked_x
            continue
        if ((kind, role, form) == (4, 4, 11)
                and rows in ((0, 1) if source_free or formatted_simulation else (0,)) and x_uid is None):
            x_uid = uid
        elif (kind, role, form) != (1, 40, _PLAIN):
            return None
        fields[uid] = (linked_x, rows, records)
    y_uids = _column_ids(metadata, MAX_COLUMNS - 1)
    if x_uid is None or not y_uids or set(fields) != {x_uid, *y_uids} or x_uid in y_uids:
        raise _UnsupportedSheet("Unrecognized saved curve column order")
    if row_title_id != -1 and title_x != x_uid:
        raise _UnsupportedSheet("Invalid saved curve row-title link")
    if any(fields[uid][0] != x_uid for uid in y_uids):
        raise _UnsupportedSheet("Saved curve series do not share the same X sequence")
    height = max(fields[uid][1] for uid in y_uids)
    if not height:
        return None
    if len(fields) * height > remaining_cells:
        raise _UnsupportedSheet("Saved curve exceeds the size limit")
    x_records = fields[x_uid][2]
    formatted_simulation = formatted_simulation and fields[x_uid][1] == 1
    columns = [_x_sequence(x_records, height, source_free=source_free,
                           formatted_curve=formatted_curve or formatted_simulation)]
    read_values = _formatted_simulation_values if formatted_simulation else _numeric_values
    headers = []
    for position, uid in enumerate((x_uid, *y_uids)):
        _, rows, records = fields[uid]
        name_payload = _record_once(records, 9)
        title = _title(name_payload)
        rich = _record_once(records, 0xD5, required=False)
        if rich is not None:
            content = bytes(rich[4:])
            if (len(rich) < 4 or unpack_from("<I", rich)[0] != len(content)
                    or content.split(b"\0", 1)[0] != bytes(name_payload[:-1])):
                raise _UnsupportedSheet("Unrecognized saved curve column title")
            title = _formatted_label(content, fonts)
        headers.append(title or (f"Y{position}" if position else "X"))
        if position:
            columns.append(read_values(records, rows))
    # A shorter series uses a prefix of the common X sequence. Missing cells
    # inside that prefix remain missing as well.
    return _table(headers, [list(row) for row in zip_longest(*columns)])


def _matches_display(value, saved, extra=0):
    if not isinstance(saved, str) or not _DECIMAL.fullmatch(saved) or not isfinite(value):
        return False
    parsed = Decimal(saved)
    precision = parsed.as_tuple().exponent
    if abs(precision) > 300:
        return False
    return abs(value - float(parsed)) <= (0.5 + 1e-10) * 10.0 ** precision + extra


def _paired_t(first, second, differences, rows):
    result = stats.ttest_rel(first, second)
    interval = result.confidence_interval()
    summary = re.fullmatch(r"t=([^ ]+) df=(\d+)", rows.get("t, df", ""))
    endpoints = rows.get("95% confidence interval", "").split(" to ")
    if not summary or len(endpoints) != 2:
        return False
    # Older stored intervals can use a critical t rounded to three decimals.
    interval_tolerance = float(stats.sem(differences)) * .0005
    return (summary[2] == str(result.df)
            and _matches_display(abs(result.statistic), summary[1])
            and _matches_display(result.pvalue, rows.get("P value"))
            and _matches_display(differences.mean(), rows.get("Mean of differences"))
            and _matches_display(interval.low, endpoints[0], interval_tolerance)
            and _matches_display(interval.high, endpoints[1], interval_tolerance))


def _wilcoxon(first, second, differences, rows):
    if len(differences) > 50 or rows.get("Exact or approximate P value?") != "Exact":
        return False
    nonzero = differences[differences != 0]
    if not len(nonzero):
        return False
    ranks = stats.rankdata(abs(nonzero))
    signed_ranks = ranks[nonzero > 0].sum() - ranks[nonzero < 0].sum()
    result = stats.wilcoxon(first, second)
    return (_matches_display(result.pvalue, rows.get("P value"))
            and _matches_display(signed_ranks, rows.get("Sum of signed ranks (W)")))


def _paired_recipe(frame, snapshot, records, source_metadata):
    if (frame.attrs.get("table_format") != "column" or len(frame.columns) != 2
            or len(frame) > 10_000 or len(snapshot.columns) != 2):
        return None
    params = _record_once(records, 0x46, required=False)
    links = _record_once(records, 0x3D, required=False)
    if params is None or len(params) != 1348 or links is None or len(links) != 26:
        return None
    flags, block = unpack_from("<II", params)
    count, id_a, _, repeat_a, id_b, _, repeat_b = unpack_from("<H6i", links)
    if (block != 3451 or flags not in (5, 7, 0x805) or count != 2 or (repeat_a, repeat_b) != (-1, -1)
            or _column_ids(source_metadata) != (id_a, id_b)):
        return None

    recipe_labels = {
        "Column A", "Column B", "One- or two-tailed P value?", "Number of pairs", "P value",
        "Paired t test", "t, df", "Mean of differences", "95% confidence interval",
        "Wilcoxon matched-pairs signed rank test", "Exact or approximate P value?", "Sum of signed ranks (W)",
    }
    rows = {}
    for label, value in snapshot.itertuples(index=False, name=None):
        if isinstance(label, str) and (label := label.strip()) in recipe_labels:
            if label in rows:
                return None
            rows[label] = value if isinstance(value, str) else ""
    a, b = frame.columns
    if rows.get("Column A") != a or rows.get("Column B") != b:
        return None
    if rows.get("One- or two-tailed P value?") != "Two-tailed":
        return None
    if flags == 0x805:
        a, b = b, a
    pairs = frame[[a, b]].dropna()
    if len(pairs) < 2 or rows.get("Number of pairs") != str(len(pairs)):
        return None
    first, second = pairs.to_numpy(dtype=float).T
    differences = first - second
    if (flags == 7 and "Paired t test" in rows and (differences != differences[0]).any()
            and _paired_t(first, second, differences, rows)):
        return "Paired t-test (columns)", {"First": a, "Second": b,
                LEGACY_NOTES: "Recalculates the two-tailed paired test in the saved column order. "
                             "Trama reports a signed t statistic and native confidence limits."}
    if (flags in (5, 0x805) and "Wilcoxon matched-pairs signed rank test" in rows
            and _wilcoxon(first, second, differences, rows)):
        return "Wilcoxon signed-rank", {"First": a, "Second": b,
                LEGACY_NOTES: "Recalculates the two-tailed paired test in the saved column order. "
                             "Trama reports the smaller rank sum."}
    return None


def _fraction_source(records, companion, indexed):
    if companion is None:
        raise _UnsupportedSheet("Missing saved fraction-of-total links")
    extension, _ = companion
    descriptor = _record_once(extension, 0x3A)
    inputs = _record_once(extension, 0x3B)
    if (len(descriptor) != 16 or unpack_from("<H", descriptor)[0] != 29
            or len(inputs) != 8 or unpack_from("<i", inputs)[0] != 1
            or _record_once(records, 0x3B) != bytes(4)
            or _record_once(records, 0x3C) != _record_once(extension, 0x3C)
            or _record_once(records, 9) != _record_once(extension, 9)
            or _view_kind(extension, 0) != _FRACTION_OF_TOTAL_VIEW):
        raise _UnsupportedSheet("Inconsistent saved fraction-of-total links")
    source_id, = unpack_from("<i", inputs, 4)
    if source_id not in indexed:
        raise _UnsupportedSheet("Invalid saved fraction-of-total source")
    return (source_id,)


def report_saved_result_warnings(tables, unavailable, unreadable=0):
    warnings = []
    if unreadable:
        warnings.append(f"Some saved content could not be read ({unreadable}).")
    if unavailable:
        label = "analysis" if len(unavailable) == 1 else "analyses"
        warnings.append(f"Recalculation unavailable for {len(unavailable)} saved {label}.")
    if tables and warnings:
        next(iter(tables.values())).attrs.setdefault("import_warnings", []).append("Project import · " + " ".join(warnings))


def restore_binary_results(data, sources, tables, cells, fonts, *, dose_curves=None, classic_curves=None,
                           calibration_curves=None, global_curves=None, pade_curves=None, pending_analyses=None):
    """Add verified snapshots and attach matching native recipes to the original source grids."""
    analyses, sheets, indexed, analysis_ids, companions = _read_groups(data)
    from .legacy_binary_dose import classic_fit_models, early_fit_inputs, restore_dose_recipes

    early_inputs = {}
    if companions:
        from .legacy_binary_global import EARLY_GLOBAL_PROFILES

        early_inputs = early_fit_inputs(data, companions, indexed, profiles=EARLY_GLOBAL_PROFILES)
    has_model_settings = any(
        tag == 0x46 and len(payload) == 1348 for entry in analyses.values() if entry
        for tag, payload in entry[0]
    )
    classic_models = classic_fit_models(data) if has_model_settings else {}
    unavailable = set()
    snapshots = {}
    may_have_dose_fits = False
    unreadable = int(analysis_ids is None)
    for analysis_id in analysis_ids or ():
        analysis = analyses.get(analysis_id)
        if analysis is None:
            unreadable += 1
            continue
        records, _ = analysis
        try:
            analysis_title = _title(_record_once(records, 9))
            inputs = _record_once(records, 0x3B)
            outputs = _record_once(records, 0x3C)
            if len(inputs) < 4 or len(outputs) not in (40, 44):
                raise _UnsupportedSheet("Unsupported saved-result links")
            source_count, = unpack_from("<i", inputs)
            slots, = unpack_from("<i", outputs)
            if not 0 <= source_count <= 256 or len(inputs) != 4 + source_count * 4 or len(outputs) != 4 + slots * 4:
                raise _UnsupportedSheet("Invalid saved-result links")
            source_ids = unpack_from(f"<{source_count}i", inputs, 4)
            if analysis_id in early_inputs:
                source_ids = (early_inputs[analysis_id][0],)
            result_ids = {slot: uid for slot, uid in enumerate(unpack_from(f"<{slots}i", outputs, 4)) if uid != -1}
            if (len(set(result_ids.values())) != len(result_ids)
                    or any(not 0 <= uid <= 65535 for uid in result_ids.values())
                    or any(not 0 <= uid <= 65535 for uid in source_ids)):
                raise _UnsupportedSheet("Invalid saved-result identifiers")
        except (_UnsupportedSheet, UnicodeDecodeError):
            unreadable += 1
            continue

        saved = restored = False
        for slot, sheet_id in result_ids.items():
            try:
                if sheet_id in indexed or sheets.get(sheet_id) is None:
                    raise _UnsupportedSheet("Saved-result sheet ownership is ambiguous")
                metadata, datasets = sheets[sheet_id]
                layout = _record_once(metadata, 0x8E)
                if len(layout) < 36:
                    raise _UnsupportedSheet("Truncated saved-result table layout")
                mode, = unpack_from("<i", layout, 16)
                view_kind = _view_kind(records, slot)
                if mode == _TEXT_MODE:
                    frame = _text_snapshot(sheet_id, analysis_id, metadata, datasets, layout, MAX_CELLS - cells, fonts)
                elif mode in (_PLAIN, _REPLICATES) and (
                        view_kind in _EXPLICIT_NUMERIC or
                        (mode == _PLAIN and slot == 0 and view_kind == _FRACTION_OF_TOTAL_VIEW)):
                    if view_kind == _FRACTION_OF_TOTAL_VIEW:
                        source_ids = _fraction_source(records, companions.get(analysis_id), indexed)
                    if len(datasets) > MAX_COLUMNS + 1:
                        raise _UnsupportedSheet("Saved-result table exceeds the column limit")
                    frame = _sheet_frame(sheet_id, metadata, datasets, MAX_CELLS - cells, fonts, analysis_id=analysis_id)
                elif mode == _PLAIN and (view_kind in _GENERATED_X
                        or (slot == 0 and not source_ids and view_kind == _UNLINKED_GENERATED_X)
                        or (slot == 2 and analysis_id in classic_models and view_kind in _CLASSIC_GENERATED_X)):
                    formatted_simulation = slot == 0 and not source_ids and view_kind == _FORMATTED_SIMULATION_X
                    frame = _sequence_snapshot(sheet_id, analysis_id, metadata, datasets, layout,
                                               MAX_CELLS - cells, fonts, formatted_curve=analysis_id in early_inputs,
                                               formatted_simulation=formatted_simulation)
                else:
                    continue
                if frame is None:
                    continue
                if len(tables) >= 256:
                    raise _UnsupportedSheet("Saved-result table limit exceeded")
                title = _title(_record_once(metadata, 9)) or f"Results {sheet_id + 1}"
            except ValueError:
                unreadable += 1
                continue

            frame.attrs["table_format"] = "Imported result snapshot"
            frame.attrs["legacy_binary_result"] = {
                "analysis_id": analysis_id, "sheet_id": sheet_id, "source_ids": list(source_ids),
                "analysis_title": analysis_title, "sheet_title": title,
            }
            _store_table(tables, f"Imported result · {title}", frame)
            cells += frame.size
            saved = True
            if sheet_id in snapshots or len(source_ids) != 1:
                snapshots[sheet_id] = None
            else:
                snapshots[sheet_id] = (analysis_id, source_ids[0], slot)

            if (mode == _TEXT_MODE and not restored and len(source_ids) == 1
                    and (source := sources.get(source_ids[0])) is not None):
                try:
                    recipe = _paired_recipe(source, frame, records, sheets[source_ids[0]][0])
                except (TypeError, ValueError):
                    recipe = None
                if recipe:
                    method, options = recipe
                    label = method.removesuffix(" (columns)")
                    label = f"{(analysis_title or title)[:156 - len(label)]} · {label}"
                    source.attrs.setdefault("legacy_recipes", []).append((method, {**options, LEGACY_TITLE: label}))
                    restored = True
        if saved and not restored:
            unavailable.add(analysis_id)
            may_have_dose_fits |= any(tag == 0x46 and len(payload) == 1348
                                      and payload[:4] == b"\x00\x21\x80\x00" for tag, payload in records)
    if may_have_dose_fits or early_inputs or classic_models:
        restored = restore_dose_recipes(data, sources, sheets, snapshots, unavailable, curves=dose_curves,
                                        early_inputs=early_inputs, classic_models=classic_models,
                                        classic_curves=classic_curves, calibration_curves=calibration_curves)
        unavailable.difference_update(restored)
    if global_curves is not None and unavailable:
        from .legacy_binary_global import global_candidates

        global_curves.update(global_candidates(data, sources, sheets, snapshots, unavailable, early_inputs=early_inputs))
    if pade_curves is not None and unavailable:
        from .legacy_binary_dose import pade_candidates

        pade_curves.update(pade_candidates(data, sources, sheets, snapshots, classic_models, unavailable))
    if pending_analyses is not None:
        pending_analyses.update(unavailable)
        unavailable = ()
    report_saved_result_warnings(tables, unavailable, unreadable)
    return cells
