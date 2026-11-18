from pathlib import Path
import struct
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from analisi.prism_binary import load_prism_binary


def record(tag, payload):
    return struct.pack("<HI", tag, len(payload)) + payload


def group(tag, payload, *children):
    return record(tag | 0x8000, payload) + b"".join(children) + struct.pack("<H", tag | 0x4000)


def dataset(uid, sheet_id, role, title, values, *, mode=10, repeats=1, precision=0, text=None):
    rows = len(values) // repeats
    dimensions = struct.pack("<15i", uid, 0, 0, -1, sheet_id, 101, -1,
                             2 if role == 256 else 1, role, mode, repeats, -1, 0, rows, len(values))
    content = struct.pack("<HI", precision, len(values))
    layout = "<IIf" if precision == 0 else "<IId"
    content += b"".join(struct.pack(layout, state, 0, value) for state, value in values)
    children = [record(9, title + b"\0"), record(16, content)]
    if precision == 0:
        flags = struct.pack("<4i", 1, 16, 4, len(values)) + bytes(4 * len(values))
    else:
        flags = struct.pack("<4i", 2, 16, 16, len(values))
        flags += b"".join(struct.pack("<4i", 0, state, 0, 0) for state, _ in values)
    children.append(record(0xf3, flags))
    if text:
        labels = b"".join(text)
        children.append(record(0x11, struct.pack("<I", len(labels)) + labels))
        offset = 0
        slices = []
        for row, label in enumerate(text):
            slices.append(struct.pack("<III", row, offset, len(label)))
            offset += len(label)
        children.append(record(0xb6, struct.pack("<I", len(slices)) + b"".join(slices)))
    return group(0xf, dimensions, *children)


def sheet(uid, title, *, mode=10, links=(), datasets=(), layout=(0, 1), title_id=-1):
    records = [record(9, title + b"\0"), record(0x8e, struct.pack("<9i", title_id, 39, 0, 0, mode, *layout, 1, -2))]
    for position, dataset_id, repeats in links:
        records.append(record(0xd, struct.pack("<III", position, dataset_id, repeats) + bytes(12 * repeats)))
    return group(8, struct.pack("<H", uid), *records, *datasets)


def document(source, *sheets):
    header = bytearray(10064)
    struct.pack_into("<i", header, 40, len(source))
    struct.pack_into("<" + "i" * len(source), header, 60, *source)
    project = group(2, header)
    footer = record(0x8003, bytes(64))
    return b"PCFFGRA4" + group(1, struct.pack("<6H", 400, 400, 2, 400, 100, 600), project, *sheets, footer)


def legacy_xy(mode, y_rows, *, y_link=0, layout_suffix=b"", dataset_suffix=b""):
    def field(uid, role, form, title, rows, linked_x):
        repeats = len(rows[0])
        header = struct.pack("<15i", uid, 0, 4, -1, 0, 101, -1, 1, role, form,
                             repeats, linked_x, 0, len(rows), len(rows) * repeats)
        content = struct.pack("<HI", 0, len(rows) * repeats)
        content += b"".join(struct.pack("<IIf", *cell) for row in rows for cell in row)
        return group(0xF, header, record(9, title + b"\0"), record(16, content),
                     record(0x8F, struct.pack("<3i", 2, -1, linked_x)), record(0x90, bytes(2)),
                     dataset_suffix if role == 8 else b"")

    repeats = len(y_rows[0])
    layout = struct.pack("<7i", -1, 39, 1, 2, mode, 0, 1) + layout_suffix
    link = struct.pack("<3I", 0, 1, repeats) + bytes(12 * repeats - (0 if layout_suffix else 8))
    x_rows = [[(0, 0, 2)], [(1, 11, 3)], [(1, 11, 4)]]
    source = group(8, bytes(2), record(9, b"Older XY\0"), record(0x8E, layout), record(0xD, link),
                   field(0, 4, 10, b"Time", x_rows, 0), field(1, 8, mode, b"Control", y_rows, y_link))
    return document([0], source)


def legacy_column(*, status=105, width=0, integer=44, linked_x=-1, field_flags=b"\x01\x00",
                  layout_tail=(0, 2), link_flags=0x7040, extra_record=b""):
    def field(uid, title, cells, *, x=-1, flags=b"\x01\x00", extra=b""):
        header = struct.pack("<15i", uid, 0, 1, -1, 0, 101, -1, 1, 8, 10, 1, x, 0,
                             len(cells), len(cells))
        content = struct.pack("<HI", 0, len(cells))
        content += b"".join(struct.pack("<IIf", *cell) for cell in cells)
        return group(0xF, header, record(0x8F, struct.pack("<3i", 2, -1, x)),
                     record(9, title + b"\0"), record(16, content), record(0x90, flags), extra)

    layout = struct.pack("<7i", -1, 44, 2, 2, 10, *layout_tail)
    links = [record(0xD, struct.pack("<4I", 0, 1, 1, 0x7140)),
             record(0xD, struct.pack("<4I", 1, 2, 1, link_flags))]
    source = group(8, bytes(2), record(9, b"Older column\0"), record(0x8E, layout), *links,
                   field(2, b"mice", [(status, width, integer)], x=linked_x, flags=field_flags,
                         extra=extra_record),
                   field(1, b"Cats", [(1, 0, 32), (1, 0, 0)]))
    return document([0], source)


def legacy_xy_limits(*, layout_type=34, form=30, x_owner=1, blank=0x100000, width=0, text=b""):
    def field(uid, role, mode, title, repeats, cells, owner=1, extra=b""):
        header = struct.pack("<15i", uid, 0, 1, -1, 0, 101, -1, 2 if role == 256 else 1,
                             role, mode, repeats, 1, 0, len(cells) // repeats, len(cells))
        values = struct.pack("<HI", 0, len(cells))
        values += b"".join(struct.pack("<IIf", *cell) for cell in cells)
        return group(0xF, header, record(9, title + b"\0"),
                     record(0x8F, struct.pack("<3i", 2, 0, owner)), record(0x90, b"\x01\x00"),
                     record(16, values), extra)

    layout = struct.pack("<7i", 0, 44, 3, 1, layout_type, 0, 1)
    link = struct.pack("<10I", 0, 2, 3, 0x7040, 0, 0, 0x7040, 0, 0, 0x7040)
    source = group(8, bytes(2), record(9, b"Legacy limits\0"), record(0x8E, layout),
                   record(0xD, link),
                   field(0, 256, 12, b"", 1, [], extra=record(0x11, bytes(4) + text) + record(0xB6, bytes(4))),
                   field(1, 4, 10, b"Time", 1, [(1, 0, i) for i in range(4)], owner=x_owner),
                   field(2, 8, form, b"Signal", 3, [(blank, 0, 0), (0, 0, 0), (0, 0, 0),
                                                   (1, 0, 8), (1, width, 3), (1, 0, 2),
                                                   (1, 0, 5), (1, 0, -4), (1, 0, -2),
                                                   (1, 0, 0.2), (1, 0, 7.8), (1, 0, -0.3)]))
    return document([0], source)


class PrismBinaryTests(unittest.TestCase):
    def load(self, data, *, restore=False):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "fixture.pzf"
            path.write_bytes(data)
            return load_prism_binary(path, restore=restore)

    def test_index_and_dataset_links_preserve_order(self):
        unlisted = sheet(9, b"Result", mode=12)
        first = sheet(0, b"Later", links=[(1, 2, 1), (0, 1, 1)],
                      datasets=[dataset(2, 0, 8, b"B", [(1, 20)]),
                                dataset(1, 0, 8, b"A", [(1, 10)])])
        second = sheet(2, b"First", links=[(0, 3, 1)],
                       datasets=[dataset(3, 2, 8, b"Y", [(5, 1e-10), (0, 109), (1, 0)], precision=1),
                                 dataset(4, 2, 4, b"Time", [(1, 0.2), (1, 0.4), (1, 0.6)], precision=1)])
        tables = self.load(document([2, 0], first, unlisted, second))
        self.assertEqual(list(tables), ["First", "Later"])
        self.assertEqual(list(tables["Later"].columns), ["A", "B"])
        self.assertEqual(tables["Later"].iloc[0].tolist(), [10, 20])
        frame = tables["First"]
        self.assertEqual(frame.attrs["table_format"], "xy")
        self.assertEqual(list(frame.columns), ["Time", "Y"])
        self.assertEqual(frame["Time"].tolist(), [0.2, 0.4, 0.6])
        self.assertEqual(frame["Y"].iloc[0], 1e-10)
        self.assertTrue(pd.isna(frame["Y"].iloc[1]))
        self.assertEqual(frame["Y"].iloc[2], 0)

    def test_grouped_integer_state_is_limited_to_the_verified_layout(self):
        fallback = sheet(2, b"Fallback", links=[(0, 3, 1)],
                         datasets=[dataset(3, 2, 8, b"A", [(1, 10)])])
        for layout, title_id, value, expected in [
                ((39, 2), 4, 23, True), ((39, 2), 4, 2.5, False),
                ((0, 1), 4, 23, False), ((39, 2), -1, 23, False)]:
            with self.subTest(layout=layout, title_id=title_id, value=value):
                grouped = sheet(1, b"Grouped", links=[(0, 2, 1)], layout=layout, title_id=title_id,
                                datasets=[dataset(2, 1, 8, b"Integer", [(105, value), (0, 99), (1, 0)]),
                                          dataset(4, 1, 256, b"", [], mode=12)])
                tables = self.load(document([1, 2], grouped, fallback))
                self.assertEqual("Grouped" in tables, expected)
                if expected:
                    frame = tables["Grouped"]
                    self.assertEqual(frame.attrs["table_format"], "grouped")
                    self.assertEqual(frame.attrs["worksheet_roles"], {"x": [], "y": [["Integer"]]})
                    self.assertEqual(frame.iat[0, 0], 23)
                    self.assertTrue(pd.isna(frame.iat[1, 0]))
                    self.assertEqual(frame.iat[2, 0], 0)

    def test_column_layout_with_the_same_flags_keeps_column_semantics(self):
        raw = document([1], sheet(1, b"Column", layout=(39, 2), links=[(0, 2, 1)],
                                  datasets=[dataset(2, 1, 8, b"Numeric", [(1, 23)])]))
        frame = self.load(raw)["Column"]
        self.assertEqual(frame.attrs["table_format"], "column")
        self.assertNotIn("worksheet_roles", frame.attrs)

    def test_grouped_data_keeps_row_titles_and_replicate_coordinates(self):
        raw = document([1], sheet(
            1, b"Grouped", mode=61, links=[(0, 2, 2)],
            datasets=[dataset(1, 1, 256, b"", [(1, 0), (1, 0)], mode=12, text=[b"ADP", b"AA"]),
                      dataset(2, 1, 8, b"PEG", [(1, 73), (1, 86), (1, 66), (0, 3.4e38)], mode=61, repeats=2)],
        ))
        frame = self.load(raw)["Grouped"]
        self.assertEqual(frame.attrs["table_format"], "grouped")
        self.assertEqual(list(frame.columns), ["Row title", "PEG [1]", "PEG [2]"])
        self.assertEqual(frame["Row title"].tolist(), ["ADP", "AA"])
        self.assertEqual(frame["PEG [1]"].tolist(), [73, 66])
        self.assertEqual(frame["PEG [2]"].iloc[0], 86)
        self.assertTrue(pd.isna(frame["PEG [2]"].iloc[1]))

    def test_unverified_cell_flags_skip_whole_sheet(self):
        supported = sheet(1, b"Known", links=[(0, 1, 1)], datasets=[dataset(1, 1, 8, b"A", [(1, 2)])])
        unknown = sheet(2, b"Unknown", links=[(0, 2, 1)], datasets=[dataset(2, 2, 8, b"A", [(2, 3)])])
        tables = self.load(document([1, 2], supported, unknown))
        self.assertEqual(list(tables), ["Known"])
        self.assertEqual(tables["Known"].attrs["skipped"], ["Unknown"])

    def test_older_numeric_xy_recovers_replicates_and_cleared_cells(self):
        raw = legacy_xy(61, [[(0, 0, 42), (0, 4, 7), (0, 0, 9)],
                             [(1, 18, 33), (1, 0, 57), (1, 25, 120)]])
        frame = self.load(raw)["Older XY"]
        self.assertEqual(frame.attrs["table_format"], "xy")
        self.assertEqual(frame.attrs["worksheet_roles"],
                         {"x": ["Time"], "y": [["Control [1]", "Control [2]", "Control [3]"]]})
        self.assertEqual(frame.iloc[1].tolist(), [3, 33, 57, 120])
        self.assertTrue(frame.iloc[0].isna().all())
        self.assertEqual(frame.iat[2, 0], 4)
        self.assertTrue(frame.iloc[2, 1:].isna().all())

    def test_older_numeric_xy_preserves_precalculated_mean_and_sd(self):
        raw = legacy_xy(21, [[(1, 25, 1.5), (1, 32, 0.75)]])
        frame = self.load(raw)["Older XY"]
        self.assertEqual(list(frame.columns), ["Time", "Control [Mean]", "Control [SD]"])
        self.assertEqual(frame.iloc[0, 1:].tolist(), [1.5, 0.75])

    def test_older_xy_limits_recovers_signed_offsets_as_endpoints(self):
        frame = self.load(legacy_xy_limits())["Legacy limits"]
        names = ["Signal [Center]", "Signal [Upper]", "Signal [Lower]"]
        self.assertEqual(frame.attrs["table_format"], "xy")
        self.assertEqual(frame.attrs["worksheet_roles"], {"x": ["Time"], "y": [names]})
        self.assertEqual(list(frame), ["Time", *names])
        self.assertEqual(frame["Time"].tolist(), [0, 1, 2, 3])
        self.assertTrue(frame[names].iloc[0].isna().all())
        self.assertEqual(frame[names].iloc[1].tolist(), [8, 11, 6])
        self.assertEqual(frame[names].iloc[2].tolist(), [5, 1, 7])
        self.assertEqual(frame["Signal [Upper]"].iloc[3], 8)
        self.assertEqual(frame["Signal [Lower]"].iloc[3], 0.5)

    def test_older_xy_limits_rejects_unverified_metadata(self):
        for invalid in ({"layout_type": 35}, {"form": 29}, {"x_owner": 2},
                        {"blank": 2}, {"width": 4}, {"text": b"label"}):
            with self.subTest(**invalid), self.assertRaisesRegex(ValueError, "Unsupported sheets: Legacy limits"):
                self.load(legacy_xy_limits(**invalid))

    def test_older_numeric_xy_rejects_unverified_status_and_mixed_layouts(self):
        y = [[(1, 0, 1), (1, 11, 2)]]
        for raw in (legacy_xy(21, [[(105, 0, 1), (1, 11, 2)]]),
                    legacy_xy(21, [[(1, 7, 1), (1, 11, 2)]]),
                    legacy_xy(21, y, y_link=4),
                    legacy_xy(21, y, layout_suffix=bytes(8)),
                    legacy_xy(21, y, dataset_suffix=record(0xF3, struct.pack("<4I", 1, 16, 4, 2) + bytes(8)))):
            with self.subTest(raw=raw[-52:]), self.assertRaisesRegex(ValueError, "Unsupported sheets: Older XY"):
                self.load(raw)

    def test_older_column_preserves_integer_data_titles_order_and_blank_tail(self):
        frame = self.load(legacy_column())["Older column"]
        self.assertEqual(frame.attrs["table_format"], "column")
        self.assertEqual(list(frame.columns), ["Cats", "mice"])
        self.assertEqual(frame.iloc[0].tolist(), [32, 44])
        self.assertEqual(frame.iat[1, 0], 0)
        self.assertTrue(pd.isna(frame.iat[1, 1]))
        self.assertFalse(frame.attrs.get("excluded"))

    def test_older_column_rejects_unverified_status_and_metadata(self):
        for overrides in (
            {"status": 5},
            {"status": 104},
            {"status": 106},
            {"integer": 44.25},
            {"integer": float("inf")},
            {"width": 18},
            {"linked_x": 1},
            {"field_flags": b"\0\0"},
            {"layout_tail": (39, 2)},
            {"link_flags": 0x7041},
            {"extra_record": record(0xF3, struct.pack("<5I", 1, 16, 4, 1, 0))},
        ):
            with self.subTest(**overrides), self.assertRaisesRegex(ValueError, "Unsupported sheets: Older column"):
                self.load(legacy_column(**overrides))

    def test_truncated_file_is_not_partially_imported(self):
        raw = document([0], sheet(0, b"Data", links=[(0, 0, 1)], datasets=[dataset(0, 0, 8, b"A", [(1, 2)])]))
        with self.assertRaisesRegex(ValueError, "binary"):
            self.load(raw[:-3])

    def test_invalid_graph_index_does_not_discard_source_tables(self):
        source = sheet(0, b"Source", links=[(0, 1, 1)],
                       datasets=[dataset(1, 0, 8, b"Y", [(1, 5)])])
        data = bytearray(document([0], source))
        header_start = len(b"PCFFGRA4") + len(record(0x8001, bytes(12))) + struct.calcsize("<HI")
        struct.pack_into("<I", data, header_start + 48, 257)
        restored = self.load(data, restore=True)
        self.assertEqual(restored["Source"]["Y"].tolist(), [5])
        self.assertIn("graph count exceeds", restored["Source"].attrs["import_warnings"][0])
