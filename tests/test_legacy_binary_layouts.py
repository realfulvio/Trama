import base64
from struct import pack, pack_into
import unittest

from analisi.legacy_binary_graphs import validate_binary_graph
from analisi.legacy_binary_layouts import read_binary_layouts
from test_legacy_binary_graphs import _emf, _record


def _project(layout_ids, *groups, graph_ids=()):
    index = bytearray(10064)
    pack_into("<I", index, 48, len(graph_ids))
    pack_into(f"<{len(graph_ids)}i", index, 4060, *graph_ids)
    pack_into("<I", index, 52, len(layout_ids))
    pack_into(f"<{len(layout_ids)}i", index, 6060, *layout_ids)
    return (b"PCFFGRA4" + _record(0x8001, bytes(12)) + _record(0x8002, index)
            + pack("<H", 0x4002) + b"".join(groups) + pack("<H", 0x4001))


def _layout(uid, title, *records):
    return (_record(0x8035, pack("<H", uid)) + _record(9, title + b"\0")
            + b"".join(records) + pack("<H", 0x4035))


def _preview(emf):
    return _record(0x61, pack("<II", len(emf), 1) + bytes(128) + emf)


def _position(uid, *, kind=11):
    coordinates = pack("<13hI", kind, 264, 264, 2227, 1696, 300, 300, 2191, 1660,
                       324, 324, 2167, 1636, 0)
    return _record(0x8020, coordinates) + _record(0x2F, pack("<H", uid)) + pack("<H", 0x4020)


def _objects(*positions, graph_ids=(), nested_count=0):
    references = pack("<H", len(graph_ids))
    for uid in graph_ids:
        references += pack("<6H", uid, 0, 65535, 0, 0, 0)
    return (_record(0x37, references) + _record(0x8018, pack("<III", 1, len(positions) + nested_count, nested_count))
            + b"".join(positions) + pack("<H", 0x4018))


def _nested_emf(inner, *, image_type=2, metafile_type=4, length=None, version=0xDBC01002,
                draw=None):
    image_size = len(inner) + 28
    header = pack("<HH6I", 0x4008, 0x0501, image_size, image_size - 12,
                  version, image_type, metafile_type, len(inner) if length is None else length)
    if draw is None:
        draw = pack("<HH4I4fI6f", 0x401B, 1, 64, 52, 0xFFFFFFFF, 2, 0, 0, 120, 80, 3,
                    10, 10, 110, 10, 10, 70)
    payload = header + inner + draw
    return _emf(pack("<III4s", 70, 16 + len(payload), 4 + len(payload), b"EMF+") + payload)


def _draw_image(*, object_id=1, source_width=120, width=100, attributes=0xFFFFFFFF):
    return pack("<HH4I4f4h", 0x401A, 0x4000 | object_id, 44, 32, attributes, 2,
                0, 0, source_width, 80, 10, 10, width, 60)


class BinaryLayoutTests(unittest.TestCase):
    def test_index_controls_order_and_binds_original_emf_to_own_layout(self):
        first = _emf()
        second = _emf(pack("<II4i", 43, 24, 5, 6, 14, 22))
        project = _project([2, 9], _layout(9, b"Page B", _preview(second)),
                           _layout(17, b"unlisted", _preview(first)),
                           _layout(2, b"Page A", _preview(first)))
        layouts, skipped = read_binary_layouts(project)
        self.assertEqual([(item["id"], item["title"]) for item in layouts], [(2, "Page A"), (9, "Page B")])
        self.assertEqual([validate_binary_graph(item["preview"], layout=True) for item in layouts],
                         [first, second])
        self.assertEqual(skipped, [])

    def test_duplicate_group_cannot_replace_an_indexed_page(self):
        group = _layout(2, b"Page A", _preview(_emf()))
        layouts, skipped = read_binary_layouts(_project([2], group, group))
        self.assertEqual((layouts, skipped), ([], ["Layout 2"]))

    def test_placement_geometry_links_only_indexed_graphs(self):
        positions = _objects(_position(4), _position(65535), graph_ids=[4, 65535])
        project = _project([2], _layout(2, b"Page", positions), graph_ids=[4])
        layout, = read_binary_layouts(project)[0]
        self.assertEqual(layout["placements"],
                         [{"graph_id": 4, "bounds": [324, 324, 2167, 1636]},
                          {"graph_id": None, "bounds": [324, 324, 2167, 1636]}])
        self.assertTrue(layout["placements_complete"])
        self.assertNotIn("preview", layout)

        layout, = read_binary_layouts(_project([2], _layout(2, b"Page", positions)))[0]
        self.assertEqual([part["graph_id"] for part in layout["placements"]], [None])
        self.assertFalse(layout["placements_complete"])

    def test_unrecognized_layout_objects_leave_verified_links_without_full_composition(self):
        positions = _objects(_position(4), _position(0, kind=2), graph_ids=[4])
        layout, = read_binary_layouts(_project([2], _layout(2, b"Page", positions), graph_ids=[4]))[0]
        self.assertEqual([part["graph_id"] for part in layout["placements"]], [4])
        self.assertFalse(layout["placements_complete"])

    def test_nested_object_count_preserves_direct_graph_links(self):
        positions = _objects(_position(4), graph_ids=[4], nested_count=1)
        layout, = read_binary_layouts(_project([2], _layout(2, b"Page", positions), graph_ids=[4]))[0]
        self.assertEqual([part["graph_id"] for part in layout["placements"]], [4])
        self.assertFalse(layout["placements_complete"])

    def test_validated_nested_emf_is_layout_only(self):
        drawing = _nested_emf(_emf())
        layout, = read_binary_layouts(_project([2], _layout(2, b"Page", _preview(drawing))))[0]
        self.assertEqual(validate_binary_graph(layout["preview"], layout=True), drawing)
        with self.assertRaises(ValueError):
            validate_binary_graph(layout["preview"])

    def test_legacy_nested_image_with_integer_destination_preserves_original_page(self):
        drawing = _nested_emf(_emf(), version=0xDBC01001, draw=_draw_image())
        layout, = read_binary_layouts(_project([2], _layout(2, b"Page", _preview(drawing))))[0]
        self.assertIn("preview", layout)
        self.assertEqual(validate_binary_graph(layout["preview"], layout=True), drawing)
        with self.assertRaises(ValueError):
            validate_binary_graph(layout["preview"])

    def test_integer_destination_requires_valid_image_reference_and_geometry(self):
        for draw in (_draw_image(object_id=2), _draw_image(source_width=float("nan")),
                     _draw_image(source_width=-1), _draw_image(width=0), _draw_image(attributes=1)):
            with self.subTest(draw=draw):
                drawing = _nested_emf(_emf(), version=0xDBC01001, draw=draw)
                layout, = read_binary_layouts(_project([2], _layout(2, b"Page", _preview(drawing))))[0]
                self.assertNotIn("preview", layout)

    def test_malformed_and_deeply_nested_images_are_rejected(self):
        for drawing in (_nested_emf(_emf(), image_type=1), _nested_emf(_emf(), metafile_type=3),
                        _nested_emf(_emf(), length=1), _nested_emf(_nested_emf(_emf())),
                        _nested_emf(_emf(pack("<4I", 105, 16, 0, 0)))):
            with self.subTest(drawing=drawing[140:156]):
                payload = {"format": "emf", "data": base64.b64encode(drawing).decode("ascii")}
                with self.assertRaises(ValueError):
                    validate_binary_graph(payload, layout=True)
                layout, = read_binary_layouts(_project([2], _layout(2, b"Page", _preview(drawing))))[0]
                self.assertNotIn("preview", layout)


if __name__ == "__main__":
    unittest.main()
