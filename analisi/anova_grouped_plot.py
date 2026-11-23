"""Observed replicates from a multifactor ANOVA, grouped by the saved primary factor."""

import pandas as pd

from . import extract_rearrange as rearrange
from .category_graphs import SYMBOLS, category_graph

METHOD = "ANOVA grouped observations"
TABLE = "Grouped observations"
PRIMARY = "Grouped plot factor"
RESPONSE_LABEL = "Response label"


def observations(data, factors, primary):
    """Make the worksheet from exactly the rows used to fit the model."""
    series = f"factor{factors.index(primary)}"
    row_factors = [f"factor{index}" for index, name in enumerate(factors) if name != primary]
    rows = list(data.loc[:, row_factors].itertuples(index=False, name=None))
    levels = sorted(set(rows))
    codes = {row: index for index, row in enumerate(levels)}
    grouped = pd.DataFrame({"Observed": data["response"].to_numpy(), "Series": data[series].to_numpy(),
                            "Row": [codes[row] for row in rows]})
    result = rearrange.extract_rearrange(grouped, {
        rearrange.OUTPUT: "Grouped", rearrange.RESPONSE: "Observed",
        rearrange.ROW_FACTOR: "Row", rearrange.COLUMN_FACTOR: "Series",
    })
    table = result.tables[rearrange.EXTRACT_TABLE]
    labels = [", ".join(row) for row in levels]
    if len(set(labels)) != len(labels):
        labels = [repr(row) for row in levels]
    table["Row title"] = pd.array([labels[int(index)] for index in table["Row title"]], dtype="string")
    return table


def graph(frame, options):
    y = [name for columns in frame.attrs.get("worksheet_roles", {}).get("y", []) for name in columns]
    result = category_graph(frame, {
        "Variables": y, "Row titles": "Row title", "Graph style": SYMBOLS, "Overlay observations": True,
    }, grouped=True)
    if response := options.get(RESPONSE_LABEL):
        result.figure.axes[0].set_ylabel(str(response), parse_math=False)
    return result
