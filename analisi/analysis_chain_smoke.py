"""Real desktop acceptance of persistent result inputs, propagation and recovery.

Drives mapped Tk controls and native exports; it does not simulate manual pointer use.
"""
from copy import deepcopy
import json
from pathlib import Path
import threading
from unittest.mock import patch

import numpy as np
import pandas as pd

from .analysis_chain import ResultSource
from .analysis_source_dialog import AnalysisSourceDialog
from .data import Dataset, save_project
from .graph_dialog import GraphFormatDialog
from .graph_language_smoke import drive_mapped_dialog
from .i18n import active_language, set_language, tr


def check_analysis_chains(root, app, directory, kit):
    out = Path(directory)/'analysis-chains'
    out.mkdir(exist_ok=True)
    language = active_language()

    def capture(window, name):
        kit.capture(window, name)
        path = Path(directory)/name
        if path.is_file():
            path.replace(out/name)

    def drive(kind, action):
        def ready(dialog):
            try:
                action(dialog)
            except Exception as error:
                kit.errors.append(f'{kind.__name__}: {error!r}')
                dialog.cancel()
        drive_mapped_dialog(root, kind, ready, kit.errors, timeout=20)

    def finish():
        kit.wait_for_calculation()
        assert not kit.errors, kit.errors
        assert all(run.calculation_error is None for run in app.runs)

    def slope():
        return app.runs[2].result.tables['Regression'].loc['Slope', 'Value']

    def expect(value):
        np.testing.assert_allclose(slope(), value, rtol=1e-12, atol=1e-12)

    def buttons(dialog):
        root.update_idletasks()
        for widget in (dialog.ok_button, dialog.cancel_button):
            assert widget.winfo_viewable()
            assert 0 <= widget.winfo_rootx() < widget.winfo_rootx()+widget.winfo_width() <= root.winfo_screenwidth()
            assert 0 <= widget.winfo_rooty() < widget.winfo_rooty()+widget.winfo_height() <= root.winfo_screenheight()

    def result_actions_visible():
        from tkinter import ttk
        root.update_idletasks()
        wanted = {tr('chain.analyze_result'), tr('chain.change_input')}
        found = set()
        pending = list(app.page.winfo_children())
        while pending:
            widget = pending.pop()
            pending.extend(widget.winfo_children())
            if isinstance(widget, ttk.Button) and widget.cget('text') in wanted:
                found.add(widget.cget('text'))
                assert widget.winfo_viewable()
                assert widget.winfo_width() >= widget.winfo_reqwidth()
                assert widget.winfo_rootx()+widget.winfo_width() <= root.winfo_screenwidth()
        assert found == wanted, found

    try:
        set_language('en')
        first = Dataset(pd.DataFrame({'X': [0., 1., 2., 3.], 'Y': [1., 3., 5., 7.]}),
                        formulas={'Scaled': '=2*Y+1'}, analyses=[('Transform', {
                            'Variables': ['X', 'Scaled'], 'Operation': 'Absolute value'})])
        before = out/'before.alab'
        save_project(before, {'Experiment': first})
        app.import_file(before)
        app.open_sheet(('result', 0))
        finish()

        def normalize(dialog):
            kit.pick_method(dialog, 'Normalize')
            kit.select_columns(dialog, 'Variables', ['X', 'Scaled'])
            dialog.controls['Method'][1].set('Subtract first value')
            capture(dialog, 'window-chain-normalize-en.png')
            dialog.ok()
        drive(kit.AnalysisDialog, normalize)
        app.analyze_result_table()
        finish()
        assert len(app.runs) == 2
        assert app.runs[1].source == ResultSource(app.runs[0].uid, 'Transformed')

        def regression(dialog):
            kit.pick_method(dialog, 'Linear regression')
            dialog.controls['X'][1].set('X')
            dialog.controls['Y'][1].set('Scaled')
            capture(dialog, 'window-chain-regression-en.png')
            dialog.ok()
        drive(kit.AnalysisDialog, regression)
        app.analyze_result_table()
        finish()
        assert len(app.runs) == 3
        assert app.runs[2].source == ResultSource(app.runs[1].uid, 'Normalized')
        identifiers = [run.uid for run in app.runs]
        sources = [run.source for run in app.runs]
        expect(4.)

        app.show('graph', 2)
        def formatting(dialog):
            dialog.inputs['title'].set('Live analysis chain')
            dialog.series_fields['color'].set('#176676')
        kit.drive_dialog(GraphFormatDialog, formatting)
        app.format_graph()
        style = deepcopy(app.runs[2].style)
        capture(root, 'window-chain-graph-en.png')
        app.show('result', 1)
        capture(root, 'window-chain-results-en.png')
        app.use_result_as_data()
        independent = app.tables['Normalized'].raw.copy(deep=True)

        observed = []
        compute = app.compute
        def spy(run, *args, **kwargs):
            observed.append((run.uid, threading.current_thread().name))
            return compute(run, *args, **kwargs)
        app.show('data', 'Experiment')
        with patch.object(app, 'compute', side_effect=spy):
            app.edit_cell(1, 1, '4')
            finish()
        assert [key for key, _ in observed] == identifiers
        assert all(name.startswith('Trama') for _, name in observed)
        expect(3.8)
        assert app.runs[2].style == style
        pd.testing.assert_frame_equal(app.tables['Normalized'].raw, independent)
        app.show('data', 'Experiment')
        app.current_grid.select((1, 1))
        app.toggle_exclusion()
        finish()
        expect(4.)
        app.show('data', 'Experiment')
        app.apply_worksheet_history()
        finish()
        expect(3.8)

        app.show('result', 2)
        with patch.object(kit.filedialog, 'asksaveasfilename', return_value=str(out/'regression.csv')):
            app.export()
        assert 'Slope' in (out/'regression.csv').read_text(encoding='utf-8')
        for suffix in ('svg', 'png', 'pdf'):
            app.show('graph', 2)
            path = out/f'linked-regression.{suffix}'
            with patch.object(kit.filedialog, 'asksaveasfilename', return_value=str(path)):
                app.export()
            assert path.stat().st_size > 1000

        # The graph chooser lists only analyses with figures; find the linked fit
        # from the canonical reference rather than relying on a display label.
        def choose_panel(dialog):
            dialog.name.set('Linked figure')
            index = next(i for i, run in enumerate(dialog.runs) if run.reference == app.runs[2].reference)
            dialog.list.selection_set(index)
            dialog.add_selected()
        kit.drive_dialog(kit.LayoutDialog, choose_panel)
        app.new_layout()
        assert app.layouts and app.layout_figure is not None
        capture(root, 'window-chain-layout-en.png')
        app.path = out/'roundtrip.alab'
        assert app.save()
        assert json.loads(app.path.read_text(encoding='utf-8'))['version'] == 3
        app.import_file(out/'roundtrip.alab')
        assert [run.uid for run in app.runs] == identifiers
        assert [run.source for run in app.runs] == sources
        assert all(run.result is None for run in app.runs)
        app.open_sheet(('layout', 0))
        finish()
        expect(3.8)
        assert app.layout_figure is not None

        set_language('it')
        app.show('result', 0)
        result_actions_visible()
        def reject_cycle(dialog):
            buttons(dialog)
            index = next(i for i, run in enumerate(dialog.parents)
                         if run is not None and run.uid == identifiers[1])
            dialog.parent_choice.current(index)
            dialog.sync_tables()
            dialog.ok()
            assert dialog.winfo_exists() and 'ciclo' in dialog.error.get()
            capture(dialog, 'window-chain-cycle-it.png')
            dialog.cancel()
        drive(AnalysisSourceDialog, reject_cycle)
        app.change_input_result()
        assert not kit.errors, kit.errors
        assert app.runs[0].source is None
        app.show('result', 2)
        capture(root, 'window-chain-results-it.png')
        app.source_analysis()
        assert app.selected == ('result', 1)

        # A failed upstream transformation retains previous outputs for review,
        # but those outputs must never be exported or reused as current data.
        app.runs[0].options['Operation'] = 'Square root'
        app.recalculate(0)
        finish()
        old = app.runs[2].result
        app.show('data', 'Experiment')
        app.edit_cell(0, 1, '-1')
        kit.wait_for_calculation()
        assert app.runs[2].result is old and app.runs[2].calculation_error
        app.show('graph', 2)
        capture(root, 'window-chain-stale-it.png')
        with patch.object(app, 'error') as error, patch.object(kit.filedialog, 'asksaveasfilename') as chooser:
            app.export()
        assert error.called and not chooser.called
        app.show('data', 'Experiment')
        app.apply_worksheet_history()
        finish()
        assert app.runs[2].style == style
        report = {'nodes': 3, 'worker_order': [key for key, _ in observed],
                  'threads': [name for _, name in observed], 'formula_edit_slope': 3.8,
                  'excluded_slope': 4., 'copied_result_independent': True,
                  'project_version': 3, 'styles_preserved': True, 'stale_export_blocked': True,
                  'screen': [root.winfo_screenwidth(), root.winfo_screenheight()]}
        (out/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    finally:
        set_language(language)
