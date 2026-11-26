"""Independent copies of source-sensitive experiment families."""
from copy import deepcopy
import importlib.util
from unittest import TestCase
from uuid import uuid4

import pandas as pd

from analisi.analysis_chain import ResultSource
from analisi.data import Dataset
from analisi.info import InfoSheet
from analisi.linked_tables import TABLES
from analisi.presentation import Layout


class FamilyCopyTests(TestCase):
    def setUp(self):
        self.ids = [str(uuid4()) for _ in range(5)]
        a = Dataset(pd.DataFrame({'X': [0., 1., 2.], 'Y': [1., 3., 5.]}),
                    formulas={'Z': '=2*Y+1'}, excluded={(1, 1)},
                    analyses=[('Transform', {'Variables': ['X', 'Z'], 'Operation': 'Absolute value'}),
                              ('Normalize', {'Variables': ['X', 'Z'], 'Method': 'Subtract first value'}),
                              ('Linear regression', {'X': 'X', 'Y': 'Z'}),
                              ('Histogram', {'Response': 'Y', 'Bins': 3})],
                    graph_styles={2: {'title': 'A fit', 'xlabel': 'Dose',
                                      'axis': {'x': {'min': 0., 'max': 4.}}}})
        a.analysis_ids = dict(enumerate(self.ids[:4]))
        a.analysis_sources = {1: ResultSource(self.ids[0], 'Transformed'),
                              2: ResultSource(self.ids[1], 'Normalized')}
        b = Dataset(pd.DataFrame({'X': [0., 1., 2.], 'Y': [3., 4., 5.]}),
                    analyses=[('Linear regression', {'X': 'X', 'Y': 'Y'})])
        b.analysis_ids = {0: self.ids[4]}
        self.tables = {'A': a, 'B': b}
        self.layouts = [Layout('A and B', 2, [('A', 2), ('B', 0)]),
                        Layout('B alone', 1, [('B', 0)])]
        self.infos = [InfoSheet('A protocol', (('Dose', '2'),), 'Rich notes', table='A',
                                note_styles=((0, 4, 1),))]

    def engine(self):
        self.assertIsNotNone(importlib.util.find_spec('analisi.family_workflow'),
                             'Persistent family duplication is not implemented')
        from analisi import family_workflow
        return family_workflow

    def test_data_family_copies_all_analyses_but_not_other_layout_panels(self):
        module = self.engine()
        copy = module.duplicate_family(self.tables, self.layouts, self.infos, ('data', 'A'), name='November')
        self.assertEqual(set(copy.tables), {'November'})
        self.assertEqual(len(copy.tables['November'].analyses), 4)
        self.assertEqual(len(copy.layouts), 1)
        self.assertEqual(copy.layouts[0].panels, [('November', 2), ('B', 0)])
        self.assertEqual(copy.shared_panels, 1)
        self.assertEqual(copy.infos[0].table, 'November')
        self.assertEqual(copy.infos[0].note_styles, self.infos[0].note_styles)

    def test_graph_family_keeps_only_the_graph_and_its_required_analysis_chain(self):
        module = self.engine()
        copy = module.duplicate_family(self.tables, self.layouts, self.infos,
                                       ('graph', ('A', 2)), name='Repeat ')
        self.assertEqual([method for method, _ in copy.tables['Repeat A'].analyses],
                         ['Transform', 'Normalize', 'Linear regression'])
        self.assertEqual(copy.layouts[0].panels, [('Repeat A', 2), ('B', 0)])
        self.assertEqual(copy.tables['Repeat A'].analysis_labels[2], 'Repeat Linear regression of Normalized')

    def test_external_graph_copies_overlay_sources_and_scopes_project_constants(self):
        source = self.tables["A"]
        source.graph_styles[2][TABLES] = [
            {"id": "values", "mode": "linked", "source": {"kind": "sheet", "sheet": "B"}},
            {"id": "fit", "mode": "linked", "source": {"kind": "result", "analysis": self.ids[4]}},
        ]
        shared = InfoSheet("Source settings", (("Dose", "42"), ("Scale", "3")))
        target = InfoSheet("Target settings", (("Scale", "99"),))
        copied = self.engine().copy_graph_family(
            self.tables, [*self.infos, shared], ("A", 2), ({"QA A": source}, [], [target]), prefix="QA ")
        name, slot = copied.focus[1]
        self.assertNotEqual(name, "QA A")
        self.assertEqual(set(copied.tables), {name, "QA B"})
        self.assertEqual(copied.tables[name].info["dose"], "2")
        self.assertEqual(copied.tables[name].info["scale"], "3")
        self.assertEqual(copied.tables["QA B"].info["dose"], "42")
        self.assertTrue(all(sheet.table in copied.tables for sheet in copied.infos))
        table, result = copied.tables[name].graph_styles[slot][TABLES]
        self.assertEqual(table["source"]["sheet"], "QA B")
        self.assertEqual(result["source"]["analysis"], copied.tables["QA B"].analysis_ids[0])
        self.assertNotEqual(result["source"]["analysis"], self.ids[4])

    def test_copy_can_keep_xy_coordinates_and_clear_labels_and_responses(self):
        module = self.engine()
        raw = pd.DataFrame({"Row title": ["A", "B"], "Dose": [1, 2], "Signal": [3, 4]})
        dataset = Dataset(raw, table_format="xy", excluded={(0, 1), (0, 2)})
        bundle = module.duplicate_family({"Dose": dataset}, [], [], ("data", "Dose"), name="Next dose",
                                         blanks=module.FamilyBlanks(values=True, row_titles=True))
        copied = bundle.tables["Next dose"]
        self.assertEqual(list(copied.raw["Dose"]), [1, 2])
        self.assertTrue(copied.raw["Signal"].isna().all())
        self.assertTrue(copied.raw["Row title"].isna().all())
        self.assertEqual(copied.excluded, {(0, 1)})
        self.assertEqual(list(dataset.raw["Signal"]), [3, 4])

    def test_layout_family_copies_all_panel_inputs_without_unrelated_analyses(self):
        module = self.engine()
        copy = module.duplicate_family(self.tables, self.layouts, self.infos, ('layout', 0), name='Repeat ')
        self.assertEqual(set(copy.tables), {'Repeat A', 'Repeat B'})
        self.assertEqual(len(copy.tables['Repeat A'].analyses), 3)
        self.assertEqual(copy.layouts[0].panels, [('Repeat A', 2), ('Repeat B', 0)])
        self.assertEqual(copy.shared_panels, 0)
        self.assertEqual(len(copy.layouts), 1)

    def test_copies_have_new_ids_and_no_mutable_storage_shared_with_originals(self):
        module = self.engine()
        before = deepcopy(self.tables['A'])
        copy = module.duplicate_family(self.tables, self.layouts, self.infos, ('data', 'A'), name='November')
        new = copy.tables['November']
        self.assertTrue(set(new.analysis_ids.values()).isdisjoint(self.ids))
        self.assertEqual(new.analysis_sources[1].analysis_id, new.analysis_ids[0])
        self.assertEqual(new.analysis_sources[2].analysis_id, new.analysis_ids[1])
        self.assertNotEqual(copy.infos[0].uid, self.infos[0].uid)
        new.raw.iloc[0, 0] = 42.
        new.analyses[0][1]['Variables'].append('Extra')
        new.graph_styles[2]['axis']['x']['min'] = -1.
        new.excluded.clear()
        pd.testing.assert_frame_equal(self.tables['A'].raw, before.raw)
        self.assertEqual(self.tables['A'].analyses, before.analyses)
        self.assertEqual(self.tables['A'].graph_styles, before.graph_styles)
        self.assertEqual(self.tables['A'].excluded, before.excluded)

    def test_layouts_can_be_excluded_and_invalid_names_do_not_mutate_source(self):
        module = self.engine()
        copy = module.duplicate_family(self.tables, self.layouts, self.infos,
                                       ('data', 'A'), name='November', include_layouts=False)
        self.assertEqual(copy.layouts, [])
        for name in ('', '   ', 'B', 'x'*161):
            with self.subTest(name=name), self.assertRaises(ValueError):
                module.duplicate_family(self.tables, self.layouts, self.infos, ('data', 'A'), name=name)
        self.assertEqual(list(self.tables), ['A', 'B'])
        self.assertEqual(self.tables['A'].analysis_ids[0], self.ids[0])
