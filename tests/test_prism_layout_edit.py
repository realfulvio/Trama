import base64
from pathlib import Path
from struct import pack
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from analisi.prism_layout_edit import editable_panels, edited_layout_preview, export_edited_layout
from analisi.prism_binary_graphs import validate_binary_graph
from test_prism_binary_graphs import _emf, _with_plus


def scene(integer):
    inner = _emf()
    image_size = len(inner) + 28
    obj = pack("<HH6I", 0x4008, 0x0501, image_size, image_size - 12,
               0xDBC01001, 2, 4, len(inner)) + inner
    if integer:
        draw = pack("<HH4I4f4h", 0x401A, 0x4001, 44, 32, 0xFFFFFFFF, 2,
                    0, 0, 120, 80, 10, 10, 100, 60)
    else:
        draw = pack("<HH4I4fI6f", 0x401B, 1, 64, 52, 0xFFFFFFFF, 2,
                    0, 0, 120, 80, 3, 10, 10, 110, 10, 10, 70)
    second = pack("<HH4I4f4h", 0x401A, 0x4001, 44, 32, 0xFFFFFFFF, 2,
                  0, 0, 120, 80, 120, 80, 100, 60)
    raw = _with_plus(obj + draw + second)
    preview = {"format": "emf", "data": base64.b64encode(raw).decode("ascii")}
    return preview, raw, obj, draw, second


class LayoutEditTests(unittest.TestCase):
    def test_complete_layout_with_reflowed_coordinates_keeps_drawn_panels_editable(self):
        preview, raw, obj, first, second = scene(True)
        placements = [{"graph_id": 4, "bounds": [9, 10, 109, 70]},
                      {"graph_id": 5, "bounds": [119, 80, 219, 140]}]
        self.assertEqual(editable_panels(preview, placements, {}), [])
        panels = editable_panels(preview, placements, {}, placements_complete=True)
        self.assertEqual([p["bounds"] for p in panels], [[10, 10, 110, 70], [120, 80, 220, 140]])
        self.assertEqual([p["graph_id"] for p in panels], [None, None])
        current = edited_layout_preview(preview, panels, {"1": [14, 18, 90, 60]})
        expected = _with_plus(obj + first[:-8] + pack("<4h", 14, 18, 76, 42) + second)
        self.assertEqual(validate_binary_graph(current, layout=True), expected)
        self.assertEqual(validate_binary_graph(preview, layout=True), raw)
        for incomplete in (placements[:1], [placements[0], placements[0]],
                           [placements[0], {**placements[1], "graph_id": None}]):
            self.assertEqual(editable_panels(preview, incomplete, {}, placements_complete=True), [])

    def test_only_the_selected_destination_changes(self):
        for integer in (True, False):
            with self.subTest(integer=integer):
                preview, raw, obj, draw, second = scene(integer)
                panels = editable_panels(preview, [{"graph_id": 4, "bounds": [10, 10, 110, 70]},
                                                   {"graph_id": 5, "bounds": [120, 80, 220, 140]}],
                                         {4: "First", 5: "Second"})
                self.assertEqual([panel["title"] for panel in panels], ["First", "Second"])
                original = validate_binary_graph(edited_layout_preview(preview, panels, {}), layout=True)
                self.assertEqual(original, raw)
                output = edited_layout_preview(preview, panels, {"1": [14, 18, 90, 60]})
                edited = validate_binary_graph(output, layout=True)
                coords = pack("<4h", 14, 18, 76, 42) if integer else pack("<6f", 14, 18, 90, 18, 14, 60)
                self.assertEqual(edited, raw.replace(obj + draw + second, obj + draw[:-len(coords)] + coords + second))
                self.assertEqual(validate_binary_graph(preview, layout=True), raw)

    def test_rejects_ambiguous_mismatched_and_outside_coordinates(self):
        preview, _, _, _, _ = scene(True)
        first = {"graph_id": 4, "bounds": [10, 10, 110, 70]}
        self.assertEqual(editable_panels(preview, [first, first], {}), [])
        self.assertEqual(editable_panels(preview, [{**first, "bounds": [11, 10, 110, 70]}], {}), [])
        panels = editable_panels(preview, [first], {})
        for edits in ({"1": [0, 10, 110, 70]}, {"1": [10, 10, 10, 70]},
                      {"2": [10, 10, 100, 60]}, {"1": [10.0, 10, 100, 60]}):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                edited_layout_preview(preview, panels, edits)

    def test_data_edit_replaces_only_a_uniquely_drawn_panel_image(self):
        import pandas as pd

        from analisi.prism_layout_edit import layout_panel_artwork

        points = (10, 60, 10, 60, 10, 60, 20, 40)
        curve = pack("<HHIII8h", 0x400D, 0x4000, 32, 20, 4, *points)
        inner = _with_plus(curve)
        image_size = len(inner) + 28
        obj = pack("<HH6I", 0x4008, 0x0501, image_size, image_size - 12,
                   0xDBC01001, 2, 4, len(inner)) + inner
        _, _, _, draw, second = scene(True)
        panels = [{"id": "1", "bounds": [10, 10, 110, 70]}]

        def preview(commands):
            return {"format": "emf", "data": base64.b64encode(_with_plus(commands)).decode("ascii")}

        self.assertEqual(layout_panel_artwork(preview(obj + draw + second), panels), {})
        original = preview(obj + draw)
        self.assertEqual(layout_panel_artwork(original, panels)["1"]["format"], "emf")
        style = {"kind": "emf-xy-curve", "chart": [10, 20, 110, 70], "source": [[0, 1], [1, 3]],
                 "axes": [{"scale": "linear", "bounds": [0, 10], "unit": .1},
                          {"scale": "linear", "bounds": [0, 5], "unit": .1}]}
        frame = pd.DataFrame({"X": [0, 1], "Y": [1, 4], "Series": ["Curve", "Curve"]})
        output = edited_layout_preview(original, panels, {}, {"1": (frame, style)})
        new_points = (*points[:6], 20, 30)
        self.assertEqual(validate_binary_graph(output, layout=True),
                         _with_plus(obj.replace(pack("<8h", *points), pack("<8h", *new_points)) + draw))
        self.assertEqual(validate_binary_graph(original, layout=True), _with_plus(obj + draw))

        with TemporaryDirectory() as directory:
            path = Path(directory) / "layout.EMF"
            edits = {"1": [14, 18, 90, 60]}
            export_edited_layout(path, original, panels, edits, {"1": (frame, style)})
            moved = pack("<4h", 14, 18, 76, 42)
            expected = _with_plus(obj.replace(pack("<8h", *points), pack("<8h", *new_points))
                                  + draw[:-len(moved)] + moved)
            self.assertEqual(path.read_bytes(), expected)
            with self.assertRaisesRegex(ValueError, "file name"):
                export_edited_layout(path.with_suffix(".pdf"), original, panels, edits)
            with patch("analisi.prism_binary_graphs.os.replace", side_effect=PermissionError("locked")):
                with self.assertRaisesRegex(PermissionError, "locked"):
                    export_edited_layout(path, original, panels, {})
            self.assertEqual(path.read_bytes(), expected)
            self.assertEqual(list(path.parent.iterdir()), [path])
