"""Exercise each published analysis from the same dispatch used by the GUI."""
import unittest

import numpy as np
import pandas as pd

from analisi.analysis_chain import result_frame
from analisi.hierarchical_workbench import HIERARCHY_GRAPH
from analisi.kmeans_options import SELECTION as KMEANS_SELECTION
from analisi.kmeans_reports import METRIC as KMEANS_METRIC, MODEL_GRAPH as KMEANS_METRIC_GRAPH
from analisi.nested import NESTED_ANOVA, NESTED_T
from analisi.reference_normalization import METHOD as REFERENCE_NORMALIZATION
from analisi.tolerance_intervals import TOLERANCE
from analisi.workbench import GRAPH_METHODS, GROUPS, METHODS, analyse


class CatalogTests(unittest.TestCase):
    def test_every_visible_method_returns_a_result(self):
        x = np.arange(1., 17.)
        data = pd.DataFrame({
            "x": x, "y": 3 * x + np.sin(x), "z": np.cos(x) + 3,
            "Group": ["A"] * 8 + ["B"] * 8,
            "Factor": ["L"] * 4 + ["H"] * 4 + ["L"] * 4 + ["H"] * 4,
            "Subject": np.tile(np.arange(8), 2),
            "Event": np.tile([0, 1, 1, 1], 4),
            "p": x / 24, "Unknown": 3 * x + .75,
        })
        curve = data.assign(fit=1 + 5 * np.exp(-.2 * x) + .02 * np.sin(x),
                            stim=5 + 25 / (1 + (6 / x) ** 1.3) + .05 * np.sin(x))
        curves = pd.DataFrame({"x": x, "a": curve["stim"],
                               "b": 5 + 25 / (1 + (9 / x)**1.3) - .05 * np.sin(x)})
        cases = {
            "One-way ANOVA from summaries": {"Mean": "y", "Dispersion": "z", "Sample size": "x"},
            "Unpaired t-test from summaries": {"Mean": "y", "Dispersion": "z", "Sample size": "x"},
            "Global nonlinear regression": {"Input format": "Wide XY", "X": "x", "Y columns": ["a", "b"],
                                            "Model": "Stimulation (variable slope)",
                                            "Shared parameters": ["Bottom", "Top", "Hill slope"],
                                            "Compare local parameters": ["EC50"]},
            "Mixed-effects model (REML)": {"Y": "y", "Subject": "Subject", "Within factors": ["Group"], "Post-hoc": "Holm"},
            "Descriptive statistics": {"Variables": ["x", "y"]},
            "Normality tests": {"Variables": ["x"]},
            TOLERANCE: {"Variables": ["x", "y"], "Group": "Group", "Distribution": "Normal", "Sides": "Two-sided",
                        "Population coverage (%)": 90., "Confidence level (%)": 95., "Show graph": False},
            "t-test": {"Design": "Paired", "Response": "y", "Group": "Group", "Subject": "Subject"},
            "Paired t-test (columns)": {"First": "x", "Second": "y"},
            "Permutation test for mean difference": {"First": "x", "Second": "z", "Resamples": 199},
            "Lognormal t-test": {"First": "x", "Second": "y", "Design": "Paired", "Report ratio": "First / Second",
                                 "Null ratio": 1., "Hypothetical geometric mean": 1., "Confidence level (%)": 95.,
                                 "Alternative": "Two-sided", "Log base": "10", "Graph": "Ratio estimation",
                                 "Pairing correlation": True},
            "Compare two variances": {"First": "x", "Second": "y", "Confidence level (%)": 95.,
                                      "Distribution": "Normal", "Graph": "None"},
            "Equivalence test (TOST)": {"Design": "Paired", "First": "x", "Second": "y",
                                        "Lower margin": -5., "Upper margin": 25., "Alpha": .05},
            NESTED_T: {}, NESTED_ANOVA: {"Post-hoc": "Holm"},
            "Mann–Whitney": {"Response": "y", "Group": "Group"},
            "Wilcoxon signed-rank": {"First": "x", "Second": "y"},
            "Kruskal–Wallis": {"Response": "y", "Group": "Group"},
            "Correlation": {"X": "x", "Y": "y", "Method": "Pearson"},
            "Correlate against control": {"X": "x", "Variables": ["y", "z"]},
            "Compare independent correlations": {"X": "x", "Y": "y", "Group": "Group"},
            "Repeated-measures correlation": {"Subject": "Subject", "X": "x", "Y": "y", "Show graph": False},
            "Correlation matrix": {"Variables": ["x", "y", "z"]},
            "Contingency table": {"Rows": "Group", "Columns": "Factor"},
            "Paired proportions": {"Input format": "Observations", "Before": "Before", "After": "After",
                                   "Negative value": "off", "Positive value": "on", "Graph": False},
            "Linear regression": {"X": "x", "Y": "y"},
            "Compare regression lines": {"X": "x", "Y": "y", "Group": "Group"},
            "Nonlinear regression": {"X": "x", "Y": "fit", "Model": "One-phase decay"},
            "Compare nonlinear models": {"X": "x", "Y": "stim",
                                        "Nested models": "Stimulation (standard slope) → Stimulation (variable slope)"},
            "Compare models (AICc)": {"X": "x", "Y": "stim", "Models": ["Michaelis–Menten", "Straight line"],
                                      "Show graph": False},
            "Grouped two-way ANOVA": {"Row labels": "Row", "Y columns": ["a [1]", "a [2]", "b [1]", "b [2]"]},
            "Multifactor ANOVA": {"Response": "z", "Factors": ["Group", "Factor"], "Interaction order": 2,
                                 "Compare marginal means by": "Group", "Within factors (simple effects)": ["Factor"]},
            "ANCOVA": {"Response": "y", "Covariate": "x", "Group": "Group", "Slope model": "By group",
                       "Reference X": None, "Reference domain": "Allow extrapolation", "Comparisons": "All pairs",
                       "Adjustment": "Holm", "Confidence level (%)": 95., "Graph": "Fitted lines"},
            "Kaplan–Meier survival": {"Time": "x", "Event": "Event", "Group": "Factor",
                                    "Pairwise correction": "Holm", "Show risk table below graph": True},
            "K-means model selection": {"Variables": ["x", "z"], "Maximum k": 4,
                                        "Standardize": True, "Seed": 42, "Criterion": "Silhouette"},
            "K-means clustering": {"Variables": ["x", "z"], "Clusters": 2, "Standardize": True, "Seed": 42},
            "K-means stability": {"Variables": ["x", "z"], "Maximum k": 3, "Resamples": 10, "Seed": 42},
            "Hierarchical clustering": {"Variables": ["x", "z"], "Clusters": 2, "Standardize": True,
                                        "Linkage": "average", "Distance": "euclidean"},
            HIERARCHY_GRAPH: {"Graph output": "Heat map"},
            "Scatter / confidence ellipse": {"X": "x", "Y": "z", "Group": "Group",
                                             "Ellipse": "Convex hull", "Level (%)": 95.0},
            "XY error bars": {"X": "x", "Y": "z", "Y lower error": "p", "Group": "Group"},
            "XY series": {"X": "x", "Y columns": ["y", "z"]},
            "Parts of whole graph": {"Values": "x", "Graph style": "Donut"},
            "Compare observed distribution with expected": {"Observed counts": "x"},
            "Column graph": {"Variables": ["x", "z"], "Graph style": "Individual points", "Interval": "SEM"},
            "Grouped graph": {"Variables": ["x", "z"], "Row titles": "Group", "Graph style": "Bars"},
            "Heat map": {"Variables": ["x", "y", "z"]},
            "Frequency distribution": {"Variables": ["x", "z"], "Distribution": "Exact cumulative"},
            "Histogram": {"Response": "x", "Bins": 4},
            "Box / violin plot": {"Response": "y", "Group": "Group", "Style": "Violin"},
            "Grouped distribution plot": {"Response": "y", "Category": "Group", "Split by": "Factor", "Style": "Violin"},
            "Bubble plot": {"X": "x", "Y": "y", "Size": "z", "Group": "Group", "Label": "Factor"},
            "Before/after": {"Pairs": [{"Before": "x", "After": "y", "Title": ""}], "Subject": "Subject"},
            "Subject trajectories": {"Input": "Separate columns", "X": "x", "Y columns": ["y", "z"]},
            "Forest plot": {"Study": "Group", "Estimate": "x", "Lower limit": "p", "Upper limit": "y"},
            "Meta-analysis of effect estimates": {"Study": "Group", "Estimate": "z", "Standard error": "p",
                                                  "Show graph": False},
            "One-way ANOVA": {"Response": "y", "Group": "Group", "Method": "Welch", "Post-hoc": "Games–Howell"},
            "Repeated measures ANOVA": {"Response": "y", "Factors": ["Group"], "Subject": "Subject",
                                        "Sphericity correction": "None"},
            "Friedman": {"Response": "y", "Group": "Group", "Subject": "Subject"},
            "ROC curve": {"Control": "x", "Patient": "z", "Direction": "Automatic"},
            "Compare paired ROC curves": {"Control A": "x", "Control B": "y", "Patient A": "z", "Patient B": "p",
                                          "Direction A": "Higher in patients", "Direction B": "Higher in patients"},
            "Compare independent ROC curves": {"Control A": "x", "Patient A": "z", "Control B": "y", "Patient B": "p",
                                               "Direction A": "Higher in patients", "Direction B": "Lower in patients",
                                               "Area": "Full", "Inference": "DeLong"},
            "Precision–recall curve": {"Outcome": "Event", "Positive": "1", "Negative": "0", "Score": "x",
                                       "Second score": "z", "Second direction": "Lower is positive"},
            "Bland–Altman": {"First": "x", "Second": "y", "Method": "Difference"},
            "Bland–Altman for repeated pairs": {"Subject": "Subject", "First": "x", "Second": "y"},
            "Cohen's kappa": {"First rating": "Group", "Second rating": "Factor"},
            "Intraclass correlation": {"Raters": ["x", "y", "z"], "Subject": "Subject"},
            "Deming regression": {"X": "x", "Y": "y", "Y / X error variance": 1.},
            "Area under curve": {"X": "x", "Y": "y", "Baseline": 10.},
            "Interpolate a standard curve": {"X": "x", "Y": "y", "Unknown responses": "Unknown"},
            "Plot a function": {"Model": "Straight line", "X source": "Worksheet", "X column": "x",
                                "Curves": [{"name": "Line", "parameters": {"Intercept": 1, "Slope": 2}}]},
            "Smooth / differentiate / integrate": {"X": "x", "Y": "y", "Method": "LOWESS", "LOWESS fraction": .5},
            "Fit spline/LOWESS": {"X": "x", "Y": "y", "Method": "Akima spline", "Direction": "X from Y",
                                  "Query": "Unknown", "Residuals": True},
            "Principal component analysis": {"Variables": ["x", "y", "z"], "Standardize": True},
            "Multiple regression": {"Response": "y", "Predictors": ["x", "Factor"],
                                    "Categorical predictors": ["Factor"], "Family": "Linear"},
            "Validate binary logistic model": {"Response": "Event", "Predictors": ["z"], "Folds": 2},
            "Negative binomial regression": {"Response": "Event", "Predictors": ["x", "Factor"],
                                             "Categorical predictors": ["Factor"], "Dispersion mode": "Fixed"},
            "Ordinal logistic regression": {"Response": "Stage", "Predictors": ["z"], "Categorical predictors": [],
                                            "Category order": ["Low", "Medium", "High"],
                                            "Confidence level (%)": 95., "Profiles": [], "Show graph": False},
            "Cox regression": {"Time": "x", "Event": "Event", "Predictors": ["z"],
                               "Categorical predictors": [], "Ties": "Efron"},
            "Competing risks": {"Time": "x", "Status": "Event", "Group": "Group", "Censor code": "0",
                                "Event codes": ["1", "2"], "Gray tests": "Omnibus and pairwise",
                                "Times": [2., 6., 40.]},
            "Weibull AFT regression": {"Time": "x", "Event": "Event", "Predictors": ["z"],
                                        "Categorical predictors": [], "Event value": "1", "Censor value": "0",
                                        "Shape mode": "Estimated ML", "Confidence level (%)": 95.,
                                        "Profiles": [{"Name": "Mid", "Values": {"z": 3.}}], "Times": [2., 6., 40.],
                                        "Show graph": True},
            "Restricted mean survival time": {"Time": "x", "Status": "Event", "Group": "Group",
                                              "Reference group": "A", "Horizon": 6.},
            "Kolmogorov–Smirnov": {"First": "x", "Second": "y"},
            "Multiple t-tests": {"Variables": ["y", "z"], "Group": "Group", "Design": "Welch", "Correction": "Holm"},
            "Multiple tests (one per row)": {"First replicates": ["x", "y"], "Second replicates": ["z", "p"]},
            "Adjust a stack of p values": {"p value": "p", "Correction": "Holm"},
            "Control false discoveries": {"p columns": ["p"], "Show diagnostic plot": False},
            "Normalize": {"Variables": ["x", "y"], "Method": "Z score"},
            REFERENCE_NORMALIZATION: {"Variables": ["y", "z"], "X": "x", "Graph results": True},
            "Transform": {"Variables": ["x", "y"], "Operation": "Log10"},
            "Transform concentrations (X)": {"X": "x", "Replace zero X": False,
                                             "Zero replacement (original units)": 1e-11,
                                             "Change units": "Multiply by", "Unit factor": 1e3, "Logarithm": "Log10"},
            "Remove baseline and column math": {"Data columns": ["y"], "Baseline column": "z", "X": "x",
                                                "Row titles": "Group", "Baseline": "Linear fit of baseline column vs X",
                                                "Rows for baseline (K)": 1, "Drop baseline rows": False,
                                                "Operation": "Percent difference: 100 × (Y − baseline) / baseline"},
            "Prune rows": {"X": "x", "Method": "Average every K rows (sorted by X)",
                           "X minimum (blank = no limit)": "", "X maximum (blank = no limit)": "",
                           "Rows per group (K)": 3, "Average only rows above an X threshold": True, "X threshold": 4.},
            "Fraction of total": {"Variables": ["x", "Event"], "Row titles": "Subject", "Divide by": "Row total",
                                  "Show as": "Percentages", "Confidence interval": "Clopper–Pearson (exact)",
                                  "Confidence level (%)": 95.},
            "Extract and rearrange": {"Output table": "Grouped", "Response variable": "y",
                                      "Row factor variable": "Group", "Column factor variable": "Factor"},
            "Select and Transform": {"Variables": ["Group", "x"],
                                     "Row filters": [{"column": "x", "operator": ">", "target": "Number", "value": "8"}],
                                     "Calculated variables": [{"name": "Scaled", "expression": "x / 2"}]},
            "Row statistics": {"Variables": ["x", "y"]},
            "Reshape replicates": {"Variables": ["x", "y"], "Row label": "Factor"},
            "Outlier test (Grubbs)": {"Response": "z", "Alpha": .05},
            "Transpose X and Y": {"X": "x", "Y sets": [{"name": "Y", "mode": "Single", "columns": ["y"]}]},
            "Reshape long and wide": {"Direction": "Wide to long", "ID columns": ["x"], "Measure columns": ["y", "z"]},
            "Join worksheets by key": {"Join right sheet": "Sites", "Join left keys": ["Group"],
                                       "Join right keys": ["Group"], "Join type": "Left",
                                       "Join cardinality": "Many-to-one"},
            "Identify outliers": {"Variables": ["x", "y", "z"], "Method": "ROUT", "Q (%)": 1.},
            "Power and sample size": {"Goal": "Sample size", "Design": "Independent t", "Standardized effect": .5,
                                      "Alpha": .05, "Target power": .8, "ANOVA groups": 3},
            "Power for paired proportions": {"Goal": "Sample size", "Alpha (%)": 5, "Target power": .8,
                                             "Negative to positive (%)": 30, "Positive to negative (%)": 10,
                                             "Graph": False},
            "Monte Carlo study": {"Study": "Welch difference", "Replicates": 20, "N A": 5, "N B": 6},
            "Fit custom equation": {"X": "x", "Y": "y", "Group": None, "Equation": "A + B*X",
                                    "Parameters": [{"name": "A", "start": 1., "lower": None, "upper": None, "fixed": False},
                                                   {"name": "B", "start": 1., "lower": None, "upper": None, "fixed": False}],
                                    "Weighting": "Unweighted", "SD column": None, "Confidence level (%)": 95.,
                                    "Curve points": 50},
            "Global fit custom equation": {"X": "x", "Y": "y", "Group": "Group", "Equation": "A + B*X",
                                           "Parameters": [
                                               {"name": "A", "start": 1., "lower": None, "upper": None,
                                                "fixed": False, "shared": False},
                                               {"name": "B", "start": 1., "lower": None, "upper": None,
                                                "fixed": False, "shared": True}],
                                           "Series constraints": [], "Weighting": "Unweighted", "SD column": None,
                                           "Confidence level (%)": 95., "Curve points": 40},
            "Robust curve fit": {"X": "x", "Y columns": ["y"], "Model": "Straight line", "Loss": "Cauchy",
                                 "Scale method": "Pilot MAD", "Initial parameters": {}},
            "Cluster silhouette": {"Variables": ["x", "y"], "Cluster": "Group", "Graph": False},
            KMEANS_METRIC_GRAPH: {KMEANS_METRIC: "WSS"},
            "Simulate data": {"Distribution": "XY with normal noise", "N": 30, "Seed": 42,
                              "Mean": 0., "SD": 1., "X minimum": 0., "X maximum": 1.,
                              "Intercept": 0., "Slope": 1., "Success probability A": .5, "Success probability B": .5},
        }
        for name, options in cases.items():
            with self.subTest(method=name):
                selected = curve if name in {"Nonlinear regression", "Compare nonlinear models", "Compare models (AICc)"} else data
                if name == "Global nonlinear regression":
                    selected = curves
                if name == "One-way ANOVA from summaries":
                    selected = data.iloc[1:].copy()
                if name == "Unpaired t-test from summaries":
                    selected = data.iloc[1:3].copy()
                if name == "Mixed-effects model (REML)":
                    selected = data.copy()
                    selected.loc[0, "y"] = np.nan
                if name in {NESTED_T, NESTED_ANOVA}:
                    groups = 2 if name == NESTED_T else 3
                    selected = pd.DataFrame({f"Group {group + 1} [{rep + 1}]": np.arange(4.) / 4 + 2 * group + rep
                                             for group in range(groups) for rep in range(3)})
                    selected.attrs["table_format"] = "nested"
                if name == "Grouped two-way ANOVA":
                    selected = pd.DataFrame({"Row": ["First", "Second"], "a [1]": [1., 3.],
                                             "a [2]": [2., 4.], "b [1]": [3., 9.], "b [2]": [4., 7.]})
                if name == "Paired proportions":
                    selected = pd.DataFrame({"Before": ["off", "off", "on", "on", "off"],
                                             "After": ["on", "off", "off", "on", "on"]})
                if name == "Ordinal logistic regression":
                    selected = data.assign(Stage=np.tile(["Low", "Medium", "High", "Medium"], 4))
                if name == "Friedman":
                    selected = pd.DataFrame({"y": [1, 2, 4, 2, 1, 4, 2, 3, 5, 4, 3, 8],
                                             "Group": list("abc") * 4, "Subject": np.repeat(np.arange(4), 3)})
                if name == HIERARCHY_GRAPH:
                    tree = analyse("Hierarchical clustering", data, cases["Hierarchical clustering"])
                    selected = result_frame(tree, "Merges")
                if name == KMEANS_METRIC_GRAPH:
                    scan = analyse(KMEANS_SELECTION, data, cases[KMEANS_SELECTION])
                    selected = result_frame(scan, "Selection")
                # The application resolves the right worksheet of a join and passes it with the recipe.
                extra = ({"join_data": pd.DataFrame({"Group": ["A", "B"], "Site": ["North", "South"]})}
                         if name == "Join worksheets by key" else {})
                results = analyse(name, selected, options, **extra)
                self.assertTrue(results.figure if name == HIERARCHY_GRAPH else results.tables)
                self.assertTrue(all(isinstance(table, pd.DataFrame) for table in results.tables.values()))
                self.assertEqual(results.figure is not None, name in GRAPH_METHODS)
                if results.figure:
                    self.assertTrue(results.figure.axes)
        self.assertEqual(set(METHODS), set(cases))
        visible = [method for group in GROUPS.values() for method in group]
        self.assertEqual(len(visible), len(set(visible)))
        self.assertEqual(set(visible), set(METHODS))

    def test_compare_models_is_offered_under_regression_and_curves(self):
        self.assertIn("Compare models (AICc)", GROUPS["Regression and Curves"])
        self.assertEqual(METHODS["Compare models (AICc)"]["Models"], "Model list")

    def test_paired_columns_use_row_matches_and_drop_incomplete_pairs(self):
        table = pd.DataFrame({"A": [5, 8, None, 10], "B": [2, 7, 3, 6]})
        result = analyse("Paired t-test (columns)", table, {"First": "A", "Second": "B"}).tables["t-test"]["Value"]
        self.assertEqual([result["First"], result["Second / null"], result["N first"], result["df"]],
                         ["A", "B", 3, 2])
        self.assertAlmostEqual(result["Difference"], 8 / 3)
        self.assertAlmostEqual(result["t"], 8 / np.sqrt(7))
