"""Independent edge cases found while reviewing PRs 93 and 94 together."""
import json
from pathlib import Path
import unittest

import numpy as np

from analisi.field_error import FieldError
from analisi.heatmap_cell_labels import parse_cell_label_font_size
from analisi.nonlinear_calibration import _report_piece
from analisi.nonlinear_inverse import InverseError, inverse_band_components, _merge

ROOT = Path(__file__).parent / 'data' / 'nonlinear-inverse'


def fixture(name):
    found = next(c for c in json.loads((ROOT / 'cases.json').read_text()) if c['id'] == name)
    return {key: value for key, value in found.items() if key != 'id'}


class InverseReviewTests(unittest.TestCase):
    def test_changing_x_units_preserves_disconnected_components(self):
        case = fixture('two-components')
        expected = np.array(json.loads((ROOT / 'expected.json').read_text())['two-components'])
        for scale in [1e-15, 1e-12, 1e-6, 1e6]:
            with self.subTest(scale=scale):
                current = dict(case)
                current['parameters'] = np.array(case['parameters'], dtype=float)
                current['parameters'][2] *= scale
                units = np.diag([1., 1., scale, 1.])
                current['covariance'] = units @ np.array(case['covariance']) @ units
                current['low'] *= scale
                current['high'] *= scale
                actual = inverse_band_components(**current)
                self.assertEqual(len(actual), 2, actual)
                np.testing.assert_allclose(np.array(actual) / scale, expected, rtol=2e-9, atol=2e-10)

    def test_certified_disjoint_pieces_are_not_joined_across_a_small_gap(self):
        pieces = [(0., 0.25), (0.25 + 5e-13, 0.5)]
        self.assertEqual(_merge(pieces, 0., 1.), pieces)

    def test_negative_covariance_is_rejected_in_every_response_unit(self):
        case = fixture('decay-mean')
        for scale in [1e-24, 1e-12, 1., 1e12]:
            with self.subTest(scale=scale):
                with self.assertRaises(InverseError):
                    inverse_band_components(**{**case, 'covariance': -np.eye(3) * scale})

    def test_small_covariance_cannot_hide_a_large_relative_asymmetry(self):
        case = fixture('decay-mean')
        covariance = np.eye(3) * 1e-16
        covariance[0, 1] = 0.25e-16
        with self.assertRaises(InverseError):
            inverse_band_components(**{**case, 'covariance': covariance})

    def test_interval_reporting_does_not_snap_small_x_units_to_both_bounds(self):
        reported = _report_piece(2e-16, 4e-16, 0., 1e-15)
        self.assertEqual(reported, (2e-16, 4e-16, False, False))


class LabelReviewTests(unittest.TestCase):
    def test_an_oversized_numeric_font_size_names_its_field(self):
        with self.assertRaises(FieldError) as error:
            parse_cell_label_font_size(10 ** 400)
        self.assertEqual(error.exception.field, 'Cell label font size')
