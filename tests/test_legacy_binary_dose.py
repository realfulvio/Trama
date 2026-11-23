"""Synthetic legacy record tests for linked single-series dose fits."""
import unittest
from hashlib import sha256
from struct import pack
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from analisi import legacy_binary_dose as dose
from analisi.legacy_fit_graph import FIT_GRAPH_OBSERVATIONS, FIT_GRAPH_POINTS, FIT_GRAPH_SPEC
from analisi.legacy_restore import LEGACY_GRAPH_LINK, SAVED_BINARY_GRAPH, SAVED_XY, paired_graph_index
from analisi.reference_normalization import METHOD, NORMALIZED


def record(tag, value):
    return tag, (), value


class BinaryDoseFitTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame({"Time": [1., 2.], "Signal": [4., 8.]})
        self.frame.attrs["table_format"] = "xy"
        metadata = [(0x0D, pack("<6I", 0, 50, 1, 0, 0, 0))]
        self.sheets = {3: (metadata, []), 5: (metadata, [])}
        self.owners = {5: (4, 3, 0), 8: (6, 5, 1), 11: (9, 3, 1)}
        norm = bytes(1348)
        standard = bytes([1]) * 1348
        conditional = bytes([2]) * 1348
        hdr = b"synthetic model"
        rule = b"test constraint"
        tail = pack("<I", len(hdr)) + hdr + pack("<HHI", 0, 0x49, len(rule)) + rule
        profiles = {
            sha256(standard + tail).hexdigest(): "Inhibition (standard slope)",
            sha256(conditional + tail).hexdigest(): "Normalized inhibition (standard slope)",
        }
        self.enterContext(patch.object(dose, "_PROFILES", profiles))
        self.enterContext(patch.object(dose, "_NORMALIZATIONS", {sha256(norm).hexdigest()}))
        self.inputs = [
            (6, 5, (0, 5, 6, 1, 255, 1, 65535, 0),
             self.records(conditional, pack("<10i", 9, -1, 8, 7, *([-1] * 6)), 2)),
            (9, 3, (0, 5, 9, 1, 255, 1, 65535, 0),
             self.records(standard, pack("<10i", 9, -1, 11, 10, *([-1] * 6))),),
            (4, 3, (4, 255, 4, 1, 191, 0, 0, 65535),
             self.records(norm, pack("<11i", 10, 5, *([-1] * 9)))),
        ]
        for *_, records in self.inputs[:2]:
            records.extend([(0x8047, (), hdr), (0x49, (0x47,), rule)])

    @staticmethod
    def records(settings, outputs, position=0):
        return [record(9, b"renamed\0"), record(0x3D, pack("<H3i", 1, 50, position, position)),
                record(0x46, settings), record(0x3C, outputs)]

    def restore(self):
        with patch.object(dose, "indexed_analyses", return_value=({3}, self.inputs)):
            return dose.restore_dose_recipes(b"", {3: self.frame}, self.sheets, self.owners, {4, 6, 9})

    def test_normalization_after_consumers_still_feeds_exactly_one_fit(self):
        self.assertEqual(self.restore(), {4, 6, 9})
        recipes = self.frame.attrs["legacy_recipes"]
        self.assertEqual([m for m, _ in recipes], [METHOD, "Nonlinear regression", "Nonlinear regression"])
        self.assertEqual(recipes[1][1]["Model"], "Normalized inhibition (standard slope)")
        sources = self.frame.attrs["legacy_analysis_sources"]
        self.assertEqual(set(sources), {1})
        self.assertEqual(sources[1].table, NORMALIZED)
        self.assertEqual(sources[1].analysis_id, self.frame.attrs["legacy_analysis_ids"][0])

    def test_ambiguous_owner_prevents_linking_normalized_fit(self):
        self.owners[5] = None
        self.assertEqual(self.restore(), {9})

    def test_unknown_constraint_leaves_that_fit_as_snapshot(self):
        self.inputs[0][3][-1] = (0x49, (0x47,), b"changed")
        self.assertEqual(self.restore(), {4, 9})

    def test_constraint_cannot_move_to_a_different_group(self):
        self.inputs[0][3][-1] = (0x49, (0x47, 0x48), b"test constraint")
        self.assertEqual(self.restore(), {4, 9})

    def test_raw_column_must_match_saved_selection(self):
        self.inputs[1][3][1] = record(0x3D, pack("<H3i", 1, 90, 0, 0))
        self.assertEqual(self.restore(), {4, 6})

    def test_unreadable_index_preserves_other_imports(self):
        with patch.object(dose, "indexed_analyses", side_effect=ValueError("no valid index")):
            self.assertEqual(dose.restore_dose_recipes(b"", {}, {}, {}, {7}), set())

    def test_graph_uses_the_linked_output_even_when_fit_titles_are_identical(self):
        self.restore()
        graph = [
            record(0x14, pack("<3i", 2, 3, 10)),
            record(0x15, pack("<3i", 2, 44, 45)),
            record(0x16, pack("<H6i", 2, 50, 0, 0, 91, 23, 24)),
        ]
        curves = {(91, 23, 24): (10, 3, (50, 0, 0), self.frame, 2),
                  (92, 23, 24): (7, 5, None, self.frame, 1)}
        axis = {"bounds": [0., 2.], "scale": "linear"}
        samples = pd.DataFrame({"X": [1., 1.5, 2.], "Fit": [8., 7., 6.]})
        with patch.object(dose, "_project_records", return_value=({}, "", {16: graph}, {})), \
                patch.object(dose, "_axis_config", return_value=[axis, axis]):
            dose.restore_dose_graphs(b"", [{"id": 16, "title": "Fit"}], {16: "saved:16"}, curves, {10: samples})
        recipes = self.frame.attrs["legacy_recipes"]
        method, options = recipes[-1]
        self.assertEqual(method, SAVED_XY)
        self.assertTrue(options[FIT_GRAPH_OBSERVATIONS])
        self.assertEqual(options[LEGACY_GRAPH_LINK], "saved:16")
        self.assertNotIn(FIT_GRAPH_SPEC, recipes[1][1])
        self.assertEqual(recipes[2][1]["Curve points"], 3)
        reference = self.frame.attrs["legacy_analysis_sources"][3]
        self.assertEqual((reference.analysis_id, reference.table),
                         (self.frame.attrs["legacy_analysis_ids"][2], FIT_GRAPH_POINTS))
        original = SimpleNamespace(method=SAVED_BINARY_GRAPH, options={LEGACY_GRAPH_LINK: "saved:16"})
        child = SimpleNamespace(method=method, options=options)
        self.assertEqual(paired_graph_index(original, [original, child]), 1)
        self.assertEqual(paired_graph_index(child, [original, child]), 0)
        self.assertIsNone(paired_graph_index(original, [original, child, child]))

    def test_drawing_link_rejects_another_worksheet_or_curve(self):
        for sheets, links in (((3, 7), (50, 0, 0, 91, 23, 24)),
                              ((3, 10), (51, 0, 0, 91, 23, 24)),
                              ((3, 10), (50, 0, 0, 91, 23, 25))):
            with self.subTest(sheets=sheets, links=links):
                graph = [record(0x14, pack("<3i", 2, *sheets)),
                         record(0x15, pack("<3i", 2, 44, 45)),
                         record(0x16, pack("<H6i", 2, *links))]
                curves = {(91, 23, 24): (10, 3, (50, 0, 0), self.frame, 2)}
                with self.assertRaises(ValueError):
                    dose._graph_curve(graph, curves)

    def test_early_input_requires_the_companion_of_the_same_analysis(self):
        uid = 9
        kind = (0, 0, 2, 1, 255, 1, 65535, 0)
        descriptor = pack("<8H", *kind)
        records = [item for item in self.inputs[1][3] if item[0] != 0x3D]
        records += [record(0x3A, descriptor), record(0x3B, bytes(4)), record(0x3D, bytes(2))]
        companion = [(tag, payload) for tag, nesting, payload in records
                     if not nesting and tag in (9, 0x3A, 0x3C, 0x46)]
        selection = pack("<H3i", 1, 50, 0, 0)
        companion += [(0x3B, pack("<2i", 1, 3)), (0x3D, selection)]
        source = ({3}, [(uid, 0, kind, records)])
        with patch.object(dose, "indexed_analyses", return_value=source), \
                patch.object(dose, "_BIPHASIC_PROFILES", dose._PROFILES):
            found = dose.early_biphasic_inputs(b"", {uid: (companion, [])}, {3})
            self.assertEqual(found[uid], (3, "Inhibition (standard slope)", selection))
            different = [(tag, b"other\0" if tag == 9 else payload) for tag, payload in companion]
            self.assertEqual(dose.early_biphasic_inputs(b"", {uid: (different, [])}, {3}), {})
