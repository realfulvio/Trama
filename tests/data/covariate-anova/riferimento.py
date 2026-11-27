import argparse
import json
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
from patsy import build_design_matrices
from scipy.stats import t
from statsmodels.formula import options as formula_options
from statsmodels.stats.anova import anova_lm


ROOT = Path(__file__).parent
AT = {"X": 6.0, "Z": 4.0}
formula_options.formula_engine = "patsy"


def mean_ci(model, design, critical):
    estimate = float(design @ model.params)
    se = float(np.sqrt(design @ model.cov_params() @ design))
    return {"estimate": estimate, "se": se, "low": estimate - critical * se,
            "high": estimate + critical * se}


def fit(frame, covariates, interaction):
    factors = ["C(Dose, Sum)", "C(Metodo, Sum)"]
    terms = [" * ".join(factors)] if interaction else factors
    centered = {name: frame[name] - AT[name] for name in covariates}
    model = smf.ols("Y ~ " + " + ".join(terms + covariates), data=frame.assign(**centered)).fit()
    anova = anova_lm(model, typ=3).drop(index=["Intercept", "Residual"])
    labels = list(product(sorted(frame.Dose.unique()), sorted(frame.Metodo.unique())))
    grid = pd.DataFrame(labels, columns=["Dose", "Metodo"]).assign(**dict.fromkeys(covariates, 0.0))
    design, = build_design_matrices([model.model.data.model_spec], grid)
    critical = t.ppf(.975, model.df_resid)
    covariate_intervals = model.conf_int()
    return {
        "n": int(model.nobs), "residual_df": int(model.df_resid), "rss": float(model.ssr),
        "type_iii": anova.to_dict(orient="index"),
        "covariates": {key: {"estimate": float(model.params[key]), "se": float(model.bse[key]),
                             "low": float(covariate_intervals.loc[key, 0]),
                             "high": float(covariate_intervals.loc[key, 1])} for key in covariates},
        "cell_means": {f"{a} / {b}": mean_ci(model, row, critical)
                       for (a, b), row in zip(labels, design, strict=True)},
        "dose_means": {level: mean_ci(model, design[grid.Dose == level].mean(axis=0), critical)
                       for level in sorted(frame.Dose.unique())},
        "method_means": {level: mean_ci(model, design[grid.Metodo == level].mean(axis=0), critical)
                         for level in sorted(frame.Metodo.unique())},
    }


def oracle():
    frame = pd.read_csv(ROOT / "fattoriale.csv")
    return {
        "references": AT,
        "two_covariates_with_interaction": fit(frame, ["X", "Z"], True),
        "one_covariate_with_interaction": fit(frame, ["X"], True),
        "two_covariates_without_interaction": fit(frame, ["X", "Z"], False),
    }


def compare(actual, expected):
    if isinstance(expected, dict):
        assert actual.keys() == expected.keys()
        for key in expected:
            compare(actual[key], expected[key])
    else:
        np.testing.assert_allclose(actual, expected, rtol=2e-8, atol=1e-10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = oracle()
    if args.check:
        compare(result, json.loads((ROOT / "atteso.json").read_text(encoding="utf-8")))
        print("PASS · tre modelli, prove F e stime aggiustate")
    else:
        print(json.dumps(result, indent=2, allow_nan=False))
