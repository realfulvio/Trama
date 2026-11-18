"""Optional diagnostics calculated from the existing PCA fit."""
import numpy as np
import pandas as pd

from . import exploration, pca_retention
from .processing import FieldError

INPUT = "Report transformed data"
VARIABLES = "Variable contributions"
CORRELATIONS = "Variable–component correlations"
CASES = "Observation contributions"
MATRIX = "Report variable matrix"
INPUT_SHEET = "Transformed data"
MATRIX_SHEET = "Variable matrix"
OPTIONS = dict.fromkeys((INPUT, VARIABLES, CORRELATIONS, CASES, MATRIX), False)
TABS = {"PCA reports": tuple(OPTIONS)}
LABEL_KEYS = {
    "PCA reports": "pca.reports.tab",
    INPUT: "pca.reports.input",
    VARIABLES: "pca.reports.variables",
    CORRELATIONS: "pca.reports.correlations",
    CASES: "pca.reports.cases",
    MATRIX: "pca.reports.matrix",
}


def _identified_table(data, columns, field, identities):
    table = pd.DataFrame(data, columns=columns)
    while field in table:
        field += " (index)"
    table.insert(0, field, identities)
    return table


def optional_tables(frame, options, parts, eigenvectors, scores, retention):
    enabled = set()
    for field in OPTIONS:
        value = options.get(field, False)
        if not isinstance(value, (bool, np.bool_)):
            raise FieldError(field, f"{field} must be on or off.")
        if value:
            enabled.add(field)
    if not enabled:
        return {}

    tables = {}
    columns = list(eigenvectors.index)
    names = list(eigenvectors.columns)
    selected = retention.tables.get(pca_retention.SELECTION_SHEET)
    if selected is not None:
        names = [name for name, retain in zip(names, selected["Retained"]) if retain]
    eigenvalues = parts.loc[names, "Eigenvalue"].to_numpy()
    alive = eigenvalues > parts["Eigenvalue"].max() * 1e-10

    if enabled & {INPUT, CORRELATIONS, MATRIX}:
        transformed, scales, rows = exploration.pca_input(frame, columns, options["Standardize"])
    if INPUT in enabled:
        tables[INPUT_SHEET] = _identified_table(transformed, columns, "Source row", rows.to_numpy())
    if VARIABLES in enabled:
        contribution = eigenvectors[names].to_numpy() ** 2
        contribution[:, ~alive] = np.nan
        tables[VARIABLES] = _identified_table(contribution, names, "Variable", columns)
    if CORRELATIONS in enabled:
        correlations = eigenvectors[names].to_numpy() * np.sqrt(eigenvalues)
        if not options["Standardize"]:
            correlations /= scales[:, None]
        correlations = np.clip(correlations, -1.0, 1.0)
        correlations[:, ~alive] = np.nan
        tables[CORRELATIONS] = _identified_table(correlations, names, "Variable", columns)
    if CASES in enabled:
        contribution = np.full((len(scores), len(names)), np.nan)
        active_scores = scores[names].to_numpy()[:, alive]
        relative = active_scores / np.max(np.abs(active_scores), axis=0)
        squared = relative ** 2
        contribution[:, alive] = squared / np.sum(squared, axis=0)
        tables[CASES] = _identified_table(contribution, names, "Source row", scores.index.to_numpy())
    if MATRIX in enabled:
        scaled = transformed / np.sqrt(len(transformed) - 1)
        matrix = scaled.T @ scaled
        tables[MATRIX_SHEET] = _identified_table(matrix, columns, "Variable", columns)
    return tables
