import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import pandas as pd

from analisi.data import Dataset, load_project, save_project
from analisi.repeated_input import curve_series_labels, decode_series_constraints, encode_series_label


class SeriesOptionsTests(unittest.TestCase):
    def test_json_recipe_keeps_numeric_and_text_labels_distinct(self):
        data = Dataset(pd.DataFrame({"x": [1, 2], "y": [3, 4]}))
        records = [{"series": encode_series_label(np.int64(1)), "parameters": {"Bottom": {"fixed": 2.}}},
                   {"series": encode_series_label("1"), "parameters": {"Bottom": {"fixed": 3.}}}]
        data.analyses.append(("Global nonlinear regression", {"Series constraints": records}))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "fit.alab"
            save_project(path, {"Input": data})
            settings = load_project(path)["Input"].analyses[0][1]
        constraints = decode_series_constraints(settings["Series constraints"])
        self.assertEqual(constraints, {1: {"Bottom": {"fixed": 2.}}, "1": {"Bottom": {"fixed": 3.}}})

    def test_duplicate_series_identity_is_rejected(self):
        entry = {"series": 2, "parameters": {"Rate": {"lower": 0}}}
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            decode_series_constraints(json.loads(json.dumps([entry, entry])))

    def test_wide_label_picker_matches_numbered_replicates(self):
        frame = pd.DataFrame({"x": [1, None], "A [1]": [2, 3], "A [2]": [1, 1], "B": [None, 4]})
        options = {"Input format": "Wide XY", "X": "x", "Y columns": ["A [1]", "A [2]", "B"]}
        self.assertEqual(curve_series_labels(frame, options), ["A"])
        options["Merge numbered replicates"] = False
        self.assertEqual(curve_series_labels(frame, options), ["A [1]", "A [2]"])

    def test_long_label_picker_keeps_first_seen_order(self):
        frame = pd.DataFrame({"x": [2, 1, 4, 3], "y": [None, 4, 7, 6], "group": ["drop", "B", "A", "B"]})
        self.assertEqual(curve_series_labels(frame, {"X": "x", "Y": "y", "Series": "group"}), ["B", "A"])

    def test_nonfinite_labels_cannot_be_saved_as_constraint_keys(self):
        with self.assertRaisesRegex(ValueError, "label"):
            encode_series_label(float("inf"))

    def test_picker_omits_labels_that_cannot_be_saved(self):
        frame = pd.DataFrame({"x": [1, 2], "y": [3, 4], "group": [1, float("inf")]})
        self.assertEqual(curve_series_labels(frame, {"X": "x", "Y": "y", "Series": "group"}), [1])
