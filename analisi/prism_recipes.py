"""Translate the verified subset of Prism ZIP analysis settings to native recipes."""
from itertools import combinations
import tokenize

import numpy as np
from pandas.api.types import is_numeric_dtype

from .survival_input import (CENSOR_CODE, EVENT_CODE, OTHER_STATUS, STATUS_POLICIES, recode_statuses,
                             PAIRWISE_CORRECTION, PAIRWISE_CONTROL, PAIRWISE_ADJUSTED, PAIRWISE_ALPHA)
from .survival_plot import BAND, FINAL, PERCENT, MARKERS, UNCERTAINTY, UNITS


def _column(frame, ref, *, wrapped=True):
    uid = ref["col"]["uid"] if wrapped else ref["uid"]
    names = frame.attrs["prism_columns"][uid]
    if not isinstance(names, (tuple, list)) or len(names) != 1 or names[0] not in frame:
        raise ValueError("The selected Prism variable does not map to one native column.")
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
        "Prism import notes": "Recalculates the saved clustering directions, scales, cuts and supported reports "
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
        raise ValueError("Invalid Prism factor indices.")
    return [factors[index] for index in indices]


def _anova_post_tests(frame, post, response, factors):
    if post["type"] == "NO_TESTS":
        return {}
    tests = post["pairwiseTests"]
    if post["type"] != "PAIRWISE_TESTS" or tests["design"] != "CONTROL_VS_ALL":
        raise ValueError("Unsupported Prism comparison design.")
    controls = tests["ctrlVsAll"]
    comparison = controls["multipleComparisons"]
    if (comparison["type"] != "STATISTICAL" or comparison["statistical"]["test"] != "DUNNET"
            or comparison["statistical"]["options"]["significanceLevel"] != .05
            or type(tests["options"]["swapDirection"]) is not bool
            or type(post["withinAsSingleFamily"]) is not bool):
        raise ValueError("Unsupported Prism comparison correction.")
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
        "Prism import notes": "Dunnett adjusted p values and intervals use Trama numerical integration. "
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


def _factorial(frame, content, results):
    model, post = content["model"], content["postTests"]
    response = _column(frame, model["response"]["variable"]["id"])
    if (model["response"]["definition"] != ""
            or any(flag is not False for block in content.get("residuals", {}).values()
                   for flag in block.values())):
        return None
    predictor = model["predictor"]
    variables = predictor["variables"]
    if any(variable["effectType"] != "FIXED" for variable in variables):
        return None
    factors = _roles(frame, [variable["id"] for variable in variables], 1, 8)
    if response in factors:
        return None
    terms = []
    for term in predictor["definition"]:
        term_factors = _factor_indices(term, factors)
        if any(_column(frame, ref["varID"]) != name for ref, name in zip(term, term_factors, strict=True)):
            return None
        terms.append(frozenset(term_factors))
    order = max(map(len, terms), default=0)
    if not 1 <= order <= min(3, len(factors)):
        return None
    expected = {frozenset(term) for size in range(order + 1) for term in combinations(factors, size)}
    if len(terms) != len(expected) or set(terms) != expected:
        return None
    return "Multifactor ANOVA", {
        "Response": response, "Factors": factors, "Interaction order": order,
        **_anova_effect_options(results, len(terms) - 1),
        **_anova_post_tests(frame, post, response, factors),
    }


def _paired_t(frame, content, results):
    design, options = content["variableDesign"], content["options"]
    if (content["experimentalDesign"] != "PAIRED_T_TEST"
            or options["pValueTailType"] != "P_VALUE_TWO_TAILED"
            or options["significanceLevel"] != .05
            or type(options["swapDirection"]) is not bool):
        return None
    response, = _roles(frame, design["responseList"])
    group, = _roles(frame, design["factorList"])
    subject = _column(frame, design["subject"])
    if len({response, group, subject}) != 3:
        return None
    order = []
    samples = results["content"]["descriptiveStatistics"]
    for key in ("sample1", "sample2"):
        roles = samples[key]["id"]["var"]
        group_ref, = roles["factorList"]
        if (_column(frame, roles["response"], wrapped=False) != response
                or _column(frame, group_ref["var"], wrapped=False) != group):
            return None
        order.append(group_ref["value"])
    levels = frame[group].dropna().drop_duplicates().tolist()
    by_label = {str(level): level for level in levels}
    order = [by_label[str(level)] for level in order]
    if len(levels) != 2 or len(set(order)) != 2:
        return None
    return "t-test", {
        "Design": "Paired", "Response": response, "Group": group, "Subject": subject, "Group order": order,
        "Prism import notes": "Recalculates the paired test and mean difference with the saved group order. "
                              "Trama reports the signed t statistic and its native effect-size summary.",
    }


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
        display.update({UNCERTAINTY: BAND, "Confidence level (%)": level})
    if calc.get("gehanBreslowWilcoxonTest") is True:
        display["Gehan–Breslow–Wilcoxon"] = True
    if len(events) == len(groups) == 1:
        group, = groups
        event, = events
        complete = recoded[[time, event, group]].dropna()
        levels = set(complete[group].map(str))
        if calc.get("logrankTestForTrend") is True and calc.get("logrankTestForTrendMethod") == "RECOMMENDED":
            uid = design["factorList"][0]["col"]["uid"]
            order = frame.attrs.get("prism_category_orders", {}).get(uid, ())
            if len(order) >= 3 and len(order) == len(levels) and set(order) == levels:
                display.update({"Log-rank trend": True, "Trend group order": list(order)})
        display.update(_survival_control_options(frame, content, event, group, levels))
    return "Kaplan–Meier survival", {
        "Time": time, "Event columns": events, "Grouping variables": groups,
        PAIRWISE_CORRECTION: "None", **coding, **display, "Show risk table below graph": graph["showNumberAtRiskTable"],
        "Prism import notes": "Recalculates survival probabilities, risk counts, and the overall log-rank test. "
                              "Supported saved curve options are applied to the native graph. "
                              "Prism post-tests and comparison tables use saved views when available.",
    }


def _nonlinear(frame, content, _results):
    from . import parameter_intervals

    design, data, model, method = (content[key] for key in ("variableDesign", "data", "model", "method"))
    equation = model["equation"]
    if ("".join(equation["definition"].split()) != "Y=100/(1+(IC50/X)^HillSlope)"
            or equation["parameters"] != ["IC50", "HillSlope"]
            or model["constraints"] != {"IC50": {"type": "GREATER", "value": 0.0}}
            or data["handleReplicatesAs"] != "INDIVIDUAL"
            or any(data["range"][endpoint]["enabled"] is not False for endpoint in ("minX", "maxX"))
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
        "Prism import notes": "Recalculates the inhibitory fit with a negative Hill slope. "
                              "Trama uses symmetric intervals and its own curve rendering. "
                              "Prism profile intervals and transformed parameters use saved views when available.",
    }
    confidence = content.get("confidence")
    if isinstance(confidence, dict):
        level = confidence.get("confidenceLevel")
        if (confidence.get("calcCI") is True and confidence.get("ciMethod") == "PROFILE_LIKELIHOOD"
                and type(level) in (int, float) and 0 < level < 100):
            options.update({
                parameter_intervals.METHOD: parameter_intervals.PROFILE,
                parameter_intervals.LEVEL: float(level),
                "Prism import notes": "Recalculates the inhibitory fit with a negative Hill slope "
                                      "and the saved profile confidence level. Transformed parameters "
                                      "use saved views when available.",
            })
    return "Nonlinear regression", options



def _select_transform(frame, content, _results):
    from .prism_import import _FORMULA_CALLS, _formula_recipe, _letters
    from .select_transform import CALCULATED, COMPARISONS, FILTERS, MAX_RULES, SELECT_TRANSFORM

    filters = content["rowFilters"]
    if filters["range"] != {"from": -1, "to": -1} or filters["variableVariable"] != []:
        return None
    variables = [_column(frame, {"uid": uid}, wrapped=False) for uid in frame.attrs["prism_y"]]
    letters = {_letters(index): name for index, name in enumerate(variables)}
    conditions = []
    value_filters = filters["variableValue"]
    if not isinstance(value_filters, list) or len(value_filters) > MAX_RULES:
        return None
    for item in value_filters:
        index, op, value = item["variableIdx"], item["logic"], item["value"]
        if (set(item) != {"variableIdx", "logic", "value"} or type(index) is not int
                or not 0 <= index < len(variables) or op not in COMPARISONS
                or type(value) not in {int, float} or not np.isfinite(value)):
            return None
        conditions.append({"column": variables[index], "operator": op, "target": "Number", "value": str(value)})

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
            expression, _ = _formula_recipe(definition, letters, _FORMULA_CALLS | {"IF"})
        except (ValueError, tokenize.TokenError):
            return None
        calculated.append({"name": title, "expression": expression})
        names.add(title)
    if not columns and not calculated:
        return None
    return SELECT_TRANSFORM, {"Variables": columns, FILTERS: conditions, CALCULATED: calculated}



def _extract_rearrange(frame, content, _results):
    from .extract_rearrange import COMPLETE, COLUMN_FACTOR, EXTRACT_REARRANGE, OUTPUT, PREFIX, RESPONSE, ROW_FACTOR

    arrangement = content["dataArrangement"]
    fields = {RESPONSE: "responseVariable", ROW_FACTOR: "rowFactorVariable", COLUMN_FACTOR: "columnFactorVariable"}
    if (content["resultTableFormat"] != "GROUPED" or content["rowTitles"] != {"type": "NO", "variable": None}
            or set(arrangement) != set(fields.values()) or type(content["includeVarNamePrefix"]) is not bool
            or type(content["reportCompleteRowsOnly"]) is not bool):
        return None
    return EXTRACT_REARRANGE, {
        OUTPUT: "Grouped", PREFIX: content["includeVarNamePrefix"], COMPLETE: content["reportCompleteRowsOnly"],
        **{field: _column(frame, arrangement[key]) for field, key in fields.items()},
    }


def _grouped_anova(frame, content, _results):
    from .grouped_anova import COLUMN_NAME, INTERACTION, METHOD, ROW_NAME, ROWS

    if frame.attrs.get("prism_y_format") != "y_replicates" or frame.attrs.get("prism_x") is not None:
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


def _kmeans(frame, content, _results):
    from . import kmeans_options as selection, kmeans_reports
    from .advanced import _check_scan_budget
    from .cluster_consensus import KL_SCALING, UNSCALED_WSS

    calc = content["calc"]
    algorithm = {"HARTIGAN_WONG": selection.HARTIGAN, "MACQUEEN": selection.MACQUEEN}.get(calc["algorithm"])
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
    gap_replicates = 20
    _check_scan_budget(count, dimensions, range(low, upper + 1), upper >= 2,
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
    return selection.SELECTION, {
        "Variables": variables, "Minimum k": low, "Maximum k": high, selection.SCALE: scale, "Seed": seed,
        "Criterion": "Consensus (17 indices)", "Gap simulations": gap_replicates, KL_SCALING: UNSCALED_WSS,
        selection.ALGORITHM: algorithm, selection.ITERATION_FIELDS[algorithm]: iterations, **reports,
        "Prism import notes": (
            f"Recalculates the saved {algorithm} settings with Trama initial centers and 20 Gap simulations. "
            "Recreates enabled WSS, silhouette and Gap plots with native formatting. "
            "Saved partitions, tables and plots remain in archived views where available."
        ),
    }


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
        "Prism import notes": (
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
    "K_MEANS_CLUSTERING": ("0.0.0", _kmeans),
    "PCA": ("0.0.0", _pca),
    "EXTRACT_REARRANGE": ("0.0.1", _extract_rearrange),
    "TWO_WAY_ANOVA": ("0.0.1", _grouped_anova),
    "SELECT_TRANSFORM": ("0.0.2", _select_transform),
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
        cached = kind == "PCA" and frame.attrs.get("prism_snapshot_source_format") == "multivariable"
        grouped = kind == "TWO_WAY_ANOVA" and frame.attrs.get("prism_snapshot_source_format") == "grouped"
        if not (regular or cached or grouped):
            return None
        recipe = convert(frame, parameters["content"], results)
    except (KeyError, TypeError, ValueError, AttributeError):
        # The metadata is optional. Keep cached results for unrecognized settings.
        return None
    return (uid, *recipe) if recipe is not None else None
