"""Real-widget lifecycle for weighted independent parameter profiles."""
import json
import threading
import time
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from . import i18n
from .data import Dataset, save_project
from .fit_weights import INVERSE_VARIANCE, INFERENCE_WEIGHTS
from .parameter_intervals import METHOD, LEVEL, PROFILE, ProfileBudget

FIT='Nonlinear regression'
BASE={'X':'X','Y columns':['Y'],'Grouping variables':[], 'Model':'Straight line'}


def check_parameter_weighting(root,app,directory,kit):
    x=np.arange(8.)
    y=np.array([2.2,3.5,6.1,6.9,9.5,10.3,13.1,14.])
    sd=np.array([.7,1.2,.9,1.7,.8,1.5,1.1,2.])
    frame=pd.DataFrame({'X':x,'Y':y,'SD':sd})
    path=directory/'weighted-parameters.alab'
    old={**BASE,'Weighting':'1/Yfit²'}
    save_project(path,{'Weighted':Dataset(frame.copy()),
                       'Legacy':Dataset(frame.copy(),analyses=[(FIT,old)])})
    app.import_file(path);app.open_sheet(('result',0));kit.wait_for_calculation()
    legacy={name:table.copy() for name,table in app.runs[0].result.tables.items()}
    assert 'Parameter CI status: All' not in legacy
    wait=kit.wait_for_calculation
    def configure(d):
        kit.pick_method(d,FIT)
        d.controls['X'][1].set('X');kit.select_columns(d,'Y columns',{'Y'})
        d.controls['Model'][1].set('Straight line')
        d.controls[METHOD][1].set(PROFILE);d.controls[LEVEL][1].set('95')
        d.controls['Weighting'][1].set(INVERSE_VARIANCE)
        d.controls['SD column'][1].set('X')
        with patch.object(kit.messagebox,'showerror') as error:
            assert not d.validate()
        d.update();assert error.called and d.focus_get()==d.field_rows['SD column'][1]
        d.controls['SD column'][1].set('SD')
        d.fields.select(d.field_rows[METHOD][1].master);d.update()
        kit.capture(d,'window-weighted-parameters-options-it.png')
    threads=set();consume=ProfileBudget.consume
    def observe(budget,n):
        threads.add(threading.current_thread().name);return consume(budget,n)
    app.show('data','Weighted')
    try:
        i18n.set_language('it')
        with patch.object(ProfileBudget,'consume',observe):
            kit.drive_dialog(kit.AnalysisDialog,configure);app.choose_analysis(only=FIT);wait()
    finally:i18n.set_language('en')
    index=next(i for i,r in enumerate(app.runs) if r.title=='Weighted')
    def compare_sd():
        source=app.tables['Weighted'].frame(mask_excluded=True).dropna(subset=['X','Y','SD'])
        design=np.column_stack([np.ones(len(source)),source.X]);a=design/source.SD.to_numpy()[:,None]
        b=source.Y.to_numpy()/source.SD;beta=np.linalg.lstsq(a,b,rcond=None)[0]
        residual=b-a@beta
        covariance=np.linalg.inv(a.T@a)*(residual@residual)/(len(source)-2)
        delta=stats.t.isf(.025,len(source)-2)*np.sqrt(np.diag(covariance))
        params=app.runs[index].result.tables['Parameters: All']
        np.testing.assert_allclose(params['CI 95% low'],beta-delta,rtol=4e-5)
        np.testing.assert_allclose(params['CI 95% high'],beta+delta,rtol=4e-5)
    compare_sd()
    app.show('data','Weighted');app.edit_cell(1,2,'1.8')
    app.open_sheet(('result',index));wait();compare_sd()
    app.show('data','Weighted');app.current_grid.select((2,1));app.toggle_exclusion()
    app.open_sheet(('result',index));wait();compare_sd()
    table=app.runs[index].result.tables['Parameters: All'].copy()
    app.result_tabs.select(list(app.runs[index].result.tables).index('Parameters: All'))
    kit.capture(root,'window-weighted-parameters-results.png')
    target=directory/'weighted-parameters.csv'
    with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(target)):app.export()
    pd.testing.assert_frame_equal(pd.read_csv(target,index_col=0),table,check_dtype=False)
    app.use_result_as_data()
    pd.testing.assert_frame_equal(app.tables['Parameters: All'].raw,table.reset_index(),check_dtype=False)

    # Observed and fitted weights must stay out of the dialog's calculation thread.
    for weighting in ('1/Y²','1/Yfit²'):
        def edit(d):d.controls['Weighting'][1].set(weighting)
        app.show('result',index)
        with patch.object(ProfileBudget,'consume',observe):
            kit.drive_dialog(kit.AnalysisDialog,edit);app.edit_analysis();wait()
        status=app.runs[index].result.tables['Parameter CI status: All']
        assert status['Weighting'].eq(weighting).all()
        assert status['Lower status'].eq('Profile root').all()
        if weighting=='1/Yfit²':assert status['Inference'].eq(INFERENCE_WEIGHTS).all()
    assert threads and threading.main_thread().name not in threads,threads
    expected=app.runs[index].result.tables['Parameters: All'].copy()
    assert app.save();app.import_file(path)
    index=next(i for i,r in enumerate(app.runs) if r.title=='Weighted')
    app.open_sheet(('graph',index));wait()
    pd.testing.assert_frame_equal(app.runs[index].result.tables['Parameters: All'],expected)
    assert app.runs[index].options['Weighting']=='1/Yfit²'
    assert app.runs[index].options[METHOD]==PROFILE
    kit.capture(root,'window-weighted-parameters-graph.png')
    for suffix,signature in [('svg',b'<svg'),('png',b'\x89PNG'),('pdf',b'%PDF')]:
        app.show('graph',index);target=directory/('weighted-parameters.'+suffix)
        with patch.object(kit.filedialog,'asksaveasfilename',return_value=str(target)):app.export()
        assert signature in target.read_bytes()[:1200]
    kept=app.runs[index].result;entered=threading.Event()
    def hold(budget,n):
        entered.set()
        while not budget.cancel.is_set():time.sleep(.01)
        return consume(budget,n)
    app.show('result',index)
    with patch.object(ProfileBudget,'consume',hold):
        kit.drive_dialog(kit.AnalysisDialog,lambda d:None);app.edit_analysis()
        deadline=time.monotonic()+10
        while not entered.is_set():
            assert time.monotonic()<deadline
            root.update();time.sleep(.01)
        app.cancel_calculation();wait()
    assert app.runs[index].result is kept
    oldindex=next(i for i,r in enumerate(app.runs) if r.title=='Legacy')
    app.open_sheet(('result',oldindex));wait()
    for name,table in legacy.items():pd.testing.assert_frame_equal(app.runs[oldindex].result.tables[name],table)
    assert app.runs[oldindex].options==old
    assert not kit.errors,kit.errors
    (directory/'weighted-parameters-acceptance.json').write_text(json.dumps({
        'status':'PASS','screen':[root.winfo_screenwidth(),root.winfo_screenheight()],
        'profile_threads':sorted(threads),'sd_edit_and_exclusion':True,'canonical_roundtrip':True,
        'frozen_irls_inference_reported':True,'cancel_preserves_previous_result':True,
        'legacy_weighted_wald_unchanged':True,'csv_png_svg_pdf':True,
    },indent=2),encoding='utf-8')
