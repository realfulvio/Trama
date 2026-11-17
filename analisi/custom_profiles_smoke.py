"""Real-widget lifecycle for opt-in custom-equation parameter profiles."""
import json
import threading
import time
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from . import i18n
from .custom_fit import CUSTOM_EQUATION
from .data import Dataset, save_project
from .fit_weights import INVERSE_VARIANCE
from .parameter_intervals import METHOD, PROFILE, ProfileBudget


def check_custom_profiles(root, app, directory, kit):
    frame = pd.DataFrame({'X': np.arange(8.), 'Y': [2.2, 3.5, 6.1, 6.9, 9.5, 10.3, 13.1, 14.],
                          'SD': [.7, 1.2, .9, 1.7, .8, 1.5, 1.1, 2.]})
    old = {'X': 'X', 'Y': 'Y', 'Equation': 'A+B*X', 'Parameters': [
        {'name': 'A', 'start': 1., 'fixed': False}, {'name': 'B', 'start': 1., 'fixed': False}],
        'Weighting': 'Unweighted', 'Confidence level (%)': 95., 'Curve points': 51}
    path = directory/'custom-profiles.alab'
    save_project(path, {'Typed': Dataset(frame.copy()),
                        'Legacy': Dataset(frame.copy(), analyses=[(CUSTOM_EQUATION, old)])})
    app.import_file(path); app.open_sheet(('result', 0)); kit.wait_for_calculation()
    legacy = {name: table.copy() for name, table in app.runs[0].result.tables.items()}
    app.show('data', 'Typed')
    threads = set(); consume = ProfileBudget.consume
    def observe(budget, n):
        threads.add(threading.current_thread().name)
        return consume(budget, n)
    def configure(d):
        kit.pick_method(d, CUSTOM_EQUATION)
        d.controls['X'][1].set('X'); d.controls['Y'][1].set('Y')
        d.controls[METHOD][1].set(PROFILE)
        d.controls['Weighting'][1].set(INVERSE_VARIANCE); d.controls['SD column'][1].set('X')
        with patch.object(kit.messagebox, 'showerror') as error:
            assert not d.validate()
        d.update(); assert error.called and d.focus_get() == d.field_rows['SD column'][1]
        d.controls['SD column'][1].set('SD')
        d.fields.select(d.field_rows[METHOD][1].master); d.lift()
        for _ in range(4):
            d.update(); time.sleep(.04)
        kit.capture(d, 'window-custom-profiles-options-it.png')
        screen_h = d.winfo_screenheight()
        assert d.winfo_rooty()+d.winfo_height() <= screen_h
    try:
        i18n.set_language('it')
        with patch.object(ProfileBudget, 'consume', observe):
            kit.drive_dialog(kit.AnalysisDialog, configure); app.choose_analysis(only=CUSTOM_EQUATION)
            kit.wait_for_calculation()
    finally:
        i18n.set_language('en')
    index = next(i for i, run in enumerate(app.runs) if run.title == 'Typed')
    def compare_sd():
        source = app.tables['Typed'].frame(mask_excluded=True).dropna(subset=['X', 'Y', 'SD'])
        design = np.column_stack([np.ones(len(source)), source.X])/source.SD.to_numpy()[:, None]
        y = source.Y.to_numpy()/source.SD
        beta = np.linalg.lstsq(design, y, rcond=None)[0]
        residual = y-design@beta
        covariance = np.linalg.inv(design.T@design)*(residual@residual)/(len(source)-2)
        delta = stats.t.isf(.025, len(source)-2)*np.sqrt(np.diag(covariance))
        actual = app.runs[index].result.tables['Parameters: All']
        np.testing.assert_allclose(actual[['CI lower', 'CI upper']],
                                   beta[:, None]+delta[:, None]*[-1, 1], rtol=4e-5)
    compare_sd()
    app.show('data', 'Typed'); app.edit_cell(1, 2, '1.8')
    app.open_sheet(('result', index)); kit.wait_for_calculation(); compare_sd()
    app.show('data', 'Typed'); app.current_grid.select((2, 1)); app.toggle_exclusion()
    app.open_sheet(('result', index)); kit.wait_for_calculation(); compare_sd()
    table = app.runs[index].result.tables['Parameters: All'].copy()
    app.result_tabs.select(list(app.runs[index].result.tables).index('Parameters: All'))
    kit.capture(root, 'window-custom-profiles-results.png')
    csv = directory/'custom-profiles.csv'
    with patch.object(kit.filedialog, 'asksaveasfilename', return_value=str(csv)): app.export()
    pd.testing.assert_frame_equal(pd.read_csv(csv, index_col=0), table, check_dtype=False)
    app.use_result_as_data()
    pd.testing.assert_frame_equal(app.tables['Parameters: All'].raw, table.reset_index(), check_dtype=False)
    assert app.save(); app.import_file(path)
    index = next(i for i, run in enumerate(app.runs) if run.title == 'Typed')
    app.open_sheet(('graph', index)); kit.wait_for_calculation()
    pd.testing.assert_frame_equal(app.runs[index].result.tables['Parameters: All'], table)
    assert app.runs[index].options[METHOD] == PROFILE
    assert app.runs[index].options['Weighting'] == INVERSE_VARIANCE
    kit.capture(root, 'window-custom-profiles-graph.png')
    for suffix, signature in [('svg', b'<svg'), ('png', b'\x89PNG'), ('pdf', b'%PDF')]:
        app.show('graph', index); target = directory/('custom-profiles.'+suffix)
        with patch.object(kit.filedialog, 'asksaveasfilename', return_value=str(target)): app.export()
        assert signature in target.read_bytes()[:1200]
    kept = app.runs[index].result; entered = threading.Event()
    def hold(budget, n):
        entered.set()
        deadline = time.monotonic()+10
        while not budget.cancel.is_set() and time.monotonic() < deadline: time.sleep(.01)
        if not budget.cancel.is_set():
            raise TimeoutError('The smoke did not cancel the waiting profile worker.')
        return consume(budget, n)
    app.show('result', index)
    with patch.object(ProfileBudget, 'consume', hold):
        kit.drive_dialog(kit.AnalysisDialog, lambda d: None); app.edit_analysis()
        deadline = time.monotonic()+10
        while not entered.is_set():
            assert time.monotonic() < deadline
            root.update(); time.sleep(.01)
        try:
            root.update_idletasks()
            assert app.calculation is not None and app.cancel_button.winfo_ismapped()
        finally:
            app.cancel_calculation()
        kit.wait_for_calculation()
    assert app.runs[index].result is kept
    legacy_index = next(i for i, run in enumerate(app.runs) if run.title == 'Legacy')
    app.open_sheet(('result', legacy_index)); kit.wait_for_calculation()
    for name, expected in legacy.items():
        pd.testing.assert_frame_equal(app.runs[legacy_index].result.tables[name], expected)
    assert app.runs[legacy_index].options == old
    assert threads and threading.main_thread().name not in threads, threads
    assert not kit.errors, kit.errors
    (directory/'custom-profiles-acceptance.json').write_text(json.dumps({
        'status': 'PASS', 'screen': [root.winfo_screenwidth(), root.winfo_screenheight()],
        'profile_threads': sorted(threads), 'sd_edit_and_exclusion': True,
        'canonical_roundtrip': True, 'cancel_preserves_previous_result': True,
        'legacy_custom_wald_unchanged': True, 'csv_png_svg_pdf': True,
    }, indent=2), encoding='utf-8')
