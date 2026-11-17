"""Regression with explicit numeric and categorical predictor roles."""
import warnings

import numpy as np
import pandas as pd
from statsmodels.duration.hazard_regression import PHReg
from statsmodels.genmod.families import Binomial, Poisson
from statsmodels.genmod.generalized_linear_model import GLM
from statsmodels.regression.linear_model import OLS
from statsmodels.tools.sm_exceptions import ConvergenceWarning, PerfectSeparationError, PerfectSeparationWarning

from .processing import FieldError
from .stats import complete

EXPOSURE, DIAGNOSTICS, RESIDUAL_PLOT = "Exposure", "Diagnostics", "Residual plot"
POISSON_DIAGNOSTICS = "Poisson diagnostics"


def _design(data, predictors, categories, intercept):
    columns = {"Intercept": np.ones(len(data))} if intercept else {}
    references = {}
    for label in predictors:
        if label not in categories:
            names, values = [label], [data[label].to_numpy()]
        else:
            series = data[label].astype(str)
            levels = sorted(series.unique())
            if not 2 <= len(levels) <= 100:
                raise ValueError(f'Categorical predictor "{label}" must have 2 to 100 levels.')
            references[label] = levels[0]
            names = [f"{label} [{value}]" for value in levels[1:]]
            values = [(series == value).to_numpy(dtype=float) for value in levels[1:]]
        for name, value in zip(names, values, strict=True):
            if name in columns:
                raise ValueError(f'Duplicate model term "{name}". Rename the source column.')
            columns[name] = value
    design = pd.DataFrame(columns, index=data.index)
    if len(design) <= design.shape[1] or design.size > 2_000_000:
        raise ValueError("Model has too many parameters for these data.")
    if np.linalg.matrix_rank(design.to_numpy()) < design.shape[1]:
        raise ValueError("The model is rank deficient. Remove redundant predictors.")
    return design, references


def _inputs(frame, responses, predictors, categories, intercept):
    if not predictors or not set(categories).issubset(predictors):
        raise ValueError("Choose predictors and identify any categorical predictors from that list.")
    numeric = [*responses, *[col for col in predictors if col not in categories]]
    data = complete(frame, numeric, categories)
    design, references = _design(data, predictors, categories, intercept)
    return data, design, references


def _report(model, design, references, total_rows, exponentiate):
    ci = np.asarray(model.conf_int())
    coeff = pd.DataFrame({"Estimate": np.asarray(model.params), "SE": np.asarray(model.bse),
                          "CI 95% low": ci[:, 0], "CI 95% high": ci[:, 1],
                          "p": np.asarray(model.pvalues)}, index=design.columns)
    if not np.isfinite(coeff.to_numpy()).all():
        raise ValueError("Could not estimate all model coefficients reliably.")
    if exponentiate:
        limits = np.exp(np.asarray(coeff[["Estimate", "CI 95% low", "CI 95% high"]]))
        if not np.isfinite(limits).all():
            raise ValueError("Exponentiated estimates are outside the supported range.")
        coeff[["Exp(estimate)", "Exp CI 95% low", "Exp CI 95% high"]] = limits
    summary = {"N": len(design), "Incomplete rows": total_rows - len(design)}
    for key, label in (("rsquared", "R²"), ("rsquared_adj", "Adjusted R²"),
                       ("llf", "Log likelihood"), ("aic", "AIC")):
        value = getattr(model, key, None)
        if value is not None and np.isfinite(value):
            summary[label] = value
    tables = {"Coefficients": coeff, "Model": pd.DataFrame.from_dict(summary, orient="index", columns=["Value"])}
    if references:
        tables["Reference levels"] = pd.DataFrame.from_dict(references, orient="index", columns=["Reference"])
    return tables


def _check_exposure(frame, exposure, response, predictors):
    """Validate present exposure values before complete cases are selected."""
    if exposure not in frame:
        raise FieldError(EXPOSURE, "Choose an existing column for Exposure.")
    if exposure == response or exposure in predictors:
        raise FieldError(EXPOSURE, "Exposure must be a column distinct from the response and the predictors.")
    raw = frame[exposure]
    values = pd.to_numeric(raw, errors="coerce")
    if np.iscomplexobj(values.to_numpy()):
        raise FieldError(EXPOSURE, f'Exposure column "{exposure}" contains complex data.')
    values = values.to_numpy(dtype=float, na_value=np.nan)
    with np.errstate(invalid="ignore"):
        invalid = raw.notna().to_numpy() & ~(np.isfinite(values) & (values > 0))
    if invalid.any():
        row = int(np.flatnonzero(invalid)[0]) + 1
        raise FieldError(EXPOSURE, f'Exposure column "{exposure}" needs finite values greater than 0 '
                                   f"(row {row}: {raw.iloc[row - 1]!r}).")


def _poisson_diagnostics(model, observed, prediction, exposure):
    """Per-row residuals and goodness-of-fit ratios; they never change the family or the SE."""
    pearson = np.asarray(model.resid_pearson, dtype=float)
    deviance = np.asarray(model.resid_deviance, dtype=float)
    rows = pd.DataFrame({"Source row": observed.index.to_numpy(), "Exposure": exposure,
                         "Fitted rate": prediction / exposure, "Pearson residual": pearson,
                         "Deviance residual": deviance}, index=observed.index)
    df = float(model.df_resid)
    summary = {"Deviance": float(model.deviance), "Pearson χ²": float(model.pearson_chi2), "Residual df": df}
    if not (np.isfinite(rows.to_numpy(dtype=float)).all() and np.isfinite(list(summary.values())).all() and df > 0):
        raise ValueError("Poisson diagnostics are not finite for these data. Check counts near zero fitted values.")
    summary.update({"Deviance / df": summary["Deviance"] / df, "Pearson χ² / df": summary["Pearson χ²"] / df})
    return rows, pd.DataFrame.from_dict(summary, orient="index", columns=["Value"])


def linear_fit(frame, response, predictors, categories):
    """Fit multiple linear regression once.

    The returned tables are the linear branch of :func:`regression`. Diagnostics and
    profile predictions reuse this fit instead of refitting.
    """
    data, design, references = _inputs(frame, [response], predictors, categories, intercept=True)
    observed = data[response]
    try:
        model = OLS(observed, design).fit()
    except np.linalg.LinAlgError as error:
        raise ValueError("Could not estimate the model reliably. Check separation and predictor variance.") from error
    tables = _report(model, design, references, len(frame), False)
    prediction = np.asarray(model.fittedvalues)
    tables["Fitted values"] = pd.DataFrame({"Observed": observed, "Fitted": prediction,
                                            "Residual": observed - prediction})
    return tables, model, design, references, data


def logistic_fit(frame, response, predictors, categories):
    """Fit logistic regression once.

    The returned tables are the logistic branch of :func:`regression`. Diagnostics and
    profile probabilities reuse this fit instead of refitting.
    """
    data, design, references = _inputs(frame, [response], predictors, categories, intercept=True)
    observed = data[response]
    if set(observed.unique()) != {0, 1}:
        raise ValueError("Logistic regression requires both outcomes 0 and 1.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PerfectSeparationWarning)
            model = GLM(observed, design, family=Binomial()).fit(maxiter=100)
            if not model.converged:
                raise ValueError("The regression did not converge.")
    except (PerfectSeparationWarning, PerfectSeparationError, np.linalg.LinAlgError) as error:
        raise ValueError("Could not estimate the model reliably. Check separation and predictor variance.") from error
    tables = _report(model, design, references, len(frame), True)
    prediction = np.asarray(model.fittedvalues)
    tables["Fitted values"] = pd.DataFrame({"Observed": observed, "Fitted": prediction,
                                            "Residual": observed - prediction})
    return tables, model, design, references, data


def regression(frame, response, predictors, categories, method, exposure=None, diagnostics=False):
    """Fit a linear, logistic or Poisson model.

    Poisson accepts an optional exposure column: log(mu) = X b + log(exposure). None means unit exposure.
    """
    if method not in {"Linear", "Logistic", "Poisson"}:
        raise ValueError("Select a regression family.")
    if method != "Poisson" and (exposure is not None or diagnostics):
        raise ValueError("Exposure and Poisson diagnostics apply only to the Poisson family.")
    if method == "Linear":
        tables, *_ = linear_fit(frame, response, predictors, categories)
        return tables
    if method == "Logistic":
        tables, *_ = logistic_fit(frame, response, predictors, categories)
        return tables
    if exposure is not None:
        _check_exposure(frame, exposure, response, predictors)
    data, design, references = _inputs(frame, [response] if exposure is None else [response, exposure],
                                       predictors, categories, intercept=True)
    observed = data[response]
    if ((observed < 0) | (observed % 1 != 0)).any():
        raise FieldError("Response", "Poisson regression requires nonnegative integer counts.")
    if not (observed > 0).any():
        raise FieldError("Response", "Poisson regression needs at least one observed event (a count above 0).")
    exposed = None if exposure is None else data[exposure].to_numpy(dtype=float)
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", PerfectSeparationWarning)
            model = GLM(observed, design, family=Poisson(), exposure=exposed).fit(maxiter=100)
            if not model.converged:
                raise ValueError("The regression did not converge.")
    except (PerfectSeparationWarning, PerfectSeparationError, np.linalg.LinAlgError) as error:
        raise ValueError("Could not estimate the model reliably. Check separation and predictor variance.") from error
    tables = _report(model, design, references, len(frame), True)
    prediction = np.asarray(model.fittedvalues)
    tables["Fitted values"] = pd.DataFrame({"Observed": observed, "Fitted": prediction,
                                            "Residual": observed - prediction})
    if diagnostics:
        unit = np.ones(len(observed)) if exposed is None else exposed
        rows, summary = _poisson_diagnostics(model, observed, prediction, unit)
        tables["Fitted values"] = tables["Fitted values"].join(rows)
        tables[POISSON_DIAGNOSTICS] = summary
    return tables


def cox_regression(frame, time, event, predictors, categories, ties="efron"):
    data, design, references = _inputs(frame, [time, event], predictors, categories, intercept=False)
    if (data[time] < 0).any() or not data[event].isin([0, 1]).all() or data[event].sum() < 2:
        raise ValueError("Cox regression needs nonnegative times, event values 0/1 and at least two events.")
    if ties not in {"breslow", "efron"}:
        raise ValueError("Choose Breslow or Efron ties handling.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", ConvergenceWarning)
            model = PHReg(data[time], design, status=data[event], ties=ties).fit(maxiter=100)
    except (ConvergenceWarning, np.linalg.LinAlgError) as error:
        raise ValueError("The Cox regression did not converge.") from error
    return _report(model, design, references, len(frame), True)
