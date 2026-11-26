"""Worksheet headers shared by the Tk and Qt grids."""
import re

_SUBCOLUMN = re.compile(
    r"(.*?) \[([1-9]\d*|Mean|SD|SEM|CV%|N|Center|Plus|Minus|Upper|Lower|Value|Error)\]( \(\d+\))?"
)

def column_label(index):
    label = ""
    while index >= 0:
        index, letter = divmod(index, 26)
        label = chr(65 + letter) + label
        index -= 1
    return label


NATIVE_XY_FORMATS = frozenset({"xy", "xy with replicates", "xy with precomputed error"})


def xy_source_roles(frame, table_format):
    """The X block and Y groups of a native XY worksheet, including implicit headings."""
    if table_format.casefold() not in NATIVE_XY_FORMATS:
        return None
    if roles := frame.attrs.get("worksheet_roles"):
        return roles
    names = list(frame.columns)
    bands, _ = heading_bands(frame, names, len(names), table_format)
    return {
        "x": [name for name, (_, _, band, _) in zip(names, bands, strict=True) if band == "X"],
        "y": [names[first:stop] for column, (first, stop, band, _) in enumerate(bands)
              if column == first and band.startswith("Group ")],
    }


def xy_replicate_groups(frame, table_format):
    """Return uniform, sequential replicate groups that can be resized in place."""
    if table_format.casefold() != "xy with replicates" or "legacy_columns" in frame.attrs:
        return ()
    names = list(frame.columns)
    bands, _ = heading_bands(frame, names, len(names), table_format)
    groups = []
    for column, (first, stop, band, title) in enumerate(bands):
        if column != first or not band.startswith("Group "):
            continue
        members = names[first:stop]
        if members != [f"{title} [{index}]" for index in range(1, len(members) + 1)]:
            return ()
        if len(members) < 2 or (groups and len(members) != len(groups[0][1])):
            return ()
        groups.append((title, members))
    return groups


def heading_bands(frame, names, source_columns, table_format, *, calculated=None):
    """Map each visible column to its display band and optional subcolumn role."""
    if calculated is None:
        calculated = set(range(source_columns, len(names)))
    kind = (table_format or "").casefold()
    xy = kind == "xy" or kind.startswith("xy ")
    if kind == "column":
        group = 0
        bands = []
        for index, name in enumerate(names):
            if name.casefold() in {"row title", "row titles"}:
                label = "Row titles"
            elif index not in calculated:
                label = f"Group {column_label(group)}"
                group += 1
            else:
                label = column_label(index)
            bands.append((index, index + 1, label, name))
        return bands, []
    if not (xy or kind in {"grouped", "twoway", "two way", "nested"}):
        return [(col, col + 1, column_label(col), name) for col, name in enumerate(names)], []

    columns = frame.attrs.get("legacy_columns", {})
    x_names = set(columns.get(frame.attrs.get("legacy_x"), []))
    y_groups = {name: key for key in frame.attrs.get("legacy_y", [])
                for name in columns.get(key, [])}
    stored = frame.attrs.get("worksheet_roles")
    if stored is not None:
        x_names = set(stored["x"])
        y_groups = {name: index for index, group in enumerate(stored["y"]) for name in group}
    row_title = names and 0 not in calculated and (
        names[0].casefold() in {"row title", "row titles"}
        or (y_groups and names[0] not in y_groups and names[0] not in x_names))
    first_data = int(bool(row_title))
    subcolumns = [_SUBCOLUMN.fullmatch(name) for name in names]
    if (xy and stored is None and "legacy_x" not in frame.attrs and first_data + 1 < len(names)
            and calculated.isdisjoint((first_data, first_data + 1))):
        first, second = subcolumns[first_data:first_data + 2]
        first_name = names[first_data]
        if second and second[2] == "Error" and second[1] == (first[1] if first else first_name):
            x_names.update(names[first_data:first_data + 2])
        elif not (first and second and first[1] == second[1] and first[3] == second[3]):
            # Adjacent replicates can start an XY sheet with implicit X values.
            x_names.add(first_name)

    bands, roles, group = [], [], 0
    start = 0
    while start < len(names):
        stop = start + 1
        title, band, role = names[start], "", ""
        if start in calculated:
            band, role = column_label(start), "Formula"
        elif start < first_data:
            band = "Row titles"
        else:
            is_x = xy and title in x_names
            match = subcolumns[start]
            if is_x:
                while stop < len(names) and stop not in calculated and names[stop] in x_names:
                    stop += 1
                band, role = "X", "X"
            else:
                if kind == "nested" and title in y_groups:
                    while (stop < len(names) and stop not in calculated
                           and y_groups.get(names[stop]) == y_groups[title]):
                        stop += 1
                else:
                    while (match and stop < len(names) and stop not in calculated and (next_match := subcolumns[stop])
                           and next_match[1] == match[1] and next_match[3] == match[3]
                           and y_groups.get(names[stop]) == y_groups.get(names[start])
                           and names[stop] not in x_names):
                        stop += 1
                band, role = f"Group {column_label(group)}", "Y" if xy else ""
                group += 1
            if stop - start > 1:
                if match:
                    title = match[1] + (match[3] or "")
                for column, subcolumn in enumerate(subcolumns[start:stop], start):
                    label = subcolumn[2] if subcolumn else role
                    if is_x and stored is not None and kind in NATIVE_XY_FORMATS and len(stored["x"]) == 2:
                        label = "Error" if names[column] == stored["x"][1] else "X"
                    if xy and not is_x and label.isdigit():
                        label = f"Y{label}"
                    roles.append(label)
        if stop == start + 1:
            roles.append(role)
        bands.extend([(start, stop, band, title)] * (stop - start))
        start = stop
    return bands, roles
