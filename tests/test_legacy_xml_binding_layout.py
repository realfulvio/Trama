from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory
import unittest

from analisi.legacy_binary import _DATASET
from analisi.legacy_restore import SAVED_BINARY_LAYOUT, SAVED_XY
from test_legacy_binary_editable import _group
from test_legacy_binary_graphs import _record
from test_legacy_xml_binding import binding_template, write_project
from trama_qt.project import Project


def _data_table(uid, analysis, x, y, role=8):
    storage = 101 if analysis == -1 else 102
    fields = [_DATASET.pack(serial, 0, 0, analysis, uid, storage, -1, 1, descriptor, 10, 1, x, 0, 0, 0)
              for serial, descriptor in ((x, 4), (y, role))]
    return _group(0x8008, pack("<H", uid), b"".join(_group(0x800F, field) for field in fields))


def _note(uid, text, bounds, flags=0):
    header = bytearray(30)
    pack_into("<H", header, 0, 2)
    pack_into("<4h", header, 18, *bounds)
    pack_into("<H", header, 28, flags)
    body = _group(0x802B, pack("<H", uid) + bytes(16), _record(0x2C, text))
    return _group(0x8020, header, body)


def _graph(uid, name, owners, links, notes=b""):
    body = _record(9, name + b"\0") + _record(0x14, pack("<3i", 2, *owners))
    body += _record(0x15, pack("<3i", 2, 11, 10))
    body += _record(0x16, pack("<H", 2) + b"".join(pack("<3i", *link) for link in links))
    for index, maximum in ((1, 80), (2, 100), (3, 100)):
        axis, scale = bytearray(60), bytearray(134)
        pack_into("<2d", axis, 16, 0, maximum)
        pack_into("<H", axis, 42, 1200)
        pack_into("<H", axis, 48, 30 + index)
        pack_into("<H", axis, 54, index)
        pack_into("<H3d", scale, 0, index, 0, maximum, maximum / 1200)
        pack_into("<d", scale, 54, 20)
        body += _record(0x17, axis) + _group(0x8025, scale)
    chart = bytearray(48)
    pack_into("<4h", chart, 0, 200, 200, 1400, 1400)
    pack_into("<H", chart, 32, 30)
    body += _record(0x13, chart)
    objects = notes
    for key, link, color in zip((10, 11), links, ("236789", "258479"), strict=True):
        header = bytearray(144)
        pack_into("<8H", header, 0, key, 0, link[0], 1, 2, 0, 0, 2)
        pack_into("<2H", header, 60, 1, 4)
        header[68:71] = bytes.fromhex(color)
        objects += _group(0x8020, pack("<H", 9) + bytes(28), _group(0x8028, header))
    body += _group(0x8018, pack("<3I", 1, 2, 0), objects)
    return _group(0x8012, pack("<H", uid), body)


def _layout():
    objects = b""
    for uid, bounds in ((20, (350, 600, 5100, 3850)), (21, (3000, 2050, 4850, 3690))):
        model = pack("<H", 11) + bytes(16) + pack("<4h", *bounds) + bytes(4)
        objects += _group(0x8020, model, _record(0x2F, pack("<H", uid)))
    references = pack("<H", 2) + b"".join(pack("<IH6s", uid, 65535, bytes(6)) for uid in (20, 21))
    page = (_record(9, b"Binding page\0") + _record(0xA, pack("<2i", 1100, 850) + bytes(292))
            + _record(0x37, references) + _group(0x8018, pack("<3I", 1, 2, 0), objects))
    return _record(0xA1, pack("<i", 600) + bytes(100)) + _group(0x8035, pack("<H", 2), page)


def _write(path, *, unknown_link=False):
    template = bytearray(binding_template(transform=b"Scatchard"))
    offset = 8 + len(_record(0x8001, bytes(12))) + len(_record(0x8002, b""))
    for relative, value in {40: 2, 64: 12, 48: 2, 4060: 20, 4064: 21, 52: 1, 6060: 2}.items():
        pack_into("<i", template, offset + relative, value)
    records = (_data_table(8, -1, 104, 105) + _data_table(9, 4, 106, 107, role=40)
               + _data_table(10, 6, 108, 109) + _data_table(12, -1, 110, 111)
               + _graph(20, b"Saturation chart", (8, 9), ((105, -1, -1), (107, 2, 2)),
                        _note(52, b"Estimate $ 60\rManual note", (260, 320, 520, 580))
                        + _note(53, b"Hidden note", (240, 310, 490, 460), 0x200)
                        + _note(54, b"Invalid position", (680, 360, 610, 420)))
               + _graph(21, b"Scatchard chart", (10, 12), ((109, 2, 2), (112 if unknown_link else 111, -1, -1)))
               + _layout())
    write_project(path, bytes(template[:-2]) + records + bytes(template[-2:]))
    line = ('<Table ID="Table12" XFormat="numbers" YFormat="replicates" Replicates="1" TableType="XY">'
            '<Title>Manual intercepts</Title><XColumn><Title>Bound</Title><Subcolumn><d>0</d><d>60</d></Subcolumn>'
            '</XColumn><YColumn><Title>Ratio</Title><Subcolumn><d>20</d><d>0</d></Subcolumn></YColumn></Table>')
    path.write_text(path.read_text(encoding="utf-8").replace("<Template ", line + "<Template "), encoding="utf-8")


def _refresh(project, runs):
    job = project.plan_refresh(runs)
    errors = project.apply_refresh(job, project.run_refresh(job))
    if errors:
        raise AssertionError(errors)


class BindingLayoutTests(unittest.TestCase):
    def test_independent_worksheet_edits_recalculate_the_saved_panels(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "binding.pzt"
            _write(path)
            project = Project()
            project.load(path)
            self.assertEqual([run.name for run in project.runs if run.method == SAVED_BINARY_LAYOUT], ["Binding page"])
            graphs = [run for run in project.runs if run.method == SAVED_XY]
            self.assertEqual({run.name for run in graphs}, {"Saturation chart", "Scatchard chart"})
            layout = next(run for run in project.runs if run.method == SAVED_BINARY_LAYOUT)
            _refresh(project, [*graphs, layout])
            self.assertEqual(tuple(layout.result.figure.get_size_inches()), (11.0, 8.5))
            fit, ratio = layout.result.figure.axes
            self.assertEqual([fit.lines[0].get_xdata()[0], fit.lines[0].get_ydata()[0]], [1, 15])
            self.assertEqual([ratio.lines[0].get_xdata()[0], ratio.lines[0].get_ydata()[0]], [15, 15])
            self.assertEqual(ratio.lines[1].get_xdata().tolist(), [0, 60])
            self.assertEqual(ratio.lines[1].get_ydata().tolist(), [20, 0])

            _refresh(project, project.paste("Binding", 0, 1, [["12"]]))
            ratio = layout.result.figure.axes[1]
            self.assertEqual([ratio.lines[0].get_xdata()[0], ratio.lines[0].get_ydata()[0]], [12, 12])
            self.assertEqual(ratio.lines[1].get_ydata().tolist(), [20, 0])
            _refresh(project, project.paste("Manual intercepts", 0, 1, [["24"]]))
            self.assertEqual(layout.result.figure.axes[1].lines[1].get_ydata().tolist(), [24, 0])
            scatchard = next(run for run in graphs if run.name == "Scatchard chart")
            self.assertEqual(scatchard.result.figure.axes[0].lines[1].get_ydata().tolist(), [24, 0])

            saved = path.with_suffix(".alab")
            project.save(saved)
            project = Project()
            project.load(saved)
            run = next(item for item in project.runs if item.method == SAVED_BINARY_LAYOUT)
            _refresh(project, [run])
            self.assertEqual(run.result.figure.axes[1].lines[1].get_ydata().tolist(), [24, 0])

    def test_multiline_graph_notes_remain_literal_in_the_linked_layout(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "binding.pzt"
            _write(path)
            project = Project()
            project.load(path)

            for roundtrip in (False, True):
                if roundtrip:
                    saved = path.with_suffix(".alab")
                    project.save(saved)
                    project = Project()
                    project.load(saved)
                saturation = next(run for run in project.runs if run.name == "Saturation chart")
                layout = next(run for run in project.runs if run.method == SAVED_BINARY_LAYOUT)
                _refresh(project, [saturation, layout])
                for figure in (saturation.result.figure, layout.result.figure):
                    axes = figure.axes[0]
                    note, = axes.texts
                    self.assertEqual(note.get_text(), "Estimate $ 60\nManual note")
                    self.assertFalse(note.get_parse_math())
                    self.assertIs(note.get_transform(), axes.transAxes)
                    self.assertAlmostEqual(note.get_position()[0], .05)
                    self.assertAlmostEqual(note.get_position()[1], .90)
                if not roundtrip:
                    _refresh(project, project.paste("Binding", 0, 1, [["12"]]))
                    self.assertEqual(layout.result.figure.axes[0].texts[0].get_text(),
                                     "Estimate $ 60\nManual note")

    def test_unresolved_series_does_not_attach_a_layout(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.pzt"
            _write(path, unknown_link=True)
            project = Project()
            project.load(path)
            self.assertEqual(set(project.tables), {"Binding", "Manual intercepts"})
            self.assertFalse(any(run.method == SAVED_BINARY_LAYOUT for run in project.runs))
