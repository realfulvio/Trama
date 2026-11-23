from base64 import b64encode
from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory
import unittest

import pandas as pd

from analisi.data import Dataset, load_tables, load_workspace, save_project
from analisi.grid_data import paste_block
from analisi.legacy_binary_bars import edit_bar_preview
from analisi.legacy_binary_graphs import validate_binary_graph
from analisi.legacy_restore import LEGACY_GRAPH_STYLE, LEGACY_PREVIEW, SAVED_EDITABLE_GRAPH
from test_legacy_binary import dataset, document, group, record, sheet
from test_legacy_binary_editable import _plus
from test_legacy_binary_graphs import _emf


def _bar_graph(*, multiple_rectangles=False, upper=400, lower=None):
    version = 0xDBC01002
    pen = pack("<4If6I", version, 0, 208, 0, 12.0, 0, 0, 0, version, 0, 0xFF445566)
    commands = _plus(0x4008, 0x0201, pen)
    rectangles = [(120, 500, 160, 500)]
    if multiple_rectangles:
        rectangles.append((300, 500, 10, 10))
    fills = pack("<II", 0xFF6288AA, len(rectangles))
    commands += _plus(0x400A, 0xC000, fills + b"".join(pack("<4h", *box) for box in rectangles))
    commands += _plus(0x400D, 0x4001, pack("<I12h", 6, 120, 1000, 120, 500, 120, 500,
                                          280, 500, 280, 500, 280, 1000))
    for y, pen_id in ((upper, 1), (lower, 2)):
        if y is not None:
            if pen_id == 2:
                commands += _plus(0x4008, 0x0202, pen[:-4] + pack("<I", 0xFF992244))
            commands += _plus(0x400D, 0x4000 | pen_id, pack("<I8h", 4, 160, y, 240, y, 200, y, 200, 500))
    comment = pack("<III4s", 70, 16 + len(commands), 4 + len(commands), b"EMF+") + commands
    return {"format": "emf", "data": b64encode(_emf(comment)).decode("ascii")}


def _column_pzf(*, show_upper=True, lower_level=350, series_flags=8, summary_lower_level=None):
    """Build a controlled PZF with mean 5 and a visible error of 1 or 1.5."""
    upper_only = summary_lower_level is not None
    preview = validate_binary_graph(_bar_graph(upper=400 if show_upper else None, lower=None if upper_only else 650))
    chart = pack("<4h", 0, 0, 500, 1000) + bytes(40)
    axes = [bytearray(60) for _ in range(3)]
    pack_into("<2d", axes[1], 16, 0, 10)
    pack_into("<H", axes[1], 42, 1000)
    pack_into("<H", axes[1], 54, 7)
    scale = pack("<H3d", 7, 0, 10, .01) + bytes(96)
    series = bytearray(144)
    pack_into("<4H", series, 0, 12, 1, 17, 1)
    pack_into("<H", series, 58, series_flags)
    pack_into("<H", series, 98, 160)
    pack_into("<5H", series, 110, 5, 2048, 2, 0, 10)
    leading = (200, 500, 500, 600, summary_lower_level) if upper_only else (200, 500, 0, 0, 0)
    cache = pack("<11i", 10, *leading, 200, 0, 500, 600, 500 if upper_only else lower_level)
    scene = group(24, bytes(12), group(32, pack("<H", 9) + bytes(28),
                                       group(40, series, record(0x29, cache))))
    graph = group(18, pack("<H", 6), record(9, b"Range columns\0"),
                  record(0x5E, pack("<II", len(preview), 1) + bytes(128) + preview),
                  record(0x13, chart), record(0x14, pack("<2i", 1, 8)),
                  record(0x15, pack("<2i", 1, 12)), record(0x16, pack("<H3i", 1, 17, 1, -1)),
                  *(record(0x17, axis) for axis in axes), group(37, scale), scene)
    values = (4, 5, 6) if upper_only else (3.5, 5.5, 6)
    source = sheet(8, b"Observations", links=[(0, 17, 1)],
                   datasets=[dataset(17, 8, 8, b"A", [(1, value) for value in values])])
    project = bytearray(document([8], source, graph))
    index = 8 + 18 + 6
    pack_into("<I", project, index + 48, 1)
    pack_into("<i", project, index + 4060, 6)
    return project


class EditableBarTests(unittest.TestCase):
    def setUp(self):
        self.preview = _bar_graph()
        self.style = {"bottom": 1000, "bounds": [0.0, 10.0], "unit": 0.01,
                      "bars": [[200, 160, 500, 600, 5.0, 1.0]]}
        self.frame = pd.DataFrame({"Mean": [5.0], "Upper error": [1.0], "Group": ["A"]})

    def test_unchanged_preview_is_byte_identical(self):
        self.assertEqual(edit_bar_preview(self.frame, self.style, self.preview), self.preview)

    def test_editable_columns_require_the_original_emf_format(self):
        with self.assertRaisesRegex(ValueError, "require an EMF preview"):
            edit_bar_preview(self.frame, self.style, {"format": "pdf", "data": self.preview["data"]})

    def test_edit_replaces_only_column_and_error_coordinates(self):
        self.frame.loc[0, ["Mean", "Upper error"]] = [6.0, 2.0]
        updated = edit_bar_preview(self.frame, self.style, self.preview)
        original = validate_binary_graph(self.preview)
        expected = original.replace(pack("<4h", 120, 500, 160, 500), pack("<4h", 120, 400, 160, 600))
        expected = expected.replace(pack("<I12h", 6, 120, 1000, 120, 500, 120, 500, 280, 500, 280, 500, 280, 1000),
                                    pack("<I12h", 6, 120, 1000, 120, 400, 120, 400, 280, 400, 280, 400, 280, 1000))
        expected = expected.replace(pack("<I8h", 4, 160, 400, 240, 400, 200, 400, 200, 500),
                                    pack("<I8h", 4, 160, 200, 240, 200, 200, 200, 200, 400))
        self.assertNotEqual(expected, original)
        self.assertEqual(validate_binary_graph(updated), expected)

    def test_unmatched_or_duplicate_bar_binding_rejected(self):
        self.style["bars"][0][0] += 12
        with self.assertRaises(ValueError):
            edit_bar_preview(self.frame, self.style, self.preview)

    def test_fill_array_moves_only_the_matched_bar(self):
        self.frame.loc[0, "Mean"] = 3.0
        preview = _bar_graph(multiple_rectangles=True)
        updated = validate_binary_graph(edit_bar_preview(self.frame, self.style, preview))
        self.assertIn(pack("<8h", 120, 700, 160, 300, 300, 500, 10, 10), updated)

    def test_out_of_range_or_negative_errors_rejected(self):
        for mean, error in [(9.0, 3.0), (5.0, -1.0), (float("nan"), 1.0)]:
            self.frame.loc[0, ["Mean", "Upper error"]] = [mean, error]
            with self.assertRaises(ValueError):
                edit_bar_preview(self.frame, self.style, self.preview)

    def test_lower_error_edits_without_creating_an_upper_whisker(self):
        self.preview = _bar_graph(upper=None, lower=650)
        self.style["bars"] = [[200, 160, 500, None, 5.0, None, 350, 1.5]]
        self.frame["Upper error"] = float("nan")
        self.frame["Lower error"] = 1.5
        self.assertEqual(edit_bar_preview(self.frame, self.style, self.preview), self.preview)
        self.frame.loc[0, "Lower error"] = 2.0
        emf = validate_binary_graph(edit_bar_preview(self.frame, self.style, self.preview))
        self.assertIn(pack("<I8h", 4, 160, 700, 240, 700, 200, 700, 200, 500), emf)
        self.frame.loc[0, "Upper error"] = 0.25
        with self.assertRaisesRegex(ValueError, "absent"):
            edit_bar_preview(self.frame, self.style, self.preview)

    def test_asymmetric_edits_keep_the_two_whisker_pens(self):
        self.preview = _bar_graph(lower=650)
        self.style["bars"][0].extend((350, 1.5))
        self.frame["Lower error"] = 1.5
        original = validate_binary_graph(self.preview)
        self.assertEqual(edit_bar_preview(self.frame, self.style, self.preview), self.preview)
        self.frame.loc[0, "Lower error"] = 2.0
        updated = validate_binary_graph(edit_bar_preview(self.frame, self.style, self.preview))
        expected = original.replace(pack("<I8h", 4, 160, 650, 240, 650, 200, 650, 200, 500),
                                    pack("<I8h", 4, 160, 700, 240, 700, 200, 700, 200, 500))
        self.assertEqual(updated, expected)
        self.frame.loc[0, "Lower error"] = 5.25
        with self.assertRaisesRegex(ValueError, "saved Y range"):
            edit_bar_preview(self.frame, self.style, self.preview)

    def test_pzf_import_cross_checks_both_ends_and_saves_edits(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.pzf"
            source.write_bytes(_column_pzf())
            frames = load_tables(source, restore_legacy=True)
            name = "Imported graph data · Range columns"
            chart = Dataset(frames[name])
            self.assertEqual(chart.locked_columns, (3,))
            self.assertEqual(chart.raw.iloc[0].tolist(), [5, 1, 1.5, "A"])
            self.assertEqual(chart.analyses[0][0], SAVED_EDITABLE_GRAPH)
            options = chart.analyses[0][1]
            self.assertEqual(edit_bar_preview(chart.raw, options[LEGACY_GRAPH_STYLE], options[LEGACY_PREVIEW]),
                             options[LEGACY_PREVIEW])
            paste_block(chart, 0, 1, [["2", "0.25"]])
            with self.assertRaises(ValueError):
                paste_block(chart, 0, 2, [["0.5", "new group"]])
            with self.assertRaisesRegex(ValueError, "saved Y range"):
                paste_block(chart, 0, 2, [["5.25"]])
            path = Path(directory) / "edited.alab"
            save_project(path, {name: chart})
            reopened = load_workspace(path)[0][name]
            self.assertEqual(reopened.raw.iloc[0].tolist(), [5, 2, .25, "A"])
            self.assertEqual(edit_bar_preview(chart.raw, options[LEGACY_GRAPH_STYLE], options[LEGACY_PREVIEW]),
                             edit_bar_preview(reopened.raw, options[LEGACY_GRAPH_STYLE], options[LEGACY_PREVIEW]))
            source.write_bytes(_column_pzf(show_upper=False))
            lower_only = load_tables(source, restore_legacy=True)[name]
            self.assertTrue(pd.isna(lower_only["Upper error"].iloc[0]))
            self.assertEqual(lower_only["Lower error"].iloc[0], 1.5)
            source.write_bytes(_column_pzf(lower_level=365))
            self.assertNotIn(name, load_tables(source, restore_legacy=True))

    def test_series_flag_four_still_requires_matching_drawing(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.pzf"
            name = "Imported graph data · Range columns"
            source.write_bytes(_column_pzf(series_flags=4))
            frames = load_tables(source, restore_legacy=True)
            self.assertIn(name, frames)
            self.assertEqual(frames[name].iloc[0].tolist(), [5, 1, 1.5, "A"])
            for options in ({"series_flags": 4, "lower_level": 365}, {"series_flags": 0x14}):
                with self.subTest(options=options):
                    source.write_bytes(_column_pzf(**options))
                    self.assertNotIn(name, load_tables(source, restore_legacy=True))

    def test_symmetric_companion_cache_does_not_add_a_lower_whisker(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.pzf"
            name = "Imported graph data · Range columns"
            source.write_bytes(_column_pzf(summary_lower_level=400))
            frames = load_tables(source, restore_legacy=True)
            self.assertIn(name, frames)
            self.assertEqual(list(frames[name].columns), ["Mean", "Upper error", "Group"])
            self.assertEqual(frames[name].iloc[0].tolist(), [5, 1, "A"])
            source.write_bytes(_column_pzf(summary_lower_level=390))
            self.assertNotIn(name, load_tables(source, restore_legacy=True))
