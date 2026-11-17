"""Names of analyses on the Run, and the transaction of a family copy in the real application."""
from pathlib import Path
import tempfile
import time
from unittest.mock import patch

import pandas as pd

from analisi.analysis_chain import ResultSource
from analisi.data import Dataset, save_project
from analisi.family_workflow import FamilyError, duplicate_family
from analisi.family_workflow_dialog import FamilyDialog, family_error_text
from analisi.i18n import tr
from analisi.info import InfoSheet
from analisi.presentation import Layout
from analisi.prism_restore import PRISM_TITLE
from analisi.theme_preferences import save_theme
from tests.test_graph_i18n import TkCase


class FamilyAppCase(TkCase):
    def setUp(self):
        import tramastat
        self.module = tramastat
        self.tmp = tempfile.TemporaryDirectory()
        prefs = Path(self.tmp.name)/'prefs.json'
        save_theme(prefs, 'standard')
        self.root.deiconify()
        with patch.object(tramastat, 'config_path', return_value=prefs):
            self.app = tramastat.App(self.root)
        self.errors = []
        self.app.error = lambda error: self.errors.append(str(error))
        a = Dataset(pd.DataFrame({'X': [0., 1., 2., 3.], 'Y': [1., 3., 5., 7.]}), analyses=[
            ('Linear regression', {'X': 'X', 'Y': 'Y'}), ('Histogram', {'Response': 'Y', 'Bins': 3})])
        info = InfoSheet('A details', (('Scale', '1'),), table='A', uid='a1' * 16)
        path = Path(self.tmp.name)/'project.alab'
        save_project(path, {'A': a}, layouts=[Layout('Fit', 1, [('A', 0)])], info_sheets=[info])
        self.app.import_file(path)
        self.root.update()

    def tearDown(self):
        self.wait()
        self.app._clear('')
        self.app.worker.shutdown(wait=True)
        for widget in self.root.winfo_children():
            widget.destroy()
        self.root.withdraw()
        self.tmp.cleanup()

    def wait(self):
        until = time.monotonic()+15
        def poll():
            if self.app.pending is None or time.monotonic() >= until:
                self.root.quit()
            else:
                self.root.after(10, poll)
        self.root.after(0, poll)
        self.root.mainloop()


class RunNames(FamilyAppCase):
    def test_label_wins_then_the_imported_title_then_the_legacy_name(self):
        run = self.app.runs[0]
        self.assertEqual(run.name, 'Linear regression of A')
        run.options[PRISM_TITLE] = 'Imported title'
        self.assertEqual(run.name, 'Imported title')
        run.label = 'Chosen label'
        self.assertEqual(run.name, 'Chosen label')
        run.label = None
        run.options.pop(PRISM_TITLE)
        run.source = ResultSource(run.uid, 'Normalized')
        self.assertEqual(run.name, 'Linear regression of Normalized')

    def test_label_survives_a_parameter_edit_and_is_stored_with_the_project(self):
        run = self.app.runs[0]
        run.label = 'My fit'
        self.app.sync_analysis_links(persist=True)
        self.assertEqual(self.app.tables['A'].analysis_labels, {0: 'My fit'})
        candidate = self.module.Run(run.method, run.title, {'X': 'Y', 'Y': 'X'}, slot=run.slot)
        self.app.start_analysis(candidate, self.app.tables['A'].frame(), 0)
        self.wait()
        replaced = self.app.runs[0]
        self.assertEqual(replaced.label, 'My fit')
        self.assertEqual(replaced.options, {'X': 'Y', 'Y': 'X'})
        self.assertEqual(self.app.tables['A'].analysis_labels, {0: 'My fit'})
        path = Path(self.tmp.name)/'saved.alab'
        self.app.path = path
        self.assertTrue(self.app.save())
        self.app.import_file(path)
        self.assertEqual(self.app.runs[0].name, 'My fit')
        self.app.runs[0].label = None
        self.app.sync_analysis_links(persist=True)
        self.assertEqual(self.app.tables['A'].analysis_labels, {})


class FamilyTransaction(FamilyAppCase):
    def bundle(self):
        return duplicate_family(self.app.tables, self.app.layouts, tuple(self.app.info_sheets.values()),
                                ('data', 'A'), name='November')

    def snapshot(self):
        return (list(self.app.tables), len(self.app.runs), len(self.app.layouts), dict(self.app.info_sheets),
                self.app.dirty)

    def test_a_valid_bundle_is_added_whole_and_the_project_becomes_dirty(self):
        bundle = self.bundle()
        self.assertFalse(self.app.dirty)
        self.app.apply_family(bundle)
        self.wait()
        self.assertEqual(list(self.app.tables), ['A', 'November'])
        self.assertEqual([run.title for run in self.app.runs], ['A', 'A', 'November', 'November'])
        self.assertEqual(self.app.layouts[-1].panels, [('November', 0)])
        self.assertEqual({sheet.table for sheet in self.app.info_sheets.values()}, {'A', 'November'})
        self.assertTrue(self.app.dirty)
        self.assertEqual(self.app.selected, ('data', 'November'))
        self.assertEqual(self.errors, [])

    def test_a_failure_while_applying_restores_the_project(self):
        bundle = self.bundle()
        before = self.snapshot()
        with patch.object(self.app, 'update_info_sheets', side_effect=ValueError('refused')):
            with self.assertRaises(ValueError):
                self.app.apply_family(bundle)
        self.assertEqual(self.snapshot(), before)

    def test_a_name_taken_in_the_meantime_adds_nothing(self):
        bundle = self.bundle()
        self.app.tables['November'] = Dataset(pd.DataFrame({'X': [1.]}))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.app.apply_family(bundle)
        self.assertEqual(self.snapshot(), before)

    def test_a_busy_worker_refuses_the_command_with_a_reason(self):
        self.app.pending = object()
        try:
            self.app.duplicate_family(('data', 'A'))
            self.app.save_family_as(('data', 'A'))
        finally:
            self.app.pending = None
        self.assertEqual(self.errors, [tr('family.wait')] * 2)

    def test_the_references_of_the_navigator_map_to_canonical_family_references(self):
        run = self.app.runs[0]
        self.assertEqual(self.app.family_ref(('data', 'A')), ('data', 'A'))
        self.assertEqual(self.app.family_ref(('result', 0)), ('result', run.reference))
        self.assertEqual(self.app.family_ref(('graph', 0)), ('graph', run.reference))
        self.assertEqual(self.app.family_ref(('layout', 0)), ('layout', 0))
        uid = next(iter(self.app.info_sheets))
        self.assertEqual(self.app.family_ref(('info', uid)), ('info', uid))
        self.assertEqual(self.app.family_ref(None), ('data', 'A'))  # the current sheet
        for bad in (('data', 'missing'), ('result', 99), ('layout', 3), ('info', 'nope'), ('section', 'x')):
            self.assertIsNone(self.app.family_ref(bad))

    def test_the_context_menu_acts_on_the_row_under_the_pointer_and_keeps_the_selection(self):
        self.app.show('data', 'A')
        node = next(node for node, ref in self.app.nodes.items() if ref == ('result', 1))
        with patch.object(self.app, 'duplicate_family') as duplicate:
            self.app.update_nav_menu(node)
            self.assertEqual(str(self.app.nav_menu.entrycget(5, 'state')), 'normal')
            self.app.nav_menu.invoke(5)
        duplicate.assert_called_once_with(('result', 1))
        self.assertEqual(self.app.selected, ('data', 'A'))
        self.app.update_nav_menu('')
        self.assertEqual(str(self.app.nav_menu.entrycget(5, 'state')), 'disabled')
        self.assertEqual(str(self.app.nav_menu.entrycget(6, 'state')), 'disabled')


class DialogBehaviour(FamilyAppCase):
    def run_dialog(self, describe, action, **options):
        outcome = {}

        def enter():
            dialog = next(child for child in self.root.winfo_children() if isinstance(child, FamilyDialog))
            if not (dialog.winfo_viewable() and dialog.grab_current() is dialog):
                self.root.after(20, enter)
                return
            try:
                action(dialog)
            finally:
                if dialog.winfo_exists():
                    dialog.cancel()
        self.root.after(50, enter)
        dialog = FamilyDialog(self.root, 'duplicate', 'data', describe, initial='Start', **options)
        outcome['result'] = dialog.result
        return outcome['result']

    def describe(self, text, include):
        error = FamilyError('name-taken', 'taken', field='name', name=text) if text == 'B' else None
        return error, [('heading', 'Preview'), ('counts', f'{text}|{include}')]

    def test_a_refused_name_stays_under_the_field_and_the_dialog_stays_open(self):
        seen = {}

        def action(dialog):
            dialog.name_var.set('B')
            seen['error'] = dialog.error_var.get()
            dialog.ok_button.invoke()
            seen['open'] = dialog.winfo_exists()
            dialog.name_var.set('Fixed')
            seen['cleared'] = dialog.error_var.get()
            dialog.include_var.set(False)
            dialog.ok_button.invoke()
        result = self.run_dialog(self.describe, action)
        self.assertEqual(seen, {'error': tr('family.error.name-taken', name='B'), 'open': True, 'cleared': ''})
        self.assertEqual(result, ('Fixed', False))

    def test_cancel_leaves_no_result(self):
        self.assertIsNone(self.run_dialog(self.describe, lambda dialog: dialog.cancel_button.invoke()))

    def test_every_engine_error_code_has_a_translated_text(self):
        for code, detail in (('name-empty', {'mode': 'name'}), ('name-empty', {'mode': 'prefix'}), ('name-invalid', {}),
                             ('name-long', {'limit': 160}), ('name-taken', {'name': 'X'}), ('name-too-long', {'table': 'T'}),
                             ('budget-tables', {'limit': 256}), ('budget-layouts', {'limit': 128}),
                             ('budget-infos', {'limit': 500}), ('budget-analyses', {'limit': 65536}),
                             ('selection', {}), ('global-info', {}), ('layout-panel', {}), ('identity', {}),
                             ('missing-source', {}), ('ambiguous-panel', {}), ('file-name', {}), ('current-path', {})):
            text = family_error_text(FamilyError(code, 'English fallback', **detail))
            self.assertNotEqual(text, 'English fallback', code)
            self.assertNotIn('family.error', text)


class RecoveredLayoutCopy(FamilyAppCase):
    def test_a_recovered_layout_is_copied_with_new_graph_identities(self):
        from analisi.prism_layout_edit import PRISM_PANEL_DATA
        from analisi.prism_restore import (PRISM_GRAPH_LINK, PRISM_GRAPH_STYLE, SAVED_BINARY_LAYOUT,
                                           SAVED_EDITABLE_GRAPH)
        tables = {
            'Recovered A': Dataset(pd.DataFrame({'X': [1., 2.], 'Y': [3., 4.]}), analyses=[
                (SAVED_EDITABLE_GRAPH, {PRISM_GRAPH_LINK: 'graph-a', PRISM_GRAPH_STYLE: {'fixture': 'A'}})]),
            'Recovered layouts': Dataset(pd.DataFrame({'View': ['Synthetic']}), analyses=[
                (SAVED_BINARY_LAYOUT, {PRISM_PANEL_DATA: {'1': 'graph-a'}})])}
        path = Path(self.tmp.name)/'recovered.alab'
        save_project(path, tables)
        self.app.import_file(path)
        index = next(i for i, run in enumerate(self.app.runs) if run.method == SAVED_BINARY_LAYOUT)
        reference = self.app.family_ref(('saved-layout', index))
        self.assertEqual(reference, ('saved-layout', ('Recovered layouts', 0)))
        describe = self.app.family_describer(reference, export=False)
        error, lines = describe('Repeat ', False)
        self.assertIsNone(error)
        self.assertIn(tr('family.counts', tables=2, analyses=2, layouts=0, infos=0), '\n'.join(text for _, text in lines))
        bundle = duplicate_family(self.app.tables, self.app.layouts, tuple(self.app.info_sheets.values()), reference,
                                  name='Repeat ')
        with patch.object(self.app, 'open_sheet') as opened:
            self.app.apply_family(bundle)
        copied = {run.title: run for run in self.app.runs if run.title.startswith('Repeat')}
        link = copied['Repeat Recovered A'].options[PRISM_GRAPH_LINK]
        self.assertNotEqual(link, 'graph-a')
        self.assertEqual(copied['Repeat Recovered layouts'].options[PRISM_PANEL_DATA], {'1': link})
        self.assertEqual(tables['Recovered layouts'].analyses[0][1][PRISM_PANEL_DATA], {'1': 'graph-a'})
        opened.assert_called_once()
        self.assertEqual(opened.call_args.args[0][0], 'saved-layout')
