from struct import pack, pack_into
import unittest

import pandas as pd

from analisi.data import Dataset, EDITABLE_PRISM_EMF
from analisi.grid_data import paste_block
from analisi.prism_binary_editable import read_editable_graphs
from analisi.prism_binary_graphs import read_binary_graphs, validate_binary_graph
from analisi.prism_emf_edit import CURVE, POINTS, edit_emf_preview
from analisi.prism_restore import PRISM_GRAPH_STYLE, PRISM_PREVIEW, SAVED_EDITABLE_GRAPH
from test_prism_binary_editable import _binary_xy
from test_prism_binary_graphs import _emf, _preview


def _classic_point():
    def line(x, y, xx, yy):
        return pack("<II2iII2i", 27, 16, x, y, 54, 16, xx, yy)

    marker = pack("<II4i", 42, 24, 35, 35, 45, 45)
    shape = marker + line(40, 20, 40, 50) + line(30, 20, 50, 20) + line(30, 50, 50, 50)
    # Unrelated artwork with the same record types stays untouched.
    drawing = bytearray(_emf(shape + line(10, 15, 90, 15)))
    pack_into("<I", drawing, 52, 11)
    return _preview(drawing)


class EditableEmfTests(unittest.TestCase):
    def test_annotated_curve_binds_cache_and_changes_only_the_stroke(self):
        raw = _binary_xy(annotation=True, log_x=True)
        source = pd.DataFrame({"Dose": [1., 10., 100.], "Signal": [0., 1., 0.]})
        frame, style = read_editable_graphs(raw, {8: source}, {}, 9)[6]
        self.assertEqual(style["kind"], CURVE)
        self.assertEqual(frame["X"].tolist(), [1., 10., 100.])
        preview = read_binary_graphs(raw)[0][0]["preview"]
        self.assertEqual(edit_emf_preview(frame, style, preview), preview)
        frame.loc[1, ["X", "Y"]] = [10 ** 1.2, .75]
        edited = validate_binary_graph(edit_emf_preview(frame, style, preview))
        original = validate_binary_graph(preview)
        changed = original.replace(pack("<4h", 700, 400, 700, 400), pack("<4h", 800, 650, 800, 650))
        self.assertNotEqual(changed, original)
        self.assertEqual(edited, changed)
        source.loc[1, "Signal"] = .5
        self.assertFalse(read_editable_graphs(raw, {8: source}, {}, 9))
        with self.assertRaisesRegex(ValueError, "positive"):
            frame.loc[1, "X"] = 0.
            edit_emf_preview(frame, style, preview)

    def test_multiple_curves_bind_by_geometry_and_keep_other_bytes(self):
        raw = _binary_xy(second_curve=True, annotation=True)
        source = pd.DataFrame({"Time": [0., 1., 2.], "First": [0., 1., 0.], "Second": [.25, .5, .25]})
        frame, style = read_editable_graphs(raw, {8: source}, {}, 40)[6]
        self.assertEqual(style["kind"], CURVE)
        self.assertEqual(style["series_lengths"], [3, 3])
        self.assertEqual(frame["Series"].tolist(), ["Second"] * 3 + ["First"] * 3)
        preview = read_binary_graphs(raw)[0][0]["preview"]
        self.assertEqual(edit_emf_preview(frame, style, preview), preview)
        original = validate_binary_graph(preview)

        frame.loc[1, "X"] = 1.2
        second_edited = original.replace(pack("<4h", 700, 900, 700, 900), pack("<4h", 800, 900, 800, 900))
        self.assertNotEqual(second_edited, original)
        self.assertEqual(validate_binary_graph(edit_emf_preview(frame, style, preview)), second_edited)
        frame.loc[4, "Y"] = .75
        both_edited = second_edited.replace(pack("<4h", 700, 400, 700, 400), pack("<4h", 700, 650, 700, 650))
        self.assertNotEqual(both_edited, second_edited)
        self.assertEqual(validate_binary_graph(edit_emf_preview(frame, style, preview)), both_edited)

    def test_ambiguous_curves_leave_the_original_preview_available(self):
        raw = _binary_xy(second_curve=True, ambiguous=True, annotation=True)
        source = pd.DataFrame({"Time": [0., 1., 2.], "First": [0., 1., 0.], "Second": [0., 1., 0.]})
        self.assertFalse(read_editable_graphs(raw, {8: source}, {}, 40))
        self.assertEqual([graph["id"] for graph in read_binary_graphs(raw)[0]], [6])

    def test_classic_marker_and_both_error_endpoints_move_independently(self):
        frame = pd.DataFrame({"X": [4.], "Y": [6.], "Upper error": [2.], "Lower error": [1.], "Series": ["A"]})
        style = {"kind": POINTS, "chart": [0, 0, 100, 100],
                 "axes": [{"bounds": [0., 10.], "unit": .1, "scale": "linear"}] * 2,
                 "source": [[4., 6., 2., 1.]]}
        preview = _classic_point()
        self.assertEqual(edit_emf_preview(frame, style, preview), preview)
        dataset = Dataset(frame, table_format=EDITABLE_PRISM_EMF, analyses=[
            (SAVED_EDITABLE_GRAPH, {PRISM_GRAPH_STYLE: style, PRISM_PREVIEW: preview})])
        original = validate_binary_graph(preview)
        paste_block(dataset, 0, 0, [["5", "5", "1", "2"]])
        expected = original
        for old, new in (
            ((35, 35, 45, 45), (45, 45, 55, 55)),
            ((40, 20), (50, 40)), ((40, 50), (50, 70)),
            ((30, 20), (40, 40)), ((50, 20), (60, 40)),
            ((30, 50), (40, 70)), ((50, 50), (60, 70)),
        ):
            expected = expected.replace(pack(f"<{len(old)}i", *old), pack(f"<{len(new)}i", *new))
        actual = validate_binary_graph(edit_emf_preview(dataset.raw, style, preview))
        self.assertEqual(actual, expected)
        accepted = dataset.raw.copy()
        for values in [["-1"], ["6"], [""]]:
            with self.subTest(values=values), self.assertRaises(ValueError):
                paste_block(dataset, 0, 2, [values])
            pd.testing.assert_frame_equal(dataset.raw, accepted)
        with self.assertRaisesRegex(ValueError, "numerical values"):
            paste_block(dataset, 0, 4, [["Renamed"]])

    def test_lower_only_and_split_asymmetric_strokes_keep_other_artwork(self):
        def line(x, y, xx, yy):
            return pack("<II2iII2i", 27, 16, x, y, 54, 16, xx, yy)

        def marker(x, y):
            return pack("<II4i", 42, 24, x - 5, y - 5, x + 5, y + 5)

        background = line(10, 15, 90, 15)
        strokes = line(40, 40, 40, 60) + line(79, 20, 79, 35) + line(79, 50, 79, 25)
        raw = bytearray(_emf(background + strokes + marker(40, 40) + marker(79, 30)))
        pack_into("<I", raw, 52, 12)
        preview = _preview(raw)
        frame = pd.DataFrame({"X": [4., 8.], "Y": [6., 7.],
                              "Upper error": [None, 1.], "Lower error": [2., 2.], "Series": ["A", "B"]})
        axis = {"bounds": [0., 10.], "unit": .1, "scale": "linear"}
        style = {"kind": POINTS, "chart": [0, 0, 100, 100], "axes": [axis, axis],
                 "source": [[4., 6., None, 2.], [8., 7., 1., 2.]], "limit_nudges": [0., -.1]}
        self.assertEqual(edit_emf_preview(frame, style, preview), preview)
        frame.loc[0, "Lower error"] = 3.
        frame.loc[1, ["X", "Y", "Upper error"]] = [8.1, 7.5, 1.5]
        edited = validate_binary_graph(edit_emf_preview(frame, style, preview))
        expected = (background + line(40, 40, 40, 70)
                    + line(80, 10, 80, 30) + line(80, 45, 80, 20) + marker(40, 40) + marker(80, 25))
        self.assertEqual(edited[108:108 + len(expected)], expected)
        frame.loc[0, "Upper error"] = 1.
        with self.assertRaisesRegex(ValueError, "absent"):
            edit_emf_preview(frame, style, preview)


if __name__ == "__main__":
    unittest.main()
