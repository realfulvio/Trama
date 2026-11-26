"""Measure the linked-coefficient fixture with the real analysis action and write a JSON like ``atteso.json``.

    python tests/coefficient_links_measure.py OUT.json [--reopen]

The three cases of ``tests/data/coefficient_links/atteso.json`` (global unweighted, global weighted with the SD
column, the series Uno alone) run ``analisi.workbench.analyse`` on the recipes stored in the two example projects
``docs/examples/Coefficienti-collegati-*.alab``. With ``--reopen`` the projects are first written again by
``save_project`` and read back with ``load_project``, so the values come from a reopened recipe. Every number is
read from the result sheets (Parameters, Fit/Global fit and the Predicted column of the residuals) of the
candidate. Compare with ``python tests/data/coefficient_links/confronta.py OUT.json --tolleranza 1e-6``.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from analisi.data import load_project, save_project  # noqa: E402
from analisi.workbench import analyse  # noqa: E402

EXAMPLES = ROOT / "docs" / "examples"
GLOBAL = EXAMPLES / "Coefficienti-collegati-globale.alab"
SINGLE = EXAMPLES / "Coefficienti-collegati-singolo.alab"


def _tables(path, reopen):
    tables = load_project(path)
    if not reopen:
        return tables
    with tempfile.TemporaryDirectory() as folder:
        copy = Path(folder) / path.name
        save_project(copy, tables)
        return load_project(copy)


def _global(result):
    parameters = result.tables["Parameters"]
    summary = result.tables["Global fit"]["Value"]

    def row(name, group=None):
        rows = parameters[(parameters["Parameter"] == name)
                          & (parameters["Group"].isna() if group is None else parameters["Group"] == group)]
        return rows.iloc[0]

    a, c = row("A"), row("C")
    groups = [g for g in pd.unique(parameters.loc[parameters["Parameter"] == "B", "Group"])]
    return {"A": float(a["Estimate"]), "C": float(c["Estimate"]),
            "B": {str(g): float(row("B", g)["Estimate"]) for g in groups},
            "df": int(summary["DF residual"]), "free": int(summary["Free parameters"]),
            "rss": float(summary["Weighted residual SS"]), "se_A": float(a["SE"]), "se_C": float(c["SE"]),
            "ci_C": [float(c["CI low"]), float(c["CI high"])],
            "predictions": [float(v) for v in result.tables["Residuals"]["Predicted"]]}


def _single(result, label="Uno"):
    parameters = result.tables[f"Parameters: {label}"]
    summary = result.tables[f"Fit: {label}"]["Value"]
    return {"A": float(parameters.loc["A", "Estimate"]), "C": float(parameters.loc["C", "Estimate"]),
            "B": {"Uno": float(parameters.loc["B", "Estimate"])},
            "df": int(summary["df"]), "free": int(summary["Free parameters"]),
            "rss": float(summary["Weighted residual SS"]), "se_A": float(parameters.loc["A", "SE"]),
            "se_C": float(parameters.loc["C", "SE"]),
            "ci_C": [float(parameters.loc["C", "CI lower"]), float(parameters.loc["C", "CI upper"])],
            "predictions": [float(v) for v in result.tables[f"Residuals: {label}"]["Predicted"]]}


def measure(reopen=False):
    measured = {}
    tables = _tables(GLOBAL, reopen)
    for table in tables.values():
        frame = table.frame(mask_excluded=True)
        for method, options in table.analyses:
            key = "pesato" if options.get("Weighting") != "Unweighted" else "globale"
            measured[key] = _global(analyse(method, frame, options))
    for table in _tables(SINGLE, reopen).values():
        frame = table.frame(mask_excluded=True)
        for method, options in table.analyses:
            measured["singolo"] = _single(analyse(method, frame, options))
    if not np.all([np.isfinite(case["se_C"]) for case in measured.values()]):
        raise SystemExit("A standard error is missing.")
    return measured


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out", type=Path)
    parser.add_argument("--reopen", action="store_true", help="save and reload the projects first")
    args = parser.parse_args(argv)
    args.out.write_text(json.dumps(measure(args.reopen), indent=2, allow_nan=False), encoding="utf-8")
    print(f"Written {args.out}")


if __name__ == "__main__":
    main()
