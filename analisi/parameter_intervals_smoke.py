"""Real-widget acceptance for independent nonlinear parameter confidence intervals."""
import json
import threading
import time
from unittest.mock import patch

import numpy as np
import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .parameter_intervals import METHOD, LEVEL, WALD, PROFILE, ProfileBudget

FIT = 'Nonlinear regression'
BASE = {'X': 'X', 'Y columns': ['Y'], 'Grouping variables': [],
        'Model': 'One-phase decay', 'Weighting': 'Unweighted'}


def check_parameter_intervals(root, app, directory, kit):
    wait = kit.wait_for_calculation
    x = np.arange(0., 6.5, .5)
    y = 2+8*np.exp(-.7*x) + np.array([.15,-.12,.2,-.14,.08,.17,-.11,.05,-.07,.12,-.15,.08,-.04])
    frame = pd.DataFrame({'X': x, 'Y': y})
    path = directory / 'parameter-intervals.alab'
    save_project(path, {'Decay': Dataset(frame.copy()),
                        'Legacy fit': Dataset(frame.copy(), analyses=[(FIT, dict(BASE))])})
    app.import_file(path)
    app.open_sheet(('result', 0)); wait()
    legacy = {name: table.copy() for name, table in app.runs[0].result.tables.items()}
    assert 'Parameter CI status: All' not in legacy

    def configure(dialog):
        kit.pick_method(dialog, FIT)
        dialog.controls['X'][1].set('X')
        kit.select_columns(dialog, 'Y columns', {'Y'})
        dialog.controls['Model'][1].set('One-phase decay')
        dialog.controls['Weighting'][1].set('Unweighted')
        dialog.controls[METHOD][1].set(PROFILE)
        dialog.controls[LEVEL][1].set('100')
        with patch.object(kit.messagebox, 'showerror') as error:
            assert not dialog.validate()
        assert error.called and dialog.winfo_exists()
        dialog.update()
        assert dialog.focus_get() == dialog.field_rows[LEVEL][1]
        assert dialog.fields.select() == str(dialog.field_rows[LEVEL][1].master)
        dialog.controls[LEVEL][1].set('90')
        dialog.controls['Band'][1].set('Confidence (mean)')
        dialog.controls['Confidence level (%)'][1].set('99')
        dialog.update()
        for field in (METHOD, LEVEL, 'Confidence level (%)'):
            widget = dialog.field_rows[field][1]
            assert widget.winfo_viewable()
            assert widget.winfo_rooty()+widget.winfo_height() <= root.winfo_screenheight()
        kit.capture(dialog, 'window-parameter-ci-options-it.png')

    threads = set()
    consume = ProfileBudget.consume
    def observed(budget, n):
        threads.add(threading.current_thread().name)
        return consume(budget, n)
    app.show('data', 'Decay')
    try:
        i18n.set_language('it')
        with patch.object(ProfileBudget, 'consume', observed):
            kit.drive_dialog(kit.AnalysisDialog, configure)
            app.choose_analysis(only=FIT); wait()
    finally:
        i18n.set_language('en')
    assert threads and threading.main_thread().name not in threads, threads
    index = next(i for i, run in enumerate(app.runs) if run.title == 'Decay')
    run = app.runs[index]
    assert run.options[METHOD] == PROFILE and run.options[LEVEL] == 90.
    assert run.options['Confidence level (%)'] == 99.
    assert run.result.tables['Parameter CI status: All']['Lower status'].eq('Profile root').all()
    parameters = run.result.tables['Parameters: All']
    assert parameters.loc['Rate', 'CI 90% low'] < parameters.loc['Rate', 'Estimate'] < parameters.loc['Rate', 'CI 90% high']
    assert abs((parameters.loc['Rate','CI 90% high']-parameters.loc['Rate','Estimate'])
               -(parameters.loc['Rate','Estimate']-parameters.loc['Rate','CI 90% low'])) > 1e-5
    app.show('result', index)
    app.result_tabs.select(list(run.result.tables).index('Parameters: All'))
    kit.capture(root, 'window-parameter-ci-results.png')
    app.show('graph', index)
    kit.capture(root, 'window-parameter-ci-graph.png')
    assert app.save()
    app.import_file(path)
    index = next(i for i, item in enumerate(app.runs) if item.title == 'Decay')
    app.open_sheet(('graph', index)); wait()
    pd.testing.assert_frame_equal(app.runs[index].result.tables['Parameters: All'], parameters)

    # Reopening a graph before its results computes the stored canonical recipe.
    assert app.runs[index].options[METHOD] == PROFILE
    app.show('data', 'Decay'); app.edit_cell(2, 1, str(y[2]+.3))
    app.open_sheet(('result', index)); wait()
    changed = app.runs[index].result.tables['Parameters: All'].copy()
    assert not np.allclose(changed.Estimate, parameters.Estimate)
    app.show('data', 'Decay'); app.current_grid.select((2, 1)); app.toggle_exclusion()
    app.open_sheet(('result', index)); wait()
    expected = app.runs[index].result.tables['Parameters: All'].copy()
    assert app.runs[index].result.tables['Fit: All'].loc['N','Value'] == len(x)-1

    app.result_tabs.select(list(app.runs[index].result.tables).index('Parameters: All'))
    target = directory/'parameter-ci.csv'
    with patch.object(kit.filedialog, 'asksaveasfilename', return_value=str(target)):
        app.export()
    pd.testing.assert_frame_equal(pd.read_csv(target,index_col=0), expected, check_dtype=False)
    app.use_result_as_data()
    pd.testing.assert_frame_equal(app.tables['Parameters: All'].raw, expected.reset_index(), check_dtype=False)
    for suffix, signature in [('svg',b'<svg'),('png',b'\x89PNG'),('pdf',b'%PDF')]:
        app.show('graph',index)
        target=directory/('parameter-ci.'+suffix)
        with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(target)):
            app.export()
        assert signature in target.read_bytes()[:1200]

    # Cancel a real in-progress profile; neither a partial result nor a new recipe is accepted.
    kept = app.runs[index].result
    entered = threading.Event()
    def hold(budget,n):
        entered.set()
        while not budget.cancel.is_set():
            time.sleep(.01)
        return consume(budget,n)
    with patch.object(ProfileBudget, 'consume', hold):
        app.show('result',index)
        kit.drive_dialog(kit.AnalysisDialog,lambda dialog:None)
        app.edit_analysis()
        deadline=time.monotonic()+10
        while not entered.is_set():
            assert time.monotonic()<deadline
            root.update(); time.sleep(.01)
        assert app.cancel_button.winfo_manager()
        app.cancel_calculation(); wait()
    assert app.runs[index].result is kept
    assert 'cancelled' in app.status.get()

    # Parameter limits and curve bands are independent; Wald remains available.
    def wald(dialog):
        dialog.controls[METHOD][1].set(WALD)
        dialog.controls[LEVEL][1].set('95')
        dialog.controls['Band'][1].set('None')
    app.show('result',index)
    kit.drive_dialog(kit.AnalysisDialog,wald)
    app.edit_analysis(); wait()
    assert 'Parameter CI status: All' not in app.runs[index].result.tables
    assert 'CI 95% low' in app.runs[index].result.tables['Parameters: All']
    old_index = next(i for i, item in enumerate(app.runs) if item.title == 'Legacy fit')
    app.open_sheet(('result',old_index)); wait()
    for name,table in legacy.items():
        pd.testing.assert_frame_equal(app.runs[old_index].result.tables[name],table)
    assert app.runs[old_index].options == BASE
    assert not kit.errors, kit.errors
    (directory/'parameter-ci-acceptance.json').write_text(json.dumps({
        'status':'PASS','profile_worker_threads':sorted(threads),'cancel_preserves_completed_result':True,
        'separate_parameter_and_band_levels':True,'canonical_recipe_roundtrip':True,
        'data_edit_and_exclusion':True,'csv_png_svg_pdf':True,'legacy_tables_unchanged':True,
        'screen':[root.winfo_screenwidth(),root.winfo_screenheight()],
    },indent=2),encoding='utf-8')
