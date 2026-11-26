"""Confronta il JSON misurato in Trama con atteso.json in questo pacchetto."""
import argparse
import json
import math
from pathlib import Path

def compare(expected, actual, path, tol):
    if isinstance(expected,dict):
        if not isinstance(actual,dict):
            raise ValueError(f"{path}: atteso un oggetto")
        for key,value in expected.items():
            if key not in actual:
                raise ValueError(f"{path}: manca {key!r}")
            compare(value,actual[key],f"{path}.{key}",tol)
    elif isinstance(expected,list):
        if not isinstance(actual,list) or len(expected)!=len(actual):
            raise ValueError(f"{path}: numero di elementi inatteso")
        for i,(a,b) in enumerate(zip(expected,actual)):
            compare(a,b,f"{path}[{i}]",tol)
    elif type(expected) in (int,float):
        if type(actual) not in (int,float) or not math.isfinite(actual) or not math.isclose(expected,actual,abs_tol=tol,rel_tol=tol):
            raise ValueError(f"{path}: previsto {expected!r}, ottenuto {actual!r}")
    elif actual != expected:
        raise ValueError(f"{path}: previsto {expected!r}, ottenuto {actual!r}")

if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("misurato",type=Path)
    p.add_argument("--tolleranza",type=float,default=1e-9)
    args=p.parse_args()
    if not 0 <= args.tolleranza <= 1e-5:
        p.error("La tolleranza deve essere compresa fra 0 e 1e-5")
    expected=json.loads(Path(__file__).with_name("atteso.json").read_text())
    try:
        compare(expected,json.loads(args.misurato.read_text()),"risultato",args.tolleranza)
    except ValueError as exc:
        p.exit(1,f"ERRORE {exc}\n")
    print("OK: tutti i casi attesi coincidono.")
