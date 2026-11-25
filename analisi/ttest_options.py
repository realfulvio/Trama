"""Inputs and inference options for the normal-data t-test."""

from numbers import Real

from .field_error import FieldError


INPUT = "Sample format"
GROUPED, COLUMNS = "One measurement and a group column", "Two measurement columns"
FORMATS = (GROUPED, COLUMNS)
LEVEL = "Confidence level (%)"
ALTERNATIVE = "Alternative for first − second"
TWO_SIDED, GREATER, LESS = "Two-sided", "Difference greater than zero", "Difference less than zero"
SIDES = {TWO_SIDED: "two-sided", GREATER: "greater", LESS: "less"}
REVERSE = "Reverse first and second samples"
DETAILS = "Show paired t-test details"
FIRST, SECOND = "First measurement", "Second measurement"
OPTIONS = {
    INPUT: FORMATS, FIRST: None, SECOND: None, LEVEL: 95., ALTERNATIVE: tuple(SIDES), REVERSE: False, DETAILS: False,
}
LABEL_KEYS = {
    "Design": "ttest.field.design",
    INPUT: "ttest.field.input", FIRST: "ttest.field.first", SECOND: "ttest.field.second",
    LEVEL: "ttest.field.level", ALTERNATIVE: "ttest.field.alternative", REVERSE: "ttest.field.reverse",
    DETAILS: "ttest.field.details",
}
CHOICE_KEYS = {
    GROUPED: "ttest.input.grouped", COLUMNS: "ttest.input.columns",
    TWO_SIDED: "ttest.side.two", GREATER: "ttest.side.greater", LESS: "ttest.side.less",
    "Paired": "ttest.design.paired", "One-sample": "ttest.design.one",
}


def visibility(design, layout):
    pair, one = design == "Paired", design == "One-sample"
    wide = not one and layout == COLUMNS
    return {
        INPUT: not one, "Response": not wide, "Group": not one and not wide, "Subject": pair, "Null mean": one,
        FIRST: wide, SECOND: wide, REVERSE: not one, DETAILS: pair,
    }


def check(options):
    """Validate visible options before launching a calculation."""
    design = options["Design"]
    if design not in ("Welch", "Student", "Paired", "One-sample"):
        raise FieldError("Design", "Choose a t-test design.")
    layout = GROUPED if design == "One-sample" else options.get(INPUT, GROUPED)
    if layout not in FORMATS:
        raise FieldError(INPUT, "Choose a sample format.")
    level = options.get(LEVEL, 95.)
    if isinstance(level, bool) or not isinstance(level, Real) or not 0 < level < 100:
        raise FieldError(LEVEL, "The confidence level must be strictly between 0 and 100.")
    alternative = options.get(ALTERNATIVE, TWO_SIDED)
    if alternative not in tuple(SIDES):
        raise FieldError(ALTERNATIVE, "Choose the direction of the alternative.")
    fields = [FIRST, SECOND] if layout == COLUMNS else ["Response"]
    if layout == GROUPED and design != "One-sample":
        fields.append("Group")
    if design == "Paired":
        fields.append("Subject")
    used = set()
    for field in fields:
        value = options.get(field)
        if not isinstance(value, str) or not value:
            raise FieldError(field, "Choose a column for this field.")
        if value in used:
            raise FieldError(field, "Choose distinct columns for the t-test.")
        used.add(value)
    return layout, float(level), SIDES[alternative]


def preserve_direction(options, frame):
    """Keep the original group orientation for a directed comparison after row reordering."""
    layout, _, alternative = check(options)
    if layout == COLUMNS or options["Design"] == "One-sample":
        return
    if "Group order" in options:
        return
    from .paired_graphs import paired_plot_options

    if alternative == "two-sided" and not options.get(REVERSE) and not paired_plot_options("t-test", options):
        return
    group = options["Group"]
    fields = [options["Response"], group]
    if options["Design"] == "Paired":
        fields.append(options["Subject"])
    if not set(fields).issubset(frame):
        return
    labels = frame[fields].dropna()[group].drop_duplicates().tolist()
    if len(labels) == 2:
        options["Group order"] = labels
