from itertools import product
import unittest

import numpy as np
import pandas as pd

from analisi.legacy_recipes import restore_recipe
from analisi.stats import GEOMETRIC_REPORT, SUMMARY_CONFIDENCE, SUMMARY_FORMAT, SUMMARY_SUM
from analisi.workbench import analyse


def var(uid, index=0):
    # Titles in this metadata can differ from the normalized imported names.
    return {"col": {"uid": uid, "idx": index, "title": "Original title"}}


def source(analysis_class, version, content, frame, columns):
    frame.attrs["table_format"] = "multivariable"
    frame.attrs["legacy_columns"] = columns
    sheet = {"analysisClass": analysis_class, "inputSheets": [{"uid": "source"}],
             "isAllDataAnalyzed": True}
    parameters = {"analysisClass": analysis_class, "version": version, "content": content}
    return sheet, parameters, {"source": frame}


class LegacyProjectRecipeTests(unittest.TestCase):
    def test_geometric_column_statistics_restore_only_the_verified_report(self):
        frame = pd.DataFrame({"Control": [1., 4., 16.], "Treated": [9., 9., 9.]})
        flags = {key: False for key in ("mean", "meanCI", "coefficientOfVariation", "skewnessAndKurtosis",
                                       "minMaxRange", "median", "medianCI", "percentiles")}
        flags.update(sum=True, geometricMean=True, geometricMeanCI=True)
        content = {"data": {"handleReplicatesAs": "AVERAGE"},
                   "calc": {"descriptiveStatistics": flags,
                            "normalityTests": dict.fromkeys(("dAgostinoPearson", "shaproWilks", "kolmogorovSmirnov"), False),
                            "oneSampleTests": {"parametric": False, "nonparametric": False, "hypotheticalValue": 0.0,
                                               "usePrattMethod": False}},
                   "options": {"confidenceLevel": 90.}}
        columns = {"a": ["Control"], "b": ["Treated"]}
        sheet, parameters, sources = source("COLUMN_STATISTICS", "0.0.0", content, frame, columns)
        frame.attrs.update(table_format="column", legacy_x=None, legacy_y=list(columns), legacy_y_format="y_single")
        sheet["inputDataSets"] = [{"uid": uid} for uid in columns]
        _, method, options = restore_recipe(sheet, parameters, sources)
        self.assertEqual((options[SUMMARY_FORMAT], options[SUMMARY_CONFIDENCE], options[SUMMARY_SUM]),
                         (GEOMETRIC_REPORT, 90., True))
        summary = analyse(method, frame, options).tables["Summary"]
        self.assertEqual(summary.loc["Control", "N"], 3)
        self.assertEqual(summary.loc["Control", "Sum"], 21)
        quantile = np.sqrt(2.) * .9 / np.sqrt(1 - .9**2)
        expected = [4., 4., 4.**(1 - quantile / np.sqrt(3.)), 4.**(1 + quantile / np.sqrt(3.))]
        fields = ["Geometric mean", "Geometric SD", "Geometric 90% CI low", "Geometric 90% CI high"]
        np.testing.assert_allclose(summary.loc["Control", fields].to_numpy(dtype=float), expected, rtol=1e-12)
        np.testing.assert_array_equal(summary.loc["Treated", fields].to_numpy(dtype=float), [9., 1., 9., 9.])

        flags["sum"] = False
        _, method, options = restore_recipe(sheet, parameters, sources)
        self.assertNotIn("Sum", analyse(method, frame, options).tables["Summary"])
        level = float(np.nextafter(100., 0.))
        extreme = analyse(method, frame * 1e-10 + 1, {**options, SUMMARY_CONFIDENCE: level})
        self.assertTrue(np.isfinite(extreme.tables["Summary"].loc["Control", f"Geometric {level}% CI high"]))
        flags["mean"] = True
        self.assertIsNone(restore_recipe(sheet, parameters, sources))
        flags["mean"] = False
        content["options"]["confidenceLevel"] = 100.
        self.assertIsNone(restore_recipe(sheet, parameters, sources))
        content["options"]["confidenceLevel"] = 95.
        sheet["inputDataSets"] = [{"uid": "a"}]
        self.assertIsNone(restore_recipe(sheet, parameters, sources))

    def test_xy_log_x_uses_the_x_identity_and_keeps_individual_replicates(self):
        frame = pd.DataFrame({"Concentration": [1e-10, .001, 1.0], "A [1]": [3, None, 9], "A [2]": [4, 5, 8]})
        settings = {"interchangeXY": False,
                    "xTransform": {"enabled": True, "function": "LOG10(X)", "k": "undefined"},
                    "yTransform": {"enabled": False}}
        content = {"data": {"handleReplicatesAs": "INDIVIDUAL"},
                   "calc": {"transformType": "STANDARD", "standardFunction": settings}}
        columns = {"x": ["Concentration"], "a": ["A [1]", "A [2]"]}
        sheet, params, sources = source("TRNSFORM", "0.0.0", content, frame, columns)
        frame.attrs.update(table_format="xy", legacy_x="x", legacy_y=["a"], legacy_y_format="y_replicates")
        sheet["inputDataSets"] = [{"uid": "a", "title": "Old title"}]
        _, method, options = restore_recipe(sheet, params, sources)
        self.assertEqual(method, "Transform concentrations (X)")
        result = analyse(method, frame, options).tables["Transformed data"]
        self.assertEqual(result["Concentration"].tolist(), [-10, -3, 0])
        pd.testing.assert_frame_equal(result.drop(columns="Concentration"), frame.drop(columns="Concentration"))
        for changed in ({"interchangeXY": True}, {"yTransform": {"enabled": True}},
                        {"xTransform": {"enabled": True, "function": "LN(X)", "k": "undefined"}}):
            with self.subTest(changed=changed):
                content["calc"]["standardFunction"] = {**settings, **changed}
                self.assertIsNone(restore_recipe(sheet, params, sources))
        content["calc"]["standardFunction"] = settings
        sheet["inputDataSets"] = [{"uid": "b"}]
        self.assertIsNone(restore_recipe(sheet, params, sources))

    def test_select_transform_restores_inclusive_row_range(self):
        frame = pd.DataFrame({"Label": list("abcdef"), "Score": [9, 3, 0, 8, 6, 4]},
                             index=[101, 102, 103, 104, 105, 106])
        uids = {"label": ["Label"], "score": ["Score"]}
        frame.attrs["legacy_y"] = list(uids)
        filters = {
            "range": {"from": 2, "to": 4},
            "variableValue": [{"variableIdx": 1, "logic": ">", "value": 2}],
            "variableVariable": [],
        }
        content = {"rowFilters": filters, "transforms": [
            {"title": "Label", "enabled": True, "definition": "A", "parameter": "undefined"},
        ]}
        args = source("SELECT_TRANSFORM", "0.0.2", content, frame, uids)

        for first, last, labels in [(2, 4, ["b", "d"]), (1, 1, ["a"]), (6, 6, ["f"])]:
            with self.subTest(first=first, last=last):
                filters["range"] = {"from": first, "to": last}
                _, method, options = restore_recipe(*args)
                self.assertEqual((options["First row"], options["Last row"]), (first, last))
                self.assertEqual(analyse(method, frame, options).tables["Selected data"]["Label"].tolist(), labels)

        for start, end in [(0, 4), (4, 2), (-1, 4), (1, -1), (True, 4), (1, 4.0), (1, 10**20)]:
            with self.subTest(start=start, end=end):
                filters["range"] = {"from": start, "to": end}
                self.assertIsNone(restore_recipe(*args))
        filters["range"] = {"from": 1, "to": 4, "newOption": True}
        self.assertIsNone(restore_recipe(*args))

    def test_select_transform_restores_joint_column_and_presence_filters(self):
        frame = pd.DataFrame({"Sample": list("abcde"), "Measured": [3, 4, 5, 2, 7],
                              "Target": [3, 6, 0, 9, 4], "Control": [10., 20., None, 10., 1.]})
        uids = {str(index): [label] for index, label in enumerate(frame.columns)}
        frame.attrs["legacy_y"] = list(uids)
        filters = {
            "range": {"from": -1, "to": -1},
            "variableValue": [{"variableIdx": 1, "logic": ">", "value": 2},
                              {"variableIdx": 3, "logic": "is_not_missing", "value": None}],
            "variableVariable": [{"variable1Idx": 1, "logic": "<>", "variable2Idx": 2}],
        }
        content = {"rowFilters": filters, "transforms": [
            {"title": "Sample", "enabled": True, "definition": "A", "parameter": "undefined"},
            {"title": "Total", "enabled": True, "definition": "B + C", "parameter": "undefined"},
        ]}
        args = source("SELECT_TRANSFORM", "0.0.2", content, frame, uids)
        _, method, options = restore_recipe(*args)
        self.assertEqual(options["Row filters"], [
            {"column": "Measured", "operator": ">", "target": "Number", "value": "2"},
            {"column": "Control", "operator": "Is not missing", "target": "Number", "value": ""},
            {"column": "Measured", "operator": "!=", "target": "Column", "value": "Target"},
        ])
        expected = pd.DataFrame({"Sample": ["b", "e"], "Total": [10., 11.]})
        actual = analyse(method, frame, options).tables["Selected data"]
        pd.testing.assert_frame_equal(actual, expected, check_dtype=False, check_exact=True)

        with self.subTest("unknown index"):
            filters["variableVariable"][0]["variable2Idx"] = 10
            self.assertIsNone(restore_recipe(*args))
        with self.subTest("wrong column type"):
            filters["variableVariable"][0]["variable2Idx"] = 0
            self.assertIsNone(restore_recipe(*args))
        with self.subTest("combined condition limit"):
            filters["variableVariable"] = [{"variable1Idx": 1, "logic": "<>", "variable2Idx": 2}] * 31
            self.assertIsNone(restore_recipe(*args))

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
        content["graph"] = {"confidenceInterval": True}
        frame.loc[len(frame)] = [4, "A", 42.]
        _, _, plotted = restore_recipe(*args, stored)
        self.assertIs(plotted["Show estimation plot"], True)
        result = analyse(method, frame, plotted)
        pd.testing.assert_series_equal(result.tables["t-test"]["Value"], test)
        measurements, differences = result.figure.axes
        self.assertEqual([label.get_text() for label in measurements.get_xticklabels()], ["A", "B"])
        self.assertEqual([len(series.get_offsets()) for series in measurements.collections if hasattr(series, "get_offsets")
                          and len(series.get_offsets()) == 3], [3, 3])
        interval, = [artist for artist in differences.collections
                     if artist.get_gid() == "paired-mean-confidence-interval"]
        segment, = interval.get_segments()
        np.testing.assert_array_equal(segment[:, 1], [test["CI 95% low"], test["CI 95% high"]])
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
            "calc": {"tabulate": "EVENT", "logrankTestMethod": "RECOMMENDED", "logrankTest": True,
                     "ciMethod": "ASYMMETRICAL", "ciLevel": 90.0},
            "graph": {"showNumberAtRiskTable": True, "errorBars": "CI"},
        }
        frame = pd.DataFrame({"Time": [1, 4, 2, 3], "Event": [1, 0, 1, 1], "Group": list("AABB")})
        args = source("SURVIVAL", "0.0.2", content, frame, {"t": ["Time"], "e": ["Event"], "g": ["Group"]})
        _, method, options = restore_recipe(*args)
        self.assertIn("Imported post-tests", options["Legacy import notes"])
        self.assertEqual(options["Uncertainty"], "Pointwise confidence bars")
        self.assertEqual(options["Confidence level (%)"], 90.0)
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
        frame.attrs["legacy_category_orders"] = {"g": ("First", "Second", "Third")}
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

        frame.attrs["legacy_category_orders"]["g"] = ("First", "Second", "Unknown")
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
        self.assertIn("symmetric intervals", options["Legacy import notes"])
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

        transforms = [{"name": "logIC50", "definition": "log(IC50)", "ciMethod": "ASYMMETRICAL"}]
        content["model"]["equation"]["transforms"] = transforms
        _, _, transformed = restore_recipe(*args)
        self.assertIs(transformed["Report log10(IC50)"], True)
        result = analyse(method, frame, transformed)
        log_table = result.tables["Transformed parameters: All"]
        parameters = result.tables["Parameters: All"]
        pd.testing.assert_frame_equal(parameters, tables["Parameters: All"], check_exact=True)
        for column in ("Estimate", "CI 92.5% low", "CI 92.5% high"):
            self.assertAlmostEqual(log_table.loc["log10(IC50)", column],
                                   np.log10(parameters.loc["IC50", column]))
        transforms[0]["definition"] = "ln(IC50)"
        self.assertNotIn("Report log10(IC50)", restore_recipe(*args)[2])
        content["model"]["equation"].pop("transforms")
        for change in ({"calcCI": False}, {"confidenceLevel": True}, {"confidenceLevel": 100.},
                       {"confidenceLevel": "92.5"}, {"ciMethod": "UNKNOWN"}):
            with self.subTest(change=change):
                content["confidence"] = {**confidence, **change}
                self.assertEqual(restore_recipe(*args)[2], options)
        content["method"]["weighting"]["type"] = "RELATIVE"
        self.assertIsNone(restore_recipe(*args))
