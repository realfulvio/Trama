import unittest
from unittest.mock import patch

import pandas as pd

from analisi import parallel
from analisi.data import Dataset
from analisi.parallel_analyses import precompute
from trama_qt.project import Project, Run


class QtMulticoreRefreshTests(unittest.TestCase):
    def test_refresh_precomputes_independent_analyses_and_preserves_results(self):
        project = Project()
        project.tables["Experiment"] = Dataset(pd.DataFrame({"X": [1., 2., 3., 4.], "Y": [2., 5., 6., 9.]}))
        project.runs = [
            Run("Correlation", "Experiment", {"X": "X", "Y": "Y", "Method": "Pearson"}, slot=0),
            Run("Correlation", "Experiment", {"X": "Y", "Y": "X", "Method": "Pearson"}, slot=1),
        ]
        with patch.dict("os.environ", {parallel.ENVIRONMENT: "1"}):
            expected = project.run_refresh(project.plan_refresh(project.runs))
        self.addCleanup(parallel.shutdown)
        with patch.dict("os.environ", {parallel.ENVIRONMENT: "2"}):
            with patch("trama_qt.project.precompute_analyses", wraps=precompute) as prepare:
                job = project.plan_refresh(project.runs)
                current = project.run_refresh(job)
        self.assertEqual(prepare.call_count, 1)
        self.assertEqual(job.control.progress(), (2, 2))
        for run in project.runs:
            self.assertIsNone(current[run.uid].error)
            for table, result in expected[run.uid].result.tables.items():
                pd.testing.assert_frame_equal(current[run.uid].result.tables[table], result, check_exact=True)
