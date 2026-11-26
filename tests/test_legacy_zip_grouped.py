import json
from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from analisi.category_graphs import GROUPED_GRAPH, INTERVAL_DIRECTION, SERIES_PLACEMENT, STACK_PREVIOUS, UPPER_INTERVAL
from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.presentation import apply_style
from analisi.workbench import analyse
from test_legacy_binary_editable import _group
from test_legacy_binary_graphs import _record


def write_fixture(path, *, wrong_sheet=False, wrong_position=False, wrong_relation=False, wrong_detail=False):
    ids = ["a", "b", "c", "d"]
    members = {
        "document.json": {"sheets": {"data": ["source"], "graphs": ["chart"]}},
        "data/sheets/source/sheet.json": {
            "uid": "source", "fenID": 14, "title": "Visits",
            "table": {"uid": "raw", "format": "grouped", "dataFormat": "y_replicates", "replicatesCount": 2,
                      "rowTitlesDataSet": "labels", "dataSets": ids},
        },
        "data/sets/labels.json": {"dataType": "text"},
        "graphs/chart/sheet.json": {"uid": "chart", "fenID": 7, "title": "Four series", "inputDataSets": ids},
    }
    chart = bytearray(48)
    pack_into("<4h", chart, 0, 100, 200, 1500, 1400)
    body = _record(0x13, chart) + _record(0x14, pack("<2i", 1, 15 if wrong_sheet else 14))
    body += _record(0x15, pack("<5i", 4, 20, 21, 22, 23))
    body += _record(0x16, pack("<H", 4) + b"".join(pack("<3i", dataset, 0, -2) for dataset in range(200, 204)))
    objects = []
    for axis_id, length, low, high in ((1, 1400, 1., 2.), (2, 1200, 0., 40.), (3, 1200, 0., 100.)):
        axis, scale = bytearray(60), bytearray(134)
        pack_into("<2d", axis, 16, low, high)
        pack_into("<4H", axis, 42, length, 0, 0, 30 + axis_id)
        pack_into("<H", axis, 54, axis_id)
        pack_into("<H2d", scale, 0, axis_id, low, high)
        pack_into("<2d", scale, 54, 1. if axis_id == 1 else 10., low)
        body += _record(0x17, axis) + _group(0x8025, scale, b"")
        if axis_id < 3:
            objects.append(_group(0x8020, pack("<H", 8) + bytes(28), _record(0x2A, pack("<H", axis_id))))
    for index, name in enumerate(ids):
        key, dataset = 20 + index, 200 + index
        members[f"data/sets/{name}.json"] = {"title": name.upper(), "dataType": "real", "fenID": dataset}
        saved, detail, rect = bytearray(144), bytearray(321), bytearray(30)
        pack_into("<8H", saved, 0, key, 1, dataset, 1, 0, 1, 2, 2)
        pack_into("<H", saved, 58, 14)
        relation = (0, 2, 1, 3 if wrong_relation else 2)[index]
        pack_into("<H", saved, 104, relation)
        pack_into("<2I", detail, 0, 27, 0xFFFFFFFF)
        pack_into("<3I", detail, 293, 1, 1, 0x20000)
        pack_into("<I", detail, 313, dataset + int(wrong_detail))
        left = (200, 201 if wrong_position else 200, 340, 340)[index]
        pack_into("<H4h", rect, 0, 9, left, 300, left + 600, 1250)
        objects.append(_group(0x8020, rect, _group(0x8028, saved, _record(0x9C, detail))))
    body += _group(0x8018, bytes(12), b"".join(reversed(objects)))
    with ZipFile(path, "w") as archive:
        for member, value in members.items():
            archive.writestr(member, json.dumps(value))
        archive.writestr("data/tables/raw/data.csv", "Before,1,3,4,6,2,4,7,9\nAfter,2,4,3,5,6,8,1,3\n")
        archive.writestr("graphs/chart/data.bin",
                         b"PCFFGRA4" + _group(0x8001, bytes(12), _group(0x8012, pack("<H", 7), body)))


class LegacyZipGroupedTests(unittest.TestCase):
    def test_grouped_stack_import_recalculates_and_persists(self):
        with TemporaryDirectory() as scratch:
            project = Path(scratch) / "grouped.pzt"
            write_fixture(project)
            source = load_tables(project, restore_legacy=True)["Visits"]
            worksheet = Dataset(source)
            self.assertFalse(source.attrs.get("import_warnings"))
            (method, options), = worksheet.analyses
            self.assertEqual(method, GROUPED_GRAPH)
            self.assertEqual(options[SERIES_PLACEMENT], {"B": STACK_PREVIOUS, "D": STACK_PREVIOUS})
            self.assertEqual(options[INTERVAL_DIRECTION], UPPER_INTERVAL)
            result = analyse(method, worksheet.frame(), options)
            apply_style(result.figure, worksheet.graph_styles[0])
            axes, = result.figure.axes
            self.assertEqual(axes.get_ylim(), (0., 40.))
            self.assertEqual([text.get_text() for text in axes.get_xticklabels()], ["Before", "After"])
            handles = axes._tramastat_grouped["handles"]
            bars = {name: handle.patches[0] for name, handle in handles.items()}
            self.assertEqual([patch.get_y() for patch in bars.values()], [0., 2., 0., 3.])
            self.assertEqual(bars["A"].get_x(), bars["B"].get_x())
            self.assertEqual(bars["C"].get_x(), bars["D"].get_x())
            self.assertLess(bars["B"].get_x(), bars["C"].get_x())
            error = handles["B"]._tramastat_grouped_series["errorbar"]
            self.assertEqual(error.lines[2][0].get_segments()[0][:, 1].tolist(), [7., 8.])
            self.assertEqual(len(error.lines[1][0].get_xdata()), 0)
            self.assertEqual(result.tables["Graph data"].loc[2, ["Lower", "Upper"]].tolist(), [4., 6.])
            worksheet.raw.loc[0, "A [2]"] = 9.
            saved = Path(scratch) / "grouped.alab"
            save_project(saved, {"Visits": worksheet})
            self.assertEqual(json.loads(saved.read_text(encoding="utf-8"))["version"], 18)
            reopened = load_project(saved)["Visits"]
            self.assertEqual(reopened.analyses, worksheet.analyses)
            self.assertEqual(reopened.graph_styles, worksheet.graph_styles)
            updated = analyse(method, reopened.frame(), options)
            self.assertEqual(updated.figure.axes[0]._tramastat_grouped["handles"]["B"].patches[0].get_y(), 5.)

    def test_unknown_or_contradictory_records_keep_the_tables_and_warning(self):
        variations = ("wrong_sheet", "wrong_position", "wrong_relation", "wrong_detail")
        with TemporaryDirectory() as scratch:
            for name in variations:
                with self.subTest(name=name):
                    project = Path(scratch) / f"{name}.pzt"
                    write_fixture(project, **{name: True})
                    source = load_tables(project, restore_legacy=True)["Visits"]
                    self.assertEqual(source.shape, (2, 9))
                    self.assertEqual(Dataset(source).analyses, [])
                    self.assertIn("Graph unavailable for Four series.", source.attrs["import_warnings"][0])
