import json
from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.prism_restore import SAVED_BINARY_LAYOUT
from analisi.workbench import analyse
from test_prism_binary_editable import _group
from test_prism_binary_graphs import _record


def _graph(markers, fen_id=8, saved_presentation=False):
    graph = _record(0x14, pack("<2i", 1, 14))
    graph += _record(0x15, pack("<3i", 2, 21, 20))
    graph += _record(0x16, pack("<H6i", 2, 205, -1, -1, 206, -1, -1))
    for uid, limits, tick in ((1, (0, 4), 1), (2, (0, 6), 2), (3, (0, 6), 2)):
        low, high = limits
        axis, scale = bytearray(60), bytearray(134)
        pack_into("<2d", axis, 16, low, high)
        pack_into("<H", axis, 42, 1200)
        pack_into("<H", axis, 48, 30 + uid)
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
    if saved_presentation:
        chart = bytearray(48)
        pack_into("<4h", chart, 0, 100, 200, 1300, 1400)
        pack_into("<H", chart, 32, 30)
        graph += _record(0x13, chart)
        background = pack("<H4h", 10, 40, 120, 1390, 1500) + bytes(20)
        objects += _group(0x8020, background, b"")
        for identity, hidden, caption in ((30, True, b"Saved title"), (31, False, b"Elapsed $ hours"),
                                          (32, True, b"Source units"), (33, True, b"Right axis")):
            flags = 0x200 if hidden else 0
            header = pack("<H", 2) + bytes(26) + pack("<H", flags)
            text = _record(0x102C, caption)
            text += _record(0x102D, pack("<HHIHIHI", 1, 2, 0, 1, 12, 10, 65001))
            objects += _group(0x8020, header, _group(0x902B, pack("<H", identity) + bytes(16), text))
        for key, _, _ in markers:
            header = pack("<H", 14) + bytes(26) + pack("<H", 0x202)
            legend = _record(0x9D, pack("<3i", 1, 203, key) + bytes(492))
            legend += _record(0x209D, pack("<IfI", 2, 8, key))
            objects += _group(0x8020, header, legend)
    graph += _group(0x8018, bytes(12), objects)
    return b"PCFFGRA4" + _group(0x8001, bytes(12), _group(0x8012, pack("<H", fen_id), graph))


def _layout(graph_id=9, arrow_direction=0, saved_presentation=False):
    dimensions = pack("<2i", 850, 1100) + bytes(292)
    references = pack("<H", 2)
    references += b"".join(pack("<IH6s", uid, 65535, bytes(6)) for uid in (8, 9))
    objects = b""
    for uid, bounds in ((8, (300, 400, 4000, 1800)), (graph_id, (500, 2200, 4200, 3600))):
        panel = pack("<H", 11) + bytes(16) + pack("<4h", *bounds) + bytes(4)
        link = _record(0x2F, pack("<H", uid))
        if saved_presentation:
            link += _record(0x30, pack("<2H", 1398, 1428))
        objects += _group(0x8020, panel, link)
    line = pack("<H", 3) + bytes(28)
    points = b"".join(_record(0xD9, pack("<iii8s", 2, x, y, bytes(8)))
                      for x, y in ((3900, 1750), (600, 2300)))
    stroke = bytearray(26)
    stroke[4:7] = bytes.fromhex("236789")
    pack_into("<3H", stroke, 8, arrow_direction, 1, 0)
    pack_into("<f", stroke, 22, 6)
    endpoint_group = _group(0x80D8, pack("<I", 2) + bytes(28), points)
    objects += _group(0x8020, line, _record(0x23, stroke) + endpoint_group)
    scene = _group(0x8018, pack("<3I", 11, 3, 0), objects)
    layout = _record(0xA, dimensions) + _record(0x37, references) + scene
    units = _record(0xA1, pack("<i", 600) + bytes(100))
    return b"PCFFGRA4" + _group(0x8001, bytes(12), units + _group(0x8035, pack("<H", 0), layout))


def _write(project, *, bad_link=False, layout_link=None, arrow_direction=0, saved_presentation=False):
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
    if layout_link is not None:
        sheets = members["document.json"]["sheets"]
        sheets["graphs"].append("detail")
        sheets["layouts"] = ["page"]
        chart = members["graphs/chart/sheet.json"]
        members["graphs/detail/sheet.json"] = {**chart, "uid": "detail", "fenID": 9, "title": "Detailed signals"}
        members["layouts/page/sheet.json"] = {"uid": "page", "fenID": 0, "title": "Results page",
                                              "linkedGraphSheets": ["chart", "detail"], "mediaCollection": []}
    with ZipFile(project, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, json.dumps(data))
        archive.writestr("data/tables/raw/data.csv", "1,3,\n2,,\n3,5,\n")
        archive.writestr("graphs/chart/data.bin", _graph([(20, 205, "22aaff"),
                                                         (21, 207 if bad_link else 206, "ff0088")],
                                                        saved_presentation=saved_presentation))
        if layout_link is not None:
            detail = _graph([(20, 205, "22aaff"), (21, 206, "ff0088")], fen_id=9,
                            saved_presentation=saved_presentation)
            archive.writestr("graphs/detail/data.bin", detail)
            archive.writestr("layouts/page/data.bin", _layout(layout_link, arrow_direction, saved_presentation))


class PrismZipSparseXYTests(unittest.TestCase):
    def test_saved_labels_and_marker_presentation_apply_to_graph_and_layout(self):
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "saved-style.pzt"
            _write(path, layout_link=9, saved_presentation=True)
            table = Dataset(load_tables(path, restore_prism=True)["Signals"])
            for method, settings in (table.analyses[0], table.analyses[2]):
                figure = analyse(method, table.frame(mask_excluded=True), settings).figure
                for axes in figure.axes:
                    self.assertEqual(axes.get_title(), "")
                    self.assertEqual(axes.get_xlabel(), "Elapsed $ hours")
                    self.assertEqual(axes.get_ylabel(), "")
                    self.assertIsNone(axes.get_legend())
                    self.assertEqual([line.get_marker() for line in axes.lines], ["v"])
                    self.assertEqual([line.get_markersize() for line in axes.lines], [8])
                    if method == SAVED_BINARY_LAYOUT:
                        x, y, width, height = axes.get_position().bounds
                        self.assertAlmostEqual(x, 84 / 1398)
                        self.assertAlmostEqual(y, 124 / 1428)
                        self.assertAlmostEqual(width, 1200 / 1398)
                        self.assertAlmostEqual(height, 1200 / 1428)

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

    def test_positioned_layout_round_trips_and_redraws_panels_from_the_edited_table(self):
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "positioned.pzt"
            _write(path, layout_link=9)
            tables = load_tables(path, restore_prism=True)
            self.assertEqual(list(tables), ["Signals"])
            dataset = Dataset(tables["Signals"])
            method, options = dataset.analyses[2]
            self.assertEqual(method, SAVED_BINARY_LAYOUT)
            figure = analyse(method, dataset.frame(mask_excluded=True), options).figure
            self.assertEqual(tuple(figure.get_size_inches()), (8.5, 11.0))
            self.assertEqual([axes.get_title() for axes in figure.axes], ["Signals by date", "Detailed signals"])
            self.assertAlmostEqual(figure.subfigs[0].bbox.x0 / figure.bbox.width, 300 / 5100)
            self.assertAlmostEqual(figure.subfigs[1].bbox.x0 / figure.bbox.width, 500 / 5100)
            self.assertAlmostEqual(figure.subfigs[1].bbox.y1 / figure.bbox.height, 1 - 2200 / 6600)
            line, = figure.artists
            self.assertEqual(tuple(line.get_xdata()), (3900 / 5100, 600 / 5100))
            self.assertEqual(tuple(line.get_ydata()), (1 - 1750 / 6600, 1 - 2300 / 6600))
            self.assertEqual(line.get_color(), "#236789")

            dataset.raw.loc[1, "B"] = 4
            saved = Path(scratch) / "positioned.alab"
            save_project(saved, {"Signals": dataset})
            restored = load_project(saved)["Signals"]
            method, options = restored.analyses[2]
            figure = analyse(method, restored.frame(mask_excluded=True), options).figure
            self.assertEqual([axes.lines[0].get_ydata().tolist() for axes in figure.axes], [[4], [4]])
            svg = Path(scratch) / "positioned.svg"
            figure.savefig(svg)
            self.assertNotIn("<image", svg.read_text(encoding="utf-8"))

    def test_layout_arrows_keep_the_saved_direction_at_each_endpoint(self):
        from matplotlib.patches import Polygon

        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "arrows.pzt"
            for direction, expected in ((1, ((600, 2300),)),
                                        (2, ((3900, 1750),)),
                                        (3, ((3900, 1750), (600, 2300)))):
                with self.subTest(direction=direction):
                    _write(path, layout_link=9, arrow_direction=direction)
                    dataset = Dataset(load_tables(path, restore_prism=True)["Signals"])
                    method, options = dataset.analyses[2]
                    figure = analyse(method, dataset.frame(mask_excluded=True), options).figure
                    heads = [artist for artist in figure.artists if isinstance(artist, Polygon)]
                    self.assertEqual(len(heads), len(expected))
                    for head, (x, y) in zip(heads, expected, strict=True):
                        self.assertAlmostEqual(head.get_xy()[0][0], x / 5100)
                        self.assertAlmostEqual(head.get_xy()[0][1], 1 - y / 6600)

    def test_layout_with_a_missing_panel_keeps_the_two_viewable_graphs(self):
        with TemporaryDirectory() as scratch:
            path = Path(scratch) / "invalid-panel.pzt"
            _write(path, layout_link=10)
            frame = load_tables(path, restore_prism=True)["Signals"]
            self.assertEqual(len(Dataset(frame).analyses), 2)
            self.assertIn("Layout unavailable for Results page.", " ".join(frame.attrs.get("import_warnings", ())))
