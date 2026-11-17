"""Real-widget acceptance, exclusions and project roundtrip for summary t tests."""
import json
from unittest.mock import patch

import numpy as np
import pandas as pd
from scipy import stats

from . import i18n
from .data import Dataset, save_project
from .summary_ttest import METHOD


def check_summary_ttest(root, app, directory, tools):
    out=directory/'summary-ttest';out.mkdir(exist_ok=True)
    language=i18n.active_language();wait=tools.wait_for_calculation

    def capture(window,name):
        tools.capture(window,name)
        source=directory/name
        if source.exists():source.replace(out/name)

    def setup(dialog):
        tools.pick_method(dialog,METHOD)
        for name,value in {'Input':'Groups in rows','Group':'Group','Mean':'Mean','Dispersion':'SD',
                           'Sample size':'N','Design':'Welch'}.items():dialog.controls[name][1].set(value)
        dialog.controls['Confidence level (%)'][1].set('100')
        with patch.object(tools.messagebox,'showerror') as error:
            assert dialog.validate() is False and error.called
        assert dialog.focus_get() is dialog.field_rows['Confidence level (%)'][1]
        capture(dialog,'error-summary-ttest-'+i18n.active_language()+'.png')
        dialog.controls['Confidence level (%)'][1].set('95')
        dialog.fields.select(1);dialog.update()
        assert dialog.winfo_rooty()+dialog.winfo_height() <= root.winfo_screenheight()
        capture(dialog,'options-summary-ttest-'+i18n.active_language()+'.png')

    try:
        data=pd.DataFrame({'Group':['A','B'],'Mean':[3.,16/3],'SD':[np.sqrt(10/3),np.sqrt(19/3)],'N':[4,3]})
        original=stats.ttest_ind([1,2,4,5],[3,5,8],equal_var=False)
        path=out/'input.alab';save_project(path,{'Summary':Dataset(data)})
        i18n.set_language('en');app.import_file(path);app.show('data','Summary')
        tools.drive_dialog(tools.AnalysisDialog,setup);app.choose_analysis(only=METHOD);wait()
        assert not tools.errors,tools.errors
        index=len(app.runs)-1
        assert np.isclose(app.runs[index].result.tables['t-test'].iloc[0]['p'],original.pvalue)
        app.show('graph',index);root.update();capture(root,'graph-summary-ttest.png')
        for suffix in ('png','svg','pdf'):app.runs[index].result.figure.savefig(out/('summary-ttest.'+suffix))
        app.show('result',index)
        with patch.object(tools.filedialog,'asksaveasfilename',return_value=str(out/'ttest.csv')):app.export()
        i18n.set_language('it');tools.drive_dialog(tools.AnalysisDialog,setup);app.edit_analysis();wait()
        assert app.runs[index].options['Design']=='Welch'
        app.show('data','Summary');app.current_grid.active_cell=(0,2);app.toggle_exclusion();wait()
        # One complete group cannot define an unpaired test. Do not show stale inference.
        assert app.runs[index].result is None
        assert 'exactly two' in app.status.get()
        app.apply_worksheet_history();wait()
        assert np.isclose(app.runs[index].result.tables['t-test'].iloc[0]['p'],original.pvalue)
        app.edit_cell(0,1,'4');wait()
        assert not np.isclose(app.runs[index].result.tables['t-test'].iloc[0]['p'],original.pvalue)
        expected=app.runs[index].result.tables['t-test'].copy(deep=True)
        roundtrip=out/'roundtrip.alab';app.path=roundtrip;assert app.save()
        i18n.set_language('en');app.import_file(roundtrip);app.show('graph',0)
        if app.runs[0].result is None:app.recalculate(0)
        wait();pd.testing.assert_frame_equal(app.runs[0].result.tables['t-test'],expected)
        app.show('result',0);app.result_tabs.select(1)
        count=len(app.tables);app.use_result_as_data();root.update();assert len(app.tables)==count+1

        wide=pd.DataFrame({f'{r.Group} [{role}]':[value] for r in data.itertuples()
                           for role,value in (('Mean',r.Mean),('SEM',r.SD/np.sqrt(r.N)),('N',r.N))})
        path=out/'wide.alab';save_project(path,{'Wide':Dataset(wide,table_format='grouped')})
        app.import_file(path);app.show('data','Wide')
        def wide_setup(dialog):
            tools.pick_method(dialog,METHOD)
            dialog.controls['Input'][1].set('Summary subcolumns')
            dialog.controls['Dispersion type'][1].set('SEM')
            dialog.controls['Design'][1].set('Student')
            tools.select_columns(dialog,'Variables',set(wide))
            dialog.controls['Summary row'][1].set('2')
            with patch.object(tools.messagebox,'showerror'):assert dialog.validate() is False
            dialog.controls['Summary row'][1].set('1')
            dialog.fields.select(0);dialog.update();capture(dialog,'input-summary-ttest-wide.png')
        tools.drive_dialog(tools.AnalysisDialog,wide_setup);app.choose_analysis(only=METHOD);wait()
        row=app.runs[0].result.tables['t-test'].iloc[0]
        assert np.isclose(row['t'],stats.ttest_ind([1,2,4,5],[3,5,8],equal_var=True).statistic)
        assert not tools.errors,tools.errors
        (out/'checks.json').write_text(json.dumps({'status':'PASS','screen':[root.winfo_screenwidth(),root.winfo_screenheight()],
            'checks':['EN/IT controls and focus','invalid confidence and summary row','Welch and Student',
                      'rows and SEM subcolumns','exclusion clears invalid inference; undo restores',
                      'edit and recalculate','roundtrip graph first','result as data','CSV/PNG/SVG/PDF']},indent=2))
    finally:i18n.set_language(language)
