"""Oracolo indipendente sulle coorti sintetiche. Richiede numpy e scipy."""
from pathlib import Path
import csv
from itertools import combinations
import json
import numpy as np
from scipy.stats import chi2

rows = list(csv.DictReader(Path(__file__).with_name("coorti.csv").open()))
groups = sorted({r["gruppo"] for r in rows})
methods = {"logrank": None, "tarone_ware": None, "gehan": None,
           "fh_1_0": (1,0), "fh_0_1": (0,1), "fh_1_1": (1,1), "fh_0_0": (0,0)}

def calc(names, method):
    cohort = [r for r in rows if r["gruppo"] in names]
    times = sorted({int(r["tempo"]) for r in cohort if int(r["evento"])})
    score = np.zeros(len(names))
    cov = np.zeros((len(names),len(names)))
    km = 1.0
    audit = []
    for t in times:
        at = np.array([sum(r["gruppo"] == g and int(r["tempo"]) >= t for r in cohort) for g in names])
        d = np.array([sum(r["gruppo"] == g and int(r["tempo"]) == t and int(r["evento"]) for r in cohort) for g in names])
        n, events = int(at.sum()), int(d.sum())
        if method.startswith("fh_"):
            rho, gamma = methods[method]
            w = km ** rho * (1-km) ** gamma
        else:
            w = {"logrank":1.0,"gehan":float(n),"tarone_ware":n**0.5}[method]
        prop = at/n
        score += w*(d-events*prop)
        if n>1:
            cov += (w*w*events*(n-events)/(n-1))*(np.diag(prop)-np.outer(prop,prop))
        audit.append(dict(t=t, at_risk=n, events=events, s_before=km, weight=w))
        km *= 1-events/n
    df = len(names)-1
    value = float(score[:-1] @ np.linalg.solve(cov[:-1,:-1],score[:-1]))
    return dict(chi2=value,df=df,p=float(chi2.sf(value,df)),audit=audit)

def holm(values):
    order=sorted(values,key=values.get)
    largest=0.0
    out={}
    for i,key in enumerate(order):
        largest=max(largest,(len(values)-i)*values[key])
        out[key]=min(1.0,largest)
    return out

result={}
for method in methods:
    global_test=calc(groups,method)
    pairs={"-".join(p):calc(p,method) for p in combinations(groups,2)}
    adj=holm({k:t["p"] for k,t in pairs.items()})
    for k in pairs:
        pairs[k]["p_holm"]=adj[k]
    result[method]=dict(global_test=global_test,pairs=pairs)
assert result["logrank"]==result["fh_0_0"]
assert result["fh_0_1"]["global_test"]["audit"][0]["weight"]==0
print(json.dumps(result,indent=2,allow_nan=False))
