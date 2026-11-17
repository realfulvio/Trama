"""Edge cases of experiment families: budgets, names, roles, chains, cancellation, persistence."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID, uuid4

import numpy as np
import pandas as pd

from analisi import family_workflow
from analisi.analysis_chain import ChainCancelled, MAX_ANALYSIS_NODES, ResultSource
from analisi.analysis_labels import MAX_LABEL, clean_label, valid_label
from analisi.data import Dataset, load_tables, load_workspace, save_project
from analisi.family_workflow import FamilyError, duplicate_family, preview_family, save_family
from analisi.info import InfoSheet
from analisi.pairwise_graph import PAIRED_COLUMNS, SECTION, section_record
from analisi.presentation import Layout


def fit(x='X', y='Y'):
    return 'Linear regression', {'X': x, 'Y': y}


def simple(title_ids=None, count=1):
    frame = pd.DataFrame({'X': [0., 1., 2., 3.], 'Y': [1., 3., 5., 7.]})
    dataset = Dataset(frame, analyses=[fit() for _ in range(count)])
    if title_ids:
        dataset.analysis_ids = dict(enumerate(title_ids))
    return dataset


class Budgets(TestCase):
    def test_info_sheet_budget_is_checked_before_anything_is_built(self):
        tables = {'A': simple()}
        sheets = [InfoSheet(f'Global {i}', ((f'k{i}', '1'),), uid=f'{i:032x}') for i in range(1, 499)]
        local = InfoSheet('A protocol', (('Scale', '1'),), table='A', uid='f' * 32)
        duplicate_family(tables, [], [*sheets, local], ('data', 'A'), name='B')
        extra = InfoSheet('One more', (('more', '1'),), uid='e' * 32)
        with self.assertRaises(FamilyError) as raised:
            duplicate_family(tables, [], [*sheets, extra, local], ('data', 'A'), name='B')
        self.assertEqual(raised.exception.code, 'budget-infos')
        self.assertEqual(list(tables), ['A'])

    def test_analysis_budget_counts_the_whole_project_without_a_chain_limit(self):
        big = Dataset(pd.DataFrame({'X': [0., 1.], 'Y': [1., 2.]}),
                      analyses=[('Histogram', {'Response': 'Y', 'Bins': 3})] * (MAX_ANALYSIS_NODES // 2))
        copy = duplicate_family({'Big': big}, [], [], ('data', 'Big'), name='Big 2')
        self.assertEqual(copy.analysis_count, MAX_ANALYSIS_NODES // 2)
        big.analyses.append(('Histogram', {'Response': 'Y', 'Bins': 3}))
        with self.assertRaises(FamilyError) as raised:
            duplicate_family({'Big': big}, [], [], ('data', 'Big'), name='Big 2')
        self.assertEqual(raised.exception.code, 'budget-analyses')

    def test_table_and_layout_budgets(self):
        tables = {f'T{i}': simple() for i in range(256)}
        with self.assertRaises(FamilyError) as raised:
            duplicate_family(tables, [], [], ('data', 'T0'), name='Extra')
        self.assertEqual(raised.exception.code, 'budget-tables')
        tables = {'A': simple()}
        layouts = [Layout(f'L{i}', 1, [('A', 0)]) for i in range(128)]
        with self.assertRaises(FamilyError) as raised:
            duplicate_family(tables, layouts, [], ('data', 'A'), name='B')
        self.assertEqual(raised.exception.code, 'budget-layouts')
        self.assertEqual(len(layouts), 128)


class Names(TestCase):
    def setUp(self):
        self.tables = {'A': simple()}

    def test_refused_names_name_the_field(self):
        for name in ('', '   ', 'a\x00b', 'two\nlines', 'tab\there', 'lone\ud800surrogate', 'x' * 161):
            with self.subTest(name=name), self.assertRaises(FamilyError) as raised:
                duplicate_family(self.tables, [], [], ('data', 'A'), name=name)
            self.assertEqual(raised.exception.field, 'name')
        for prefix in ('', '   ', 'a\x00', 'x\ny', 'p' * 81):
            with self.subTest(prefix=prefix), self.assertRaises(FamilyError):
                duplicate_family(self.tables, [], [], ('result', ('A', 0)), name=prefix)

    def test_prefix_is_literal_and_keeps_spaces(self):
        copy = duplicate_family(self.tables, [], [], ('graph', ('A', 0)), name='  Repeat  ')
        self.assertEqual(list(copy.tables), ['  Repeat  A'])
        self.assertEqual(copy.tables['  Repeat  A'].analysis_labels[0], '  Repeat  Linear regression of A')

    def test_data_name_is_trimmed_and_prefix_too_long_for_a_title_is_refused(self):
        copy = duplicate_family(self.tables, [], [], ('data', 'A'), name='  November  ')
        self.assertEqual(list(copy.tables), ['November'])
        long_table = {'T' * 150: simple()}
        with self.assertRaises(FamilyError) as raised:
            duplicate_family(long_table, [], [], ('result', ('T' * 150, 0)), name='P' * 20)
        self.assertEqual(raised.exception.code, 'name-too-long')

    def test_generated_collisions_never_overwrite(self):
        tables = {'A': simple(), 'Repeat A': simple()}
        copy = duplicate_family(tables, [], [], ('result', ('A', 0)), name='Repeat ')
        self.assertEqual(list(copy.tables), ['Repeat A (2)'])
        first = duplicate_family(self.tables, [], [], ('result', ('A', 0)), name='Repeat ')
        merged = {**self.tables, **first.tables}
        second = duplicate_family(merged, [], [], ('result', ('A', 0)), name='Repeat ')
        self.assertEqual(list(second.tables), ['Repeat A (2)'])
        self.assertEqual(list(first.tables), ['Repeat A'])

    def test_original_names_inside_other_names_are_replaced_as_whole_words_only(self):
        tables = {'A': Dataset(pd.DataFrame({'X': [0., 1.], 'Y': [1., 2.]}), analyses=[fit()],
                               analysis_labels={0: 'A fit, not Data or A1'})}
        copy = duplicate_family(tables, [Layout('A and Alpha', 1, [('A', 0)])], [], ('data', 'A'), name='Nov')
        self.assertEqual(copy.tables['Nov'].analysis_labels[0], 'Nov fit, not Data or A1')
        self.assertEqual(copy.layouts[0].name, 'Nov and Alpha')
        self.assertEqual(tables['A'].analysis_labels[0], 'A fit, not Data or A1')

    def test_preview_reports_the_same_names_the_copy_uses(self):
        layouts = [Layout('A and B', 2, [('A', 0)])]
        preview = preview_family(self.tables, layouts, [], ('data', 'A'), name='Nov')
        copy = duplicate_family(self.tables, layouts, [], ('data', 'A'), name='Nov')
        self.assertEqual(preview.table_names, copy.table_names)
        self.assertEqual([layout.name for layout in copy.layouts], list(preview.layout_names.values()))
        self.assertEqual(preview.counts['analyses'], copy.analysis_count)
        self.assertEqual(self.tables['A'].analysis_labels, {})


class Contents(TestCase):
    def test_replicate_roles_attrs_missing_values_and_exclusions_are_copied_exactly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'replicates.csv'
            pd.DataFrame({'X': [0., 1., 2., 3.], 'Control [1]': [1., 3., None, 7.],
                          'Control [2]': [1.2, 3.2, 5.2, 7.2], 'Treatment [1]': [2., 4., 6., 8.],
                          'Treatment [2]': [2.2, None, 6.2, 8.2]}).to_csv(path, index=False)
            frame = load_tables(path)['replicates']
        frame.attrs['table_format'] = 'XY'
        dataset = Dataset(frame, analyses=[('Descriptive statistics', {'Variables': ['X']})], excluded={(0, 1)})
        original = deepcopy(dataset)
        copy = duplicate_family({'R': dataset}, [], [], ('data', 'R'), name='R2').tables['R2']
        pd.testing.assert_frame_equal(copy.raw, original.raw)
        self.assertEqual(dict(copy.raw.attrs), {k: v for k, v in original.raw.attrs.items()
                                                if k not in {'excluded', 'prism_recipes', 'prism_formulas'}})
        self.assertEqual(copy.table_format, 'XY')
        self.assertEqual(copy.excluded, {(0, 1)})
        self.assertTrue(pd.isna(copy.raw.iloc[2, 1]) and pd.isna(copy.raw.iloc[1, 4]))
        copy.raw.iloc[0, 0] = 99.
        copy.excluded.add((1, 1))
        pd.testing.assert_frame_equal(dataset.raw, original.raw)
        self.assertEqual(dataset.excluded, {(0, 1)})

    def test_multiindex_columns_survive_the_copy(self):
        columns = pd.MultiIndex.from_tuples([('Control', 1), ('Control', 2), ('Treatment', 1)])
        frame = pd.DataFrame([[1., 2., 3.], [4., 5., 6.]], columns=columns)
        copy = duplicate_family({'M': Dataset(frame)}, [], [], ('data', 'M'), name='M2').tables['M2']
        self.assertTrue(copy.raw.columns.equals(columns))
        self.assertIsNot(copy.raw.columns, columns)

    def test_recipes_only_present_in_attrs_are_not_reinjected_into_a_partial_copy(self):
        frame = pd.DataFrame({'X': [0., 1.], 'Y': [1., 2.]})
        frame.attrs['prism_recipes'] = [fit(), ('Histogram', {'Response': 'Y', 'Bins': 3})]
        dataset = Dataset(frame)
        self.assertEqual(len(dataset.analyses), 2)
        copy = duplicate_family({'P': dataset}, [], [], ('graph', ('P', 1)), name='Only ').tables['Only P']
        self.assertEqual([method for method, _ in copy.analyses], ['Histogram'])
        self.assertNotIn('prism_recipes', copy.raw.attrs)

    def test_chain_across_tables_with_the_source_declared_after_its_children(self):
        ids = [str(UUID(int=number)) for number in range(1, 4)]
        child = Dataset(pd.DataFrame({'X': [0., 1.], 'Y': [1., 2.]}), analyses=[fit()], analysis_ids={0: ids[0]},
                        analysis_sources={0: ResultSource(ids[1], 'Normalized')})
        middle = Dataset(pd.DataFrame({'X': [0., 1.], 'Y': [3., 4.]}), analyses=[
            ('Histogram', {'Response': 'Y', 'Bins': 3}), ('Normalize', {'Variables': ['X'], 'Method': 'Subtract first value'})],
            analysis_ids={0: str(UUID(int=77)), 1: ids[1]}, analysis_sources={1: ResultSource(ids[2], 'Transformed')})
        root = Dataset(pd.DataFrame({'X': [0., 1.], 'Y': [5., 6.]}), analyses=[
            ('Transform', {'Variables': ['X'], 'Operation': 'Absolute value'})], analysis_ids={0: ids[2]})
        tables = {'Child': child, 'Middle': middle, 'Root': root}
        copy = duplicate_family(tables, [], [], ('graph', ('Child', 0)), name='Again ')
        self.assertEqual(list(copy.tables), ['Again Child', 'Again Middle', 'Again Root'])
        self.assertEqual([len(dataset.analyses) for dataset in copy.tables.values()], [1, 1, 1])
        new_child, new_middle, new_root = copy.tables.values()
        self.assertEqual(new_child.analysis_sources[0].analysis_id, new_middle.analysis_ids[0])
        self.assertEqual(new_middle.analysis_sources[0].analysis_id, new_root.analysis_ids[0])
        self.assertEqual(new_middle.analysis_sources[0].table, 'Transformed')
        used = {identifier for dataset in tables.values() for identifier in dataset.analysis_ids.values()}
        self.assertTrue(used.isdisjoint({identifier for dataset in copy.tables.values()
                                         for identifier in dataset.analysis_ids.values()}))

    def test_data_that_cannot_be_calculated_is_copied_without_invented_results(self):
        frame = pd.DataFrame({'X': [np.nan, np.nan], 'Y': [np.nan, np.nan]})
        dataset = Dataset(frame, analyses=[fit()])
        copy = duplicate_family({'Empty': dataset}, [], [], ('data', 'Empty'), name='Empty 2')
        new = copy.tables['Empty 2']
        self.assertEqual(new.analyses, [fit()])
        self.assertFalse(hasattr(new, 'result') or hasattr(new, 'results'))
        self.assertTrue(new.raw.isna().all().all())

    def test_a_broken_comparison_reference_stays_broken(self):
        c = Dataset(pd.DataFrame({'A': [1., 2., 4.], 'B': [2., 3., 5.]}), analyses=[
            ('Histogram', {'Response': 'A', 'Bins': 3}), (PAIRED_COLUMNS, {'First': 'A', 'Second': 'B'}),
            ('Column graph', {'Variables': ['A', 'B'], SECTION: section_record(1, PAIRED_COLUMNS)}),
            ('Column graph', {'Variables': ['A', 'B'], SECTION: section_record(9, PAIRED_COLUMNS)})])
        c.analyses[3][1][SECTION]['Source slot'] = 9
        copy = duplicate_family({'C': c}, [], [], ('data', 'C'), name='C2').tables['C2']
        self.assertEqual(copy.analyses[2][1][SECTION]['Source slot'], 1)
        self.assertGreaterEqual(copy.analyses[3][1][SECTION]['Source slot'], len(copy.analyses))
        self.assertEqual(c.analyses[3][1][SECTION]['Source slot'], 9)

    def test_repeated_copies_of_one_family_never_share_identities(self):
        tables = {'A': simple([str(uuid4())])}
        first = duplicate_family(tables, [], [], ('data', 'A'), name='One')
        second = duplicate_family(tables, [], [], ('data', 'A'), name='Two')
        ids = [dataset.analysis_ids[0] for dataset in (tables['A'], first.tables['One'], second.tables['Two'])]
        self.assertEqual(len(set(ids)), 3)

    def test_two_analyses_sharing_an_identity_are_refused(self):
        same = str(uuid4())
        tables = {'A': simple([same]), 'B': simple([same])}
        with self.assertRaises(FamilyError) as raised:
            duplicate_family(tables, [], [], ('data', 'A'), name='C')
        self.assertEqual(raised.exception.code, 'identity')

    def test_a_copy_leaves_every_argument_unchanged(self):
        tables = {'A': simple([str(uuid4())], 2), 'B': simple()}
        layouts = [Layout('Both', 1, [('A', 1), ('B', 0)])]
        infos = [InfoSheet('Details', (('k', 'v'),), table='A', uid='1' * 32), InfoSheet('Global', (('g', '1'),), uid='2' * 32)]
        before = deepcopy((tables, layouts, infos))
        for selected in (('data', 'A'), ('result', ('A', 0)), ('graph', ('A', 1)), ('layout', 0), ('info', '1' * 32)):
            duplicate_family(tables, layouts, infos, selected, name='N ' if selected[0] != 'data' else 'N')
            save_family_to_temp(tables, layouts, infos, selected)
        after = (tables, layouts, infos)
        for left, right in zip(before[0].values(), after[0].values()):
            pd.testing.assert_frame_equal(left.raw, right.raw)
            self.assertEqual((left.analyses, left.analysis_ids, left.analysis_labels),
                             (right.analyses, right.analysis_ids, right.analysis_labels))
        self.assertEqual(before[1], after[1])
        self.assertEqual(before[2], after[2])


def save_family_to_temp(tables, layouts, infos, selected):
    with tempfile.TemporaryDirectory() as folder:
        return save_family(Path(folder) / 'family.alab', tables, layouts, infos, selected)


class Cancellation(TestCase):
    def setUp(self):
        self.tables = {'A': simple([str(uuid4())] * 1), 'B': simple()}

    def test_a_cancelled_copy_raises_before_anything_is_returned(self):
        class Cancelled:
            def is_set(self):
                return True
        with self.assertRaises(ChainCancelled):
            duplicate_family(self.tables, [], [], ('data', 'A'), name='N', cancel=Cancelled())
        self.assertEqual(list(self.tables), ['A', 'B'])

    def test_cancel_in_the_middle_of_a_large_copy_discards_the_candidate(self):
        tables = {f'T{i}': simple() for i in range(12)}
        layouts = [Layout('All', 1, [(title, 0) for title in tables])]
        calls = []

        class After:
            def is_set(self):
                calls.append(1)
                return len(calls) > 6
        with self.assertRaises(ChainCancelled):
            duplicate_family(tables, layouts, [], ('layout', 0), name='Copy ', cancel=After())
        self.assertGreater(len(calls), 6)
        self.assertEqual(len(tables), 12)

    def test_a_cancelled_save_writes_nothing(self):
        class Cancelled:
            def is_set(self):
                return True
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'family.alab'
            with self.assertRaises(ChainCancelled):
                save_family(target, self.tables, [], [], ('data', 'A'), cancel=Cancelled())
            self.assertEqual(os.listdir(folder), [])


class Persistence(TestCase):
    def test_labels_round_trip_in_a_version_two_project_and_never_reach_the_options(self):
        dataset = simple(count=2)
        dataset.analysis_labels = {1: 'Second fit — ünïcode'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'labels.alab'
            save_project(path, {'A': dataset})
            stored = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(stored['version'], 2)
            self.assertEqual(stored['tables'][0]['analysis_labels'], {'1': 'Second fit — ünïcode'})
            loaded = load_workspace(path)[0]['A']
        self.assertEqual(loaded.analysis_labels, {1: 'Second fit — ünïcode'})
        self.assertNotIn('label', json.dumps(loaded.analyses))

    def test_a_project_without_labels_keeps_no_label_key(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plain.alab'
            save_project(path, {'A': simple()})
            self.assertNotIn('analysis_labels', path.read_text(encoding='utf-8'))

    def test_malformed_labels_are_refused_before_a_file_is_touched(self):
        for labels in ({0: ''}, {0: '   '}, {0: 'a\x00b'}, {0: 'two\nlines'}, {0: 'x' * (MAX_LABEL + 1)},
                       {0: 'lone\ud800'}, {5: 'out of range'}, {'0': 'text key'}, {0: 3}):
            with self.subTest(labels=labels), tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'keep.alab'
                save_project(path, {'A': simple()})
                digest = path.read_bytes()
                dataset = simple()
                dataset.analysis_labels = labels
                with self.assertRaises(ValueError):
                    save_project(path, {'A': dataset})
                self.assertEqual(path.read_bytes(), digest)
                self.assertEqual(os.listdir(folder), ['keep.alab'])

    def test_malformed_stored_labels_are_refused_on_load(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'a.alab'
            dataset = simple()
            dataset.analysis_labels = {0: 'Fit'}
            save_project(path, {'A': dataset})
            stored = json.loads(path.read_text(encoding='utf-8'))
            for bad in ({'0': ''}, {'7': 'slot out of range'}, {'x': 'not a slot'}, {'0': 'a\x00b'}, [], 'text'):
                stored['tables'][0]['analysis_labels'] = bad
                path.write_text(json.dumps(stored), encoding='utf-8')
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    load_workspace(path)

    def test_generated_labels_are_cleaned_and_bounded(self):
        self.assertTrue(valid_label(clean_label('line\nbreak\x00 and \ud800 surrogate')))
        self.assertEqual(len(clean_label('x' * 5000)), MAX_LABEL)
        self.assertFalse(valid_label(''))

    def test_a_failed_write_preserves_an_existing_file(self):
        tables = {'A': simple()}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'family.alab'
            save_family(path, tables, [], [], ('data', 'A'))
            before = path.read_bytes()
            with patch('analisi.family_workflow.save_project', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    save_family(path, tables, [], [], ('data', 'A'))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(os.listdir(folder), ['family.alab'])

    def test_the_current_project_path_is_refused_also_through_links_and_dots(self):
        tables = {'A': simple()}
        with tempfile.TemporaryDirectory() as folder:
            current = Path(folder) / 'current.alab'
            save_project(current, tables)
            before = current.read_bytes()
            link = Path(folder) / 'alias.alab'
            os.link(current, link)
            for target in (current, link, Path(folder) / '.' / 'current.alab', Path(folder) / 'sub' / '..' / 'current.alab'):
                with self.subTest(target=str(target)), self.assertRaises(FamilyError) as raised:
                    save_family(target, tables, [], [], ('data', 'A'), source_path=current)
                self.assertEqual(raised.exception.code, 'current-path')
            self.assertEqual(current.read_bytes(), before)
            with self.assertRaises(FamilyError):
                save_family(Path(folder) / 'not-a-project.txt', tables, [], [], ('data', 'A'))

    def test_the_current_project_path_is_refused_through_a_symbolic_link(self):
        tables = {'A': simple()}
        with tempfile.TemporaryDirectory() as folder:
            current = Path(folder) / 'current.alab'
            save_project(current, tables)
            before = current.read_bytes()
            link = Path(folder) / 'symbolic.alab'
            try:
                link.symlink_to(current)
            except OSError as error:
                if os.name == 'nt' and error.winerror == 1314:
                    self.skipTest('Windows test account cannot create symbolic links (WinError 1314).')
                raise
            with self.assertRaises(FamilyError) as raised:
                save_family(link, tables, [], [], ('data', 'A'), source_path=current)
            self.assertEqual(raised.exception.code, 'current-path')
            self.assertTrue(link.is_symlink())
            self.assertEqual(current.read_bytes(), before)

    def test_a_saved_family_needs_nothing_from_the_original_project(self):
        a = simple([str(uuid4())])
        a.formulas = {'Z': '=2*Y+INFO("Scale")'}
        b = simple()
        infos = [InfoSheet('Shared', (('Scale', '3'),), uid='a' * 32), InfoSheet('Unused', (('Other', '1'),), uid='b' * 32)]
        layouts = [Layout('Both', 1, [('A', 0), ('B', 0)]), Layout('Other', 1, [('B', 0)])]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'family.alab'
            save_family(path, {'A': a, 'B': b, 'C': simple()}, layouts, infos, ('data', 'A'))
            tables, saved_layouts, saved_infos = load_workspace(path, include_info=True)
        self.assertEqual(list(tables), ['A', 'B'])
        self.assertEqual([layout.name for layout in saved_layouts], ['Both'])
        self.assertEqual([sheet.title for sheet in saved_infos], ['Shared'])
        self.assertEqual(tables['A'].frame()['Z'].iloc[0], 5.)
