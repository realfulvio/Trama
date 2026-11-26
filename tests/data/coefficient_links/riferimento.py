"""Modello ristretto ridotto a minimi quadrati lineari. Richiede numpy e scipy."""
from pathlib import Path
import csv,json
import numpy as np
from scipy.stats import t

data=list(csv.DictReader(Path(__file__).with_name("curve.csv").open()))
def fit(rows, weighted):
    names=list(dict.fromkeys(r["serie"] for r in rows))
    x=np.array([float(r["x"]) for r in rows])
    y=np.array([float(r["y"]) for r in rows])
    sd=np.array([float(r["sd"]) if weighted else 1. for r in rows])
    z=x+2*x*x
    design=np.column_stack([z]+[[r["serie"]==g for r in rows] for g in names])
    a=design/sd[:,None]
    response=(y-x*x)/sd
    beta,_,rank,_=np.linalg.lstsq(a,response,rcond=None)
    df=int(len(y)-rank)
    res=y-(x*x+design@beta)
    rss=float(np.sum((res/sd)**2))
    cov=np.linalg.inv(a.T@a)*(rss/df)
    se=float(cov[0,0]**.5)
    c=2*float(beta[0])+1
    crit=t.ppf(.975,df)
    return dict(A=float(beta[0]),C=c,B=dict(zip(names,map(float,beta[1:]))),
                df=df,free=int(rank),rss=rss,se_A=se,se_C=2*se,ci_C=[c-crit*2*se,c+crit*2*se],
                predictions=(x*x+design@beta).tolist())
out={name:fit(rows,w) for name,rows,w in [('globale',data,False),('pesato',data,True),
                             ('singolo',[r for r in data if r['serie']=='Uno'],False)]}
assert abs(out['globale']['rss']-.5)<1e-12 and out['globale']['df']==7
assert abs(out['globale']['A']-1.5)<1e-12 and abs(out['globale']['C']-4)<1e-12
print(json.dumps(out,indent=2,allow_nan=False))
