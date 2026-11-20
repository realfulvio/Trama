from itertools import product
import unittest

import pandas as pd

from analisi.prism_recipes import restore_recipe
from analisi.workbench import analyse


def var(uid, index=0):
    # Titles in this metadata can differ from the normalized imported names.
    return {"col": {"uid": uid, "idx": index, "title": "Original title"}}


def source(analysis_class, version, content, frame, columns):
    frame.attrs["table_format"] = "multivariable"
    frame.attrs["prism_columns"] = columns
    sheet = {"analysisClass": analysis_class, "inputSheets": [{"uid": "source"}],
             "isAllDataAnalyzed": True}
    parameters = {"analysisClass": analysis_class, "version": version, "content": content}
    return sheet, parameters, {"source": frame}


class PrismRecipeTests(unittest.TestCase):
    def test_extract_rearrange_restores_xy_column_and_weighted_counts(self):
        frame = pd.DataFrame({"Time": [1, 2, 1, 2], "Value": [3, 5, 7, 9],
                              "Arm 2": ["A", "A", "B", "B"], "Event": ["yes", "no", "yes", "yes"],
                              "Visit": ["Visit 1", "Visit 2", "Visit 1", "Visit 2"],
                              "Count": [2, 1, 4, 3]})
        columns = {str(index): [label] for index, label in enumerate(frame.columns)}
        time, value, arm, event, visit, count = (var(str(index)) for index in range(len(columns)))
        cases = [
            ("XY", {"xVariable": time, "yVariable": value, "groupingVariable": arm, "subjectType": "NO"},
             {"type": "VARIABLE", "variable": visit},
             {"Row title": ["Visit 1", "Visit 2"], "Time": [1, 2], "A": [3, 5], "B": [7, 9]}),
            ("COLUMN", {"responseVariable": value, "columnFactorVariable": arm,
                        "columnSubjectType": "VARIABLE", "subjectVariable": visit},
             {"type": "NO", "variable": None},
             {"Row title": ["Visit 1", "Visit 2"], "A": [3, 5], "B": [7, 9]}),
            ("CONTINGENCY", {"rowVariable": arm, "columnVariable": event, "countVariable": count},
             {"type": "NO", "variable": None},
             {"Row title": ["A", "B"], "no": [1, 0], "yes": [2, 7]}),
        ]
        for name, arrangement, titles, expected in cases:
            with self.subTest(name=name):
                content = {"resultTableFormat": name, "includeVarNamePrefix": False, "reportCompleteRowsOnly": True,
                           "rowTitles": titles, "dataArrangement": arrangement}
                args = source("EXTRACT_REARRANGE", "0.0.1", content, frame, columns)
                restored = restore_recipe(*args)
                self.assertIsNotNone(restored)
                _, method, options = restored
                self.assertEqual(method, "Extract and rearrange")
                table = analyse(method, frame, options).tables["Rearranged data"]
                self.assertEqual(table.attrs["table_format"], name.lower())
                pd.testing.assert_frame_equal(table, pd.DataFrame(expected), check_dtype=False, check_exact=True)
                arrangement["unrecognizedSetting"] = True
                self.assertIsNone(restore_recipe(*args))

    def test_extract_rearrange_does_not_guess_subject_mode_or_unavailable_roles(self):
        frame = pd.DataFrame({"Time": [1, 2], "Signal": [4, 5], "Replicate": ["s1", "s1"]})
        columns = {"t": ["Time"], "r": ["Signal"], "s": ["Replicate"]}
        arrangement = {"xVariable": var("t"), "yVariable": var("r"), "subjectVariable": var("s"),
                       "subjectType": "NO"}
        content = {"resultTableFormat": "XY", "includeVarNamePrefix": False, "reportCompleteRowsOnly": True,
                   "rowTitles": {"type": "NO", "variable": None}, "dataArrangement": arrangement}
        args = source("EXTRACT_REARRANGE", "0.0.1", content, frame, columns)
        self.assertIsNone(restore_recipe(*args))
        arrangement["subjectType"] = "SAME_X"
        self.assertIsNone(restore_recipe(*args))
        arrangement["subjectType"] = "VARIABLE"
        self.assertEqual(restore_recipe(*args)[2]["Subject/replicate variable"], "Replicate")
        arrangement["subjectVariable"] = var("missing")
        self.assertIsNone(restore_recipe(*args))

    def test_factorial_resolves_columns_by_uid_and_preserves_interaction_order(self):
        x, y, response = var("x"), var("y", 1), var("r", 2)
        tx, ty = {"varIdx": 0, "varID": x}, {"varIdx": 1, "varID": y}
        predictor = {"variables": [{"id": v, "effectType": "FIXED"} for v in (x, y)],
                     "definition": [[], [tx], [ty], [tx, ty]]}
        content = {"model": {"response": {"variable": {"id": response}, "definition": ""},
                             "predictor": predictor},
                   "postTests": {"type": "NO_TESTS"}}
        frame = pd.DataFrame(columns=["Factor", "Factor (2)", "Value"])
        args = source("MULTI_FACTOR_ANOVA", "0.0.0", content, frame,
                      {"x": ["Factor"], "y": ["Factor (2)"], "r": ["Value"]})
        self.assertEqual(restore_recipe(*args), ("source", "Multifactor ANOVA",
                                                {"Response": "Value", "Factors": ["Factor", "Factor (2)"],
                                                 "Interaction order": 2}))
        term = {"variation": 0.1, "partialEta2": 0.2, "CohenF": 0.5,
                "fTest": {"pValue": {"level": 0.025}}}
        terms = [dict(term) for _ in range(3)]
        results = {"version": "0.0.0", "content": {"ordinaryModel": {
            "status": "VALID", "anovaTable": {"fixedEffects": terms}}}}
        _, _, options = restore_recipe(*args, results)
        self.assertTrue(options["Effect sizes"])
        self.assertEqual(options["Alpha"], 0.025)

        # Incomplete or inconsistent cache metadata must leave the supported base recipe usable.
        terms[-1]["fTest"] = {"pValue": {"level": 0.05}}
        self.assertEqual(restore_recipe(*args, results), restore_recipe(*args))
        terms[-1].pop("CohenF")
        self.assertEqual(restore_recipe(*args, results), restore_recipe(*args))
        predictor["definition"].remove([ty])
        self.assertIsNone(restore_recipe(*args))

    def test_factorial_import_keeps_only_saved_interactions(self):
        factors = ["Dose", "Batch", "Day"]
        references = [var(name, i) for i, name in enumerate(factors)]
        dose, batch, day = ({"varIdx": i, "varID": ref} for i, ref in enumerate(references))
        predictor = {"variables": [{"id": ref, "effectType": "FIXED"} for ref in references],
                     "definition": [[], [day], [dose], [batch], [batch, dose]]}
        content = {"model": {"response": {"variable": {"id": var("y", 3)}, "definition": ""},
                             "predictor": predictor}, "postTests": {"type": "NO_TESTS"}}
        frame = pd.DataFrame([(str(a), str(b), str(c), 10 + 2 * a + 3 * b + 4 * c + 5 * a * b + noise)
                              for a, b, c, noise in product((-1, 1), repeat=4)],
                             columns=[*factors, "Value"])
        columns = {name: [name] for name in factors}
        args = source("MULTI_FACTOR_ANOVA", "0.0.0", content, frame, {**columns, "y": ["Value"]})
        _, method, options = restore_recipe(*args)
        self.assertEqual(options["Term selection"], "Selected terms")
        self.assertEqual(options["Model terms"], [["Dose"], ["Batch"], ["Day"], ["Dose", "Batch"]])
        table = analyse(method, frame, options).tables["ANOVA (type III)"]
        self.assertEqual(list(table.index), ["Dose", "Batch", "Day", "Dose:Batch", "Residual"])
        self.assertAlmostEqual(table.at["Dose:Batch", "SS"], 400)
        self.assertAlmostEqual(table.at["Dose:Batch", "F"], 275)

        predictor["definition"].append([dose, batch])
        self.assertIsNone(restore_recipe(*args))
        predictor["definition"].pop()
        predictor["definition"].remove([])
        self.assertIsNone(restore_recipe(*args))

    def test_clustering_preserves_the_row_configuration(self):
        content = {
            "data": {"inputType": "ROWS", "variables": [var("long"), var("lat", 1)],
                     "label": {"type": "VARIABLE", "variable": var("city", 2)}},
            "calc": {"columnTransform": "STANDARDIZE", "rowTransform": "NONE",
                     "distance": {"type": "EUCLIDIAN", "value": 2.0}, "linkage": "GROUP_AVERAGE"},
            "defineClusters": {"rows": {"method": "NUMBER_OF_CLUSTERS", "clusterCount": 5},
                               "columns": {"method": "NONE"}},
        }
        frame = pd.DataFrame({"Longitude": [1., 2., 4., 5., None, 9.],
                              "Latitude": [1., 2., 4., 5., 0., 9.],
                              "City": list("ABCDEF")})
        args = source("HIERARCHICAL_CLUSTERING", "0.0.0", content, frame,
                      {"long": ["Longitude"], "lat": ["Latitude"], "city": ["City"]})
        _, method, options = restore_recipe(*args)
        self.assertEqual(method, "Hierarchical clustering")
        self.assertEqual(options["Variables"], ["Longitude", "Latitude"])
        self.assertEqual(options["Clusters"], 5)
        self.assertTrue(options["Standardize"])
        self.assertEqual(options["Linkage"], "average")
        self.assertEqual(options["Distance"], "euclidean")
        self.assertEqual(options["Observation labels"], "City")
        graph = analyse(method, frame, options).figure
        self.assertEqual({label.get_text() for label in graph.axes[0].get_xticklabels()}, set("ABCDF"))
        content["data"]["inputType"] = "UNKNOWN"
        self.assertIsNone(restore_recipe(*args))

    def test_paired_t_uses_saved_sample_ids_instead_of_first_seen_order(self):
        response, group, subject = var("r"), var("g", 1), var("s", 2)
        content = {
            "variableDesign": {"responseList": [response], "factorList": [group], "subject": subject},
            "experimentalDesign": "PAIRED_T_TEST",
            "options": {"pValueTailType": "P_VALUE_TWO_TAILED", "significanceLevel": .05,
                        "swapDirection": True},
        }
        frame = pd.DataFrame({"Subject": [1, 1, 2, 2, 3, 3], "Treatment": list("ABABAB"),
                              "Value": [5, 4, 8, 4, 6, 5]})
        args = source("T_TESTS_AND_NONPARAMETRIC", "0.0.1", content, frame,
                      {"s": ["Subject"], "g": ["Treatment"], "r": ["Value"]})
        samples = {"sample" + str(i): {"id": {"var": {"response": response["col"],
                    "factorList": [{"var": group["col"], "value": level}]}}}
                   for i, level in enumerate(("B", "A"), 1)}
        stored = {"content": {"descriptiveStatistics": samples}}
        _, method, options = restore_recipe(*args, stored)
        self.assertEqual(method, "t-test")
        self.assertEqual(options["Group order"], ["B", "A"])
        test = analyse(method, frame, options).tables["t-test"]["Value"]
        self.assertAlmostEqual(test["Difference"], -2.)
        self.assertAlmostEqual(test["t"], -2.)
        content["options"]["pValueTailType"] = "P_VALUE_ONE_TAILED"
        self.assertIsNone(restore_recipe(*args, stored))

    def test_dunnett_uses_the_saved_control_and_contrast_direction(self):
        g, response = var("g"), var("r", 1)
        factor = {"varIdx": 0, "varID": g}
        content = {
            "model": {"response": {"variable": {"id": response}, "definition": ""},
                      "predictor": {"variables": [{"id": g, "effectType": "FIXED"}],
                                    "definition": [[], [factor]]}},
            "postTests": {"type": "PAIRWISE_TESTS", "betweenFactorList": [factor],
                          "withinFactorList": [], "withinAsSingleFamily": False, "pairwiseTests": {
                              "design": "CONTROL_VS_ALL", "options": {"swapDirection": False},
                              "ctrlVsAll": {
                                  "controlID": {"var": {"response": response["col"], "factorList": [
                                      {"var": g["col"], "value": "Placebo"}]}},
                                  "multipleComparisons": {"type": "STATISTICAL", "statistical": {
                                      "test": "DUNNET", "options": {"significanceLevel": .05}}},
                              },
                          }},
        }
        frame = pd.DataFrame({"Group": ["Placebo", "A", "B"] * 3,
                              "Value": [1., 4., 8., 2., 5., 10., 3., 6., 9.]})
        args = source("MULTI_FACTOR_ANOVA", "0.0.0", content, frame, {"g": ["Group"], "r": ["Value"]})
        _, method, options = restore_recipe(*args)
        contrasts = analyse(method, frame, options).tables["Multiple comparisons"]
        self.assertAlmostEqual(contrasts.at["Placebo − A", "Difference"], -3.)
        self.assertAlmostEqual(contrasts.at["Placebo − B", "Difference"], -7.)
        content["postTests"]["pairwiseTests"]["options"]["swapDirection"] = True
        _, method, options = restore_recipe(*args)
        contrasts = analyse(method, frame, options).tables["Multiple comparisons"]
        self.assertAlmostEqual(contrasts.at["A − Placebo", "Difference"], 3.)

    def test_survival_recalculates_curves_and_overall_logrank(self):
        content = {
            "variableDesign": {"x": var("t"), "responseList": [var("e", 1)], "factorList": [var("g", 2)]},
            "data": {"eventCode": 1, "censorCode": 0, "treatUndefinedValuesAs": "MISSING"},
            "calc": {"tabulate": "EVENT", "logrankTestMethod": "RECOMMENDED", "logrankTest": True},
            "graph": {"showNumberAtRiskTable": True},
        }
        frame = pd.DataFrame({"Time": [1, 4, 2, 3], "Event": [1, 0, 1, 1], "Group": list("AABB")})
        args = source("SURVIVAL", "0.0.2", content, frame, {"t": ["Time"], "e": ["Event"], "g": ["Group"]})
        _, method, options = restore_recipe(*args)
        self.assertIn("Prism post-tests", options["Prism import notes"])
        result = analyse(method, frame, options)
        self.assertEqual(len(result.figure.axes), 2)
        self.assertEqual(result.tables["Curve: A"]["Survival"].tolist(), [.5, .5])
        self.assertEqual(result.tables["Curve: B"]["Survival"].tolist(), [.5, 0.])
        self.assertAlmostEqual(result.tables["Log-rank test"].at["Log-rank χ²", "Value"], 2 / 13)
        content["data"].update(eventCode=0, censorCode=1)
        frame["Event"] = 1 - frame["Event"]
        _, method, options = restore_recipe(*args)
        recoded = analyse(method, frame, options)
        self.assertAlmostEqual(recoded.tables["Log-rank test"].at["Log-rank χ²", "Value"], 2 / 13)

        content["data"].update(eventCodeStr="Occurred", censorCodeStr="Followed")
        frame["Event"] = frame["Event"].map({0: "Occurred", 1: "Followed"})
        _, method, options = restore_recipe(*args)
        recoded = analyse(method, frame, options)
        self.assertEqual(recoded.tables["Curve: A"]["Survival"].tolist(), [.5, .5])

        content["data"]["censorCodeStr"] = "Occurred"
        self.assertIsNone(restore_recipe(*args))

    def test_survival_restores_complete_saved_category_order_for_trend(self):
        frame = pd.DataFrame({"Time": [2, 6, 4, 7, 5, 9], "Event": [1, 0, 1, 1, 1, 0],
                              "Group": ["Third", "Third", "First", "First", "Second", "Second"]})
        frame.attrs["prism_category_orders"] = {"g": ("First", "Second", "Third")}
        content = {
            "variableDesign": {"x": var("t"), "responseList": [var("e", 1)], "factorList": [var("g", 2)]},
            "data": {"eventCode": 1, "censorCode": 0, "treatUndefinedValuesAs": "MISSING"},
            "calc": {"tabulate": "EVENT", "logrankTestMethod": "RECOMMENDED", "logrankTest": True,
                     "logrankTestForTrend": True, "logrankTestForTrendMethod": "RECOMMENDED",
                     "gehanBreslowWilcoxonTest": True},
            "graph": {"showNumberAtRiskTable": False},
            "postTests": {"type": "PAIRWISE_TESTS", "pairwiseTests": {
                "pairwiseDesign": {"type": "CONTROL_VS_ALL", "selectedPairIDList": [], "controlID": {
                    "var": {"response": {"uid": "e"}, "factorList": [{"value": "Second", "var": {"uid": "g"}}]},
                }},
                "multipleComparisons": {"type": "STATISTICAL", "statistical": {
                    "test": "HOLM_SIDAK", "report": {"adjustedPValues": False},
                    "options": {"significanceLevel": .05},
                }},
            }},
        }
        args = source("SURVIVAL", "0.0.2", content, frame, {"t": ["Time"], "e": ["Event"], "g": ["Group"]})
        _, method, options = restore_recipe(*args)
        self.assertEqual(options["Trend group order"], ["First", "Second", "Third"])
        result = analyse(method, frame, options)
        self.assertIn("Log-rank trend", result.tables)
        self.assertIn("Gehan–Breslow–Wilcoxon test", result.tables)
        self.assertEqual(options["Pairwise control group"], "Second")
        self.assertEqual(options["Pairwise correction"], "Holm–Šídák")
        self.assertEqual(result.tables["Pairwise log-rank"].index.tolist(), ["Second / Third", "Second / First"])
        self.assertIn("Significant", result.tables["Pairwise log-rank"])
        self.assertNotIn("Adjusted p", result.tables["Pairwise log-rank"])

        frame.attrs["prism_category_orders"]["g"] = ("First", "Second", "Unknown")
        _, _, restored = restore_recipe(*args)
        self.assertNotIn("Log-rank trend", restored)
        self.assertTrue(restored["Gehan–Breslow–Wilcoxon"])
        control = content["postTests"]["pairwiseTests"]["pairwiseDesign"]["controlID"]["var"]
        control["response"] = {"uid": "t"}
        _, _, restored = restore_recipe(*args)
        self.assertEqual(restored["Pairwise correction"], "None")

    def test_nonlinear_uses_saved_equation_and_rejects_changed_fitting_options(self):
        content = {
            "variableDesign": {"x": var("x"), "responseList": [var("y", 1)], "factorList": []},
            "data": {"handleReplicatesAs": "INDIVIDUAL",
                     "range": {"minX": {"enabled": False}, "maxX": {"enabled": False}}},
            "model": {
                "equation": {"definition": "Y=100 / (1+(IC50/X)^HillSlope)\r\n",
                             "parameters": ["IC50", "HillSlope"]},
                "constraints": {"IC50": {"type": "GREATER", "value": 0.0}},
                "initialValues": {"IC50": [{"isAuto": True, "value": 5.}],
                                  "HillSlope": [{"isAuto": True, "value": -1.}]},
            },
            "method": {"fittingMethod": "LS", "outliers": {"method": "DO_NOT_HANDLE"},
                       "weighting": {"type": "NO_WEIGHTING"}},
            "interpolation": {"enabled": False},
            "modelComparison": {"type": "NO_COMPARISON"},
        }
        frame = pd.DataFrame({"X": [1, 2, 5, 10, 30], "Y": [83, 72, 50, 33, 14]})
        args = source("NONLINEAR_REGRESSION", "0.0.0", content, frame, {"x": ["X"], "y": ["Y"]})
        _, method, options = restore_recipe(*args)
        self.assertIn("symmetric intervals", options["Prism import notes"])
        params = analyse(method, frame, options).tables["Parameters: All"]["Estimate"]
        self.assertAlmostEqual(params["IC50"], 5., delta=.1)
        self.assertAlmostEqual(params["Hill slope"], -1., delta=.1)
        confidence = {"calcCI": True, "ciMethod": "PROFILE_LIKELIHOOD", "confidenceLevel": 92.5}
        content["confidence"] = confidence
        _, _, profiled = restore_recipe(*args)
        self.assertEqual(profiled["Parameter intervals"], "Profile likelihood")
        self.assertEqual(profiled["Parameter confidence level (%)"], 92.5)
        tables = analyse(method, frame, profiled).tables
        self.assertIn("CI 92.5% low", tables["Parameters: All"])
        self.assertIn("Parameter CI status: All", tables)
        for change in ({"calcCI": False}, {"confidenceLevel": True}, {"confidenceLevel": 100.},
                       {"confidenceLevel": "92.5"}, {"ciMethod": "UNKNOWN"}):
            with self.subTest(change=change):
                content["confidence"] = {**confidence, **change}
                self.assertEqual(restore_recipe(*args)[2], options)
        content["method"]["weighting"]["type"] = "RELATIVE"
        self.assertIsNone(restore_recipe(*args))
