"""Real Tk lifecycle of chained transformations, normalization and regression."""
from pathlib import Path
import tempfile
import threading
import time
from unittest.mock import patch

import numpy as np
import pandas as pd

from analisi.analysis_chain import ResultSource
from analisi.theme_preferences import save_theme
from tests.test_graph_i18n import TkCase


class AnalysisChainAppTests(TkCase):
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
        self.app._add_tables({'Experiment': pd.DataFrame({'X': [0., 1., 2., 3.], 'Y': [1., 3., 5., 7.]})})
        self.app.tables['Experiment'].set_formula('Scaled', '=2*Y+1')
        self.first = tramastat.Run('Transform', 'Experiment', {
            'Variables': ['X', 'Scaled'], 'Operation': 'Absolute value'})
        self.app.add_result(self.first, self.app.compute(self.first, self.app.tables['Experiment'].frame()))
        self.second = tramastat.Run('Normalize', 'Experiment', {
            'Variables': ['X', 'Scaled'], 'Method': 'Subtract first value'},
            source=ResultSource(self.first.uid, 'Transformed'))
        self.app.add_result(self.second, self.app.compute(self.second, self.app.input_frame(self.second)))
        self.third = tramastat.Run('Linear regression', 'Experiment', {'X': 'X', 'Y': 'Scaled'},
                                   source=ResultSource(self.second.uid, 'Normalized'))
        self.app.add_result(self.third, self.app.compute(self.third, self.app.input_frame(self.third)))
        self.root.update()

    def tearDown(self):
        if hasattr(self, 'app'):
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
        self.root.update()
        self.assertIsNone(self.app.pending)

    def slope(self):
        return self.third.result.tables['Regression'].loc['Slope', 'Value']

    def test_formula_source_edits_propagate_in_order_once_on_the_worker(self):
        self.assertAlmostEqual(self.slope(), 4.)
        calls = []
        original = self.app.compute
        def compute(run, *args, **kwargs):
            calls.append((run.uid, threading.current_thread().name))
            return original(run, *args, **kwargs)
        self.app.show('data', 'Experiment')
        with patch.object(self.app, 'compute', side_effect=compute):
            self.app.edit_cell(1, 1, '4')
            self.wait()
        self.assertEqual([item[0] for item in calls], [self.first.uid, self.second.uid, self.third.uid])
        self.assertTrue(all(name.startswith('Trama') for _, name in calls))
        self.assertAlmostEqual(self.slope(), 3.8)
        self.assertAlmostEqual(self.third.result.tables['Regression'].loc['Intercept', 'Value'], .8)
        self.assertFalse(self.errors)

    def test_failed_source_keeps_outputs_stale_and_successful_correction_clears_them(self):
        self.first.options['Operation'] = 'Square root'
        self.app.recalculate(0)
        self.wait()
        old = self.third.result
        self.app.show('data', 'Experiment')
        self.app.edit_cell(0, 1, '-1')
        self.wait()
        self.assertIs(self.third.result, old)
        self.assertTrue(all(run.calculation_error for run in self.app.runs))
        self.app.show('result', 2)
        with patch.object(self.module.filedialog, 'asksaveasfilename') as chooser:
            self.app.export()
        chooser.assert_not_called()
        self.app.show('data', 'Experiment')
        self.app.edit_cell(0, 1, '1')
        self.wait()
        self.assertTrue(all(run.calculation_error is None for run in self.app.runs))
        self.assertIsNot(self.third.result, old)

    def test_reopen_and_start_with_child_graph_resolves_uncalculated_ancestors(self):
        from analisi.data import save_project
        path = Path(self.tmp.name)/'chain.alab'
        save_project(path, self.app.tables)
        identifiers = [run.uid for run in self.app.runs]
        self.app.import_file(path)
        self.assertEqual([run.uid for run in self.app.runs], identifiers)
        self.assertTrue(all(run.result is None for run in self.app.runs))
        self.third = self.app.runs[2]
        self.app.show('graph', 2)
        self.app.recalculate(2)
        self.wait()
        self.assertAlmostEqual(self.slope(), 4.)
        self.assertTrue(all(run.result is not None for run in self.app.runs))
        self.assertFalse(self.errors)

    def test_linked_hierarchy_graph_uses_real_dialog_and_recalculates_after_reopening(self):
        from analisi.data import save_project
        from analisi.hierarchical_style import describe_hierarchical_artists
        from analisi.hierarchical_workbench import HIERARCHY_GRAPH
        from analisi.presentation import apply_style
        from tests.test_legacy_hierarchical_recipes import write_project

        source = Path(self.tmp.name) / "tree.prismt"
        write_project(source, row_only=True)
        self.app._clear("")
        self.app.import_file(source)
        tree_index = next(index for index, run in enumerate(self.app.runs) if run.method == "Hierarchical clustering")
        self.app.open_sheet(("result", tree_index))
        self.wait()
        tree = self.app.runs[tree_index]
        self.app.result_tabs.select(list(tree.result.tables).index("Merges"))

        def add_view(dialog):
            item = next(key for key, value in dialog.method_by_item.items() if value == HIERARCHY_GRAPH)
            dialog.methods.selection_set(item)
            dialog.select_method()
            dialog.controls["Graph output"][1].set("Heat map")
            dialog.ok()

        self.drive(self.module.AnalysisDialog, add_view)
        self.app.analyze_result_table()
        self.wait()
        view_index = next(index for index, run in enumerate(self.app.runs) if run.method == HIERARCHY_GRAPH)
        view = self.app.runs[view_index]
        self.assertEqual(view.source, ResultSource(tree.uid, "Merges"))
        self.assertEqual(self.app.selected, ("graph", view_index))
        style = {"hierarchical": {"heatmap": {"cmap": "plasma", "colorbar": False}}}
        apply_style(view.result.figure, style)
        self.app.commit_graph_style(view, style)
        self.assertFalse(tree.style)
        raster = describe_hierarchical_artists(view.result.figure)["heatmap"]["image"]
        before = np.asarray(raster.get_array()).copy()
        target = Path(self.tmp.name) / "tree-views.alab"
        save_project(target, self.app.tables)
        self.app.import_file(target)
        self.assertTrue(all(run.result is None for run in self.app.runs))
        view_index = next(index for index, run in enumerate(self.app.runs) if run.method == HIERARCHY_GRAPH)
        self.app.open_sheet(("graph", view_index))
        self.wait()
        heat = describe_hierarchical_artists(self.app.runs[view_index].result.figure)["heatmap"]
        np.testing.assert_array_equal(heat["image"].get_array(), before)
        self.assertEqual(heat["image"].get_cmap().name, "plasma")
        self.assertFalse(heat["colorbar"].ax.get_visible())
        self.app.show("data", tree.title)
        self.app.edit_cell(0, 1, "25")
        self.wait()
        after = describe_hierarchical_artists(self.app.runs[view_index].result.figure)["heatmap"]["image"].get_array()
        self.assertFalse(np.allclose(before, after))
        self.assertFalse(self.errors)

    def test_parent_parameter_change_preserves_identity_and_updates_descendants(self):
        from types import SimpleNamespace
        identifiers = [run.uid for run in self.app.runs]
        options = {'Variables': ['X', 'Scaled'], 'Operation': 'Square'}
        dialog = SimpleNamespace(result=('Transform', options), processing_result=None)
        self.app.submit_edit(0, self.app.input_frame(self.first), dialog)
        self.wait()
        self.assertEqual([run.uid for run in self.app.runs], identifiers)
        self.third = self.app.runs[2]
        raw = self.app.tables['Experiment'].frame()
        expected = np.polyfit(raw.X**2, raw.Scaled**2-raw.Scaled.iloc[0]**2, 1)
        self.assertAlmostEqual(self.slope(), expected[0])
        self.assertFalse(self.errors)

    def drive(self, kind, action):
        from analisi.graph_language_smoke import drive_mapped_dialog
        def ready(dialog):
            try:
                action(dialog)
            except Exception as error:
                self.errors.append(repr(error))
                dialog.cancel()
        drive_mapped_dialog(self.root, kind, ready, self.errors)

    def test_real_result_action_creates_an_analysis_of_the_selected_output(self):
        self.app.show('result', 1)
        def run(dialog):
            item = next(key for key, value in dialog.method_by_item.items() if value == 'Linear regression')
            dialog.methods.selection_set(item)
            dialog.select_method()
            dialog.controls['X'][1].set('X')
            dialog.controls['Y'][1].set('Scaled')
            dialog.ok()
        self.drive(self.module.AnalysisDialog, run)
        self.app.analyze_result_table()
        self.wait()
        self.assertEqual(len(self.app.runs), 4)
        self.assertEqual(self.app.runs[3].source, ResultSource(self.second.uid, 'Normalized'))
        self.assertAlmostEqual(self.app.runs[3].result.tables['Regression'].loc['Slope', 'Value'], 4.)
        self.assertFalse(self.errors)

    def test_real_input_change_reviews_parameters_and_commits_both_together(self):
        from analisi.analysis_source_dialog import AnalysisSourceDialog
        self.app.show('result', 2)
        def choose(dialog):
            index = next(i for i, run in enumerate(dialog.parents) if run is not None and run.uid == self.first.uid)
            dialog.parent_choice.current(index)
            dialog.sync_tables()
            dialog.table_choice.set('Transformed')
            self.drive(self.module.AnalysisDialog, lambda analysis: analysis.ok())
            dialog.ok()
        self.drive(AnalysisSourceDialog, choose)
        self.app.change_input_result()
        self.wait()
        self.third = self.app.runs[2]
        self.assertEqual(self.third.source, ResultSource(self.first.uid, 'Transformed'))
        self.assertAlmostEqual(self.third.result.tables['Regression'].loc['Intercept', 'Value'], 3.)
        self.app.source_analysis()
        self.assertEqual(self.app.selected, ('result', 0))
        self.assertFalse(self.errors)

    def test_cycle_is_rejected_in_the_real_italian_dialog_without_changing_recipe(self):
        from analisi.analysis_source_dialog import AnalysisSourceDialog
        from analisi.i18n import active_language, set_language
        old_language = active_language()
        self.addCleanup(set_language, old_language)
        set_language('it')
        self.app.show('result', 0)
        seen = []
        def choose(dialog):
            index = next(i for i, run in enumerate(dialog.parents) if run is not None and run.uid == self.second.uid)
            dialog.parent_choice.current(index)
            dialog.sync_tables()
            dialog.ok()
            seen.append(dialog.error.get())
            self.assertTrue(dialog.winfo_exists())
            dialog.cancel()
        self.drive(AnalysisSourceDialog, choose)
        self.app.change_input_result()
        self.assertTrue(seen)
        self.assertIn('ciclo', seen[0])
        self.assertIsNone(self.first.source)
        self.assertFalse(self.errors)

    def block_first_worker(self):
        started, release = threading.Event(), threading.Event()
        original = self.app.compute
        frames = []
        def compute(run, frame, *args, **kwargs):
            if run.uid == self.first.uid:
                frames.append(frame.Y.iloc[1])
                if len(frames) == 1:
                    started.set()
                    if not release.wait(5):
                        raise AssertionError('Test did not release the worker')
            return original(run, frame, *args, **kwargs)
        return started, release, frames, patch.object(self.app, 'compute', side_effect=compute)

    def wait_started(self, started):
        until = time.monotonic()+3
        def poll():
            if started.is_set() or time.monotonic() >= until:
                self.root.quit()
            else:
                self.root.after(10, poll)
        self.root.after(0, poll)
        self.root.mainloop()
        self.assertTrue(started.is_set())

    def test_manual_recalculation_cancel_keeps_already_current_results_current(self):
        started, release, frames, blocking = self.block_first_worker()
        old = self.third.result
        with blocking:
            try:
                self.app.recalculate(0)
                self.wait_started(started)
                self.app.cancel_calculation()
            finally:
                release.set()
            self.wait()
        self.assertIs(self.third.result, old)
        self.assertTrue(all(run.calculation_error is None for run in self.app.runs))

    def test_cancelling_after_a_source_edit_retains_outputs_with_a_stale_warning(self):
        started, release, frames, blocking = self.block_first_worker()
        old = self.third.result
        self.app.show('data', 'Experiment')
        with blocking:
            try:
                self.app.edit_cell(1, 1, '4')
                self.wait_started(started)
                self.app.cancel_calculation()
            finally:
                release.set()
            self.wait()
        self.assertIs(self.third.result, old)
        self.assertTrue(all(run.calculation_error for run in self.app.runs))

    def test_a_new_revision_while_work_is_running_discards_the_old_batch(self):
        started, release, frames, blocking = self.block_first_worker()
        self.app.show('data', 'Experiment')
        with blocking:
            try:
                self.app.edit_cell(1, 1, '4')
                self.wait_started(started)
                dataset = self.app.tables['Experiment']
                dataset.raw = dataset.raw.copy()
                dataset.raw.iloc[1, 1] = 5.
                self.app.invalidate()
            finally:
                release.set()
            self.wait()
        self.assertEqual(frames, [4., 5.])
        self.assertAlmostEqual(self.slope(), 3.6)
        self.assertAlmostEqual(self.third.result.tables['Regression'].loc['Intercept', 'Value'], 1.6)
        self.assertTrue(all(run.calculation_error is None for run in self.app.runs))

    def test_pairwise_annotations_require_the_same_input_not_just_matching_column_names(self):
        from analisi.pairwise_graph import PAIRED_COLUMNS, SECTION, section_record
        options = {'First': 'X', 'Second': 'Scaled'}
        stats = self.module.Run(PAIRED_COLUMNS, 'Experiment', options, slot=3,
                                source=ResultSource(self.second.uid, 'Normalized'))
        self.app.tables['Experiment'].analyses.append((stats.method, stats.options))
        self.app.runs.append(stats)
        graph = self.module.Run('Column graph', 'Experiment', {
            'Variables': ['X', 'Scaled'], SECTION: section_record(3, stats.method)}, slot=4)
        snapshot = self.app.pairwise_snapshot(graph)
        self.assertIn('different input', snapshot['message'])
        graph.source = stats.source
        snapshot = self.app.pairwise_snapshot(graph)
        self.assertEqual(snapshot['key'], ('Experiment', 3))

    def test_another_analysis_of_linked_input_does_not_revert_to_the_original_raw_data(self):
        self.app.show('result', 2)
        def run(dialog):
            item = next(key for key, value in dialog.method_by_item.items() if value == 'Linear regression')
            dialog.methods.selection_set(item)
            dialog.select_method()
            dialog.controls['X'][1].set('X')
            dialog.controls['Y'][1].set('Scaled')
            dialog.ok()
        self.drive(self.module.AnalysisDialog, run)
        self.app.choose_analysis()
        self.wait()
        self.assertEqual(self.app.runs[3].source, self.third.source)
        self.assertAlmostEqual(self.app.runs[3].result.tables['Regression'].loc['Intercept', 'Value'], 0.)

    def test_navigator_displays_the_chain_and_repeated_refresh_does_not_leave_deleted_nodes(self):
        def result_nodes(root):
            pending, found = list(self.app.nav.get_children(root)), {}
            while pending:
                node = pending.pop()
                ref = self.app.nodes.get(node)
                if ref and ref[0] == 'result':
                    found[ref[1]] = node
                pending.extend(self.app.nav.get_children(node))
            return found
        self.app.show('result', 2)
        self.app.refresh_navigator()
        nodes = result_nodes('section:Family')
        self.assertEqual(self.app.nav.parent(nodes[1]), nodes[0])
        self.assertEqual(self.app.nav.parent(nodes[2]), nodes[1])
        self.app.refresh_family()
        self.app.refresh_family()
        self.app.select_current_nav()
        self.assertTrue(all(self.app.nav.exists(node) for node in self.app.nodes))
        self.app.set_combined_navigator(True)
        nodes = result_nodes('section:Data + Results')
        self.assertEqual(self.app.nav.parent(nodes[2]), nodes[1])

    def test_missing_output_after_a_parent_change_is_blocked_and_repairable(self):
        from types import SimpleNamespace
        from analisi.analysis_source_dialog import AnalysisSourceDialog
        old = self.third.result
        dialog = SimpleNamespace(result=('Normalize', {
            'Variables': ['X', 'Scaled'], 'Method': 'Subtract first value'}), processing_result=None)
        self.app.submit_edit(0, self.app.input_frame(self.first), dialog)
        self.wait()
        self.assertTrue(self.app.runs[1].calculation_error)
        self.assertTrue(self.app.runs[2].calculation_error)
        self.assertIs(self.app.runs[2].result, old)
        self.app.show('result', 1)
        def choose(source):
            self.assertEqual(source.table_choice.get(), '')
            source.table_choice.set('Normalized')
            self.drive(self.module.AnalysisDialog, lambda analysis: analysis.ok())
            source.ok()
        self.drive(AnalysisSourceDialog, choose)
        self.app.change_input_result()
        self.wait()
        self.third = self.app.runs[2]
        self.assertAlmostEqual(self.slope(), 4.)
        self.assertTrue(all(run.calculation_error is None for run in self.app.runs))
        self.assertFalse(self.errors)

    def test_copied_result_is_independent_while_a_cross_table_branch_stays_live(self):
        self.app.show('result', 1)
        self.app.use_result_as_data()
        copied = self.app.tables['Normalized'].raw.copy(deep=True)
        branch = self.module.Run('Linear regression', 'Normalized', {'X': 'X', 'Y': 'Scaled'},
                                source=ResultSource(self.second.uid, 'Normalized'))
        self.app.add_result(branch, self.app.compute(branch, self.app.input_frame(branch)))
        self.app.show('data', 'Experiment')
        self.app.edit_cell(1, 1, '4')
        self.wait()
        pd.testing.assert_frame_equal(self.app.tables['Normalized'].raw, copied)
        self.assertAlmostEqual(branch.result.tables['Regression'].loc['Slope', 'Value'], 3.8)
        self.assertFalse(self.errors)

    def test_reopening_a_layout_calculates_missing_source_chains(self):
        from analisi.data import save_project
        from analisi.presentation import Layout
        layout = Layout('Linked figure', 1, [self.third.reference])
        path = Path(self.tmp.name)/'layout-chain.alab'
        save_project(path, self.app.tables, layouts=[layout])
        self.app.import_file(path)
        self.app.open_sheet(('layout', 0))
        self.wait()
        self.third = self.app.runs[2]
        self.assertAlmostEqual(self.slope(), 4.)
        self.assertIsNotNone(self.app.layout_figure)
        self.assertFalse(self.errors)

    def test_cancelling_parameter_review_keeps_the_confirmed_input_and_options(self):
        from copy import deepcopy
        from analisi.analysis_source_dialog import AnalysisSourceDialog
        self.app.show('result', 2)
        source, options, result = self.third.source, deepcopy(self.third.options), self.third.result
        def choose(dialog):
            index = next(i for i, run in enumerate(dialog.parents) if run is not None and run.uid == self.first.uid)
            dialog.parent_choice.current(index)
            dialog.sync_tables()
            self.drive(self.module.AnalysisDialog, lambda review: review.cancel())
            dialog.ok()
        self.drive(AnalysisSourceDialog, choose)
        self.app.change_input_result()
        self.assertEqual(self.third.source, source)
        self.assertEqual(self.third.options, options)
        self.assertIs(self.third.result, result)
        self.assertIsNone(self.app.pending)
        self.assertFalse(self.errors)
