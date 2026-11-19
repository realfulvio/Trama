from base64 import b64encode
from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory
import unittest
from zlib import compress

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.workbench import analyse
from test_prism_binary_editable import _group
from test_prism_binary_graphs import _project, _record


def template(*, row=2):
    # Two replicate columns and three rows. Each series changes direction
    # on the last row, and the stored series order differs from the XML order.
    source = b""
    for index, uid in enumerate((21, 22)):
        source += _record(0x0D, pack("<3I", index, uid, 2) + bytes(28))
    for uid, role, form, repeat in ((20, 4, 10, 1), (21, 8, 61, 2), (22, 8, 61, 2)):
        source += _group(0x800F, pack("<15i", uid, 0, 1, -1, 8, 101, -1, 1,
                                     role, form, repeat, 20, 0, 0, 0))
    graph = _record(9, b"Signals\x00") + _record(0x13, bytes(48))
    graph += _record(0x14, pack("<2i", 1, 8))
    graph += _record(0x15, pack("<3i", 2, 10, 11))
    graph += _record(0x16, pack("<H6i", 2, 21, 8, 0, 22, 8, 0))
    for uid, high, step in ((1, 4, 1), (2, 24, 6), (3, 24, 6)):
        axis, scale = bytearray(60), bytearray(134)
        pack_into("<2d", axis, 16, 0, high)
        pack_into("<H", axis, 42, 1200)
        pack_into("<H", axis, 54, uid)
        pack_into("<H3d", scale, 0, uid, 0, high, high / 1200)
        pack_into("<d", scale, 54, step)
        graph += _record(0x17, axis) + _group(0x8025, scale)
    objects = b""
    for key, uid, default, marker, color in ((11, 21, 1, 5, b"\xdd\x19\x22"),
                                               (10, 22, 0, 1, b"\x22\x33\xaa")):
        header = bytearray(144)
        pack_into("<10H", header, 0, key, 0, uid, 1, default, 2, 1, 2, 0, 256)
        pack_into("<4H", header, 58, 8, marker, 5, 1)
        for offset in (68, 84, 88):
            header[offset:offset + 3] = color
        records = _group(0x8028, header, _record(0x29, bytes(4)))
        objects += _group(0x8020, pack("<H", 9) + bytes(28), records)
        points = bytearray(3 * 249)
        for i in range(3):
            pack_into("<II", points, i * 249 + 4, uid, i if i < 2 else row)
        points[2 * 249] = 0x41
        points[2 * 249 + 77] = 1 - default
        graph += _record(0xAE, pack("<3I", key, 3, 249) + points)
    graph += _group(0x8018, bytes(12), objects)
    return _project([6], _group(0x8008, pack("<H", 8), source), _group(0x8012, pack("<H", 6), graph))


class PrismXmlErrorBarsTests(unittest.TestCase):
    def setUp(self):
        workspace = TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.path = Path(workspace.name)

    def project(self, payload):
        source = self.path / "replicates.pzt"
        source.write_text(
            '<GraphPadPrismFile PrismXMLVersion="5.00" xmlns:dt="urn:schemas-microsoft-com:datatypes">'
            '<Info ID="Info0"><Title>Notebook</Title><Constant><Name>Batch</Name><Value>A</Value></Constant></Info>'
            '<Table ID="Table8" XFormat="numbers" YFormat="replicates" Replicates="2" TableType="XY">'
            '<Title>Measurements</Title><XColumn><Title>Time</Title><Subcolumn><d>1</d><d>2</d><d>3</d>'
            '</Subcolumn></XColumn><YColumn><Title>A</Title><Subcolumn><d>2</d><d>6</d><d>10</d></Subcolumn>'
            '<Subcolumn><d>4</d><d>8</d><d>12</d></Subcolumn></YColumn><YColumn><Title>B</Title>'
            '<Subcolumn><d>12</d><d>16</d><d>20</d></Subcolumn><Subcolumn><d>14</d><d>18</d><d>22</d>'
            '</Subcolumn></YColumn></Table><Template dt:dt="bin.base64">'
            + b64encode(payload).decode() + '</Template></GraphPadPrismFile>', encoding="utf-8")
        return source

    def test_error_directions_follow_replicates_through_edit_and_reopen(self):
        source = self.project(compress(template()))
        info = []
        frame = load_tables(source, restore_prism=True, info_sheets=info)["Measurements"]
        self.assertEqual(info[0].title, "Notebook")
        self.assertFalse(Dataset(load_tables(source)["Measurements"]).analyses)
        dataset = Dataset(frame)
        method, options = dataset.analyses[0]
        result = analyse(method, dataset.frame(mask_excluded=True), options)
        points = result.tables["Saved XY coordinates"]
        self.assertEqual(points["Y"].tolist(), [13, 17, 21, 3, 7, 11])
        self.assertEqual(points["Y minus"].eq(0).tolist(), [True, True, False, False, False, True])
        self.assertEqual(points["Y plus"].eq(0).tolist(), [False, False, True, True, True, False])
        self.assertAlmostEqual(points["Y plus"].iloc[0], 2 ** 0.5)
        axes = result.figure.axes[0]
        self.assertEqual([line.get_marker() for line in axes.lines], ["s", "o"])
        self.assertEqual([line.get_color() for line in axes.lines], ["#2233aa", "#dd1922"])
        self.assertEqual(tuple(axes.get_yticks()), (0, 6, 12, 18, 24))
        self.assertIsNone(axes.get_legend())
        dataset.raw.loc[2, "A [1]"] = 16
        dataset.excluded.add((0, 0))
        native = self.path / "replicates.alab"
        save_project(native, {"Measurements": dataset})
        loaded = load_project(native)["Measurements"]
        method, options = loaded.analyses[0]
        updated = analyse(method, loaded.frame(mask_excluded=True), options).tables["Saved XY coordinates"]
        self.assertEqual(updated["X"].tolist(), [2, 3, 2, 3])
        self.assertEqual(updated["Y"].tolist(), [17, 21, 7, 14])
        self.assertAlmostEqual(updated["Y plus"].iloc[-1], 2 * 2 ** 0.5)

    def test_invalid_graph_metadata_keeps_data_and_info(self):
        for payload in (compress(template(row=1)), compress(template()) + b"junk", b"invalid zlib"):
            with self.subTest(size=len(payload)):
                info = []
                frame = load_tables(self.project(payload), restore_prism=True, info_sheets=info)["Measurements"]
                self.assertEqual(frame.shape, (3, 5))
                self.assertEqual(info[0].title, "Notebook")
                self.assertFalse(Dataset(frame).analyses)
