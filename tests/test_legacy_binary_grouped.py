from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory
import unittest

from pandas.testing import assert_frame_equal

from analisi.data import Dataset, load_tables
from analisi.workbench import analyse
from test_legacy_binary import group, record
from test_legacy_binary_graphs import _project
from test_legacy_zip_grouped import graph_group, write_fixture


def write_binary_fixture(path, *, damaged_index=False, missing=False, **graph_variations):
    def field(uid, role, title, values, *extra, repeats=1, text_size=0):
        mode = 12 if role == 256 else 61
        header = pack("<15i", uid, 0, 1, -1, 14, 101, 0, 2 if role == 256 else 1, role, mode,
                      repeats, 199, 0, len(values) // repeats, len(values))
        cells = pack("<HI", 0, len(values))
        cells += b"".join(pack("<IIf", status, 0, value) for status, value in values)
        return group(0xF, header, record(9, title + b"\0"), record(0x10, cells),
                     record(0x8F, pack("<6i", 3, 0, -1, 1, text_size, len(title))),
                     record(0x90, b"\x01\x00"), *extra)

    text = b"BeforeAfter"
    first, second = 6 << 16, (5 << 16) | 6
    names = field(199, 256, b"", [(1, first), (1, second)],
                  record(0x11, pack("<I", len(text)) + text),
                  record(0x92, pack("<3I", 2, first, second + int(damaged_index))),
                  record(0xB6, pack("<7I", 2, 0, 0, 6, 1, 6, 5)), text_size=len(text))
    data = ((1, 3, 2, 4), (4, 6, 3, 5), (2, 4, 6, 8), (7, 9, 1, 3))
    links, datasets = [], []
    for index, (title, raw) in enumerate(zip(b"ABCD", data, strict=True)):
        uid = 200 + index
        links.append(record(0xD, pack("<3I", index, uid, 2) + bytes(24)))
        values = [(105, value) for value in raw]
        if missing and index == 0:
            values[-1] = (0, 3.4e38)
        datasets.append(field(uid, 8, bytes([title]), values, repeats=2))
    source = group(0x8, pack("<H", 14), record(9, b"Visits\0"),
                   record(0x8E, pack("<8i", 199, 107, 3, 3, 61, 0, 3, 3)), *links, names, *datasets)
    path.write_bytes(_project([7], source, graph_group(legacy=True, **graph_variations), source_ids=[14]))


class LegacyBinaryGroupedTests(unittest.TestCase):
    def test_binary_and_zip_projects_restore_the_same_linked_chart(self):
        with TemporaryDirectory() as scratch:
            binary, modern = [Path(scratch) / f"grouped.{suffix}" for suffix in ("pzf", "pzt")]
            write_binary_fixture(binary)
            write_fixture(modern)
            first, second = [load_tables(path, restore_legacy=True)["Visits"] for path in (binary, modern)]
            self.assertFalse(first.attrs.get("import_warnings"))
            assert_frame_equal(first, second, check_dtype=False)
            legacy, zipped = Dataset(first), Dataset(second)
            self.assertEqual(len(legacy.analyses), 1)
            self.assertEqual(legacy.analyses, zipped.analyses)
            self.assertEqual(legacy.graph_styles, zipped.graph_styles)
            method, options = legacy.analyses[0]
            figure = analyse(method, legacy.frame(), options).figure
            bars = figure.axes[0]._tramastat_grouped["handles"]
            self.assertEqual(bars["B"].patches[0].get_y(), 2.)
            self.assertEqual(bars["D"].patches[0].get_y(), 3.)
            legacy.raw.loc[0, "C [2]"] = 6.
            updated = analyse(method, legacy.frame(), options).figure
            self.assertEqual(updated.axes[0]._tramastat_grouped["handles"]["D"].patches[0].get_y(), 4.)

    def test_cleared_cells_remain_empty_and_a_contradictory_graph_stays_unavailable(self):
        with TemporaryDirectory() as scratch:
            binary = Path(scratch) / "inconsistent.pzf"
            write_binary_fixture(binary, wrong_detail=True, missing=True)
            frame = load_tables(binary, restore_legacy=True)["Visits"]
            self.assertTrue(frame["A [2]"].isna().iloc[1])
            self.assertEqual(Dataset(frame).analyses, [])
            self.assertIn("Unavailable imported graph previews (1)", frame.attrs["import_warnings"][0])

    def test_corrupt_text_index_does_not_import_mislabelled_rows(self):
        with TemporaryDirectory() as scratch:
            binary = Path(scratch) / "inconsistent-index.pzf"
            write_binary_fixture(binary, damaged_index=True)
            with self.assertRaisesRegex(ValueError, "no supported populated tables"):
                load_tables(binary, restore_legacy=True)
