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


def _graph(markers):
    graph = _record(0x14, pack("<2i", 1, 14))
    graph += _record(0x15, pack("<3i", 2, 21, 20))
    graph += _record(0x16, pack("<H6i", 2, 205, -1, -1, 206, -1, -1))
    for uid, limits, tick in ((1, (0, 4), 1), (2, (0, 6), 2), (3, (0, 6), 2)):
        low, high = limits
        axis, scale = bytearray(60), bytearray(134)
        pack_into("<2d", axis, 16, low, high)
        pack_into("<H", axis, 42, 1200)
        pack_into("<H", axis, 54, uid)
        pack_into("<H3d", scale, 0, uid, low, high, (high - low) / 1200)
        pack_into("<d", scale, 54, tick)
        graph += _record(0x17, axis) + _group(0x8025, scale)
    objects = b""
    for key, uid, color in markers:
        header = bytearray(144)
        pack_into("<8H", header, 0, key, 0, uid, 1, 2, 0, 0, 2)
        pack_into("<4H", header, 58, 8, 3, 8, 0)
        header[68:71] = bytes.fromhex(color)
        objects += _group(0x8020, pack("<H", 9) + bytes(28), _group(0x8028, header))
    graph += _group(0x8018, bytes(12), objects)
    return b"PCFFGRA4" + _group(0x8001, bytes(12), _group(0x8012, pack("<H", 8), graph))


def _write(project, *, bad_link=False):
    table = {"format": "xy", "dataFormat": "y_single", "uid": "raw",
             "xDataSet": "x", "dataSets": ["first", "second"]}
    members = {
        "document.json": {"sheets": {"data": ["source"], "graphs": ["chart"], "info": []}},
        "data/sheets/source/sheet.json": {"uid": "source", "fenID": 14, "title": "Signals", "table": table},
        "data/tables/raw/content.json": {"numberOfColumns": 3, "numberOfRows": 3},
        "data/sets/x.json": {"title": "Time", "dataType": "real", "fenID": 204},
        "data/sets/first.json": {"title": "A", "dataType": "real", "fenID": 205},
        "data/sets/second.json": {"title": "B", "dataType": "real", "fenID": 206},
        "graphs/chart/sheet.json": {"uid": "chart", "fenID": 8, "title": "Signals by date",
                                    "inputDataSets": ["first", "second"]},
    }
    with ZipFile(project, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, json.dumps(data))
        archive.writestr("data/tables/raw/data.csv", "1,3,\n2,,\n3,5,\n")
        archive.writestr("graphs/chart/data.bin", _graph([(20, 205, "22aaff"),
                                                         (21, 207 if bad_link else 206, "ff0088")]))


class PrismZipSparseXYTests(unittest.TestCase):
    def test_initially_empty_series_remains_linked_to_its_original_column(self):
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "test.pzt"
            _write(path)
            tables = load_tables(path, restore_prism=True)
            self.assertEqual(list(tables), ["Signals"])
            data = Dataset(tables["Signals"])
            method, options = data.analyses[0]
            report = analyse(method, data.frame(mask_excluded=True), options)
            self.assertEqual(report.tables["Saved XY coordinates"]["Y"].tolist(), [3, 5])
            self.assertEqual(report.figure.axes[0].get_xlim(), (0, 4))
            self.assertEqual(report.figure.axes[0].get_ylim(), (0, 6))
            data.raw.loc[1, "B"] = 4
            data.excluded.add((0, 1))
            out = Path(scratch) / "roundtrip.alab"
            save_project(out, {"Signals": data})
            restored = load_project(out)["Signals"]
            method, options = restored.analyses[0]
            report = analyse(method, restored.frame(mask_excluded=True), options)
            points = report.tables["Saved XY coordinates"]
            self.assertEqual(points["Series"].tolist(), ["B", "A"])
            self.assertEqual(points["Y"].tolist(), [4, 5])
            self.assertEqual([line.get_color() for line in report.figure.axes[0].lines], ["#ff0088", "#22aaff"])

    def test_rejects_a_binary_series_that_does_not_match_the_document(self):
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "invalid.pzt"
            _write(path, bad_link=True)
            data = Dataset(load_tables(path, restore_prism=True)["Signals"])
            self.assertFalse(data.analyses)
