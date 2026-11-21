"""Synthetic legacy record tests for linked single-series dose fits."""
import unittest
from hashlib import sha256
from struct import pack
from unittest.mock import patch

import pandas as pd

from analisi import prism_binary_dose as dose
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
        recipes = self.frame.attrs["prism_recipes"]
        self.assertEqual([m for m, _ in recipes], [METHOD, "Nonlinear regression", "Nonlinear regression"])
        self.assertEqual(recipes[1][1]["Model"], "Normalized inhibition (standard slope)")
        sources = self.frame.attrs["prism_analysis_sources"]
        self.assertEqual(set(sources), {1})
        self.assertEqual(sources[1].table, NORMALIZED)
        self.assertEqual(sources[1].analysis_id, self.frame.attrs["prism_analysis_ids"][0])

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
