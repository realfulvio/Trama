import struct
import unittest

import pandas as pd

from analisi.legacy_binary import _UnsupportedSheet
from analisi.legacy_binary_results import _read_groups, _sequence_snapshot, _x_sequence, restore_binary_results
from test_legacy_binary import dataset, document, group, record, sheet


def result_dataset(uid, owner, title, rows, *, role=8, malformed=False, overlapping=False):
    content = struct.pack("<HI", 0, len(rows))
    attributes = struct.pack("<4I", 1, 16, 4, len(rows)) + bytes(4 * len(rows))
    index, pool = [], bytearray()
    for row, value in enumerate(rows):
        content += struct.pack("<IIf", int(value is not None), 0, 0)
        if value is not None:
            offset = 0 if overlapping else len(pool)
            index.append(struct.pack("<III", row, offset, len(value) + int(malformed)))
            pool.extend(value)
    return group(0xf, struct.pack("<15i", uid, 0, 0, 3, owner, 102, -1, 2, role, 12, 1, -1, 0,
                                   len(rows), len(rows)),
                 record(9, title + b"\0"),
                 record(0x10, content),
                 record(0xf3, attributes),
                 record(0x11, struct.pack("<I", len(pool)) + pool),
                 record(0xb6, struct.pack("<I", len(index)) + b"".join(index)))


def result_document(*groups, analysis_ids=(3,)):
    raw = bytearray(document([0], *groups))
    header = 8 + struct.calcsize("<HI6HHI")
    struct.pack_into("<I", raw, header + 44, len(analysis_ids))
    struct.pack_into(f"<{len(analysis_ids)}i", raw, header + 2060, *analysis_ids)
    return bytes(raw)


def fixture(labels, values, *, malformed=False, overlapping=False, flags=7, links=(5, 8), analysis_ids=(3,)):
    parameters = struct.pack("<II", flags, 3451) + bytes(1340)
    analysis = group(0x39, struct.pack("<H", 3),
                     record(9, b"Custom analysis name\0"),
                     record(0x3b, struct.pack("<2i", 1, 0)),
                     record(0x3c, struct.pack("<11i", 10, 7, *([-1] * 9))),
                     record(0x3d, struct.pack("<H6i", 2, links[0], 4, -1, links[1], 4, -1)),
                     record(0x46, parameters))
    src = sheet(0, b"Measurements", links=[(0, 5, 1), (1, 8, 1)],
                datasets=[dataset(5, 0, 8, b"A", [(1, 1), (0, 42), (1, 3), (1, 6)]),
                          dataset(8, 0, 8, b"B", [(1, 2), (1, 1), (1, 4), (1, 9)])])
    result = group(8, struct.pack("<H", 7), record(9, b"Saved results\0"),
                   record(0x8e, struct.pack("<9i", 20, 232, 0, 0, 12, 0, -1, -1, -2)),
                   record(0xd, struct.pack("<3I", 0, 21, 1) + bytes(12)),
                   result_dataset(21, 7, b"", values, malformed=malformed, overlapping=overlapping),
                   result_dataset(20, 7, b"Parameter", labels, role=256))
    return result_document(analysis, src, result, analysis_ids=analysis_ids)


def numeric_fixture(*, step=None, analysis_id=3, fraction_source=None, source_free=False, generated_flags=None,
                    shorter=False):
    flags = 0x00100000 if step is None else 0x20001000
    if fraction_source is not None:
        flags = 0x00140400
    if generated_flags is not None:
        flags = generated_flags
    kind = 1 if step is None else 4
    name = record(9, b"Saved analysis\0")
    outputs = record(0x3c, struct.pack("<11i", 10, 7, *([-1] * 9)))
    view = record(0x3f, struct.pack("<7i", 2, 1, kind, flags, 0, -1, 0))
    source = bytes(4) if source_free or fraction_source is not None else struct.pack("<2i", 1, 0)
    analysis = group(0x39, struct.pack("<H", 3), name, record(0x3b, source), outputs, view)
    if fraction_source is not None:
        companion = group(0xE1, struct.pack("<H", 3), name, record(0x3a, struct.pack("<8H", 29, *([0] * 7))),
                          record(0x3b, struct.pack("<2i", 1, fraction_source)), outputs, view)
        analysis += companion
    ys = bytearray(dataset(21, 7, 8, b"Y", [(1, 2), (0, 99), (1, 4)], precision=1))
    struct.pack_into("<i", ys, 6 + 12, analysis_id)
    struct.pack_into("<i", ys, 6 + 20, 102)
    if step is None:
        xs = bytearray(dataset(20, 7, 4, b"X", [(1, 1), (1, 2), (1, 3)], precision=1))
        struct.pack_into("<i", xs, 6 + 12, analysis_id)
        struct.pack_into("<i", xs, 6 + 20, 102)
    else:
        struct.pack_into("<i", ys, 6 + 32, 40)
        struct.pack_into("<i", ys, 6 + 44, 20)
        xs = group(0xf, struct.pack("<15i", 20, 0, 0, analysis_id, 7, 102, -1, 4, 4, 11, 1, 20, 0, 0, 0),
                   record(9, b"X\0"),
                   record(0x10, struct.pack("<HIIIdIId", 1, 2, 1, 0, 1.0, 0, 0, step)),
                   record(0x90, bytes(2)),
                   record(0xf3, struct.pack("<12I", 2, 16, 16, 2, 0, 1, 0, 0, 0, 0, 0, 0)))
    extra = ()
    if shorter:
        second = bytearray(dataset(22, 7, 40, b"Second Y", [(1, 5), (1, 6)], precision=1))
        struct.pack_into("<i", second, 6 + 12, analysis_id)
        struct.pack_into("<i", second, 6 + 20, 102)
        struct.pack_into("<i", second, 6 + 44, 20)
        extra = (record(0xd, struct.pack("<3I", 1, 22, 1) + bytes(12)), bytes(second))
    result = group(8, struct.pack("<H", 7), record(9, b"Saved numbers\0"),
                   record(0x8e, struct.pack("<9i", -1, 0, 0, 0, 10, 0, -1, -1, -2)),
                   record(0xd, struct.pack("<3I", 0, 21, 1) + bytes(12)), bytes(ys), bytes(xs), *extra)
    return result_document(analysis, sheet(0, b"Measurements"), result)


class SavedXSequenceTests(unittest.TestCase):
    def test_formatted_sequence_ignores_only_a_verified_empty_row_title(self):
        metadata, datasets = _read_groups(numeric_fixture(step=.5))[1][7]
        layout = struct.pack("<9i", 30, 0, 0, 0, 10, 0, -1, -1, -2)
        fields = [30, 0, 0, 3, 7, 102, -1, 2, 256, 12, 1, 20, 0, 0, 0]
        records = [(9, b"\0"), (0x10, bytes(6)), (0xB6, struct.pack("<2I", 0, 30))]
        title = struct.pack("<15i", *fields), records

        def read(field):
            return _sequence_snapshot(7, 3, metadata, [*datasets, field], layout, 100, {}, formatted_curve=True)

        self.assertEqual(read(title).columns.tolist(), ["X", "Y"])
        self.assertIsNone(_sequence_snapshot(7, 3, metadata, [*datasets, title], layout, 100, {}))
        with self.assertRaises(_UnsupportedSheet):
            read((title[0], records + [(0x11, b"Not empty")]))
        fields[11] = 31
        with self.assertRaises(_UnsupportedSheet):
            read((struct.pack("<15i", *fields), records))

    def test_single_precision_axis_with_corroborated_title_runs(self):
        records = {
            0x10: struct.pack("<HI2If2If", 0, 2, 1, 0, -9., 0, 0, .25),
            0x90: b"\0\0",
            0xF3: struct.pack("<6I", 1, 16, 4, 2, 0, 0),
            0x64: b"format\0",
            0xD5: struct.pack("<I", 11) + b"Dose\0format",
        }
        self.assertEqual(_x_sequence(records.items(), 4), [-9., -8.75, -8.5, -8.25])
        records[0x64] = b"other\0"
        with self.assertRaisesRegex(_UnsupportedSheet, "title formatting"):
            _x_sequence(records.items(), 4)

    def test_formatted_sequence_requires_the_recognized_curve_profile(self):
        records = {
            0x10: struct.pack("<HI2Id2Id", 1, 2, 5, 0, -.5, 1, 0xb7, .125),
            0x90: b"\0\0",
            0xF3: struct.pack("<12I", 2, 16, 16, 2, 0, 5, 0xffffffff, 0x7fffffff,
                              0, 1, 0xffffffff, 0x7fffffff),
        }
        with self.assertRaises(_UnsupportedSheet):
            _x_sequence(records.items(), 3)
        self.assertEqual(_x_sequence(records.items(), 3, formatted_curve=True), [-.5, -.375, -.25])
        records[0xF3] = bytes(len(records[0xF3]))
        with self.assertRaises(_UnsupportedSheet):
            _x_sequence(records.items(), 3, formatted_curve=True)

    def test_formatted_concentration_sequence_uses_the_second_slot_status(self):
        records = {
            0x10: struct.pack("<HI2Id2Id", 1, 2, 5, 0, .125, 5, 183, .25),
            0x90: b"\0\0",
            0xF3: struct.pack("<12I", 2, 16, 16, 2, 0, 5, 0xffffffff, 0x7fffffff,
                              0, 5, 0xffffffff, 0x7fffffff),
        }
        self.assertEqual(_x_sequence(records.items(), 3, formatted_curve=True), [.125, .375, .625])
        records[0xF3] = struct.pack("<12I", 2, 16, 16, 2, 0, 5, 0xffffffff, 0x7fffffff,
                                   0, 1, 0xffffffff, 0x7fffffff)
        with self.assertRaises(_UnsupportedSheet):
            _x_sequence(records.items(), 3, formatted_curve=True)



class LegacyBinaryResultTests(unittest.TestCase):
    def restore(self, raw, *, frame=None):
        if frame is None:
            frame = pd.DataFrame({"A": [1, None, 3, 6], "B": [2, 1, 4, 9]})
        frame.attrs["table_format"] = "column"
        tables = {"Measurements": frame}
        restore_binary_results(raw, {0: frame}, tables, frame.size, {0: b"Arial"})
        return tables

    def test_shorter_saved_curve_series_keeps_the_shared_x_and_empty_cells(self):
        snapshot = self.restore(numeric_fixture(step=.5, shorter=True))["Imported result · Saved numbers"]
        self.assertEqual(list(snapshot.columns), ["X", "Y", "Second Y"])
        self.assertEqual(list(snapshot["X"]), [1., 1.5, 2.])
        self.assertTrue(pd.isna(snapshot.at[1, "Y"]))
        self.assertEqual(snapshot["Second Y"].dropna().to_list(), [5., 6.])
        self.assertTrue(pd.isna(snapshot.at[2, "Second Y"]))

    def test_preserves_saved_text_and_explicit_analysis_links(self):
        raw = fixture([b"  R\xb2\0\x04\x01\x01", None, b"P value", b"N"],
                      [b"0.9000", None, b"<0.0001", b"002"])
        snapshot = self.restore(raw)["Imported result · Saved results"]
        self.assertEqual(snapshot.attrs["table_format"], "Imported result snapshot")
        self.assertEqual(snapshot.attrs["legacy_binary_result"], {
            "analysis_id": 3, "sheet_id": 7, "source_ids": [0],
            "analysis_title": "Custom analysis name", "sheet_title": "Saved results",
        })
        self.assertEqual(snapshot.iloc[0].tolist(), ["  R²", "0.9000"])
        self.assertTrue(snapshot.iloc[1].isna().all())
        self.assertEqual(snapshot.iloc[2].tolist(), ["P value", "<0.0001"])
        self.assertEqual(snapshot.iloc[3].tolist(), ["N", "002"])

    def test_recalculates_paired_test_only_when_source_and_cache_agree(self):
        labels = [b"Column A", b"vs.", b"Column B", b"Paired t test", b"  P value",
                  b"  One- or two-tailed P value?", b"  t, df", b"  Number of pairs",
                  b"  Mean of differences", b"  95% confidence interval"]
        values = [b"A", b"vs.", b"B", None, b"0.1296", b"Two-tailed",
                  b"t=2.500 df=2", b"3", b"-1.667", b"-4.535 to 1.202"]
        raw = fixture(labels, values)
        sources = self.restore(raw)
        method, options = sources["Measurements"].attrs["legacy_recipes"][0]
        self.assertEqual(method, "Paired t-test (columns)")
        self.assertEqual((options["First"], options["Second"]), ("A", "B"))
        self.assertEqual(options["Legacy sheet title"], "Custom analysis name · Paired t-test")

        for invalid in (fixture(labels, [*values[:4], b"0.5568", *values[5:]]),
                        fixture(labels, values, links=(5, 9)),
                        fixture(labels, values, flags=9)):
            with self.subTest(invalid=invalid[-15:]):
                restored = self.restore(invalid)
                self.assertNotIn("legacy_recipes", restored["Measurements"].attrs)
                self.assertIn("Imported result · Saved results", restored)

    def test_wilcoxon_uses_saved_direction_and_ignores_repeated_display_labels(self):
        labels = [b"Column B", b"vs.", b"Column A", b"Wilcoxon matched-pairs signed rank test",
                  b"  P value", b"  P value summary", b"  Exact or approximate P value?",
                  b"  One- or two-tailed P value?", b"  Number of pairs", b"  Sum of signed ranks (W)",
                  b"  P value summary"]
        values = [b"B", b"vs.", b"A", None, b"0.2500", b"ns", b"Exact",
                  b"Two-tailed", b"3", b"6.00", b"*"]
        restored = self.restore(fixture(labels, values, flags=0x805))
        method, options = restored["Measurements"].attrs["legacy_recipes"][0]
        self.assertEqual(method, "Wilcoxon signed-rank")
        self.assertEqual((options["First"], options["Second"]), ("B", "A"))

    def test_out_of_range_text_does_not_create_partial_snapshot(self):
        tables = self.restore(fixture([b"P value"], [b"0.0001"], malformed=True))
        self.assertEqual(list(tables), ["Measurements"])
        self.assertIn("could not be read", tables["Measurements"].attrs["import_warnings"][0])


    def test_numeric_grids_check_ownership_and_keep_missing_slots(self):
        snapshot = self.restore(numeric_fixture())["Imported result · Saved numbers"]
        self.assertEqual(list(snapshot.columns), ["X", "Y"])
        self.assertEqual(snapshot["X"].tolist(), [1, 2, 3])
        self.assertEqual(snapshot["Y"].iloc[2], 4)
        self.assertTrue(pd.isna(snapshot["Y"].iloc[1]))
        self.assertEqual(list(self.restore(numeric_fixture(analysis_id=4))), ["Measurements"])

    def test_fraction_of_total_uses_companion_source_link(self):
        snapshot = self.restore(numeric_fixture(fraction_source=0))["Imported result · Saved numbers"]
        self.assertEqual(snapshot.attrs["legacy_binary_result"]["source_ids"], [0])
        self.assertEqual(snapshot["Y"].iloc[0], 2)
        self.assertEqual(list(self.restore(numeric_fixture(fraction_source=6))), ["Measurements"])

    def test_generated_x_recovers_origin_and_step(self):
        snapshot = self.restore(numeric_fixture(step=.25))["Imported result · Saved numbers"]
        self.assertEqual(snapshot["X"].tolist(), [1.0, 1.25, 1.5])
        self.assertTrue(pd.isna(snapshot["Y"].iloc[1]))
        self.assertEqual(list(self.restore(numeric_fixture(step=-.25))), ["Measurements"])


    def test_older_generated_x_view_requires_no_source_table(self):
        supported = numeric_fixture(step=.25, source_free=True, generated_flags=0x1802)
        snapshot = self.restore(supported)["Imported result · Saved numbers"]
        self.assertEqual(snapshot["X"].tolist(), [1., 1.25, 1.5])
        self.assertEqual(snapshot.attrs["legacy_binary_result"]["source_ids"], [])
        unrelated = numeric_fixture(step=.25, generated_flags=0x1802)
        self.assertEqual(list(self.restore(unrelated)), ["Measurements"])

    def test_formatted_simulation_recovers_values_with_one_recorded_x_row(self):
        sizes = (0xFFFFFFFF, 0x7FFFFFFF)
        name = record(9, b"Saved model\0")
        generated = struct.pack("<7i", 2, 1, 4, 0x20001002, 0, -1, 0)
        outputs = record(0x3c, struct.pack("<11i", 10, 7, *([-1] * 9)))
        x = group(0xf, struct.pack("<15i", 20, 0, 0, 3, 7, 102, -1, 4, 4, 11, 1, 20, 0, 1, 1),
                  record(9, b"Dose\0"), record(0x90, bytes(2)),
                  record(0x10, struct.pack("<HI2Id2Id", 1, 2, 1, 0, 1., 0, 0, .5)),
                  record(0xf3, struct.pack("<12I", 2, 16, 16, 2, 0, 1, *sizes, 0, 0, *sizes)))
        y = group(0xf, struct.pack("<15i", 21, 0, 0, 3, 7, 102, -1, 1, 40, 10, 1, 20, 0, 3, 3),
                  record(9, b"Signal\0"),
                  record(0x10, struct.pack("<HI", 1, 3) + b"".join(struct.pack("<IId", 1, 53, v) for v in (2., 4., 7.))),
                  record(0xf3, struct.pack("<4I", 2, 16, 16, 3) + struct.pack("<4I", 0, 1, *sizes) * 3))
        result = group(8, struct.pack("<H", 7), record(9, b"Saved numbers\0"),
                       record(0x8e, struct.pack("<9i", -1, 0, 4, 4, 10, 0, -1, -1, -2)),
                       record(0xd, struct.pack("<3I", 0, 21, 1) + bytes(12)), x, y)
        for inputs in (bytes(4), struct.pack("<2i", 1, 0)):
            analysis = group(0x39, struct.pack("<H", 3), name, record(0x3b, inputs),
                             outputs, record(0x3f, generated))
            tables = self.restore(result_document(analysis, sheet(0, b"Measurements"), result))
            if inputs == bytes(4):
                actual = tables["Imported result · Saved numbers"]
                self.assertEqual(actual.to_dict("list"), {"Dose": [1., 1.5, 2.], "Signal": [2., 4., 7.]})
                self.assertEqual(actual.attrs["legacy_binary_result"]["source_ids"], [])
            else:
                self.assertEqual(list(tables), ["Measurements"])

    def test_analysis_index_ignores_unlisted_or_ambiguous_groups(self):
        raw = fixture([b"P value"], [b"0.0001"], analysis_ids=())
        tables = self.restore(raw)
        self.assertEqual(list(tables), ["Measurements"])
        self.assertNotIn("import_warnings", tables["Measurements"].attrs)

        raw = fixture([b"P value"], [b"0.0001"], analysis_ids=(3, 3))
        tables = self.restore(raw)
        self.assertEqual(list(tables), ["Measurements"])
        self.assertIn("could not be read", tables["Measurements"].attrs["import_warnings"][0])


    def test_overlapping_text_spans_cannot_amplify_allocations(self):
        raw = fixture([b"P value", b"Pairs"], [b"0.0001", b"5"], overlapping=True)
        tables = self.restore(raw)
        self.assertEqual(list(tables), ["Measurements"])
        self.assertIn("could not be read", tables["Measurements"].attrs["import_warnings"][0])
