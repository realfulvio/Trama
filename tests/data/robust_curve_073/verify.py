"""External contract verifier. Run unchanged, with or without --repo."""
import argparse
import copy
import importlib
import json
import math
import sys
from pathlib import Path

import numpy as np
from reference_oracle import MODEL_PARAMETERS, reference_fit, rho_weights

ROOT=Path(__file__).resolve().parent


def close(a,b,*,rtol=3e-5,atol=2e-7):
    # numpy.testing formats atol as a scalar even when the comparison needs a
    # separate bound per coefficient. Keep those bounds, including tiny ones.
    actual, desired = np.asarray(a, float), np.asarray(b, float)
    if not np.allclose(actual, desired, rtol=rtol, atol=atol, equal_nan=True):
        raise AssertionError(f"not close: {actual!r} vs {desired!r}; rtol={rtol!r}, atol={atol!r}")


def serialize_result(result):
    def scalar(v):
        if hasattr(v,'item'):v=v.item()
        if isinstance(v,(float,int)) and not isinstance(v,bool):return float(v) if math.isfinite(v) else None
        if isinstance(v,tuple):return [scalar(x) for x in v]
        return v
    return {name:{'columns':[scalar(v) for v in t.columns], 'index':[scalar(v) for v in t.index],
                  'data':[[scalar(v) for v in row] for row in t.to_numpy().tolist()]} for name,t in result.tables.items()}


def compare_tree(a,b):
    if isinstance(b,dict):
        assert set(a)==set(b),(set(a),set(b))
        for k in b:compare_tree(a[k],b[k])
    elif isinstance(b,list):
        assert len(a)==len(b),(len(a),len(b))
        for x,y in zip(a,b):compare_tree(x,y)
    elif isinstance(b,(int,float)) and not isinstance(b,bool):
        assert math.isclose(a,b,rel_tol=2e-8,abs_tol=1e-10),(a,b)
    else:assert a==b,(a,b)


def legacy_cases(pd,analyse):
    f=pd.DataFrame({'X':list(range(9)),'Y':[2.1,4.8,8.1,11.,14.2,16.9,50.,23.1,25.8]})
    out={}
    for mode in ['Percent of range','Z score','Percent of first value','Subtract first value']:
        out[mode]=serialize_result(analyse('Normalize',f,{'Variables':['Y'],'Method':mode}))
    out['ordinary']=serialize_result(analyse('Nonlinear regression',f,{'X':'X','Y columns':['Y'],
                'Grouping variables':[],'Model':'Straight line','Weighting':'Unweighted'}))
    return out


def expected_case(c):
    o=c['options']; data=c['data']; pos=[i for i,(x,y) in enumerate(zip(data['X'],data['Y'])) if x is not None and y is not None]
    names=MODEL_PARAMETERS[o['Model']]
    result=reference_fit(o['Model'],[data['X'][i] for i in pos],[data['Y'][i] for i in pos],
                [o['Initial parameters'][k] for k in names],o['Loss'],o.get('Residual scale',1),o.get('Scale method','Fixed'))
    return {**result,'source_rows':pos,'source_index':[c.get('index',list(range(len(data['X']))))[i] for i in pos],
            'parameter_names':names}


def run(repo=None,freeze=False):
    cases=json.loads((ROOT/'fixtures/cases.json').read_text());reports=[]
    def check(name,fn):
        try:fn()
        except Exception as e:reports.append({'case':name,'status':'FAIL','reason':f'{type(e).__name__}: {e}'})
        else:reports.append({'case':name,'status':'PASS'})
    if repo:
        sys.path.insert(0,str(Path(repo).resolve()))
        import matplotlib
        matplotlib.use('Agg')
        import pandas as pd
        from analisi.workbench import analyse
        from analisi.field_error import FieldError
        from matplotlib.backends.backend_agg import FigureCanvasAgg
    if freeze:
        exp={c['name']:expected_case(c) for c in cases}
        (ROOT/'expected').mkdir(exist_ok=True)
        (ROOT/'expected/results.json').write_text(json.dumps(exp,indent=2,allow_nan=False)+'\n')
        if repo:(ROOT/'expected/legacy.json').write_text(json.dumps(legacy_cases(pd,analyse),indent=2,allow_nan=False)+'\n')
        return [{'case':'freeze-independent-goldens','status':'PASS'}]
    expected=json.loads((ROOT/'expected/results.json').read_text())
    if not repo:
        for c in cases:
            def oracle(c=c):
                now=expected_case(c);gold=expected[c['name']]
                for key in ['parameters','scale','objective','weights','predicted','raw_ss']:
                    close(now[key],gold[key],rtol=5e-6,atol=1e-10*max(1e-300,np.max(np.abs(gold[key]))))
                assert now['source_rows']==gold['source_rows']
            check(c['name'],oracle)
        def hand():
            for loss,values,weights in [('Cauchy',[0,math.log(2),math.log(5)],[1,.5,.2]),
                                        ('Huber',[0,1,3],[1,1,.5]),
                                        ('Soft L1',[0,2*(math.sqrt(2)-1),2*(math.sqrt(5)-1)],[1,1/math.sqrt(2),1/math.sqrt(5)])]:
                r,w=rho_weights([0,1,2],loss);close(r,values,rtol=1e-12,atol=1e-14);close(w,weights,rtol=1e-12,atol=1e-14)
        check('loss-hand-calculations',hand)
        def second_solver():
            from scipy.optimize import least_squares
            from reference_oracle import equation
            losses={'Cauchy':'cauchy','Huber':'huber','Soft L1':'soft_l1'}
            for c in cases:
                o=c['options'];g=expected[c['name']];i=g['source_rows'];x=np.array([c['data']['X'][j] for j in i]);y=np.array([c['data']['Y'][j] for j in i])
                p0=np.array([o['Initial parameters'][k] for k in g['parameter_names']]);units=np.where(p0==0,1,np.abs(p0))
                lo=np.full(len(p0),-np.inf)
                if o['Model']=='One-phase decay':lo[2]=0
                if o['Model']=='Logistic (4 parameters)':lo[3]=0
                s=g['scale']
                if s==0:
                    close(g['predicted'],y,rtol=0,atol=0);assert all(w==1 for w in g['weights']);continue
                q=least_squares(lambda q:(y-equation(o['Model'],x,q*units))/s,p0/units,bounds=(lo,np.inf),
                                loss=losses[o['Loss']],ftol=1e-12,xtol=1e-12,gtol=1e-12,max_nfev=20000)
                assert q.success,c['name']
                close(q.x*units,g['parameters'],rtol=3e-5,atol=2e-6*max(np.max(np.abs(g['parameters'])),1e-300))
        check('independent-trust-region-crosscheck',second_solver)
        return reports

    def legacy():compare_tree(legacy_cases(pd,analyse),json.loads((ROOT/'expected/legacy.json').read_text()))
    check('legacy-five-recipes',legacy)
    for c in cases:
        def candidate(c=c):
            f=pd.DataFrame(c['data'],index=c.get('index'));before=f.copy(deep=True)
            result=analyse('Robust curve fit',f,copy.deepcopy(c['options']));gold=expected[c['name']]
            pd.testing.assert_frame_equal(f,before);assert list(result.tables)[:4]==['Robust parameters','Robust fit','Robust residuals','Robust curve']
            p=result.tables['Robust parameters'];r=result.tables['Robust residuals'];fit=result.tables['Robust fit'].iloc[0]
            assert p['Parameter'].tolist()==gold['parameter_names'];assert p['Series'].eq('Y').all()
            assert p['Group'].eq('All').all();assert r['Source row'].tolist()==gold['source_rows']
            assert r['Source index'].tolist()==gold['source_index']
            pp=np.asarray(gold['parameters']);units=np.maximum(np.abs(pp),1e-300)
            close(p['Estimate'],pp,atol=2e-6*units)
            yu=max(max(abs(x) for x in c['data']['Y'] if x is not None),1e-300)
            close(r['Predicted'],gold['predicted'],atol=2e-6*yu)
            close(r['Influence weight'],gold['weights'],atol=2e-5)
            close(fit['Robust objective'],gold['objective'],atol=2e-6)
            close(fit['Residual scale'],gold['scale'],rtol=2e-6,atol=1e-10*yu)
            close(fit['Raw residual SS'],gold['raw_ss'],rtol=2e-5,atol=1e-10*yu*yu)
            assert fit['N']==len(gold['source_rows'])
            assert r['Low weight'].tolist()==[w<.25 for w in gold['weights']]
            assert len(result.tables['Robust curve'])==201
            assert result.figure is not None;FigureCanvasAgg(result.figure).draw()
            assert not any(k in p.columns for k in ['SE','p','CI lower','CI upper'])
        check(c['name'],candidate)
    first=cases[0]
    bad=[('zero scale',{'Residual scale':0},'Residual scale'),('negative scale',{'Residual scale':-1},'Residual scale'),
         ('infinite scale',{'Residual scale':'inf'},'Residual scale'),('bad loss',{'Loss':'unknown'},'Loss'),
         ('empty Y',{'Y columns':[]},'Y columns'),('overlap group',{'Group':'Y'},'Group'),
         ('initial missing',{'Initial parameters':{'Intercept':2}},'Initial parameters'),
         ('initial bool',{'Initial parameters':{'Intercept':True,'Slope':3}},'Initial parameters'),
         ('threshold zero',{'Low weight threshold':0},'Low weight threshold'),
         ('eval bool',{'Maximum evaluations':True},'Maximum evaluations')]
    for name,patch,field in bad:
        def invalid(patch=patch,field=field):
            f=pd.DataFrame(first['data']);before=f.copy(deep=True)
            try:analyse('Robust curve fit',f,{**first['options'],**patch})
            except FieldError as e:assert e.field==field,(e.field,field)
            else:raise AssertionError('Expected FieldError')
            pd.testing.assert_frame_equal(f,before)
        check(name,invalid)
    return reports


def main():
    p=argparse.ArgumentParser();p.add_argument('--repo');p.add_argument('--freeze',action='store_true');p.add_argument('--json',type=Path)
    a=p.parse_args();report=run(a.repo,a.freeze)
    for r in report:print(r['status'],r['case'],r.get('reason',''))
    print(f"{sum(r['status']=='PASS' for r in report)}/{len(report)} PASS")
    if a.json:a.json.write_text(json.dumps(report,indent=2)+'\n')
    raise SystemExit(0 if all(r['status']=='PASS' for r in report) else 1)


if __name__=='__main__':main()
