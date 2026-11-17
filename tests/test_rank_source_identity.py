"""PR #51 regression for original source labels, including duplicates and missing data."""
import unittest

import numpy as np
import pandas as pd

from analisi.workbench import analyse


class RankSourceIdentityTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({
            "Y": [1., 2., np.nan, 3., 4., 5.],
            "Group": ["A", "A", "A", "B", "B", "B"],
            "First": [2., 3., np.nan, 4., 5., 6.],
            "Second": [1., 1., 3., 2., 4., 5.],
        }, index=["subject-A", "subject-A", "missing", "subject-C", "subject-D", "subject-D"])

    def check_identity(self, frame):
        expected = frame.index[frame.Y.notna()].tolist()
        cases = (
            ("Mann–Whitney", {"Response": "Y", "Group": "Group"}),
            ("Wilcoxon signed-rank", {"First": "First", "Second": "Second"}),
        )
        for method, roles in cases:
            with self.subTest(method=method, index=frame.index.tolist()):
                result = analyse(method, frame, {**roles, "P value": "Exact conditional"})
                self.assertEqual(result.tables["Ranks"]["Source row"].tolist(), expected)

    def test_duplicate_text_source_labels_survive_complete_case_filter(self):
        self.check_identity(self.frame())

    def test_duplicate_numeric_source_labels_survive_complete_case_filter(self):
        frame = self.frame()
        frame.index = [101, 101, 303, 404, 909, 909]
        self.check_identity(frame)

    def test_subset_keeps_source_identity(self):
        self.check_identity(self.frame().iloc[[0, 1, 3, 4, 5]])


if __name__ == "__main__":
    unittest.main()

