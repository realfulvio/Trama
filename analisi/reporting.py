"""Tables and plots returned by workbench analyses."""
from dataclasses import dataclass, field

from matplotlib.figure import Figure
import pandas as pd


@dataclass
class Result:
    tables: dict[str, pd.DataFrame]
    figure: Figure | None = None
    style_warning: str | None = None
    table_contexts: dict[str, object] = field(default_factory=dict, repr=False, compare=False)


def _report(values):
    return pd.DataFrame({"Value": pd.Series(values, dtype=object)})


def _plot(title, x="", y=""):
    figure = Figure(figsize=(8, 5), dpi=100, layout="constrained")
    axes = figure.add_subplot()
    axes.set(title=title, xlabel=x, ylabel=y)
    axes.spines[["right", "top"]].set_visible(False)
    return figure, axes
