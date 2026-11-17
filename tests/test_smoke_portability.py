"""Acceptance checks must survive harmless PDF extraction and LAPACK differences."""
import unittest
from unittest.mock import patch

import numpy as np

from tests import test_pca_graphs as pca_tests


class SmokePortabilityTests(unittest.TestCase):
    def test_pdf_title_allows_whitespace_but_not_missing_or_reordered_words(self):
        from analisi.layout_svg_smoke import extracted_title_present, TITLE
        self.assertTrue(extracted_title_present(TITLE))
        self.assertTrue(extracted_title_present('prefix\n' + TITLE.replace(' ', '\r\n') + '\nsuffix'))
        self.assertFalse(extracted_title_present(TITLE.replace('città', '')))
        self.assertFalse(extracted_title_present(' '.join(reversed(TITLE.split()))))

    def test_biplot_accepts_a_different_near_tie_anchor_from_lapack(self):
        original = np.linalg.svd
        def other_backend(values, *args, **kwargs):
            result = original(values, *args, **kwargs)
            if values.shape == (6, 2) and len(result) == 3:
                u, singular, vt = result
                # Both entries have equal magnitude analytically. One ulp decides
                # which coordinate anchors the documented canonical sign.
                vt[1, 1] = np.copysign(np.nextafter(abs(vt[1, 0]), np.inf), vt[1, 1])
            return result
        with patch('numpy.linalg.svd', side_effect=other_backend):
            pca_tests.PcaGraphTests().test_biplot_reconstructs_the_centered_matrix_with_canonical_signs()
