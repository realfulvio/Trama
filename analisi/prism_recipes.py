"""Translate the verified subset of Prism ZIP analysis settings to native recipes."""
from itertools import combinations
import tokenize

import numpy as np
from pandas.api.types import is_numeric_dtype

from .survival_input import CENSOR_CODE, EVENT_CODE, OTHER_STATUS, STATUS_POLICIES, recode_statuses
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
    if "DENDROGRAM" in plots:
        options["Graph output"] = "Dendrogram"
    elif "HEATMAP" in plots:
        options["Graph output"] = "Heat map"
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


def _factorial(frame, content, _results):
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
    return "Kaplan–Meier survival", {
        "Time": time, "Event columns": events, "Grouping variables": groups, **coding, **display,
        "Pairwise correction": "None", "Show risk table below graph": graph["showNumberAtRiskTable"],
        "Prism import notes": "Recalculates survival probabilities, risk counts, and the overall log-rank test. "
                              "Supported saved curve options are applied to the native graph. "
                              "Prism post-tests and comparison tables use saved views when available.",
    }


def _nonlinear(frame, content, _results):
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
    return "Nonlinear regression", {
        "X": x, "Y columns": responses, "Grouping variables": groups,
        "Model": "Normalized inhibition (variable slope)", "Weighting": "Unweighted",
        "Prism import notes": "Recalculates the inhibitory fit with a negative Hill slope. "
                              "Trama uses symmetric intervals and its own curve rendering. "
                              "Prism profile intervals and transformed parameters use saved views when available.",
    }



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


_RECIPES = {
    "EXTRACT_REARRANGE": ("0.0.1", _extract_rearrange),
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
        if frame.attrs.get("table_format") != "multivariable":
            return None
        recipe = convert(frame, parameters["content"], results)
    except (KeyError, TypeError, ValueError, AttributeError):
        # The metadata is optional. Keep cached results for unrecognized settings.
        return None
    return (uid, *recipe) if recipe is not None else None
