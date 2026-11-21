from base64 import b64encode
from hashlib import sha256
from pathlib import Path
from struct import pack, pack_into
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zlib import compress

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal

from analisi.data import Dataset, load_project, load_tables, save_project
from analisi.workbench import analyse
from test_prism_binary_editable import _group
from test_prism_binary_graphs import _project, _record


_TEST_NORMALIZATION = bytes(1352)
_TEST_FIT_PROFILE = bytes([2]) * 1352
_TEST_FORMULA_HEADERS = (bytes(218), bytes([1]) * 218)
_TEST_FIT_CONSTRAINTS = {0xC4: bytes(46), 0xC9: bytes(78)}


def normalized_template(*, selection=(31, 4, 4, 32, 4, -1), owner=4, settings=_TEST_NORMALIZATION, fit_headers=(), view=b"", curve_owner=6):
    def table(sheet, x, analysis):
        storage = 101 if analysis == -1 else 102
        fields = b"".join(
            _group(0x800F, pack("<15i", uid, 0, 1, analysis, sheet, storage, -1, 1, role, form, repeat, x, 0, 0, 0))
            for uid, role, form, repeat in ((x, 4, 10, 1), (x + 1, 8, 61, 3), (x + 2, 8, 61, 3))
        )
        links = b"".join(_record(0x0D, pack("<3I", index, x + 1 + index, 3) + bytes(36))
                         for index in range(2))
        return _group(0x8008, pack("<H", sheet), links + fields)

    def analysis(uid, title, kind, source, output, columns, summary=b"", profile=None):
        records = (_record(9, title + b"\0") + _record(0xA, (bytes(24) + summary).ljust(300, b"\0"))
                   + _record(0x3A, pack("<8H", *kind))
                   + _record(0x3B, pack("<2i", 1, source))
                   + _record(0x3C, pack("<11i", 10, output, *([-1] * 9)))
                   + _record(0x3D, pack("<H6i", 2, *columns)))
        if profile is not None:
            records += _record(0x46, profile)
        return _group(0x8039, pack("<H", uid), records)

    log = analysis(4, b"Log concentrations", (3, 255, 4, 1, 191, 0, 2, 0), 8, 9,
                   (21, -1, -1, 22, -1, -1), summary=b"Transform: X=Log(X)")
    norm = analysis(5, b"Relative response", (4, 255, 5, 1, 251, 0, 10, 65535), 9, 10,
                    selection, profile=settings)
    fits = b""
    ids = [4, 5]
    if fit_headers:
        equation = _record(0x49, b"Y=Bottom + (Top-Bottom)/(1+10^((LogEC50-X)*HillSlope))\0")
        constraints = b"".join(_record(tag, payload) for tag, payload in _TEST_FIT_CONSTRAINTS.items())
        models = b"".join(_group(0x8048, header, equation + constraints) for header in fit_headers)
        settings = _group(0x8047, pack("<4i4B6i", 1, 0, 2, 1, 34, 16, 0, 9, 1, 8, 4, 7, -1, -1), models)
        fields = (_record(9, b"Fit normalized dose\0")
                  + _record(0x3A, pack("<8H", 0, 5, 6, 1, 255, 1, 65535, 0))
                  + _record(0x3B, pack("<2i", 1, 10))
                  + _record(0x3D, pack("<H6i", 2, 41, 4, 4, 42, 4, -1))
                  + _record(0x3C, pack("<10i", 9, -1, 11, 12, *([-1] * 6)))
                  + _record(0x46, _TEST_FIT_PROFILE) + settings)
        fits = _group(0x8039, pack("<H", 6), fields)
        ids.append(6)
    curve_links = b"".join(_record(0x0D, pack("<3I", i, 51+i, 1) + bytes(12)) for i in (0, 1))
    curves = _group(0x8008, pack("<H", 12), curve_links + b"".join(
        _group(0x800F, pack("<15i", uid, 0, 5, curve_owner, 12, 102, -1, 1, 40, 10, 1, 50, 0, 0, 0))
        for uid in (51, 52)))
    return _project([3] if view else [], table(8, 20, -1), table(9, 30, owner), table(10, 40, 5),
                    log, norm, fits, curves, view, source_ids=[8], analysis_ids=ids)


def fit_graph(*, gap=100, tick=b"Blank", dataset=52, replicate_display=False, label_mode=None):
    graph = _record(0x14, pack("<3i", 2, 10, 12)) + _record(0x15, pack("<5i", 4, 3, 2, 1, 0))
    graph += _record(0x13, bytes(48))
    series = [41, 42, 51, dataset]
    graph += _record(0x16, pack("<H", 4) + b"".join(pack("<3i", uid, 4, 4) for uid in series))
    for low, high, title, count, first, second in ((0, 10, 1, 2, 20, 21), (-10, 90, 2, 1, 22, 0),
                                                  (0, 100, 3, 1, 23, 0)):
        raw = bytearray(60)
        pack_into("<2d", raw, 16, low, high)
        pack_into("<9H", raw, 42, 1000, 0, 0, title, count, 0, first, second, 0)
        graph += _record(0x17, raw)
    for key, low, high, span, blank, step in [(20, 0, 2, 200, 0, 1), (21, 2, 10, 700, gap, 2),
                                              (22, -10, 90, 1000, 0, 20)]:
        raw = bytearray(134)
        pack_into("<H3d", raw, 0, key, low, high, (high-low)/span)
        pack_into("<3H", raw, 28, 0, span+blank, blank)
        pack_into("<2d", raw, 54, step, 0)
        if label_mode is not None and key == 21:
            pack_into("<H", raw, 52, 9)
            pack_into("<2d", raw, 54, 1, 2)
            pack_into("<4H", raw, 78, 2, 2, 0, label_mode)
        named = pack("<d2x12s12x", 1, tick)
        graph += _group(0x8025, raw, _record(0x26, named) if key == 20 else b"")
    objects = b""
    for key, text in [(0, b"Trial $42"), (1, b"Dose"), (2, b"Signal")]:
        label = _group(0x802B, pack("<H", key)+bytes(16), _record(0x2C, text))
        objects += _group(0x8020, pack("<H", 2)+bytes(28), label)
    for key, uid in enumerate(series):
        raw = bytearray(144)
        pack_into("<4H", raw, 0, key, 0, uid, 1)
        if replicate_display:
            observed = key < 2
            pack_into("<4H", raw, 8, key if observed else 2, int(observed), 1 if observed else 2, 2)
            pack_into("<4H", raw, 58, 12 if observed else 138, key+1 if observed else 0, 8, int(not observed))
            color = (b"\xab\x22\x33", b"\x11\x33\xcd", b"\x44\x55\x66", b"\x22\xa0\x22")[key]
            for offset in ((84, 88) if observed else (68,)):
                raw[offset:offset+3] = color
        data = _group(0x8028, raw)
        objects += _group(0x8020, pack("<H", 9)+bytes(28), data)
    return _group(0x8012, pack("<H", 3), graph + _group(0x8018, bytes(12), objects))


def template(*, row=2, transform_heading=None, selected=(21, 22)):
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
    source = _group(0x8008, pack("<H", 8), source)
    graph = _group(0x8012, pack("<H", 6), graph)
    if transform_heading is None:
        return _project([6], source, graph)
    analysis = _group(0x8039, pack("<H", 4), (
        _record(9, b"Log concentrations\0")
        + _record(0xA, (bytes(24) + transform_heading).ljust(300, b"\0"))
        + _record(0x3A, pack("<8H", 3, 255, 4, 1, 191, 0, 2, 0))
        + _record(0x3B, pack("<2i", 1, 8))
        + _record(0x3C, pack("<11i", 10, 9, *([-1] * 9)))
        + _record(0x3D, pack("<H", len(selected)) + b"".join(pack("<3i", uid, -1, -1) for uid in selected))
    ))
    return _project([6], source, graph, analysis, source_ids=[8], analysis_ids=[4])


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

    def test_legacy_log_x_recalculates_from_the_source_after_reopening(self):
        source = self.project(compress(template(transform_heading=b"Transform: X=Log(X)")))
        dataset = Dataset(load_tables(source, restore_prism=True)["Measurements"])
        method, options = dataset.analyses[0]
        self.assertEqual(method, "Transform concentrations (X)")
        self.assertEqual(options["Prism sheet title"], "Log concentrations")
        self.assertEqual(options["Logarithm"], "Log10")
        dataset.raw.loc[0, "Time"] = 100
        dataset.raw.loc[1, "A [1]"] = 25
        native = self.path / "log.alab"
        save_project(native, {"Measurements": dataset})
        loaded = load_project(native)["Measurements"]
        method, options = loaded.analyses[0]
        result = analyse(method, loaded.frame(mask_excluded=True), options).tables["Transformed data"]
        self.assertEqual(result["Time"].iloc[0], 2)
        self.assertEqual(result["A [1]"].tolist(), [2, 25, 10])
        self.assertEqual(loaded.raw["Time"].tolist(), [100, 2, 3])

    def test_legacy_transform_requires_the_known_operation_and_all_series(self):
        for raw in (template(transform_heading=b"Transform: Y=Log(Y)"),
                    template(transform_heading=b"Transform: X=Log(X)", selected=(21,)),
                    template(transform_heading=b"Transform: X=Log(X)", selected=(21, 99))):
            source = self.project(compress(raw))
            dataset = Dataset(load_tables(source, restore_prism=True)["Measurements"])
            self.assertEqual(len(dataset.analyses), 1)  # The well-formed XY graph is still imported.
            self.assertNotEqual(dataset.analyses[0][0], "Transform concentrations (X)")

    def normalized_project(self, payload):
        path = self.project(compress(payload))
        xml = path.read_text(encoding="utf-8")
        xml = xml.replace('Replicates="2"', 'Replicates="3"')
        xml = xml.replace('</YColumn>', '<Subcolumn><d>3</d><d>7</d><d>11</d></Subcolumn></YColumn>', 1)
        xml = xml.replace('<d>22</d></Subcolumn></YColumn>',
                          '<d>22</d></Subcolumn><Subcolumn><d>13</d><d>17</d><d>21</d></Subcolumn></YColumn>')
        path.write_text(xml, encoding="utf-8")
        digest = sha256(_TEST_NORMALIZATION).hexdigest()
        with patch.multiple(
            "analisi.prism_xml_xy", _REPLICATE_NORMALIZE_PROFILE=digest,
            _NORMALIZED_FIT_PROFILE=sha256(_TEST_FIT_PROFILE).hexdigest(),
            _NORMALIZED_FIT_HEADERS=tuple(sha256(header).hexdigest() for header in _TEST_FORMULA_HEADERS),
            _NORMALIZED_CONSTRAINTS={tag: sha256(payload).hexdigest()
                                     for tag, payload in _TEST_FIT_CONSTRAINTS.items()},
        ):
            return Dataset(load_tables(path, restore_prism=True)["Measurements"])

    def test_normalization_uses_the_live_log_result_and_round_trips(self):
        dataset = self.normalized_project(normalized_template())
        self.assertEqual([name for name, _ in dataset.analyses],
                         ["Transform concentrations (X)", "Normalize to references"])
        dataset.raw.loc[2, "A [1]"] = 22
        native = self.path / "normalized.alab"
        save_project(native, {"Measurements": dataset})
        loaded = load_project(native)["Measurements"]
        log, norm = loaded.analyses
        source = loaded.analysis_sources[1]
        self.assertEqual(source.analysis_id, loaded.analysis_ids[0])
        self.assertEqual(source.table, "Transformed data")
        transformed = analyse(log[0], loaded.frame(mask_excluded=True), log[1]).tables[source.table]
        result = analyse(norm[0], transformed, norm[1]).tables
        self.assertEqual(result["Normalization references"]["One reference"].tolist(), [15.0, 21.0])
        self.assertAlmostEqual(result["Normalized"]["A [1]"].iloc[2], 100 * (22 - 3) / (15 - 3))
        self.assertAlmostEqual(result["Normalized"]["Time"].iloc[2], 0.47712125471966244)

    def test_normalization_requires_the_profile_and_the_saved_input(self):
        for payload in (normalized_template(selection=(32, 4, 4, 31, 4, -1)),
                        normalized_template(owner=99), normalized_template(settings=b"\1" * 1352)):
            with self.subTest():
                dataset = self.normalized_project(payload)
                self.assertEqual([name for name, _ in dataset.analyses], ["Transform concentrations (X)"])
                self.assertFalse(dataset.analysis_sources)

    def test_restores_both_fits_as_consumers_of_the_normalized_replicates(self):
        dataset = self.normalized_project(normalized_template(fit_headers=_TEST_FORMULA_HEADERS))
        log, norm, separate, shared = dataset.analyses
        self.assertEqual(separate[0], "Global nonlinear regression")
        self.assertEqual(shared[0], separate[0])
        self.assertEqual(shared[1]["Shared parameters"], ["Log EC50"])
        self.assertFalse(separate[1].get("Shared parameters"))
        transformed = analyse(log[0], dataset.frame(mask_excluded=True), log[1]).tables["Transformed data"]
        for slot, (method, options) in enumerate((separate, shared), start=2):
            source = dataset.analysis_sources[slot]
            self.assertEqual(source.analysis_id, dataset.analysis_ids[1])
            normalized = analyse(norm[0], transformed, norm[1]).tables[source.table]
            result = analyse(method, normalized, options).tables
            self.assertEqual(result["Per-series fit"]["N"].to_dict(), {"A": 9, "B": 9})
            self.assertEqual("Shared vs independent" in result, slot == 3)

    def test_fit_viewport_matches_the_source_and_survives_a_native_round_trip(self):
        dataset = self.normalized_project(normalized_template(fit_headers=_TEST_FORMULA_HEADERS, view=fit_graph()))
        self.assertEqual(set(dataset.graph_styles), {2, 3})
        style = dataset.graph_styles[2]
        self.assertIsNot(style["axis_breaks"], dataset.graph_styles[3]["axis_breaks"])
        self.assertEqual(style["title"], r"Trial \$42")
        self.assertNotIn("Saved replicate display", dataset.analyses[2][1])
        self.assertEqual((style["xlabel"], style["ylabel"]), ("Dose", "Signal"))
        self.assertEqual(style["axis"]["y"], {"min": -10, "max": 90, "step": 20, "start": 0})
        record = style["axis_breaks"]
        self.assertAlmostEqual(record["gap"], .1)
        first, second = record["segments"]
        self.assertEqual(first["tick_labels"], [[1, "Blank"]])
        self.assertAlmostEqual(first["share"], 100 * 200 / 900)
        self.assertEqual((first["high"], second["low"]), (2, 2))
        path = self.path / "fit-viewport.alab"
        save_project(path, {"Measurements": dataset})
        self.assertEqual(load_project(path)["Measurements"].graph_styles, dataset.graph_styles)

    def test_concentration_labels_require_the_saved_format_on_a_linear_log_dose_segment(self):
        for mode in (0, 2):
            with self.subTest(mode=mode):
                graph = fit_graph(label_mode=mode)
                dataset = self.normalized_project(normalized_template(fit_headers=_TEST_FORMULA_HEADERS, view=graph))
                path = self.path / "dose-format.alab"
                save_project(path, {"Dose": dataset})
                segment = load_project(path)["Dose"].graph_styles[2]["axis_breaks"]["segments"][1]
                self.assertEqual(segment.get("tick_format"), "power10" if mode == 2 else None)
                self.assertEqual(segment.get("minor_ticks"), 8 if mode == 2 else None)

    def test_saved_whiskers_summarize_rows_without_changing_fit_or_merging_tied_x(self):
        from analisi.repeated_input import SAVED_REPLICATE_DISPLAY
        from matplotlib.collections import LineCollection, PathCollection

        dataset = self.normalized_project(normalized_template(fit_headers=_TEST_FORMULA_HEADERS,
                                                              view=fit_graph(replicate_display=True)))
        path = self.path / "fit-means.alab"
        save_project(path, {"Measurements": dataset})
        dataset = load_project(path)["Measurements"]
        method, options = dataset.analyses[2]
        self.assertEqual(options[SAVED_REPLICATE_DISPLAY]["B"]["marker"], "^")
        log, norm = dataset.analyses[:2]
        logged = analyse(log[0], dataset.raw, log[1]).tables["Transformed data"]
        frame = analyse(norm[0], logged, norm[1]).tables["Normalized"]
        extra = frame.iloc[[1]].copy()
        extra.loc[:, ["A [1]", "A [2]", "A [3]"]] = [13.0, np.nan, np.nan]
        frame = pd.concat([frame, extra])  # repeated row label and repeated dose
        ordinary = options.copy()
        ordinary.pop(SAVED_REPLICATE_DISPLAY)
        reference = analyse(method, frame, ordinary)
        saved = analyse(method, frame, options)
        for key in reference.tables:
            assert_frame_equal(saved.tables[key], reference.tables[key], check_exact=True)
        axes = saved.figure.axes[0]
        self.assertEqual([t.get_text() for t in axes.get_legend().get_texts()], ["A", "B"])
        self.assertEqual([line.get_color() for line in axes.lines if line.get_label() in ("A", "B")],
                         ["#445566", "#22a022"])
        dots = [c.get_offsets() for c in axes.collections if isinstance(c, PathCollection)]
        bars = [c.get_segments() for c in axes.collections if isinstance(c, LineCollection)]
        for i, (label, side) in enumerate((("A", 1), ("B", -1))):
            values = frame[[f"{label} [{n}]" for n in (1, 2, 3)]]
            means, sd = values.mean(axis=1), values.std(axis=1)
            np.testing.assert_allclose(dots[i][:, 0], frame["Time"])
            np.testing.assert_allclose(dots[i][:, 1], means)
            segments = np.array(bars[i])
            keep = sd.notna() & sd.gt(0)
            np.testing.assert_allclose(segments[:, 0, 1], means[keep])
            np.testing.assert_allclose(segments[:, 1, 1], (means + side * sd)[keep])

    def test_inconsistent_graph_does_not_remove_the_fits_or_assign_a_view(self):
        for options in ({"view": fit_graph(gap=90)}, {"view": fit_graph(dataset=55)},
                        {"view": fit_graph(), "curve_owner": 42}, {"view": fit_graph(tick=b"longtruncated")}):
            with self.subTest(options=list(options)):
                dataset = self.normalized_project(normalized_template(fit_headers=_TEST_FORMULA_HEADERS, **options))
                self.assertEqual(len(dataset.analyses), 4)
                self.assertEqual(dataset.graph_styles, {})

    def test_unknown_fit_settings_leave_the_available_transform_and_normalization(self):
        dataset = self.normalized_project(normalized_template(fit_headers=_TEST_FORMULA_HEADERS[::-1]))
        self.assertEqual([name for name, _ in dataset.analyses],
                         ["Transform concentrations (X)", "Normalize to references"])
