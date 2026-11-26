"""Worksheet formats, samples and frame creation shared by the desktop interfaces."""
from dataclasses import dataclass, replace

import pandas as pd

from .grid_headings import xy_source_roles
from .i18n import tr


@dataclass(frozen=True)
class Template:
    name: str
    kind: str
    detail: str
    columns: tuple
    rows: tuple


TEMPLATES = (
    Template("XY", "xy", "Pair an X value with one or more Y series. Use this for curves and regression.",
             ("X", "Control", "Treatment"), ((0.1, 2.4, 2.1), (1, 4.1, 5.3), (10, 8.2, 11.4), (100, 9.3, 13.2))),
    Template("Column", "column", "Place each group in its own column. Use this for comparisons and distributions.",
             ("Control", "Treatment"), ((12, 19), (15, 24), (11, 18), (16, 26), (14, 21))),
    Template("Grouped", "grouped", "Organize observations by row and column groups, with separate replicate columns.",
             ("Row title", "Control [1]", "Control [2]", "Treatment [1]", "Treatment [2]"),
             (("Week 1", 4.1, 4.4, 5.6, 5.9), ("Week 2", 4.7, 4.9, 7.1, 7.6), ("Week 3", 5.2, 5.5, 8.2, 8.7))),
    Template("Contingency", "contingency", "Enter whole counts for each combination of group and outcome.",
             ("Row title", "Event", "No event"), (("Control", 12, 28), ("Treatment", 5, 35))),
    Template("Survival", "survival", "Record a time, event indicator and group for each subject.",
             ("Time", "Event", "Group"), ((6, 1, "Control"), (8, 1, "Control"), (11, 0, "Control"),
                                          (9, 1, "Treatment"), (12, 0, "Treatment"), (15, 1, "Treatment"))),
    Template("Parts of whole", "parts_of_whole", "Enter one value per category to plot each part as a share of the total.",
             ("Row title", "Count"), (("Category A", 22), ("Category B", 16), ("Category C", 12), ("Category D", 8))),
    Template("Multiple variables", "multivariable", "Record each observation as a row with numeric or categorical variables.",
             ("Subject", "Measurement", "Group"), (("S01", 12.4, "Control"), ("S02", 14.1, "Control"),
                                                   ("S03", 18.3, "Treatment"), ("S04", 20.2, "Treatment"))),
    Template("Nested", "nested", "Give each independent subject or unit its own subcolumn and stack its repeated measurements.",
             ("Control [1]", "Control [2]", "Control [3]", "Treatment [1]", "Treatment [2]", "Treatment [3]"),
             ((4.1, 5.4, 6.0, 7.8, 8.3, 9.1), (3.8, 5.1, 5.8, 7.2, 8.6, 9.5),
              (4.4, 5.7, 6.3, 7.6, 8.1, 9.2), (None, 5.4, None, 7.4, None, 9.3))),
)

XY_FORMATS = {
    "A single Y value for each X": TEMPLATES[0],
    "Replicates in side-by-side subcolumns": Template(
        "XY replicates", "XY with replicates", TEMPLATES[0].detail,
        ("X", "Control [1]", "Control [2]", "Treatment [1]", "Treatment [2]"),
        ((0.1, 2.4, 2.6, 2.1, 2.7), (1, 4.1, 4.5, 5.3, 5.8), (10, 8.2, 8.7, 11.4, 10.8),
         (100, 9.3, 8.9, 13.2, 13.6)),
    ),
    "Precalculated mean, SD and N": Template(
        "XY mean and SD", "XY with precomputed error", TEMPLATES[0].detail,
        ("X", "Control [Mean]", "Control [SD]", "Control [N]", "Treatment [Mean]", "Treatment [SD]", "Treatment [N]"),
        ((0.1, 2.5, 0.2, 3, 2.4, 0.3, 3), (1, 4.3, 0.4, 3, 5.6, 0.5, 3),
         (10, 8.5, 0.5, 3, 11.1, 0.6, 3), (100, 9.1, 0.4, 3, 13.4, 0.4, 3)),
    ),
}

XY_EXAMPLES = (
    ("Curves and regression", "Dose–response with two data sets", "A single Y value for each X"),
    ("Replicates and error bars", "Measure duplicate observations", "Replicates in side-by-side subcolumns"),
    ("Replicates and error bars", "Enter means, SD and sample sizes", "Precalculated mean, SD and N"),
)

def _grouped_summary(name, fields, rows):
    """Reuse the Grouped worksheet with one subcolumn for each entered statistic."""
    columns = ("Row title", *(f"{group} [{field}]" for group in ("Control", "Treated") for field in fields))
    return Template(name, "grouped", TEMPLATES[2].detail, columns, rows)


GROUPED_FORMATS = {
    "Replicates in side-by-side subcolumns": TEMPLATES[2],
    "Mean, SD and N": _grouped_summary("Grouped mean, SD and N", ("Mean", "SD", "N"), (
        ("Week 1", 4.3, .2, 4, 5.8, .3, 4), ("Week 2", 4.8, .3, 4, 7.4, .4, 4), ("Week 3", 5.4, .2, 4, 8.5, .4, 4))),
    "Mean and SEM": _grouped_summary("Grouped mean and SEM", ("Mean", "SEM"), (
        ("Week 1", 4.3, .1, 5.8, .15), ("Week 2", 4.8, .15, 7.4, .2), ("Week 3", 5.4, .1, 8.5, .2))),
    "Mean with minus and plus distances": _grouped_summary(
        "Grouped asymmetric distances", ("Mean", "Minus", "Plus"), (
            ("Week 1", 4.3, .2, .4, 5.8, .3, .5), ("Week 2", 4.8, .3, .2, 7.4, .4, .6),
            ("Week 3", 5.4, .2, .3, 8.5, .5, .4))),
    "Mean with lower and upper limits": _grouped_summary(
        "Grouped asymmetric limits", ("Mean", "Lower", "Upper"), (
            ("Week 1", 4.3, 4.1, 4.7, 5.8, 5.5, 6.3), ("Week 2", 4.8, 4.5, 5., 7.4, 7., 8.),
            ("Week 3", 5.4, 5.2, 5.7, 8.5, 8., 8.9))),
}

# Display keys for the canonical format and example names; choices keep the English names as codes.
FORMAT_KEYS = {
    "A single Y value for each X": "format.xy_single", "Replicates in side-by-side subcolumns": "format.replicates",
    "Precalculated mean, SD and N": "format.xy_mean_sd_n", "Mean, SD and N": "format.mean_sd_n",
    "Mean and SEM": "format.mean_sem", "Mean with minus and plus distances": "format.mean_distances",
    "Mean with lower and upper limits": "format.mean_limits",
}
EXAMPLE_KEYS = {
    "Curves and regression": "example.curves", "Replicates and error bars": "example.replicates",
    "Dose–response with two data sets": "example.dose_response",
    "Measure duplicate observations": "example.duplicates", "Enter means, SD and sample sizes": "example.means",
}
BASE_KINDS = {template.kind for template in TEMPLATES}


def format_label(code):
    """Visible name of a table format; code is the canonical kind or format name."""
    if code in BASE_KINDS:
        return tr(f"table.{code}")
    return tr(FORMAT_KEYS[code]) if code in FORMAT_KEYS else code


def template_detail(template):
    kind = template.kind if template.kind in BASE_KINDS else "xy"
    return tr(f"table_detail.{kind}")


EXAMPLES = {
    "column": "Compare a control and a treated group",
    "grouped": "Repeated measurements by week",
    "contingency": "Treatment and event counts",
    "survival": "Time to event in two groups",
    "parts_of_whole": "Composition of four categories",
    "multivariable": "Subject, measurement and group",
    "nested": "Repeated measurements within independent units",
}


def _blank_xy(template, datasets, replicates, row_titles, *, x_error=False):
    if template.kind == "XY with replicates":
        suffixes = tuple(f" [{index}]" for index in range(1, replicates + 1))
    elif template.kind == "XY with precomputed error":
        suffixes = (" [Mean]", " [SD]", " [N]")
    else:
        suffixes = ("",)
    groups = ("Control", "Treatment", *(f"Series {index}" for index in range(3, datasets + 1)))
    x_columns = ("X", "X [Error]") if x_error else ("X",)
    values = (*x_columns, *(f"{group}{suffix}" for group in groups[:datasets] for suffix in suffixes))
    return replace(template, columns=(("Row title",) if row_titles else ()) + values,
                   rows=((("",) if row_titles else ()) + (0,) * len(values),))


def table_frame(template, sample):
    if sample:
        frame = pd.DataFrame(template.rows, columns=template.columns)
    else:
        frame = pd.DataFrame({
            name: pd.Series(index=range(20), dtype="Float64" if isinstance(value, (int, float)) else "string")
            for name, value in zip(template.columns, template.rows[0], strict=True)
        })
    frame.attrs["table_format"] = template.kind
    roles = xy_source_roles(frame, template.kind)
    if roles and len(roles["x"]) == 2:
        frame.attrs["worksheet_roles"] = roles
    return frame
