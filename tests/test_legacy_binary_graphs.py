import base64
from io import BytesIO
from struct import pack, pack_into
import unittest

from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure

from analisi.legacy_binary_graphs import read_binary_graphs, render_binary_graph, validate_binary_graph


def _record(tag, payload):
    return pack("<HI", tag, len(payload)) + payload


def _graph(uid, title, preview=None, *, pdfs=()):
    records = _record(0x8012, pack("<H", uid)) + _record(9, title + b"\0")
    if preview is not None:
        records += _record(0x5E, pack("<II", len(preview), 1) + bytes(128) + preview)
    records += b"".join(_record(0xF00, pdf) for pdf in pdfs)
    return records + pack("<H", 0x4012)


def _project(ids, *groups, source_ids=(), analysis_ids=()):
    header = bytearray(10064)
    pack_into("<2I", header, 40, len(source_ids), len(analysis_ids))
    pack_into(f"<{len(source_ids)}i", header, 60, *source_ids)
    pack_into(f"<{len(analysis_ids)}i", header, 2060, *analysis_ids)
    pack_into("<I", header, 48, len(ids))
    pack_into(f"<{len(ids)}i", header, 4060, *ids)
    return (b"PCFFGRA4" + _record(0x8001, bytes(12)) + _record(0x8002, header)
            + pack("<H", 0x4002) + b"".join(groups) + pack("<H", 0x4001))


def _emf(record=None):
    if record is None:
        record = pack("<II4i", 43, 24, 4, 6, 12, 18)
    header = bytearray(108)
    pack_into("<II8i4sIII", header, 0, 1, 108, 0, 0, 120, 80,
              0, 0, 5080, 3387, b" EMF", 0x10000, 128 + len(record), 3)
    return bytes(header) + record + pack("<5I", 14, 20, 0, 0, 20)


def _preview(payload):
    return {"format": "emf", "data": base64.b64encode(payload).decode("ascii")}


def _plus_object(kind, size):
    record = bytearray(size)
    pack_into("<HHIII", record, 0, 0x4008, kind << 8, size, size - 12, 0xDBC01002)
    return record


def _with_plus(record):
    return _emf(pack("<III4s", 70, 16 + len(record), 4 + len(record), b"EMF+") + record)


class BinaryGraphTests(unittest.TestCase):
    def test_index_controls_order_and_preview_is_bound_to_own_graph(self):
        first, second = _emf(), _emf(pack("<II4i", 43, 24, 5, 6, 14, 22))
        graph_data = _project([27, 4, 8], _graph(4, b"same", first), _graph(8, b"missing"),
                              _graph(27, b"same", second), _graph(35, b"unlisted", first))
        graphs, skipped = read_binary_graphs(graph_data)
        self.assertEqual([(graph["id"], graph["title"]) for graph in graphs],
                         [(27, "same"), (4, "same")])
        self.assertEqual([validate_binary_graph(graph["preview"]) for graph in graphs], [second, first])
        self.assertEqual(skipped, ["missing"])

    def test_legacy_pdf_preview_fallback_retains_original_vector_bytes(self):
        figure = Figure(figsize=(2, 1))
        figure.add_subplot().plot([0, 1], [1, 0], linewidth=4)
        output = BytesIO()
        figure.savefig(output, format="pdf")
        pdf = output.getvalue()
        graphs, skipped = read_binary_graphs(_project(
            [2, 3], _graph(2, b"PDF", b"", pdfs=[pdf]), _graph(3, b"EMF", _emf(), pdfs=[pdf])))
        self.assertEqual(skipped, [])
        first, second = [graph["preview"] for graph in graphs]
        self.assertEqual(first["format"], "pdf")
        self.assertEqual(validate_binary_graph(first), pdf)
        self.assertEqual(second["format"], "emf")
        image = render_binary_graph(first, crop=False, max_side=400)
        self.assertEqual(image.size, (400, 200))
        self.assertGreater(len(image.getcolors(100_000)), 20)

        pages = BytesIO()
        with PdfPages(pages) as document:
            document.savefig(figure)
            document.savefig(figure)
        for invalid in ([pdf, pdf], [pdf[:-20]], [pages.getvalue()], [b"%PDF-1.3 %%EOF"]):
            with self.subTest(count=len(invalid), size=len(invalid[0])):
                self.assertEqual(read_binary_graphs(_project([2], _graph(2, b"bad", pdfs=invalid))),
                                 ([], ["bad"]))

    def test_truncated_preview_and_unsafe_operations_are_rejected(self):
        bad_comment = pack("<II4s", 70, 16, b"pass")
        plus_image = pack("<HHII", 0x4008, 0x0501, 12, 0)
        plus_comment = pack("<III4s", 70, 28, 16, b"EMF+") + plus_image
        escape_record = pack("<4I", 105, 16, 0, 0)
        for malformed in (_emf()[:-1], _emf(escape_record), _emf(bad_comment), _emf(plus_comment)):
            with self.subTest(malformed=malformed[-24:]), self.assertRaises(ValueError):
                validate_binary_graph(_preview(malformed))
            graphs, skipped = read_binary_graphs(_project([2], _graph(2, b"unsafe", malformed)))
            self.assertEqual((graphs, skipped), ([], ["unsafe"]))

    def test_classic_ellipse_preserves_original_preview_bytes(self):
        ellipse = pack("<II4i", 42, 24, -10, 6, 12, 18)
        emf = _emf(ellipse)
        graphs, skipped = read_binary_graphs(_project([2], _graph(2, b"ellipse", emf)))
        self.assertEqual(skipped, [])
        self.assertEqual(validate_binary_graph(graphs[0]["preview"]), emf)

    def test_classic_ellipse_rejects_invalid_size_and_bounds(self):
        invalid = (pack("<II5i", 42, 28, 4, 6, 12, 18, 0),
                   pack("<II4i", 42, 24, 4, 18, 12, 6),
                   pack("<II4i", 42, 24, 4, 6, 4, 18),
                   pack("<II4i", 42, 24, 0, 6, 100_001, 18),
                   pack("<II4i", 42, 24, 1_000_001, 6, 1_000_002, 18))
        for ellipse in invalid:
            with self.subTest(ellipse=ellipse), self.assertRaisesRegex(ValueError, "Unsupported EMF drawing record"):
                validate_binary_graph(_preview(_emf(ellipse)))

    def test_classic_stroke_path_requires_bounded_rectangle(self):
        drawing = _emf(pack("<II4i", 64, 24, 4, 6, 12, 18))
        self.assertEqual(validate_binary_graph(_preview(drawing)), drawing)
        for record in (pack("<II2i", 64, 16, 4, 6),
                       pack("<II4i", 64, 24, 12, 6, 4, 18),
                       pack("<II4i", 64, 24, 4, 6, 2_000_000, 18)):
            with self.subTest(record=record), self.assertRaises(ValueError):
                validate_binary_graph(_preview(_emf(record)))

    def test_record_counts_cannot_reference_points_outside_record(self):
        truncated_polyline = pack("<II4iIhh", 87, 32, 4, 6, 12, 18, 1000, 4, 6)
        with self.assertRaisesRegex(ValueError, "Unsupported EMF drawing record"):
            validate_binary_graph(_preview(_emf(truncated_polyline)))

    def test_extended_pen_rejects_unstored_styles(self):
        pen = pack("<14I", 95, 56, 1, 56, 0, 56, 0, 0x10007, 1, 0, 0, 0, 0x7FFFFFFF, 0)
        with self.assertRaisesRegex(ValueError, "Unsupported EMF drawing record"):
            validate_binary_graph(_preview(_emf(pen)))

    def test_bitmap_brush_palette_is_bounded_and_pointer_brushes_are_rejected(self):
        bitmap_brush = bytearray(116)
        pack_into("<8I", bitmap_brush, 0, 94, 116, 1, 0, 36, 48, 84, 32)
        pack_into("<IiiHHIIiiII", bitmap_brush, 36, 40, 8, 8, 1, 1, 0, 32, 0, 0, 0x7FFFFFFF, 0)
        pointer_brush = pack("<6I", 39, 24, 1, 3, 0, 0x7FFFFFFF)
        for malformed in (bitmap_brush, pointer_brush):
            with self.subTest(malformed=len(malformed)), self.assertRaisesRegex(ValueError, "Unsupported EMF drawing record"):
                validate_binary_graph(_preview(_emf(malformed)))

    def test_emf_plus_counts_cannot_reference_unstored_arrays(self):
        string_format = _plus_object(7, 72)
        pack_into("<II", string_format, 64, 0x7FFFFFFF, 0x7FFFFFFF)
        dashed_pen = _plus_object(2, 68)
        pack_into("<I", dashed_pen, 20, 464)
        pack_into("<I", dashed_pen, 44, 0x7FFFFFFF)
        pack_into("<II", dashed_pen, 56, 0xDBC01002, 0)
        custom_cap = _plus_object(2, 192)
        pack_into("<I", custom_cap, 20, 2258)
        pack_into("<4I", custom_cap, 48, 128, 0xDBC01002, 0, 1)
        pack_into("<4I", custom_cap, 108, 68, 0xDBC01002, 0x7FFFFFFF, 0x2000)
        pack_into("<II", custom_cap, 180, 0xDBC01002, 0)
        for malformed in (string_format, dashed_pen, custom_cap):
            with self.subTest(malformed=len(malformed)), self.assertRaisesRegex(ValueError, r"Unsupported EMF\+ record"):
                validate_binary_graph(_preview(_with_plus(malformed)))

    def test_malformed_graph_header_leaves_other_indexed_preview_available(self):
        malformed = _record(0x8012, b"\x02") + _record(9, b"broken\0") + pack("<H", 0x4012)
        graphs, skipped = read_binary_graphs(_project([2, 3], malformed, _graph(3, b"ok", _emf())))
        self.assertEqual([graph["title"] for graph in graphs], ["ok"])
        self.assertEqual(skipped, ["Graph 2"])

    def test_duplicate_index_or_ambiguous_graph_metadata_fails_closed(self):
        with self.assertRaises(ValueError):
            read_binary_graphs(_project([2, 2], _graph(2, b"ambiguous", _emf())))
        data = _project([2], _graph(2, b"ambiguous", _emf()), _graph(2, b"ambiguous", _emf()))
        self.assertEqual(read_binary_graphs(data), ([], ["Graph 2"]))


if __name__ == "__main__":
    unittest.main()
