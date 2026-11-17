from struct import pack, pack_into
import unittest

import pandas as pd

from analisi.prism_binary_editable import read_editable_graphs, render_editable_graph
from analisi.prism_binary_graphs import read_binary_graphs
from test_prism_binary_graphs import _emf, _project, _record


def _group(tag, header, children=b""):
    return _record(tag, header) + children + pack("<H", tag - 0x4000)


def _plus(tag, flags, payload):
    return pack("<HHII", tag, flags, len(payload) + 12, len(payload)) + payload


def _plot_emf(*, annotation=False, second_curve=False, ambiguous=False):
    version = 0xDBC01002
    commands = b""
    for index, rgb in ((1, 0xFF336699), (2, 0xFFE04040)):
        pen = pack("<4If6I", version, 0, 208, 0, 12.0, 0, 0, 0, version, 0, rgb)
        commands += _plus(0x4008, 0x0200 + index, pen)
    for endpoints in ((194, 1400, 1206, 1400), (200, 1406, 200, 394)):
        path = pack("<3I4h4B", version, 2, 0x4000, *endpoints, 0, 1, 0, 0)
        commands += _plus(0x4008, 0x0303, path) + _plus(0x4015, 3, pack("<I", 1))
    points = ((200, 1400), (200, 1400), (200, 1400), (700, 400), (700, 400), (1200, 1400))
    commands += _plus(0x400D, 0x4002, pack("<I", len(points))
                      + b"".join(pack("<hh", *point) for point in points))
    if second_curve:
        if not ambiguous:
            points = ((200, 1150), (200, 1150), (200, 1150), (700, 900), (700, 900), (1200, 1150))
        commands += _plus(0x400D, 0x4001, pack("<I", len(points))
                          + b"".join(pack("<hh", *point) for point in points))
    if annotation:
        commands += _plus(0x400D, 0x4001, pack("<I4h", 2, 500, 900, 650, 900))
    record = pack("<III4s", 70, 16 + len(commands), 4 + len(commands), b"EMF+") + commands
    return _emf(record)


def _binary_xy(dataset=17, *, log_x=False, annotation=False, second_curve=False, ambiguous=False):
    sheet_id, graph_id, series_id = 8, 6, 5
    emf = _plot_emf(annotation=annotation, second_curve=second_curve, ambiguous=ambiguous)
    graph = _record(9, b"Graph name\0") + _record(0x5E, pack("<II", len(emf), 1) + bytes(128) + emf)
    graph += _record(0x13, pack("<4h", 200, 400, 1200, 1400) + bytes(40))
    graph += _record(0x14, pack("<2i", 1, sheet_id))
    order = [6, series_id] if second_curve else [series_id]
    graph += _record(0x15, pack(f"<{len(order) + 1}i", len(order), *order))
    links = pack("<3i", dataset, 8, 12)
    if second_curve:
        links += pack("<3i", 18, 8, 12)
    graph += _record(0x16, pack("<H", len(order)) + links)
    for index, high in enumerate((2.0, 1.0, 1.0)):
        axis = bytearray(60)
        pack_into("<2d", axis, 16, 0.0, high)
        log = int(log_x and index == 0)
        pack_into("<H", axis, 42, 1000)
        pack_into("<H", axis, 46, log)
        pack_into("<H", axis, 54, index + 1)
        graph += _record(0x17, axis)
        scale = bytearray(122)
        pack_into("<H3d", scale, 0, index + 1, 0.0, high, high / 1000)
        pack_into("<H", scale, 28, log)
        graph += _group(0x8025, scale)
    series = bytearray(144)
    pack_into("<4H", series, 0, series_id, 0, dataset, 1)
    pack_into("<H", series, 58, 0x88)
    cache = _record(0x29, pack("<7i", 6, 0, 0, 500, 1000, 1000, 0))
    header = pack("<H", 9) + bytes(28)
    objects = _group(0x8020, header, _group(0x8028, series, cache))
    if second_curve:
        pack_into("<4H", series, 0, 6, 0, 18, 1)
        if not ambiguous:
            cache = _record(0x29, pack("<7i", 6, 0, 250, 500, 500, 1000, 250))
        objects += _group(0x8020, header, _group(0x8028, series, cache))
    if annotation:
        objects += _group(0x8020, pack("<H", 3) + bytes(28))
    graph += _group(0x8018, bytes(12), objects)
    y_ids = [17, 18] if second_curve else [17]
    source = b"".join(_record(0x0D, pack("<3I", index, uid, 1) + bytes(12))
                      for index, uid in enumerate(y_ids))
    for data_id, role in [(4, 4), *((uid, 8) for uid in y_ids)]:
        source += _group(0x800F, pack("<15i", data_id, 0, 0, -1, sheet_id, 101, 0,
                                     1, role, 10, 1, 0, 0, 3, 3))
    return _project([graph_id], _group(0x8008, pack("<H", sheet_id), source),
                    _group(0x8012, pack("<H", graph_id), graph))


class EditablePrismGraphTests(unittest.TestCase):
    def test_graph_binds_saved_ids_and_uses_the_corroborated_pen(self):
        frame = pd.DataFrame({"Time": [0.0, 1.0, 2.0], "Response": [0.0, 1.0, 0.0]})
        points, style = read_editable_graphs(_binary_xy(), {8: frame}, {}, 12)[6]
        self.assertEqual(list(points.columns), ["X", "Y", "Series", "Dataset"])
        self.assertEqual(list(points["Series"]), ["Response"] * 3)
        self.assertEqual(style["axes"][0]["color"], "#336699")
        self.assertEqual(style["series"][0]["color"], "#e04040")
        self.assertEqual(style["axes"][0]["bounds"], [0.0, 2.0])

    def test_log_axis_uses_untransformed_editable_coordinates(self):
        frame = pd.DataFrame({"Dose": [1.0, 10.0, 100.0], "Response": [0.0, 1.0, 0.0]})
        points, style = read_editable_graphs(_binary_xy(log_x=True), {8: frame}, {}, 12)[6]
        axes = render_editable_graph(points, style).axes[0]
        self.assertEqual(axes.get_xscale(), "log")
        self.assertEqual(axes.get_xlim(), (1.0, 100.0))
        self.assertEqual(list(axes.lines[0].get_xdata()), [1.0, 10.0, 100.0])

    def test_missing_binding_or_inconsistent_coordinates_leave_original_preview(self):
        frame = pd.DataFrame({"Time": [0.0, 1.0, 2.0], "Response": [0.0, 1.0, 0.0]})
        self.assertFalse(read_editable_graphs(_binary_xy(22), {8: frame}, {}, 100))
        frame.loc[1, "Response"] = 0.5
        data = _binary_xy()
        self.assertFalse(read_editable_graphs(data, {8: frame}, {}, 100))
        previews, skipped = read_binary_graphs(data)
        self.assertEqual(([graph["id"] for graph in previews], skipped), ([6], []))

    def test_plot_remains_native_after_coordinate_edits(self):
        frame = pd.DataFrame({
            "X": [0.0, 1.0, 0.0, 1.0], "Y": [0.0, 0.5, 0.5, -0.5],
            "Dataset": [4, 4, 3, 3], "Series": ["Saved curve", "Saved curve", "Second", "Second"],
        })
        style = {
            "title": "Saved title",
            "axes": [
                {"label": "Time", "bounds": [0, 1], "cross": 0, "color": "#336699",
                 "width": 1.5, "ticks": [[0, ""], [1, ""]]},
                {"label": "Response", "bounds": [-1, 1], "cross": 0, "color": "#000000",
                 "width": 1.5, "ticks": [[-1, "Low"], [1, "High"]]},
            ],
            "series": [{"id": 3, "color": "#000000", "width": 1.0},
                       {"id": 4, "color": "#e04040", "width": 2.0}],
            "references": [],
        }
        frame.loc[1, "Y"] = 0.875
        axes = render_editable_graph(frame, style).axes[0]
        self.assertEqual([line.get_label() for line in axes.lines], ["Second", "Saved curve"])
        self.assertEqual(axes.lines[1].get_color(), "#e04040")
        self.assertEqual(list(axes.lines[1].get_ydata()), [0.0, 0.875])
        self.assertEqual(axes.spines["bottom"].get_position(), ("data", 0))
        self.assertEqual(axes.get_ylabel(), "Response")
        self.assertEqual([label.get_text() for label in axes.get_yticklabels()], ["Low", "High"])


if __name__ == "__main__":
    unittest.main()
