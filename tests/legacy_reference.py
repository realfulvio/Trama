"""Compare recalculated results with local examples in supported legacy formats.

Pass the directory with the extracted .prismt files. The examples are external
test inputs and are not distributed with Trama.
"""
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from analisi import Dataset, factorial_anova, hierarchical, load_tables, nonlinear, survival, t_test
from analisi.analysis_chain import result_frame
from analisi.exploration import bland_altman, roc
from analisi.legacy_fit_graph import FIT_GRAPH, FIT_GRAPH_POINTS
from analisi.legacy_restore import (LEGACY_PREVIEW, LEGACY_TITLE, SAVED_BINARY_GRAPH, SAVED_BINARY_LAYOUT,
                                   SAVED_BINARY_RESULT, SAVED_EDITABLE_GRAPH, SAVED_XY)
from analisi.survival_plot import CI_BARS, PERCENT, SURVIVAL_GRAPH, SURVIVAL_SUMMARY, UNCERTAINTY, UNITS
from analisi.workbench import analyse


def read_example(directory, name):
    path = directory / (name + ".prismt")
    with ZipFile(path) as archive:
        result_names = [item for item in archive.namelist() if item.endswith("/results.json")]
        if len(result_names) != 1:
            raise AssertionError(f"Expected one analysis in {name}")
        reference = json.loads(archive.read(result_names[0]))["content"]
    return next(iter(load_tables(path).values())), reference


def verify(directory):
    data, ref = read_example(directory, "MVPairedttest")
    fit = t_test(data, "Blood_Pressure", "Treatment", "paired", "Patient_ID", order=("Drug_B", "Drug_A"))
    paired = ref["pairedTTestModel"]["pairedTTest"]
    np.testing.assert_allclose([abs(fit["t"]), fit["df"], fit["p"]],
                               [abs(paired["t"]), paired["df"], paired["pValue"]["value"]], rtol=1e-10)
    print("PASS paired t-test (t magnitude, df, p)")

    data, ref = read_example(directory, "MVMultifactorANOVA")
    fit = factorial_anova(data, "Height (cm)", ["Fertilizer", "Light", "Water"], 3)
    for term in ref["ordinaryModel"]["anovaTable"]["fixedEffects"]:
        np.testing.assert_allclose(fit.loc[":".join(part.strip() for part in term["name"].split(":")), ["SS", "df", "F", "p"]].to_numpy(),
                                   [term["ss"], term["df"], term["fTest"]["f"],
                                    term["fTest"]["pValue"]["value"]], rtol=1e-9)
    print("PASS three-factor ANOVA (all seven terms)")

    if (directory / "MVEffectSizesforANOVA.prismt").is_file():
        verify_anova_effect_sizes(directory)

    data, ref = read_example(directory, "MVSimplesurvivalKaplanMeieranalysis")
    curves, test = survival(data, "Time (days)", "Event", "Treatment")
    logrank = ref["curveComparison"]["logrankMantelCoxTest"]
    np.testing.assert_allclose([test["Log-rank χ²"], test["df"], test["p"]],
                               [logrank["chiSquared"], logrank["df"], logrank["pValue"]["value"]], rtol=1e-9)
    for series in ref["dataSummary"].values():
        label = series["id"]["var"]["factorList"][0]["value"]
        expected = series["value"]
        curve = curves[label]
        np.testing.assert_equal(curve["Events"].sum(), expected["eventCount"])
        np.testing.assert_equal(curve["Censored"].sum(), expected["censoredCount"])
        np.testing.assert_allclose(curve.loc[curve["Survival"] <= .5, "Time"].iloc[0],
                                   expected["medianSurvival"], rtol=1e-10)
    assert len(data) == 135
    result = analyse("Kaplan–Meier survival", data, {
        "Time": "Time (days)", "Event columns": ["Event"], "Grouping variables": ["Treatment"],
        "Gehan–Breslow–Wilcoxon": True, "Log-rank trend": True,
        "Trend group order": ["Vehicle", "Drug_B", "Drug_A"],
    }).tables
    for title, statistic, key in [
        ("Gehan–Breslow–Wilcoxon test", "Gehan–Breslow–Wilcoxon χ²", "gehanBreslowWilcoxonTest"),
        ("Log-rank trend", "Trend χ²", "logrankTestForTrend"),
    ]:
        reference = ref["curveComparison"][key]
        np.testing.assert_allclose(result[title].loc[[statistic, "df", "p"], "Value"].to_numpy(dtype=float),
                                   [reference["chiSquared"], reference["df"], reference["pValue"]["value"]],
                                   rtol=1e-10)
    for series in ref["dataSummary"].values():
        label = series["id"]["var"]["factorList"][0]["value"]
        interval = series["value"]["medianSurvivalCI"]
        np.testing.assert_allclose(result["Survival summary"].loc[label, ["Median CI lower", "Median CI upper"]],
                                   [interval["lower"], interval["upper"]], rtol=1e-10)
    print("PASS Kaplan–Meier (135 subjects, medians and CIs, event/censor counts, log-rank, GBW and ordered trend)")

    tables = load_tables(directory / "MVSimplesurvivalKaplanMeieranalysis.prismt", restore_legacy=True)
    source = next(frame for frame in tables.values() if "Treatment" in frame)
    method, options = next((method, options) for method, options in Dataset(source).analyses
                           if method == "Kaplan–Meier survival")
    assert options[UNITS] == PERCENT and options[UNCERTAINTY] == CI_BARS
    result = analyse(method, source, options)
    saved = next(frame for name, frame in tables.items() if name.endswith(" · Survival proportions"))
    verified, intervals = 0, 0
    for name in result.tables:
        if not name.startswith("Curve: "):
            continue
        group = name.removeprefix("Curve: ")
        curve = result.tables[name].set_index("Time")
        curve.loc[0, "Survival (%)"] = 100.0
        center_key, plus_key, minus_key = (f"{group} [{side}]" for side in ("Center", "Plus", "Minus"))
        rows = saved.dropna(subset=[center_key])
        expected = curve.loc[rows["Time (days)"], "Survival (%)"].to_numpy(dtype=float)
        np.testing.assert_allclose(expected, rows[center_key], rtol=1e-9, atol=1e-10)
        inside = rows.dropna(subset=[minus_key, plus_key])
        bounds = curve.loc[inside["Time (days)"], ["CI 95% low", "CI 95% high"]].to_numpy(dtype=float)
        np.testing.assert_allclose(bounds[:, 0], inside[center_key] - inside[minus_key], rtol=1e-9, atol=1e-10)
        np.testing.assert_allclose(bounds[:, 1], inside[center_key] + inside[plus_key], rtol=1e-9, atol=1e-10)
        verified += len(rows)
        intervals += len(inside)
    assert verified == 129 and intervals == 99
    print(f"PASS Kaplan–Meier presentation ({verified} stored percentages and {intervals} archived pointwise intervals)")

    verify_linked_survival_graph(Dataset(source), result)

    data, ref = read_example(directory, "MVSimpleNonlinearRegression")
    fits = nonlinear(data, "Drug Concentration", "Response", "Normalized inhibition", "Inhibitor")
    for model in ref["models"].values():
        label = model["id"]["var"]["factorList"][0]["value"]
        expected = model["value"]
        ic50 = next(iter(expected["parameters"]["IC50"].values()))["value"]["estimate"]
        hill = next(iter(expected["parameters"]["HillSlope"].values()))["value"]["estimate"]
        ss = next(iter(expected["goodnessOfFit"]["ss"].values()))["value"]
        actual = fits[label]
        np.testing.assert_allclose([*actual.parameters["Estimate"], actual.residual_ss],
                                   [ic50, -hill, ss], rtol=2e-6)
    print("PASS normalized inhibition (three groups, IC50, slope magnitude, residual SS)")

    data, ref = read_example(directory, "HierarchicalClusteringCities")
    fit = hierarchical(data, ["Longitude", "Latitude"], 5, standardize=True)
    expected = ref["rows"]["dendrogram"]
    np.testing.assert_allclose(fit.tree[:, 2], [merge["distance"] for merge in expected], rtol=1e-10)
    for merge, observed in zip(expected, fit.tree, strict=True):
        assert set(observed[:2]) == {merge["node1"]["id"], merge["node2"]["id"]}
    print("PASS hierarchical clustering (42 merge distances and node pairs)")


def verify_anova_effect_sizes(directory):
    name = "MVEffectSizesforANOVA"
    _, stored = read_example(directory, name)
    tables = load_tables(directory / (name + ".prismt"), restore_legacy=True)
    source = Dataset(next(iter(tables.values())))
    method, options = next((name, values) for name, values in source.analyses if name == "Multifactor ANOVA")
    assert options["Effect sizes"] is True
    result = analyse(method, source.frame(mask_excluded=True), options).tables["Effect sizes"]
    terms = stored["ordinaryModel"]["anovaTable"]["fixedEffects"]
    observed_terms = [":".join(part.strip() for part in term["name"].split(":")) for term in terms]
    assert set(result.index) == set(observed_terms)
    columns = ["Partial eta squared", "Cohen f", "% total variation"]
    for term, label in zip(terms, observed_terms, strict=True):
        expected = [term["partialEta2"], term["CohenF"], 100 * term["variation"]]
        np.testing.assert_allclose(result.loc[label, columns].to_numpy(dtype=float), expected, rtol=1e-10)
    print(f"PASS ANOVA effect sizes ({len(terms)} saved terms with partial eta squared, Cohen f and variation)")


def verify_legacy(directory):
    data = next(iter(load_tables(directory / "BlandAltmanmethodcomparison.pzfx").values()))
    result, _ = bland_altman(data, "MF", "SV")
    # Published rounded values for the Bland–Altman bias and agreement limits.
    np.testing.assert_equal(round(result["Bias"], 2), .24)
    np.testing.assert_equal(round(result["Lower agreement limit"], 1), -13.4)
    np.testing.assert_equal(round(result["Upper agreement limit"], 1), 13.9)
    print("PASS Bland–Altman (published bias and limits)")

    data = next(iter(load_tables(directory / "ROCcurve.pzfx").values()))
    result, _ = roc(data, "Controls", "Patients", "Automatic")
    controls, patients = data["Controls"].dropna().to_numpy(), data["Patients"].dropna().to_numpy()
    empirical = ((patients[:, None] > controls) + .5 * (patients[:, None] == controls)).mean()
    np.testing.assert_allclose(result["AUC"], empirical, rtol=1e-12)
    np.testing.assert_equal([len(controls), len(patients)], [45, 55])
    print("PASS ROC (legacy decimal-comma example checked against pairwise ranks)")


def verify_mixed_global(directory):
    sample = directory / "OnewayANOVARepeatedmeasures.pzfx"
    data = next(iter(load_tables(sample).values()))
    options = {"Input format": "Wide repeated measures", "Subject": "Row title",
               "Measurement columns": data.columns[1:].tolist(), "Post-hoc": "Holm"}
    result = analyse("Mixed-effects model (REML)", data, options)
    effect = result.tables["Fixed effects"].loc["Condition"]
    np.testing.assert_allclose(effect[["F", "F df1", "F df2"]].astype(float), [3.6184336406, 3, 12], rtol=1e-6)
    np.testing.assert_equal(round(float(effect["p"]), 4), .0455)

    partial = data.copy()
    partial.iloc[0, 2] = np.nan
    fitted = analyse("Mixed-effects model (REML)", partial, options)
    model = fitted.tables["Model"].iloc[0]
    np.testing.assert_equal([model["Subjects used"], model["Subjects partial"], model["Observations used"]], [5, 1, 19])
    print("PASS mixed-effects REML (published balanced F and p, retained partially observed subject)")

    sample = directory / "DoseresponseEC50shiftbyglobalfitting.pzfx"
    data = next(iter(load_tables(sample).values()))
    opts = {"Input format": "Wide XY", "X": "log(agonist)", "Y columns": data.columns[1:].tolist(),
            "Model": "Stimulation (variable slope)", "X values": "Log10 concentrations",
            "Shared parameters": ["Bottom", "Top", "Hill slope"], "Compare local parameters": ["EC50"],
            "Parameter intervals": "Profile likelihood"}
    fit = analyse("Global nonlinear regression", data, opts)
    values = fit.tables["Parameters"]
    shared = values[values["Scope"] == "Shared"].set_index("Parameter")
    ec50 = values[values["Parameter"] == "EC50"].set_index("Group")
    np.testing.assert_allclose(shared.loc[["Bottom", "Top", "Hill slope"], "Estimate"],
                               [395.4, 1388, 1.099], rtol=5e-4)
    np.testing.assert_allclose(ec50.loc[["Control", "Treated"], "Estimate"],
                               [4.960e-7, 3.719e-6], rtol=5e-4)
    np.testing.assert_allclose(ec50.loc[["Control", "Treated"], ["CI 95% low", "CI 95% high"]],
                               [[2.360e-7, 1.052e-6], [1.943e-6, 6.638e-6]], rtol=3e-3)
    np.testing.assert_allclose(shared.loc[["Bottom", "Top", "Hill slope"], ["CI 95% low", "CI 95% high"]],
                               [[214.9, 511.7], [1263, 1594], [.6052, 1.910]], rtol=3e-3)
    report = fit.tables["Joint fit"]["Value"]
    np.testing.assert_allclose([report["Residual SS"], report["df"]], [364947, 23], rtol=5e-5)
    comparison = fit.tables["Selected parameter comparison"]["Value"]
    np.testing.assert_allclose([comparison["F"], comparison["df numerator"], comparison["df denominator"]],
                               [33.57, 1, 23], rtol=2e-4)
    print("PASS global EC50 shift (published estimates, profile intervals, RSS, df and nested F)")


def verify_import(directory):
    source = next(iter(load_tables(directory / "MVCreatedVariablesfromIntableFormulas.prismt").values()))
    dataset = Dataset(source)
    assert set(dataset.formulas) == {"ΔCt", "Mean Control ΔCt", "ΔΔCt", "Fold Change"}
    delta = source["Target_Gene_Ct"] - source["Reference_Gene_Ct"]
    np.testing.assert_allclose(source["Fold Change"], 2 ** (4.398 - delta), rtol=1e-12)
    dataset.raw.loc[0, "Target_Gene_Ct"] += 1
    np.testing.assert_allclose(dataset.frame()["Fold Change"].iloc[0], source["Fold Change"].iloc[0] / 2)
    print("PASS Imported formulas (four recipes, dependent values and recalc)")

    tables = load_tables(directory / "Timeline.pzt")
    assert list(tables) == ["Data 1- Column table", "Data 2 - XY table"]
    assert tables["Data 2 - XY table"].shape == (14, 16)
    assert tables["Data 2 - XY table"].iloc[0, 0] == "H1N1- Spanish"
    print("PASS ZIP PZT (two ordered sheets, row labels and numeric columns)")

    data = next(iter(load_tables(directory / "Barsextendingleftandright.pzt").values()))
    assert list(data)[1:3] == ["log IG1 titter [Mean]", "log IG1 titter [SD]"]
    np.testing.assert_allclose(data.iloc[:3, 1], [-3, -2.5, -3.3])
    print("PASS XML PZT (SD subcolumns, decimal commas and row labels)")

    data = next(iter(load_tables(directory / "Enteringmeanwitherrorvalues.xml").values()))
    columns = ["Control [Mean]", "Control [SD]", "Control [N]"]
    np.testing.assert_allclose(data.loc[0, columns].astype(float), [45.9, 6.3, 4])
    assert data["Hours"].tolist() == [0, 6, 12, 24, 48, 72]
    print("PASS wrapped legacy XML (mean, SD, N and time column)")

    data = next(iter(load_tables(directory / "EnteringdatesintotheXcolumn.xml").values()))
    assert data.loc[1, "X"] == 24 and data.loc[1, "X [Date]"] == "6-Aug-2013"
    print("PASS legacy XML advanced X column (numeric offset and original date)")


def verify_binary(directory):
    tables = load_tables(directory / "plos-s1.pzf")
    assert len(tables) == 14
    np.testing.assert_equal(tables["Fibrinogen"]["Saline"].tolist(), [193, 207, 188, 154, 157, 203])
    assert tables["CAT-ETP PPP"].iloc[1].isna().all()
    print("PASS binary PZF (source order, numeric values and cleared cells)")

    tables = load_tables(directory / "plos-s2.pzf")
    assert len(tables) == 16
    grouped = tables["*Platelet Mapping % Agg"]
    assert grouped["Row title"].tolist() == ["ADP", "AA"]
    np.testing.assert_equal(grouped.iloc[0, 1:4].tolist(), [73, 86, 100])
    np.testing.assert_equal(grouped.iloc[1, 1:4].tolist(), [66, 88, 100])
    print("PASS binary PZF (grouped rows and ordered replicates)")

    data = load_tables(directory / "Exponential.pzt")["association data"]
    np.testing.assert_equal(data.iloc[:3, :].to_numpy(dtype=float), [[1, 121], [2, 155], [3, 178]])
    print("PASS binary PZT (XY source data in equation template)")


def verify_binary_views(directory):
    from analisi.legacy_binary_graphs import validate_binary_graph

    tables = load_tables(directory / "plos-s2.pzf", restore_legacy=True)
    saved = tables["Imported result · t test of CAT-Peak PPP:Tabular results"]
    assert saved.attrs["legacy_recipes"][0][0] == SAVED_BINARY_RESULT
    values = {value for value in saved.to_numpy().ravel() if isinstance(value, str)}
    assert "0.0821" in values and "t=2.309 df=4" in values and "-3.886 to 42.29" in values
    print("PASS binary PZF original paired-test table (stored p, statistic and interval strings)")

    source = Dataset(tables["CAT-Peak PPP"])
    method, options = next((method, options) for method, options in source.analyses
                           if method == "Paired t-test (columns)")
    result = analyse(method, source.frame(mask_excluded=True), options).tables["t-test"]["Value"]
    np.testing.assert_allclose([result["N first"], result["t"], result["df"], result["p"]],
                               [5, 2.309067034509449, 4, .08211641061951554], rtol=1e-12)
    print("PASS binary PZF paired-test recipe (complete pairs, signed statistic, df and p)")

    tables = load_tables(directory / "Exponential.pzt", restore_legacy=True)
    graphs = [(title, options) for title, frame in tables.items()
              for method, options in frame.attrs.get("legacy_recipes", []) if method == SAVED_BINARY_GRAPH]
    titles = [options[LEGACY_TITLE] for _, options in graphs]
    assert titles == ["Curve: Nonlin fit of Yo to plateau", "Plateau then one-phase decay", "two phase decay",
                      "dissocation three phases", "Curve:  Association y0 and plateau",
                      "Curve: association starting at x0", "Curve: association two phases",
                      "Theoretical curve of  Association y0 and plateau"], titles
    path_bytes = (directory / "Exponential.pzt").read_bytes()
    for _, options in graphs:
        preview = validate_binary_graph(options[LEGACY_PREVIEW])
        assert preview[40:44] == b" EMF" and preview in path_bytes
    if sys.platform == "win32":
        owner, options = graphs[0]
        image = analyse(SAVED_BINARY_GRAPH, tables[owner], options).figure.axes[0].images[0].get_array()
        assert np.ptp(np.asarray(image, dtype=float)) > 40
    print("PASS binary PZT original graph previews (eight verified embedded vectors in project order)")

    curve = tables["Imported result · Nonlin fit of Yo to plateau:Curve"]
    assert len(curve) == 150
    np.testing.assert_allclose(curve["X"].iloc[[0, -1]].astype(float), [0, 16])
    np.testing.assert_allclose(curve["Y1"].iloc[[0, -1]].astype(float),
                               [253.9163740402304, 97.1541618222991], rtol=1e-12)
    print("PASS binary PZT saved fit coordinates (150 values with stored X sequence)")

    layouts = [(frame, options) for frame in tables.values() for method, options in frame.attrs.get("legacy_recipes", [])
               if method == SAVED_BINARY_LAYOUT]
    assert [options[LEGACY_TITLE] for _, options in layouts] == ["Layout-1", "*Layout-1"]
    for frame, options in layouts:
        assert validate_binary_graph(options[LEGACY_PREVIEW], layout=True) in path_bytes
        if sys.platform == "win32":
            image = analyse(SAVED_BINARY_LAYOUT, frame, options).figure.axes[0].images[0].get_array()
            assert np.ptp(np.asarray(image, dtype=float)) > 40
    print("PASS binary PZT original layouts (both original vectors and page rendering)")

    pzf_layout = directory / "Figure4-S4_final.pzf"
    if pzf_layout.is_file():
        restored = load_tables(pzf_layout, restore_legacy=True)
        frame, options = next((frame, options) for frame in restored.values()
                              for method, options in frame.attrs.get("legacy_recipes", [])
                              if method == SAVED_BINARY_LAYOUT and options[LEGACY_TITLE] == "Figure S4")
        assert validate_binary_graph(options[LEGACY_PREVIEW], layout=True) in pzf_layout.read_bytes()
        if sys.platform == "win32":
            image = analyse(SAVED_BINARY_LAYOUT, frame, options).figure.axes[0].images[0].get_array()
            assert np.ptp(np.asarray(image, dtype=float)) > 40
        print("PASS binary PZF publication layout (original vector page and rendering)")

    if (directory / "Sinewaves.pzt").is_file():
        tables = load_tables(directory / "Sinewaves.pzt", restore_legacy=True)
        curve = tables["Imported result · Sine wave"]
        x, y = curve.to_numpy(dtype=float).T
        np.testing.assert_allclose(x, np.arange(151) / 15, rtol=1e-14)
        np.testing.assert_allclose(y, np.sin(np.pi * x), atol=2e-14)
        print("PASS binary PZT saved generated sine wave (151 points, no populated source table)")

        frame, options = next((frame, options) for frame in tables.values()
                              for method, options in frame.attrs.get("legacy_recipes", [])
                              if method == SAVED_EDITABLE_GRAPH and options[LEGACY_TITLE] == "Sine wave · Editable")
        axes = analyse(SAVED_EDITABLE_GRAPH, frame, options).figure.axes[0]
        line = axes.lines[-1]
        np.testing.assert_allclose(line.get_xdata(), x)
        np.testing.assert_allclose(line.get_ydata(), y)
        assert line.get_color() == "#000000" and line.get_linewidth() == 2
        print("PASS editable binary XY graph (original series, stroke and saved data)")


def verify_linked_survival_graph(source, result):
    graph_method, graph_options = next(
        (name, values) for name, values in source.analyses if name == SAVED_XY and values.get(SURVIVAL_GRAPH) is True
    )
    axes = analyse(graph_method, result_frame(result, SURVIVAL_SUMMARY), graph_options).figure.axes[0]
    assert len(axes.get_legend_handles_labels()[1]) == 3
    assert sum(getattr(item, "has_yerr", False) for item in axes.containers) == 3
    print("PASS linked Kaplan–Meier graph (three editable series and asymmetric confidence bars)")


def verify_restored(directory):
    tables = load_tables(directory / "MVPairedttest.prismt", restore_legacy=True)
    data = Dataset(next(iter(tables.values())))
    method, options = data.analyses[0]
    result = analyse(method, data.frame(mask_excluded=True), options).tables["t-test"]["Value"]
    np.testing.assert_allclose([result["df"], result["p"]], [14, .0112274147289], rtol=1e-9)
    assert any("Tabular results" in title for title in tables)
    print("PASS restored paired test recipe and original results snapshot")

    tables = load_tables(directory / "MVSimpleNonlinearRegression.prismt", restore_legacy=True)
    source = Dataset(next(iter(tables.values())))
    method, options = next((name, values) for name, values in source.analyses if name == "Nonlinear regression")
    fitted = analyse(method, source.frame(mask_excluded=True), options)
    frame = result_frame(fitted, FIT_GRAPH_POINTS)
    method, options = next(
        (name, values) for name, values in source.analyses if name == SAVED_XY and values.get(FIT_GRAPH) is True
    )
    assert frame["Geometry"].value_counts().to_dict() == {"line": 3000, "points": 54}
    saved = next(values for title, values in tables.items() if title.endswith(" · Curve"))
    for series, rows in frame[frame["Geometry"] == "line"].groupby("Series"):
        np.testing.assert_array_equal(rows["X"], saved["Drug Concentration"])
        np.testing.assert_allclose(rows["Y"], saved[series], rtol=2e-6, atol=3e-5)
    axes = analyse(method, frame, options).figure.axes[0]
    assert len(axes.lines) == len(axes.collections) == 3
    np.testing.assert_allclose([axes.lines[0].get_xdata()[0], axes.lines[0].get_xdata()[-1]], [.1, 1000.])
    print("PASS linked nonlinear graph (three fitted arrays verified against the saved points and 54 observations)")

    tables = load_tables(directory / "MVSimplesurvivalKaplanMeieranalysis.prismt", restore_legacy=True)
    source = Dataset(next(iter(tables.values())))
    method, options = next((name, values) for name, values in source.analyses if name == "Kaplan–Meier survival")
    verify_linked_survival_graph(source, analyse(method, source.frame(mask_excluded=True), options))


def verify_mv_processing(directory):
    tables = load_tables(directory / "MVSelectandTransform.prismt", restore_legacy=True)
    source, saved = list(tables.values())
    dataset = Dataset(source)
    (method, options), = dataset.analyses
    assert method == "Select and Transform"
    actual = analyse(method, dataset.frame(mask_excluded=True), options).tables["Selected data"]
    assert actual.shape == (28, 8)
    pd.testing.assert_frame_equal(actual, saved, check_dtype=False, rtol=1e-14)
    print("PASS Select and Transform (28 rows, 8 columns including stored text classifications)")

    tables = load_tables(directory / "MVExtractandRearrange.prismt", restore_legacy=True)
    source, method, options = next((frame, method, options) for frame in tables.values()
                                   for method, options in Dataset(frame).analyses
                                   if method == "Extract and rearrange")
    actual = analyse(method, Dataset(source).frame(mask_excluded=True), options).tables["Rearranged data"]
    saved = tables["Imported result · VO2_max extracted from MV: Extract and Rearrange · Results"]
    assert actual.shape == (3, 13)
    pd.testing.assert_frame_equal(actual.rename(columns={"Row title": "Age_Group"}), saved,
                                  check_dtype=False, check_exact=True)
    print("PASS Extract and rearrange (3 row labels, 12 replicate subcolumns, 36 values)")


def verify_correlation_sample(path):
    data = next(iter(load_tables(path).values())).select_dtypes("number")
    names = data.columns.tolist()
    assert data.shape == (21, 4)
    for method, reference in (("Pearson", pearsonr), ("Spearman", spearmanr)):
        tables = analyse("Correlation matrix", data, {"Variables": names, "Method": method}).tables
        for j, right in enumerate(names):
            for left in names[:j]:
                pairs = data[[left, right]].dropna()
                expected = reference(pairs[left].to_numpy(dtype=float), pairs[right].to_numpy(dtype=float))
                assert tables["Sample sizes"].loc[left, right] == len(pairs)
                np.testing.assert_allclose([tables["Coefficients"].loc[left, right],
                                            tables["P values"].loc[left, right]],
                                           [expected.statistic, expected.pvalue], rtol=1e-12)
    print("PASS correlation matrix (original 21-row worksheet, six pairs per method compared with SciPy)")


def verify_grouped_pzf(path):
    from hashlib import sha256
    from analisi.legacy_binary_graphs import render_binary_graph, validate_binary_graph

    tables = load_tables(path, restore_legacy=True)
    labels = ["Freshmen", "Sophmores", "Juniors", "Seniors"]
    first, two, raw, parts, saved, graphs, *editable = tables.values()
    assert all(frame.attrs["table_format"] == "grouped" for frame in (first, two, raw))
    assert first.columns.tolist() == labels and first.iloc[0].tolist() == [23, 27, 31, 19]
    assert two["Row title"].tolist() == ["First game", "Last game"]
    assert two[labels].to_numpy().tolist() == [[23, 27, 31, 19], [34, 21, 21, 23]]
    assert raw.iloc[0].tolist() == [23, 34, 56, 67]
    assert parts["Row title"].tolist() == labels and parts["Y1"].tolist() == [23, 27, 31, 19]
    assert saved.attrs["legacy_binary_result"]["source_ids"] == [2]
    np.testing.assert_allclose(saved[labels].iloc[0].astype(float), np.array([23, 34, 56, 67]) / 1.8, rtol=1e-6)
    drawings = graphs.attrs["legacy_recipes"]
    assert len(drawings) == 2
    original = path.read_bytes()
    digests = []
    for method, options in drawings:
        assert method == SAVED_BINARY_GRAPH
        preview = options[LEGACY_PREVIEW]
        raw_pdf = validate_binary_graph(preview)
        assert raw_pdf in original and preview["format"] == "pdf"
        digests.append(sha256(raw_pdf).hexdigest())
        assert np.ptp(np.asarray(render_binary_graph(preview))) > 40
    assert digests == [
        "74d140b2d05155c2559f0ec0b8d800f117b3a930bebe8b926ca99e4596464693",
        "0ee29cd3dd6b57b2fb15ac9ee70d9b4a62b7b7b6f18055688033a640024008f0",
    ]
    from PIL import ImageChops
    from analisi.grid_data import paste_block
    from analisi.legacy_pdf_stacks import render_pdf_stack
    from analisi.legacy_restore import LEGACY_GRAPH_LINK, LEGACY_GRAPH_STYLE

    assert len(editable) == 2
    for index, (frame, bounds) in enumerate(zip(editable, [(331, 685, 588, 962), (260, 542, 459, 759)], strict=True)):
        dataset = Dataset(frame)
        assert dataset.locked_columns == (0,)
        (method, options), = dataset.analyses
        assert method == SAVED_EDITABLE_GRAPH
        assert options[LEGACY_GRAPH_LINK] == drawings[index][1][LEGACY_GRAPH_LINK]
        style, preview = options[LEGACY_GRAPH_STYLE], options[LEGACY_PREVIEW]
        original_image = render_binary_graph(preview, crop=False)
        exact = render_pdf_stack(dataset.raw, style, preview, crop=False)
        assert ImageChops.difference(exact, original_image).getbbox() is None

        for row, col, cells in [(0, 0, [["New label"]]), (0, 1, [["101"]]), (0, 1, [[""]])]:
            try:
                paste_block(dataset, row, col, cells)
            except ValueError:
                pd.testing.assert_frame_equal(dataset.raw, frame)
            else:
                raise AssertionError("Invalid PDF stack edit was accepted")
        # This small decrease used to increase the highest painted edge because
        # the ideal tick calibration disagrees slightly with PDF rounding.
        if index == 0:
            paste_block(dataset, 0, 4, [["18.99"]])
            reduced = np.asarray(render_pdf_stack(dataset.raw, style, preview, crop=False))
            pixels = np.asarray(original_image)
            assert not (np.all(pixels == 255, axis=2) & np.any(reduced != 255, axis=2)).any()
            paste_block(dataset, 0, 4, [["19"]])
        paste_block(dataset, 0, 1, [["30", "20"]])
        edited = render_pdf_stack(dataset.raw, style, preview, crop=False)
        changed = ImageChops.difference(edited, original_image).getbbox()
        assert changed and all(edge >= limit if i < 2 else edge <= limit
                               for i, (edge, limit) in enumerate(zip(changed, bounds, strict=True))), changed
        assert validate_binary_graph(preview) == validate_binary_graph(drawings[index][1][LEGACY_PREVIEW])
    print("PASS Grouped PZF (4 source tables, 4 saved percentages, 2 exact PDF originals and editable stack views)")


def verify_heat_map_sample(path):
    _, frame = next(iter(load_tables(path).items()))
    names = frame.columns[1:].tolist()
    assert frame.shape == (6, 7)
    options = {"Variables": names, "Show cell values": True}
    result = analyse("Heat map", frame, options)
    matrix = result.tables["Heat map data"]
    assert matrix.index.tolist() == frame["Row title"].tolist()
    assert matrix.columns.tolist() == names
    np.testing.assert_array_equal(matrix.to_numpy(), frame[names].to_numpy(dtype=float))
    mesh, = result.figure.axes[0].collections
    np.testing.assert_array_equal(mesh.get_array(), matrix.to_numpy())
    print("PASS native heat map (36 original Grouped source values and cell positions)")


def verify_row_test_sample(path):
    from scipy.stats import ttest_ind
    from statsmodels.stats.multitest import multipletests
    from analisi.row_tests import ROW_TESTS, default_options

    frame = next(iter(load_tables(path).values()))
    assert frame.shape == (24, 6)
    options = default_options(frame)
    assert options["First replicates"] == frame.columns[:3].tolist()
    assert options["Second replicates"] == frame.columns[3:].tolist()
    report = analyse(ROW_TESTS, frame, options).tables["Row comparisons"]
    expected = ttest_ind(frame.iloc[:, :3].to_numpy(dtype=float),
                         frame.iloc[:, 3:].to_numpy(dtype=float), axis=1, equal_var=False)
    np.testing.assert_allclose(report["Statistic"], expected.statistic, rtol=1e-12)
    np.testing.assert_allclose(report["df"], expected.df, rtol=1e-12)
    np.testing.assert_allclose(report["p"], expected.pvalue, rtol=1e-12)
    np.testing.assert_allclose(report["Adjusted p"], multipletests(expected.pvalue, method="holm-sidak")[1], rtol=1e-12)
    print("PASS multiple row tests (24 original worksheet rows, Welch and Holm–Šídák checked independently)")


def verify_nested_samples(t_path, anova_path, csv_path):
    from scipy.stats import f_oneway
    from statsmodels.regression.mixed_linear_model import MixedLM

    from analisi.nested import NESTED_ANOVA, NESTED_T

    source = pd.read_csv(csv_path, skipinitialspace=True)
    design = pd.get_dummies(source["Condition"].astype(str), dtype=float)
    groups = source["Condition"].astype(str) + ":" + source["Room"].astype(str)
    reference = MixedLM(source["Inductive"], design, groups=groups).fit(reml=True, method="powell", ftol=1e-13)
    assert reference.converged
    frame = next(iter(load_tables(t_path).values()))
    assert frame.attrs["table_format"].casefold() == "nested"
    result = analyse(NESTED_T, frame, {}).tables
    assert result["Subcolumns"]["N"].tolist() == [4, 6, 5, 3, 5, 6]
    np.testing.assert_allclose(result["Treatment means"]["Estimate"], reference.fe_params, rtol=5e-7)
    np.testing.assert_allclose(result["Variance components"]["Variance"],
                               [reference.cov_re.iat[0, 0], reference.scale], rtol=5e-7)
    effect = result["Difference of means"].iloc[0]
    np.testing.assert_allclose([effect["df"], effect["p"]], [3.98821196895, 0.148125274149], rtol=1e-7)
    print("PASS nested t test (29 original observations, REML estimates checked against statsmodels)")

    frame = next(iter(load_tables(anova_path).values()))
    means = frame.mean(axis=0).to_numpy(dtype=float).reshape(3, 3)
    reference = f_oneway(*means)
    result = analyse(NESTED_ANOVA, frame, {"Post-hoc": "Holm"}).tables
    test = result["Fixed effect"].loc["Treatment"]
    np.testing.assert_allclose([test["F"], test["F df2"], test["p"]],
                               [reference.statistic, 6, reference.pvalue], rtol=1e-7)
    assert len(result["Multiple comparisons"]) == 3
    print("PASS nested one-way ANOVA (36 original observations, verified against ANOVA of subcolumn means)")


def verify_fraction_sample(path):
    from scipy.stats import binomtest, poisson
    from analisi.processing import WILSON_BROWN

    frame = next(iter(load_tables(path).values()))
    title, count = frame.columns.tolist()
    observed = frame[count].to_numpy(dtype=float)
    assert observed.tolist() == [23, 29, 7, 2, 0]
    tables = analyse("Fraction of total", frame, {"Variables": [count], "Row titles": title,
                     "Divide by": "Column total", "Confidence interval": WILSON_BROWN,
                     "Confidence level (%)": 95.}).tables
    np.testing.assert_allclose(tables["Fraction of column total"][count], observed / 61, rtol=1e-12)
    limits = tables["Lower 95% limit"][count], tables["Upper 95% limit"][count]
    np.testing.assert_allclose([limits[0].iat[0], limits[1].iat[0]], binomtest(23, 61).proportion_ci(method="wilson"))
    assert abs(poisson.cdf(1, limits[0].iat[3] * 61) - .95) < 1e-12
    assert limits[0].iat[4] == 0
    print("PASS Fraction of total (five original grade counts, Wilson and Poisson interval checks)")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
    if len(sys.argv) > 2:
        verify_legacy(Path(sys.argv[2]))
    if len(sys.argv) > 3:
        verify_mixed_global(Path(sys.argv[3]))
    if len(sys.argv) > 4:
        verify_import(Path(sys.argv[4]))
    if len(sys.argv) > 5:
        verify_binary(Path(sys.argv[5]))
        verify_binary_views(Path(sys.argv[5]))
        verify_restored(Path(sys.argv[1]))
    if len(sys.argv) > 6:
        verify_mv_processing(Path(sys.argv[6]))
    if len(sys.argv) > 7:
        verify_correlation_sample(Path(sys.argv[7]))
    if len(sys.argv) > 8:
        verify_grouped_pzf(Path(sys.argv[8]))
    if len(sys.argv) > 9:
        verify_heat_map_sample(Path(sys.argv[9]))
    if len(sys.argv) > 10:
        verify_row_test_sample(Path(sys.argv[10]))
    if len(sys.argv) > 13:
        verify_nested_samples(*(Path(path) for path in sys.argv[11:14]))
    if len(sys.argv) > 14:
        verify_fraction_sample(Path(sys.argv[14]))
