"""Synthetic records for generated graphs with no user data worksheets."""

from base64 import b64encode
from io import StringIO
from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory
import unittest
from xml.etree import ElementTree
from zlib import compress

from matplotlib import rc_context

from analisi.data import Dataset, load_tables, load_workspace, save_project
from analisi.legacy_xml_generated import XML_GENERATED_XY
from analisi.workbench import analyse
from test_legacy_binary_editable import _group
from test_legacy_binary_graphs import _project, _record
from test_legacy_xml_binding_layout import _note


def _dataset(uid, series, *, changed=False):
    is_x = uid == 0
    role, form = (4, 11) if is_x else (40, 10)
    header_rows = 1 if is_x else 3
    header = pack("<15i", uid, 0, 0, 4, 7, 102, -1, 4 if is_x else 1, role, form, 1,
                  0, 0, header_rows, header_rows)
    if is_x:
        samples = [(1, 0, 1), (0, 0, .5)]
    else:
        samples = [(1, 39, v) for v in (3 * series, 4 * series, 5 * series)]
        if changed and uid == 1:
            samples[0] = (1, 39, 25.)
    values = pack("<HI", 1, len(samples)) + b"".join(pack("<2Id", *value) for value in samples)
    attrs = pack("<4I", 2, 16, 16, len(samples)) + b"".join(
        pack("<4I", 0, status, 0, 0) for status, _, _ in samples
    )
    records = _record(9, (b"Input" if is_x else f"Curve {uid}".encode()) + b"\x00")
    records += _record(0x10, values) + _record(0xF3, attrs) + _record(0x90, b"\x01\x00")
    return _group(0x800F, header, records)


def _analysis(*, has_input=False):
    inputs = pack("<2i", 1, 2) if has_input else bytes(4)
    body = _record(0x3A, pack("<8H", 15, 0, 0, 0, 0, 0, 0, 0))
    body += _record(0x3B, inputs) + _record(0x3C, pack("<11i", 10, 7, *([-1] * 9)))
    for index, scale in enumerate((2., 4.)):
        expression = _record(0x49, b"Y=(2*X+1)*S\r\n\0")
        expression += _record(0x53, b"S\0") + _record(0x54, pack("<d", scale))
        body += _group(0x8047, pack("<11I", 1, index, 1, *([0] * 8)), _group(0x8048, bytes(10), expression))
    return _group(0x8039, pack("<H", 4), body)


def _figure(*, percent=False):
    body = _record(9, b"Generator test\0") + _record(0x14, pack("<2i", 1, 7))
    body += _record(0x15, pack("<3i", 2, 11, 9)) + _record(0x16, pack("<H6i", 2, 1, 0, 0, 2, 0, 0))
    for index, end, step, name_id in ((20, 3, 1, 30), (21, 24, 6, 31), (22, 24, 6, 33)):
        axis, scale = bytearray(60), bytearray(134)
        pack_into("<2d", axis, 16, 0, end)
        pack_into("<H", axis, 42, 1200)
        pack_into("<H", axis, 48, name_id)
        pack_into("<H", axis, 54, index)
        pack_into("<H3d", scale, 0, index, 0, end, end / 1200)
        pack_into("<Hd", scale, 52, 2, step)
        if name_id == 31 and percent:
            scale[102] = ord("%")
        body += _record(0x17, axis) + _group(0x8025, scale)
    chart = bytearray(48)
    pack_into("<4h", chart, 0, 200, 300, 1400, 1500)
    pack_into("<H", chart, 32, 32)
    body += _record(0x13, chart)

    objects = _note(30, b"Dose", (200, 1520, 510, 1580))
    objects += _note(31, b"Response", (100, 300, 170, 600))
    objects += _note(32, b"Generated response", (410, 200, 960, 280))
    objects += _note(34, b"Marker $ 4", (300, 360, 620, 580))
    for key, uid, color in ((9, 1, "220077"), (11, 2, "007144")):
        line = bytearray(144)
        pack_into("<8H", line, 0, key, 0, uid, 1, 2, 0, 0, 2)
        line[84:87] = bytes.fromhex(color)
        objects += _group(0x8020, pack("<H", 9) + bytes(28), _group(0x8028, line))
    body += _group(0x8018, bytes(12), objects)
    return _group(0x8012, pack("<H", 6), body)


def _template(**options):
    layout = _record(0x8E, pack("<9i", -1, 0, -1, -1, 10, 0, -1, -1, -2))
    links = b"".join(_record(0x0D, pack("<6I", uid - 1, uid, 1, 0, 0, 0)) for uid in (1, 2))
    datasets = _dataset(0, 0) + _dataset(1, 2, changed=options.get("changed")) + _dataset(2, 4)
    table = _group(0x8008, pack("<H", 7), layout + links + datasets)
    data = bytearray(_project([6], _analysis(has_input=options.get("has_input")), table,
                              _figure(percent=options.get("percent"))))
    index_start = 8 + len(_record(0x8001, bytes(12))) + len(_record(0x8002, b""))
    pack_into("<I", data, index_start + 44, 1)
    pack_into("<I", data, index_start + 2060, 4)
    return b64encode(compress(data)).decode()


def _write(path, **options):
    path.write_text(
        '<GraphPadPrismFile PrismXMLVersion="5.00" xmlns:dt="urn:schemas-microsoft-com:datatypes">'
        '<Info ID="Info0"><Title>Notebook</Title><Constant><Name>Batch</Name><Value>S1</Value></Constant></Info>'
        '<TableSequence/><Template dt:dt="bin.base64">' + _template(**options) +
        '</Template></GraphPadPrismFile>', encoding="utf-8",
    )


class GeneratedGraphTests(unittest.TestCase):
    def test_original_values_order_appearance_and_edit_roundtrip(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "generator.pzt"
            _write(path, percent=True)
            info = []
            tables = load_tables(path, restore_legacy=True, info_sheets=info)
            self.assertEqual(info[0].fields, (("Batch", "S1"),))
            self.assertEqual(list(tables), ["Generator test"])
            dataset = Dataset(tables["Generator test"])
            self.assertEqual(dataset.raw.to_numpy().tolist(), [[1, 6, 12], [1.5, 8, 16], [2, 10, 20]])
            method, options = dataset.analyses[0]
            view = analyse(method, dataset.frame(mask_excluded=True), options)
            axes = view.figure.axes[0]
            self.assertEqual(axes.get_xlabel(), "Dose")
            self.assertEqual(axes.get_title(), "Generated response")
            self.assertEqual(tuple(axes.get_xticks()), (0, 1, 2, 3))

            self.assertEqual(axes.yaxis.get_major_formatter()(18, 0), "18%")
            self.assertNotIn("%", axes.xaxis.get_major_formatter().format_data_short(3))
            self.assertEqual([line.get_color() for line in axes.lines], ["#007144", "#220077"])
            self.assertEqual([text.get_text() for text in axes.texts], ["Marker $ 4"])
            self.assertEqual(view.tables["Saved equations"]["Parameters"].tolist(), ["S=2", "S=4"])

            dataset.raw.iat[1, 1] = 7.5
            dataset.excluded.add((0, 2))
            native = Path(folder) / "roundtrip.alab"
            save_project(native, {"Generator test": dataset}, info_sheets=info)
            saved, _, reopened_info = load_workspace(native, include_info=True)
            loaded = saved["Generator test"]
            self.assertEqual(list(reopened_info), info)
            method, options = loaded.analyses[0]
            result = analyse(method, loaded.frame(mask_excluded=True), options)
            self.assertEqual(list(result.figure.axes[0].lines[1].get_ydata()), [6, 7.5, 10])
            self.assertTrue(result.tables["Saved XY coordinates"]["Y"].isna().iloc[0])
            self.assertEqual(result.figure.axes[0].yaxis.get_major_formatter()(18, 0), "18%")

    def test_annotation_fits_saved_width_and_legacy_style_still_renders(self):
        def svg_font_size(figure, size):
            figure.set_size_inches(*size)
            target = StringIO()
            with rc_context({"svg.fonttype": "none"}):
                figure.savefig(target, format="svg")
            xml = ElementTree.fromstring(target.getvalue())
            label, = [node for node in xml.iter("{http://www.w3.org/2000/svg}text")
                      if node.text == "Marker $ 4"]
            return float(label.attrib["style"].split("font-size: ", 1)[1].split("px", 1)[0])

        with TemporaryDirectory() as folder:
            path = Path(folder) / "generator.pzt"
            _write(path)
            dataset = Dataset(load_tables(path, restore_legacy=True)["Generator test"])
        method, options = dataset.analyses[0]
        style = options[XML_GENERATED_XY]
        note, = style["notes"]
        self.assertAlmostEqual(note[3], 320 / 1200)
        figure = analyse(method, dataset.frame(), options).figure
        small_size = (2.4, 2.2)
        compact = svg_font_size(figure, small_size)
        full = svg_font_size(figure, (8, 5))
        legacy_options = {XML_GENERATED_XY: {**style, "notes": [note[:3]]}}
        legacy = analyse(method, dataset.frame(), legacy_options).figure
        self.assertLess(compact, full)
        self.assertAlmostEqual(svg_font_size(legacy, small_size), full)
        self.assertAlmostEqual(svg_font_size(figure, small_size), compact)

    def test_denied_ownership_and_mismatched_samples_keep_info(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "generator.pzt"
            for options in ({"has_input": True}, {"changed": True}, {}):
                with self.subTest(options=options):
                    _write(path, **options)
                    info = []
                    tables = load_tables(path, restore_legacy=bool(options), info_sheets=info)
                    self.assertEqual(info[0].title, "Notebook")
                    self.assertFalse(tables)
