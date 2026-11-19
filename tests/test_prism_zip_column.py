import json
from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.workbench import analyse
from test_prism_binary_editable import _group
from test_prism_binary_graphs import _record


def _graph(*, point_dataset=200):
    chart = bytearray(48)
    pack_into("<4h", chart, 0, 100, 200, 1300, 600)
    pack_into("<H", chart, 32, 30)
    graph = _record(0x13, chart)
    graph += _record(0x14, pack("<2i", 1, 14))
    graph += _record(0x15, pack("<2i", 1, 20))
    graph += _record(0x16, pack("<H3i", 1, 200, -2, -2))
    for uid, bounds, length, title in ((1, (0, 4), 1200, 31), (2, (1, 2), 400, 32), (3, (1, 2), 400, 33)):
        lo, hi = bounds
        axis, scale = bytearray(60), bytearray(134)
        pack_into("<2d", axis, 16, lo, hi)
        pack_into("<4H", axis, 42, length, 0, 0, title)
        pack_into("<H", axis, 54, uid)
        graph += _record(0x17, axis)
    for uid, (lo, hi), length in ((1, (0, 4), 1200), (2, (1, 2), 400), (3, (1, 2), 400)):
        scale = bytearray(134)
        pack_into("<H3d", scale, 0, uid, lo, hi, (hi - lo) / length)
        pack_into("<d", scale, 54, 1)
        if uid == 1:
            scale[102:105] = b":00"
        alignment = _record(0x27, pack("<3Hi", 200, length, 200, -2)) if uid == 2 else b""
        graph += _group(0x8025, scale, alignment)
    style = bytearray(144)
    pack_into("<8H", style, 0, 20, 1, 200, 1, 0, 1, 0, 2)
    pack_into("<3H", style, 58, 0xC008, 3, 8)
    series = _group(0x8020, pack("<H", 9) + bytes(28), _group(0x8028, style, _record(0x29, bytes(4))))
    objects = [series]
    for axis_id, flags in ((1, 0x30), (2, 0x830)):
        header = pack("<H", 8) + bytes(26) + pack("<H", flags)
        objects.append(_group(0x8020, header, _record(0x2A, pack("<H", axis_id))))
    for text_id, flags, label in ((30, 0x332, b"Hidden title"), (31, 0x130, b"Time"), (34, 0, b"2:00")):
        header = pack("<H", 2) + bytes(16) + pack("<4h2H", 650, 130, 750, 180, 0, flags)
        text = _record(0x102C, label)
        props = [(1, 12), (8, 0xFF0000FF), (10, 65001)] if text_id == 34 else [(1, 12), (10, 65001)]
        text += _record(0x102D, pack("<HHI", 1, len(props), 0) + b"".join(pack("<HI", *prop) for prop in props))
        objects.append(_group(0x8020, header, _group(0x902B, pack("<H", text_id) + bytes(16), text)))
    graph += _group(0x8018, pack("<3I", 11, len(objects), 0), b"".join(objects))
    points = [bytearray(249) for _ in range(4)]
    for row, point in enumerate(points[:3]):
        pack_into("<3I", point, 4, point_dataset if row == 1 else 200, row, 0xFFFFFFFF)
    points[1][0] = 4
    points[1][165:169] = bytes.fromhex("ff0000ff")
    pack_into("<I", points[-1], 4, 200)
    graph += _record(0xAE, pack("<3I", 20, len(points), 249) + b"".join(points))
    return b"PCFFGRA4" + _group(0x8001, bytes(12), _group(0x8012, pack("<H", 7), graph))


def _write(path, *, point_dataset=200):
    members = {
        "document.json": {"sheets": {"data": ["source"], "graphs": ["chart"]}},
        "data/sheets/source/sheet.json": {"uid": "source", "fenID": 14, "title": "Schedule",
                                         "table": {"uid": "raw", "format": "column", "dataFormat": "y_single",
                                                   "dataSets": ["times"]}},
        "data/sets/times.json": {"title": "Elapsed", "dataType": "real", "fenID": 200},
        "data/tables/raw/content.json": {"numberOfRows": 3, "numberOfColumns": 1},
        "graphs/chart/sheet.json": {"uid": "chart", "fenID": 7, "title": "Events",
                                    "inputDataSets": ["times"]},
    }
    with ZipFile(path, "w") as archive:
        for member, data in members.items():
            archive.writestr(member, json.dumps(data))
        archive.writestr("data/tables/raw/data.csv", "1\n2.125\n3\n")
        archive.writestr("graphs/chart/data.bin", _graph(point_dataset=point_dataset))


class PrismZipColumnTests(unittest.TestCase):
    def test_aligned_points_recalculate_with_the_source_and_keep_their_colors(self):
        with TemporaryDirectory() as scratch:
            project = Path(scratch) / "schedule.pzt"
            _write(project)
            table = Dataset(load_tables(project, restore_prism=True)["Schedule"])
            (method, options), = table.analyses
            result = analyse(method, table.frame(mask_excluded=True), options)
            axes, = result.figure.axes
            points, = axes.collections
            self.assertEqual(points.get_offsets().tolist(), [[1, 1.5], [2.125, 1.5], [3, 1.5]])
            self.assertEqual(points.get_facecolors().tolist(), [[0, 0, 0, 1], [1, 0, 0, 1], [0, 0, 0, 1]])
            self.assertEqual([text.get_text() for text in axes.get_xticklabels()], ["0:00", "1:00", "2:00", "3:00", "4:00"])
            self.assertEqual(axes.get_xlabel(), "Time")
            self.assertAlmostEqual(axes.get_box_aspect(), 400 / 1200)
            self.assertEqual(axes.get_title(), "")
            self.assertFalse(axes.yaxis.get_visible())
            note, = axes.texts
            self.assertEqual((note.get_text(), note.get_color(), note.get_fontsize()), ("2:00", "#ff0000", 12))
            table.raw.loc[1, "Elapsed"] = 2.5
            table.raw.loc[0, "Elapsed"] = None
            saved = Path(scratch) / "schedule.alab"
            save_project(saved, {"Schedule": table})
            reopened = load_project(saved)["Schedule"]
            (method, options), = reopened.analyses
            updated = analyse(method, reopened.frame(mask_excluded=True), options)
            (points,) = updated.figure.axes[0].collections
            self.assertEqual(points.get_offsets().tolist(), [[2.5, 1.5], [3, 1.5]])
            self.assertEqual(points.get_facecolors().tolist(), [[1, 0, 0, 1], [0, 0, 0, 1]])

    def test_a_point_cache_for_another_dataset_does_not_bind(self):
        with TemporaryDirectory() as scratch:
            project = Path(scratch) / "invalid.pzt"
            _write(project, point_dataset=201)
            source = load_tables(project, restore_prism=True)["Schedule"]
            self.assertEqual(Dataset(source).analyses, [])
            self.assertIn("Graph unavailable for Events.", source.attrs["import_warnings"][0])
