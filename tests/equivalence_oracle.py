"""Independent TOST fixture oracle; imports no Trama modules."""
import csv
import json
import math
from pathlib import Path
from scipy import stats
ROOT = Path(__file__).resolve().parent / "data" / "equivalence_071"

def read_columns(path):
    with (ROOT / path).open(newline="", encoding="utf-8") as stream:
        rows=list(csv.DictReader(stream))
    return {name:[float(row[name]) if row[name].strip() else math.nan for row in rows]
            for name in rows[0].keys()}

def finite(values):
    return [x for x in values if math.isfinite(x)]

def tost(estimate,se,df,lower,upper,alpha):
    tl=(estimate-lower)/se
    tu=(estimate-upper)/se
    pl=float(stats.t.sf(tl,df))
    pu=float(stats.t.cdf(tu,df))
    q=float(stats.t.ppf(1-alpha,df))
    return {"difference":estimate,"se":se,"df":df,"lower_margin":lower,"upper_margin":upper,
      "alpha":alpha,"ci_level":100*(1-2*alpha),"ci_lower":estimate-q*se,"ci_upper":estimate+q*se,
      "t_lower":tl,"p_lower":pl,"t_upper":tu,"p_upper":pu,"p_tost":max(pl,pu),
      "conclusion":"Equivalent" if pl<alpha and pu<alpha else "Not demonstrated"}

def one_sample(values,reference,lower,upper,alpha):
    xs=finite(values); n=len(xs); mean=sum(xs)/n; sd=stats.tstd(xs,ddof=1)
    return {"n_first":n,"n_second":None,**tost(mean-reference,sd/math.sqrt(n),n-1,lower,upper,alpha)}

def paired(first,second,lower,upper,alpha):
    d=[a-b for a,b in zip(first,second) if math.isfinite(a) and math.isfinite(b)]
    n=len(d); mean=sum(d)/n; sd=stats.tstd(d,ddof=1)
    return {"n_first":n,"n_second":n,**tost(mean,sd/math.sqrt(n),n-1,lower,upper,alpha)}

def independent(first,second,lower,upper,alpha,method):
    a,b=finite(first),finite(second); n1,n2=len(a),len(b)
    m1,m2=sum(a)/n1,sum(b)/n2; v1,v2=stats.tvar(a,ddof=1),stats.tvar(b,ddof=1)
    if method=="Student":
        df=n1+n2-2; sp2=((n1-1)*v1+(n2-1)*v2)/df; se=math.sqrt(sp2*(1/n1+1/n2))
    else:
        va,vb=v1/n1,v2/n2; se=math.sqrt(va+vb); df=(va+vb)**2/(va**2/(n1-1)+vb**2/(n2-1))
    return {"n_first":n1,"n_second":n2,**tost(m1-m2,se,df,lower,upper,alpha)}

def build():
    one=read_columns("one_sample.csv")
    paired_data=read_columns("paired.csv")
    indep=read_columns("independent.csv")
    return {"one_sample":one_sample(one["Response"],0.,-.06,.06,.05),
      "paired":paired(paired_data["First"],paired_data["Second"],-.08,.12,.05),
      "independent_student":independent(indep["First"],indep["Second"],-.12,.12,.05,"Student"),
      "independent_welch":independent(indep["First"],indep["Second"],-.12,.12,.05,"Welch"),
      "provenance":"Synthetic CSV values; direct sample moments and scipy Student-t CDF/SF/quantile; no application function."}

if __name__=="__main__":
    result=build()
    (ROOT/"expected.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2,sort_keys=True))
