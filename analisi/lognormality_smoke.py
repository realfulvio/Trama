"""Normal/lognormal real-widget checks with both Q–Q panels and saved recipes."""
import json
from unittest.mock import patch
import numpy as np
import pandas as pd

from . import i18n
from .data import Dataset, save_project
from .normality import NORMALITY, TESTS
from .lognormality import DISTRIBUTION, COMPARE, COMPARISON, LOG_TESTS, LOG_QQ


def check_lognormality(root, app, directory, tools):
    out=directory/'lognormality';out.mkdir(exist_ok=True)
    language=i18n.active_language()
    wait=tools.wait_for_calculation
    def capture(window,name):
        tools.capture(window,name)
        source=directory/name
        if source.exists():source.replace(out/name)
    def options(dialog):
        tools.pick_method(dialog,NORMALITY)
        tools.select_columns(dialog,'Variables',{'A','B'})
        dialog.controls[DISTRIBUTION][1].set('Both')
        dialog.controls[COMPARE][1].set(True)
        for test in TESTS:dialog.controls[test][1].set(True)
        dialog.controls['Q–Q plot'][1].set(True)
        dialog.controls['Q–Q variable'][1].set('B')
        with patch.object(tools.messagebox,'showerror') as error:
            assert dialog.validate() is False
            assert 'positive' in str(error.call_args) or 'positivi' in str(error.call_args)
        dialog.controls['Q–Q variable'][1].set('A')
        dialog.fields.select(1);dialog.update()
        assert dialog.winfo_rooty()+dialog.winfo_height() <= root.winfo_screenheight()
        capture(dialog,'dialog-lognormal-'+i18n.active_language()+'.png')
    def comparison(index):return app.runs[index].result.tables[COMPARISON]
    try:
        i18n.set_language('en')
        data=pd.DataFrame({'A':np.exp(np.linspace(-2,2,12)),'B':np.arange(12.)})
        source=out/'input.alab';save_project(source,{'Distributions':Dataset(data)})
        app.import_file(source);app.show('data','Distributions')
        tools.drive_dialog(tools.AnalysisDialog,options)
        app.choose_analysis(only=NORMALITY);wait()
        index=len(app.runs)-1
        run=app.runs[index]
        assert len(run.result.figure.axes)==2
        assert set(run.result.tables[LOG_TESTS].query('Variable == "B"')['Decision'])=={'Not tested'}
        weights=comparison(index).query('Variable == "A"')['Relative weight (%)'].to_numpy()
        assert np.isclose(weights.sum(),100)
        app.show('graph',index);root.update();capture(root,'graph-normal-lognormal.png')
        for suffix in ('png','svg','pdf'):run.result.figure.savefig(out/('normal-lognormal.'+suffix))
        app.show('result',index)
        app.result_tabs.select(list(run.result.tables).index(COMPARISON))
        with patch.object(tools.filedialog,'asksaveasfilename',return_value=str(out/'comparison.csv')):app.export()
        assert len(pd.read_csv(out/'comparison.csv',index_col=0))==4
        i18n.set_language('it')
        tools.drive_dialog(tools.AnalysisDialog,options);app.edit_analysis();wait()
        assert app.runs[index].options[DISTRIBUTION]=='Both'
        app.show('data','Distributions');app.current_grid.active_cell=(4,0);app.toggle_exclusion();wait()
        assert set(comparison(index).query('Variable == "A"')['N'])=={11}
        assert 5 not in app.runs[index].result.tables[LOG_QQ]['Source row'].tolist()
        app.apply_worksheet_history();wait()
        app.edit_cell(4,0,'30');wait()
        assert not np.allclose(comparison(index).query('Variable == "A"')['Relative weight (%)'],weights)
        path=out/'roundtrip.alab';app.path=path;assert app.save()
        i18n.set_language('en');app.import_file(path)
        index=next(i for i,run in enumerate(app.runs) if run.options.get(DISTRIBUTION)=='Both')
        app.show('graph',index)
        if app.runs[index].result is None:app.recalculate(index)
        wait();assert len(app.runs[index].result.figure.axes)==2
        assert app.runs[index].options[COMPARE] is True
        app.show('result',index);app.result_tabs.select(list(app.runs[index].result.tables).index(COMPARISON))
        count=len(app.tables);app.use_result_as_data();root.update();assert len(app.tables)==count+1
        assert not tools.errors,tools.errors
        (out/'checks.json').write_text(json.dumps({'status':'PASS','screen':[root.winfo_screenwidth(),root.winfo_screenheight()],
            'checks':['real EN/IT dialog','positive-domain error and correction','both Q–Q panels','source edit/exclusion',
                      'canonical roundtrip','CSV/PNG/SVG/PDF','Use Result as Data']},indent=2))
    finally:i18n.set_language(language)
