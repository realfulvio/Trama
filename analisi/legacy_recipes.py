"""Translate the verified subset of ZIP project analysis settings to native recipes."""
import tokenize

import numpy as np
from pandas.api.types import is_numeric_dtype

from . import anova_diagnostics as diag, result_display, ttest_options
from .anova_terms import MODEL_TERMS, SELECTED, TERM_SELECTION, active_factors, canonical_terms, full_terms
from .replicate_fit import MERGE_REPLICATES, replicate_groups
from .stats import GEOMETRIC_REPORT, SUMMARY_CONFIDENCE, SUMMARY_FORMAT, SUMMARY_SUM, summary_confidence
from .survival_input import (CENSOR_CODE, EVENT_CODE, OTHER_STATUS, STATUS_POLICIES, recode_statuses,
                             PAIRWISE_CORRECTION, PAIRWISE_CONTROL, PAIRWISE_ADJUSTED, PAIRWISE_ALPHA)
from .survival_plot import CI_BARS, FINAL, PERCENT, MARKERS, UNCERTAINTY, UNITS


def _column(frame, ref, *, wrapped=True):
    uid = ref["col"]["uid"] if wrapped else ref["uid"]
    names = frame.attrs["legacy_columns"][uid]
    if not isinstance(names, (tuple, list)) or len(names) != 1 or names[0] not in frame:
        raise ValueError("The selected imported variable does not map to one native column.")
    return names[0]


def _roles(frame, references, minimum=1, maximum=None):
    if not isinstance(references, list) or not minimum <= len(references) <= (maximum or minimum):
        raise ValueError("Unsupported number of analysis variables.")
    roles = [_column(frame, ref) for ref in references]
    if len(roles) != len(set(roles)):
        raise ValueError("Repeated analysis variable.")
    return roles


def _hierarchical(frame, content, _results):
    data, calc, clusters = (content[key] for key in ("data", "calc", "defineClusters"))
    direction, axes = {"ROWS": ("Rows", ("rows",)), "COLUMNS": ("Columns", ("columns",)),
                       "ROWS_COLUMNS": ("Rows and columns", ("rows", "columns"))}[data["inputType"]]
    variables = _roles(frame, data["variables"], 1, len(frame.columns))
    label = data["label"]
    if label["type"] not in {"VARIABLE", "NONE"}:
        return None
    scales = {"STANDARDIZE": "Standardize", "NONE": "None", "CENTER": "Center"}
    options = {
        "Variables": variables, "Direction": direction,
        "Observation labels": _column(frame, label["variable"]) if label["type"] == "VARIABLE" else None,
        "Standardize": calc["columnTransform"] == "STANDARDIZE",
        "Scale columns": scales[calc["columnTransform"]], "Scale rows": scales[calc["rowTransform"]],
        "Linkage": {"GROUP_AVERAGE": "average", "COMPLETE": "complete"}[calc["linkage"]],
        "Distance": {"EUCLIDIAN": "euclidean"}[calc["distance"]["type"]],
        "Legacy import notes": "Recalculates the saved clustering directions, scales, cuts and supported reports "
                              "with native cluster numbering. Native graph styling is used; additional plots "
                              "and original formatting remain in saved views when available.",
    }
    for axis, prefix, count_field, maximum in (("rows", "Row", "Clusters", len(frame)),
                                              ("columns", "Column", "Column clusters", len(variables))):
        cut = clusters[axis]
        if axis not in axes:
            if cut["method"] != "NONE":
                return None
            continue
        options[f"{prefix} cut"] = {"NONE": "No cut", "NUMBER_OF_CLUSTERS": "Count"}[cut["method"]]
        if cut["method"] == "NUMBER_OF_CLUSTERS":
            count = cut["clusterCount"]
            if type(count) is not int or not 1 <= count <= maximum:
                return None
            options[count_field] = count
    report = content.get("report", {})
    for saved, native in (("standardizedData", "Scaled data"), ("distanceMatrix", "Distance matrix"),
                          ("mergeMap", "Merge map"),
                          ("copheneticDistanceMatrix", "Cophenetic distances"),
                          ("copheneticCorrelation", "Cophenetic correlation")):
        value = report.get(saved, False)
        if type(value) is not bool:
            return None
        options[native] = value
    full = report.get("outputFullMatrix", True)
    if type(full) is not bool:
        return None
    options["Matrix format"] = "Full" if full else "Lower triangle"
    plots = content.get("graph", {}).get("plots", ["DENDROGRAM"])
    if not isinstance(plots, list) or any(not isinstance(plot, str) for plot in plots):
        return None
    if "ELBOW_PLOT" in plots:
        options["Elbow data"] = True
    if "DENDROGRAM" in plots:
        options["Graph output"] = "Dendrogram"
    elif "HEATMAP" in plots:
        options["Graph output"] = "Heat map"
    elif "ELBOW_PLOT" in plots:
        options["Graph output"] = "Elbow plot"
    else:
        return None
    return "Hierarchical clustering", options


def _factor_indices(references, factors):
    indices = [ref["varIdx"] for ref in references]
    if (any(type(index) is not int or not 0 <= index < len(factors) for index in indices)
            or len(indices) != len(set(indices))):
        raise ValueError("Invalid legacy factor indices.")
    return [factors[index] for index in indices]


def _anova_post_tests(frame, post, response, factors):
    if post["type"] == "NO_TESTS":
        return {}
    tests = post["pairwiseTests"]
    if post["type"] != "PAIRWISE_TESTS" or tests["design"] != "CONTROL_VS_ALL":
        raise ValueError("Unsupported legacy comparison design.")
    controls = tests["ctrlVsAll"]
    comparison = controls["multipleComparisons"]
    if (comparison["type"] != "STATISTICAL" or comparison["statistical"]["test"] != "DUNNET"
            or comparison["statistical"]["options"]["significanceLevel"] != .05
            or type(tests["options"]["swapDirection"]) is not bool
            or type(post["withinAsSingleFamily"]) is not bool):
        raise ValueError("Unsupported legacy comparison correction.")
    between = _factor_indices(post["betweenFactorList"], factors)
    within = _factor_indices(post["withinFactorList"], factors)
    control = controls["controlID"]["var"]
    levels = {_column(frame, ref["var"], wrapped=False): ref["value"] for ref in control["factorList"]}
    if (not between or len(levels) != len(control["factorList"])
            or set(between).intersection(within) or set(between) != set(levels)
            or _column(frame, control["response"], wrapped=False) != response):
        raise ValueError("The saved control does not match the compared factors.")
    if any(not isinstance(value, str) or not value or value.strip() != value
           or (len(between) > 1 and "|" in value) for value in levels.values()):
        raise ValueError("Unsupported control level.")
    return {
        "Cell comparison factors": between, "Within factors (simple effects)": within,
        "Families": "Pooled" if post["withinAsSingleFamily"] else "Separate", "Correction": "Dunnett",
        "Control level(s), separated by |": "|".join(levels[factor] for factor in between),
        "Reverse comparisons": not tests["options"]["swapDirection"],
        "Legacy import notes": "Dunnett adjusted p values and intervals use Trama numerical integration. "
                              "Trama reports signed contrast t statistics.",
    }


def _anova_effect_options(results, term_count):
    """Use a complete saved effect-size report to select the native calculations."""
    if not isinstance(results, dict) or results.get("version") != "0.0.0":
        return {}
    try:
        model = results["content"]["ordinaryModel"]
        terms = model["anovaTable"]["fixedEffects"]
        if model["status"] != "VALID" or not isinstance(terms, list) or len(terms) != term_count:
            return {}
        values = [term[key] for term in terms for key in ("variation", "partialEta2", "CohenF")]
        levels = [term["fTest"]["pValue"]["level"] for term in terms]
    except (KeyError, TypeError):
        return {}
    if any(type(value) not in {int, float} or not 0 <= value < float("inf") for value in values):
        return {}
    if any(type(level) not in {int, float} or not 0 < level < 1 for level in levels) or len(set(levels)) != 1:
        return {}
    return {"Effect sizes": True, "Alpha": levels[0]}


def saved_anova_diagnostics(content):
    """Translate ordinary multifactor ANOVA diagnostic requests from compatible metadata."""
    residuals = content.get("residuals", {})
    checks = residuals.get("diagnostics", {})
    charts = residuals.get("graphs", {})
    graph_flags = {"residualsPlot": diag.GRAPH_RESIDUALS, "homoscedasticityPlot": diag.GRAPH_HOMO,
                   "qqPlot": diag.GRAPH_QQ}
    known = {"diagnostics": ("normalityTests", "heteroscedasticityTests"), "graphs": graph_flags}
    for section, block in residuals.items():
        for key, value in block.items():
            if type(value) is not bool or (value and key not in known.get(section, ())):
                raise ValueError("Unsupported ANOVA residual setting.")
    normality = checks.get("normalityTests", False)
    variance = checks.get("heteroscedasticityTests", False)
    options = {diag.ASSUMPTIONS: True} if normality or variance else {}
    if normality != variance:
        options[diag.TEST_SET] = diag.NORMALITY_TESTS if normality else diag.VARIANCE_TEST
    graphs = [graph for key, graph in graph_flags.items() if charts.get(key)]
    if graphs:
        options[diag.DIAGNOSTICS] = True
    return options, graphs


def _factorial(frame, content, results):
    model, post = content["model"], content["postTests"]
    response = _column(frame, model["response"]["variable"]["id"])
    if model["response"]["definition"] != "":
        return None
    diagnostics, _ = saved_anova_diagnostics(content)
    predictor = model["predictor"]
    variables = predictor["variables"]
    if any(variable["effectType"] != "FIXED" for variable in variables):
        return None
    factors = _roles(frame, [variable["id"] for variable in variables], 1, 8)
    if response in factors:
        return None
    saved_terms = []
    for term in predictor["definition"]:
        term_factors = _factor_indices(term, factors)
        if any(_column(frame, ref["varID"]) != name for ref, name in zip(term, term_factors, strict=True)):
            return None
        saved_terms.append(term_factors)
    if saved_terms.count([]) != 1:
        return None
    terms = canonical_terms([term for term in saved_terms if term], factors)
    # Keep every declared predictor in the model so row eligibility still uses all selected columns.
    if active_factors(factors, terms) != factors:
        return None
    order = len(terms[-1])
    selection = {}
    if terms != full_terms(factors, order):
        selection = {TERM_SELECTION: SELECTED, MODEL_TERMS: [list(term) for term in terms]}
    return "Multifactor ANOVA", {
        "Response": response, "Factors": factors, "Interaction order": order,
        **selection, **diagnostics, **_anova_effect_options(results, len(terms)),
        **_anova_post_tests(frame, post, response, factors),
        **result_display.imported_output(content.get("output")),
    }


def saved_anova_primary_factor(frame, method, parameters, options):
    factors = options.get("Factors", ())
    if method != "Multifactor ANOVA" or len(factors) < 2:
        return None
    try:
        primary = parameters["content"]["graph"]["primaryFactor"]
        index = primary["varIdx"]
        if type(index) is int and 0 <= index < len(factors) and _column(frame, primary["varID"]) == factors[index]:
            return factors[index]
    except (KeyError, TypeError, ValueError):
        pass
    return None


def _paired_t(frame, content, results):
    from .paired_graphs import TTEST_CORRELATION, TTEST_DIFFERENCES, TTEST_ESTIMATION

    design, options = content["variableDesign"], content["options"]
    alpha = options["significanceLevel"]
    if (content["experimentalDesign"] != "PAIRED_T_TEST"
            or options["pValueTailType"] != "P_VALUE_TWO_TAILED"
            or type(alpha) not in (int, float) or not 0 < alpha < 1
            or type(options["swapDirection"]) is not bool):
        return None
    level = 100. - 100. * alpha
    if not 0 < level < 100:
        return None
    responses = _roles(frame, design["responseList"], 1, 2)
    factors = _roles(frame, design["factorList"], 0, 1)
    subject = _column(frame, design["subject"])
    if len({*responses, *factors, subject}) != 3 or len(responses) + len(factors) != 2:
        return None
    samples = results["content"]["descriptiveStatistics"]
    roles = [samples[key]["id"]["var"] for key in ("sample1", "sample2")]
    columns = [_column(frame, role["response"], wrapped=False) for role in roles]
    if factors:
        group, = factors
        response, = responses
        order = []
        for column, role in zip(columns, roles, strict=True):
            group_ref, = role["factorList"]
            if column != response or _column(frame, group_ref["var"], wrapped=False) != group:
                return None
            order.append(group_ref["value"])
        levels = frame[group].dropna().drop_duplicates().tolist()
        by_label = {str(value): value for value in levels}
        order = [by_label[str(value)] for value in order]
        if len(levels) != 2 or len(set(by_label)) != 2 or len(set(order)) != 2:
            return None
        source = {"Response": response, "Group": group, "Group order": order}
    else:
        if set(columns) != set(responses) or any(role.get("factorList", []) != [] for role in roles):
            return None
        source = {ttest_options.INPUT: ttest_options.COLUMNS,
                  ttest_options.FIRST: columns[0], ttest_options.SECOND: columns[1]}
    recipe = {
        "Design": "Paired", **source, "Subject": subject,
        "Legacy import notes": "Recalculates the paired test with the saved sample order and confidence level. "
                              "Trama reports the signed t statistic.",
        **result_display.imported_output(content.get("output")),
    }
    if level != 95.:
        recipe[ttest_options.LEVEL] = level
    if content.get("report", {}).get("effectSizes") is True:
        recipe[ttest_options.DETAILS] = True
    graph = content.get("graph")
    if isinstance(graph, dict):
        for key, option in (("confidenceInterval", TTEST_ESTIMATION), ("differences", TTEST_DIFFERENCES),
                            ("correlation", TTEST_CORRELATION)):
            if graph.get(key) is True:
                recipe[option] = True
    return "t-test", recipe


def _survival_control_options(frame, content, response, group, levels):
    """Translate the saved Holm–Šídák family when the control role resolves exactly."""
    try:
        post = content["postTests"]
        pairwise = post["pairwiseTests"]
        design = pairwise["pairwiseDesign"]
        family = pairwise["multipleComparisons"]
        test = family["statistical"]
        control = design["controlID"]["var"]
        factor, = control["factorList"]
        value = factor["value"]
        alpha = test["options"]["significanceLevel"]
        adjusted = test["report"]["adjustedPValues"]
        if (post["type"] != "PAIRWISE_TESTS" or design["type"] != "CONTROL_VS_ALL"
                or design["selectedPairIDList"] != [] or family["type"] != "STATISTICAL"
                or test["test"] != "HOLM_SIDAK" or type(adjusted) is not bool
                or type(alpha) not in {float, int} or not 0 < alpha < 1
                or _column(frame, control["response"], wrapped=False) != response
                or _column(frame, factor["var"], wrapped=False) != group
                or not isinstance(value, str) or value not in levels or not 2 <= len(levels) <= 12):
            return {}
    except (KeyError, TypeError, ValueError):
        return {}
    return {PAIRWISE_CORRECTION: "Holm–Šídák", PAIRWISE_CONTROL: value,
            PAIRWISE_ADJUSTED: adjusted, PAIRWISE_ALPHA: alpha}


def _survival(frame, content, _results):
    design, data, calc, graph = (content[key] for key in ("variableDesign", "data", "calc", "graph"))
    if (data["treatUndefinedValuesAs"] != "MISSING"
            or calc["tabulate"] != "EVENT" or calc["logrankTestMethod"] != "RECOMMENDED"
            or calc["logrankTest"] is not True
            or type(graph["showNumberAtRiskTable"]) is not bool):
        return None
    time = _column(frame, design["x"])
    events = _roles(frame, design["responseList"], 1, 8)
    groups = _roles(frame, design["factorList"], 0, 4)
    if len({time, *events, *groups}) != 1 + len(events) + len(groups):
        return None
    numeric = all(is_numeric_dtype(frame[event].dtype) for event in events)
    event_key, censor_key = ("eventCode", "censorCode") if numeric else ("eventCodeStr", "censorCodeStr")
    event, censor = data[event_key], data[censor_key]
    if type(event) is not (int if numeric else str) or type(censor) is not type(event):
        return None
    coding = {EVENT_CODE: str(event), CENSOR_CODE: str(censor), OTHER_STATUS: STATUS_POLICIES[1]}
    recoded = recode_statuses(frame, events, coding)
    if any(not recoded[column].notna().any() for column in events):
        return None
    display = {}
    if calc.get("probabilityAs") == "PERCENTAGE":
        display[UNITS] = PERCENT
    if graph.get("showCensoredSubjects") is False:
        display[MARKERS] = FINAL
    level = calc.get("ciLevel")
    if graph.get("errorBars") == "CI" and calc.get("ciMethod") == "ASYMMETRICAL" and (
            type(level) in (int, float) and 0 < level < 100):
        display.update({UNCERTAINTY: CI_BARS, "Confidence level (%)": level})
    if calc.get("gehanBreslowWilcoxonTest") is True:
        display["Gehan–Breslow–Wilcoxon"] = True
    if len(events) == len(groups) == 1:
        group, = groups
        event, = events
        complete = recoded[[time, event, group]].dropna()
        levels = set(complete[group].map(str))
        if calc.get("logrankTestForTrend") is True and calc.get("logrankTestForTrendMethod") == "RECOMMENDED":
            uid = design["factorList"][0]["col"]["uid"]
            order = frame.attrs.get("legacy_category_orders", {}).get(uid, ())
            if len(order) >= 3 and len(order) == len(levels) and set(order) == levels:
                display.update({"Log-rank trend": True, "Trend group order": list(order)})
        display.update(_survival_control_options(frame, content, event, group, levels))
    return "Kaplan–Meier survival", {
        "Time": time, "Event columns": events, "Grouping variables": groups,
        PAIRWISE_CORRECTION: "None", **coding, **display, "Show risk table below graph": graph["showNumberAtRiskTable"],
        "Legacy import notes": "Recalculates survival probabilities, risk counts, and the overall log-rank test. "
                              "Supported saved curve options are applied to the native graph. "
                              "Imported post-tests and comparison tables use saved views when available.",
        **result_display.imported_output(content.get("output")),
    }


def _nonlinear(frame, content, _results):
    from . import parameter_intervals, regression_range as rr
    from .legacy_fit_graph import saved_curve_range

    design, data, model, method = (content[key] for key in ("variableDesign", "data", "model", "method"))
    equation = model["equation"]
    if ("".join(equation["definition"].split()) != "Y=100/(1+(IC50/X)^HillSlope)"
            or equation["parameters"] != ["IC50", "HillSlope"]
            or model["constraints"] != {"IC50": {"type": "GREATER", "value": 0.0}}
            or data["handleReplicatesAs"] != "INDIVIDUAL"
            or method["fittingMethod"] != "LS" or method["outliers"]["method"] != "DO_NOT_HANDLE"
            or method["weighting"]["type"] != "NO_WEIGHTING"
            or content["interpolation"]["enabled"] is not False
            or content["modelComparison"]["type"] != "NO_COMPARISON"):
        return None
    if (set(model["initialValues"]) != {"IC50", "HillSlope"}
            or any(initial["isAuto"] is not True
                   for values in model["initialValues"].values() for initial in values)
            or any(initial["value"] >= 0 for initial in model["initialValues"]["HillSlope"])):
        return None
    x = _column(frame, design["x"])
    responses = _roles(frame, design["responseList"], 1, 8)
    groups = _roles(frame, design["factorList"], 0, 4)
    if len({x, *responses, *groups}) != 1 + len(responses) + len(groups):
        return None
    options = {
        "X": x, "Y columns": responses, "Grouping variables": groups,
        "Model": "Normalized inhibition (variable slope)", "Weighting": "Unweighted",
        "Legacy import notes": "Recalculates the inhibitory fit with a negative Hill slope. "
                              "Trama uses symmetric intervals and its own curve rendering. "
                              "Imported profile intervals and transformed parameters use saved views when available.",
        **result_display.imported_output(content.get("output")),
    }
    for edge, field in (("minX", rr.FIT_MIN), ("maxX", rr.FIT_MAX)):
        endpoint = data["range"][edge]
        enabled = endpoint["enabled"]
        if type(enabled) is not bool:
            return None
        if enabled:
            value = endpoint["value"]
            if type(value) not in (int, float) or not np.isfinite(value):
                return None
            options[field] = value
    curve = saved_curve_range({"content": content})
    if curve and (rr.CURVE_MIN in curve or rr.CURVE_MAX in curve):
        options.update(curve)
    rr.normalize(options)
    confidence = content.get("confidence")
    if isinstance(confidence, dict):
        level = confidence.get("confidenceLevel")
        if (confidence.get("calcCI") is True and confidence.get("ciMethod") == "PROFILE_LIKELIHOOD"
                and type(level) in (int, float) and 0 < level < 100):
            options.update({
                parameter_intervals.METHOD: parameter_intervals.PROFILE,
                parameter_intervals.LEVEL: float(level),
                "Legacy import notes": "Recalculates the inhibitory fit with a negative Hill slope "
                                      "and the saved profile confidence level. Transformed parameters "
                                      "use saved views when available.",
            })
            transforms = equation.get("transforms")
            if isinstance(transforms, list) and {
                "name": "logIC50", "definition": "log(IC50)", "ciMethod": "ASYMMETRICAL",
            } in transforms:
                options[parameter_intervals.REPORT_LOG_IC50] = True
                options["Legacy import notes"] = (
                    "Recalculates the inhibitory fit with a negative Hill slope, the saved profile "
                    "confidence level and log10(IC50)."
                )
    return "Nonlinear regression", options



def restore_log_dose_fit(sheet, parameters, frame):
    """Fit the verified log-dose equation to an imported transformed XY view."""
    from .parameter_intervals import LEVEL, METHOD, PROFILE

    content = parameters["content"]
    data, model, method = (content[key] for key in ("data", "model", "method"))
    equation, confidence = model["equation"], content["confidence"]
    names = ("Bottom", "Top", "LogEC50", "HillSlope")
    if (sheet["isAllDataAnalyzed"] is not True or parameters["analysisClass"] != "NONLINEAR_REGRESSION"
            or parameters["version"] != "0.0.0" or frame.attrs["legacy_y_format"] not in ("y_single", "y_replicates")
            or "".join(equation["definition"].split()) != "Y=Bottom+(Top-Bottom)/(1+10^((LogEC50-X)*HillSlope))"
            or equation["parameters"] != list(names) or model["constraints"] != {}
            or data["handleReplicatesAs"] != "INDIVIDUAL"
            or any(data["range"][endpoint]["enabled"] is not False for endpoint in ("minX", "maxX"))
            or method["fittingMethod"] != "LS" or method["outliers"]["method"] != "DO_NOT_HANDLE"
            or method["weighting"]["type"] != "NO_WEIGHTING"
            or content["interpolation"]["enabled"] is not False
            or content["modelComparison"]["type"] != "NO_COMPARISON"
            or confidence["calcCI"] is not True or confidence["ciMethod"] != "PROFILE_LIKELIHOOD"):
        return None
    selected = [series["uid"] for series in sheet["inputDataSets"]]
    if not selected or len(selected) != len(set(selected)) or selected != frame.attrs["legacy_y"]:
        return None
    initial = model["initialValues"]
    if (set(initial) != set(names) or any(
        [record["dataSet"]["col"]["uid"] for record in initial[name]] != selected
        or any(record["isAuto"] is not True for record in initial[name]) for name in names
    ) or any(record["value"] <= 0 for record in initial["HillSlope"])):
        return None
    level = confidence["confidenceLevel"]
    if type(level) not in (int, float) or not 0 < level < 100:
        return None
    x = _column(frame, {"uid": frame.attrs["legacy_x"]}, wrapped=False)
    column_groups = [frame.attrs["legacy_columns"][uid] for uid in selected]
    columns = [name for group in column_groups for name in group]
    if not all(is_numeric_dtype(frame[name]) for name in (x, *columns)):
        return None
    options = {
        "X": x, "Y columns": columns, "Grouping variables": [],
        MERGE_REPLICATES: True, "Model": "Stimulation (variable slope, log10 X)", "Weighting": "Unweighted",
        METHOD: PROFILE, LEVEL: float(level),
        "Legacy import notes": "Fits one curve per series using individual replicates and the linked log10 result.",
    }
    return options if replicate_groups(frame, options) == column_groups else None


def _xy_log_transform(frame, content, _results):
    calc = content["calc"]
    standard = calc["standardFunction"]
    x_transform = standard["xTransform"]
    if (content["data"]["handleReplicatesAs"] != "INDIVIDUAL" or calc["transformType"] != "STANDARD"
            or standard["interchangeXY"] is not False or standard["yTransform"]["enabled"] is not False
            or x_transform["enabled"] is not True
            or x_transform != {"enabled": True, "function": "LOG10(X)", "k": "undefined"}
            or frame.attrs["legacy_y_format"] not in {"y_replicates", "y_single"}):
        return None
    x = _column(frame, {"uid": frame.attrs["legacy_x"]}, wrapped=False)
    if is_numeric_dtype(frame[x]):
        return "Transform concentrations (X)", {"X": x, "Logarithm": "Log10"}
    return None


def _select_transform(frame, content, _results):
    from .data import MAX_CELLS
    from .legacy_import import _formula_recipe, _letters
    from .select_transform import (CALCULATED, COMPARISONS, FILTERS, MAX_RULES, SELECT_TRANSFORM, _numeric,
                                   seeded_transform_options)

    filters = content["rowFilters"]
    bounds = filters["range"]
    if not isinstance(bounds, dict) or bounds.keys() != {"from", "to"}:
        return None
    first, last = bounds["from"], bounds["to"]
    if type(first) is not int or type(last) is not int:
        return None
    all_rows = first == last == -1
    if not all_rows and not 1 <= first <= last <= MAX_CELLS:
        return None
    variables = [_column(frame, {"uid": uid}, wrapped=False) for uid in frame.attrs["legacy_y"]]
    letters = {_letters(index): name for index, name in enumerate(variables)}
    conditions = []
    value_filters, column_filters = filters["variableValue"], filters["variableVariable"]
    if (not isinstance(value_filters, list) or not isinstance(column_filters, list)
            or len(value_filters) + len(column_filters) > MAX_RULES):
        return None
    for item in value_filters:
        index, op = item["variableIdx"], item["logic"]
        if type(index) is not int or not 0 <= index < len(variables):
            return None
        column = variables[index]
        if op == "is_not_missing":
            if set(item) - {"variableIdx", "logic", "value"}:
                return None
            conditions.append({"column": column, "operator": "Is not missing", "target": "Number", "value": ""})
            continue
        value = item["value"]
        op = "!=" if op == "<>" else op
        if (set(item) != {"variableIdx", "logic", "value"} or op not in COMPARISONS
                or type(value) not in {int, float} or not np.isfinite(value)):
            return None
        conditions.append({"column": column, "operator": op, "target": "Number", "value": str(value)})
    for item in column_filters:
        left, right, op = item["variable1Idx"], item["variable2Idx"], item["logic"]
        op = "!=" if op == "<>" else op
        if (set(item) != {"variable1Idx", "variable2Idx", "logic"} or op not in COMPARISONS
                or any(type(index) is not int or not 0 <= index < len(variables) for index in (left, right))):
            return None
        left, right = variables[left], variables[right]
        if not (_numeric(frame[left]) and _numeric(frame[right])):
            return None
        conditions.append({"column": left, "operator": op, "target": "Column", "value": right})

    transforms = content["transforms"]
    if not isinstance(transforms, list) or len(transforms) > len(variables) + MAX_RULES:
        return None
    columns, calculated = [], []
    names = set(variables)
    for item in transforms:
        if item["enabled"] is False:
            continue
        if item["enabled"] is not True or item["parameter"] != "undefined":
            return None
        title, definition = item["title"], item["definition"]
        if not isinstance(title, str) or not isinstance(definition, str) or not 1 <= len(title) <= 160:
            return None
        if definition.strip() in letters and letters[definition.strip()] == title:
            if calculated or title in columns:
                return None
            columns.append(title)
            continue
        if title in names or title.strip() != title or len(calculated) >= MAX_RULES:
            return None
        try:
            expression, _ = _formula_recipe(definition, letters, allow_sampling=True)
        except (ValueError, tokenize.TokenError):
            return None
        calculated.append({"name": title, "expression": expression})
        names.add(title)
    if not columns and not calculated:
        return None
    options = {"Variables": columns, FILTERS: conditions, CALCULATED: calculated}
    if not all_rows:
        # The saved endpoints are one-based and inclusive, as in the native editor.
        options.update({"First row": first, "Last row": last})
    seeded = seeded_transform_options(options)
    if seeded is not options:
        seeded["Legacy import notes"] = ("The live transform uses a new reproducible random sample. "
                                       "Saved result views contain the original recorded values.")
    return SELECT_TRANSFORM, seeded



def _extract_rearrange(frame, content, _results):
    from . import extract_rearrange as extract

    format_name = content["resultTableFormat"]
    format_title = {"XY": "XY", "COLUMN": "Column", "GROUPED": "Grouped", "CONTINGENCY": "Contingency"}[format_name]
    prefix, complete = content["includeVarNamePrefix"], content["reportCompleteRowsOnly"]
    if type(prefix) is not bool or type(complete) is not bool:
        return None
    if not isinstance(content["dataArrangement"], dict):
        return None
    arrangement = content["dataArrangement"].copy()
    fields = {
        "XY": {extract.X: "xVariable", extract.RESPONSE: "yVariable", extract.GROUP: "groupingVariable"},
        "COLUMN": {extract.RESPONSE: "responseVariable", extract.GROUP: "columnFactorVariable"},
        "GROUPED": {extract.RESPONSE: "responseVariable", extract.ROW_FACTOR: "rowFactorVariable",
                    extract.COLUMN_FACTOR: "columnFactorVariable"},
        "CONTINGENCY": {extract.TREATMENT: "rowVariable", extract.OUTCOME: "columnVariable",
                        extract.COUNT: "countVariable"},
    }[format_name]
    if format_name != "CONTINGENCY":
        mode_key = "subjectType" if format_name == "XY" else "columnSubjectType"
        subject_mode = arrangement.pop(mode_key, "NO")
        if subject_mode == "VARIABLE":
            if arrangement.get("subjectVariable") is None:
                return None
            fields[extract.SUBJECT] = "subjectVariable"
        elif subject_mode != "NO" or arrangement.pop("subjectVariable", None) is not None:
            return None

    titles = content["rowTitles"]
    options = {extract.OUTPUT: format_title, extract.PREFIX: prefix, extract.COMPLETE: complete}
    if titles != {"type": "NO", "variable": None}:
        if (format_title not in {"XY", "Column"} or not isinstance(titles, dict)
                or set(titles) != {"type", "variable"}
                or titles["type"] != "VARIABLE"):
            return None
        options[extract.TITLES] = _column(frame, titles["variable"])
    for field, key in fields.items():
        reference = arrangement.pop(key, None)
        if reference is not None or field not in extract.EXTRACT_OPTIONAL_FIELDS:
            options[field] = _column(frame, reference)
    return None if arrangement else (extract.EXTRACT_REARRANGE, options)


def _column_statistics(frame, content, _results):
    """Recreate the geometric column report only when its requested outputs are supported."""
    calc = content["calc"]
    descriptive = calc["descriptiveStatistics"]
    enabled = {"geometricMean", "geometricMeanCI"}
    disabled = {"mean", "meanCI", "coefficientOfVariation", "skewnessAndKurtosis",
                "minMaxRange", "median", "medianCI", "percentiles"}
    if (content["data"] != {"handleReplicatesAs": "AVERAGE"}
            or set(calc) != {"descriptiveStatistics", "normalityTests", "oneSampleTests"}
            or set(descriptive) != enabled | disabled | {"sum"}
            or any(descriptive[key] is not True for key in enabled)
            or any(descriptive[key] is not False for key in disabled)
            or type(descriptive["sum"]) is not bool):
        return None
    normality = calc["normalityTests"]
    one_sample = calc["oneSampleTests"]
    if (set(normality) != {"dAgostinoPearson", "shaproWilks", "kolmogorovSmirnov"}
            or any(value is not False for value in normality.values())
            or set(one_sample) != {"parametric", "nonparametric", "hypotheticalValue", "usePrattMethod"}
            or one_sample["parametric"] is not False or one_sample["nonparametric"] is not False):
        return None
    columns = _roles(frame, [{"col": {"uid": uid}} for uid in frame.attrs["legacy_y"]], 1, 256)
    level = summary_confidence({SUMMARY_CONFIDENCE: content["options"]["confidenceLevel"]})
    return "Descriptive statistics", {"Variables": columns, SUMMARY_FORMAT: GEOMETRIC_REPORT,
                                      SUMMARY_CONFIDENCE: level, SUMMARY_SUM: descriptive["sum"]}


def _grouped_anova(frame, content, _results):
    from .grouped_anova import COLUMN_NAME, INTERACTION, METHOD, ROW_NAME, ROWS

    if frame.attrs.get("legacy_y_format") != "y_replicates" or frame.attrs.get("legacy_x") is not None:
        return None
    residuals = content["residuals"]
    report = content["report"]
    names = content["factorNames"]
    interaction = content["options"]["includeInteractionTerm"]
    if (content["experimentalDesign"] != "ORDINARY_ANOVA" or type(interaction) is not bool
            or content["postTests"]["type"] != "NO_TESTS"
            or any(flag is not False for block in residuals.values() for flag in block.values())
            or any(flag is not False for flag in report.values())):
        return None
    row, column = names["rowFactor"], names["colFactor"]
    if (any(not isinstance(name, str) or not name.strip() or name.strip() != name
            or len(name) > 160 or name == "Residual" for name in (row, column)) or row == column):
        return None
    return METHOD, {ROWS: "Row title", ROW_NAME: row, COLUMN_NAME: column, INTERACTION: interaction}


def _kmeans(frame, content, results):
    from . import kmeans_archive, kmeans_options as selection, kmeans_reports
    from .advanced import _check_scan_budget, gap_replicate_limit
    from .cluster_consensus import KL_SCALING, UNSCALED_WSS

    calc = content["calc"]
    algorithm = {"HARTIGAN_WONG": selection.HARTIGAN, "MACQUEEN": selection.MACQUEEN,
                 "LLOYD_FORGY": selection.FORGY_LLOYD}.get(calc["algorithm"])
    scale = {"STANDARDIZE": selection.STANDARDIZED, "CENTER": selection.CENTERED,
             "NONE": selection.UNSCALED}.get(calc["transform"])
    if (algorithm is None or scale is None
            or calc["distance"]["type"] != "EUCLIDIAN" or calc["clusterMetrics"] is not True):
        return None
    variables = _roles(frame, content["data"]["variables"], 1, len(frame.columns))
    if not all(is_numeric_dtype(frame[name]) for name in variables):
        return None
    limits, seed = calc["clusterCount"], calc["randomSeed"]["value"]
    low, high, iterations = limits["min"], limits["max"], calc["maxIterCount"]
    if (any(type(value) is not int for value in (low, high, iterations, seed))
            or not 1 <= low <= high <= 30 or not 1 <= iterations <= 1000 or not 0 <= seed < 2**63):
        return None
    values = frame[variables].dropna().to_numpy(dtype=float)
    count, dimensions = values.shape
    if (not 2 <= count <= 3000 or not np.isfinite(values).all()
            or (scale == selection.STANDARDIZED and (values == values[0]).all(axis=0).any())):
        return None
    upper = min(high, len(np.unique(values, axis=0)))
    if low > upper:
        return None
    candidates = range(low, upper + 1)
    gap_replicates = gap_replicate_limit(count, dimensions, candidates)
    if gap_replicates < 20:
        return None
    _check_scan_budget(count, dimensions, candidates, upper >= 2,
                       simulate_gap=True, gap_replicates=gap_replicates)
    saved_reports = content.get("report", {})
    reports = {kmeans_reports.ASSIGNMENTS: True}
    for saved, native in (("clusterDetails", kmeans_reports.DETAILS), ("transformedData", kmeans_reports.SCALED),
                          ("distances", kmeans_reports.DISTANCES), ("initialCentroids", kmeans_reports.CENTROIDS),
                          ("anovaTable", kmeans_reports.ANOVA)):
        flag = saved_reports.get(saved, False)
        if type(flag) is not bool:
            return None
        if flag:
            reports[native] = True
    saved_graphs = content.get("graph", {})
    for saved, native in (("elbowPlot", selection.WSS_PLOT), ("silhouettePlot", selection.SILHOUETTE_PLOT),
                          ("gapPlot", selection.GAP_PLOT)):
        flag = saved_graphs.get(saved, False)
        if type(flag) is not bool:
            return None
        if flag:
            reports[native] = True
    if reports.get(selection.GAP_PLOT):
        reports[kmeans_reports.GAP] = True
    options = {
        "Variables": variables, "Minimum k": low, "Maximum k": high, selection.SCALE: scale, "Seed": seed,
        "Criterion": "Consensus (17 indices)", "Gap simulations": gap_replicates, KL_SCALING: UNSCALED_WSS,
        selection.GAP_REFERENCE: selection.GAP_PRINCIPAL_AXES,
        selection.ALGORITHM: algorithm, selection.ITERATION_FIELDS[algorithm]: iterations, **reports,
        "Legacy import notes": (
            f"Recalculates the saved {algorithm} settings with Trama initial centers and "
            f"{gap_replicates} Gap simulations along principal components. "
            "Recreates enabled WSS, silhouette and Gap plots with native formatting. "
            "Saved partitions, tables and plots remain in archived views where available."
        ),
    }
    archive = kmeans_archive.restore(frame, options, results)
    if archive is not None:
        options[kmeans_archive.ARCHIVE] = archive
        options["Legacy import notes"] = (
            "Uses the saved K-means partitions and Gap statistics while worksheet values and fitting settings match. "
            "Recalculates with Trama after a change. See the Selection sheet for the source of the result."
        )
    return selection.SELECTION, options


def _pca(frame, content, _results):
    from . import pca_reports, pca_retention
    from .pca_graphs import COLOR_GROUPS, GRAPH, SCORES

    data, calc, report, graph = (content[key] for key in ("data", "calc", "report", "graph"))
    if (calc["transform"] != "STANDARDIZE_DATA" or calc["method"] != "PARALLEL_ANALYSIS"
            or calc["regression"]["run"] is not False or graph["scorePlot"] is not True
            or any(graph[key] is not False for key in ("loadingPlot", "biPlot", "screePlot", "varianceProportionPlot"))):
        return None
    variables = _roles(frame, data["variables"], 2, pca_retention.MAX_VARIABLES)
    if not all(is_numeric_dtype(frame[name]) for name in variables):
        return None
    parallel = calc["parallelAnalysis"]
    count, seed, level = (parallel[key] for key in ("simulationCount", "randomSeed", "percentileLevel"))
    if (type(count) is not int or not pca_retention.MIN_SIMULATIONS <= count <= pca_retention.MAX_SIMULATIONS
            or type(seed) is not int or not 0 <= seed <= pca_retention.MAX_SEED
            or type(level) not in (int, float) or not 0 < level < 100):
        return None
    complete_rows = int(frame[variables].notna().all(axis=1).sum())
    if complete_rows < 2 or complete_rows * len(variables) * count > pca_retention.BUDGET:
        return None
    graph_variables = graph["variables"]
    if any(graph_variables[key]["use"] is not False for key in ("labels", "symbolSize", "connectingLine")):
        return None
    color = graph_variables["symbolColor"]
    if type(color["use"]) is not bool:
        return None
    group = _column(frame, color["variable"]) if color["use"] else None
    if group in variables:
        return None
    options = {
        "Variables": variables, "Standardize": True, GRAPH: SCORES, COLOR_GROUPS: group,
        pca_retention.SELECTION: pca_retention.PARALLEL, pca_retention.SIMULATIONS: count,
        pca_retention.SEED: seed, pca_retention.PERCENTILE: level,
        "Legacy import notes": (
            "Recalculates standardized PCA and the saved color grouping. Trama draws the graph "
            "with native formatting and generates its own random samples from the saved seed. "
            "Archived results remain available."
        ),
    }
    for saved, native in (("transformedData", pca_reports.INPUT),
                          ("variablesContributionMatrix", pca_reports.VARIABLES),
                          ("variablesComponentsCorrelationMatrix", pca_reports.CORRELATIONS),
                          ("casesContributionMatrix", pca_reports.CASES),
                          ("variablesCorrelationMatrix", pca_reports.MATRIX)):
        value = report.get(saved, False)
        if type(value) is not bool:
            return None
        options[native] = value
    return "Principal component analysis", options


_RECIPES = {
    "COLUMN_STATISTICS": ("0.0.0", _column_statistics),
    "K_MEANS_CLUSTERING": ("0.0.0", _kmeans),
    "PCA": ("0.0.0", _pca),
    "EXTRACT_REARRANGE": ("0.0.1", _extract_rearrange),
    "TWO_WAY_ANOVA": ("0.0.1", _grouped_anova),
    "SELECT_TRANSFORM": ("0.0.2", _select_transform),
    "TRNSFORM": ("0.0.0", _xy_log_transform),
    "HIERARCHICAL_CLUSTERING": ("0.0.0", _hierarchical),
    "MULTI_FACTOR_ANOVA": ("0.0.0", _factorial),
    "T_TESTS_AND_NONPARAMETRIC": ("0.0.1", _paired_t),
    "SURVIVAL": ("0.0.2", _survival),
    "NONLINEAR_REGRESSION": ("0.0.0", _nonlinear),
}


def restore_recipe(sheet, parameters, sources, results=None):
    """Return (source UID, method, options) when verified settings can be recalculated."""
    try:
        kind = sheet["analysisClass"]
        version, convert = _RECIPES[kind]
        if (parameters["analysisClass"] != kind or parameters["version"] != version
                or sheet["isAllDataAnalyzed"] is not True):
            return None
        source, = sheet["inputSheets"]
        uid = source["uid"]
        frame = sources[uid]
        regular = frame.attrs.get("table_format") == "multivariable"
        cached = kind == "PCA" and frame.attrs.get("legacy_snapshot_source_format") == "multivariable"
        grouped = kind == "TWO_WAY_ANOVA" and frame.attrs.get("legacy_snapshot_source_format") == "grouped"
        if kind == "TRNSFORM":
            selected = [dataset["uid"] for dataset in sheet["inputDataSets"]]
            if frame.attrs.get("table_format") != "xy" or selected != frame.attrs["legacy_y"] or not selected:
                return None
        elif kind == "COLUMN_STATISTICS":
            selected = [dataset["uid"] for dataset in sheet["inputDataSets"]]
            if (frame.attrs.get("table_format") != "column" or frame.attrs.get("legacy_y_format") != "y_single"
                    or frame.attrs.get("legacy_x") is not None or not selected or selected != frame.attrs["legacy_y"]):
                return None
        elif not (regular or cached or grouped):
            return None
        recipe = convert(frame, parameters["content"], results)
    except (KeyError, TypeError, ValueError, AttributeError):
        # The metadata is optional. Keep cached results for unrecognized settings.
        return None
    return (uid, *recipe) if recipe is not None else None
