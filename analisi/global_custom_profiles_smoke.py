"""Real-widget lifecycle and independent joint-linear checks for global profiles."""
import json
import threading
import time
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from . import i18n
from .data import Dataset, save_project
from .fit_weights import INVERSE_VARIANCE
from .global_custom_fit import GLOBAL_CUSTOM_EQUATION
from .parameter_intervals import METHOD, PROFILE, ProfileBudget


def check_global_custom_profiles(root, app, directory, kit):
    frame = pd.DataFrame({'X': np.tile(np.arange(6.), 2),
        'Y': [1.1, 2.8, 5.2, 6.9, 9.1, 10.9, 4.8, 7.1, 8.9, 11.2, 12.8, 15.2],
        'Group': ['A']*6+['B']*6, 'SD': [1., 2., 1., 2., 1., 2., .8, 1.5, 1.1, 1.8, .9, 2.1]})
    old = {'X': 'X', 'Y': 'Y', 'Group': 'Group', 'Equation': 'A+B*X', 'Parameters': [
        {'name': 'A', 'start': 1., 'fixed': False, 'shared': False},
        {'name': 'B', 'start': 2., 'fixed': False, 'shared': True}],
        'Series constraints': [], 'Weighting': 'Unweighted', 'Confidence level (%)': 95., 'Curve points': 51}
    path = directory/'global-profiles.alab'
    save_project(path, {'Joint': Dataset(frame.copy()),
                        'Legacy joint': Dataset(frame.copy(), analyses=[(GLOBAL_CUSTOM_EQUATION, old)])})
    app.import_file(path)
    app.open_sheet(('result', 0))
    kit.wait_for_calculation()
    legacy = {name: table.copy() for name, table in app.runs[0].result.tables.items()}
    app.show('data', 'Joint')
    threads = set()
    consume = ProfileBudget.consume

    def observe(budget, n):
        threads.add(threading.current_thread().name)
        return consume(budget, n)

    def configure(d):
        kit.pick_method(d, GLOBAL_CUSTOM_EQUATION)
        for name in ('X', 'Y', 'Group'):
            d.controls[name][1].set(name)
        d.controls[METHOD][1].set(PROFILE)
        d.controls['Weighting'][1].set(INVERSE_VARIANCE)
        d.controls['SD column'][1].set('SD')
        d.controls['Confidence level (%)'][1].set('100')
        with patch.object(kit.messagebox, 'showerror') as error:
            assert not d.validate()
        d.update()
        assert error.called and d.focus_get() == d.field_rows['Confidence level (%)'][1]
        d.controls['Confidence level (%)'][1].set('95')
        d.fields.select(d.field_rows[METHOD][1].master)
        d.lift()
        for _ in range(4):
            d.update()
            time.sleep(.04)
        kit.capture(d, 'window-global-profiles-options-it.png')
        assert d.winfo_rooty()+d.winfo_height() <= d.winfo_screenheight()

    language = i18n.active_language()
    try:
        i18n.set_language('it')
        with patch.object(ProfileBudget, 'consume', observe):
            kit.drive_dialog(kit.AnalysisDialog, configure)
            app.choose_analysis(only=GLOBAL_CUSTOM_EQUATION)
            kit.wait_for_calculation()
    finally:
        i18n.set_language(language)
    index = next(i for i, run in enumerate(app.runs) if run.title == 'Joint')

    def compare_joint():
        source = app.tables['Joint'].frame(mask_excluded=True).dropna(subset=['X', 'Y', 'Group', 'SD'])
        design = np.column_stack([source.X, source.Group.eq('A'), source.Group.eq('B')]).astype(float)
        scales = (source.SD.to_numpy() if app.runs[index].options['Weighting'] == INVERSE_VARIANCE
                  else np.ones(len(source)))
        matrix = design/scales[:, None]
        y = source.Y.to_numpy()/scales
        beta = np.linalg.lstsq(matrix, y, rcond=None)[0]
        residual = y-matrix@beta
        df = len(source)-3
        delta = stats.t.isf(.025, df)*np.sqrt(np.diag(np.linalg.inv(matrix.T@matrix))*(residual@residual)/df)
        result = app.runs[index].result
        np.testing.assert_allclose(result.tables['Parameters'][['CI low', 'CI high']],
                                   beta[:, None]+delta[:, None]*[-1, 1], rtol=4e-5)
        assert result.tables['Parameter CI status']['df'].eq(df).all()
        if app.runs[index].options.get('Curve band', 'None') != 'None':
            assert app.runs[index].options['Response level (%)'] == 90.

    compare_joint()
    app.show('data', 'Joint')
    app.edit_cell(1, 3, '1.8')
    app.open_sheet(('result', index))
    kit.wait_for_calculation()
    compare_joint()
    app.show('data', 'Joint')
    app.current_grid.select((2, 1))
    app.toggle_exclusion()
    app.open_sheet(('result', index))
    kit.wait_for_calculation()
    compare_joint()
    # Response intervals intentionally remain restricted to the existing unweighted
    # path; profile intervals do not change that independent inference contract.
    def add_response_band(d):
        d.controls['Weighting'][1].set('Unweighted')
        d.controls['Curve band'][1].set('Confidence')
        d.controls['Response level (%)'][1].set('90')
    kit.drive_dialog(kit.AnalysisDialog, add_response_band)
    app.edit_analysis()
    kit.wait_for_calculation()
    compare_joint()
    table = app.runs[index].result.tables['Parameters'].copy()
    app.result_tabs.select(list(app.runs[index].result.tables).index('Parameters'))
    kit.capture(root, 'window-global-profiles-results.png')
    csv = directory/'global-profiles.csv'
    with patch.object(kit.filedialog, 'asksaveasfilename', return_value=str(csv)):
        app.export()
    pd.testing.assert_frame_equal(pd.read_csv(csv, index_col=0), table, check_dtype=False)
    app.use_result_as_data()
    pd.testing.assert_frame_equal(app.tables['Parameters'].raw, table, check_dtype=False)
    assert app.save()
    app.import_file(path)
    index = next(i for i, run in enumerate(app.runs) if run.title == 'Joint')
    app.open_sheet(('graph', index))
    kit.wait_for_calculation()
    pd.testing.assert_frame_equal(app.runs[index].result.tables['Parameters'], table)
    assert app.runs[index].options[METHOD] == PROFILE
    kit.capture(root, 'window-global-profiles-graph.png')
    for suffix, signature in [('svg', b'<svg'), ('png', b'\x89PNG'), ('pdf', b'%PDF')]:
        app.show('graph', index)
        target = directory/('global-profiles.'+suffix)
        with patch.object(kit.filedialog, 'asksaveasfilename', return_value=str(target)):
            app.export()
        assert signature in target.read_bytes()[:1200]

    kept = app.runs[index].result
    entered = threading.Event()

    def hold(budget, n):
        entered.set()
        deadline = time.monotonic()+10
        while not budget.cancel.is_set() and time.monotonic() < deadline:
            time.sleep(.01)
        if not budget.cancel.is_set():
            raise TimeoutError('The smoke did not cancel the waiting profile worker.')
        return consume(budget, n)

    app.show('result', index)
    with patch.object(ProfileBudget, 'consume', hold):
        kit.drive_dialog(kit.AnalysisDialog, lambda d: None)
        app.edit_analysis()
        deadline = time.monotonic()+10
        while not entered.is_set():
            assert time.monotonic() < deadline
            root.update()
            time.sleep(.01)
        try:
            root.update_idletasks()
            assert app.calculation is not None and app.cancel_button.winfo_ismapped()
        finally:
            app.cancel_calculation()
        kit.wait_for_calculation()
    assert app.runs[index].result is kept
    legacy_index = next(i for i, run in enumerate(app.runs) if run.title == 'Legacy joint')
    app.open_sheet(('result', legacy_index))
    kit.wait_for_calculation()
    for name, expected in legacy.items():
        pd.testing.assert_frame_equal(app.runs[legacy_index].result.tables[name], expected)
    assert app.runs[legacy_index].options == old
    assert threads and threading.main_thread().name not in threads, threads
    assert not kit.errors, kit.errors
    (directory/'global-profiles-acceptance.json').write_text(json.dumps({
        'status': 'PASS', 'screen': [root.winfo_screenwidth(), root.winfo_screenheight()],
        'profile_threads': sorted(threads), 'joint_wls_oracle': True, 'global_df': True,
        'sd_edit_and_exclusion': True, 'separate_response_level': True,
        'canonical_roundtrip': True, 'cancel_preserves_previous_result': True,
        'legacy_joint_wald_unchanged': True, 'csv_png_svg_pdf': True,
    }, indent=2), encoding='utf-8')
