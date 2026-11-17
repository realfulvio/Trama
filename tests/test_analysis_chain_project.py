"""Project-format contracts: explicit links, safe old-version rejection, stable identities."""
import json
from pathlib import Path
import tempfile
from unittest import TestCase

import pandas as pd

from analisi.analysis_chain import ResultSource
from analisi.data import Dataset, load_workspace, save_project
from tests.test_analysis_chain import uid


class LinkedProjectTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)/'chain.alab'

    def tables(self):
        first = Dataset(pd.DataFrame({'X': [0., 1.], 'Y': [1., 3.]}),
                        analyses=[('Transform', {}), ('Linear regression', {})])
        first.analysis_ids = {0: uid(1), 1: uid(2)}
        first.analysis_sources = {1: ResultSource(uid(1), 'Transformed')}
        return {'Esperimento α': first}

    def test_links_round_trip_with_literal_names_and_unchanged_recipes(self):
        tables = self.tables()
        save_project(self.path, tables)
        raw = json.loads(self.path.read_text())
        self.assertEqual(raw['version'], 3)
        loaded, layouts = load_workspace(self.path)
        data = loaded['Esperimento α']
        self.assertEqual(data.analysis_ids, tables['Esperimento α'].analysis_ids)
        self.assertEqual(data.analysis_sources, tables['Esperimento α'].analysis_sources)
        self.assertEqual(data.analyses, tables['Esperimento α'].analyses)
        self.assertEqual(layouts, [])

    def test_unlinked_project_stays_version_two_without_new_metadata(self):
        save_project(self.path, {'Input': Dataset(pd.DataFrame({'Y': [1., 2.]}))})
        raw = json.loads(self.path.read_text())
        self.assertEqual(raw['version'], 2)
        self.assertNotIn('analysis_ids', raw['tables'][0])
        self.assertNotIn('analysis_sources', raw['tables'][0])

    def test_missing_duplicate_or_cyclic_sources_fail_before_overwriting_a_file(self):
        for problem in ('missing', 'duplicate', 'cycle'):
            with self.subTest(problem=problem):
                tables = self.tables()
                data = tables['Esperimento α']
                if problem == 'missing':
                    data.analysis_sources[1] = ResultSource(uid(9), 'Transformed')
                elif problem == 'duplicate':
                    data.analysis_ids[1] = uid(1)
                else:
                    data.analysis_sources[0] = ResultSource(uid(2), 'Transformed')
                self.path.write_text('preserve me')
                with self.assertRaises(ValueError):
                    save_project(self.path, tables)
                self.assertEqual(self.path.read_text(), 'preserve me')

    def test_cross_table_links_resolve_by_identity_and_not_names_or_order(self):
        tables = self.tables()
        other = Dataset(pd.DataFrame({'Z': [4., 5.]}), analyses=[('Transform', {})])
        other.analysis_ids = {0: uid(3)}
        other.analysis_sources = {0: ResultSource(uid(2), 'Data')}
        tables = {'Second': other, 'Renamed root': tables['Esperimento α']}
        save_project(self.path, tables)
        loaded, _ = load_workspace(self.path)
        self.assertEqual(loaded['Second'].analysis_sources[0].analysis_id, uid(2))

    def test_links_must_not_be_silently_accepted_as_a_legacy_file(self):
        save_project(self.path, self.tables())
        raw = json.loads(self.path.read_text())
        raw['version'] = 2
        self.path.write_text(json.dumps(raw))
        with self.assertRaises(ValueError):
            load_workspace(self.path)

    def test_malformed_source_metadata_is_rejected(self):
        save_project(self.path, self.tables())
        original = self.path.read_text()
        for value in ({'500': {'analysis_id': uid(1), 'table': 'Data'}},
                      {'1': {'analysis_id': uid(1), 'table': 'Data', 'unexpected': 1}},
                      {'1': {'analysis_id': 'not-an-id', 'table': 'Data'}}):
            with self.subTest(value=value):
                raw = json.loads(original)
                raw['tables'][0]['analysis_sources'] = value
                self.path.write_text(json.dumps(raw))
                with self.assertRaises(ValueError):
                    load_workspace(self.path)

    def test_chain_length_is_not_the_legacy_per_worksheet_recipe_limit(self):
        count = 400
        data = Dataset(pd.DataFrame({'Y': [1., 2.]}), analyses=[('Transform', {}) for _ in range(count)])
        data.analysis_ids = {i: uid(i+1) for i in range(count)}
        data.analysis_sources = {i: ResultSource(uid(i), 'Transformed') for i in range(1, count)}
        save_project(self.path, {'Long chain': data})
        loaded, _ = load_workspace(self.path)
        self.assertEqual(len(loaded['Long chain'].analyses), count)
        self.assertEqual(loaded['Long chain'].analysis_sources[count-1].analysis_id, uid(count-1))
