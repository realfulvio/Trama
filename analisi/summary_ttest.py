"""Two-sided independent t tests from sufficient statistics, without pseudo-data."""
import math

import numpy as np
import pandas as pd
from scipy import stats

from .processing import FieldError
from .reporting import Result, _plot
from .summary_anova import (OPTIONS as SUMMARY_OPTIONS, ROWS, SUBCOLUMNS,
                            check_options as read_summaries, _number, _restore)

METHOD = "Unpaired t-test from summaries"
OPTIONS = {key: SUMMARY_OPTIONS[key] for key in ("Input", "Group", "Mean", "Dispersion", "Sample size",
           "Variables", "Summary row", "Dispersion type", "Confidence level (%)")}
OPTIONS.update({"Design": ("Welch", "Student"), "Null difference": 0.})


def check_options(frame, options):
    design = options.get("Design", "Welch")
    if design not in ("Welch", "Student"):
        raise FieldError("Design", "Choose Welch or Student for independent groups.")
    null = _number(options.get("Null difference", 0.), "Null difference")
    # Only reuse the input parser, never an ANOVA fit or a post-hoc calculation.
    # Pin its analysis choices so future summary-ANOVA options cannot affect this test.
    try:
        used, omitted, level, _ = read_summaries(frame, {**options, "Method": "Ordinary", "Post-hoc": "None"})
    except FieldError as error:
        if str(error) == "ANOVA requires positive pooled residual variance.":
            raise FieldError(error.field, "At least one group must have a positive SD for a t-test.") from None
        if str(error) == "Provide between 2 and 30 complete groups.":
            raise FieldError(error.field, "Provide exactly two complete independent groups.") from None
        raise
    if len(used) != 2:
        raise FieldError("Variables" if options.get("Input", ROWS) == SUBCOLUMNS else "Mean",
                         "Provide exactly two complete independent groups.")
    return used, omitted, level, design, null


def summary_ttest(frame, options):
    used, omitted, level, design, null = check_options(frame, options)
    means, sds, sizes = (used[key].to_numpy(dtype=float) for key in ("Mean", "SD", "N"))
    # Remove the common location before scaling: a large common mean must not
    # erase a small, yet representable SD. Avoid forming an overflowing difference.
    origin = .5*means.min() + .5*means.max()
    shifted = means-origin
    scale = max(float(np.max(abs(shifted))), float(sds.max()), abs(null))
    delta = float(shifted[0]/scale - shifted[1]/scale)
    errors = sds/scale
    if design == "Student":
        df = sum(int(n) for n in used.N)-2
        pooled = math.hypot(errors[0]*math.sqrt((sizes[0]-1)/df),
                            errors[1]*math.sqrt((sizes[1]-1)/df))
        se = pooled*math.hypot(1/math.sqrt(sizes[0]), 1/math.sqrt(sizes[1]))
    else:
        terms = errors/np.sqrt(sizes)
        se = math.hypot(*terms)
        df = 1/sum((float(term)/se)**4/(n-1) for term,n in zip(terms,sizes)) if se else np.nan
    error_field = "Dispersion" if options.get("Input", ROWS) == ROWS else "Variables"
    if not se > 0 or not np.isfinite(df):
        raise FieldError(error_field, "The standard error is outside the supported numeric range.")
    statistic = (delta-null/scale)/se
    if not np.isfinite(statistic):
        raise FieldError(error_field, "The t statistic is outside the supported numeric range.")
    p = float(2*stats.t.sf(abs(statistic),df))
    critical = float(stats.t.isf((1-level/100)/2,df))
    half = critical*se
    original = {"Difference":_restore(delta,scale), "SE":_restore(se,scale),
                "CI lower":_restore(delta-half,scale), "CI upper":_restore(delta+half,scale)}
    unavailable = not np.isfinite(list(original.values())).all()
    note = ("Some quantities are not representable in the original units and are blank; scaled inference is retained."
            if unavailable else "")
    row = {"First":used.Group.iloc[0], "Second":used.Group.iloc[1],
           "First source row":int(used['Source row'].iloc[0]),
           "Second source row":int(used['Source row'].iloc[1]), "Design":design,
           **original, "Null difference":null, "t":statistic, "df":df, "p":p,
           "Confidence level (%)":level, "Significant":p < 1-level/100, "Note":note}
    figure, axes = _plot("Difference between independent means", "First mean − second mean", "")
    if not unavailable:
        # Pass endpoints rather than subtracting rounded bounds from the center.
        axes.plot([original['CI lower'],original['CI upper']],[0,0],color='#24779b',linewidth=2,
                  label=f"{level:g}% two-sided confidence interval")
        axes.plot([original['Difference']],[0],marker='o',color='#24779b',linestyle='None',label='Mean difference')
        axes.axvline(null,color='#697987',linestyle='--',label='Null difference')
        axes.set_yticks([0],[f"{used.Group.iloc[0]} − {used.Group.iloc[1]}"])
        axes.legend(fontsize=8)
    else:
        axes.set_axis_off()
        axes.text(.5,.5,"Original-unit interval cannot be plotted.\nScaled inference is available in the t-test table.",
                  ha='center',va='center',transform=axes.transAxes,wrap=True)
    settings = {"Design":design,"Alternative":"Two-sided", "Direction":"First complete group minus second complete group",
                "Input":options.get("Input",ROWS), "Dispersion type":options.get("Dispersion type","SD"),
                "Confidence level (%)":level,"Null difference":null,"Groups omitted":len(omitted),
                "Total N":sum(int(n) for n in used.N), "Display limits":note or "None",
                "Interpretation":"Independent groups are required. Student assumes common variance; Welch uses separate variances. "
                "Summaries cannot assess normality, pairing or outliers. The interval estimates the mean difference, not future observations."}
    return Result({"t-test":pd.DataFrame([row]),"Summaries used":used,"Omitted groups":omitted,
                   "Settings":pd.DataFrame({"Setting":list(settings),"Value":list(settings.values())})},figure)
